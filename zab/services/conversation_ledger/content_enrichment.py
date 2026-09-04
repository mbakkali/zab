"""Fetch and persist full message bodies for indexed InteractionEvents."""

from __future__ import annotations

import json
import subprocess
from typing import Any

from zab.services.conversation_ledger.normalizers import normalize_gmail_message
from zab.services.conversation_ledger.store import upsert_event


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


def _extract_gmail_body(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    body = _first_text(
        payload.get("body"),
        payload.get("text"),
        payload.get("plain"),
        payload.get("content"),
        payload.get("bodyText"),
        payload.get("body_text"),
    )
    if body:
        return body
    for key in ("message", "data", "result"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            body = _extract_gmail_body(nested)
            if body:
                return body
    return None


def fetch_gmail_message_details(*, native_id: str, account: str) -> dict[str, Any] | None:
    if not native_id or not account:
        return None
    cmd = ["gog", "gmail", "get", native_id, "-a", account, "-j", "--no-input", "--sanitize-content"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    body = _extract_gmail_body(data)
    headers = data.get("headers")
    message = data.get("message")
    message = message if isinstance(message, dict) else {}
    message_headers = message.get("headers") if isinstance(message.get("headers"), dict) else {}
    return {
        "id": message.get("id") or native_id,
        "threadId": message.get("threadId") or data.get("threadId") or native_id,
        "date": (headers or {}).get("date") if isinstance(headers, dict) else None,
        "subject": (headers or {}).get("subject") if isinstance(headers, dict) else None,
        "from": (headers or {}).get("from") if isinstance(headers, dict) else None,
        "body": body,
        "snippet": message.get("snippet"),
        "labels": message.get("labelIds") or data.get("labels") or [],
        "headers": {
            **(message_headers if isinstance(message_headers, dict) else {}),
            **(headers if isinstance(headers, dict) else {}),
        },
    }


def fetch_gmail_body(*, native_id: str, account: str) -> str | None:
    details = fetch_gmail_message_details(native_id=native_id, account=account)
    if not details:
        return None
    body = details.get("body")
    return str(body).strip() if body else None


def enrich_event_content(event: dict[str, Any]) -> dict[str, Any]:
    """Return event with body filled when the source supports it."""
    if event.get("body") and event.get("counterparties"):
        return event
    source = str(event.get("source") or "").lower()
    if source == "gmail":
        details = fetch_gmail_message_details(
            native_id=str(event.get("native_id") or ""),
            account=str(event.get("source_account") or ""),
        )
        if details:
            event = dict(event)
            normalized = normalize_gmail_message(
                {
                    **details,
                    "id": event.get("native_id") or details.get("id"),
                    "threadId": event.get("thread_id") or details.get("threadId"),
                    "subject": details.get("subject") or event.get("title"),
                    "from": details.get("from") or (event.get("actor") or {}).get("display_name"),
                    "date": event.get("timestamp") or details.get("date"),
                    "body": details.get("body") or event.get("body"),
                    "labels": details.get("labels") or [],
                    "snippet": details.get("snippet") or event.get("snippet"),
                },
                channel={
                    "channel_id": event.get("channel_id"),
                    "tool_id": event.get("tool_id"),
                    "account": event.get("source_account"),
                    "last_check_status": event.get("tool_check_status_at_ingest"),
                },
            )
            for key in ("actor", "body", "counterparties", "snippet", "summary", "title"):
                if normalized.get(key):
                    event[key] = normalized[key]
            if event.get("counterparties"):
                from zab.services.conversation_ledger.entity_resolver import build_entity_links

                event["entity_links"] = build_entity_links(event)
    return event


def enrich_events_content(
    events: list[dict[str, Any]],
    *,
    persist: bool = False,
    max_fetch: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Enrich a batch of events; optionally persist updates to SQLite."""
    enriched: list[dict[str, Any]] = []
    fetched = 0
    skipped = 0
    failed = 0

    def _process(batch: list[dict[str, Any]], conn: Any | None) -> None:
        nonlocal fetched, skipped, failed
        for event in batch:
            needs = (
                str(event.get("source") or "").lower() == "gmail"
                and event.get("native_id")
                and event.get("source_account")
                and (not event.get("body") or not event.get("counterparties"))
            )
            if needs and max_fetch is not None and fetched >= max_fetch:
                enriched.append(event)
                skipped += 1
                continue
            updated = enrich_event_content(event)
            if needs:
                has_new_content = bool(updated.get("body")) or updated.get("counterparties") != event.get("counterparties")
                if has_new_content:
                    fetched += 1
                    if conn is not None:
                        upsert_event(conn, updated)
                else:
                    failed += 1
            enriched.append(updated)

    if persist:
        from zab.services import ledger_db

        with ledger_db.transaction() as conn:
            _process(events, conn)
    else:
        _process(events, None)

    return enriched, {"fetched": fetched, "skipped": skipped, "failed": failed}


def enrich_organization_content(
    organization_id: str,
    *,
    limit: int = 500,
    max_fetch: int | None = None,
) -> dict[str, Any]:
    """Backfill Gmail bodies for all events linked to an organization."""
    from zab.services import ledger_db
    from zab.services.conversation_ledger.store import list_events

    with ledger_db.transaction() as conn:
        events = list_events(conn, organization_id=organization_id, limit=limit)
    enriched, stats = enrich_events_content(events, persist=True, max_fetch=max_fetch)
    with_body = sum(1 for e in enriched if e.get("body"))
    return {
        "contract": "conversation-ledger-enrich-content",
        "organization_id": organization_id,
        "events_scanned": len(enriched),
        "events_with_body": with_body,
        **stats,
    }
