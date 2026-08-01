"""Un WorkPacket naît d'une intention humaine, jamais d'une exécution machine."""

from __future__ import annotations

import pytest

from zab.services.conversation_ledger.intent_signals import (
    AUTOMATED,
    BOILERPLATE,
    EMPTY,
    HUMAN,
    classify_intent,
    intent_key,
    intent_title,
    is_human_intent,
)


@pytest.mark.parametrize(
    "text",
    [
        "Run id: 20260801T111826Z Current UTC time: 2026-08-01T11:18:26Z # Hourly archive",
        '<scheduled-task name="ui-quality-autopilot" file="/tmp/x.md">',
        "# Nightly maintenance run",
        "<<autonomous-loop-dynamic>>",
    ],
)
def test_machine_runs_are_not_tasks(text: str) -> None:
    assert classify_intent(text) == AUTOMATED
    assert is_human_intent(text) is False


@pytest.mark.parametrize(
    "text",
    [
        "Here is a list of plugins that are available but not installed. - Airtable",
        "<system-reminder>As you answer the user's questions…",
        "Caveat: The messages below were generated while running a command",
    ],
)
def test_tool_boilerplate_is_not_an_intent(text: str) -> None:
    assert classify_intent(text) == BOILERPLATE


def test_short_text_is_empty_not_human() -> None:
    assert classify_intent("ok") == EMPTY
    assert classify_intent("") == EMPTY


def test_a_real_request_is_a_human_intent() -> None:
    assert classify_intent("Fixe le zab projet il ne démarre plus via le raycast") == HUMAN


def test_the_same_task_restated_shares_one_key() -> None:
    """Une session reprise ne doit pas créer un second paquet."""
    first = intent_key("Corriger le dashboard qui ne démarre plus (essai 1)")
    second = intent_key("Corriger le dashboard qui ne démarre plus (essai 2)")
    assert first == second

    other = intent_key("Préparer la facture du mois")
    assert other != first


def test_title_drops_the_command_prefix_and_the_attached_path() -> None:
    assert intent_title("loop /loop 10m Dossier Fournisseur 360 — itération autonome").startswith(
        "Dossier Fournisseur"
    )
    assert intent_title('@"/Users/x/Downloads/inventaire.csv" à partir de ce fichier construis').startswith(
        "à partir de ce fichier"
    )


def test_title_keeps_the_first_sentence_and_truncates() -> None:
    long_text = "Refaire la page de connexion. Puis migrer le reste de l'application vers la nouvelle stack."
    assert intent_title(long_text) == "Refaire la page de connexion"

    assert len(intent_title("x" * 300)) <= 90
    assert intent_title("x" * 300).endswith("…")


def test_untitled_intent_never_produces_an_empty_title() -> None:
    assert intent_title("") == "Tâche sans intitulé"
    assert intent_title("/goal") == "Tâche sans intitulé"
