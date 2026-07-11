from __future__ import annotations

from typing import Any, Dict, List, TypedDict

class BrainStatusContract(TypedDict):
    contract: str
    contract_version: str
    generated_at_utc: str
    store: Dict[str, Any]
    brain_tables: Dict[str, int]
    ok: bool
    warnings: List[str]

class BrainSchemaContract(TypedDict):
    contract: str
    contract_version: str
    schema: str
    schema_version: int
    tables: List[str]
