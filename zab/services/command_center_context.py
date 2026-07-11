"""Daily context-intelligence packet for the Hermes Command Center skill."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from zab.paths import data_dir, user_home
from zab.services import brain, crons, state_index
from zab.services.source_health import get_source_health
from zab.services.tasks_inbox import fetch_tasks_inbox
from zab.user_config import organization_slugs_from_user_config

CONTRACT = "zab-command-center-context"
CONTRACT_VERSION = "1.0"
DEFAULT_FOCUS_ORGS = ("zab", "work", "personal", "clients")


def _focus_orgs() -> tuple[str, ...]:
    orgs = tuple(organization_slugs_from_user_config())
    return orgs or DEFAULT_FOCUS_ORGS


def packet_dir() -> Path:
    return data_dir() / "command-center"


def latest_json_path() -> Path:
    return packet_dir() / "latest-context-packet.json"


def latest_markdown_path() -> Path:
    return packet_dir() / "latest-context-packet.md"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_hours(value: Any, now: datetime) -> float | None:
    parsed = _parse_dt(value)
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds() / 3600.0)


def _source_score(source: dict[str, Any], now: datetime) -> int:
    status = str(source.get("status") or "not_verified")
    base = {
        "ok": 1.0,
        "local_ok": 0.8,
        "legacy_reference": 0.6,
        "stale": 0.35,
        "needs_auth": 0.25,
        "not_verified": 0.2,
        "error": 0.0,
    }.get(status, 0.2)
    age = _age_hours(source.get("last_success_at"), now)
    penalty = 0.0
    if age is None:
        penalty = 0.10 if status in {"local_ok", "ok"} else 0.0
    elif age > 72:
        penalty = 0.25
    elif age > 24:
        penalty = 0.10
    if source.get("warnings"):
        penalty += 0.05
    return int(max(0.0, min(1.0, base - penalty)) * 100)


def _score_sources(source_health: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for row in source_health.get("sources") or []:
        if not isinstance(row, dict):
            continue
        scored.append(
            {
                "id": row.get("id"),
                "kind": row.get("kind"),
                "status": row.get("status"),
                "freshness": row.get("freshness"),
                "score": _source_score(row, now),
                "last_success_at": row.get("last_success_at"),
                "safe_message": row.get("safe_message"),
                "warnings": row.get("warnings") or [],
            }
        )
    scored.sort(key=lambda item: (int(item.get("score") or 0), str(item.get("id") or "")))
    return scored


def _state_knowledge_sources(state: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    sources = state.get("knowledge_sources")
    if not isinstance(sources, dict):
        return out
    for key, value in sources.items():
        if not isinstance(value, dict):
            continue
        out.append(
            {
                "id": value.get("id") or key,
                "kind": value.get("kind"),
                "connected": bool(value.get("connected")),
                "configured": bool(value.get("configured")),
                "path": value.get("path"),
                "notes_count": value.get("notes_count"),
                "validation": value.get("validation") if isinstance(value.get("validation"), dict) else {},
            }
        )
    return out


def _active_project_registry_paths() -> list[Path]:
    paths: list[Path] = []
    if env_path := os.getenv("ZAB_ACTIVE_PROJECTS_REGISTRY"):
        paths.append(Path(env_path).expanduser())
    paths.extend(
        [
            user_home() / ".config/zab/active-projects.md",
            user_home() / ".hermes/skills/productivity/daily-command-center/references/active-projects.md",
            user_home()
            / ".hermes/profiles/orchestrator/skills/productivity/daily-command-center/references/active-projects.md",
        ]
    )
    return paths


def _load_active_project_registry() -> list[dict[str, Any]]:
    for path in _active_project_registry_paths():
        if not path.is_file():
            continue
        current: dict[str, Any] | None = None
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("### "):
                if current:
                    rows.append(current)
                current = {"id": line[4:].strip(), "source_path": str(path)}
                continue
            if current is None or not line.startswith("- "):
                continue
            label, sep, value = line[2:].partition(":")
            if sep:
                current[label.strip().lower().replace(" ", "_")] = value.strip()
        if current:
            rows.append(current)
        return rows
    return []


def _project_mtime(path_value: Any) -> str | None:
    if not isinstance(path_value, str) or not path_value.strip():
        return None
    try:
        path = Path(path_value).expanduser()
        if not path.exists():
            return None
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        return None


def _focus_projects(state: dict[str, Any], now: datetime, *, limit: int = 24, per_focus_org: int = 6) -> list[dict[str, Any]]:
    projects = state.get("projects")
    if not isinstance(projects, dict):
        return []
    focus_orgs = _focus_orgs()
    rows: list[dict[str, Any]] = []
    for key, value in projects.items():
        if not isinstance(value, dict):
            continue
        org = str(value.get("org") or "other").lower()
        mtime = _project_mtime(value.get("path"))
        age = _age_hours(mtime, now)
        org_rank = focus_orgs.index(org) if org in focus_orgs else len(focus_orgs)
        rows.append(
            {
                "id": key,
                "name": value.get("name") or Path(str(value.get("path") or key)).name,
                "org": org,
                "path": value.get("path") or key,
                "git_repo": bool(value.get("git_repo")),
                "git_branch": value.get("git_branch"),
                "skills_count": int(value.get("skills_count") or 0),
                "last_path_mtime": mtime,
                "age_hours": age,
                "markers": value.get("project_markers") or [],
                "aliases": value.get("aliases") or [],
                "_rank": (org_rank, 999999 if age is None else age, str(value.get("name") or key).lower()),
            }
        )
    rows.sort(key=lambda item: item["_rank"])
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    for org in focus_orgs:
        org_rows = [row for row in rows if row.get("org") == org]
        for row in org_rows[:per_focus_org]:
            selected.append(row)
            selected_ids.add(str(row.get("id")))
    for row in rows:
        if len(selected) >= limit:
            break
        key = str(row.get("id"))
        if key in selected_ids:
            continue
        selected.append(row)
        selected_ids.add(key)
    for item in selected:
        item.pop("_rank", None)
    return selected[:limit]


def _recent_tasks(tasks: dict[str, Any], now: datetime, *, hours: int = 24, limit: int = 12) -> list[dict[str, Any]]:
    since = now - timedelta(hours=hours)
    rows: list[dict[str, Any]] = []
    for item in tasks.get("all_tasks") or []:
        if not isinstance(item, dict):
            continue
        updated = _parse_dt(item.get("updated_at"))
        if updated is None or updated < since:
            continue
        rows.append(
            {
                "identifier": item.get("identifier"),
                "title": item.get("title"),
                "source_label": item.get("source_label"),
                "state": item.get("state"),
                "updated_at": item.get("updated_at"),
                "url": item.get("url"),
            }
        )
    rows.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return rows[:limit]


def _cron_signals() -> list[dict[str, Any]]:
    interesting = []
    for item in crons.load_cached_crons():
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        cid = str(item.get("id") or "")
        if "command-center" in name or "zab" in name.lower() or "zab" in cid.lower():
            interesting.append(
                {
                    "id": cid,
                    "name": name,
                    "source": item.get("source"),
                    "schedule": item.get("schedule"),
                    "enabled": item.get("enabled"),
                    "status": item.get("status"),
                    "last_run": item.get("last_run"),
                    "next_run": item.get("next_run"),
                }
            )
    return interesting


def _graph(
    *,
    state: dict[str, Any],
    focus_projects: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    knowledge_sources: list[dict[str, Any]],
    brain_status: dict[str, Any],
) -> dict[str, Any]:
    orgs_raw = state.get("orgs") if isinstance(state.get("orgs"), dict) else {}
    focus_orgs = _focus_orgs()
    orgs = [
        {
            "id": key,
            "skills_count": len(value.get("skills") or []) if isinstance(value, dict) else 0,
            "focus": key in focus_orgs,
        }
        for key, value in orgs_raw.items()
    ]
    orgs.sort(key=lambda item: (not bool(item["focus"]), str(item["id"])))

    nodes = {
        "orgs": orgs[:40],
        "projects": [
            {k: p.get(k) for k in ("name", "org", "path", "git_repo", "git_branch", "skills_count")}
            for p in focus_projects
        ],
        "sources": [{k: s.get(k) for k in ("id", "kind", "status", "score")} for s in sources],
        "knowledge_sources": knowledge_sources,
        "brain_tables": brain_status.get("brain_tables") or {},
    }
    edges: list[dict[str, Any]] = []
    for project in focus_projects:
        org = project.get("org") or "other"
        edges.append({"from": f"org:{org}", "to": f"project:{project.get('name')}", "kind": "owns"})
        edges.append({"from": f"project:{project.get('name')}", "to": "source:project_workspaces", "kind": "observed_by"})
        edges.append({"from": f"project:{project.get('name')}", "to": "source:tasks_cache", "kind": "may_have_tasks"})
    for source in sources:
        edges.append({"from": f"source:{source.get('id')}", "to": "briefing:source_health", "kind": "feeds"})
    for source in knowledge_sources:
        edges.append({"from": f"knowledge:{source.get('id')}", "to": "briefing:official_notes", "kind": "feeds"})
    return {"nodes": nodes, "edges": edges[:120]}


def _context_gaps(
    *,
    scored_sources: list[dict[str, Any]],
    tasks: dict[str, Any],
    brain_status: dict[str, Any],
    knowledge_sources: list[dict[str, Any]],
    crons_signals: list[dict[str, Any]],
    now: datetime,
) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for source in scored_sources:
        score = int(source.get("score") or 0)
        status = str(source.get("status") or "")
        if score < 70 or status in {"error", "needs_auth", "not_verified", "stale"}:
            gaps.append(
                {
                    "id": f"source:{source.get('id')}",
                    "severity": "high" if status == "error" else "medium",
                    "official": f"Source {source.get('id')} status is {status}.",
                    "observed": source.get("safe_message") or "No detailed source message.",
                    "inferred": "Briefing should mark this source as degraded and avoid overclaiming.",
                    "confidence": "high",
                }
            )

    task_age = _age_hours(tasks.get("generated_at_utc"), now)
    if task_age is None:
        gaps.append(
            {
                "id": "tasks:no-cache",
                "severity": "high",
                "official": "No task cache timestamp is available.",
                "observed": "Zab cannot prove tracker freshness for the briefing.",
                "inferred": "Run `zab tasks sync` or mark trackers cached_only.",
                "confidence": "high",
            }
        )
    elif task_age > 36:
        gaps.append(
            {
                "id": "tasks:stale-cache",
                "severity": "medium",
                "official": f"Task cache is {task_age:.1f}h old.",
                "observed": "Top priorities may miss recent tracker changes.",
                "inferred": "Refresh tasks before treating tracker state as official.",
                "confidence": "high",
            }
        )

    for source in knowledge_sources:
        validation = source.get("validation") if isinstance(source.get("validation"), dict) else {}
        missing = validation.get("missing_dirs") if isinstance(validation.get("missing_dirs"), list) else []
        if missing:
            gaps.append(
                {
                    "id": f"knowledge:{source.get('id')}:structure",
                    "severity": "low",
                    "official": f"Knowledge source {source.get('id')} is connected.",
                    "observed": f"Expected vault folders missing: {', '.join(str(x) for x in missing[:6])}.",
                    "inferred": "Use explicit note paths/search rather than assuming a strict PARA layout.",
                    "confidence": "medium",
                }
            )

    brain_tables = brain_status.get("brain_tables") if isinstance(brain_status.get("brain_tables"), dict) else {}
    if not any(int(v or 0) for v in brain_tables.values()):
        gaps.append(
            {
                "id": "brain:empty-graph",
                "severity": "medium",
                "official": "Brain graph tables are present but empty.",
                "observed": "No persisted entity/edge memory is available yet.",
                "inferred": "Use the packet graph as a lightweight bootstrap; do not claim deep graph memory.",
                "confidence": "high",
            }
        )

    failed_crons = [c for c in crons_signals if str(c.get("status")) == "error"]
    if failed_crons:
        gaps.append(
            {
                "id": "crons:zab-or-command-center-errors",
                "severity": "high",
                "official": "Some Zab/Command Center crons are in error.",
                "observed": ", ".join(str(c.get("name")) for c in failed_crons[:5]),
                "inferred": "Mention scheduler drift before relying on automated freshness.",
                "confidence": "high",
            }
        )

    return gaps


def _quality_gate(
    *,
    global_freshness_score: int,
    gaps: list[dict[str, Any]],
    recent_tasks: list[dict[str, Any]],
    source_health: dict[str, Any],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    checks.append(
        {
            "id": "freshness-score",
            "status": "pass" if global_freshness_score >= 75 else "warn" if global_freshness_score >= 50 else "fail",
            "detail": f"global freshness score is {global_freshness_score}/100",
        }
    )
    source_count = len(source_health.get("sources") or [])
    checks.append(
        {
            "id": "source-health-coverage",
            "status": "pass" if source_count >= 5 else "fail",
            "detail": f"{source_count} source-health rows available",
        }
    )
    high_gaps = [gap for gap in gaps if gap.get("severity") == "high"]
    checks.append(
        {
            "id": "high-severity-gaps",
            "status": "pass" if not high_gaps else "warn",
            "detail": f"{len(high_gaps)} high-severity context gap(s)",
        }
    )
    checks.append(
        {
            "id": "daily-task-delta",
            "status": "pass" if recent_tasks else "warn",
            "detail": f"{len(recent_tasks)} task update(s) in the last 24h",
        }
    )
    order = {"fail": 2, "warn": 1, "pass": 0}
    worst = max(checks, key=lambda item: order[str(item["status"])])
    return {"status": worst["status"], "checks": checks}


def _briefing_hints(packet: dict[str, Any]) -> list[str]:
    hints = [
        "Read this packet before producing the Hermes morning Command Center briefing.",
        "Use it as context only: Hermes still decides the final Top 3 and must separate official/observed/inferred.",
        "Surface degraded sources in the reliability footer instead of inventing missing facts.",
    ]
    if packet.get("context_gaps"):
        hints.append("Review context_gaps first; they are the most likely stale or missing facts.")
    if packet.get("quality_gate", {}).get("status") != "pass":
        hints.append("Quality gate is not pass; keep confidence labels conservative.")
    return hints


def _render_markdown(packet: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# Zab Command Center Context Packet - {packet.get('local_date')}")
    lines.append("")
    lines.append(f"- Generated: `{packet.get('generated_at_utc')}`")
    lines.append(f"- Quality gate: `{packet.get('quality_gate', {}).get('status')}`")
    lines.append(f"- Freshness score: `{packet.get('freshness', {}).get('global_score')}/100`")
    lines.append("")
    lines.append("## Hermes Instructions")
    for hint in packet.get("briefing_hints") or []:
        lines.append(f"- {hint}")
    lines.append("")
    lines.append("## Source Freshness")
    for source in packet.get("freshness", {}).get("sources") or []:
        lines.append(
            f"- `{source.get('id')}`: {source.get('score')}/100, "
            f"{source.get('status')} ({source.get('freshness')})"
        )
    lines.append("")
    lines.append("## Context Gaps")
    gaps = packet.get("context_gaps") or []
    if not gaps:
        lines.append("- None detected.")
    for gap in gaps[:12]:
        lines.append(
            f"- `{gap.get('severity')}` `{gap.get('id')}`: {gap.get('observed')} "
            f"-> {gap.get('inferred')}"
        )
    lines.append("")
    lines.append("## Delta 24h")
    delta = packet.get("delta_24h") or {}
    recent_tasks = delta.get("recent_tasks") or []
    if recent_tasks:
        lines.append("### Recent Tasks")
        for task in recent_tasks[:8]:
            lines.append(f"- {task.get('source_label')} {task.get('identifier')}: {task.get('title')}")
    else:
        lines.append("- No task update detected in the last 24h.")
    lines.append("")
    lines.append("## Active Project Registry")
    registry = packet.get("active_project_registry") or []
    if not registry:
        lines.append("- No Hermes active-project registry found.")
    for item in registry[:12]:
        label = item.get("name") or item.get("id")
        org = item.get("org") or "unknown"
        priority = item.get("priority") or "unknown"
        lines.append(f"- `{priority}` `{org}` {label}")
    lines.append("")
    lines.append("## Focus Projects")
    for project in packet.get("focus_projects") or []:
        lines.append(f"- `{project.get('org')}` {project.get('name')} - {project.get('path')}")
    lines.append("")
    lines.append("## Graph Summary")
    graph = packet.get("graph") or {}
    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), dict) else {}
    lines.append(f"- Orgs: {len(nodes.get('orgs') or [])}")
    lines.append(f"- Projects: {len(nodes.get('projects') or [])}")
    lines.append(f"- Sources: {len(nodes.get('sources') or [])}")
    lines.append(f"- Edges: {len(graph.get('edges') or [])}")
    lines.append("")
    lines.append("## Files")
    paths = packet.get("paths") or {}
    for key, value in paths.items():
        lines.append(f"- {key}: `{value}`")
    return "\n".join(lines).rstrip() + "\n"


def build_context_packet(*, refresh: bool = False) -> dict[str, Any]:
    now = _now()
    generated = now.isoformat()
    source_health = get_source_health(refresh=refresh)
    state = state_index.load_state()
    if refresh or not state:
        _, state = state_index.sync_state()
    tasks = fetch_tasks_inbox()
    brain_status = brain.status()
    scored_sources = _score_sources(source_health, now)
    global_score = (
        int(sum(int(row.get("score") or 0) for row in scored_sources) / len(scored_sources))
        if scored_sources
        else 0
    )
    knowledge_sources = _state_knowledge_sources(state)
    focus_projects = _focus_projects(state, now)
    active_registry = _load_active_project_registry()
    recent_tasks = _recent_tasks(tasks, now)
    cron_signals = _cron_signals()
    gaps = _context_gaps(
        scored_sources=scored_sources,
        tasks=tasks,
        brain_status=brain_status,
        knowledge_sources=knowledge_sources,
        crons_signals=cron_signals,
        now=now,
    )
    packet: dict[str, Any] = {
        "contract": CONTRACT,
        "contract_version": CONTRACT_VERSION,
        "generated_at_utc": generated,
        "local_date": datetime.now().astimezone().date().isoformat(),
        "refresh": refresh,
        "paths": {
            "latest_json": str(latest_json_path()),
            "latest_markdown": str(latest_markdown_path()),
        },
        "freshness": {
            "global_score": global_score,
            "sources": scored_sources,
            "status_counts": source_health.get("status_counts") or {},
        },
        "source_health": source_health,
        "knowledge_sources": knowledge_sources,
        "active_project_registry": active_registry,
        "focus_projects": focus_projects,
        "delta_24h": {
            "recent_tasks": recent_tasks,
            "recent_tasks_count": len(recent_tasks),
            "tasks_cache_generated_at_utc": tasks.get("generated_at_utc"),
        },
        "scheduler_signals": cron_signals,
        "brain_status": brain_status,
        "graph": _graph(
            state=state,
            focus_projects=focus_projects,
            sources=scored_sources,
            knowledge_sources=knowledge_sources,
            brain_status=brain_status,
        ),
        "context_gaps": gaps,
    }
    packet["quality_gate"] = _quality_gate(
        global_freshness_score=global_score,
        gaps=gaps,
        recent_tasks=recent_tasks,
        source_health=source_health,
    )
    packet["briefing_hints"] = _briefing_hints(packet)
    packet["markdown"] = _render_markdown(packet)
    return packet


def write_context_packet(packet: dict[str, Any] | None = None, *, refresh: bool = False) -> dict[str, Any]:
    payload = packet or build_context_packet(refresh=refresh)
    target_dir = packet_dir()
    history_dir = target_dir / "history"
    target_dir.mkdir(parents=True, exist_ok=True)
    history_dir.mkdir(parents=True, exist_ok=True)

    local_date = str(payload.get("local_date") or datetime.now().astimezone().date().isoformat())
    json_path = latest_json_path()
    md_path = latest_markdown_path()
    history_json = history_dir / f"{local_date}-context-packet.json"
    history_md = history_dir / f"{local_date}-context-packet.md"

    payload["paths"] = {
        **(payload.get("paths") or {}),
        "latest_json": str(json_path),
        "latest_markdown": str(md_path),
        "history_json": str(history_json),
        "history_markdown": str(history_md),
    }
    clean = {k: v for k, v in payload.items() if k != "markdown"}
    markdown = str(payload.get("markdown") or _render_markdown(payload))

    for path in (json_path, history_json):
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    for path in (md_path, history_md):
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(markdown, encoding="utf-8")
        os.replace(tmp, path)

    return payload
