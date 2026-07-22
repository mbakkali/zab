"""Daily digest and connectique report."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from zab.services import local_db
from zab.services.conversation_ledger.channel_bindings import list_channels
from zab.services.conversation_ledger.store import list_events, list_workpackets


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_daily_digest(*, since: str = "1d") -> str:
    since_dt = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    if since == "yesterday":
        since_dt = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()

    with local_db.transaction() as conn:
        events = list_events(conn, since=since_dt, limit=100)
        packets = list_workpackets(conn, limit=50)
    channels = list_channels(check=True)

    day = datetime.now(timezone.utc).date().isoformat()
    lines = [f"# Digest interactions - {day}", "", "## Nouveaux signaux importants"]
    if events:
        for event in events[:8]:
            org = event.get("organization_label") or "Unknown"
            ws = event.get("client_workstream_label") or "—"
            lines.append(
                f"- [{org} / {ws}] {event.get('source')} · "
                f"{(event.get('actor') or {}).get('display_name', '?')} · {event.get('title')}"
            )
    else:
        lines.append("- _No new indexed signals._")

    lines.extend(["", "## WorkPackets mis à jour"])
    updated = [p for p in packets if str(p.get("updated_at") or "") >= since_dt]
    if updated:
        for packet in updated[:8]:
            lines.append(f"- [{packet.get('display_id')}] {packet.get('title')} · state={packet.get('state')}")
    else:
        lines.append("- _No WorkPacket updates._")

    lines.extend(["", "## Ambigus à classer"])
    ambiguous = [e for e in events if not e.get("client_workstream_id") or e.get("client_workstream_id") == "unclassified"]
    if ambiguous:
        for event in ambiguous[:5]:
            lines.append(f"- {event.get('title')} · hypothesis: review organization/workstream")
    else:
        lines.append("- _None._")

    lines.extend(["", "## Connectique"])
    for channel in channels.get("channels") or []:
        lines.append(
            f"- {channel.get('channel_id')}: {channel.get('last_check_status')} · {channel.get('last_check_reason')}"
        )

    lines.extend(["", "## Focus propose"])
    focus = [p for p in packets if p.get("state") in {"active", "candidate", "in_progress"}][:3]
    if focus:
        for packet in focus:
            lines.append(f"- {packet.get('title')} · next: {(packet.get('actions') or ['review'])[0]}")
    else:
        lines.append("- _No focus items._")
    return "\n".join(lines) + "\n"


def digest_payload(*, since: str = "1d") -> dict[str, Any]:
    return {
        "contract": "workpacket-daily-digest",
        "contract_version": "1.0",
        "generated_at_utc": _now(),
        "markdown": build_daily_digest(since=since),
    }
