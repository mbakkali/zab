"""Linear projection (dry-run first)."""

from __future__ import annotations

from hashlib import sha256
from typing import Any

from zab.services import local_db
from zab.services.conversation_ledger.store import get_workpacket, list_events, upsert_projection


def projection_hash(body: str) -> str:
    return sha256(body.encode("utf-8")).hexdigest()[:16]


def build_linear_description(packet: dict[str, Any], *, events: list[dict[str, Any]] | None = None) -> str:
    lock = packet.get("subject_lock") or {}
    lines = [
        "## Subject Lock",
        f"- Client: {lock.get('client')}",
        f"- Project / workstream: {lock.get('project_or_workstream')}",
        f"- Subject: {lock.get('subject')}",
        f"- Canonical source: {lock.get('canonical_source')}",
        f"- Out of scope: {', '.join(lock.get('out_of_scope') or []) or '—'}",
        "",
        "## Recent Timeline",
    ]
    timeline_events = events or []
    for event in timeline_events[:12]:
        lines.append(
            f"- {event.get('timestamp')} · {event.get('source')} · "
            f"{(event.get('actor') or {}).get('display_name', '?')} · "
            f"{event.get('direction')} · {event.get('title')}"
        )
    if not timeline_events:
        lines.append("- _No events linked._")
    lines.extend(["", "## Actions"])
    for action in packet.get("actions") or []:
        lines.append(f"- [ ] {action}")
    if not packet.get("actions"):
        lines.append("- [ ] Review canonical WorkPacket in Zab")
    lines.extend(
        [
            "",
            "## Links",
            f"- Zab WorkPacket: {packet.get('workpacket_id')}",
            f"- Canonical source: {lock.get('canonical_source')}",
            "",
            "## Gates",
        ]
    )
    for gate in packet.get("gates") or []:
        lines.append(f"- {gate}")
    if not packet.get("gates"):
        lines.append("- no email send without approval")
        lines.append("- no CRM mutation without approval")
    lines.extend(
        [
            "",
            "## Metadata",
            f"- workpacket_id: {packet.get('workpacket_id')}",
            f"- display_id: {packet.get('display_id')}",
            f"- projection_hash: {projection_hash(chr(10).join(lines))}",
        ]
    )
    return "\n".join(lines)


def project_linear(workpacket_id: str, *, dry_run: bool = True) -> dict[str, Any]:
    with local_db.transaction() as conn:
        packet = get_workpacket(conn, workpacket_id)
        if not packet:
            raise ValueError(f"workpacket not found: {workpacket_id}")
        from zab.services.conversation_ledger.store import get_event

        event_ids = packet.get("event_ids") or []
        events = []
        for eid in event_ids:
            item = get_event(conn, eid)
            if item:
                events.append(item)
        body = build_linear_description(packet, events=events)
        phash = projection_hash(body)
        projection = {
            "workpacket_id": workpacket_id,
            "target": "linear",
            "status": "dry_run" if dry_run else "projected",
            "issue_id": None,
            "url": None,
            "description_markdown": body,
            "projection_hash": phash,
            "last_synced_at": None if dry_run else packet.get("updated_at"),
            "last_seen_hash": phash,
        }
        if not dry_run:
            upsert_projection(conn, projection)
            packet.setdefault("projections", {})["linear"] = {
                "status": "projected",
                "projection_hash": phash,
            }
        return {
            "contract": "workpacket-linear-projection",
            "contract_version": "1.0",
            "dry_run": dry_run,
            "workpacket_id": workpacket_id,
            "projection_hash": phash,
            "description_markdown": body,
            "projection": projection,
        }


def import_linear_candidate(issue: dict[str, Any], *, workpacket_id: str) -> dict[str, Any]:
    """Linear issue becomes projection candidate, never canonical overwrite."""
    return {
        "workpacket_id": workpacket_id,
        "target": "linear",
        "status": "candidate",
        "issue_id": issue.get("identifier") or issue.get("id"),
        "url": issue.get("url"),
        "description_markdown": issue.get("description"),
        "note": "imported as candidate; canonical Zab record preserved",
    }
