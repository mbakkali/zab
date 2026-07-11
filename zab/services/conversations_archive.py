"""Table Postgres `zab_conversations` : archive fidèle des conversations (hors chunks index)."""

from __future__ import annotations

import json
import uuid
from typing import Any

# Slugs alignés sur ALL_CONVERSATION_PROVIDERS
ARCHIVE_PROVIDERS = frozenset({"cursor", "claude", "codex", "kimi", "hermes", "gemini"})


def ensure_conversations_archive_schema(cur: Any) -> None:
    """Crée la table et les index si absents (idempotent)."""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS zab_conversations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            provider text NOT NULL,
            source text NOT NULL,
            source_path text NOT NULL,
            source_hash text NOT NULL UNIQUE,
            wing text,
            room text,
            title text,
            started_at timestamptz,
            updated_at timestamptz,
            raw_events jsonb NOT NULL DEFAULT '[]'::jsonb,
            messages jsonb NOT NULL DEFAULT '[]'::jsonb,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            synced_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_zab_conversations_provider_updated
        ON zab_conversations (provider, updated_at DESC NULLS LAST)
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_zab_conversations_wing
        ON zab_conversations (wing)
        """
    )


def delete_archive_for_providers(cur: Any, providers: frozenset[str]) -> int:
    """Supprime les lignes archive pour les providers donnés."""
    if not providers:
        return 0
    allowed = [p for p in providers if p in ARCHIVE_PROVIDERS]
    if not allowed:
        return 0
    cur.execute(
        "DELETE FROM zab_conversations WHERE provider = ANY(%s)",
        (allowed,),
    )
    return cur.rowcount


def delete_all_archive_conversations(cur: Any) -> int:
    cur.execute("DELETE FROM zab_conversations")
    return cur.rowcount


def _sanitize_nul(obj: Any) -> Any:
    if isinstance(obj, str):
        return obj.replace("\x00", "")
    elif isinstance(obj, dict):
        return {k: _sanitize_nul(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_sanitize_nul(x) for x in obj]
    return obj

def upsert_conversation_archive(
    cur: Any,
    *,
    provider: str,
    source: str,
    source_path: str,
    source_hash: str,
    wing: str,
    room: str,
    title: str | None,
    started_at: Any,
    updated_at: Any,
    raw_events: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    metadata: dict[str, Any],
    synced_at: Any,
) -> uuid.UUID:
    """Upsert une conversation par `source_hash`, retourne l'id archive."""
    raw_events = _sanitize_nul(raw_events)
    messages = _sanitize_nul(messages)
    metadata = _sanitize_nul(metadata)
    cur.execute(
        """
        INSERT INTO zab_conversations (
            provider, source, source_path, source_hash, wing, room, title,
            started_at, updated_at, raw_events, messages, metadata, synced_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s)
        ON CONFLICT (source_hash) DO UPDATE SET
            provider = EXCLUDED.provider,
            source = EXCLUDED.source,
            source_path = EXCLUDED.source_path,
            wing = EXCLUDED.wing,
            room = EXCLUDED.room,
            title = EXCLUDED.title,
            started_at = EXCLUDED.started_at,
            updated_at = EXCLUDED.updated_at,
            raw_events = EXCLUDED.raw_events,
            messages = EXCLUDED.messages,
            metadata = EXCLUDED.metadata,
            synced_at = EXCLUDED.synced_at
        RETURNING id
        """,
        (
            provider,
            source,
            source_path,
            source_hash,
            wing,
            room,
            title,
            started_at,
            updated_at,
            json.dumps(raw_events, ensure_ascii=False, default=str),
            json.dumps(messages, ensure_ascii=False, default=str),
            json.dumps(metadata, ensure_ascii=False, default=str),
            synced_at,
        ),
    )
    row = cur.fetchone()
    if not row or row[0] is None:
        raise RuntimeError("upsert_conversation_archive: RETURNING id vide")
    return uuid.UUID(str(row[0]))
