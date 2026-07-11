"""Shared Postgres DSN resolution for Zab operational and memory stores."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from zab.paths import config_dir
from zab.user_config import load_user_config


def _dsn_from_anchor(anchor: Path) -> str | None:
    for candidate in (anchor, *anchor.parents):
        env_file = candidate / ".env"
        if not env_file.is_file():
            continue
        vals = dotenv_values(env_file)
        for key in ("ZAB_MEMORY_DATABASE_URL", "MEHDI_MEMORY_DATABASE_URL"):
            raw = vals.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
    return None


def resolve_postgres_dsn() -> str | None:
    """Resolve the canonical Zab Postgres DSN without registry/path recursion."""
    for var in ("ZAB_MEMORY_DATABASE_URL", "MEHDI_MEMORY_DATABASE_URL"):
        raw = os.environ.get(var)
        if raw and raw.strip():
            return raw.strip()

    anchors: list[Path] = [config_dir()]
    if "PYTEST_CURRENT_TEST" not in os.environ:
        anchors.append(Path.home() / "projects" / "skills")

    try:
        cfg = load_user_config()
    except Exception:
        cfg = {}

    def add_anchor(value: Any) -> None:
        if isinstance(value, str) and value.strip():
            anchors.append(Path(value).expanduser())

    if isinstance(cfg, dict):
        for key in ("skills_root", "skills_repo", "skills_repo_root"):
            add_anchor(cfg.get(key))
        roots = cfg.get("skills_roots")
        if isinstance(roots, list):
            for root in roots:
                add_anchor(root)
        sync_cfg = cfg.get("skills_sync")
        if isinstance(sync_cfg, dict):
            for key in ("repo_root", "skills_repo", "skills_root"):
                add_anchor(sync_cfg.get(key))

    seen: set[str] = set()
    for anchor in anchors:
        marker = str(anchor)
        if marker in seen:
            continue
        seen.add(marker)
        url = _dsn_from_anchor(anchor)
        if url:
            return url
    return None
