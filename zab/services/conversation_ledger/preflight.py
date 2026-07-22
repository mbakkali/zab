"""Preflight checks for Conversation Ledger sources."""

from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Any


def _run(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    out = (proc.stdout or proc.stderr or "").strip()
    return proc.returncode, out[:500]


def check_gog_gmail(account: str) -> dict[str, Any]:
    code, out = _run(
        ["gog", "gmail", "messages", "search", "is:unread", "-a", account, "-j", "--no-input", "--max", "1"]
    )
    return {"account": account, "status": "ok" if code == 0 else "error", "detail": out[:200]}


def check_gog_calendar(account: str) -> dict[str, Any]:
    code, out = _run(["gog", "calendar", "events", "list", "-a", account, "-j", "--no-input"])
    return {"account": account, "status": "ok" if code == 0 else "error", "detail": out[:200]}


def check_fireflies() -> dict[str, Any]:
    key = os.environ.get("FIREFLIES_API_KEY", "").strip()
    return {"status": "ok" if key else "degraded", "detail": "FIREFLIES_API_KEY set" if key else "missing API key"}


def check_linear() -> dict[str, Any]:
    key = os.environ.get("LINEAR_API_KEY", "").strip()
    return {"status": "ok" if key else "degraded", "detail": "LINEAR_API_KEY set" if key else "missing API key"}


def check_attio() -> dict[str, Any]:
    key = os.environ.get("ATTIO_API_KEY", "").strip()
    return {"status": "ok" if key else "degraded", "detail": "ATTIO_API_KEY set" if key else "missing API key"}


def check_imessage() -> dict[str, Any]:
    chat_db = Path.home() / "Library" / "Messages" / "chat.db"
    if not chat_db.exists():
        return {"status": "error", "detail": "chat.db not found"}
    try:
        conn = sqlite3.connect(f"file:{chat_db}?mode=ro", uri=True)
        conn.execute("SELECT 1")
        conn.close()
        return {"status": "ok", "detail": "chat.db readable"}
    except sqlite3.Error as exc:
        return {"status": "degraded", "detail": str(exc)}


def run_preflight() -> dict[str, Any]:
    return {
        "contract": "ledger-preflight-report",
        "contract_version": "1.0",
        "gog": {
            "gmail_flowmetrik": check_gog_gmail("mehdi@flowmetrik.com"),
            "gmail_upfund": check_gog_gmail("mehdi@upfundpro.com"),
            "calendar_flowmetrik": check_gog_calendar("mehdi@flowmetrik.com"),
            "calendar_upfund": check_gog_calendar("mehdi@upfundpro.com"),
        },
        "fireflies": check_fireflies(),
        "linear": check_linear(),
        "attio": check_attio(),
        "imessage": check_imessage(),
    }
