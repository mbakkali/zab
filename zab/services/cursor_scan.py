"""Lecture best-effort des réglages Cursor / Cody (pas d’API officielle stable)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _cursor_user_settings_candidates() -> list[Path]:
    home = Path.home()
    sysname = os.name
    out: list[Path] = []
    if sysname == "nt":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            base = Path(appdata) / "Cursor" / "User"
            out.append(base / "settings.json")
    elif sysname == "posix":
        out.append(home / "Library" / "Application Support" / "Cursor" / "User" / "settings.json")
        out.append(home / ".config" / "Cursor" / "User" / "settings.json")
    return out


def _model_related_entries(doc: dict[str, Any]) -> dict[str, Any]:
    """Extrait des paires clé → valeur dont la clé évoque modèle / Cody / Copilot."""
    pat = re.compile(r"(model|cody|copilot|chat|ai|claude|gpt|cursor\.|aichat)", re.I)
    found: dict[str, Any] = {}
    for k, v in doc.items():
        if not isinstance(k, str):
            continue
        if pat.search(k):
            if isinstance(v, (str, int, float, bool)):
                found[k] = v
            elif isinstance(v, list) and len(v) <= 30:
                found[k] = v
            elif isinstance(v, dict):
                found[k] = {sk: sv for sk, sv in list(v.items())[:20]}
    return found


def scan_cursor_cody() -> dict[str, Any]:
    """
    Sonde l’environnement Cursor : binaire, fichier settings.json, extraits « modèle ».
    Les détails varient selon les versions ; l’UI permet aussi l’édition manuelle du YAML.
    """
    cursor_bin = shutil.which("cursor")
    version_line: str | None = None
    if cursor_bin:
        try:
            r = subprocess.run(
                [cursor_bin, "--version"],
                capture_output=True,
                text=True,
                timeout=8,
            )
            version_line = (r.stdout or r.stderr or "").strip().splitlines()[0] if (r.stdout or r.stderr) else None
        except (subprocess.TimeoutExpired, OSError, IndexError):
            version_line = None

    settings_path: str | None = None
    settings_ok = False
    model_hints: dict[str, Any] = {}
    parse_error: str | None = None

    for cand in _cursor_user_settings_candidates():
        if not cand.is_file():
            continue
        settings_path = str(cand.resolve())
        try:
            doc = json.loads(cand.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            parse_error = str(e)
            settings_ok = False
            break
        if isinstance(doc, dict):
            model_hints = _model_related_entries(doc)
            settings_ok = True
        break

    return {
        "cursor_cli_on_path": cursor_bin,
        "cursor_version_line": version_line,
        "settings_path": settings_path,
        "settings_readable": settings_ok,
        "settings_parse_error": parse_error,
        "model_related_settings": model_hints,
        "note": "Les clés exactes dépendent de la version de Cursor. Complétez via local-tools.yaml ou ~/.config/zab/config.yaml.",
    }
