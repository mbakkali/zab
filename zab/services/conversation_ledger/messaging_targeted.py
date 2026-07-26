"""Targeted WhatsApp/iMessage fetchers (active contacts only)."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from zab.services.dotenv_locate import load_standard_dotenvs_once

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


def _iso_to_apple_ns(value: str | None) -> int | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.fromisoformat(f"{value}T00:00:00+00:00")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int((dt.astimezone(timezone.utc) - _APPLE_EPOCH).total_seconds() * 1_000_000_000)


def _first_non_empty_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
    return ""


def _evolution_env() -> tuple[str, str, str] | None:
    load_standard_dotenvs_once()
    base = _first_non_empty_str(os.environ.get("EVOLUTION_API_URL")).rstrip("/")
    key = _first_non_empty_str(os.environ.get("EVOLUTION_API_KEY"))
    instance = _first_non_empty_str(os.environ.get("EVOLUTION_INSTANCE"), os.environ.get("EVOLUTION_INSTANCE_NAME"))
    if not (base and key and instance):
        return None
    return base, key, instance


def _evolution_records(payload: Any) -> list[dict[str, Any]]:
    records: list[Any] = []
    if isinstance(payload, dict):
        messages = payload.get("messages")
        if isinstance(messages, dict) and isinstance(messages.get("records"), list):
            records = messages["records"]
        elif isinstance(messages, list):
            records = messages
        elif isinstance(payload.get("records"), list):
            records = payload["records"]
        elif isinstance(payload.get("data"), list):
            records = payload["data"]
        elif isinstance(payload.get("data"), dict):
            records = _evolution_records(payload["data"])
    elif isinstance(payload, list):
        records = payload
    return [item for item in records if isinstance(item, dict)]


def fetch_imessage_recent(*, limit: int = 50, since: str | None = None) -> list[dict[str, Any]]:
    """Read recent local iMessage history.

    Requires Full Disk Access. Empty means unavailable or no matching messages.
    """
    db_path = _chat_db_path()
    if not db_path.exists():
        return []
    where = "m.text IS NOT NULL"
    params: list[Any] = []
    since_ns = _iso_to_apple_ns(since)
    if since_ns is not None:
        where += " AND m.date >= ?"
        params.append(since_ns)
    query = f"""
        SELECT m.ROWID as rowid, m.guid as guid, m.text as text,
               m.is_from_me as is_from_me, m.date as date, h.id as handle
        FROM message m
        LEFT JOIN handle h ON m.handle_id = h.ROWID
        WHERE {where}
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
    env = _evolution_env()
    if env is None or not contacts:
        return []
    base, key, instance = env
    out: list[dict[str, Any]] = []
    for contact in contacts:
        remote_jid = contact if "@" in contact else f"{contact}@s.whatsapp.net"
        try:
            resp = httpx.post(
                f"{base}/chat/findMessages/{instance}",
                headers={"apikey": key, "Content-Type": "application/json"},
                json={"where": {"key": {"remoteJid": remote_jid}}, "limit": limit},
                timeout=15,
            )
            if resp.status_code >= 400:
                continue
            payload = resp.json()
            for msg in _evolution_records(payload)[:limit]:
                out.append(msg)
        except Exception:  # noqa: BLE001
            continue
    return out


def fetch_whatsapp_recent(*, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch recent inbound WhatsApp messages via Evolution API."""
    env = _evolution_env()
    if env is None:
        return []
    base, key, instance = env
    try:
        resp = httpx.post(
            f"{base}/chat/findMessages/{instance}",
            headers={"apikey": key, "Content-Type": "application/json"},
            json={"where": {"key": {"fromMe": False}}, "limit": limit},
            timeout=15,
        )
        if resp.status_code >= 400:
            return []
        return _evolution_records(resp.json())[:limit]
    except Exception:  # noqa: BLE001
        return []
