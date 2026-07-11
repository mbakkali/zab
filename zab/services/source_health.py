"""Freshness-aware health contract for Zab context sources."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Any

from zab.paths import data_dir, resolve_skills_root
from zab.services import agent_context, mcp_registry, state_index
from zab.services.memory_db import fetch_status as fetch_memory_status
from zab.services.secrets_scan import scan_secret_presence
from zab.user_config import security_env_paths_resolved, tracked_env_names_for_security
from zab.services.workspace_projects import discover_projects

ALLOWED_SOURCE_STATUSES = {
    "ok",
    "local_ok",
    "needs_auth",
    "error",
    "legacy_reference",
    "not_verified",
    "stale",
}
_CACHE_TTL_SECONDS = 60.0
_SOURCE_HEALTH_CACHE: tuple[float, dict[str, Any]] | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file_mtime(path: Path) -> str | None:
    try:
        if not path.is_file():
            return None
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        return None


def _source(
    *,
    id: str,
    kind: str,
    status: str,
    freshness: str,
    safe_message: str,
    last_checked_at: str,
    last_success_at: str | None = None,
    item_count: int | None = None,
    auth: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    normalized = status if status in ALLOWED_SOURCE_STATUSES else "error"
    return {
        "id": id,
        "kind": kind,
        "status": normalized,
        "freshness": freshness,
        "last_checked_at": last_checked_at,
        "last_success_at": last_success_at,
        "item_count": item_count,
        "auth": auth or {"status": "not_applicable", "secret_names": [], "secret_values_exposed": False},
        "safe_message": safe_message,
        "warnings": warnings or [],
    }


def _safe_source_error(source_id: str, exc: Exception, checked_at: str) -> dict[str, Any]:
    return _source(
        id=source_id,
        kind="internal",
        status="error",
        freshness="not_verified",
        last_checked_at=checked_at,
        safe_message=f"{source_id} health check failed: {exc.__class__.__name__}",
        warnings=[str(exc)],
    )


def get_source_health(*, refresh: bool = False) -> dict[str, Any]:
    """Return source availability/freshness without exposing raw secrets."""

    global _SOURCE_HEALTH_CACHE
    if not refresh and _SOURCE_HEALTH_CACHE is not None:
        cached_at, cached_payload = _SOURCE_HEALTH_CACHE
        if monotonic() - cached_at < _CACHE_TTL_SECONDS:
            return cached_payload

    checked_at = _now()
    sources: list[dict[str, Any]] = []
    state_counts: dict[str, Any] = {}

    try:
        if refresh:
            state_path, state = state_index.sync_state()
        else:
            state_path = state_index.state_path()
            state = state_index.load_state()
        summary = state_index.state_summary(state)
        counts = summary.get("counts") if isinstance(summary.get("counts"), dict) else {}
        state_counts = counts
        last_sync = state.get("last_sync_at") if isinstance(state, dict) else None
        sources.append(
            _source(
                id="zab_inventory",
                kind="inventory",
                status="ok" if state else "not_verified",
                freshness="fresh" if refresh else "local",
                last_checked_at=checked_at,
                last_success_at=last_sync or _file_mtime(state_path),
                item_count=sum(int(v or 0) for v in counts.values()) if counts else 0,
                safe_message=f"Inventory state readable at {state_path}.",
            )
        )
    except Exception as exc:  # pragma: no cover - defensive contract boundary
        sources.append(_safe_source_error("zab_inventory", exc, checked_at))

    try:
        task_sources = agent_context.task_sources_status()
        rows = task_sources.get("sources") if isinstance(task_sources.get("sources"), list) else []
        cache_present = bool(task_sources.get("cache_present"))
        token_missing = [str(row.get("id")) for row in rows if isinstance(row, dict) and not row.get("token_present")]
        status = "local_ok" if cache_present else "not_verified"
        if rows and len(token_missing) == len(rows):
            status = "needs_auth"
        sources.append(
            _source(
                id="task_sources",
                kind="tasks",
                status=status,
                freshness="local" if cache_present else "not_verified",
                last_checked_at=checked_at,
                last_success_at=task_sources.get("cache_generated_at_utc"),
                item_count=len(rows),
                auth={
                    "status": "configured" if rows and len(token_missing) < len(rows) else "needs_auth",
                    "secret_names": [str(row.get("env_token")) for row in rows if isinstance(row, dict) and row.get("env_token")],
                    "secret_values_exposed": False,
                },
                safe_message="Task sources inspected from config and local cache.",
                warnings=[f"missing token for {sid}" for sid in token_missing],
            )
        )
    except Exception as exc:  # pragma: no cover - defensive contract boundary
        sources.append(_safe_source_error("task_sources", exc, checked_at))

    try:
        tasks = agent_context.tasks_list(limit=1, refresh=refresh)
        sources.append(
            _source(
                id="tasks_cache",
                kind="tasks",
                status="local_ok" if tasks.get("cache_present") else "not_verified",
                freshness="fresh" if tasks.get("refreshed") else ("local" if tasks.get("cache_present") else "not_verified"),
                last_checked_at=checked_at,
                last_success_at=tasks.get("cache_generated_at_utc"),
                item_count=int(tasks.get("total") or 0),
                safe_message="Unified tasks are read from cache by default; refresh performs explicit external reads.",
                warnings=[] if tasks.get("cache_present") else [str(tasks.get("message") or "No local tasks cache.")],
            )
        )
    except Exception as exc:  # pragma: no cover - defensive contract boundary
        sources.append(_safe_source_error("tasks_cache", exc, checked_at))

    try:
        memory = fetch_memory_status()
        sources.append(
            _source(
                id="postgres_memory",
                kind="memory",
                status="ok" if memory.get("connected") else ("needs_auth" if memory.get("configured") else "not_verified"),
                freshness="live" if memory.get("connected") else "not_verified",
                last_checked_at=checked_at,
                last_success_at=checked_at if memory.get("connected") else None,
                item_count=memory.get("document_count"),
                auth={"status": "configured" if memory.get("configured") else "missing", "secret_names": ["DATABASE_URL"], "secret_values_exposed": False},
                safe_message="Postgres memory status checked without returning connection strings.",
                warnings=[str(memory.get("error"))] if memory.get("error") else [],
            )
        )
    except Exception as exc:  # pragma: no cover - defensive contract boundary
        sources.append(_safe_source_error("postgres_memory", exc, checked_at))

    try:
        if refresh:
            security = agent_context.security_status()
        else:
            tracked = tracked_env_names_for_security()
            scan = scan_secret_presence(tracked, env_files=security_env_paths_resolved())
            security = {
                "tracked_env_count": len(tracked),
                "tracked_env_present": [row["name"] for row in scan["variables"] if row.get("present")],
                "tracked_env_missing": [row["name"] for row in scan["variables"] if not row.get("present")],
            }
        sources.append(
            _source(
                id="secret_readiness",
                kind="security",
                status="ok",
                freshness="local",
                last_checked_at=checked_at,
                last_success_at=checked_at,
                item_count=int(security.get("tracked_env_count") or 0),
                auth={"status": "masked", "secret_names": list(security.get("tracked_env_present") or []), "secret_values_exposed": False},
                safe_message="Security status reports secret presence only; raw values are never returned.",
                warnings=[f"missing {name}" for name in list(security.get("tracked_env_missing") or [])[:10]],
            )
        )
    except Exception as exc:  # pragma: no cover - defensive contract boundary
        sources.append(_safe_source_error("secret_readiness", exc, checked_at))

    try:
        if refresh:
            connectors = agent_context.connectors_list(limit=200)
            connectors_count = len(connectors.get("connectors") if isinstance(connectors.get("connectors"), list) else [])
            message = "Connector catalog is readable from normalized Zab sources."
        else:
            connectors_count = int(state_counts.get("connectors") or 0)
            message = "Connector catalog count read from current inventory summary."
        sources.append(
            _source(
                id="connectors_catalog",
                kind="connectors",
                status="local_ok",
                freshness="local",
                last_checked_at=checked_at,
                last_success_at=checked_at,
                item_count=connectors_count,
                safe_message=message,
            )
        )
    except Exception as exc:  # pragma: no cover - defensive contract boundary
        sources.append(_safe_source_error("connectors_catalog", exc, checked_at))

    try:
        doc = mcp_registry.load_registry_document()
        servers = doc.get("servers") if isinstance(doc.get("servers"), dict) else {}
        sources.append(
            _source(
                id="mcp_registry",
                kind="mcp",
                status="local_ok" if servers else "not_verified",
                freshness="local" if servers else "not_verified",
                last_checked_at=checked_at,
                last_success_at=doc.get("updated_at") or _file_mtime(mcp_registry.registry_path()),
                item_count=len(servers),
                safe_message="MCP registry metadata is readable.",
            )
        )
    except Exception as exc:  # pragma: no cover - defensive contract boundary
        sources.append(_safe_source_error("mcp_registry", exc, checked_at))

    try:
        skills_root, skills_source = resolve_skills_root()
        sources.append(
            _source(
                id="skills_root",
                kind="skills",
                status="ok" if skills_root.exists() else "error",
                freshness="local",
                last_checked_at=checked_at,
                last_success_at=checked_at if skills_root.exists() else None,
                item_count=None,
                safe_message=f"Skills root resolved from {skills_source}: {skills_root}.",
            )
        )
    except Exception as exc:  # pragma: no cover - defensive contract boundary
        sources.append(_safe_source_error("skills_root", exc, checked_at))

    try:
        if refresh:
            projects_count = len(discover_projects())
            last_success_at = checked_at if projects_count else None
        else:
            projects_count = int(state_counts.get("projects") or 0)
            last_success_at = checked_at if projects_count else None
        sources.append(
            _source(
                id="project_workspaces",
                kind="workspace",
                status="local_ok" if projects_count else "not_verified",
                freshness="local",
                last_checked_at=checked_at,
                last_success_at=last_success_at,
                item_count=projects_count,
                safe_message=(
                    "Project workspaces read from current inventory summary."
                    if not refresh
                    else "Project workspaces discovered from configured projects_roots."
                ),
            )
        )
    except Exception as exc:  # pragma: no cover - defensive contract boundary
        sources.append(_safe_source_error("project_workspaces", exc, checked_at))

    status_counts: dict[str, int] = {}
    for row in sources:
        status_counts[str(row.get("status"))] = status_counts.get(str(row.get("status")), 0) + 1

    payload = {
        "contract": "source-health",
        "contract_version": "1.0",
        "generated_at_utc": checked_at,
        "refresh": refresh,
        "data_dir": str(data_dir().resolve()),
        "status_counts": status_counts,
        "sources": sources,
    }
    if not refresh:
        _SOURCE_HEALTH_CACHE = (monotonic(), payload)
    return payload
