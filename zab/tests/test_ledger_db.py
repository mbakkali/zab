"""L'adaptateur du ledger : ce qui doit rester vrai des deux côtés.

Ces cas ne demandent aucune base. Ils tiennent la promesse du module — le code
appelant ne sait pas quel moteur répond — sur les trois points où SQLite et
Postgres divergeaient réellement : les marqueurs de paramètre, l'accès aux
colonnes par position, et le type rendu pour `payload_json`.
"""

from __future__ import annotations

import json

import pytest

from zab.services import ledger_db


def test_traduit_les_marqueurs_de_parametre() -> None:
    assert (
        ledger_db._en_postgres("SELECT a FROM t WHERE b = ? AND c = ? LIMIT ?")
        == "SELECT a FROM t WHERE b = %s AND c = %s LIMIT %s"
    )


def test_ne_traduit_pas_un_point_dinterrogation_dans_une_chaine() -> None:
    """Une substitution naïve corromprait la requête sans rien dire."""
    assert (
        ledger_db._en_postgres("SELECT '?' FROM t WHERE a = ?")
        == "SELECT '?' FROM t WHERE a = %s"
    )


def test_ligne_lisible_par_position_et_par_nom() -> None:
    """Le SQL du ledger lit `row[0]` ; psycopg rend des dictionnaires."""
    ligne = ledger_db._Ligne({"payload_json": "{}", "source": "gmail"})
    assert ligne[0] == "{}"
    assert ligne["source"] == "gmail"
    assert list(ligne.keys()) == ["payload_json", "source"]
    assert len(ligne) == 2


def test_jsonb_ressort_en_texte() -> None:
    """`payload_json` est TEXT en SQLite et jsonb en Postgres.

    Sans cette normalisation, `json.loads(row[0])` lèverait un TypeError à la
    lecture — une panne invisible à l'écriture.
    """
    ligne = ledger_db._Ligne({"payload_json": {"title": "Réunion"}})
    assert isinstance(ligne[0], str)
    assert json.loads(ligne[0])["title"] == "Réunion"


def test_backend_retombe_sur_sqlite_sans_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Une machine sans proxy Cloud SQL écrit en local plutôt que d'échouer."""
    monkeypatch.delenv("ZAB_LEDGER_BACKEND", raising=False)
    monkeypatch.setattr(ledger_db, "resolve_postgres_dsn", lambda: "")
    assert ledger_db.backend() == "sqlite"


def test_backend_forcable_en_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZAB_LEDGER_BACKEND", "sqlite")
    monkeypatch.setattr(ledger_db, "resolve_postgres_dsn", lambda: "postgres://x")
    assert ledger_db.backend() == "sqlite"


def test_cle_de_curseur_propre_a_la_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Une clé unique et partagée faisait qu'une machine effaçait l'autre."""
    monkeypatch.setenv("ZAB_MACHINE_ID", "mac-de-mehdi")
    assert ledger_db.cursors_key() == "ledger.source_cursors.mac-de-mehdi"
    assert ledger_db.cursors_key("cowork-linux") == "ledger.source_cursors.cowork-linux"


def test_machine_id_forcable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZAB_MACHINE_ID", "poste-de-test")
    assert ledger_db.machine_id() == "poste-de-test"
