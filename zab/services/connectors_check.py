"""Checks par connecteur (et globaux) pour le dashboard zab.

Pour chaque "forme" (form) d'un connecteur on calcule une petite série de
vérifications best-effort :

- ``kind=api``   : présence de la variable d'env et probe ``/v1/models`` pour
                    LiteLLM / OpenRouter ; HTTP de base sinon.
- ``kind=mcp``   : ``stdio`` → ``shutil.which`` + variables d'env attendues ;
                    ``http`` / ``sse`` → reachability HTTP.
- ``kind=composio``: statut ACTIVE et clé API présente.

Les checks restent read-only et n'échouent pas le dashboard si une intégration
optionnelle est cassée. Deux modes :

* :func:`check_connector_payload` — synchrone, retourne le payload complet.
* :func:`iter_connector_checks` / :func:`iter_global_checks` — générateurs SSE.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from typing import Any, Generator

import httpx

from zab.services import connectors_aggregate
from zab.services.tools_probe import probe_models

Status = str  # "ok" | "warn" | "fail"

_HTTP_TIMEOUT_SECONDS = 6.0
_REACHABLE_OK_STATUSES = {200, 204, 301, 302, 303, 307, 308}
# 401/403/405/501 ⇒ joignable mais auth/méthode → warn plutôt que fail.
_REACHABLE_WARN_STATUSES = {401, 403, 404, 405, 500, 501, 502, 503}


def _safe_id(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", s or "").strip("-") or "x"


def _check_id(slug: str, form_id: str, suffix: str) -> str:
    return f"{_safe_id(slug)}__{_safe_id(form_id)}__{suffix}"


def _http_reachable(url: str, *, timeout: float = _HTTP_TIMEOUT_SECONDS) -> tuple[Status, str, dict[str, Any]]:
    if not url:
        return "fail", "URL manquante", {}
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            r = client.get(url)
    except httpx.HTTPError as exc:
        return "fail", f"Réseau KO : {type(exc).__name__}", {"url": url, "error": str(exc)[:200]}
    sc = r.status_code
    if sc in _REACHABLE_OK_STATUSES:
        return "ok", f"HTTP {sc}", {"status_code": sc, "url": url}
    if sc in _REACHABLE_WARN_STATUSES:
        return "warn", f"Joignable mais HTTP {sc}", {"status_code": sc, "url": url}
    return "fail", f"HTTP {sc}", {"status_code": sc, "url": url}


def _form_checks(slug: str, form: dict[str, Any]) -> list[dict[str, Any]]:
    """Construit la liste des checks pour une forme. Aucune exception ne fuit."""
    kind = str(form.get("kind") or "").lower()
    transport = str(form.get("transport_kind") or "").lower()
    target = str(form.get("target") or "")
    enabled = bool(form.get("enabled"))
    form_id = str(form.get("id") or "")
    meta = form.get("meta") if isinstance(form.get("meta"), dict) else {}

    out: list[dict[str, Any]] = []

    def _add(suffix: str, *, label: str, status: Status, message: str, detail: dict[str, Any] | None = None) -> None:
        out.append(
            {
                "id": _check_id(slug, form_id, suffix),
                "form_id": form_id,
                "label": label,
                "status": status,
                "message": message,
                "detail": detail or {},
            }
        )

    if not enabled:
        _add(
            "enabled",
            label=f"{form_id} · état",
            status="warn",
            message="désactivé dans la configuration",
            detail={"kind": kind, "transport": transport},
        )
        return out

    try:
        if kind == "api":
            env_name = meta.get("api_key_env") if isinstance(meta, dict) else None
            if env_name:
                present = bool((os.environ.get(str(env_name)) or "").strip())
                _add(
                    "env",
                    label=f"{form_id} · variable {env_name}",
                    status="ok" if present else "fail",
                    message="présente" if present else "absente",
                    detail={"env": str(env_name)},
                )
            if slug in ("litellm", "openrouter"):
                res = probe_models(slug)
                ok = bool(res.get("ok"))
                status_code = res.get("status_code")
                if status_code is not None:
                    msg = f"GET /v1/models → HTTP {status_code}"
                else:
                    msg = f"erreur : {res.get('error') or 'inconnue'}"
                _add(
                    "models",
                    label=f"{form_id} · GET /v1/models",
                    status="ok" if ok else "fail",
                    message=msg,
                    detail={k: v for k, v in res.items() if k != "body_preview"},
                )
            else:
                base = str((meta or {}).get("base_url") or target or "").strip()
                if base.startswith("http"):
                    status, msg, det = _http_reachable(base)
                    _add(
                        "http",
                        label=f"{form_id} · {base[:80]}",
                        status=status,
                        message=msg,
                        detail=det,
                    )

        elif kind == "mcp":
            cmd = meta.get("command") if isinstance(meta, dict) else None
            env_vars = meta.get("env_vars") if isinstance(meta, dict) else None
            if transport == "stdio":
                if isinstance(cmd, str) and cmd.strip():
                    resolved = shutil.which(cmd.strip())
                    _add(
                        "cmd",
                        label=f"{form_id} · commande `{cmd.strip()}`",
                        status="ok" if resolved else "fail",
                        message=f"trouvée : {resolved}" if resolved else "introuvable dans le PATH",
                        detail={"command": cmd.strip(), "resolved": resolved},
                    )
                if isinstance(env_vars, list) and env_vars:
                    missing = [
                        str(v)
                        for v in env_vars
                        if not (os.environ.get(str(v)) or "").strip()
                    ]
                    _add(
                        "envs",
                        label=f"{form_id} · {len(env_vars)} variable(s) d'env",
                        status="ok" if not missing else "warn",
                        message=(
                            "toutes définies"
                            if not missing
                            else f"manquantes : {', '.join(missing[:8])}"
                        ),
                        detail={"missing": missing, "expected": [str(v) for v in env_vars]},
                    )
            elif transport in ("http", "sse") and target.startswith("http"):
                status, msg, det = _http_reachable(target)
                _add(
                    "http",
                    label=f"{form_id} · endpoint {transport.upper()}",
                    status=status,
                    message=msg,
                    detail=det,
                )

        elif kind == "composio":
            status_raw = str((meta or {}).get("status") or "").upper()
            if status_raw == "ACTIVE":
                _add(
                    "status",
                    label=f"{form_id} · statut Composio",
                    status="ok",
                    message="ACTIVE",
                    detail={"status": status_raw},
                )
            elif status_raw:
                _add(
                    "status",
                    label=f"{form_id} · statut Composio",
                    status="warn",
                    message=f"statut={status_raw}",
                    detail={"status": status_raw},
                )
            else:
                _add(
                    "status",
                    label=f"{form_id} · statut Composio",
                    status="fail",
                    message="statut inconnu",
                    detail={"status": ""},
                )

        if not out:
            _add(
                "noop",
                label=f"{form_id} · type {kind or '?'}/{transport or '?'}",
                status="warn",
                message="aucun check automatique pour ce type",
                detail={"kind": kind, "transport": transport},
            )
    except Exception as exc:  # pragma: no cover - garde défensive
        _add(
            "exception",
            label=f"{form_id} · check impossible",
            status="fail",
            message=f"{type(exc).__name__}: {str(exc)[:160]}",
            detail={"kind": kind, "transport": transport},
        )

    return out


def _build_descriptors_for_row(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Construit les descripteurs (id, label, form_id) sans I/O coûteuse.

    On reproduit la même séquence que :func:`_form_checks` mais en ne calculant
    que les "etiquettes" : aucun appel réseau, aucun ``shutil.which``.
    """
    slug = str(row.get("id") or "")
    desc: list[dict[str, Any]] = []
    for form in row.get("forms") or []:
        kind = str(form.get("kind") or "").lower()
        transport = str(form.get("transport_kind") or "").lower()
        enabled = bool(form.get("enabled"))
        form_id = str(form.get("id") or "")
        meta = form.get("meta") if isinstance(form.get("meta"), dict) else {}

        def _push(suffix: str, label: str) -> None:
            desc.append(
                {
                    "id": _check_id(slug, form_id, suffix),
                    "form_id": form_id,
                    "label": label,
                }
            )

        if not enabled:
            _push("enabled", f"{form_id} · état")
            continue

        any_pushed = False
        if kind == "api":
            env_name = meta.get("api_key_env") if isinstance(meta, dict) else None
            if env_name:
                _push("env", f"{form_id} · variable {env_name}")
                any_pushed = True
            if slug in ("litellm", "openrouter"):
                _push("models", f"{form_id} · GET /v1/models")
                any_pushed = True
            else:
                base = str((meta or {}).get("base_url") or form.get("target") or "").strip()
                if base.startswith("http"):
                    _push("http", f"{form_id} · {base[:80]}")
                    any_pushed = True

        elif kind == "mcp":
            cmd = meta.get("command") if isinstance(meta, dict) else None
            env_vars = meta.get("env_vars") if isinstance(meta, dict) else None
            if transport == "stdio":
                if isinstance(cmd, str) and cmd.strip():
                    _push("cmd", f"{form_id} · commande `{cmd.strip()}`")
                    any_pushed = True
                if isinstance(env_vars, list) and env_vars:
                    _push("envs", f"{form_id} · {len(env_vars)} variable(s) d'env")
                    any_pushed = True
            elif transport in ("http", "sse") and str(form.get("target") or "").startswith("http"):
                _push("http", f"{form_id} · endpoint {transport.upper()}")
                any_pushed = True

        elif kind == "composio":
            _push("status", f"{form_id} · statut Composio")
            any_pushed = True

        if not any_pushed:
            _push("noop", f"{form_id} · type {kind or '?'}/{transport or '?'}")
    return desc


def _summary(checks: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(checks),
        "ok": sum(1 for c in checks if c.get("status") == "ok"),
        "warn": sum(1 for c in checks if c.get("status") == "warn"),
        "fail": sum(1 for c in checks if c.get("status") == "fail"),
    }


def check_connector_payload(slug: str) -> dict[str, Any] | None:
    """Calcule tous les checks pour un slug donné (sync)."""
    row = connectors_aggregate.get_connector(slug)
    if not row:
        return None
    checks: list[dict[str, Any]] = []
    for form in row.get("forms") or []:
        checks.extend(_form_checks(slug, form))
    return {
        "slug": slug,
        "display_name": row.get("display_name") or slug,
        "checks": checks,
        **_summary(checks),
    }


def iter_connector_checks(slug: str) -> Generator[dict[str, Any], None, None]:
    """Itère check par check pour un connecteur (pour SSE).

    Yields des dicts ``{"event": "registry"|"check"|"done", "data": ...}``.
    """
    row = connectors_aggregate.get_connector(slug)
    if not row:
        yield {
            "event": "error",
            "data": {"error": "slug_inconnu", "slug": slug},
        }
        return
    descriptors = _build_descriptors_for_row(row)
    yield {"event": "registry", "data": {"slug": slug, "checks": descriptors}}
    collected: list[dict[str, Any]] = []
    for form in row.get("forms") or []:
        for chk in _form_checks(slug, form):
            collected.append(chk)
            yield {"event": "check", "data": chk}
    summary = {
        "slug": slug,
        "display_name": row.get("display_name") or slug,
        **_summary(collected),
    }
    yield {"event": "done", "data": summary}


def iter_global_checks() -> Generator[dict[str, Any], None, None]:
    """Itère par connecteur pour le check global (SSE).

    Émet :
      * ``registry`` : la liste des connecteurs à vérifier
        (``{"slug", "display_name", "form_count"}``).
      * ``connector`` : un connecteur terminé avec tous ses checks.
      * ``done`` : résumé agrégé.
    """
    payload = connectors_aggregate.list_connectors(page=1, limit=200)
    rows = payload.get("data") or []
    registry = [
        {
            "slug": str(row.get("id")),
            "display_name": str(row.get("display_name") or row.get("id") or "?"),
            "form_count": int(row.get("form_count") or 0),
        }
        for row in rows
        if row.get("id")
    ]
    yield {"event": "registry", "data": registry}
    aggregate: list[dict[str, Any]] = []
    for entry in registry:
        slug = entry["slug"]
        result = check_connector_payload(slug) or {
            "slug": slug,
            "display_name": entry["display_name"],
            "checks": [],
            "total": 0,
            "ok": 0,
            "warn": 0,
            "fail": 0,
        }
        aggregate.extend(result.get("checks") or [])
        yield {"event": "connector", "data": result}
    summary = {
        "connectors_total": len(registry),
        **_summary(aggregate),
    }
    yield {"event": "done", "data": summary}


def sse_format(event: dict[str, Any]) -> str:
    name = str(event.get("event") or "message")
    data = event.get("data")
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {name}\ndata: {payload}\n\n"
