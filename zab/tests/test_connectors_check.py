"""Tests pour zab.services.connectors_check + routes /api/connectors*/check*."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from zab.api.app import create_app
from zab.services import connectors_aggregate, connectors_check


# ── helpers de stub ───────────────────────────────────────────────────


def _row_litellm() -> dict[str, Any]:
    return {
        "id": "litellm",
        "display_name": "LiteLLM",
        "tags": [],
        "forms": [
            {
                "id": "api-litellm",
                "kind": "api",
                "transport_kind": "http",
                "enabled": True,
                "target": "https://litellm.example.com",
                "source_label": "local-tools.yaml",
                "config_path": "/tmp/local-tools.yaml",
                "source_ref": "proxies.litellm",
                "meta": {
                    "base_url": "https://litellm.example.com",
                    "api_key_env": "OPENAI_API_KEY",
                    "auth": "bearer",
                },
            }
        ],
    }


def _row_mcp_stdio() -> dict[str, Any]:
    return {
        "id": "fake-mcp",
        "display_name": "Fake Mcp",
        "tags": [],
        "forms": [
            {
                "id": "mcp-cursor-fake",
                "kind": "mcp",
                "transport_kind": "stdio",
                "enabled": True,
                "target": "command-not-on-path-xyz",
                "source_label": "configs/cursor-mcp.json",
                "config_path": "/tmp/cursor-mcp.json",
                "source_ref": "configs/cursor-mcp.json#fake",
                "meta": {
                    "transport": "stdio",
                    "command": "command-not-on-path-xyz",
                    "args": [],
                    "env_vars": ["EXPECTED_ENV_THAT_IS_MISSING"],
                },
            }
        ],
    }


def _row_composio_active() -> dict[str, Any]:
    return {
        "id": "gmail",
        "display_name": "Gmail",
        "tags": ["composio"],
        "forms": [
            {
                "id": "composio-acct123",
                "kind": "composio",
                "transport_kind": "http",
                "enabled": True,
                "target": "gmail · user@example.com",
                "source_label": "composio",
                "config_path": None,
                "source_ref": "composio/connected_accounts/acct123",
                "meta": {
                    "toolkit_slug": "gmail",
                    "auth_scheme": "OAUTH2",
                    "connected_account_id": "acct123",
                    "status": "ACTIVE",
                },
            }
        ],
    }


def _row_composio_inactive() -> dict[str, Any]:
    row = _row_composio_active()
    row["id"] = "slack"
    row["display_name"] = "Slack"
    row["forms"][0]["id"] = "composio-acct999"
    row["forms"][0]["enabled"] = False
    row["forms"][0]["meta"]["toolkit_slug"] = "slack"
    row["forms"][0]["meta"]["status"] = "INITIATED"
    return row


@pytest.fixture
def stub_aggregate(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    rows = [_row_litellm(), _row_mcp_stdio(), _row_composio_active(), _row_composio_inactive()]

    def fake_get(slug: str) -> dict[str, Any] | None:
        for r in rows:
            if r["id"] == slug:
                return r
        return None

    def fake_list(**_kw: Any) -> dict[str, Any]:
        data = [
            {
                "id": r["id"],
                "display_name": r["display_name"],
                "tags": r.get("tags") or [],
                "form_count": len(r["forms"]),
                "kind_badges": sorted({f["kind"] for f in r["forms"]}),
                "transport_badges": sorted({f["transport_kind"] for f in r["forms"]}),
                "any_enabled": any(f.get("enabled") for f in r["forms"]),
                "preview_target": r["forms"][0].get("target") or "",
            }
            for r in rows
        ]
        return {
            "data": data,
            "pagination": {
                "page": 1,
                "limit": 200,
                "total": len(data),
                "total_pages": 1,
            },
        }

    monkeypatch.setattr(connectors_aggregate, "get_connector", fake_get)
    monkeypatch.setattr(connectors_aggregate, "list_connectors", fake_list)
    return rows


# ── tests service ─────────────────────────────────────────────────────


def test_check_unknown_slug_returns_none(stub_aggregate: list[dict[str, Any]]) -> None:
    assert connectors_check.check_connector_payload("ghost") is None


def test_check_mcp_stdio_detects_missing_command_and_env(
    stub_aggregate: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("EXPECTED_ENV_THAT_IS_MISSING", raising=False)

    payload = connectors_check.check_connector_payload("fake-mcp")
    assert payload is not None
    assert payload["slug"] == "fake-mcp"
    assert payload["total"] >= 2

    ids = [c["id"] for c in payload["checks"]]
    assert any(c.endswith("__cmd") for c in ids), payload["checks"]
    assert any(c.endswith("__envs") for c in ids), payload["checks"]

    statuses = {c["id"].split("__")[-1]: c["status"] for c in payload["checks"]}
    assert statuses["cmd"] == "fail"
    assert statuses["envs"] == "warn"


def test_check_composio_active_vs_inactive(stub_aggregate: list[dict[str, Any]]) -> None:
    ok = connectors_check.check_connector_payload("gmail")
    nok = connectors_check.check_connector_payload("slack")
    assert ok is not None
    assert nok is not None
    assert ok["ok"] >= 1 and ok["fail"] == 0
    assert nok["warn"] >= 1  # désactivé → warn


def test_check_api_litellm_uses_probe_models(
    stub_aggregate: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-xxx")
    captured: dict[str, Any] = {}

    def fake_probe(kind: str) -> dict[str, Any]:
        captured["kind"] = kind
        return {"ok": True, "status_code": 200, "url": "https://x/v1/models"}

    monkeypatch.setattr(connectors_check, "probe_models", fake_probe)
    payload = connectors_check.check_connector_payload("litellm")
    assert payload is not None
    assert captured.get("kind") == "litellm"

    ids = [c["id"] for c in payload["checks"]]
    assert any(c.endswith("__env") for c in ids)
    assert any(c.endswith("__models") for c in ids)
    statuses = {c["id"].split("__")[-1]: c["status"] for c in payload["checks"]}
    assert statuses["env"] == "ok"
    assert statuses["models"] == "ok"


def test_iter_global_checks_emits_registry_then_connectors_then_done(
    stub_aggregate: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(connectors_check, "probe_models", lambda kind: {"ok": True, "status_code": 200})

    events = list(connectors_check.iter_global_checks())
    names = [e["event"] for e in events]
    assert names[0] == "registry"
    assert names[-1] == "done"
    assert names.count("connector") == 4

    registry = events[0]["data"]
    slugs = [entry["slug"] for entry in registry]
    assert {"litellm", "fake-mcp", "gmail", "slack"} <= set(slugs)

    summary = events[-1]["data"]
    assert summary["connectors_total"] == 4
    assert summary["total"] >= 1
    assert summary["ok"] + summary["warn"] + summary["fail"] == summary["total"]


# ── tests routes ──────────────────────────────────────────────────────


def test_route_connector_check_404_unknown(stub_aggregate: list[dict[str, Any]]) -> None:
    client = TestClient(create_app())
    r = client.get("/api/connectors/ghost-slug/check")
    assert r.status_code == 404


def test_route_connector_check_ok(
    stub_aggregate: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.setattr(connectors_check, "probe_models", lambda k: {"ok": True, "status_code": 200})
    client = TestClient(create_app())
    r = client.get("/api/connectors/litellm/check")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["slug"] == "litellm"
    assert body["display_name"] == "LiteLLM"
    assert body["total"] >= 2
    assert isinstance(body["checks"], list)


def test_route_global_check_sse(
    stub_aggregate: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.setattr(connectors_check, "probe_models", lambda k: {"ok": True, "status_code": 200})

    client = TestClient(create_app())
    r = client.get("/api/connectors-check/stream")
    assert r.status_code == 200
    assert "text/event-stream" in r.headers.get("content-type", "")

    events: dict[str, list[dict[str, Any]]] = {}
    current = ""
    for line in r.text.splitlines():
        if line.startswith("event: "):
            current = line[len("event: ") :].strip()
            events.setdefault(current, [])
        elif line.startswith("data: ") and current:
            events[current].append(json.loads(line[len("data: ") :]))

    assert "registry" in events
    assert "connector" in events
    assert "done" in events
    assert len(events["registry"]) == 1
    assert isinstance(events["registry"][0], list)
    assert len(events["connector"]) == 4
    summary = events["done"][0]
    assert summary["connectors_total"] == 4


def test_route_connector_check_stream_per_slug(
    stub_aggregate: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.setattr(connectors_check, "probe_models", lambda k: {"ok": True, "status_code": 200})

    client = TestClient(create_app())
    r = client.get("/api/connectors/litellm/check/stream")
    assert r.status_code == 200
    text = r.text
    assert "event: registry" in text
    assert "event: check" in text
    assert "event: done" in text
