"""SQLite local-first store for Zab generated state and registries."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import yaml

from zab.paths import config_dir, data_dir

SCHEMA_VERSION = 4
DEFAULT_FILENAME = "zab.db"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def database_path() -> Path:
    raw = os.environ.get("ZAB_LOCAL_DATABASE_PATH", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (data_dir() / DEFAULT_FILENAME).resolve()


def _json_dumps(value: Any) -> str:
    return json.dumps(_json_safe(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


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


def _json_loads(value: str | bytes | None, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        return default


def connect(*, migrate: bool = True) -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = _open_with_lock_retry(path)
    if migrate:
        migrate_schema(conn)
    return conn


def _open_with_lock_retry(
    path: Path, *, attempts: int = 8, initial_delay: float = 0.05
) -> sqlite3.Connection:
    """Open a connection, retrying a transient "database is locked" at the
    Python level.

    `PRAGMA busy_timeout` does not cover this: switching journal_mode to WAL
    needs an exclusive lock, and SQLite does not run the busy handler for
    that specific pragma — it returns SQLITE_BUSY immediately instead of
    waiting, even with busy_timeout set. In practice this only bites the
    first connection(s) to ever open a given database file (later
    connections find it already in WAL mode and the pragma is a no-op), but
    concurrent processes racing that first conversion hit it for real, as CI
    did here.
    """
    delay = initial_delay
    last_exc: sqlite3.OperationalError | None = None
    for _ in range(attempts):
        try:
            conn = sqlite3.connect(str(path))
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout = 5000")
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            return conn
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower():
                raise
            last_exc = exc
            time.sleep(delay)
            delay = min(delay * 2, 0.5)
    assert last_exc is not None
    raise last_exc


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    conn = connect(migrate=True)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def migrate_schema(conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    if conn is None:
        conn = connect(migrate=False)
    try:
        current = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if current < 1:
            _migrate_v1(conn)
        if current < 2:
            _migrate_v2(conn)
        if current < 3:
            _migrate_v3(conn)
        if current < 4:
            _migrate_v4(conn)
        if current < SCHEMA_VERSION:
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
        return {"path": str(database_path()), "schema_version": schema_version(conn), "created": current == 0}
    finally:
        if own_conn:
            conn.close()


def _migrate_v1(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sync_meta (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS state_sections (
            section TEXT NOT NULL,
            item_key TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (section, item_key)
        );

        CREATE TABLE IF NOT EXISTS skills_registry (
            key TEXT PRIMARY KEY,
            org TEXT NOT NULL,
            slug TEXT NOT NULL,
            status TEXT NOT NULL,
            canonical_path TEXT,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_skills_registry_status ON skills_registry(status);
        CREATE INDEX IF NOT EXISTS idx_skills_registry_org ON skills_registry(org);

        CREATE TABLE IF NOT EXISTS mcp_registry (
            slug TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            fingerprint TEXT,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_mcp_registry_status ON mcp_registry(status);

        CREATE TABLE IF NOT EXISTS tasks_sources (
            id TEXT PRIMARY KEY,
            status TEXT,
            backend TEXT,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tasks_items (
            source_id TEXT NOT NULL,
            identifier TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT,
            state TEXT,
            updated_at_remote TEXT,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (source_id, identifier)
        );
        CREATE INDEX IF NOT EXISTS idx_tasks_items_updated ON tasks_items(updated_at_remote DESC);

        CREATE TABLE IF NOT EXISTS crons (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            source TEXT NOT NULL,
            schedule TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            status TEXT,
            last_run TEXT,
            next_run TEXT,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS cron_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cron_id TEXT NOT NULL,
            status TEXT NOT NULL,
            content TEXT NOT NULL,
            stdout TEXT,
            stderr TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_cron_runs_cron_created ON cron_runs(cron_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS communication_channels (
            id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            type TEXT,
            connector TEXT,
            org TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            status TEXT,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS dashboard_actions (
            id TEXT PRIMARY KEY,
            channel_id TEXT,
            status TEXT,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
                section,
                item_key,
                title,
                body,
                payload_json,
                tokenize='unicode61'
            )
            """
        )
    except sqlite3.DatabaseError:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS search_index (
                section TEXT NOT NULL,
                item_key TEXT NOT NULL,
                title TEXT,
                body TEXT,
                payload_json TEXT,
                PRIMARY KEY (section, item_key)
            )
            """
        )


def _migrate_v2(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS request_events (
            event_id TEXT PRIMARY KEY,
            ts TEXT NOT NULL,
            level TEXT NOT NULL,
            component TEXT,
            surface TEXT,
            request_id TEXT,
            actor_id TEXT,
            actor_kind TEXT,
            org TEXT,
            project_id TEXT,
            project_path TEXT,
            task_source_id TEXT,
            request_name TEXT,
            status TEXT,
            duration_ms INTEGER,
            http_status INTEGER,
            exit_code INTEGER,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_request_events_ts ON request_events(ts DESC);
        CREATE INDEX IF NOT EXISTS idx_request_events_surface ON request_events(surface);
        CREATE INDEX IF NOT EXISTS idx_request_events_component ON request_events(component);
        CREATE INDEX IF NOT EXISTS idx_request_events_actor ON request_events(actor_id);
        CREATE INDEX IF NOT EXISTS idx_request_events_org ON request_events(org);
        CREATE INDEX IF NOT EXISTS idx_request_events_project ON request_events(project_id);
        CREATE INDEX IF NOT EXISTS idx_request_events_status ON request_events(status);
        """
    )


def _migrate_v3(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS ledger_events (
            event_id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            native_id TEXT NOT NULL,
            channel_id TEXT,
            timestamp TEXT,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(source, native_id)
        );
        CREATE INDEX IF NOT EXISTS idx_ledger_events_timestamp ON ledger_events(timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_ledger_events_channel ON ledger_events(channel_id);

        CREATE TABLE IF NOT EXISTS ledger_workpackets (
            workpacket_id TEXT PRIMARY KEY,
            display_id TEXT UNIQUE,
            state TEXT,
            organization_id TEXT,
            client_workstream_id TEXT,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ledger_workpackets_state ON ledger_workpackets(state);
        CREATE INDEX IF NOT EXISTS idx_ledger_workpackets_org ON ledger_workpackets(organization_id);

        CREATE TABLE IF NOT EXISTS ledger_projection_states (
            workpacket_id TEXT NOT NULL,
            target TEXT NOT NULL,
            status TEXT,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (workpacket_id, target)
        );
        CREATE INDEX IF NOT EXISTS idx_ledger_projection_status ON ledger_projection_states(status);
        """
    )


def _migrate_v4(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS ledger_organizations (
            organization_id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ledger_workstreams (
            client_workstream_id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            label TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ledger_workstreams_org ON ledger_workstreams(organization_id);
        """
    )


def schema_version(conn: sqlite3.Connection | None = None) -> int:
    own_conn = conn is None
    if conn is None:
        conn = sqlite3.connect(str(database_path()))
    try:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        if own_conn:
            conn.close()


def status() -> dict[str, Any]:
    path = database_path()
    payload: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "schema_version": 0,
        "target_schema_version": SCHEMA_VERSION,
        "ok": False,
        "tables": {},
        "error": None,
    }
    try:
        with connect(migrate=True) as conn:
            payload["schema_version"] = schema_version(conn)
            payload["ok"] = True
            tables = [
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
            ]
            payload["tables"] = {
                name: int(conn.execute(f"SELECT count(*) FROM {name}").fetchone()[0])
                for name in tables
            }
    except sqlite3.DatabaseError as exc:
        payload["error"] = f"{type(exc).__name__}: {str(exc).splitlines()[0][:240]}"
    return payload


def vacuum() -> dict[str, Any]:
    with connect(migrate=True) as conn:
        conn.execute("VACUUM")
    return status()


def set_meta(key: str, value: Any, conn: sqlite3.Connection | None = None) -> None:
    own_conn = conn is None
    if conn is None:
        conn = connect(migrate=True)
    try:
        conn.execute(
            """
            INSERT INTO sync_meta (key, value_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
              value_json = excluded.value_json,
              updated_at = excluded.updated_at
            """,
            (key, _json_dumps(value), utc_now()),
        )
        if own_conn:
            conn.commit()
    finally:
        if own_conn:
            conn.close()


def get_meta(key: str, default: Any = None) -> Any:
    with connect(migrate=True) as conn:
        row = conn.execute("SELECT value_json FROM sync_meta WHERE key = ?", (key,)).fetchone()
    return _json_loads(row["value_json"], default) if row else default


def replace_state(state: dict[str, Any]) -> None:
    now = utc_now()
    with transaction() as conn:
        conn.execute("DELETE FROM state_sections")
        _clear_search_index(conn)
        for section, value in state.items():
            if not isinstance(value, dict):
                set_meta(f"state.{section}", value, conn)
                continue
            for item_key, payload in value.items():
                if not isinstance(payload, dict):
                    payload = {"value": payload}
                payload_json = _json_dumps(payload)
                conn.execute(
                    """
                    INSERT INTO state_sections (section, item_key, payload_json, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (section, str(item_key), payload_json, now),
                )
                _upsert_search_index(conn, section, str(item_key), payload, payload_json)
        set_meta(
            "state.root",
            {k: v for k, v in state.items() if not isinstance(v, dict)},
            conn,
        )


def load_state() -> dict[str, Any]:
    with connect(migrate=True) as conn:
        root = get_meta("state.root", {})
        rows = conn.execute(
            "SELECT section, item_key, payload_json FROM state_sections ORDER BY section, item_key"
        ).fetchall()
    state = root if isinstance(root, dict) else {}
    for row in rows:
        section = str(row["section"])
        state.setdefault(section, {})
        state[section][str(row["item_key"])] = _json_loads(row["payload_json"], {})
    return state


def has_state() -> bool:
    with connect(migrate=True) as conn:
        row = conn.execute("SELECT 1 FROM state_sections LIMIT 1").fetchone()
    return row is not None


def list_state_section(section: str) -> list[dict[str, Any]]:
    with connect(migrate=True) as conn:
        rows = conn.execute(
            "SELECT item_key, payload_json FROM state_sections WHERE section = ? ORDER BY item_key",
            (section,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        payload = _json_loads(row["payload_json"], {})
        if isinstance(payload, dict):
            out.append({"key": str(row["item_key"]), **payload})
    return out


def get_state_item(section: str, key: str) -> dict[str, Any] | None:
    with connect(migrate=True) as conn:
        row = conn.execute(
            "SELECT item_key, payload_json FROM state_sections WHERE section = ? AND item_key = ?",
            (section, key),
        ).fetchone()
        if row is None:
            rows = conn.execute(
                "SELECT item_key, payload_json FROM state_sections WHERE section = ?",
                (section,),
            ).fetchall()
        else:
            rows = [row]
    for item in rows:
        payload = _json_loads(item["payload_json"], {})
        if not isinstance(payload, dict):
            continue
        if str(item["item_key"]) == key or str(payload.get("id") or "").lower() == key.lower():
            return {"key": str(item["item_key"]), **payload}
    return None


def upsert_state_item(section: str, key: str, payload: dict[str, Any]) -> None:
    """Met à jour un seul item de l'index local (state + search) sans reconstruire tout l'état.

    Utile après une édition unitaire (ex: annotation d'un tool) pour que le chemin
    rapide de lecture reflète immédiatement le changement, sans ``zab sync`` complet."""

    if not has_state():
        return
    now = utc_now()
    payload = payload if isinstance(payload, dict) else {"value": payload}
    payload_json = _json_dumps(payload)
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO state_sections (section, item_key, payload_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(section, item_key)
            DO UPDATE SET payload_json = excluded.payload_json, updated_at = excluded.updated_at
            """,
            (section, str(key), payload_json, now),
        )
        conn.execute(
            "DELETE FROM search_index WHERE section = ? AND item_key = ?",
            (section, str(key)),
        )
        _upsert_search_index(conn, section, str(key), payload, payload_json)


def search_state(query: str, *, sections: list[str] | None = None, limit: int = 20) -> list[dict[str, Any]]:
    terms = [t for t in query.strip().split() if t]
    capped = max(1, min(100, int(limit)))
    with connect(migrate=True) as conn:
        fts = _search_index_is_fts(conn)
        if fts and terms:
            match = " OR ".join(t.replace('"', '""') for t in terms)
            params: list[Any] = [match]
            where = "search_index MATCH ?"
            if sections:
                where += f" AND section IN ({','.join('?' for _ in sections)})"
                params.extend(sections)
            params.append(capped)
            try:
                rows = conn.execute(
                    f"""
                    SELECT section, item_key, payload_json, bm25(search_index) AS rank
                    FROM search_index
                    WHERE {where}
                    ORDER BY rank
                    LIMIT ?
                    """,
                    params,
                ).fetchall()
                return [_row_to_search_result(r) for r in rows]
            except sqlite3.DatabaseError:
                pass
        rows = conn.execute(
            "SELECT section, item_key, payload_json, body FROM search_index"
        ).fetchall()
    lowered = [t.lower() for t in terms]
    out: list[dict[str, Any]] = []
    for row in rows:
        if sections and row["section"] not in sections:
            continue
        body = str(row["body"] or "").lower()
        if lowered and not any(t in body for t in lowered):
            continue
        out.append(_row_to_search_result(row))
    return out[:capped]


def _row_to_search_result(row: sqlite3.Row) -> dict[str, Any]:
    payload = _json_loads(row["payload_json"], {})
    if not isinstance(payload, dict):
        payload = {}
    return {"section": str(row["section"]), "key": str(row["item_key"]), **payload}


def replace_tasks_cache(payload: dict[str, Any]) -> None:
    now = utc_now()
    sources = [x for x in payload.get("sources") or [] if isinstance(x, dict)]
    tasks = [x for x in payload.get("all_tasks") or [] if isinstance(x, dict)]
    with transaction() as conn:
        conn.execute("DELETE FROM tasks_sources")
        conn.execute("DELETE FROM tasks_items")
        for src in sources:
            sid = str(src.get("id") or src.get("label") or src.get("source_label") or "unknown")
            conn.execute(
                """
                INSERT INTO tasks_sources (id, status, backend, payload_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (sid, src.get("status"), src.get("backend") or src.get("type"), _json_dumps(src), now),
            )
        for item in tasks:
            source_id = str(item.get("source_id") or item.get("source_label") or "unknown")
            identifier = str(item.get("identifier") or item.get("url") or item.get("title") or "unknown")
            conn.execute(
                """
                INSERT INTO tasks_items
                  (source_id, identifier, title, url, state, updated_at_remote, payload_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id, identifier) DO UPDATE SET
                  title = excluded.title,
                  url = excluded.url,
                  state = excluded.state,
                  updated_at_remote = excluded.updated_at_remote,
                  payload_json = excluded.payload_json,
                  updated_at = excluded.updated_at
                """,
                (
                    source_id,
                    identifier,
                    str(item.get("title") or ""),
                    item.get("url"),
                    item.get("state"),
                    item.get("updated_at"),
                    _json_dumps(item),
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
    with connect(migrate=True) as conn:
        source_rows = conn.execute("SELECT payload_json FROM tasks_sources ORDER BY id").fetchall()
        task_rows = conn.execute(
            "SELECT payload_json FROM tasks_items ORDER BY updated_at_remote DESC, identifier"
        ).fetchall()
    if not source_rows and not task_rows:
        return None
    meta = get_meta("tasks.cache", {})
    return {
        "generated_at_utc": meta.get("generated_at_utc") if isinstance(meta, dict) else None,
        "parse_errors": meta.get("parse_errors", []) if isinstance(meta, dict) else [],
        "env_hints": meta.get("env_hints", {}) if isinstance(meta, dict) else {},
        "sources": [_json_loads(r["payload_json"], {}) for r in source_rows],
        "all_tasks": [_json_loads(r["payload_json"], {}) for r in task_rows],
        "total_count": len(task_rows),
    }


def save_mcp_registry_document(doc: dict[str, Any]) -> None:
    now = utc_now()
    servers = doc.get("servers") if isinstance(doc.get("servers"), dict) else {}
    with transaction() as conn:
        conn.execute("DELETE FROM mcp_registry")
        for slug, raw in servers.items():
            payload = raw if isinstance(raw, dict) else {}
            conn.execute(
                """
                INSERT INTO mcp_registry (slug, status, fingerprint, payload_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(slug),
                    str(payload.get("status") or "detected"),
                    payload.get("fingerprint"),
                    _json_dumps(payload),
                    now,
                ),
            )
        set_meta("mcp_registry.document", {k: v for k, v in doc.items() if k != "servers"}, conn)


def load_mcp_registry_document(default: dict[str, Any]) -> dict[str, Any]:
    with connect(migrate=True) as conn:
        rows = conn.execute("SELECT slug, payload_json FROM mcp_registry ORDER BY slug").fetchall()
    if not rows:
        return default
    meta = get_meta("mcp_registry.document", {})
    doc = meta if isinstance(meta, dict) else {}
    doc["servers"] = {str(r["slug"]): _json_loads(r["payload_json"], {}) for r in rows}
    return doc


def save_skills_registry_document(doc: dict[str, Any]) -> None:
    now = utc_now()
    skills = [x for x in doc.get("skills") or [] if isinstance(x, dict)]
    with transaction() as conn:
        conn.execute("DELETE FROM skills_registry")
        for skill in skills:
            key = str(skill.get("key") or "")
            if not key:
                continue
            conn.execute(
                """
                INSERT INTO skills_registry
                  (key, org, slug, status, canonical_path, payload_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    key,
                    str(skill.get("org") or "hors-org"),
                    str(skill.get("slug") or "unknown"),
                    str(skill.get("status") or "candidate"),
                    skill.get("canonical_path"),
                    _json_dumps(skill),
                    now,
                ),
            )
        set_meta("skills_registry.document", {k: v for k, v in doc.items() if k != "skills"}, conn)


def load_skills_registry_document(default: dict[str, Any]) -> dict[str, Any]:
    with connect(migrate=True) as conn:
        rows = conn.execute("SELECT payload_json FROM skills_registry ORDER BY key").fetchall()
    if not rows:
        return default
    meta = get_meta("skills_registry.document", {})
    doc = meta if isinstance(meta, dict) else {}
    doc["skills"] = [_json_loads(r["payload_json"], {}) for r in rows]
    return doc


def replace_crons(crons: list[dict[str, Any]]) -> None:
    now = utc_now()
    with transaction() as conn:
        conn.execute("DELETE FROM crons")
        for cron in crons:
            cid = str(cron.get("id") or "")
            if not cid:
                continue
            conn.execute(
                """
                INSERT INTO crons
                  (id, name, source, schedule, enabled, status, last_run, next_run, payload_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cid,
                    str(cron.get("name") or cid),
                    str(cron.get("source") or "unknown"),
                    cron.get("schedule"),
                    1 if cron.get("enabled", True) else 0,
                    cron.get("status"),
                    cron.get("last_run"),
                    cron.get("next_run"),
                    _json_dumps(cron),
                    now,
                ),
            )


def load_crons() -> list[dict[str, Any]]:
    with connect(migrate=True) as conn:
        rows = conn.execute("SELECT payload_json FROM crons ORDER BY source, name").fetchall()
    return [_json_loads(r["payload_json"], {}) for r in rows]


def save_cron_run(cron_id: str, status_value: str, content: str, stdout: str | None = None, stderr: str | None = None) -> None:
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO cron_runs (cron_id, status, content, stdout, stderr, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (cron_id, status_value, content, stdout, stderr, utc_now()),
        )


def load_cron_runs(cron_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
    with connect(migrate=True) as conn:
        rows = conn.execute(
            """
            SELECT created_at, status, content, stdout, stderr
            FROM cron_runs
            WHERE cron_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (cron_id, max(1, min(200, limit))),
        ).fetchall()
    return [
        {
            "timestamp": r["created_at"],
            "status": r["status"],
            "content": r["content"],
            "stdout": r["stdout"],
            "stderr": r["stderr"],
        }
        for r in rows
    ]


def replace_channels(channels: list[dict[str, Any]]) -> None:
    now = utc_now()
    with transaction() as conn:
        conn.execute("DELETE FROM communication_channels")
        for channel in channels:
            cid = str(channel.get("id") or "")
            if not cid:
                continue
            conn.execute(
                """
                INSERT INTO communication_channels
                  (id, label, type, connector, org, enabled, status, payload_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cid,
                    str(channel.get("label") or cid),
                    channel.get("type"),
                    channel.get("connector"),
                    channel.get("org"),
                    1 if channel.get("enabled", True) else 0,
                    channel.get("status"),
                    _json_dumps(channel),
                    now,
                ),
            )


def load_channels() -> list[dict[str, Any]]:
    with connect(migrate=True) as conn:
        rows = conn.execute("SELECT payload_json FROM communication_channels ORDER BY org, label").fetchall()
    return [_json_loads(r["payload_json"], {}) for r in rows]


def replace_dashboard_actions(actions: list[dict[str, Any]]) -> None:
    now = utc_now()
    with transaction() as conn:
        conn.execute("DELETE FROM dashboard_actions")
        for action in actions:
            aid = str(action.get("id") or "")
            if not aid:
                continue
            conn.execute(
                """
                INSERT INTO dashboard_actions (id, channel_id, status, payload_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    aid,
                    action.get("channel_id"),
                    action.get("status"),
                    _json_dumps(action),
                    now,
                ),
            )


def load_dashboard_actions() -> list[dict[str, Any]]:
    with connect(migrate=True) as conn:
        rows = conn.execute("SELECT payload_json FROM dashboard_actions ORDER BY updated_at DESC, id").fetchall()
    return [_json_loads(r["payload_json"], {}) for r in rows]


def get_dashboard_action(action_id: str) -> dict[str, Any] | None:
    with connect(migrate=True) as conn:
        row = conn.execute(
            "SELECT payload_json FROM dashboard_actions WHERE id = ?",
            (action_id,),
        ).fetchone()
    if not row:
        return None
    payload = _json_loads(row["payload_json"], {})
    return payload if isinstance(payload, dict) else None


def update_dashboard_action(action_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    current = get_dashboard_action(action_id)
    if current is None:
        return None
    updated = {**current, **patch}
    with transaction() as conn:
        conn.execute(
            """
            UPDATE dashboard_actions
            SET status = ?, payload_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (updated.get("status"), _json_dumps(updated), utc_now(), action_id),
        )
    return updated


def save_request_event(event: dict[str, Any]) -> None:
    actor = event.get("actor") if isinstance(event.get("actor"), dict) else {}
    scope = event.get("scope") if isinstance(event.get("scope"), dict) else {}
    request = event.get("request") if isinstance(event.get("request"), dict) else {}
    result = event.get("result") if isinstance(event.get("result"), dict) else {}
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO request_events
              (event_id, ts, level, component, surface, request_id, actor_id, actor_kind,
               org, project_id, project_path, task_source_id, request_name, status,
               duration_ms, http_status, exit_code, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
              ts = excluded.ts,
              level = excluded.level,
              component = excluded.component,
              surface = excluded.surface,
              request_id = excluded.request_id,
              actor_id = excluded.actor_id,
              actor_kind = excluded.actor_kind,
              org = excluded.org,
              project_id = excluded.project_id,
              project_path = excluded.project_path,
              task_source_id = excluded.task_source_id,
              request_name = excluded.request_name,
              status = excluded.status,
              duration_ms = excluded.duration_ms,
              http_status = excluded.http_status,
              exit_code = excluded.exit_code,
              payload_json = excluded.payload_json
            """,
            (
                str(event.get("event_id") or ""),
                str(event.get("ts") or utc_now()),
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
                _json_dumps(event),
            ),
        )


def query_request_events(filters: dict[str, Any] | None = None, *, limit: int = 100) -> list[dict[str, Any]]:
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
            where.append(f"LOWER(COALESCE({column}, '')) LIKE ?")
            params.append(f"%{str(value).lower()}%")
    since = _since_to_iso(filters.get("since"))
    if since:
        where.append("ts >= ?")
        params.append(since)
    q = str(filters.get("q") or "").strip()
    if q:
        where.append("LOWER(payload_json) LIKE ?")
        params.append(f"%{q.lower()}%")
    sql_where = " AND ".join(where) if where else "1 = 1"
    params.append(capped * 5 if filters.get("level") else capped)
    with connect(migrate=True) as conn:
        rows = conn.execute(
            f"""
            SELECT payload_json
            FROM request_events
            WHERE {sql_where}
            ORDER BY ts DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    events = [_json_loads(r["payload_json"], {}) for r in rows]
    level = filters.get("level")
    if level:
        min_rank = _level_rank(str(level))
        events = [
            event for event in events
            if isinstance(event, dict) and _level_rank(str(event.get("level") or "INFO")) >= min_rank
        ]
    return [e for e in events if isinstance(e, dict)][:capped]


def export_database(*, fmt: str = "json") -> str:
    payload = {
        "meta": {
            "exported_at": utc_now(),
            "database_path": str(database_path()),
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
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _dump_table(name: str) -> list[dict[str, Any]]:
    with connect(migrate=True) as conn:
        rows = conn.execute(f"SELECT * FROM {name}").fetchall()
    return [dict(r) for r in rows]


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _level_rank(level: str) -> int:
    return {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}.get(level.upper(), 20)


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
    from zab.services import mcp_registry, skills_registry

    result: dict[str, Any] = {"imported": {}, "errors": []}
    try:
        p = data_dir() / "tasks_cache.json"
        if p.is_file():
            replace_tasks_cache(json.loads(p.read_text(encoding="utf-8")))
            result["imported"]["tasks_cache"] = str(p)
    except Exception as exc:
        result["errors"].append({"source": "tasks_cache", "error": str(exc)})

    try:
        doc = mcp_registry.load_registry_document(prefer_db=False)
        save_mcp_registry_document(doc)
        result["imported"]["mcp_registry"] = str(mcp_registry.registry_path())
    except Exception as exc:
        result["errors"].append({"source": "mcp_registry", "error": str(exc)})

    try:
        doc = skills_registry.load_registry_document(prefer_db=False)
        save_skills_registry_document(doc)
        result["imported"]["skills_registry"] = str(skills_registry.registry_path())
    except Exception as exc:
        result["errors"].append({"source": "skills_registry", "error": str(exc)})

    try:
        p = config_dir() / "crons-registry.json"
        if p.is_file():
            doc = json.loads(p.read_text(encoding="utf-8"))
            crons = doc.get("crons") if isinstance(doc, dict) else None
            if isinstance(crons, list):
                replace_crons([x for x in crons if isinstance(x, dict)])
                result["imported"]["crons_registry"] = str(p)
    except Exception as exc:
        result["errors"].append({"source": "crons_registry", "error": str(exc)})

    try:
        p = data_dir() / "state.yaml"
        if p.is_file():
            state = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            if isinstance(state, dict):
                replace_state(state)
                result["imported"]["state"] = str(p)
    except Exception as exc:
        result["errors"].append({"source": "state", "error": str(exc)})

    return result


def _clear_search_index(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM search_index")


def _upsert_search_index(
    conn: sqlite3.Connection,
    section: str,
    item_key: str,
    payload: dict[str, Any],
    payload_json: str,
) -> None:
    title = str(
        payload.get("display_name")
        or payload.get("name")
        or payload.get("id")
        or payload.get("title")
        or item_key
    )
    body = _flatten_for_search({"key": item_key, **payload})
    conn.execute(
        """
        INSERT INTO search_index (section, item_key, title, body, payload_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (section, item_key, title, body, payload_json),
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


def _search_index_is_fts(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'search_index' AND type = 'table'"
    ).fetchone()
    return bool(row and "VIRTUAL TABLE" in str(row["sql"]).upper() and "FTS5" in str(row["sql"]).upper())
