"""Targeted WhatsApp/iMessage fetchers (active contacts only)."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Apple stores message dates as nanoseconds since 2001-01-01 (Mac epoch).
_APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


def _apple_ns_to_iso(value: Any) -> str:
    try:
        ns = int(value)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).isoformat()
    if ns == 0:
        return datetime.now(timezone.utc).isoformat()
    seconds = ns / 1_000_000_000 if ns > 1_000_000_000_000 else ns
    return (_APPLE_EPOCH + timedelta(seconds=seconds)).isoformat()


def _chat_db_path() -> Path:
    override = os.environ.get("ZAB_IMESSAGE_DB")
    if override:
        return Path(override).expanduser()
    return Path.home() / "Library" / "Messages" / "chat.db"


def fetch_imessage_targeted(*, contacts: list[str], limit: int = 50, since: str | None = None) -> list[dict[str, Any]]:
    """Read local iMessage history for the given handles (phone/email).

    Requires Full Disk Access. Returns raw message dicts (normalize separately).
    """
    if not contacts:
        return []
    db_path = _chat_db_path()
    if not db_path.exists():
        return []
    like_clauses = " OR ".join("h.id LIKE ?" for _ in contacts)
    params: list[Any] = [f"%{c}%" for c in contacts]
    query = f"""
        SELECT m.ROWID as rowid, m.guid as guid, m.text as text,
               m.is_from_me as is_from_me, m.date as date, h.id as handle
        FROM message m
        JOIN handle h ON m.handle_id = h.ROWID
        WHERE ({like_clauses}) AND m.text IS NOT NULL
        ORDER BY m.date DESC
        LIMIT ?
    """
    params.append(limit)
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()
        conn.close()
    except sqlite3.Error:
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "rowid": row["rowid"],
                "guid": row["guid"],
                "text": row["text"],
                "is_from_me": bool(row["is_from_me"]),
                "handle": row["handle"],
                "timestamp": _apple_ns_to_iso(row["date"]),
            }
        )
    return out


def fetch_whatsapp_targeted(*, contacts: list[str], limit: int = 50) -> list[dict[str, Any]]:
    """Fetch WhatsApp messages via Evolution API for the given chat ids/numbers.

    Requires EVOLUTION_API_URL / EVOLUTION_API_KEY / EVOLUTION_INSTANCE. Returns
    raw message dicts (normalize separately). Empty when unconfigured.
    """
    base = os.environ.get("EVOLUTION_API_URL", "").strip().rstrip("/")
    key = os.environ.get("EVOLUTION_API_KEY", "").strip()
    instance = os.environ.get("EVOLUTION_INSTANCE", "").strip()
    if not (base and key and instance and contacts):
        return []
    try:
        import requests  # type: ignore
    except Exception:  # noqa: BLE001
        return []
    out: list[dict[str, Any]] = []
    for contact in contacts:
        remote_jid = contact if "@" in contact else f"{contact}@s.whatsapp.net"
        try:
            resp = requests.post(
                f"{base}/chat/findMessages/{instance}",
                headers={"apikey": key, "Content-Type": "application/json"},
                json={"where": {"key": {"remoteJid": remote_jid}}, "limit": limit},
                timeout=15,
            )
            if resp.status_code != 200:
                continue
            payload = resp.json()
            messages = payload if isinstance(payload, list) else payload.get("messages") or payload.get("data") or []
            for msg in messages[:limit]:
                out.append(msg)
        except Exception:  # noqa: BLE001
            continue
    return out
