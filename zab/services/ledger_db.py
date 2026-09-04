"""La porte unique du Conversation Ledger — Postgres, partagé entre machines.

Le ledger écrivait dans un SQLite local (`~/.local/share/zab/zab.db`) pendant
que le reste de zab écrivait dans Postgres. Deux conséquences, toutes deux
mesurées le 2026-09-04 :

  · `zab db status` listait 18 tables et **aucune** table `ledger_*` : le
    magasin canonique ne savait pas que 4 894 interactions, 220 work packets et
    9 organisations existaient ;
  · le SQLite est propre à la machine. Le Mac et la VM tenaient chacun leur
    ledger, sans jamais se voir, et le curseur de synchronisation d'un canal
    était une clé globale que la seconde machine écrasait.

Ce module rend le ledger à Postgres. Le SQL du ledger était déjà portable —
`ON CONFLICT ... DO UPDATE SET excluded.*` est du Postgres autant que du
SQLite — seuls les marqueurs de paramètre différaient. L'adaptateur ci-dessous
traduit `?` en `%s` et rien d'autre : le code appelant n'a pas à savoir quel
moteur répond.

Le repli SQLite reste atteignable par `ZAB_LEDGER_BACKEND=sqlite`, le temps que
la bascule se prouve. Il n'est pas le défaut, et il ne voit pas ce que l'autre
machine écrit.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from zab.services import local_db, postgres_store
from zab.services.postgres_dsn import resolve_postgres_dsn
from zab.services.machine import get_machine

SCHEMA = postgres_store.SCHEMA

# Les tables que ce module possède. Elles vivent dans le même schéma que le
# reste de zab : un ledger dans un schéma à part se serait fait oublier des
# sauvegardes et de `zab db status`, ce qui est exactement le défaut corrigé.
TABLES = (
    "ledger_events",
    "ledger_workpackets",
    "ledger_projection_states",
    "ledger_organizations",
    "ledger_workstreams",
)



def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def backend() -> str:
    """`postgres` dès qu'un DSN répond ; SQLite sinon.

    C'est la règle que le reste de zab applique déjà, fonction par fonction
    (`postgres_store` : *pas de DSN, donc SQLite*). La reprendre ici évite deux
    surprises : une machine sans proxy Cloud SQL — un Mac qui vient d'être
    installé — n'échoue pas, elle écrit en local ; et la suite de tests, qui
    isole `HOME`, n'a pas besoin de connaître Postgres pour tourner.

    `ZAB_LEDGER_BACKEND=sqlite` force le repli même quand Postgres répond.
    """
    if (os.environ.get("ZAB_LEDGER_BACKEND") or "").strip().lower() == "sqlite":
        return "sqlite"
    return "postgres" if resolve_postgres_dsn() else "sqlite"


def machine_id() -> str:
    """L'identifiant de la machine qui écrit — le nom court de l'hôte.

    Il sert à ranger les curseurs de synchronisation par machine. Deux zab qui
    partagent la même base doivent partager les *données* sans partager leur
    *avancement de lecture* : le Mac lit iMessage, la VM ne peut pas, et un
    curseur commun ferait croire à chacun que l'autre a déjà tout lu.
    """
    forcee = (os.environ.get("ZAB_MACHINE_ID") or "").strip()
    if forcee:
        return forcee
    infos = get_machine()
    return str(infos.get("hote") or infos.get("genre") or "inconnue")


# --------------------------------------------------------------------------- #
# L'adaptateur                                                                 #
# --------------------------------------------------------------------------- #


def _en_postgres(sql: str) -> str:
    """Traduit les `?` de SQLite en `%s`, sans toucher aux chaînes littérales.

    Le SQL du ledger n'a pas de `?` dans une chaîne aujourd'hui, mais le jour
    où il y en aura un, une substitution naïve corromprait la requête sans rien
    dire — et une requête corrompue dans un `INSERT` se voit six mois plus tard.
    """
    sortie: list[str] = []
    quote: str | None = None
    for i, car in enumerate(sql):
        if quote:
            sortie.append(car)
            if car == quote and sql[i - 1 : i] != "\\":
                quote = None
            continue
        if car in ("'", '"'):
            quote = car
            sortie.append(car)
            continue
        sortie.append("%s" if car == "?" else car)
    return "".join(sortie)


class _Ligne:
    """Une ligne lisible par position **et** par nom, comme `sqlite3.Row`.

    psycopg rend des dictionnaires ; le SQL du ledger lit `row[0]`. Sans cette
    enveloppe, chaque `SELECT payload_json` lèverait un `KeyError` là où le
    code attendait une chaîne — une panne qui ne se voit qu'à l'exécution.
    """

    __slots__ = ("_valeurs", "_cles")

    def __init__(self, ligne: dict[str, Any]) -> None:
        self._valeurs = [_texte_si_json(v) for v in ligne.values()]
        self._cles = list(ligne.keys())

    def __getitem__(self, cle: Any) -> Any:
        if isinstance(cle, int):
            return self._valeurs[cle]
        return self._valeurs[self._cles.index(cle)]

    def keys(self) -> list[str]:
        return list(self._cles)

    def __iter__(self) -> Iterator[Any]:
        return iter(self._valeurs)

    def __len__(self) -> int:
        return len(self._valeurs)

    def __repr__(self) -> str:
        return f"_Ligne({dict(zip(self._cles, self._valeurs))!r})"


def _texte_si_json(valeur: Any) -> Any:
    """Rend un `jsonb` sous la même forme que le `TEXT` de SQLite.

    Les colonnes `payload_json` sont `TEXT` côté SQLite et `jsonb` côté
    Postgres. psycopg désérialise donc ce que le code appelant s'apprête à
    passer à `json.loads` — et l'erreur n'apparaît qu'à la lecture, pas à
    l'écriture. L'adaptateur rétablit le contrat : ce qui entre en texte
    ressort en texte, quel que soit le moteur.
    """
    if isinstance(valeur, (dict, list)):
        return json.dumps(valeur, ensure_ascii=False)
    return valeur


def _enveloppe(ligne: Any) -> Any:
    return _Ligne(ligne) if isinstance(ligne, dict) else ligne


class _Curseur:
    """Un curseur psycopg qui se laisse lire comme un curseur sqlite3."""

    def __init__(self, cur: Any) -> None:
        self._cur = cur

    def fetchone(self) -> Any:
        return _enveloppe(self._cur.fetchone())

    def fetchall(self) -> list[Any]:
        return [_enveloppe(r) for r in self._cur.fetchall()]

    def __iter__(self) -> Iterator[Any]:
        return (_enveloppe(r) for r in self._cur)

    def __getattr__(self, nom: str) -> Any:
        return getattr(self._cur, nom)


class _Connexion:
    """Une connexion Postgres qui accepte le SQL écrit pour SQLite.

    Volontairement mince : elle traduit les marqueurs de paramètre et rien
    d'autre. Tout ce qui demanderait plus qu'une traduction — un `PRAGMA`, un
    `executescript` — doit être écrit en Postgres, pas émulé ici.
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def execute(self, sql: str, params: Any = ()) -> _Curseur:
        cur = self._conn.cursor()
        cur.execute(_en_postgres(sql), tuple(params) if params else None)
        return _Curseur(cur)

    def executemany(self, sql: str, seq: Any) -> None:
        with self._conn.cursor() as cur:
            cur.executemany(_en_postgres(sql), [tuple(p) for p in seq])

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    @property
    def brut(self) -> Any:
        """La connexion psycopg elle-même, pour le SQL qui n'a pas à être traduit."""
        return self._conn


@contextmanager
def transaction() -> Iterator[Any]:
    """La transaction du ledger. Postgres par défaut, SQLite sur demande."""
    if backend() == "sqlite":
        with local_db.transaction() as conn:
            yield conn
        return

    with postgres_store.transaction() as conn:
        enveloppe = _Connexion(conn)
        with conn.cursor() as cur:
            cur.execute(f"SET LOCAL search_path TO {SCHEMA}, public")
        yield enveloppe


def ensure_schema() -> dict[str, Any]:
    """Crée les tables du ledger dans le schéma canonique si elles manquent."""
    if backend() == "sqlite":
        local_db.migrate_schema()
        return {"backend": "sqlite", "tables": list(TABLES), "created": False}

    # Le DDL des tables `ledger_*` vit dans `postgres_store._migrate_v4` : le
    # recopier ici en ferait une seconde vérité, qui divergerait au premier
    # ajout de colonne.
    postgres_store.migrate_schema()
    return {"backend": "postgres", "schema": SCHEMA, "tables": list(TABLES)}


# --------------------------------------------------------------------------- #
# Méta partagée, curseurs par machine                                          #
# --------------------------------------------------------------------------- #


def get_meta(cle: str, defaut: Any = None) -> Any:
    if backend() == "sqlite":
        return local_db.get_meta(cle, defaut)
    return postgres_store.get_meta(cle, defaut)


def set_meta(cle: str, valeur: Any) -> None:
    if backend() == "sqlite":
        local_db.set_meta(cle, valeur)
        return
    postgres_store.set_meta(cle, valeur)


def cursors_key(machine: str | None = None) -> str:
    """La clé des curseurs, propre à une machine.

    `ledger.source_cursors` était une clé unique. Avec une base partagée, la
    dernière machine à synchroniser effaçait l'avancement de l'autre : chacune
    reprenait alors la lecture d'un canal là où l'autre l'avait laissée, et
    sautait les messages arrivés entre-temps.
    """
    return f"ledger.source_cursors.{machine or machine_id()}"


def get_source_cursors(machine: str | None = None) -> dict[str, Any]:
    valeur = get_meta(cursors_key(machine), None)
    if isinstance(valeur, dict):
        return valeur
    if isinstance(valeur, str):
        try:
            return json.loads(valeur)
        except json.JSONDecodeError:
            return {}
    # Reprise de l'ancienne clé globale, une seule fois : sans elle, la
    # première synchronisation après bascule relirait tout l'historique.
    ancien = get_meta("ledger.source_cursors", None)
    if isinstance(ancien, str):
        try:
            ancien = json.loads(ancien)
        except json.JSONDecodeError:
            ancien = None
    return ancien if isinstance(ancien, dict) else {}


def set_source_cursor(channel_id: str, cursor: dict[str, Any]) -> None:
    curseurs = get_source_cursors()
    curseurs[channel_id] = {**cursor, "updated_at": utc_now(), "machine": machine_id()}
    set_meta(cursors_key(), curseurs)


# --------------------------------------------------------------------------- #
# Reprise du SQLite                                                            #
# --------------------------------------------------------------------------- #

_CLES = {
    "ledger_events": ("event_id",),
    "ledger_workpackets": ("workpacket_id",),
    "ledger_projection_states": ("workpacket_id", "target"),
    "ledger_organizations": ("organization_id",),
    "ledger_workstreams": ("client_workstream_id",),
}


def _colonnes_sqlite(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def import_sqlite(*, apply: bool = False) -> dict[str, Any]:
    """Recopie le ledger SQLite dans Postgres. Idempotent, rejouable.

    Rien n'est supprimé côté SQLite : tant que la bascule n'est pas prouvée, le
    fichier reste la sauvegarde. `--apply` est explicite pour la même raison.
    """
    chemin = local_db.database_path()
    rapport: dict[str, Any] = {
        "contract": "zab-ledger-import",
        "source": str(chemin),
        "dry_run": not apply,
        "tables": {},
    }
    if not chemin.exists():
        rapport["status"] = "absent"
        return rapport

    ensure_schema()
    src = sqlite3.connect(f"file:{chemin}?mode=ro", uri=True)
    try:
        with transaction() as dst:
            for table, cles in _CLES.items():
                try:
                    colonnes = _colonnes_sqlite(src, table)
                except sqlite3.Error:
                    colonnes = []
                if not colonnes:
                    rapport["tables"][table] = {"source": 0, "importees": 0}
                    continue
                lignes = src.execute(
                    f"SELECT {', '.join(colonnes)} FROM {table}"
                ).fetchall()
                avant = dst.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                if apply and lignes:
                    conflit = ", ".join(cles)
                    maj = ", ".join(
                        f"{c}=excluded.{c}" for c in colonnes if c not in cles
                    )
                    sql = (
                        f"INSERT INTO {table} ({', '.join(colonnes)}) "
                        f"VALUES ({', '.join('?' for _ in colonnes)}) "
                        f"ON CONFLICT ({conflit}) DO UPDATE SET {maj}"
                    )
                    dst.executemany(sql, lignes)
                apres = dst.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                rapport["tables"][table] = {
                    "source": len(lignes),
                    "avant": avant,
                    "apres": apres,
                    "importees": apres - avant if apply else 0,
                }
    finally:
        src.close()

    rapport["curseurs"] = _import_curseurs_sqlite(chemin, apply=apply)
    rapport["status"] = "applique" if apply else "simule"
    return rapport


def _import_curseurs_sqlite(chemin: Any, *, apply: bool) -> dict[str, Any]:
    """Reprend l'avancement de lecture des canaux, sous la clé de cette machine.

    Sans lui, la première synchronisation après bascule relirait tout
    l'historique de chaque canal — plusieurs milliers de messages, et autant
    d'appels d'API pour un résultat déjà en base.
    """
    src = sqlite3.connect(f"file:{chemin}?mode=ro", uri=True)
    try:
        ligne = src.execute(
            "SELECT value_json FROM sync_meta WHERE key = ?", ("ledger.source_cursors",)
        ).fetchone()
    except sqlite3.Error:
        ligne = None
    finally:
        src.close()
    if not ligne:
        return {"repris": 0}
    try:
        anciens = json.loads(ligne[0])
    except (json.JSONDecodeError, TypeError):
        return {"repris": 0}
    if not isinstance(anciens, dict):
        return {"repris": 0}

    deja = get_source_cursors()
    fusion = {**anciens, **deja}  # ce que cette machine a déjà lu fait foi
    if apply:
        set_meta(cursors_key(), fusion)
    return {"repris": len(anciens), "canaux": sorted(anciens), "machine": machine_id()}


def status() -> dict[str, Any]:
    """Ce que le ledger contient, et sur quel moteur."""
    infos: dict[str, Any] = {
        "contract": "zab-ledger-db-status",
        "backend": backend(),
        "machine": machine_id(),
        "tables": {},
    }
    try:
        with transaction() as conn:
            for table in TABLES:
                try:
                    infos["tables"][table] = conn.execute(
                        f"SELECT count(*) FROM {table}"
                    ).fetchone()[0]
                except Exception as souci:  # table absente : on le dit, on ne casse pas
                    infos["tables"][table] = f"erreur: {type(souci).__name__}"
        infos["ok"] = True
    except Exception as souci:
        infos["ok"] = False
        infos["error"] = f"{type(souci).__name__}: {souci}"

    chemin = local_db.database_path()
    infos["sqlite_legacy"] = {
        "path": str(chemin),
        "exists": chemin.exists(),
        "bytes": chemin.stat().st_size if chemin.exists() else 0,
    }
    return infos
