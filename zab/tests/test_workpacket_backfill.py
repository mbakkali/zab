"""Backfill des WorkPackets : les faits dérivés doivent rester traçables aux évènements."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from zab.services.conversation_ledger.workpacket_backfill import (
    collect_facts,
    derive_actions,
    derive_state,
    derive_title,
    rebuild_packet,
)

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)


def _event(**kwargs):
    base = {
        "event_id": "gmail:1",
        "timestamp": (NOW - timedelta(days=1)).isoformat(),
        "direction": "inbound",
        "source": "gmail",
        "title": "Sujet",
        "actor": {"display_name": "Alice Martin <alice@client.com>"},
    }
    base.update(kwargs)
    return base


def test_inbound_last_means_we_owe_a_reply() -> None:
    facts = collect_facts([_event(title="Devis à valider")], now=NOW)

    assert facts["awaiting_reply_from_us"] is True
    assert facts["counterparty"] == "Alice"
    assert facts["days_since_last_event"] == 1
    assert "répondre à Alice" in derive_title(
        facts, organization_label="Client", workstream_label="Devis"
    )
    assert "Répondre à Alice" in derive_actions(facts, organization_label="Client")[0]


def test_outbound_last_waits_instead_of_chasing() -> None:
    events = [
        _event(direction="outbound", actor={"display_name": "moi@exemple.com"}, timestamp=(NOW - timedelta(days=2)).isoformat()),
    ]
    facts = collect_facts(events, now=NOW)

    assert facts["awaiting_reply_from_us"] is False
    action = derive_actions(facts, organization_label="Client")[0]
    assert action.startswith("Attendre la réponse")
    # La date de relance est calculée, pas suggérée vaguement.
    assert "2026-08-05" in action  # 29 juillet + 7 jours de silence toléré


def test_long_silence_switches_to_follow_up() -> None:
    events = [
        _event(direction="outbound", actor={"display_name": "moi@exemple.com"}, timestamp=(NOW - timedelta(days=20)).isoformat()),
    ]
    facts = collect_facts(events, now=NOW)

    assert "relancer après 20 j" in derive_title(
        facts, organization_label="Client", workstream_label="Devis"
    )
    assert derive_actions(facts, organization_label="Client")[0].startswith("Relancer Client")


def test_user_own_message_is_never_a_counterparty() -> None:
    """Un fil où l'utilisateur apparaît en entrant ne doit pas produire « répondre à soi-même »."""
    me = {"display_name": "Mehdi B <moi@exemple.com>"}
    events = [
        _event(direction="outbound", actor=me, timestamp=(NOW - timedelta(days=3)).isoformat()),
        _event(direction="inbound", actor=me, timestamp=(NOW - timedelta(days=1)).isoformat()),
    ]
    facts = collect_facts(events, now=NOW)

    assert facts["counterparty"] is None
    assert facts["awaiting_reply_from_us"] is False


def test_future_message_is_treated_as_the_latest_activity() -> None:
    """Un e-mail horodaté en avance (fuseau) reste le dernier échange, pas une échéance."""
    events = [
        _event(title="Ancien", timestamp=(NOW - timedelta(days=2)).isoformat()),
        _event(
            title="Tout récent",
            timestamp=(NOW + timedelta(hours=2)).isoformat(),
            actor={"display_name": "Bob <bob@client.com>"},
        ),
    ]
    facts = collect_facts(events, now=NOW)

    assert facts["last_subject"] == "Tout récent"
    assert facts["counterparty"] == "Bob"
    assert facts["days_since_last_event"] == 0
    assert facts["next_event_at"] is None  # un message n'est pas une réunion à préparer


def test_only_calendar_events_become_deadlines() -> None:
    events = [
        _event(timestamp=(NOW - timedelta(days=1)).isoformat()),
        _event(
            event_id="calendar:1",
            source="calendar",
            direction="meeting",
            title="Comité de pilotage",
            timestamp=(NOW + timedelta(days=2)).isoformat(),
        ),
    ]
    facts = collect_facts(events, now=NOW)

    assert facts["next_event_title"] == "Comité de pilotage"
    assert facts["next_event_in_days"] == 2
    assert derive_state(facts) == "active"
    assert derive_actions(facts, organization_label="Client")[0].startswith("Préparer")


def test_past_meeting_asks_for_a_follow_up_not_a_reply() -> None:
    events = [
        _event(
            event_id="calendar:1",
            source="calendar",
            direction="meeting",
            title="Point hebdo",
            timestamp=(NOW - timedelta(days=1)).isoformat(),
        )
    ]
    facts = collect_facts(events, now=NOW)

    assert facts["last_is_message"] is False
    assert derive_actions(facts, organization_label="Client")[0].startswith("Donner suite")


def test_state_follows_activity_windows() -> None:
    def facts_after(days: int) -> dict:
        return collect_facts([_event(timestamp=(NOW - timedelta(days=days)).isoformat())], now=NOW)

    assert derive_state(facts_after(3)) == "active"
    assert derive_state(facts_after(30)) == "candidate"
    assert derive_state(facts_after(120)) == "archived"
    assert derive_state(collect_facts([], now=NOW)) == "candidate"


def test_subject_from_a_chat_body_is_collapsed_and_truncated() -> None:
    events = [_event(source="whatsapp", title="Bien merci !\n\nTop , " + "x" * 120)]
    facts = collect_facts(events, now=NOW)

    assert "\n" not in facts["last_subject"]
    assert len(facts["last_subject"]) <= 68
    assert facts["last_subject"].endswith("…")


def test_rebuild_is_idempotent_and_reports_changes() -> None:
    packet = {
        "workpacket_id": "wp_1",
        "title": "Client - Devis",
        "state": "candidate",
        "actions": ["Create or locate the parent Work Packet using the idempotency key."],
        "organization_label": "Client",
        "client_workstream_label": "Devis",
    }
    events = [_event(title="Devis à valider")]

    updated, changes = rebuild_packet(packet, events, now=NOW)
    assert set(changes) == {"title", "state", "actions"}
    assert updated["state"] == "active"
    assert updated["metadata"]["ledger_facts"]["counterparty"] == "Alice"

    again, changes_again = rebuild_packet(updated, events, now=NOW)
    assert changes_again == {}
    assert again["title"] == updated["title"]
