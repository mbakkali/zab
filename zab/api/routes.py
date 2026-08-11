"""Routes REST + SSE jobs."""

from __future__ import annotations

import json
import os
import queue
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
import httpx
from fastapi import APIRouter, Body, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typer.testing import CliRunner

from zab.cli import app as zab_cli_app
from zab.paths import skills_root_from_config_file_only
from zab.services import (
    agent_context,
    agents_registry,
    cli_check,
    command_center_context,
    config_snapshots,
    connectors_aggregate,
    connectors_check,
    conversations,
    crons,
    discovery,
    jobs,
    memory_db,
    model_runtimes,
    postgres_store,
    remote_vm,
    request_logs,
    scan_persist,
    scanner,
    security_secret_sync,
    skills_fs,
    skills_registry,
    state_index,
    system_check,
    system_check_persist,
    tool_catalog,
    tool_checks,
    tools_probe,
    tools_scan,
    vertex_openai_proxy,
    workstation,
)
from zab.services.capabilities import get_capabilities
from zab.services.feature_catalog import agent_guide, catalog
from zab.services.workpacket_intake import get_global_rule as get_workpacket_intake_rule
from zab.services.workpacket_intake import intake_from_params as workpacket_intake_from_params
from zab.services.pm_env_sync import sync_pm_tokens_to_user_dotenv
from zab.services import mcp_sync_status, skills_sync_status
from zab.services.hermes_config import update_external_dirs
from zab.services.models_agents_discovery import build_agents_discovery
from zab.services.env_token_locate import task_sources_secret_locations
from zab.services.tasks_inbox import check_single_source, fetch_tasks_inbox, sync_tasks_inbox
from zab.services.project_git import open_project_origin_browser, run_pm_repo_tool
from zab.services.dotenv_locate import dotenv_key_line
from zab.services.secrets_scan import scan_secret_presence
from zab.services.workspace_projects import path_is_under_projects_roots, project_dir_is_under_projects_roots
from zab.system_open import open_in_editor, open_os_path
from zab.user_config import (
    load_user_config,
    merge_models_discovery_from_workspace_scan,
    merge_projects_roots_into_config,
    save_user_config,
    security_env_paths_resolved,
    skills_sync_settings,
    user_config_path,
)

router = APIRouter()

_INVENTORY_SECTION_ALIASES: dict[str, str] = {
    "skills": "skills",
    "connectors": "connectors",
    "tools": "tools",
    "code-tools": "code_tools",
    "code_tools": "code_tools",
    "models": "models",
    "memory": "memory_sources",
    "memory-sources": "memory_sources",
    "memory_sources": "memory_sources",
    "knowledge": "knowledge_sources",
    "knowledge-sources": "knowledge_sources",
    "security": "security",
    "policies": "policies",
    "subscriptions": "subscriptions",
    "projects": "projects",
    "orgs": "orgs",
    "organizations": "orgs",
}


def _resolve_inventory_section_api(raw: str) -> str:
    section = _INVENTORY_SECTION_ALIASES.get(raw.strip().lower())
    if not section:
        choices = ", ".join(sorted(_INVENTORY_SECTION_ALIASES))
        raise HTTPException(status_code=400, detail=f"section inconnue: {raw!r}. Choix: {choices}")
    return section


def _dashboard_skills_root() -> Path | None:
    return skills_root_from_config_file_only()


def _require_dashboard_skills_root() -> Path:
    r = _dashboard_skills_root()
    if r is None:
        raise HTTPException(
            status_code=503,
            detail="Définissez skills_roots ou des skills adoptées dans ~/.config/zab/skills-registry.json pour cette action.",
        )
    return r


def _require_skills_anchor_or_project_path(path: str) -> None:
    """Lecture/écriture SKILL : ancre dépôt skills sauf chemin absolu autorisé (registre skills ou projects_roots)."""
    raw = (path or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="chemin vide")
    p = Path(raw).expanduser()
    if p.is_absolute():
        try:
            r = p.resolve()
        except OSError:
            r = None
        if r is not None and r.name == "SKILL.md":
            if path_is_under_projects_roots(r):
                return
            allowed = skills_registry.allowed_absolute_skill_paths_for_api()
            if str(r) in allowed:
                return
    if skills_root_from_config_file_only() is None:
        raise HTTPException(
            status_code=503,
            detail="Définissez skills_roots dans ~/.config/zab/config.yaml ou adoptez des skills dans le registre, "
            "ou passez un chemin absolu vers un SKILL.md sous projects_roots.",
        )


@router.get("/health")
def health(response: Response) -> dict[str, Any]:
    storage = postgres_store.probe()
    ready = bool(storage.get("ok"))
    response.headers["Cache-Control"] = "no-store"
    if not ready:
        response.status_code = 503
    return {
        "status": "ok" if ready else "degraded",
        "service": "zab",
        "dependencies": {"primary_store": storage},
    }


@router.get("/logs/files")
def logs_files_api(response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return request_logs.list_files()


@router.get("/logs/events")
def logs_events_api(
    response: Response,
    surface: str | None = Query(None),
    component: str | None = Query(None),
    level: str | None = Query(None),
    actor: str | None = Query(None),
    org: str | None = Query(None),
    project: str | None = Query(None),
    status: str | None = Query(None),
    q: str | None = Query(None),
    since: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return request_logs.query_events(
        surface=surface,
        component=component,
        level=level,
        actor=actor,
        org=org,
        project=project,
        status=status,
        q=q,
        since=since,
        limit=limit,
    )


@router.get("/logs/summary")
def logs_summary_api(response: Response, since: str | None = Query("24h")) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return request_logs.summary(since=since)


@router.get("/logs/tail")
def logs_tail_api(
    response: Response,
    file: str = Query("requests"),
    lines: int = Query(100, ge=1, le=1000),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return request_logs.tail_file(file=file, lines=lines)


@router.get("/capabilities")
def capabilities_api(response: Response) -> dict[str, Any]:
    """AI-native Core/CLI/MCP/API/UI capability manifest."""
    response.headers["Cache-Control"] = "no-store"
    return get_capabilities()


@router.head("/capabilities")
def capabilities_head() -> Response:
    """Cheap smoke check for the capability manifest contract."""
    return Response(status_code=200, media_type="application/json", headers={"Cache-Control": "no-store"})


@router.get("/source-health")
def source_health_api(response: Response, refresh: bool = Query(False)) -> dict[str, Any]:
    """Source availability, freshness and masked auth readiness for agent-grade outputs."""
    response.headers["Cache-Control"] = "no-store"
    return agent_context.source_health(refresh=refresh)


@router.head("/source-health")
def source_health_head() -> Response:
    """Cheap smoke check for the Source Health contract."""
    return Response(status_code=200, media_type="application/json", headers={"Cache-Control": "no-store"})


@router.get("/command-center/context")
def command_center_context_api(
    response: Response,
    refresh: bool = Query(False),
    write: bool = Query(False),
) -> dict[str, Any]:
    """Daily context-intelligence packet for Hermes Command Center."""
    response.headers["Cache-Control"] = "no-store"
    payload = (
        command_center_context.write_context_packet(refresh=refresh)
        if write
        else command_center_context.build_context_packet(refresh=refresh)
    )
    return {k: v for k, v in payload.items() if k != "markdown"}


@router.head("/command-center/context")
def command_center_context_head() -> Response:
    """Cheap smoke check for the Command Center context packet contract."""
    return Response(status_code=200, media_type="application/json", headers={"Cache-Control": "no-store"})


class ResearchBody(BaseModel):
    query: str = Field(..., min_length=1, description="Question or mission to research")
    project: str | None = Field(None, description="Project name or path")
    mode: str = Field("plan", description="plan|debug|review|briefing|handoff")
    max_tokens: int = Field(6000, ge=500, le=50000)
    refresh: bool = Field(False, description="Explicitly refresh supported external reads")


@router.post("/research")
def research_api(body: ResearchBody, response: Response) -> dict[str, Any]:
    """Build a deterministic, cited, freshness-aware research packet."""
    response.headers["Cache-Control"] = "no-store"
    return agent_context.research(
        body.query,
        project=body.project,
        mode=body.mode,
        max_tokens=body.max_tokens,
        refresh=body.refresh,
    )


class WorkPacketIntakeBody(BaseModel):
    signal: str = Field(..., min_length=1, description="Incoming signal, user instruction, run event, or receipt")
    source: str = Field("manual", description="Signal source: manual, codex, claude, cron, channel...")
    project: str | None = Field(None, description="Project name or path associated with the signal")
    requested_by: str | None = Field(None, description="Human or agent requesting the work")


@router.get("/workpackets/intake-rule")
def workpacket_intake_rule_api(response: Response) -> dict[str, Any]:
    """Global rule that turns incoming signals into Work Packet contracts."""
    response.headers["Cache-Control"] = "no-store"
    return get_workpacket_intake_rule()


@router.head("/workpackets/intake-rule")
def workpacket_intake_rule_head() -> Response:
    """Cheap smoke check for the Work Packet intake rule contract."""
    return Response(status_code=200, media_type="application/json", headers={"Cache-Control": "no-store"})


@router.post("/workpackets/intake")
def workpacket_intake_api(body: WorkPacketIntakeBody, response: Response) -> dict[str, Any]:
    """Classify a signal into Zab's Work Packet execution contract."""
    response.headers["Cache-Control"] = "no-store"
    payload = workpacket_intake_from_params(
        body.signal,
        source=body.source,
        project=body.project,
        requested_by=body.requested_by,
    )
    return {k: v for k, v in payload.items() if k != "markdown"}


@router.get("/channels/check")
def channels_check_api(response: Response, live: bool = False) -> dict[str, Any]:
    from zab.services.conversation_ledger.channel_bindings import list_channels

    response.headers["Cache-Control"] = "no-store"
    return list_channels(check=live)


@router.get("/interactions/timeline")
def interactions_timeline_api(
    response: Response,
    organization: str | None = None,
    client_workstream: str | None = None,
    since: str | None = None,
    limit: int = 100,
    enrich: bool = True,
    enrich_max: int = 200,
) -> dict[str, Any]:
    from zab.services import local_db
    from zab.services.conversation_ledger.content_enrichment import enrich_events_content
    from zab.services.conversation_ledger.entity_resolver import DEFAULT_ORGANIZATIONS, WORKSTREAM_SEEDS
    from zab.services.conversation_ledger.store import list_events

    response.headers["Cache-Control"] = "no-store"
    org_id = None
    if organization:
        for oid, org in DEFAULT_ORGANIZATIONS.items():
            if org["label"].lower() == organization.lower() or oid == organization:
                org_id = oid
                break
    ws_id = None
    if client_workstream:
        for wid, ws in WORKSTREAM_SEEDS.items():
            if ws["label"].lower() == client_workstream.lower() or wid == client_workstream:
                ws_id = wid
                break
    with local_db.transaction() as conn:
        events = list_events(conn, organization_id=org_id, client_workstream_id=ws_id, since=since, limit=limit)
    enrichment_stats: dict[str, int] = {"fetched": 0, "skipped": 0, "failed": 0}
    if enrich and events:
        events, enrichment_stats = enrich_events_content(
            events,
            persist=True,
            max_fetch=enrich_max,
        )
    return {
        "contract": "interactions-timeline",
        "count": len(events),
        "enrichment": enrichment_stats,
        "events": events,
    }


@router.get("/interactions/organizations")
def interactions_organizations_api(response: Response, limit: int = 2000) -> dict[str, Any]:
    """Aggregate indexed events per client organization for the cross-platform inbox."""
    from zab.services import local_db
    from zab.services.conversation_ledger.entity_resolver import DEFAULT_ORGANIZATIONS, WORKSTREAM_SEEDS
    from zab.services.conversation_ledger.store import list_events

    response.headers["Cache-Control"] = "no-store"

    def _org_of(event: dict[str, Any]) -> str | None:
        if event.get("organization_id"):
            return str(event["organization_id"])
        for link in event.get("entity_links") or []:
            if link.get("entity_type") == "organization" and link.get("entity_id"):
                return str(link["entity_id"])
        return None

    def _ws_of(event: dict[str, Any]) -> str | None:
        if event.get("client_workstream_id"):
            return str(event["client_workstream_id"])
        for link in event.get("entity_links") or []:
            if link.get("entity_type") == "client_workstream" and link.get("entity_id"):
                return str(link["entity_id"])
        return None

    with local_db.transaction() as conn:
        events = list_events(conn, limit=limit)

    orgs: dict[str, dict[str, Any]] = {}
    for event in events:
        org_id = _org_of(event)
        if not org_id:
            continue
        label = str(
            event.get("organization_label")
            or (DEFAULT_ORGANIZATIONS.get(org_id) or {}).get("label")
            or org_id
        )
        bucket = orgs.setdefault(
            org_id,
            {
                "organization_id": org_id,
                "organization_label": label,
                "event_count": 0,
                "sources": {},
                "workstreams": {},
                "last_activity": None,
            },
        )
        bucket["event_count"] += 1
        source = str(event.get("source") or "unknown")
        bucket["sources"][source] = bucket["sources"].get(source, 0) + 1
        ws_id = _ws_of(event)
        if ws_id and ws_id != "unclassified":
            ws_label = str((WORKSTREAM_SEEDS.get(ws_id) or {}).get("label") or ws_id)
            bucket["workstreams"][ws_id] = {
                "id": ws_id,
                "label": ws_label,
                "count": (bucket["workstreams"].get(ws_id) or {}).get("count", 0) + 1,
            }
        ts = str(event.get("timestamp") or "")
        if ts and (bucket["last_activity"] is None or ts > bucket["last_activity"]):
            bucket["last_activity"] = ts

    org_list = []
    for bucket in orgs.values():
        bucket["sources"] = [
            {"source": src, "count": count}
            for src, count in sorted(bucket["sources"].items(), key=lambda kv: -kv[1])
        ]
        bucket["workstreams"] = sorted(
            bucket["workstreams"].values(), key=lambda w: -int(w.get("count", 0))
        )
        org_list.append(bucket)
    org_list.sort(key=lambda b: (b.get("last_activity") or "", b.get("event_count", 0)), reverse=True)

    return {
        "contract": "interactions-organizations",
        "count": len(org_list),
        "organizations": org_list,
    }


@router.post("/interactions/sync")
def interactions_sync_api(
    response: Response,
    since: str = "90d",
    until: str | None = None,
    sources: str = "",
    channels: str = "",
    max_per_channel: int = 500,
    dry_run: bool = False,
) -> dict[str, Any]:
    from zab.services.conversation_ledger.sync import sync_channels

    response.headers["Cache-Control"] = "no-store"
    source_list = [s.strip() for s in sources.split(",") if s.strip()] or None
    channel_list = [s.strip() for s in channels.split(",") if s.strip()] or None
    return sync_channels(
        since=since,
        until=until,
        sources=source_list,
        channel_ids=channel_list,
        dry_run=dry_run,
        max_per_channel=max_per_channel,
    )


@router.get("/workpackets")
def workpackets_list_api(
    response: Response,
    state: str = "",
    organization: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    from zab.services import local_db
    from zab.services.conversation_ledger.store import list_workpackets

    response.headers["Cache-Control"] = "no-store"
    states = [s.strip() for s in state.split(",") if s.strip()] or None
    with local_db.transaction() as conn:
        items = list_workpackets(conn, states=states, limit=limit)
    if organization:
        needle = organization.lower()
        items = [
            p
            for p in items
            if needle in str(p.get("organization_id", "")).lower()
            or needle in str(p.get("organization_label", "")).lower()
        ]
    return {"contract": "workpacket-list", "count": len(items), "items": items}


@router.get("/workpackets/{wp_id}")
def workpacket_detail_api(wp_id: str, response: Response) -> dict[str, Any]:
    from zab.services import local_db
    from zab.services.conversation_ledger.store import get_workpacket, list_workpackets

    response.headers["Cache-Control"] = "no-store"
    with local_db.transaction() as conn:
        packet = get_workpacket(conn, wp_id)
        if not packet:
            for candidate in list_workpackets(conn, limit=500):
                if candidate.get("display_id") == wp_id:
                    packet = candidate
                    break
    if not packet:
        raise HTTPException(status_code=404, detail=f"workpacket not found: {wp_id}")
    return packet


@router.get("/workpackets/{wp_id}/timeline")
def workpacket_timeline_api(wp_id: str, response: Response) -> dict[str, Any]:
    from zab.services import local_db
    from zab.services.conversation_ledger.store import get_event, get_workpacket, list_workpackets

    response.headers["Cache-Control"] = "no-store"
    with local_db.transaction() as conn:
        packet = get_workpacket(conn, wp_id)
        if not packet:
            for candidate in list_workpackets(conn, limit=500):
                if candidate.get("display_id") == wp_id:
                    packet = candidate
                    break
        if not packet:
            raise HTTPException(status_code=404, detail=f"workpacket not found: {wp_id}")
        events = []
        for eid in packet.get("event_ids") or []:
            event = get_event(conn, eid)
            if event:
                events.append(event)
    return {"contract": "workpacket-timeline", "workpacket_id": packet["workpacket_id"], "events": events}


@router.get("/workpackets/{wp_id}/projections")
def workpacket_projections_api(wp_id: str, response: Response) -> dict[str, Any]:
    from zab.services import local_db
    from zab.services.conversation_ledger.store import get_workpacket, list_projections, list_workpackets

    response.headers["Cache-Control"] = "no-store"
    with local_db.transaction() as conn:
        packet = get_workpacket(conn, wp_id)
        if not packet:
            for candidate in list_workpackets(conn, limit=500):
                if candidate.get("display_id") == wp_id:
                    packet = candidate
                    break
        if not packet:
            raise HTTPException(status_code=404, detail=f"workpacket not found: {wp_id}")
        projections = list_projections(conn, packet["workpacket_id"])
    return {"contract": "workpacket-projections", "items": projections}


@router.post("/workpackets/{wp_id}/project-linear")
def workpacket_project_linear_api(
    wp_id: str,
    response: Response,
    dry_run: bool = True,
) -> dict[str, Any]:
    from zab.services.conversation_ledger.projections.linear import project_linear

    response.headers["Cache-Control"] = "no-store"
    return project_linear(wp_id, dry_run=dry_run)


@router.get("/ledger/eval")
def ledger_eval_api(response: Response, suite: str = "all") -> dict[str, Any]:
    from zab.services.conversation_ledger.eval import run_eval

    response.headers["Cache-Control"] = "no-store"
    return run_eval(suite=suite)


@router.get("/system/check")
def system_check_api(response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return system_check.run_system_check()


@router.get("/system/check/stream")
def system_check_stream() -> StreamingResponse:
    """SSE stream: emits one check result at a time.

    Event types:
      - ``registry``  (first event): list of check descriptors so the UI
        can pre-populate "pending" rows.
      - ``check``: one completed check result.
      - ``done``: final aggregate payload (percentage, ok/warn/fail counts).
    """

    def _stream() -> Any:
        # 1) Registry — tell the client what checks are coming
        registry = system_check.check_registry()
        yield f"event: registry\ndata: {json.dumps(registry, ensure_ascii=False)}\n\n"

        checks: list[dict[str, Any]] = []
        weights = {"ok": 1.0, "warn": 0.5, "fail": 0.0}

        # 2) Run checks one by one, stream each result
        for chk in system_check.iter_system_checks():
            checks.append(chk)
            yield f"event: check\ndata: {json.dumps(chk, ensure_ascii=False)}\n\n"

        # 3) Aggregate and send done
        score = sum(weights.get(str(c.get("status")), 0.0) for c in checks)
        total = len(checks)
        percentage = round((score / total) * 100) if total else 0
        summary = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "percentage": percentage,
            "score": score,
            "total": total,
            "ok": sum(1 for c in checks if c.get("status") == "ok"),
            "warn": sum(1 for c in checks if c.get("status") == "warn"),
            "fail": sum(1 for c in checks if c.get("status") == "fail"),
        }
        yield f"event: done\ndata: {json.dumps(summary, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class SystemCheckPersistBody(BaseModel):
    report: dict[str, Any] = Field(..., description="Rapport complet system check (summary + checks)")


@router.get("/system/check/last")
def system_check_last_api(response: Response) -> dict[str, Any]:
    """Dernier rapport system check persisté (sans relancer les checks)."""
    response.headers["Cache-Control"] = "no-store"
    prev = system_check_persist.load_last_system_check()
    if prev is None:
        return {"present": False}
    return {"present": True, **prev}


@router.post("/system/check/last")
def system_check_save_api(body: SystemCheckPersistBody) -> dict[str, Any]:
    """Persiste le rapport JSON et met à jour ~/.config/zab/config.yaml."""
    path = system_check_persist.persist_system_check_report(body.report)
    loaded = system_check_persist.load_last_system_check() or {}
    return {
        "saved": True,
        "path": str(path),
        "saved_at_utc": loaded.get("saved_at_utc"),
        "generated_at_utc": loaded.get("generated_at_utc"),
    }


@router.get("/cli-check")
def cli_check_api(
    response: Response,
    only: list[str] | None = Query(None, description="Limiter à un ou plusieurs ids/labels de checks"),
) -> dict[str, Any]:
    """Checks déclaratifs d'auth CLI depuis ~/.config/zab/cli-checks.json."""
    response.headers["Cache-Control"] = "no-store"
    try:
        return cli_check.run_cli_checks(only=only)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/cli-check/config")
def cli_check_config_api(response: Response) -> dict[str, Any]:
    """Retourne le chemin et le contenu du fichier JSON cli-check courant."""
    response.headers["Cache-Control"] = "no-store"
    try:
        path, cfg = cli_check.load_cli_checks_config()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"path": str(path), "config": cfg}


@router.post("/cli-check/config/checks")
def cli_check_create_config_check_api(
    check: dict[str, Any] = Body(..., description="Objet JSON du check CLI à ajouter"),
) -> dict[str, Any]:
    """Ajoute un check dans ~/.config/zab/cli-checks.json sans l'exécuter."""
    try:
        return cli_check.upsert_cli_check_config(check)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/cli-check/config/checks/{check_id}")
def cli_check_update_config_check_api(
    check_id: str,
    check: dict[str, Any] = Body(..., description="Objet JSON du check CLI à remplacer"),
) -> dict[str, Any]:
    """Remplace un check dans ~/.config/zab/cli-checks.json sans l'exécuter."""
    try:
        return cli_check.upsert_cli_check_config(check, previous_id=check_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/cli-check/config/checks/{check_id}")
def cli_check_delete_config_check_api(check_id: str) -> dict[str, Any]:
    """Supprime un check dans ~/.config/zab/cli-checks.json."""
    try:
        return cli_check.delete_cli_check_config(check_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Check inconnu : {check_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/cli-check/init")
def cli_check_init_api() -> dict[str, Any]:
    """Crée le fichier cli-checks.json d'exemple si absent."""
    path = cli_check.ensure_default_cli_checks_config()
    return {"written": True, "path": str(path)}


@router.post("/cli-check/{check_id}/open-terminal")
def cli_check_open_terminal_api(check_id: str) -> dict[str, Any]:
    """Ouvre un nouveau terminal avec la commande déclarée pour ce check."""
    try:
        return cli_check.open_check_command_terminal(check_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Check inconnu : {check_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/cli-check/{check_id}/open-login-terminal")
def cli_check_open_login_terminal_api(check_id: str) -> dict[str, Any]:
    """Ouvre un nouveau terminal avec la commande de login déclarée pour ce check."""
    try:
        return cli_check.open_check_login_terminal(check_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Check inconnu : {check_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/memory/status")
def memory_status() -> dict[str, Any]:
    return memory_db.fetch_status()


@router.get("/memory/documents")
def memory_documents(
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    st = memory_db.fetch_status()
    if not st["configured"]:
        raise HTTPException(status_code=503, detail=st.get("error") or "mémoire_non_configurée")
    if not st.get("psycopg_available"):
        raise HTTPException(status_code=503, detail=st.get("error") or "psycopg_manquant")
    if not st.get("connected"):
        raise HTTPException(status_code=503, detail=st.get("error") or "postgres_inaccessible")
    return {"documents": memory_db.fetch_documents(limit=limit, offset=offset)}


@router.get("/memory/chunks")
def memory_chunks(
    document_id: str = Query(..., description="UUID du document"),
    limit: int = Query(30, ge=1, le=100),
) -> dict[str, Any]:
    st = memory_db.fetch_status()
    if not st["configured"]:
        raise HTTPException(status_code=503, detail=st.get("error") or "mémoire_non_configurée")
    if not st.get("psycopg_available"):
        raise HTTPException(status_code=503, detail=st.get("error") or "psycopg_manquant")
    if not st.get("connected"):
        raise HTTPException(status_code=503, detail=st.get("error") or "postgres_inaccessible")
    return {"chunks": memory_db.fetch_chunks_for_document(document_id, limit=limit)}


@router.get("/memory/search")
def memory_search(
    q: str = Query(..., min_length=1, description="Recherche texte"),
    limit: int = Query(10, ge=1, le=50),
    source: str | None = Query(None, description="Filtre source exact"),
    wing: str | None = Query(None, description="Filtre wing partiel"),
) -> dict[str, Any]:
    st = memory_db.fetch_status()
    if not st["configured"]:
        raise HTTPException(status_code=503, detail=st.get("error") or "mémoire_non_configurée")
    if not st.get("psycopg_available"):
        raise HTTPException(status_code=503, detail=st.get("error") or "psycopg_manquant")
    if not st.get("connected"):
        raise HTTPException(status_code=503, detail=st.get("error") or "postgres_inaccessible")
    return {"results": memory_db.search_memory(q, limit=limit, source=source, wing=wing)}


@router.get("/memory/document/{document_id}")
def memory_document_detail(
    document_id: str,
    chunk_limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    st = memory_db.fetch_status()
    if not st["configured"]:
        raise HTTPException(status_code=503, detail=st.get("error") or "mémoire_non_configurée")
    if not st.get("psycopg_available"):
        raise HTTPException(status_code=503, detail=st.get("error") or "psycopg_manquant")
    if not st.get("connected"):
        raise HTTPException(status_code=503, detail=st.get("error") or "postgres_inaccessible")
    doc = memory_db.fetch_document_detail(document_id, chunk_limit=chunk_limit)
    if doc is None:
        raise HTTPException(status_code=404, detail="document introuvable")
    return {"document": doc}


def _with_structured_messages(doc: dict[str, Any]) -> dict[str, Any]:
    """Expose `metadata.messages` at top-level for UI clients."""
    if isinstance(doc.get("messages"), list):
        return doc
    meta = doc.get("metadata")
    if isinstance(meta, dict) and isinstance(meta.get("messages"), list):
        return {**doc, "messages": meta["messages"]}
    return {**doc, "messages": []}


@router.get("/conversations/providers")
def conversations_providers() -> dict[str, Any]:
    """État discovery local + comptes Postgres par provider."""
    return conversations.build_providers_payload()


@router.get("/conversations/health")
def conversations_health() -> dict[str, Any]:
    """Checks données Postgres + recommandations (base vide, intégrité, Gemini)."""
    return conversations.build_health_payload()


@router.get("/conversations/search")
def conversations_search(
    q: str = Query(..., min_length=1, description="Recherche texte"),
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0, le=5000),
    provider: str | None = Query(None, description="cursor|claude|codex|kimi|hermes|gemini"),
    providers: str | None = Query(None, description="Liste CSV de providers conversationnels"),
    wing: str | None = Query(None),
    source: str | None = Query(None, description="Filtre source SQL exact"),
) -> dict[str, Any]:
    st = memory_db.fetch_status()
    if not st["configured"]:
        raise HTTPException(status_code=503, detail=st.get("error") or "mémoire_non_configurée")
    if not st.get("psycopg_available"):
        raise HTTPException(status_code=503, detail=st.get("error") or "psycopg_manquant")
    if not st.get("connected"):
        raise HTTPException(status_code=503, detail=st.get("error") or "postgres_inaccessible")
    provider_filter = providers or provider
    return {
        "results": memory_db.search_conversations(
            q, limit=limit, offset=offset, provider=provider_filter, wing=wing, source=source
        )
    }


@router.get("/conversations/documents")
def conversations_documents(
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0, le=5000),
    provider: str | None = Query(None, description="cursor|claude|codex|kimi|hermes|gemini"),
    providers: str | None = Query(None, description="Liste CSV de providers conversationnels"),
    wing: str | None = Query(None),
    source: str | None = Query(None, description="Filtre source SQL exact"),
) -> dict[str, Any]:
    """Exploration paginée de l'historique conversation sans recherche plein texte."""
    st = memory_db.fetch_status()
    if not st["configured"]:
        raise HTTPException(status_code=503, detail=st.get("error") or "mémoire_non_configurée")
    if not st.get("psycopg_available"):
        raise HTTPException(status_code=503, detail=st.get("error") or "psycopg_manquant")
    if not st.get("connected"):
        raise HTTPException(status_code=503, detail=st.get("error") or "postgres_inaccessible")
    provider_filter = providers or provider
    return memory_db.fetch_conversation_documents(
        limit=limit,
        offset=offset,
        provider=provider_filter,
        wing=wing,
        source=source,
    )


@router.get("/conversations/document/{document_id}")
def conversations_document_detail(
    document_id: str,
    chunk_limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    st = memory_db.fetch_status()
    if not st["configured"]:
        raise HTTPException(status_code=503, detail=st.get("error") or "mémoire_non_configurée")
    if not st.get("psycopg_available"):
        raise HTTPException(status_code=503, detail=st.get("error") or "psycopg_manquant")
    if not st.get("connected"):
        raise HTTPException(status_code=503, detail=st.get("error") or "postgres_inaccessible")
    doc = memory_db.fetch_conversation_document_detail(document_id, chunk_limit=chunk_limit)
    if doc is None:
        raise HTTPException(status_code=404, detail="document introuvable")
    return {"document": _with_structured_messages(doc)}


class ConversationSyncBody(BaseModel):
    dry_run: bool = False
    append: bool = False
    with_mempalace: bool = False
    workspace_storage_cursor: bool = False
    providers: list[str] | None = None
    batch_id: str | None = Field(None, description="export_batch_id Postgres")


@router.post("/conversations/sync")
def conversations_sync_start(body: ConversationSyncBody) -> dict[str, Any]:
    """Démarre un job ``conversation_sync`` (logs via SSE jobs)."""
    extra: dict[str, Any] = {
        "dry_run": body.dry_run,
        "append": body.append,
        "with_mempalace": body.with_mempalace,
        "workspace_storage_cursor": body.workspace_storage_cursor,
        "providers": body.providers,
    }
    if body.batch_id:
        extra["batch_id"] = body.batch_id
    try:
        job = jobs.store.start("conversation_sync", extra)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return job.to_summary()


@router.get("/projects")
def projects_list() -> dict[str, Any]:
    """Raccourci pratique : retourne la section projects de l'overview."""
    ov = discovery.overview(from_index=True)
    return {"projects": ov.get("projects", []), "projects_roots": ov.get("projects_roots", [])}


@router.get("/config")
def config_summary() -> dict[str, Any]:
    """Raccourci pratique : résumé de la configuration zab."""
    from zab.user_config import load_user_config, user_config_path
    cfg = load_user_config()
    return {
        "config_path": str(user_config_path()),
        "keys": sorted(k for k in cfg.keys() if not str(k).startswith("_")),
        "skills_roots": cfg.get("skills_roots", []),
        "projects_roots": cfg.get("projects_roots", []),
    }


@router.get("/tasks")
def tasks_redirect(response: Response) -> dict[str, Any]:
    """Redirection vers /api/tasks/inbox."""
    response.headers["Cache-Control"] = "no-store"
    return fetch_tasks_inbox()


@router.get("/hermes/status")
def hermes_status() -> dict[str, Any]:
    """Statut rapide de l'intégration Hermes."""
    import yaml as _yaml
    from zab.services import skills_sync_status
    hcfg_path = Path.home() / ".hermes" / "config.yaml"
    result = {
        "config_exists": hcfg_path.is_file(),
        "config_path": str(hcfg_path),
        "providers": [],
        "external_dirs_count": 0,
        "memory_provider": "file",
    }
    if hcfg_path.is_file():
        try:
            doc = _yaml.safe_load(hcfg_path.read_text(encoding="utf-8")) or {}
        except Exception:
            doc = {}
        result["providers"] = list((doc.get("providers") or {}).keys()) if isinstance(doc.get("providers"), dict) else []
        skills_cfg = doc.get("skills", {}) if isinstance(doc.get("skills"), dict) else {}
        result["external_dirs_count"] = len(skills_cfg.get("external_dirs", []))
        mem = doc.get("memory", {}) if isinstance(doc.get("memory"), dict) else {}
        result["memory_provider"] = mem.get("provider", "file")
    try:
        sync = skills_sync_status.skills_sync_status_payload()
        result["hermes_sync"] = sync.get("hermes", {})
    except Exception:
        pass
    return result


@router.get("/overview")
def overview(response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return discovery.overview(from_index=True)


@router.get("/tasks/inbox")
def tasks_inbox(response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return fetch_tasks_inbox()

@router.post("/tasks/inbox/sync")
def tasks_inbox_sync(response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return sync_tasks_inbox()


@router.get("/tasks/secret-locations")
def tasks_secret_locations(response: Response) -> dict[str, Any]:
    """Pour chaque task_sources : fichier .env et ligne du jeton (sans valeur)."""
    response.headers["Cache-Control"] = "no-store"
    return task_sources_secret_locations()


@router.post("/tasks/sources/{source_id}/check")
def tasks_source_check(source_id: str, response: Response) -> dict[str, Any]:
    """Vérifie une seule source (connectivité + token) sans relancer toute la sync."""
    response.headers["Cache-Control"] = "no-store"
    try:
        return check_single_source(source_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Source inconnue : {source_id}") from exc


from urllib.parse import urlparse
import re

class TaskSourceAddBody(BaseModel):
    url: str

@router.post("/tasks/sources/add")
def tasks_sources_add(body: TaskSourceAddBody) -> dict[str, Any]:
    url = body.url.strip()
    parsed = urlparse(url)
    
    from zab.user_config import load_user_config, save_user_config
    cfg = load_user_config()
    sources = cfg.get("task_sources") or []
    if not isinstance(sources, list):
        sources = []
    
    new_source = None
    if "notion.so" in parsed.netloc:
        m = re.search(r'([a-f0-9]{32})', parsed.path)
        if m:
            db_id = m.group(1)
            # Hyphenate ID if needed, but Notion API works with 32-char hex string as ID too.
            new_source = {
                "id": f"notion-{db_id[:8]}",
                "label": f"Notion DB {db_id[:8]}",
                "backend": "notion",
                "database_id": db_id,
                "notion_title_prop": "Features",
                "url": url
            }
    elif "linear.app" in parsed.netloc:
        m = re.search(r'/project/([^/]+)', parsed.path)
        if m:
            pid = m.group(1)
            new_source = {
                "id": f"linear-{pid[:12]}",
                "label": f"Linear Project {pid[:12]}",
                "backend": "linear",
                "url": url
            }
        else:
            m = re.search(r'/team/([^/]+)', parsed.path)
            if m:
                tid = m.group(1)
                new_source = {
                    "id": f"linear-team-{tid}",
                    "label": f"Linear Team {tid.upper()}",
                    "backend": "linear",
                    "team_keys": [tid.upper()],
                    "url": url
                }
    elif "gitlab.com" in parsed.netloc:
        m = re.search(r'^/([^/]+/[^/]+(?:/[^/]+)*?)(?:/-|$)', parsed.path)
        if m:
            pwn = m.group(1)
            new_source = {
                "id": f"gitlab-{pwn.split('/')[-1]}",
                "label": f"GitLab {pwn.split('/')[-1]}",
                "backend": "gitlab",
                "path_with_namespace": pwn,
                "url": url
            }
    elif "github.com" in parsed.netloc:
        m = re.search(r'^/([^/]+/[^/]+)', parsed.path)
        if m:
            repo = m.group(1)
            new_source = {
                "id": f"github-{repo.split('/')[-1]}",
                "label": f"GitHub {repo}",
                "backend": "github",
                "repos": [repo],
                "url": url
            }
            
    if not new_source:
        raise HTTPException(status_code=400, detail="URL non reconnue (Notion, Linear, GitLab, GitHub attendus)")
        
    sources.append(new_source)
    cfg["task_sources"] = sources
    save_user_config(cfg)
    
    # Sync after adding
    from zab.services.tasks_inbox import sync_tasks_inbox
    sync_tasks_inbox()
    
    return {"status": "ok", "source": new_source}

class PmEnvSyncBody(BaseModel):
    force: bool = Field(False, description="Remplace les jetons PM même s’ils existent déjà dans ~/.config/zab/.env")


class SkillsGithubSyncBody(BaseModel):
    message: str | None = Field(None, description="Message de commit Git pour la sync skills")


@router.post("/tasks/pm-env/sync")
def tasks_pm_env_sync(body: PmEnvSyncBody = Body(default_factory=PmEnvSyncBody)) -> dict[str, Any]:
    """Scanne les .env sous projects_roots (+ skills/.env) et fusionne GITLAB_TOKEN / LINEAR_API_KEY / NOTION_TOKEN dans ~/.config/zab/.env."""
    return sync_pm_tokens_to_user_dotenv(force=body.force)


class ChannelAddBody(BaseModel):
    label: str = Field(..., description="Nom d'affichage du canal")
    type: str = Field(..., description="Type de canal (email, whatsapp, slack, telegram)")
    connector: str = Field(..., description="Connecteur associé (gmail, outlook, evolution-api, slack, telegram)")
    email_address: str | None = Field(None, description="Adresse e-mail optionnelle")
    org: str | None = Field(None, description="Slug de l'organisation associée")


@router.get("/channels")
def channels_get(response: Response) -> dict[str, Any]:
    """Liste les canaux de communication et l'état de leur synchronisation."""
    response.headers["Cache-Control"] = "no-store"
    from zab.services import communication_channels
    return communication_channels.fetch_channels_cache()


@router.post("/channels/sync")
def channels_sync(response: Response) -> dict[str, Any]:
    """Force la synchronisation de tous les canaux de communication."""
    response.headers["Cache-Control"] = "no-store"
    from zab.services import communication_channels
    return communication_channels.sync_communication_channels()


@router.get("/channels/hermes")
def channels_hermes(response: Response) -> dict[str, Any]:
    """Snapshot read-only de la configuration Channels Hermes locale."""
    response.headers["Cache-Control"] = "no-store"
    from zab.services import communication_channels
    return communication_channels.hermes_channels_snapshot()


@router.post("/channels/add")
def channels_add(body: ChannelAddBody) -> dict[str, Any]:
    """Ajoute un canal de communication."""
    from zab.services import communication_channels
    new_chan = communication_channels.add_channel_config(
        label=body.label,
        channel_type=body.type,
        connector=body.connector,
        email_address=body.email_address,
        org=body.org
    )
    # Re-sync to rebuild cache
    cache = communication_channels.sync_communication_channels()
    return {"status": "ok", "channel": new_chan, "cache": cache}


@router.post("/channels/actions/{action_id}/dismiss")
def channels_action_dismiss(action_id: str) -> dict[str, Any]:
    """Archive un message d'action à mener."""
    from zab.services import communication_channels
    try:
        return communication_channels.dismiss_action_item(action_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/channels/actions/{action_id}/obsidian-convert")
def channels_action_obsidian_convert(action_id: str) -> dict[str, Any]:
    """Convertit un message d'action en tâche dans Obsidian."""
    from zab.services import communication_channels
    try:
        return communication_channels.convert_action_to_obsidian_task(action_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


class ObsidianQuickAddBody(BaseModel):
    content: str = Field(..., description="Contenu à ajouter à la Daily Note")


@router.post("/obsidian/quick-add")
def obsidian_quick_add(body: ObsidianQuickAddBody) -> dict[str, Any]:
    """Ajoute une note ou tâche libre dans la Daily Note d'Obsidian."""
    from zab.services import obsidian_vault
    try:
        obsidian_vault.daily_append(body.content)
        return {"status": "ok", "message": "Note ajoutée avec succès"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/dashboard/stats")
def dashboard_stats(response: Response) -> dict[str, Any]:
    """Résumé des statistiques agrégées pour le Dashboard Cockpit."""
    response.headers["Cache-Control"] = "no-store"
    from zab.services import communication_channels, tasks_inbox
    
    # Charger les canaux de communication
    chan_cache = communication_channels.fetch_channels_cache()
    channels_info = chan_cache.get("channels", [])
    
    # Calculer e-mails non lus
    unread_emails = 0
    for c in channels_info:
        if c.get("type") == "email":
            unread_emails += c.get("sync_summary", {}).get("unread_count", 0)
            
    # Tâches Zab
    tasks_data = tasks_inbox.fetch_tasks_inbox()
    total_tasks = tasks_data.get("total_count", 0)
    
    # Mémoire Postgres
    from zab.services.postgres_dsn import resolve_postgres_dsn
    has_memory_db = bool(resolve_postgres_dsn())
    
    return {
        "unread_emails_count": unread_emails,
        "total_tasks_count": total_tasks,
        "urgent_actions_count": chan_cache.get("total_actions_count", 0),
        "has_memory_db": has_memory_db,
    }


@router.get("/orgs")
def orgs() -> list[dict[str, Any]]:
    return discovery.list_orgs_with_skills(from_index=True)


@router.get("/plugins")
def plugins() -> list[dict[str, Any]]:
    return discovery.list_claude_plugin_bundles()


@router.get("/mcp")
def mcp() -> dict[str, Any]:
    return discovery.list_mcp_configs()


@router.get("/mcps")
def mcps_list_api() -> dict[str, Any]:
    return mcp_sync_status.mcp_list_payload()


@router.get("/mcps/sync-status")
def mcps_sync_status_api(response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return mcp_sync_status.mcp_sync_status_payload()


@router.post("/mcps/scan")
def mcps_scan_api() -> dict[str, Any]:
    scan_out = mcp_sync_status.run_mcp_scan_and_persist()
    _, state = state_index.sync_state()
    return {**scan_out, "state_summary": state_index.state_summary(state)}


@router.get("/features")
def features_api() -> dict[str, Any]:
    return catalog()


@router.get("/agent-guide")
def agent_guide_api() -> dict[str, Any]:
    return agent_guide()


@router.get("/state")
def state_api() -> dict[str, Any]:
    return state_index.state_summary(state_index.load_state())


@router.get("/state/full")
def state_full_api() -> dict[str, Any]:
    return state_index.load_state()


@router.post("/sync")
def sync_api() -> dict[str, Any]:
    _, state = state_index.sync_state()
    return state_index.state_summary(state)


class SkillsHermesUpdateBody(BaseModel):
    apply: bool = Field(False, description="Si true, écrit ~/.hermes/config.yaml ; sinon dry-run uniquement")


@router.get("/skills")
def skills_index_api(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    q: str = "",
    tag: str | None = Query(None),
    status: str | None = Query(None, description="Filtre registry_status (candidate|adopted|…)"),
    org: str | None = Query(None),
    project: str | None = Query(None),
) -> dict[str, Any]:
    return state_index.list_section(
        "skills",
        page=page,
        limit=limit,
        q=q,
        tag=tag,
        registry_status=status,
        org=org,
        project=project,
    )


@router.get("/skills/sync-status")
def skills_sync_status_api(response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return skills_sync_status.skills_sync_status_payload()


@router.get("/skills/sync-hints")
def skills_sync_hints_api(
    response: Response,
    limit: int = Query(500, ge=1, le=2000),
) -> dict[str, Any]:
    """Indices Hermes / Cursor / Claude / GitHub par SKILL.md (clés = chemins absolus résolus)."""

    response.headers["Cache-Control"] = "no-store"
    return skills_sync_status.skills_sync_hints_payload(limit=limit)


@router.post("/skills/scan-external-dirs")
def skills_scan_external_dirs_api() -> dict[str, Any]:
    return skills_sync_status.scan_external_dirs_import_and_sync()


@router.post("/skills/auto-sync")
def skills_auto_sync_api() -> dict[str, Any]:
    """Import workspace (projects_roots) → miroir, Hermes, index ; notification optionnelle."""
    return skills_sync_status.auto_sync_project_skills()


@router.post("/skills/hermes-update")
def skills_hermes_update_api(body: SkillsHermesUpdateBody = Body(default_factory=SkillsHermesUpdateBody)) -> dict[str, Any]:
    settings = skills_sync_settings()
    result = update_external_dirs(
        config_path=settings["hermes_config_path"],
        repo_root=settings["repo_root"],
        apply=bool(body.apply),
    )
    return {
        "config_path": result.config_path,
        "external_dirs": result.external_dirs,
        "changed": result.changed,
        "dry_run": result.dry_run,
        "backup_path": result.backup_path,
        "applied": bool(body.apply),
    }


@router.post("/skills/github-sync")
def skills_github_sync_api(body: SkillsGithubSyncBody = Body(default_factory=SkillsGithubSyncBody)) -> dict[str, Any]:
    return skills_sync_status.github_sync_explicit(message=body.message)


class SkillsResolveConflictBody(BaseModel):
    keep_path: str = Field(..., description="Chemin absolu du SKILL.md à conserver")


@router.get("/skills/registry")
def skills_registry_dump_api() -> dict[str, Any]:
    return skills_registry.load_registry_document()


@router.post("/skills/hermes-export")
def skills_hermes_export_api() -> dict[str, Any]:
    return {"yaml": skills_registry.hermes_export_yaml_fragment()}


@router.post("/skills/registry/adopt")
def skills_registry_adopt_api(
    key: str = Query(..., description="Clé org:slug"),
    canonical_path: str | None = Query(None, description="SKILL.md canonique (optionnel)"),
) -> dict[str, Any]:
    return skills_registry.adopt_registry_key(key, canonical_path=canonical_path)


@router.post("/skills/registry/unadopt")
def skills_registry_unadopt_api(key: str = Query(...)) -> dict[str, Any]:
    return skills_registry.unadopt_registry_key(key)


@router.post("/skills/registry/ignore")
def skills_registry_ignore_api(key: str = Query(...)) -> dict[str, Any]:
    return skills_registry.ignore_registry_key(key)


@router.post("/skills/registry/unignore")
def skills_registry_unignore_api(key: str = Query(...)) -> dict[str, Any]:
    return skills_registry.unignore_registry_key(key)


@router.post("/skills/registry/resolve-conflict")
def skills_registry_resolve_conflict_api(
    key: str = Query(...),
    body: SkillsResolveConflictBody = Body(...),
) -> dict[str, Any]:
    return skills_registry.resolve_conflict_keep_path(key, body.keep_path)


@router.get("/skills/by-id/{skill_id}")
def skills_index_detail_api(skill_id: str) -> dict[str, Any]:
    row = state_index.get_section_item("skills", skill_id)
    if not row:
        raise HTTPException(status_code=404, detail="skill inconnue")
    return row


@router.get("/code-tools")
def code_tools_api(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    q: str = "",
    installed: bool | None = Query(None),
) -> dict[str, Any]:
    return state_index.list_section("code_tools", page=page, limit=limit, q=q, installed=installed)


@router.get("/code-tools/{tool_id}")
def code_tools_detail_api(tool_id: str) -> dict[str, Any]:
    row = state_index.get_section_item("code_tools", tool_id)
    if not row:
        raise HTTPException(status_code=404, detail="outil inconnu")
    return row


@router.get("/models")
def models_api(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    q: str = "",
) -> dict[str, Any]:
    return state_index.list_section("models", page=page, limit=limit, q=q)


@router.get("/models/{model_id}")
def models_detail_api(model_id: str) -> dict[str, Any]:
    if model_id == "runtimes":
        return model_runtimes.collect_model_runtimes()
    row = state_index.get_section_item("models", model_id)
    if not row:
        raise HTTPException(status_code=404, detail="modèle inconnu")
    return row


class ContextPackBody(BaseModel):
    org: str | None = None
    project: str | None = None
    query: str | None = None
    include: list[str] | None = None
    limit: int = Field(80, ge=1, le=300)


@router.post("/context-pack")
def context_pack_api(body: ContextPackBody = Body(default_factory=ContextPackBody)) -> dict[str, Any]:
    path, text = state_index.build_context_pack(
        org=body.org,
        project=body.project,
        query=body.query,
        include=body.include,
        limit=body.limit,
    )
    return {"path": str(path), "bytes": len(text.encode("utf-8")), "preview": text[:2000]}


@router.get("/agent/bootstrap")
def agent_bootstrap_api(refresh: bool = Query(False, description="Exécute zab sync avant le bootstrap")) -> dict[str, Any]:
    return agent_context.agent_bootstrap(refresh=refresh)


@router.get("/agent/skills")
def agent_skills_api(
    org: str | None = Query(None),
    project: str | None = Query(None),
    query: str | None = Query(None),
    limit: int = Query(200, ge=1, le=500),
    refresh: bool = Query(False),
) -> dict[str, Any]:
    return agent_context.skills_manifest(org=org, project=project, query=query, limit=limit, refresh=refresh)


class AgentHandoffBody(BaseModel):
    project: str = Field(..., description="Nom ou chemin de projet")
    limit: int = Field(80, ge=1, le=300)


@router.post("/agent/handoff")
def agent_handoff_api(body: AgentHandoffBody) -> dict[str, Any]:
    payload = agent_context.project_handoff(body.project, limit=body.limit)
    if not payload.get("found"):
        raise HTTPException(status_code=404, detail=payload)
    return payload


@router.get("/search")
def search_api(
    q: str = Query("", description="Requête de recherche"),
    limit: int = Query(20, ge=1, le=100),
    section: list[str] | None = Query(None),
    refresh: bool = Query(False),
) -> dict[str, Any]:
    return agent_context.search(q, limit=limit, sections=section, refresh=refresh)


@router.get("/inspect/{section}/{key:path}")
def inspect_item_api(section: str, key: str) -> dict[str, Any]:
    state_section = _resolve_inventory_section_api(section)
    row = state_index.get_section_item(state_section, key)
    if not row:
        raise HTTPException(status_code=404, detail={"section": state_section, "key": key, "found": False})
    return {"section": state_section, "key": key, "found": True, "item": row}


@router.get("/connectors")
def connectors_api(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    q: str = "",
    kind: str | None = Query(None),
    tag: str | None = Query(None),
) -> dict[str, Any]:
    return connectors_aggregate.list_connectors(page=page, limit=limit, q=q, kind=kind, tag=tag)


@router.get("/composio/connections")
def composio_connections_api(
    toolkit: str | None = Query(None),
    active_only: bool = Query(True),
    resolve_identities: bool = Query(False),
) -> dict[str, Any]:
    return agent_context.composio_connections(
        toolkit=toolkit,
        active_only=active_only,
        resolve_identities=resolve_identities,
    )


@router.get("/connectors/{slug}")
def connectors_detail(slug: str) -> dict[str, Any]:
    row = connectors_aggregate.get_connector(slug)
    if not row:
        raise HTTPException(status_code=404, detail="connecteur inconnu")
    return row


@router.get("/connectors/{slug}/check")
def connectors_check_one(slug: str, response: Response) -> dict[str, Any]:
    """Lance les checks pour un connecteur (sync). 404 si slug inconnu."""

    response.headers["Cache-Control"] = "no-store"
    payload = connectors_check.check_connector_payload(slug)
    if payload is None:
        raise HTTPException(status_code=404, detail="connecteur inconnu")
    return payload


@router.get("/connectors/{slug}/check/stream")
def connectors_check_one_stream(slug: str) -> StreamingResponse:
    """SSE par-connecteur : ``registry`` → ``check`` ×N → ``done``."""

    def _stream() -> Any:
        for event in connectors_check.iter_connector_checks(slug):
            yield connectors_check.sse_format(event)

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/connectors-check/stream")
def connectors_check_global_stream() -> StreamingResponse:
    """SSE global : ``registry`` → ``connector`` ×N → ``done``.

    Le chemin est ``connectors-check`` (et non ``connectors/check``) pour ne pas
    rentrer en conflit avec la route ``/connectors/{slug}`` qui matche tout.
    """

    def _stream() -> Any:
        for event in connectors_check.iter_global_checks():
            yield connectors_check.sse_format(event)

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/config/files")
def config_files_snapshot_list() -> list[dict[str, Any]]:
    return config_snapshots.list_config_files()


@router.get("/config/history")
def config_history_snapshot_list() -> list[dict[str, Any]]:
    return config_snapshots.list_config_history()


@router.get("/config/sync-status")
def config_sync_status_api(response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return config_snapshots.config_sync_status()


@router.get("/config/file")
def config_file_snapshot(key: str = Query(..., description="local_tools_actual|user_zab_config|example|*_json…")) -> dict[str, Any]:
    try:
        return config_snapshots.read_config_snapshot(key)
    except ValueError:
        raise HTTPException(status_code=400, detail="clé_de_fichier_inconnue")


class ConfigYamlPutBody(BaseModel):
    content: str


@router.put("/config/file")
def config_file_put(
    key: str = Query(..., description="local_tools_actual|user_zab_config"),
    body: ConfigYamlPutBody = Body(...),
) -> dict[str, Any]:
    try:
        path = config_snapshots.write_config_snapshot(key, body.content)
    except ValueError as e:
        detail = str(e)
        if detail == "clé_non_éditable":
            raise HTTPException(status_code=400, detail="ce fichier est en lecture seule") from e
        raise HTTPException(status_code=400, detail="écriture_impossible") from e
    return {"written": True, "path": str(path)}


class ProjectsRootsPutBody(BaseModel):
    roots: list[str] = Field(
        default_factory=list,
        description="Racines à scanner (ex. ~/projects) — une entrée par dossier parent des projets",
    )


class OpenFolderBody(BaseModel):
    path: str = Field(
        ...,
        description="Chemin absolu du dossier projet (sous projects_roots : 1 ou 2 segments sous la racine)",
    )


@router.get("/workstation/status")
def workstation_status_api() -> dict[str, Any]:
    """État de la workstation GCP Flowmetrik utilisée pour le remote dev."""

    return workstation.get_workstation_status()


@router.post("/workstation/start")
def workstation_start_api() -> dict[str, Any]:
    """Démarre la workstation Compute Engine configurée."""

    result = workstation.start_workstation()
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result)
    return result


@router.post("/workstation/stop")
def workstation_stop_api() -> dict[str, Any]:
    """Arrête la workstation Compute Engine configurée."""

    result = workstation.stop_workstation()
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result)
    return result


@router.get("/workstation/ssh-command")
def workstation_ssh_command_api() -> dict[str, Any]:
    return workstation.ssh_workstation_command()


@router.post("/workstation/sync")
def workstation_sync_api(dry_run: bool = False) -> dict[str, Any]:
    """Synchronise ou prévisualise la copie locale ~/projects vers le bucket."""
    result = workstation.sync_workstation(dry_run=dry_run)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result)
    return result


@router.get("/remote-vm/overview")
def remote_vm_overview_api() -> dict[str, Any]:
    """VM de dev distante : état Compute, connexions SSH et sessions de sync."""

    return remote_vm.overview()


@router.get("/remote-vm/cost")
def remote_vm_cost_api(
    days: int = Query(30, ge=1, le=180, description="Fenêtre d'analyse en jours"),
    refresh: bool = Query(False, description="Ignore le cache disque et relance la requête de facturation"),
) -> dict[str, Any]:
    """Coûts et heures d'exécution depuis l'export BigQuery de facturation."""

    return remote_vm.cost_report(days=days, refresh=refresh)


@router.get("/remote-vm/sync")
def remote_vm_sync_api() -> dict[str, Any]:
    """Détail des sessions de synchronisation (fichiers, écart, conflits)."""

    return remote_vm.sync_state()


@router.get("/remote-vm/ssh")
def remote_vm_ssh_api() -> dict[str, Any]:
    """Connexions SSH locales vers la VM (multiplexage, tunnels, agents de sync)."""

    return remote_vm.ssh_state()


@router.post("/remote-vm/start")
def remote_vm_start_api() -> dict[str, Any]:
    """Démarre la VM distante (via le script de pilotage si configuré)."""

    result = remote_vm.start_vm()
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result)
    return result


@router.post("/remote-vm/stop")
def remote_vm_stop_api() -> dict[str, Any]:
    """Arrête la VM distante après avoir vidé la sync si le script le prévoit."""

    result = remote_vm.stop_vm()
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result)
    return result


@router.post("/remote-vm/sync-action")
def remote_vm_sync_action_api(
    action: str = Query(..., description="sync-flush | sync-resume | sync-pause"),
) -> dict[str, Any]:
    """Actions de synchronisation non destructives sur les sessions locales."""

    result = remote_vm.sync_action(action)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result)
    return result


def _allowed_security_env_paths() -> set[str]:
    return {str(p) for p in security_env_paths_resolved()}


class OpenEditorFileBody(BaseModel):
    path: str = Field(..., description="Chemin absolu du fichier .env")
    line: int | None = Field(None, ge=1, description="Numéro de ligne (1-based)")
    key: str | None = Field(None, description="Clé à localiser si line absent")


@router.post("/system/open-editor-file")
def system_open_editor_file(body: OpenEditorFileBody) -> dict[str, Any]:
    """Ouvre un .env dans Cursor/VS Code à la ligne de la clé (ou via l’app par défaut)."""
    raw = (body.path or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="chemin vide")
    try:
        target = Path(raw).expanduser().resolve()
    except OSError as exc:
        raise HTTPException(status_code=400, detail="chemin invalide") from exc
    if target.name != ".env":
        raise HTTPException(status_code=400, detail="seul un fichier .env est autorisé")
    if str(target) not in _allowed_security_env_paths():
        raise HTTPException(status_code=403, detail="chemin .env hors périmètre sécurité")
    line = body.line
    if body.key and (line is None or line < 1):
        line = dotenv_key_line(target, body.key)
    opened_with = open_in_editor(target, line=line)
    return {
        "opened": True,
        "path": str(target),
        "line": line,
        "key": body.key,
        "opened_with": opened_with,
        "vscode_uri": f"vscode://file{target}" + (f":{line}:1" if line and line > 0 else ""),
    }


@router.post("/system/open-folder")
def system_open_folder(body: OpenFolderBody) -> dict[str, Any]:
    """Ouvre un dossier projet dans le Finder (macOS), l’Explorateur Windows ou xdg-open (Linux)."""
    raw = (body.path or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="chemin vide")
    try:
        p = Path(raw).expanduser().resolve()
    except OSError as exc:
        raise HTTPException(status_code=400, detail="chemin invalide") from exc
    if not p.exists():
        raise HTTPException(status_code=404, detail="dossier introuvable")
    if not project_dir_is_under_projects_roots(p):
        raise HTTPException(status_code=403, detail="chemin hors périmètre projects_roots")
    open_os_path(p)
    return {"opened": True, "path": str(p)}


@router.post("/system/open-git-remote")
def system_open_git_remote(body: OpenFolderBody) -> dict[str, Any]:
    """Ouvre l’URL https déduite de ``remote.origin.url`` dans le navigateur (projet sous ``projects_roots``)."""
    raw = (body.path or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="chemin vide")
    try:
        p = Path(raw).expanduser().resolve()
    except OSError as exc:
        raise HTTPException(status_code=400, detail="chemin invalide") from exc
    if not p.is_dir():
        raise HTTPException(status_code=404, detail="dossier introuvable")
    if not project_dir_is_under_projects_roots(p):
        raise HTTPException(status_code=403, detail="chemin hors périmètre projects_roots")
    ok, err = open_project_origin_browser(p)
    if not ok:
        raise HTTPException(status_code=400, detail=err or "ouverture_impossible")
    return {"opened": True, "path": str(p)}


class ProjectPmCliBody(BaseModel):
    path: str = Field(..., description="Dossier projet absolu sous projects_roots")
    tool: str = Field(..., description="gh ou glab")


@router.post("/system/project-pm-cli")
def system_project_pm_cli(body: ProjectPmCliBody) -> dict[str, Any]:
    """Lance ``gh repo view --web`` ou ``glab repo view --web`` dans le dépôt (navigateur / auth CLI)."""
    raw = (body.path or "").strip()
    tool = (body.tool or "").strip().lower()
    if tool not in ("gh", "glab"):
        raise HTTPException(status_code=400, detail="outil_inconnu")
    if not raw:
        raise HTTPException(status_code=400, detail="chemin vide")
    try:
        p = Path(raw).expanduser().resolve()
    except OSError as exc:
        raise HTTPException(status_code=400, detail="chemin invalide") from exc
    if not p.is_dir():
        raise HTTPException(status_code=404, detail="dossier introuvable")
    if not project_dir_is_under_projects_roots(p):
        raise HTTPException(status_code=403, detail="chemin hors périmètre projects_roots")
    code, out, err = run_pm_repo_tool(p, tool)  # type: ignore[arg-type]
    if code != 0:
        raise HTTPException(
            status_code=502,
            detail={"error": err or "cli_echec", "exit_code": code, "output": out[:4000]},
        )
    return {"ok": True, "path": str(p), "tool": tool, "output": out[:4000]}


@router.put("/config/projects-roots")
def config_projects_roots_put(body: ProjectsRootsPutBody) -> dict[str, Any]:
    """Persiste ``projects_roots`` dans ~/.config/zab/config.yaml puis renvoie les chemins enregistrés."""
    path, saved = merge_projects_roots_into_config(body.roots)
    return {
        "written": True,
        "config_path": str(path.resolve()),
        "projects_roots": saved,
    }


class JobStartBody(BaseModel):
    preset: str = Field(
        ...,
        description="smoke_mcps|gateway_pytest|sync_mcps_litellm|build_plugins|google_oauth_mehdi_context|memory_import|conversation_sync|mempalace_install|mempalace_mine|security_osv_zab|security_npm_audit_zab_ui|security_gitleaks_zab|security_osv_skills|security_pip_audit_zab|security_osv_project|security_npm_audit_project|security_gitleaks_project|flowmetrik_openwebui_compose_up|flowmetrik_openwebui_compose_down (ces deux derniers : args.project_path)",
    )
    args: dict[str, Any] | None = None


@router.post("/jobs/start")
def job_start(body: JobStartBody) -> dict[str, Any]:
    try:
        job = jobs.store.start(body.preset, body.args)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return job.to_summary()


@router.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict[str, Any]:
    job = jobs.store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job introuvable")
    return job.to_summary()


@router.post("/jobs/{job_id}/cancel")
def job_cancel(job_id: str) -> dict[str, bool]:
    ok = jobs.store.cancel(job_id)
    return {"cancelled": ok}


@router.get("/jobs/{job_id}/stream")
def job_stream(job_id: str) -> StreamingResponse:
    job = jobs.store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job introuvable")

    def event_stream() -> Any:
        while True:
            try:
                line = job.lines.get(timeout=1.0)
            except queue.Empty:
                if job.status in ("done", "error", "cancelled"):
                    yield f"data: {json.dumps({'summary': job.to_summary()}, ensure_ascii=False)}\n\n"
                    return
                continue
            if line is None:
                yield f"data: {json.dumps({'summary': job.to_summary()}, ensure_ascii=False)}\n\n"
                return
            yield f"data: {json.dumps({'line': line}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/security/last")
def security_last(key: str | None = Query(None, description="Clé optionnelle du rapport sécurité")) -> dict[str, Any]:
    try:
        return jobs.read_security_report(key)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"rapport sécurité illisible: {exc}") from exc


@router.get("/security/reports")
def security_reports() -> dict[str, Any]:
    return {"reports": jobs.list_security_reports()}


@router.get("/security/status")
def security_status_api() -> dict[str, Any]:
    return agent_context.security_status()


@router.get("/security/locate")
def security_locate_api(
    q: str = Query(..., min_length=1, description="Nom ou intention à chercher, ex. payfit ou qonto api key"),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """Localise des noms de variables sensibles sans exposer les valeurs brutes."""

    return agent_context.security_locate(q, limit=limit)


def _mask_value(val: str) -> str:
    v = val.strip()
    if not v:
        return ""
    if len(v) <= 4:
        return "****"
    return "****" + v[-4:]


def _dotenv_file_values() -> dict[str, str | None]:
    merged: dict[str, str | None] = {}
    for env_path in security_env_paths_resolved():
        if not env_path.is_file():
            continue
        try:
            raw = dotenv_values(env_path)
        except OSError:
            continue
        for k, v in raw.items():
            if not k:
                continue
            key = str(k)
            if key in merged:
                continue
            if v is not None and str(v).strip():
                merged[key] = v
    return merged


def _security_env_path_display(path: Path) -> str:
    home = Path.home()
    try:
        rel = path.relative_to(home)
        return f"~/{rel.as_posix()}"
    except ValueError:
        return str(path)


def _resolve_security_env_path(path: str | None) -> Path:
    allowed = security_env_paths_resolved()
    if not allowed:
        raise HTTPException(
            status_code=503,
            detail="Définissez security_env_paths dans ~/.config/zab/config.yaml (ex. ~/projects/skills/.env, ~/.hermes/.env).",
        )
    if not path or not str(path).strip():
        return allowed[0]
    try:
        target = Path(str(path).strip()).expanduser().resolve()
    except OSError as exc:
        raise HTTPException(status_code=400, detail="chemin .env invalide") from exc
    if target.name != ".env":
        raise HTTPException(status_code=400, detail="seul un fichier nommé .env est autorisé")
    allowed_set = {str(p) for p in allowed}
    if str(target) not in allowed_set:
        raise HTTPException(
            status_code=400,
            detail="chemin .env hors liste security_env_paths",
        )
    return target


def _security_env_overview_payload() -> dict[str, Any]:
    configured = security_env_paths_resolved()
    configured_paths = {str(p) for p in configured}
    scan = scan_secret_presence(env_files=configured)
    file_index: dict[str, dict[str, Any]] = {}

    def _ensure_file(path_str: str) -> dict[str, Any]:
        if path_str not in file_index:
            p = Path(path_str)
            file_index[path_str] = {
                "path": path_str,
                "path_display": _security_env_path_display(p),
                "exists": p.is_file(),
                "configured": path_str in configured_paths,
                "keys": [],
            }
        return file_index[path_str]

    for path_str in configured_paths:
        _ensure_file(path_str)

    variables: list[dict[str, Any]] = []
    raw_values_by_name: dict[str, str] = {}
    for row in scan.get("variables") or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "")
        sources: list[dict[str, Any]] = []
        in_process_as = row.get("in_process_as") if isinstance(row.get("in_process_as"), list) else []
        if row.get("in_process"):
            sources.append({"kind": "process", "keys": [str(k) for k in in_process_as if k]})
        for src in row.get("in_files") or []:
            if not isinstance(src, dict):
                continue
            path_str = str(src.get("path") or "")
            key = str(src.get("key") or name)
            if not path_str:
                continue
            p = Path(path_str)
            line = dotenv_key_line(p, key) if p.is_file() else None
            entry = _ensure_file(path_str)
            if key and key not in entry["keys"]:
                entry["keys"].append(key)
            sources.append(
                {
                    "kind": "file",
                    "path": path_str,
                    "path_display": _security_env_path_display(p),
                    "key": key,
                    "line": line,
                }
            )
        variable = {
            "name": name,
            "present": bool(row.get("present")),
            "in_process": bool(row.get("in_process")),
            "in_file": any(s.get("kind") == "file" for s in sources),
            "masked": "",
            "sources": sources,
        }
        raw_for_mask = _raw_security_value_for_row(variable) or ""
        raw_values_by_name[name] = raw_for_mask
        variable["masked"] = _mask_value(raw_for_mask) if raw_for_mask else ""
        variables.append(variable)

    files = sorted(
        file_index.values(),
        key=lambda f: (not f.get("configured"), not f.get("exists"), str(f.get("path_display") or "")),
    )
    secret_sync = security_secret_sync.attach_secret_sync(variables, raw_values_by_name)
    return {
        "configured_paths": sorted(configured_paths),
        "files": files,
        "variables": variables,
        "env_files_scanned": scan.get("env_files_scanned") or [],
        "secret_sync": secret_sync,
    }


@router.get("/security/env")
def security_env() -> dict[str, Any]:
    overview = _security_env_overview_payload()
    rows: list[dict[str, Any]] = []
    for row in overview["variables"]:
        rows.append(
            {
                "name": row["name"],
                "present": row["present"],
                "in_process": row["in_process"],
                "in_file": row["in_file"],
                "masked": row.get("masked") or "",
                "sources": row.get("sources") or [],
            }
        )
    return {"variables": rows}


@router.get("/security/env-overview")
def security_env_overview() -> dict[str, Any]:
    """Liste des .env, clés présentes et provenance par variable (sans valeurs brutes)."""
    return _security_env_overview_payload()


@router.get("/security/secret-providers")
def security_secret_providers() -> dict[str, Any]:
    """Providers de gestion de secrets proposés dans l'écran Sécurité."""
    return {"providers": security_secret_sync.secret_providers()}


class SecretSyncCheckBody(BaseModel):
    provider: str = "dashlane"
    apply: bool = False


@router.post("/security/secret-sync/check")
def security_secret_sync_check(body: SecretSyncCheckBody) -> dict[str, Any]:
    """Prépare le check de synchronisation Dashlane sans exposer les valeurs brutes."""
    provider = body.provider.strip().lower()
    if provider not in ("dashlane", ""):
        raise HTTPException(status_code=400, detail="seul le provider dashlane est disponible pour l'instant")
    overview = _security_env_overview_payload()
    sync_payload = overview.get("secret_sync")
    if not isinstance(sync_payload, dict):
        raise HTTPException(status_code=500, detail="sync secrets indisponible")
    return security_secret_sync.dashlane_sync_check(sync_payload, apply=body.apply)


class DashlaneSecretSyncApplyBody(BaseModel):
    provider: str = "dashlane"
    name: str = Field(..., min_length=1)
    reference: str | None = Field(None, description="Reference dl:// deja creee dans Dashlane")
    selected_count: int = Field(1, ge=1)
    total_selectable: int | None = Field(None, ge=1)
    confirm_all: bool = False


def _secret_sync_row_by_name(sync_payload: dict[str, Any], name: str) -> dict[str, Any] | None:
    for row in sync_payload.get("variables") or []:
        if isinstance(row, dict) and str(row.get("name") or "") == name:
            return row
    return None


@router.post("/security/secret-sync/dashlane/apply")
def security_secret_sync_dashlane_apply(body: DashlaneSecretSyncApplyBody) -> dict[str, Any]:
    """Applique une reference Dashlane a une variable .env sans exposer la valeur brute."""
    provider = body.provider.strip().lower()
    if provider not in ("dashlane", ""):
        raise HTTPException(status_code=400, detail="seul le provider dashlane est disponible pour l'instant")
    overview = _security_env_overview_payload()
    sync_payload = overview.get("secret_sync")
    if not isinstance(sync_payload, dict):
        raise HTTPException(status_code=500, detail="sync secrets indisponible")
    pending = [row for row in sync_payload.get("variables") or [] if isinstance(row, dict) and row.get("status") == "pending"]
    total_for_guard = body.total_selectable or len(pending)
    if total_for_guard > 0 and body.selected_count >= total_for_guard and not body.confirm_all:
        raise HTTPException(status_code=409, detail="selection_totale_a_confirmer")
    sync_row = _secret_sync_row_by_name(sync_payload, body.name)
    if not sync_row:
        raise HTTPException(status_code=404, detail="variable_introuvable")
    reference = str(sync_row.get("dashlane_reference_value") or body.reference or "")
    created_secret: dict[str, Any] | None = None
    if sync_row.get("status") == "pending" and sync_row.get("dashlane_match_status") != "matched":
        variable_row = next(
            (row for row in overview.get("variables") or [] if isinstance(row, dict) and row.get("name") == body.name),
            None,
        )
        if not variable_row:
            raise HTTPException(status_code=404, detail="variable_introuvable")
        raw_value = _raw_security_value_for_row(variable_row)
        if not raw_value:
            return {
                "provider": "dashlane",
                "result": {
                    "name": body.name,
                    "status": "error",
                    "reason": "valeur_locale_introuvable",
                    "dashlane_title": sync_row.get("dashlane_title"),
                    "dashlane_reference_value": sync_row.get("dashlane_reference_value"),
                },
                "secret_sync": sync_payload,
            }
        created_secret = security_secret_sync.create_dashlane_secret(variable_row, value=raw_value)
        if not created_secret.get("ok"):
            return {
                "provider": "dashlane",
                "result": {
                    "name": body.name,
                    "status": "error",
                    "reason": created_secret.get("reason") or "dashlane_secret_create_failed",
                    "dashlane_title": created_secret.get("dashlane_title") or sync_row.get("dashlane_title"),
                    "dashlane_reference_value": created_secret.get("dashlane_reference_value")
                    or sync_row.get("dashlane_reference_value"),
                    "dashlane_web_url": created_secret.get("dashlane_web_url") or sync_row.get("dashlane_web_url"),
                    "hint": created_secret.get("hint"),
                },
                "secret_sync": sync_payload,
            }
        reference = str(created_secret.get("dashlane_reference_value") or reference)
    result = security_secret_sync.apply_dashlane_reference(
        overview.get("variables") or [],
        name=body.name,
        reference=reference,
        allowed_paths=_allowed_security_env_paths(),
    )
    if created_secret and result.get("status") == "synced":
        result["dashlane_secret_status"] = created_secret.get("status")
        result["dashlane_title"] = created_secret.get("dashlane_title")
        result["dashlane_reference_value"] = created_secret.get("dashlane_reference_value")
        result["dashlane_web_url"] = created_secret.get("dashlane_web_url")
    refreshed = _security_env_overview_payload()
    return {
        "provider": "dashlane",
        "result": result,
        "secret_sync": refreshed.get("secret_sync"),
    }


def _raw_security_value_for_row(row: dict[str, Any]) -> str | None:
    """Find a local secret value from row sources without exposing it."""
    for source in row.get("sources") or []:
        if not isinstance(source, dict) or source.get("kind") != "file":
            continue
        raw_path = str(source.get("path") or "").strip()
        key = str(source.get("key") or row.get("name") or "").strip()
        if not raw_path or not key:
            continue
        try:
            path = Path(raw_path).expanduser().resolve()
        except OSError:
            continue
        if str(path) not in _allowed_security_env_paths():
            continue
        try:
            value = dotenv_values(path).get(key)
        except OSError:
            value = None
        if value is not None and str(value).strip():
            return str(value)
    for source in row.get("sources") or []:
        if not isinstance(source, dict) or source.get("kind") != "process":
            continue
        for key in source.get("keys") or []:
            value = os.environ.get(str(key))
            if value:
                return value
    return None


class DashlaneSecretCopyValueBody(BaseModel):
    name: str = Field(..., min_length=1)
    confirm_clipboard: bool = False


@router.post("/security/secret-sync/dashlane/copy-value")
def security_secret_sync_dashlane_copy_value(body: DashlaneSecretCopyValueBody) -> dict[str, Any]:
    """Copie explicitement une valeur locale dans le presse-papiers sans la renvoyer."""
    if not body.confirm_clipboard:
        raise HTTPException(status_code=400, detail="confirmation_clipboard_requise")
    overview = _security_env_overview_payload()
    sync_payload = overview.get("secret_sync")
    if not isinstance(sync_payload, dict):
        raise HTTPException(status_code=500, detail="sync secrets indisponible")
    sync_row = _secret_sync_row_by_name(sync_payload, body.name)
    row = next((v for v in overview.get("variables") or [] if isinstance(v, dict) and v.get("name") == body.name), None)
    if not sync_row or not row:
        raise HTTPException(status_code=404, detail="variable_introuvable")
    value = _raw_security_value_for_row(row)
    if not value:
        raise HTTPException(status_code=404, detail="valeur_locale_introuvable")
    ok, reason = security_secret_sync.copy_to_clipboard(value)
    if not ok:
        raise HTTPException(status_code=503, detail=reason or "clipboard_indisponible")
    return {
        "copied": True,
        "name": body.name,
        "dashlane_title": sync_row.get("dashlane_title"),
    }


@router.get("/security/env-files")
def security_env_files() -> dict[str, Any]:
    """Liste les fichiers .env configurés (security_env_paths) pour l’éditeur Sécurité."""
    files: list[dict[str, Any]] = []
    for path in security_env_paths_resolved():
        files.append(
            {
                "path": str(path),
                "path_display": _security_env_path_display(path),
                "exists": path.is_file(),
            }
        )
    return {"files": files}


@router.get("/security/env-file")
def security_env_file(path: str | None = Query(None, description="Chemin absolu du .env (défaut : premier security_env_paths)")) -> dict[str, Any]:
    """Contenu brut d’un .env autorisé — réservé au dashboard local (secret en clair)."""
    target = _resolve_security_env_path(path)
    exists = target.is_file()
    content = target.read_text(encoding="utf-8") if exists else ""
    return {
        "path": str(target),
        "path_display": _security_env_path_display(target),
        "exists": exists,
        "content": content,
    }


class EnvFilePutBody(BaseModel):
    content: str


@router.put("/security/env-file")
def security_env_file_put(
    body: EnvFilePutBody,
    path: str | None = Query(None, description="Chemin absolu du .env à écrire"),
) -> dict[str, Any]:
    """Écrit un .env autorisé (sauvegarde horodatée si le fichier existait déjà)."""
    target = _resolve_security_env_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup: str | None = None
    if target.is_file():
        backup_path = target.with_name(f".env.zab-backup-{ts}")
        shutil.copy2(target, backup_path)
        backup = str(backup_path)
    target.write_text(body.content, encoding="utf-8")
    rel_backup: str | None = _security_env_path_display(Path(backup)) if backup else None
    return {
        "path": str(target),
        "written": True,
        "backup": rel_backup,
    }


@router.get("/skills/file")
def skill_get(
    path: str = Query(..., description="Chemin relatif sous le dépôt (orgs/… ou claude-plugins/…) ou absolu autorisé par le registre / sous projects_roots"),
) -> dict[str, str]:
    _require_skills_anchor_or_project_path(path)
    try:
        content = skills_fs.read_skill(path)
    except skills_fs.SkillPathError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"path": path, "content": content}


class SkillPutBody(BaseModel):
    content: str


@router.put("/skills/file")
def skill_put(body: SkillPutBody, path: str = Query(...)) -> dict[str, str]:
    _require_skills_anchor_or_project_path(path)
    try:
        return skills_fs.write_skill(path, body.content)
    except skills_fs.SkillPathError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/scan")
def scan_workspace(
    root: str | None = Query(None, description="Sous-chemin sous ~ (HOME) ou chemin absolu situé sous le home"),
    persist: bool = Query(False, description="Persiste dans ~/.local/share/zab/scan-last.yaml ; pose last_scan_at_utc et models_discovery dans ~/.config/zab/config.yaml"),
) -> dict[str, Any]:
    """Scan SKILL.md sous ~ ; CLIs ; Agentpipe/Codexbar ; Cursor/Cody (best-effort)."""
    rp = scanner.resolve_optional_scan_root(root)
    payload = scanner.workspace_scan(rp)
    if persist:
        scan_persist.persist_workspace_scan(payload)
        cfg = dict(load_user_config())
        cfg.pop("_error", None)
        cfg["last_scan_at_utc"] = datetime.now(timezone.utc).isoformat()
        save_user_config(cfg)
        merge_models_discovery_from_workspace_scan(payload)
    return payload


@router.get("/config/models-discovery")
def models_discovery_read() -> dict[str, Any]:
    """Lecture ``models_discovery`` et overrides chemins agentpipe/codexbar depuis ~/.config/zab/config.yaml."""
    cfg = load_user_config()
    return {
        "user_config_path": str(user_config_path()),
        "models_discovery": cfg.get("models_discovery"),
        "agentpipe_config_path_override": cfg.get("agentpipe_config_path"),
        "codexbar_config_path_override": cfg.get("codexbar_config_path"),
    }


@router.get("/agents/discovery")
def agents_discovery_combined() -> dict[str, Any]:
    """Fusion agentpipe (~/.agentpipe.yaml) + providers CodexBar activés pour le dashboard."""
    return build_agents_discovery()


@router.get("/agents")
def agents_codexbar_list() -> dict[str, Any]:
    """Providers CodexBar activés + résolution CLI (``which`` ou surcharges ``agent_cli_paths`` / ``agents``)."""
    return agents_registry.list_codexbar_agents()


@router.get("/codexbar/usage")
def codexbar_usage_api(provider: str = Query(..., description="Identifiant provider codexbar (ex. claude, codex)")) -> dict[str, Any]:
    """Appelle ``codexbar usage --format json`` pour un seul provider (évite les timeouts ``--provider all``)."""
    return agents_registry.codexbar_usage_json(provider)


@router.get("/scan/last")
def scan_last() -> dict[str, Any]:
    """Dernier scan persisté (si présent)."""
    prev = scan_persist.load_last_scan()
    if prev is None:
        return {"present": False}
    return {"present": True, **prev}


@router.get("/tools/catalog")
def tools_catalog_api() -> dict[str, Any]:
    return tool_catalog.build_tools_catalog()


@router.get("/tools")
def tools_list_api(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    q: str = "",
    kind: str | None = Query(None),
    status: str | None = Query(None),
    provider: str | None = Query(None),
) -> dict[str, Any]:
    return tool_catalog.list_tools(page=page, limit=limit, q=q, kind=kind, status=status, provider=provider)


@router.get("/tools/search")
def tools_search_api(
    q: str = Query(..., description="Requête de recherche"),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    return tool_catalog.search_tools(q, limit=limit)


@router.get("/tools/validate")
def tools_validate_api(strict: bool = Query(False)) -> dict[str, Any]:
    return tool_catalog.validate_tools(strict=strict)


@router.get("/tools/check")
def tools_check_api(
    tool_id: str | None = Query(None),
    all: bool = Query(False),
    refresh: bool = Query(False, description="Recheck unitaire en direct (relance les probes de connexion)"),
) -> dict[str, Any]:
    if all and tool_id:
        raise HTTPException(status_code=400, detail="all et tool_id sont incompatibles")
    if not all and not tool_id:
        raise HTTPException(status_code=400, detail="tool_id ou all requis")
    payload = tool_checks.check_tools() if all else tool_checks.check_tool(str(tool_id or ""), refresh=refresh)
    if not payload:
        raise HTTPException(status_code=404, detail="tool inconnu")
    return payload


class ToolAnnotationPatch(BaseModel):
    label: str | None = None
    kind: str | None = None
    coverage: str | None = None
    safety: str | None = None
    notes: str | None = None
    keywords: list[str] | None = None
    examples: list[str] | None = None
    skill_refs: list[str] | None = None
    commands: list[str] | None = None


@router.get("/tools/{tool_id}/editable")
def tools_editable_fields_api(tool_id: str) -> dict[str, Any]:
    fields = tool_catalog.editable_tool_fields(tool_id)
    if fields is None:
        raise HTTPException(status_code=404, detail="tool inconnu")
    return {"tool_id": tool_id, "annotations_path": str(tool_catalog.tools_catalog_config_path()), "fields": fields}


@router.patch("/tools/{tool_id}")
def tools_update_api(
    tool_id: str,
    patch: ToolAnnotationPatch = Body(...),
) -> dict[str, Any]:
    updated = tool_catalog.update_tool_annotations(tool_id, patch.model_dump(exclude_none=True))
    if updated is None:
        raise HTTPException(status_code=404, detail="tool inconnu")
    return {
        "tool_id": tool_id,
        "annotations_path": str(tool_catalog.tools_catalog_config_path()),
        "tool": updated,
    }


@router.get("/tools/local")
def tools_local() -> dict[str, Any]:
    return tools_probe.local_tools_public()


@router.get("/tools/scan")
def scan_tools_route() -> dict[str, Any]:
    return tools_scan.scan_tools()


@router.get("/cli/help")
def cli_help() -> dict[str, str]:
    """Texte de `zab --help` pour affichage dans le dashboard."""
    runner = CliRunner()
    result = runner.invoke(zab_cli_app, ["--help"])
    try:
        stderr = result.stderr or ""
    except ValueError:
        stderr = ""
    text = (result.stdout or "") + stderr
    if result.exit_code != 0 and not text.strip():
        raise HTTPException(status_code=500, detail="Échec zab --help")
    return {"text": text.strip() or "(vide)"}


@router.get("/tools/probe")
def tools_probe_route(kind: str = Query(...)) -> dict[str, Any]:
    if kind not in ("litellm", "openrouter"):
        raise HTTPException(status_code=400, detail="kind doit être litellm ou openrouter")
    return tools_probe.probe_models(kind)


@router.get("/tools/{tool_id}")
def tools_detail_api(tool_id: str) -> dict[str, Any]:
    payload = tool_catalog.get_tool(tool_id)
    if not payload:
        raise HTTPException(status_code=404, detail="tool inconnu")
    return payload


@router.get("/exports/hints")
def exports_hints() -> dict[str, Any]:
    root = _dashboard_skills_root()
    if root is None:
        return {
            "sync_mcps_litellm": "",
            "build_plugins": "",
            "plugin_config": discovery.load_plugin_config_summary(),
        }
    return {
        "sync_mcps_litellm": str(root / "scripts" / "sync-mcps-to-litellm.sh"),
        "build_plugins": str(root / "build-plugins.sh"),
        "plugin_config": discovery.load_plugin_config_summary(),
    }


@router.get("/model-runtimes")
def model_runtimes_route() -> dict[str, Any]:
    """Runtimes modèles (proxy Vertex zab, agentpipe, codexbar, synthèse coding_models_flat).

    (Pas sous ``/api/models/…`` pour éviter le conflit avec ``/api/models/{model_id}``.)
    """
    return model_runtimes.collect_model_runtimes()


@router.get("/vertex-openai/status")
def vertex_openai_status() -> dict[str, Any]:
    """Prérequis proxy Vertex (SA, projet) — sans jeton dans la réponse."""
    return vertex_openai_proxy.public_status()


@router.get("/vertex-openai/v1/models/{model_id:path}")
def vertex_openai_model_by_id(model_id: str) -> dict[str, Any]:
    """GET /v1/models/{id} — Hermes probe chaque modèle au démarrage."""
    return {
        "id": model_id,
        "object": "model",
        "created": 0,
        "owned_by": "vertex",
    }


@router.get("/vertex-openai/v1/models")
def vertex_openai_models_list() -> dict[str, Any]:
    """Liste minimale compatible OpenAI pour clients qui appellent GET /v1/models."""
    return vertex_openai_proxy.openai_models_list_payload()


@router.post("/vertex-openai/v1/chat/completions")
async def vertex_openai_chat_completions(request: Request) -> Response:
    """
    Proxy OpenAI → Vertex : Authorization avec jeton SA rafraîchi ici (process zab / uvicorn).
    """
    body = await request.body()
    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail="Corps JSON invalide") from e
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Le corps doit être un objet JSON")

    stream = bool(payload.get("stream"))
    try:
        url = vertex_openai_proxy.upstream_chat_completions_url()
        token = vertex_openai_proxy.refresh_access_token()
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    timeout = httpx.Timeout(300.0, connect=30.0)

    if stream:
        client = httpx.AsyncClient(timeout=timeout)
        req = client.build_request("POST", url, headers=headers, content=body)
        upstream = await client.send(req, stream=True)
        ct = upstream.headers.get("content-type", "text/event-stream")

        async def passthrough() -> Any:
            try:
                async for chunk in upstream.aiter_bytes():
                    yield chunk
            finally:
                await upstream.aclose()
                await client.aclose()

        return StreamingResponse(passthrough(), status_code=upstream.status_code, media_type=ct)

    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, headers=headers, content=body)
    return Response(
        content=r.content,
        status_code=r.status_code,
        media_type=r.headers.get("content-type", "application/json"),
    )


@router.get("/crons")
def get_crons_api() -> dict[str, Any]:
    """Récupère la liste des crons (Hermes, launchd, GCP, etc.) depuis le cache local."""
    return {"crons": crons.load_cached_crons()}


@router.post("/crons/sync")
def sync_crons_api() -> dict[str, Any]:
    """Force un scan actif des crons (Hermes + launchd + GCP) et renvoie la liste à jour."""
    list_crons = crons.scan_and_save_crons()
    return {"crons": list_crons}


@router.get("/crons/{cron_id}/logs")
def get_cron_logs_api(cron_id: str) -> dict[str, Any]:
    """Récupère l'historique d'exécution (les logs de run) pour un cron donné."""
    log_runs = crons.get_cron_logs(cron_id)
    return {"logs": log_runs}


@router.post("/crons/{cron_id}/run")
def trigger_cron_api(cron_id: str) -> dict[str, Any]:
    """Déclenche immédiatement l'exécution d'un cron."""
    res = crons.run_cron_now(cron_id)
    return res
