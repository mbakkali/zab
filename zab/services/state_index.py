"""Index YAML régénérable pour le command center zab."""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from zab.paths import config_dir, data_dir
from zab.services import connectors_aggregate, discovery, memory_db, postgres_store as local_db, skills_registry, tool_catalog
from zab.services.skill_env_vars import build_env_index, env_vars_for_skill
from zab.services.workspace_projects import discover_projects
from zab.user_config import load_user_config, organization_slug_set_from_user_config, user_config_path

STATE_VERSION = "2.1"


def state_path() -> Path:
    """Fichier d'index généré, jetable."""

    return data_dir() / "state.yaml"


def overrides_path() -> Path:
    """Préférences utilisateur persistantes, non générées par ``zab sync``."""

    return config_dir() / "overrides.yaml"


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_yaml_atomic(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    os.replace(tmp, path)
    return path


def _slug(value: str) -> str:
    return value.strip().lower().replace(" ", "-") or "unknown"


def _frontmatter(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    try:
        raw = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError:
        return {}
    return raw if isinstance(raw, dict) else {}


def _skill_record(
    skill: dict[str, Any],
    *,
    org: str,
    repo_root: str = "",
    env_index: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    raw_path = str(skill.get("path") or "")
    p = Path(raw_path).expanduser()
    if not p.is_absolute() and repo_root:
        p = Path(repo_root).expanduser() / p
    exists = p.is_file()
    fm = _frontmatter(p) if exists and p.is_absolute() else {}
    tags = [org]
    for item in fm.get("tags") or []:
        if isinstance(item, str) and item not in tags:
            tags.append(item)
    env_vars: list[dict[str, object]] = []
    if exists and p.is_absolute() and env_index is not None:
        env_vars = env_vars_for_skill(p, env_index)
    return {
        "id": str(fm.get("name") or skill.get("id") or p.parent.name or "unknown"),
        "org": org,
        "path": str(p.resolve()) if exists else raw_path,
        "source": skill.get("source") or ("inventory" if p.is_absolute() else "skills_repo"),
        "description": fm.get("description") if isinstance(fm.get("description"), str) else None,
        "tags": tags,
        "uses_connectors": _string_list(fm.get("uses_connectors")),
        "uses_code_tools": _string_list(fm.get("uses_code_tools")),
        "uses_models": _string_list(fm.get("uses_models")),
        "env_vars": env_vars,
        "exists": exists if p.is_absolute() else None,
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip() and item.strip() not in out:
            out.append(item.strip())
    return out


def _flatten_text(value: Any) -> str:
    parts: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            parts.append(str(key))
            parts.append(_flatten_text(nested))
    elif isinstance(value, list):
        for nested in value:
            parts.append(_flatten_text(nested))
    elif isinstance(value, (str, int, float, bool)):
        parts.append(str(value))
    return " ".join(part for part in parts if part).lower()


def _query_matches_text(query: str | None, text: str) -> bool:
    if not query:
        return True
    q = query.strip().lower()
    if not q:
        return True
    if q in text:
        return True
    terms = [term for term in q.split() if term]
    return bool(terms) and any(term in text for term in terms)


def _path_under_any_projects_root(p: Path, roots: list[Path]) -> bool:
    pr = p.resolve()
    for root in roots:
        try:
            pr.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def _collect_skills(user_cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    roots: list[Path] = []
    for key in ("projects_roots", "skills_roots"):
        for raw in user_cfg.get(key) or []:
            if isinstance(raw, str) and raw.strip():
                roots.append(Path(raw.strip()).expanduser())
    env_index = build_env_index(roots) if roots else {}
    proj_roots: list[Path] = []
    for raw in user_cfg.get("projects_roots") or []:
        if isinstance(raw, str) and raw.strip():
            try:
                proj_roots.append(Path(raw.strip()).expanduser().resolve())
            except OSError:
                continue

    for e in skills_registry.query_registry():
        if str(e.get("status") or "").lower() == "ignored":
            continue
        org = str(e.get("org") or "hors-org")
        path_str = ""
        cp = e.get("canonical_path")
        if isinstance(cp, str) and cp.strip():
            try:
                pp = Path(cp).expanduser().resolve()
                if pp.is_file():
                    path_str = str(pp)
            except OSError:
                path_str = cp.strip()
        if not path_str:
            for src in e.get("sources") or []:
                if not isinstance(src, dict):
                    continue
                sp = str(src.get("path") or "")
                if not sp:
                    continue
                try:
                    pp = Path(sp).expanduser().resolve()
                    if pp.is_file():
                        path_str = str(pp)
                        break
                except OSError:
                    continue
        if not path_str:
            continue
        pobj = Path(path_str)
        try:
            p_res = pobj.resolve()
        except OSError:
            p_res = pobj
        project_name = ""
        for src in e.get("sources") or []:
            if isinstance(src, dict) and str(src.get("kind") or "") == "workspace" and src.get("project"):
                project_name = str(src.get("project"))
                break
        src_label = "workspace" if _path_under_any_projects_root(p_res, proj_roots) else "inventory"
        skill = {
            "id": str(e.get("slug") or p_res.parent.name),
            "path": path_str,
            "source": src_label,
            "project": project_name or None,
        }
        rec = _skill_record(skill, org=org, repo_root="", env_index=env_index)
        rec["registry_key"] = str(e.get("key") or "")
        rec["registry_status"] = str(e.get("status") or "")
        key_base = _slug(f"{org}-{rec['id']}")
        key = key_base
        n = 2
        while key in out and out[key].get("path") != rec.get("path"):
            key = f"{key_base}-{n}"
            n += 1
        out[key] = rec
    return dict(sorted(out.items(), key=lambda x: x[0]))


def _collect_mcps() -> dict[str, Any]:
    """Index MCP multi-sources + instantané sync-status (section ``mcps``)."""
    from zab.services import mcp_sync_status

    rows = mcp_sync_status.mcp_list_payload().get("data") or []
    servers: dict[str, Any] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        slug = str(row.get("slug") or "unknown")
        sk = str(row.get("source_kind") or "")
        key = f"{slug}__{sk}" if sk else slug
        servers[key] = {
            "slug": slug,
            "name": row.get("name"),
            "kind": row.get("kind"),
            "enabled": row.get("enabled"),
            "config_path": row.get("config_path"),
            "source_kind": sk,
            "source_label": row.get("source_label"),
            "registry_status": row.get("registry_status"),
            "fingerprint": row.get("fingerprint"),
            "skills_repo_root": row.get("skills_repo_root"),
        }
    return {
        "servers": dict(sorted(servers.items(), key=lambda x: x[0].casefold())),
        "sync_status": mcp_sync_status.mcp_sync_status_payload(),
    }


def _collect_connectors() -> dict[str, dict[str, Any]]:
    rows = connectors_aggregate.list_connectors(limit=200).get("data") or []
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        slug = str(row.get("id") or "")
        if not slug:
            continue
        detail = connectors_aggregate.get_connector(slug) or row
        out[slug] = {
            "id": slug,
            "display_name": detail.get("display_name") or row.get("display_name") or slug,
            "tags": detail.get("tags") or [],
            "forms": detail.get("forms") or [],
            "agent_hints": _connector_agent_hints(slug, detail.get("forms") or []),
        }
    return dict(sorted(out.items(), key=lambda x: x[0]))


def _connector_agent_hints(slug: str, forms: list[Any]) -> dict[str, Any]:
    """Compact guidance for agents inspecting a connector.

    The hints deliberately stop at discovery and invocation patterns. Business
    workflows belong in skills or the target project, not in zab's middleware.
    """
    forms_list = [f for f in forms if isinstance(f, dict)]
    kinds = sorted({str(f.get("kind") or "").lower() for f in forms_list if f.get("kind")})
    composio_forms = [f for f in forms_list if str(f.get("kind") or "").lower() == "composio"]
    env_vars: list[str] = []
    for form in forms_list:
        meta = form.get("meta") if isinstance(form.get("meta"), dict) else {}
        for name in meta.get("env_vars") or []:
            if isinstance(name, str) and name not in env_vars:
                env_vars.append(name)
    from zab.services.composio_connectors import get_cached_identity

    accounts: list[dict[str, Any]] = []
    for form in composio_forms:
        meta = form.get("meta") if isinstance(form.get("meta"), dict) else {}
        account_id = meta.get("connected_account_id")
        if account_id:
            email = meta.get("account_email")
            # Try to enrich from identity cache
            cached = get_cached_identity(str(account_id))
            if cached and cached.get("successful"):
                email = cached.get("email") or email
            accounts.append(
                {
                    "id": account_id,
                    "status": meta.get("status"),
                    "label": email or meta.get("account_label") or form.get("target"),
                    "email": email,
                }
            )
    commands = {
        "inspect": f"zab inspect connectors {slug} --json",
        "search_related_skills": f"zab search {slug} --section skills --json",
    }
    if composio_forms:
        commands["list_accounts"] = f"zab composio connections --toolkit {slug} --active --json"
        commands["discover_tools"] = f"zab composio search '<task>' --toolkits {slug} --limit 5"
        commands["schema_required_fields"] = "zab composio execute <TOOL_SLUG> --get-schema --required-only"
        commands["resolve_identity"] = f"zab composio whoami --toolkit {slug}"
        if len(accounts) > 1:
            commands["try_all_accounts"] = f"zab composio execute <TOOL_SLUG> --toolkit {slug} --all-accounts -d '{{...}}'"
            commands["gmail_search_all"] = "zab composio gmail search --query '<query>' --limit 5"
    warnings: list[str] = []
    if len(accounts) > 1:
        known_emails = [a.get("email") for a in accounts if a.get("email")]
        unknown_count = len(accounts) - len(known_emails)
        if unknown_count:
            warnings.append(
                f"multi_account: {len(accounts)} accounts — {unknown_count} with unknown email. "
                f"Run '{commands.get('resolve_identity')}' to map emails before choosing."
            )
        else:
            warnings.append(
                f"multi_account: {len(accounts)} accounts known. "
                "Use --account <word_id> or --all-accounts for sweep queries."
            )
    if env_vars:
        warnings.append("secrets: use zab security status --json to locate env files; never print raw values")
    return {
        "purpose": "discover_connector_capabilities_for_agent_use",
        "forms_count": len(forms_list),
        "kinds": kinds,
        "accounts": accounts,
        "env_vars": env_vars,
        "commands": commands,
        "warnings": warnings,
    }


def _collect_models(user_cfg: dict[str, Any]) -> dict[str, Any]:
    raw = user_cfg.get("models_discovery")
    return raw if isinstance(raw, dict) else {}


_CODE_TOOL_BINARIES: dict[str, dict[str, str]] = {
    "claude": {"display_name": "Claude Code", "provider": "anthropic", "kind": "agent"},
    "codex": {"display_name": "Codex CLI", "provider": "openai", "kind": "agent"},
    "cursor": {"display_name": "Cursor", "provider": "cursor", "kind": "ide"},
    "gemini": {"display_name": "Gemini CLI", "provider": "google", "kind": "agent"},
    "kimi": {"display_name": "Kimi", "provider": "moonshot", "kind": "agent"},
    "qwen": {"display_name": "Qwen", "provider": "alibaba", "kind": "agent"},
    "factory": {"display_name": "Factory", "provider": "factory", "kind": "agent"},
    "continue": {"display_name": "Continue", "provider": "continue", "kind": "ide-extension"},
    "hermes": {"display_name": "Hermes Agent", "provider": "hermes", "kind": "agent"},
}


def _configured_path(user_cfg: dict[str, Any], key: str, default: Path) -> Path:
    raw = user_cfg.get(key)
    if isinstance(raw, str) and raw.strip():
        return Path(raw.strip()).expanduser()
    return default


def _collect_code_tools(user_cfg: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    agentpipe = _configured_path(user_cfg, "agentpipe_config_path", Path.home() / ".agentpipe.yaml")
    codexbar = _configured_path(user_cfg, "codexbar_config_path", Path.home() / ".codexbar" / "config.json")
    for binary, meta in _CODE_TOOL_BINARIES.items():
        found = shutil.which(binary)
        out[binary] = {
            "id": binary,
            **meta,
            "binary": found,
            "installed": bool(found),
            "sources": [],
        }
    if agentpipe.is_file():
        for rec in out.values():
            rec["sources"].append({"kind": "agentpipe", "path": str(agentpipe.expanduser().resolve())})
    if codexbar.is_file():
        out.setdefault(
            "codexbar",
            {
                "id": "codexbar",
                "display_name": "CodexBar",
                "provider": "codexbar",
                "kind": "router",
                "binary": shutil.which("codexbar"),
                "installed": bool(shutil.which("codexbar")),
                "sources": [],
            },
        )
        out["codexbar"]["sources"].append({"kind": "codexbar", "path": str(codexbar.expanduser().resolve())})

    if "hermes" in out:
        hcfg_path = Path.home() / ".hermes" / "config.yaml"
        if hcfg_path.is_file():
            try:
                import yaml
                hcfg = yaml.safe_load(hcfg_path.read_text(encoding="utf-8")) or {}
                out["hermes"]["hermes_config"] = {
                    "providers": list(hcfg.get("providers", {}).keys()),
                    "toolsets": hcfg.get("toolsets", []),
                    "external_dirs": hcfg.get("skills", {}).get("external_dirs", []),
                    "memory_provider": hcfg.get("memory", {}).get("provider", "file") if hcfg.get("memory") else "file",
                }
            except Exception:
                pass

    return dict(sorted(out.items(), key=lambda x: x[0]))


def _collect_memory() -> dict[str, Any]:
    st = memory_db.fetch_status()
    out: dict[str, Any] = {
        "mempalace": {
            "configured": bool(st.get("configured")),
            "connected": bool(st.get("connected")),
            "psycopg_available": bool(st.get("psycopg_available")),
            "document_count": st.get("document_count"),
            "error": st.get("error"),
        }
    }
    
    hermes_mem_dir = Path.home() / ".hermes" / "memories"
    if hermes_mem_dir.is_dir():
        user_md = hermes_mem_dir / "USER.md"
        memory_md = hermes_mem_dir / "MEMORY.md"
        out["hermes"] = {
            "configured": True,
            "user_md_exists": user_md.is_file(),
            "user_md_size": user_md.stat().st_size if user_md.is_file() else 0,
            "memory_md_exists": memory_md.is_file(),
            "memory_md_size": memory_md.stat().st_size if memory_md.is_file() else 0,
        }
    return out


def _collect_knowledge_sources(user_cfg: dict[str, Any]) -> dict[str, Any]:
    from zab.services import obsidian_vault

    out: dict[str, Any] = {}
    obsidian_cfg = user_cfg.get("obsidian") if isinstance(user_cfg.get("obsidian"), dict) else {}
    try:
        doctor = obsidian_vault.doctor_payload()
    except Exception as exc:  # noqa: BLE001 - knowledge source discovery must not block sync.
        doctor = {
            "vault_path": obsidian_cfg.get("vault_path") or str(Path.home() / "ObsidianVault"),
            "exists": False,
            "error": str(exc),
        }
    configured = bool(obsidian_cfg) or bool(doctor.get("exists"))
    out["obsidian"] = {
        "id": "obsidian",
        "display_name": "Obsidian Vault",
        "kind": "local_markdown_vault",
        "configured": configured,
        "connected": bool(doctor.get("exists")),
        "path": doctor.get("vault_path"),
        "notes_count": doctor.get("notes_count"),
        "validation": doctor.get("validation"),
        "aliases": ["obsidian", "vault", "second brain", "secondbrain", "knowledge base"],
        "tags": ["obsidian", "second-brain", "knowledge", "local-first"],
        "agent_hints": {
            "search_tool": "vault_search",
            "read_tool": "vault_read",
            "list_tool": "vault_list",
            "append_tools": ["daily_append", "inbox_create"],
            "secrets_policy": "local paths only; note content is returned only by explicit vault_read/vault_search",
        },
    }
    return out


def _collect_orgs(projects: list[dict[str, Any]]) -> dict[str, Any]:
    orgs = {
        str(o.get("org") or "hors-org"): dict(o)
        for o in discovery.list_orgs_with_skills()
        if isinstance(o, dict)
    }
    canonical = organization_slug_set_from_user_config()
    if canonical:
        canonical.add("hors-org")
    for project in projects:
        raw_org = str(project.get("org") or "hors-org")
        org = raw_org if not canonical or raw_org in canonical else "hors-org"
        row = orgs.setdefault(
            org,
            {
                "org": org,
                "name": org,
                "skills": [],
                "projects": [],
                "sources": [],
            },
        )
        projects_list = row.setdefault("projects", [])
        if isinstance(projects_list, list):
            project_ref = {
                "id": project.get("id"),
                "name": project.get("name"),
                "path": project.get("path"),
                "workspace_parent": project.get("workspace_parent"),
                "skills_count": len(project.get("skills") or []),
                "org": raw_org,
                "git_repo": project.get("git_repo"),
                "git_branch": project.get("git_branch"),
                "remote_host": project.get("remote_host"),
                "last_activity_at_utc": project.get("last_activity_at_utc"),
                "last_activity_source": project.get("last_activity_source"),
                "last_activity_path": project.get("last_activity_path"),
            }
            if project_ref not in projects_list:
                projects_list.append(project_ref)
        sources = row.setdefault("sources", [])
        if isinstance(sources, list) and "workspace_projects" not in sources:
            sources.append("workspace_projects")
        row["projects_count"] = len(row.get("projects") or [])
        row["project_names"] = [p.get("name") for p in row.get("projects") or [] if isinstance(p, dict)]
        row["aliases"] = sorted({org, org.replace("-", "_"), org.replace("_", "-")})
    return dict(sorted(orgs.items(), key=lambda x: x[0].casefold()))


def _apply_overrides(state: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    for section in ("connectors", "skills", "models", "code_tools", "memory_sources", "knowledge_sources", "projects", "orgs"):
        target = state.get(section)
        source = overrides.get(section)
        if not isinstance(target, dict) or not isinstance(source, dict):
            continue
        for key, patch in source.items():
            if key not in target or not isinstance(patch, dict):
                continue
            merged = dict(target[key])
            for field in ("note", "description", "tags", "aliases", "hidden"):
                if field in patch:
                    merged[field] = patch[field]
            target[key] = merged
    return state


def build_state(*, include_overrides: bool = True) -> dict[str, Any]:
    skills_registry.refresh_registry_from_disk()
    user_cfg = load_user_config()
    projects = discover_projects()
    state: dict[str, Any] = {
        "version": STATE_VERSION,
        "last_sync_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": "zab sync",
        "sources": {
            "user_config": str(user_config_path().resolve()),
            "state_path": str(state_path().resolve()),
            "overrides_path": str(overrides_path().resolve()),
        },
        "orgs": _collect_orgs(projects),
        "projects": {str(p.get("path") or p.get("name")): p for p in projects},
        "skills": _collect_skills(user_cfg),
        "mcps": _collect_mcps(),
        "connectors": _collect_connectors(),
        "code_tools": _collect_code_tools(user_cfg),
        "models": _collect_models(user_cfg),
        "memory_sources": _collect_memory(),
        "knowledge_sources": _collect_knowledge_sources(user_cfg),
        "security": {
            "env_tracked_count": len(user_cfg.get("tracked_env_extra") or []),
            "reports_path": str((data_dir() / "security-last").resolve()),
            "policy": "masked_secrets_only",
        },
        "policies": {
            "secrets": "never_print_raw_values",
            "state_store": "postgres:zab_core",
            "state_yaml": "legacy_export_only",
            "config_yaml": "user_intent",
            "overrides_yaml": "user_intent",
        },
        "subscriptions": {},
        "sync_log": [
            {
                "scope": "all",
                "status": "success",
                "ended_at": datetime.now(timezone.utc).isoformat(),
            }
        ],
    }
    tools_catalog_payload = tool_catalog.build_tools_catalog(state=state)
    state["tools"] = {
        str(tool.get("id") or tool.get("key") or f"tool-{idx}"): tool
        for idx, tool in enumerate(tools_catalog_payload.get("tools") or [])
        if isinstance(tool, dict) and (tool.get("id") or tool.get("key"))
    }
    if include_overrides:
        state = _apply_overrides(state, _read_yaml(overrides_path()))
    return state


def sync_state() -> tuple[Path, dict[str, Any]]:
    state = build_state(include_overrides=True)
    local_db.replace_state(state)
    return _write_yaml_atomic(state_path(), state), state


def load_state() -> dict[str, Any]:
    if local_db.has_state():
        state = local_db.load_state()
        if state:
            if state.get("version") != STATE_VERSION or "tools" not in state:
                state = build_state(include_overrides=True)
                try:
                    local_db.replace_state(state)
                except Exception:
                    pass
                return _apply_overrides(state, _read_yaml(overrides_path()))
            return _apply_overrides(state, _read_yaml(overrides_path()))
    raw = _read_yaml(state_path())
    if raw:
        raw = local_db.json_safe(raw)
        try:
            local_db.replace_state(raw)
        except Exception:
            # Legacy YAML import is a compatibility path. Runtime storage is
            # Postgres; if that is unavailable, the store error should surface.
            pass
        if raw.get("version") != STATE_VERSION or "tools" not in raw:
            raw = build_state(include_overrides=True)
            try:
                local_db.replace_state(raw)
            except Exception:
                pass
        return _apply_overrides(raw, _read_yaml(overrides_path()))
    return build_state(include_overrides=True)


def state_summary(state: dict[str, Any]) -> dict[str, Any]:
    mcps_block = state.get("mcps") if isinstance(state.get("mcps"), dict) else {}
    mcps_servers = mcps_block.get("servers") if isinstance(mcps_block.get("servers"), dict) else {}
    return {
        "version": state.get("version"),
        "last_sync_at": state.get("last_sync_at"),
        "path": str(state_path().resolve()),
        "database_path": str(local_db.database_path()),
        "counts": {
            "orgs": len(state.get("orgs") or {}),
            "projects": len(state.get("projects") or {}),
            "skills": len(state.get("skills") or {}),
            "mcp_servers": len(mcps_servers),
            "connectors": len(state.get("connectors") or {}),
            "code_tools": len(state.get("code_tools") or {}),
            "tools": len(state.get("tools") or {}),
            "models": len(state.get("models") or {}),
            "memory_sources": len(state.get("memory_sources") or {}),
            "knowledge_sources": len(state.get("knowledge_sources") or {}),
            "security": len(state.get("security") or {}),
            "policies": len(state.get("policies") or {}),
            "subscriptions": len(state.get("subscriptions") or {}),
        },
    }


def list_section(
    section: str,
    *,
    page: int = 1,
    limit: int = 50,
    q: str = "",
    tag: str | None = None,
    installed: bool | None = None,
    registry_status: str | None = None,
    org: str | None = None,
    project: str | None = None,
) -> dict[str, Any]:
    state = load_state()
    raw = state.get(section)
    rows: list[dict[str, Any]] = []
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, dict):
                rows.append({"key": str(key), **value})
    qn = q.strip().lower()
    tag_n = tag.strip().lower() if tag else None
    rs_n = registry_status.strip().lower() if isinstance(registry_status, str) and registry_status.strip() else None
    org_n = org.strip().lower() if isinstance(org, str) and org.strip() else None
    proj_n = project.strip().lower() if isinstance(project, str) and project.strip() else None
    filtered: list[dict[str, Any]] = []
    for row in rows:
        if section == "skills" and rs_n:
            if str(row.get("registry_status") or "").lower() != rs_n:
                continue
        if section in ("skills", "projects", "orgs") and org_n:
            if str(row.get("org") or "").lower() != org_n:
                continue
        if section in ("skills", "projects") and proj_n:
            if not _query_matches_text(proj_n, _flatten_text(row)):
                continue
        if tag_n:
            tags = [str(x).lower() for x in row.get("tags") or []]
            if tag_n not in tags:
                continue
        if installed is not None and bool(row.get("installed")) is not installed:
            continue
        if qn:
            if not _query_matches_text(qn, _flatten_text(row)):
                continue
        filtered.append(row)
    total = len(filtered)
    limit = max(1, min(200, limit))
    page = max(1, page)
    start = (page - 1) * limit
    return {
        "data": filtered[start : start + limit],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": max(1, (total + limit - 1) // limit) if total else 1,
        },
    }


def get_section_item(section: str, key: str) -> dict[str, Any] | None:
    state = load_state()
    raw = state.get(section)
    if not isinstance(raw, dict):
        return None
    item = raw.get(key)
    if isinstance(item, dict):
        return {"key": key, **item}
    for k, value in raw.items():
        if isinstance(value, dict) and str(value.get("id") or "").lower() == key.lower():
            return {"key": str(k), **value}
    return None


def context_pack_path(name: str = "context-pack.md") -> Path:
    return data_dir() / "context-pack" / name


def build_context_pack(
    *,
    org: str | None = None,
    project: str | None = None,
    query: str | None = None,
    include: list[str] | None = None,
    limit: int = 80,
) -> tuple[Path, str]:
    state = load_state()
    org_n = org.strip().lower() if org else None
    project_n = project.strip().lower() if project else None
    query_n = query.strip().lower() if query else None
    include_set = set(include or ["orgs", "projects", "skills", "connectors", "code_tools", "tools", "memory_sources", "knowledge_sources"])
    orgs_raw = state.get("orgs") if isinstance(state.get("orgs"), dict) else {}
    orgs: list[dict[str, Any]] = []
    for key, value in orgs_raw.items():
        if not isinstance(value, dict):
            continue
        row = {"key": str(key), **value}
        text = _flatten_text(row)
        if org_n and str(row.get("org") or row.get("key") or "").lower() != org_n:
            continue
        if project_n and not _query_matches_text(project_n, text):
            continue
        if query_n and not (org_n or project_n) and not _query_matches_text(query_n, text):
            continue
        orgs.append(row)
    orgs = sorted(orgs, key=lambda x: str(x.get("key") or "").lower())[: max(1, min(100, limit))]

    projects_raw = state.get("projects") if isinstance(state.get("projects"), dict) else {}
    projects: list[dict[str, Any]] = []
    for key, value in projects_raw.items():
        if not isinstance(value, dict):
            continue
        row = {"key": str(key), **value}
        text = _flatten_text(row)
        if org_n and str(row.get("org") or "").lower() != org_n:
            continue
        if project_n and not _query_matches_text(project_n, text):
            continue
        if query_n and not (org_n or project_n) and not _query_matches_text(query_n, text):
            continue
        projects.append(row)
    projects = sorted(projects, key=lambda x: (str(x.get("org") or ""), str(x.get("name") or "")))[: max(1, min(100, limit))]

    skills_raw = state.get("skills") if isinstance(state.get("skills"), dict) else {}
    skills: list[dict[str, Any]] = []
    for key, value in skills_raw.items():
        if not isinstance(value, dict):
            continue
        row = {"key": str(key), **value}
        text = _flatten_text(row)
        if org_n and str(row.get("org") or "").lower() != org_n:
            continue
        if project_n and not _query_matches_text(project_n, text):
            continue
        if query_n and not _query_matches_text(query_n, text):
            continue
        skills.append(row)
    skills = sorted(skills, key=lambda x: str(x.get("key") or "").lower())[: max(1, min(300, limit))]

    connectors = state.get("connectors") if isinstance(state.get("connectors"), dict) else {}
    code_tools = state.get("code_tools") if isinstance(state.get("code_tools"), dict) else {}
    tools = state.get("tools") if isinstance(state.get("tools"), dict) else {}
    memory = state.get("memory_sources") if isinstance(state.get("memory_sources"), dict) else {}
    knowledge = state.get("knowledge_sources") if isinstance(state.get("knowledge_sources"), dict) else {}

    lines: list[str] = [
        "# zab Context Pack",
        "",
        f"Generated at: {datetime.now(timezone.utc).isoformat()}",
        f"State synced at: {state.get('last_sync_at') or 'unknown'}",
        f"Filter org: {org or 'all'}",
        f"Filter project: {project or 'all'}",
        f"Filter query: {query or 'all'}",
        "",
        "## Summary",
        "",
        f"- Orgs included: {len(orgs)}",
        f"- Projects included: {len(projects)}",
        f"- Skills included: {len(skills)}",
        f"- Connectors indexed: {len(connectors)}",
        f"- Code tools indexed: {len(code_tools)}",
        f"- Tools catalog indexed: {len(tools)}",
        f"- Memory sources indexed: {len(memory)}",
        f"- Knowledge sources indexed: {len(knowledge)}",
        "",
    ]
    if "orgs" in include_set:
        lines.extend(["## Orgs", ""])
        if not orgs:
            lines.append("- No orgs matched the selected filters.")
        for org_row in orgs:
            name = org_row.get("name") or org_row.get("org") or org_row.get("key")
            projects_count = org_row.get("projects_count")
            if projects_count is None:
                projects_count = len(org_row.get("projects") or [])
            lines.append(f"- {name}: projects={projects_count}, skills={len(org_row.get('skills') or [])}")
        lines.append("")

    if "projects" in include_set:
        lines.extend(["## Projects", ""])
        if not projects:
            lines.append("- No projects matched the selected filters.")
        for project_row in projects:
            lines.append(f"### {project_row.get('name') or project_row.get('key')}")
            lines.append("")
            lines.append(f"- Org: {project_row.get('org') or 'unknown'}")
            lines.append(f"- Path: {project_row.get('path') or ''}")
            if project_row.get("workspace_parent"):
                lines.append(f"- Workspace parent: {project_row.get('workspace_parent')}")
            if project_row.get("detection_reasons"):
                lines.append(f"- Detected by: {', '.join(project_row['detection_reasons'])}")
            if project_row.get("project_markers"):
                lines.append(f"- Markers: {', '.join(project_row['project_markers'][:8])}")
            lines.append(f"- Workspace skills: {len(project_row.get('skills') or [])}")
            lines.append("")

    if "skills" in include_set:
        lines.extend(["## Skills", ""])
        if not skills:
            lines.append("- No skills matched the selected filters.")
        for skill in skills:
            lines.append(f"### {skill.get('id') or skill.get('key')}")
            lines.append("")
            lines.append(f"- Org: {skill.get('org') or 'unknown'}")
            if skill.get("description"):
                lines.append(f"- Description: {skill['description']}")
            lines.append(f"- Path: {skill.get('path') or ''}")
            if skill.get("uses_connectors"):
                lines.append(f"- Uses connectors: {', '.join(skill['uses_connectors'])}")
            if skill.get("uses_models"):
                lines.append(f"- Uses models: {', '.join(skill['uses_models'])}")
            if skill.get("uses_code_tools"):
                lines.append(f"- Uses code tools: {', '.join(skill['uses_code_tools'])}")
            lines.append("")

    if "connectors" in include_set:
        lines.extend(["## Connectors", ""])
        for key, conn in sorted(connectors.items(), key=lambda x: x[0])[:100]:
            if not isinstance(conn, dict):
                continue
            forms = conn.get("forms") if isinstance(conn.get("forms"), list) else []
            kinds = sorted({str(f.get("kind")) for f in forms if isinstance(f, dict) and f.get("kind")})
            lines.append(f"- {conn.get('display_name') or key}: {', '.join(kinds) or 'unknown'}")
            # If composio multi-account, show account mapping
            composio_forms = [f for f in forms if isinstance(f, dict) and str(f.get("kind")).lower() == "composio"]
            hints_accounts = conn.get("agent_hints", {}).get("accounts") if isinstance(conn.get("agent_hints"), dict) else None
            if hints_accounts:
                lines.append("  Accounts:")
                for ha in hints_accounts:
                    acc_id = ha.get("id") or "?"
                    email = ha.get("email") or ha.get("label") or "?"
                    status = ha.get("status") or "?"
                    lines.append(f"    - {acc_id} → {email} ({status})")
            elif len(composio_forms) > 1:
                lines.append("  Accounts:")
                for f in composio_forms:
                    meta = f.get("meta") if isinstance(f.get("meta"), dict) else {}
                    acc_id = meta.get("connected_account_id") or "?"
                    email = meta.get("account_email") or "?"
                    status = meta.get("status") or "?"
                    lines.append(f"    - {acc_id} → {email} ({status})")

    if "code_tools" in include_set or "code-tools" in include_set:
        lines.extend(["", "## Code Tools", ""])
        for key, tool in sorted(code_tools.items(), key=lambda x: x[0]):
            if not isinstance(tool, dict):
                continue
            state_word = "installed" if tool.get("installed") else "missing"
            lines.append(f"- {tool.get('display_name') or key}: {state_word} ({tool.get('binary') or 'no binary'})")

    if "tools" in include_set or "tool-catalog" in include_set or "tools_catalog" in include_set:
        lines.extend(["", "## Tools Catalog", ""])
        if not tools:
            lines.append("- No tools catalog entries matched the selected filters.")
        for key, tool in sorted(tools.items(), key=lambda x: x[0])[:120]:
            if not isinstance(tool, dict):
                continue
            status = str(tool.get("status") or "skipped")
            primary = str(tool.get("primary") or "—")
            fallback = str(tool.get("fallback") or "—")
            origin = str(tool.get("origin") or "local")
            lines.append(
                f"- {tool.get('label') or key}: status={status}, primary={primary}, fallback={fallback}, origin={origin}"
            )
            skill_refs = [str(x) for x in tool.get("skill_refs") or [] if str(x).strip()]
            if skill_refs:
                lines.append(f"  Skills: {', '.join(skill_refs)}")
            if tool.get("status_reason"):
                lines.append(f"  Reason: {tool.get('status_reason')}")

    if "memory_sources" in include_set or "memory" in include_set:
        lines.extend(["", "## Memory", ""])
        for key, src in sorted(memory.items(), key=lambda x: x[0]):
            if not isinstance(src, dict):
                continue
            lines.append(f"- {key}: configured={bool(src.get('configured'))}, connected={bool(src.get('connected'))}")

    if "knowledge_sources" in include_set or "knowledge" in include_set:
        lines.extend(["", "## Knowledge Sources", ""])
        for key, src in sorted(knowledge.items(), key=lambda x: x[0]):
            if not isinstance(src, dict):
                continue
            lines.append(
                f"- {src.get('display_name') or key}: "
                f"configured={bool(src.get('configured'))}, connected={bool(src.get('connected'))}"
            )
            if src.get("path"):
                lines.append(f"  Path: {src.get('path')}")
            hints = src.get("agent_hints") if isinstance(src.get("agent_hints"), dict) else {}
            tools = [hints.get("search_tool"), hints.get("read_tool"), hints.get("list_tool")]
            tools = [str(tool) for tool in tools if tool]
            if tools:
                lines.append(f"  Tools: {', '.join(tools)}")

    text = "\n".join(lines).rstrip() + "\n"
    name_parts = ["context-pack"]
    if org:
        name_parts.append(_slug(org))
    if project:
        name_parts.append(_slug(project))
    if query:
        name_parts.append(_slug(query))
    path = context_pack_path("-".join(name_parts) + ".md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path, text
