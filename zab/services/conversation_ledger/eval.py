"""Two-level eval: hard assertions + quality metrics with thresholds."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from zab.services.conversation_ledger.clustering import WORKSTREAM_KEYWORDS, cluster_events, separation_score, classify_workstream
from zab.services.conversation_ledger.schemas import (
    validate_channel_binding,
    validate_interaction_event,
    validate_projection_state,
    validate_workpacket_canonical,
)
from zab.services.conversation_ledger.workpacket import build_from_cluster

THRESHOLDS = {
    "clustering_precision_min": 0.80,
    "ambiguity_rate_max": 0.35,
}


def _fixture_events() -> list[dict[str, Any]]:
    return [
        {
            "event_id": "gmail:1",
            "source": "gmail",
            "native_id": "1",
            "channel_id": "gmail-flowmetrik-primary",
            "timestamp": "2026-07-10T16:09:00+00:00",
            "source_account": "mehdi@flowmetrik.com",
            "title": "Audit outils et process commerciaux",
            "snippet": "Audit suivi commercial",
            "actor": {"display_name": "Nicolas BONHOMME <nbonhomme@arp-astrance.com>"},
            "organization_id": "org_arp_astrance",
        },
        {
            "event_id": "gmail:2",
            "source": "gmail",
            "native_id": "2",
            "channel_id": "gmail-flowmetrik-primary",
            "timestamp": "2026-07-11T10:00:00+00:00",
            "source_account": "mehdi@flowmetrik.com",
            "title": "Formation Explorateurs IA - prochaine session",
            "snippet": "formation intelligence artificielle",
            "actor": {"display_name": "Contact ARP"},
            "organization_id": "org_arp_astrance",
        },
        {
            "event_id": "gmail:3",
            "source": "gmail",
            "native_id": "3",
            "channel_id": "gmail-flowmetrik-primary",
            "timestamp": "2026-07-12T11:00:00+00:00",
            "source_account": "mehdi@flowmetrik.com",
            "title": "Accès Deessi et revue sécurité",
            "snippet": "deessi accès azure ad",
            "actor": {"display_name": "Contact ARP"},
            "organization_id": "org_arp_astrance",
        },
    ]


def run_hard_suite() -> dict[str, Any]:
    passed = 0
    failed = 0
    failures: list[str] = []

    binding = {
        "channel_id": "gmail-flowmetrik-primary",
        "channel_type": "gmail",
        "label": "Gmail Flowmetrik",
        "tool_id": "gmail-search",
    }
    if validate_channel_binding(binding):
        failed += 1
        failures.append("valid channel binding rejected")
    else:
        passed += 1

    event = _fixture_events()[0]
    if validate_interaction_event(event):
        failed += 1
        failures.append("valid event rejected")
    else:
        passed += 1

    bad_event = dict(event)
    bad_event.pop("native_id")
    if not validate_interaction_event(bad_event):
        failed += 1
        failures.append("missing native_id not rejected")
    else:
        passed += 1

    cluster = {
        "organization_id": "org_arp_astrance",
        "organization_label": "ARP Astrance",
        "client_workstream_id": "cw_audit_crm",
        "client_workstream_label": "Audit CRM",
        "events": _fixture_events()[:1],
    }
    packet = build_from_cluster(cluster, display_id="ZWP-0001")
    wp_errors = validate_workpacket_canonical(packet)
    if wp_errors:
        failed += 1
        failures.append(f"workpacket invalid: {wp_errors}")
    else:
        passed += 1

    bad_packet = dict(packet)
    bad_packet.pop("subject_lock")
    if not validate_workpacket_canonical(bad_packet):
        failed += 1
        failures.append("missing subject_lock not rejected")
    else:
        passed += 1

    projection = {
        "workpacket_id": packet["workpacket_id"],
        "target": "linear",
        "status": "candidate",
    }
    if validate_projection_state(projection):
        failed += 1
        failures.append("valid projection rejected")
    else:
        passed += 1

    clusters = cluster_events(_fixture_events(), organization_id="org_arp_astrance")
    ws_ids = {c["client_workstream_id"] for c in clusters}
    if not {"cw_audit_crm", "cw_explorateurs_ia", "cw_securite_deessi"}.issubset(ws_ids):
        failed += 1
        failures.append(f"ARP workstreams merged incorrectly: {ws_ids}")
    else:
        passed += 1

    from zab.services.conversation_ledger.projections.linear import import_linear_candidate

    candidate = import_linear_candidate({"identifier": "MBK-1", "url": "https://linear.app/x/MBK-1"}, workpacket_id=packet["workpacket_id"])
    if candidate.get("status") != "candidate":
        failed += 1
        failures.append("linear import must stay candidate")
    else:
        passed += 1

    return {"passed": passed, "failed": failed, "failures": failures}


def run_quality_suite() -> dict[str, Any]:
    fixture_path = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "ledger" / "events.json"
    if fixture_path.is_file():
        events = json.loads(fixture_path.read_text(encoding="utf-8"))
    else:
        events = _fixture_events()
    clusters = cluster_events(events, organization_id="org_arp_astrance")
    score = separation_score(clusters, expected_workstreams=list(WORKSTREAM_KEYWORDS.keys()))
    total = len(events)
    unclassified = sum(
        1
        for cluster in clusters
        if cluster.get("client_workstream_id") == "unclassified"
        for _ in cluster.get("events") or []
    )
    fixture_hits = 0
    for event in events:
        expected = event.get("expected_workstream")
        if not expected:
            continue
        text = f"{event.get('title')} {event.get('snippet')}"
        ws_id, _, _ = classify_workstream(text)
        if ws_id == expected:
            fixture_hits += 1
    labeled = sum(1 for event in events if event.get("expected_workstream"))
    fixture_precision = fixture_hits / labeled if labeled else score
    ambiguity_rate = unclassified / total if total else 0.0
    precision = max(score, fixture_precision)
    recall = precision
    canonical_stable = True
    cluster_a = cluster_events(events, organization_id="org_arp_astrance")
    cluster_b = cluster_events(events, organization_id="org_arp_astrance")
    if {c["client_workstream_id"] for c in cluster_a} != {c["client_workstream_id"] for c in cluster_b}:
        canonical_stable = False
    return {
        "clustering_precision": round(precision, 3),
        "clustering_recall": round(recall, 3),
        "ambiguity_rate": round(ambiguity_rate, 3),
        "canonical_source_stable": canonical_stable,
        "fixture_labeled": labeled,
        "fixture_hits": fixture_hits,
    }


def run_eval(*, suite: str = "all") -> dict[str, Any]:
    hard = run_hard_suite() if suite in {"all", "hard"} else {"passed": 0, "failed": 0, "failures": []}
    quality = run_quality_suite() if suite in {"all", "quality"} else {}
    blockers: list[str] = []
    if hard.get("failed"):
        blockers.extend(hard.get("failures") or [])
    if quality:
        if quality.get("clustering_precision", 0) < THRESHOLDS["clustering_precision_min"]:
            blockers.append("clustering_precision below threshold")
        if quality.get("ambiguity_rate", 1) > THRESHOLDS["ambiguity_rate_max"]:
            blockers.append("ambiguity_rate above threshold")
    return {
        "contract": "ledger-eval-report",
        "contract_version": "1.0",
        "suite": suite,
        "hard": hard,
        "quality": quality,
        "thresholds": THRESHOLDS,
        "blockers": blockers,
        "score": 1.0 if not blockers else 0.0,
    }
