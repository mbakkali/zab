"""Localisation des jetons task_sources dans les fichiers .env (sans exposer les valeurs)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from zab.paths import config_dir
from zab.services.dotenv_locate import dotenv_key_line
from zab.services.pm_env_sync import scan_pm_tokens_from_projects
from zab.user_config import security_env_paths_resolved, task_sources_from_user_config


def fallbacks_for_backend(backend: str) -> list[str]:
    """Variables d'environnement alternatives si la principale est vide."""
    if backend == "gitlab":
        return ["GITLAB_TOKEN", "GLAB_TOKEN"]
    if backend == "notion":
        return ["NOTION_NOTION_SECRET", "NOTION_NOTION_SECRET_DEV", "NOTION_TOKEN"]
    if backend == "github":
        return ["GH_TOKEN"]
    return []


def _path_display(path: Path) -> str:
    home = Path.home()
    try:
        rel = path.relative_to(home)
        return f"~/{rel.as_posix()}"
    except ValueError:
        return str(path)


def candidate_env_files_for_task_source(*, local_project_path: str | None = None) -> list[Path]:
    """
    Fichiers .env parcourus pour localiser un jeton (ordre = priorité d'affichage).

    Inclut le .env du projet local, ~/.config/zab/.env, ~/.env, security_env_paths
    et les chemins déjà scannés par pm-env sync.
    """
    out: list[Path] = []
    if local_project_path and str(local_project_path).strip():
        try:
            out.append(Path(str(local_project_path).strip()).expanduser().resolve() / ".env")
        except OSError:
            pass
    out.append(config_dir() / ".env")
    out.append(Path.home() / ".env")
    for p in security_env_paths_resolved():
        out.append(p)
    _found, pm_sources = scan_pm_tokens_from_projects()
    for src in pm_sources:
        try:
            out.append(Path(src).expanduser().resolve())
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
        uniq.append(r)
    return uniq


def _key_nonempty_in_file(path: Path, key: str) -> bool:
    if not path.is_file():
        return False
    try:
        vals = dotenv_values(path)
    except OSError:
        return False
    v = vals.get(key)
    return v is not None and str(v).strip() != ""


def locate_env_token(
    env_token: str,
    backend: str,
    *,
    local_project_path: str | None = None,
) -> dict[str, Any]:
    """
    Indique où le jeton est disponible (fichier + ligne, ou processus uniquement).

    Essaie ``env_token`` puis les fallbacks du backend, dans l'ordre des candidats .env.
    """
    primary = (env_token or "").strip()
    keys = [k for k in [primary, *fallbacks_for_backend(backend)] if k]
    if not keys:
        keys = fallbacks_for_backend(backend)

    files = candidate_env_files_for_task_source(local_project_path=local_project_path)
    for key in keys:
        for path in files:
            if _key_nonempty_in_file(path, key):
                line = dotenv_key_line(path, key) if path.is_file() else None
                return {
                    "status": "file",
                    "key_used": key,
                    "env_token": primary or key,
                    "path": str(path),
                    "path_display": _path_display(path),
                    "line": line,
                    "in_process": bool(os.environ.get(key) and str(os.environ.get(key)).strip()),
                }

    for key in keys:
        if os.environ.get(key) and str(os.environ.get(key)).strip():
            return {
                "status": "process",
                "key_used": key,
                "env_token": primary or key,
                "path": None,
                "path_display": None,
                "line": None,
                "in_process": True,
            }

    suggested = [_path_display(f) for f in files[:4]]
    if len(files) > 4:
        suggested.append(f"(+{len(files) - 4} autres .env scannés)")
    return {
        "status": "missing",
        "key_used": None,
        "env_token": primary,
        "path": None,
        "path_display": None,
        "line": None,
        "in_process": False,
        "suggested_paths": suggested,
        "keys_tried": keys,
    }


def task_sources_secret_locations() -> dict[str, Any]:
    """Localisation pour chaque entrée ``task_sources`` valide du config utilisateur."""
    sources, parse_errors = task_sources_from_user_config()
    locations: list[dict[str, Any]] = []
    for entry in sources:
        loc = locate_env_token(
            str(entry.get("env_token") or ""),
            str(entry.get("backend") or ""),
            local_project_path=entry.get("local_project_path"),
        )
        locations.append(
            {
                "id": entry["id"],
                "label": entry.get("label"),
                "backend": entry.get("backend"),
                **loc,
            }
        )
    return {"sources": locations, "parse_errors": parse_errors}
