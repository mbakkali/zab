"""Tests agrégation GET /api/tasks/inbox et parsing task_sources."""

from __future__ import annotations

import yaml
from fastapi.testclient import TestClient

from zab.api.app import create_app
from zab.services.tasks_inbox import _fetch_notion
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


def test_notion_identifier_keeps_full_page_id(monkeypatch):
    page_id = "35e20277-4e9e-8163-95b3-c6f32384b0f4"

    class _Response:
        status_code = 200

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {
                "results": [
                    {
                        "id": page_id,
                        "url": "https://app.notion.com/p/example",
                        "last_edited_time": "2026-05-12T12:52:00.000Z",
                        "properties": {
                            "Name": {
                                "type": "title",
                                "title": [{"plain_text": "Arnaud Baudel - Contact MIPIM"}],
                            }
                        },
                    }
                ]
            }

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        @staticmethod
        def post(*args, **kwargs):
            return _Response()

    monkeypatch.setattr("zab.services.tasks_inbox.httpx.Client", _Client)

    rows = _fetch_notion("database", "secret", "Name")

    assert rows[0]["identifier"] == page_id
    assert rows[0]["display_identifier"] == "35e20277…84b0f4"


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


def test_tasks_inbox_reads_token_from_local_project_dotenv(tmp_path, monkeypatch):
    cfg = tmp_path / ".config" / "zab" / "config.yaml"
    project = tmp_path / "project"
    project.mkdir()
    (project / ".env").write_text("gitlab_access_token_ntp=glpat-project\n", encoding="utf-8")

    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    data["task_sources"] = [
        {
            "id": "danmdata-gitlab",
            "label": "GitLab projet",
            "backend": "gitlab",
            "host": "gitlab.com",
            "project_id": 123,
            "env_token": "gitlab_access_token_ntp",
            "local_project_path": str(project),
        },
    ]
    cfg.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    monkeypatch.delenv("gitlab_access_token_ntp", raising=False)
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)

    seen: dict[str, str] = {}

    def fake_fetch(_host, _project_ref, token, _assignee_username):
        seen["token"] = token
        return [
            {
                "identifier": "#7",
                "title": "Depuis .env local",
                "url": "https://gitlab.com/foo/bar/-/issues/7",
                "state": "opened",
                "updated_at": "2024-01-03T00:00:00Z",
            }
        ]

    monkeypatch.setattr("zab.services.tasks_inbox._fetch_gitlab", fake_fetch)
    client = TestClient(create_app())
    body = client.get("/api/tasks/inbox").json()

    assert seen["token"] == "glpat-project"
    assert body["sources"][0]["status"] == "ok"
    assert body["sources"][0]["items"][0]["title"] == "Depuis .env local"
    assert body["env_hints"]["gitlab_access_token_ntp"] is True


def _write_single_gitlab_source(tmp_path):
    """Helper : écrit un task_sources GitLab unique dans le config.yaml du HOME isolé."""
    cfg = tmp_path / ".config" / "zab" / "config.yaml"
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    data["task_sources"] = [
        {
            "id": "gl-check",
            "label": "GitLab à tester",
            "backend": "gitlab",
            "host": "gitlab.com",
            "path_with_namespace": "foo/bar",
        },
    ]
    cfg.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_check_single_source_unknown_id_returns_404(tmp_path):
    _write_single_gitlab_source(tmp_path)
    client = TestClient(create_app())
    r = client.post("/api/tasks/sources/does-not-exist/check")
    assert r.status_code == 404


def test_check_single_source_skipped_without_token(tmp_path, monkeypatch):
    _write_single_gitlab_source(tmp_path)
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    monkeypatch.delenv("gitlab_access_token_ntp", raising=False)
    monkeypatch.delenv("gitlab_access_token_mehdi_group", raising=False)
    client = TestClient(create_app())
    r = client.post("/api/tasks/sources/gl-check/check")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "gl-check"
    assert body["status"] == "skipped"
    assert body["token_present"] is False
    assert "GITLAB_TOKEN" in (body.get("reason") or "")
    assert "checked_at_utc" in body


def test_check_single_source_ok_updates_cache(tmp_path, monkeypatch):
    _write_single_gitlab_source(tmp_path)
    monkeypatch.setenv("GITLAB_TOKEN", "glpat-test")

    monkeypatch.setattr(
        "zab.services.tasks_inbox._fetch_gitlab",
        lambda *_a, **_k: [
            {
                "identifier": "#1",
                "title": "T",
                "url": "https://gitlab.com/foo/bar/-/issues/1",
                "state": "opened",
                "updated_at": "2024-01-01T00:00:00Z",
            }
        ],
    )
    client = TestClient(create_app())
    full = client.get("/api/tasks/inbox").json()
    assert full["sources"][0]["status"] == "ok"

    r = client.post("/api/tasks/sources/gl-check/check")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["token_present"] is True
    assert len(body["items"]) == 1

    refreshed = client.get("/api/tasks/inbox").json()
    assert refreshed["sources"][0]["status"] == "ok"
    assert refreshed["sources"][0]["items"][0]["identifier"] == "#1"


def test_check_single_source_http_error_reflected(tmp_path, monkeypatch):
    _write_single_gitlab_source(tmp_path)
    monkeypatch.setenv("GITLAB_TOKEN", "glpat-test")

    import httpx as _httpx

    def _boom(*_a, **_k):
        req = _httpx.Request("GET", "https://gitlab.com")
        resp = _httpx.Response(404, request=req)
        raise _httpx.HTTPStatusError("404", request=req, response=resp)

    monkeypatch.setattr("zab.services.tasks_inbox._fetch_gitlab", _boom)
    client = TestClient(create_app())
    r = client.post("/api/tasks/sources/gl-check/check")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "error"
    assert "404" in (body.get("reason") or "")
    assert body["token_present"] is True


# --- Plane -----------------------------------------------------------------

_PLANE_PROJECT_ID = "11111111-2222-3333-4444-555555555555"


def _plane_transport(seen: list):
    """Instance Plane factice : un projet, des états, deux pages de work items."""
    import httpx as _httpx

    states = [
        {"id": "st-todo", "name": "Todo", "group": "unstarted"},
        {"id": "st-done", "name": "Done", "group": "completed"},
        {"id": "st-cancel", "name": "Canceled", "group": "cancelled"},
        {"id": "st-review", "name": "In Review", "group": "started"},
    ]
    page_1 = {
        "results": [
            {"id": "w1", "sequence_id": 12, "name": "Open task", "state": "st-todo",
             "updated_at": "2026-01-03T00:00:00Z", "archived_at": None, "is_draft": False},
            {"id": "w2", "sequence_id": 11, "name": "Closed task", "state": "st-done",
             "updated_at": "2026-01-02T00:00:00Z"},
        ],
        "next_page_results": True,
        "next_cursor": "100:1:0",
    }
    page_2 = {
        "results": [
            {"id": "w3", "sequence_id": 10, "name": "Cancelled task", "state": "st-cancel",
             "updated_at": "2026-01-01T00:00:00Z"},
            {"id": "w4", "sequence_id": 9, "name": "Archived task", "state": "st-todo",
             "updated_at": "2026-01-01T00:00:00Z", "archived_at": "2026-01-01T00:00:00Z"},
            {"id": "w5", "sequence_id": 8, "name": "Under review", "state": "st-review",
             "updated_at": "2025-12-31T00:00:00Z"},
        ],
        "next_page_results": False,
        "next_cursor": "100:2:0",
    }

    def handler(request: _httpx.Request) -> _httpx.Response:
        seen.append(request)
        path = request.url.path
        prefix = "/api/v1/workspaces/acme/"
        assert path.startswith(prefix), path
        rest = path[len(prefix):]
        if rest == "projects/":
            return _httpx.Response(200, json={"results": [
                {"id": "other", "identifier": "OPS"},
                {"id": _PLANE_PROJECT_ID, "identifier": "ENG"},
            ], "next_page_results": False})
        if rest == f"projects/{_PLANE_PROJECT_ID}/states/":
            return _httpx.Response(200, json={"results": states, "next_page_results": False})
        if rest == f"projects/{_PLANE_PROJECT_ID}/work-items/":
            cursor = request.url.params.get("cursor")
            return _httpx.Response(200, json=page_2 if cursor == "100:1:0" else page_1)
        return _httpx.Response(404, json={"detail": "not found"})

    return _httpx.MockTransport(handler)


def _mock_plane_http(monkeypatch, seen: list) -> None:
    import httpx as _httpx

    real_client = _httpx.Client
    transport = _plane_transport(seen)
    monkeypatch.setattr(
        "zab.services.tasks_inbox.httpx.Client",
        lambda **kw: real_client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )


def test_plane_fetch_paginates_and_skips_closed_items(monkeypatch):
    from zab.services.tasks_inbox import _fetch_plane

    seen: list = []
    _mock_plane_http(monkeypatch, seen)

    rows = _fetch_plane(
        "plane-test-key",
        api_url="http://plane.internal:8080/",
        workspace="acme",
        project="ENG",
        public_url="https://plane.example.com",
    )

    assert [r["identifier"] for r in rows] == ["ENG-12", "ENG-8"]
    assert rows[0] == {
        "identifier": "ENG-12",
        "title": "Open task",
        "url": "https://plane.example.com/acme/browse/ENG-12/",
        "state": "Todo",
        "updated_at": "2026-01-03T00:00:00Z",
        "source_label": "Plane",
    }
    assert rows[1]["state"] == "In Review"
    # Lecture seule, clé dans X-Api-Key (pas de Bearer), pagination par curseur.
    assert {req.method for req in seen} == {"GET"}
    assert all(req.headers.get("x-api-key") == "plane-test-key" for req in seen)
    assert all("authorization" not in req.headers for req in seen)
    work_item_calls = [req for req in seen if req.url.path.endswith("/work-items/")]
    assert [req.url.params.get("cursor") for req in work_item_calls] == [None, "100:1:0"]
    assert work_item_calls[0].url.params.get("order_by") == "-updated_at"


def test_plane_fetch_accepts_project_uuid_and_reports_unknown_project(monkeypatch):
    import pytest

    from zab.services.tasks_inbox import _fetch_plane

    _mock_plane_http(monkeypatch, [])
    rows = _fetch_plane("k", api_url="http://plane.internal", workspace="acme", project=_PLANE_PROJECT_ID)
    assert rows[0]["identifier"] == "ENG-12"
    assert rows[0]["url"] == "http://plane.internal/acme/browse/ENG-12/"

    with pytest.raises(RuntimeError, match="NOPE"):
        _fetch_plane("k", api_url="http://plane.internal", workspace="acme", project="NOPE")


def _write_task_sources(tmp_path, sources):
    cfg = tmp_path / ".config" / "zab" / "config.yaml"
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    data["task_sources"] = sources
    cfg.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _clear_plane_env(monkeypatch):
    for name in ("PLANE_API_KEY", "PLANE_URL", "PLANE_PUBLIC_URL", "PLANE_WORKSPACE", "PLANE_PROJECT"):
        monkeypatch.delenv(name, raising=False)


def test_task_sources_parse_plane_entry(tmp_path):
    _write_task_sources(tmp_path, [
        {"id": "eng", "label": "Eng (Plane)", "backend": "plane", "workspace": "acme", "project": "ENG"},
        {"id": "bad", "label": "Bad", "backend": "jira"},
    ])
    sources, errs = task_sources_from_user_config()
    assert len(sources) == 1
    entry = sources[0]
    assert entry["backend"] == "plane"
    assert entry["env_token"] == "PLANE_API_KEY"
    assert entry["workspace"] == "acme"
    assert entry["project"] == "ENG"
    assert entry["api_url"] is None and entry["public_url"] is None
    assert any("gitlab|linear|plane|notion|github" in e for e in errs)


def test_tasks_inbox_plane_settings_from_entry_then_env(tmp_path, monkeypatch):
    _write_task_sources(tmp_path, [
        {"id": "eng", "label": "Eng (Plane)", "backend": "plane", "project": "ENG"},
    ])
    _clear_plane_env(monkeypatch)
    monkeypatch.setenv("PLANE_API_KEY", "plane-test-key")
    monkeypatch.setenv("PLANE_URL", "http://plane.internal:8080/")
    monkeypatch.setenv("PLANE_WORKSPACE", "acme")
    monkeypatch.setenv("PLANE_PROJECT", "IGNORED")  # le champ de l'entrée prime

    seen: dict = {}

    def fake_fetch(token, **settings):
        seen["token"] = token
        seen.update(settings)
        return [{"identifier": "ENG-1", "title": "T", "url": "u", "state": "Todo",
                 "updated_at": "2026-01-01T00:00:00Z", "source_label": "Plane"}]

    monkeypatch.setattr("zab.services.tasks_inbox._fetch_plane", fake_fetch)
    body = TestClient(create_app()).get("/api/tasks/inbox").json()

    assert body["sources"][0]["status"] == "ok"
    assert body["sources"][0]["env_token"] == "PLANE_API_KEY"
    assert seen == {
        "token": "plane-test-key",
        "api_url": "http://plane.internal:8080",
        "workspace": "acme",
        "project": "ENG",
        "public_url": "http://plane.internal:8080",
    }


def test_tasks_inbox_plane_incomplete_config_is_an_error_without_network(tmp_path, monkeypatch):
    _write_task_sources(tmp_path, [{"id": "eng", "label": "Eng (Plane)", "backend": "plane"}])
    _clear_plane_env(monkeypatch)
    monkeypatch.setenv("PLANE_API_KEY", "plane-test-key")

    def no_network(*_a, **_k):
        raise AssertionError("no HTTP call expected")

    monkeypatch.setattr("zab.services.tasks_inbox._fetch_plane", no_network)
    body = TestClient(create_app()).get("/api/tasks/inbox").json()

    source = body["sources"][0]
    assert source["status"] == "error"
    for name in ("PLANE_URL", "PLANE_WORKSPACE", "PLANE_PROJECT"):
        assert name in source["reason"]
    assert "plane-test-key" not in str(body)


def test_tasks_sources_add_recognises_plane_urls(tmp_path, monkeypatch):
    monkeypatch.setattr("zab.services.tasks_inbox.sync_tasks_inbox", lambda: {})
    client = TestClient(create_app())

    r = client.post("/api/tasks/sources/add", json={"url": "https://plane.example.com/acme/browse/ENG-42/"})
    assert r.status_code == 200, r.text
    assert r.json()["source"] == {
        "id": "plane-acme-eng",
        "label": "Plane acme/ENG",
        "backend": "plane",
        "api_url": "https://plane.example.com",
        "public_url": "https://plane.example.com",
        "workspace": "acme",
        "project": "ENG",
        "url": "https://plane.example.com/acme/browse/ENG-42/",
    }

    r = client.post(
        "/api/tasks/sources/add",
        json={"url": f"https://app.plane.so/acme/projects/{_PLANE_PROJECT_ID}/issues/"},
    )
    assert r.status_code == 200, r.text
    source = r.json()["source"]
    assert source["api_url"] == "https://api.plane.so"
    assert source["public_url"] == "https://app.plane.so"
    assert source["project"] == _PLANE_PROJECT_ID

    sources, errs = task_sources_from_user_config()
    assert [s["backend"] for s in sources] == ["plane", "plane"]
    assert not errs

    r = client.post("/api/tasks/sources/add", json={"url": "https://example.com/acme/settings/"})
    assert r.status_code == 400
