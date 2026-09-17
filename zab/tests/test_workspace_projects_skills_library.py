import os
from pathlib import Path

from zab.services.workspace_projects import _looks_like_project, discover_skills_in_project


def _skill(root: Path, name: str) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: x\n---\n", encoding="utf-8")
    return d


def test_bibliotheque_skills_exposee_par_liens(tmp_path):
    projet = tmp_path / "cowork"
    lib = _skill(projet / "skills", "socle")
    _skill(projet / "skills", "metier")
    expo = projet / ".claude" / "skills"
    expo.mkdir(parents=True)
    os.symlink(os.path.relpath(lib, expo), expo / "socle")

    trouves = discover_skills_in_project(projet)

    assert sorted(p.parent.name for p in trouves) == ["metier", "socle"]
    assert _looks_like_project(projet, trouves) == (True, ["workspace_skills"])


def test_bibliotheque_profondeur_bornee(tmp_path):
    projet = tmp_path / "p"
    _skill(projet / "skills" / "a" / "b" / "c", "trop-profond")

    assert discover_skills_in_project(projet) == []
