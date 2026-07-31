"""Tests import conversations agents (Hermes SQLite, Gemini discovery, providers)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from zab.services.agent_memory_import import (
    PROVIDER_GEMINI,
    PROVIDER_HERMES,
    _parse_jsonl_transcript_arrays,
    _storage_metadata_stub,
    AgentMemoryDocument,
    collect_agent_memory_documents,
    collect_hermes_documents,
    discover_gemini_cli_status,
    discover_provider_dry_run_summary,
    parse_jsonl_transcript_structured,
    sync_agent_memory_to_postgres,
)


def test_discover_provider_dry_run_has_keys() -> None:
    out = discover_provider_dry_run_summary()
    assert "providers" in out
    for slug in ("cursor", "claude", "codex", "kimi", "hermes", "gemini"):
        assert slug in out["providers"]


def test_parse_jsonl_transcript_structured_splits_human_and_tool_messages(tmp_path: Path) -> None:
    p = tmp_path / "conversation.jsonl"
    rows = [
        {
            "role": "user",
            "timestamp": "2026-05-20T16:00:00Z",
            "message": {"content": [{"type": "text", "text": "cherche factory"}]},
        },
        {
            "role": "assistant",
            "timestamp": "2026-05-20T16:00:02Z",
            "message": {
                "content": [
                    {"type": "text", "text": "Je vais chercher."},
                    {"type": "tool_use", "name": "rg", "input": {"pattern": "factory"}},
                    {"type": "tool_result", "content": "3 résultats"},
                ]
            },
        },
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    text, messages = parse_jsonl_transcript_structured(p)

    assert "### user" in text
    assert [m["role"] for m in messages] == ["user", "assistant", "tool", "tool"]
    _t, raw_ev, _m2 = _parse_jsonl_transcript_arrays(p)
    assert len(raw_ev) == 2
    assert raw_ev[0].get("role") == "user"
    assert _m2 == messages
    assert messages[0]["label"] == "You"
    assert messages[1]["label"] == "Agent"
    assert messages[2]["label"] == "Tool call"
    assert messages[2]["tool_name"] == "rg"
    assert '"pattern": "factory"' in messages[2]["content"]
    assert messages[3]["label"] == "Tool result"
    assert messages[0]["timestamp"] == "2026-05-20T16:00:00Z"


def test_storage_metadata_does_not_duplicate_structured_messages(tmp_path: Path) -> None:
    messages = [{"role": "user", "content": "large transcript payload"}]
    doc = AgentMemoryDocument(
        source="codex_transcript",
        wing="codex__sessions",
        room="conversation",
        path=tmp_path / "conversation.jsonl",
        content="hello",
        metadata={
            "conversation_provider": "codex",
            "kind": "codex_session",
            "messages": messages,
        },
        messages=tuple(messages),
    )

    compact = _storage_metadata_stub(doc, content_len=len(doc.content))

    assert "messages" not in compact
    assert compact["conversation_provider"] == "codex"
    assert compact["path"] == str(doc.path)
    assert doc.metadata["messages"] == messages


def test_collect_hermes_documents_from_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hermes_dir = tmp_path / ".hermes"
    hermes_dir.mkdir()
    db = hermes_dir / "state.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        """CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            title TEXT,
            source TEXT,
            model TEXT,
            message_count INTEGER,
            started_at INTEGER,
            ended_at INTEGER
        )"""
    )
    conn.execute(
        """CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            session_id TEXT,
            role TEXT,
            content TEXT,
            timestamp INTEGER,
            tool_name TEXT,
            tool_call_id TEXT
        )"""
    )
    conn.execute(
        "INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
        ("s1", "Test", "cli", "gpt", 2, 1, 2),
    )
    conn.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,?)", ("m1", "s1", "user", "hello", 1, None, None))
    conn.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,?)", ("m2", "s1", "assistant", "world", 2, None, None))
    conn.commit()
    conn.close()

    monkeypatch.setattr("zab.services.agent_memory_import.Path.home", lambda: tmp_path)

    docs = collect_hermes_documents()
    assert len(docs) == 1
    assert docs[0].source == "hermes_transcript"
    assert "hello" in docs[0].content
    assert docs[0].metadata["messages"][0]["label"] == "You"
    assert docs[0].metadata["messages"][1]["label"] == "Agent"
    assert len(docs[0].raw_events) == 2
    assert docs[0].raw_events[0].get("role") == "user"

    part = collect_agent_memory_documents(providers=frozenset({PROVIDER_HERMES}))
    assert len(part) >= 1


def test_collect_hermes_documents_skips_malformed_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hermes_dir = tmp_path / ".hermes"
    hermes_dir.mkdir()
    (hermes_dir / "state.db").write_bytes(b"not a sqlite database")

    monkeypatch.setattr("zab.services.agent_memory_import.Path.home", lambda: tmp_path)

    assert collect_hermes_documents() == []


def test_sync_dry_run_reports_failed_provider_without_crashing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("zab.services.agent_memory_import.collect_cursor_documents", lambda **_: [])

    def broken_hermes():
        raise RuntimeError("database disk image is malformed")

    monkeypatch.setattr("zab.services.agent_memory_import._collect_hermes_documents_strict", broken_hermes)

    summary = sync_agent_memory_to_postgres(dry_run=True, providers=frozenset({"cursor", "hermes"}))

    assert summary["failed_providers"] == {"hermes": "database disk image is malformed"}
    assert summary["providers"] == ["cursor"]
    assert summary.get("inserted_archive_documents") == 0
    assert summary.get("deleted_previous_archive_rows") == 0


def test_gemini_discovery_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("zab.services.agent_memory_import.Path.home", lambda: tmp_path)
    g = discover_gemini_cli_status()
    assert g["present"] is False
    assert g["status"] == "missing"


def test_gemini_discovery_ready_with_safe_jsonl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gem = tmp_path / ".gemini" / "sessions"
    gem.mkdir(parents=True)
    line = json.dumps({"role": "user", "message": "x" * 50}) + "\n"
    (gem / "a.jsonl").write_text(line * 3, encoding="utf-8")

    monkeypatch.setattr("zab.services.agent_memory_import.Path.home", lambda: tmp_path)
    monkeypatch.setattr("zab.services.agent_memory_import._gemini_path_skipped", lambda _path: None)
    st = discover_gemini_cli_status()
    assert st["status"] == "ready"
    docs = collect_agent_memory_documents(providers=frozenset({PROVIDER_GEMINI}))
    assert len(docs) >= 1


def test_collect_respects_provider_filter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("zab.services.agent_memory_import.Path.home", lambda: tmp_path)
    empty = collect_agent_memory_documents(providers=frozenset({PROVIDER_HERMES}))
    assert empty == []
