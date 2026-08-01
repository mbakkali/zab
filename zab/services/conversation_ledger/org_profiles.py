"""Organization profiles: Gmail queries, subject hints, workstream keywords."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from zab.paths import config_dir

# Comptes Mehdi — ne pas inférer un client depuis le domaine seul.
_BUILTIN_INTERNAL_DOMAINS = frozenset({"flowmetrik.com", "upfundpro.com", "gmail.com"})

_BUILTIN_ORG_PROFILES: dict[str, dict[str, Any]] = {
    "org_arp_astrance": {
        "organization_id": "org_arp_astrance",
        "label": "ARP Astrance",
        "domains": ["arp-astrance.com"],
        "subject_hints": ("arp astrance", "arp-astrance", "arp astrance"),
        "gmail_query": 'from:arp-astrance.com OR to:arp-astrance.com OR "ARP Astrance"',
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
                "keywords": (
                    "deessi",
                    "sécurité",
                    "securite",
                    "security",
                    "accès",
                    "acces",
                    "sso",
                    "azure ad",
                ),
            },
        },
    },
    "org_agile_immo": {
        "organization_id": "org_agile_immo",
        "label": "Agile Immo",
        "domains": ["agileimmo.com", "agile.immo", "agileimmo.dev"],
        "subject_hints": (
            "agile immo",
            "agileimmo",
            "ipmvp",
            "agile compliance",
            "contractualisation",
            "kpi variable",
            "step 2",
        ),
        "gmail_query": '"Agile Immo" OR agileimmo OR ipmvp OR contractualisation OR "Agile Compliance" OR "CR - Outil IPMVP"',
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
                "keywords": (
                    "déploiement agile",
                    "deploiement agile",
                    "agile immo x upfund",
                ),
            },
        },
    },
    "org_ofi_invest": {
        "organization_id": "org_ofi_invest",
        "label": "OFI Invest",
        "domains": ["ofi-invest.com"],
        "subject_hints": ("ofi invest", "ofi-invest"),
        "gmail_query": 'from:ofi-invest.com OR to:ofi-invest.com OR "OFI Invest"',
        "workstreams": {
            "cw_ofi_invest": {
                "label": "OFI Invest",
                "keywords": (
                    "ofi invest",
                    "ofi-invest",
                    "formation ia",
                    "agent ia",
                    "audit ia",
                    "point ia",
                ),
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
                "keywords": (
                    "restitution",
                    "delivery",
                    "danm",
                    "roadmap",
                    "off site",
                    "g7",
                ),
            },
            "cw_ai_team": {
                "label": "AI team / weekly",
                "keywords": (
                    "[ai]",
                    "team meeting",
                    "weekly",
                    "déblocage",
                    "deblocage",
                ),
            },
        },
    },
}


def local_entity_profiles_path() -> Path:
    override = os.environ.get("ZAB_ENTITY_PROFILES_PATH", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (config_dir() / "conversation-ledger-entities.yaml").resolve()


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = [str(item) for item in value if str(item).strip()]
    else:
        values = []
    return list(dict.fromkeys(item.strip().lower() for item in values if item.strip()))


def _local_profile_document(path: Path | None = None) -> dict[str, Any]:
    resolved = path or local_entity_profiles_path()
    if not resolved.is_file():
        return {}
    try:
        payload = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _iter_local_profiles(document: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    raw = document.get("organizations") or {}
    items: list[tuple[str, dict[str, Any]]] = []
    if isinstance(raw, dict):
        for org_id, profile in raw.items():
            if isinstance(profile, dict):
                items.append((str(org_id), profile))
    elif isinstance(raw, list):
        for profile in raw:
            if not isinstance(profile, dict):
                continue
            org_id = str(profile.get("organization_id") or "").strip()
            if org_id:
                items.append((org_id, profile))
    return items


def _merge_profiles(
    builtin: dict[str, dict[str, Any]],
    document: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    merged = {org_id: dict(profile) for org_id, profile in builtin.items()}
    for org_id, local in _iter_local_profiles(document):
        current = dict(merged.get(org_id) or {})
        label = str(local.get("label") or current.get("label") or org_id).strip()
        profile: dict[str, Any] = {
            **current,
            **local,
            "organization_id": org_id,
            "label": label,
        }
        for field in ("domains", "subject_hints", "aliases"):
            profile[field] = _string_list(
                [*_string_list(current.get(field)), *_string_list(local.get(field))]
            )
        workstreams = {
            str(ws_id): dict(ws)
            for ws_id, ws in (current.get("workstreams") or {}).items()
            if isinstance(ws, dict)
        }
        for ws_id, ws in (local.get("workstreams") or {}).items():
            if not isinstance(ws, dict):
                continue
            ws_key = str(ws_id)
            previous = workstreams.get(ws_key) or {}
            workstreams[ws_key] = {
                **previous,
                **ws,
                "keywords": _string_list(
                    [
                        *_string_list(previous.get("keywords")),
                        *_string_list(ws.get("keywords")),
                    ]
                ),
            }
        profile["workstreams"] = workstreams
        merged[org_id] = profile
    return merged


_LOCAL_DOCUMENT = _local_profile_document()
INTERNAL_DOMAINS = frozenset(
    {
        *_BUILTIN_INTERNAL_DOMAINS,
        *_string_list(_LOCAL_DOCUMENT.get("internal_domains") or []),
    }
)


def _internal_org_domains(document: dict[str, Any]) -> dict[str, str]:
    """domaine -> organisation interne, pour les profils marqués `internal: true`.

    Le travail qui n'est pas pour un client est du travail quand même. Sans
    organisation interne, il n'a nulle part où aller et disparaît du système.
    """
    mapping: dict[str, str] = {}
    organizations = document.get("organizations")
    if not isinstance(organizations, dict):
        return mapping
    for org_id, profile in organizations.items():
        if not isinstance(profile, dict) or not profile.get("internal"):
            continue
        for domain in _string_list(profile.get("domains") or []):
            mapping[domain.lower()] = str(org_id)
    return mapping


INTERNAL_ORG_DOMAINS: dict[str, str] = _internal_org_domains(_LOCAL_DOCUMENT)
INTERNAL_ORG_IDS: frozenset[str] = frozenset(INTERNAL_ORG_DOMAINS.values())
ORG_PROFILES: dict[str, dict[str, Any]] = _merge_profiles(
    _BUILTIN_ORG_PROFILES, _LOCAL_DOCUMENT
)


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
