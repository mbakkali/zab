"""Tests légers classification erreurs Postgres (sans vraie connexion)."""

from __future__ import annotations

from zab.services.memory_db import _postgres_failure_metadata


def test_failure_metadata_mehdi_table_missing():
    _, rid = _postgres_failure_metadata(
        RuntimeError('relation "mehdi_memory_documents" does not exist')
    )
    assert rid == "apply_gateway_migrations"


def test_failure_metadata_connection_refused():
    _, rid = _postgres_failure_metadata(OSError("[Errno 61] Connection refused"))
    assert rid == "ensure_postgres_running"


def test_failure_metadata_pg_password():
    _, rid = _postgres_failure_metadata(
        RuntimeError("password authentication failed for user \"x\"")
    )
    assert rid == "fix_pg_credentials"


def test_failure_metadata_database_missing():
    err = (
        'connection failed: connection to server at "127.0.0.1", port 5432 failed: '
        'FATAL:  database "mempalace" does not exist\n'
    )
    _, rid = _postgres_failure_metadata(RuntimeError(err))
    assert rid == "create_database_or_fix_dsn"
