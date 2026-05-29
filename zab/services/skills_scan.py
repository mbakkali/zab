"""Parcours récursif des SKILL.md (layout orgs/common et catégories Hermes)."""

from __future__ import annotations

import os
from pathlib import Path

# Répertoires ignorés lors du parcours récursif (bruit / volumétrie)
_SKILL_SCAN_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".svn",
        ".hg",
        "node_modules",
        "venv",
        ".venv",
        "__pycache__",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        "dist",
        "build",
        ".next",
        "target",
        ".cargo",
        "site-packages",
        ".archive",
        ".hub",
        ".curator_backups",
    }
)

# Racines de dépôt skills : ne pas re-scanner comme « catégories » (déjà couvertes)
_REPO_LAYOUT_TOP_SKIP: frozenset[str] = frozenset(
    {
        "orgs",
        "common",
        ".git",
        ".archive",
        ".hub",
        ".curator_backups",
    }
)


def iter_skill_md_recursive(root: Path, *, max_depth: int = 12) -> list[Path]:
    """Liste les SKILL.md sous ``root`` (profondeur bornée, ignore le bruit)."""
    base = root.expanduser().resolve()
    if not base.is_dir():
        return []
    out: list[Path] = []
    base_len = len(base.parts)
    try:
        for dirpath, dirnames, filenames in os.walk(os.fspath(base), topdown=True, followlinks=False):
            cur = Path(dirpath)
            depth = len(cur.parts) - base_len
            if depth > max_depth:
                dirnames[:] = []
                continue
            dirnames[:] = sorted(
                d for d in dirnames if d not in _SKILL_SCAN_SKIP_DIRS and not d.startswith(".")
            )
            if "SKILL.md" not in filenames:
                continue
            md = cur / "SKILL.md"
            if md.is_file():
                out.append(md)
    except OSError:
        return []
    return out


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for p in paths:
        key = str(p.resolve())
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def collect_skill_md_under_repo(repo: Path) -> list[Path]:
    """
    Collecte les SKILL.md d'un dépôt skills :
    - layout classique ``common/skills`` et ``orgs/<org>/skills`` ;
    - layout Hermes par catégorie à la racine (``apple/<skill>/``, etc.).
    """
    root = repo.expanduser().resolve()
    if not root.is_dir():
        return []

    found: list[Path] = []

    common = root / "common" / "skills"
    if common.is_dir():
        found.extend(iter_skill_md_recursive(common))

    orgs = root / "orgs"
    if orgs.is_dir():
        try:
            for org_dir in sorted(orgs.iterdir(), key=lambda p: p.name.casefold()):
                if not org_dir.is_dir() or org_dir.name.startswith("."):
                    continue
                skills_dir = org_dir / "skills"
                if skills_dir.is_dir():
                    found.extend(iter_skill_md_recursive(skills_dir))
        except OSError:
            pass

    try:
        for child in sorted(root.iterdir(), key=lambda p: p.name.casefold()):
            if not child.is_dir():
                continue
            if child.name in _REPO_LAYOUT_TOP_SKIP or child.name.startswith("."):
                continue
            found.extend(iter_skill_md_recursive(child))
    except OSError:
        pass

    return _dedupe_paths(found)
