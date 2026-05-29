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
