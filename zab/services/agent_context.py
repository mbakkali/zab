"""Agent-oriented context contract for zab CLI/API/MCP."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from zab.paths import config_dir, data_dir, resolve_skills_root
from zab.services import jobs, obsidian_vault, state_index
from zab.services.feature_catalog import agent_guide, catalog
from zab.services.memory_db import fetch_status as fetch_memory_status
from zab.services.secrets_scan import scan_secret_presence
from zab.services.workspace_projects import discover_projects
from zab.user_config import load_user_config, tracked_env_names_for_security, user_config_path


SAFE_AGENT_ACTIONS = {
    "bootstrap": "lecture_sure",
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
        if isinstance(value, (str, int, float, bool)):
            parts.append(str(value))
        elif isinstance(value, list):
            parts.extend(str(x) for x in value if isinstance(x, (str, int, float, bool)))
        elif isinstance(value, dict):
            for nested in value.values():
                if isinstance(nested, (str, int, float, bool)):
                    parts.append(str(nested))
    return " ".join(parts).lower()


def search(query: str, *, limit: int = 20, sections: list[str] | None = None, refresh: bool = False) -> dict[str, Any]:
    q = query.strip()
    if refresh:
        state_index.sync_state()
    state = state_index.load_state()
    terms = [t for t in q.lower().split() if t]
    results: list[dict[str, Any]] = []
    for row in _iter_state_rows(state, sections):
        hay = _haystack(row)
        if terms and not all(term in hay for term in terms):
            continue
        score = 0
        reasons: list[str] = []
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
        if not terms:
            score = 1
            reasons.append("unfiltered")
        item = dict(row)
        item["score"] = score
        item["match_reasons"] = reasons or ["content"]
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
    s = selector.strip().lower()
    if not s:
        return False
    fields = [project.get("name"), project.get("path"), project.get("org"), project.get("workspace_parent")]
    return any(s == str(x).lower() or s in str(x).lower() for x in fields if x)


def project_handoff(project: str, *, limit: int = 80) -> dict[str, Any]:
    selector = project.strip()
    projects = discover_projects()
    matches = [p for p in projects if _project_matches(p, selector)]
    if not matches:
        return {
            "found": False,
            "selector": selector,
            "available_projects": [{"name": p.get("name"), "path": p.get("path"), "org": p.get("org")} for p in projects[:50]],
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
    security = security_status()
    pack_path, pack_text = state_index.build_context_pack(
        org=org,
        project=project_path or selector,
        limit=limit,
        include=["skills", "connectors", "code_tools", "memory_sources"],
        query=selector,
    )
    payload = {
        "found": True,
        "selector": selector,
        "project": selected,
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
            f"zab search {selector!r} --json",
            f"zab context-pack --project {selector!r} --stdout",
            "zab security status --json",
        ],
    }
    append_audit_event("project_handoff", {"project": selector, "found": True})
    return payload


def run_mcp_stdio() -> None:
    """Small MCP-compatible JSON-RPC stdio server for read-only zab tools."""

    tools = [
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
                    "limit": {"type": "integer", "default": 80}
                }
            }
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
                name = params.get("name")
                args = params.get("arguments") or {}
                if name == "search":
                    section_arg = args.get("section")
                    sections = [str(section_arg)] if section_arg else None
                    result = search(
                        str(args.get("query") or ""),
                        limit=int(args.get("limit") or 10),
                        sections=sections,
                    )
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
                    result = obsidian_vault.list_notes(
                        subdir=args.get("subdir") or None,
                        limit=int(args.get("limit") or 500),
                    )
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
                        path = obsidian_vault.inbox_create(
                            str(args.get("filename") or ""),
                            str(args.get("body") or ""),
                        )
                        result = {"ok": True, "path": str(path)}
                    except (ValueError, FileExistsError) as exc:
                        result = {"ok": False, "error": str(exc)}
                else:
                    respond(req_id, error={"code": -32601, "message": f"Unknown tool: {name}"})
                    continue
                respond(req_id, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]})
            elif method == "notifications/initialized":
                continue
            else:
                respond(req_id, error={"code": -32601, "message": f"Unknown method: {method}"})
        except Exception as exc:  # noqa: BLE001 - MCP stdio must report and keep serving.
            respond(None, error={"code": -32603, "message": str(exc)})
