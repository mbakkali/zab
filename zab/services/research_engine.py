"""Deterministic research packets for agents and humans."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from zab.services import agent_context
from zab.services.source_health import get_source_health

RESEARCH_MODES = {"plan", "debug", "review", "briefing", "handoff"}


@dataclass(frozen=True)
class ResearchRequest:
    query: str
    project: str | None = None
    mode: str = "plan"
    max_tokens: int = 6000
    refresh: bool = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _intent_for(query: str, mode: str) -> dict[str, Any]:
    terms = [part.strip(".,:;!?()[]{}").lower() for part in query.split()]
    entities = [part for part in terms if len(part) > 3][:12]
    kind_by_mode = {
        "plan": "implementation_plan",
        "debug": "diagnostic",
        "review": "review",
        "briefing": "briefing",
        "handoff": "agent_handoff",
    }
    return {
        "kind": kind_by_mode.get(mode, "implementation_plan"),
        "confidence": 0.72 if query.strip() else 0.35,
        "detected_entities": entities,
    }


def _source_status(source_health: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for source in source_health.get("sources") or []:
        if not isinstance(source, dict):
            continue
        rows.append(
            {
                "source": source.get("id"),
                "kind": source.get("kind"),
                "status": source.get("status"),
                "freshness": source.get("freshness"),
                "items_considered": source.get("item_count"),
            }
        )
    return rows


def _freshness(source_health: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for source in source_health.get("sources") or []:
        if not isinstance(source, dict):
            continue
        sid = str(source.get("id") or "")
        if not sid:
            continue
        out[sid] = {
            "status": source.get("freshness"),
            "last_checked_at": source.get("last_checked_at"),
            "last_success_at": source.get("last_success_at"),
        }
    return out


def _citation(id: str, kind: str, label: str, reason: str, path: str | None = None) -> dict[str, Any]:
    payload = {"id": id, "kind": kind, "label": label, "reason": reason}
    if path:
        payload["path"] = path
    return payload


def _render_packet(
    *,
    request: ResearchRequest,
    project_payload: dict[str, Any] | None,
    bootstrap: dict[str, Any],
    skills: dict[str, Any],
    tasks: dict[str, Any],
    memory: dict[str, Any] | None,
    source_health: dict[str, Any],
    warnings: list[str],
) -> str:
    project = project_payload.get("project") if project_payload and project_payload.get("found") else None
    project_name = project.get("name") if isinstance(project, dict) else request.project
    project_path = project.get("path") if isinstance(project, dict) else None
    source_lines = [
        f"- {row.get('source')}: {row.get('status')} / {row.get('freshness')}"
        for row in _source_status(source_health)[:12]
    ]
    task_lines = [
        f"- {task.get('identifier') or task.get('display_identifier') or '?'}: {task.get('title')}"
        for task in (tasks.get("tasks") or [])[:8]
        if isinstance(task, dict)
    ]
    skill_lines = [
        f"- {skill.get('key') or skill.get('id')}: {skill.get('description') or ''}".rstrip()
        for skill in (skills.get("skills") or [])[:8]
        if isinstance(skill, dict)
    ]
    memory_lines = [
        f"- {row.get('source') or row.get('wing') or 'memory'}: {str(row.get('content') or row.get('text') or row.get('summary') or '')[:180]}"
        for row in ((memory or {}).get("results") or [])[:5]
        if isinstance(row, dict)
    ]
    commands = bootstrap.get("commands") if isinstance(bootstrap.get("commands"), dict) else {}
    action_by_mode = {
        "plan": "Lire les sources listées, identifier le plus petit changement utile, puis ajouter les tests avant la modification.",
        "debug": "Reproduire le symptôme, vérifier les sources en erreur, puis isoler la cause la plus proche du changement récent.",
        "review": "Comparer le diff aux règles projet, vérifier les tests exécutés et signaler les risques bloquants.",
        "briefing": "Résumer l'état confirmé, les lacunes de fraîcheur et les prochaines actions à faible ambiguïté.",
        "handoff": "Transmettre ce packet à l'agent exécutant avec les commandes de validation et les warnings.",
    }

    warning_lines = [f"- {warning}" for warning in warnings] if warnings else ["- None."]
    return "\n".join(
        [
            "# Research Packet",
            "",
            "## Mission",
            request.query.strip() or "(empty query)",
            "",
            "## Résumé court",
            f"Mode `{request.mode}` pour `{project_name or 'workspace Zab'}`. Packet déterministe construit depuis les contrats Zab existants.",
            "",
            "## Sources de vérité",
            "- Official: Zab state, task cache, project handoff, capabilities.",
            "- Observed: local source health, local memory status, local workspace discovery.",
            "- Inferred: next actions below; confidence depends on source freshness.",
            "",
            "## Projet / workspace",
            f"- Project: {project_name or 'not specified'}",
            f"- Path: {project_path or 'not resolved'}",
            f"- Handoff found: {bool(project_payload and project_payload.get('found'))}",
            "",
            "## Contexte pertinent",
            *(skill_lines or ["- No matching skills found in v1 packet."]),
            "",
            "## Tâches probables",
            *(task_lines or ["- No matching cached tasks found."]),
            "",
            "## Mémoire récente",
            *(memory_lines or ["- No memory hits available or memory not configured."]),
            "",
            "## Commandes utiles",
            f"- Refresh: {commands.get('refresh') or 'zab sync --json'}",
            f"- Search: {commands.get('search') or 'zab search <query> --json'}",
            f"- Security: {commands.get('security') or 'zab security status --json'}",
            "",
            "## Tests et preuves attendues",
            "- Backend: targeted pytest for changed contracts.",
            "- API/MCP: JSON contract smoke tests.",
            "- UI: Vite build and focused Playwright coverage for new views.",
            "",
            "## Actions recommandées",
            f"- {action_by_mode.get(request.mode, action_by_mode['plan'])}",
            "- Relancer `zab research ... --mode review --json` après le diff.",
            "",
            "## Warnings",
            *warning_lines,
            "",
            "## Sources et fraîcheur",
            *(source_lines or ["- No source health rows returned."]),
        ]
    )


def research(request: ResearchRequest) -> dict[str, Any]:
    query = request.query.strip()
    mode = request.mode.strip().lower() or "plan"
    warnings: list[str] = []
    if mode not in RESEARCH_MODES:
        warnings.append(f"Unsupported mode {mode!r}; falling back to plan.")
        mode = "plan"
        request = ResearchRequest(query=request.query, project=request.project, mode=mode, max_tokens=request.max_tokens, refresh=request.refresh)

    source_health = get_source_health(refresh=request.refresh)
    bootstrap = agent_context.agent_bootstrap(refresh=request.refresh)
    skills = agent_context.skills_manifest(project=request.project, query=query or None, limit=20, refresh=False)
    tasks = agent_context.tasks_list(q=query, limit=20, refresh=request.refresh)
    memory: dict[str, Any] | None = None
    project_payload: dict[str, Any] | None = None

    if request.project:
        project_payload = agent_context.project_handoff(request.project, limit=60)
        if not project_payload.get("found"):
            warnings.append(f"Project {request.project!r} was not resolved by project_handoff.")

    try:
        memory = agent_context.memory_search(query, limit=8) if query else None
    except Exception as exc:  # pragma: no cover - defensive against optional memory setup
        warnings.append(f"memory_search unavailable: {exc.__class__.__name__}")
        memory = None

    search_results = agent_context.search(query, limit=12, refresh=False) if query else {"data": [], "total": 0}
    citations = [
        _citation("src_source_health", "contract", "source-health", "Freshness and source availability for this run."),
        _citation("src_agent_bootstrap", "contract", "agent-bootstrap", "Baseline Zab paths, commands and safety policy."),
    ]
    if project_payload and project_payload.get("found"):
        project = project_payload.get("project") if isinstance(project_payload.get("project"), dict) else {}
        citations.append(
            _citation(
                "src_project_handoff",
                "contract",
                "project_handoff",
                "Project-specific context, skills and routing hints.",
                path=str(project.get("path") or "") or None,
            )
        )
    citations.extend(
        _citation(f"src_search_{idx}", "index", str(row.get("key") or row.get("id") or row.get("section")), "Matched Zab index row.")
        for idx, row in enumerate((search_results.get("data") or [])[:5], start=1)
        if isinstance(row, dict)
    )

    conflicts: list[dict[str, Any]] = []
    for row in source_health.get("sources") or []:
        if isinstance(row, dict) and row.get("status") in {"needs_auth", "error", "not_verified", "stale"}:
            conflicts.append(
                {
                    "topic": f"source:{row.get('id')}",
                    "chosen": "Continue with available local context",
                    "rejected": "Treat source as confirmed live truth",
                    "reason": row.get("safe_message") or "Source is not fully verified.",
                    "confidence": "medium",
                    "evidence": [row.get("id")],
                }
            )

    packet = _render_packet(
        request=request,
        project_payload=project_payload,
        bootstrap=bootstrap,
        skills=skills,
        tasks=tasks,
        memory=memory,
        source_health=source_health,
        warnings=warnings,
    )

    project = project_payload.get("project") if project_payload and isinstance(project_payload.get("project"), dict) else None
    return {
        "contract": "research-packet",
        "contract_version": "1.0",
        "generated_at_utc": _now(),
        "query": query,
        "mode": mode,
        "project": {
            "id": request.project,
            "path": project.get("path") if isinstance(project, dict) else None,
            "confidence": "high" if project_payload and project_payload.get("found") else ("not_applicable" if not request.project else "low"),
        },
        "intent": _intent_for(query, mode),
        "freshness": _freshness(source_health),
        "source_status": _source_status(source_health),
        "context_packet_markdown": packet,
        "citations": citations,
        "conflicts": conflicts[:20],
        "recommended_next_actions": [
            "Lire le context_packet_markdown avant de modifier le code.",
            "Vérifier les sources `needs_auth`, `error` ou `not_verified` avant de traiter leurs données comme vérité.",
            "Relancer ce research packet en mode review après le diff.",
        ],
        "warnings": warnings,
        "sources": {
            "source_health": source_health,
            "skills_total": skills.get("total"),
            "tasks_total": tasks.get("total"),
            "memory_total": (memory or {}).get("total"),
            "search_total": search_results.get("total"),
        },
    }


def research_from_params(
    query: str,
    *,
    project: str | None = None,
    mode: str = "plan",
    max_tokens: int = 6000,
    refresh: bool = False,
) -> dict[str, Any]:
    return research(ResearchRequest(query=query, project=project, mode=mode, max_tokens=max_tokens, refresh=refresh))
