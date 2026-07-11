import pytest
from unittest.mock import patch
from zab.services.brain import schema

@patch("zab.services.brain.postgres_store.SCHEMA", "zab_core")
@patch("zab.services.brain.postgres_store.SCHEMA_VERSION", 2)
def test_brain_schema():
    result = schema()

    assert result["contract"] == "zab-brain-schema"
    assert result["contract_version"] == "1.0"
    assert result["schema"] == "zab_core"
    assert result["schema_version"] == 2
    assert "brain_conversations" in result["tables"]
    assert "brain_messages" in result["tables"]
    assert "brain_artifacts" in result["tables"]
    assert "brain_entities" in result["tables"]
    assert "brain_edges" in result["tables"]
    assert "brain_ingest_runs" in result["tables"]
