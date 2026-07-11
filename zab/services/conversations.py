"""Agrégation conversations multi-provider : discovery locale, health Postgres, index compact."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, FrozenSet

from zab.paths import data_dir
from zab.services import memory_db
from zab.services.agent_memory_import import (
    ALL_CONVERSATION_PROVIDERS,
    PROVIDER_CLAUDE,
    PROVIDER_CODEX,
    PROVIDER_CURSOR,
    PROVIDER_GEMINI,
    PROVIDER_HERMES,
    PROVIDER_KIMI,
    discover_gemini_cli_status,
    discover_provider_dry_run_summary,
)

CONVERSATIONS_INDEX = "conversations-index.json"

PROVIDER_ORDER = (
    PROVIDER_CURSOR,
    PROVIDER_CLAUDE,
    PROVIDER_CODEX,
    PROVIDER_HERMES,
    PROVIDER_GEMINI,
    PROVIDER_KIMI,
)


def conversations_index_path() -> Path:
    return data_dir() / CONVERSATIONS_INDEX


def _load_index() -> dict[str, Any]:
    p = conversations_index_path()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def write_conversations_index(payload: dict[str, Any]) -> None:
    """Écriture atomique de l’index compact (chemins, dernier sync)."""
    p = conversations_index_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".tmp.{os.getpid()}.json")
    body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(p)


def _postgres_counts_by_slug() -> dict[str, int]:
    raw = memory_db.fetch_conversation_provider_document_counts()
    return {k: int(raw.get(k, 0)) for k in PROVIDER_ORDER}


def _provider_status(
    slug: str,
    local: dict[str, Any],
    pg_count: int,
) -> dict[str, Any]:
    """missing | detected | ready | synced | unsupported | error"""
    if slug == PROVIDER_GEMINI:
        g = discover_gemini_cli_status()
        if not g.get("present"):
            st = "missing"
        elif g.get("status") == "ready":
            st = "ready" if pg_count == 0 else "synced"
        elif g.get("status") == "unsupported_format":
            st = "unsupported"
        else:
            st = "detected"
        return {
            "id": slug,
            "status": st,
            "postgres_documents": pg_count,
            "local": g,
            "label": _label(slug),
        }

    loc = local.get("providers", {}).get(slug, {})
    detected = bool(loc.get("paths_detected") or loc.get("state_db_present") or loc.get("jsonl_files", 0) > 0 or loc.get("agent_transcript_jsonl", 0) > 0 or loc.get("session_jsonl", 0) > 0)

    if slug == PROVIDER_HERMES:
        detected = bool(loc.get("state_db_present"))
        if pg_count > 0:
            st = "synced"
        elif not detected:
            st = "missing"
        elif (loc.get("session_rows_estimate") or 0) > 0:
            st = "ready"
        else:
            st = "detected"
    elif slug == PROVIDER_CURSOR:
        if not loc.get("paths_detected"):
            st = "missing"
        elif pg_count > 0:
            st = "synced"
        elif (loc.get("agent_transcript_jsonl") or 0) > 0:
            st = "ready"
        else:
            st = "detected"
    elif slug in (PROVIDER_CLAUDE, PROVIDER_CODEX, PROVIDER_KIMI):
        if not loc.get("paths_detected"):
            st = "missing"
        elif pg_count > 0:
            st = "synced"
        elif (loc.get("jsonl_files") or loc.get("session_jsonl") or 0) > 0 or loc.get("history_jsonl"):
            st = "ready"
        else:
            st = "detected"
    else:
        st = "missing"

    return {
        "id": slug,
        "status": st,
        "postgres_documents": pg_count,
        "local": loc,
        "label": _label(slug),
    }


def _label(slug: str) -> str:
    return {
        PROVIDER_CURSOR: "Cursor",
        PROVIDER_CLAUDE: "Claude Code",
        PROVIDER_CODEX: "Codex",
        PROVIDER_HERMES: "Hermes",
        PROVIDER_GEMINI: "Gemini CLI",
        PROVIDER_KIMI: "Kimi",
    }.get(slug, slug)


def build_providers_payload() -> dict[str, Any]:
    local = discover_provider_dry_run_summary()
    idx = _load_index()
    pg = _postgres_counts_by_slug()
    failed = idx.get("summary", {}).get("failed_providers", {})
    failed_providers = failed if isinstance(failed, dict) else {}
    providers = [_provider_status(s, local, pg.get(s, 0)) for s in PROVIDER_ORDER]
    for provider in providers:
        err = failed_providers.get(provider["id"])
        if isinstance(err, str) and err:
            if int(provider.get("postgres_documents") or 0) > 0:
                provider["local"] = {**provider.get("local", {}), "last_sync_warning": err}
            else:
                provider["status"] = "error"
                provider["local"] = {**provider.get("local", {}), "last_sync_error": err}
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "providers": providers,
        "compact_index": {
            "path": str(conversations_index_path()),
            "last_batch": idx.get("last_batch"),
            "updated_at_utc": idx.get("updated_at_utc"),
        },
    }


def build_health_payload() -> dict[str, Any]:
    st = memory_db.fetch_status()
    recs: list[dict[str, str]] = []
    severity = "ok"
    idx = _load_index()

    if not st.get("configured"):
        severity = "fail"
        recs.append({
            "id": "configure_postgres",
            "message": "Définir ZAB_MEMORY_DATABASE_URL (ou l’alias legacy MEHDI_MEMORY_DATABASE_URL).",
        })
    elif not st.get("psycopg_available"):
        severity = "fail"
        recs.append({"id": "install_memory_extra", "message": "Installer psycopg : uv sync --extra memory"})
    elif not st.get("connected"):
        severity = "fail"
        detail = st.get("error") or "Connexion Postgres impossible."
        recs.append({"id": "fix_postgres", "message": detail})
        rid = st.get("remediation_id")
        extra_hints: dict[str, str] = {
            "apply_gateway_migrations": "Étapes : créer une base dédiée puis `apply_migrations.sh` (mehdi_mcp_memory).",
            "create_database_or_fix_dsn": "Après `createdb`, appliquer les migrations puis redémarrer `zab dashboard`.",
            "fix_pg_ssl": "DSN : tester `sslmode=require` ou `prefer` selon votre hébergement.",
            "fix_pg_credentials": "Regénérez ou corrigez le mot de passe côté rôle Postgres et dans le `.env`.",
            "ensure_postgres_running": "Lancer Postgres localement ou `cloud-sql-proxy INSTANCE` puis relancer zab dashboard.",
            "fix_pg_host": "Corriger host/port dans le DSN ou les règles réseau / VPC.",
        }
        if isinstance(rid, str) and rid in extra_hints and rid != "apply_gateway_migrations":
            recs.append({"id": rid, "message": extra_hints[rid]})
    else:
        ch = memory_db.fetch_conversation_data_health()
        doc_n = ch.get("document_total", 0)
        if doc_n == 0:
            severity = "warn"
            recs.append({"id": "run_sync", "message": "Base vide : lancer une synchronisation conversations."})
        if ch.get("documents_without_chunks", 0) > 0:
            severity = "warn" if severity == "ok" else severity
            recs.append(
                {
                    "id": "integrity_docs_without_chunks",
                    "message": f"{ch['documents_without_chunks']} document(s) sans chunks.",
                }
            )
        if ch.get("orphan_chunks", 0) > 0:
            severity = "warn" if severity == "ok" else severity
            recs.append({"id": "integrity_orphan_chunks", "message": f"{ch['orphan_chunks']} chunk(s) orphelins."})

        g = discover_gemini_cli_status()
        if g.get("present") and g.get("status") == "unsupported_format":
            recs.append(
                {
                    "id": "enable_provider_support",
                    "message": "Gemini CLI détecté mais aucun JSONL transcript exploitable.",
                }
            )
            if severity == "ok":
                severity = "warn"

        if doc_n > 0 and severity == "ok":
            recs.append(
                {
                    "id": "run_mempalace_optional",
                    "message": "Optionnel : indexer dans MemPalace pour recherche sémantique (job mempalace).",
                }
            )

        failed = idx.get("summary", {}).get("failed_providers", {})
        if isinstance(failed, dict) and failed:
            pg_counts = _postgres_counts_by_slug()
            for provider, message in sorted(failed.items()):
                pg_count = int(pg_counts.get(str(provider), 0) or 0)
                if pg_count > 0:
                    continue
                severity = "warn" if severity == "ok" else severity
                recs.append(
                    {
                        "id": f"provider_sync_failed_{provider}",
                        "message": f"Provider {provider} non resynchronisé : {message}",
                    }
                )

        return {
            "severity": severity,
            "postgres": st,
            "integrity": ch if st.get("connected") else None,
            "recommendations": recs,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        }

    return {
        "severity": severity,
        "postgres": st,
        "integrity": None,
        "recommendations": recs,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def record_sync_index(*, batch_id: str, summary: dict[str, Any], providers: FrozenSet[str] | None) -> None:
    """Met à jour l’index compact après sync."""
    discover = discover_provider_dry_run_summary(providers=providers)
    write_conversations_index(
        {
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            "last_batch": batch_id,
            "summary": summary,
            "discovery": discover,
        }
    )


def parse_providers_arg(raw: list[str] | None) -> FrozenSet[str] | None:
    if not raw:
        return None
    allowed = ALL_CONVERSATION_PROVIDERS
    out = {p.strip().lower() for p in raw if p.strip()}
    unknown = out - allowed
    if unknown:
        raise ValueError(f"providers inconnus : {sorted(unknown)} (autorisés : {sorted(allowed)})")
    return frozenset(out)
