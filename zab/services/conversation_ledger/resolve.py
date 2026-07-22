"""Resolution helpers: unclassified events, manual links, dry-run resolve."""

from __future__ import annotations

from typing import Any

from zab.services import local_db
from zab.services.conversation_ledger.clustering import cluster_events
from zab.services.conversation_ledger.entity_resolver import (
    DEFAULT_ORGANIZATIONS,
    WORKSTREAM_SEEDS,
    build_entity_links,
    resolve_organization,
    resolve_workstream,
)
from zab.services.conversation_ledger.store import get_event, list_events, upsert_event


def _match_org(organization: str) -> tuple[str | None, str | None]:
    needle = organization.lower()
    from zab.services.conversation_ledger.org_profiles import ORG_PROFILES

    for org_id, profile in ORG_PROFILES.items():
        if needle in org_id.lower() or needle in profile["label"].lower():
            return org_id, profile["label"]
    for org_id, org in DEFAULT_ORGANIZATIONS.items():
        if needle in org_id.lower() or needle in org["label"].lower():
            return org_id, org["label"]
    return None, None


def _match_workstream(client_workstream: str) -> tuple[str | None, str | None]:
    needle = client_workstream.lower()
    for ws_id, ws in WORKSTREAM_SEEDS.items():
        if needle in ws_id.lower() or needle in ws["label"].lower():
            return ws_id, ws["label"]
    return None, None


def list_unclassified(*, since: str | None = None, limit: int = 100) -> dict[str, Any]:
    with local_db.transaction() as conn:
        events = list_events(conn, limit=limit * 3)
    ambiguous = []
    for event in events:
        if since and str(event.get("timestamp") or "") < since:
            continue
        ws = event.get("client_workstream_id")
        if not ws or ws == "unclassified":
            text = f"{event.get('title')} {event.get('snippet')}"
            org_id, org_label, org_conf, _ = resolve_organization(text=text)
            ws_id, ws_label, ws_conf, evidence = resolve_workstream(text=text, organization_id=org_id)
            ambiguous.append(
                {
                    "event_id": event.get("event_id"),
                    "title": event.get("title"),
                    "timestamp": event.get("timestamp"),
                    "hypotheses": {
                        "organization": {"id": org_id, "label": org_label, "confidence": org_conf},
                        "client_workstream": {"id": ws_id, "label": ws_label, "confidence": ws_conf, "evidence": evidence},
                    },
                }
            )
        if len(ambiguous) >= limit:
            break
    return {"contract": "interactions-unclassified", "count": len(ambiguous), "items": ambiguous}


def resolve_preview(
    *,
    organization: str,
    client_workstream: str | None = None,
    since: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    org_id, org_label = _match_org(organization)
    ws_id, ws_label = (None, None)
    if client_workstream:
        ws_id, ws_label = _match_workstream(client_workstream)
    with local_db.transaction() as conn:
        events = list_events(conn, organization_id=org_id, client_workstream_id=ws_id, since=since, limit=500)
    clusters = cluster_events(events, organization_id=org_id or "org_unknown")
    return {
        "contract": "interactions-resolve",
        "dry_run": dry_run,
        "organization": {"id": org_id, "label": org_label},
        "client_workstream": {"id": ws_id, "label": ws_label},
        "event_count": len(events),
        "cluster_count": len(clusters),
        "clusters": [
            {
                "client_workstream_id": c.get("client_workstream_id"),
                "client_workstream_label": c.get("client_workstream_label"),
                "event_count": len(c.get("events") or []),
            }
            for c in clusters
        ],
    }


def link_event(
    event_id: str,
    *,
    organization: str,
    client_workstream: str,
    confirm: bool = False,
) -> dict[str, Any]:
    org_id, org_label = _match_org(organization)
    ws_id, ws_label = _match_workstream(client_workstream)
    if not org_id or not ws_id:
        raise ValueError("organization or client_workstream not recognized")
    with local_db.transaction() as conn:
        event = get_event(conn, event_id)
        if not event:
            raise ValueError(f"event not found: {event_id}")
        links = list(event.get("entity_links") or [])
        links = [link for link in links if link.get("entity_type") not in {"organization", "client_workstream"}]
        status = "confirmed" if confirm else "candidate"
        links.extend(
            [
                {
                    "entity_type": "organization",
                    "entity_id": org_id,
                    "label": org_label,
                    "confidence": 1.0 if confirm else 0.9,
                    "evidence": ["manual link"],
                    "status": status,
                },
                {
                    "entity_type": "client_workstream",
                    "entity_id": ws_id,
                    "label": ws_label,
                    "confidence": 1.0 if confirm else 0.9,
                    "evidence": ["manual link"],
                    "status": status,
                },
            ]
        )
        event["entity_links"] = links
        event["organization_id"] = org_id
        event["organization_label"] = org_label
        event["client_workstream_id"] = ws_id
        event["client_workstream_label"] = ws_label
        if confirm:
            saved = upsert_event(conn, event)
        else:
            saved = event
    return {"contract": "interactions-link", "confirmed": confirm, "event": saved}
