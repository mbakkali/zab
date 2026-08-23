import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from typer.testing import CliRunner

from zab.cli import app
from zab.services import local_db


def test_local_db_migrates_with_custom_path(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "custom" / "zab.sqlite"
    monkeypatch.setenv("ZAB_LOCAL_DATABASE_PATH", str(db))

    payload = local_db.migrate_schema()

    assert payload["schema_version"] == local_db.SCHEMA_VERSION
    assert db.is_file()
    with sqlite3.connect(str(db)) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "state_sections" in tables
    assert "tasks_items" in tables
    assert "skills_registry" in tables


def test_local_db_transaction_rolls_back(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ZAB_LOCAL_DATABASE_PATH", str(tmp_path / "zab.db"))
    try:
        with local_db.transaction() as conn:
            local_db.set_meta("demo", {"ok": True}, conn)
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    assert local_db.get_meta("demo") is None


def test_local_db_status_reports_corruption(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "bad.db"
    db.write_text("not sqlite", encoding="utf-8")
    monkeypatch.setenv("ZAB_LOCAL_DATABASE_PATH", str(db))

    payload = local_db.status()

    assert payload["exists"] is True
    assert payload["ok"] is False
    assert payload["error"]


def test_tasks_cache_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ZAB_LOCAL_DATABASE_PATH", str(tmp_path / "zab.db"))
    payload = {
        "generated_at_utc": "2026-01-01T00:00:00+00:00",
        "parse_errors": [],
        "env_hints": {"LINEAR_API_KEY": False},
        "sources": [{"id": "linear-main", "backend": "linear", "status": "ok"}],
        "all_tasks": [
            {
                "source_id": "linear-main",
                "source_label": "Linear",
                "identifier": "ABC-1",
                "title": "Do the thing",
                "state": "Todo",
                "updated_at": "2026-01-02T00:00:00Z",
            }
        ],
        "total_count": 1,
    }

    local_db.replace_tasks_cache(payload)
    cached = local_db.load_tasks_cache()

    assert cached is not None
    assert cached["total_count"] == 1
    assert cached["all_tasks"][0]["identifier"] == "ABC-1"


def test_state_roundtrip_normalizes_yaml_datetime(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ZAB_LOCAL_DATABASE_PATH", str(tmp_path / "zab.db"))
    state = {
        "version": "2.0",
        "last_sync_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "skills": {
            "demo": {
                "id": "demo",
                "updated_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
            }
        },
    }

    local_db.replace_state(state)
    loaded = local_db.load_state()

    assert loaded["last_sync_at"] == "2026-01-01T00:00:00+00:00"
    assert loaded["skills"]["demo"]["updated_at"] == "2026-01-02T00:00:00+00:00"


def test_search_state_matches_partial_multi_term_query(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ZAB_LOCAL_DATABASE_PATH", str(tmp_path / "zab.db"))
    state = {
        "version": "2.0",
        "knowledge_sources": {
            "obsidian": {
                "id": "obsidian",
                "display_name": "Obsidian Vault",
                "aliases": ["second brain", "secondbrain", "knowledge base"],
            }
        },
    }

    local_db.replace_state(state)
    rows = local_db.search_state("obsidian second brain", sections=["knowledge_sources"], limit=5)

    assert rows
    assert rows[0]["key"] == "obsidian"


def test_connect_waits_out_a_transient_writer_lock(tmp_path: Path, monkeypatch) -> None:
    """CI hit a real `sqlite3.OperationalError: database is locked` from
    `connect()` even though it sets `PRAGMA busy_timeout = 5000`, because that
    pragma ran *after* `PRAGMA journal_mode = WAL` — the one statement most
    likely to contend with a concurrent writer (switching journal mode needs
    an exclusive lock) had no retry window. Hold a write lock on a fresh
    (not-yet-WAL) database from another connection, release it shortly after,
    and confirm connect() waits it out instead of raising immediately."""
    db_path = tmp_path / "zab.db"
    monkeypatch.setenv("ZAB_LOCAL_DATABASE_PATH", str(db_path))

    blocker = sqlite3.connect(str(db_path), check_same_thread=False)
    blocker.execute("BEGIN IMMEDIATE")
    blocker.execute("CREATE TABLE _lock_probe (id INTEGER)")

    def release() -> None:
        blocker.commit()
        blocker.close()

    timer = threading.Timer(0.3, release)
    timer.start()
    try:
        conn = local_db.connect(migrate=False)
    finally:
        timer.cancel()
    conn.close()


def test_db_cli_status_and_export(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("ZAB_LOCAL_DATABASE_PATH", str(tmp_path / "zab.db"))
    runner = CliRunner()

    status = runner.invoke(app, ["db", "status", "--json"])
    assert status.exit_code == 0
    assert json.loads(status.stdout)["ok"] is True

    exported = runner.invoke(app, ["db", "export", "--format", "json"])
    assert exported.exit_code == 0
    assert json.loads(exported.stdout)["meta"]["schema_version"] == local_db.SCHEMA_VERSION
