"""Tests d'intégration pour les endpoints API des canaux de communication."""

from fastapi.testclient import TestClient
import pytest

from zab.api.app import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


@pytest.fixture
def sample_channels() -> list[dict]:
    return [
        {
            "id": "email-work",
            "label": "Work email",
            "type": "email",
            "connector": "gog",
            "org": "acme",
            "email_address": "work@example.com",
            "enabled": True,
        }
    ]


def test_api_get_channels(client, monkeypatch, tmp_path, sample_channels) -> None:
    """Vérifie l'endpoint GET /api/channels."""
    monkeypatch.setattr("zab.services.communication_channels.data_dir", lambda: tmp_path)
    monkeypatch.setattr("zab.services.communication_channels.load_channels_config", lambda: sample_channels)

    response = client.get("/api/channels")
    assert response.status_code == 200
    data = response.json()
    assert "channels" in data
    assert "action_items" in data
    assert len(data["channels"]) == 1


def test_api_sync_channels(client, monkeypatch, tmp_path, sample_channels) -> None:
    """Vérifie l'endpoint POST /api/channels/sync."""
    monkeypatch.setattr("zab.services.communication_channels.data_dir", lambda: tmp_path)
    monkeypatch.setattr("zab.services.communication_channels.load_channels_config", lambda: sample_channels)

    response = client.post("/api/channels/sync")
    assert response.status_code == 200
    data = response.json()
    assert "generated_at_utc" in data
    assert len(data["channels"]) == 1


def test_api_add_channel(client, monkeypatch, tmp_path) -> None:
    """Vérifie l'endpoint POST /api/channels/add."""
    monkeypatch.setattr("zab.services.communication_channels.data_dir", lambda: tmp_path)
    monkeypatch.setattr("zab.services.communication_channels.load_channels_config", lambda: [])
    
    body = {
        "label": "Slack Carrefour",
        "type": "slack",
        "connector": "slack",
        "email_address": None,
        "org": "carrefour"
    }
    response = client.post("/api/channels/add", json=body)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["channel"]["id"] == "slack-carrefour"


def test_api_dashboard_stats(client, monkeypatch, tmp_path) -> None:
    """Vérifie l'endpoint GET /api/dashboard/stats."""
    monkeypatch.setattr("zab.services.communication_channels.data_dir", lambda: tmp_path)
    
    # Mock tasks inbox
    def mock_fetch_tasks():
        return {"total_count": 42, "all_tasks": []}
    monkeypatch.setattr("zab.services.tasks_inbox.fetch_tasks_inbox", mock_fetch_tasks)
    
    response = client.get("/api/dashboard/stats")
    assert response.status_code == 200
    data = response.json()
    assert "unread_emails_count" in data
    assert data["total_tasks_count"] == 42
    assert "urgent_actions_count" in data


def test_list_channels_uses_cached_tool_status_without_live_probe(monkeypatch) -> None:
    """Sans sonde live, le statut vient du catalogue plutôt que de rester `unknown`."""
    from zab.services.conversation_ledger import channel_bindings

    monkeypatch.setattr(
        channel_bindings,
        "load_channel_bindings",
        lambda: [
            {"channel_id": "c1", "channel_type": "gmail", "label": "C1", "tool_id": "t-warn"},
            {"channel_id": "c2", "channel_type": "gmail", "label": "C2", "tool_id": "t-skipped"},
        ],
    )
    catalog = {
        "t-warn": {"tool": {"status": "warn", "status_reason": "connector absent", "last_checked_at_utc": "2026-07-31T08:00:00+00:00"}},
        "t-skipped": {"tool": {"status": "skipped", "status_reason": "probe inconnue"}},
    }
    monkeypatch.setattr(channel_bindings.tool_catalog, "get_tool", lambda tid: catalog.get(tid))

    def _boom(_binding):  # la version non-live ne doit lancer aucune sonde
        raise AssertionError("check_channel_binding must not run when check=False")

    monkeypatch.setattr(channel_bindings, "check_channel_binding", _boom)

    out = channel_bindings.list_channels(check=False)
    by_id = {c["channel_id"]: c for c in out["channels"]}
    assert by_id["c1"]["last_check_status"] == "degraded"
    assert by_id["c1"]["last_check_source"] == "tool_catalog_cache"
    assert by_id["c1"]["last_checked_at"] == "2026-07-31T08:00:00+00:00"
    # `skipped` n'est pas un verdict : on ne fabrique pas de statut.
    assert "last_check_status" not in by_id["c2"]
    assert out["summary"]["degraded"] == 1
