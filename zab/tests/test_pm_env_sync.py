"""Fusion des jetons PM depuis les .env locaux."""

from __future__ import annotations

import os

import yaml
from dotenv import dotenv_values

from zab.services.pm_env_sync import apply_pm_tokens_from_user_dotenv, sync_pm_tokens_to_user_dotenv


def test_sync_writes_zab_dotenv_from_projects(tmp_path) -> None:
    repo = tmp_path / "skills-repo"
    assert repo.is_dir()
    proot = tmp_path / "projects"
    proot.mkdir()
    proj = proot / "demo-app"
    proj.mkdir()
    (proj / ".env").write_text(
        "GITLAB_TOKEN=glpat-from-demo\nLINEAR_API_KEY=lin_from_demo\nOTHER=x\n",
        encoding="utf-8",
    )

    cfg = tmp_path / ".config" / "zab" / "config.yaml"
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    data["projects_roots"] = [str(proot.resolve())]
    cfg.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    summary = sync_pm_tokens_to_user_dotenv(force=False)
    zab_env = tmp_path / ".config" / "zab" / ".env"
    assert summary["path"] == str(zab_env.resolve())
    assert "GITLAB_TOKEN" in summary["keys_updated"]
    assert "LINEAR_API_KEY" in summary["keys_updated"]
    vals = dotenv_values(zab_env)
    assert vals.get("GITLAB_TOKEN") == "glpat-from-demo"
    assert vals.get("LINEAR_API_KEY") == "lin_from_demo"


def test_apply_loads_custom_task_source_env_token(tmp_path, monkeypatch) -> None:
    cfg = tmp_path / ".config" / "zab" / "config.yaml"
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    data["task_sources"] = [
        {
            "id": "danmdata-gitlab",
            "label": "Danmdata",
            "backend": "gitlab",
            "project_id": 123,
            "env_token": "gitlab_access_token_ntp",
        }
    ]
    cfg.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    zab_env = tmp_path / ".config" / "zab" / ".env"
    zab_env.write_text("gitlab_access_token_ntp=glpat-custom\n", encoding="utf-8")
    monkeypatch.delenv("gitlab_access_token_ntp", raising=False)

    apply_pm_tokens_from_user_dotenv()

    assert os.environ["gitlab_access_token_ntp"] == "glpat-custom"


def test_sync_skips_existing_without_force(tmp_path) -> None:
    proot = tmp_path / "projects"
    proot.mkdir()
    proj = proot / "demo-app"
    proj.mkdir()
    (proj / ".env").write_text("GITLAB_TOKEN=new-token\n", encoding="utf-8")

    cfg = tmp_path / ".config" / "zab" / "config.yaml"
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    data["projects_roots"] = [str(proot.resolve())]
    cfg.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    zab_env = tmp_path / ".config" / "zab" / ".env"
    zab_env.write_text("GITLAB_TOKEN=old-token\n", encoding="utf-8")

    summary = sync_pm_tokens_to_user_dotenv(force=False)
    assert "GITLAB_TOKEN" not in summary["keys_updated"]
    assert "GITLAB_TOKEN" in summary["keys_skipped_already_present"]
    vals = dotenv_values(zab_env)
    assert vals.get("GITLAB_TOKEN") == "old-token"

    summary2 = sync_pm_tokens_to_user_dotenv(force=True)
    assert "GITLAB_TOKEN" in summary2["keys_updated"]
    vals2 = dotenv_values(zab_env)
    assert vals2.get("GITLAB_TOKEN") == "new-token"


def test_tasks_pm_env_sync_route() -> None:
    from fastapi.testclient import TestClient

    from zab.api.app import create_app

    client = TestClient(create_app())
    r = client.post("/api/tasks/pm-env/sync", json={"force": False})
    assert r.status_code == 200
    body = r.json()
    assert "path" in body and "keys_updated" in body
