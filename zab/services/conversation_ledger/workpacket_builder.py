"""Discover and reconstruct WorkPacket candidates from indexed events."""

from __future__ import annotations

import json

from collections import Counter, defaultdict
from datetime import datetime, timezone
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


def _org_for_project(project: str, *, project_path: str | None = None) -> tuple[str | None, str | None]:
    """Organisation d'un projet, déduite de son nom.

    Le nom d'un dépôt porte presque toujours son rattachement : `danmdata` est
    un chantier client, `flowmetrik-cowork` est interne. On réutilise la même
    résolution que pour le courrier plutôt que d'inventer une table de plus.
    """
    from zab.services.conversation_ledger.entity_resolver import (
        DEFAULT_ORGANIZATIONS,
        resolve_organization,
    )
    from zab.services.conversation_ledger.org_profiles import INTERNAL_ORG_IDS

    name = str(project or "").replace("-", " ").replace("_", " ").strip()
    # Le chemin est plus fiable que le nom : un dépôt rangé dans un espace de
    # travail hérite de son organisation, même si son nom ne l'évoque pas.
    haystack = f"{name} {str(project_path or '').replace('-', ' ').replace('/', ' ')}".strip()
    if not haystack:
        return None, None
    org_id, org_label, _conf, _evidence = resolve_organization(text=name)
    if org_id:
        return org_id, org_label
    # Convention des espaces de travail : `<organisation>-cowork`. Le préfixe
    # suffit à rattacher un dépôt dont le nom complet ne dit rien au résolveur.
    prefix = str(project or "").split("-cowork")[0].split("_cowork")[0].strip().lower()
    if prefix and prefix != str(project or "").strip().lower():
        for candidate_id, org in DEFAULT_ORGANIZATIONS.items():
            names = [candidate_id.removeprefix("org_"), str(org.get("label") or "")]
            names += list(org.get("aliases") or [])
            if any(str(n).lower().replace(" ", "-").startswith(prefix) for n in names if n):
                return candidate_id, org.get("label") or candidate_id

    # Les alias internes sont volontairement ignorés côté courrier ; sur un nom
    # de projet, en revanche, ils sont le signal le plus fiable.
    for internal_id in sorted(INTERNAL_ORG_IDS):
        org = DEFAULT_ORGANIZATIONS.get(internal_id) or {}
        for alias in org.get("aliases") or []:
            if len(alias) >= 4 and alias in haystack.lower():
                return internal_id, org.get("label") or internal_id
    return None, None


def discover_workpackets_from_intent(
    *,
    days: int = 7,
    limit: int = 100,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Crée un WorkPacket par tâche réellement démarrée dans une conversation d'agent.

    La découverte historique part du courrier reçu : elle décrit des dossiers
    clients, pas des tâches. Ici le déclencheur est l'intention — ce que
    l'utilisateur a demandé à un agent — et le ledger d'interactions ne sert
    qu'à enrichir ensuite.
    """
    from zab.services.conversation_ledger.intent_signals import (
        classify_intent,
        intent_key,
        intent_title,
        is_human_intent,
    )
    from zab.services.conversation_ledger.store import get_workpacket
    from zab.services.conversation_digest import build_conversation_digest
    from zab.services.workpacket_intake import intake_from_params
    from zab.services.conversation_ledger.workpacket import from_intake_and_cluster

    digest = build_conversation_digest(days=days, limit=300, include_subagents=False)
    items = digest.get("items") or []
    rejected = Counter(
        classify_intent(item.get("intent")) for item in items if not is_human_intent(item.get("intent"))
    )

    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        if not is_human_intent(item.get("intent")):
            continue
        project = str(item.get("project") or "sans-projet")
        groups[(project, intent_key(item.get("intent")))].append(item)

    now = datetime.now(timezone.utc)
    candidates: list[dict[str, Any]] = []
    for (project, key), members in groups.items():
        members.sort(key=lambda row: str(row.get("updated_at") or ""))
        latest = members[-1]
        intent_text = str(latest.get("intent") or "")
        org_id, org_label = _org_for_project(project, project_path=latest.get("project_path"))
        intake = intake_from_params(
            intent_text, source="conversation_ledger", project=project, requested_by="Mehdi"
        )
        packet = from_intake_and_cluster(
            intake_payload=intake,
            organization_id=org_id or "org_unassigned",
            organization_label=org_label or "Sans organisation",
            client_workstream_id=f"proj_{project}",
            client_workstream_label=project,
            subject=intent_title(intent_text),
            canonical_source_event_id=f"conversation:{latest.get('conversation_id')}",
            event_ids=[f"conversation:{row.get('conversation_id')}" for row in members],
            zab_project_refs=[project],
        )
        packet["title"] = f"{org_label or project} — {intent_title(intent_text)}"
        packet["owner"] = "Mehdi"
        packet["metadata"] = {
            **(packet.get("metadata") or {}),
            "intent_key": key,
            "project": project,
            "session_count": len(members),
            "agent_tools": sorted({str(row.get("agent_tool")) for row in members if row.get("agent_tool")}),
            "last_session_at": latest.get("updated_at"),
        }
        packet["actions"] = _intent_actions(members, project=project, now=now)
        packet["state"] = _intent_state(latest.get("updated_at"), now=now)
        candidates.append(packet)

    candidates.sort(key=lambda p: str(p["metadata"].get("last_session_at") or ""), reverse=True)
    candidates = candidates[: max(1, min(int(limit), 300))]

    created = updated = 0
    stored: list[dict[str, Any]] = []
    if not dry_run:
        with local_db.transaction() as conn:
            by_key = {
                str((p.get("metadata") or {}).get("intent_key")): p
                for p in list_workpackets(conn, limit=1000)
                if (p.get("metadata") or {}).get("intent_key")
            }
            for packet in candidates:
                existing = by_key.get(packet["metadata"]["intent_key"])
                if existing:
                    packet["workpacket_id"] = existing["workpacket_id"]
                    packet["display_id"] = existing.get("display_id")
                    packet["created_at"] = existing.get("created_at") or packet.get("created_at")
                    updated += 1
                else:
                    packet["display_id"] = next_display_id(conn)
                    created += 1
                stored.append(upsert_workpacket(conn, packet))
        _ = get_workpacket  # conservé pour les consommateurs qui rechargent après écriture

    return {
        "contract": "workpacket-intent-discovery",
        "contract_version": "1.0",
        "dry_run": dry_run,
        "window_days": days,
        "conversations_scanned": digest.get("scanned_conversations"),
        "conversations_retained": len(items),
        "human_intents": sum(len(v) for v in groups.values()),
        "rejected_intents": dict(rejected),
        "candidate_count": len(candidates),
        "created_count": created,
        "updated_count": updated,
        "candidates": stored or candidates,
    }


def _intent_state(last_session_at: Any, *, now: datetime) -> str:
    parsed = _parse_iso(last_session_at)
    if parsed is None:
        return "candidate"
    days = (now - parsed).days
    if days <= 14:
        return "active"
    if days <= 60:
        return "candidate"
    return "archived"


def _intent_actions(members: list[dict[str, Any]], *, project: str, now: datetime) -> list[str]:
    latest = members[-1]
    parsed = _parse_iso(latest.get("updated_at"))
    days = (now - parsed).days if parsed else None
    tools = ", ".join(sorted({str(row.get("agent_tool")) for row in members if row.get("agent_tool")}))
    when = "aujourd'hui" if days == 0 else (f"il y a {days} j" if days is not None else "date inconnue")
    actions = [
        f"Reprendre le travail sur {project} — {len(members)} session(s) {tools or 'agent'}, dernière {when}."
    ]
    if days is not None and days >= 7:
        actions.append(f"Sans reprise depuis {days} j : conclure, replanifier ou abandonner explicitement.")
    return actions


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def backfill_workpackets(*, dry_run: bool = True, limit: int = 200) -> dict[str, Any]:
    """Réécrit titre, état et actions des paquets stockés depuis les faits du ledger.

    Les paquets existants gardent leur identité (organisation + workstream) et
    leurs sources : seule leur lecture est refaite. Idempotent — relancer sans
    nouvel évènement ne produit aucune différence.
    """
    from zab.services.conversation_ledger.entity_registry import list_organizations
    from zab.services.conversation_ledger.org_profiles import INTERNAL_DOMAINS
    from zab.services.entity_graph import key_people_for, link_projects, people_from_events
    from zab.services.workspace_projects import discover_projects

    with local_db.transaction() as conn:
        packets = list_workpackets(conn, limit=limit)
        organizations = list_organizations(conn)
        all_events = [
            json.loads(row[0])
            for row in conn.execute("SELECT payload_json FROM ledger_events").fetchall()
        ]

    # Le graphe est résolu une fois pour tous les paquets : les projets locaux et
    # les interlocuteurs ne dépendent pas du paquet, seulement de l'organisation.
    graph = link_projects(discover_projects(), organizations)
    projects_by_org = graph["projects_by_organization"]
    people = people_from_events(all_events, organizations, internal_domains=INTERNAL_DOMAINS)["people"]

    results: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    for packet in packets:
        organization_id = str(packet.get("organization_id") or "")
        with local_db.transaction() as conn:
            events = list_events(
                conn,
                organization_id=organization_id or None,
                client_workstream_id=str(packet.get("client_workstream_id") or "") or None,
                limit=1000,
            )
        updated, changes = rebuild_packet(
            packet,
            events,
            project_refs=projects_by_org.get(organization_id, []),
            key_people=key_people_for(people, organization_id=organization_id),
        )
        entry = {
            "workpacket_id": updated.get("workpacket_id"),
            "display_id": updated.get("display_id"),
            "title": updated.get("title"),
            "state": updated.get("state"),
            "actions": updated.get("actions"),
            "event_count": len(events),
            "project_refs": updated.get("zab_project_refs") or [],
            "key_people": updated.get("key_people") or [],
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
