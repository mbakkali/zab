"""JSON contracts for Conversation Ledger objects."""

from __future__ import annotations

from typing import Any

CHANNEL_BINDING_CONTRACT = "conversation-ledger-channel-binding"
INTERACTION_EVENT_CONTRACT = "conversation-ledger-interaction-event"
WORKPACKET_CANONICAL_CONTRACT = "workpacket-canonical"
PROJECTION_STATE_CONTRACT = "conversation-ledger-projection-state"
LEDGER_EVAL_CONTRACT = "ledger-eval-report"

CONTRACT_VERSION = "1.0"

CHANNEL_TYPES = frozenset(
    {
        "gmail",
        "calendar",
        "fireflies",
        "whatsapp",
        "ios_messages",
        "google_chat",
        "drive",
        "attio",
        "linear",
        "local",
    }
)

READ_CAPABILITIES = frozenset({"metadata", "search", "read", "sync", "write"})
WRITE_CAPABILITIES = frozenset({"none", "draft", "send", "mutate"})
CHECK_STATUSES = frozenset({"ok", "degraded", "error", "unknown"})
DIRECTIONS = frozenset({"inbound", "outbound", "meeting", "system", "artifact", "task"})
MEDIA = frozenset(
    {
        "email",
        "calendar_event",
        "meeting_transcript",
        "chat_message",
        "file",
        "crm_note",
        "issue",
    }
)
PRIVACY_LEVELS = frozenset({"metadata", "snippet", "summary", "raw_local_only"})
PROJECTION_STATUSES = frozenset({"not_projected", "dry_run", "projected", "stale", "error", "candidate"})
WP_STATES = frozenset(
    {
        "candidate",
        "active",
        "waiting_approval",
        "in_progress",
        "blocked",
        "verified",
        "closed",
        "archived",
    }
)


def validate_channel_binding(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in ("channel_id", "channel_type", "label", "tool_id"):
        if not payload.get(field):
            errors.append(f"missing {field}")
    if payload.get("channel_type") and payload["channel_type"] not in CHANNEL_TYPES:
        errors.append("invalid channel_type")
    if payload.get("read_capability") and payload["read_capability"] not in READ_CAPABILITIES:
        errors.append("invalid read_capability")
    if payload.get("write_capability") and payload["write_capability"] not in WRITE_CAPABILITIES:
        errors.append("invalid write_capability")
    if payload.get("last_check_status") and payload["last_check_status"] not in CHECK_STATUSES:
        errors.append("invalid last_check_status")
    return errors


def validate_interaction_event(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in ("event_id", "source", "channel_id", "native_id", "timestamp"):
        if not payload.get(field):
            errors.append(f"missing {field}")
    if payload.get("direction") and payload["direction"] not in DIRECTIONS:
        errors.append("invalid direction")
    if payload.get("medium") and payload["medium"] not in MEDIA:
        errors.append("invalid medium")
    if payload.get("privacy_level") and payload["privacy_level"] not in PRIVACY_LEVELS:
        errors.append("invalid privacy_level")
    source = payload.get("source")
    if source in {"gmail", "calendar", "drive"} and not payload.get("source_account"):
        errors.append("missing source_account for gmail/calendar/drive")
    return errors


def validate_workpacket_canonical(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in ("workpacket_id", "title", "state"):
        if not payload.get(field):
            errors.append(f"missing {field}")
    subject_lock = payload.get("subject_lock")
    if not isinstance(subject_lock, dict):
        errors.append("missing subject_lock")
    else:
        for field in ("client", "project_or_workstream", "subject"):
            if not subject_lock.get(field):
                errors.append(f"missing subject_lock.{field}")
    if payload.get("state") and payload["state"] not in WP_STATES:
        errors.append("invalid state")
    if payload.get("intake_ref") != "workpacket-intake":
        errors.append("intake_ref must reference workpacket-intake")
    return errors


def validate_projection_state(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in ("workpacket_id", "target", "status"):
        if not payload.get(field):
            errors.append(f"missing {field}")
    if payload.get("status") and payload["status"] not in PROJECTION_STATUSES:
        errors.append("invalid projection status")
    return errors
