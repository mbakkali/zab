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

# Le schéma commun : registres, état, tâches, méta. Il ne porte plus le ledger.
SCHEMA_COMMUN = postgres_store.SCHEMA

# Le schéma des vues d'union, en lecture seule.
SCHEMA_UNION = "zab_all"

PREFIXE_DEVICE = "zab_"

TABLES = (
    "ledger_events",
    "ledger_workpackets",
    "ledger_projection_states",
    "ledger_organizations",
    "ledger_workstreams",
)

# Le ledger vit dans un schéma par machine — `zab_mac`, `zab_vm`. Deux zab
# écrivent alors sans jamais se marcher dessus, et l'origine d'une ligne se lit
# dans son emplacement plutôt que dans une colonne qu'on oublierait de remplir.
# Ce qu'on y perd, une vue d'ensemble, se rattrape par les vues de `zab_all`,
# qui font l'union de tous les schémas de machine.
DDL_LEDGER = """
CREATE TABLE IF NOT EXISTS {schema}.ledger_events (
    event_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    native_id TEXT NOT NULL,
    channel_id TEXT,
    timestamp TEXT,
    payload_json JSONB NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (source, native_id)
);
CREATE INDEX IF NOT EXISTS idx_ledger_events_timestamp
    ON {schema}.ledger_events (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_ledger_events_channel
    ON {schema}.ledger_events (channel_id);

CREATE TABLE IF NOT EXISTS {schema}.ledger_workpackets (
    workpacket_id TEXT PRIMARY KEY,
    display_id TEXT UNIQUE,
    state TEXT,
    organization_id TEXT,
    client_workstream_id TEXT,
    payload_json JSONB NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ledger_workpackets_state
    ON {schema}.ledger_workpackets (state);
CREATE INDEX IF NOT EXISTS idx_ledger_workpackets_org
    ON {schema}.ledger_workpackets (organization_id);

CREATE TABLE IF NOT EXISTS {schema}.ledger_projection_states (
    workpacket_id TEXT NOT NULL,
    target TEXT NOT NULL,
    status TEXT,
    payload_json JSONB NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (workpacket_id, target)
);
CREATE INDEX IF NOT EXISTS idx_ledger_projection_status
    ON {schema}.ledger_projection_states (status);

CREATE TABLE IF NOT EXISTS {schema}.ledger_organizations (
    organization_id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS {schema}.ledger_workstreams (
    client_workstream_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    label TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ledger_workstreams_org
    ON {schema}.ledger_workstreams (organization_id);
"""



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


def _assainir(nom: str) -> str:
    """Un nom d'hôte devient un identifiant de schéma sûr.

    ASCII strictement : `isalnum()` accepte les accents, et un `é` dans un nom
    de schéma se cite différemment selon le client SQL. Le nom finit dans un
    `CREATE SCHEMA` non paramétrable — c'est le seul endroit du module où une
    chaîne entre dans du SQL sans passer par un marqueur.
    """
    propre = "".join(
        c if (c.isascii() and c.isalnum()) else "_" for c in nom.lower()
    ).strip("_")
    return propre[:40] or "inconnu"


def schema(machine: str | None = None) -> str:
    """Le schéma d'écriture d'une machine — `zab_mac`, `zab_vm`.

    Le genre plutôt que le nom d'hôte : un Mac reste un Mac même renommé, et
    deux schémas nommés d'après des hôtes changeants laisseraient des schémas
    orphelins derrière eux. Une machine qui n'est ni l'un ni l'autre retombe
    sur son nom d'hôte, assaini.
    """
    force = (os.environ.get("ZAB_LEDGER_SCHEMA") or "").strip()
    if force:
        return force
    if machine:
        return f"{PREFIXE_DEVICE}{_assainir(machine)}"
    infos = get_machine()
    genre = str(infos.get("genre") or "")
    if genre in ("mac", "vm"):
        return f"{PREFIXE_DEVICE}{genre}"
    return f"{PREFIXE_DEVICE}{_assainir(str(infos.get('hote') or 'inconnu'))}"


def device_schemas() -> list[str]:
    """Les schémas de machine existants, `zab_all` et le commun exclus."""
    if backend() == "sqlite":
        return []
    with postgres_store.transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT nspname FROM pg_namespace "
                "WHERE nspname LIKE %s AND nspname NOT IN (%s, %s) ORDER BY nspname",
                (f"{PREFIXE_DEVICE}%", SCHEMA_COMMUN, SCHEMA_UNION),
            )
            lignes = cur.fetchall()
    return [(l["nspname"] if isinstance(l, dict) else l[0]) for l in lignes]


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
def transaction(*, scope: str = "device") -> Iterator[Any]:
    """La transaction du ledger.

    `scope="device"` — le schéma de cette machine. C'est le défaut, et le seul
    qui accepte l'écriture.

    `scope="all"` — les vues d'union de `zab_all`, qui rassemblent toutes les
    machines. **Lecture seule** : une vue d'union n'est pas modifiable, et une
    écriture y échouerait bruyamment plutôt que d'aller silencieusement dans le
    mauvais schéma.
    """
    if backend() == "sqlite":
        with local_db.transaction() as conn:
            yield conn
        return

    cible = SCHEMA_UNION if scope == "all" else schema()
    with postgres_store.transaction() as conn:
        enveloppe = _Connexion(conn)
        with conn.cursor() as cur:
            cur.execute(
                f"SET LOCAL search_path TO {cible}, {SCHEMA_COMMUN}, public"
            )
        yield enveloppe


def ensure_schema() -> dict[str, Any]:
    """Crée les tables du ledger dans le schéma canonique si elles manquent."""
    if backend() == "sqlite":
        local_db.migrate_schema()
        return {"backend": "sqlite", "tables": list(TABLES), "created": False}

    postgres_store.migrate_schema()
    mien = schema()
    with postgres_store.transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {mien}")
            cur.execute(DDL_LEDGER.format(schema=mien))
    vues = rebuild_union_views()
    return {
        "backend": "postgres",
        "schema": mien,
        "shared_schema": SCHEMA_COMMUN,
        "union_schema": SCHEMA_UNION,
        "devices": vues["devices"],
        "tables": list(TABLES),
    }


def rebuild_union_views() -> dict[str, Any]:
    """(Re)construit les vues de `zab_all` : l'union de toutes les machines.

    Une machine qui apparaît n'est pas vue tant que les vues n'ont pas été
    rejouées — d'où l'appel à chaque `ensure_schema`. Chaque vue ajoute une
    colonne `device` : sans elle, deux lignes venues de machines différentes
    seraient indiscernables une fois réunies.
    """
    schemas = device_schemas()
    with postgres_store.transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA_UNION}")
            for table in TABLES:
                if not schemas:
                    cur.execute(f"DROP VIEW IF EXISTS {SCHEMA_UNION}.{table}")
                    continue
                morceaux = " UNION ALL ".join(
                    f"SELECT '{s[len(PREFIXE_DEVICE):]}'::text AS device, * "
                    f"FROM {s}.{table}"
                    for s in schemas
                )
                cur.execute(
                    f"CREATE OR REPLACE VIEW {SCHEMA_UNION}.{table} AS {morceaux}"
                )
    return {"union_schema": SCHEMA_UNION, "devices": schemas, "tables": list(TABLES)}


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


def migrate_from_shared_schema(*, apply: bool = False) -> dict[str, Any]:
    """Déplace un ledger resté dans le schéma commun vers celui de la machine.

    Le ledger a d'abord vécu dans `zab_core`, avant qu'on ne le range par
    machine. Les lignes qui s'y trouvent viennent forcément de la machine qui
    lance cette reprise : c'est la seule qui y écrivait. Rien n'est supprimé
    côté source tant que `--apply` n'est pas passé, et la copie est idempotente.
    """
    mien = schema()
    rapport: dict[str, Any] = {
        "contract": "zab-ledger-schema-migration",
        "from": SCHEMA_COMMUN,
        "to": mien,
        "dry_run": not apply,
        "tables": {},
    }
    if backend() == "sqlite":
        rapport["status"] = "sans_objet"
        return rapport

    ensure_schema()
    with postgres_store.transaction() as conn:
        with conn.cursor() as cur:
            for table in TABLES:
                cur.execute(
                    "SELECT to_regclass(%s) IS NOT NULL AS existe",
                    (f"{SCHEMA_COMMUN}.{table}",),
                )
                ligne = cur.fetchone()
                if not (ligne["existe"] if isinstance(ligne, dict) else ligne[0]):
                    rapport["tables"][table] = {"source": 0, "deplacees": 0}
                    continue
                cur.execute(f"SELECT count(*) AS n FROM {SCHEMA_COMMUN}.{table}")
                ligne = cur.fetchone()
                source = ligne["n"] if isinstance(ligne, dict) else ligne[0]
                avant = 0
                cur.execute(f"SELECT count(*) AS n FROM {mien}.{table}")
                ligne = cur.fetchone()
                avant = ligne["n"] if isinstance(ligne, dict) else ligne[0]
                if apply and source:
                    cur.execute(
                        f"INSERT INTO {mien}.{table} "
                        f"SELECT * FROM {SCHEMA_COMMUN}.{table} "
                        "ON CONFLICT DO NOTHING"
                    )
                cur.execute(f"SELECT count(*) AS n FROM {mien}.{table}")
                ligne = cur.fetchone()
                apres = ligne["n"] if isinstance(ligne, dict) else ligne[0]
                rapport["tables"][table] = {
                    "source": source,
                    "avant": avant,
                    "apres": apres,
                    "deplacees": apres - avant,
                }
    rapport["status"] = "applique" if apply else "simule"
    rapport["note"] = (
        "les tables d'origine sont laissées en place ; les vider est une "
        "décision séparée, une fois la bascule vérifiée"
    )
    return rapport


def status() -> dict[str, Any]:
    """Ce que le ledger contient, et sur quel moteur."""
    infos: dict[str, Any] = {
        "contract": "zab-ledger-db-status",
        "backend": backend(),
        "machine": machine_id(),
        "schema": schema() if backend() == "postgres" else None,
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

    # Ce que les autres machines détiennent. Sans cette vue, un chiffre bas ici
    # se lit comme une perte alors que les lignes sont simplement ailleurs.
    if backend() == "postgres":
        infos["devices"] = {}
        try:
            for autre in device_schemas():
                with postgres_store.transaction() as conn:
                    with conn.cursor() as cur:
                        cur.execute(f"SELECT count(*) AS n FROM {autre}.ledger_events")
                        ligne = cur.fetchone()
                infos["devices"][autre[len(PREFIXE_DEVICE):]] = (
                    ligne["n"] if isinstance(ligne, dict) else ligne[0]
                )
        except Exception as souci:
            infos["devices_error"] = f"{type(souci).__name__}: {souci}"

    chemin = local_db.database_path()
    infos["sqlite_legacy"] = {
        "path": str(chemin),
        "exists": chemin.exists(),
        "bytes": chemin.stat().st_size if chemin.exists() else 0,
    }
    return infos
