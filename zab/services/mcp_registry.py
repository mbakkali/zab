"""Registre léger des MCP locaux (~/.config/zab/mcp-registry.json)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from zab.paths import config_dir

REGISTRY_VERSION = 1
DEFAULT_FILENAME = "mcp-registry.json"

McpRegistryStatus = Literal["detected", "adopted", "conflict", "orphan", "ignored"]


def registry_path() -> Path:
    return (config_dir() / DEFAULT_FILENAME).resolve()


def load_registry_document() -> dict[str, Any]:
    p = registry_path()
    if not p.is_file():
        return {"version": REGISTRY_VERSION, "updated_at": "", "servers": {}}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"version": REGISTRY_VERSION, "updated_at": "", "servers": {}}
    if not isinstance(raw, dict):
        return {"version": REGISTRY_VERSION, "updated_at": "", "servers": {}}
    raw.setdefault("version", REGISTRY_VERSION)
    raw.setdefault("servers", {})
    if not isinstance(raw.get("servers"), dict):
        raw["servers"] = {}
    return raw


def save_registry_document(doc: dict[str, Any]) -> None:
    p = registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    doc["version"] = REGISTRY_VERSION
    doc["updated_at"] = datetime.now(timezone.utc).isoformat()
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def get_server_entry(doc: dict[str, Any], slug: str) -> dict[str, Any]:
    servers = doc.get("servers")
    if not isinstance(servers, dict):
        return {}
    e = servers.get(slug)
    return e if isinstance(e, dict) else {}


def merge_scan_into_registry(
    *,
    scanned_by_slug: dict[str, list[dict[str, Any]]],
    conflict_slugs: set[str],
) -> dict[str, Any]:
    """Met à jour le registre après un scan."""
    doc = load_registry_document()
    servers: dict[str, Any] = doc.setdefault("servers", {})
    if not isinstance(servers, dict):
        doc["servers"] = {}
        servers = doc["servers"]

    scanned_slugs = set(scanned_by_slug.keys())

    for slug, items in scanned_by_slug.items():
        if not items:
            continue
        fp = str(items[0].get("fingerprint") or "")
        prev = servers.get(slug)
        prev = prev if isinstance(prev, dict) else {}
        prev_status = str(prev.get("status", "")).lower()
        prev_fp = str(prev.get("fingerprint", ""))

        if prev_status == "ignored":
            servers[slug] = {"status": "ignored", "fingerprint": prev_fp or fp}
            continue

        if slug in conflict_slugs:
            servers[slug] = {"status": "conflict", "fingerprint": fp}
            continue

        if prev_status == "adopted":
            if prev_fp and fp and prev_fp != fp:
                servers[slug] = {"status": "conflict", "fingerprint": fp}
            else:
                servers[slug] = {"status": "adopted", "fingerprint": fp or prev_fp}
        else:
            servers[slug] = {"status": "detected", "fingerprint": fp}

    for slug in list(servers.keys()):
        if slug in scanned_slugs:
            continue
        prev = servers.get(slug)
        if not isinstance(prev, dict):
            continue
        if str(prev.get("status", "")).lower() == "ignored":
            continue
        servers[slug] = {
            "status": "orphan",
            "fingerprint": str(prev.get("fingerprint") or ""),
        }

    save_registry_document(doc)
    return doc


def registry_status_for_slug(slug: str) -> str:
    doc = load_registry_document()
    e = get_server_entry(doc, slug)
    return str(e.get("status") or "detected")


def is_slug_ignored(slug: str) -> bool:
    return registry_status_for_slug(slug).lower() == "ignored"
