from pathlib import Path

import pytest

from zab.services import skills_broadcast as sb


def _skill(root: Path, name: str) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: x\n---\n", encoding="utf-8")
    return d


def test_sans_politique_tout_est_diffuse(tmp_path):
    assert sb.load_claude_allowlist(tmp_path / "absent.yml") is None


def test_mode_all_ne_filtre_pas(tmp_path):
    p = tmp_path / "policy.yml"
    p.write_text("claude:\n  mode: all\n  global: [a]\n", encoding="utf-8")
    assert sb.load_claude_allowlist(p) is None


def test_liste_invalide_leve_au_lieu_de_tout_retirer(tmp_path):
    p = tmp_path / "policy.yml"
    p.write_text("claude:\n  mode: allowlist\n  global: a\n", encoding="utf-8")
    with pytest.raises(ValueError):
        sb.load_claude_allowlist(p)


def test_allowlist_retire_les_managees_et_respecte_le_reste(tmp_path):
    store = tmp_path / "store"
    target = tmp_path / "claude"
    skills = [(n, _skill(store, n)) for n in ("garde", "retire", "nouveau-hors-liste")]

    # Premier passage historique : tout est posé et managé.
    sb.broadcast_claude(skills, target_dir=target)
    # Une entrée posée à la main ne doit jamais être touchée.
    (target / "perso").mkdir()

    r = sb.broadcast_claude(skills, target_dir=target, allowlist={"garde", "inconnu"})

    assert r.policy == "allowlist"
    assert r.filtered_out == 2
    assert r.allowlist_missing == ["inconnu"]
    assert sorted(r.removed) == ["nouveau-hors-liste", "retire"]
    assert sorted(p.name for p in target.iterdir() if not p.name.startswith(".")) == [
        "garde",
        "perso",
    ]
    assert list(sb._read_marker(target / sb.MARKER_FILENAME)) == ["garde"]


def test_dry_run_ne_touche_a_rien(tmp_path):
    store = tmp_path / "store"
    target = tmp_path / "claude"
    skills = [(n, _skill(store, n)) for n in ("garde", "retire")]
    sb.broadcast_claude(skills, target_dir=target)

    r = sb.broadcast_claude(skills, target_dir=target, allowlist={"garde"}, dry_run=True)

    assert r.removed == ["retire"]
    assert (target / "retire").is_symlink()
