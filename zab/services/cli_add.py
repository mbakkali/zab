"""Fonctions d’édition de config invoquées par `zab add` (MCP, CLI, API, env)."""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path
from typing import Any, Literal

import yaml

from zab.paths import configs_dir, local_tools_config_path
from zab.user_config import load_user_config, save_user_config

McpTarget = Literal["cursor", "desktop"]


def resolve_mcp_json_path(target: McpTarget) -> Path:
    name = "cursor-mcp.json" if target == "cursor" else "claude-desktop-mcp.json"
    return configs_dir() / name


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"mcpServers": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise ValueError(f"fichier JSON invalide ou illisible : {path} ({e})") from e
    if not isinstance(raw, dict):
        raise ValueError("le JSON MCP doit être un objet à la racine")
    return raw


def add_mcp_server(
    *,
    target: McpTarget,
    name: str,
    url: str | None,
    command: str | None,
    args: list[str] | None,
    env_pairs: dict[str, str] | None,
    force: bool,
) -> Path:
    """Ajoute ou remplace une entrée sous mcpServers. Soit url (HTTP), soit command (+ args)."""
    key = name.strip()
    if not key:
        raise ValueError("nom du serveur MCP vide")

    has_url = bool(url and url.strip())
    has_cmd = bool(command and command.strip())
    if has_url == has_cmd:
        raise ValueError("indique soit --url (MCP HTTP), soit --command (stdio), pas les deux ni aucun")

    path = resolve_mcp_json_path(target)
    doc = _load_json_object(path)
    servers = doc.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
        doc["mcpServers"] = servers

    if key in servers and not force:
        raise ValueError(f"le serveur « {key} » existe déjà (utilise --force pour remplacer)")

    block: dict[str, Any]
    if has_url:
        block = {"url": url.strip()}
    else:
        block = {"command": command.strip()}
        if args:
            block["args"] = list(args)
        if env_pairs:
            block["env"] = dict(env_pairs)

    servers[key] = block
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _load_local_tools_for_write() -> dict[str, Any]:
    p = local_tools_config_path()
    if not p.is_file():
        return {}
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except yaml.YAMLError as e:
        raise ValueError(f"YAML local-tools invalide : {p} ({e})") from e


def _write_local_tools(data: dict[str, Any]) -> Path:
    p = local_tools_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return p


def add_cli_watchlist(binary: str, *, where: Literal["local_tools", "user_config"]) -> Path:
    """Ajoute un binaire à la liste fusionnée du scan (local-tools et/ou config utilisateur)."""
    name = binary.strip()
    if not name:
        raise ValueError("nom du binaire vide")
    if re.search(r"[\s/\\]", name):
        raise ValueError("indique uniquement le nom du binaire (ex. gh), pas un chemin")

    if where == "user_config":
        cfg = dict(load_user_config())
        cfg.pop("_error", None)
        wl = cfg.get("cli_watchlist")
        if not isinstance(wl, list):
            wl = []
        names = [str(x).strip() for x in wl if isinstance(x, str) and str(x).strip()]
        if name not in names:
            names.append(name)
        cfg["cli_watchlist"] = names
        return save_user_config(cfg)

    data = _load_local_tools_for_write()
    wl = data.get("cli_watchlist")
    if not isinstance(wl, list):
        wl = []
    names = [str(x).strip() for x in wl if isinstance(x, str) and str(x).strip()]
    if name not in names:
        names.append(name)
    data["cli_watchlist"] = names
    return _write_local_tools(data)


def add_api_proxy(key: str, base_url: str, api_key_env: str | None) -> Path:
    """Ajoute une entrée sous proxies dans local-tools.yaml."""
    slug = key.strip()
    if not slug:
        raise ValueError("clé proxy vide (ex. litellm)")
    slug_norm = re.sub(r"[^a-zA-Z0-9_-]+", "_", slug).strip("_").lower() or "proxy"

    url = base_url.strip()
    if not url:
        raise ValueError("base_url vide")

    data = _load_local_tools_for_write()
    proxies = data.get("proxies")
    if not isinstance(proxies, dict):
        proxies = {}
        data["proxies"] = proxies

    block: dict[str, Any] = {"base_url": url}
    if api_key_env and api_key_env.strip():
        block["api_key_env"] = api_key_env.strip()

    proxies[slug_norm] = block
    return _write_local_tools(data)


def add_tracked_env(name: str) -> Path:
    """Ajoute une variable au catalogue étendu (onglet Sécurité + mêmes règles que ALL_TRACKED)."""
    var = name.strip()
    if not var:
        raise ValueError("nom de variable vide")
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", var):
        raise ValueError("nom de variable invalide (lettres, chiffres, underscore)")

    cfg = dict(load_user_config())
    cfg.pop("_error", None)
    extra = cfg.get("tracked_env_extra")
    if not isinstance(extra, list):
        extra = []
    names = [str(x).strip() for x in extra if isinstance(x, str) and str(x).strip()]
    if var not in names:
        names.append(var)
    cfg["tracked_env_extra"] = names
    return save_user_config(cfg)


def parse_env_flags(pairs: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in pairs:
        if "=" not in raw:
            raise ValueError(f"format env attendu KEY=value, reçu : {raw!r}")
        k, _, v = raw.partition("=")
        k = k.strip()
        if not k:
            raise ValueError(f"clé env vide dans : {raw!r}")
        out[k] = v
    return out


def parse_args_option(args_str: str | None) -> list[str] | None:
    if args_str is None or not str(args_str).strip():
        return None
    return shlex.split(args_str.strip())
