"""Lecture seule Postgres mehdi_memory_* (MEHDI_MEMORY_DATABASE_URL)."""

from __future__ import annotations

import os
import re
import uuid
from typing import Any

from zab.paths import skills_root, skills_root_from_config_file_only
from zab.services.conversations_archive import ensure_conversations_archive_schema
from zab.services.memory_scan import resolve_mehdi_memory_database_url

_MAX_DOCS = 100
_MAX_CHUNKS = 100
_CONTENT_PREVIEW = 2000
_SEARCH_PREVIEW = 1200
_CONVERSATION_SOURCES = (
    "cursor_agent_transcript",
    "claude_code_transcript",
    "codex_transcript",
    "kimi_transcript",
    "hermes_transcript",
    "gemini_cli_transcript",
    "agent_context_artifact",
)

# Sources présentes dans `zab_conversations` (transcripts seulement).
_ARCHIVE_CONVERSATION_SOURCES = (
    "cursor_agent_transcript",
    "claude_code_transcript",
    "codex_transcript",
    "kimi_transcript",
    "hermes_transcript",
    "gemini_cli_transcript",
)


def _pg_connect_timeout() -> int:
    """Secondes avant timeout TCP (borne 3–120) ; ZAB_PG_CONNECT_TIMEOUT."""
    raw = os.environ.get("ZAB_PG_CONNECT_TIMEOUT", "12").strip()
    try:
        return max(3, min(120, int(raw)))
    except ValueError:
        return 12


def _postgres_failure_metadata(exc: BaseException) -> tuple[str, str | None]:
    """Message utilisateur avec exception + id de remediation optionnel."""
    full_raw = str(exc).strip()
    first_line = full_raw.split("\n")[0]
    if len(first_line) > 260:
        first_line = first_line[:257] + "…"

    cls = type(exc).__name__
    base = (
        "Connexion ou requête Postgres impossible."
        f" Détail technique : [{cls}] {first_line}"
    )

    sqlstate: str | None = None
    try:
        import psycopg

        if isinstance(exc, psycopg.Error):
            diag = getattr(exc, "diag", None)
            if diag is not None:
                raw_st = getattr(diag, "sqlstate", None)
                sqlstate = raw_st if isinstance(raw_st, str) else None
    except ImportError:
        pass

    low = first_line.lower()
    full_lower = full_raw.lower()
    rem: str | None = None

    db_match = re.search(r'database\s+"([^"]+)"\s+does not exist', full_lower)
    if db_match:
        rem = "create_database_or_fix_dsn"
        db_name = db_match.group(1)
        base += (
            f' La base `{db_name}` n’existe pas sur ce serveur Postgres — créez-la '
            f'(ex. localement : `createdb {db_name}` avec le même utilisateur que dans le DSN) '
            "ou changez le nom de base dans MEHDI_MEMORY_DATABASE_URL "
            "(documentation zab : base dédiée du type `mehdi_mcp_memory`). "
            "Ensuite appliquez les migrations gateway avant la sync conversations."
        )
        return base, rem

    schema_missing = sqlstate == "42P01" or (
        "does not exist" in low and ("mehdi_memory" in low or "relation " in low)
    )
    if schema_missing:
        rem = "apply_gateway_migrations"
        base += (
            " Les tables mémoire MCP ne sont pas créées — exécutez les migrations gateway "
            "depuis votre dépôt skills : mcps/flowmetrik-gateway/apply_migrations.sh "
            "(cf. README zab § « Mémoire MCP »)."
        )
    elif "password authentication failed" in low:
        rem = "fix_pg_credentials"
        base += " Vérifiez utilisateur / mot de passe dans MEHDI_MEMORY_DATABASE_URL."
    elif "certificate verify failed" in low or "endpoint identification failed" in low:
        rem = "fix_pg_ssl"
        base += " Ajustez sslmode dans le DSN (souvent ?sslmode=require pour un hôte managé)."
    elif "could not translate host name" in low or "name or service not known" in low:
        rem = "fix_pg_host"
    elif (
        "connection refused" in low
        or "could not connect to server" in low
        or ("permission denied" in low and "socket" in low)
    ):
        rem = "ensure_postgres_running"
        base += " Instance ou proxy Postgres injoignable (port, Cloud SQL Proxy, socket unix)."

    return base, rem


def _url_or_none() -> str | None:
    for anchor in (skills_root_from_config_file_only(), skills_root()):
        url = resolve_mehdi_memory_database_url(anchor)
        if url:
            return url
    return None


def memory_psycopg_available() -> bool:
    try:
        import psycopg  # noqa: F401
    except ImportError:
        return False
    return True


def fetch_status() -> dict[str, Any]:
    url = _url_or_none()
    if not url:
        return {
            "configured": False,
            "connected": False,
            "psycopg_available": memory_psycopg_available(),
            "document_count": None,
            "chunk_count": None,
            "error": "MEHDI_MEMORY_DATABASE_URL non défini (processus ou fichier .env du dépôt skills).",
            "remediation_id": None,
        }
    if not memory_psycopg_available():
        return {
            "configured": True,
            "connected": False,
            "psycopg_available": False,
            "document_count": None,
            "chunk_count": None,
            "error": "Installer le extra optionnel : uv sync --extra memory",
            "remediation_id": None,
        }
    import psycopg

    try:
        with psycopg.connect(url, connect_timeout=_pg_connect_timeout()) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM mehdi_memory_documents")
                doc_n = int(cur.fetchone()[0])
                cur.execute("SELECT count(*) FROM mehdi_memory_chunks")
                chunk_n = int(cur.fetchone()[0])
        return {
            "configured": True,
            "connected": True,
            "psycopg_available": True,
            "document_count": doc_n,
            "chunk_count": chunk_n,
            "error": None,
            "remediation_id": None,
        }
    except Exception as exc:
        msg, remediation = _postgres_failure_metadata(exc)
        return {
            "configured": True,
            "connected": False,
            "psycopg_available": True,
            "document_count": None,
            "chunk_count": None,
            "error": msg,
            "remediation_id": remediation,
        }


def fetch_documents(*, limit: int, offset: int) -> list[dict[str, Any]]:
    url = _url_or_none()
    if not url or not memory_psycopg_available():
        return []
    lim = max(1, min(int(limit), _MAX_DOCS))
    off = max(0, int(offset))
    import psycopg

    try:
        with psycopg.connect(url, connect_timeout=_pg_connect_timeout()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, source, export_batch_id, wing, room, synced_at, metadata
                    FROM mehdi_memory_documents
                    ORDER BY synced_at DESC NULLS LAST, id DESC
                    LIMIT %s OFFSET %s
                    """,
                    (lim, off),
                )
                rows = cur.fetchall()
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        meta = r[6]
        if hasattr(meta, "data"):
            meta = meta.data  # type: ignore[union-attr]
        out.append(
            {
                "id": str(r[0]),
                "source": r[1],
                "export_batch_id": r[2],
                "wing": r[3],
                "room": r[4],
                "synced_at": r[5].isoformat() if r[5] is not None else None,
                "metadata": meta,
            }
        )
    return out


def fetch_chunks_for_document(document_id: str, *, limit: int) -> list[dict[str, Any]]:
    url = _url_or_none()
    if not url or not memory_psycopg_available():
        return []
    try:
        uuid.UUID(document_id)
    except ValueError:
        return []
    lim = max(1, min(int(limit), _MAX_CHUNKS))
    import psycopg

    try:
        with psycopg.connect(url, connect_timeout=_pg_connect_timeout()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, document_id, left(content, %s) AS excerpt, chunk_index, created_at
                    FROM mehdi_memory_chunks
                    WHERE document_id = %s::uuid
                    ORDER BY chunk_index ASC, id ASC
                    LIMIT %s
                    """,
                    (_CONTENT_PREVIEW, document_id, lim),
                )
                rows = cur.fetchall()
    except Exception:
        return []
    return [
        {
            "id": str(r[0]),
            "document_id": str(r[1]),
            "content_excerpt": r[2],
            "chunk_index": r[3],
            "created_at": r[4].isoformat() if r[4] is not None else None,
        }
        for r in rows
    ]


def search_memory(
    query: str,
    *,
    limit: int = 10,
    source: str | None = None,
    wing: str | None = None,
) -> list[dict[str, Any]]:
    """Recherche texte simple dans les chunks Postgres (source de vérité zab)."""
    url = _url_or_none()
    q = (query or "").strip()
    if not url or not memory_psycopg_available() or not q:
        return []
    lim = max(1, min(int(limit), 50))
    import psycopg

    terms = [t for t in re.split(r"\s+", q) if len(t) >= 2][:8] or [q]
    clauses = ["(" + " AND ".join("c.content ILIKE %s" for _ in terms) + ")"]
    where_params: list[Any] = [f"%{t}%" for t in terms]
    if source:
        clauses.append("d.source = %s")
        where_params.append(source)
    if wing:
        clauses.append("d.wing ILIKE %s")
        where_params.append(f"%{wing}%")
    where = " AND ".join(clauses)
    try:
        with psycopg.connect(url, connect_timeout=_pg_connect_timeout()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        d.id,
                        c.id,
                        d.source,
                        d.export_batch_id,
                        d.wing,
                        d.room,
                        d.metadata,
                        c.chunk_index,
                        left(c.content, %s) AS excerpt,
                        c.created_at
                    FROM mehdi_memory_chunks c
                    JOIN mehdi_memory_documents d ON d.id = c.document_id
                    WHERE {where}
                    ORDER BY
                        CASE WHEN d.wing ILIKE %s THEN 0 ELSE 1 END,
                        d.synced_at DESC NULLS LAST,
                        c.created_at DESC NULLS LAST,
                        c.chunk_index ASC
                    LIMIT %s
                    """,
                    (_SEARCH_PREVIEW, *where_params, f"%{q}%", lim),
                )
                rows = cur.fetchall()
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        meta = r[6]
        if hasattr(meta, "data"):
            meta = meta.data  # type: ignore[union-attr]
        out.append(
            {
                "document_id": str(r[0]),
                "chunk_id": str(r[1]),
                "source": r[2],
                "export_batch_id": r[3],
                "wing": r[4],
                "room": r[5],
                "metadata": meta,
                "path": meta.get("path") if isinstance(meta, dict) else None,
                "chunk_index": r[7],
                "content_excerpt": r[8],
                "created_at": r[9].isoformat() if r[9] is not None else None,
            }
        )
    return out


def fetch_document_detail(document_id: str, *, chunk_limit: int = 100) -> dict[str, Any] | None:
    """Document + chunks, pour `zab memory show` et l'API."""
    url = _url_or_none()
    if not url or not memory_psycopg_available():
        return None
    try:
        uuid.UUID(document_id)
    except ValueError:
        return None
    import psycopg

    lim = max(1, min(int(chunk_limit), 500))
    try:
        with psycopg.connect(url, connect_timeout=_pg_connect_timeout()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, source, export_batch_id, wing, room, synced_at, metadata, created_at
                    FROM mehdi_memory_documents
                    WHERE id = %s::uuid
                    """,
                    (document_id,),
                )
                doc = cur.fetchone()
                if not doc:
                    return None
                cur.execute(
                    """
                    SELECT id, document_id, content, metadata, chunk_index, created_at
                    FROM mehdi_memory_chunks
                    WHERE document_id = %s::uuid
                    ORDER BY chunk_index ASC, id ASC
                    LIMIT %s
                    """,
                    (document_id, lim),
                )
                chunks = cur.fetchall()
    except Exception:
        return None
    meta = doc[6]
    if hasattr(meta, "data"):
        meta = meta.data  # type: ignore[union-attr]
    return {
        "id": str(doc[0]),
        "source": doc[1],
        "export_batch_id": doc[2],
        "wing": doc[3],
        "room": doc[4],
        "synced_at": doc[5].isoformat() if doc[5] is not None else None,
        "metadata": meta,
        "path": meta.get("path") if isinstance(meta, dict) else None,
        "created_at": doc[7].isoformat() if doc[7] is not None else None,
        "chunks": [
            {
                "id": str(r[0]),
                "document_id": str(r[1]),
                "content": r[2],
                "metadata": r[3],
                "chunk_index": r[4],
                "created_at": r[5].isoformat() if r[5] is not None else None,
            }
            for r in chunks
        ],
    }


def _coerce_jsonb_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if hasattr(value, "data"):
        d = getattr(value, "data", None)
        return list(d) if isinstance(d, list) else []
    return []


def fetch_conversation_document_detail(document_id: str, *, chunk_limit: int = 100) -> dict[str, Any] | None:
    """Détail conversation : archive `zab_conversations` + chunks index (debug)."""
    try:
        uid = uuid.UUID(document_id)
    except ValueError:
        return None
    url = _url_or_none()
    if not url or not memory_psycopg_available():
        return None
    import psycopg

    lim = max(1, min(int(chunk_limit), 500))
    try:
        with psycopg.connect(url, connect_timeout=_pg_connect_timeout()) as conn:
            with conn.cursor() as cur:
                ensure_conversations_archive_schema(cur)
                cur.execute(
                    """
                    SELECT id, source, wing, room, synced_at, metadata, title,
                           raw_events, messages, source_path, created_at
                    FROM zab_conversations
                    WHERE id = %s::uuid
                    """,
                    (str(uid),),
                )
                zrow = cur.fetchone()
                if zrow:
                    (
                        z_id,
                        source,
                        wing,
                        room,
                        synced_at,
                        zmeta,
                        title,
                        raw_events,
                        messages,
                        source_path,
                        created_at,
                    ) = zrow
                    meta = zmeta
                    if hasattr(meta, "data"):
                        meta = meta.data  # type: ignore[union-attr]
                    if not isinstance(meta, dict):
                        meta = {}
                    msg_list = _coerce_jsonb_list(messages)
                    raw_list = _coerce_jsonb_list(raw_events)
                    cur.execute(
                        """
                        SELECT c.id, c.document_id, c.content, c.metadata, c.chunk_index, c.created_at
                        FROM mehdi_memory_documents d
                        JOIN mehdi_memory_chunks c ON c.document_id = d.id
                        WHERE d.metadata->>'conversation_id' = %s
                        ORDER BY c.chunk_index ASC, c.id ASC
                        LIMIT %s
                        """,
                        (str(z_id), lim),
                    )
                    chunks = cur.fetchall()
                    path_out = meta.get("path") or (str(source_path) if source_path else "")
                    meta_out = {**meta, "messages": msg_list}
                    if title:
                        meta_out["title"] = title
                    return {
                        "id": str(z_id),
                        "source": source,
                        "export_batch_id": meta.get("export_batch_id"),
                        "wing": wing,
                        "room": room,
                        "synced_at": synced_at.isoformat() if synced_at is not None else None,
                        "metadata": meta_out,
                        "path": path_out,
                        "created_at": created_at.isoformat() if created_at is not None else None,
                        "chunks": [
                            {
                                "id": str(cr[0]),
                                "document_id": str(cr[1]),
                                "content": cr[2],
                                "metadata": cr[3],
                                "chunk_index": cr[4],
                                "created_at": cr[5].isoformat() if cr[5] is not None else None,
                            }
                            for cr in chunks
                        ],
                        "messages": msg_list,
                        "raw_events": raw_list,
                    }
    except Exception:
        pass
    return fetch_document_detail(document_id, chunk_limit=chunk_limit)


def _conversation_provider_sql(alias: str, provider: str | None) -> tuple[str, list[Any]]:
    """Filtre slug dashboard -> SQL sur documents."""
    if not provider or not str(provider).strip():
        return "", []
    p = str(provider).strip().lower()
    a = alias
    if p == "cursor":
        return (
            f" AND ({a}.source = %s OR ({a}.source = %s AND {a}.wing ILIKE %s))",
            ["cursor_agent_transcript", "agent_context_artifact", "cursor%"],
        )
    if p == "claude":
        return (f" AND {a}.source = %s", ["claude_code_transcript"])
    if p == "codex":
        return (
            f" AND ({a}.source = %s OR ({a}.source = %s AND {a}.wing ILIKE %s))",
            ["codex_transcript", "agent_context_artifact", "codex%"],
        )
    if p == "kimi":
        return (
            f" AND ({a}.source = %s OR ({a}.source = %s AND {a}.wing ILIKE %s))",
            ["kimi_transcript", "agent_context_artifact", "kimi%"],
        )
    if p == "hermes":
        return (f" AND {a}.source = %s", ["hermes_transcript"])
    if p in ("gemini", "gemini_cli"):
        return (f" AND {a}.source = %s", ["gemini_cli_transcript"])
    return (f" AND {a}.source = %s", [provider])


def _conversation_archive_provider_sql(alias: str, provider: str | None) -> tuple[str, list[Any]]:
    """Filtre slug dashboard -> colonne `provider` de `zab_conversations`."""
    if not provider or not str(provider).strip():
        return "", []
    p = str(provider).strip().lower()
    if p == "gemini_cli":
        p = "gemini"
    a = alias
    if p in ("cursor", "claude", "codex", "kimi", "hermes", "gemini"):
        return (f" AND {a}.provider = %s", [p])
    return ("", [])


def _legacy_fetch_conversation_documents_from_memory_index(
    cur: Any,
    *,
    limit: int,
    offset: int,
    provider: str | None,
    wing: str | None,
    source: str | None,
    excerpt_len: int,
) -> tuple[int, list[dict[str, Any]]]:
    """Liste historique depuis mehdi_memory_* seul (sans lignes dans ``zab_conversations``)."""
    doc_filter = "WHERE d.source = ANY(%s)"
    doc_params: list[Any] = [list(_CONVERSATION_SOURCES)]
    if source:
        doc_filter += " AND d.source = %s"
        doc_params.append(source)
    if wing:
        doc_filter += " AND d.wing ILIKE %s"
        doc_params.append(f"%{wing}%")
    prov_sql, prov_params = _conversation_provider_sql("d", provider if not source else None)
    doc_filter += prov_sql
    doc_params.extend(prov_params)

    cur.execute(
        f"""
        SELECT COUNT(*)::bigint
        FROM mehdi_memory_documents d
        {doc_filter}
        """,
        tuple(doc_params),
    )
    total = int(cur.fetchone()[0])
    cur.execute(
        f"""
        SELECT
            d.id,
            d.source,
            d.export_batch_id,
            d.wing,
            d.room,
            d.synced_at,
            d.metadata,
            COUNT(c.id)::bigint AS chunk_count,
            COALESCE(left(MIN(c.content), %s), '') AS excerpt
        FROM mehdi_memory_documents d
        LEFT JOIN mehdi_memory_chunks c ON c.document_id = d.id
        {doc_filter}
        GROUP BY d.id, d.source, d.export_batch_id, d.wing, d.room, d.synced_at, d.metadata
        ORDER BY d.synced_at DESC NULLS LAST, d.id DESC
        LIMIT %s OFFSET %s
        """,
        (excerpt_len, *doc_params, limit, offset),
    )
    rows = cur.fetchall()
    items: list[dict[str, Any]] = []
    for r in rows:
        meta = r[6]
        if hasattr(meta, "data"):
            meta = meta.data  # type: ignore[union-attr]
        messages = meta.get("messages") if isinstance(meta, dict) else None
        title = meta.get("title") if isinstance(meta, dict) else None
        path = meta.get("path") if isinstance(meta, dict) else None
        items.append(
            {
                "document_id": str(r[0]),
                "conversation_id": None,
                "source": r[1],
                "export_batch_id": r[2],
                "wing": r[3],
                "room": r[4],
                "synced_at": r[5].isoformat() if r[5] is not None else None,
                "metadata": meta,
                "path": path,
                "title": title,
                "chunk_count": int(r[7]),
                "message_count": len(messages) if isinstance(messages, list) else 0,
                "content_excerpt": r[8],
            }
        )
    return total, items


def fetch_conversation_sources() -> list[dict[str, Any]]:
    """Comptes par colonne source (documents)."""
    url = _url_or_none()
    if not url or not memory_psycopg_available():
        return []
    import psycopg

    try:
        with psycopg.connect(url, connect_timeout=_pg_connect_timeout()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT source, COUNT(*)::bigint AS n
                    FROM mehdi_memory_documents
                    GROUP BY source
                    ORDER BY source
                    """
                )
                rows = cur.fetchall()
    except Exception:
        return []
    return [{"source": r[0], "count": int(r[1])} for r in rows]


def fetch_conversation_documents(
    *,
    limit: int = 25,
    offset: int = 0,
    provider: str | None = None,
    wing: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Liste depuis ``zab_conversations`` si l’archive n’est pas vide ; sinon depuis l’index mehdi_memory_*."""
    url = _url_or_none()
    if not url or not memory_psycopg_available():
        return {"items": [], "total": 0, "conversation_storage": "unavailable"}
    lim = max(1, min(int(limit), 100))
    off = max(0, int(offset))
    import psycopg

    excerpt_len = min(_SEARCH_PREVIEW, 2000)
    try:
        with psycopg.connect(url, connect_timeout=_pg_connect_timeout()) as conn:
            with conn.cursor() as cur:
                ensure_conversations_archive_schema(cur)
                cur.execute("SELECT COUNT(*)::bigint FROM zab_conversations")
                archive_nonempty = int(cur.fetchone()[0]) > 0

                if not archive_nonempty:
                    total, items = _legacy_fetch_conversation_documents_from_memory_index(
                        cur,
                        limit=lim,
                        offset=off,
                        provider=provider,
                        wing=wing,
                        source=source,
                        excerpt_len=excerpt_len,
                    )
                    return {
                        "items": items,
                        "total": total,
                        "conversation_storage": "index_fallback",
                    }

                doc_filter = "WHERE z.source = ANY(%s)"
                doc_params: list[Any] = [list(_ARCHIVE_CONVERSATION_SOURCES)]
                if source:
                    doc_filter += " AND z.source = %s"
                    doc_params.append(source)
                if wing:
                    doc_filter += " AND z.wing ILIKE %s"
                    doc_params.append(f"%{wing}%")
                prov_sql, prov_params = _conversation_archive_provider_sql("z", provider if not source else None)
                doc_filter += prov_sql
                doc_params.extend(prov_params)

                cur.execute(
                    f"""
                    SELECT COUNT(*)::bigint
                    FROM zab_conversations z
                    {doc_filter}
                    """,
                    tuple(doc_params),
                )
                total = int(cur.fetchone()[0])
                cur.execute(
                    f"""
                    SELECT
                        z.id,
                        z.source,
                        z.metadata,
                        z.wing,
                        z.room,
                        z.synced_at,
                        z.title,
                        COALESCE(jsonb_array_length(z.messages), 0)::bigint AS message_count,
                        COALESCE((
                            SELECT COUNT(*)::bigint
                            FROM mehdi_memory_documents d2
                            JOIN mehdi_memory_chunks c2 ON c2.document_id = d2.id
                            WHERE d2.metadata->>'conversation_id' = z.id::text
                        ), 0)::bigint AS chunk_count,
                        COALESCE(
                            (
                                SELECT left(coalesce(e->>'content', ''), %s)
                                FROM jsonb_array_elements(z.messages) AS e
                                WHERE coalesce(e->>'content', '') <> ''
                                LIMIT 1
                            ),
                            left(z.messages::text, %s)
                        ) AS excerpt
                    FROM zab_conversations z
                    {doc_filter}
                    ORDER BY z.synced_at DESC NULLS LAST, z.id DESC
                    LIMIT %s OFFSET %s
                    """,
                    (excerpt_len, excerpt_len, *doc_params, lim, off),
                )
                rows = cur.fetchall()

                items_archive: list[dict[str, Any]] = []
                for r in rows:
                    meta = r[2]
                    if hasattr(meta, "data"):
                        meta = meta.data  # type: ignore[union-attr]
                    export_batch_id = meta.get("export_batch_id") if isinstance(meta, dict) else None
                    path = meta.get("path") if isinstance(meta, dict) else None
                    title = r[6] or (meta.get("title") if isinstance(meta, dict) else None)
                    items_archive.append(
                        {
                            "document_id": str(r[0]),
                            "conversation_id": str(r[0]),
                            "source": r[1],
                            "export_batch_id": export_batch_id,
                            "wing": r[3],
                            "room": r[4],
                            "synced_at": r[5].isoformat() if r[5] is not None else None,
                            "metadata": meta,
                            "path": path,
                            "title": title,
                            "chunk_count": int(r[8]),
                            "message_count": int(r[7]),
                            "content_excerpt": r[9] or "",
                        }
                    )
                return {"items": items_archive, "total": total, "conversation_storage": "archive"}
    except Exception:
        return {"items": [], "total": 0, "conversation_storage": "error"}


def search_conversations(
    query: str,
    *,
    limit: int = 20,
    offset: int = 0,
    provider: str | None = None,
    wing: str | None = None,
    source: str | None = None,
) -> list[dict[str, Any]]:
    """Recherche dans les chunks ; résultats résolus vers l'archive quand `conversation_id` est lié."""
    url = _url_or_none()
    q = (query or "").strip()
    if not url or not memory_psycopg_available() or not q:
        return []
    lim = max(1, min(int(limit), 50))
    off = max(0, int(offset))
    import psycopg

    terms = [t for t in re.split(r"\s+", q) if len(t) >= 2][:8] or [q]
    chunk_where_c = "(" + " AND ".join("c.content ILIKE %s" for _ in terms) + ")"
    chunk_where_c2 = "(" + " AND ".join("c2.content ILIKE %s" for _ in terms) + ")"
    term_params = [f"%{t}%" for t in terms]

    doc_filter = ""
    doc_params: list[Any] = []
    if source:
        doc_filter += " AND d.source = %s"
        doc_params.append(source)
    if wing:
        doc_filter += " AND d.wing ILIKE %s"
        doc_params.append(f"%{wing}%")
    prov_sql, prov_params = _conversation_provider_sql("d", provider if not source else None)
    doc_filter += prov_sql
    doc_params.extend(prov_params)

    excerpt_len = min(_SEARCH_PREVIEW, 2000)
    matched_params = [*term_params, *doc_params]
    lateral_params = [excerpt_len, *term_params]
    try:
        with psycopg.connect(url, connect_timeout=_pg_connect_timeout()) as conn:
            with conn.cursor() as cur:
                ensure_conversations_archive_schema(cur)
                cur.execute(
                    f"""
                    WITH matched AS (
                        SELECT c.document_id AS did,
                               COUNT(*)::bigint AS match_chunks
                        FROM mehdi_memory_chunks c
                        INNER JOIN mehdi_memory_documents d ON d.id = c.document_id
                        WHERE {chunk_where_c}
                        {doc_filter}
                        GROUP BY c.document_id
                    )
                    SELECT
                        COALESCE(z.id::text, d.id::text) AS document_id,
                        d.id::text AS index_document_id,
                        z.id::text AS conversation_id,
                        COALESCE(z.source, d.source) AS source,
                        COALESCE(z.metadata->>'export_batch_id', d.export_batch_id::text) AS export_batch_id,
                        COALESCE(z.wing, d.wing) AS wing,
                        COALESCE(z.room, d.room) AS room,
                        COALESCE(z.synced_at, d.synced_at) AS synced_at,
                        COALESCE(z.metadata, d.metadata) AS metadata,
                        m.match_chunks,
                        COALESCE(ex.excerpt, '') AS excerpt
                    FROM matched m
                    INNER JOIN mehdi_memory_documents d ON d.id = m.did
                    LEFT JOIN zab_conversations z
                        ON d.metadata->>'conversation_id' IS NOT NULL
                       AND z.id::text = d.metadata->>'conversation_id'
                    LEFT JOIN LATERAL (
                        SELECT left(c2.content, %s) AS excerpt
                        FROM mehdi_memory_chunks c2
                        WHERE c2.document_id = m.did
                          AND {chunk_where_c2}
                        ORDER BY c2.chunk_index ASC, c2.id ASC
                        LIMIT 1
                    ) ex ON TRUE
                    ORDER BY COALESCE(z.synced_at, d.synced_at) DESC NULLS LAST,
                             COALESCE(z.id, d.id) DESC
                    LIMIT %s OFFSET %s
                    """,
                    (*matched_params, *lateral_params, lim, off),
                )
                rows = cur.fetchall()
    except Exception:
        return []

    out: list[dict[str, Any]] = []
    for r in rows:
        meta = r[8]
        if hasattr(meta, "data"):
            meta = meta.data  # type: ignore[union-attr]
        out.append(
            {
                "document_id": str(r[0]),
                "index_document_id": str(r[1]) if r[1] else None,
                "conversation_id": str(r[2]) if r[2] else None,
                "source": r[3],
                "export_batch_id": r[4],
                "wing": r[5],
                "room": r[6],
                "synced_at": r[7].isoformat() if r[7] is not None else None,
                "metadata": meta,
                "path": meta.get("path") if isinstance(meta, dict) else None,
                "match_chunks": int(r[9]),
                "content_excerpt": r[10],
            }
        )
    return out


def fetch_conversation_data_health() -> dict[str, Any]:
    """Checks intégrité / volumes pour l’onglet Conversations."""
    url = _url_or_none()
    base: dict[str, Any] = {
        "postgres_configured": bool(_url_or_none()),
        "psycopg_available": memory_psycopg_available(),
        "connected": False,
        "document_total": 0,
        "chunk_total": 0,
        "documents_without_chunks": 0,
        "orphan_chunks": 0,
        "documents_missing_path": 0,
        "duplicate_content_hash": 0,
        "sources": [],
    }
    if not base["postgres_configured"] or not base["psycopg_available"]:
        return base
    import psycopg

    try:
        with psycopg.connect(url, connect_timeout=_pg_connect_timeout()) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM mehdi_memory_documents")
                base["document_total"] = int(cur.fetchone()[0])
                cur.execute("SELECT COUNT(*) FROM mehdi_memory_chunks")
                base["chunk_total"] = int(cur.fetchone()[0])
                base["connected"] = True

                cur.execute(
                    """
                    SELECT COUNT(*) FROM mehdi_memory_documents d
                    WHERE NOT EXISTS (
                        SELECT 1 FROM mehdi_memory_chunks c WHERE c.document_id = d.id
                    )
                    """
                )
                base["documents_without_chunks"] = int(cur.fetchone()[0])

                cur.execute(
                    """
                    SELECT COUNT(*) FROM mehdi_memory_chunks c
                    WHERE NOT EXISTS (
                        SELECT 1 FROM mehdi_memory_documents d WHERE d.id = c.document_id
                    )
                    """
                )
                base["orphan_chunks"] = int(cur.fetchone()[0])

                cur.execute(
                    """
                    SELECT COUNT(*) FROM mehdi_memory_documents d
                    WHERE d.metadata IS NULL
                       OR (d.metadata::text = 'null')
                       OR (d.metadata->>'path' IS NULL OR d.metadata->>'path' = '')
                    """
                )
                base["documents_missing_path"] = int(cur.fetchone()[0])

                cur.execute(
                    """
                    SELECT COUNT(*) FROM (
                        SELECT content_hash FROM mehdi_memory_documents
                        WHERE content_hash IS NOT NULL AND content_hash <> ''
                        GROUP BY content_hash
                        HAVING COUNT(*) > 1
                    ) t
                    """
                )
                base["duplicate_content_hash"] = int(cur.fetchone()[0])

                cur.execute(
                    """
                    SELECT source, COUNT(*)::bigint FROM mehdi_memory_documents
                    GROUP BY source ORDER BY source
                    """
                )
                base["sources"] = [{"source": r[0], "count": int(r[1])} for r in cur.fetchall()]
    except Exception:
        base["connected"] = False
        base["error"] = "postgres_query_failed"
        return base

    return base


def fetch_conversation_provider_document_counts() -> dict[str, int]:
    """Comptes conversations par slug : archive ``zab_conversations`` sinon index mehdi_memory_*."""
    url = _url_or_none()
    if not url or not memory_psycopg_available():
        return {}
    import psycopg

    base = {slug: 0 for slug in ("cursor", "claude", "codex", "hermes", "gemini", "kimi")}
    archive_sql = """
        SELECT provider, COUNT(*)::bigint
        FROM zab_conversations
        GROUP BY provider
    """
    legacy_sql = """
        SELECT slug, SUM(n)::bigint AS total FROM (
            SELECT 'cursor' AS slug, COUNT(*)::bigint AS n FROM mehdi_memory_documents
                WHERE source = 'cursor_agent_transcript'
            UNION ALL
            SELECT 'cursor', COUNT(*)::bigint FROM mehdi_memory_documents
                WHERE source = 'agent_context_artifact' AND wing ILIKE 'cursor%%'
            UNION ALL
            SELECT 'claude', COUNT(*)::bigint FROM mehdi_memory_documents
                WHERE source = 'claude_code_transcript'
            UNION ALL
            SELECT 'codex', COUNT(*)::bigint FROM mehdi_memory_documents
                WHERE source = 'codex_transcript'
            UNION ALL
            SELECT 'codex', COUNT(*)::bigint FROM mehdi_memory_documents
                WHERE source = 'agent_context_artifact' AND wing ILIKE 'codex%%'
            UNION ALL
            SELECT 'kimi', COUNT(*)::bigint FROM mehdi_memory_documents
                WHERE source = 'kimi_transcript'
            UNION ALL
            SELECT 'kimi', COUNT(*)::bigint FROM mehdi_memory_documents
                WHERE source = 'agent_context_artifact' AND wing ILIKE 'kimi%%'
            UNION ALL
            SELECT 'hermes', COUNT(*)::bigint FROM mehdi_memory_documents
                WHERE source = 'hermes_transcript'
            UNION ALL
            SELECT 'gemini', COUNT(*)::bigint FROM mehdi_memory_documents
                WHERE source = 'gemini_cli_transcript'
        ) x
        GROUP BY slug
    """
    try:
        with psycopg.connect(url, connect_timeout=_pg_connect_timeout()) as conn:
            with conn.cursor() as cur:
                ensure_conversations_archive_schema(cur)
                cur.execute("SELECT COUNT(*)::bigint FROM zab_conversations")
                n_arch = int(cur.fetchone()[0])
                sql = archive_sql if n_arch > 0 else legacy_sql
                cur.execute(sql)
                rows = cur.fetchall()
    except Exception:
        return {}

    for r in rows:
        slug = str(r[0])
        if slug in base:
            base[slug] = int(r[1])

    return base
