import pytest
from unittest.mock import patch
from zab.services.brain import status, schema

@patch("zab.services.brain.postgres_store.status")
def test_brain_status(mock_status):
    mock_status.return_value = {
        "database": "postgres",
        "schema": "zab_core",
        "configured": True,
        "connected": True,
        "psycopg_available": True,
        "schema_version": 2,
        "target_schema_version": 2,
        "ok": True,
        "tables": {
            "sync_meta": 0,
            "brain_conversations": 5,
            "brain_messages": 10,
            "brain_artifacts": 1,
            "brain_entities": 2,
            "brain_edges": 3,
            "brain_ingest_runs": 0,
        },
        "pgvector_ready": True,
        "error": None,
    }

    result = status()

    assert result["contract"] == "zab-brain-status"
    assert result["contract_version"] == "1.0"
    assert "generated_at_utc" in result
    assert result["store"]["schema_version"] == 2
    assert result["store"]["connected"] is True
    assert result["brain_tables"] == {
        "brain_conversations": 5,
        "brain_messages": 10,
        "brain_artifacts": 1,
        "brain_entities": 2,
        "brain_edges": 3,
        "brain_ingest_runs": 0,
    }
    assert result["ok"] is True
    assert result["warnings"] == []


def test_cli_brain_commands():
    from typer.testing import CliRunner
    from zab.cli import app

    runner = CliRunner()

    # Test status
    result = runner.invoke(app, ["brain", "status", "--json"])
    assert result.exit_code == 0
    assert "zab-brain-status" in result.stdout

    # Test schema
    result = runner.invoke(app, ["brain", "schema", "--json"])
    assert result.exit_code == 0
    assert "zab-brain-schema" in result.stdout
