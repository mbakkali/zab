"""Rapports de rattachement : ce qui est relié à une organisation, et ce qui ne l'est pas.

Sépare la lecture de la base du calcul pur d'`entity_graph`, qui reste testable
sans base ni système de fichiers.
"""

from __future__ import annotations

import json
from typing import Any

from zab.services import local_db
from zab.services.conversation_ledger.entity_registry import list_organizations
from zab.services.conversation_ledger.org_profiles import INTERNAL_DOMAINS
from zab.services.conversation_ledger.store import list_workpackets
from zab.services.entity_graph import (
    link_projects,
    people_from_events,
    suggest_organization_domains,
)
from zab.services.workspace_projects import discover_projects


def _load() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    with local_db.transaction() as conn:
        organizations = list_organizations(conn)
        events = [
            json.loads(row[0])
            for row in conn.execute("SELECT payload_json FROM ledger_events").fetchall()
        ]
        packets = list_workpackets(conn, limit=500)
    return organizations, events, packets


def _pct(part: int, total: int) -> float:
    return round(100 * part / total, 1) if total else 0.0


def coverage_report() -> dict[str, Any]:
    organizations, events, packets = _load()
    projects = discover_projects()

    graph = link_projects(projects, organizations)
    people = people_from_events(events, organizations, internal_domains=INTERNAL_DOMAINS)

    with_org = sum(1 for e in events if e.get("organization_id"))
    with_ws = sum(1 for e in events if e.get("client_workstream_id"))

    return {
        "contract": "entity-coverage",
        "contract_version": "1.0",
        "organizations": {"total": len(organizations)},
        "events": {
            "total": len(events),
            "with_organization": with_org,
            "organization_pct": _pct(with_org, len(events)),
            "with_workstream": with_ws,
            "workstream_pct": _pct(with_ws, len(events)),
        },
        "projects": {
            "total": len(projects),
            "linked_count": graph["linked_count"],
            "unlinked_count": graph["unlinked_count"],
            "organizations_covered": graph["organizations_covered"],
        },
        "people": {
            "recurring": people["people_count"],
            "counterpart_count": people["counterpart_count"],
            "attached_count": people["attached_count"],
            "unattached_count": people["unattached_count"],
        },
        "workpackets": {
            "total": len(packets),
            "with_projects": sum(1 for p in packets if p.get("zab_project_refs")),
            "with_people": sum(1 for p in packets if p.get("key_people")),
        },
        "suggested_domains": suggest_organization_domains(people["people"]),
    }


def people_report(*, organization_id: str | None = None, limit: int = 20) -> dict[str, Any]:
    organizations, events, _packets = _load()
    people = people_from_events(events, organizations, internal_domains=INTERNAL_DOMAINS)
    rows = [row for row in people["people"] if row["is_counterpart"]]
    if organization_id:
        needle = organization_id.lower()
        rows = [
            row
            for row in rows
            if needle in str(row.get("organization_id") or "").lower()
        ]
    return {
        "contract": "entity-people",
        "contract_version": "1.0",
        "count": len(rows),
        "people": rows[: max(1, limit)],
    }


def projects_report() -> dict[str, Any]:
    organizations, _events, _packets = _load()
    graph = link_projects(discover_projects(), organizations)
    return {"contract": "entity-projects", "contract_version": "1.0", **graph}
