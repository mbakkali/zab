"""Heuristic clustering for organization + client_workstream + subject."""

from __future__ import annotations

import re
from collections import defaultdict
from hashlib import sha256
from typing import Any

from zab.services.conversation_ledger.entity_resolver import WORKSTREAM_SEEDS

PARTICIPANT_WORKSTREAM_HINTS: dict[str, str] = {
    "anne-sophie delamare": "cw_audit_crm",
    "asdelamare": "cw_audit_crm",
    "nicolas bonhomme": "cw_audit_crm",
    "nbonhomme": "cw_audit_crm",
    "julie vinay": "cw_securite_deessi",
    "jvinay": "cw_securite_deessi",
    "gaëtan d'amécourt": "cw_explorateurs_ia",
    "gdamecourt": "cw_explorateurs_ia",
    "stephanie": "cw_maintenance",
    "yannis": "cw_maintenance",
}

SCHEDULING_NOISE_TERMS = (
    "appointment booked",
    "acceptée",
    "acceptee",
    "prise de rdv",
    "invitation:",
    "updated invitation",
    "canceled:",
    "annulé",
)


def workstream_labels() -> dict[str, str]:
    return {ws_id: str(ws.get("label") or ws_id) for ws_id, ws in WORKSTREAM_SEEDS.items()}


def _keywords_for_org(organization_id: str | None) -> dict[str, tuple[str, ...]]:
    rows: dict[str, tuple[str, ...]] = {}
    for ws_id, ws in WORKSTREAM_SEEDS.items():
        if organization_id and ws.get("organization_id") != organization_id:
            continue
        keywords = tuple(str(k) for k in (ws.get("keywords") or ()))
        if keywords:
            rows[ws_id] = keywords
    return rows


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def is_scheduling_noise(text: str) -> bool:
    normalized = _normalize(text)
    return any(term in normalized for term in SCHEDULING_NOISE_TERMS)


def classify_workstream(text: str, *, organization_id: str | None = None) -> tuple[str, str, float]:
    normalized = _normalize(text)
    labels = workstream_labels()
    if not organization_id:
        from zab.services.conversation_ledger.entity_resolver import resolve_organization

        organization_id, _, org_conf, _ = resolve_organization(text=text)
        if not organization_id or org_conf < 0.7:
            return "unclassified", "Unclassified", 0.0
    keywords_map = _keywords_for_org(organization_id)
    scores: dict[str, int] = {}
    for ws_id, keywords in keywords_map.items():
        hit = sum(1 for kw in keywords if kw in normalized)
        if hit:
            scores[ws_id] = hit
    if scores:
        best = max(scores, key=lambda k: scores[k])
        confidence = min(0.95, 0.5 + 0.1 * scores[best])
        return best, labels.get(best, best), round(confidence, 2)
    if organization_id == "org_arp_astrance":
        for participant, ws_id in PARTICIPANT_WORKSTREAM_HINTS.items():
            if participant in normalized and ws_id in keywords_map:
                return ws_id, labels.get(ws_id, ws_id), 0.72
    return "unclassified", "Unclassified", 0.0


def subject_fingerprint(text: str) -> str:
    normalized = re.sub(r"^(re:|fw:|fwd:|acceptée|acceptee|réponse automatique)\s*", "", _normalize(text), flags=re.I)
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    tokens = [t for t in normalized.split() if len(t) > 2][:8]
    material = " ".join(tokens)
    return sha256(material.encode("utf-8")).hexdigest()[:12]


def cluster_events(events: list[dict[str, Any]], *, organization_id: str) -> list[dict[str, Any]]:
    threads: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        thread_key = str(event.get("thread_id") or event.get("native_id") or event.get("event_id"))
        threads[thread_key].append(event)

    enriched_events: list[dict[str, Any]] = []
    for _thread_key, thread_events in threads.items():
        org_id = organization_id if organization_id != "mixed" else None
        for ev in thread_events:
            if ev.get("organization_id"):
                org_id = str(ev.get("organization_id"))
        combined = " ".join(str(ev.get("title") or "") + " " + str(ev.get("snippet") or "") for ev in thread_events)
        ws_id, ws_label, confidence = classify_workstream(combined, organization_id=org_id)
        for event in thread_events:
            text = " ".join(
                [
                    str(event.get("title") or ""),
                    str(event.get("snippet") or ""),
                    str((event.get("actor") or {}).get("display_name") or ""),
                ]
            )
            event_org = str(event.get("organization_id") or org_id or "")
            event_ws_id, event_ws_label, event_conf = classify_workstream(
                text,
                organization_id=event_org or None,
            )
            final_ws = ws_id if ws_id != "unclassified" else event_ws_id
            final_label = ws_label if ws_id != "unclassified" else event_ws_label
            final_conf = max(confidence, event_conf)
            enriched = dict(event)
            enriched["client_workstream_id"] = final_ws
            enriched["client_workstream_label"] = final_label
            enriched["workstream_confidence"] = final_conf
            enriched["subject_fingerprint"] = subject_fingerprint(str(event.get("title") or ""))
            if event_org:
                enriched["organization_id"] = event_org
            elif organization_id != "mixed":
                enriched["organization_id"] = organization_id
            enriched_events.append(enriched)

    by_workstream: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in enriched_events:
        by_workstream[str(event.get("client_workstream_id") or "unclassified")].append(event)

    labels = workstream_labels()
    clusters: list[dict[str, Any]] = []
    for ws_id, items in by_workstream.items():
        clusters.append(
            {
                "organization_id": organization_id,
                "client_workstream_id": ws_id,
                "client_workstream_label": labels.get(ws_id, "Unclassified"),
                "event_count": len(items),
                "events": sorted(items, key=lambda e: str(e.get("timestamp") or ""), reverse=True),
            }
        )
    return sorted(clusters, key=lambda c: (-c["event_count"], c["client_workstream_id"]))


def separation_score(clusters: list[dict[str, Any]], *, expected_workstreams: list[str]) -> float:
    total = 0
    unclassified_count = 0
    for cluster in clusters:
        for event in cluster.get("events") or []:
            text = f"{event.get('title')} {event.get('snippet')}"
            if is_scheduling_noise(text):
                continue
            total += 1
            if cluster.get("client_workstream_id") == "unclassified":
                unclassified_count += 1
    if total == 0:
        return 0.0
    classified = [c for c in clusters if c.get("client_workstream_id") != "unclassified"]
    expected_ids = [ws for ws in expected_workstreams if ws != "unclassified"]
    distinct_expected = len([c for c in classified if c.get("client_workstream_id") in expected_ids])
    if distinct_expected < 2:
        return 0.0
    base = 1.0 - (unclassified_count / total)
    workstream_bonus = min(1.0, distinct_expected / max(len(expected_ids), 1))
    return round(min(1.0, base * 0.6 + workstream_bonus * 0.4), 3)


# Backward compat for spike script
WORKSTREAM_KEYWORDS = _keywords_for_org("org_arp_astrance")
WORKSTREAM_LABELS = workstream_labels()
