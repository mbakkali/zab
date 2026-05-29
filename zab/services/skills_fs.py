"""Lecture / écriture sécurisée des fichiers SKILL (repo relatif ou chemins absolus du registre skills)."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from zab.paths import skills_root


class SkillPathError(ValueError):
    pass


def _repo_root(repo_root: Path | None) -> Path:
    return repo_root if repo_root is not None else skills_root()


def _all_skill_repo_bases() -> list[Path]:
    """Bases dépôt pour chemins relatifs : discovery puis repli sur skills_root()."""
    from zab.services.discovery import discovery_repo_bases

    bases = discovery_repo_bases()
    if bases:
        return bases
    root = skills_root()
    return [root] if root.is_dir() else []


def _validate_relative(rel: str, repo_root: Path | None) -> Path:
    if not rel or ".." in Path(rel).parts:
        raise SkillPathError("chemin invalide")
    root = _repo_root(repo_root)
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise SkillPathError("hors du dépôt") from exc
    parts = candidate.relative_to(root.resolve()).parts
    if len(parts) < 2:
        raise SkillPathError("chemin trop court")
    if parts[0] not in ("orgs", "claude-plugins", "common"):
        raise SkillPathError("autorisé uniquement sous orgs/ ou claude-plugins/")
    if parts[0] == "orgs":
        if len(parts) < 4 or parts[2] != "skills":
            raise SkillPathError("attendu orgs/<org>/skills/.../SKILL.md")
    elif parts[0] == "claude-plugins":
        if len(parts) < 4 or parts[2] != "skills":
            raise SkillPathError("attendu claude-plugins/<id>/skills/.../SKILL.md")
    else:
        if len(parts) < 3 or parts[1] != "skills":
            raise SkillPathError("attendu common/skills/.../SKILL.md")
    if candidate.name != "SKILL.md":
        raise SkillPathError("seul SKILL.md est éditable via cette API")
    return candidate


def resolve_skill_md_path(path: str, *, must_exist: bool) -> Path:
    """
    - Chemin absolu : doit être autorisé par ``skills_registry`` (adoptées / sources indexées) ou sous ``projects_roots``.
    - Chemin relatif : sous l’un des dépôts ``discovery_repo_bases()`` ou ``skills_root()`` en secours.
    """
    raw = path.strip()
    if not raw:
        raise SkillPathError("chemin vide")
    exp = Path(raw).expanduser()
    if exp.is_absolute():
        resolved = exp.resolve()
        if resolved.name != "SKILL.md":
            raise SkillPathError("seul SKILL.md est éditable via cette API")
        from zab.services.workspace_projects import path_is_under_projects_roots
        from zab.services import skills_registry

        allowed = skills_registry.allowed_absolute_skill_paths_for_api()
        if str(resolved) not in allowed and not path_is_under_projects_roots(resolved):
            raise SkillPathError(
                "chemin absolu non autorisé — adoptez la skill dans le registre "
                "ou placez-le sous projects_roots (voir docs/skills-registry-migration.md)"
            )
        if must_exist:
            if not resolved.is_file():
                raise SkillPathError("fichier introuvable")
        elif resolved.exists() and not resolved.is_file():
            raise SkillPathError("la cible existe et n'est pas un fichier")
        return resolved

    last_err: SkillPathError | None = None
    for base in _all_skill_repo_bases():
        try:
            return _validate_relative(raw, base)
        except SkillPathError as e:
            last_err = e
    raise last_err if last_err else SkillPathError("aucun dépôt skills résolu pour ce chemin relatif")


def read_skill(rel: str, *, repo_root: Path | None = None) -> str:
    """Si ``repo_root`` est fourni (API legacy), valide uniquement sous cette racine ; sinon résolution unifiée."""
    if repo_root is not None:
        p = _validate_relative(rel, repo_root)
    else:
        p = resolve_skill_md_path(rel, must_exist=True)
    if not p.is_file():
        raise SkillPathError("fichier introuvable")
    return p.read_text(encoding="utf-8")


def write_skill(rel: str, content: str, *, repo_root: Path | None = None) -> dict[str, str]:
    if repo_root is not None:
        p = _validate_relative(rel, repo_root)
        root = _repo_root(repo_root)
    else:
        p = resolve_skill_md_path(rel, must_exist=False)
        root = None
        br = p.resolve()
        for base in _all_skill_repo_bases():
            try:
                br.relative_to(base.resolve())
                root = base.resolve()
                break
            except ValueError:
                continue
        if root is None:
            root = p.parent
    p.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = p.with_suffix(f".md.zab-backup-{ts}")
    if p.is_file():
        shutil.copy2(p, backup)
    p.write_text(content, encoding="utf-8")
    try:
        rel_path = str(p.resolve().relative_to(root.resolve()))
    except ValueError:
        rel_path = str(p.resolve())
    try:
        rel_backup = str(backup.resolve().relative_to(root.resolve())) if backup.is_file() else ""
    except ValueError:
        rel_backup = str(backup.resolve()) if backup.is_file() else ""
    return {"path": rel_path, "backup": rel_backup}
