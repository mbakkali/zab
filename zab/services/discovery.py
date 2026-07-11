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
    organization_slugs_from_user_config,
    projects_roots_resolved,
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
    """Dépôts pour MCP / registry : racines YAML + bases déduites des SKILL.md adoptés."""
    from zab.services import skills_registry

    bases: list[Path] = []
    seen: set[str] = set()
    for p in skills_roots_resolved_from_config():
        k = str(p.resolve())
        if k not in seen:
            seen.add(k)
            bases.append(p.resolve())
    for md in skills_registry.adopted_skill_md_paths_resolved():
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
            try:
                ix = parts.index("common")
                if ix + 2 < len(parts) and parts[ix + 1] == "skills":
                    org_name = "common"
                    skill_id = parts[ix + 2]
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


def _canonical_org_records(
    *,
    base_orgs: list[dict[str, Any]],
    projects: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Retourne uniquement les organisations métier définies par l'utilisateur."""
    canonical = organization_slugs_from_user_config()
    if not canonical:
        return merge_workspace_projects_into_orgs(base_orgs, projects)
    if "hors-org" not in canonical:
        canonical = [*canonical, "hors-org"]
    canonical_set = set(canonical)
    base_by_org = {str(o.get("org") or ""): o for o in base_orgs if isinstance(o, dict)}
    by_org: dict[str, dict[str, Any]] = {}

    for org in canonical:
        base = base_by_org.get(org) or {}
        by_org[org] = {
            "org": org,
            "skills": [dict(s) for s in (base.get("skills") or [])],
            "skills_repo_root": base.get("skills_repo_root") or "",
            "from_inventory": bool(base.get("from_inventory", False)),
            "projects": [],
            "sources": ["canonical_config"],
        }

    seen_paths: set[str] = set()
    for block in by_org.values():
        for s in block.get("skills") or []:
            raw_p = str(s.get("path") or "")
            if not raw_p:
                continue
            try:
                seen_paths.add(str(Path(raw_p).expanduser().resolve()))
            except OSError:
                seen_paths.add(raw_p)

    for proj in projects:
        raw_org = str(proj.get("org") or "hors-org")
        org_slug = raw_org if raw_org in canonical_set else "hors-org"
        bucket = by_org[org_slug]
        project_ref = {
            "id": proj.get("id"),
            "name": proj.get("name"),
            "path": proj.get("path"),
            "workspace_parent": proj.get("workspace_parent"),
            "skills_count": len(proj.get("skills") or []),
            "org": raw_org,
            "git_repo": proj.get("git_repo"),
            "git_branch": proj.get("git_branch"),
            "remote_host": proj.get("remote_host"),
            "last_activity_at_utc": proj.get("last_activity_at_utc"),
            "last_activity_source": proj.get("last_activity_source"),
            "last_activity_path": proj.get("last_activity_path"),
        }
        projects_bucket = bucket.setdefault("projects", [])
        if isinstance(projects_bucket, list) and project_ref not in projects_bucket:
            projects_bucket.append(project_ref)
        sources = bucket.setdefault("sources", [])
        if isinstance(sources, list) and "workspace_projects" not in sources:
            sources.append("workspace_projects")
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
            bucket["skills"].append(
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
        block["projects"] = sorted(
            block.get("projects") or [],
            key=lambda x: (str(x.get("workspace_parent") or "").casefold(), str(x.get("name") or "").casefold()),
        )
        block["projects_count"] = len(block.get("projects") or [])
        block["project_names"] = [p.get("name") for p in block.get("projects") or [] if isinstance(p, dict)]
    return [by_org[org] for org in canonical]


def _orgs_with_projects_tuple() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from zab.services.workspace_projects import discover_projects

    projects = discover_projects()
    base = list_orgs_skills_repo_only()
    return _canonical_org_records(base_orgs=base, projects=projects), projects


def list_orgs_with_skills() -> list[dict[str, Any]]:
    """Dépôt skills + skills découvertes sous ``projects_roots`` (fusion par slug d’org)."""
    return _orgs_with_projects_tuple()[0]


def _orgs_from_skills_roots_walk() -> list[dict[str, Any]]:
    """Parcours skills_roots quand le registre est vide (avant premier refresh)."""
    from zab.services import skills_registry
    from zab.services.skills_scan import collect_skill_md_under_repo

    out: list[dict[str, Any]] = []
    for base in _repos_walk():
        groups: dict[str, list[dict[str, str]]] = {}
        for md in collect_skill_md_under_repo(base):
            if not md.is_file():
                continue
            org_name = skills_registry.infer_org_slug_for_skill_file(md, base) or "hors-org"
            skill_id = md.parent.name
            try:
                rel_path = str(md.relative_to(base))
            except ValueError:
                rel_path = str(md.resolve())
            groups.setdefault(org_name, []).append({"id": skill_id, "path": rel_path})
        for org in sorted(groups.keys(), key=lambda x: x.casefold()):
            skills = sorted(groups[org], key=lambda x: (x["id"].casefold(), x["path"]))
            out.append(
                {
                    "org": org,
                    "skills": skills,
                    "skills_repo_root": str(base.resolve()),
                    "from_inventory": False,
                }
            )
    return out


def _orgs_from_registry_inventory() -> list[dict[str, Any]]:
    from zab.services import skills_registry

    skills_registry.ensure_registry_and_migrate()
    entries = skills_registry.query_registry()
    if not entries:
        return []
    groups: dict[str, list[dict[str, str]]] = {}
    for e in entries:
        if str(e.get("status") or "").lower() == "ignored":
            continue
        org = str(e.get("org") or "hors-org")
        slug = str(e.get("slug") or "")
        cp = e.get("canonical_path")
        path_abs = ""
        if isinstance(cp, str) and cp.strip():
            try:
                p = Path(cp).expanduser().resolve()
                if p.is_file():
                    path_abs = str(p)
            except OSError:
                path_abs = cp.strip()
        if not path_abs:
            for src in e.get("sources") or []:
                if not isinstance(src, dict):
                    continue
                sp = str(src.get("path") or "")
                if not sp:
                    continue
                try:
                    pp = Path(sp).expanduser().resolve()
                    if pp.is_file():
                        path_abs = str(pp)
                        break
                except OSError:
                    continue
        if not path_abs:
            continue
        groups.setdefault(org, []).append({"id": slug or Path(path_abs).parent.name, "path": path_abs})
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


def list_orgs_skills_repo_only() -> list[dict[str, Any]]:
    """Inventaire skills sans les projets locaux (registre ; repli skills_roots si vide)."""
    inv = _orgs_from_registry_inventory()
    if inv:
        return inv
    return _orgs_from_skills_roots_walk()


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


def list_mcp_configs() -> dict[str, Any]:
    """MCP versionnés dans les dépôts skills uniquement (rétrocompat ``GET /api/mcp``)."""
    from zab.services import mcp_sources

    bases = discovery_repo_bases()
    if not bases:
        return {
            "cursor_mcp": {"source": "cursor-mcp.json", "servers": []},
            "claude_desktop_mcp": {"source": "claude-desktop-mcp.json", "servers": []},
        }

    cur_servers: list[dict[str, Any]] = []
    desk_servers: list[dict[str, Any]] = []
    for item in mcp_sources.scan_skills_repo_config_files():
        if not isinstance(item, dict):
            continue
        sk = str(item.get("source_kind") or "")
        if sk == "skills_repo_cursor":
            cur_servers.append(item)
        elif sk == "skills_repo_desktop":
            desk_servers.append(item)

    return {
        "cursor_mcp": {"source": "cursor-mcp.json", "servers": cur_servers},
        "claude_desktop_mcp": {"source": "claude-desktop-mcp.json", "servers": desk_servers},
    }


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
    from zab.services import skills_registry

    bases_walk = _repos_walk()
    bases_mcp = discovery_repo_bases()
    primary = dashboard_anchor_path()
    inv_skills = skills_registry.adopted_skill_md_paths_resolved()
    inv_plugins = claude_plugin_paths_resolved()
    configured = len(bases_walk) > 0 or len(inv_skills) > 0 or len(inv_plugins) > 0
    ordered_yaml = skills_roots_strings_ordered()
    warn = None
    if not configured:
        warn = (
            "Remplissez la config : skills_roots dans ~/.config/zab/config.yaml "
            "ou adoptez des skills dans ~/.config/zab/skills-registry.json (zab sync)."
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
