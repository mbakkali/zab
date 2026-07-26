"""Tests for Conversation Ledger contracts and pipeline."""

from __future__ import annotations

import json

import pytest

from zab.services import local_db
from zab.services.conversation_ledger.clustering import cluster_events
from zab.services.conversation_ledger.eval import run_eval
from zab.services.conversation_ledger.schemas import validate_interaction_event, validate_workpacket_canonical
from zab.services.conversation_ledger.store import upsert_event, upsert_projection, upsert_workpacket
from zab.services.conversation_ledger.workpacket import build_from_cluster
from zab.services.conversation_ledger.workpacket_builder import discover_workpackets, reconstruct_seed_candidates
from zab.services.conversation_ledger.projections.linear import project_linear


def _event(native_id: str, title: str, ws_hint: str = "") -> dict:
    return {
        "event_id": f"gmail:{native_id}",
        "source": "gmail",
        "native_id": native_id,
        "channel_id": "gmail-flowmetrik-primary",
        "timestamp": "2026-07-13T15:08:00+00:00",
        "source_account": "mehdi@flowmetrik.com",
        "title": title,
        "snippet": f"{title} {ws_hint}",
        "actor": {"display_name": "nbonhomme@arp-astrance.com"},
        "organization_id": "org_arp_astrance",
    }


def test_interaction_event_requires_native_id() -> None:
    event = _event("abc", "Audit suivi commercial")
    assert not validate_interaction_event(event)
    bad = dict(event)
    bad.pop("native_id")
    assert validate_interaction_event(bad)


def test_dedup_source_native_id() -> None:
    event = _event("dedup-1", "Audit CRM follow-up")
    with local_db.transaction() as conn:
        upsert_event(conn, event)
        upsert_event(conn, event)
        count = conn.execute("SELECT COUNT(*) FROM ledger_events").fetchone()[0]
    assert count == 1


def test_arp_workstreams_do_not_merge() -> None:
    events = [
        _event("1", "Audit outils et process commerciaux"),
        _event("2", "Formation Explorateurs IA"),
        _event("3", "Accès Deessi sécurité"),
    ]
    clusters = cluster_events(events, organization_id="org_arp_astrance")
    ws_ids = {c["client_workstream_id"] for c in clusters}
    assert {"cw_audit_crm", "cw_explorateurs_ia", "cw_securite_deessi"}.issubset(ws_ids)


def test_workpacket_requires_subject_lock() -> None:
    cluster = {
        "organization_id": "org_arp_astrance",
        "organization_label": "ARP Astrance",
        "client_workstream_id": "cw_audit_crm",
        "client_workstream_label": "Audit CRM",
        "events": [_event("10", "Audit suivi commercial")],
    }
    packet = build_from_cluster(cluster, display_id="ZWP-0001")
    assert not validate_workpacket_canonical(packet)
    packet.pop("subject_lock")
    assert validate_workpacket_canonical(packet)


def test_linear_import_stays_candidate() -> None:
    cluster = {
        "organization_id": "org_arp_astrance",
        "organization_label": "ARP Astrance",
        "client_workstream_id": "cw_audit_crm",
        "client_workstream_label": "Audit CRM",
        "events": [_event("11", "Audit suivi commercial")],
    }
    packet = build_from_cluster(cluster, display_id="ZWP-0002")
    with local_db.transaction() as conn:
        saved = upsert_workpacket(conn, packet)
        upsert_projection(
            conn,
            {
                "workpacket_id": saved["workpacket_id"],
                "target": "linear",
                "status": "candidate",
                "issue_id": "MBK-123",
            },
        )
        canonical = upsert_workpacket(conn, saved)
    assert canonical["workpacket_id"] == packet["workpacket_id"]
    assert canonical["title"].startswith("ARP Astrance")


def test_project_linear_dry_run() -> None:
    cluster = {
        "organization_id": "org_arp_astrance",
        "organization_label": "ARP Astrance",
        "client_workstream_id": "cw_audit_crm",
        "client_workstream_label": "Audit CRM",
        "events": [_event("12", "Audit suivi commercial")],
    }
    packet = build_from_cluster(cluster, display_id="ZWP-0003")
    with local_db.transaction() as conn:
        saved = upsert_workpacket(conn, packet)
        upsert_event(conn, cluster["events"][0])
    payload = project_linear(saved["workpacket_id"], dry_run=True)
    assert payload["dry_run"] is True
    assert "Subject Lock" in payload["description_markdown"]


def test_reconstruct_seed_candidates_count() -> None:
    payload = reconstruct_seed_candidates(dry_run=True)
    assert payload["count"] == 10


def test_reconstruct_reuses_existing_display_id() -> None:
    cluster = {
        "organization_id": "org_arp_astrance",
        "organization_label": "ARP Astrance",
        "client_workstream_id": "cw_audit_crm",
        "client_workstream_label": "Audit CRM",
        "events": [_event("reconstruct-1", "Audit suivi commercial")],
    }
    with local_db.transaction() as conn:
        first = upsert_workpacket(conn, build_from_cluster(cluster, display_id="ZWP-0001"))
        first_id = first["workpacket_id"]
    payload = reconstruct_seed_candidates(dry_run=False)
    arp = next(w for w in payload["workpackets"] if w.get("client_workstream_id") == "cw_audit_crm")
    assert arp["workpacket_id"] == first_id
    assert arp["display_id"] == "ZWP-0001"


def test_discover_reuses_existing_organization_workstream(monkeypatch) -> None:
    cluster = {
        "organization_id": "org_arp_astrance",
        "organization_label": "ARP Astrance",
        "client_workstream_id": "cw_audit_crm",
        "client_workstream_label": "Audit CRM",
        "events": [_event("discover-idempotent", "Audit outils et process commerciaux")],
    }
    with local_db.transaction() as conn:
        upsert_event(conn, cluster["events"][0])
        first = upsert_workpacket(conn, build_from_cluster(cluster, display_id="ZWP-0042"))

    monkeypatch.setattr(
        "zab.services.conversation_ledger.workpacket_builder.cluster_events",
        lambda *_args, **_kwargs: [cluster],
    )
    payload = discover_workpackets(dry_run=False, min_confidence=0)
    match = next(row for row in payload["candidates"] if row["client_workstream_id"] == "cw_audit_crm")

    assert match["workpacket_id"] == first["workpacket_id"]
    assert match["display_id"] == "ZWP-0042"
    assert match["_flowgo_created"] is False
    assert payload["created_count"] == 0
    assert payload["updated_count"] == 1


def test_eval_hard_suite_passes() -> None:
    payload = run_eval(suite="hard")
    assert payload["hard"]["failed"] == 0


def test_eval_quality_thresholds() -> None:
    payload = run_eval(suite="quality")
    assert payload["quality"]["clustering_precision"] >= 0.80
    assert payload["quality"]["ambiguity_rate"] <= 0.35


def test_resolve_preview() -> None:
    from zab.services.conversation_ledger.resolve import resolve_preview

    payload = resolve_preview(organization="ARP Astrance", client_workstream="Audit CRM", dry_run=True)
    assert payload["contract"] == "interactions-resolve"
    assert payload["organization"]["id"] == "org_arp_astrance"


def test_entity_registry_seeded() -> None:
    from zab.services import local_db
    from zab.services.conversation_ledger.entity_registry import list_organizations, list_workstreams

    with local_db.transaction() as conn:
        orgs = list_organizations(conn)
        streams = list_workstreams(conn, organization_id="org_arp_astrance")
    assert len(orgs) >= 8
    assert len(streams) >= 3


def test_channel_binding_gog_smoke(monkeypatch) -> None:
    from zab.services.conversation_ledger.channel_bindings import check_channel_binding

    binding = {
        "channel_id": "gmail-flowmetrik-primary",
        "channel_type": "gmail",
        "label": "Gmail Flowmetrik",
        "tool_id": "gmail-search",
        "transport": "gog",
        "account": "mehdi@flowmetrik.com",
        "enabled": True,
    }

    def fake_gog_smoke(_binding):
        return "ok", "gog_smoke=ok"

    monkeypatch.setattr(
        "zab.services.conversation_ledger.channel_bindings._gog_smoke",
        fake_gog_smoke,
    )
    monkeypatch.setattr(
        "zab.services.tool_checks.check_tool",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("psycopg absent")),
    )
    checked = check_channel_binding(binding)
    assert checked["last_check_status"] == "ok"


def test_enrich_gmail_event_adds_body(monkeypatch) -> None:
    from zab.services.conversation_ledger.content_enrichment import enrich_event_content

    event = {
        "event_id": "gmail:abc123",
        "source": "gmail",
        "native_id": "abc123",
        "source_account": "mehdi@flowmetrik.com",
        "title": "Sujet test",
        "snippet": "Sujet test",
    }

    monkeypatch.setattr(
        "zab.services.conversation_ledger.content_enrichment.fetch_gmail_body",
        lambda **_: "Corps complet du mail avec détails contractuels.",
    )
    enriched = enrich_event_content(event)
    assert enriched["body"].startswith("Corps complet")
    assert enriched["snippet"].startswith("Corps complet")


def test_enrich_skips_when_body_present(monkeypatch) -> None:
    from zab.services.conversation_ledger.content_enrichment import enrich_event_content

    called = {"n": 0}

    def _fetch(**_):
        called["n"] += 1
        return "should not run"

    monkeypatch.setattr(
        "zab.services.conversation_ledger.content_enrichment.fetch_gmail_body",
        _fetch,
    )
    event = {
        "source": "gmail",
        "native_id": "x",
        "source_account": "mehdi@flowmetrik.com",
        "body": "already there",
    }
    enrich_event_content(event)
    assert called["n"] == 0


def test_gmail_normalizer_preserves_snippet_without_body() -> None:
    from zab.services.conversation_ledger.normalizers import normalize_gmail_message

    event = normalize_gmail_message(
        {
            "id": "msg-snippet",
            "threadId": "thread-snippet",
            "date": "2026-07-26 11:15",
            "from": "Alice Example <alice@example.com>",
            "subject": "Point projet",
            "snippet": "Bonjour, voici le détail demandé pour le point projet.",
            "labels": ["INBOX"],
        },
        channel={"channel_id": "gmail-flowmetrik-primary", "account": "mehdi@flowmetrik.com"},
    )

    assert event["body"] is None
    assert event["snippet"].startswith("Bonjour")
    assert event["summary"].startswith("Bonjour")
    assert event["actor"]["email"] == "alice@example.com"


def test_whatsapp_normalizer_extracts_extended_text_and_timestamp() -> None:
    from zab.services.conversation_ledger.normalizers import normalize_whatsapp_message

    event = normalize_whatsapp_message(
        {
            "key": {"id": "wa-1", "remoteJid": "33601020304@s.whatsapp.net", "fromMe": False},
            "pushName": "Alice",
            "messageTimestamp": 1785064500,
            "message": {"extendedTextMessage": {"text": "Message WhatsApp complet"}},
        },
        channel={"channel_id": "whatsapp-evolution-mehdi", "account": "mehdi-perso", "tool_id": "whatsapp-search"},
    )

    assert not validate_interaction_event(event)
    assert event["body"] == "Message WhatsApp complet"
    assert event["snippet"] == "Message WhatsApp complet"
    assert event["timestamp"].startswith("2026-07-26T")


def test_fireflies_normalizer_uses_structured_summary_and_sentences() -> None:
    from zab.services.conversation_ledger.normalizers import normalize_fireflies_meeting

    event = normalize_fireflies_meeting(
        {
            "id": "ff-1",
            "title": "Point client",
            "date": 1785064500000,
            "host": "Mehdi",
            "participants": ["alice@example.com"],
            "summary": {"overview": "Synthèse du rendez-vous", "action_items": ["Envoyer le compte rendu"]},
            "sentences": [{"speaker_name": "Alice", "text": "On valide la prochaine étape."}],
        },
        channel={"channel_id": "fireflies-flowmetrik", "account": "n/a", "tool_id": "fireflies-search"},
    )

    assert not validate_interaction_event(event)
    assert event["body"].startswith("Alice:")
    assert "Synthèse" in event["summary"]
    assert event["timestamp"].startswith("2026-07-26T")


def test_sync_channels_ingests_whatsapp(monkeypatch) -> None:
    from zab.services.conversation_ledger.sync import sync_channels

    channel = {
        "channel_id": "whatsapp-evolution-mehdi",
        "channel_type": "whatsapp",
        "label": "WhatsApp",
        "tool_id": "whatsapp-search",
        "account": "mehdi-perso",
        "enabled": True,
        "last_check_status": "ok",
    }
    monkeypatch.setattr(
        "zab.services.conversation_ledger.sync.list_channels",
        lambda check=True: {"summary": {"total": 1, "ok": 1, "degraded": 0, "error": 0}, "channels": [channel]},
    )
    monkeypatch.setattr(
        "zab.services.conversation_ledger.sync.check_channel_binding",
        lambda c: {**c, "last_check_status": "ok"},
    )
    monkeypatch.setattr(
        "zab.services.conversation_ledger.sync.fetch_whatsapp_recent",
        lambda *, limit: [
            {
                "key": {"id": "wa-sync-1", "remoteJid": "33601020304@s.whatsapp.net", "fromMe": False},
                "pushName": "Alice",
                "messageTimestamp": 1785064500,
                "message": {"conversation": "Signal WhatsApp à indexer"},
            }
        ],
    )

    payload = sync_channels(since="7d", sources=["whatsapp"], dry_run=True)

    assert payload["summary"]["channels_selected"] == 1
    assert payload["summary"]["events_created"] == 1
    assert payload["channels"][0]["fetched"] == 1
    assert payload["channels"][0]["stored"] == 1
