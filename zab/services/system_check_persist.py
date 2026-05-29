"""Persistance du dernier rapport system check (JSON + métadonnées config.yaml)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from zab.paths import data_dir
from zab.user_config import load_user_config, save_user_config


def system_check_last_path() -> Path:
    return data_dir() / "system-check-last.json"


def _normalize_report(raw: dict[str, Any]) -> dict[str, Any]:
    checks = raw.get("checks")
    if not isinstance(checks, list):
        checks = []
    generated_at = str(raw.get("generated_at_utc") or datetime.now(timezone.utc).isoformat())
    return {
        "generated_at_utc": generated_at,
        "percentage": int(raw.get("percentage") or 0),
        "score": float(raw.get("score") or 0.0),
        "total": int(raw.get("total") or len(checks)),
        "ok": int(raw.get("ok") or 0),
        "warn": int(raw.get("warn") or 0),
        "fail": int(raw.get("fail") or 0),
        "checks": checks,
    }


def persist_system_check_report(report: dict[str, Any]) -> Path:
    """Écrit le JSON complet et met à jour ~/.config/zab/config.yaml."""
    normalized = _normalize_report(report)
    saved_at = datetime.now(timezone.utc).isoformat()

    data_dir().mkdir(parents=True, exist_ok=True)
    path = system_check_last_path()
    envelope = {
        "saved_at_utc": saved_at,
        "generated_at_utc": normalized["generated_at_utc"],
        "report": normalized,
    }
    path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")

    cfg = dict(load_user_config())
    cfg.pop("_error", None)
    cfg["last_system_check_at_utc"] = normalized["generated_at_utc"]
    cfg["system_check_last"] = {
        "saved_at_utc": saved_at,
        "generated_at_utc": normalized["generated_at_utc"],
        "report_path": str(path.resolve()),
        "percentage": normalized["percentage"],
        "score": normalized["score"],
        "total": normalized["total"],
        "ok": normalized["ok"],
        "warn": normalized["warn"],
        "fail": normalized["fail"],
        "report": normalized,
    }
    save_user_config(cfg)
    return path


def load_last_system_check() -> dict[str, Any] | None:
    path = system_check_last_path()
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(raw, dict):
        return None
    report = raw.get("report")
    if not isinstance(report, dict):
        return None
    return {
        "saved_at_utc": raw.get("saved_at_utc"),
        "generated_at_utc": raw.get("generated_at_utc") or report.get("generated_at_utc"),
        "report_path": str(path.resolve()),
        "report": _normalize_report(report),
    }
