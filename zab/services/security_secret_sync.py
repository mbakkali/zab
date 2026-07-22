"""Secret-provider sync metadata for the local Security dashboard.

The functions in this module deliberately avoid returning raw secret values.
They only build masked readiness/status data and human-reviewable plans.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote


DASHLANE_ID = "dashlane"
DASHLANE_WEB_SECRETS_URL = "https://app.dashlane.com/#/credentials"
_DASHLANE_CREATE_COMMAND_ENV = "ZAB_DASHLANE_SECRET_CREATE_COMMAND"
_DASHLANE_REFERENCE_RE = re.compile(r"^dl://\S+$")
_DASHLANE_UUID_RE = re.compile(
    r"^\{?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}?$"
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short_text(value: str, *, limit: int = 280) -> str:
    clean = " ".join(value.strip().split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3] + "..."


def _short_error(value: str, secret_value: str = "", *, limit: int = 160) -> str:
    text = value
    if secret_value:
        text = text.replace(secret_value, "[redacted]")
    return _short_text(text, limit=limit)


def _normalize_secret_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.strip().lower())


def dashlane_title_for_name(name: str) -> str:
    """Return a Dashlane-safe title for a tracked env variable."""
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip()).strip("_")
    if clean.upper().startswith("Z_"):
        return clean or "Z_VARIABLE"
    return f"Z_{clean or 'VARIABLE'}"


def dashlane_reference_for_name(name: str) -> str:
    return f"dl://{dashlane_title_for_name(name)}"


def _dashlane_identity(value: str) -> str:
    return value.strip().strip("{}").casefold()


def _dashlane_reference_target(reference: str) -> str:
    ref = reference.strip()
    if not ref.startswith("dl://"):
        return ""
    return ref[5:].split("/", 1)[0].strip()


def _dashlane_web_url_for_item_id(item_id: str) -> str:
    target = item_id.strip().strip("{}")
    if not target:
        return DASHLANE_WEB_SECRETS_URL
    return f"{DASHLANE_WEB_SECRETS_URL}/{quote(target, safe='')}"


def _dashlane_web_url_for_reference(reference: str, items: list[dict[str, Any]]) -> str:
    target = _dashlane_reference_target(reference)
    if not target:
        return DASHLANE_WEB_SECRETS_URL

    target_identity = _dashlane_identity(target)
    target_normalized = _normalize_secret_name(target)
    for item in items:
        item_id = str(item.get("id") or "")
        item_reference_target = _dashlane_reference_target(str(item.get("reference") or ""))
        title = str(item.get("title") or "")
        if target_identity and target_identity in {
            _dashlane_identity(item_id),
            _dashlane_identity(item_reference_target),
        }:
            return str(item.get("web_url") or _dashlane_web_url_for_item_id(item_id))
        if target_normalized and _normalize_secret_name(title) == target_normalized:
            return str(item.get("web_url") or _dashlane_web_url_for_item_id(item_id))

    if _DASHLANE_UUID_RE.match(target):
        return _dashlane_web_url_for_item_id(target)
    return DASHLANE_WEB_SECRETS_URL


def _validate_dashlane_reference(reference: str) -> str:
    ref = reference.strip()
    if not _DASHLANE_REFERENCE_RE.match(ref):
        raise ValueError("reference_dashlane_invalide")
    if "<" in ref or ">" in ref:
        raise ValueError("reference_dashlane_placeholder")
    return ref


def _dashlane_create_command() -> list[str]:
    raw = os.environ.get(_DASHLANE_CREATE_COMMAND_ENV, "").strip()
    if not raw:
        node = shutil.which("node")
        root = _repo_root()
        script = root / "scripts" / "dashlane-secret-writer.mjs"
        playwright_dir = root / "zab-ui" / "node_modules" / "playwright"
        if node and script.is_file() and playwright_dir.is_dir():
            return [node, str(script)]
        return []
    # Secrets must travel via stdin only. Passing them in argv would expose them
    # to process listings and shell histories.
    if "{value}" in raw:
        return ["__invalid_value_placeholder__"]
    if raw.startswith("["):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return ["__invalid_json__"]
        if not isinstance(data, list):
            return ["__invalid_json__"]
        return [str(part) for part in data if str(part).strip()]
    try:
        return shlex.split(raw)
    except ValueError:
        return ["__invalid_shell__"]


def dashlane_secret_write_available() -> bool:
    cmd = _dashlane_create_command()
    return bool(cmd) and not (cmd[0].startswith("__invalid_") if cmd else False)


def _format_dashlane_create_command(
    command: list[str],
    *,
    name: str,
    title: str,
    reference: str,
    note: str,
) -> list[str]:
    return [
        part.replace("{name}", name)
        .replace("{title}", title)
        .replace("{reference}", reference)
        .replace("{note}", note)
        for part in command
    ]


def _dashlane_create_success_from_match(match: dict[str, Any], *, status: str = "created") -> dict[str, Any]:
    item_id = str(match.get("id") or "")
    return {
        "ok": True,
        "status": status,
        "provider": DASHLANE_ID,
        "dashlane_title": match.get("title") or "",
        "dashlane_reference_value": match.get("reference") or "",
        "dashlane_web_url": match.get("web_url") or _dashlane_web_url_for_item_id(item_id),
    }


def _safe_dashlane_item(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("title") or raw.get("name") or "").strip()
    item_id = str(raw.get("id") or "").strip()
    if not title and not item_id:
        return None
    raw_reference = str(raw.get("reference") or "").strip()
    raw_web_url = str(raw.get("web_url") or raw.get("url") or "").strip()
    reference_target = item_id or title
    return {
        "id": item_id,
        "title": title or item_id,
        "reference": raw_reference if raw_reference.startswith("dl://") else f"dl://{reference_target}",
        "web_url": raw_web_url if raw_web_url.startswith("https://") else _dashlane_web_url_for_item_id(item_id),
    }


def dashlane_secret_inventory(*, timeout: float = 5.0) -> dict[str, Any]:
    """Return redacted Dashlane Secret metadata.

    ``dcli secret -o json`` returns Secret item metadata. We keep only id/title
    and never return field values.
    """
    dcli = shutil.which("dcli")
    if not dcli:
        return {"available": False, "status": "missing_cli", "items": [], "count": 0}
    try:
        proc = subprocess.run(
            [dcli, "secret", "-o", "json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "available": False,
            "status": "error",
            "items": [],
            "count": 0,
            "status_detail": _short_text(str(exc)),
        }
    if proc.returncode != 0:
        text = proc.stderr.strip() or proc.stdout.strip()
        return {
            "available": False,
            "status": "error",
            "items": [],
            "count": 0,
            "status_detail": _short_text(text),
        }
    try:
        data = json.loads(proc.stdout or "[]")
    except Exception as exc:  # noqa: BLE001 - tolerate dcli output drift.
        return {
            "available": False,
            "status": "parse_error",
            "items": [],
            "count": 0,
            "status_detail": _short_text(str(exc)),
        }
    if isinstance(data, list):
        raw_items = data
    elif isinstance(data, dict):
        raw_items = data.get("items") or data.get("secrets") or []
    else:
        raw_items = []
    items = [item for item in (_safe_dashlane_item(raw) for raw in raw_items) if item]
    items.sort(key=lambda item: str(item.get("title") or "").casefold())
    return {"available": True, "status": "ok", "items": items, "count": len(items)}


def _dashlane_matches(name: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_desired = _normalize_secret_name(dashlane_title_for_name(name))
    if not normalized_desired:
        return []
    matches: list[dict[str, Any]] = []
    for item in items:
        title = str(item.get("title") or "")
        normalized_title = _normalize_secret_name(title)
        if not normalized_title:
            continue
        if normalized_title != normalized_desired:
            continue
        matches.append(
            {
                "id": item.get("id") or "",
                "title": title,
                "reference": item.get("reference") or "",
                "web_url": item.get("web_url") or _dashlane_web_url_for_item_id(str(item.get("id") or "")),
                "match": "exact",
                "score": 1.0,
            }
        )
    matches.sort(key=lambda item: (-float(item.get("score") or 0), str(item.get("title") or "").casefold()))
    return matches[:3]


def _run_status(cmd: list[str]) -> tuple[bool, str | None]:
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, _short_text(str(exc))
    text = proc.stdout.strip() or proc.stderr.strip()
    return proc.returncode == 0, (_short_text(text) if text else None)


def secret_providers() -> list[dict[str, Any]]:
    """Return configured providers for the UI provider rail."""
    dcli = shutil.which("dcli")
    dashlane_ok = False
    dashlane_status: str | None = None
    if dcli:
        dashlane_ok, dashlane_status = _run_status([dcli, "status"])
    dashlane_write_available = dashlane_secret_write_available()

    return [
        {
            "id": DASHLANE_ID,
            "label": "Dashlane",
            "available": bool(dcli),
            "implemented": True,
            "enabled": True,
            "cli": "dcli",
            "cli_path": dcli,
            "status": "ready" if dashlane_ok else ("login_required" if dcli else "missing_cli"),
            "status_label": (
                "CLI connecte" if dashlane_ok else ("Login requis" if dcli else "dcli absent")
            ),
            "status_detail": dashlane_status,
            "login_command": "dcli sync",
            "check_command": "dcli status",
            "capabilities": [
                "detect_dl_refs",
                "sync_plan",
                "write_local_dl_refs",
                "create_missing_secrets" if dashlane_write_available else "create_missing_secrets_requires_writer",
            ],
            "limitations": [
                (
                    "Le CLI Dashlane expose le coffre en lecture. Zab utilise le writer local quand il est disponible; "
                    "sur macOS il cible Chrome deja connecte via AppleScript, sinon il bascule sur Playwright/CDP."
                ),
            ],
            "write_supported": dashlane_write_available,
            "local_reference_write_supported": True,
            "create_command_env": _DASHLANE_CREATE_COMMAND_ENV,
        },
        {
            "id": "dotenvx",
            "label": "dotenvx",
            "available": bool(shutil.which("dotenvx")),
            "implemented": False,
            "enabled": False,
            "cli": "dotenvx",
            "status": "planned",
            "status_label": "Prevus",
            "capabilities": ["planned"],
            "limitations": ["Provider grise pour cette iteration."],
            "write_supported": False,
        },
        {
            "id": "op",
            "label": "1Password",
            "available": bool(shutil.which("op")),
            "implemented": False,
            "enabled": False,
            "cli": "op",
            "status": "planned",
            "status_label": "Prevus",
            "capabilities": ["planned"],
            "limitations": ["Provider grise pour cette iteration."],
            "write_supported": False,
        },
        {
            "id": "sops",
            "label": "SOPS",
            "available": bool(shutil.which("sops")),
            "implemented": False,
            "enabled": False,
            "cli": "sops",
            "status": "planned",
            "status_label": "Prevus",
            "capabilities": ["planned"],
            "limitations": ["Provider grise pour cette iteration."],
            "write_supported": False,
        },
    ]


def _source_lines(sources: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for source in sources:
        if source.get("kind") == "file":
            label = str(source.get("path_display") or source.get("path") or ".env")
            key = str(source.get("key") or "")
            line = source.get("line")
            suffix = f" (l.{line})" if line else ""
            out.append(f"- {label} -> {key}{suffix}")
        elif source.get("kind") == "process":
            keys = [str(k) for k in source.get("keys") or [] if k]
            out.append(f"- Processus dashboard -> {', '.join(keys) if keys else 'variable presente'}")
    return out or ["- Aucune source locale detectee"]


def _dashlane_note_template(variable: dict[str, Any], *, reference: str | None = None) -> str:
    name = str(variable.get("name") or "")
    source_text = "\n".join(_source_lines(variable.get("sources") or []))
    ref = reference or dashlane_reference_for_name(name)
    return "\n".join(
        [
            "Zab Security sync",
            f"Variable: {name}",
            "Provider target: Dashlane Secret",
            "",
            "Local sources:",
            source_text,
            "",
            "After creating the Dashlane Secret, replace the local .env value with:",
            f"{name}={ref}",
            "",
            "Do not paste the secret value in this note.",
        ]
    )


def create_dashlane_secret(
    variable: dict[str, Any],
    *,
    value: str,
    timeout: float = 20.0,
) -> dict[str, Any]:
    """Create a missing Dashlane Secret through a configured writer command.

    Dashlane's public ``dcli secret`` command is read-only. When a local writer
    is configured, Zab sends the secret payload on stdin as JSON and then
    verifies the created item by re-reading the redacted Dashlane inventory.
    """
    name = str(variable.get("name") or "").strip()
    title = dashlane_title_for_name(name)
    reference = dashlane_reference_for_name(name)
    if not name:
        return {"ok": False, "status": "error", "reason": "variable_introuvable"}
    secret_value = value.strip()
    if not secret_value:
        return {
            "ok": False,
            "status": "error",
            "reason": "valeur_locale_introuvable",
            "dashlane_title": title,
            "dashlane_reference_value": reference,
        }
    if secret_value.startswith("dl://"):
        return {
            "ok": True,
            "status": "exists",
            "provider": DASHLANE_ID,
            "dashlane_title": title,
            "dashlane_reference_value": secret_value,
            "dashlane_web_url": _dashlane_web_url_for_reference(secret_value, []),
        }

    inventory = dashlane_secret_inventory()
    items = [item for item in (_safe_dashlane_item(raw) for raw in inventory.get("items") or []) if item]
    matches = _dashlane_matches(name, items)
    if matches:
        return _dashlane_create_success_from_match(matches[0], status="exists")

    command = _dashlane_create_command()
    if not command:
        return {
            "ok": False,
            "status": "unsupported",
            "reason": "dashlane_secret_write_unavailable",
            "dashlane_title": title,
            "dashlane_reference_value": reference,
            "dashlane_web_url": DASHLANE_WEB_SECRETS_URL,
            "hint": f"Configure {_DASHLANE_CREATE_COMMAND_ENV}; dcli secret est lecture seule.",
        }
    if command[0].startswith("__invalid_"):
        return {
            "ok": False,
            "status": "error",
            "reason": "dashlane_secret_create_command_invalid",
            "dashlane_title": title,
            "dashlane_reference_value": reference,
        }

    note = _dashlane_note_template(variable, reference=reference)
    argv = _format_dashlane_create_command(command, name=name, title=title, reference=reference, note=note)
    payload = json.dumps(
        {
            "provider": DASHLANE_ID,
            "name": name,
            "title": title,
            "value": secret_value,
            "note": note,
        },
        ensure_ascii=False,
    )
    try:
        proc = subprocess.run(
            argv,
            input=payload,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "ok": False,
            "status": "error",
            "reason": "dashlane_secret_create_failed",
            "dashlane_title": title,
            "dashlane_reference_value": reference,
            "error": _short_error(str(exc), secret_value),
        }
    if proc.returncode != 0:
        text = proc.stderr.strip() or proc.stdout.strip()
        return {
            "ok": False,
            "status": "error",
            "reason": "dashlane_secret_create_failed",
            "dashlane_title": title,
            "dashlane_reference_value": reference,
            "exit_code": proc.returncode,
            "error": _short_error(text or "commande_echouee", secret_value),
        }

    dcli = shutil.which("dcli")
    if dcli:
        try:
            subprocess.run([dcli, "sync"], check=False, capture_output=True, text=True, timeout=8)
        except (OSError, subprocess.TimeoutExpired):
            pass

    refreshed = dashlane_secret_inventory()
    refreshed_items = [
        item for item in (_safe_dashlane_item(raw) for raw in refreshed.get("items") or []) if item
    ]
    refreshed_matches = _dashlane_matches(name, refreshed_items)
    if refreshed_matches:
        return _dashlane_create_success_from_match(refreshed_matches[0], status="created")

    returned_item: dict[str, Any] | None = None
    if proc.stdout.strip():
        try:
            returned_item = _safe_dashlane_item(json.loads(proc.stdout))
        except Exception:  # noqa: BLE001 - stdout is optional and not trusted.
            returned_item = None
    if returned_item and _normalize_secret_name(str(returned_item.get("title") or "")) == _normalize_secret_name(title):
        return _dashlane_create_success_from_match(returned_item, status="created")

    return {
        "ok": False,
        "status": "error",
        "reason": "dashlane_secret_create_not_verified",
        "dashlane_title": title,
        "dashlane_reference_value": reference,
        "dashlane_web_url": DASHLANE_WEB_SECRETS_URL,
    }


def _reference_hint(value: str) -> str:
    v = value.strip()
    if not v.startswith("dl://"):
        return ""
    if len(v) <= 18:
        return v
    return v[:12] + "..." + v[-6:]


def _path_display(path: Path) -> str:
    home = Path.home()
    try:
        rel = path.resolve().relative_to(home)
        return f"~/{rel.as_posix()}"
    except (OSError, ValueError):
        return str(path)


def build_secret_sync_payload(
    variables: list[dict[str, Any]],
    raw_values_by_name: dict[str, str],
    *,
    generated_at_utc: str | None = None,
    dashlane_inventory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build provider sync status for the tracked env variables.

    ``raw_values_by_name`` is accepted only to detect provider references. Raw
    values must not be copied into the returned payload.
    """
    generated = generated_at_utc or _now_iso()
    inventory = dashlane_inventory if isinstance(dashlane_inventory, dict) else dashlane_secret_inventory()
    dashlane_items = [item for item in (_safe_dashlane_item(raw) for raw in inventory.get("items") or []) if item]
    rows: list[dict[str, Any]] = []
    counts = {"synced": 0, "pending": 0, "missing": 0, "total": 0}

    for variable in variables:
        name = str(variable.get("name") or "")
        present = bool(variable.get("present"))
        raw = str(raw_values_by_name.get(name) or "").strip()
        is_dashlane_ref = raw.startswith("dl://")
        if is_dashlane_ref:
            status = "synced"
            counts["synced"] += 1
        elif present:
            status = "pending"
            counts["pending"] += 1
        else:
            status = "missing"
            counts["missing"] += 1
        counts["total"] += 1

        matches = _dashlane_matches(name, dashlane_items)
        selected_match = matches[0] if matches else None
        title = str((selected_match or {}).get("title") or dashlane_title_for_name(name))
        reference = str((selected_match or {}).get("reference") or dashlane_reference_for_name(name))
        web_url = (
            _dashlane_web_url_for_reference(raw, dashlane_items)
            if is_dashlane_ref
            else str((selected_match or {}).get("web_url") or DASHLANE_WEB_SECRETS_URL)
        )
        row = {
            "name": name,
            "status": status,
            "provider": DASHLANE_ID if is_dashlane_ref else None,
            "recommended_provider": DASHLANE_ID if status == "pending" else None,
            "dashlane_title": title,
            "dashlane_reference_value": reference,
            "dashlane_reference_template": f"{name}={reference}" if name else reference,
            "dashlane_web_url": web_url,
            "dashlane_match_status": "matched" if selected_match else "not_found",
            "dashlane_matches": matches,
            "reference_hint": _reference_hint(raw) if is_dashlane_ref else "",
            "note_template": _dashlane_note_template(variable, reference=reference) if status == "pending" else "",
            "source_count": len(variable.get("sources") or []),
        }
        rows.append(row)

    status = "ok" if counts["pending"] == 0 else "needs_sync"
    return {
        "provider": DASHLANE_ID,
        "status": status,
        "generated_at_utc": generated,
        "write_supported": False,
        "dashlane_inventory": {
            "available": bool(inventory.get("available")),
            "status": inventory.get("status") or "unknown",
            "count": int(inventory.get("count") or 0),
            "status_detail": inventory.get("status_detail"),
            "items": dashlane_items,
        },
        "counts": counts,
        "variables": rows,
        "manual_steps": [
            "Lancer dcli sync si Dashlane n'est pas connecte.",
            "Pour une sync complete, configurer le writer ZAB_DASHLANE_SECRET_CREATE_COMMAND si dcli ne sait pas creer de Secret.",
            "La modale synchronise ensuite chaque variable une par une: creation du Secret manquant puis remplacement local par dl://.",
        ],
    }


def attach_secret_sync(
    variables: list[dict[str, Any]],
    raw_values_by_name: dict[str, str],
) -> dict[str, Any]:
    sync = build_secret_sync_payload(variables, raw_values_by_name)
    by_name = {str(row.get("name") or ""): row for row in sync["variables"]}
    for variable in variables:
        variable["sync"] = by_name.get(str(variable.get("name") or ""))
    return sync


def dashlane_sync_check(sync_payload: dict[str, Any], *, apply: bool = False) -> dict[str, Any]:
    pending = int(sync_payload.get("counts", {}).get("pending") or 0)
    write_available = dashlane_secret_write_available()
    if apply and pending and not write_available:
        status = "action_required"
        message = "Creation Dashlane non cablee: configurez ZAB_DASHLANE_SECRET_CREATE_COMMAND pour creer les Secrets manquants."
    elif apply and pending:
        status = "needs_sync"
        message = f"{pending} secret(s) seront crees puis references un par un par la modale."
    elif pending:
        status = "needs_sync"
        message = f"{pending} secret(s) a synchroniser vers Dashlane."
    else:
        status = "ok"
        message = "Aucune variable locale en attente de synchronisation Dashlane."
    return {
        **sync_payload,
        "status": status,
        "apply_requested": bool(apply),
        "message": message,
        "providers": secret_providers(),
    }


def copy_to_clipboard(value: str) -> tuple[bool, str | None]:
    """Copy a secret value to the OS clipboard without returning it."""
    if not value:
        return False, "valeur_vide"
    pbcopy = shutil.which("pbcopy")
    if not pbcopy:
        return False, "clipboard_indisponible"
    try:
        proc = subprocess.run(
            [pbcopy],
            input=value,
            text=True,
            capture_output=True,
            check=False,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, _short_text(str(exc), limit=120)
    if proc.returncode != 0:
        return False, _short_text(proc.stderr or proc.stdout or "clipboard_error", limit=120)
    return True, None


def _dotenv_line_parts(raw_line: str) -> tuple[str, str]:
    if raw_line.endswith("\r\n"):
        return raw_line[:-2], "\r\n"
    if raw_line.endswith("\n"):
        return raw_line[:-1], "\n"
    return raw_line, ""


def _replace_dotenv_key(text: str, key: str, reference: str) -> tuple[str, bool]:
    pattern = re.compile(rf"^(\s*(?:export\s+)?{re.escape(key)}\s*=\s*).*$")
    changed = False
    out: list[str] = []
    for raw_line in text.splitlines(keepends=True):
        body, eol = _dotenv_line_parts(raw_line)
        match = pattern.match(body)
        if match:
            out.append(f"{match.group(1)}{reference}{eol}")
            changed = True
        else:
            out.append(raw_line)
    return "".join(out), changed


def apply_dashlane_reference(
    variables: list[dict[str, Any]],
    *,
    name: str,
    reference: str | None = None,
    allowed_paths: set[str] | None = None,
) -> dict[str, Any]:
    """Replace raw local .env values with Dashlane references.

    This intentionally does not return or log the old value. Dashlane's CLI is
    read-only for vault mutations, so Zab only persists dl:// references to
    secrets that live in Dashlane.
    """
    clean_name = name.strip()
    row = next((v for v in variables if str(v.get("name") or "") == clean_name), None)
    if row is None:
        return {"name": clean_name, "status": "error", "reason": "variable_introuvable"}
    sync = row.get("sync") if isinstance(row.get("sync"), dict) else {}
    if sync.get("status") == "missing" or not row.get("present"):
        return {"name": clean_name, "status": "skipped", "reason": "variable_absente"}
    if sync.get("status") == "synced":
        return {"name": clean_name, "status": "skipped", "reason": "deja_synced"}

    try:
        ref = _validate_dashlane_reference(reference or dashlane_reference_for_name(clean_name))
    except ValueError as exc:
        return {"name": clean_name, "status": "error", "reason": str(exc)}

    file_sources: list[dict[str, Any]] = [
        source
        for source in row.get("sources") or []
        if isinstance(source, dict) and source.get("kind") == "file"
    ]
    if not file_sources:
        return {"name": clean_name, "status": "skipped", "reason": "source_process_only"}

    allowed = allowed_paths or set()
    by_path: dict[Path, set[str]] = {}
    skipped_sources: list[dict[str, Any]] = []
    for source in file_sources:
        raw_path = str(source.get("path") or "").strip()
        key = str(source.get("key") or clean_name).strip()
        if not raw_path or not key:
            skipped_sources.append({"reason": "source_incomplete"})
            continue
        try:
            path = Path(raw_path).expanduser().resolve()
        except OSError:
            skipped_sources.append({"path": raw_path, "key": key, "reason": "chemin_invalide"})
            continue
        if allowed and str(path) not in allowed:
            skipped_sources.append({"path": str(path), "key": key, "reason": "chemin_hors_perimetre"})
            continue
        if path.name != ".env":
            skipped_sources.append({"path": str(path), "key": key, "reason": "fichier_non_env"})
            continue
        by_path.setdefault(path, set()).add(key)

    changed_files: list[dict[str, Any]] = []
    for path, keys in sorted(by_path.items(), key=lambda item: str(item[0])):
        if not path.is_file():
            skipped_sources.append({"path": str(path), "reason": "fichier_absent"})
            continue
        try:
            original = path.read_text(encoding="utf-8")
        except OSError as exc:
            skipped_sources.append({"path": str(path), "reason": _short_text(str(exc), limit=120)})
            continue
        updated = original
        changed_keys: list[str] = []
        for key in sorted(keys):
            updated, changed = _replace_dotenv_key(updated, key, ref)
            if changed:
                changed_keys.append(key)
            else:
                skipped_sources.append({"path": str(path), "key": key, "reason": "cle_introuvable"})
        if not changed_keys or updated == original:
            continue
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        tmp_path = path.with_name(f".env.zab-dashlane-tmp-{ts}")
        try:
            st = path.stat()
            tmp_path.write_text(updated, encoding="utf-8")
            try:
                tmp_path.chmod(st.st_mode)
            except OSError:
                pass
            tmp_path.replace(path)
        except OSError as exc:
            try:
                tmp_path.unlink()
            except OSError:
                pass
            return {
                "name": clean_name,
                "status": "error",
                "reason": _short_text(str(exc), limit=160),
                "reference_hint": _reference_hint(ref),
            }
        changed_files.append(
            {
                "path": str(path),
                "path_display": _path_display(path),
                "keys": changed_keys,
                "storage": "dashlane_reference",
            }
        )

    if not changed_files:
        return {
            "name": clean_name,
            "status": "skipped",
            "reason": "aucune_source_modifiee",
            "reference_hint": _reference_hint(ref),
            "skipped_sources": skipped_sources,
        }
    return {
        "name": clean_name,
        "status": "synced",
        "provider": DASHLANE_ID,
        "reference_hint": _reference_hint(ref),
        "changed_files": changed_files,
        "skipped_sources": skipped_sources,
    }
