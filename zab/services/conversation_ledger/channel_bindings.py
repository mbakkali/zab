"""ChannelBinding resolution via Tool Catalog and connector checks."""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any

from zab.services import connectors_check, tool_catalog
from zab.services import tool_checks
from zab.services.conversation_ledger.schemas import (
    CHANNEL_BINDING_CONTRACT,
    CONTRACT_VERSION,
    validate_channel_binding,
)
from zab.services.dotenv_locate import load_standard_dotenvs_once
from zab.user_config import load_user_config

DEFAULT_BINDINGS: list[dict[str, Any]] = [
    {
        "channel_id": "gmail-flowmetrik-primary",
        "channel_type": "gmail",
        "label": "Gmail Flowmetrik",
        "tool_id": "gmail-search",
        "implementation_id": "gmail-gog",
        "connector_ref": "gmail",
        "transport": "gog",
        "account": "mehdi@flowmetrik.com",
        "enabled": True,
        "read_capability": "search",
        "write_capability": "none",
    },
    {
        "channel_id": "gmail-upfund-history",
        "channel_type": "gmail",
        "label": "Gmail Upfund",
        "tool_id": "gmail-search",
        "implementation_id": "gmail-gog",
        "connector_ref": "gmail",
        "transport": "gog",
        "account": "mehdi@upfundpro.com",
        "enabled": True,
        "read_capability": "search",
        "write_capability": "none",
    },
    {
        "channel_id": "calendar-flowmetrik-primary",
        "channel_type": "calendar",
        "label": "Calendar Flowmetrik",
        "tool_id": "google-calendar-search",
        "implementation_id": "calendar-gog",
        "connector_ref": "google-calendar",
        "transport": "gog",
        "account": "mehdi@flowmetrik.com",
        "enabled": True,
        "read_capability": "read",
        "write_capability": "none",
    },
    {
        "channel_id": "calendar-upfund-history",
        "channel_type": "calendar",
        "label": "Calendar Upfund",
        "tool_id": "google-calendar-search",
        "implementation_id": "calendar-gog",
        "connector_ref": "google-calendar",
        "transport": "gog",
        "account": "mehdi@upfundpro.com",
        "enabled": True,
        "read_capability": "read",
        "write_capability": "none",
    },
    {
        "channel_id": "fireflies-flowmetrik",
        "channel_type": "fireflies",
        "label": "Fireflies Flowmetrik",
        "tool_id": "fireflies-search",
        "implementation_id": "fireflies-api",
        "connector_ref": "fireflies",
        "transport": "api",
        "account": "n/a",
        "enabled": True,
        "read_capability": "search",
        "write_capability": "none",
    },
    {
        "channel_id": "whatsapp-evolution-mehdi",
        "channel_type": "whatsapp",
        "label": "WhatsApp (Evolution API)",
        "tool_id": "whatsapp-search",
        "implementation_id": "whatsapp-evolution",
        "connector_ref": "evolution-api",
        "transport": "evolution",
        "account": "mehdi-perso",
        "enabled": True,
        "read_capability": "search",
        "write_capability": "none",
    },
    {
        "channel_id": "imessage-local",
        "channel_type": "ios_messages",
        "label": "iMessage (local)",
        "tool_id": "imessage-search",
        "implementation_id": "imessage-chatdb",
        "connector_ref": None,
        "transport": "local",
        "account": "local",
        "enabled": True,
        "read_capability": "read",
        "write_capability": "none",
    },
    {
        "channel_id": "attio-crm",
        "channel_type": "attio",
        "label": "Attio CRM",
        "tool_id": "attio-cockpit",
        "implementation_id": "attio-api",
        "connector_ref": "attio",
        "transport": "attio",
        "account": "flowmetrik",
        "enabled": True,
        "read_capability": "read",
        "write_capability": "none",
    },
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gog_smoke(binding: dict[str, Any]) -> tuple[str, str]:
    if not shutil.which("gog"):
        return "error", "gog binary not found"
    account = str(binding.get("account") or "")
    ctype = str(binding.get("channel_type") or "")
    if ctype == "gmail":
        cmd = [
            "gog",
            "gmail",
            "messages",
            "search",
            "is:unread",
            "-a",
            account,
            "-j",
            "--no-input",
            "--max",
            "1",
        ]
    elif ctype == "calendar":
        cmd = ["gog", "calendar", "events", "list", "-a", account, "-j", "--no-input"]
    else:
        return "unknown", "no gog smoke for channel type"
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "gog smoke failed").strip()[:160]
        return "error", f"gog_smoke_failed={detail}"
    return "ok", "gog_smoke=ok"


def _fireflies_smoke() -> tuple[str, str]:
    import os

    load_standard_dotenvs_once()
    if os.environ.get("FIREFLIES_API_KEY", "").strip():
        return "ok", "fireflies_api_key=present"
    return "degraded", "fireflies_api_key=missing"


def _evolution_smoke() -> tuple[str, str]:
    import os

    load_standard_dotenvs_once()
    required = ("EVOLUTION_API_URL", "EVOLUTION_API_KEY")
    missing = [key for key in required if not os.environ.get(key, "").strip()]
    if not (
        os.environ.get("EVOLUTION_INSTANCE", "").strip()
        or os.environ.get("EVOLUTION_INSTANCE_NAME", "").strip()
    ):
        missing.append("EVOLUTION_INSTANCE")
    if missing:
        return "degraded", f"evolution_env_missing={','.join(missing)}"
    unresolved = [
        key
        for key in (
            "EVOLUTION_API_URL",
            "EVOLUTION_API_KEY",
            "EVOLUTION_INSTANCE",
            "EVOLUTION_INSTANCE_NAME",
        )
        if os.environ.get(key, "").strip().startswith("dl://")
    ]
    if unresolved:
        return (
            "error",
            f"evolution_dashlane_reference_unresolved={','.join(unresolved)}",
        )
    return "ok", "evolution_env=present"


def _imessage_smoke() -> tuple[str, str]:
    try:
        from zab.services.conversation_ledger.preflight import check_imessage

        result = check_imessage()
        return str(
            result.get("status") or "unknown"
        ), f"imessage={result.get('detail')}"
    except Exception as exc:  # noqa: BLE001
        return "degraded", f"imessage_check_error={exc}"


def _attio_smoke() -> tuple[str, str]:
    import os

    load_standard_dotenvs_once()
    if os.environ.get("ATTIO_API_KEY", "").strip():
        return "ok", "attio_api_key=present"
    return "degraded", "attio_api_key=missing"


def _transport_smoke(binding: dict[str, Any]) -> tuple[str, str]:
    transport = str(binding.get("transport") or "")
    ctype = str(binding.get("channel_type") or "")
    if transport == "gog":
        return _gog_smoke(binding)
    if transport == "api" and ctype == "fireflies":
        return _fireflies_smoke()
    if transport == "evolution" or ctype == "whatsapp":
        return _evolution_smoke()
    if transport == "local" and ctype == "ios_messages":
        return _imessage_smoke()
    if transport == "attio" or ctype == "attio":
        return _attio_smoke()
    return "unknown", "transport_smoke=skipped"


def load_channel_bindings() -> list[dict[str, Any]]:
    cfg = load_user_config()
    section = (
        cfg.get("conversation_ledger")
        if isinstance(cfg.get("conversation_ledger"), dict)
        else {}
    )
    channels = (
        section.get("channels") if isinstance(section.get("channels"), list) else None
    )
    raw = channels if channels else DEFAULT_BINDINGS
    bindings: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        binding = dict(item)
        binding.setdefault("contract", CHANNEL_BINDING_CONTRACT)
        binding.setdefault("contract_version", CONTRACT_VERSION)
        binding.setdefault(
            "tool_catalog_ref", f"tools.catalog:{binding.get('tool_id')}"
        )
        bindings.append(binding)
    return bindings


def check_channel_binding(binding: dict[str, Any]) -> dict[str, Any]:
    result = dict(binding)
    result["last_checked_at"] = _now()
    tool_id = str(binding.get("tool_id") or "")
    reasons: list[str] = []
    status = "unknown"

    try:
        payload = tool_catalog.get_tool(tool_id)
        tool = (payload or {}).get("tool") if payload else None
        if not tool:
            status = "degraded"
            reasons.append(f"tool {tool_id} not found in catalog")
        else:
            check = tool_checks.check_tool(tool_id)
            tool_status = str((check or {}).get("status") or "unknown")
            if tool_status == "ok":
                status = "ok"
            elif tool_status in {"warn", "degraded", "warning"}:
                status = "degraded"
            else:
                status = "degraded"
            reasons.append(f"tool_check={tool_status}")
    except Exception as exc:  # noqa: BLE001
        status = "degraded"
        reasons.append(f"tool_check_error={exc}")

    connector_ref = binding.get("connector_ref")
    if connector_ref:
        try:
            payload = connectors_check.check_connector_payload(str(connector_ref))
            conn_status = str((payload or {}).get("status") or "unknown")
            reasons.append(f"connector={conn_status}")
            if conn_status != "ok" and status == "ok":
                status = "degraded"
        except Exception as exc:  # noqa: BLE001
            reasons.append(f"connector_check_error={exc}")

    probe_status, probe_reason = _transport_smoke(binding)
    reasons.append(probe_reason)
    if probe_status == "ok":
        status = "ok"
    elif probe_status == "degraded" and status != "ok":
        status = "degraded"
    elif probe_status == "error":
        status = "error"

    if not binding.get("enabled", True):
        status = "degraded"
        reasons.append("channel disabled")

    result["last_check_status"] = status
    result["last_check_reason"] = "; ".join(reasons)
    return result


def list_channels(*, check: bool = True) -> dict[str, Any]:
    bindings = load_channel_bindings()
    checked = [check_channel_binding(b) if check else b for b in bindings]
    for item in checked:
        validate_channel_binding(item)
    ok = sum(1 for c in checked if c.get("last_check_status") == "ok")
    degraded = sum(1 for c in checked if c.get("last_check_status") == "degraded")
    error = sum(1 for c in checked if c.get("last_check_status") == "error")
    return {
        "contract": "conversation-ledger-channels",
        "contract_version": CONTRACT_VERSION,
        "generated_at_utc": _now(),
        "summary": {
            "total": len(checked),
            "ok": ok,
            "degraded": degraded,
            "error": error,
        },
        "channels": checked,
    }


def channels_by_id() -> dict[str, dict[str, Any]]:
    return {b["channel_id"]: b for b in load_channel_bindings()}
