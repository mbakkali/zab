"""Création contrôlée de fichiers Agent Skill dans le dépôt skills."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from zab.user_config import skills_sync_settings

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$")


class SkillScaffoldError(ValueError):
    pass


def validate_skill_slug(value: str) -> str:
    slug = value.strip()
    if not _SLUG_RE.fullmatch(slug) or ".." in Path(slug).parts:
        raise SkillScaffoldError("slug invalide : utilisez [a-z0-9-] sans espace ni chemin")
    return slug


def _target_path(repo_root: Path, *, org: str, name: str) -> Path:
    root = repo_root.expanduser().resolve()
    if org == "common":
        target = (root / "common" / "skills" / name / "SKILL.md").resolve()
    else:
        target = (root / "orgs" / org / "skills" / name / "SKILL.md").resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise SkillScaffoldError("chemin cible hors du dépôt skills") from exc
    return target


def _skill_text(name: str, *, description: str, tags: list[str]) -> str:
    frontmatter = {
        "name": name,
        "description": description or f"Skill {name}",
        "version": "0.1.0",
        "tags": tags,
    }
    return (
        "---\n"
        + yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip()
        + "\n---\n\n"
        + f"# {name}\n\n"
        + "## When to use\n\n"
        + "- Décrire les situations où l'agent doit charger cette skill.\n\n"
        + "## Inputs\n\n"
        + "- Préciser les informations attendues avant exécution.\n\n"
        + "## Steps\n\n"
        + "1. Lire le contexte pertinent.\n"
        + "2. Exécuter le workflow en respectant les contraintes locales.\n"
        + "3. Retourner un résultat vérifiable.\n\n"
        + "## Outputs\n\n"
        + "- Décrire le livrable attendu et les preuves de vérification.\n"
    )


def create_skill(
    name: str,
    *,
    org: str | None = None,
    description: str = "",
    repo_root: str | Path | None = None,
    force: bool = False,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    skill_id = validate_skill_slug(name)
    org_slug = validate_skill_slug(org or "common")
    settings = skills_sync_settings()
    root = Path(repo_root).expanduser() if repo_root is not None else Path(str(settings["repo_root"])).expanduser()
    target = _target_path(root, org=org_slug, name=skill_id)
    if target.exists() and not force:
        raise SkillScaffoldError(f"skill existe déjà : {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    tag_list = tags if tags is not None else [org_slug]
    target.write_text(_skill_text(skill_id, description=description, tags=tag_list), encoding="utf-8")
    return {
        "id": skill_id,
        "org": org_slug,
        "scope": "global",
        "path": str(target.resolve()),
        "repo_root": str(root.resolve()),
        "created": True,
    }


def create_global_skill(
    name: str,
    *,
    org: str | None = None,
    description: str = "",
    repo_root: str | Path | None = None,
    force: bool = False,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Alias explicite pour clarifier qu'on écrit dans le repo global de skills."""

    return create_skill(
        name,
        org=org,
        description=description,
        repo_root=repo_root,
        force=force,
        tags=tags,
    )


def create_project_skill(
    name: str,
    *,
    project_path: str | Path,
    description: str = "",
    force: bool = False,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    skill_id = validate_skill_slug(name)
    root = Path(project_path).expanduser().resolve()
    if not root.is_dir():
        raise SkillScaffoldError(f"projet introuvable : {root}")
    target = (root / ".cursor" / "skills" / skill_id / "SKILL.md").resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise SkillScaffoldError("chemin cible hors du projet") from exc
    if target.exists() and not force:
        raise SkillScaffoldError(f"skill existe déjà : {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    tag_list = tags if tags is not None else ["project"]
    target.write_text(_skill_text(skill_id, description=description, tags=tag_list), encoding="utf-8")
    return {
        "id": skill_id,
        "org": None,
        "scope": "project",
        "path": str(target),
        "project_path": str(root),
        "created": True,
    }
