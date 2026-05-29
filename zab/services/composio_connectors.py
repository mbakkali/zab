"""Source de connecteurs Composio (live fetch via CLI puis REST v3, pas de cache disque)."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_USER_DATA_PATH = Path.home() / ".composio" / "user_data.json"
_DEFAULT_BASE_URL = "https://backend.composio.dev"
_DEFAULT_TIMEOUT = 4.0
_COMPOSIO_CLI_FALLBACK = Path.home() / ".composio" / "composio"
_FORMS_CACHE_TTL_SECONDS = 90.0
_forms_cache: dict[str, Any] = {"at": 0.0, "value": None}

# Cache pour les identités résolues (whoami) par connected_account_id
_IDENTITY_CACHE_TTL_SECONDS = 300.0
_identity_cache: dict[str, Any] = {"at": 0.0, "value": {}}


def _identity_cache_path() -> Path:
    from zab.paths import data_dir

    return data_dir() / "composio-identities.yaml"


def _load_identity_cache() -> dict[str, Any]:
    path = _identity_cache_path()
    if not path.is_file():
        return {}
    try:
        import yaml

        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
    except Exception:
        pass
    return {}


def _save_identity_cache(data: dict[str, Any]) -> None:
    path = _identity_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import yaml

        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=True), encoding="utf-8")
    except Exception:
        pass


def _cache_get() -> list[tuple[str, dict[str, Any]]] | None:
    val = _forms_cache.get("value")
    if val is None:
        return None
    if (time.monotonic() - float(_forms_cache.get("at") or 0.0)) > _FORMS_CACHE_TTL_SECONDS:
        return None
    return list(val)


def _cache_set(value: list[tuple[str, dict[str, Any]]]) -> None:
    _forms_cache["value"] = list(value)
    _forms_cache["at"] = time.monotonic()


def clear_forms_cache() -> None:
    _forms_cache["value"] = None
    _forms_cache["at"] = 0.0


def get_cached_identity(word_id: str) -> dict[str, Any] | None:
    """Retourne l'identité résolue d'un compte si elle est en cache (mémoire ou disque)."""
    # In-memory first
    cached = _identity_cache.get("value", {})
    cache_at = float(_identity_cache.get("at") or 0.0)
    if (time.monotonic() - cache_at) <= _IDENTITY_CACHE_TTL_SECONDS:
        hit = cached.get(word_id)
        if hit:
            return dict(hit)
    # Disk fallback
    disk = _load_identity_cache()
    hit = disk.get(word_id)
    if isinstance(hit, dict) and hit.get("successful"):
        # Warm memory cache
        cached[word_id] = hit
        _identity_cache["value"] = cached
        _identity_cache["at"] = time.monotonic()
        return dict(hit)
    return None


def composio_cli_path() -> str | None:
    """Retourne le chemin du binaire composio (PATH ou ~/.composio/composio), ou None."""
    found = shutil.which("composio")
    if found:
        return found
    if _COMPOSIO_CLI_FALLBACK.is_file() and os.access(_COMPOSIO_CLI_FALLBACK, os.X_OK):
        return str(_COMPOSIO_CLI_FALLBACK)
    return None


def _run_composio_cli(args: list[str], timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    """Exécute le CLI Composio avec les arguments donnés."""
    cli = composio_cli_path()
    if not cli:
        raise RuntimeError("composio CLI introuvable")
    return subprocess.run([cli, *args], capture_output=True, text=True, check=False, timeout=timeout)


def _extract_email_from_gmail_messages(result: dict[str, Any]) -> str | None:
    """Tente d'extraire l'email du propriétaire depuis le résultat GMAIL_FETCH_EMAILS."""
    data = result.get("data") if isinstance(result.get("data"), dict) else result
    messages = data.get("messages") if isinstance(data, dict) else None
    if not isinstance(messages, list) or not messages:
        return None
    first = messages[0]
    if not isinstance(first, dict):
        return None
    payload = first.get("payload") or first
    headers = payload.get("headers") if isinstance(payload, dict) else None
    if isinstance(headers, list):
        for h in headers:
            if isinstance(h, dict) and h.get("name") == "Delivered-To":
                val = str(h.get("value") or "").strip()
                if val:
                    return val
            if isinstance(h, dict) and h.get("name") == "To":
                val = str(h.get("value") or "").strip()
                if val:
                    return val
    # fallback: thread last message
    thread = first.get("thread") if isinstance(first, dict) else None
    if isinstance(thread, dict):
        msgs = thread.get("messages")
        if isinstance(msgs, list) and msgs:
            last = msgs[-1]
            if isinstance(last, dict):
                pl = last.get("payload") or last
                hs = pl.get("headers") if isinstance(pl, dict) else None
                if isinstance(hs, list):
                    for h in hs:
                        if isinstance(h, dict) and h.get("name") == "Delivered-To":
                            val = str(h.get("value") or "").strip()
                            if val:
                                return val
    return None


def resolve_account_identity(
    word_id: str,
    toolkit: str = "gmail",
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Résout l'identité (email, nom) d'un compte Composio en exécutant un tool léger.

    Stratégie :
      1. Tente GMAIL_GET_PROFILE / GMAIL_FETCH_PROFILE
      2. Fallback sur GMAIL_FETCH_EMAILS limit=1 et extraction du header Delivered-To
      3. Retourne un dict avec email, account, toolkit, method
    """
    # Check cache
    now = time.monotonic()
    cached = _identity_cache.get("value", {})
    cache_at = float(_identity_cache.get("at") or 0.0)
    if (now - cache_at) < _IDENTITY_CACHE_TTL_SECONDS:
        hit = cached.get(word_id)
        if hit:
            return dict(hit)

    # Candidate tools to probe identity
    candidates: list[tuple[str, dict[str, Any]]] = [
        ("GMAIL_GET_PROFILE", {}),
        ("GMAIL_FETCH_PROFILE", {}),
    ]
    if toolkit.lower() == "gmail":
        candidates.append(("GMAIL_FETCH_EMAILS", {"limit": 1, "fetch_conversations": False}))
        candidates.append(("GMAIL_FETCH_EMAILS", {"limit": 1}))

    last_error: str | None = None
    for tool_slug, payload in candidates:
        try:
            proc = _run_composio_cli(
                ["execute", tool_slug, "-d", json.dumps(payload), "--account", word_id],
                timeout=timeout,
            )
            if proc.returncode != 0:
                last_error = proc.stderr.strip()[:200]
                continue
            try:
                result = json.loads(proc.stdout)
            except json.JSONDecodeError:
                continue
            email: str | None = None
            name: str | None = None
            # Direct profile tools
            data = result.get("data") if isinstance(result.get("data"), dict) else result
            if isinstance(data, dict):
                for k in ("emailAddress", "email_address", "email", "user_email", "address"):
                    v = data.get(k)
                    if isinstance(v, str) and v.strip():
                        email = v.strip()
                        break
                for k in ("displayName", "display_name", "name", "user_name", "given_name"):
                    v = data.get(k)
                    if isinstance(v, str) and v.strip():
                        name = v.strip()
                        break
            # Fallback from message headers
            if not email:
                email = _extract_email_from_gmail_messages(result)
            if email:
                out = {
                    "account": word_id,
                    "toolkit": toolkit,
                    "email": email,
                    "name": name,
                    "method": tool_slug,
                    "successful": True,
                }
                # Store in cache (memory + disk)
                cached[word_id] = out
                _identity_cache["value"] = cached
                _identity_cache["at"] = now
                disk = _load_identity_cache()
                disk[word_id] = out
                _save_identity_cache(disk)
                return out
        except (RuntimeError, subprocess.TimeoutExpired, OSError) as exc:
            last_error = str(exc)
            continue

    out = {
        "account": word_id,
        "toolkit": toolkit,
        "email": None,
        "name": None,
        "method": None,
        "successful": False,
        "error": last_error or "unable to resolve identity",
    }
    cached[word_id] = out
    _identity_cache["value"] = cached
    _identity_cache["at"] = now
    disk = _load_identity_cache()
    disk[word_id] = out
    _save_identity_cache(disk)
    return out


def execute_tool_via_rest(
    slug: str,
    arguments: dict[str, Any],
    *,
    connected_account_id: str | None = None,
    user_id: str | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Appelle POST /api/v3/tools/execute/{slug} (route multi-compte).

    Permet de cibler un compte Composio précis via `connected_account_id`
    (word_id) côté REST. Le passthrough CLI supporte aussi `--account`, mais
    cette route garde une surface HTTP programmatique quand le namespace REST
    expose bien les comptes.
    """
    api_key = _composio_api_key()
    if not api_key:
        return {"successful": False, "error": "no composio api key (régénère uak_ via dashboard.composio.dev)"}
    url = f"{_composio_base_url()}/api/v3/tools/execute/{slug}"
    body: dict[str, Any] = {"arguments": arguments}
    if connected_account_id:
        body["connected_account_id"] = connected_account_id
    if user_id:
        body["user_id"] = user_id
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(url, headers={"x-api-key": api_key, "content-type": "application/json"}, json=body)
    except httpx.HTTPError as exc:
        return {"successful": False, "error": f"http error: {exc}"}
    try:
        payload = r.json()
    except ValueError:
        return {"successful": False, "error": f"non-JSON response (status {r.status_code}): {r.text[:200]}"}
    if r.status_code // 100 != 2:
        err = payload.get("error") if isinstance(payload, dict) else None
        return {"successful": False, "status": r.status_code, "error": err or payload}
    return payload


def fetch_connections_via_cli(timeout: float = 6.0) -> list[dict[str, Any]]:
    """Lit `composio connections list` (JSON) et le mappe au format connected_accounts."""
    cli = composio_cli_path()
    if not cli:
        return []
    try:
        proc = subprocess.run(
            [cli, "connections", "list"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("composio CLI connections list failed: %s", exc)
        return []
    if proc.returncode != 0:
        logger.debug("composio CLI returned %s: %s", proc.returncode, proc.stderr[:200])
        return []
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []
    accounts: list[dict[str, Any]] = []
    for toolkit_slug, entries in payload.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            word_id = str(entry.get("word_id") or "").strip()
            accounts.append(
                {
                    "id": word_id or f"{toolkit_slug}_unknown",
                    "status": str(entry.get("status") or "").strip(),
                    "toolkit": {"slug": toolkit_slug, "name": toolkit_slug},
                    "label": entry.get("alias"),
                    "auth_config": {"auth_scheme": entry.get("auth_scheme")},
                    "_source": "cli",
                }
            )
    return accounts


def fetch_connections_via_cli_enriched(
    toolkit: str | None = None,
    active_only: bool = True,
    resolve_identities: bool = False,
    timeout: float = 10.0,
) -> list[dict[str, Any]]:
    """Récupère les connexions CLI et optionnellement résout les emails via whoami."""
    accounts = fetch_connections_via_cli(timeout=timeout)
    if toolkit:
        accounts = [a for a in accounts if _toolkit_info(a)[0] == toolkit.lower()]
    if active_only:
        accounts = [a for a in accounts if str(a.get("status") or "").strip().upper() == "ACTIVE"]
    if not resolve_identities:
        return accounts
    # Resolve identity for each account in parallel-ish (sequential for now)
    for acc in accounts:
        word_id = str(acc.get("id") or "").strip()
        tk = _toolkit_info(acc)[0]
        if word_id:
            resolved = resolve_account_identity(word_id, toolkit=tk, timeout=8.0)
            if resolved.get("successful"):
                data = acc.setdefault("data", {})
                if isinstance(data, dict):
                    data["resolved_email"] = resolved.get("email")
                    data["resolved_name"] = resolved.get("name")
                acc["resolved_identity"] = resolved
    return accounts


def _read_user_data() -> dict[str, Any]:
    try:
        return json.loads(_USER_DATA_PATH.read_text(encoding="utf-8")) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def _composio_api_key() -> str | None:
    data = _read_user_data()
    key = str(data.get("api_key") or "").strip()
    if key:
        return key
    env_key = (os.environ.get("COMPOSIO_API_KEY") or "").strip()
    return env_key or None


def _composio_base_url() -> str:
    data = _read_user_data()
    base = str(data.get("base_url") or "").strip()
    return base.rstrip("/") if base else _DEFAULT_BASE_URL


def fetch_connected_accounts(timeout: float = _DEFAULT_TIMEOUT) -> list[dict[str, Any]]:
    """REST v3 d'abord, sinon CLI locale. Retourne [] silencieusement si tout échoue."""
    rest = _fetch_connected_accounts_rest(timeout=timeout)
    if rest:
        return rest
    return fetch_connections_via_cli()


def _fetch_connected_accounts_rest(timeout: float = _DEFAULT_TIMEOUT) -> list[dict[str, Any]]:
    api_key = _composio_api_key()
    if not api_key:
        return []
    url = f"{_composio_base_url()}/api/v3/connected_accounts"
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(url, headers={"x-api-key": api_key, "accept": "application/json"})
        if r.status_code // 100 != 2:
            logger.debug("composio connected_accounts HTTP %s: %s", r.status_code, r.text[:200])
            return []
        payload = r.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.debug("composio connected_accounts fetch failed: %s", exc)
        return []
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        raw = payload.get("items") or payload.get("data") or payload.get("connected_accounts") or []
        items = raw if isinstance(raw, list) else []
    else:
        items = []
    return [it for it in items if isinstance(it, dict)]


def _toolkit_info(account: dict[str, Any]) -> tuple[str, str]:
    """Retourne (slug, display_name) du toolkit pour un connected_account."""
    tk = account.get("toolkit")
    if isinstance(tk, dict):
        slug = str(tk.get("slug") or tk.get("name") or "").strip().lower()
        name = str(tk.get("name") or tk.get("slug") or slug).strip()
        if slug:
            return slug, name or slug
    for key in ("toolkit_slug", "app_name", "appName", "app"):
        v = account.get(key)
        if isinstance(v, str) and v.strip():
            s = v.strip().lower()
            return s, s
    return "unknown", "Composio"


def _account_identity(account: dict[str, Any]) -> dict[str, str | None]:
    """Extrait les infos d'identification du compte (user_id, email, label) pour distinguer plusieurs accounts d'un même toolkit."""
    user_id = account.get("user_id") or account.get("entity_id") or account.get("entityId")
    label = account.get("label") or account.get("name")
    email: str | None = None
    data = account.get("data")
    if isinstance(data, dict):
        for key in ("email", "user_email", "account_email", "profile_email"):
            v = data.get(key)
            if isinstance(v, str) and v.strip():
                email = v.strip()
                break
        if not label:
            for key in ("name", "display_name", "profile_name", "account_name", "username"):
                v = data.get(key)
                if isinstance(v, str) and v.strip():
                    label = v.strip()
                    break
    return {
        "user_id": str(user_id).strip() if isinstance(user_id, str) and user_id.strip() else None,
        "email": email,
        "label": str(label).strip() if isinstance(label, str) and label.strip() else None,
    }


def _auth_scheme(account: dict[str, Any]) -> str | None:
    auth_cfg = account.get("auth_config")
    if isinstance(auth_cfg, dict):
        scheme = auth_cfg.get("auth_scheme") or auth_cfg.get("authScheme")
        if isinstance(scheme, str) and scheme.strip():
            return scheme.strip()
    scheme = account.get("auth_scheme") or account.get("authScheme")
    if isinstance(scheme, str) and scheme.strip():
        return scheme.strip()
    return None


def composio_forms() -> list[tuple[str, dict[str, Any]]]:
    """Mappe chaque connected_account vers (slug, form_dict) pour _build_connectors_raw.

    Cache TTL en mémoire (_FORMS_CACHE_TTL_SECONDS) pour lisser les rechargements
    rapides du dashboard et les appels MCP rapprochés.
    """
    cached = _cache_get()
    if cached is not None:
        return cached

    from zab.services.connectors_aggregate import normalize_connector_slug  # local import to avoid cycle

    accounts = fetch_connected_accounts()
    mcp_url = os.environ.get("COMPOSIO_MCP") or None
    out: list[tuple[str, dict[str, Any]]] = []
    for acc in accounts:
        toolkit_slug, toolkit_name = _toolkit_info(acc)
        slug = normalize_connector_slug(toolkit_slug)
        account_id = str(acc.get("id") or acc.get("connected_account_id") or "").strip()
        status = str(acc.get("status") or "").strip().upper() or None
        scheme = _auth_scheme(acc)
        identity = _account_identity(acc)
        account_label = identity["email"] or identity["label"] or identity["user_id"] or account_id
        form_id = f"composio-{account_id or toolkit_slug}"
        target = f"{toolkit_slug} · {account_label}" if account_label else toolkit_slug
        note = account_label if account_label and account_label != account_id else None
        out.append(
            (
                slug,
                {
                    "id": form_id[:120],
                    "kind": "composio",
                    "transport_kind": "http",
                    "enabled": status == "ACTIVE",
                    "target": target,
                    "note": note,
                    "source_label": "composio",
                    "config_path": None,
                    "source_ref": f"composio/connected_accounts/{account_id}" if account_id else f"composio/toolkits/{toolkit_slug}",
                    "meta": {
                        "toolkit_slug": toolkit_slug,
                        "toolkit_name": toolkit_name,
                        "auth_scheme": scheme,
                        "connected_account_id": account_id or None,
                        "user_id": identity["user_id"],
                        "account_email": identity["email"],
                        "account_label": identity["label"],
                        "status": status,
                        "mcp_url": mcp_url,
                    },
                },
            )
        )
    _cache_set(out)
    return out
