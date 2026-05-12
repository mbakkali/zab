"""Scan des .env sous projects_roots + skills — fusion GITLAB_TOKEN / LINEAR_API_KEY / NOTION_TOKEN dans ~/.config/zab/.env."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from zab.paths import config_dir, skills_root_from_config_file_only
from zab.user_config import projects_roots_resolved

PM_KEYS: tuple[str, ...] = ("GITLAB_TOKEN", "LINEAR_API_KEY", "NOTION_TOKEN")


def user_pm_dotenv_path() -> Path:
    return config_dir() / ".env"


def apply_pm_tokens_from_user_dotenv() -> None:
    """
    Après chargement de skills/.env : complète os.environ avec ~/.config/zab/.env
    pour les clés PM uniquement si la variable est encore absente ou vide.
    """
    path = user_pm_dotenv_path()
    if not path.is_file():
        return
    vals = dotenv_values(path)
    for key in PM_KEYS:
        cur = os.environ.get(key)
        if cur is not None and str(cur).strip():
            continue
        v = vals.get(key)
        if v is not None and str(v).strip():
            os.environ[key] = str(v).strip()


def _consider_env_file(path: Path, found: dict[str, str], sources: list[str]) -> None:
    if not path.is_file():
        return
    vals = dotenv_values(path)
    sources.append(str(path.resolve()))
    for k in PM_KEYS:
        if k in found:
            continue
        v = vals.get(k)
        if v is not None and str(v).strip():
            found[k] = str(v).strip()


def scan_pm_tokens_from_projects() -> tuple[dict[str, str], list[str]]:
    """
    Parcourt ``projects_roots`` : ``.env`` à la racine de chaque racine + ``.env`` dans chaque sous-dossier direct ;
    puis ``skills_root/.env`` si présent.
    Première valeur non vide gagne par clé (ordre stable).
    """
    found: dict[str, str] = {}
    sources: list[str] = []

    for pr in projects_roots_resolved():
        try:
            pr_r = pr.resolve()
        except OSError:
            continue
        _consider_env_file(pr_r / ".env", found, sources)
        try:
            subs = sorted(
                (p for p in pr_r.iterdir() if p.is_dir() and not p.name.startswith(".")),
                key=lambda x: x.name.casefold(),
            )
        except OSError:
            subs = []
        for proj in subs:
            _consider_env_file(proj / ".env", found, sources)

    sr = skills_root_from_config_file_only()
    if sr is not None:
        _consider_env_file(sr / ".env", found, sources)

    return found, sources


def _quote_dotenv_value(val: str) -> str:
    v = val.strip()
    if not v:
        return '""'
    if any(c in v for c in "\n\r\"") or " " in v or "#" in v:
        escaped = v.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return v


def sync_pm_tokens_to_user_dotenv(*, force: bool = False) -> dict[str, Any]:
    """
    Fusionne les jetons PM découverts dans ``~/.config/zab/.env``.
    Conserve les autres clés déjà présentes dans ce fichier.

    - Sans ``force`` : n’écrit une clé PM que si elle est absente ou vide dans le fichier cible.
    - Avec ``force`` : remplace les clés PM par la valeur scannée lorsque le scan en fournit une.
    """
    path = user_pm_dotenv_path()
    scanned, scanned_paths = scan_pm_tokens_from_projects()
    existing_flat = dotenv_values(path) if path.is_file() else {}
    merged: dict[str, str] = {}
    for k, v in existing_flat.items():
        if v is None:
            continue
        s = str(v).strip()
        if s:
            merged[str(k)] = s

    updated: list[str] = []
    skipped_existing: list[str] = []

    for k in PM_KEYS:
        sv = scanned.get(k)
        if not sv:
            continue
        if force:
            old = merged.get(k)
            if old != sv:
                merged[k] = sv
                updated.append(k)
            continue
        if not merged.get(k):
            merged[k] = sv
            updated.append(k)
        else:
            skipped_existing.append(k)

    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{k}={_quote_dotenv_value(v)}" for k, v in sorted(merged.items())]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    apply_pm_tokens_from_user_dotenv()

    return {
        "path": str(path.resolve()),
        "scanned_env_files": len(scanned_paths),
        "keys_updated": updated,
        "keys_skipped_already_present": skipped_existing if not force else [],
        "keys_found_by_scan": sorted(scanned.keys()),
        "keys_missing_after_scan": [k for k in PM_KEYS if k not in scanned],
    }
