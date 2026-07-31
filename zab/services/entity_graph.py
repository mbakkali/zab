"""Rattache projets et personnes aux organisations du ledger.

Zab tient deux espaces de noms d'organisation qui ne se parlent pas : celui du
ledger (clients, avec domaines e-mail et alias) et celui des projets locaux (nom
du dossier parent, souvent suffixé `-cowork`). Résultat : un WorkPacket connaît
son client mais jamais le dépôt de code correspondant, et les personnes
n'existent que comme texte libre dans les évènements.

Ce module fait la jointure, uniquement sur des règles explicables : alias
déclaré, slug normalisé, ou domaine e-mail. Chaque lien porte sa raison et son
niveau de confiance ; ce qui ne matche pas reste non rattaché plutôt que deviné.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Iterable

# Suffixes d'espace de travail qui ne font pas partie du nom du client.
WORKSPACE_SUFFIXES = ("-cowork", "_cowork", "-workspace", "-knowledge", "-org")

LINK_REASONS = ("alias", "slug", "domain", "label")


def normalize_key(value: Any) -> str:
    """Clé de comparaison : minuscules, sans séparateur ni suffixe d'espace de travail."""
    text = str(value or "").strip().lower()
    for suffix in WORKSPACE_SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    return re.sub(r"[^a-z0-9]", "", text)


def organization_index(organizations: Iterable[dict[str, Any]]) -> dict[str, tuple[str, str]]:
    """clé normalisée -> (organization_id, raison du rattachement).

    Les alias déclarés priment sur le libellé, qui prime sur le domaine : une
    correspondance explicite doit toujours l'emporter sur une correspondance
    dérivée.
    """
    index: dict[str, tuple[str, str]] = {}

    def offer(raw: Any, org_id: str, reason: str) -> None:
        key = normalize_key(raw)
        if not key or len(key) < 3:
            return
        current = index.get(key)
        if current and LINK_REASONS.index(current[1]) <= LINK_REASONS.index(reason):
            return
        index[key] = (org_id, reason)

    for org in organizations:
        org_id = str(org.get("organization_id") or "")
        if not org_id:
            continue
        for alias in org.get("aliases") or []:
            offer(alias, org_id, "alias")
        offer(org.get("label"), org_id, "label")
        for domain in org.get("domains") or []:
            offer(str(domain).split(".")[0], org_id, "domain")
        offer(org_id.removeprefix("org_"), org_id, "slug")
    return index


def link_project(project: dict[str, Any], index: dict[str, tuple[str, str]]) -> dict[str, Any] | None:
    """Rattache un projet local à une organisation, ou rien si aucune règle ne s'applique."""
    candidates: list[tuple[str, str]] = []
    for field in ("org", "workspace_parent"):
        value = project.get(field)
        if value and str(value) != "hors-org":
            candidates.append((str(value), field))
    for alias in project.get("aliases") or []:
        candidates.append((str(alias), "alias"))

    for raw, field in candidates:
        hit = index.get(normalize_key(raw))
        if hit:
            org_id, reason = hit
            return {
                "project_id": project.get("id"),
                "project_name": project.get("name"),
                "path": project.get("path"),
                "organization_id": org_id,
                "matched_on": raw,
                "matched_field": field,
                "reason": reason,
                "confidence": 0.9 if reason == "alias" else 0.75,
            }
    return None


def link_projects(
    projects: Iterable[dict[str, Any]], organizations: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    index = organization_index(organizations)
    linked: list[dict[str, Any]] = []
    unlinked: list[dict[str, Any]] = []
    for project in projects:
        hit = link_project(project, index)
        if hit:
            linked.append(hit)
        else:
            unlinked.append(
                {
                    "project_id": project.get("id"),
                    "project_name": project.get("name"),
                    "org_hint": project.get("org"),
                    "path": project.get("path"),
                }
            )
    by_org: dict[str, list[str]] = defaultdict(list)
    for row in linked:
        by_org[row["organization_id"]].append(str(row["project_id"]))
    return {
        "linked_count": len(linked),
        "unlinked_count": len(unlinked),
        "organizations_covered": len(by_org),
        "links": linked,
        "unlinked": unlinked,
        "projects_by_organization": {k: sorted(v) for k, v in sorted(by_org.items())},
    }


def _email_of(entry: Any) -> str | None:
    if isinstance(entry, dict):
        for field in ("email", "address", "display_name"):
            value = entry.get(field)
            if value and "@" in str(value):
                return _extract_email(str(value))
        return None
    if entry and "@" in str(entry):
        return _extract_email(str(entry))
    return None


def _extract_email(raw: str) -> str | None:
    match = re.search(r"[\w.+-]+@[\w.-]+\.\w+", raw)
    return match.group(0).lower() if match else None


def _display_of(entry: Any) -> str | None:
    if isinstance(entry, dict):
        name = entry.get("display_name") or entry.get("name")
        if name:
            return str(name).split("<")[0].strip().strip('"').strip("'") or None
    elif entry:
        return str(entry).split("<")[0].strip().strip('"').strip("'") or None
    return None


def people_from_events(
    events: Iterable[dict[str, Any]],
    organizations: Iterable[dict[str, Any]],
    *,
    internal_domains: frozenset[str] = frozenset(),
    min_events: int = 2,
) -> dict[str, Any]:
    """Personnes récurrentes, dérivées des évènements, rattachées par domaine e-mail.

    L'identité stable est l'adresse e-mail : deux graphies d'un même nom se
    rejoignent, et rien n'est inventé quand l'adresse manque.
    """
    domain_to_org: dict[str, str] = {}
    for org in organizations:
        for domain in org.get("domains") or []:
            domain_to_org[str(domain).lower()] = str(org.get("organization_id"))

    people: dict[str, dict[str, Any]] = {}
    for event in events:
        entries = [event.get("actor"), *(event.get("counterparties") or [])]
        for entry in entries:
            email = _email_of(entry)
            if not email:
                continue
            domain = email.split("@", 1)[1]
            if domain in internal_domains:
                continue
            person = people.setdefault(
                email,
                {
                    "person_id": f"person_{re.sub(r'[^a-z0-9]', '_', email)}",
                    "email": email,
                    "display_name": None,
                    "domain": domain,
                    "organization_id": domain_to_org.get(domain),
                    "event_count": 0,
                    "inbound_count": 0,
                    "outbound_count": 0,
                    "meeting_count": 0,
                    "first_seen": None,
                    "last_seen": None,
                    "channels": set(),
                    "workstreams": set(),
                },
            )
            person["event_count"] += 1
            direction = str(event.get("direction") or "")
            if direction == "outbound":
                person["outbound_count"] += 1
            elif direction == "meeting":
                person["meeting_count"] += 1
            else:
                person["inbound_count"] += 1
            person["display_name"] = person["display_name"] or _display_of(entry)
            person["channels"].add(str(event.get("source") or "inconnu"))
            if event.get("client_workstream_id"):
                person["workstreams"].add(str(event["client_workstream_id"]))
            timestamp = str(event.get("timestamp") or "")
            if timestamp:
                if not person["first_seen"] or timestamp < person["first_seen"]:
                    person["first_seen"] = timestamp
                if not person["last_seen"] or timestamp > person["last_seen"]:
                    person["last_seen"] = timestamp

    rows = [
        {
            **person,
            "channels": sorted(person["channels"]),
            "workstreams": sorted(person["workstreams"]),
            # Un interlocuteur est quelqu'un à qui on a écrit ou avec qui on s'est réuni.
            # Sans ce critère, le classement par volume remonte les newsletters.
            "is_counterpart": bool(person["outbound_count"] or person["meeting_count"]),
        }
        for person in people.values()
        if person["event_count"] >= min_events
    ]
    rows.sort(key=lambda row: (not row["is_counterpart"], -row["event_count"], row["email"]))
    counterparts = [row for row in rows if row["is_counterpart"]]
    attached = [row for row in counterparts if row["organization_id"]]
    return {
        "people_count": len(rows),
        "counterpart_count": len(counterparts),
        "attached_count": len(attached),
        "unattached_count": len(counterparts) - len(attached),
        "people": rows,
    }


def key_people_for(people: list[dict[str, Any]], *, organization_id: str, limit: int = 3) -> list[str]:
    """Les interlocuteurs les plus présents d'une organisation, e-mail en identité."""
    matching = [
        p for p in people if p.get("organization_id") == organization_id and p.get("is_counterpart")
    ]
    return [str(p["email"]) for p in matching[:limit]]


def suggest_organization_domains(
    people: list[dict[str, Any]], *, min_counterparts: int = 2, limit: int = 15
) -> list[dict[str, Any]]:
    """Domaines d'interlocuteurs récurrents qu'aucune organisation ne revendique.

    Un rattachement manquant n'est presque jamais un défaut d'algorithme : c'est
    un domaine absent des profils. On le remonte, avec de quoi décider, plutôt
    que de deviner l'organisation.
    """
    by_domain: dict[str, dict[str, Any]] = {}
    for person in people:
        if person.get("organization_id") or not person.get("is_counterpart"):
            continue
        row = by_domain.setdefault(
            str(person.get("domain")),
            {"domain": person.get("domain"), "counterparts": 0, "events": 0, "samples": []},
        )
        row["counterparts"] += 1
        row["events"] += int(person.get("event_count") or 0)
        if len(row["samples"]) < 3:
            row["samples"].append(person.get("display_name") or person.get("email"))
    rows = [r for r in by_domain.values() if r["counterparts"] >= min_counterparts]
    rows.sort(key=lambda r: (-r["events"], r["domain"]))
    return rows[:limit]
