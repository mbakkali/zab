"""Tests for Conversation Ledger contracts and pipeline."""

from __future__ import annotations

import json
import urllib.request
from types import SimpleNamespace

from zab.services import local_db
from zab.services.conversation_ledger.clustering import cluster_events
from zab.services.conversation_ledger.eval import run_eval
from zab.services.conversation_ledger.schemas import (
    validate_interaction_event,
    validate_workpacket_canonical,
)
from zab.services.conversation_ledger.store import (
    compact_events_jsonl,
    get_event,
    upsert_event,
    upsert_projection,
    upsert_workpacket,
)
from zab.services.conversation_ledger.workpacket import build_from_cluster
from zab.services.conversation_ledger.workpacket_builder import (
    discover_workpackets,
    reconstruct_seed_candidates,
)
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


def test_unchanged_event_does_not_append_duplicate_journal_row(monkeypatch) -> None:
    appended: list[dict] = []
    monkeypatch.setattr(
        "zab.services.conversation_ledger.store.append_event_jsonl",
        lambda event: appended.append(event),
    )
    event = _event("dedup-journal", "Audit CRM follow-up")
    with local_db.transaction() as conn:
        upsert_event(conn, event)
        upsert_event(conn, event)
    assert len(appended) == 1


def test_compact_events_jsonl_rewrites_canonical_rows() -> None:
    with local_db.transaction() as conn:
        upsert_event(conn, _event("compact-1", "Audit CRM"))
        upsert_event(conn, _event("compact-2", "Explorateurs IA"))
        upsert_event(conn, _event("compact-1", "Audit CRM mis à jour"))
    preview = compact_events_jsonl(apply=False)
    applied = compact_events_jsonl(apply=True, archive=False)
    assert preview["event_count"] == 2
    assert applied["dry_run"] is False
    assert applied["bytes_after"] <= applied["bytes_before"]


def test_upsert_event_preserves_enriched_content_on_sync_refresh() -> None:
    enriched = {
        **_event("dedup-enriched", "Audit CRM follow-up"),
        "body": "Corps complet déjà récupéré.",
        "counterparties": ["Nicolas BONHOMME <nbonhomme@arp-astrance.com>"],
        "entity_links": [
            {
                "entity_type": "organization",
                "entity_id": "org_arp_astrance",
                "label": "ARP Astrance",
                "confidence": 0.9,
                "evidence": ["email domain arp-astrance.com"],
                "status": "confirmed",
            }
        ],
    }
    refresh = _event("dedup-enriched", "Audit CRM follow-up")
    refresh["counterparties"] = []

    with local_db.transaction() as conn:
        saved = upsert_event(conn, enriched)
        upsert_event(conn, refresh)
        stored = get_event(conn, saved["event_id"])

    assert stored is not None
    assert stored["body"] == "Corps complet déjà récupéré."
    assert stored["counterparties"] == ["Nicolas BONHOMME <nbonhomme@arp-astrance.com>"]
    assert stored["entity_links"][0]["entity_id"] == "org_arp_astrance"


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
        first = upsert_workpacket(
            conn, build_from_cluster(cluster, display_id="ZWP-0001")
        )
        first_id = first["workpacket_id"]
    payload = reconstruct_seed_candidates(dry_run=False)
    arp = next(
        w
        for w in payload["workpackets"]
        if w.get("client_workstream_id") == "cw_audit_crm"
    )
    assert arp["workpacket_id"] == first_id
    assert arp["display_id"] == "ZWP-0001"


def test_discover_reuses_existing_organization_workstream(monkeypatch) -> None:
    cluster = {
        "organization_id": "org_arp_astrance",
        "organization_label": "ARP Astrance",
        "client_workstream_id": "cw_audit_crm",
        "client_workstream_label": "Audit CRM",
        "events": [
            _event("discover-idempotent", "Audit outils et process commerciaux")
        ],
    }
    with local_db.transaction() as conn:
        upsert_event(conn, cluster["events"][0])
        first = upsert_workpacket(
            conn, build_from_cluster(cluster, display_id="ZWP-0042")
        )

    monkeypatch.setattr(
        "zab.services.conversation_ledger.workpacket_builder.cluster_events",
        lambda *_args, **_kwargs: [cluster],
    )
    payload = discover_workpackets(dry_run=False, min_confidence=0)
    match = next(
        row
        for row in payload["candidates"]
        if row["client_workstream_id"] == "cw_audit_crm"
    )

    assert match["workpacket_id"] == first["workpacket_id"]
    assert match["display_id"] == "ZWP-0042"
    assert match["_flowgo_created"] is False
    assert payload["created_count"] == 0
    assert payload["updated_count"] == 1


def test_discover_resolves_since_and_enforces_candidate_limit(monkeypatch) -> None:
    captured: dict[str, object] = {}
    clusters = [
        {
            "organization_id": f"org_{idx}",
            "organization_label": f"Organization {idx}",
            "client_workstream_id": f"cw_{idx}",
            "client_workstream_label": f"Workstream {idx}",
            "events": [_event(f"event-{idx}", f"Qualified action {idx}", f"cw_{idx}")],
        }
        for idx in range(4)
    ]

    def fake_list_events(_conn, **kwargs):
        captured.update(kwargs)
        return [event for cluster in clusters for event in cluster["events"]]

    monkeypatch.setattr(
        "zab.services.conversation_ledger.workpacket_builder.parse_since",
        lambda value: "2026-07-15" if value == "14d" else value,
    )
    monkeypatch.setattr(
        "zab.services.conversation_ledger.workpacket_builder.list_events",
        fake_list_events,
    )
    monkeypatch.setattr(
        "zab.services.conversation_ledger.workpacket_builder.cluster_events",
        lambda *_args, **_kwargs: clusters,
    )

    payload = discover_workpackets(since="14d", min_confidence=0, limit=2, dry_run=True)

    assert captured["since"] == "2026-07-15"
    assert payload["resolved_since"] == "2026-07-15"
    assert payload["limit"] == 2
    assert payload["candidate_count"] == 2


def test_reindex_infers_unique_contact_history() -> None:
    from zab.services.conversation_ledger.sync import reindex_entity_links

    classified = {
        **_event("known-contact", "Example client — point"),
        "thread_id": "thread-a",
        "source_account": "owner@internal.example",
        "actor": {
            "display_name": "Owner <owner@internal.example>",
            "email": "owner@internal.example",
        },
        "counterparties": ["Shared Contact <shared-contact@gmail.com>"],
        "organization_id": "org_example",
        "organization_label": "Example Client",
        "entity_links": [
            {
                "entity_type": "organization",
                "entity_id": "org_example",
                "label": "Example Client",
                "confidence": 1.0,
                "evidence": ["manual link"],
                "status": "confirmed",
            }
        ],
    }
    unclassified = {
        **_event("known-contact-followup", "Point de suivi"),
        "thread_id": "thread-b",
        "source_account": "owner@internal.example",
        "actor": {
            "display_name": "Owner <owner@internal.example>",
            "email": "owner@internal.example",
        },
        "counterparties": ["Shared Contact <shared-contact@gmail.com>"],
    }
    unclassified.pop("organization_id", None)
    with local_db.transaction() as conn:
        upsert_event(conn, classified)
        upsert_event(conn, unclassified)

    payload = reindex_entity_links()
    with local_db.transaction() as conn:
        saved = get_event(conn, unclassified["event_id"])

    assert payload["inferred_from_contact"] >= 1
    assert saved is not None
    assert saved["organization_id"] == "org_example"


def test_eval_hard_suite_passes() -> None:
    payload = run_eval(suite="hard")
    assert payload["hard"]["failed"] == 0


def test_eval_quality_thresholds() -> None:
    payload = run_eval(suite="quality")
    assert payload["quality"]["clustering_precision"] >= 0.80
    assert payload["quality"]["ambiguity_rate"] <= 0.35


def test_resolve_preview() -> None:
    from zab.services.conversation_ledger.resolve import resolve_preview

    payload = resolve_preview(
        organization="ARP Astrance", client_workstream="Audit CRM", dry_run=True
    )
    assert payload["contract"] == "interactions-resolve"
    assert payload["organization"]["id"] == "org_arp_astrance"


def test_entity_registry_seeded() -> None:
    from zab.services import local_db
    from zab.services.conversation_ledger.entity_registry import (
        list_organizations,
        list_workstreams,
    )

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


def test_gmail_sync_uses_all_pages_when_limit_exceeds_single_page(monkeypatch) -> None:
    from zab.services.conversation_ledger.sync import _run_gog_gmail

    captured: dict[str, list[str]] = {}

    def fake_run(cmd, **_kwargs):
        captured["cmd"] = list(cmd)
        return SimpleNamespace(
            returncode=0, stdout=json.dumps({"messages": [{"id": "1"}, {"id": "2"}]})
        )

    monkeypatch.setattr(
        "zab.services.conversation_ledger.sync.subprocess.run", fake_run
    )

    rows = _run_gog_gmail(
        {"account": "mehdi@flowmetrik.com"},
        since="2026-07-12",
        max_results=1200,
    )

    assert "--all" in captured["cmd"]
    assert len(rows) == 2


def test_fireflies_sync_uses_valid_transcript_query(monkeypatch) -> None:
    from zab.services.conversation_ledger.sync import _run_fireflies_search

    captured: dict[str, str] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "data": {
                        "transcripts": [
                            {
                                "id": "ff-1",
                                "title": "Meeting",
                                "date": 1785064500000,
                                "host": "host@example.com",
                                "participants": ["guest@example.com"],
                                "summary": {"overview": "Overview"},
                                "url": "https://example.test/transcript",
                            }
                        ]
                    }
                }
            ).encode("utf-8")

    def fake_urlopen(req, **_kwargs):
        body = json.loads(req.data.decode("utf-8"))
        captured["query"] = body["query"]
        return FakeResponse()

    monkeypatch.setenv("FIREFLIES_API_KEY", "test-key")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    rows = _run_fireflies_search({"account": "n/a"}, limit=1)

    assert "host: host_email" in captured["query"]
    assert "url: transcript_url" in captured["query"]
    assert "summary {" in captured["query"]
    assert rows[0]["summary"]["overview"] == "Overview"


def test_calendar_sync_uses_since_and_all_pages(monkeypatch) -> None:
    from zab.services.conversation_ledger.sync import _run_gog_calendar

    captured: dict[str, list[str]] = {}

    def fake_run(cmd, **_kwargs):
        captured["cmd"] = list(cmd)
        return SimpleNamespace(returncode=0, stdout=json.dumps({"events": []}))

    monkeypatch.setattr(
        "zab.services.conversation_ledger.sync.subprocess.run", fake_run
    )
    _run_gog_calendar(
        {"account": "mehdi@example.com"},
        since="2026-01-01",
        max_results=500,
    )

    assert captured["cmd"][-1] == "--all-pages"
    assert "--from" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("--from") + 1] == "2026-01-01"
    assert captured["cmd"][captured["cmd"].index("--max") + 1] == "500"


def test_calendar_normalizer_indexes_organizer_and_attendees() -> None:
    from zab.services.conversation_ledger.normalizers import normalize_calendar_event

    event = normalize_calendar_event(
        {
            "id": "calendar-1",
            "summary": "Steering committee",
            "start": {"dateTime": "2026-07-29T09:00:00+02:00"},
            "organizer": {"email": "owner@example.com", "displayName": "Owner"},
            "attendees": [{"email": "guest@client.example", "displayName": "Guest"}],
        },
        channel={
            "channel_id": "calendar-primary",
            "account": "owner@example.com",
            "tool_id": "calendar-search",
        },
    )

    assert event["actor"]["email"] == "owner@example.com"
    assert "guest@client.example" in event["counterparties"]


def test_local_entity_profile_document_merges_without_repository_data(tmp_path) -> None:
    from zab.services.conversation_ledger.org_profiles import (
        _local_profile_document,
        _merge_profiles,
    )

    config = tmp_path / "entities.yaml"
    config.write_text(
        """
internal_domains: [internal.example]
organizations:
  org_example:
    label: Example
    domains: [client.example]
    workstreams:
      cw_example:
        label: Delivery
        keywords: [delivery]
""".strip(),
        encoding="utf-8",
    )
    document = _local_profile_document(config)
    merged = _merge_profiles({}, document)

    assert document["internal_domains"] == ["internal.example"]
    assert merged["org_example"]["domains"] == ["client.example"]
    assert merged["org_example"]["workstreams"]["cw_example"]["keywords"] == [
        "delivery"
    ]


def test_enrich_gmail_event_adds_body(monkeypatch) -> None:
    from zab.services.conversation_ledger.content_enrichment import enrich_event_content

    event = {
        "event_id": "gmail:abc123",
        "source": "gmail",
        "native_id": "abc123",
        "channel_id": "gmail-flowmetrik-primary",
        "source_account": "mehdi@flowmetrik.com",
        "title": "Sujet test",
        "snippet": "Sujet test",
    }

    monkeypatch.setattr(
        "zab.services.conversation_ledger.content_enrichment.fetch_gmail_message_details",
        lambda **_: {
            "id": "abc123",
            "threadId": "thread-abc123",
            "date": "2026-07-26 11:15",
            "from": "Mehdi <mehdi@flowmetrik.com>",
            "subject": "Sujet test",
            "body": "Corps complet du mail avec détails contractuels.",
            "snippet": "Corps complet du mail avec détails contractuels.",
            "labels": ["SENT"],
            "headers": {"to": "Alice Example <alice@example.com>"},
        },
    )
    enriched = enrich_event_content(event)
    assert enriched["body"].startswith("Corps complet")
    assert enriched["snippet"].startswith("Corps complet")
    assert enriched["counterparties"] == ["Alice Example <alice@example.com>"]


def test_enrich_skips_when_body_present(monkeypatch) -> None:
    from zab.services.conversation_ledger.content_enrichment import enrich_event_content

    called = {"n": 0}

    def _fetch(**_):
        called["n"] += 1
        return {"body": "should not run"}

    monkeypatch.setattr(
        "zab.services.conversation_ledger.content_enrichment.fetch_gmail_message_details",
        _fetch,
    )
    event = {
        "source": "gmail",
        "native_id": "x",
        "source_account": "mehdi@flowmetrik.com",
        "body": "already there",
        "counterparties": ["alice@example.com"],
    }
    enrich_event_content(event)
    assert called["n"] == 0


def test_enrich_gmail_event_fetches_missing_counterparties(monkeypatch) -> None:
    from zab.services.conversation_ledger.content_enrichment import enrich_event_content

    event = {
        "event_id": "gmail:abc124",
        "source": "gmail",
        "native_id": "abc124",
        "channel_id": "gmail-flowmetrik-primary",
        "source_account": "mehdi@flowmetrik.com",
        "title": "Point plateforme",
        "snippet": "Point plateforme",
        "body": "Corps déjà enrichi.",
        "actor": {
            "display_name": "Mehdi <mehdi@flowmetrik.com>",
            "email": "mehdi@flowmetrik.com",
        },
    }

    monkeypatch.setattr(
        "zab.services.conversation_ledger.content_enrichment.fetch_gmail_message_details",
        lambda **_: {
            "id": "abc124",
            "threadId": "thread-abc124",
            "date": "2026-07-26 11:15",
            "from": "Mehdi <mehdi@flowmetrik.com>",
            "subject": "Point plateforme",
            "body": None,
            "snippet": "Point plateforme",
            "labels": ["SENT"],
            "headers": {"to": "Yannis CAUBET <yannis.caubet@agile.immo>"},
        },
    )

    enriched = enrich_event_content(event)

    assert enriched["body"] == "Corps déjà enrichi."
    assert enriched["counterparties"] == ["Yannis CAUBET <yannis.caubet@agile.immo>"]
    assert enriched["organization_id"] == "org_agile_immo"


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
        channel={
            "channel_id": "gmail-flowmetrik-primary",
            "account": "mehdi@flowmetrik.com",
        },
    )

    assert event["body"] is None
    assert event["snippet"].startswith("Bonjour")
    assert event["summary"].startswith("Bonjour")
    assert event["actor"]["email"] == "alice@example.com"


def test_gmail_normalizer_uses_recipient_headers_for_counterparties() -> None:
    from zab.services.conversation_ledger.normalizers import normalize_gmail_message

    event = normalize_gmail_message(
        {
            "id": "msg-recipients",
            "threadId": "thread-recipients",
            "date": "2026-07-26 11:15",
            "from": "Mehdi <mehdi@flowmetrik.com>",
            "subject": "Point client",
            "snippet": "Bonjour, voici le point.",
            "labels": ["SENT"],
            "headers": {
                "to": "Yannis CAUBET <yannis.caubet@agile.immo>",
                "cc": "Samir BOUZIDI <samir.bouzidi@ofi-invest.com>",
            },
        },
        channel={
            "channel_id": "gmail-flowmetrik-primary",
            "account": "mehdi@flowmetrik.com",
        },
    )

    assert event["counterparties"] == [
        "Yannis CAUBET <yannis.caubet@agile.immo>",
        "Samir BOUZIDI <samir.bouzidi@ofi-invest.com>",
    ]


def test_whatsapp_normalizer_extracts_extended_text_and_timestamp() -> None:
    from zab.services.conversation_ledger.normalizers import normalize_whatsapp_message

    event = normalize_whatsapp_message(
        {
            "key": {
                "id": "wa-1",
                "remoteJid": "33601020304@s.whatsapp.net",
                "fromMe": False,
            },
            "pushName": "Alice",
            "messageTimestamp": 1785064500,
            "message": {"extendedTextMessage": {"text": "Message WhatsApp complet"}},
        },
        channel={
            "channel_id": "whatsapp-evolution-mehdi",
            "account": "mehdi-perso",
            "tool_id": "whatsapp-search",
        },
    )

    assert not validate_interaction_event(event)
    assert event["body"] == "Message WhatsApp complet"
    assert event["snippet"] == "Message WhatsApp complet"
    assert event["timestamp"].startswith("2026-07-26T")


def test_evolution_preflight_rejects_unresolved_dashlane_references(
    monkeypatch,
) -> None:
    from zab.services.conversation_ledger.preflight import check_evolution

    monkeypatch.setenv("EVOLUTION_API_URL", "dl://missing-url")
    monkeypatch.setenv("EVOLUTION_API_KEY", "dl://missing-key")
    monkeypatch.setenv("EVOLUTION_INSTANCE", "dl://missing-instance")

    payload = check_evolution()

    assert payload["status"] == "error"
    assert "unresolved Dashlane references" in payload["detail"]


def test_fireflies_normalizer_uses_structured_summary_and_sentences() -> None:
    from zab.services.conversation_ledger.normalizers import normalize_fireflies_meeting

    event = normalize_fireflies_meeting(
        {
            "id": "ff-1",
            "title": "Point client",
            "date": 1785064500000,
            "host": "Mehdi",
            "participants": ["alice@example.com"],
            "summary": {
                "overview": "Synthèse du rendez-vous",
                "action_items": ["Envoyer le compte rendu"],
            },
            "sentences": [
                {"speaker_name": "Alice", "text": "On valide la prochaine étape."}
            ],
        },
        channel={
            "channel_id": "fireflies-flowmetrik",
            "account": "n/a",
            "tool_id": "fireflies-search",
        },
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
        lambda check=True: {
            "summary": {"total": 1, "ok": 1, "degraded": 0, "error": 0},
            "channels": [channel],
        },
    )
    monkeypatch.setattr(
        "zab.services.conversation_ledger.sync.check_channel_binding",
        lambda c: {**c, "last_check_status": "ok"},
    )
    monkeypatch.setattr(
        "zab.services.conversation_ledger.sync.fetch_whatsapp_recent",
        lambda *, limit: [
            {
                "key": {
                    "id": "wa-sync-1",
                    "remoteJid": "33601020304@s.whatsapp.net",
                    "fromMe": False,
                },
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
