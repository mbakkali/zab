"""Tests agrégation GET /api/tasks/inbox et parsing task_sources."""

from __future__ import annotations

import yaml
from fastapi.testclient import TestClient

from zab.api.app import create_app
from zab.user_config import task_sources_from_user_config


def test_task_sources_parse_errors(tmp_path):
    cfg = tmp_path / ".config" / "zab" / "config.yaml"
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    data["task_sources"] = [
        "bad",
        {"id": "", "label": "x", "backend": "gitlab", "path_with_namespace": "a/b"},
        {"id": "ok", "label": "OK", "backend": "gitlab", "path_with_namespace": "grp/proj"},
    ]
    cfg.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    sources, errs = task_sources_from_user_config()
    assert len(sources) == 1
    assert sources[0]["id"] == "ok"
    assert any("task_sources[0]" in e for e in errs)
    assert any("id manquant" in e for e in errs)


def test_tasks_inbox_skipped_without_token(tmp_path, monkeypatch):
    cfg = tmp_path / ".config" / "zab" / "config.yaml"
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    data["task_sources"] = [
        {
            "id": "gl1",
            "label": "GitLab test",
            "backend": "gitlab",
            "host": "gitlab.com",
            "path_with_namespace": "foo/bar",
            "routing_doc": "~/README.md",
        },
    ]
    cfg.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    client = TestClient(create_app())
    r = client.get("/api/tasks/inbox")
    assert r.status_code == 200
    body = r.json()
    assert "sources" in body and len(body["sources"]) == 1
    assert body["sources"][0]["status"] == "skipped"
    assert "GITLAB_TOKEN" in (body["sources"][0].get("reason") or "")


def test_tasks_inbox_gitlab_mocked(tmp_path, monkeypatch):
    cfg = tmp_path / ".config" / "zab" / "config.yaml"
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    data["task_sources"] = [
        {
            "id": "gl1",
            "label": "GitLab test",
            "backend": "gitlab",
            "host": "gitlab.com",
            "path_with_namespace": "foo/bar",
        },
    ]
    cfg.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("GITLAB_TOKEN", "glpat-test")

    def fake_fetch(*_a, **_k):
        return [
            {
                "identifier": "#9",
                "title": "Issue test",
                "url": "https://gitlab.com/foo/bar/-/issues/9",
                "state": "opened",
                "updated_at": "2024-01-02T00:00:00Z",
            }
        ]

    monkeypatch.setattr("zab.services.tasks_inbox._fetch_gitlab", fake_fetch)
    client = TestClient(create_app())
    r = client.get("/api/tasks/inbox")
    assert r.status_code == 200
    body = r.json()
    assert body["sources"][0]["status"] == "ok"
    assert len(body["sources"][0]["items"]) == 1
    assert body["sources"][0]["items"][0]["title"] == "Issue test"
