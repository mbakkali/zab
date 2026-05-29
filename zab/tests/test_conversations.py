"""Tests service conversations (health, providers payload)."""

from __future__ import annotations

import pytest

from zab.services import conversations


def test_build_providers_payload_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "zab.services.conversations.memory_db.fetch_conversation_provider_document_counts",
        lambda: {"cursor": 1, "claude": 0, "codex": 0, "hermes": 0, "gemini": 0, "kimi": 0},
    )
    p = conversations.build_providers_payload()
    assert "providers" in p
    assert len(p["providers"]) >= 6
    ids = {x["id"] for x in p["providers"]}
    assert "cursor" in ids
    assert "gemini" in ids


def test_build_health_payload_no_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "zab.services.conversations.memory_db.fetch_status",
        lambda: {
            "configured": False,
            "connected": False,
            "psycopg_available": False,
            "document_count": None,
            "chunk_count": None,
            "error": "no dsn",
        },
    )
    h = conversations.build_health_payload()
    assert h["severity"] == "fail"
    assert any(r["id"] == "configure_postgres" for r in h["recommendations"])


def test_build_providers_payload_marks_last_failed_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "zab.services.conversations.memory_db.fetch_conversation_provider_document_counts",
        lambda: {"cursor": 1, "claude": 0, "codex": 0, "hermes": 181, "gemini": 0, "kimi": 0},
    )
    monkeypatch.setattr(
        "zab.services.conversations._load_index",
        lambda: {"summary": {"failed_providers": {"hermes": "database disk image is malformed"}}},
    )

    p = conversations.build_providers_payload()
    hermes = next(row for row in p["providers"] if row["id"] == "hermes")
    assert hermes["status"] == "error"
    assert "malformed" in hermes["local"]["last_sync_error"]
