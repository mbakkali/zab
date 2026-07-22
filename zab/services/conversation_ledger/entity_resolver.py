"""Entity resolution: organization, client_workstream, zab_project."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from zab.services.conversation_ledger.org_profiles import INTERNAL_DOMAINS, ORG_PROFILES

DEFAULT_ORGANIZATIONS: dict[str, dict[str, Any]] = {
    org_id: {
        "organization_id": org_id,
        "label": profile["label"],
        "domains": list(profile.get("domains") or []),
        "aliases": list(profile.get("subject_hints") or [])[:4],
    }
    for org_id, profile in ORG_PROFILES.items()
}
DEFAULT_ORGANIZATIONS.update(
    {
        "org_sogeprom": {
            "organization_id": "org_sogeprom",
            "label": "Sogeprom",
            "domains": ["sogeprom.com"],
            "aliases": ["sogeprom"],
        },
        "org_tikehau": {
            "organization_id": "org_tikehau",
            "label": "Tikehau / Sofidy",
            "domains": ["tikehau.com", "sofidy.com"],
            "aliases": ["tikehau", "sofidy"],
        },
        "org_bnp_expertise": {
            "organization_id": "org_bnp_expertise",
            "label": "BNP Expertise",
            "domains": ["bnpparibas.com", "bnpexpertise.fr"],
            "aliases": ["bnp expertise", "bnp"],
        },
        "org_mastora": {
            "organization_id": "org_mastora",
            "label": "Mastora",
            "domains": [],
            "aliases": ["mastora"],
        },
        "org_arthur_loyd": {
            "organization_id": "org_arthur_loyd",
            "label": "Arthur Loyd",
            "domains": ["arthur-loyd.com"],
            "aliases": ["arthur loyd", "propuls'immo", "propuls immo"],
        },
    }
)

WORKSTREAM_SEEDS: dict[str, dict[str, Any]] = {}
for _org_id, _profile in ORG_PROFILES.items():
    for ws_id, ws in (_profile.get("workstreams") or {}).items():
        WORKSTREAM_SEEDS[ws_id] = {
            "client_workstream_id": ws_id,
            "label": ws["label"],
            "organization_id": _org_id,
            "keywords": list(ws.get("keywords") or ()),
        }
WORKSTREAM_SEEDS.update(
    {
        "cw_agent_ia": {
            "client_workstream_id": "cw_agent_ia",
            "label": "Agent IA foncier",
            "organization_id": "org_sogeprom",
            "keywords": ["agent ia", "copilot studio", "foncier"],
        },
        "cw_relance": {
            "client_workstream_id": "cw_relance",
            "label": "Relance proposition",
            "organization_id": "org_tikehau",
            "keywords": ["relance", "proposition", "tikehau", "sofidy"],
        },
        "cw_demo": {
            "client_workstream_id": "cw_demo",
            "label": "Demo agent IA",
            "organization_id": "org_bnp_expertise",
            "keywords": ["demo", "démonstration", "agent ia"],
        },
        "cw_formation": {
            "client_workstream_id": "cw_formation",
            "label": "Formations",
            "organization_id": "org_mastora",
            "keywords": ["formation", "mastora"],
        },
        "cw_formation_facturation": {
            "client_workstream_id": "cw_formation_facturation",
            "label": "Formation et facturation",
            "organization_id": "org_arthur_loyd",
            "keywords": ["formation", "facturation", "arthur loyd", "propuls"],
        },
    }
)


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _extract_email(value: str) -> str | None:
    match = re.search(r"[\w.+-]+@([\w.-]+)", value)
    if not match:
        return None
    return match.group(1).lower()


def resolve_organization(*, text: str = "", email: str | None = None) -> tuple[str | None, str | None, float, list[str]]:
    domain = _extract_email(email or text)
    normalized = _normalize(text)
    evidence: list[str] = []

    # 1) Strong subject hints (priorité sur domaines internes)
    for org_id, profile in ORG_PROFILES.items():
        for hint in profile.get("subject_hints") or ():
            if hint in normalized:
                evidence.append(f"subject hint {hint}")
                return org_id, profile["label"], 0.88, evidence

    # 2) Domaine client explicite (hors comptes internes Mehdi)
    if domain and domain not in INTERNAL_DOMAINS:
        for org_id, org in DEFAULT_ORGANIZATIONS.items():
            for d in org.get("domains") or []:
                if domain.endswith(d):
                    evidence.append(f"email domain {d}")
                    return org_id, org["label"], 0.9, evidence

    # 3) Aliases génériques
    for org_id, org in DEFAULT_ORGANIZATIONS.items():
        for alias in org.get("aliases") or []:
            if len(alias) >= 4 and alias in normalized:
                evidence.append(f"alias {alias}")
                return org_id, org["label"], 0.75, evidence
    return None, None, 0.0, evidence


def resolve_workstream(*, text: str, organization_id: str | None) -> tuple[str | None, str | None, float, list[str]]:
    from zab.services.conversation_ledger.clustering import classify_workstream

    ws_id, ws_label, confidence = classify_workstream(text, organization_id=organization_id)
    if ws_id == "unclassified":
        return None, None, 0.0, []
    seed = WORKSTREAM_SEEDS.get(ws_id)
    if seed and organization_id and seed.get("organization_id") != organization_id:
        return None, None, 0.0, ["workstream org mismatch"]
    evidence = [f"keyword match -> {ws_label}"]
    return ws_id, ws_label, confidence, evidence


def resolve_zab_project(*, text: str) -> tuple[str | None, float, list[str]]:
    normalized = _normalize(text)
    projects = {
        "flowmetrik-cowork": ("flowmetrik", "cowork"),
        "zab": ("zab",),
        "agile-taskforce": ("agile", "taskforce"),
    }
    for project_id, terms in projects.items():
        if all(term in normalized for term in terms):
            return project_id, 0.7, [f"project keyword {project_id}"]
    return None, 0.0, []


def build_entity_links(event: dict[str, Any]) -> list[dict[str, Any]]:
    text = " ".join(
        [
            str(event.get("title") or ""),
            str(event.get("snippet") or ""),
            str((event.get("actor") or {}).get("display_name") or ""),
            str((event.get("actor") or {}).get("email") or ""),
        ]
    )
    email = (event.get("actor") or {}).get("email")
    org_id, org_label, org_conf, org_evidence = resolve_organization(text=text, email=email)
    links: list[dict[str, Any]] = []
    if org_id:
        links.append(
            {
                "entity_type": "organization",
                "entity_id": org_id,
                "label": org_label,
                "confidence": org_conf,
                "evidence": org_evidence,
                "status": "confirmed" if org_conf >= 0.85 else "candidate",
            }
        )
        event["organization_id"] = org_id
        event["organization_label"] = org_label
    ws_id, ws_label, ws_conf, ws_evidence = resolve_workstream(text=text, organization_id=org_id)
    if ws_id:
        links.append(
            {
                "entity_type": "client_workstream",
                "entity_id": ws_id,
                "label": ws_label,
                "confidence": ws_conf,
                "evidence": ws_evidence,
                "status": "confirmed" if ws_conf >= 0.8 else "candidate",
            }
        )
        event["client_workstream_id"] = ws_id
        event["client_workstream_label"] = ws_label
    project_id, project_conf, project_evidence = resolve_zab_project(text=text)
    if project_id:
        links.append(
            {
                "entity_type": "zab_project",
                "entity_id": project_id,
                "label": project_id,
                "confidence": project_conf,
                "evidence": project_evidence,
                "status": "candidate",
            }
        )
    return links


def clients_dir_hint(clients_root: Path | None = None) -> list[str]:
    root = clients_root or Path.home() / "projects" / "clients"
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())
