"""Source normalizers for InteractionEvent."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
        elif value is not None:
            text = str(value).strip()
            if text:
                return text
    return ""


def _parse_timestamp(value: Any) -> str:
    if not value:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(value, (int, float)):
        raw_num = float(value)
        if raw_num > 10_000_000_000:
            raw_num = raw_num / 1000.0
        try:
            return datetime.fromtimestamp(raw_num, tz=timezone.utc).isoformat()
        except (OSError, OverflowError, ValueError):
            return datetime.now(timezone.utc).isoformat()
    text = str(value).strip()
    if text.isdigit():
        return _parse_timestamp(int(text))
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue
    return text


def _parse_email(value: str) -> str | None:
    match = re.search(r"<([^<>@\s]+@[^<>@\s]+)>", value)
    if match:
        return match.group(1)
    match = re.search(r"([^<>\s]+@[^<>\s]+)", value)
    if match:
        return match.group(1)
    return None


def _address_values(*values: Any) -> list[str]:
    out: list[str] = []
    for value in values:
        if not value:
            continue
        if isinstance(value, list):
            out.extend(_address_values(*value))
            continue
        if isinstance(value, dict):
            out.extend(
                _address_values(
                    value.get("email"),
                    value.get("address"),
                    value.get("name"),
                    value.get("display_name"),
                )
            )
            continue
        text = str(value)
        for part in re.split(r",(?=(?:[^<]*<[^>]*>)*[^>]*$)", text):
            clean = " ".join(part.strip().split())
            if clean and clean not in out:
                out.append(clean)
    return out


def _gmail_body(msg: dict[str, Any]) -> str:
    body = _first_text(
        msg.get("body"),
        msg.get("text"),
        msg.get("plain"),
        msg.get("content"),
        msg.get("bodyText"),
        msg.get("body_text"),
    )
    if body:
        return body
    payload = msg.get("message")
    if isinstance(payload, dict):
        return _first_text(
            payload.get("body"),
            payload.get("text"),
            payload.get("plain"),
            payload.get("content"),
        )
    return ""


def _gmail_preview(msg: dict[str, Any], subject: str) -> str:
    return _first_text(
        _gmail_body(msg),
        msg.get("snippet"),
        msg.get("Snippet"),
        msg.get("bodyPreview"),
        msg.get("preview"),
        subject,
    )


def _whatsapp_text(msg: dict[str, Any]) -> str:
    message = msg.get("message")
    message = message if isinstance(message, dict) else {}
    text = _first_text(
        msg.get("text"),
        msg.get("body"),
        message.get("conversation"),
        (message.get("extendedTextMessage") or {}).get("text")
        if isinstance(message.get("extendedTextMessage"), dict)
        else None,
        (message.get("imageMessage") or {}).get("caption")
        if isinstance(message.get("imageMessage"), dict)
        else None,
        (message.get("videoMessage") or {}).get("caption")
        if isinstance(message.get("videoMessage"), dict)
        else None,
        (message.get("documentMessage") or {}).get("caption")
        if isinstance(message.get("documentMessage"), dict)
        else None,
        (message.get("buttonsResponseMessage") or {}).get("selectedDisplayText")
        if isinstance(message.get("buttonsResponseMessage"), dict)
        else None,
        (message.get("listResponseMessage") or {}).get("title")
        if isinstance(message.get("listResponseMessage"), dict)
        else None,
    )
    if text:
        return text
    for key, label in (
        ("imageMessage", "image"),
        ("videoMessage", "video"),
        ("audioMessage", "audio"),
        ("documentMessage", "document"),
        ("stickerMessage", "sticker"),
        ("reactionMessage", "reaction"),
    ):
        if key in message:
            return f"({label} message)"
    return ""


def _fireflies_summary_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        parts: list[str] = []
        for key in (
            "overview",
            "short_summary",
            "gist",
            "bullet_gist",
            "action_items",
            "keywords",
        ):
            raw = value.get(key)
            if isinstance(raw, list):
                parts.extend(str(item).strip() for item in raw if str(item).strip())
            elif raw:
                parts.append(str(raw).strip())
        return "\n".join(part for part in parts if part)
    return ""


def _fireflies_transcript_text(item: dict[str, Any]) -> str:
    transcript = _first_text(
        item.get("transcript"), item.get("body"), item.get("notes")
    )
    if transcript:
        return transcript
    sentences = item.get("sentences")
    if isinstance(sentences, list):
        lines: list[str] = []
        for sentence in sentences:
            if not isinstance(sentence, dict):
                continue
            text = _first_text(sentence.get("text"))
            if not text:
                continue
            speaker = _first_text(sentence.get("speaker_name"), sentence.get("speaker"))
            lines.append(f"{speaker}: {text}" if speaker else text)
        return "\n".join(lines)
    return ""


def normalize_gmail_message(
    msg: dict[str, Any], *, channel: dict[str, Any]
) -> dict[str, Any]:
    native_id = str(msg.get("id") or msg.get("messageId") or msg.get("threadId") or "")
    headers = msg.get("headers") if isinstance(msg.get("headers"), dict) else {}
    subject = str(msg.get("subject") or headers.get("subject") or "")
    sender = str(msg.get("from") or headers.get("from") or "")
    direction = "outbound" if "SENT" in (msg.get("labels") or []) else "inbound"
    account = str(channel.get("account") or "")
    thread_id = str(msg.get("threadId") or native_id)
    body = _gmail_body(msg)
    preview = _gmail_preview(msg, subject)
    counterparties = _address_values(
        msg.get("to"),
        msg.get("cc"),
        msg.get("bcc"),
        headers.get("to"),
        headers.get("cc"),
        headers.get("bcc"),
    )
    if account:
        source_url = f"https://mail.google.com/mail/?authuser={account}#all/{thread_id}"
    else:
        source_url = f"https://mail.google.com/mail/u/0/#all/{thread_id}"
    return {
        "event_id": f"gmail:{native_id}",
        "source": "gmail",
        "channel_id": channel["channel_id"],
        "tool_id": channel.get("tool_id"),
        "source_account": account,
        "native_id": native_id,
        "thread_id": thread_id,
        "source_url": source_url,
        "timestamp": _parse_timestamp(msg.get("date") or msg.get("internalDate")),
        "direction": direction,
        "medium": "email",
        "actor": {
            "display_name": sender,
            "email": _parse_email(sender),
            "role": "unknown",
        },
        "counterparties": counterparties,
        "title": subject,
        "snippet": preview[:360],
        "body": body or None,
        "summary": preview[:160],
        "raw_available": True,
        "privacy_level": "snippet",
        "tool_check_status_at_ingest": channel.get("last_check_status", "unknown"),
        "confidence": 0.9,
    }


def normalize_calendar_event(
    ev: dict[str, Any], *, channel: dict[str, Any]
) -> dict[str, Any]:
    native_id = str(ev.get("id") or ev.get("etag") or ev.get("htmlLink") or "")
    title = str(ev.get("summary") or ev.get("title") or "Calendar event")
    start = (
        (ev.get("start") or {}).get("dateTime")
        or (ev.get("start") or {}).get("date")
        or ev.get("startLocal")
    )
    organizer = ev.get("organizer") if isinstance(ev.get("organizer"), dict) else {}
    attendees = ev.get("attendees") if isinstance(ev.get("attendees"), list) else []
    counterparties = _address_values(
        organizer,
        *attendees,
    )
    organizer_email = _parse_email(str(organizer.get("email") or ""))
    return {
        "event_id": f"calendar:{native_id}",
        "source": "calendar",
        "channel_id": channel["channel_id"],
        "tool_id": channel.get("tool_id"),
        "source_account": channel.get("account"),
        "native_id": native_id,
        "source_url": str(ev.get("htmlLink") or ""),
        "timestamp": _parse_timestamp(start),
        "direction": "meeting",
        "medium": "calendar_event",
        "actor": {
            "display_name": str(
                organizer.get("displayName") or organizer.get("email") or ""
            ),
            "email": organizer_email,
            "role": "organizer",
        },
        "counterparties": counterparties,
        "title": title,
        "snippet": title[:360],
        "summary": title[:160],
        "raw_available": True,
        "privacy_level": "metadata",
        "tool_check_status_at_ingest": channel.get("last_check_status", "unknown"),
        "confidence": 0.85,
    }


def normalize_imessage_message(
    msg: dict[str, Any], *, channel: dict[str, Any]
) -> dict[str, Any]:
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
        "timestamp": str(
            msg.get("timestamp") or datetime.now(timezone.utc).isoformat()
        ),
        "direction": "outbound" if is_from_me else "inbound",
        "medium": "chat_message",
        "actor": {
            "display_name": "Mehdi" if is_from_me else handle,
            "email": None,
            "role": "unknown",
        },
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


def normalize_whatsapp_message(
    msg: dict[str, Any], *, channel: dict[str, Any]
) -> dict[str, Any]:
    key = msg.get("key") if isinstance(msg.get("key"), dict) else {}
    sender = str(
        msg.get("pushName")
        or msg.get("notifyName")
        or msg.get("from")
        or key.get("remoteJid")
        or ""
    )
    is_from_me = bool(msg.get("fromMe") or key.get("fromMe"))
    text = _whatsapp_text(msg)
    preliminary_native_id = str(
        msg.get("id") or key.get("id") or msg.get("messageId") or ""
    )
    remote_jid = str(
        msg.get("chatId")
        or msg.get("from")
        or msg.get("remoteJid")
        or key.get("remoteJid")
        or preliminary_native_id
    )
    timestamp = _parse_timestamp(msg.get("timestamp") or msg.get("messageTimestamp"))
    native_id = preliminary_native_id or f"{remote_jid}:{timestamp}"
    return {
        "event_id": f"whatsapp:{native_id}",
        "source": "whatsapp",
        "channel_id": channel["channel_id"],
        "tool_id": channel.get("tool_id"),
        "source_account": channel.get("account"),
        "native_id": native_id,
        "thread_id": remote_jid,
        "source_url": "",
        "timestamp": timestamp,
        "direction": "outbound" if is_from_me else "inbound",
        "medium": "chat_message",
        "actor": {
            "display_name": "Mehdi" if is_from_me else sender,
            "email": None,
            "role": "unknown",
        },
        "counterparties": [sender] if sender else [],
        "title": text[:120] or "Message WhatsApp",
        "snippet": text[:360],
        "body": text or None,
        "summary": text[:160],
        "raw_available": True,
        "privacy_level": "snippet",
        "tool_check_status_at_ingest": channel.get("last_check_status", "unknown"),
        "confidence": 0.7,
    }


def normalize_fireflies_meeting(
    item: dict[str, Any], *, channel: dict[str, Any]
) -> dict[str, Any]:
    native_id = str(item.get("id") or item.get("meeting_id") or "")
    title = str(item.get("title") or item.get("topic") or "Fireflies meeting")
    transcript = _fireflies_transcript_text(item)
    summary = _fireflies_summary_text(item.get("summary")) or title
    preview = transcript or summary
    return {
        "event_id": f"fireflies:{native_id}",
        "source": "fireflies",
        "channel_id": channel["channel_id"],
        "tool_id": channel.get("tool_id"),
        "source_account": channel.get("account", "n/a"),
        "native_id": native_id,
        "source_url": str(item.get("url") or ""),
        "timestamp": _parse_timestamp(item.get("date") or item.get("start_time")),
        "direction": "meeting",
        "medium": "meeting_transcript",
        "actor": {
            "display_name": str(item.get("host") or ""),
            "email": None,
            "role": "unknown",
        },
        "counterparties": item.get("participants") or [],
        "title": title,
        "snippet": preview[:360],
        "body": transcript or None,
        "summary": summary[:160],
        "raw_available": True,
        "privacy_level": "summary",
        "tool_check_status_at_ingest": channel.get("last_check_status", "unknown"),
        "confidence": 0.8,
    }
