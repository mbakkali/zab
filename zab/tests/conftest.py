"""Isolation HOME + dépôt skills minimal pour l’API dashboard (skills_root dans config.yaml)."""

from __future__ import annotations

import yaml
import pytest


@pytest.fixture(autouse=True)
def zab_isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = tmp_path / "skills-repo"
    repo.mkdir(parents=True)
    (repo / "orgs").mkdir()
    (repo / "configs").mkdir()
    (repo / "configs" / "cursor-mcp.json").write_text("{}", encoding="utf-8")
    (repo / "configs" / "claude-desktop-mcp.json").write_text("{}", encoding="utf-8")
    cfg_d = tmp_path / ".config" / "zab"
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
