import shutil

import pytest

from zab.paths import skills_root_from_config_file_only, zab_repo_root
from zab.services.jobs import build_argv_for_preset


def test_unknown_preset():
    with pytest.raises(ValueError, match="inconnu"):
        build_argv_for_preset("nope", {})


def test_security_osv_zab_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/fake/osv-scanner" if name == "osv-scanner" else None)
    argv, cwd = build_argv_for_preset("security_osv_zab", None)
    assert argv == ["/fake/osv-scanner", "-r", "."]
    assert cwd == str(zab_repo_root())


def test_security_npm_audit_zab_ui_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/fake/npm" if name == "npm" else None)
    argv, cwd = build_argv_for_preset("security_npm_audit_zab_ui", None)
    assert argv == ["/fake/npm", "audit"]
    assert cwd == str(zab_repo_root() / "zab-ui")


def test_security_gitleaks_zab_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/fake/gitleaks" if name == "gitleaks" else None)
    zroot = zab_repo_root()
    argv, cwd = build_argv_for_preset("security_gitleaks_zab", None)
    assert argv[0] == "/fake/gitleaks"
    assert argv[1:5] == ["detect", "--source", str(zroot), "--redact"]
    assert argv[5] == "-v"
    assert cwd == str(zroot)


def test_security_osv_skills_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/fake/osv-scanner" if name == "osv-scanner" else None)
    argv, cwd = build_argv_for_preset("security_osv_skills", None)
    assert argv == ["/fake/osv-scanner", "-r", "."]
    assert cwd == str(skills_root_from_config_file_only().resolve())


def test_security_osv_zab_requires_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(ValueError, match="osv-scanner introuvable"):
        build_argv_for_preset("security_osv_zab", None)


def test_security_pip_audit_zab_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/fake/uv" if name == "uv" else None)
    argv, cwd = build_argv_for_preset("security_pip_audit_zab", None)
    assert argv == ["/fake/uv", "run", "--with", "pip-audit", "pip-audit"]
    assert cwd == str(zab_repo_root())


def test_security_project_presets_argv(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import yaml

    root = tmp_path / "projects"
    project = root / "demo"
    project.mkdir(parents=True)
    (project / "package.json").write_text('{"name":"demo"}\n', encoding="utf-8")
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump({"projects_roots": [str(root)], "cli_watchlist": [], "tracked_env_extra": []}),
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        shutil,
        "which",
        lambda name: {"osv-scanner": "/fake/osv-scanner", "npm": "/fake/npm", "gitleaks": "/fake/gitleaks"}.get(name),
    )

    argv, cwd = build_argv_for_preset("security_osv_project", {"project_path": str(project)})
    assert argv == ["/fake/osv-scanner", "-r", "."]
    assert cwd == str(project.resolve())

    argv, cwd = build_argv_for_preset("security_npm_audit_project", {"project_path": str(project)})
    assert argv == ["/fake/npm", "audit"]
    assert cwd == str(project.resolve())

    argv, cwd = build_argv_for_preset("security_gitleaks_project", {"project_path": str(project)})
    assert argv == ["/fake/gitleaks", "detect", "--source", str(project.resolve()), "--redact", "-v"]
    assert cwd == str(project.resolve())


def test_smoke_argv():
    argv, cwd = build_argv_for_preset("smoke_mcps", None)
    assert "smoke_test_all_mcps.sh" in argv[-1]
    assert cwd == str(skills_root_from_config_file_only().resolve())
