"""Scan multi-sources + statut sync MCP (aligné sur l’esprit de ``skills_sync_status``)."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from zab.services import mcp_registry
from zab.services.connectors_aggregate import normalize_connector_slug
from zab.services.mcp_sources import (
    claude_desktop_user_config_path,
    cursor_user_mcp_path,
    list_mcp_servers_flat,
    mcp_fingerprint,
    scan_mcps_packages_hints,
)


def _group_by_slug(flat: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_slug: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in flat:
        name = str(s.get("name") or "").strip()
        if not name:
            continue
        slug = normalize_connector_slug(name)
        s = dict(s)
        s.setdefault("fingerprint", mcp_fingerprint(s))
        by_slug[slug].append(s)
    return dict(by_slug)


def _conflict_slugs(by_slug: dict[str, list[dict[str, Any]]]) -> set[str]:
    out: set[str] = set()
    for slug, items in by_slug.items():
        fps = {str(x.get("fingerprint") or mcp_fingerprint(x)) for x in items}
        fps.discard("")
        if len(fps) > 1:
            out.add(slug)
    return out


def mcp_sources_probe() -> dict[str, Any]:
    """Fichiers de config MCP : présence et chemins."""
    cur = cursor_user_mcp_path()
    cl = claude_desktop_user_config_path()
    return {
        "cursor_user": {"path": str(cur), "exists": cur.is_file()},
        "claude_desktop_user": {"path": str(cl), "exists": cl.is_file()},
    }


def mcp_sync_status_payload() -> dict[str, Any]:
    flat = list_mcp_servers_flat()
    by_slug = _group_by_slug(flat)
    conflicts = _conflict_slugs(by_slug)
    doc = mcp_registry.load_registry_document()
    reg_servers = doc.get("servers") if isinstance(doc.get("servers"), dict) else {}

    counts = {
        "servers_total": len(flat),
        "slugs_unique": len(by_slug),
        "stdio": sum(1 for s in flat if str(s.get("kind", "")).lower() == "stdio"),
        "http": sum(1 for s in flat if str(s.get("kind", "")).lower() == "http"),
        "conflict_slugs": len(conflicts),
        "orphan_registry": sum(
            1
            for slug, e in reg_servers.items()
            if isinstance(e, dict) and str(e.get("status", "")).lower() == "orphan"
        ),
    }

    by_source_kind: dict[str, int] = defaultdict(int)
    for s in flat:
        by_source_kind[str(s.get("source_kind") or "unknown")] += 1

    hints = scan_mcps_packages_hints()

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "sources": mcp_sources_probe(),
        "sources_scanned_counts": dict(sorted(by_source_kind.items(), key=lambda x: x[0].casefold())),
        "counts": counts,
        "mcps_packages_hints": hints,
        "conflict_slugs": sorted(conflicts, key=str.casefold),
        "explain_zero_local_mcp": (
            "Aucun serveur MCP stdio trouvé dans les fichiers scannés "
            "(dépôt skills configs/, ~/.cursor/mcp.json, Claude Desktop). "
            "Utilise « Scanner MCP locaux » après avoir configuré Cursor ou le dépôt skills."
            if counts["stdio"] == 0
            else ""
        ),
    }


def mcp_list_payload() -> dict[str, Any]:
    flat = list_mcp_servers_flat()
    out: list[dict[str, Any]] = []
    for s in flat:
        name = str(s.get("name") or "").strip()
        slug = normalize_connector_slug(name) if name else "unknown"
        st = mcp_registry.registry_status_for_slug(slug)
        row = dict(s)
        row["slug"] = slug
        row["registry_status"] = st
        out.append(row)
    return {"data": out, "total": len(out)}


def run_mcp_scan_and_persist() -> dict[str, Any]:
    flat = list_mcp_servers_flat()
    for s in flat:
        s.setdefault("fingerprint", mcp_fingerprint(s))
    by_slug = _group_by_slug(flat)
    conflicts = _conflict_slugs(by_slug)
    mcp_registry.merge_scan_into_registry(scanned_by_slug=by_slug, conflict_slugs=conflicts)
    return {
        "ok": True,
        "scanned_servers": len(flat),
        "unique_slugs": len(by_slug),
        "conflict_slugs": sorted(conflicts, key=str.casefold),
        "sync_status": mcp_sync_status_payload(),
    }
