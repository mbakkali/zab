"""Discover and reconstruct WorkPacket candidates from indexed events."""

from __future__ import annotations

from typing import Any

from zab.services import local_db
from zab.services.conversation_ledger.clustering import cluster_events
from zab.services.conversation_ledger.store import (
    find_workpacket,
    list_events,
    list_workpackets,
    next_display_id,
    upsert_workpacket,
)
from zab.services.conversation_ledger.sync import parse_since
from zab.services.conversation_ledger.workpacket import build_from_cluster
from zab.services.conversation_ledger.workpacket_backfill import rebuild_packet

SEED_CANDIDATES: list[dict[str, str]] = [
    {
        "organization_id": "org_arp_astrance",
        "client_workstream_id": "cw_audit_crm",
        "label": "ARP Astrance - Audit CRM",
    },
    {
        "organization_id": "org_arp_astrance",
        "client_workstream_id": "cw_explorateurs_ia",
        "label": "ARP Astrance - Explorateurs IA",
    },
    {
        "organization_id": "org_arp_astrance",
        "client_workstream_id": "cw_securite_deessi",
        "label": "ARP Astrance - Sécurité Deessi",
    },
    {
        "organization_id": "org_carrefour",
        "client_workstream_id": "cw_delivery",
        "label": "Carrefour - Delivery",
    },
    {
        "organization_id": "org_sogeprom",
        "client_workstream_id": "cw_agent_ia",
        "label": "Sogeprom - Agent IA foncier",
    },
    {
        "organization_id": "org_tikehau",
        "client_workstream_id": "cw_relance",
        "label": "Tikehau/Sofidy - Relance proposition",
    },
    {
        "organization_id": "org_bnp_expertise",
        "client_workstream_id": "cw_demo",
        "label": "BNP Expertise - Demo agent IA",
    },
    {
        "organization_id": "org_agile_immo",
        "client_workstream_id": "cw_maintenance",
        "label": "Agile Immo - Step 2 maintenance",
    },
    {
        "organization_id": "org_mastora",
        "client_workstream_id": "cw_formation",
        "label": "Mastora - Formations",
    },
    {
        "organization_id": "org_arthur_loyd",
        "client_workstream_id": "cw_formation_facturation",
        "label": "Arthur Loyd - Formation et facturation",
    },
]


def discover_workpackets(
    *,
    since: str | None = None,
    min_confidence: float = 0.65,
    limit: int = 7,
    dry_run: bool = False,
) -> dict[str, Any]:
    candidate_limit = max(1, min(int(limit), 100))
    resolved_since = parse_since(since) if since else None
    with local_db.transaction() as conn:
        events = list_events(conn, since=resolved_since, limit=5000)
    org_ids = sorted(
        {str(e.get("organization_id")) for e in events if e.get("organization_id")}
    )
    clusters: list[dict[str, Any]] = []
    for org_id in org_ids or ["org_unknown"]:
        org_events = [
            e
            for e in events
            if str(e.get("organization_id") or "org_unknown") == org_id
        ]
        clusters.extend(cluster_events(org_events, organization_id=org_id))
    discovered: list[dict[str, Any]] = []
    for cluster in clusters:
        if cluster.get("client_workstream_id") == "unclassified":
            continue
        avg_conf = sum(
            float(e.get("workstream_confidence") or 0)
            for e in cluster.get("events") or []
        ) / max(len(cluster.get("events") or []), 1)
        if avg_conf < min_confidence:
            continue
        cluster["organization_label"] = _org_label(cluster)
        cluster["organization_id"] = _org_id(cluster)
        packet = build_from_cluster(cluster)
        packet["confidence"] = round(avg_conf, 2)
        discovered.append(packet)

    existing_keys: set[tuple[str, str]] = set()
    with local_db.transaction() as conn:
        for packet in discovered:
            org_id = str(packet.get("organization_id") or "")
            workstream_id = str(packet.get("client_workstream_id") or "")
            if find_workpacket(
                conn,
                organization_id=org_id,
                client_workstream_id=workstream_id,
            ):
                existing_keys.add((org_id, workstream_id))
    new_candidates = [
        packet
        for packet in discovered
        if (
            str(packet.get("organization_id") or ""),
            str(packet.get("client_workstream_id") or ""),
        )
        not in existing_keys
    ]
    existing_candidates = [
        packet
        for packet in discovered
        if (
            str(packet.get("organization_id") or ""),
            str(packet.get("client_workstream_id") or ""),
        )
        in existing_keys
    ]
    candidates = [*new_candidates, *existing_candidates][:candidate_limit]

    stored: list[dict[str, Any]] = []
    created_count = 0
    updated_count = 0
    if not dry_run:
        with local_db.transaction() as conn:
            for packet in candidates:
                existing = find_workpacket(
                    conn,
                    organization_id=str(packet.get("organization_id") or ""),
                    client_workstream_id=str(packet.get("client_workstream_id") or ""),
                )
                if existing:
                    packet["workpacket_id"] = existing["workpacket_id"]
                    packet["display_id"] = existing.get(
                        "display_id"
                    ) or next_display_id(conn)
                    packet["created_at"] = existing.get("created_at") or packet.get(
                        "created_at"
                    )
                    created = False
                    updated_count += 1
                else:
                    packet["display_id"] = next_display_id(conn)
                    created = True
                    created_count += 1
                saved = upsert_workpacket(conn, packet)
                saved["_flowgo_created"] = created
                stored.append(saved)

    return {
        "contract": "workpacket-discover",
        "contract_version": "1.0",
        "dry_run": dry_run,
        "since": since,
        "resolved_since": resolved_since,
        "min_confidence": min_confidence,
        "limit": candidate_limit,
        "candidate_count": len(candidates),
        "eligible_count": len(discovered),
        "new_candidate_count": len(new_candidates),
        "created_count": created_count,
        "updated_count": updated_count,
        "candidates": stored or candidates,
    }


def backfill_workpackets(*, dry_run: bool = True, limit: int = 200) -> dict[str, Any]:
    """Réécrit titre, état et actions des paquets stockés depuis les faits du ledger.

    Les paquets existants gardent leur identité (organisation + workstream) et
    leurs sources : seule leur lecture est refaite. Idempotent — relancer sans
    nouvel évènement ne produit aucune différence.
    """
    with local_db.transaction() as conn:
        packets = list_workpackets(conn, limit=limit)

    results: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    for packet in packets:
        with local_db.transaction() as conn:
            events = list_events(
                conn,
                organization_id=str(packet.get("organization_id") or "") or None,
                client_workstream_id=str(packet.get("client_workstream_id") or "") or None,
                limit=1000,
            )
        updated, changes = rebuild_packet(packet, events)
        entry = {
            "workpacket_id": updated.get("workpacket_id"),
            "display_id": updated.get("display_id"),
            "title": updated.get("title"),
            "state": updated.get("state"),
            "actions": updated.get("actions"),
            "event_count": len(events),
            "changes": changes,
        }
        results.append(entry)
        if changes:
            changed.append(entry)
            if not dry_run:
                with local_db.transaction() as conn:
                    upsert_workpacket(conn, updated)

    return {
        "contract": "workpacket-backfill",
        "contract_version": "1.0",
        "dry_run": dry_run,
        "scanned_count": len(packets),
        "changed_count": len(changed),
        "state_counts": _count_by(results, "state"),
        "items": results,
    }


def _count_by(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get(field) or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _org_label(cluster: dict[str, Any]) -> str:
    events = cluster.get("events") or []
    for event in events:
        if event.get("organization_label"):
            return str(event["organization_label"])
    return "Unknown"


def _org_id(cluster: dict[str, Any]) -> str:
    events = cluster.get("events") or []
    for event in events:
        if event.get("organization_id"):
            return str(event["organization_id"])
    return "org_unknown"


def reconstruct_seed_candidates(*, dry_run: bool = True) -> dict[str, Any]:
    """Build 10 seed WorkPackets from indexed events or minimal placeholders."""
    from zab.paths import data_dir

    with local_db.transaction() as conn:
        events = list_events(conn, limit=2000)
    all_clusters = cluster_events(events, organization_id="mixed")
    by_ws = {c.get("client_workstream_id"): c for c in all_clusters}
    results: list[dict[str, Any]] = []
    markdown_sections: list[str] = ["# WorkPacket reconstruction report", ""]
    with local_db.transaction() as conn:
        for idx, seed in enumerate(SEED_CANDIDATES, start=1):
            cluster = by_ws.get(seed["client_workstream_id"])
            if cluster:
                cluster["organization_id"] = seed["organization_id"]
                cluster["organization_label"] = seed["label"].split(" - ")[0]
                packet = build_from_cluster(cluster, display_id=f"ZWP-{idx:04d}")
            else:
                packet = build_from_cluster(
                    {
                        "organization_id": seed["organization_id"],
                        "organization_label": seed["label"].split(" - ")[0],
                        "client_workstream_id": seed["client_workstream_id"],
                        "client_workstream_label": seed["label"].split(" - ", 1)[-1],
                        "events": [],
                    },
                    display_id=f"ZWP-{idx:04d}",
                )
            packet["title"] = seed["label"]
            packet["state"] = "candidate"
            display_id = f"ZWP-{idx:04d}"
            existing = find_workpacket(
                conn,
                organization_id=seed["organization_id"],
                client_workstream_id=seed["client_workstream_id"],
                display_id=display_id,
            )
            if existing:
                packet["workpacket_id"] = existing["workpacket_id"]
                packet["display_id"] = existing.get("display_id") or display_id
                packet["created_at"] = existing.get("created_at") or packet.get(
                    "created_at"
                )
            if not dry_run:
                results.append(upsert_workpacket(conn, packet))
            else:
                results.append(packet)
            markdown_sections.append(format_workpacket_markdown(packet))
    report_md = "\n".join(markdown_sections)
    report_path = data_dir() / "ledger" / "workpacket_reconstruct_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_md, encoding="utf-8")
    return {
        "contract": "workpacket-reconstruct",
        "count": len(results),
        "workpackets": results,
        "report_path": str(report_path),
        "markdown": report_md,
    }


def format_workpacket_markdown(packet: dict[str, Any]) -> str:
    lock = packet.get("subject_lock") or {}
    lines = [
        f"# {packet.get('title')}",
        "",
        f"- ID: `{packet.get('workpacket_id')}` ({packet.get('display_id')})",
        f"- State: {packet.get('state')}",
        f"- Priority: {packet.get('priority')}",
        f"- Confidence: {packet.get('confidence', 'n/a')}",
        "",
        "## Subject Lock",
        f"- Client: {lock.get('client')}",
        f"- Project / workstream: {lock.get('project_or_workstream')}",
        f"- Subject: {lock.get('subject')}",
        f"- Canonical source: {lock.get('canonical_source')}",
        f"- Out of scope: {', '.join(lock.get('out_of_scope') or []) or '—'}",
        "",
        "## Recent Timeline",
    ]
    event_ids = packet.get("event_ids") or []
    if not event_ids:
        lines.append("- _No linked events yet._")
    else:
        lines.append(f"- {len(event_ids)} linked events")
    lines.extend(["", "## Actions"])
    for action in packet.get("actions") or []:
        lines.append(f"- [ ] {action}")
    if not packet.get("actions"):
        lines.append("- _No open actions inferred._")
    lines.extend(["", "## Gates"])
    for gate in packet.get("gates") or []:
        lines.append(f"- {gate}")
    proj = (packet.get("projections") or {}).get("linear") or {}
    lines.extend(
        ["", "## Projections", f"- Linear: {proj.get('status', 'not_projected')}"]
    )
    return "\n".join(lines) + "\n"
