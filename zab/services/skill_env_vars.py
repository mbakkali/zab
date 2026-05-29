"""Lie les skills à leurs variables d'environnement et aux .env locaux qui les portent."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

_ENV_VAR_RE = re.compile(r"\b([A-Z][A-Z0-9_]{3,}[A-Z0-9])\b")
# Bruit fréquent (mots all-caps non secrets), à filtrer.
_BLOCKLIST: frozenset[str] = frozenset(
    {
        "TODO", "NOTE", "WARNING", "IMPORTANT", "README", "INFO", "DEBUG", "ERROR",
        "TRUE", "FALSE", "NULL", "NONE", "YES", "NO", "OK",
        "JSON", "YAML", "HTML", "URL", "URI", "HTTP", "HTTPS", "API", "REST", "CRUD",
        "GET", "POST", "PUT", "DELETE", "PATCH", "HEAD",
        "MCP", "CLI", "IDE", "SDK", "PDF", "CSV", "XLSX", "PNG", "JPG", "JPEG",
        "AND", "OR", "NOT", "WITH", "WITHOUT", "FROM", "INTO", "AUTO",
        "MD", "PY", "TS", "JS", "TSX", "JSX",
        "UUID", "UTC", "GMT", "ISO",
    }
)


def extract_env_var_names(text: str) -> list[str]:
    """Extrait des noms ALL_CAPS vraisemblablement env-var dans un SKILL.md."""
    candidates: list[str] = []
    seen: set[str] = set()
    for match in _ENV_VAR_RE.finditer(text):
        name = match.group(1)
        if name in _BLOCKLIST or name in seen:
            continue
        # heuristique : doit contenir un underscore OU un mot connu (KEY/TOKEN/SECRET/URL/ID)
        if "_" not in name and not any(
            tag in name for tag in ("KEY", "TOKEN", "SECRET", "URL", "PASSWORD", "ID")
        ):
            continue
        seen.add(name)
        candidates.append(name)
    return candidates


def _iter_dotenv_keys(path: Path) -> Iterable[str]:
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key = line.split("=", 1)[0].strip().lstrip("export ").strip()
            if key:
                yield key
    except OSError:
        return


def _candidate_env_files(roots: list[Path], max_depth: int = 4) -> list[Path]:
    out: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        try:
            root = root.expanduser().resolve()
        except OSError:
            continue
        if not root.is_dir():
            continue
        for env in root.rglob(".env"):
            try:
                rel_parts = env.resolve().relative_to(root).parts
            except (ValueError, OSError):
                continue
            if len(rel_parts) > max_depth:
                continue
            if any(part in {"node_modules", ".venv", "venv", "__pycache__", ".git", "dist", "build"} for part in rel_parts):
                continue
            resolved = env.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            out.append(resolved)
    return out


def _index_env_files(env_files: list[Path]) -> dict[str, list[str]]:
    """{ENV_VAR_NAME: [chemin1, chemin2]}."""
    idx: dict[str, list[str]] = {}
    for f in env_files:
        for key in _iter_dotenv_keys(f):
            idx.setdefault(key, []).append(str(f))
    return idx


def build_env_index(roots: list[Path]) -> dict[str, list[str]]:
    return _index_env_files(_candidate_env_files(roots))


def env_vars_for_skill(skill_md_path: Path, env_index: dict[str, list[str]]) -> list[dict[str, object]]:
    """Retourne [{name, files, present}] pour les env vars détectées dans un SKILL.md."""
    try:
        text = skill_md_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    out: list[dict[str, object]] = []
    for name in extract_env_var_names(text):
        files = env_index.get(name, [])
        out.append({"name": name, "files": files, "present": bool(files)})
    return out
