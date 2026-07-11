from __future__ import annotations

import json

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from zab.api.app import create_app
from zab.cli import app
from zab.services import agent_context
from zab.services.research_engine import ResearchRequest, research


def _source_health() -> dict:
    return {
        "contract": "source-health",
        "contract_version": "1.0",
        "generated_at_utc": "2026-06-09T00:00:00+00:00",
        "sources": [
            {
                "id": "zab_inventory",
                "kind": "inventory",
                "status": "ok",
                "freshness": "local",
                "last_checked_at": "2026-06-09T00:00:00+00:00",
                "last_success_at": "2026-06-09T00:00:00+00:00",
                "item_count": 3,
                "safe_message": "ok",
            }
        ],
    }


def test_research_packet_contract_with_mocked_sources(monkeypatch) -> None:
    monkeypatch.setattr("zab.services.research_engine.get_source_health", lambda refresh=False: _source_health())
    monkeypatch.setattr(
        "zab.services.research_engine.agent_context.agent_bootstrap",
        lambda refresh=False: {"commands": {"refresh": "zab sync --json", "security": "zab security status --json"}},
    )
    monkeypatch.setattr(
        "zab.services.research_engine.agent_context.skills_manifest",
        lambda **_: {"total": 1, "skills": [{"key": "zab-orchestrator", "description": "Use Zab safely."}]},
    )
    monkeypatch.setattr(
        "zab.services.research_engine.agent_context.tasks_list",
        lambda **_: {"total": 1, "tasks": [{"identifier": "ZAB-1", "title": "Ship research MVP"}]},
    )
    monkeypatch.setattr(
        "zab.services.research_engine.agent_context.memory_search",
        lambda *_, **__: {"total": 1, "results": [{"source": "memory", "content": "Prior decision."}]},
    )
    monkeypatch.setattr(
        "zab.services.research_engine.agent_context.project_handoff",
        lambda *_, **__: {"found": True, "project": {"name": "zab", "path": "/tmp/zab"}},
    )
    monkeypatch.setattr(
        "zab.services.research_engine.agent_context.search",
        lambda *_, **__: {"total": 1, "data": [{"section": "projects", "key": "zab"}]},
    )

    payload = research(ResearchRequest(query="implement source health", project="zab", mode="plan"))

    assert payload["contract"] == "research-packet"
    assert payload["mode"] == "plan"
    assert payload["project"]["confidence"] == "high"
    assert payload["citations"]
    assert payload["freshness"]["zab_inventory"]["status"] == "local"
    assert "Research Packet" in payload["context_packet_markdown"]
    assert payload["recommended_next_actions"]


def test_research_cli_json(monkeypatch) -> None:
    monkeypatch.setattr(
        agent_context,
        "research",
        lambda query, **kwargs: {
            "contract": "research-packet",
            "contract_version": "1.0",
            "query": query,
            "mode": kwargs.get("mode"),
            "context_packet_markdown": "# Research Packet",
            "citations": [],
            "freshness": {},
            "source_status": [],
            "conflicts": [],
            "recommended_next_actions": [],
            "warnings": [],
        },
    )

    result = CliRunner().invoke(app, ["research", "comment rendre Zab dynamique ?", "--project", "zab", "--mode", "plan", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["contract"] == "research-packet"
    assert payload["query"] == "comment rendre Zab dynamique ?"


def test_research_api(monkeypatch) -> None:
    monkeypatch.setattr(
        agent_context,
        "research",
        lambda query, **kwargs: {
            "contract": "research-packet",
            "contract_version": "1.0",
            "query": query,
            "mode": kwargs.get("mode"),
            "context_packet_markdown": "# Research Packet",
            "citations": [],
            "freshness": {},
            "source_status": [],
            "conflicts": [],
            "recommended_next_actions": [],
            "warnings": [],
        },
    )
    client = TestClient(create_app())

    r = client.post("/api/research", json={"query": "review diff", "project": "zab", "mode": "review"})

    assert r.status_code == 200
    assert r.json()["contract"] == "research-packet"
    assert r.json()["mode"] == "review"


def test_research_mcp_tool_declared_and_callable(monkeypatch) -> None:
    monkeypatch.setattr(
        agent_context,
        "research",
        lambda query, **kwargs: {
            "contract": "research-packet",
            "contract_version": "1.0",
            "query": query,
            "mode": kwargs.get("mode"),
            "context_packet_markdown": "# Research Packet",
            "citations": [],
            "freshness": {},
            "source_status": [],
            "conflicts": [],
            "recommended_next_actions": [],
            "warnings": [],
        },
    )
    by_name = {tool["name"]: tool for tool in agent_context.mcp_tools()}

    assert "research" in by_name
    payload = agent_context.call_mcp_tool("research", {"query": "plan", "mode": "plan"})
    assert payload["contract"] == "research-packet"
