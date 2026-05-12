"""Lecture seule Postgres mehdi_memory_* (MEHDI_MEMORY_DATABASE_URL)."""

from __future__ import annotations

import uuid
from typing import Any

from zab.paths import skills_root_from_config_file_only
from zab.services.memory_scan import resolve_mehdi_memory_database_url

_MAX_DOCS = 100
_MAX_CHUNKS = 100
_CONTENT_PREVIEW = 2000


def _url_or_none() -> str | None:
    anchor = skills_root_from_config_file_only()
    return resolve_mehdi_memory_database_url(anchor)


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
        }
    if not memory_psycopg_available():
        return {
            "configured": True,
            "connected": False,
            "psycopg_available": False,
            "document_count": None,
            "chunk_count": None,
            "error": "Installer le extra optionnel : uv sync --extra memory",
        }
    import psycopg

    try:
        with psycopg.connect(url, connect_timeout=3) as conn:
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
        }
    except Exception:
        return {
            "configured": True,
            "connected": False,
            "psycopg_available": True,
            "document_count": None,
            "chunk_count": None,
            "error": "Connexion ou requête Postgres impossible (vérifier le DSN, SSL, migrations).",
        }


def fetch_documents(*, limit: int, offset: int) -> list[dict[str, Any]]:
    url = _url_or_none()
    if not url or not memory_psycopg_available():
        return []
    lim = max(1, min(int(limit), _MAX_DOCS))
    off = max(0, int(offset))
    import psycopg

    with psycopg.connect(url, connect_timeout=3) as conn:
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

    with psycopg.connect(url, connect_timeout=3) as conn:
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
