"""Fetch and persist full message bodies for indexed InteractionEvents."""

from __future__ import annotations

import json
import subprocess
from typing import Any

from zab.services.conversation_ledger.store import upsert_event


def fetch_gmail_body(*, native_id: str, account: str) -> str | None:
    if not native_id or not account:
        return None
    cmd = ["gog", "gmail", "get", native_id, "-a", account, "-j", "--no-input"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return None
    body = data.get("body")
    if not body:
        return None
    return str(body).strip()


def enrich_event_content(event: dict[str, Any]) -> dict[str, Any]:
    """Return event with body filled when the source supports it."""
    if event.get("body"):
        return event
    source = str(event.get("source") or "").lower()
    if source == "gmail":
        body = fetch_gmail_body(
            native_id=str(event.get("native_id") or ""),
            account=str(event.get("source_account") or ""),
        )
        if body:
            event = dict(event)
            event["body"] = body
            if not event.get("snippet") or event.get("snippet") == event.get("title"):
                event["snippet"] = body[:360]
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
                not event.get("body")
                and str(event.get("source") or "").lower() == "gmail"
                and event.get("native_id")
                and event.get("source_account")
            )
            if needs and max_fetch is not None and fetched >= max_fetch:
                enriched.append(event)
                skipped += 1
                continue
            updated = enrich_event_content(event)
            if needs:
                if updated.get("body"):
                    fetched += 1
                    if conn is not None:
                        upsert_event(conn, updated)
                else:
                    failed += 1
            enriched.append(updated)

    if persist:
        from zab.services import local_db

        with local_db.transaction() as conn:
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
    from zab.services import local_db
    from zab.services.conversation_ledger.store import list_events

    with local_db.transaction() as conn:
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
