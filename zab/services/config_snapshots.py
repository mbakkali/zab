"""Lecture seule de fichiers de config versionnés (pas de secrets hors fichiers)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from zab.paths import (
    config_dir,
    dashboard_local_tools_config_path,
    primary_repo_base_for_mcp_files,
    skills_roots_resolved_from_config,
    zab_package_dir,
)
from zab.user_config import claude_plugin_paths_resolved, skill_md_paths_resolved, user_config_path

MaxBytes = 400_000

ConfigKey = Literal[
    "local_tools_actual",
    "local_tools_example",
    "user_zab_config",
    "cursor_mcp_json",
    "claude_desktop_mcp_json",
    "plugin_config",
]


def _under_root(candidate: Path, root: Path) -> bool:
    try:
        c = candidate.resolve()
        r = root.resolve()
        return r in c.parents or c == r
    except OSError:
        return False


def _read_allowed_roots() -> list[Path]:
    """Périmètre dashboard : dépôts skills + chemins inventoriés + ~/.config/zab."""
    cfg_home = config_dir().resolve()
    roots: list[Path] = [cfg_home]
    roots.extend(skills_roots_resolved_from_config())
    seen = {str(r.resolve()) for r in roots}
    for p in skill_md_paths_resolved():
        if not p.is_file():
            continue
        try:
            pr = p.resolve().parent
            k = str(pr)
            if k not in seen:
                seen.add(k)
                roots.append(pr)
        except OSError:
            continue
    for p in claude_plugin_paths_resolved():
        if not p.is_dir():
            continue
        try:
            k = str(p.resolve())
            if k not in seen:
                seen.add(k)
                roots.append(p.resolve())
        except OSError:
            continue
    return roots


def _read_text(path: Path) -> tuple[bool, str, str | None]:
    roots = _read_allowed_roots()
    if not path.is_file():
        return False, "", None
    resolved = path.resolve()
    if not any(_under_root(resolved, ar) for ar in roots):
        return False, "", "path_outside_roots"

    raw = resolved.read_bytes()
    if len(raw) > MaxBytes:
        preview = raw[: MaxBytes // 2].decode("utf-8", errors="replace")
        return True, preview + "\n\n… tronqué (fichier > limite lecture)\n", "truncated"
    return True, raw.decode("utf-8", errors="replace"), None


def resolve_config_path(key: ConfigKey | str) -> Path | None:
    k = str(key).strip().lower().replace("-", "_")
    pkg = zab_package_dir()
    sr = primary_repo_base_for_mcp_files()
    mapping: dict[str, Path] = {
        "local_tools_actual": dashboard_local_tools_config_path(),
        "local_tools_example": pkg / "local-tools.example.yaml",
        "user_zab_config": user_config_path(),
        "cursor_mcp_json": (sr / "configs" / "cursor-mcp.json") if sr is not None else Path("/nonexistent-zab-cursor-mcp"),
        "claude_desktop_mcp_json": (sr / "configs" / "claude-desktop-mcp.json") if sr is not None else Path("/nonexistent-zab-desktop-mcp"),
        "plugin_config": (sr / "plugin-config.yaml") if sr is not None else Path("/nonexistent-zab-plugin-config"),
    }
    p = mapping.get(k)
    if p is None:
        return None
    return p


def list_config_files() -> list[dict[str, Any]]:
    """Fichiers éditables / consultables — données pilotées par ~/.config/zab/config.yaml."""
    out: list[dict[str, Any]] = []
    meta: list[tuple[ConfigKey, str, Literal["yaml", "json"], str]] = [
        ("user_zab_config", "~/.config/zab/config.yaml (skill_md_paths, skills_roots, …)", "yaml", "Éditable"),
        ("local_tools_actual", "local-tools.yaml (proxies, cli_watchlist) — voir local_tools_path dans config", "yaml", "Éditable"),
    ]
    for key, title, syntax, hint in meta:
        p = resolve_config_path(key)
        if p is None:
            continue
        exists = p.is_file()
        out.append(
            {
                "key": key,
                "title": title,
                "syntax": syntax,
                "exists": exists,
                "path_display": str(p.resolve()),
                "hint": hint or None,
            }
        )
    return out


WRITABLE_CONFIG_KEYS: frozenset[str] = frozenset({"local_tools_actual", "user_zab_config"})


def write_config_snapshot(key: ConfigKey | str, content: str) -> Path:
    """Écrit uniquement local-tools.yaml effectif ou ~/.config/zab/config.yaml."""
    k = str(key).strip().lower().replace("-", "_")
    if k not in WRITABLE_CONFIG_KEYS:
        raise ValueError("clé_non_éditable")
    p = resolve_config_path(k)
    if p is None:
        raise ValueError("clé_inconnue")
    resolved = p.expanduser().resolve()
    allowed_roots = {config_dir().resolve()}
    if not any(_under_root(resolved, ar) for ar in allowed_roots):
        raise ValueError("path_interdit")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")
    return resolved


def read_config_snapshot(key: ConfigKey | str) -> dict[str, Any]:
    p = resolve_config_path(key)
    if p is None:
        raise ValueError("clé_inconnue")
    try:
        path_display = str(p.resolve())
    except OSError:
        path_display = str(p)

    exists, body, truncate_note = _read_text(p)
    err = truncate_note == "path_outside_roots"
    return {
        "key": key,
        "exists": exists and not err,
        "path_display": path_display,
        "syntax": "json" if str(p.name).lower().endswith(".json") else "yaml",
        "content": "" if err else body if exists else "",
        "truncate_note": truncate_note if truncate_note not in (None, "path_outside_roots") else None,
        "error": "path hors périmètre" if err else None,
    }
