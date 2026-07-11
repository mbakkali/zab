from __future__ import annotations

import json

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from zab.api.app import create_app
from zab.cli import app
from zab.services import agent_context
from zab.services.source_health import ALLOWED_SOURCE_STATUSES, get_source_health


def test_source_health_contract_masks_secret_values(monkeypatch) -> None:
    monkeypatch.setattr(
        "zab.services.source_health.agent_context.task_sources_status",
        lambda: {
            "cache_present": True,
            "cache_generated_at_utc": "2026-06-09T00:00:00+00:00",
            "sources": [
                {
                    "id": "linear",
                    "env_token": "LINEAR_API_KEY",
                    "token_present": True,
                    "cached_items_count": 2,
                }
            ],
        },
    )

    payload = get_source_health()

    assert payload["contract"] == "source-health"
    assert payload["contract_version"] == "1.0"
    assert payload["sources"]
    assert all(row["status"] in ALLOWED_SOURCE_STATUSES for row in payload["sources"])
    dumped = json.dumps(payload)
    assert "LINEAR_API_KEY" in dumped
    assert "super-secret-value" not in dumped
    assert all(row["auth"].get("secret_values_exposed") is False for row in payload["sources"])


def test_source_health_missing_sources_are_structured(monkeypatch) -> None:
    monkeypatch.setattr(
        "zab.services.source_health.agent_context.tasks_list",
        lambda **_: {
            "contract": "zab-tasks-list",
            "cache_present": False,
            "total": 0,
            "message": "No local tasks cache.",
        },
    )

    payload = get_source_health()
    tasks_cache = next(row for row in payload["sources"] if row["id"] == "tasks_cache")

    assert tasks_cache["status"] == "not_verified"
    assert tasks_cache["warnings"]


def test_source_health_cli_json(monkeypatch) -> None:
    monkeypatch.setattr(
        agent_context,
        "source_health",
        lambda refresh=False: {
            "contract": "source-health",
            "contract_version": "1.0",
            "generated_at_utc": "2026-06-09T00:00:00+00:00",
            "refresh": refresh,
            "status_counts": {"ok": 1},
            "sources": [],
        },
    )

    result = CliRunner().invoke(app, ["source-health", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["contract"] == "source-health"
    assert payload["refresh"] is False


def test_source_health_api_get_and_head(monkeypatch) -> None:
    monkeypatch.setattr(
        agent_context,
        "source_health",
        lambda refresh=False: {
            "contract": "source-health",
            "contract_version": "1.0",
            "generated_at_utc": "2026-06-09T00:00:00+00:00",
            "refresh": refresh,
            "status_counts": {"ok": 1},
            "sources": [],
        },
    )
    client = TestClient(create_app())

    r = client.get("/api/source-health")
    assert r.status_code == 200
    assert r.json()["contract"] == "source-health"

    head = client.head("/api/source-health")
    assert head.status_code == 200
    assert head.text == ""
