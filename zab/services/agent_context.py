"""Agent-oriented context contract for zab CLI/API/MCP."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from zab.paths import config_dir, data_dir, resolve_skills_root
from zab.services import jobs, obsidian_vault, postgres_store as local_db, state_index
from zab.services.capabilities import get_capabilities
from zab.services.feature_catalog import agent_guide, catalog
from zab.services.memory_db import fetch_status as fetch_memory_status
from zab.services.secrets_scan import scan_secret_presence
from zab.services.workspace_projects import discover_projects
from zab.user_config import load_user_config, tracked_env_names_for_security, user_config_path


SAFE_AGENT_ACTIONS = {
    "capabilities": "lecture_sure",
    "bootstrap": "lecture_sure",
    "source_health": "lecture_sure",
    "research": "lecture_sure",
    "search": "lecture_sure",
    "inspect": "lecture_sure",
    "skills_manifest": "lecture_sure",
    "context_pack": "lecture_sure",
    "project_handoff": "lecture_sure",
    "memory_status": "lecture_sure",
    "security_status": "lecture_sure",
}


def audit_log_path() -> Path:
    return data_dir() / "audit.log"


def append_audit_event(action: str, meta: dict[str, Any] | None = None) -> Path:
    """Append metadata-only audit event. Secret-looking fields are deliberately dropped."""

    clean_meta: dict[str, Any] = {}
    for key, value in (meta or {}).items():
        lk = str(key).lower()
        if any(token in lk for token in ("secret", "token", "key", "password")):
            continue
        clean_meta[str(key)] = value
    payload = {
        "at": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "risk": SAFE_AGENT_ACTIONS.get(action, "unknown"),
        "meta": clean_meta,
    }
    path = audit_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def security_status() -> dict[str, Any]:
    cfg = load_user_config()
    tracked = tracked_env_names_for_security()
    scan = scan_secret_presence(tracked)
    present = [row["name"] for row in scan["variables"] if row.get("present")]
    missing = [row["name"] for row in scan["variables"] if not row.get("present")]
    reports = jobs.list_security_reports()
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "tracked_env_count": len(tracked),
        "tracked_env_present": present,
        "tracked_env_missing": missing,
        "env_files_scanned": scan["env_files_scanned"],
        "env_files_with_tracked_keys": scan["env_files_with_tracked_keys"],
        "variables": scan["variables"],
        "groups": scan["groups"],
        "reports": reports[:10],
        "latest_report": reports[0] if reports else None,
        "config_path": str(user_config_path().resolve()),
        "audit_log_path": str(audit_log_path().resolve()),
        "policy": {
            "secrets": "never_print_raw_values",
            "secret_values": "never_returned_by_security_status",
            "state_yaml": "generated_cache",
            "user_intent_files": ["~/.config/zab/config.yaml", "~/.config/zab/overrides.yaml"],
        },
        "agent_instructions": [
            "Use this endpoint to locate which known .env file contains a needed key, but never print the value.",
            "If a variable lists aliases, source the file containing either the canonical key or alias and map it in-memory only for the current command.",
            "Prefer connector-specific read-only commands unless the user explicitly asks for a mutation.",
        ],
        "configured_projects_roots": cfg.get("projects_roots") if isinstance(cfg.get("projects_roots"), list) else [],
    }
    append_audit_event("security_status", {"tracked_env_count": len(tracked)})
    return payload


def agent_bootstrap(*, refresh: bool = False) -> dict[str, Any]:
    if refresh:
        path, state = state_index.sync_state()
    else:
        path = state_index.state_path()
        state = state_index.load_state()
        if state.get("version") != state_index.STATE_VERSION:
            path, state = state_index.sync_state()
    sr_path, sr_source = resolve_skills_root()
    summary = state_index.state_summary(state)
    memory = fetch_memory_status()
    guide = agent_guide()
    security = security_status()
    projects = state.get("projects") if isinstance(state.get("projects"), dict) else {}
    security_groups_summary = {
        key: {
            "ready": bool(value.get("ready")),
            "present_count": len(value.get("present") or []),
            "missing_count": len(value.get("missing") or []),
        }
        for key, value in (security.get("groups") or {}).items()
        if isinstance(value, dict)
    }
    payload = {
        "product": "zab",
        "contract": "agent-bootstrap",
        "contract_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "paths": {
            "skills_root": str(sr_path),
            "skills_root_source": sr_source,
            "config_dir": str(config_dir().resolve()),
            "data_dir": str(data_dir().resolve()),
            "state_yaml": str(path.resolve()),
            "config_yaml": str(user_config_path().resolve()),
            "overrides_yaml": str(state_index.overrides_path().resolve()),
        },
        "state": summary,
        "sections": list(summary.get("counts", {}).keys()),
        "commands": {
            "refresh": "zab sync --json",
            "search": "zab search <query> --json",
            "inspect": "zab inspect <section> <id> --json",
            "skills_manifest": "zab agent skills --json",
            "handoff": "zab agent handoff --project <name-or-path> --json",
            "context_pack": "zab context-pack --query <query> --stdout",
            "security": "zab security status --json",
        },
        "quick_start": [
            "Use `zab agent skills --json` to list available skills across configured repos and projects.",
            "Use `zab tools list --json` to inspect actionable tools, their implementations and linked skills.",
            "Use `zab search <topic> --json` before scanning files manually.",
            "Use `zab security status --json` before any connector requiring secrets; it returns presence and paths, never values.",
            "Use `zab agent handoff --project <name> --json` for project-specific context.",
            "Use `zab context-pack --query <topic> --stdout` when a compact prompt pack is needed.",
        ],
        "context_summary": {
            "top_projects": [
                {
                    "name": (p.get("name") if isinstance(p, dict) else None),
                    "org": (p.get("org") if isinstance(p, dict) else None),
                    "path": (p.get("path") if isinstance(p, dict) else None),
                    "skills_count": len(p.get("skills") or []) if isinstance(p, dict) else 0,
                }
                for p in list(projects.values())[:12]
                if isinstance(p, dict)
            ],
            "security_groups": security_groups_summary,
        },
        "features_count": len(catalog().get("features", [])),
        "agent_guide": guide,
        "memory": {
            "configured": bool(memory.get("configured")),
            "connected": bool(memory.get("connected")),
            "psycopg_available": bool(memory.get("psycopg_available")),
            "document_count": memory.get("document_count"),
            "error": memory.get("error"),
        },
        "installed_agents": [
            {"id": key, **value}
            for key, value in (state.get("code_tools") or {}).items()
            if isinstance(value, dict) and value.get("installed") and value.get("kind") == "agent"
        ],
        "safety": {
            "default_mode": "read_context_before_acting",
            "secrets": "do_not_print_or_infer_raw_secret_values",
            "secret_presence": "use `zab security status --json`; it scans known .env files and aliases",
            "write_files": "only_after_task_requires_it",
            "generated_cache": "~/.local/share/zab/state.yaml",
        },
    }
    append_audit_event("bootstrap", {"refresh": refresh})
    return payload


def _iter_state_rows(state: dict[str, Any], sections: list[str] | None = None) -> list[dict[str, Any]]:
    wanted = sections or [
        "skills",
        "connectors",
        "code_tools",
        "tools",
        "models",
        "memory_sources",
        "knowledge_sources",
        "subscriptions",
        "projects",
        "orgs",
    ]
    rows: list[dict[str, Any]] = []
    for section in wanted:
        raw = state.get(section)
        if not isinstance(raw, dict):
            continue
        for key, value in raw.items():
            if isinstance(value, dict):
                rows.append({"section": section, "key": str(key), **value})
    return rows


def _haystack(row: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, value in row.items():
        if key.startswith("_"):
            continue
        parts.append(_flatten_haystack_value(value))
    return " ".join(parts).lower()


def _flatten_haystack_value(value: Any) -> str:
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return " ".join(_flatten_haystack_value(x) for x in value)
    if isinstance(value, dict):
        return " ".join(_flatten_haystack_value(x) for x in value.values())
    return ""


def search(query: str, *, limit: int = 20, sections: list[str] | None = None, refresh: bool = False) -> dict[str, Any]:
    q = query.strip()
    if refresh:
        state_index.sync_state()
    state = state_index.load_state()
    terms = [t for t in q.lower().split() if t]
    candidate_rows: list[dict[str, Any]] = []
    try:
        has_cached_state = local_db.has_state()
    except Exception:
        has_cached_state = False
    if has_cached_state:
        try:
            candidate_rows.extend(local_db.search_state(q, sections=sections, limit=100))
        except Exception:
            candidate_rows = []
    candidate_rows.extend(_iter_state_rows(state, sections))
    seen: set[tuple[str, str]] = set()
    results: list[dict[str, Any]] = []
    for row in candidate_rows:
        identity = (str(row.get("section") or ""), str(row.get("key") or row.get("id") or row.get("path") or ""))
        if identity in seen:
            continue
        seen.add(identity)
        hay = _haystack(row)
        matched_terms = [term for term in terms if term in hay]
        missing_terms = [term for term in terms if term not in hay]
        if terms and not matched_terms:
            continue
        score = 0
        reasons: list[str] = []
        if not terms:
            score = 1
            reasons.append("unfiltered")
        elif q.lower() in hay:
            score += 15
            reasons.append("phrase")
        if terms and not missing_terms:
            score += 10
            reasons.append("all terms")
        if matched_terms:
            score += 3 * len(matched_terms)
        for field in ("key", "id", "display_name", "name", "description", "org", "path", "provider", "kind"):
            val = str(row.get(field) or "").lower()
            if not val:
                continue
            hits = [term for term in terms if term in val]
            if hits:
                score += 5 if field in ("key", "id", "display_name", "name") else 2
                reasons.append(f"{field}: {', '.join(hits)}")
        tags = [str(x).lower() for x in row.get("tags") or []]
        tag_hits = [term for term in terms if term in tags]
        if tag_hits:
            score += 3
            reasons.append(f"tags: {', '.join(tag_hits)}")
        item = dict(row)
        item["score"] = score
        item["match_reasons"] = reasons or ["content"]
        item["terms_matched"] = matched_terms
        item["terms_missing"] = missing_terms
        item["match_type"] = "exact_or_complete" if terms and not missing_terms else ("partial" if terms else "unfiltered")
        results.append(item)
    results.sort(key=lambda x: (-int(x.get("score") or 0), str(x.get("section")), str(x.get("key"))))
    capped = max(1, min(100, limit))
    append_audit_event("search", {"query": q, "limit": capped})
    return {
        "query": q,
        "limit": capped,
        "total": len(results),
        "data": results[:capped],
    }


def skills_manifest(
    *,
    org: str | None = None,
    project: str | None = None,
    query: str | None = None,
    limit: int = 200,
    refresh: bool = False,
) -> dict[str, Any]:
    """Compact, agent-facing list of available skills across repos/projects."""

    if refresh:
        state_index.sync_state()
    state = state_index.load_state()
    org_n = org.strip().lower() if org else None
    project_n = project.strip().lower() if project else None
    query_n = query.strip().lower() if query else None
    rows: list[dict[str, Any]] = []
    for row in _iter_state_rows(state, ["skills"]):
        rs = str(row.get("registry_status") or "").lower()
        if rs in ("candidate", "ignored", "conflict"):
            continue
        if org_n and str(row.get("org") or "").lower() != org_n:
            continue
        if project_n:
            hay_project = " ".join(str(row.get(k) or "") for k in ("project", "path", "source")).lower()
            if project_n not in hay_project:
                continue
        if query_n and query_n not in _haystack(row):
            continue
        key = str(row.get("key") or "")
        scope = "project" if str(row.get("source") or "").lower() == "workspace" else "global"
        rows.append(
            {
                "key": key,
                "id": row.get("id") or key,
                "scope": scope,
                "org": row.get("org"),
                "source": row.get("source"),
                "project": row.get("project"),
                "description": row.get("description"),
                "tags": row.get("tags") or [],
                "path": row.get("path"),
                "uses_connectors": row.get("uses_connectors") or [],
                "uses_models": row.get("uses_models") or [],
                "uses_code_tools": row.get("uses_code_tools") or [],
                "activation": {
                    "inspect_command": f"zab inspect skills {key} --json",
                    "mcp_inspect": {"tool": "inspect", "arguments": {"section": "skills", "key": key}},
                },
            }
        )
    rows.sort(key=lambda x: (str(x.get("org") or ""), str(x.get("id") or "")))
    capped = max(1, min(500, limit))
    append_audit_event("skills_manifest", {"limit": capped})
    return {
        "contract": "skills-manifest",
        "contract_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "filters": {"org": org, "project": project, "query": query},
        "total": len(rows),
        "skills": rows[:capped],
        "usage": {
            "refresh_command": "zab sync --json",
            "search_command": "zab search <topic> --section skills --json",
            "inspect_command": "zab inspect skills <key> --json",
            "mcp_tools": ["skills_manifest", "search", "inspect"],
        },
    }


def _project_matches(project: dict[str, Any], selector: str) -> bool:
    return _project_match_score(project, selector) > 0


def _project_match_score(project: dict[str, Any], selector: str) -> int:
    s = selector.strip().lower()
    if not s:
        return 0
    name = str(project.get("name") or "").lower()
    path = str(project.get("path") or "").lower()
    path_name = Path(path).name.lower() if path else ""
    org = str(project.get("org") or "").lower()
    workspace_parent = str(project.get("workspace_parent") or "").lower()
    aliases = [str(x).lower() for x in project.get("aliases") or []]
    score = 0
    if s == name:
        score = max(score, 100)
    if s == path_name:
        score = max(score, 95)
    if path and s == path:
        score = max(score, 90)
    if s in aliases:
        score = max(score, 88)
    if s == org:
        score = max(score, 70)
    if s == workspace_parent:
        score = max(score, 60)
    for value, points in ((name, 45), (path_name, 42), (path, 35), (workspace_parent, 28), (org, 22)):
        if value and s in value:
            score = max(score, points)
    if any(s in alias for alias in aliases):
        score = max(score, 40)
    return score


def project_handoff(project: str, *, limit: int = 80) -> dict[str, Any]:
    selector = project.strip()
    projects = discover_projects()
    matches = sorted(
        [p for p in projects if _project_matches(p, selector)],
        key=lambda p: (-_project_match_score(p, selector), str(p.get("path") or "")),
    )
    if not matches:
        return {
            "found": False,
            "selector": selector,
            "available_projects": [
                {
                    "name": p.get("name"),
                    "path": p.get("path"),
                    "org": p.get("org"),
                    "detection_reasons": p.get("detection_reasons") or [],
                }
                for p in projects[:50]
            ],
        }
    selected = matches[0]
    project_path = str(selected.get("path") or "")
    org = str(selected.get("org") or "") or None
    state = state_index.load_state()
    skills = []
    for row in _iter_state_rows(state, ["skills"]):
        path = str(row.get("path") or "")
        if project_path and path.startswith(project_path):
            skills.append(row)
        elif org and str(row.get("org") or "").lower() == org.lower():
            skills.append(row)
    connectors = state.get("connectors") if isinstance(state.get("connectors"), dict) else {}
    orgs = state.get("orgs") if isinstance(state.get("orgs"), dict) else {}
    org_context = orgs.get(org) if org and isinstance(orgs.get(org), dict) else None
    related_projects = [
        {
            "name": p.get("name"),
            "path": p.get("path"),
            "workspace_parent": p.get("workspace_parent"),
            "skills_count": len(p.get("skills") or []),
        }
        for p in projects
        if org and str(p.get("org") or "").lower() == org.lower()
    ][:20]
    security = security_status()
    pack_path, pack_text = state_index.build_context_pack(
        org=org,
        project=selector,
        limit=limit,
        include=["orgs", "projects", "skills", "connectors", "code_tools", "tools", "memory_sources", "knowledge_sources"],
        query=selector,
    )
    payload = {
        "found": True,
        "selector": selector,
        "match": {
            "score": _project_match_score(selected, selector),
            "candidates": [
                {
                    "name": p.get("name"),
                    "path": p.get("path"),
                    "org": p.get("org"),
                    "score": _project_match_score(p, selector),
                }
                for p in matches[:5]
            ],
        },
        "project": selected,
        "org_context": org_context,
        "related_projects": related_projects,
        "skills": skills[:limit],
        "connectors_summary": {
            key: {
                "display_name": value.get("display_name"),
                "forms_count": len(value.get("forms") or []),
                "tags": value.get("tags") or [],
            }
            for key, value in connectors.items()
            if isinstance(value, dict)
        },
        "security": {
            "latest_report": security.get("latest_report"),
            "tracked_env_count": security.get("tracked_env_count"),
            "tracked_env_missing": security.get("tracked_env_missing"),
        },
        "context_pack": {"path": str(pack_path), "bytes": len(pack_text.encode("utf-8"))},
        "recommended_next_commands": [
            "zab sync --json",
            f"zab search {selector!r} --json",
            f"zab context-pack --project {selector!r} --stdout",
            "zab security status --json",
        ],
    }
    append_audit_event("project_handoff", {"project": selector, "found": True})
    return payload


def _json_cache(filename: str) -> dict[str, Any] | None:
    path = data_dir() / filename
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def connectors_list(
    *,
    q: str = "",
    kind: str | None = None,
    tag: str | None = None,
    limit: int = 50,
    include_details: bool = False,
) -> dict[str, Any]:
    """Agent-facing connector catalog from MCP, API proxies and Composio accounts."""

    from zab.services import connectors_aggregate

    capped = max(1, min(200, int(limit or 50)))
    payload = connectors_aggregate.list_connectors(page=1, limit=capped, q=q or "", kind=kind, tag=tag)
    rows = list(payload.get("data") or [])
    if include_details:
        detailed: list[dict[str, Any]] = []
        for row in rows:
            slug = str(row.get("id") or "")
            detail = connectors_aggregate.get_connector(slug) if slug else None
            detailed.append(detail or row)
        rows = detailed
    result = {
        "contract": "zab-connectors-catalog",
        "contract_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "filters": {"q": q, "kind": kind, "tag": tag, "include_details": include_details},
        "connectors": rows,
        "pagination": payload.get("pagination") or {},
        "usage": {
            "inspect_tool": "connector_status",
            "search_related_skills_tool": "search(section='skills')",
            "secrets_policy": "raw secrets are never returned; use security_status for presence/path hints",
        },
    }
    append_audit_event("connectors_list", {"q": q, "kind": kind, "tag": tag, "limit": capped})
    return result


def connector_status(slug: str, *, include_checks: bool = True) -> dict[str, Any]:
    """Return one connector detail plus optional read-only health checks."""

    from zab.services import connectors_aggregate, connectors_check

    key = (slug or "").strip()
    detail = connectors_aggregate.get_connector(key) if key else None
    checks = connectors_check.check_connector_payload(key) if key and include_checks else None
    result = {
        "contract": "zab-connector-status",
        "contract_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "found": bool(detail),
        "slug": key,
        "connector": detail,
        "checks": checks,
    }
    append_audit_event("connector_status", {"slug": key, "include_checks": include_checks, "found": bool(detail)})
    return result


def task_sources_status() -> dict[str, Any]:
    """List configured PM task sources with cache status and token presence only."""

    from zab.services.tasks_inbox import _resolve_token_for_entry  # noqa: PLC2701 - agent-safe metadata only.
    from zab.user_config import task_sources_from_user_config

    sources_cfg, parse_errors = task_sources_from_user_config()
    cache = _json_cache("tasks_cache.json") or {}
    cached_sources_raw = cache.get("sources")
    cached_sources = cached_sources_raw if isinstance(cached_sources_raw, list) else []
    cache_sources = {
        str(src.get("id")): src
        for src in cached_sources
        if isinstance(src, dict) and src.get("id")
    }
    rows: list[dict[str, Any]] = []
    for entry in sources_cfg:
        sid = str(entry.get("id") or "")
        cached = cache_sources.get(sid) or {}
        try:
            token_present = bool(_resolve_token_for_entry(entry)[0])
        except Exception:
            token_present = False
        rows.append(
            {
                "id": sid,
                "label": entry.get("label"),
                "backend": entry.get("backend"),
                "url": entry.get("url"),
                "local_project_path": entry.get("local_project_path"),
                "routing_doc": entry.get("routing_doc"),
                "mcp_hint": entry.get("mcp_hint"),
                "env_token": entry.get("env_token"),
                "token_present": token_present,
                "cache_status": cached.get("status"),
                "cache_reason": cached.get("reason"),
                "cached_items_count": len(cached.get("items") or []) if isinstance(cached, dict) else 0,
            }
        )
    append_audit_event("task_sources_status", {"sources": len(rows)})
    return {
        "contract": "zab-task-sources-status",
        "contract_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "parse_errors": parse_errors,
        "cache_present": bool(cache),
        "cache_generated_at_utc": cache.get("generated_at_utc") if cache else None,
        "sources": rows,
    }


def tasks_list(
    *,
    q: str = "",
    source: str | None = None,
    status: str | None = None,
    limit: int = 50,
    refresh: bool = False,
) -> dict[str, Any]:
    """List unified tasks. By default reads local cache only; refresh=True performs external reads."""

    from zab.services.tasks_inbox import sync_tasks_inbox

    cache = sync_tasks_inbox() if refresh else _json_cache("tasks_cache.json")
    if cache is None:
        return {
            "contract": "zab-tasks-list",
            "contract_version": "1.0",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "cache_present": False,
            "tasks": [],
            "total": 0,
            "message": "No local tasks cache. Call tasks_sync or run `zab tasks sync` to refresh from external PM backends.",
        }
    qn = (q or "").strip().lower()
    sn = (source or "").strip().lower()
    stn = (status or "").strip().lower()
    rows: list[dict[str, Any]] = []
    for item in cache.get("all_tasks") or []:
        if not isinstance(item, dict):
            continue
        hay = " ".join(str(item.get(k) or "") for k in ("identifier", "display_identifier", "title", "source_label", "state", "url")).lower()
        if qn and qn not in hay:
            continue
        if sn and sn not in str(item.get("source_label") or "").lower():
            continue
        if stn and stn not in str(item.get("state") or "").lower():
            continue
        rows.append(item)
    capped = max(1, min(200, int(limit or 50)))
    append_audit_event("tasks_list", {"q": q, "source": source, "status": status, "limit": capped, "refresh": refresh})
    return {
        "contract": "zab-tasks-list",
        "contract_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "cache_present": True,
        "cache_generated_at_utc": cache.get("generated_at_utc"),
        "refreshed": refresh,
        "filters": {"q": q, "source": source, "status": status},
        "total": len(rows),
        "tasks": rows[:capped],
        "sources": cache.get("sources") or [],
        "parse_errors": cache.get("parse_errors") or [],
    }


def tasks_sync() -> dict[str, Any]:
    """Refresh task cache from configured PM backends (external read only)."""

    from zab.services.tasks_inbox import sync_tasks_inbox

    result = sync_tasks_inbox()
    append_audit_event("tasks_sync", {"total_count": result.get("total_count")})
    return result


def task_source_check(source_id: str) -> dict[str, Any]:
    """Check one configured task source and update its cached block when possible."""

    from zab.services.tasks_inbox import check_single_source

    sid = (source_id or "").strip()
    try:
        result = check_single_source(sid)
    except KeyError:
        result = {"ok": False, "error": f"unknown task source: {sid}", "source_id": sid}
    append_audit_event("task_source_check", {"source_id": sid})
    return result


def channels_list(*, include_actions: bool = True, refresh: bool = False, limit: int = 50) -> dict[str, Any]:
    """List communication channels. By default reads config/cache only; refresh=True fetches channels."""

    from zab.services.communication_channels import load_channels_config, sync_communication_channels

    cache = sync_communication_channels() if refresh else _json_cache("channels_cache.json")
    channels = (cache.get("channels") if isinstance(cache, dict) else None) or load_channels_config()
    actions = (cache.get("action_items") if isinstance(cache, dict) else []) if include_actions else []
    capped = max(1, min(200, int(limit or 50)))
    append_audit_event("channels_list", {"refresh": refresh, "include_actions": include_actions, "limit": capped})
    return {
        "contract": "zab-channels-list",
        "contract_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "cache_present": bool(cache),
        "cache_generated_at_utc": cache.get("generated_at_utc") if isinstance(cache, dict) else None,
        "refreshed": refresh,
        "channels": channels,
        "action_items": list(actions or [])[:capped],
        "total_actions_count": len(actions or []),
    }


def composio_connections(
    *,
    toolkit: str | None = None,
    active_only: bool = True,
    resolve_identities: bool = False,
) -> dict[str, Any]:
    """List Composio connected accounts through Zab's safer CLI wrapper."""

    from zab.services import composio_connectors

    accounts = composio_connectors.fetch_connections_via_cli_enriched(
        toolkit=toolkit,
        active_only=active_only,
        resolve_identities=resolve_identities,
    )
    append_audit_event("composio_connections", {"toolkit": toolkit, "active_only": active_only, "resolve_identities": resolve_identities})
    return {
        "contract": "zab-composio-connections",
        "contract_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "filters": {"toolkit": toolkit, "active_only": active_only, "resolve_identities": resolve_identities},
        "total": len(accounts),
        "connections": accounts,
        "repair_hint": "If no active account is returned for a needed toolkit, run `zab composio link <toolkit>` or inspect `zab composio whoami --toolkit <toolkit> --json`.",
    }


def memory_status() -> dict[str, Any]:
    from zab.services.memory_db import fetch_status

    result = fetch_status()
    append_audit_event("memory_status", {"connected": result.get("connected")})
    return result


def memory_search(query: str, *, limit: int = 10, source: str | None = None, wing: str | None = None) -> dict[str, Any]:
    from zab.services.memory_db import search_memory

    rows = search_memory(query, limit=limit, source=source, wing=wing)
    append_audit_event("memory_search", {"query": query, "limit": limit, "source": source, "wing": wing})
    return {
        "contract": "zab-memory-search",
        "contract_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "total": len(rows),
        "results": rows,
    }


def source_health(*, refresh: bool = False) -> dict[str, Any]:
    from zab.services.source_health import get_source_health

    result = get_source_health(refresh=refresh)
    append_audit_event("source_health", {"refresh": refresh, "sources": len(result.get("sources") or [])})
    return result


def research(
    query: str,
    *,
    project: str | None = None,
    mode: str = "plan",
    max_tokens: int = 6000,
    refresh: bool = False,
) -> dict[str, Any]:
    from zab.services.research_engine import research_from_params

    result = research_from_params(query, project=project, mode=mode, max_tokens=max_tokens, refresh=refresh)
    append_audit_event("research", {"mode": mode, "project": project, "refresh": refresh})
    return result


def cli_auth_check(only: list[str] | None = None) -> dict[str, Any]:
    from zab.services.cli_check import run_cli_checks

    result = run_cli_checks(only=only)
    append_audit_event("cli_auth_check", {"only": only or [], "total": result.get("total")})
    return result


def system_health_check() -> dict[str, Any]:
    from zab.services.system_check import run_system_check

    result = run_system_check()
    append_audit_event("system_health_check", {"percentage": result.get("percentage")})
    return result


def mcp_tools() -> list[dict[str, Any]]:
    """Return MCP tool descriptors for Zab's read-first stdio server."""

    return [
        {
            "name": "capabilities",
            "description": "Retourne le capability manifest AI-native de Zab : parité Core, CLI, MCP, API et UI.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "agent_bootstrap",
            "description": "Contrat de bootstrap complet pour agents : chemins, commandes, résumé d'inventaire, sécurité et sources disponibles.",
            "inputSchema": {
                "type": "object",
                "properties": {"refresh": {"type": "boolean", "default": False}},
            },
        },
        {
            "name": "source_health",
            "description": "Source Health unifié : disponibilité, fraîcheur, auth masquée et warnings pour les sources Zab.",
            "inputSchema": {
                "type": "object",
                "properties": {"refresh": {"type": "boolean", "default": False}},
            },
        },
        {
            "name": "research",
            "description": "Construit un research packet déterministe, sourcé et freshness-aware pour agents et humains.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "project": {"type": "string"},
                    "mode": {"type": "string", "default": "plan", "description": "plan|debug|review|briefing|handoff"},
                    "max_tokens": {"type": "integer", "default": 6000},
                    "refresh": {"type": "boolean", "default": False},
                },
                "required": ["query"],
            },
        },
        {
            "name": "project_handoff",
            "description": "Compose un pack de contexte projet + skills/connecteurs associés pour un agent.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "limit": {"type": "integer", "default": 80},
                },
                "required": ["project"],
            },
        },
        {
            "name": "security_status",
            "description": "Statut de présence des secrets/env vars et chemins de fichiers, sans jamais retourner de valeur brute.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "memory_status",
            "description": "Statut de la mémoire Postgres/Hermes connue par Zab.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "memory_search",
            "description": "Recherche dans la mémoire Postgres unifiée Zab, si configurée.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                    "source": {"type": "string"},
                    "wing": {"type": "string"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "connectors_list",
            "description": "Liste les connecteurs exposés à Zab : MCP, proxies API et comptes Composio. Surface principale pour découvrir les connecteurs actionnables.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "q": {"type": "string"},
                    "kind": {"type": "string", "description": "mcp|api|composio"},
                    "tag": {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                    "include_details": {"type": "boolean", "default": False},
                },
            },
        },
        {
            "name": "connector_status",
            "description": "Détail d'un connecteur + checks read-only de santé/disponibilité.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "slug": {"type": "string"},
                    "include_checks": {"type": "boolean", "default": True},
                },
                "required": ["slug"],
            },
        },
        {
            "name": "composio_connections",
            "description": "Liste les comptes Composio connectés par toolkit, avec option de résolution d'identité. Ne retourne pas de secrets.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "toolkit": {"type": "string", "description": "gmail, googlecalendar, notion, slack, ..."},
                    "active_only": {"type": "boolean", "default": True},
                    "resolve_identities": {"type": "boolean", "default": False},
                },
            },
        },
        {
            "name": "task_sources_status",
            "description": "Liste les sources de tâches configurées (GitLab, Linear, Notion, GitHub) avec statut cache et présence de token masquée.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "tasks_list",
            "description": "Liste les tâches unifiées depuis le cache local par défaut. Mettre refresh=true pour relire les backends externes.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "q": {"type": "string"},
                    "source": {"type": "string"},
                    "status": {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                    "refresh": {"type": "boolean", "default": False},
                },
            },
        },
        {
            "name": "tasks_sync",
            "description": "Synchronise le cache de tâches depuis les backends externes configurés. Lecture externe uniquement, pas de mutation distante.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "task_source_check",
            "description": "Vérifie une source de tâches spécifique par id et met à jour son bloc dans le cache local.",
            "inputSchema": {
                "type": "object",
                "properties": {"source_id": {"type": "string"}},
                "required": ["source_id"],
            },
        },
        {
            "name": "channels_list",
            "description": "Liste les canaux de communication configurés et actions cache. Mettre refresh=true pour relire emails/WhatsApp/etc.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "include_actions": {"type": "boolean", "default": True},
                    "refresh": {"type": "boolean", "default": False},
                    "limit": {"type": "integer", "default": 50},
                },
            },
        },
        {
            "name": "cli_auth_check",
            "description": "Lance les checks déclaratifs d'auth CLI (read-only) depuis la config Zab.",
            "inputSchema": {
                "type": "object",
                "properties": {"only": {"type": "array", "items": {"type": "string"}}},
            },
        },
        {
            "name": "system_health_check",
            "description": "Lance le check système Zab agrégé (config, skills, mémoire, connecteurs, CLIs, Hermes).",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "search",
            "description": "Recherche dans l'index zab (skills, connecteurs, projets, modèles, mémoire). Retourne top-N résumés.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "section": {"type": "string", "description": "skills|connectors|projects|models|memory_sources"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
        },
        {
            "name": "inspect",
            "description": "Détail complet d'un item indexé (section + key). À utiliser après search.",
            "inputSchema": {
                "type": "object",
                "properties": {"section": {"type": "string"}, "key": {"type": "string"}},
                "required": ["section", "key"],
            },
        },
        {
            "name": "skills_manifest",
            "description": "Liste compacte des skills disponibles pour agents, agrégée depuis repos et projets.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "org": {"type": "string"},
                    "project": {"type": "string"},
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 200},
                },
            },
        },
        {
            "name": "context_pack",
            "description": "Génère un pack de contexte Markdown local pour les agents, filtrable par organisation, projet, ou requête texte.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "org": {"type": "string"},
                    "project": {"type": "string"},
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 80},
                },
            },
        },
        {
            "name": "vault_list",
            "description": "Liste les notes du vault Obsidian (chemins relatifs). Optionnel: sous-dossier.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "subdir": {"type": "string", "description": "Sous-dossier relatif au vault (ex: 50_notes)"},
                    "limit": {"type": "integer", "default": 500},
                },
            },
        },
        {
            "name": "vault_read",
            "description": "Lit une note du vault (frontmatter + body). Le chemin doit être relatif au vault.",
            "inputSchema": {
                "type": "object",
                "properties": {"rel": {"type": "string"}},
                "required": ["rel"],
            },
        },
        {
            "name": "vault_search",
            "description": "Recherche substring dans tout le vault Obsidian. Retourne hits {rel, line, text}.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 100},
                    "case_sensitive": {"type": "boolean", "default": False},
                },
                "required": ["query"],
            },
        },
        {
            "name": "daily_append",
            "description": "Append un bloc Markdown à la daily note du jour (création si absente). Append-only.",
            "inputSchema": {
                "type": "object",
                "properties": {"block": {"type": "string"}},
                "required": ["block"],
            },
        },
        {
            "name": "inbox_create",
            "description": "Crée une nouvelle note dans 00_inbox/. Refuse l'écrasement.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Nom de fichier sans chemin (ex: idea-mcp.md)"},
                    "body": {"type": "string"},
                },
                "required": ["filename", "body"],
            },
        },
    ]


def call_mcp_tool(name: str, args: dict[str, Any] | None = None) -> Any:
    """Call a Zab MCP tool implementation by name and return its raw payload."""

    args = args or {}
    if name == "capabilities":
        result = get_capabilities()
    elif name == "agent_bootstrap":
        result = agent_bootstrap(refresh=bool(args.get("refresh") or False))
    elif name == "source_health":
        result = source_health(refresh=bool(args.get("refresh") or False))
    elif name == "research":
        result = research(
            str(args.get("query") or ""),
            project=args.get("project") or None,
            mode=str(args.get("mode") or "plan"),
            max_tokens=int(args.get("max_tokens") or 6000),
            refresh=bool(args.get("refresh") or False),
        )
    elif name == "project_handoff":
        result = project_handoff(str(args.get("project") or ""), limit=int(args.get("limit") or 80))
    elif name == "security_status":
        result = security_status()
    elif name == "memory_status":
        result = memory_status()
    elif name == "memory_search":
        result = memory_search(
            str(args.get("query") or ""),
            limit=int(args.get("limit") or 10),
            source=args.get("source") or None,
            wing=args.get("wing") or None,
        )
    elif name == "connectors_list":
        result = connectors_list(
            q=str(args.get("q") or ""),
            kind=args.get("kind") or None,
            tag=args.get("tag") or None,
            limit=int(args.get("limit") or 50),
            include_details=bool(args.get("include_details") or False),
        )
    elif name == "connector_status":
        result = connector_status(
            str(args.get("slug") or ""),
            include_checks=bool(args.get("include_checks", True)),
        )
    elif name == "composio_connections":
        result = composio_connections(
            toolkit=args.get("toolkit") or None,
            active_only=bool(args.get("active_only", True)),
            resolve_identities=bool(args.get("resolve_identities") or False),
        )
    elif name == "task_sources_status":
        result = task_sources_status()
    elif name == "tasks_list":
        result = tasks_list(
            q=str(args.get("q") or ""),
            source=args.get("source") or None,
            status=args.get("status") or None,
            limit=int(args.get("limit") or 50),
            refresh=bool(args.get("refresh") or False),
        )
    elif name == "tasks_sync":
        result = tasks_sync()
    elif name == "task_source_check":
        result = task_source_check(str(args.get("source_id") or ""))
    elif name == "channels_list":
        result = channels_list(
            include_actions=bool(args.get("include_actions", True)),
            refresh=bool(args.get("refresh") or False),
            limit=int(args.get("limit") or 50),
        )
    elif name == "cli_auth_check":
        only_arg = args.get("only")
        only = [str(x) for x in only_arg] if isinstance(only_arg, list) else None
        result = cli_auth_check(only=only)
    elif name == "system_health_check":
        result = system_health_check()
    elif name == "search":
        section_arg = args.get("section")
        sections = [str(section_arg)] if section_arg else None
        result = search(str(args.get("query") or ""), limit=int(args.get("limit") or 10), sections=sections)
    elif name == "inspect":
        result = state_index.get_section_item(str(args.get("section") or ""), str(args.get("key") or ""))
    elif name == "skills_manifest":
        result = skills_manifest(
            org=args.get("org") or None,
            project=args.get("project") or None,
            query=args.get("query") or None,
            limit=int(args.get("limit") or 200),
        )
    elif name == "context_pack":
        _, pack_md = state_index.build_context_pack(
            org=args.get("org") or None,
            project=args.get("project") or None,
            query=args.get("query") or None,
            limit=int(args.get("limit") or 80),
        )
        result = {"content": pack_md}
    elif name == "vault_list":
        result = obsidian_vault.list_notes(subdir=args.get("subdir") or None, limit=int(args.get("limit") or 500))
    elif name == "vault_read":
        result = obsidian_vault.read_note(str(args.get("rel") or ""))
    elif name == "vault_search":
        result = obsidian_vault.vault_search(
            str(args.get("query") or ""),
            limit=int(args.get("limit") or 100),
            case_sensitive=bool(args.get("case_sensitive") or False),
        )
    elif name == "daily_append":
        path = obsidian_vault.daily_append(str(args.get("block") or ""))
        result = {"ok": True, "path": str(path)}
    elif name == "inbox_create":
        try:
            path = obsidian_vault.inbox_create(str(args.get("filename") or ""), str(args.get("body") or ""))
            result = {"ok": True, "path": str(path)}
        except (ValueError, FileExistsError) as exc:
            result = {"ok": False, "error": str(exc)}
    else:
        raise KeyError(f"Unknown tool: {name}")
    append_audit_event(name, {"source": "mcp"})
    return result


def run_mcp_stdio() -> None:
    """Small MCP-compatible JSON-RPC stdio server for read-only zab tools."""

    tools = mcp_tools()

    def respond(req_id: Any, result: Any = None, error: Any = None) -> None:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id}
        if error is not None:
            payload["error"] = error
        else:
            payload["result"] = result
        sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    for line in sys.stdin:
        try:
            req = json.loads(line)
            method = req.get("method")
            req_id = req.get("id")
            params = req.get("params") or {}
            if method == "initialize":
                respond(
                    req_id,
                    {
                        "protocolVersion": "2024-11-05",
                        "serverInfo": {"name": "zab", "version": "0.2.0"},
                        "capabilities": {"tools": {}},
                    },
                )
            elif method == "tools/list":
                respond(req_id, {"tools": tools})
            elif method == "tools/call":
                name = str(params.get("name") or "")
                args = params.get("arguments") or {}
                try:
                    result = call_mcp_tool(name, args)
                except KeyError:
                    respond(req_id, error={"code": -32601, "message": f"Unknown tool: {name}"})
                    continue
                respond(req_id, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]})
            elif method == "notifications/initialized":
                continue
            else:
                respond(req_id, error={"code": -32601, "message": f"Unknown method: {method}"})
        except Exception as exc:  # noqa: BLE001 - MCP stdio must report and keep serving.
            respond(None, error={"code": -32603, "message": str(exc)})
