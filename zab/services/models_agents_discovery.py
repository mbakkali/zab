"""Fusion découverte agents : ~/.agentpipe.yaml (scanner) + providers CodexBar activés."""

from __future__ import annotations

from typing import Any

from zab.services import agents_registry, scanner


def _norm(s: str) -> str:
    return s.strip().casefold()


def build_agents_discovery() -> dict[str, Any]:
    """Agrège agentpipe + codexbar pour le dashboard « Modèles & agents »."""
    cb = agents_registry.list_codexbar_agents()
    ap = scanner.scan_agentpipe()

    cb_agents = cb.get("agents") if isinstance(cb.get("agents"), list) else []
    ap_agents = ap.get("agents") if isinstance(ap.get("agents"), list) else []

    cb_by_norm: dict[str, dict[str, Any]] = {}
    for a in cb_agents:
        if not isinstance(a, dict):
            continue
        i = a.get("id")
        if not isinstance(i, str) or not i.strip():
            continue
        cb_by_norm[_norm(i)] = a

    ap_by_norm: dict[str, dict[str, Any]] = {}
    for a in ap_agents:
        if not isinstance(a, dict):
            continue
        i = a.get("id")
        if not isinstance(i, str) or not i.strip():
            continue
        ap_by_norm[_norm(i)] = a

    all_norms = sorted(set(cb_by_norm) | set(ap_by_norm), key=lambda x: x.lower())

    rows: list[dict[str, Any]] = []
    for nk in all_norms:
        cbr = cb_by_norm.get(nk)
        apr = ap_by_norm.get(nk)
        sources: list[str] = []
        if apr is not None:
            sources.append("agentpipe")
        if cbr is not None:
            sources.append("codexbar")

        display_id = (
            str(cbr["id"]).strip()
            if cbr and isinstance(cbr.get("id"), str)
            else str(apr["id"]).strip()
            if apr and isinstance(apr.get("id"), str)
            else nk
        )

        codexbar_usage_id: str | None = None
        if cbr and isinstance(cbr.get("id"), str) and cbr["id"].strip():
            codexbar_usage_id = cbr["id"].strip()

        if cbr:
            cli_path = cbr.get("cli_path")
            on_path = bool(cbr.get("on_path"))
            cli_source = str(cbr.get("cli_source") or "codexbar")
        elif apr:
            cli_path = apr.get("which_path")
            on_path = bool(apr.get("on_path"))
            cli_source = "agentpipe"
        else:
            cli_path = None
            on_path = False
            cli_source = None

        ap_type = apr.get("type") if apr and isinstance(apr.get("type"), str) else None
        coding_models = apr.get("coding_models") if isinstance(apr, dict) else None
        cm_preview: list[str] | None = None
        if isinstance(coding_models, list):
            cm_preview = [str(x) for x in coding_models if isinstance(x, str) and x.strip()][:6]

        rows.append(
            {
                "id": display_id,
                "codexbar_usage_id": codexbar_usage_id,
                "cli_path": cli_path if isinstance(cli_path, str) else None,
                "on_path": on_path,
                "cli_source": cli_source,
                "sources": sources,
                "agentpipe_type": ap_type,
                "coding_models_preview": cm_preview,
            }
        )

    return {
        "codexbar_config_path": cb.get("config_path"),
        "codexbar_present": cb.get("present"),
        "codexbar_error": cb.get("error"),
        "agentpipe_path": ap.get("path"),
        "agentpipe_present": ap.get("present"),
        "agentpipe_error": ap.get("error"),
        "rows": rows,
    }
