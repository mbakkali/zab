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
    assert ledger_db.cursors_key("vm-de-travail") == "ledger.source_cursors.vm-de-travail"


def test_machine_id_forcable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZAB_MACHINE_ID", "poste-de-test")
    assert ledger_db.machine_id() == "poste-de-test"


def test_le_schema_vient_du_genre_de_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le genre, pas le nom d'hôte : un Mac renommé reste un Mac.

    Nommer les schémas d'après des hôtes changeants laisserait un schéma
    orphelin derrière chaque renommage.
    """
    monkeypatch.delenv("ZAB_LEDGER_SCHEMA", raising=False)
    monkeypatch.setattr(
        ledger_db, "get_machine", lambda: {"genre": "mac", "hote": "macbook-de-x"}
    )
    assert ledger_db.schema() == "zab_mac"
    monkeypatch.setattr(
        ledger_db, "get_machine", lambda: {"genre": "vm", "hote": "vm-de-travail"}
    )
    assert ledger_db.schema() == "zab_vm"


def test_une_machine_quelconque_retombe_sur_son_hote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ZAB_LEDGER_SCHEMA", raising=False)
    monkeypatch.setattr(
        ledger_db, "get_machine", lambda: {"genre": "autre", "hote": "Poste-De.Test"}
    )
    assert ledger_db.schema() == "zab_poste_de_test"


def test_le_nom_de_schema_est_assaini() -> None:
    """Un nom d'hôte ne doit jamais pouvoir devenir un identifiant SQL hostile."""
    assert ledger_db._assainir("héllo; DROP SCHEMA x--") == "h_llo__drop_schema_x"
    assert ledger_db._assainir("") == "inconnu"
    assert len(ledger_db._assainir("x" * 200)) == 40


def test_schema_forcable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZAB_LEDGER_SCHEMA", "zab_essai")
    assert ledger_db.schema() == "zab_essai"


def test_schema_dune_autre_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pouvoir viser le schéma d'en face sans être sur la machine d'en face."""
    monkeypatch.delenv("ZAB_LEDGER_SCHEMA", raising=False)
    assert ledger_db.schema("mac") == "zab_mac"
    assert ledger_db.schema("vm") == "zab_vm"


def test_require_postgres_refuse_le_repli_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Le repli silencieux est ce qui a produit deux magasins séparés."""
    monkeypatch.delenv("ZAB_LEDGER_BACKEND", raising=False)
    monkeypatch.setenv("ZAB_REQUIRE_POSTGRES", "1")
    monkeypatch.setattr(ledger_db, "resolve_postgres_dsn", lambda: "")
    with pytest.raises(ledger_db.LedgerLocalRefuse):
        ledger_db.backend()


def test_require_postgres_laisse_passer_si_le_dsn_repond(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ZAB_LEDGER_BACKEND", raising=False)
    monkeypatch.setenv("ZAB_REQUIRE_POSTGRES", "1")
    monkeypatch.setattr(ledger_db, "resolve_postgres_dsn", lambda: "postgres://x")
    assert ledger_db.backend() == "postgres"


def test_sans_exigence_le_repli_reste_possible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un Mac qui vient d'être installé écrit en local plutôt que d'échouer."""
    monkeypatch.delenv("ZAB_LEDGER_BACKEND", raising=False)
    monkeypatch.setenv("ZAB_REQUIRE_POSTGRES", "0")
    monkeypatch.setattr(ledger_db, "resolve_postgres_dsn", lambda: "")
    assert ledger_db.backend() == "sqlite"
