"""Commande `zab config`."""

from pathlib import Path

from typer.testing import CliRunner

from zab.cli import app

runner = CliRunner()


def test_config_paths_only(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("ZAB_SKILLS_ROOT", raising=False)
    monkeypatch.delenv("ZAB_INVOCATION_CWD", raising=False)
    monkeypatch.chdir(tmp_path)
    from zab import user_config

    monkeypatch.setattr(user_config, "load_user_config", lambda: {})

    r = runner.invoke(app, ["config", "--paths"])
    assert r.exit_code == 0
    assert "skills_root=" in r.stdout
    assert "config_yaml=" in r.stdout
    assert "local_tools_yaml=" not in r.stdout


def test_config_help():
    r = runner.invoke(app, ["config", "--help"], env={"NO_COLOR": "1", "TERM": "dumb"})
    assert r.exit_code == 0
    assert "open" in r.stdout
