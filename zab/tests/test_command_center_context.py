from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from zab.api.app import create_app
from zab.cli import app
from zab.services import command_center_context as ccc


def _patch_packet_inputs(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(ccc, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(ccc, "user_home", lambda: tmp_path)
    monkeypatch.setattr(ccc, "_now", lambda: datetime(2026, 6, 15, 8, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(
        ccc,
        "get_source_health",
        lambda refresh=False: {
            "contract": "source-health",
            "contract_version": "1.0",
            "generated_at_utc": "2026-06-15T07:00:00+00:00",
            "refresh": refresh,
            "status_counts": {"ok": 1, "local_ok": 1},
            "sources": [
                {
                    "id": "zab_inventory",
                    "kind": "inventory",
                    "status": "ok",
                    "freshness": "fresh",
                    "last_success_at": "2026-06-15T07:00:00+00:00",
                    "safe_message": "Inventory ok.",
                    "warnings": [],
                },
                {
                    "id": "tasks_cache",
                    "kind": "tasks",
                    "status": "local_ok",
                    "freshness": "local",
                    "last_success_at": "2026-06-15T07:00:00+00:00",
                    "safe_message": "Tasks cache ok.",
                    "warnings": [],
                },
            ],
        },
    )
    monkeypatch.setattr(
        ccc.state_index,
        "load_state",
        lambda: {
            "orgs": {"work": {"skills": []}},
            "projects": {
                str(tmp_path / "work"): {
                    "name": "work",
                    "org": "work",
                    "path": str(tmp_path / "work"),
                    "git_repo": True,
                    "git_branch": "main",
                    "skills_count": 1,
                }
            },
            "knowledge_sources": {
                "obsidian": {
                    "id": "obsidian",
                    "kind": "local_markdown_vault",
                    "connected": True,
                    "configured": True,
                    "path": str(tmp_path / "vault"),
                    "notes_count": 3,
                    "validation": {"missing_dirs": []},
                }
            },
        },
    )
    monkeypatch.setattr(
        ccc,
        "fetch_tasks_inbox",
        lambda: {
            "generated_at_utc": "2026-06-15T07:00:00+00:00",
            "total_count": 1,
            "all_tasks": [
                {
                    "identifier": "T-1",
                    "title": "Prepare briefing",
                    "source_label": "Linear",
                    "state": "Todo",
                    "updated_at": "2026-06-15T06:50:00+00:00",
                    "url": "https://example.test/T-1",
                }
            ],
        },
    )
    monkeypatch.setattr(
        ccc.brain,
        "status",
        lambda: {
            "contract": "zab-brain-status",
            "brain_tables": {"brain_entities": 1, "brain_edges": 1},
            "ok": True,
        },
    )
    monkeypatch.setattr(ccc.crons, "load_cached_crons", lambda: [])
    (tmp_path / "work").mkdir()


def test_command_center_context_packet_contract(monkeypatch, tmp_path) -> None:
    _patch_packet_inputs(monkeypatch, tmp_path)

    payload = ccc.build_context_packet(refresh=True)

    assert payload["contract"] == "zab-command-center-context"
    assert payload["refresh"] is True
    assert payload["freshness"]["global_score"] >= 80
    assert payload["delta_24h"]["recent_tasks_count"] == 1
    assert payload["graph"]["edges"]
    assert "markdown" in payload


def test_command_center_context_write_outputs_latest_and_history(monkeypatch, tmp_path) -> None:
    _patch_packet_inputs(monkeypatch, tmp_path)

    payload = ccc.write_context_packet(refresh=False)
    paths = payload["paths"]

    assert ccc.latest_json_path().is_file()
    assert ccc.latest_markdown_path().is_file()
    assert paths["history_json"].endswith("-context-packet.json")
    stored = json.loads(ccc.latest_json_path().read_text(encoding="utf-8"))
    assert stored["contract"] == "zab-command-center-context"
    assert "markdown" not in stored
    assert stored["paths"]["history_json"] == paths["history_json"]


def test_command_center_context_cli_json(monkeypatch, tmp_path) -> None:
    _patch_packet_inputs(monkeypatch, tmp_path)

    result = CliRunner().invoke(app, ["command-center", "context", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["contract"] == "zab-command-center-context"


def test_command_center_context_api(monkeypatch) -> None:
    monkeypatch.setattr(
        ccc,
        "build_context_packet",
        lambda refresh=False: {
            "contract": "zab-command-center-context",
            "contract_version": "1.0",
            "refresh": refresh,
            "markdown": "# hidden in API",
        },
    )
    client = TestClient(create_app())

    response = client.get("/api/command-center/context")
    assert response.status_code == 200
    assert response.json()["contract"] == "zab-command-center-context"
    assert "markdown" not in response.json()

    head = client.head("/api/command-center/context")
    assert head.status_code == 200
