from pathlib import Path

from zab.services import scanner


def _skill(root: Path, name: str) -> None:
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: x\ndescription: y\n---\n", encoding="utf-8")


def test_balayage_actif_par_defaut(tmp_path, monkeypatch):
    monkeypatch.delenv("ZAB_SKILLS_SCAN", raising=False)
    monkeypatch.setattr("zab.user_config.load_user_config", lambda: {})
    _skill(tmp_path, "a")
    assert scanner.skills_scan_enabled() is True
    assert len(scanner.scan_skill_md_files(tmp_path)) == 1


def test_config_coupe_le_balayage(tmp_path, monkeypatch):
    monkeypatch.delenv("ZAB_SKILLS_SCAN", raising=False)
    monkeypatch.setattr("zab.user_config.load_user_config", lambda: {"skills_scan": False})
    _skill(tmp_path, "a")
    assert scanner.skills_scan_enabled() is False
    assert scanner.scan_skill_md_files(tmp_path) == []


def test_env_force_le_balayage(tmp_path, monkeypatch):
    monkeypatch.setattr("zab.user_config.load_user_config", lambda: {"skills_scan": False})
    monkeypatch.setenv("ZAB_SKILLS_SCAN", "1")
    _skill(tmp_path, "a")
    assert len(scanner.scan_skill_md_files(tmp_path)) == 1
