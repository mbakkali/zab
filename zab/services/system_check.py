"""System checks for the zab dashboard.

The checks are intentionally read-only and best-effort: a broken optional
integration should be reported as a failed/warn check, not break the dashboard.

Two modes:
- ``run_system_check()`` — sync, returns full payload (backward compat).
- ``iter_system_checks()`` — generator, yields one check dict at a time
  for SSE streaming so the UI can show progressive results.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Generator

from zab.paths import data_dir, resolve_skills_root, zab_repo_root, zab_ui_dist_dir
from zab.services import (
    agents_registry,
    composio_connectors,
    connectors_aggregate,
    memory_db,
    model_runtimes,
    state_index,
    workstation,
)
from zab.services.secrets_scan import scan_secret_presence
from zab.services.skills_sync_status import skills_sync_status_payload
from zab.user_config import load_user_config, tracked_env_names_for_security, user_config_path

Status = str

# ── Registry of all checks (ordered) ──────────────────────────────────

_CHECKS: list[tuple[str, str, str, Callable[[], dict[str, Any]]]] = [
    ("config_yaml",   "Configuration zab",      "core",     lambda: _check_config()),
    ("skills_root",   "Skills root",             "core",     lambda: _check_skills_root()),
    ("state_index",   "Index local-first",       "core",     lambda: _check_state_index()),
    ("dashboard_dist","Dashboard SPA",           "ui",       lambda: _check_dashboard_dist()),
    ("security_env",  "Variables d'environnement","security", lambda: _check_security_env()),
    ("memory",        "Mémoire Postgres",        "services", lambda: _check_memory()),
    ("composio",      "Composio",                "services", lambda: _check_composio()),
    ("connectors",    "Connecteurs (MCP + API)", "services", lambda: _check_connectors()),
    ("models_agents", "Modèles & agents",        "agents",   lambda: _check_models_agents()),
    ("hermes",        "Hermes Agent",            "agents",   lambda: _check_hermes()),
    ("workstation",   "Workstation GCP",        "infra",    lambda: _check_workstation()),
    ("cli_tools",     "CLI locaux",              "tools",    lambda: _check_cli_tools()),
]


def check_registry() -> list[dict[str, str]]:
    """Return the ordered list of check descriptors (id, label, category).

    Used by the SSE endpoint so the client can pre-populate the UI with
    "pending" rows before the first check result arrives.
    """
    return [{"id": cid, "label": lbl, "category": cat} for cid, lbl, cat, _fn in _CHECKS]


# ── Helpers ────────────────────────────────────────────────────────────

def _item(
    *,
    id: str,
    label: str,
    category: str,
    status: Status,
    message: str,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": id,
        "label": label,
        "category": category,
        "status": status,
        "message": message,
        "detail": detail or {},
    }


def _safe(fn: Callable[[], dict[str, Any]], *, id: str, label: str, category: str) -> dict[str, Any]:
    try:
        return fn()
    except Exception as exc:  # pragma: no cover - defensive dashboard guard
        return _item(
            id=id,
            label=label,
            category=category,
            status="fail",
            message=f"Check impossible: {type(exc).__name__}",
            detail={"error": str(exc)[:300]},
        )


# ── Individual checks ──────────────────────────────────────────────────

def _check_config() -> dict[str, Any]:
    cfg_path = user_config_path()
    cfg = load_user_config()
    if cfg.get("_error") == "yaml_invalid":
        return _item(
            id="config_yaml", label="Configuration zab", category="core",
            status="fail", message="config.yaml invalide",
            detail={"path": str(cfg_path)},
        )
    return _item(
        id="config_yaml", label="Configuration zab", category="core",
        status="ok" if cfg_path.is_file() else "warn",
        message="config.yaml chargé" if cfg_path.is_file() else "config.yaml absent, defaults utilisés",
        detail={"path": str(cfg_path), "keys": sorted(k for k in cfg.keys() if not str(k).startswith("_"))},
    )


def _check_skills_root() -> dict[str, Any]:
    root, source = resolve_skills_root()
    ok = root.exists() and root.is_dir()
    skill_count = 0
    if ok:
        try:
            skill_count = sum(1 for _ in root.rglob("SKILL.md"))
        except OSError:
            skill_count = 0
    return _item(
        id="skills_root", label="Skills root", category="core",
        status="ok" if ok and skill_count > 0 else "fail",
        message=f"{skill_count} SKILL.md détectés" if ok else "Racine skills introuvable",
        detail={"path": str(root), "source": source, "skill_count": skill_count},
    )


def _check_state_index() -> dict[str, Any]:
    state = state_index.load_state()
    summary = state_index.state_summary(state)
    path = Path(str(summary.get("path") or data_dir() / "state.yaml"))
    counts = summary.get("counts") if isinstance(summary.get("counts"), dict) else {}
    total_indexed = sum(int(v or 0) for v in counts.values()) if counts else 0
    status = "ok" if path.is_file() and total_indexed > 0 else "warn"
    return _item(
        id="state_index", label="Index local-first", category="core",
        status=status,
        message=f"{total_indexed} éléments indexés" if total_indexed else "Index vide ou non synchronisé",
        detail={"path": str(path), "last_sync_at": summary.get("last_sync_at"), "counts": counts},
    )


def _check_dashboard_dist() -> dict[str, Any]:
    index = zab_ui_dist_dir() / "index.html"
    return _item(
        id="dashboard_dist", label="Dashboard SPA", category="ui",
        status="ok" if index.is_file() else "warn",
        message="Build frontend présent" if index.is_file() else "Build frontend absent: lancer npm run build",
        detail={"index_html": str(index), "repo": str(zab_repo_root())},
    )


def _check_security_env() -> dict[str, Any]:
    tracked = tracked_env_names_for_security()
    scan = scan_secret_presence(tracked)
    raw_rows = scan.get("variables")
    rows: list[Any] = raw_rows if isinstance(raw_rows, list) else []
    present = [r for r in rows if isinstance(r, dict) and r.get("present")]
    missing = [str(r.get("name")) for r in rows if isinstance(r, dict) and not r.get("present")]
    ratio = (len(present) / len(rows)) if rows else 1.0
    status = "ok" if ratio >= 0.8 else "warn" if ratio >= 0.5 else "fail"
    return _item(
        id="security_env", label="Variables d'environnement", category="security",
        status=status,
        message=f"{len(present)}/{len(rows)} variables suivies présentes",
        detail={"missing": missing[:20], "env_files_scanned": scan.get("env_files_scanned", [])},
    )


def _check_memory() -> dict[str, Any]:
    st = memory_db.fetch_status()
    configured = bool(st.get("configured"))
    connected = bool(st.get("connected"))
    psycopg_ok = bool(st.get("psycopg_available"))
    if connected:
        status = "ok"
        message = f"Postgres connecté · {st.get('document_count') or 0} documents"
    elif configured and psycopg_ok:
        status = "warn"
        message = str(st.get("error") or "Mémoire configurée mais inaccessible")
    elif configured:
        status = "warn"
        message = str(st.get("error") or "Extra memory non installé")
    else:
        status = "fail"
        message = str(st.get("error") or "Mémoire non configurée")
    return _item(id="memory", label="Mémoire Postgres", category="services", status=status, message=message, detail=st)


def _check_composio() -> dict[str, Any]:
    cli = composio_connectors.composio_cli_path()
    accounts = composio_connectors.fetch_connections_via_cli(timeout=5.0) if cli else []
    active = [a for a in accounts if str(a.get("status") or "").upper() == "ACTIVE"]
    if active:
        status = "ok"
        message = f"{len(active)} comptes actifs / {len(accounts)} connexions"
    elif accounts:
        status = "warn"
        message = f"Aucun compte actif / {len(accounts)} connexions"
    else:
        status = "fail" if not cli else "warn"
        message = "CLI Composio introuvable" if not cli else "Aucune connexion Composio lisible"
    return _item(
        id="composio", label="Composio", category="services",
        status=status, message=message,
        detail={"cli": cli, "total": len(accounts), "active": len(active)},
    )


def _check_connectors() -> dict[str, Any]:
    try:
        payload = connectors_aggregate.list_connectors(page=1, limit=200)
    except Exception:
        payload = {}
    total = int(payload.get("pagination", {}).get("total", 0))
    rows = payload.get("data") or []
    enabled = sum(1 for r in rows if isinstance(r, dict) and r.get("any_enabled"))
    if total > 0 and enabled > 0:
        status = "ok"
        message = f"{enabled} connecteurs actifs / {total} au total"
    elif total > 0:
        status = "warn"
        message = f"{total} connecteurs trouvés, aucun activé"
    else:
        status = "warn"
        message = "Aucun connecteur configuré"
    return _item(
        id="connectors", label="Connecteurs (MCP + API)", category="services",
        status=status, message=message,
        detail={"total": total, "enabled": enabled},
    )


def _check_models_agents() -> dict[str, Any]:
    try:
        runtimes = model_runtimes.collect_model_runtimes()
    except Exception:
        runtimes = {}
    coding_models = runtimes.get("coding_models_flat_merged") or []
    runtime_count = len(runtimes.get("runtimes") or [])

    try:
        agents_data = agents_registry.list_codexbar_agents()
    except Exception:
        agents_data = {}
    agents_list = agents_data.get("agents") or []
    agents_requiring_cli = [
        a for a in agents_list
        if isinstance(a, dict) and a.get("requires_cli", True)
    ]
    agents_ok = [a for a in agents_requiring_cli if isinstance(a, dict) and a.get("on_path")]
    agents_missing = [
        str(a.get("id", "?"))
        for a in agents_requiring_cli
        if isinstance(a, dict) and not a.get("on_path")
    ]

    parts = []
    if coding_models:
        parts.append(f"{len(coding_models)} modèles coding")
    if runtime_count:
        parts.append(f"{runtime_count} runtimes")
    if agents_list:
        parts.append(f"{len(agents_ok)}/{len(agents_list)} agents sur PATH")

    if agents_missing:
        status = "warn"
        message = ", ".join(parts) + f" · Manquants: {', '.join(agents_missing[:5])}"
    elif parts:
        status = "ok"
        message = ", ".join(parts)
    else:
        status = "warn"
        message = "Aucun modèle ni agent configuré"
    return _item(
        id="models_agents", label="Modèles & agents", category="agents",
        status=status, message=message,
        detail={
            "coding_models_count": len(coding_models),
            "runtime_count": runtime_count,
            "agents_total": len(agents_list),
            "agents_on_path": len(agents_ok),
            "agents_missing": agents_missing[:10],
        },
    )


def _check_hermes() -> dict[str, Any]:
    hcfg_path = Path.home() / ".hermes" / "config.yaml"
    if not hcfg_path.is_file():
        return _item(
            id="hermes", label="Hermes Agent", category="agents",
            status="warn", message="Config Hermes absente (~/.hermes/config.yaml)",
            detail={"config_path": str(hcfg_path)},
        )

    try:
        import yaml as _yaml
        doc = _yaml.safe_load(hcfg_path.read_text(encoding="utf-8")) or {}
    except Exception:
        doc = {}

    providers = list((doc.get("providers") or {}).keys()) if isinstance(doc.get("providers"), dict) else []
    toolsets = doc.get("toolsets") or []
    external_dirs = doc.get("skills", {}).get("external_dirs", []) if isinstance(doc.get("skills"), dict) else []
    mem_provider = (doc.get("memory") or {}).get("provider", "file") if isinstance(doc.get("memory"), dict) else "file"

    try:
        sync_payload = skills_sync_status_payload()
    except Exception:
        sync_payload = {}
    hermes_info = sync_payload.get("hermes") or {}
    missing_in_hermes = hermes_info.get("missing_in_hermes") or []

    parts = [f"{len(providers)} providers", f"{len(external_dirs)} external_dirs"]
    if missing_in_hermes:
        status = "warn"
        parts.append(f"{len(missing_in_hermes)} dirs manquants dans hermes")
    else:
        status = "ok"

    return _item(
        id="hermes", label="Hermes Agent", category="agents",
        status=status, message=", ".join(parts),
        detail={
            "config_path": str(hcfg_path),
            "providers": providers[:15],
            "toolsets": toolsets[:10],
            "external_dirs_count": len(external_dirs),
            "memory_provider": mem_provider,
            "missing_in_hermes": missing_in_hermes[:10],
        },
    )


def _check_workstation() -> dict[str, Any]:
    try:
        ws = workstation.get_workstation_status()
    except Exception as exc:
        return _item(
            id="workstation", label="Workstation GCP", category="infra",
            status="warn", message=f"Statut inaccessible: {type(exc).__name__}",
            detail={"error": str(exc)[:300]},
        )

    found = bool(ws.get("found"))
    ws_status = str(ws.get("status") or "").lower()
    resource_type = str(ws.get("resource_type") or "unknown")

    if not found:
        status = "warn"
        message = f"Ressource non trouvée ({resource_type})"
    elif ws_status == "running":
        status = "ok"
        zone = ws.get("zone", "?")
        message = f"En cours d'exécution ({resource_type}, zone {zone})"
    elif ws_status == "stopped":
        status = "ok"
        message = f"Arrêtée ({resource_type})"
    else:
        status = "warn"
        message = f"Statut: {ws_status} ({resource_type})"

    return _item(
        id="workstation", label="Workstation GCP", category="infra",
        status=status, message=message,
        detail={
            "found": found,
            "resource_type": resource_type,
            "status": ws.get("status"),
            "zone": ws.get("zone"),
            "project_id": ws.get("project_id"),
            "instance_name": ws.get("instance_name"),
        },
    )


def _check_cli_tools() -> dict[str, Any]:
    required = ["zab", "uv", "node", "npm", "git", "gh", "gcloud", "mempalace", "mempalace-mcp"]
    rows = [{"name": name, "path": shutil.which(name), "ok": bool(shutil.which(name))} for name in required]
    missing = [r["name"] for r in rows if not r["ok"]]
    status = "ok" if not missing else "warn" if len(missing) <= 2 else "fail"
    return _item(
        id="cli_tools", label="CLI locaux", category="tools",
        status=status,
        message="Tous les CLI clés sont installés" if not missing else f"Manquants: {', '.join(missing)}",
        detail={"tools": rows, "missing": missing},
    )


# ── Public API ─────────────────────────────────────────────────────────

def iter_system_checks() -> Generator[dict[str, Any], None, None]:
    """Yield one check result at a time (for SSE streaming).

    Each yielded dict is a single check item.  The caller is responsible
    for computing the aggregate score after all checks have been emitted.
    """
    for cid, lbl, cat, fn in _CHECKS:
        yield _safe(fn, id=cid, label=lbl, category=cat)


def run_system_check() -> dict[str, Any]:
    """Synchronous full check — backward compatible."""
    checks = list(iter_system_checks())
    weights = {"ok": 1.0, "warn": 0.5, "fail": 0.0}
    score = sum(weights.get(str(c.get("status")), 0.0) for c in checks)
    percentage = round((score / len(checks)) * 100) if checks else 0
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "percentage": percentage,
        "score": score,
        "total": len(checks),
        "ok": sum(1 for c in checks if c.get("status") == "ok"),
        "warn": sum(1 for c in checks if c.get("status") == "warn"),
        "fail": sum(1 for c in checks if c.get("status") == "fail"),
        "checks": checks,
    }
