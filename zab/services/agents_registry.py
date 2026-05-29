"""Agents CodexBar (providers activés + résolution CLI) et appel ``codexbar usage``."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from zab.user_config import load_user_config

_PROVIDER_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$", re.I)


def codexbar_config_path_resolved() -> Path:
    cfg = load_user_config()
    raw = cfg.get("codexbar_config_path")
    if isinstance(raw, str) and raw.strip():
        return Path(raw.strip()).expanduser().resolve()
    return (Path.home() / ".codexbar" / "config.json").resolve()


def _cli_path_overrides_from_user_config() -> dict[str, str]:
    """Chemins CLI explicites dans ``~/.config/zab/config.yaml``.

    Clés supportées (dict ``str -> chemin``) :
    - ``agent_cli_paths`` (recommandé)
    - ``agents`` si toutes les valeurs sont des chaînes (chemins), ignoré sinon.
    """
    cfg = load_user_config()
    out: dict[str, str] = {}

    raw = cfg.get("agent_cli_paths")
    if isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(k, str) and isinstance(v, str) and v.strip():
                out[k.strip()] = v.strip()

    raw2 = cfg.get("agents")
    if isinstance(raw2, dict):
        for k, v in raw2.items():
            if not isinstance(k, str) or k in out:
                continue
            if isinstance(v, str) and v.strip():
                out[k.strip()] = v.strip()

    return out


def _resolve_cli_for_provider(provider_id: str, overrides: dict[str, str]) -> tuple[str | None, bool, str]:
    """Retourne (chemin_absolu_ou_None, sur_path, source)."""
    o = overrides.get(provider_id)
    if isinstance(o, str) and o.strip():
        p = Path(o.strip()).expanduser()
        try:
            rp = p.resolve()
        except OSError:
            return str(p), False, "override"
        if rp.is_file() or shutil.which(str(rp)):
            return str(rp), True, "override"
        return str(rp), False, "override"
    loc = shutil.which(provider_id)
    if loc:
        return loc, True, "which"
    return None, False, "which"


def list_codexbar_agents() -> dict[str, Any]:
    path = codexbar_config_path_resolved()
    overrides = _cli_path_overrides_from_user_config()
    if not path.is_file():
        return {
            "config_path": str(path),
            "present": False,
            "agents": [],
            "error": "codexbar_config_missing",
        }
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return {"config_path": str(path), "present": True, "agents": [], "error": f"invalid_json:{e}"}

    providers = doc.get("providers") if isinstance(doc, dict) else None
    if not isinstance(providers, list):
        return {"config_path": str(path), "present": True, "agents": [], "error": "no_providers_key"}

    agents: list[dict[str, Any]] = []
    for item in providers:
        if not isinstance(item, dict):
            continue
        if item.get("enabled") is not True:
            continue
        pid = item.get("id")
        if not isinstance(pid, str) or not pid.strip():
            continue
        pid = pid.strip()
        cli_path, on_path, src = _resolve_cli_for_provider(pid, overrides)
        row: dict[str, Any] = {
            "id": pid,
            "enabled": True,
            "cli_path": cli_path,
            "on_path": on_path,
            "cli_source": src,
        }
        if isinstance(item.get("source"), str):
            row["provider_source"] = item["source"]
        agents.append(row)

    agents.sort(key=lambda x: str(x["id"]).lower())
    return {"config_path": str(path), "present": True, "agents": agents}


def codexbar_usage_json(provider: str, *, timeout_sec: float = 28.0) -> dict[str, Any]:
    """Exécute ``codexbar usage --format json --provider <id>`` (un seul provider)."""
    p = (provider or "").strip()
    if not p or not _PROVIDER_RE.match(p):
        return {"ok": False, "error": "invalid_provider", "provider": provider}
    binary = shutil.which("codexbar")
    if not binary:
        return {"ok": False, "error": "codexbar_not_found", "provider": p}
    env = {**os.environ, "NO_COLOR": "1", "TERM": "dumb"}
    try:
        r = subprocess.run(
            [binary, "usage", "--format", "json", "--provider", p, "--no-color", "--pretty"],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "provider": p}
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "error": str(e), "provider": p}

    raw_out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    payload: dict[str, Any] = {
        "ok": r.returncode == 0,
        "exit_code": r.returncode,
        "provider": p,
        "stderr_preview": err[:4000] if err else None,
    }
    if raw_out:
        try:
            payload["data"] = json.loads(raw_out)
        except json.JSONDecodeError:
            payload["ok"] = False
            payload["error"] = "invalid_json_stdout"
            payload["stdout_preview"] = raw_out[:8000]
    else:
        payload["data"] = None
        if r.returncode != 0:
            payload["ok"] = False
            if not payload.get("error"):
                payload["error"] = "empty_stdout"
    return payload
