"""Ecriture du digest conversations dans Obsidian."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from zab.services.agent_memory_import import AgentMemoryDocument
from zab.services.conversation_obsidian_daily import format_obsidian_detail_markdown, write_obsidian_conversation_digest


def _project(name: str, org: str, path: str) -> dict:
    return {"name": name, "org": org, "path": path, "aliases": [name, org]}


def test_write_obsidian_digest_updates_daily_without_duplicates(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    todos = vault / "todos"
    todos.mkdir(parents=True)
    daily = todos / "Daily.md"
    daily.write_text(
        "---\nsticker: emoji//1f4c6\nbanner:\n---\n"
        "## Todo en vrac : \n"
        "- [ ] existant\n\n"
        "**Mercredi 24 juin \n"
        "- [ ] Faire\n",
        encoding="utf-8",
    )
    doc = AgentMemoryDocument(
        source="codex_transcript",
        wing="codex__sessions",
        room="conversation",
        path=tmp_path / "codex-123.jsonl",
        content="cwd=/workspace/projects/zab",
        metadata={"conversation_provider": "codex"},
        messages=(
            {
                "role": "user",
                "timestamp": "2026-06-24T10:00:00Z",
                "content": "Mettre en place le digest zab",
            },
        ),
    )

    first = write_obsidian_conversation_digest(
        target_date=date(2026, 6, 24),
        vault=vault,
        documents=[doc],
        projects=[_project("zab", "example-org", "/workspace/projects/zab")],
    )
    second = write_obsidian_conversation_digest(
        target_date=date(2026, 6, 24),
        vault=vault,
        documents=[doc],
        projects=[_project("zab", "example-org", "/workspace/projects/zab")],
    )

    assert first["status"] == "written"
    assert second["status"] == "written"
    detail = vault / "todos" / "Agent conversations" / "2026-06-24 - conversations agents.md"
    assert detail.is_file()
    detail_text = detail.read_text(encoding="utf-8")
    assert "id `codex-123`" in detail_text
    assert "Codex" in detail_text
    text = daily.read_text(encoding="utf-8")
    assert text.count("zab-conversation-digest:2026-06-24:start") == 1
    assert "[[todos/Agent conversations/2026-06-24 - conversations agents|conversations agents 2026-06-24]]" in text


def test_write_obsidian_digest_once_per_day_skips_existing_marker(tmp_path: Path, monkeypatch) -> None:
    marker_root = tmp_path / "state"
    monkeypatch.setattr(
        "zab.services.conversation_obsidian_daily.data_dir",
        lambda: marker_root,
    )
    vault = tmp_path / "vault"
    (vault / "todos").mkdir(parents=True)
    day = date(2026, 6, 24)
    doc = AgentMemoryDocument(
        source="codex_transcript",
        wing="codex__sessions",
        room="conversation",
        path=tmp_path / "session.jsonl",
        content="",
        metadata={"conversation_provider": "codex"},
        messages=(
            {
                "role": "user",
                "timestamp": "2026-06-24T10:00:00Z",
                "content": "Premier digest",
            },
        ),
    )

    written = write_obsidian_conversation_digest(
        target_date=day,
        vault=vault,
        documents=[doc],
        projects=[],
        once_per_day=True,
    )
    skipped = write_obsidian_conversation_digest(
        target_date=day,
        vault=vault,
        documents=[doc],
        projects=[],
        once_per_day=True,
    )

    assert written["status"] == "written"
    assert skipped["status"] == "skipped"
    assert skipped["reason"] == "already_ran"


def test_detail_markdown_escapes_inline_content_that_breaks_obsidian() -> None:
    text = format_obsidian_detail_markdown(
        {
            "target_date": "2026-06-25",
            "timezone": "Europe/Paris",
            "generated_at": "2026-06-26T07:00:00Z",
            "window": {},
            "shown_conversations": 1,
            "retained_conversations": 1,
            "scanned_conversations": 1,
            "retained_provider_counts": {"codex": 1},
            "batch_size": 10,
            "batches": [{"index": 1, "count": 1}],
            "items": [
                {
                    "updated_at": "2026-06-25T16:34:00Z",
                    "agent_tool": "Codex",
                    "conversation_id": "rollout-`bad`",
                    "org": "example-org",
                    "project": "example-project",
                    "match_reason": "contenu-chemin",
                    "intent": 'http://127.0.0.1:9119/cron <image name=[Image #1] path="/tmp/img.png"> `open',
                }
            ],
        }
    )

    assert "## Actions a traiter" in text
    assert "&lt;image name=[Image #1] path=" in text
    assert "\\`open" in text
    assert "id `` rollout-`bad` ``" in text
    assert "<image name=" not in text
