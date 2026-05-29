"""Isolation HOME + dépôt skills minimal pour l’API dashboard (skills_root dans config.yaml)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from zab import paths
from zab.paths import config_dir, data_dir


@pytest.fixture(autouse=True)
def zab_isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    def xdg_config_home() -> Path:
        return (Path(os.environ["HOME"]).expanduser().resolve() / ".config")

    def xdg_data_home() -> Path:
        return (Path(os.environ["HOME"]).expanduser().resolve() / ".local" / "share")

    monkeypatch.setattr(paths, "xdg_config_home", xdg_config_home)
    monkeypatch.setattr(paths, "xdg_data_home", xdg_data_home)
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = tmp_path / "skills-repo"
    repo.mkdir(parents=True)
    (repo / "orgs").mkdir()
    (repo / "configs").mkdir()
    (repo / "configs" / "cursor-mcp.json").write_text("{}", encoding="utf-8")
    (repo / "configs" / "claude-desktop-mcp.json").write_text("{}", encoding="utf-8")
    cfg_d = config_dir()
    cfg_d.mkdir(parents=True)
    (cfg_d / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "skills_roots": [str(repo.resolve())],
                "projects_roots": [],
                "cli_watchlist": [],
                "tracked_env_extra": [],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    data_dir().mkdir(parents=True, exist_ok=True)
