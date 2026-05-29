"""Bloc memory_stack pour le scan workspace (MemPalace, scripts skills, sonde Postgres)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from dotenv import dotenv_values


def resolve_mehdi_memory_database_url(skills_repo: Path | None) -> str | None:
    """DSN depuis l'environnement puis depuis ``.env`` autour de l'ancre skills.

    Accepts ``ZAB_MEMORY_DATABASE_URL`` (preferred) and legacy ``MEHDI_MEMORY_DATABASE_URL``.
    """
    for var in ("ZAB_MEMORY_DATABASE_URL", "MEHDI_MEMORY_DATABASE_URL"):
        u = os.environ.get(var, "").strip()
        if u:
            return u
    if skills_repo is None:
        return None
    anchors = [skills_repo, *skills_repo.parents]
    for anchor in anchors:
        env_file = anchor / ".env"
        if not env_file.is_file():
            continue
        vals = dotenv_values(env_file)
        for key in ("ZAB_MEMORY_DATABASE_URL", "MEHDI_MEMORY_DATABASE_URL"):
            raw = vals.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
    return None


def _mempalace_probe() -> dict[str, Any]:
    exe = shutil.which("mempalace")
    out: dict[str, Any] = {"on_path": exe is not None, "which_path": exe, "version": None}
    if not exe:
        return out
    try:
        proc = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        text = (proc.stdout or proc.stderr or "").strip().splitlines()
        out["version"] = text[0][:200] if text else None
    except (OSError, subprocess.TimeoutExpired):
        out["version"] = None
    return out


def _postgres_counts(url: str) -> dict[str, Any]:
    try:
        import psycopg
    except ImportError:
        return {"skipped_reason": "psycopg_non_installe", "document_count": None, "chunk_count": None}

    try:
        with psycopg.connect(url, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM mehdi_memory_documents")
                doc_n = int(cur.fetchone()[0])
                cur.execute("SELECT count(*) FROM mehdi_memory_chunks")
                chunk_n = int(cur.fetchone()[0])
        return {"skipped_reason": None, "document_count": doc_n, "chunk_count": chunk_n}
    except Exception as exc:
        return {
            "skipped_reason": "postgres_erreur",
            "document_count": None,
            "chunk_count": None,
            "error_class": type(exc).__name__,
        }


def build_memory_stack(skills_repo: Path) -> dict[str, Any]:
    """Résumé sans secrets pour inclusion dans le JSON du scan."""
    url = resolve_mehdi_memory_database_url(skills_repo)
    scripts = skills_repo / "scripts"
    imp = scripts / "import_memory_jsonl.py"
    ext = scripts / "extract_mempalace_to_jsonl.py"

    stack: dict[str, Any] = {
        "mempalace": _mempalace_probe(),
        "MEHDI_MEMORY_DATABASE_URL_configured": bool(url),
        "skills_scripts": {
            "import_memory_jsonl": str(imp),
            "import_memory_jsonl_exists": imp.is_file(),
            "extract_mempalace_to_jsonl": str(ext),
            "extract_mempalace_to_jsonl_exists": ext.is_file(),
        },
    }
    if url:
        stack["postgres_probe"] = _postgres_counts(url)
    else:
        stack["postgres_probe"] = {
            "skipped_reason": "dsn_absent",
            "document_count": None,
            "chunk_count": None,
        }
    return stack
