"""Masked secret presence scan for agents and dashboard security status."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from zab.paths import config_dir, skills_root_from_config_file_only
from zab.secrets_catalog import SECRET_ALIASES, SECRET_GROUPS
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


def _candidate_env_files() -> list[Path]:
    out: list[Path] = []

    for p in security_env_paths_resolved():
        out.append(p)

    out.append(config_dir() / ".env")
    sr = skills_root_from_config_file_only()
    if sr is not None:
        out.append(sr / ".env")

    for pr in projects_roots_resolved():
        if pr.is_dir():
            out.append(pr / ".env")
        try:
            projects = sorted((p for p in pr.iterdir() if p.is_dir() and not p.name.startswith(".")), key=lambda x: x.name.casefold())
        except OSError:
            projects = []
        for project in projects:
            out.append(project / ".env")
            # A bounded recursive pass catches real project layouts like compta/bridge/.env
            # without turning security status into a full-disk scan.
            try:
                for p in project.rglob(".env"):
                    try:
                        rel_parts = p.relative_to(project).parts
                    except ValueError:
                        continue
                    if len(rel_parts) > 5:
                        continue
                    if any(part in _SKIP_DIRS for part in rel_parts):
                        continue
                    out.append(p)
            except OSError:
                continue

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
