"""Seed and load organization / workstream registry tables."""

from __future__ import annotations

import json
from typing import Any

from zab.services import local_db
from zab.services.conversation_ledger.entity_resolver import DEFAULT_ORGANIZATIONS, WORKSTREAM_SEEDS
from zab.services.conversation_ledger.store import utc_now


def ensure_entity_registry(conn) -> None:
    now = utc_now()
    for org_id, org in DEFAULT_ORGANIZATIONS.items():
        payload = dict(org)
        conn.execute(
            """
            INSERT INTO ledger_organizations (organization_id, label, payload_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(organization_id) DO UPDATE SET
                label=excluded.label,
                payload_json=excluded.payload_json,
                updated_at=excluded.updated_at
            """,
            (org_id, org["label"], json.dumps(payload, ensure_ascii=False), now),
        )
    for ws_id, ws in WORKSTREAM_SEEDS.items():
        payload = dict(ws)
        conn.execute(
            """
            INSERT INTO ledger_workstreams (client_workstream_id, organization_id, label, payload_json, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(client_workstream_id) DO UPDATE SET
                organization_id=excluded.organization_id,
                label=excluded.label,
                payload_json=excluded.payload_json,
                updated_at=excluded.updated_at
            """,
            (ws_id, ws["organization_id"], ws["label"], json.dumps(payload, ensure_ascii=False), now),
        )


def list_organizations(conn) -> list[dict[str, Any]]:
    ensure_entity_registry(conn)
    rows = conn.execute("SELECT payload_json FROM ledger_organizations ORDER BY label").fetchall()
    return [json.loads(r[0]) for r in rows]


def list_workstreams(conn, *, organization_id: str | None = None) -> list[dict[str, Any]]:
    ensure_entity_registry(conn)
    if organization_id:
        rows = conn.execute(
            "SELECT payload_json FROM ledger_workstreams WHERE organization_id = ? ORDER BY label",
            (organization_id,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT payload_json FROM ledger_workstreams ORDER BY label").fetchall()
    return [json.loads(r[0]) for r in rows]
