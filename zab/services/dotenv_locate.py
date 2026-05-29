"""Localisation d'une clé dans un fichier .env (numéro de ligne, sans lire la valeur)."""

from __future__ import annotations

import re
from pathlib import Path


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
