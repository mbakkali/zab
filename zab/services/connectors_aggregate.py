"""Agrégation logique MCP + proxies API (local-tools.yaml) pour /api/connectors."""

from __future__ import annotations

import math
import re
from typing import Any

import yaml

from zab.paths import dashboard_local_tools_config_path
from zab.services.discovery import list_mcp_configs


def normalize_connector_slug(name: str) -> str:
    base = re.sub(r"^_TODO[-_]?", "", str(name).strip(), flags=re.IGNORECASE)
    slug = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")
    return slug or "unknown"


def _display_name(slug: str, sample_name: str) -> str:
    if slug == "unknown":
        return sample_name
    return slug.replace("-", " ").strip().title()


def _load_local_tools_structure() -> dict[str, Any]:
    p = dashboard_local_tools_config_path()
    if not p.is_file():
        return {}
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError):
        return {}


def _api_forms_from_proxies() -> list[tuple[str, dict[str, Any]]]:
    """Retourne (slug, form_dict) pour chaque entrée proxies."""
    cfg = _load_local_tools_structure()
    proxies = cfg.get("proxies")
    if not isinstance(proxies, dict):
        return []
    out: list[tuple[str, dict[str, Any]]] = []
    for key, block in proxies.items():
        if not isinstance(block, dict):
            continue
        slug_raw = str(key).strip().lower().replace("_", "-")
        slug = slug_raw or "proxy"
        path = dashboard_local_tools_config_path()
        cf = str(path.resolve()) if path.is_file() else ""
        base_url = str(block.get("base_url") or "").strip()
        api_key_env = block.get("api_key_env")
        env_name = str(api_key_env) if api_key_env else None
        form_id = f"api-{slug}"
        url_target = base_url[:500] if base_url else "— base_url manquant"
        out.append(
            (
                slug,
                {
                    "id": form_id,
                    "kind": "api",
                    "transport_kind": "http",
                    "enabled": True,
                    "target": url_target,
                    "source_label": "local-tools.yaml",
                    "config_path": cf,
                    "source_ref": f"proxies.{key}",
                    "meta": {
                        "base_url": base_url or None,
                        "api_key_env": env_name,
                        "auth": "bearer" if env_name else None,
                    },
                },
            )
        )
    return out


def _build_connectors_raw() -> list[dict[str, Any]]:
    by_slug: dict[str, dict[str, Any]] = {}
    blocks = list_mcp_configs()
    source_keys_display = {"cursor_mcp": "configs/cursor-mcp.json", "claude_desktop_mcp": "configs/claude-desktop-mcp.json"}

    for block_key, block in blocks.items():
        servers = block.get("servers") or []
        src_label = source_keys_display.get(block_key, str(block_key))
        for s in servers:
            if not isinstance(s, dict):
                continue
            name = str(s.get("name", "")).strip()
            if not name:
                continue
            slug = normalize_connector_slug(name)
            entry = by_slug.setdefault(
                slug,
                {
                    "id": slug,
                    "display_name": _display_name(slug, name),
                    "tags": [],  # rempli plus tard depuis state ; vide en v1
                    "forms": [],
                },
            )
            tk = str(s.get("kind", "stdio"))
            form_id = f"mcp-{block_key}-{re.sub(r'[^a-z0-9_-]+', '-', name.lower())}"
            cf = str(s.get("config_path") or "")
            meta: dict[str, Any] = {
                "transport": tk,
                "command": s.get("transport_command"),
                "args": s.get("transport_args") or [],
                "env_vars": s.get("env_var_names") or [],
            }
            entry["forms"].append(
                {
                    "id": form_id.strip("-")[:120],
                    "kind": "mcp",
                    "transport_kind": tk if tk in ("stdio", "http", "sse") else tk,
                    "enabled": bool(s.get("enabled", True)),
                    "target": str(s.get("target") or ""),
                    "note": str(s.get("note") or "") or None,
                    "source_label": src_label,
                    "config_path": cf if cf else None,
                    "source_ref": f"{src_label}#{name}",
                    "meta": meta,
                }
            )

    for slug, form in _api_forms_from_proxies():
        entry = by_slug.setdefault(
            slug,
            {
                "id": slug,
                "display_name": _display_name(slug, slug),
                "tags": [],
                "forms": [],
            },
        )
        entry["forms"].append(form)

    return sorted(by_slug.values(), key=lambda x: str(x["display_name"]).lower())



def clear_connectors_cache() -> None:
    """Placeholder si cache réintroduit plus tard."""

    pass


def list_connectors(
    *,
    page: int = 1,
    limit: int = 50,
    q: str = "",
    kind: str | None = None,
    tag: str | None = None,
) -> dict[str, Any]:
    all_rows = list(_build_connectors_raw())
    qn = q.strip().lower()
    kn = kind.strip().lower() if kind else None
    tgn = tag.strip().lower() if tag else None

    filtered_full: list[dict[str, Any]] = []
    for row in all_rows:
        slug = str(row["id"]).lower()
        disp = str(row["display_name"]).lower()
        forms_all = list(row.get("forms") or [])

        if tgn:
            tags = [str(t).lower() for t in (row.get("tags") or [])]
            if tgn not in tags:
                continue

        forms_matched = forms_all
        if kn:
            forms_matched = [f for f in forms_all if str(f.get("kind", "")).lower() == kn]
            if not forms_matched:
                continue

        if qn:
            row_matches = qn in slug or qn in disp
            form_matches = [
                f
                for f in forms_matched
                if qn in str(f.get("target") or "").lower()
                or qn in str(f.get("source_label") or "").lower()
                or qn in str(f.get("source_ref") or "").lower()
            ]
            if not row_matches and not form_matches:
                continue
            forms_out = forms_matched if row_matches else form_matches
        else:
            forms_out = forms_matched

        filtered_full.append({**row, "forms": forms_out})

    total = len(filtered_full)
    limit = max(1, min(200, limit))
    page = max(1, page)
    pages = max(1, math.ceil(total / limit)) if total else 1
    start = (page - 1) * limit
    slice_rows = filtered_full[start : start + limit]
    summaries: list[dict[str, Any]] = []
    for row in slice_rows:
        forms = row.get("forms") or []
        kinds = sorted({str(f.get("kind", "")) for f in forms if f.get("kind")})
        transports = sorted({str(f.get("transport_kind", "")) for f in forms if f.get("transport_kind")})
        any_enabled = any(bool(f.get("enabled")) for f in forms)
        summaries.append(
            {
                "id": row["id"],
                "display_name": row["display_name"],
                "tags": row.get("tags") or [],
                "form_count": len(forms),
                "kind_badges": kinds,
                "transport_badges": transports,
                "any_enabled": any_enabled,
                "preview_target": str(forms[0].get("target") or "")[:200] if forms else "",
            }
        )
    return {
        "data": summaries,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": pages,
        },
    }


def get_connector(slug: str) -> dict[str, Any] | None:
    want = slug.strip().lower()
    if not want:
        return None
    for row in _build_connectors_raw():
        if str(row["id"]).lower() != want:
            continue
        return row
    return None
