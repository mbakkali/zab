from __future__ import annotations

from typing import cast
from zab.services import postgres_store
from zab.services.brain_contracts import BrainStatusContract, BrainSchemaContract
from zab.services.postgres_store import utc_now

BRAIN_TABLES = (
    "brain_conversations",
    "brain_messages",
    "brain_artifacts",
    "brain_entities",
    "brain_edges",
    "brain_ingest_runs",
)


def status() -> BrainStatusContract:
    store_status = postgres_store.status()
    tables_counts = store_status.get("tables", {})

    brain_tables = {
        t: tables_counts.get(t, 0)
        for t in BRAIN_TABLES
    }

    ok = store_status.get("ok", False)
    warnings = []
    target_schema_version = store_status.get("target_schema_version", postgres_store.SCHEMA_VERSION)
    if store_status.get("schema_version") != target_schema_version:
        warnings.append("Schema version mismatch")

    return {
        "contract": "zab-brain-status",
        "contract_version": "1.0",
        "generated_at_utc": utc_now(),
        "store": store_status,
        "brain_tables": brain_tables,
        "ok": ok,
        "warnings": warnings,
    }


def schema() -> BrainSchemaContract:
    return {
        "contract": "zab-brain-schema",
        "contract_version": "1.0",
        "schema": postgres_store.SCHEMA,
        "schema_version": postgres_store.SCHEMA_VERSION,
        "tables": list(BRAIN_TABLES),
    }
