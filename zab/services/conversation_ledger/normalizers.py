"""Source normalizers for InteractionEvent."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _parse_gmail_date(value: str | None) -> str:
    if not value:
        return datetime.now(timezone.utc).isoformat()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(value.strip(), fmt)
            return dt.replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue
    return value


def normalize_gmail_message(msg: dict[str, Any], *, channel: dict[str, Any]) -> dict[str, Any]:
    native_id = str(msg.get("id") or "")
    subject = str(msg.get("subject") or "")
    sender = str(msg.get("from") or "")
    direction = "outbound" if "SENT" in (msg.get("labels") or []) else "inbound"
    account = str(channel.get("account") or "")
    thread_id = str(msg.get("threadId") or native_id)
    body = str(msg.get("body") or "").strip()
    if account:
        source_url = f"https://mail.google.com/mail/?authuser={account}#all/{thread_id}"
    else:
        source_url = f"https://mail.google.com/mail/u/0/#all/{thread_id}"
    snippet = body[:360] if body else subject[:360]
    return {
        "event_id": f"gmail:{native_id}",
        "source": "gmail",
        "channel_id": channel["channel_id"],
        "tool_id": channel.get("tool_id"),
        "source_account": account,
        "native_id": native_id,
        "thread_id": thread_id,
        "source_url": source_url,
        "timestamp": _parse_gmail_date(msg.get("date")),
        "direction": direction,
        "medium": "email",
        "actor": {"display_name": sender, "email": None, "role": "unknown"},
        "counterparties": [],
        "title": subject,
        "snippet": snippet,
        "body": body or None,
        "summary": (body or subject)[:160],
        "raw_available": True,
        "privacy_level": "snippet",
        "tool_check_status_at_ingest": channel.get("last_check_status", "unknown"),
        "confidence": 0.9,
    }


def normalize_calendar_event(ev: dict[str, Any], *, channel: dict[str, Any]) -> dict[str, Any]:
    native_id = str(ev.get("id") or ev.get("etag") or ev.get("htmlLink") or "")
    title = str(ev.get("summary") or ev.get("title") or "Calendar event")
    start = (ev.get("start") or {}).get("dateTime") or (ev.get("start") or {}).get("date") or ev.get("startLocal")
    return {
        "event_id": f"calendar:{native_id}",
        "source": "calendar",
        "channel_id": channel["channel_id"],
        "tool_id": channel.get("tool_id"),
        "source_account": channel.get("account"),
        "native_id": native_id,
        "source_url": str(ev.get("htmlLink") or ""),
        "timestamp": str(start or datetime.now(timezone.utc).isoformat()),
        "direction": "meeting",
        "medium": "calendar_event",
        "actor": {"display_name": str((ev.get("organizer") or {}).get("email") or ""), "email": None, "role": "unknown"},
        "counterparties": [],
        "title": title,
        "snippet": title[:360],
        "summary": title[:160],
        "raw_available": True,
        "privacy_level": "metadata",
        "tool_check_status_at_ingest": channel.get("last_check_status", "unknown"),
        "confidence": 0.85,
    }


def normalize_imessage_message(msg: dict[str, Any], *, channel: dict[str, Any]) -> dict[str, Any]:
    native_id = str(msg.get("guid") or msg.get("rowid") or "")
    handle = str(msg.get("handle") or "")
    is_from_me = bool(msg.get("is_from_me"))
    text = str(msg.get("text") or "")
    return {
        "event_id": f"imessage:{native_id}",
        "source": "imessage",
        "channel_id": channel["channel_id"],
        "tool_id": channel.get("tool_id"),
        "source_account": channel.get("account", "local"),
        "native_id": native_id,
        "thread_id": handle,
        "source_url": "",
        "timestamp": str(msg.get("timestamp") or datetime.now(timezone.utc).isoformat()),
        "direction": "outbound" if is_from_me else "inbound",
        "medium": "chat_message",
        "actor": {"display_name": "Mehdi" if is_from_me else handle, "email": None, "role": "unknown"},
        "counterparties": [handle] if handle else [],
        "title": text[:120] or "Message iMessage",
        "snippet": text[:360],
        "body": text or None,
        "summary": text[:160],
        "raw_available": False,
        "privacy_level": "raw_local_only",
        "tool_check_status_at_ingest": channel.get("last_check_status", "unknown"),
        "confidence": 0.7,
    }


def normalize_whatsapp_message(msg: dict[str, Any], *, channel: dict[str, Any]) -> dict[str, Any]:
    native_id = str(msg.get("id") or msg.get("key", {}).get("id") or "")
    sender = str(msg.get("pushName") or msg.get("from") or "")
    is_from_me = bool(msg.get("fromMe") or (msg.get("key") or {}).get("fromMe"))
    text = str(msg.get("text") or msg.get("body") or (msg.get("message") or {}).get("conversation") or "")
    return {
        "event_id": f"whatsapp:{native_id}",
        "source": "whatsapp",
        "channel_id": channel["channel_id"],
        "tool_id": channel.get("tool_id"),
        "source_account": channel.get("account"),
        "native_id": native_id,
        "thread_id": str(msg.get("chatId") or msg.get("from") or native_id),
        "source_url": "",
        "timestamp": str(msg.get("timestamp") or msg.get("messageTimestamp") or datetime.now(timezone.utc).isoformat()),
        "direction": "outbound" if is_from_me else "inbound",
        "medium": "chat_message",
        "actor": {"display_name": "Mehdi" if is_from_me else sender, "email": None, "role": "unknown"},
        "counterparties": [sender] if sender else [],
        "title": text[:120] or "Message WhatsApp",
        "snippet": text[:360],
        "body": text or None,
        "summary": text[:160],
        "raw_available": False,
        "privacy_level": "snippet",
        "tool_check_status_at_ingest": channel.get("last_check_status", "unknown"),
        "confidence": 0.7,
    }


def normalize_fireflies_meeting(item: dict[str, Any], *, channel: dict[str, Any]) -> dict[str, Any]:
    native_id = str(item.get("id") or item.get("meeting_id") or "")
    title = str(item.get("title") or item.get("topic") or "Fireflies meeting")
    return {
        "event_id": f"fireflies:{native_id}",
        "source": "fireflies",
        "channel_id": channel["channel_id"],
        "tool_id": channel.get("tool_id"),
        "source_account": channel.get("account", "n/a"),
        "native_id": native_id,
        "source_url": str(item.get("url") or ""),
        "timestamp": str(item.get("date") or item.get("start_time") or datetime.now(timezone.utc).isoformat()),
        "direction": "meeting",
        "medium": "meeting_transcript",
        "actor": {"display_name": str(item.get("host") or ""), "email": None, "role": "unknown"},
        "counterparties": item.get("participants") or [],
        "title": title,
        "snippet": str(item.get("summary") or title)[:360],
        "summary": str(item.get("summary") or title)[:160],
        "raw_available": True,
        "privacy_level": "summary",
        "tool_check_status_at_ingest": channel.get("last_check_status", "unknown"),
        "confidence": 0.8,
    }
