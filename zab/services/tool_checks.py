"""Read-only availability checks for Zab action tools."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from zab.services import tool_catalog


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _primary_impl(tool: dict[str, Any]) -> dict[str, Any] | None:
    impls = [item for item in tool.get("implementations") or [] if isinstance(item, dict)]
    if not impls:
        return None
    primary_id = str(tool.get("primary_implementation_id") or "").strip().lower()
    if primary_id:
        for impl in impls:
            if str(impl.get("id") or "").strip().lower() == primary_id:
                return dict(impl)
    for impl in impls:
        if str(impl.get("role") or "").lower() != "fallback":
            return dict(impl)
    return dict(impls[0])


def _fallback_impls(tool: dict[str, Any]) -> list[dict[str, Any]]:
    impls = [item for item in tool.get("implementations") or [] if isinstance(item, dict)]
    return [dict(item) for item in impls if str(item.get("role") or "").lower() == "fallback"]


def _implementation_summary(impl: dict[str, Any] | None) -> dict[str, Any] | None:
    if not impl:
        return None
    return {
        "implementation_id": impl.get("id"),
        "kind": impl.get("kind"),
        "provider": impl.get("provider"),
        "role": impl.get("role"),
        "priority": impl.get("priority"),
        "coverage": impl.get("coverage"),
        "command": impl.get("command"),
        "fallback_when": impl.get("fallback_when") or [],
    }


def _tool_checks(tool: dict[str, Any]) -> list[dict[str, Any]]:
    linked = [item for item in tool.get("linked_skills") or [] if isinstance(item, dict)]
    found = [item for item in linked if item.get("found")]
    missing = [item for item in linked if not item.get("found")]
    checks: list[dict[str, Any]] = [
        {
            "id": "catalog_status",
            "status": str(tool.get("status") or "skipped"),
            "message": str(tool.get("status_reason") or "status inconnu"),
            "detail": {
                "availability_tag": tool.get("availability_tag"),
                "primary_implementation_id": tool.get("primary_implementation_id"),
                "has_fallback": bool(tool.get("has_fallback")),
            },
        }
    ]
    if linked:
        checks.append(
            {
                "id": "linked_skills",
                "status": "ok" if not missing else "warn",
                "message": f"{len(found)}/{len(linked)} skill(s) résolue(s)",
                "detail": {"resolved": found, "missing": missing},
            }
        )
    primary = _primary_impl(tool)
    if primary:
        checks.append(
            {
                "id": "primary_implementation",
                "status": str(tool.get("status") or "skipped"),
                "message": str(tool.get("status_reason") or "impl primaire évaluée"),
                "detail": _implementation_summary(primary),
            }
        )
    else:
        checks.append(
            {
                "id": "primary_implementation",
                "status": "skipped",
                "message": "aucune implémentation primaire",
                "detail": {},
            }
        )
    if tool.get("has_fallback"):
        checks.append(
            {
                "id": "fallbacks_present",
                "status": "warn",
                "message": f"{len(_fallback_impls(tool))} fallback(s) déclaré(s)",
                "detail": {"fallbacks": [_implementation_summary(item) for item in _fallback_impls(tool)]},
            }
        )
    return checks


def _validation_issues(state: dict[str, Any] | None = None) -> dict[str, list[dict[str, Any]]]:
    payload = tool_catalog.validate_tools(state=state)
    by_tool: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for issue in payload.get("issues") or []:
        if not isinstance(issue, dict):
            continue
        tool_id = str(issue.get("tool_id") or "").strip()
        if tool_id:
            by_tool[tool_id].append(dict(issue))
    return dict(by_tool)


def _tool_result(tool: dict[str, Any], *, validation_issues: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "tool_id": tool.get("id"),
        "label": tool.get("label"),
        "kind": tool.get("kind"),
        "status": tool.get("status"),
        "availability_tag": tool.get("availability_tag"),
        "status_reason": tool.get("status_reason"),
        "primary": _implementation_summary(_primary_impl(tool)),
        "fallbacks": [_implementation_summary(item) for item in _fallback_impls(tool)],
        "providers": tool.get("providers") or [],
        "origin": tool.get("origin"),
        "skill_refs": tool.get("skill_refs") or [],
        "linked_skills": tool.get("linked_skills") or [],
        "checks": _tool_checks(tool),
        "validation_issues": validation_issues or [],
        "last_checked_at_utc": _now(),
    }


def check_tool(tool_id: str, *, state: dict[str, Any] | None = None) -> dict[str, Any] | None:
    catalog = tool_catalog.build_tools_catalog(state=state)
    key = tool_id.strip().lower()
    tool = next((row for row in catalog.get("tools") or [] if str(row.get("id") or "").lower() == key), None)
    if not tool:
        return None
    by_tool = _validation_issues(state=state)
    result = _tool_result(tool, validation_issues=by_tool.get(str(tool.get("id") or ""), []))
    result.update(
        {
            "contract": "tools-check",
            "contract_version": tool_catalog.TOOLS_CATALOG_CONTRACT_VERSION,
            "generated_at_utc": catalog.get("generated_at_utc"),
        }
    )
    return result


def check_tools(
    *,
    tool_ids: list[str] | None = None,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    catalog = tool_catalog.build_tools_catalog(state=state)
    wanted = {item.strip().lower() for item in (tool_ids or []) if item and item.strip()}
    rows = list(catalog.get("tools") or [])
    if wanted:
        rows = [row for row in rows if str(row.get("id") or "").lower() in wanted]

    by_tool = _validation_issues(state=state)
    tools = [
        _tool_result(tool, validation_issues=by_tool.get(str(tool.get("id") or ""), []))
        for tool in rows
    ]
    tools.sort(key=lambda x: str(x.get("label") or x.get("tool_id") or "").casefold())
    counts = Counter(str(tool.get("status") or "skipped") for tool in tools)
    payload = {
        "contract": "tools-checks",
        "contract_version": tool_catalog.TOOLS_CATALOG_CONTRACT_VERSION,
        "generated_at_utc": catalog.get("generated_at_utc"),
        "filters": {"tool_ids": sorted(wanted) if wanted else None},
        "summary": {
            "total": len(tools),
            "ok": counts.get("ok", 0),
            "warn": counts.get("warn", 0),
            "fail": counts.get("fail", 0),
            "skipped": counts.get("skipped", 0),
        },
        "tools": tools,
    }
    return payload
