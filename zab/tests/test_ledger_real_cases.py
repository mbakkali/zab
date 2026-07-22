"""Real-case regression tests for ARP Astrance, Agile Immo, Carrefour."""

from __future__ import annotations

import pytest

from zab.services.conversation_ledger.clustering import classify_workstream, cluster_events
from zab.services.conversation_ledger.entity_resolver import build_entity_links, resolve_organization
from zab.services.conversation_ledger.org_profiles import ORG_PROFILES


REAL_CASES = [
    {
        "name": "arp_audit_crm_email",
        "subject": "RE: Audit outils et process commerciaux",
        "actor": "Anne-Sophie DELAMARE <asdelamare@arp-astrance.com>",
        "org_id": "org_arp_astrance",
        "workstream_id": "cw_audit_crm",
    },
    {
        "name": "arp_explorateurs_ia",
        "subject": "RE: Challenge IA ARP Astrance : À vos projets !",
        "actor": "contact@arp-astrance.com",
        "org_id": "org_arp_astrance",
        "workstream_id": "cw_explorateurs_ia",
    },
    {
        "name": "arp_securite_deessi",
        "subject": "Re: Point sécurité avec Responsable IA de Deessi",
        "actor": "Nicolas BONHOMME <nbonhomme@arp-astrance.com>",
        "org_id": "org_arp_astrance",
        "workstream_id": "cw_securite_deessi",
    },
    {
        "name": "agile_ipmvp",
        "subject": "Backtest IPMVP — alignement calcul Agile (Mehdi) vs fichier de référence",
        "actor": "stephanie@agileimmo.com",
        "org_id": "org_agile_immo",
        "workstream_id": "cw_maintenance",
    },
    {
        "name": "agile_contractualisation",
        "subject": "Récapitulatif contractuel — Agile Immo x Upfund / Flowmetrik",
        "actor": "mehdi@upfundpro.com",
        "org_id": "org_agile_immo",
        "workstream_id": "cw_maintenance",
    },
    {
        "name": "carrefour_weekly",
        "subject": "[Carrefour] [Weekly] Mehdi / Sélim",
        "actor": "mehdi@upfundpro.com",
        "org_id": "org_carrefour",
        "workstream_id": "cw_ai_team",
    },
    {
        "name": "carrefour_restitution",
        "subject": "[Carrefour] Restitution finale DANM",
        "actor": "mehdi@flowmetrik.com",
        "org_id": "org_carrefour",
        "workstream_id": "cw_delivery",
    },
    {
        "name": "not_agile_from_upfund_calendar",
        "subject": "Bureau",
        "actor": "mehdi@upfundpro.com",
        "org_id": None,
        "workstream_id": "unclassified",
    },
]


@pytest.mark.parametrize("case", REAL_CASES, ids=[c["name"] for c in REAL_CASES])
def test_real_case_org_and_workstream(case: dict) -> None:
    text = f"{case['subject']} {case['actor']}"
    org_id, org_label, org_conf, _ = resolve_organization(text=text, email=case["actor"])
    if case["org_id"] is None:
        assert org_id is None, f"expected no org for {case['name']}, got {org_label}"
    else:
        assert org_id == case["org_id"], f"{case['name']}: org {org_id} != {case['org_id']}"
        assert org_conf >= 0.75
    ws_id, _, ws_conf = classify_workstream(text, organization_id=org_id)
    assert ws_id == case["workstream_id"], f"{case['name']}: ws {ws_id} != {case['workstream_id']}"
    if case["workstream_id"] != "unclassified":
        assert ws_conf >= 0.6


def test_arp_three_workstreams_not_merged() -> None:
    events = []
    for case in REAL_CASES[:3]:
        events.append(
            {
                "event_id": f"gmail:{case['name']}",
                "native_id": case["name"],
                "thread_id": case["name"],
                "title": case["subject"],
                "snippet": case["subject"],
                "actor": {"display_name": case["actor"]},
                "organization_id": case["org_id"],
            }
        )
    clusters = cluster_events(events, organization_id="org_arp_astrance")
    ws_ids = {c["client_workstream_id"] for c in clusters}
    assert {"cw_audit_crm", "cw_explorateurs_ia", "cw_securite_deessi"}.issubset(ws_ids)


def test_build_entity_links_agile_immo() -> None:
    event = {
        "title": "Re: CR - Outil IPMVP",
        "snippet": "contractualisation step 2",
        "actor": {"display_name": "Stephanie <stephanie@agileimmo.com>"},
    }
    links = build_entity_links(event)
    org_links = [l for l in links if l["entity_type"] == "organization"]
    ws_links = [l for l in links if l["entity_type"] == "client_workstream"]
    assert org_links and org_links[0]["entity_id"] == "org_agile_immo"
    assert ws_links and ws_links[0]["entity_id"] == "cw_maintenance"
    assert event.get("organization_id") == "org_agile_immo"


def test_org_profiles_cover_real_clients() -> None:
    assert "org_arp_astrance" in ORG_PROFILES
    assert "org_agile_immo" in ORG_PROFILES
    assert "org_carrefour" in ORG_PROFILES
    assert ORG_PROFILES["org_agile_immo"].get("gmail_query")
