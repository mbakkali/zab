"""Localisation des jetons task_sources dans les .env."""

from __future__ import annotations

from pathlib import Path

from zab.services.env_token_locate import locate_env_token, task_sources_secret_locations
from zab.user_config import save_user_config


def test_locate_env_token_in_home_dotenv(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    (home / ".env").write_text("NOTION_NOTION_SECRET=ntn_secret\n", encoding="utf-8")

    loc = locate_env_token("NOTION_NOTION_SECRET", "notion")
    assert loc["status"] == "file"
    assert loc["key_used"] == "NOTION_NOTION_SECRET"
    assert loc["path_display"] == "~/.env"
    assert loc["line"] == 1


def test_locate_prefers_local_project_dotenv(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    proj = tmp_path / "projects" / "upfund"
    proj.mkdir(parents=True)
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    (home / ".env").write_text("NOTION_NOTION_SECRET=from_home\n", encoding="utf-8")
    (proj / ".env").write_text("NOTION_NOTION_SECRET=from_project\n", encoding="utf-8")

    loc = locate_env_token(
        "NOTION_NOTION_SECRET",
        "notion",
        local_project_path=str(proj),
    )
    assert loc["status"] == "file"
    assert "upfund" in loc["path"]


def test_task_sources_secret_locations_api_shape(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    save_user_config(
        {
            "task_sources": [
                {
                    "id": "test-notion",
                    "label": "Test",
                    "backend": "notion",
                    "env_token": "NOTION_NOTION_SECRET",
                    "database_id": "abc",
                }
            ]
        }
    )
    (tmp_path / ".env").write_text("NOTION_NOTION_SECRET=x\n", encoding="utf-8")

    out = task_sources_secret_locations()
    assert len(out["sources"]) == 1
    row = out["sources"][0]
    assert row["id"] == "test-notion"
    assert row["status"] == "file"
    assert row["path_display"] == "~/.env"
