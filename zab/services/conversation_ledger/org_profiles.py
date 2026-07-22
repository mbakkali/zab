"""Organization profiles: Gmail queries, subject hints, workstream keywords."""

from __future__ import annotations

from typing import Any

# Comptes Mehdi — ne pas inférer un client depuis le domaine seul.
INTERNAL_DOMAINS = frozenset({"flowmetrik.com", "upfundpro.com", "gmail.com"})

ORG_PROFILES: dict[str, dict[str, Any]] = {
    "org_arp_astrance": {
        "organization_id": "org_arp_astrance",
        "label": "ARP Astrance",
        "domains": ["arp-astrance.com"],
        "subject_hints": ("arp astrance", "arp-astrance", "arp astrance"),
        "gmail_query": "from:arp-astrance.com OR to:arp-astrance.com OR \"ARP Astrance\"",
        "workstreams": {
            "cw_audit_crm": {
                "label": "Audit CRM",
                "keywords": (
                    "audit",
                    "suivi commercial",
                    "crm",
                    "commercial",
                    "process commerciaux",
                    "outils commerciaux",
                    "questions pour toi",
                ),
            },
            "cw_explorateurs_ia": {
                "label": "Explorateurs IA",
                "keywords": (
                    "explorateur",
                    "explorateurs",
                    "formation ia",
                    "intelligence artificielle",
                    "digital twin",
                    "challenge ia",
                    "point ia",
                    "codir ia",
                ),
            },
            "cw_securite_deessi": {
                "label": "Sécurité Deessi",
                "keywords": ("deessi", "sécurité", "securite", "security", "accès", "acces", "sso", "azure ad"),
            },
        },
    },
    "org_agile_immo": {
        "organization_id": "org_agile_immo",
        "label": "Agile Immo",
        "domains": ["agileimmo.com"],
        "subject_hints": (
            "agile immo",
            "agileimmo",
            "ipmvp",
            "agile compliance",
            "contractualisation",
            "kpi variable",
            "step 2",
        ),
        "gmail_query": "\"Agile Immo\" OR agileimmo OR ipmvp OR contractualisation OR \"Agile Compliance\" OR \"CR - Outil IPMVP\"",
        "workstreams": {
            "cw_maintenance": {
                "label": "Step 2 / IPMVP maintenance",
                "keywords": (
                    "step 2",
                    "maintenance",
                    "ipmvp",
                    "contractualisation",
                    "agile compliance",
                    "kpi variable",
                    "backtest ipmvp",
                    "outil ipmvp",
                    "regulation",
                    "devops",
                    "récapitulatif contractuel",
                    "recapitulatif contractuel",
                ),
            },
            "cw_agile_delivery": {
                "label": "Delivery Agile Immo",
                "keywords": ("déploiement agile", "deploiement agile", "agile immo x upfund"),
            },
        },
    },
    "org_carrefour": {
        "organization_id": "org_carrefour",
        "label": "Carrefour",
        "domains": ["carrefour.com"],
        "subject_hints": ("[carrefour]", "carrefour", "danm"),
        "gmail_query": "[Carrefour] OR from:carrefour.com OR to:carrefour.com",
        "workstreams": {
            "cw_delivery": {
                "label": "Delivery / restitution",
                "keywords": ("restitution", "delivery", "danm", "roadmap", "off site", "g7"),
            },
            "cw_ai_team": {
                "label": "AI team / weekly",
                "keywords": ("[ai]", "team meeting", "weekly", "déblocage", "deblocage"),
            },
        },
    },
}


def profile_for_org(org_id: str) -> dict[str, Any] | None:
    return ORG_PROFILES.get(org_id)


def gmail_query_for_org(org_id: str) -> str | None:
    profile = profile_for_org(org_id)
    if not profile:
        return None
    return str(profile.get("gmail_query") or "") or None


def workstream_keywords(org_id: str | None = None) -> dict[str, dict[str, Any]]:
    if org_id and org_id in ORG_PROFILES:
        return dict(ORG_PROFILES[org_id].get("workstreams") or {})
    merged: dict[str, dict[str, Any]] = {}
    for profile in ORG_PROFILES.values():
        for ws_id, ws in (profile.get("workstreams") or {}).items():
            merged[ws_id] = {**ws, "organization_id": profile["organization_id"]}
    return merged
