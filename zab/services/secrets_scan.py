"""Masked secret presence scan for agents and dashboard security status."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from zab.paths import config_dir, skills_root_from_config_file_only
from zab.secrets_catalog import SECRET_ALIASES, SECRET_GROUPS
from zab.services.dotenv_locate import dotenv_key_line
from zab.user_config import (
    projects_roots_resolved,
    security_env_paths_resolved,
    tracked_env_names_for_security,
)

_SKIP_DIRS = {
    ".git",
    "node_modules",
    "dist",
    "build",
    ".next",
    "venv",
    ".venv",
    "__pycache__",
    ".turbo",
    "coverage",
}

_LOCATE_STOPWORDS = {
    "api",
    "apikey",
    "apiKey",
    "key",
    "keys",
    "cle",
    "clé",
    "token",
    "secret",
    "secrets",
    "password",
    "passwd",
    "de",
    "du",
    "des",
    "la",
    "le",
    "les",
    "l",
    "d",
    "pour",
    "trouve",
    "moi",
    "find",
}


def _candidate_env_files() -> list[Path]:
    out: list[Path] = []

    try:
        configured_paths = security_env_paths_resolved()
    except Exception:
        configured_paths = []
    for p in configured_paths:
        out.append(p)

    out.append(Path.home() / ".env")
    out.append(Path.home() / ".hermes" / ".env")
    out.append(config_dir() / ".env")

    # Les coffres que le registre de connecteurs déclare. Sans eux, zab
    # répondait « clé absente » pour une clé bien présente, rangée dans un
    # coffre qu'il ne balayait pas — le cas d'`attio`, le 2026-09-04.
    try:
        from zab.services.secrets_registry import vault_paths

        out.extend(vault_paths())
    except Exception:
        pass
    try:
        sr = skills_root_from_config_file_only()
    except Exception:
        sr = None
    if sr is not None:
        out.append(sr / ".env")

    try:
        project_roots = projects_roots_resolved()
    except Exception:
        project_roots = []
    for pr in project_roots:
        if pr.is_dir():
            out.append(pr / ".env")
        try:
            projects = sorted((p for p in pr.iterdir() if p.is_dir() and not p.name.startswith(".")), key=lambda x: x.name.casefold())
        except OSError:
            projects = []
        for project in projects:
            out.append(project / ".env")
            # A bounded recursive pass catches real project layouts like compta/bridge/.env
            # without turning security status into a full-disk scan. We prune heavy
            # directories (node_modules, .git, .venv…) *during* traversal via os.walk
            # instead of filtering rglob results afterwards, which otherwise still
            # descends into those subtrees and makes this a ~20s walk.
            base_depth = len(project.parts)
            for dirpath, dirnames, filenames in os.walk(project):
                depth = len(Path(dirpath).parts) - base_depth
                if depth >= 5:
                    dirnames[:] = []
                else:
                    dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
                if ".env" in filenames:
                    out.append(Path(dirpath) / ".env")

    seen: set[str] = set()
    uniq: list[Path] = []
    for p in out:
        try:
            r = p.expanduser().resolve()
        except OSError:
            continue
        key = str(r)
        if key in seen:
            continue
        seen.add(key)
        if r.is_file():
            uniq.append(r)
    return uniq


def _mask_secret_value(value: str) -> str:
    v = str(value or "").strip()
    if not v:
        return ""
    if len(v) <= 4:
        return "****"
    return "****" + v[-4:]


def _display_path(path: Path) -> str:
    home = Path.home()
    try:
        rel = path.resolve().relative_to(home)
        return f"~/{rel.as_posix()}"
    except (OSError, ValueError):
        return str(path)


def _norm_secret_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _locate_terms(query: str) -> list[str]:
    raw_terms = re.findall(r"[A-Za-z0-9_À-ÿ-]+", str(query or "").casefold())
    normalized = [_norm_secret_text(term) for term in raw_terms]
    terms = [term for term in normalized if term and term not in {_norm_secret_text(x) for x in _LOCATE_STOPWORDS}]
    return terms or [term for term in normalized if term]


def _secret_name_match(name: str, query: str, terms: list[str]) -> tuple[bool, int, list[str]]:
    hay = _norm_secret_text(name)
    direct = _norm_secret_text(query)
    reasons: list[str] = []
    score = 0
    if direct and direct in hay:
        reasons.append("query_substring")
        score += 30
    matched_terms = [term for term in terms if term and term in hay]
    if terms and len(matched_terms) == len(terms):
        reasons.append("all_terms")
        score += 50
    elif matched_terms:
        reasons.append("partial_terms")
        score += 10 * len(matched_terms)
    if not reasons:
        return False, 0, []
    if any(marker in hay for marker in ("apikey", "token", "secret", "password", "passwd")):
        reasons.append("secret_like_name")
        score += 5
    return True, score, reasons


def locate_secret_names(
    query: str,
    *,
    env_files: list[Path] | None = None,
    include_process: bool = True,
    limit: int = 20,
) -> dict[str, Any]:
    """Find secret-like environment variable names without returning raw values."""

    q = str(query or "").strip()
    capped = max(1, min(100, int(limit or 20)))
    files = env_files if env_files is not None else _candidate_env_files()
    terms = _locate_terms(q)
    values_by_file: list[tuple[Path, dict[str, str | None]]] = []
    for path in files:
        try:
            values_by_file.append((path, dotenv_values(path)))
        except OSError:
            continue

    candidates: dict[str, dict[str, Any]] = {}

    def ensure_candidate(name: str) -> dict[str, Any]:
        key = str(name or "").strip()
        row = candidates.setdefault(
            key,
            {
                "name": key,
                "present": False,
                "in_process": False,
                "in_file": False,
                "masked": "",
                "value_length": 0,
                "sources": [],
                "match_reasons": [],
                "score": 0,
            },
        )
        return row

    def note_value(row: dict[str, Any], value: str | None) -> None:
        if value is None or not str(value).strip():
            return
        text = str(value)
        row["present"] = True
        if not row.get("masked"):
            row["masked"] = _mask_secret_value(text)
            row["value_length"] = len(text)

    for path, vals in values_by_file:
        for raw_key, raw_value in vals.items():
            if not raw_key:
                continue
            key = str(raw_key)
            matched, score, reasons = _secret_name_match(key, q, terms)
            if not matched:
                continue
            row = ensure_candidate(key)
            row["in_file"] = True
            row["score"] = max(int(row.get("score") or 0), score)
            row["match_reasons"] = sorted(set([*row.get("match_reasons", []), *reasons]))
            note_value(row, raw_value)
            source = {
                "kind": "file",
                "path": str(path),
                "path_display": _display_path(path),
                "key": key,
                "line": dotenv_key_line(path, key) if path.is_file() else None,
            }
            if source not in row["sources"]:
                row["sources"].append(source)

    if include_process:
        for key, raw_value in os.environ.items():
            matched, score, reasons = _secret_name_match(key, q, terms)
            if not matched:
                continue
            row = ensure_candidate(key)
            row["in_process"] = True
            row["score"] = max(int(row.get("score") or 0), score)
            row["match_reasons"] = sorted(set([*row.get("match_reasons", []), *reasons]))
            note_value(row, raw_value)
            source = {"kind": "process", "keys": [key]}
            if source not in row["sources"]:
                row["sources"].append(source)

    for name in tracked_env_names_for_security():
        names = (name, *SECRET_ALIASES.get(name, ()))
        for key in names:
            matched, score, reasons = _secret_name_match(key, q, terms)
            if not matched:
                continue
            row = ensure_candidate(str(key))
            row["score"] = max(int(row.get("score") or 0), score)
            row["match_reasons"] = sorted(set([*row.get("match_reasons", []), *reasons, "tracked_env"]))

    matches = sorted(
        candidates.values(),
        key=lambda row: (-int(row.get("score") or 0), not bool(row.get("present")), str(row.get("name") or "").casefold()),
    )
    for row in matches:
        row.pop("score", None)

    return {
        "contract": "security-secret-locate",
        "contract_version": "1.0",
        "query": q,
        "terms": terms,
        "total": len(matches),
        "matches": matches[:capped],
        "env_files_scanned": [str(p) for p in files],
        "policy": {
            "secrets": "never_print_raw_values",
            "values_returned": False,
            "search_scope": "environment_variable_names_only",
        },
        "usage": {
            "cli": "zab security locate <query> --json",
            "mcp": "security_locate",
            "api": "GET /api/security/locate?q=<query>",
        },
    }


def scan_secret_presence(
    names: tuple[str, ...] | None = None,
    *,
    env_files: list[Path] | None = None,
) -> dict[str, Any]:
    tracked = names or tracked_env_names_for_security()
    files = env_files if env_files is not None else _candidate_env_files()
    values_by_file: list[tuple[Path, dict[str, str | None]]] = []
    for path in files:
        try:
            values_by_file.append((path, dotenv_values(path)))
        except OSError:
            continue

    variables: list[dict[str, Any]] = []
    file_key_index: dict[str, set[str]] = {str(path): set() for path, _ in values_by_file}
    for name in tracked:
        aliases = SECRET_ALIASES.get(name, ())
        candidates = (name, *aliases)
        in_process_as = [k for k in candidates if os.environ.get(k)]
        file_sources: list[dict[str, str]] = []
        for path, vals in values_by_file:
            for k in candidates:
                v = vals.get(k)
                if v is not None and str(v).strip():
                    file_sources.append({"path": str(path), "key": k})
                    file_key_index.setdefault(str(path), set()).add(k)
                    break
        variables.append(
            {
                "name": name,
                "aliases": list(aliases),
                "present": bool(in_process_as or file_sources),
                "in_process": bool(in_process_as),
                "in_process_as": in_process_as,
                "in_files": file_sources,
                "source_count": len(file_sources),
            }
        )

    by_name = {row["name"]: row for row in variables}
    groups: dict[str, Any] = {}
    for group, keys in SECRET_GROUPS.items():
        rows = [by_name.get(k) for k in keys if by_name.get(k)]
        present = [str(r["name"]) for r in rows if r and r.get("present")]
        missing = [str(r["name"]) for r in rows if r and not r.get("present")]
        groups[group] = {
            "ready": len(rows) > 0 and not missing,
            "present": present,
            "missing": missing,
        }

    files_summary = [
        {
            "path": path,
            "tracked_keys_present": sorted(keys),
            "tracked_key_count": len(keys),
        }
        for path, keys in sorted(file_key_index.items())
        if keys
    ]

    return {
        "env_files_scanned": [str(p) for p in files],
        "env_files_with_tracked_keys": files_summary,
        "variables": variables,
        "groups": groups,
    }
