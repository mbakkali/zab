"""Digest conversations: extraction locale et rattachement projets/orgs."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from zab.services.agent_memory_import import AgentMemoryDocument
from zab.services.conversation_digest import (
    build_conversation_digest,
    build_conversation_digest_for_date,
    format_conversation_digest_markdown,
)


def _project(name: str, org: str, path: str, *, parent: str | None = None) -> dict:
    row = {
        "name": name,
        "org": org,
        "path": path,
        "aliases": [name, name.replace("-", "_"), org],
    }
    if parent:
        row["workspace_parent"] = parent
    return row


def test_digest_extracts_codex_user_message_and_maps_project(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "zab.services.conversation_digest.organization_slug_set_from_user_config",
        lambda: {"example-org"},
    )
    doc = AgentMemoryDocument(
        source="codex_transcript",
        wing="codex__sessions",
        room="conversation",
        path=tmp_path / "session.jsonl",
        content="cwd=/workspace/projects/zab",
        metadata={"conversation_provider": "codex"},
        raw_events=(
            {
                "timestamp": "2026-06-24T23:00:00Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "<environment_context>ignored</environment_context>"}],
                },
            },
            {
                "timestamp": "2026-06-24T23:00:30Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "# AGENTS.md instructions for /workspace/projects/zab"}],
                },
            },
            {
                "timestamp": "2026-06-24T23:01:00Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Fais un digest pour zab"}],
                },
            },
        ),
    )

    payload = build_conversation_digest(
        days=2,
        now=datetime(2026, 6, 25, 0, 0, tzinfo=timezone.utc),
        documents=[doc],
        projects=[_project("zab", "example-org", "/workspace/projects/zab")],
    )

    assert payload["shown_conversations"] == 1
    item = payload["items"][0]
    assert item["agent_tool"] == "Codex"
    assert item["conversation_id"] == "session"
    assert item["intent"] == "Fais un digest pour zab"
    assert item["org"] == "example-org"
    assert item["project"] == "zab"


def test_digest_cleans_redacts_claude_loop_and_ignores_subagents(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "zab.services.conversation_digest.organization_slug_set_from_user_config",
        lambda: {"example-client"},
    )
    main = AgentMemoryDocument(
        source="claude_code_transcript",
        wing="claude__-workspace-projects-client-alpha",
        room="conversation",
        path=tmp_path / "main.jsonl",
        content="alpha build_supplier_dossier",
        metadata={"conversation_provider": "claude"},
        messages=(
            {
                "role": "user",
                "timestamp": "2026-06-24T17:00:00Z",
                "content": "<command-message>loop</command-message> <command-name>/loop</command-name> <command-args>10m Docs sweep pour alpha avec key=fake-placeholder-token",
            },
        ),
    )
    sub = AgentMemoryDocument(
        source="claude_code_transcript",
        wing="claude__subagents",
        room="conversation",
        path=tmp_path / "subagents" / "agent.jsonl",
        content="alpha",
        metadata={"conversation_provider": "claude"},
        messages=(
            {"role": "user", "timestamp": "2026-06-24T17:01:00Z", "content": "Analyse interne subagent"},
        ),
    )

    payload = build_conversation_digest(
        days=2,
        now=datetime(2026, 6, 25, 0, 0, tzinfo=timezone.utc),
        documents=[main, sub],
        projects=[_project("alpha", "example-client", "/workspace/projects/client/alpha", parent="example-client")],
    )

    assert payload["shown_conversations"] == 1
    assert payload["skipped_subagents"] == 1
    item = payload["items"][0]
    assert "command-message" not in item["intent"]
    assert "Docs sweep pour alpha" in item["intent"]
    assert "fake-placeholder-token" not in item["intent"]
    assert "[redacted]" in item["intent"]
    assert item["org"] == "example-client"
    assert item["project"] == "alpha"


def test_digest_markdown_empty_window() -> None:
    payload = build_conversation_digest(
        days=1,
        now=datetime(2026, 6, 25, 0, 0, tzinfo=timezone.utc),
        documents=[],
        projects=[],
    )

    md = format_conversation_digest_markdown(payload)

    assert "Rien de net" in md


def test_digest_for_date_uses_local_calendar_window_and_batches(tmp_path: Path) -> None:
    inside = AgentMemoryDocument(
        source="hermes_transcript",
        wing="hermes__abc",
        room="conversation",
        path=tmp_path / "_zab_session_export" / "abc.jsonl",
        content="example-client alpha",
        metadata={"conversation_provider": "hermes", "hermes_session_id": "hermes-abc"},
        messages=(
            {"role": "user", "timestamp": "2026-06-24T21:30:00Z", "content": "Point alpha"},
        ),
    )
    outside = AgentMemoryDocument(
        source="codex_transcript",
        wing="codex__sessions",
        room="conversation",
        path=tmp_path / "outside.jsonl",
        content="alpha",
        metadata={"conversation_provider": "codex"},
        messages=(
            {"role": "user", "timestamp": "2026-06-24T22:30:00Z", "content": "Trop tard localement"},
        ),
    )

    payload = build_conversation_digest_for_date(
        on=date(2026, 6, 24),
        timezone_name="Europe/Paris",
        now=datetime(2026, 6, 25, 9, 0, tzinfo=timezone.utc),
        documents=[inside, outside],
        projects=[_project("alpha", "example-client", "/workspace/projects/client/alpha")],
        batch_size=1,
    )

    assert payload["shown_conversations"] == 1
    assert payload["items"][0]["conversation_id"] == "hermes-abc"
    assert payload["items"][0]["agent_tool"] == "Hermes"
    assert payload["batches"] == [{"index": 1, "count": 1, "conversation_ids": ["hermes-abc"]}]


def test_digest_canonicalizes_unknown_org_to_hors_org(tmp_path: Path) -> None:
    doc = AgentMemoryDocument(
        source="codex_transcript",
        wing="codex__sessions",
        room="conversation",
        path=tmp_path / "side-project-session.jsonl",
        content="/workspace/projects/side-project",
        metadata={"conversation_provider": "codex"},
        messages=(
            {
                "role": "user",
                "timestamp": "2026-06-24T10:00:00Z",
                "content": "Continue le projet side-project",
            },
        ),
    )

    payload = build_conversation_digest(
        days=2,
        now=datetime(2026, 6, 25, 0, 0, tzinfo=timezone.utc),
        documents=[doc],
        projects=[_project("side-project", "zab", "/workspace/projects/side-project")],
    )

    assert payload["shown_conversations"] == 1
    assert payload["items"][0]["org"] == "hors-org"
    assert payload["items"][0]["project"] == "side-project"
