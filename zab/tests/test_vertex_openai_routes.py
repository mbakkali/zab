"""Routes proxy Vertex OpenAI-compatible et agrégation runtimes."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from zab.api.app import create_app


def test_models_runtimes_contains_vertex_block() -> None:
    client = TestClient(create_app())
    r = client.get("/api/model-runtimes")
    assert r.status_code == 200
    data = r.json()
    assert "runtimes" in data
    ids = {x.get("id") for x in data["runtimes"] if isinstance(x, dict)}
    assert "vertex_openai_via_zab" in ids


def test_vertex_openai_status_without_project(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GCP_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    client = TestClient(create_app())
    r = client.get("/api/vertex-openai/status")
    assert r.status_code == 200
    j = r.json()
    assert j.get("ready") is False
    assert j.get("project_configured") is False


def test_vertex_openai_models_list() -> None:
    client = TestClient(create_app())
    r = client.get("/api/vertex-openai/v1/models")
    assert r.status_code == 200
    j = r.json()
    assert j.get("object") == "list"
    assert isinstance(j.get("data"), list) and len(j["data"]) >= 1


def test_vertex_chat_invalid_json() -> None:
    client = TestClient(create_app())
    r = client.post("/api/vertex-openai/v1/chat/completions", content=b"not-json")
    assert r.status_code == 400


def test_vertex_chat_missing_credentials_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "fake-project-for-test")
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    client = TestClient(create_app())
    r = client.post(
        "/api/vertex-openai/v1/chat/completions",
        content=json.dumps({"model": "gemini-2.0-flash", "messages": [{"role": "user", "content": "hi"}]}),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 503
