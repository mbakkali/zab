"""Tests wizard `zab channels setup` et persistance credentials."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from zab.cli import app
from zab.services import communication_channels as cc
from zab.services.channels_setup import (
    available_email_connectors,
    build_channel_payload,
    setup_channel_from_payload,
)

runner = CliRunner()


def test_available_email_connectors_detects_gog(monkeypatch) -> None:
    monkeypatch.setattr("zab.services.channels_setup.shutil.which", lambda name: "gog" if name == "gog" else None)
    opts = available_email_connectors()
    assert any(o["connector"] == "gmail" and o["transport"] == "gog" for o in opts)


def _patch_local_channel_store(monkeypatch, state: dict) -> None:
    monkeypatch.setattr("zab.services.communication_channels.get_pg_connection", lambda: (None, None))

    def mock_load_user():
        chans = state.get("communication_channels")
        payload = dict(state)
        payload["communication_channels"] = list(chans) if isinstance(chans, list) else []
        return payload

    def mock_save_user(data):
        state.clear()
        state.update(data)
        return Path("/mock/config.yaml")

    def mock_load_channels():
        channels = state.get("communication_channels")
        if isinstance(channels, list):
            return list(channels)
        return []

    monkeypatch.setattr("zab.services.communication_channels.load_user_config", mock_load_user)
    monkeypatch.setattr("zab.services.communication_channels.save_user_config", mock_save_user)
    monkeypatch.setattr("zab.services.communication_channels.load_channels_config", mock_load_channels)


def test_add_channel_config_persists_credentials(monkeypatch) -> None:
    state: dict = {"communication_channels": []}
    _patch_local_channel_store(monkeypatch, state)

    chan = cc.add_channel_config(
        label="WhatsApp Test",
        channel_type="whatsapp",
        connector="evolution-api",
        org="flowmetrik",
        documentation="https://doc.evolution-api.com/",
        credentials={
            "evolution_api_url": "https://wa.example.com",
            "evolution_api_key": "secret",
            "evolution_instance": "inst",
        },
    )

    assert chan["credentials"]["evolution_instance"] == "inst"
    assert state["communication_channels"][0]["documentation"].startswith("https://")


def test_check_channel_config_persists_status(monkeypatch) -> None:
    state = {
        "communication_channels": [
            {
                "id": "slack-test",
                "label": "Slack Test",
                "type": "slack",
                "connector": "slack",
                "org": "personal",
                "enabled": True,
                "credentials": {"slack_bot_token": "xoxb-test"},
            }
        ]
    }
    _patch_local_channel_store(monkeypatch, state)
    monkeypatch.setattr(
        "zab.services.channel_fetchers.check_slack_connection",
        lambda _ch: ("ok", None),
    )

    result = cc.check_channel_config("slack-test")
    assert result["last_check_status"] == "ok"
    assert state["communication_channels"][0]["last_check_status"] == "ok"


def test_setup_channel_from_payload_writes_then_checks(monkeypatch) -> None:
    state: dict = {"communication_channels": []}
    _patch_local_channel_store(monkeypatch, state)
    monkeypatch.setattr(
        "zab.services.channel_fetchers.check_channel_connection",
        lambda _ch, _now: {"status": "ok", "reason": None, "sync_summary": {"unread_count": 0}, "actions_count": 0},
    )

    payload = build_channel_payload(
        label="WA Setup",
        org="flowmetrik",
        channel_type="whatsapp",
        connector="evolution-api",
        documentation="https://doc.evolution-api.com/",
        credentials={"evolution_api_url": "https://wa.example.com", "evolution_api_key": "k", "evolution_instance": "i"},
    )
    checked = setup_channel_from_payload(payload)
    assert checked["id"] == "wa-setup"
    assert checked["last_check_status"] == "ok"
    assert len(state["communication_channels"]) == 1


def test_channels_setup_cli_whatsapp(monkeypatch) -> None:
    state: dict = {"communication_channels": []}
    _patch_local_channel_store(monkeypatch, state)
    inputs = "\n".join(
        [
            "Mon WhatsApp",
            "flowmetrik",
            "3",  # WhatsApp
            "https://doc.evolution-api.com/",
            "https://wa.example.com",
            "secret-key",
            "my-instance",
            "",
        ]
    )
    with patch(
        "zab.services.channel_fetchers.check_channel_connection",
        lambda _ch, _now: {"status": "ok", "reason": None, "sync_summary": {"unread_count": 0}, "actions_count": 0},
    ):
        result = runner.invoke(app, ["channels", "setup"], input=inputs)
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "Mon WhatsApp" in result.stdout
    assert state["communication_channels"][0]["type"] == "whatsapp"
    assert state["communication_channels"][0]["credentials"]["evolution_instance"] == "my-instance"


def test_channels_setup_help() -> None:
    result = runner.invoke(app, ["channels", "setup", "--help"])
    assert result.exit_code == 0
    assert "Wizard" in result.stdout or "wizard" in result.stdout.lower()
