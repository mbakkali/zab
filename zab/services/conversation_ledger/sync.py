"""Sync pipeline: preflight channels, fetch sources, normalize, persist."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any

from zab.services import local_db
from zab.services.conversation_ledger.channel_bindings import (
    check_channel_binding,
    list_channels,
)
from zab.services.conversation_ledger.entity_resolver import (
    build_entity_links,
    extract_contact_addresses,
    resolve_workstream,
)
from zab.services.conversation_ledger.messaging_targeted import (
    fetch_imessage_recent,
    fetch_whatsapp_recent,
)
from zab.services.conversation_ledger.normalizers import (
    normalize_calendar_event,
    normalize_fireflies_meeting,
    normalize_gmail_message,
    normalize_imessage_message,
    normalize_whatsapp_message,
)
from zab.services.conversation_ledger.store import set_source_cursor, upsert_event
from zab.services.dotenv_locate import load_standard_dotenvs_once


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_since(value: str) -> str:
    value = value.strip().lower()
    if value.endswith("d"):
        days = int(value[:-1])
        dt = datetime.now(timezone.utc) - timedelta(days=days)
        return dt.date().isoformat()
    return value


def _run_gog_gmail(
    channel: dict[str, Any],
    *,
    since: str,
    max_results: int = 200,
    query: str | None = None,
) -> list[dict[str, Any]]:
    base_query = query or f"after:{since.replace('-', '/')}"
    cmd = [
        "gog",
        "gmail",
        "messages",
        "search",
        base_query,
        "-a",
        str(channel.get("account")),
        "-j",
        "--no-input",
        "--max",
        str(max_results),
    ]
    if max_results > 500:
        cmd.append("--all")
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return []
    data = json.loads(proc.stdout or "{}")
    return (data.get("messages") or [])[:max_results]


def _run_gog_calendar(
    channel: dict[str, Any],
    *,
    since: str | None = None,
    max_results: int = 100,
) -> list[dict[str, Any]]:
    cmd = [
        "gog",
        "calendar",
        "events",
        "list",
        "-a",
        str(channel.get("account")),
        "-j",
        "--no-input",
        "--max",
        str(max_results),
    ]
    if since:
        cmd.extend(["--from", since])
    if max_results > 10:
        cmd.append("--all-pages")
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return []
    data = json.loads(proc.stdout or "{}")
    events = data.get("events") or []
    return events[:max_results]


def _run_fireflies_search(
    channel: dict[str, Any],
    *,
    query: str = "",
    since: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    import json
    import os
    import urllib.request

    load_standard_dotenvs_once()
    api_key = os.environ.get("FIREFLIES_API_KEY", "").strip()
    if not api_key:
        return []
    requested = max(1, int(limit))
    page_size = min(requested, 50)
    from_date = f"{since}T00:00:00.000Z" if since and "T" not in since else since
    data: list[dict[str, Any]] = []
    for skip in range(0, requested, page_size):
        gql = {
            "query": (
                "query Transcripts($limit: Int, $skip: Int, $fromDate: DateTime) { "
                "transcripts(limit: $limit, skip: $skip, fromDate: $fromDate) "
                "{ id title date host: host_email organizer_email participants "
                "summary { overview short_summary gist bullet_gist action_items keywords } "
                "url: transcript_url } }"
            ),
            "variables": {
                "limit": min(page_size, requested - len(data)),
                "skip": skip,
                "fromDate": from_date,
            },
        }
        req = urllib.request.Request(
            "https://api.fireflies.ai/graphql",
            data=json.dumps(gql).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            break
        page = (payload.get("data") or {}).get("transcripts") or []
        data.extend(item for item in page if isinstance(item, dict))
        if len(page) < page_size or len(data) >= requested:
            break
    if query:
        needle = query.lower()
        data = [row for row in data if needle in str(row.get("title") or "").lower()]
    return data[:requested]


def _entity_text(event: dict[str, Any]) -> str:
    actor = event.get("actor") or {}
    return " ".join(
        [
            str(event.get("title") or ""),
            str(event.get("snippet") or ""),
            str(event.get("summary") or ""),
            str(actor.get("display_name") or ""),
            str(actor.get("email") or ""),
            *(str(item) for item in (event.get("counterparties") or []) if item),
        ]
    )


def _organization_link(event: dict[str, Any]) -> dict[str, Any] | None:
    for link in event.get("entity_links") or []:
        if link.get("entity_type") == "organization" and link.get("entity_id"):
            return link
    return None


def _manual_links(event: dict[str, Any]) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for link in event.get("entity_links") or []:
        evidence = [str(item).lower() for item in (link.get("evidence") or [])]
        if link.get("status") == "confirmed" and "manual link" in evidence:
            links.append(dict(link))
    return links


def _rebuild_direct_links(event: dict[str, Any]) -> dict[str, Any]:
    manual = _manual_links(event)
    for key in (
        "organization_id",
        "organization_label",
        "client_workstream_id",
        "client_workstream_label",
    ):
        event[key] = None
    links = build_entity_links(event)
    for manual_link in manual:
        entity_type = manual_link.get("entity_type")
        links = [link for link in links if link.get("entity_type") != entity_type]
        links.append(manual_link)
        if entity_type == "organization":
            event["organization_id"] = manual_link.get("entity_id")
            event["organization_label"] = manual_link.get("label")
        elif entity_type == "client_workstream":
            event["client_workstream_id"] = manual_link.get("entity_id")
            event["client_workstream_label"] = manual_link.get("label")
    event["entity_links"] = links
    return event


def _unique_history_indexes(
    events: list[dict[str, Any]],
) -> tuple[dict[str, tuple[str, str]], dict[str, tuple[str, str]]]:
    contact_orgs: dict[str, set[tuple[str, str]]] = {}
    thread_orgs: dict[str, set[tuple[str, str]]] = {}
    for event in events:
        org = _organization_link(event)
        if not org:
            continue
        identity = (str(org["entity_id"]), str(org.get("label") or org["entity_id"]))
        thread_id = str(event.get("thread_id") or "").strip()
        if thread_id:
            thread_orgs.setdefault(thread_id, set()).add(identity)
        for address in extract_contact_addresses(event):
            contact_orgs.setdefault(address, set()).add(identity)
    unique_contacts = {
        address: next(iter(organizations))
        for address, organizations in contact_orgs.items()
        if len(organizations) == 1
    }
    unique_threads = {
        thread_id: next(iter(organizations))
        for thread_id, organizations in thread_orgs.items()
        if len(organizations) == 1
    }
    return unique_contacts, unique_threads


def _infer_from_history(
    event: dict[str, Any],
    *,
    unique_contacts: dict[str, tuple[str, str]],
    unique_threads: dict[str, tuple[str, str]],
) -> str | None:
    if _organization_link(event):
        return None
    identity: tuple[str, str] | None = None
    reason: str | None = None
    confidence = 0.0
    thread_id = str(event.get("thread_id") or "").strip()
    if thread_id and thread_id in unique_threads:
        identity = unique_threads[thread_id]
        reason = "unique organization in message thread"
        confidence = 0.93
    else:
        candidates = {
            unique_contacts[address]
            for address in extract_contact_addresses(event)
            if address in unique_contacts
        }
        if len(candidates) == 1:
            identity = next(iter(candidates))
            reason = "unique organization for known contact"
            confidence = 0.82
    if not identity or not reason:
        return None

    org_id, org_label = identity
    links = list(event.get("entity_links") or [])
    links.append(
        {
            "entity_type": "organization",
            "entity_id": org_id,
            "label": org_label,
            "confidence": confidence,
            "evidence": [reason],
            "status": "confirmed" if confidence >= 0.9 else "candidate",
        }
    )
    event["organization_id"] = org_id
    event["organization_label"] = org_label
    ws_id, ws_label, ws_conf, ws_evidence = resolve_workstream(
        text=_entity_text(event),
        organization_id=org_id,
    )
    if ws_id:
        links = [
            link for link in links if link.get("entity_type") != "client_workstream"
        ]
        links.append(
            {
                "entity_type": "client_workstream",
                "entity_id": ws_id,
                "label": ws_label,
                "confidence": ws_conf,
                "evidence": ws_evidence,
                "status": "confirmed" if ws_conf >= 0.8 else "candidate",
            }
        )
        event["client_workstream_id"] = ws_id
        event["client_workstream_label"] = ws_label
    event["entity_links"] = links
    return "thread" if confidence >= 0.9 else "contact"


def reindex_entity_links(*, limit: int | None = None) -> dict[str, Any]:
    """Re-run direct and history-assisted entity resolution on indexed events."""
    with local_db.transaction() as conn:
        from zab.services.conversation_ledger.entity_registry import (
            ensure_entity_registry,
        )

        ensure_entity_registry(conn)
        query = "SELECT payload_json FROM ledger_events ORDER BY timestamp DESC"
        params: tuple[Any, ...] = ()
        if limit and limit > 0:
            query += " LIMIT ?"
            params = (limit,)
        rows = conn.execute(query, params).fetchall()
        original_events = [json.loads(row[0]) for row in rows]
        before_classified = sum(
            1 for event in original_events if event.get("organization_id")
        )
        events = [_rebuild_direct_links(dict(event)) for event in original_events]
        direct_classified = sum(1 for event in events if event.get("organization_id"))
        unique_contacts, unique_threads = _unique_history_indexes(events)
        inferred_thread = 0
        inferred_contact = 0
        for event in events:
            inferred = _infer_from_history(
                event,
                unique_contacts=unique_contacts,
                unique_threads=unique_threads,
            )
            if inferred == "thread":
                inferred_thread += 1
            elif inferred == "contact":
                inferred_contact += 1
        for event in events:
            upsert_event(conn, event)
        after_classified = sum(1 for event in events if event.get("organization_id"))
    return {
        "contract": "conversation-ledger-reindex",
        "updated": len(events),
        "classified_before": before_classified,
        "classified_direct": direct_classified,
        "inferred_from_thread": inferred_thread,
        "inferred_from_contact": inferred_contact,
        "classified_after": after_classified,
        "newly_classified": max(after_classified - before_classified, 0),
        "unclassified_after": len(events) - after_classified,
    }


def sync_organization(
    organization: str,
    *,
    since: str = "90d",
    dry_run: bool = False,
    max_per_channel: int = 300,
) -> dict[str, Any]:
    from zab.services.conversation_ledger.org_profiles import gmail_query_for_org
    from zab.services.conversation_ledger.resolve import _match_org

    org_id, org_label = _match_org(organization)
    if not org_id:
        raise ValueError(f"organization not recognized: {organization}")
    gmail_query = gmail_query_for_org(org_id)
    if not gmail_query:
        raise ValueError(f"no gmail query configured for {organization}")
    since_date = parse_since(since)
    query = f"({gmail_query}) after:{since_date.replace('-', '/')}"
    preflight = list_channels(check=True)
    selected = [
        c
        for c in preflight.get("channels") or []
        if c.get("channel_type") == "gmail" and c.get("enabled", True)
    ]
    created = 0
    channel_reports: list[dict[str, Any]] = []
    with local_db.transaction() as conn:
        from zab.services.conversation_ledger.entity_registry import (
            ensure_entity_registry,
        )

        ensure_entity_registry(conn)
        for channel in selected:
            checked = check_channel_binding(channel)
            if checked.get("last_check_status") == "error":
                channel_reports.append(
                    {
                        "channel_id": channel.get("channel_id"),
                        "status": "error",
                        "stored": 0,
                    }
                )
                continue
            raw_items = _run_gog_gmail(
                checked, since=since_date, max_results=max_per_channel, query=query
            )
            stored = 0
            for raw in raw_items:
                event = normalize_gmail_message(raw, channel=checked)
                links = build_entity_links(event)
                event["entity_links"] = links
                if dry_run:
                    stored += 1
                    continue
                upsert_event(conn, event)
                stored += 1
            created += stored
            channel_reports.append(
                {
                    "channel_id": channel.get("channel_id"),
                    "organization": org_label,
                    "query": query,
                    "fetched": len(raw_items),
                    "stored": stored,
                    "dry_run": dry_run,
                }
            )
    return {
        "contract": "conversation-ledger-sync-organization",
        "organization": {"id": org_id, "label": org_label},
        "since": since_date,
        "dry_run": dry_run,
        "events_created": created,
        "channels": channel_reports,
    }


def sync_channels(
    *,
    since: str = "90d",
    sources: list[str] | None = None,
    channel_ids: list[str] | None = None,
    dry_run: bool = False,
    max_per_channel: int = 500,
) -> dict[str, Any]:
    since_date = parse_since(since)
    preflight = list_channels(check=True)
    selected = []
    for channel in preflight.get("channels") or []:
        if not channel.get("enabled", True):
            continue
        if channel_ids and channel.get("channel_id") not in channel_ids:
            continue
        ctype = str(channel.get("channel_type") or "")
        if sources and ctype not in sources:
            continue
        selected.append(channel)

    created = 0
    skipped = 0
    degraded: list[str] = []
    channel_reports: list[dict[str, Any]] = []

    with local_db.transaction() as conn:
        from zab.services.conversation_ledger.entity_registry import (
            ensure_entity_registry,
        )

        ensure_entity_registry(conn)
        for channel in selected:
            checked = check_channel_binding(channel)
            status = checked.get("last_check_status")
            if status != "ok":
                degraded.append(str(channel.get("channel_id")))
            raw_items: list[dict[str, Any]] = []
            ctype = str(channel.get("channel_type"))
            if status == "error":
                channel_reports.append(
                    {
                        "channel_id": channel.get("channel_id"),
                        "status": status,
                        "fetched": 0,
                        "stored": 0,
                        "reason": checked.get("last_check_reason"),
                    }
                )
                continue
            if ctype == "gmail":
                raw_items = _run_gog_gmail(
                    checked, since=since_date, max_results=max_per_channel
                )
            elif ctype == "calendar":
                raw_items = _run_gog_calendar(
                    checked, since=since_date, max_results=max_per_channel
                )
            elif ctype == "fireflies":
                raw_items = _run_fireflies_search(
                    checked,
                    since=since_date,
                    limit=max_per_channel,
                )
            elif ctype == "whatsapp":
                raw_items = fetch_whatsapp_recent(limit=max_per_channel)
            elif ctype == "ios_messages":
                raw_items = fetch_imessage_recent(
                    limit=max_per_channel, since=since_date
                )

            stored = 0
            for raw in raw_items:
                if ctype == "gmail":
                    event = normalize_gmail_message(raw, channel=checked)
                elif ctype == "calendar":
                    event = normalize_calendar_event(raw, channel=checked)
                elif ctype == "fireflies":
                    event = normalize_fireflies_meeting(raw, channel=checked)
                elif ctype == "whatsapp":
                    event = normalize_whatsapp_message(raw, channel=checked)
                elif ctype == "ios_messages":
                    event = normalize_imessage_message(raw, channel=checked)
                else:
                    continue
                links = build_entity_links(event)
                event["entity_links"] = links
                for link in links:
                    if link.get("entity_type") == "organization":
                        event["organization_id"] = link.get("entity_id")
                        event["organization_label"] = link.get("label")
                    if link.get("entity_type") == "client_workstream":
                        event["client_workstream_id"] = link.get("entity_id")
                        event["client_workstream_label"] = link.get("label")
                if dry_run:
                    stored += 1
                    continue
                upsert_event(conn, event)
                stored += 1
            if not dry_run:
                set_source_cursor(
                    conn,
                    str(channel.get("channel_id")),
                    {
                        "last_seen": _now(),
                        "last_success": _now(),
                        "since": since_date,
                        "stored": stored,
                    },
                )
            created += stored
            channel_reports.append(
                {
                    "channel_id": channel.get("channel_id"),
                    "status": status,
                    "fetched": len(raw_items),
                    "stored": stored,
                    "dry_run": dry_run,
                }
            )

    return {
        "contract": "conversation-ledger-sync",
        "contract_version": "1.0",
        "generated_at_utc": _now(),
        "since": since_date,
        "dry_run": dry_run,
        "summary": {
            "channels_selected": len(selected),
            "events_created": created,
            "events_skipped": skipped,
            "degraded_channels": degraded,
        },
        "preflight": preflight.get("summary"),
        "channels": channel_reports,
    }


def build_timeline_markdown(
    *,
    organization: str | None = None,
    client_workstream: str | None = None,
    since: str | None = None,
    limit: int = 50,
) -> str:
    from zab.services.conversation_ledger.entity_resolver import DEFAULT_ORGANIZATIONS

    org_id = None
    if organization:
        for oid, org in DEFAULT_ORGANIZATIONS.items():
            if org["label"].lower() == organization.lower() or oid == organization:
                org_id = oid
                break
    ws_id = None
    if client_workstream:
        from zab.services.conversation_ledger.entity_resolver import WORKSTREAM_SEEDS

        for wid, ws in WORKSTREAM_SEEDS.items():
            if (
                ws["label"].lower() == client_workstream.lower()
                or wid == client_workstream
            ):
                ws_id = wid
                break

    with local_db.transaction() as conn:
        from zab.services.conversation_ledger.store import (
            list_events as ledger_list_events,
        )

        events = ledger_list_events(
            conn,
            organization_id=org_id,
            client_workstream_id=ws_id,
            since=since,
            limit=limit,
        )

    lines = ["# Interaction Timeline", ""]
    if organization:
        lines.append(f"- Organization: {organization}")
    if client_workstream:
        lines.append(f"- Client workstream: {client_workstream}")
    lines.append("")
    for event in events:
        lines.append(
            f"- {event.get('timestamp')} · {event.get('source')} · "
            f"{(event.get('actor') or {}).get('display_name', '?')} · "
            f"{event.get('direction')} · {event.get('title')}"
        )
    if not events:
        lines.append("_No events indexed yet._")
    return "\n".join(lines) + "\n"
