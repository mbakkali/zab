import pytest
from typing import get_type_hints
from zab.services.brain_contracts import BrainStatusContract, BrainSchemaContract

def test_brain_status_contract_fields():
    hints = get_type_hints(BrainStatusContract)
    assert "contract" in hints
    assert "contract_version" in hints
    assert "generated_at_utc" in hints
    assert "store" in hints
    assert "brain_tables" in hints
    assert "ok" in hints
    assert "warnings" in hints

def test_brain_schema_contract_fields():
    hints = get_type_hints(BrainSchemaContract)
    assert "contract" in hints
    assert "contract_version" in hints
    assert "schema" in hints
    assert "schema_version" in hints
    assert "tables" in hints
