"""Tests HTTP vers proxies LLM (LiteLLM, OpenRouter) sans fuite de secrets."""

from __future__ import annotations

import os
from typing import Any

import httpx
import yaml

from zab.paths import dashboard_local_tools_config_path


def _load_yaml() -> dict[str, Any]:
    p = dashboard_local_tools_config_path()
    if not p.is_file():
        return {}
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {"_error": "yaml_invalid"}


def probe_models(kind: str) -> dict[str, Any]:
    """kind: litellm | openrouter — GET /v1/models avec Authorization Bearer."""
    cfg = _load_yaml()
    proxies = cfg.get("proxies") or {}
    if kind == "litellm":
        block = proxies.get("litellm") or {}
    elif kind == "openrouter":
        block = proxies.get("openrouter") or {}
    else:
        return {"ok": False, "error": "kind inconnu (litellm|openrouter)"}

    base = (block.get("base_url") or "").rstrip("/")
    env_key_name = block.get("api_key_env") or (
        "OPENROUTER_API_KEY" if kind == "openrouter" else "OPENAI_API_KEY"
    )
    api_key = os.environ.get(str(env_key_name), "").strip()
    if not base:
        return {"ok": False, "error": "base_url manquant dans local-tools.yaml"}
    if not api_key:
        return {"ok": False, "error": f"variable {env_key_name} absente"}

    url = f"{base}/v1/models"
    masked = f"****{api_key[-4:]}" if len(api_key) >= 4 else "****"
    try:
        r = httpx.get(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=20.0,
        )
        body_preview = (r.text[:400] + "…") if len(r.text) > 400 else r.text
        return {
            "ok": r.is_success,
            "status_code": r.status_code,
            "url": url,
            "key_env": env_key_name,
            "key_masked": masked,
            "body_preview": body_preview,
        }
    except httpx.HTTPError as e:
        return {"ok": False, "error": str(e), "url": url, "key_env": env_key_name, "key_masked": masked}


def local_tools_public() -> dict[str, Any]:
    """Contenu YAML sans clés secrètes (structure seule)."""
    raw = _load_yaml()
    if "_hint" in raw or "_error" in raw:
        return raw
    out: dict[str, Any] = {"ide": raw.get("ide"), "proxies": {}}
    proxies = raw.get("proxies") or {}
    for name, block in proxies.items():
        if not isinstance(block, dict):
            continue
        out["proxies"][name] = {
            "base_url": block.get("base_url"),
            "api_key_env": block.get("api_key_env"),
        }
    return out
