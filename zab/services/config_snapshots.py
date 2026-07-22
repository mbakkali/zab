"""Lecture seule de fichiers de config versionnés (pas de secrets hors fichiers)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml

from zab.paths import (
    config_dir,
    data_dir,
    dashboard_local_tools_config_path,
    primary_repo_base_for_mcp_files,
    tools_catalog_config_path,
    skills_roots_resolved_from_config,
    zab_package_dir,
)
from zab.services import skills_registry
from zab.user_config import claude_plugin_paths_resolved, load_user_config, user_config_path

MaxBytes = 400_000

ConfigKey = Literal[
    "local_tools_actual",
    "local_tools_example",
    "tools_catalog_annotations",
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
        "tools_catalog_annotations": tools_catalog_config_path(),
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
        _file_history_row(
            tools_catalog_config_path(),
            key="tools_catalog_annotations",
            title="tools.yaml d'intention",
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


WRITABLE_CONFIG_KEYS: frozenset[str] = frozenset({"local_tools_actual", "tools_catalog_annotations", "user_zab_config", "skills_registry"})


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


def _coerce_iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if not isinstance(value, str):
        return None
    s = value.strip()
    return s or None


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _latest_iso(*values: Any) -> str | None:
    best_raw: str | None = None
    best_dt: datetime | None = None
    for raw in values:
        iso = _coerce_iso(raw)
        dt = _parse_iso(iso)
        if iso is None or dt is None:
            continue
        if best_dt is None or dt > best_dt:
            best_raw = iso
            best_dt = dt
    return best_raw


def _sync_row(
    last_synced_at: str | None,
    *,
    source: str,
    detail: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    synced = _coerce_iso(last_synced_at)
    return {
        "status": status or ("synced" if synced else "never"),
        "last_synced_at": synced,
        "source": source,
        "detail": detail,
    }


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _read_yaml_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _state_last_sync_at() -> str | None:
    try:
        from zab.services import postgres_store

        if postgres_store.has_state():
            state = postgres_store.load_state()
            return _coerce_iso(state.get("last_sync_at"))
    except Exception:
        pass
    state = _read_yaml_object(data_dir() / "state.yaml")
    return _coerce_iso(state.get("last_sync_at"))


def _skills_registry_updated_at() -> str | None:
    try:
        p = skills_registry.registry_path()
    except Exception:
        return None
    doc = _read_json_object(p)
    return _coerce_iso(doc.get("updated_at"))


def _mcp_registry_updated_at() -> str | None:
    doc = _read_json_object(config_dir() / "mcp-registry.json")
    return _coerce_iso(doc.get("updated_at"))


def _scan_saved_at() -> str | None:
    doc = _read_yaml_object(data_dir() / "scan-last.yaml")
    return _coerce_iso(doc.get("saved_at_utc")) or _coerce_iso(doc.get("generated_at_utc"))


def _tasks_cache_sync() -> tuple[str | None, dict[str, dict[str, Any]]]:
    cache: dict[str, Any] | None = None
    try:
        from zab.services import postgres_store

        cache = postgres_store.load_tasks_cache()
    except Exception:
        cache = None
    if not isinstance(cache, dict):
        cache = _read_json_object(data_dir() / "tasks_cache.json")
    when = _coerce_iso(cache.get("generated_at_utc"))
    items: dict[str, dict[str, Any]] = {}
    for src in cache.get("sources") or []:
        if not isinstance(src, dict):
            continue
        sid = str(src.get("id") or "").strip()
        if not sid:
            continue
        items[sid] = _sync_row(
            when,
            source="tasks_inbox",
            detail=str(src.get("status") or "") or None,
            status="synced" if when else "never",
        )
    return when, items


def _channels_sync() -> tuple[str | None, dict[str, dict[str, Any]]]:
    channels: list[dict[str, Any]] = []
    generated_at: str | None = None
    try:
        from zab.services import postgres_store

        loaded = postgres_store.load_channels()
        channels = [x for x in loaded if isinstance(x, dict)]
    except Exception:
        channels = []
    if not channels:
        cache = _read_json_object(data_dir() / "channels_cache.json")
        generated_at = _coerce_iso(cache.get("generated_at_utc"))
        channels = [x for x in cache.get("channels") or [] if isinstance(x, dict)]
    items: dict[str, dict[str, Any]] = {}
    latest = generated_at
    for channel in channels:
        cid = str(channel.get("id") or "").strip()
        if not cid:
            continue
        when = _coerce_iso(channel.get("last_synced_at")) or generated_at
        latest = _latest_iso(latest, when)
        items[cid] = _sync_row(
            when,
            source="communication_channels",
            detail=str(channel.get("status") or "") or None,
            status=str(channel.get("status") or "synced"),
        )
    return latest, items


def config_sync_status() -> dict[str, Any]:
    """Dates de dernière synchronisation par section de ``config.yaml``.

    Lecture passive uniquement : cette fonction lit les métadonnées déjà
    persistées et ne déclenche ni scan, ni sync réseau.
    """

    state_sync = _state_last_sync_at()
    scan_sync = _scan_saved_at()
    skills_sync = _skills_registry_updated_at()
    mcp_sync = _mcp_registry_updated_at()
    tasks_sync, task_items = _tasks_cache_sync()
    channels_sync, channel_items = _channels_sync()

    sections: dict[str, dict[str, Any]] = {}
    items: dict[str, dict[str, dict[str, Any]]] = {}

    def add(keys: tuple[str, ...], when: str | None, *, source: str, detail: str | None = None) -> None:
        for key in keys:
            sections[key] = _sync_row(when, source=source, detail=detail)

    add(
        ("skills_roots", "skills_root", "skill_md_paths", "skills_registry_path", "claude_plugin_paths"),
        _latest_iso(skills_sync, state_sync),
        source="skills_registry",
    )
    add(("skills_sync",), _latest_iso(skills_sync, state_sync), source="skills_sync")
    add(("projects_roots", "organizations", "obsidian", "workstation"), state_sync, source="state_index")
    add(
        ("cli_watchlist", "tracked_env_extra", "agentpipe_config_path", "codexbar_config_path", "local_tools_path"),
        _latest_iso(scan_sync, state_sync),
        source="workspace_scan",
    )
    add(("models_discovery", "last_scan_at_utc"), scan_sync, source="workspace_scan")
    add(("mcp_config_paths", "cursor_mcp_json", "claude_desktop_mcp_json"), mcp_sync, source="mcp_registry")
    add(("task_sources",), tasks_sync, source="tasks_inbox")
    add(("communication_channels",), channels_sync, source="communication_channels")

    for key in load_user_config().keys():
        key_s = str(key)
        if key_s.startswith("_") or key_s in sections:
            continue
        sections[key_s] = _sync_row(state_sync, source="state_index", detail="fallback")

    if task_items:
        items["task_sources"] = task_items
    if channel_items:
        items["communication_channels"] = channel_items

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "state_last_sync_at": state_sync,
        "sections": sections,
        "items": items,
    }
