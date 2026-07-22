"""Canonical WorkPacket = persisted intake + subject_lock + ledger links."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from zab.services.conversation_ledger.store import new_workpacket_id
from zab.services.workpacket_intake import (
    AUTHORITY_LEVELS,
    INTENT_KEYWORDS,
    WORKPACKET_STATES,
    intake_from_params,
)

CANONICAL_CONTRACT = "workpacket-canonical"
CANONICAL_VERSION = "1.0"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_subject_lock(
    *,
    client: str,
    project_or_workstream: str,
    subject: str,
    canonical_source: str,
    out_of_scope: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "client": client,
        "project_or_workstream": project_or_workstream,
        "subject": subject,
        "canonical_source": canonical_source,
        "out_of_scope": out_of_scope or [],
    }


def from_intake_and_cluster(
    *,
    intake_payload: dict[str, Any],
    organization_id: str,
    organization_label: str,
    client_workstream_id: str,
    client_workstream_label: str,
    subject: str,
    canonical_source_event_id: str,
    event_ids: list[str],
    zab_project_refs: list[str] | None = None,
    out_of_scope: list[str] | None = None,
    display_id: str | None = None,
    workpacket_id: str | None = None,
) -> dict[str, Any]:
    intake_packet = intake_payload.get("workpacket") or {}
    subject_lock = build_subject_lock(
        client=organization_label,
        project_or_workstream=client_workstream_label,
        subject=subject,
        canonical_source=canonical_source_event_id,
        out_of_scope=out_of_scope,
    )
    return {
        "contract": CANONICAL_CONTRACT,
        "contract_version": CANONICAL_VERSION,
        "intake_ref": "workpacket-intake",
        "intake_contract_version": intake_payload.get("contract_version", "1.0"),
        "workpacket_id": workpacket_id or new_workpacket_id(),
        "display_id": display_id,
        "title": f"{organization_label} - {client_workstream_label}",
        "organization_id": organization_id,
        "organization_label": organization_label,
        "client_workstream_id": client_workstream_id,
        "client_workstream_label": client_workstream_label,
        "zab_project_refs": zab_project_refs or [],
        "subject": subject,
        "subject_lock": subject_lock,
        "state": "candidate",
        "priority": intake_packet.get("priority", "P3"),
        "owner": intake_packet.get("owner", "Mehdi"),
        "authority": intake_packet.get("authority"),
        "intent": intake_packet.get("intent"),
        "policy_gates": intake_packet.get("policy_gates", []),
        "gates": [g.get("rule") for g in intake_packet.get("policy_gates", []) if g.get("rule")],
        "actions": intake_packet.get("next_actions", []),
        "canonical_source_event_id": canonical_source_event_id,
        "event_ids": event_ids,
        "receipts": [],
        "metadata": {
            "idempotency_key": intake_packet.get("idempotency_key"),
            "signal_hash": (intake_payload.get("signal") or {}).get("hash"),
        },
        "projections": {
            "linear": {"status": "not_projected"},
            "attio": {"status": "none"},
            "cockpit": {"status": "none"},
        },
        "created_at": _now(),
        "updated_at": _now(),
    }


def intake_signal_from_cluster(cluster: dict[str, Any]) -> str:
    events = cluster.get("events") or []
    if not events:
        return "WorkPacket candidate"
    top = events[0]
    return "\n".join(
        [
            str(top.get("title") or ""),
            str(top.get("snippet") or ""),
            f"organization={cluster.get('organization_label')}",
            f"workstream={cluster.get('client_workstream_label')}",
        ]
    ).strip()


def build_from_cluster(cluster: dict[str, Any], *, display_id: str | None = None) -> dict[str, Any]:
    signal = intake_signal_from_cluster(cluster)
    intake_payload = intake_from_params(signal, source="conversation_ledger", project=None, requested_by="agent")
    events = cluster.get("events") or []
    canonical = events[0]["event_id"] if events else f"seed:{cluster.get('client_workstream_id')}"
    subject = str(
        events[0].get("title")
        if events
        else cluster.get("client_workstream_label") or cluster.get("title") or "Untitled"
    )
    out_of_scope = [
        label
        for ws_id, label in {
            "cw_audit_crm": "Audit CRM",
            "cw_explorateurs_ia": "Explorateurs IA",
            "cw_securite_deessi": "Sécurité Deessi",
        }.items()
        if ws_id != cluster.get("client_workstream_id")
    ]
    zab_refs = []
    for event in events:
        for link in event.get("entity_links") or []:
            if link.get("entity_type") == "zab_project" and link.get("entity_id"):
                zab_refs.append(str(link["entity_id"]))
    return from_intake_and_cluster(
        intake_payload=intake_payload,
        organization_id=str(cluster.get("organization_id") or "org_unknown"),
        organization_label=str(cluster.get("organization_label") or "Unknown"),
        client_workstream_id=str(cluster.get("client_workstream_id") or "unclassified"),
        client_workstream_label=str(cluster.get("client_workstream_label") or "Unclassified"),
        subject=subject,
        canonical_source_event_id=canonical,
        event_ids=[str(e.get("event_id")) for e in events if e.get("event_id")],
        zab_project_refs=sorted(set(zab_refs)),
        out_of_scope=out_of_scope if cluster.get("organization_id") == "org_arp_astrance" else [],
        display_id=display_id,
    )


# Re-export intake constants for consumers/tests
__all__ = [
    "AUTHORITY_LEVELS",
    "INTENT_KEYWORDS",
    "WORKPACKET_STATES",
    "build_from_cluster",
    "build_subject_lock",
    "from_intake_and_cluster",
]
