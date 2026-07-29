"""SQLite + JSONL persistence for Conversation Ledger."""

from __future__ import annotations

import gzip
import json
import os
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from zab.paths import data_dir
from zab.services import local_db
from zab.services.conversation_ledger.schemas import (
    CONTRACT_VERSION,
    INTERACTION_EVENT_CONTRACT,
    WORKPACKET_CANONICAL_CONTRACT,
    validate_interaction_event,
    validate_projection_state,
    validate_workpacket_canonical,
)

CURSORS_KEY = "ledger.source_cursors"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ledger_dir() -> Path:
    path = data_dir() / "ledger"
    path.mkdir(parents=True, exist_ok=True)
    return path


def events_jsonl_path() -> Path:
    return ledger_dir() / "events.jsonl"


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def append_event_jsonl(event: dict[str, Any]) -> None:
    _append_jsonl(events_jsonl_path(), event)


def compact_events_jsonl(
    *, apply: bool = False, archive: bool = True
) -> dict[str, Any]:
    """Rewrite the append journal from canonical rows, with an optional gzip backup."""
    path = events_jsonl_path()
    current_bytes = path.stat().st_size if path.exists() else 0
    with local_db.transaction() as conn:
        rows = conn.execute(
            "SELECT payload_json FROM ledger_events ORDER BY timestamp, event_id"
        ).fetchall()
    canonical_lines = [
        json.dumps(json.loads(row[0]), ensure_ascii=False, sort_keys=True) + "\n"
        for row in rows
    ]
    canonical_bytes = sum(len(line.encode("utf-8")) for line in canonical_lines)
    payload: dict[str, Any] = {
        "contract": "conversation-ledger-events-compact",
        "dry_run": not apply,
        "event_count": len(rows),
        "bytes_before": current_bytes,
        "bytes_after": canonical_bytes,
        "bytes_reclaimable": max(current_bytes - canonical_bytes, 0),
        "path": str(path),
        "archive_path": None,
    }
    if not apply:
        return payload

    tmp_path = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            handle.writelines(canonical_lines)
            handle.flush()
            os.fsync(handle.fileno())
        if archive and path.exists() and current_bytes:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            archive_path = path.with_name(f"{path.name}.{timestamp}.gz")
            with (
                path.open("rb") as source,
                gzip.open(archive_path, "wb", compresslevel=6) as target,
            ):
                shutil.copyfileobj(source, target, length=1024 * 1024)
            payload["archive_path"] = str(archive_path)
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
    return payload


def upsert_event(conn: sqlite3.Connection, event: dict[str, Any]) -> dict[str, Any]:
    payload = dict(event)
    existing_row = None
    existing: dict[str, Any] | None = None
    if payload.get("source") and payload.get("native_id"):
        existing_row = conn.execute(
            "SELECT payload_json FROM ledger_events WHERE source = ? AND native_id = ?",
            (payload.get("source"), payload.get("native_id")),
        ).fetchone()
    if existing_row:
        existing = json.loads(existing_row[0])
        for key in ("body", "counterparties", "created_at"):
            if not payload.get(key) and existing.get(key):
                payload[key] = existing[key]
        for key in (
            "entity_links",
            "organization_id",
            "organization_label",
            "client_workstream_id",
            "client_workstream_label",
        ):
            if key not in payload and existing.get(key):
                payload[key] = existing[key]

    errors = validate_interaction_event(payload)
    if errors:
        raise ValueError("; ".join(errors))
    payload.setdefault("contract", INTERACTION_EVENT_CONTRACT)
    payload.setdefault("contract_version", CONTRACT_VERSION)
    payload.setdefault("created_at", utc_now())
    entity_links = payload.pop("entity_links", [])
    stored_payload = {**payload, "entity_links": entity_links}
    conn.execute(
        """
        INSERT INTO ledger_events (event_id, source, native_id, channel_id, timestamp, payload_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, native_id) DO UPDATE SET
            payload_json=excluded.payload_json,
            timestamp=excluded.timestamp,
            channel_id=excluded.channel_id
        """,
        (
            payload["event_id"],
            payload["source"],
            payload["native_id"],
            payload.get("channel_id"),
            payload.get("timestamp"),
            json.dumps(stored_payload, ensure_ascii=False),
            payload["created_at"],
        ),
    )
    if existing != stored_payload:
        append_event_jsonl(stored_payload)
    return stored_payload


def get_event(conn: sqlite3.Connection, event_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT payload_json FROM ledger_events WHERE event_id = ?", (event_id,)
    ).fetchone()
    if not row:
        return None
    return json.loads(row[0])


def list_events(
    conn: sqlite3.Connection,
    *,
    organization_id: str | None = None,
    client_workstream_id: str | None = None,
    since: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT payload_json FROM ledger_events ORDER BY timestamp DESC LIMIT ?",
        (limit * 5,),
    ).fetchall()
    events = [json.loads(r[0]) for r in rows]
    filtered: list[dict[str, Any]] = []
    for event in events:
        links = event.get("entity_links") or []
        if organization_id:
            org_match = any(
                link.get("entity_type") == "organization"
                and link.get("entity_id") == organization_id
                for link in links
            )
            if not org_match and event.get("organization_id") != organization_id:
                continue
        if client_workstream_id:
            ws_match = any(
                link.get("entity_type") == "client_workstream"
                and link.get("entity_id") == client_workstream_id
                for link in links
            )
            event_ws = event.get("client_workstream_id")
            if not ws_match and event_ws != client_workstream_id:
                continue
            if not ws_match and event_ws == client_workstream_id:
                # Accept direct field only when subject keywords support the workstream.
                from zab.services.conversation_ledger.clustering import (
                    classify_workstream,
                )

                inferred, _, conf = classify_workstream(
                    f"{event.get('title')} {event.get('snippet')}"
                )
                if inferred != client_workstream_id or conf < 0.65:
                    continue
        if since and str(event.get("timestamp") or "") < since:
            continue
        filtered.append(event)
        if len(filtered) >= limit:
            break
    return filtered


def upsert_workpacket(
    conn: sqlite3.Connection, packet: dict[str, Any]
) -> dict[str, Any]:
    errors = validate_workpacket_canonical(packet)
    if errors:
        raise ValueError("; ".join(errors))
    payload = dict(packet)
    payload.setdefault("contract", WORKPACKET_CANONICAL_CONTRACT)
    payload.setdefault("contract_version", CONTRACT_VERSION)
    payload.setdefault("intake_ref", "workpacket-intake")
    payload["updated_at"] = utc_now()
    payload.setdefault("created_at", payload["updated_at"])
    conn.execute(
        """
        INSERT INTO ledger_workpackets
            (workpacket_id, display_id, state, organization_id, client_workstream_id, payload_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(workpacket_id) DO UPDATE SET
            state=excluded.state,
            organization_id=excluded.organization_id,
            client_workstream_id=excluded.client_workstream_id,
            payload_json=excluded.payload_json,
            updated_at=excluded.updated_at
        """,
        (
            payload["workpacket_id"],
            payload.get("display_id"),
            payload.get("state"),
            payload.get("organization_id"),
            payload.get("client_workstream_id"),
            json.dumps(payload, ensure_ascii=False),
            payload["created_at"],
            payload["updated_at"],
        ),
    )
    return payload


def next_display_id(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT COUNT(*) AS c FROM ledger_workpackets").fetchone()
    count = int(row[0]) if row else 0
    return f"ZWP-{count + 1:04d}"


def get_workpacket(
    conn: sqlite3.Connection, workpacket_id: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT payload_json FROM ledger_workpackets WHERE workpacket_id = ?",
        (workpacket_id,),
    ).fetchone()
    if not row:
        return None
    return json.loads(row[0])


def find_workpacket(
    conn: sqlite3.Connection,
    *,
    organization_id: str | None = None,
    client_workstream_id: str | None = None,
    display_id: str | None = None,
) -> dict[str, Any] | None:
    if display_id:
        row = conn.execute(
            "SELECT payload_json FROM ledger_workpackets WHERE display_id = ?",
            (display_id,),
        ).fetchone()
        if row:
            return json.loads(row[0])
    if organization_id and client_workstream_id:
        row = conn.execute(
            """
            SELECT payload_json FROM ledger_workpackets
            WHERE organization_id = ? AND client_workstream_id = ?
            ORDER BY updated_at DESC LIMIT 1
            """,
            (organization_id, client_workstream_id),
        ).fetchone()
        if row:
            return json.loads(row[0])
    return None


def list_workpackets(
    conn: sqlite3.Connection,
    *,
    states: list[str] | None = None,
    organization_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    query = "SELECT payload_json FROM ledger_workpackets WHERE 1=1"
    params: list[Any] = []
    if states:
        placeholders = ",".join("?" for _ in states)
        query += f" AND state IN ({placeholders})"
        params.extend(states)
    if organization_id:
        query += " AND organization_id = ?"
        params.append(organization_id)
    query += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    return [json.loads(r[0]) for r in rows]


def upsert_projection(
    conn: sqlite3.Connection, projection: dict[str, Any]
) -> dict[str, Any]:
    errors = validate_projection_state(projection)
    if errors:
        raise ValueError("; ".join(errors))
    payload = dict(projection)
    payload.setdefault("contract", "conversation-ledger-projection-state")
    payload.setdefault("contract_version", CONTRACT_VERSION)
    payload["updated_at"] = utc_now()
    conn.execute(
        """
        INSERT INTO ledger_projection_states (workpacket_id, target, status, payload_json, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(workpacket_id, target) DO UPDATE SET
            status=excluded.status,
            payload_json=excluded.payload_json,
            updated_at=excluded.updated_at
        """,
        (
            payload["workpacket_id"],
            payload["target"],
            payload.get("status"),
            json.dumps(payload, ensure_ascii=False),
            payload["updated_at"],
        ),
    )
    return payload


def get_projection(
    conn: sqlite3.Connection, workpacket_id: str, target: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT payload_json FROM ledger_projection_states WHERE workpacket_id = ? AND target = ?",
        (workpacket_id, target),
    ).fetchone()
    if not row:
        return None
    return json.loads(row[0])


def list_projections(
    conn: sqlite3.Connection, workpacket_id: str
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT payload_json FROM ledger_projection_states WHERE workpacket_id = ? ORDER BY target",
        (workpacket_id,),
    ).fetchall()
    return [json.loads(r[0]) for r in rows]


def get_source_cursors(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        "SELECT value_json FROM sync_meta WHERE key = ?", (CURSORS_KEY,)
    ).fetchone()
    if not row:
        return {}
    return json.loads(row[0])


def set_source_cursor(
    conn: sqlite3.Connection, channel_id: str, cursor: dict[str, Any]
) -> None:
    cursors = get_source_cursors(conn)
    cursors[channel_id] = {**cursor, "updated_at": utc_now()}
    conn.execute(
        """
        INSERT INTO sync_meta (key, value_json, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at
        """,
        (CURSORS_KEY, json.dumps(cursors, ensure_ascii=False), utc_now()),
    )


def new_workpacket_id() -> str:
    return f"wp_{uuid.uuid4().hex[:16]}"
