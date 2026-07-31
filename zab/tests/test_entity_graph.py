"""Graphe d'entités : un rattachement doit être explicable, jamais deviné."""

from __future__ import annotations

from zab.services.entity_graph import (
    key_people_for,
    link_project,
    link_projects,
    normalize_key,
    organization_index,
    people_from_events,
    suggest_organization_domains,
)

ORGS = [
    {
        "organization_id": "org_acme",
        "label": "Acme Group",
        "domains": ["acme.com", "acme-labs.fr"],
        "aliases": ["acme", "acm"],
    },
    {
        "organization_id": "org_globex",
        "label": "Globex",
        "domains": ["globex.io"],
        "aliases": [],
    },
]


def test_workspace_suffix_is_not_part_of_the_client_name() -> None:
    assert normalize_key("acme-cowork") == "acme"
    assert normalize_key("Acme Group") == "acmegroup"
    assert normalize_key("arp-knowledge") == "arp"


def test_explicit_alias_beats_a_derived_match() -> None:
    index = organization_index(ORGS)
    assert index["acme"] == ("org_acme", "alias")
    # Le libellé et le domaine restent des portes d'entrée, avec leur raison.
    assert index["globex"][0] == "org_globex"


def test_project_links_through_its_workspace_folder() -> None:
    index = organization_index(ORGS)
    link = link_project({"id": "acme-cowork/api", "org": "acme-cowork", "name": "api"}, index)

    assert link is not None
    assert link["organization_id"] == "org_acme"
    assert link["reason"] == "alias"
    assert link["matched_on"] == "acme-cowork"


def test_unmatched_project_stays_unlinked_rather_than_guessed() -> None:
    result = link_projects([{"id": "misc/tool", "org": "hors-org", "name": "tool"}], ORGS)

    assert result["linked_count"] == 0
    assert result["unlinked"][0]["project_id"] == "misc/tool"


def _event(email: str, *, direction: str = "inbound", source: str = "gmail", ts: str = "2026-07-01T10:00:00+00:00"):
    return {
        "actor": {"display_name": f"Someone <{email}>"},
        "direction": direction,
        "source": source,
        "timestamp": ts,
    }


def test_a_newsletter_is_not_a_counterpart() -> None:
    events = [_event("news@letter.com") for _ in range(20)]
    events += [
        _event("bob@acme.com"),
        _event("bob@acme.com", direction="outbound"),
    ]

    people = people_from_events(events, ORGS)
    by_email = {p["email"]: p for p in people["people"]}

    assert by_email["news@letter.com"]["is_counterpart"] is False
    assert by_email["bob@acme.com"]["is_counterpart"] is True
    assert people["counterpart_count"] == 1
    # L'interlocuteur réel passe devant, malgré un volume dix fois moindre.
    assert people["people"][0]["email"] == "bob@acme.com"


def test_people_attach_to_an_organization_by_email_domain() -> None:
    events = [
        _event("bob@acme.com"),
        _event("bob@acme.com", direction="outbound"),
        _event("zoe@unknown.tld"),
        _event("zoe@unknown.tld", direction="meeting"),
    ]
    people = people_from_events(events, ORGS)
    by_email = {p["email"]: p for p in people["people"]}

    assert by_email["bob@acme.com"]["organization_id"] == "org_acme"
    assert by_email["zoe@unknown.tld"]["organization_id"] is None
    assert key_people_for(people["people"], organization_id="org_acme") == ["bob@acme.com"]


def test_internal_domains_never_appear_as_counterparts() -> None:
    events = [
        _event("moi@interne.com", direction="outbound"),
        _event("moi@interne.com"),
    ]
    people = people_from_events(events, ORGS, internal_domains=frozenset({"interne.com"}))

    assert people["people"] == []


def test_unattached_counterparts_become_domain_suggestions() -> None:
    events = []
    for name in ("a", "b"):
        events.append(_event(f"{name}@newclient.fr"))
        events.append(_event(f"{name}@newclient.fr", direction="outbound"))
    people = people_from_events(events, ORGS)

    suggestions = suggest_organization_domains(people["people"])
    assert suggestions[0]["domain"] == "newclient.fr"
    assert suggestions[0]["counterparts"] == 2
