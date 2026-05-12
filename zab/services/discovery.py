"""Découverte orgs, skills, plugins MCP configs (dashboard : lu depuis ~/.config/zab/config.yaml)."""

from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError, version as pkg_version
from pathlib import Path
from typing import Any

import yaml

from zab.paths import dashboard_anchor_path, skills_roots_resolved_from_config
from zab.services.inventory_config import infer_mcp_repo_base_from_skill_md
from zab.user_config import (
    claude_plugin_paths_resolved,
    projects_roots_resolved,
    skill_md_paths_resolved,
    skills_roots_strings_ordered,
    user_config_path,
)


def _zab_release_version() -> str:
    try:
        return pkg_version("zab")
    except PackageNotFoundError:
        from zab import __version__

        return __version__


def _repos_walk() -> list[Path]:
    """Uniquement les répertoires déclarés dans ``skills_roots`` (parcours disque classique)."""
    return skills_roots_resolved_from_config()


def discovery_repo_bases() -> list[Path]:
    """Dépôts pour MCP / registry : racines YAML + bases déduites des SKILL.md inventoriés."""
    bases: list[Path] = []
    seen: set[str] = set()
    for p in skills_roots_resolved_from_config():
        k = str(p.resolve())
        if k not in seen:
            seen.add(k)
            bases.append(p.resolve())
    for md in skill_md_paths_resolved():
        b = infer_mcp_repo_base_from_skill_md(md)
        if b is None:
            continue
        k = str(b.resolve())
        if k not in seen:
            seen.add(k)
            bases.append(b.resolve())
    return bases


def _orgs_from_skill_inventory(paths: list[Path]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, str]]] = {}
    for md in paths:
        if not md.is_file():
            continue
        parts = md.parts
        org_name = "hors-org"
        skill_id = md.parent.name
        try:
            ix = parts.index("orgs")
            if ix + 3 < len(parts) and parts[ix + 2] == "skills":
                org_name = parts[ix + 1]
                skill_id = parts[ix + 3]
        except ValueError:
            pass
        groups.setdefault(org_name, []).append({"id": skill_id, "path": str(md.resolve())})
    out: list[dict[str, Any]] = []
    for org in sorted(groups.keys(), key=lambda x: x.casefold()):
        skills = sorted(groups[org], key=lambda x: (x["id"].casefold(), x["path"]))
        out.append(
            {
                "org": org,
                "skills": skills,
                "skills_repo_root": "",
                "from_inventory": True,
            }
        )
    return out


def merge_workspace_projects_into_orgs(
    orgs: list[dict[str, Any]],
    projects: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Ajoute les skills des projets locaux aux groupes d’org (sans doublon de chemin résolu)."""
    by_org: dict[str, dict[str, Any]] = {}
    for o in orgs:
        by_org[o["org"]] = {
            "org": o["org"],
            "skills": [dict(s) for s in (o.get("skills") or [])],
            "skills_repo_root": o.get("skills_repo_root") or "",
            "from_inventory": bool(o.get("from_inventory", False)),
        }

    seen_paths: set[str] = set()
    for o in orgs:
        for s in o.get("skills") or []:
            raw_p = str(s.get("path") or "")
            if not raw_p:
                continue
            try:
                seen_paths.add(str(Path(raw_p).expanduser().resolve()))
            except OSError:
                seen_paths.add(raw_p)

    for proj in projects:
        org_slug = str(proj.get("org") or "hors-org")
        if org_slug not in by_org:
            by_org[org_slug] = {
                "org": org_slug,
                "skills": [],
                "skills_repo_root": "",
                "from_inventory": False,
            }
        bucket = by_org[org_slug]["skills"]
        for sk in proj.get("skills") or []:
            ap = str(sk.get("path") or "")
            if not ap:
                continue
            try:
                key = str(Path(ap).expanduser().resolve())
            except OSError:
                key = ap
            if key in seen_paths:
                continue
            seen_paths.add(key)
            bucket.append(
                {
                    "id": str(sk.get("id") or Path(ap).parent.name),
                    "path": key,
                    "source": "workspace",
                    "project": str(proj.get("name") or ""),
                }
            )

    for block in by_org.values():
        block["skills"] = sorted(
            block["skills"],
            key=lambda x: (str(x.get("id", "")).casefold(), str(x.get("path", "")).casefold()),
        )
    return sorted(by_org.values(), key=lambda x: str(x["org"]).casefold())


def _orgs_with_projects_tuple() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from zab.services.workspace_projects import discover_projects

    projects = discover_projects()
    base = list_orgs_skills_repo_only()
    if not projects:
        return base, projects
    return merge_workspace_projects_into_orgs(base, projects), projects


def list_orgs_with_skills() -> list[dict[str, Any]]:
    """Dépôt skills + skills découvertes sous ``projects_roots`` (fusion par slug d’org)."""
    return _orgs_with_projects_tuple()[0]


def list_orgs_skills_repo_only() -> list[dict[str, Any]]:
    """Inventaire skills sans les projets locaux (uniquement dépôt ``orgs/`` ou ``skill_md_paths``)."""
    inv = skill_md_paths_resolved()
    if inv:
        return _orgs_from_skill_inventory(inv)

    out: list[dict[str, Any]] = []
    for base in _repos_walk():
        root = base / "orgs"
        if not root.is_dir():
            continue
        for org_path in sorted(root.iterdir()):
            if not org_path.is_dir() or org_path.name.startswith("."):
                continue
            skills_dir = org_path / "skills"
            skills: list[dict[str, str]] = []
            if skills_dir.is_dir():
                for skill_dir in sorted(skills_dir.iterdir()):
                    if not skill_dir.is_dir():
                        continue
                    md = skill_dir / "SKILL.md"
                    if md.is_file():
                        skills.append(
                            {
                                "id": skill_dir.name,
                                "path": str(md.relative_to(base)),
                            }
                        )
            out.append(
                {
                    "org": org_path.name,
                    "skills": skills,
                    "skills_repo_root": str(base.resolve()),
                    "from_inventory": False,
                }
            )
    return out


def _plugin_bundle_record(plugin_dir: Path, base: Path | None) -> dict[str, Any]:
    meta = plugin_dir / ".claude-plugin" / "plugin.json"
    skills_dir = plugin_dir / "skills"
    n_skills = 0
    if skills_dir.is_dir():
        n_skills = sum(1 for p in skills_dir.iterdir() if p.is_dir() and (p / "SKILL.md").is_file())
    meta_obj: dict[str, Any] = {}
    if meta.is_file():
        try:
            meta_obj = json.loads(meta.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            meta_obj = {"_error": "invalid_json"}
    fs_path = str(plugin_dir.resolve())
    rel_path = fs_path
    skills_repo_root = ""
    if base is not None:
        try:
            rel_path = str(plugin_dir.resolve().relative_to(base.resolve()))
            skills_repo_root = str(base.resolve())
        except ValueError:
            rel_path = fs_path
    return {
        "id": plugin_dir.name,
        "path": rel_path,
        "fs_path": fs_path,
        "plugin_json": meta_obj,
        "skill_count": n_skills,
        "skills_repo_root": skills_repo_root,
        "from_inventory": base is None,
    }


def list_claude_plugin_bundles() -> list[dict[str, Any]]:
    explicit = claude_plugin_paths_resolved()
    if explicit:
        return [_plugin_bundle_record(p, None) for p in sorted(explicit, key=lambda x: str(x).casefold())]

    out: list[dict[str, Any]] = []
    for base in _repos_walk():
        root = base / "claude-plugins"
        if not root.is_dir():
            continue
        for plugin_dir in sorted(root.iterdir()):
            if not plugin_dir.is_dir() or plugin_dir.name.startswith("."):
                continue
            out.append(_plugin_bundle_record(plugin_dir, base))
    return out


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"_error": "invalid_json", "path": str(path)}


def list_mcp_configs() -> dict[str, Any]:
    bases = discovery_repo_bases()
    if not bases:
        return {
            "cursor_mcp": _normalize_mcp_servers({}, "cursor-mcp.json", config_file=None),
            "claude_desktop_mcp": _normalize_mcp_servers({}, "claude-desktop-mcp.json", config_file=None),
        }

    cur_servers: list[dict[str, Any]] = []
    desk_servers: list[dict[str, Any]] = []
    for base in bases:
        cfgdir = base / "configs"
        cursor = cfgdir / "cursor-mcp.json"
        desktop = cfgdir / "claude-desktop-mcp.json"
        bc = _normalize_mcp_servers(_load_json(cursor), "cursor-mcp.json", config_file=cursor)
        bd = _normalize_mcp_servers(_load_json(desktop), "claude-desktop-mcp.json", config_file=desktop)
        for item in bc.get("servers") or []:
            if isinstance(item, dict):
                cur_servers.append({**item, "skills_repo_root": str(base.resolve())})
        for item in bd.get("servers") or []:
            if isinstance(item, dict):
                desk_servers.append({**item, "skills_repo_root": str(base.resolve())})

    return {
        "cursor_mcp": {"source": "cursor-mcp.json", "servers": cur_servers},
        "claude_desktop_mcp": {"source": "claude-desktop-mcp.json", "servers": desk_servers},
    }


def _normalize_mcp_servers(
    doc: dict[str, Any],
    source: str,
    *,
    config_file: Path | None = None,
) -> dict[str, Any]:
    servers = doc.get("mcpServers", doc) if isinstance(doc, dict) else {}
    if not isinstance(servers, dict):
        return {"source": source, "servers": [], "_raw_error": "no_mcpServers"}
    items: list[dict[str, Any]] = []
    cf_base = ""
    if config_file is not None and config_file.is_file():
        cf_base = str(config_file.resolve())
    for name, cfg in servers.items():
        if not isinstance(cfg, dict):
            items.append(
                {
                    "name": str(name),
                    "kind": "unknown",
                    "target": "",
                    "enabled": True,
                    "note": "",
                    "config_path": cf_base,
                    "transport_command": None,
                    "transport_args": [],
                    "env_var_names": [],
                }
            )
            continue
        enabled = cfg.get("enabled", True)
        if str(name).startswith("_TODO"):
            enabled = False
        env_obj = cfg.get("env") if isinstance(cfg.get("env"), dict) else {}
        env_var_names = sorted(str(k) for k in env_obj.keys())
        cmd = cfg.get("command")
        args_raw = cfg.get("args") or []
        args_list = [str(a) for a in args_raw] if isinstance(args_raw, list) else []
        if "url" in cfg:
            kind = "http"
            target = str(cfg.get("url", ""))
        elif "command" in cfg:
            kind = "stdio"
            target = f"{cfg.get('command', '')} {' '.join(args_list)}".strip()
        else:
            kind = "other"
            target = ""
        cf = cf_base
        items.append(
            {
                "name": str(name),
                "kind": kind,
                "target": target[:500],
                "enabled": bool(enabled),
                "note": str(cfg.get("note", ""))[:200],
                "config_path": cf,
                "transport_command": str(cmd) if cmd is not None else None,
                "transport_args": args_list[:80],
                "env_var_names": env_var_names,
            }
        )
    return {"source": source, "servers": items}


def mcp_registry_path() -> str | None:
    for base in discovery_repo_bases():
        p = base / "common" / "mcp-registry" / "SKILL.md"
        if p.is_file():
            return str(p.relative_to(base))
    return None


def load_plugin_config_summary() -> dict[str, Any]:
    for base in discovery_repo_bases():
        path = base / "plugin-config.yaml"
        if not path.is_file():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, OSError):
            return {
                "present": True,
                "path": str(path.relative_to(base)),
                "error": "yaml_parse",
                "skills_repo_root": str(base.resolve()),
            }
        return {
            "present": True,
            "path": str(path.relative_to(base)),
            "keys": list(data.keys()) if isinstance(data, dict) else [],
            "skills_repo_root": str(base.resolve()),
        }
    return {"present": False}


def overview() -> dict[str, Any]:
    bases_walk = _repos_walk()
    bases_mcp = discovery_repo_bases()
    primary = dashboard_anchor_path()
    inv_skills = skill_md_paths_resolved()
    inv_plugins = claude_plugin_paths_resolved()
    configured = len(bases_walk) > 0 or len(inv_skills) > 0 or len(inv_plugins) > 0
    ordered_yaml = skills_roots_strings_ordered()
    warn = None
    if not configured:
        warn = (
            "Remplissez la config : zab scan --propose-config puis zab scan --apply-config "
            "(écrit skill_md_paths et claude_plugin_paths), ou éditez ~/.config/zab/config.yaml."
        )
    orgs, projects = _orgs_with_projects_tuple()
    return {
        "skills_root": str(primary) if primary else None,
        "skills_roots": [str(b.resolve()) for b in bases_walk],
        "skills_root_configured": configured,
        "skills_root_yaml_raw": ordered_yaml[0] if len(ordered_yaml) == 1 else None,
        "skills_roots_yaml": ordered_yaml,
        "skill_md_paths_count": len(inv_skills),
        "claude_plugin_paths_count": len(inv_plugins),
        "user_config_path": str(user_config_path().resolve()),
        "zab_version": _zab_release_version(),
        "dashboard_warning": warn if not configured else None,
        "orgs": orgs,
        "projects": projects,
        "projects_roots": [str(p.resolve()) for p in projects_roots_resolved()],
        "plugin_bundles": list_claude_plugin_bundles(),
        "mcp_configs": list_mcp_configs(),
        "mcp_registry_relative": mcp_registry_path(),
        "plugin_config": load_plugin_config_summary(),
        "discovery_repo_bases": [str(b.resolve()) for b in bases_mcp],
    }
