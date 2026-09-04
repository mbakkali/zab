"""Canonical Postgres store for Zab generated state and operational registries."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import yaml

from zab.paths import config_dir, data_dir
from zab.services.postgres_dsn import resolve_postgres_dsn
from zab.services.memory_db import _pg_connect_timeout, memory_psycopg_available

SCHEMA_VERSION = 4
SCHEMA = "zab_core"
TABLES = (
    "sync_meta",
    "state_sections",
    "skills_registry",
    "mcp_registry",
    "tasks_sources",
    "tasks_items",
    "crons",
    "cron_runs",
    "communication_channels",
    "dashboard_actions",
    "request_events",
    "search_index",
    "brain_conversations",
    "brain_messages",
    "brain_artifacts",
    "brain_entities",
    "brain_edges",
    "brain_ingest_runs",
    # Le Conversation Ledger. Absentes de cette liste jusqu'au 2026-09-04,
    # `zab db status` affichait 18 tables et taisait 4 929 interactions,
    # 220 work packets et 9 organisations restées côté SQLite.
    "ledger_events",
    "ledger_workpackets",
    "ledger_projection_states",
    "ledger_organizations",
    "ledger_workstreams",
)


class PostgresStoreError(RuntimeError):
    code = "postgres_error"


class PostgresNotConfigured(PostgresStoreError):
    code = "postgres_not_configured"


class PostgresUnavailable(PostgresStoreError):
    code = "postgres_unreachable"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def database_path() -> str:
    """Compatibility label for callers that used to display the SQLite path."""
    return f"postgres://{SCHEMA}"


def _dsn() -> str:
    url = resolve_postgres_dsn()
    if not url:
        raise PostgresNotConfigured(
            "ZAB_MEMORY_DATABASE_URL / MEHDI_MEMORY_DATABASE_URL non défini."
        )
    return url


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


def json_safe(value: Any) -> Any:
    return _json_safe(value)


def _json_dumps(value: Any) -> str:
    return json.dumps(_json_safe(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    try:
        return json.loads(str(value))
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        return default


# DSN déjà migrés dans ce process : la migration (CREATE TABLE/INDEX IF NOT
# EXISTS ×30) coûte ~1 s et n'a besoin de tourner qu'une fois par process. Sans
# ce garde-fou, chaque connexion (donc chaque log de requête, chaque lecture)
# relançait tout le DDL. Cf. profilage middleware.
_MIGRATED_DSNS: set[str] = set()


def _connect(*, migrate: bool = True):
    if not memory_psycopg_available():
        raise PostgresUnavailable("psycopg absent ; exécuter `uv sync --extra memory`.")
    dsn = _dsn()
    try:
        import psycopg
        from psycopg.rows import dict_row

        conn = psycopg.connect(dsn, connect_timeout=_pg_connect_timeout(), row_factory=dict_row)
    except PostgresStoreError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalize external driver errors
        raise PostgresUnavailable(str(exc)) from exc
    if migrate and dsn not in _MIGRATED_DSNS:
        migrate_schema(conn)
        _MIGRATED_DSNS.add(dsn)
    return conn


@contextmanager
def transaction() -> Iterator[Any]:
    conn = _connect(migrate=True)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def migrate_schema(conn: Any | None = None) -> dict[str, Any]:
    if conn is None and not resolve_postgres_dsn():
        from zab.services import local_db as sqlite_store

        return sqlite_store.migrate_schema()
    own_conn = conn is None
    if conn is None:
        conn = _connect(migrate=False)
    try:
        with conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {SCHEMA}.schema_migrations (
                    version integer PRIMARY KEY,
                    applied_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            current = _schema_version(cur)
            if current < 1:
                _migrate_v1(cur)
                cur.execute(
                    f"INSERT INTO {SCHEMA}.schema_migrations (version) VALUES (%s) ON CONFLICT (version) DO NOTHING",
                    (1,)
                )
            if current < 2:
                _migrate_v2(cur)
                cur.execute(
                    f"INSERT INTO {SCHEMA}.schema_migrations (version) VALUES (%s) ON CONFLICT (version) DO NOTHING",
                    (2,)
                )
            if current < 3:
                _migrate_v3(cur)
                cur.execute(
                    f"INSERT INTO {SCHEMA}.schema_migrations (version) VALUES (%s) ON CONFLICT (version) DO NOTHING",
                    (3,)
                )
            if current < 4:
                _migrate_v4(cur)
                cur.execute(
                    f"INSERT INTO {SCHEMA}.schema_migrations (version) VALUES (%s) ON CONFLICT (version) DO NOTHING",
                    (4,)
                )
            conn.commit()
            return {
                "database": "postgres",
                "schema": SCHEMA,
                "schema_version": schema_version(conn),
                "created": current == 0,
            }
    finally:
        if own_conn:
            conn.close()


def _schema_version(cur: Any) -> int:
    cur.execute(f"SELECT COALESCE(MAX(version), 0) AS version FROM {SCHEMA}.schema_migrations")
    row = cur.fetchone()
    return int(row["version"] if isinstance(row, dict) else row[0])


def _migrate_v1(cur: Any) -> None:
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.sync_meta (
            key text PRIMARY KEY,
            value jsonb NOT NULL,
            updated_at timestamptz NOT NULL
        )
        """
    )
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.state_sections (
            section text NOT NULL,
            item_key text NOT NULL,
            payload jsonb NOT NULL,
            updated_at timestamptz NOT NULL,
            PRIMARY KEY (section, item_key)
        )
        """
    )
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.skills_registry (
            key text PRIMARY KEY,
            org text NOT NULL,
            slug text NOT NULL,
            status text NOT NULL,
            canonical_path text,
            payload jsonb NOT NULL,
            updated_at timestamptz NOT NULL
        )
        """
    )
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_zab_core_skills_status ON {SCHEMA}.skills_registry(status)")
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_zab_core_skills_org ON {SCHEMA}.skills_registry(org)")
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.mcp_registry (
            slug text PRIMARY KEY,
            status text NOT NULL,
            fingerprint text,
            payload jsonb NOT NULL,
            updated_at timestamptz NOT NULL
        )
        """
    )
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_zab_core_mcp_status ON {SCHEMA}.mcp_registry(status)")
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.tasks_sources (
            id text PRIMARY KEY,
            status text,
            backend text,
            payload jsonb NOT NULL,
            updated_at timestamptz NOT NULL
        )
        """
    )
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.tasks_items (
            source_id text NOT NULL,
            identifier text NOT NULL,
            title text NOT NULL,
            url text,
            state text,
            updated_at_remote text,
            payload jsonb NOT NULL,
            updated_at timestamptz NOT NULL,
            PRIMARY KEY (source_id, identifier)
        )
        """
    )
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_zab_core_tasks_updated ON {SCHEMA}.tasks_items(updated_at_remote DESC)")
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.crons (
            id text PRIMARY KEY,
            name text NOT NULL,
            source text NOT NULL,
            schedule text,
            enabled boolean NOT NULL DEFAULT true,
            status text,
            last_run text,
            next_run text,
            payload jsonb NOT NULL,
            updated_at timestamptz NOT NULL
        )
        """
    )
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.cron_runs (
            id bigserial PRIMARY KEY,
            cron_id text NOT NULL,
            status text NOT NULL,
            content text NOT NULL,
            stdout text,
            stderr text,
            created_at timestamptz NOT NULL
        )
        """
    )
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_zab_core_cron_runs_created ON {SCHEMA}.cron_runs(cron_id, created_at DESC)")
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.communication_channels (
            id text PRIMARY KEY,
            label text NOT NULL,
            type text,
            connector text,
            org text,
            enabled boolean NOT NULL DEFAULT true,
            status text,
            payload jsonb NOT NULL,
            updated_at timestamptz NOT NULL
        )
        """
    )
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.dashboard_actions (
            id text PRIMARY KEY,
            channel_id text,
            status text,
            payload jsonb NOT NULL,
            updated_at timestamptz NOT NULL
        )
        """
    )
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.search_index (
            section text NOT NULL,
            item_key text NOT NULL,
            title text,
            body text,
            payload jsonb NOT NULL,
            tsv tsvector GENERATED ALWAYS AS (
                to_tsvector('simple'::regconfig, coalesce(title, '') || ' ' || coalesce(body, ''))
            ) STORED,
            PRIMARY KEY (section, item_key)
        )
        """
    )
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_zab_core_search_tsv ON {SCHEMA}.search_index USING gin(tsv)")
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_zab_core_search_section ON {SCHEMA}.search_index(section)")


def _migrate_v2(cur: Any) -> None:
    for table in [
        "brain_conversations",
        "brain_messages",
        "brain_artifacts",
        "brain_entities",
        "brain_edges",
        "brain_ingest_runs",
    ]:
        cur.execute(
            f"CREATE TABLE IF NOT EXISTS {SCHEMA}.{table} (id text PRIMARY KEY, payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now())"
        )


def _migrate_v3(cur: Any) -> None:
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.request_events (
            event_id text PRIMARY KEY,
            ts timestamptz NOT NULL,
            level text NOT NULL,
            component text,
            surface text,
            request_id text,
            actor_id text,
            actor_kind text,
            org text,
            project_id text,
            project_path text,
            task_source_id text,
            request_name text,
            status text,
            duration_ms integer,
            http_status integer,
            exit_code integer,
            payload jsonb NOT NULL
        )
        """
    )
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_zab_core_request_events_ts ON {SCHEMA}.request_events(ts DESC)")
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_zab_core_request_events_surface ON {SCHEMA}.request_events(surface)")
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_zab_core_request_events_component ON {SCHEMA}.request_events(component)")
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_zab_core_request_events_actor ON {SCHEMA}.request_events(actor_id)")
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_zab_core_request_events_org ON {SCHEMA}.request_events(org)")
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_zab_core_request_events_project ON {SCHEMA}.request_events(project_id)")
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_zab_core_request_events_status ON {SCHEMA}.request_events(status)")


def _migrate_v4(cur: Any) -> None:
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.ledger_events (
            event_id text PRIMARY KEY,
            source text NOT NULL,
            native_id text NOT NULL,
            channel_id text,
            timestamp timestamptz,
            payload_json jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE(source, native_id)
        )
        """
    )
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_zab_core_ledger_events_ts ON {SCHEMA}.ledger_events(timestamp DESC)")
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.ledger_workpackets (
            workpacket_id text PRIMARY KEY,
            display_id text UNIQUE,
            state text,
            organization_id text,
            client_workstream_id text,
            payload_json jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.ledger_projection_states (
            workpacket_id text NOT NULL,
            target text NOT NULL,
            status text,
            payload_json jsonb NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (workpacket_id, target)
        )
        """
    )
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.ledger_organizations (
            organization_id text PRIMARY KEY,
            label text NOT NULL,
            payload_json jsonb NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.ledger_workstreams (
            client_workstream_id text PRIMARY KEY,
            organization_id text NOT NULL,
            label text NOT NULL,
            payload_json jsonb NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def schema_version(conn: Any | None = None) -> int:
    own_conn = conn is None
    if conn is None:
        conn = _connect(migrate=False)
    try:
        with conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {SCHEMA}.schema_migrations (
                    version integer PRIMARY KEY,
                    applied_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            return _schema_version(cur)
    finally:
        if own_conn:
            conn.close()


def _pgvector_ready(cur: Any) -> bool:
    try:
        cur.execute("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') AS ok")
        row = cur.fetchone()
        return bool(row["ok"] if isinstance(row, dict) else row[0])
    except Exception:
        return False


def status() -> dict[str, Any]:
    # Deux zab partagent cette base. Sans le nom de la machine, deux sorties
    # côte à côte sont indiscernables, et on répare la mauvaise.
    from zab.services.machine import get_machine

    machine = get_machine().get("hote")

    if not resolve_postgres_dsn():
        from zab.services import local_db as sqlite_store

        payload = sqlite_store.status()
        payload["database"] = "sqlite"
        payload["schema"] = None
        payload["configured"] = True
        payload["machine"] = machine
        payload["shared"] = False
        return payload
    payload: dict[str, Any] = {
        "database": "postgres",
        "machine": machine,
        "shared": True,
        "schema": SCHEMA,
        "configured": bool(resolve_postgres_dsn()),
        "connected": False,
        "psycopg_available": memory_psycopg_available(),
        "schema_version": 0,
        "target_schema_version": SCHEMA_VERSION,
        "ok": False,
        "tables": {},
        "pgvector_ready": False,
        "error": None,
    }
    try:
        with _connect(migrate=True) as conn:
            with conn.cursor() as cur:
                payload["connected"] = True
                payload["schema_version"] = schema_version(conn)
                payload["pgvector_ready"] = _pgvector_ready(cur)
                counts: dict[str, int] = {}
                for name in TABLES:
                    cur.execute(f"SELECT count(*) AS n FROM {SCHEMA}.{name}")
                    row = cur.fetchone()
                    counts[name] = int(row["n"] if isinstance(row, dict) else row[0])
                payload["tables"] = counts
                payload["ok"] = True
    except PostgresStoreError as exc:
        payload["error"] = {"code": exc.code, "message": str(exc)}
    except Exception as exc:  # noqa: BLE001
        payload["error"] = {"code": "postgres_error", "message": f"{type(exc).__name__}: {str(exc).splitlines()[0][:240]}"}
    return payload


def probe() -> dict[str, Any]:
    """Cheap readiness probe for the configured primary store."""
    if not resolve_postgres_dsn():
        from zab.services import local_db as sqlite_store

        sqlite_status = sqlite_store.status()
        ready = bool(sqlite_status.get("ok", True))
        return {
            "backend": "sqlite",
            "configured": True,
            "connected": ready,
            "ok": ready,
            "error": sqlite_status.get("error"),
        }

    try:
        with _connect(migrate=False) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS ok")
                cur.fetchone()
        return {
            "backend": "postgres",
            "configured": True,
            "connected": True,
            "ok": True,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 - health must return a structured failure
        return {
            "backend": "postgres",
            "configured": True,
            "connected": False,
            "ok": False,
            "error": {
                "code": getattr(exc, "code", "primary_store_unavailable"),
                "message": "Primary store is unavailable.",
            },
        }


def vacuum() -> dict[str, Any]:
    if not resolve_postgres_dsn():
        from zab.services import local_db as sqlite_store

        payload = sqlite_store.vacuum()
        payload["database"] = "sqlite"
        payload["maintenance"] = "vacuum"
        return payload
    with _connect(migrate=True) as conn:
        with conn.cursor() as cur:
            for name in TABLES:
                cur.execute(f"ANALYZE {SCHEMA}.{name}")
        conn.commit()
    payload = status()
    payload["maintenance"] = "analyze"
    return payload


def _jsonb(value: Any) -> Any:
    from psycopg.types.json import Jsonb

    return Jsonb(_json_safe(value))


def set_meta(key: str, value: Any, conn: Any | None = None) -> None:
    own_conn = conn is None
    if conn is None:
        conn = _connect(migrate=True)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {SCHEMA}.sync_meta (key, value, updated_at)
                VALUES (%s, %s, %s)
                ON CONFLICT(key) DO UPDATE SET
                  value = EXCLUDED.value,
                  updated_at = EXCLUDED.updated_at
                """,
                (key, _jsonb(value), utc_now()),
            )
        if own_conn:
            conn.commit()
    finally:
        if own_conn:
            conn.close()


def get_meta(key: str, default: Any = None) -> Any:
    with _connect(migrate=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT value FROM {SCHEMA}.sync_meta WHERE key = %s", (key,))
            row = cur.fetchone()
    return row["value"] if row else default


def replace_state(state: dict[str, Any]) -> None:
    if not resolve_postgres_dsn():
        from zab.services import local_db as sqlite_store

        return sqlite_store.replace_state(state)
    now = utc_now()
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {SCHEMA}.state_sections")
            cur.execute(f"DELETE FROM {SCHEMA}.search_index")
            for section, value in state.items():
                if not isinstance(value, dict):
                    set_meta(f"state.{section}", value, conn)
                    continue
                for item_key, payload in value.items():
                    if not isinstance(payload, dict):
                        payload = {"value": payload}
                    cur.execute(
                        f"""
                        INSERT INTO {SCHEMA}.state_sections (section, item_key, payload, updated_at)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (section, str(item_key), _jsonb(payload), now),
                    )
                    _upsert_search_index(cur, section, str(item_key), payload)
            set_meta("state.root", {k: v for k, v in state.items() if not isinstance(v, dict)}, conn)


def load_state() -> dict[str, Any]:
    if not resolve_postgres_dsn():
        from zab.services import local_db as sqlite_store

        return sqlite_store.load_state()
    with _connect(migrate=True) as conn:
        root = get_meta("state.root", {})
        with conn.cursor() as cur:
            cur.execute(f"SELECT section, item_key, payload FROM {SCHEMA}.state_sections ORDER BY section, item_key")
            rows = cur.fetchall()
    state = root if isinstance(root, dict) else {}
    for row in rows:
        section = str(row["section"])
        state.setdefault(section, {})
        state[section][str(row["item_key"])] = _json_loads(row["payload"], {})
    return state


def has_state() -> bool:
    if not resolve_postgres_dsn():
        from zab.services import local_db as sqlite_store

        return sqlite_store.has_state()
    with _connect(migrate=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT 1 FROM {SCHEMA}.state_sections LIMIT 1")
            return cur.fetchone() is not None


def list_state_section(section: str) -> list[dict[str, Any]]:
    with _connect(migrate=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT item_key, payload FROM {SCHEMA}.state_sections WHERE section = %s ORDER BY item_key",
                (section,),
            )
            rows = cur.fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        payload = _json_loads(row["payload"], {})
        if isinstance(payload, dict):
            out.append({"key": str(row["item_key"]), **payload})
    return out


def get_state_item(section: str, key: str) -> dict[str, Any] | None:
    with _connect(migrate=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT item_key, payload FROM {SCHEMA}.state_sections WHERE section = %s AND item_key = %s",
                (section, key),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(f"SELECT item_key, payload FROM {SCHEMA}.state_sections WHERE section = %s", (section,))
                rows = cur.fetchall()
            else:
                rows = [row]
    for item in rows:
        payload = _json_loads(item["payload"], {})
        if isinstance(payload, dict) and (
            str(item["item_key"]) == key or str(payload.get("id") or "").lower() == key.lower()
        ):
            return {"key": str(item["item_key"]), **payload}
    return None


def upsert_state_item(section: str, key: str, payload: dict[str, Any]) -> None:
    """Met à jour un seul item de l'index (state + search) sans reconstruire tout l'état.

    Permet à une édition unitaire (ex: annotation d'un tool) d'être immédiatement visible
    par le chemin rapide de lecture, sans ``zab sync`` complet."""

    if not resolve_postgres_dsn():
        from zab.services import local_db as sqlite_store

        return sqlite_store.upsert_state_item(section, key, payload)
    if not has_state():
        return
    now = utc_now()
    payload = payload if isinstance(payload, dict) else {"value": payload}
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {SCHEMA}.state_sections (section, item_key, payload, updated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (section, item_key)
                DO UPDATE SET payload = EXCLUDED.payload, updated_at = EXCLUDED.updated_at
                """,
                (section, str(key), _jsonb(payload), now),
            )
            cur.execute(
                f"DELETE FROM {SCHEMA}.search_index WHERE section = %s AND item_key = %s",
                (section, str(key)),
            )
            _upsert_search_index(cur, section, str(key), payload)


def search_state(query: str, *, sections: list[str] | None = None, limit: int = 20) -> list[dict[str, Any]]:
    if not resolve_postgres_dsn():
        from zab.services import local_db as sqlite_store

        return sqlite_store.search_state(query, sections=sections, limit=limit)
    q = (query or "").strip()
    capped = max(1, min(100, int(limit)))
    params: list[Any] = []
    where = "true"
    order = "section, item_key"
    if q:
        params.append(q)
        where = "tsv @@ websearch_to_tsquery('simple'::regconfig, %s)"
        order = "ts_rank_cd(tsv, websearch_to_tsquery('simple'::regconfig, %s)) DESC, section, item_key"
    if sections:
        where += " AND section = ANY(%s)"
        params.append(sections)
    if q:
        params.append(q)
    params.append(capped)
    try:
        with _connect(migrate=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT section, item_key, payload
                    FROM {SCHEMA}.search_index
                    WHERE {where}
                    ORDER BY {order}
                    LIMIT %s
                    """,
                    tuple(params),
                )
                rows = cur.fetchall()
                if q and not rows:
                    raise RuntimeError("fts_no_rows")
    except Exception:
        terms = [t.lower() for t in q.split() if t]
        with _connect(migrate=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT section, item_key, payload, body FROM {SCHEMA}.search_index")
                rows = cur.fetchall()
        filtered = []
        for row in rows:
            if sections and row["section"] not in sections:
                continue
            body = str(row.get("body") or "").lower()
            if terms and not any(t in body for t in terms):
                continue
            filtered.append(row)
        rows = filtered[:capped]
    return [_row_to_search_result(r) for r in rows]


def _row_to_search_result(row: dict[str, Any]) -> dict[str, Any]:
    payload = _json_loads(row["payload"], {})
    if not isinstance(payload, dict):
        payload = {}
    return {"section": str(row["section"]), "key": str(row["item_key"]), **payload}


def replace_tasks_cache(payload: dict[str, Any]) -> None:
    if not resolve_postgres_dsn():
        from zab.services import local_db as sqlite_store

        return sqlite_store.replace_tasks_cache(payload)
    now = utc_now()
    sources = [x for x in payload.get("sources") or [] if isinstance(x, dict)]
    tasks = [x for x in payload.get("all_tasks") or [] if isinstance(x, dict)]
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {SCHEMA}.tasks_sources")
            cur.execute(f"DELETE FROM {SCHEMA}.tasks_items")
            for src in sources:
                sid = str(src.get("id") or src.get("label") or src.get("source_label") or "unknown")
                cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.tasks_sources (id, status, backend, payload, updated_at)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (sid, src.get("status"), src.get("backend") or src.get("type"), _jsonb(src), now),
                )
            for item in tasks:
                source_id = str(item.get("source_id") or item.get("source_label") or "unknown")
                identifier = str(item.get("identifier") or item.get("url") or item.get("title") or "unknown")
                cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.tasks_items
                      (source_id, identifier, title, url, state, updated_at_remote, payload, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(source_id, identifier) DO UPDATE SET
                      title = EXCLUDED.title,
                      url = EXCLUDED.url,
                      state = EXCLUDED.state,
                      updated_at_remote = EXCLUDED.updated_at_remote,
                      payload = EXCLUDED.payload,
                      updated_at = EXCLUDED.updated_at
                    """,
                    (
                        source_id,
                        identifier,
                        str(item.get("title") or ""),
                        item.get("url"),
                        item.get("state"),
                        item.get("updated_at"),
                        _jsonb(item),
                        now,
                    ),
                )
            set_meta(
                "tasks.cache",
                {
                    "generated_at_utc": payload.get("generated_at_utc"),
                    "parse_errors": payload.get("parse_errors") or [],
                    "env_hints": payload.get("env_hints") or {},
                    "total_count": payload.get("total_count", len(tasks)),
                },
                conn,
            )


def load_tasks_cache() -> dict[str, Any] | None:
    if not resolve_postgres_dsn():
        from zab.services import local_db as sqlite_store

        return sqlite_store.load_tasks_cache()
    with _connect(migrate=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT payload FROM {SCHEMA}.tasks_sources ORDER BY id")
            source_rows = cur.fetchall()
            cur.execute(f"SELECT payload FROM {SCHEMA}.tasks_items ORDER BY updated_at_remote DESC, identifier")
            task_rows = cur.fetchall()
    if not source_rows and not task_rows:
        return None
    meta = get_meta("tasks.cache", {})
    return {
        "generated_at_utc": meta.get("generated_at_utc") if isinstance(meta, dict) else None,
        "parse_errors": meta.get("parse_errors", []) if isinstance(meta, dict) else [],
        "env_hints": meta.get("env_hints", {}) if isinstance(meta, dict) else {},
        "sources": [_json_loads(r["payload"], {}) for r in source_rows],
        "all_tasks": [_json_loads(r["payload"], {}) for r in task_rows],
        "total_count": len(task_rows),
    }


def save_mcp_registry_document(doc: dict[str, Any]) -> None:
    if not resolve_postgres_dsn():
        from zab.services import local_db as sqlite_store

        return sqlite_store.save_mcp_registry_document(doc)
    now = utc_now()
    servers = doc.get("servers") if isinstance(doc.get("servers"), dict) else {}
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {SCHEMA}.mcp_registry")
            for slug, raw in servers.items():
                payload = raw if isinstance(raw, dict) else {}
                cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.mcp_registry (slug, status, fingerprint, payload, updated_at)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        str(slug),
                        str(payload.get("status") or "detected"),
                        payload.get("fingerprint"),
                        _jsonb(payload),
                        now,
                    ),
                )
            set_meta("mcp_registry.document", {k: v for k, v in doc.items() if k != "servers"}, conn)


def load_mcp_registry_document(default: dict[str, Any]) -> dict[str, Any]:
    if not resolve_postgres_dsn():
        from zab.services import local_db as sqlite_store

        return sqlite_store.load_mcp_registry_document(default)
    with _connect(migrate=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT slug, payload FROM {SCHEMA}.mcp_registry ORDER BY slug")
            rows = cur.fetchall()
    if not rows:
        return default
    meta = get_meta("mcp_registry.document", {})
    doc = meta if isinstance(meta, dict) else {}
    doc["servers"] = {str(r["slug"]): _json_loads(r["payload"], {}) for r in rows}
    return doc


def save_skills_registry_document(doc: dict[str, Any]) -> None:
    if not resolve_postgres_dsn():
        from zab.services import local_db as sqlite_store

        return sqlite_store.save_skills_registry_document(doc)
    now = utc_now()
    skills = [x for x in doc.get("skills") or [] if isinstance(x, dict)]
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {SCHEMA}.skills_registry")
            for skill in skills:
                key = str(skill.get("key") or "")
                if not key:
                    continue
                cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.skills_registry
                      (key, org, slug, status, canonical_path, payload, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        key,
                        str(skill.get("org") or "hors-org"),
                        str(skill.get("slug") or "unknown"),
                        str(skill.get("status") or "candidate"),
                        skill.get("canonical_path"),
                        _jsonb(skill),
                        now,
                    ),
                )
            set_meta("skills_registry.document", {k: v for k, v in doc.items() if k != "skills"}, conn)


def load_skills_registry_document(default: dict[str, Any]) -> dict[str, Any]:
    if not resolve_postgres_dsn():
        from zab.services import local_db as sqlite_store

        return sqlite_store.load_skills_registry_document(default)
    with _connect(migrate=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT payload FROM {SCHEMA}.skills_registry ORDER BY key")
            rows = cur.fetchall()
    if not rows:
        return default
    meta = get_meta("skills_registry.document", {})
    doc = meta if isinstance(meta, dict) else {}
    doc["skills"] = [_json_loads(r["payload"], {}) for r in rows]
    return doc


def replace_crons(crons: list[dict[str, Any]]) -> None:
    now = utc_now()
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {SCHEMA}.crons")
            for cron in crons:
                cid = str(cron.get("id") or "")
                if not cid:
                    continue
                cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.crons
                      (id, name, source, schedule, enabled, status, last_run, next_run, payload, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        cid,
                        str(cron.get("name") or cid),
                        str(cron.get("source") or "unknown"),
                        cron.get("schedule"),
                        bool(cron.get("enabled", True)),
                        cron.get("status"),
                        cron.get("last_run"),
                        cron.get("next_run"),
                        _jsonb(cron),
                        now,
                    ),
                )


def load_crons() -> list[dict[str, Any]]:
    with _connect(migrate=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT payload FROM {SCHEMA}.crons ORDER BY source, name")
            rows = cur.fetchall()
    return [_json_loads(r["payload"], {}) for r in rows]


def save_cron_run(cron_id: str, status_value: str, content: str, stdout: str | None = None, stderr: str | None = None) -> None:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {SCHEMA}.cron_runs (cron_id, status, content, stdout, stderr, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (cron_id, status_value, content, stdout, stderr, utc_now()),
            )


def load_cron_runs(cron_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
    with _connect(migrate=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT created_at, status, content, stdout, stderr
                FROM {SCHEMA}.cron_runs
                WHERE cron_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (cron_id, max(1, min(200, limit))),
            )
            rows = cur.fetchall()
    return [
        {
            "timestamp": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else r["created_at"],
            "status": r["status"],
            "content": r["content"],
            "stdout": r.get("stdout"),
            "stderr": r.get("stderr"),
        }
        for r in rows
    ]


def replace_channels(channels: list[dict[str, Any]]) -> None:
    if not resolve_postgres_dsn():
        from zab.services import local_db as sqlite_store

        return sqlite_store.replace_channels(channels)
    now = utc_now()
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {SCHEMA}.communication_channels")
            for channel in channels:
                cid = str(channel.get("id") or "")
                if not cid:
                    continue
                cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.communication_channels
                      (id, label, type, connector, org, enabled, status, payload, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        cid,
                        str(channel.get("label") or cid),
                        channel.get("type"),
                        channel.get("connector"),
                        channel.get("org"),
                        bool(channel.get("enabled", True)),
                        channel.get("status"),
                        _jsonb(channel),
                        now,
                    ),
                )


def load_channels() -> list[dict[str, Any]]:
    if not resolve_postgres_dsn():
        from zab.services import local_db as sqlite_store

        return sqlite_store.load_channels()
    with _connect(migrate=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT payload FROM {SCHEMA}.communication_channels ORDER BY org, label")
            rows = cur.fetchall()
    return [_json_loads(r["payload"], {}) for r in rows]


def replace_dashboard_actions(actions: list[dict[str, Any]]) -> None:
    if not resolve_postgres_dsn():
        from zab.services import local_db as sqlite_store

        return sqlite_store.replace_dashboard_actions(actions)
    now = utc_now()
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {SCHEMA}.dashboard_actions")
            for action in actions:
                aid = str(action.get("id") or "")
                if not aid:
                    continue
                cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.dashboard_actions (id, channel_id, status, payload, updated_at)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (aid, action.get("channel_id"), action.get("status"), _jsonb(action), now),
                )


def load_dashboard_actions() -> list[dict[str, Any]]:
    if not resolve_postgres_dsn():
        from zab.services import local_db as sqlite_store

        return sqlite_store.load_dashboard_actions()
    with _connect(migrate=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT payload FROM {SCHEMA}.dashboard_actions ORDER BY updated_at DESC, id")
            rows = cur.fetchall()
    return [_json_loads(r["payload"], {}) for r in rows]


def get_dashboard_action(action_id: str) -> dict[str, Any] | None:
    if not resolve_postgres_dsn():
        from zab.services import local_db as sqlite_store

        return sqlite_store.get_dashboard_action(action_id)
    with _connect(migrate=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT payload FROM {SCHEMA}.dashboard_actions WHERE id = %s", (action_id,))
            row = cur.fetchone()
    if not row:
        return None
    payload = _json_loads(row["payload"], {})
    return payload if isinstance(payload, dict) else None


def update_dashboard_action(action_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    if not resolve_postgres_dsn():
        from zab.services import local_db as sqlite_store

        return sqlite_store.update_dashboard_action(action_id, patch)
    current = get_dashboard_action(action_id)
    if current is None:
        return None
    updated = {**current, **patch}
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {SCHEMA}.dashboard_actions
                SET status = %s, payload = %s, updated_at = %s
                WHERE id = %s
                """,
                (updated.get("status"), _jsonb(updated), utc_now(), action_id),
            )
    return updated


def save_request_event(event: dict[str, Any]) -> None:
    if not resolve_postgres_dsn():
        from zab.services import local_db as sqlite_store

        return sqlite_store.save_request_event(event)
    actor = event.get("actor") if isinstance(event.get("actor"), dict) else {}
    scope = event.get("scope") if isinstance(event.get("scope"), dict) else {}
    request = event.get("request") if isinstance(event.get("request"), dict) else {}
    result = event.get("result") if isinstance(event.get("result"), dict) else {}
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {SCHEMA}.request_events
                  (event_id, ts, level, component, surface, request_id, actor_id, actor_kind,
                   org, project_id, project_path, task_source_id, request_name, status,
                   duration_ms, http_status, exit_code, payload)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (event_id) DO UPDATE SET
                  ts = EXCLUDED.ts,
                  level = EXCLUDED.level,
                  component = EXCLUDED.component,
                  surface = EXCLUDED.surface,
                  request_id = EXCLUDED.request_id,
                  actor_id = EXCLUDED.actor_id,
                  actor_kind = EXCLUDED.actor_kind,
                  org = EXCLUDED.org,
                  project_id = EXCLUDED.project_id,
                  project_path = EXCLUDED.project_path,
                  task_source_id = EXCLUDED.task_source_id,
                  request_name = EXCLUDED.request_name,
                  status = EXCLUDED.status,
                  duration_ms = EXCLUDED.duration_ms,
                  http_status = EXCLUDED.http_status,
                  exit_code = EXCLUDED.exit_code,
                  payload = EXCLUDED.payload
                """,
                (
                    str(event.get("event_id") or ""),
                    event.get("ts") or utc_now(),
                    str(event.get("level") or "INFO"),
                    event.get("component"),
                    event.get("surface"),
                    event.get("request_id"),
                    actor.get("id"),
                    actor.get("kind"),
                    scope.get("org"),
                    scope.get("project_id"),
                    scope.get("project_path"),
                    scope.get("task_source_id"),
                    request.get("name") or request.get("path") or request.get("tool") or request.get("command"),
                    result.get("status"),
                    _int_or_none(result.get("duration_ms")),
                    _int_or_none(result.get("http_status")),
                    _int_or_none(result.get("exit_code")),
                    _jsonb(event),
                ),
            )


def query_request_events(filters: dict[str, Any] | None = None, *, limit: int = 100) -> list[dict[str, Any]]:
    if not resolve_postgres_dsn():
        from zab.services import local_db as sqlite_store

        return sqlite_store.query_request_events(filters, limit=limit)
    filters = filters or {}
    capped = max(1, min(1000, int(limit)))
    where: list[str] = []
    params: list[Any] = []
    for key, column in (
        ("surface", "surface"),
        ("component", "component"),
        ("actor", "actor_id"),
        ("org", "org"),
        ("project", "project_id"),
        ("status", "status"),
    ):
        value = filters.get(key)
        if value not in (None, ""):
            where.append(f"LOWER(COALESCE({column}, '')) LIKE %s")
            params.append(f"%{str(value).lower()}%")
    since = _since_to_iso(filters.get("since"))
    if since:
        where.append("ts >= %s")
        params.append(since)
    q = str(filters.get("q") or "").strip()
    if q:
        where.append("LOWER(payload::text) LIKE %s")
        params.append(f"%{q.lower()}%")
    level = filters.get("level")
    if level:
        ranks = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
        allowed = [name for name, rank in ranks.items() if rank >= ranks.get(str(level).upper(), 20)]
        where.append("level = ANY(%s)")
        params.append(allowed)
    sql_where = " AND ".join(where) if where else "true"
    params.append(capped)
    with _connect(migrate=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT payload
                FROM {SCHEMA}.request_events
                WHERE {sql_where}
                ORDER BY ts DESC
                LIMIT %s
                """,
                tuple(params),
            )
            rows = cur.fetchall()
    return [_json_loads(r["payload"], {}) for r in rows]


def export_database(*, fmt: str = "json") -> str:
    if not resolve_postgres_dsn():
        from zab.services import local_db as sqlite_store

        return sqlite_store.export_database(fmt=fmt)
    payload = {
        "meta": {
            "exported_at": utc_now(),
            "database": "postgres",
            "schema": SCHEMA,
            "schema_version": status().get("schema_version"),
        },
        "sync_meta": _dump_table("sync_meta"),
        "state_sections": _dump_table("state_sections"),
        "skills_registry": _dump_table("skills_registry"),
        "mcp_registry": _dump_table("mcp_registry"),
        "tasks_sources": _dump_table("tasks_sources"),
        "tasks_items": _dump_table("tasks_items"),
        "crons": _dump_table("crons"),
        "cron_runs": _dump_table("cron_runs"),
        "communication_channels": _dump_table("communication_channels"),
        "dashboard_actions": _dump_table("dashboard_actions"),
        "request_events": _dump_table("request_events"),
    }
    if fmt == "yaml":
        return yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n"


def _dump_table(name: str) -> list[dict[str, Any]]:
    with _connect(migrate=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM {SCHEMA}.{name}")
            rows = cur.fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        clean = dict(row)
        clean.pop("tsv", None)
        out.append(_json_safe(clean))
    return out


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _since_to_iso(raw: Any) -> str | None:
    if raw in (None, ""):
        return None
    text = str(raw).strip().lower()
    if text.endswith(("s", "m", "h", "d")) and text[:-1].isdigit():
        value = int(text[:-1])
        unit = text[-1]
        delta = {
            "s": 1,
            "m": 60,
            "h": 3600,
            "d": 86400,
        }[unit]
        return (datetime.now(timezone.utc) - timedelta(seconds=value * delta)).isoformat()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()
    except ValueError:
        return None


def import_legacy() -> dict[str, Any]:
    result: dict[str, Any] = {"imported": {}, "errors": []}
    migrate_schema()
    _import_legacy_sqlite(result)
    _import_legacy_files(result)
    _import_legacy_ledger(result)
    return result


def _import_legacy_ledger(result: dict[str, Any]) -> None:
    """Reprend aussi le Conversation Ledger, que la reprise oubliait.

    L'import local ne connaissait que les registres et l'état ; les tables
    `ledger_*` restaient dans le SQLite, invisibles du magasin canonique.
    """
    from zab.services import ledger_db  # importé ici : ledger_db dépend de ce module

    try:
        rapport = ledger_db.import_sqlite(apply=True)
    except Exception as souci:
        result["errors"].append({"source": "ledger", "error": str(souci)})
        return
    for table, detail in (rapport.get("tables") or {}).items():
        result["imported"][table] = detail.get("importees", 0)


def _import_legacy_sqlite(result: dict[str, Any]) -> None:
    db = data_dir() / "zab.db"
    if not db.is_file():
        return
    try:
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        result["errors"].append({"source": "sqlite", "error": str(exc)})
        return
    try:
        def rows(table: str) -> list[sqlite3.Row]:
            try:
                return conn.execute(f"SELECT * FROM {table}").fetchall()
            except sqlite3.Error:
                return []

        sources = [_json_loads(r["payload_json"], {}) for r in rows("tasks_sources")]
        tasks = [_json_loads(r["payload_json"], {}) for r in rows("tasks_items")]
        if sources or tasks:
            replace_tasks_cache({"sources": sources, "all_tasks": tasks})
            result["imported"]["sqlite.tasks"] = len(tasks)

        mcp_rows = rows("mcp_registry")
        if mcp_rows:
            save_mcp_registry_document({"version": 1, "servers": {r["slug"]: _json_loads(r["payload_json"], {}) for r in mcp_rows}})
            result["imported"]["sqlite.mcp_registry"] = len(mcp_rows)

        skill_rows = rows("skills_registry")
        if skill_rows:
            save_skills_registry_document({"version": 1, "skills": [_json_loads(r["payload_json"], {}) for r in skill_rows]})
            result["imported"]["sqlite.skills_registry"] = len(skill_rows)

        cron_rows = rows("crons")
        if cron_rows:
            replace_crons([_json_loads(r["payload_json"], {}) for r in cron_rows])
            result["imported"]["sqlite.crons"] = len(cron_rows)

        channel_rows = rows("communication_channels")
        if channel_rows:
            replace_channels([_json_loads(r["payload_json"], {}) for r in channel_rows])
            result["imported"]["sqlite.communication_channels"] = len(channel_rows)

        action_rows = rows("dashboard_actions")
        if action_rows:
            replace_dashboard_actions([_json_loads(r["payload_json"], {}) for r in action_rows])
            result["imported"]["sqlite.dashboard_actions"] = len(action_rows)

        state_rows = rows("state_sections")
        if state_rows:
            state: dict[str, Any] = {}
            try:
                root_row = conn.execute("SELECT value_json FROM sync_meta WHERE key = 'state.root'").fetchone()
                root = _json_loads(root_row["value_json"], {}) if root_row else {}
                if isinstance(root, dict):
                    state.update(root)
            except sqlite3.Error:
                pass
            for r in state_rows:
                state.setdefault(str(r["section"]), {})
                state[str(r["section"])][str(r["item_key"])] = _json_loads(r["payload_json"], {})
            replace_state(state)
            result["imported"]["sqlite.state_sections"] = len(state_rows)
    finally:
        conn.close()


def _import_legacy_files(result: dict[str, Any]) -> None:
    from zab.services import mcp_registry, skills_registry

    try:
        p = data_dir() / "tasks_cache.json"
        if p.is_file() and load_tasks_cache() is None:
            replace_tasks_cache(json.loads(p.read_text(encoding="utf-8")))
            result["imported"]["tasks_cache"] = str(p)
    except Exception as exc:
        result["errors"].append({"source": "tasks_cache", "error": str(exc)})

    try:
        doc = mcp_registry.load_registry_document(prefer_db=False)
        if doc.get("servers") and not load_mcp_registry_document({}).get("servers"):
            save_mcp_registry_document(doc)
            result["imported"]["mcp_registry"] = str(mcp_registry.registry_path())
    except Exception as exc:
        result["errors"].append({"source": "mcp_registry", "error": str(exc)})

    try:
        doc = skills_registry.load_registry_document(prefer_db=False)
        if doc.get("skills") and not load_skills_registry_document({}).get("skills"):
            save_skills_registry_document(doc)
            result["imported"]["skills_registry"] = str(skills_registry.registry_path())
    except Exception as exc:
        result["errors"].append({"source": "skills_registry", "error": str(exc)})

    try:
        p = config_dir() / "crons-registry.json"
        if p.is_file() and not load_crons():
            doc = json.loads(p.read_text(encoding="utf-8"))
            crons = doc.get("crons") if isinstance(doc, dict) else None
            if isinstance(crons, list):
                replace_crons([x for x in crons if isinstance(x, dict)])
                result["imported"]["crons_registry"] = str(p)
    except Exception as exc:
        result["errors"].append({"source": "crons_registry", "error": str(exc)})

    try:
        p = data_dir() / "state.yaml"
        if p.is_file() and not has_state():
            state = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            if isinstance(state, dict):
                replace_state(state)
                result["imported"]["state"] = str(p)
    except Exception as exc:
        result["errors"].append({"source": "state", "error": str(exc)})


def _upsert_search_index(cur: Any, section: str, item_key: str, payload: dict[str, Any]) -> None:
    title = str(
        payload.get("display_name")
        or payload.get("name")
        or payload.get("id")
        or payload.get("title")
        or item_key
    )
    body = _flatten_for_search({"key": item_key, **payload})
    cur.execute(
        f"""
        INSERT INTO {SCHEMA}.search_index (section, item_key, title, body, payload)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (section, item_key, title, body, _jsonb(payload)),
    )


def _flatten_for_search(value: Any) -> str:
    parts: list[str] = []
    if isinstance(value, dict):
        for k, v in value.items():
            parts.append(str(k))
            parts.append(_flatten_for_search(v))
    elif isinstance(value, list):
        for item in value:
            parts.append(_flatten_for_search(item))
    elif isinstance(value, (str, int, float, bool)):
        parts.append(str(value))
    return " ".join(p for p in parts if p)
