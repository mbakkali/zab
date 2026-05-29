"""Agrégation des « runtimes » modèles (agentpipe, CodexBar, proxy Vertex local) pour le dashboard."""

from __future__ import annotations

from typing import Any

from zab.services import scan_persist
from zab.user_config import load_user_config


def _coding_flat_from_cfg(cfg: dict[str, Any]) -> list[str]:
    md = cfg.get("models_discovery")
    if not isinstance(md, dict):
        return []
    ap = md.get("agentpipe")
    if not isinstance(ap, dict):
        return []
    raw = ap.get("coding_models_flat")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for x in raw:
        if isinstance(x, str) and x.strip() and x not in out:
            out.append(x.strip())
    return out


def _coding_flat_from_last_scan() -> list[str]:
    prev = scan_persist.load_last_scan()
    if not prev or not isinstance(prev.get("scan"), dict):
        return []
    scan = prev["scan"]
    ap = scan.get("agentpipe") if isinstance(scan, dict) else None
    if not isinstance(ap, dict):
        return []
    raw = ap.get("coding_models_flat")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for x in raw:
        if isinstance(x, str) and x.strip() and x not in out:
            out.append(x.strip())
    return out


def collect_model_runtimes() -> dict[str, Any]:
    cfg = dict(load_user_config())
    cfg.pop("_error", None)

    from_flat = _coding_flat_from_cfg(cfg)
    from_scan = _coding_flat_from_last_scan()
    merged: list[str] = []
    for x in from_flat + from_scan:
        if x not in merged:
            merged.append(x)

    agentpipe_path = cfg.get("agentpipe_config_path")
    codexbar_path = cfg.get("codexbar_config_path")

    runtimes: list[dict[str, Any]] = [
        {
            "id": "vertex_openai_via_zab",
            "kind": "vertex_proxy",
            "label": "Vertex Gemini (proxy zab)",
            "description": (
                "OpenAI-compatible via zab : le jeton SA est rafraîchi dans le process du dashboard, "
                "évitant le 401 Hermes après hot-swap de modèle si VERTEX_ACCESS_TOKEN n'est pas dans le process."
            ),
            "hermes_custom_base_path": "/api/vertex-openai/v1",
            "hermes_hint": (
                "Hermes (provider custom) : base_url = <origine du dashboard> + /api/vertex-openai/v1 "
                "(ex. http://127.0.0.1:8742/api/vertex-openai/v1). Variables GCP : GOOGLE_APPLICATION_CREDENTIALS, "
                "GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION (défaut global)."
            ),
        },
        {
            "id": "agentpipe_yaml",
            "kind": "agentpipe",
            "label": "Agentpipe (YAML)",
            "config_path_override": agentpipe_path,
            "coding_models_flat": from_flat or None,
        },
        {
            "id": "codexbar_json",
            "kind": "codexbar",
            "label": "CodexBar",
            "config_path_override": codexbar_path,
        },
    ]

    if merged:
        runtimes.append(
            {
                "id": "coding_models_union",
                "kind": "synthesis",
                "label": "Modèles coding (config + dernier scan)",
                "models": merged,
            }
        )

    return {
        "runtimes": runtimes,
        "coding_models_flat_merged": merged,
        "user_config_keys": sorted(k for k in cfg.keys() if not k.startswith("_")),
    }
