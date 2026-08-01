"""Un expéditeur automatique ne crée jamais de relation client."""

from __future__ import annotations

import pytest

from zab.services.conversation_ledger.automated_senders import (
    is_automated_address,
    is_automated_event,
)
from zab.services.conversation_ledger.entity_resolver import build_entity_links


@pytest.mark.parametrize(
    "address",
    [
        "jobalerts-noreply@linkedin.com",
        "noreply@glassdoor.com",
        "calendar-notification@google.com",
        "ne-pas-repondre@banque.fr",
        "newsletter@media.fr",
        "bounces@campagne.io",
    ],
)
def test_automated_addresses_are_recognized(address: str) -> None:
    assert is_automated_address(address) is True


@pytest.mark.parametrize(
    "address",
    [
        "sophie.martin@client.com",
        "contact@client.com",
        "real-estate@client.com",  # « estate » ne doit pas déclencher « alerte »
        "commercial@client.fr",
    ],
)
def test_human_addresses_are_left_alone(address: str) -> None:
    assert is_automated_address(address) is False


def test_a_job_alert_naming_a_client_is_not_attributed_to_it() -> None:
    """Le cas réel : une alerte emploi citant un client le faisait apparaître comme échange."""
    event = {
        "source": "gmail",
        "direction": "inbound",
        "title": "Architect & Interior Designer chez Generali",
        "snippet": "Des offres qui pourraient vous intéresser chez Generali Real Estate",
        "actor": {"display_name": "Emplois Glassdoor", "email": "noreply@glassdoor.com"},
        "counterparties": [],
    }

    links = build_entity_links(event)

    assert links == []
    assert event["automated_sender"] is True
    assert event["organization_id"] is None
    assert event["automated_reason"].startswith("bulk_domain:")


def test_a_calendar_invitation_stays_a_real_meeting() -> None:
    """Un évènement d'agenda porte souvent une adresse technique sans être du bruit."""
    event = {
        "source": "calendar",
        "direction": "meeting",
        "title": "Comité de pilotage",
        "actor": {"email": "calendar-notification@google.com"},
    }

    assert is_automated_event(event) is False


def test_an_existing_wrong_attribution_is_removed_on_reindex() -> None:
    event = {
        "source": "gmail",
        "direction": "inbound",
        "title": "Votre sélection d'offres",
        "actor": {"email": "jobalerts-noreply@linkedin.com"},
        "organization_id": "org_client",
        "organization_label": "Client",
        "client_workstream_id": "cw_x",
    }

    build_entity_links(event)

    assert event["organization_id"] is None
    assert event["client_workstream_id"] is None
