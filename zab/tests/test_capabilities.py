from __future__ import annotations

import json

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from zab.api.app import create_app
from zab.cli import app
from zab.services import agent_context


def test_capability_manifest_core_contract() -> None:
    from zab.services.capabilities import get_capabilities

    payload = get_capabilities()

    assert payload["contract"] == "capability-manifest"
    assert payload["contract_version"] == "1.0"
    assert payload["name"] == "zab"
    assert payload["contracts"]["json_cli"] is True
    assert payload["contracts"]["mcp_tools"] is True
    assert payload["contracts"]["http_api"] is True
    capabilities = payload["capabilities"]
    assert isinstance(capabilities, list)
    assert payload["summary"]["total"] == len(capabilities)
    assert payload["total"] == payload["summary"]["total"]
    assert payload["complete"] == payload["summary"]["complete"]
    assert payload["partial"] == payload["summary"]["partial"]
    assert {cap["id"] for cap in capabilities} >= {
        "capabilities.manifest",
        "source.health",
        "research.packet",
        "tasks.list",
        "agent.bootstrap",
        "search.global",
        "connectors.list",
        "connectors.status",
        "tools.catalog",
        "composio.connections",
        "tasks.sources_status",
        "channels.list",
    }
    manifest = next(cap for cap in capabilities if cap["id"] == "capabilities.manifest")
    assert manifest["core"] == "zab.services.capabilities.get_capabilities"
    assert manifest["cli"] == "zab capabilities --json"
    assert manifest["mcp"] == "capabilities"
    assert manifest["api"] == "GET /api/capabilities"
    assert manifest["ui"] == "Capabilities"
    assert manifest["risk"] == "read"
    assert manifest["status"] == "complete"


def test_capabilities_cli_json() -> None:
    result = CliRunner().invoke(app, ["capabilities", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["contract"] == "capability-manifest"
    assert any(cap["id"] == "capabilities.manifest" for cap in payload["capabilities"])


def test_capabilities_api_get_and_head() -> None:
    client = TestClient(create_app())

    r = client.get("/api/capabilities")
    assert r.status_code == 200
    assert r.json()["contract"] == "capability-manifest"
    assert r.json()["total"] == r.json()["summary"]["total"]
    assert r.json()["complete"] > r.json()["partial"]

    head = client.head("/api/capabilities")
    assert head.status_code == 200
    assert head.headers.get("content-type", "").startswith("application/json")
    assert head.text == ""


def test_generic_inspect_api(monkeypatch) -> None:
    monkeypatch.setattr(
        "zab.api.routes.state_index.get_section_item",
        lambda section, key: {"id": key, "section_seen": section},
    )
    client = TestClient(create_app())

    r = client.get("/api/inspect/code-tools/hermes")

    assert r.status_code == 200
    assert r.json()["found"] is True
    assert r.json()["section"] == "code_tools"
    assert r.json()["item"]["id"] == "hermes"


def test_composio_connections_api(monkeypatch) -> None:
    monkeypatch.setattr(
        "zab.api.routes.agent_context.composio_connections",
        lambda **kwargs: {"contract": "zab-composio-connections", "filters": kwargs, "connections": []},
    )
    client = TestClient(create_app())

    r = client.get("/api/composio/connections?toolkit=gmail&active_only=false&resolve_identities=true")

    assert r.status_code == 200
    assert r.json()["contract"] == "zab-composio-connections"
    assert r.json()["filters"] == {"toolkit": "gmail", "active_only": False, "resolve_identities": True}


def test_capabilities_mcp_tool_is_declared_and_callable() -> None:
    tools = agent_context.mcp_tools()

    by_name = {tool["name"]: tool for tool in tools}
    assert "capabilities" in by_name
    assert "capability manifest" in by_name["capabilities"]["description"].lower()
    assert by_name["capabilities"]["inputSchema"]["type"] == "object"
    assert {
        "agent_bootstrap",
        "source_health",
        "research",
        "connectors_list",
        "connector_status",
        "composio_connections",
        "task_sources_status",
        "tasks_list",
        "tasks_sync",
        "task_source_check",
        "channels_list",
        "security_status",
        "memory_status",
        "memory_search",
        "cli_auth_check",
        "system_health_check",
        "project_handoff",
    } <= set(by_name)

    payload = agent_context.call_mcp_tool("capabilities", {})
    assert payload["contract"] == "capability-manifest"


def test_mcp_connectors_and_tasks_agent_contracts(monkeypatch) -> None:
    def fake_list_connectors(**kwargs):
        return {
            "data": [{"id": "gmail", "display_name": "Gmail", "form_count": 1}],
            "pagination": {"total": 1, "page": 1, "limit": kwargs.get("limit", 50)},
        }

    def fake_get_connector(slug):
        return {"id": slug, "display_name": slug.title(), "forms": []}

    monkeypatch.setattr("zab.services.connectors_aggregate.list_connectors", fake_list_connectors)
    monkeypatch.setattr("zab.services.connectors_aggregate.get_connector", fake_get_connector)
    monkeypatch.setattr("zab.services.connectors_check.check_connector_payload", lambda slug: {"slug": slug, "checks": []})
    monkeypatch.setattr(
        "zab.services.agent_context._json_cache",
        lambda filename: {
            "generated_at_utc": "2026-06-08T00:00:00+00:00",
            "sources": [{"id": "linear", "status": "ok", "items": []}],
            "all_tasks": [
                {"identifier": "AGI-1", "title": "Fix connector visibility", "source_label": "Linear", "state": "Todo"}
            ],
        }
        if filename == "tasks_cache.json"
        else None,
    )

    connectors = agent_context.call_mcp_tool("connectors_list", {"include_details": True})
    assert connectors["contract"] == "zab-connectors-catalog"
    assert connectors["connectors"][0]["id"] == "gmail"

    status = agent_context.call_mcp_tool("connector_status", {"slug": "gmail"})
    assert status["found"] is True
    assert status["checks"]["slug"] == "gmail"

    tasks = agent_context.call_mcp_tool("tasks_list", {"q": "connector"})
    assert tasks["contract"] == "zab-tasks-list"
    assert tasks["tasks"][0]["identifier"] == "AGI-1"
