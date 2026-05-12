"""Persistance du dernier scan (~/.local/share/zab/scan-last.yaml)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from zab.paths import data_dir


def scan_last_path() -> Path:
    return data_dir() / "scan-last.yaml"


def persist_workspace_scan(payload: dict[str, Any]) -> Path:
    data_dir().mkdir(parents=True, exist_ok=True)
    p = scan_last_path()
    envelope = {
        "saved_at_utc": datetime.now(timezone.utc).isoformat(),
        "scan": payload,
    }
    p.write_text(yaml.safe_dump(envelope, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return p


def load_last_scan() -> dict[str, Any] | None:
    p = scan_last_path()
    if not p.is_file():
        return None
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except (yaml.YAMLError, OSError):
        return None
