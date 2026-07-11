"""Découverte des dépôts locaux (ex. ~/projects) et skills .cursor / .claude — inférence d’organisation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from zab.paths import skills_roots_resolved_from_config, user_home
from zab.services.project_git import project_file_activity, project_git_metadata
from zab.user_config import organization_slugs_from_user_config, projects_roots_resolved, skills_sync_settings

# Parcours .cursor / .claude : ignorer autant que possible le bruit / la volumétrie
_PROJECT_SUBTREE_SKIP: frozenset[str] = frozenset(
    {
        ".git",
        "node_modules",
        "dist",
        "build",
        ".next",
        "venv",
        ".venv",
        "__pycache__",
        ".turbo",
        "coverage",
    }
)

_PROJECT_MARKER_FILES: frozenset[str] = frozenset(
    {
        ".git",
        "pyproject.toml",
        "package.json",
        "uv.lock",
        "requirements.txt",
        "setup.py",
        "Cargo.toml",
        "go.mod",
        "pom.xml",
        "Makefile",
        "docker-compose.yml",
        "compose.yaml",
        "pnpm-lock.yaml",
        "yarn.lock",
        "package-lock.json",
        "bun.lockb",
        "tsconfig.json",
    }
)


def infer_org_slug(project_dir_name: str) -> str:
    """
    Associe un dossier projet (nom court) à une « organisation » logique (slug minuscule).
    Les slugs configurés dans ``organizations`` sont utilisés comme préfixes publics.
    """
    n = project_dir_name.strip().lower().replace(" ", "-")
    if not n:
        return "hors-org"

    if n == "zab" or n.startswith("zab-"):
        return "zab"

    for org in organization_slugs_from_user_config():
        org_slug = org.strip().lower().replace("_", "-")
        if not org_slug or org_slug == "zab":
            continue
        if n == org_slug or n.startswith(f"{org_slug}-") or n.startswith(f"{org_slug}_"):
            return org_slug

    return "hors-org"


def _project_markers(project_path: Path) -> list[str]:
    """Return lightweight project markers present at the repository root."""

    markers: list[str] = []
    for name in sorted(_PROJECT_MARKER_FILES, key=str.casefold):
        if (project_path / name).exists():
            markers.append(name)
    return markers


def _looks_like_project(project_path: Path, skills_paths: list[Path]) -> tuple[bool, list[str]]:
    markers = _project_markers(project_path)
    reasons: list[str] = []
    if skills_paths:
        reasons.append("workspace_skills")
    if markers:
        reasons.append("project_markers")
    return bool(reasons), reasons


def _skill_id_for_path(skill_md: Path) -> str:
    return skill_md.parent.name


def _iter_skill_md_under(
    base: Path,
    *,
    subtree_name: str,
    max_depth: int,
) -> list[Path]:
    """Parcourt base/subtree_name avec limite de profondeur (prof. 0 = subtree seul)."""
    root = (base / subtree_name).resolve()
    if not root.is_dir():
        return []
    out: list[Path] = []
    base_len = len(root.parts)
    try:
        for dirpath, dirnames, filenames in os.walk(os.fspath(root), topdown=True, followlinks=False):
            cur = Path(dirpath)
            depth = len(cur.parts) - base_len
            if depth > max_depth:
                dirnames[:] = []
                continue
            dirnames[:] = sorted(d for d in dirnames if d not in _PROJECT_SUBTREE_SKIP and not d.startswith("."))
            if "SKILL.md" in filenames:
                p = cur / "SKILL.md"
                if p.is_file():
                    out.append(p)
    except OSError:
        return []
    return out


def discover_skills_in_project(project_path: Path) -> list[Path]:
    """SKILL.md à la racine du projet + sous .cursor/** et .claude/** (profondeur bornée)."""
    discovered: list[Path] = []
    root = project_path.resolve()
    if not root.is_dir():
        return []

    top = root / "SKILL.md"
    if top.is_file():
        discovered.append(top)

    # .cursor et .claude : typiquement .cursor/skills/<id>/SKILL.md
    for dot in (".cursor", ".claude"):
        discovered.extend(_iter_skill_md_under(root, subtree_name=dot, max_depth=12))

    seen: set[str] = set()
    uniq: list[Path] = []
    for p in discovered:
        k = str(p.resolve())
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    uniq.sort(key=lambda x: str(x).casefold())
    return uniq


def _immediate_project_dirs(projects_root: Path) -> list[Path]:
    excluded = _excluded_project_dirs()
    try:
        items = sorted(projects_root.iterdir(), key=lambda x: x.name.casefold())
    except OSError:
        return []
    out: list[Path] = []
    for p in items:
        if not p.is_dir():
            continue
        if p.name.startswith("."):
            continue
        try:
            if p.resolve() in excluded:
                continue
        except OSError:
            continue
        out.append(p)
    return out


def _excluded_project_dirs() -> set[Path]:
    out: set[Path] = set()
    try:
        out.add(Path(str(skills_sync_settings()["repo_root"])).expanduser().resolve())
    except OSError:
        pass
    for root in skills_roots_resolved_from_config():
        try:
            out.add(root.resolve())
        except OSError:
            continue
    return out


def _project_row(
    *,
    name: str,
    path: Path,
    org: str,
    projects_root: Path,
    skills_paths: list[Path],
    workspace_parent: str | None,
) -> dict[str, Any]:
    hp = user_home().resolve()
    markers = _project_markers(path)
    try:
        project_id = str(path.resolve().relative_to(projects_root.resolve())).replace("\\", "/")
    except ValueError:
        project_id = name
    skills_payload: list[dict[str, Any]] = []
    for md in skills_paths:
        abs_p = str(md.resolve())
        try:
            rel_from_home = str(md.resolve().relative_to(hp))
        except ValueError:
            rel_from_home = abs_p
        skills_payload.append(
            {
                "id": _skill_id_for_path(md),
                "path": abs_p,
                "rel_from_home": rel_from_home.replace("\\", "/"),
                "source": "workspace",
            }
        )
    row: dict[str, Any] = {
        "id": project_id,
        "name": name,
        "path": str(path.resolve()),
        "org": org,
        "projects_root": str(projects_root.resolve()),
        "skills": skills_payload,
        "skills_count": len(skills_payload),
        "project_markers": markers,
        "detection_reasons": [
            reason
            for reason, enabled in (
                ("workspace_skills", bool(skills_payload)),
                ("project_markers", bool(markers)),
            )
            if enabled
        ],
        "aliases": sorted(
            {
                name,
                name.lower(),
                name.replace("_", "-"),
                name.replace("-", "_"),
                project_id,
                project_id.lower(),
                org,
                path.name,
            }
        ),
    }
    if workspace_parent is not None:
        row["workspace_parent"] = workspace_parent
    row.update(project_git_metadata(path))
    if not row.get("last_activity_at_utc"):
        row.update(project_file_activity(path))
    return row


def discover_projects() -> list[dict[str, Any]]:
    """
    Pour chaque racine dans ``projects_roots`` :

    - Dossiers immédiats avec au moins un SKILL.md = un projet (racine du workspace).
    - Sous-dossiers immédiats de ceux-ci (un niveau de plus) = projets distincts ; l’org est
      inférée depuis le dossier parent (ex. ``clients/acme`` → org ``clients``).
    """
    projects_out: list[dict[str, Any]] = []
    for pr in projects_roots_resolved():
        try:
            pr_r = pr.resolve()
        except OSError:
            continue
        if not pr_r.is_dir():
            continue
        for l1 in _immediate_project_dirs(pr_r):
            skills_l1 = discover_skills_in_project(l1)
            include_l1, _ = _looks_like_project(l1, skills_l1)
            if include_l1:
                org = infer_org_slug(l1.name)
                projects_out.append(
                    _project_row(
                        name=l1.name,
                        path=l1,
                        org=org,
                        projects_root=pr_r,
                        skills_paths=skills_l1,
                        workspace_parent=None,
                    )
                )
            for l2 in _immediate_project_dirs(l1):
                skills_l2 = discover_skills_in_project(l2)
                include_l2, _ = _looks_like_project(l2, skills_l2)
                if not include_l2:
                    continue
                org_nested = infer_org_slug(l1.name)
                if org_nested == "hors-org":
                    org_nested = l1.name.strip().lower().replace(" ", "-") or "hors-org"
                projects_out.append(
                    _project_row(
                        name=l2.name,
                        path=l2,
                        org=org_nested,
                        projects_root=pr_r,
                        skills_paths=skills_l2,
                        workspace_parent=l1.name,
                    )
                )
    projects_out.sort(
        key=lambda x: (
            x["org"].casefold(),
            (x.get("workspace_parent") or "").casefold(),
            x["name"].casefold(),
        )
    )
    return projects_out


def project_dir_is_under_projects_roots(candidate: Path) -> bool:
    """True si ``candidate`` est un dossier projet : immédiat sous ``projects_roots`` ou un niveau plus bas."""
    try:
        cr = candidate.expanduser().resolve()
    except OSError:
        return False
    if not cr.is_dir():
        return False
    try:
        parent = cr.parent.resolve()
        grand = parent.parent.resolve()
    except OSError:
        return False
    for root in projects_roots_resolved():
        try:
            rr = root.resolve()
        except OSError:
            continue
        if parent == rr or grand == rr:
            return True
    return False


def path_is_under_projects_roots(candidate: Path) -> bool:
    """True si candidate est un SKILL.md sous une racine ``projects_roots``."""
    try:
        cr = candidate.expanduser().resolve()
    except OSError:
        return False
    if cr.name != "SKILL.md":
        return False
    for root in projects_roots_resolved():
        try:
            cr.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False
