"""Localisation et chargement sûr des fichiers .env locaux."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv

from zab.paths import config_dir, zab_repo_root

_LOADED_DOTENV_PATHS: set[str] = set()


def dotenv_key_line(path: Path, key: str) -> int | None:
    """Retourne le numéro de ligne (1-based) de la première assignation ``key=`` / ``export key=``."""
    k = key.strip()
    if not k:
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    pat = re.compile(rf"^\s*(?:export\s+)?{re.escape(k)}\s*=", re.IGNORECASE)
    for idx, line in enumerate(lines, start=1):
        if pat.match(line):
            return idx
    return None


def standard_dotenv_paths(extra_paths: Iterable[Path] | None = None) -> list[Path]:
    """Return local env files that Zab CLI/services should read without overriding process env."""
    repo_root = zab_repo_root()
    raw = [
        config_dir() / ".env",
        repo_root / ".env.local",
        repo_root / ".env",
        Path.home() / ".hermes" / ".env",
        Path.home() / ".env",
    ]
    if extra_paths:
        raw.extend(extra_paths)

    seen: set[str] = set()
    paths: list[Path] = []
    for path in raw:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            resolved = path.expanduser()
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        paths.append(resolved)
    return paths


def load_standard_dotenvs_once(
    extra_paths: Iterable[Path] | None = None,
    *,
    force: bool = False,
) -> list[Path]:
    """Load standard Zab env files once and return the files that were read.

    Values already present in ``os.environ`` keep precedence.
    """
    if force:
        _LOADED_DOTENV_PATHS.clear()

    loaded: list[Path] = []
    for path in standard_dotenv_paths(extra_paths):
        key = str(path)
        if key in _LOADED_DOTENV_PATHS:
            continue
        _LOADED_DOTENV_PATHS.add(key)
        if not path.is_file():
            continue
        load_dotenv(path, override=False)
        loaded.append(path)
    return loaded
