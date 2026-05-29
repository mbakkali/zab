"""Argv des jobs MemPalace (mine) et périmètre projects_roots."""

from __future__ import annotations

import pytest
import yaml

from zab.services.jobs import build_argv_for_preset


def _write_config(home, proot) -> None:
    cfg_d = home / ".config" / "zab"
    cfg_d.mkdir(parents=True)
    (cfg_d / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "skills_roots": [],
                "projects_roots": [str(proot.resolve())],
                "skill_md_paths": [],
                "claude_plugin_paths": [],
                "cli_watchlist": [],
                "tracked_env_extra": [],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_build_argv_mempalace_mine(monkeypatch, tmp_path_factory) -> None:
    home = tmp_path_factory.mktemp("mine-home")
    monkeypatch.setenv("HOME", str(home))
    proot = home / "projects"
    leaf = proot / "carrefour" / "danmdata"
    leaf.mkdir(parents=True)
    _write_config(home, proot)
    monkeypatch.setattr("zab.services.jobs.resolve_mempalace_interpreter", lambda: "/fake/mempalace-venv/bin/python")

    argv, cwd = build_argv_for_preset(
        "mempalace_mine",
        {"project_path": str(leaf), "wing": "danmdata", "mode": "projects"},
    )
    assert argv[:3] == ["/fake/mempalace-venv/bin/python", "-m", "zab.services.mempalace_mine_projects_docs"]
    assert str(leaf) in argv
    assert "--wing" in argv
    assert argv[argv.index("--wing") + 1] == "danmdata"
    assert cwd == str(leaf)


def test_build_argv_mempalace_mine_projects_falls_back_to_cli(monkeypatch, tmp_path_factory) -> None:
    home = tmp_path_factory.mktemp("mine-fallback")
    monkeypatch.setenv("HOME", str(home))
    proot = home / "projects"
    leaf = proot / "app" / "svc"
    leaf.mkdir(parents=True)
    _write_config(home, proot)
    monkeypatch.setattr("zab.services.jobs.resolve_mempalace_interpreter", lambda: None)

    argv, cwd = build_argv_for_preset(
        "mempalace_mine",
        {"project_path": str(leaf), "mode": "projects"},
    )
    assert argv[:2] == ["mempalace", "mine"]
    assert str(leaf) in argv
    assert argv[argv.index("--mode") + 1] == "projects"
    assert cwd == str(leaf)


def test_build_argv_mempalace_mine_rejects_outside_roots(monkeypatch, tmp_path_factory) -> None:
    home = tmp_path_factory.mktemp("mine-out")
    monkeypatch.setenv("HOME", str(home))
    proot = home / "projects"
    proot.mkdir()
    outsider = home / "elsewhere" / "x"
    outsider.mkdir(parents=True)
    _write_config(home, proot)

    with pytest.raises(ValueError, match="projects_roots"):
        build_argv_for_preset("mempalace_mine", {"project_path": str(outsider)})


def test_build_argv_mempalace_mine_mode_convos(monkeypatch, tmp_path_factory) -> None:
    home = tmp_path_factory.mktemp("mine-conv")
    monkeypatch.setenv("HOME", str(home))
    proot = home / "projects"
    app = proot / "app1"
    app.mkdir(parents=True)
    _write_config(home, proot)

    argv, _cwd = build_argv_for_preset(
        "mempalace_mine",
        {"project_path": str(app), "mode": "convos"},
    )
    assert argv[argv.index("--mode") + 1] == "convos"


def test_build_argv_conversation_sync() -> None:
    argv, cwd = build_argv_for_preset(
        "conversation_sync",
        {"dry_run": True, "append": True, "providers": ["cursor", "hermes"]},
    )
    assert "python" in argv
    assert "-m" in argv
    assert "zab.services.conversation_sync" in argv
    assert "--dry-run" in argv
    assert "--append" in argv
    assert "--providers" in argv
    assert "cursor,hermes" in argv
    assert cwd
