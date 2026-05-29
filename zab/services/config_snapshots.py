"""Lecture seule de fichiers de config versionnés (pas de secrets hors fichiers)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from zab.paths import (
    config_dir,
    data_dir,
    dashboard_local_tools_config_path,
    primary_repo_base_for_mcp_files,
    skills_roots_resolved_from_config,
    zab_package_dir,
)
from zab.services import skills_registry
from zab.user_config import claude_plugin_paths_resolved, user_config_path

MaxBytes = 400_000

ConfigKey = Literal[
    "local_tools_actual",
    "local_tools_example",
    "user_zab_config",
    "skills_registry",
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
    for p in skills_registry.adopted_skill_md_paths_resolved():
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


def _path_display(p: Path) -> str:
    try:
        resolved = p.expanduser().resolve()
    except OSError:
        resolved = p.expanduser()
    home = Path.home()
    try:
        return "~/" + str(resolved.relative_to(home))
    except ValueError:
        return str(resolved)


def resolve_config_path(key: ConfigKey | str) -> Path | None:
    k = str(key).strip().lower().replace("-", "_")
    pkg = zab_package_dir()
    sr = primary_repo_base_for_mcp_files()
    mapping: dict[str, Path] = {
        "local_tools_actual": dashboard_local_tools_config_path(),
        "local_tools_example": pkg / "local-tools.example.yaml",
        "user_zab_config": user_config_path(),
        "skills_registry": skills_registry.registry_path(),
        "cursor_mcp_json": (sr / "configs" / "cursor-mcp.json") if sr is not None else Path("/nonexistent-zab-cursor-mcp"),
        "claude_desktop_mcp_json": (sr / "configs" / "claude-desktop-mcp.json") if sr is not None else Path("/nonexistent-zab-desktop-mcp"),
        "plugin_config": (sr / "plugin-config.yaml") if sr is not None else Path("/nonexistent-zab-plugin-config"),
    }
    p = mapping.get(k)
    if p is None:
        return None
    return p


def list_config_files() -> list[dict[str, Any]]:
    """Fichier de configuration utilisateur unique (~/.config/zab/config.yaml)."""
    key: ConfigKey = "user_zab_config"
    p = resolve_config_path(key)
    if p is None:
        return []
    exists = p.is_file()
    return [
        {
            "key": key,
            "title": "~/.config/zab/config.yaml",
            "syntax": "yaml",
            "exists": exists,
            "path_display": _path_display(p),
            "hint": "skills_roots, cli_watchlist, local_tools_path, task_sources, …",
        }
    ]


def _file_history_row(path: Path, *, key: str, title: str, kind: str) -> dict[str, Any]:
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        resolved = path
    exists = resolved.is_file()
    stat = resolved.stat() if exists else None
    return {
        "key": key,
        "title": title,
        "kind": kind,
        "exists": exists,
        "path_display": str(resolved),
        "updated_at_unix": stat.st_mtime if stat is not None else None,
        "bytes": stat.st_size if stat is not None else None,
    }


def list_config_history() -> list[dict[str, Any]]:
    """Historique récupérable sans exposer de contenu ni de secrets."""
    rows: list[dict[str, Any]] = [
        _file_history_row(user_config_path(), key="user_zab_config", title="config.yaml actuel", kind="current"),
        _file_history_row(
            dashboard_local_tools_config_path(),
            key="local_tools_actual",
            title="local-tools.yaml actuel",
            kind="current",
        ),
        _file_history_row(data_dir() / "scan-last.yaml", key="scan_last", title="Dernier scan persisté", kind="scan"),
        _file_history_row(
            data_dir() / "system-check-last.json",
            key="system_check_last",
            title="Dernier check system persisté",
            kind="system_check",
        ),
    ]

    cfg = config_dir()
    if cfg.is_dir():
        for p in sorted(cfg.glob("*.zab-backup-*"), key=lambda x: x.stat().st_mtime if x.is_file() else 0, reverse=True):
            if not p.is_file() or p.name.startswith(".env."):
                continue
            rows.append(
                _file_history_row(
                    p,
                    key=f"backup:{p.name}",
                    title=f"Backup config : {p.name}",
                    kind="backup",
                )
            )

    return rows


WRITABLE_CONFIG_KEYS: frozenset[str] = frozenset({"local_tools_actual", "user_zab_config", "skills_registry"})


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
    path_display = _path_display(p)

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
