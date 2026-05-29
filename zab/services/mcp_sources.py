"""Sources MCP multi-fichiers : dépôt skills, Cursor utilisateur, Claude Desktop — normalisation partagée."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from zab.paths import skills_roots_resolved_from_config
from zab.services.inventory_config import infer_mcp_repo_base_from_skill_md


def _discovery_repo_bases() -> list[Path]:
    """Même logique que ``discovery.discovery_repo_bases`` sans importer ``discovery`` (évite cycles)."""
    from zab.services import skills_registry

    bases: list[Path] = []
    seen: set[str] = set()
    for p in skills_roots_resolved_from_config():
        k = str(p.resolve())
        if k not in seen:
            seen.add(k)
            bases.append(p.resolve())
    for md in skills_registry.adopted_skill_md_paths_resolved():
        b = infer_mcp_repo_base_from_skill_md(md)
        if b is None:
            continue
        k = str(b.resolve())
        if k not in seen:
            seen.add(k)
            bases.append(b.resolve())
    return bases


def load_mcp_json(path: Path) -> dict[str, Any]:
    """Lit un JSON MCP ; retourne {} si absent ou invalide."""
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"_error": "invalid_json", "path": str(path)}


def normalize_mcp_servers(
    doc: dict[str, Any],
    source: str,
    *,
    config_file: Path | None = None,
    source_kind: str | None = None,
    skills_repo_root: str | None = None,
) -> list[dict[str, Any]]:
    """Normalise ``mcpServers`` (ou racine = map de serveurs) en liste d’entrées homogènes."""
    servers = doc.get("mcpServers", doc) if isinstance(doc, dict) else {}
    if not isinstance(servers, dict):
        return []
    items: list[dict[str, Any]] = []
    cf_base = ""
    if config_file is not None and config_file.is_file():
        cf_base = str(config_file.resolve())
    sk = source_kind or source
    for name, cfg in servers.items():
        if str(name).startswith("_") and name != "_meta":
            continue
        if not isinstance(cfg, dict):
            items.append(
                {
                    "name": str(name),
                    "kind": "unknown",
                    "target": "",
                    "enabled": True,
                    "note": "",
                    "config_path": cf_base,
                    "transport_command": None,
                    "transport_args": [],
                    "env_var_names": [],
                    "source_kind": sk,
                    "source_label": source,
                    "skills_repo_root": skills_repo_root,
                }
            )
            continue
        enabled = cfg.get("enabled", True)
        if str(name).startswith("_TODO"):
            enabled = False
        env_obj = cfg.get("env") if isinstance(cfg.get("env"), dict) else {}
        env_var_names = sorted(str(k) for k in env_obj.keys())
        cmd = cfg.get("command")
        args_raw = cfg.get("args") or []
        args_list = [str(a) for a in args_raw] if isinstance(args_raw, list) else []
        if "url" in cfg:
            kind = "http"
            target = str(cfg.get("url", ""))
        elif "command" in cfg:
            kind = "stdio"
            target = f"{cfg.get('command', '')} {' '.join(args_list)}".strip()
        else:
            kind = "other"
            target = ""
        items.append(
            {
                "name": str(name),
                "kind": kind,
                "target": target[:500],
                "enabled": bool(enabled),
                "note": str(cfg.get("note", ""))[:200],
                "config_path": cf_base,
                "transport_command": str(cmd) if cmd is not None else None,
                "transport_args": args_list[:80],
                "env_var_names": env_var_names,
                "source_kind": sk,
                "source_label": source,
                "skills_repo_root": skills_repo_root,
            }
        )
    return items


def mcp_fingerprint(server: dict[str, Any]) -> str:
    """Empreinte stable pour comparer deux définitions de serveur (même nom, config différente)."""
    payload = {
        "name": str(server.get("name", "")),
        "kind": str(server.get("kind", "")),
        "cmd": server.get("transport_command"),
        "args": server.get("transport_args") or [],
        "target": str(server.get("target", ""))[:400],
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def cursor_user_mcp_path() -> Path:
    return Path.home().expanduser() / ".cursor" / "mcp.json"


def claude_desktop_user_config_path() -> Path:
    """macOS par défaut ; ailleurs le chemin peut ne pas exister."""
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / "Claude"
        / "claude_desktop_config.json"
    )


def scan_skills_repo_config_files() -> list[dict[str, Any]]:
    """Entrées depuis ``configs/cursor-mcp.json`` et ``configs/claude-desktop-mcp.json`` par dépôt."""
    out: list[dict[str, Any]] = []
    for base in _discovery_repo_bases():
        root = str(base.resolve())
        cfgdir = base / "configs"
        cursor = cfgdir / "cursor-mcp.json"
        desktop = cfgdir / "claude-desktop-mcp.json"
        for path, sk, label in (
            (cursor, "skills_repo_cursor", "configs/cursor-mcp.json"),
            (desktop, "skills_repo_desktop", "configs/claude-desktop-mcp.json"),
        ):
            doc = load_mcp_json(path)
            for item in normalize_mcp_servers(doc, label, config_file=path, source_kind=sk, skills_repo_root=root):
                out.append(item)
    return out


def scan_user_cursor_mcp() -> list[dict[str, Any]]:
    path = cursor_user_mcp_path()
    doc = load_mcp_json(path)
    return normalize_mcp_servers(
        doc,
        "~/.cursor/mcp.json",
        config_file=path if path.is_file() else path,
        source_kind="cursor_user",
        skills_repo_root=None,
    )


def scan_user_claude_desktop_mcp() -> list[dict[str, Any]]:
    path = claude_desktop_user_config_path()
    if not path.is_file():
        return []
    doc = load_mcp_json(path)
    return normalize_mcp_servers(
        doc,
        "~/Library/Application Support/Claude/claude_desktop_config.json",
        config_file=path,
        source_kind="claude_desktop_user",
        skills_repo_root=None,
    )


def scan_mcps_packages_hints() -> list[dict[str, Any]]:
    """Répertoires sous ``<repo>/mcps/`` (indices de paquets locaux)."""
    hints: list[dict[str, Any]] = []
    for base in _discovery_repo_bases():
        mcps = base / "mcps"
        if not mcps.is_dir():
            continue
        try:
            names = sorted(
                d.name for d in mcps.iterdir() if d.is_dir() and not d.name.startswith(".")
            )
        except OSError:
            continue
        if names:
            hints.append(
                {
                    "skills_repo_root": str(base.resolve()),
                    "mcps_dir": str(mcps.resolve()),
                    "package_names": names,
                    "package_count": len(names),
                }
            )
    return hints


def list_mcp_servers_flat() -> list[dict[str, Any]]:
    """Toutes les définitions serveur MCP détectées (une entrée par nom × fichier source)."""
    servers: list[dict[str, Any]] = []
    servers.extend(scan_skills_repo_config_files())
    servers.extend(scan_user_cursor_mcp())
    servers.extend(scan_user_claude_desktop_mcp())
    for s in servers:
        s.setdefault("fingerprint", mcp_fingerprint(s))
    return servers
