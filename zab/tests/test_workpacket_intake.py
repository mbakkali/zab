from __future__ import annotations

import json

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from zab.api.app import create_app
from zab.cli import app
from zab.services import agent_context
from zab.services.workpacket_intake import get_global_rule, intake_from_params


def test_workpacket_intake_rule_contract() -> None:
    payload = get_global_rule()

    assert payload["contract"] == "workpacket-intake-rule"
    assert payload["contract_version"] == "1.0"
    assert "detected" in payload["state_machine"]
    assert "closed" in payload["state_machine"]
    assert any(level["level"] == "L3_approval_before_external_action" for level in payload["authority_levels"])
    assert any("No packet can close" in rule for rule in payload["invariants"])


def test_workpacket_intake_goal_contract() -> None:
    payload = intake_from_params(
        "/goal /Users/mbakkali/projects/flowmetrik-cowork/docs/cowork-maintenance/plan-regle-globale-workpacket-intake-zab-2026-07-12.md\n"
        "\n"
        "développe ce plan\n"
        "Et teste le",
        source="codex",
        project="zab",
        requested_by="Mehdi",
    )

    packet = payload["workpacket"]
    assert payload["contract"] == "workpacket-intake"
    assert payload["event_type"]["type"] == "goal"
    assert payload["event_type"]["action"] == "create_parent_packet"
    assert packet["should_create"] is True
    assert packet["state"] == "detected"
    assert packet["owner"] == "Mehdi"
    assert packet["authority"]["level"] == "L2_local_write"
    assert packet["idempotency_key"].startswith("wp-")
    assert any(row["id"] == "parent_goal" for row in packet["required_sources"])
    assert any(row["id"] == "code_projection" for row in packet["required_projections"])
    assert "Work Packet Intake" in payload["markdown"]


def test_workpacket_intake_external_signal_requires_approval_and_all_projections() -> None:
    payload = intake_from_params(
        "Réponds à ce mail Gmail, puis mets Attio à jour avec le deal et le contact.",
        source="manual",
        project="flowmetrik-cowork",
    )

    packet = payload["workpacket"]
    assert payload["event_type"]["type"] == "human_message"
    assert packet["priority"] == "P2"
    assert packet["authority"]["requires_human_approval"] is True
    assert packet["authority"]["level"] == "L3_approval_before_external_action"
    assert any(gate["id"] == "human_approval_required" for gate in packet["policy_gates"])
    projection_ids = {row["id"] for row in packet["required_projections"]}
    assert {"crm_projection", "communication_projection"} <= projection_ids
    assert any("Human approval" in item for item in packet["definition_of_done"])


def test_workpacket_intake_harness_noise_is_closed_without_packet() -> None:
    payload = intake_from_params("<environment_context><recommended_plugins>tool schema</recommended_plugins></environment_context>")

    assert payload["event_type"]["type"] == "harness_noise"
    assert payload["workpacket"]["should_create"] is False
    assert payload["workpacket"]["state"] == "closed"
    assert payload["workpacket"]["authority"]["level"] == "L0_ignore_or_record"


def test_workpacket_cli_json_and_rule() -> None:
    runner = CliRunner()

    rule = runner.invoke(app, ["workpacket", "rule", "--json"])
    assert rule.exit_code == 0, rule.output
    assert json.loads(rule.stdout)["contract"] == "workpacket-intake-rule"

    result = runner.invoke(app, ["workpacket", "intake", "développe le plan et teste le", "--source", "codex", "--project", "zab", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["contract"] == "workpacket-intake"
    assert payload["workpacket"]["authority"]["level"] == "L2_local_write"


def test_workpacket_api_get_head_and_post() -> None:
    client = TestClient(create_app())

    rule = client.get("/api/workpackets/intake-rule")
    assert rule.status_code == 200
    assert rule.json()["contract"] == "workpacket-intake-rule"

    head = client.head("/api/workpackets/intake-rule")
    assert head.status_code == 200
    assert head.text == ""

    intake = client.post(
        "/api/workpackets/intake",
        json={"signal": "prépare une réponse email sans envoyer", "source": "manual", "project": "flowmetrik-cowork"},
    )
    assert intake.status_code == 200
    payload = intake.json()
    assert payload["contract"] == "workpacket-intake"
    assert "markdown" not in payload
    assert payload["workpacket"]["authority"]["requires_human_approval"] is True


def test_workpacket_mcp_tools_declared_and_callable() -> None:
    by_name = {tool["name"]: tool for tool in agent_context.mcp_tools()}

    assert "workpacket_intake_rule" in by_name
    assert "workpacket_intake" in by_name
    assert by_name["workpacket_intake"]["inputSchema"]["required"] == ["signal"]

    rule = agent_context.call_mcp_tool("workpacket_intake_rule", {})
    assert rule["contract"] == "workpacket-intake-rule"

    payload = agent_context.call_mcp_tool("workpacket_intake", {"signal": "audit puis propose un plan", "source": "codex"})
    assert payload["contract"] == "workpacket-intake"
    assert payload["workpacket"]["should_create"] is True
