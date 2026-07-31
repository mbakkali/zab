"""Point d'entrée Typer pour la commande `zab`."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
import subprocess
import webbrowser
from typing import Any, Optional

import typer
import uvicorn
import yaml

from zab.system_open import open_os_path
from zab.paths import (
    config_dir,
    configs_dir,
    data_dir,
    mehdi_context_root,
    resolve_skills_root,
    scripts_dir,
    skills_root,
    skills_root_from_config_file_only,
    dashboard_local_tools_config_path,
    zab_package_dir,
    zab_repo_root,
    zab_ui_dist_dir,
)
from zab.user_config import (
    load_user_config,
    skills_sync_settings,
    user_config_path,
)
from zab.services.scan_persist import persist_workspace_scan
from zab.services import skills_registry
from zab.services.cli_add import (
    McpTarget,
    add_api_proxy,
    add_cli_watchlist,
    add_mcp_server,
    add_tracked_env,
    parse_args_option,
    parse_env_flags,
    resolve_mcp_json_path,
)
from zab.services.memory_scan import resolve_mehdi_memory_database_url
from zab.services import mempalace_mcp_snippet as mempalace_mcp_snippet
from zab.services.scanner import resolve_optional_scan_root, workspace_scan
from zab.services.pm_env_sync import sync_pm_tokens_to_user_dotenv
from zab.services.capabilities import get_capabilities
from zab.services.command_center_context import build_context_packet, write_context_packet
from zab.services.feature_catalog import agent_guide, agent_guide_markdown, catalog
from zab.services.state_index import build_context_pack, get_section_item, list_section, state_summary, sync_state
from zab.services.workpacket_intake import get_global_rule as get_workpacket_intake_rule
from zab.services.workpacket_intake import intake_from_params as workpacket_intake_from_params
from zab.services import agent_context, cli_check as cli_check_svc, cli_update_status as cli_update_svc, composio_connectors as composio_svc
from zab.services import request_logs
from zab.services import tool_catalog, tool_checks
from zab.services.hermes_config import update_external_dirs
from zab.services.skill_ai_router import choose_skill_placement
from zab.services.skills_git_sync import commit_and_push, ensure_remote_origin, ensure_repo_initialized
from zab.services.skills_scaffold import SkillScaffoldError, create_global_skill, create_project_skill, create_skill
from zab.services import skills_broadcast

app = typer.Typer(no_args_is_help=True, help="CLI zab — dashboard, scan workspace et jobs du dépôt skills.")
add_app = typer.Typer(help="Ajouter MCP (skills/configs), CLI watchlist, proxy API ou variable suivie (Sécurité).")
app.add_typer(add_app, name="add")
pm_env_app = typer.Typer(help="Jetons gestion de projet (GitLab / Linear / Notion) depuis les .env locaux.")
app.add_typer(pm_env_app, name="pm-env")
projects_app = typer.Typer(help="Projets locaux sous projects_roots (skills + métadonnées Git).")
app.add_typer(projects_app, name="projects")
mempalace_app = typer.Typer(help="MemPalace : diagnostic MCP (mempalace-mcp) et configs skills/*.json.")
app.add_typer(mempalace_app, name="mempalace")
memory_app = typer.Typer(help="Mémoire Postgres : sync conversations/artefacts agents et lecture.")
app.add_typer(memory_app, name="memory")
conversations_app = typer.Typer(help="Conversations multi-provider : sync vers Postgres / MemPalace.")
app.add_typer(conversations_app, name="conversations")
agent_app = typer.Typer(help="Contrat agent : bootstrap, recherche et handoff projet.")
app.add_typer(agent_app, name="agent")
security_app = typer.Typer(help="Statut sécurité local sans secrets bruts.")
app.add_typer(security_app, name="security")
mcp_app = typer.Typer(help="Serveur MCP stdio read-only pour exposer zab aux agents.")
app.add_typer(mcp_app, name="mcp")
composio_app = typer.Typer(
    help="Composio : lister les connections et exécuter des tools via la CLI / API Composio.",
    no_args_is_help=True,
)
app.add_typer(composio_app, name="composio")
skill_app = typer.Typer(help="Créer, synchroniser et exposer des Agent Skills.", no_args_is_help=True)
app.add_typer(skill_app, name="skill")
tools_app = typer.Typer(help="Catalogue des tools actionnables Zab.", no_args_is_help=True)
app.add_typer(tools_app, name="tools")
logs_app = typer.Typer(help="Logs structurés Zab (CLI/API/MCP/jobs).", no_args_is_help=True)
app.add_typer(logs_app, name="logs")
db_app = typer.Typer(help="Base Postgres canonique Zab.", no_args_is_help=True)
app.add_typer(db_app, name="db")
ws_app = typer.Typer(help="Cloud Workstation : sync bidirectionnelle env/CLIs.", no_args_is_help=True)
ws_sync_app = typer.Typer(help="Sync Mac ↔ GCS ↔ Workstation par profils.", no_args_is_help=True)
ws_app.add_typer(ws_sync_app, name="sync")
app.add_typer(ws_app, name="ws")

vm_app = typer.Typer(help="VM de dev distante : coût, heures, SSH et sync.", no_args_is_help=True)
app.add_typer(vm_app, name="vm")

tasks_app = typer.Typer(help="Gestion des tâches unifiée (GitLab, Linear, Notion, GitHub).", no_args_is_help=True)
app.add_typer(tasks_app, name="tasks")

brain_app = typer.Typer(help="Zab-as-GBrain status et schema.", no_args_is_help=True)
app.add_typer(brain_app, name="brain")

command_center_app = typer.Typer(help="Packets Command Center pour Hermes.", no_args_is_help=True)
app.add_typer(command_center_app, name="command-center")

workpacket_app = typer.Typer(help="Contrats Work Packet : règle globale et intake de signaux.", no_args_is_help=True)
app.add_typer(workpacket_app, name="workpacket")

interactions_app = typer.Typer(help="Conversation Ledger : channels, sync et timeline.", no_args_is_help=True)
app.add_typer(interactions_app, name="interactions")

ledger_app = typer.Typer(help="Conversation Ledger : eval et preflight.", no_args_is_help=True)
app.add_typer(ledger_app, name="ledger")


@workpacket_app.command("rule")
def workpacket_rule_cmd(
    *,
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Expose la règle globale d'intake Work Packet."""
    payload = get_workpacket_intake_rule()
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(typer.style(payload["name"], fg=typer.colors.GREEN, bold=True))
    typer.echo(payload["summary"])
    typer.echo("  states : " + " -> ".join(payload["state_machine"]))
    typer.echo("  json   : zab workpacket rule --json")


@workpacket_app.command("intake")
def workpacket_intake_cmd(
    signal: str = typer.Argument(..., help="Signal, message ou instruction à classifier"),
    *,
    source: str = typer.Option("manual", "--source", help="Source du signal : codex, claude, channel, cron, manual..."),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Projet ou chemin associé"),
    requested_by: Optional[str] = typer.Option(None, "--requested-by", help="Humain ou agent demandeur"),
    markdown: bool = typer.Option(False, "--markdown", help="Affiche le packet Markdown compact"),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Transforme un signal entrant en contrat Work Packet déterministe."""
    payload = workpacket_intake_from_params(signal, source=source, project=project, requested_by=requested_by)
    if markdown:
        typer.echo(str(payload.get("markdown") or "").rstrip())
        return
    if json_out:
        typer.echo(json.dumps({k: v for k, v in payload.items() if k != "markdown"}, ensure_ascii=False, indent=2))
        return
    packet = payload.get("workpacket") or {}
    typer.echo(typer.style("Work Packet intake", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"  event     : {payload.get('event_type', {}).get('type')} / {payload.get('event_type', {}).get('action')}")
    typer.echo(f"  intent    : {packet.get('intent', {}).get('kind')}")
    typer.echo(f"  authority : {packet.get('authority', {}).get('level')}")
    typer.echo(f"  key       : {packet.get('idempotency_key')}")
    typer.echo("  json      : zab workpacket intake <signal> --json")


@workpacket_app.command("list")
def workpacket_list_cmd(
    *,
    state: str = typer.Option("", "--state", help="Filtrer par états CSV: active,candidate"),
    organization: Optional[str] = typer.Option(None, "--organization", help="Filtrer par organization_id ou label"),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON"),
) -> None:
    from zab.services import local_db
    from zab.services.conversation_ledger.store import list_workpackets

    states = [s.strip() for s in state.split(",") if s.strip()] or None
    with local_db.transaction() as conn:
        items = list_workpackets(conn, states=states, limit=200)
    if organization:
        needle = organization.lower()
        items = [
            p
            for p in items
            if needle in str(p.get("organization_id", "")).lower()
            or needle in str(p.get("organization_label", "")).lower()
        ]
    payload = {"contract": "workpacket-list", "count": len(items), "items": items}
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    for item in items:
        typer.echo(f"{item.get('display_id')}  {item.get('state')}  {item.get('title')}")


@workpacket_app.command("show")
def workpacket_show_cmd(
    wp_id: str = typer.Argument(..., help="workpacket_id ou display_id"),
    *,
    fmt: str = typer.Option("md", "--format", help="md|json"),
    json_out: bool = typer.Option(False, "--json", help="Alias --format json"),
) -> None:
    from zab.services import local_db
    from zab.services.conversation_ledger.store import get_workpacket, list_workpackets
    from zab.services.conversation_ledger.workpacket_builder import format_workpacket_markdown

    with local_db.transaction() as conn:
        packet = get_workpacket(conn, wp_id)
        if not packet:
            for candidate in list_workpackets(conn, limit=500):
                if candidate.get("display_id") == wp_id:
                    packet = candidate
                    break
    if not packet:
        typer.echo(f"WorkPacket introuvable: {wp_id}", err=True)
        raise typer.Exit(1)
    if json_out or fmt == "json":
        typer.echo(json.dumps(packet, ensure_ascii=False, indent=2))
        return
    typer.echo(format_workpacket_markdown(packet))


@workpacket_app.command("discover")
def workpacket_discover_cmd(
    *,
    since: str = typer.Option("90d", "--since"),
    min_confidence: float = typer.Option(0.65, "--min-confidence"),
    limit: int = typer.Option(7, "--limit", min=1, max=100),
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    from zab.services.conversation_ledger.workpacket_builder import discover_workpackets

    payload = discover_workpackets(
        since=since,
        min_confidence=min_confidence,
        limit=limit,
        dry_run=dry_run,
    )
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(f"Candidates: {payload.get('candidate_count')}")


@workpacket_app.command("reconstruct")
def workpacket_reconstruct_cmd(
    *,
    dry_run: bool = typer.Option(True, "--dry-run/--apply"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    from zab.services.conversation_ledger.workpacket_builder import reconstruct_seed_candidates

    payload = reconstruct_seed_candidates(dry_run=dry_run)
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(f"Reconstructed: {payload.get('count')}")


@workpacket_app.command("project-linear")
def workpacket_project_linear_cmd(
    wp_id: str = typer.Argument(..., help="workpacket_id"),
    *,
    dry_run: bool = typer.Option(True, "--dry-run/--apply"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    from zab.services.conversation_ledger.projections.linear import project_linear

    payload = project_linear(wp_id, dry_run=dry_run)
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(payload.get("description_markdown") or "")


@workpacket_app.command("daily-digest")
def workpacket_daily_digest_cmd(
    *,
    since: str = typer.Option("yesterday", "--since"),
    fmt: str = typer.Option("md", "--format"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    from zab.services.conversation_ledger.digest import digest_payload

    payload = digest_payload(since=since)
    if json_out or fmt == "json":
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(payload.get("markdown") or "")


@interactions_app.command("channels")
def interactions_channels_cmd(
    *,
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    from zab.services.conversation_ledger.channel_bindings import list_channels

    payload = list_channels(check=True)
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    for channel in payload.get("channels") or []:
        typer.echo(f"{channel.get('channel_id')}  {channel.get('last_check_status')}  {channel.get('tool_id')}")


@interactions_app.command("sync")
def interactions_sync_cmd(
    *,
    since: str = typer.Option("90d", "--since"),
    until: str = typer.Option("", "--until", help="Exclusive end date for bounded backfills"),
    sources: str = typer.Option("", "--sources", help="CSV gmail,calendar,fireflies,whatsapp,ios_messages"),
    channels: str = typer.Option("", "--channels", help="CSV channel_ids"),
    max_per_channel: int = typer.Option(500, "--max-per-channel", min=1),
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    from zab.services.conversation_ledger.sync import sync_channels

    source_list = [s.strip() for s in sources.split(",") if s.strip()] or None
    channel_list = [s.strip() for s in channels.split(",") if s.strip()] or None
    payload = sync_channels(
        since=since,
        until=until or None,
        sources=source_list,
        channel_ids=channel_list,
        dry_run=dry_run,
        max_per_channel=max_per_channel,
    )
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(f"Events: {payload.get('summary', {}).get('events_created')}")


@interactions_app.command("timeline")
def interactions_timeline_cmd(
    *,
    organization: Optional[str] = typer.Option(None, "--organization"),
    client_workstream: Optional[str] = typer.Option(None, "--client-workstream"),
    since: Optional[str] = typer.Option(None, "--since"),
    fmt: str = typer.Option("md", "--format"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    from zab.services import local_db
    from zab.services.conversation_ledger.store import list_events
    from zab.services.conversation_ledger.sync import build_timeline_markdown

    if json_out or fmt == "json":
        with local_db.transaction() as conn:
            events = list_events(conn, limit=200)
        typer.echo(json.dumps({"events": events}, ensure_ascii=False, indent=2))
        return
    typer.echo(
        build_timeline_markdown(
            organization=organization,
            client_workstream=client_workstream,
            since=since,
        )
    )


@interactions_app.command("reindex")
def interactions_reindex_cmd(
    *,
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    from zab.services.conversation_ledger.sync import reindex_entity_links

    payload = reindex_entity_links()
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(f"Reindexed: {payload.get('updated')}")


@interactions_app.command("compact-events")
def interactions_compact_events_cmd(
    *,
    apply: bool = typer.Option(False, "--apply"),
    archive: bool = typer.Option(True, "--archive/--no-archive"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    from zab.services.conversation_ledger.store import compact_events_jsonl

    payload = compact_events_jsonl(apply=apply, archive=archive)
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    mode = "compacted" if apply else "dry-run"
    typer.echo(
        f"Events {mode}: count={payload.get('event_count')} "
        f"reclaimable={payload.get('bytes_reclaimable')}"
    )


@interactions_app.command("enrich-content")
def interactions_enrich_content_cmd(
    organization: str = typer.Option("", "--organization", help="Organization id or label (empty = all indexed)"),
    *,
    limit: int = typer.Option(500, "--limit"),
    max_fetch: int = typer.Option(0, "--max-fetch", help="Cap Gmail fetches (0 = no cap)"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    from zab.services.conversation_ledger.content_enrichment import enrich_events_content, enrich_organization_content
    from zab.services.conversation_ledger.entity_resolver import DEFAULT_ORGANIZATIONS
    from zab.services.conversation_ledger.store import list_events
    from zab.services import local_db

    cap = max_fetch if max_fetch > 0 else None
    if organization:
        org_id = None
        needle = organization.lower()
        for oid, org in DEFAULT_ORGANIZATIONS.items():
            if oid == organization or org["label"].lower() == needle:
                org_id = oid
                break
        if not org_id:
            raise typer.BadParameter(f"organization not recognized: {organization}")
        payload = enrich_organization_content(org_id, limit=limit, max_fetch=cap)
    else:
        with local_db.transaction() as conn:
            events = list_events(conn, limit=limit)
        enriched, stats = enrich_events_content(events, persist=True, max_fetch=cap)
        payload = {
            "contract": "conversation-ledger-enrich-content",
            "events_scanned": len(enriched),
            "events_with_body": sum(1 for e in enriched if e.get("body")),
            **stats,
        }
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(
        f"Enriched: fetched={payload.get('fetched')} "
        f"with_body={payload.get('events_with_body')} "
        f"scanned={payload.get('events_scanned')}"
    )


@interactions_app.command("sync-org")
def interactions_sync_org_cmd(
    organization: str = typer.Option(..., "--organization"),
    *,
    since: str = typer.Option("90d", "--since"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    from zab.services.conversation_ledger.sync import sync_organization

    payload = sync_organization(organization, since=since, dry_run=dry_run)
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(f"Events: {payload.get('events_created')} org={payload.get('organization', {}).get('label')}")


@interactions_app.command("unclassified")
def interactions_unclassified_cmd(
    *,
    since: str = typer.Option("", "--since"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    from zab.services.conversation_ledger.resolve import list_unclassified

    payload = list_unclassified(since=since or None)
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(f"Ambiguous events: {payload.get('count')}")


@interactions_app.command("resolve")
def interactions_resolve_cmd(
    *,
    organization: str = typer.Option(..., "--organization"),
    client_workstream: Optional[str] = typer.Option(None, "--client-workstream"),
    since: Optional[str] = typer.Option(None, "--since"),
    dry_run: bool = typer.Option(True, "--dry-run/--apply"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    from zab.services.conversation_ledger.resolve import resolve_preview

    payload = resolve_preview(
        organization=organization,
        client_workstream=client_workstream,
        since=since,
        dry_run=dry_run,
    )
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(f"Events: {payload.get('event_count')} clusters: {payload.get('cluster_count')}")


@interactions_app.command("link")
def interactions_link_cmd(
    event_id: str = typer.Argument(..., help="event_id"),
    *,
    organization: str = typer.Option(..., "--organization"),
    client_workstream: str = typer.Option(..., "--client-workstream"),
    confirm: bool = typer.Option(False, "--confirm"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    from zab.services.conversation_ledger.resolve import link_event

    payload = link_event(
        event_id,
        organization=organization,
        client_workstream=client_workstream,
        confirm=confirm,
    )
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(f"Linked {event_id} confirmed={confirm}")


@workpacket_app.command("projections")
def workpacket_projections_cmd(
    wp_id: str = typer.Argument(..., help="workpacket_id"),
    *,
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    from zab.services import local_db
    from zab.services.conversation_ledger.store import get_workpacket, list_projections, list_workpackets

    with local_db.transaction() as conn:
        packet = get_workpacket(conn, wp_id)
        if not packet:
            for candidate in list_workpackets(conn, limit=500):
                if candidate.get("display_id") == wp_id:
                    packet = candidate
                    break
        if not packet:
            typer.echo(f"WorkPacket introuvable: {wp_id}", err=True)
            raise typer.Exit(1)
        items = list_projections(conn, packet["workpacket_id"])
    payload = {"contract": "workpacket-projections", "workpacket_id": packet["workpacket_id"], "items": items}
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    for item in items:
        typer.echo(f"{item.get('target')}: {item.get('status')}")


@ledger_app.command("eval")
def ledger_eval_cmd(
    *,
    suite: str = typer.Option("all", "--suite", help="all|hard|quality"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    from zab.services.conversation_ledger.eval import run_eval

    payload = run_eval(suite=suite)
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(f"score={payload.get('score')} blockers={len(payload.get('blockers') or [])}")


@ledger_app.command("preflight")
def ledger_preflight_cmd(
    *,
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    from zab.services.conversation_ledger.preflight import run_preflight

    payload = run_preflight()
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(json.dumps(payload.get("gog"), ensure_ascii=False))


@tasks_app.command(name="sync")
def tasks_sync() -> None:
    """Synchronise la boîte de réception des tâches et met en cache local."""
    from zab.services.tasks_inbox import sync_tasks_inbox
    import typer
    from rich.console import Console

    console = Console()
    console.print("[yellow]Synchronisation des tâches en cours...[/yellow]")
    data = sync_tasks_inbox()
    console.print(f"[green]✔ Synchro terminée.[/green] {data.get('total_count', 0)} tâches trouvées parmi {len(data.get('sources', []))} sources.")


@command_center_app.command("context")
def command_center_context_cmd(
    *,
    refresh: bool = typer.Option(False, "--refresh", help="Relit explicitement les sources supportées avant le packet"),
    write: bool = typer.Option(False, "--write", help="Ecrit le packet latest + historique dans ~/.local/share/zab"),
    markdown: bool = typer.Option(False, "--markdown", help="Affiche le Markdown du packet"),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Produit le packet de contexte daily lu par Hermes Command Center."""
    payload = write_context_packet(refresh=refresh) if write else build_context_packet(refresh=refresh)
    if markdown:
        typer.echo(str(payload.get("markdown") or "").rstrip())
        return
    clean = {k: v for k, v in payload.items() if k != "markdown"}
    if json_out:
        typer.echo(json.dumps(clean, ensure_ascii=False, indent=2))
        return
    typer.echo(typer.style("Zab Command Center context packet", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"  freshness : {payload.get('freshness', {}).get('global_score')}/100")
    typer.echo(f"  quality   : {payload.get('quality_gate', {}).get('status')}")
    typer.echo(f"  gaps      : {len(payload.get('context_gaps') or [])}")
    if write:
        paths = payload.get("paths") or {}
        typer.echo(f"  json      : {paths.get('latest_json')}")
        typer.echo(f"  markdown  : {paths.get('latest_markdown')}")

@tasks_app.command(name="list")
def tasks_list(
    *,
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Liste les tâches depuis le cache local (unifié)."""
    from zab.services.tasks_inbox import fetch_tasks_inbox

    data = fetch_tasks_inbox()
    if json_out:
        typer.echo(json.dumps(data, ensure_ascii=False, indent=2))
        return
    from rich.console import Console
    from rich.table import Table

    console = Console()

    total = data.get('total_count', 0)
    table = Table(title=f"Tâches Unifiées (Total: {total})", header_style="bold blue")
    table.add_column("Source", style="cyan", no_wrap=True)
    table.add_column("ID", style="magenta")
    table.add_column("Titre")
    table.add_column("Statut", style="yellow")
    table.add_column("Dernière MàJ", style="dim")

    for t in data.get("all_tasks", []):
        table.add_row(
            t.get("source_label", ""),
            t.get("identifier", ""),
            t.get("title", "")[:80] + ("..." if len(t.get("title", "")) > 80 else ""),
            t.get("state", ""),
            t.get("updated_at", "")[:16].replace("T", " "),
        )

    console.print(table)


@db_app.command("status")
def db_status_cmd(
    *,
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Affiche le statut de la base Postgres canonique."""
    from zab.services import postgres_store

    payload = postgres_store.status()
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False).rstrip())


@db_app.command("migrate")
def db_migrate_cmd(
    *,
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Crée ou migre le schéma Postgres canonique."""
    from zab.services import postgres_store

    payload = postgres_store.migrate_schema()
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False).rstrip())


@db_app.command("export")
def db_export_cmd(
    *,
    fmt: str = typer.Option("json", "--format", help="json ou yaml"),
) -> None:
    """Exporte le contenu Postgres pour debug/backup."""
    from zab.services import postgres_store

    normalized = fmt.strip().lower()
    if normalized not in ("json", "yaml"):
        typer.echo("--format doit être json ou yaml", err=True)
        raise typer.Exit(1)
    typer.echo(postgres_store.export_database(fmt=normalized).rstrip())


@db_app.command("import-legacy")
def db_import_legacy_cmd(
    *,
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Importe SQLite legacy et fichiers JSON/YAML dans Postgres."""
    from zab.services import postgres_store

    payload = postgres_store.import_legacy()
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False).rstrip())


@db_app.command("vacuum")
def db_vacuum_cmd(
    *,
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Lance la maintenance Postgres (ANALYZE) sur le schéma Zab."""
    from zab.services import postgres_store

    payload = postgres_store.vacuum()
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False).rstrip())


channels_app = typer.Typer(help="Gestion des canaux de communication (emails, WhatsApp, Slack, Telegram).", no_args_is_help=True)
app.add_typer(channels_app, name="channels")

@channels_app.command(name="sync")
def channels_sync() -> None:
    """Synchronise tous les canaux de communication et génère les actions du cockpit."""
    from zab.services.communication_channels import sync_communication_channels
    from rich.console import Console

    console = Console()
    console.print("[yellow]Synchronisation des canaux de communication en cours...[/yellow]")
    data = sync_communication_channels()
    
    # Calculer le nombre total de messages d'actions et non lus
    actions_count = data.get("total_actions_count", 0)
    unread_emails = 0
    for c in data.get("channels", []):
        if c.get("type") == "email":
            unread_emails += c.get("sync_summary", {}).get("unread_count", 0)
            
    console.print(f"[green]✔ Synchro terminée.[/green] {len(data.get('channels', []))} canaux synchronisés.")
    console.print(f"👉 Mails non lus : [bold cyan]{unread_emails}[/bold cyan] | Actions prioritaires détectées : [bold magenta]{actions_count}[/bold magenta]")

@channels_app.command(name="list")
def channels_list() -> None:
    """Liste les canaux de communication et leur état actuel de synchronisation."""
    from zab.services.communication_channels import fetch_channels_cache
    from rich.console import Console
    from rich.table import Table

    data = fetch_channels_cache()
    console = Console()

    table = Table(title="Canaux de Communication", header_style="bold green")
    table.add_column("Canal (Label)", style="cyan", no_wrap=True)
    table.add_column("Type", style="magenta")
    table.add_column("Connecteur", style="blue")
    table.add_column("Organisation", style="yellow")
    table.add_column("Statut", style="green")
    table.add_column("Synchro / Non lus", style="bold white")

    for c in data.get("channels", []):
        summary_text = ""
        st = c.get("type")
        if st == "email":
            sum_info = c.get("sync_summary", {})
            unread = sum_info.get("unread_count", 0)
            today = sum_info.get("received_today", 0)
            week = sum_info.get("received_this_week", 0)
            summary_text = f"Non lus: {unread} | Reçus ce jour: {today} | Semaine: {week}"
        else:
            unread = c.get("sync_summary", {}).get("unread_count", 0)
            summary_text = f"Messages non lus: {unread}"
            
        table.add_row(
            c.get("label", ""),
            c.get("type", ""),
            c.get("connector", ""),
            c.get("org", "personal"),
            "✔ OK" if c.get("status") == "ok" else f"❌ {c.get('reason', 'Erreur')}",
            summary_text
        )

    console.print(table)

@channels_app.command(name="add")
def channels_add(
    label: str = typer.Argument(..., help="Nom d'affichage du canal"),
    type_chan: str = typer.Option(..., "--type", "-t", help="Type de canal (email, whatsapp, slack, telegram)"),
    connector: str = typer.Option(..., "--connector", "-c", help="Connecteur (gmail, outlook, evolution-api, slack, telegram)"),
    email: str = typer.Option(None, "--email", "-e", help="Adresse e-mail optionnelle"),
    org: str = typer.Option(None, "--org", "-o", help="Organisation associée (slug)"),
) -> None:
    """Ajoute un nouveau canal de communication à la configuration."""
    from zab.services.communication_channels import add_channel_config, sync_communication_channels
    from rich.console import Console

    console = Console()
    console.print(f"[yellow]Ajout du canal [bold]{label}[/bold]...[/yellow]")
    
    new_chan = add_channel_config(
        label=label,
        channel_type=type_chan,
        connector=connector,
        email_address=email,
        org=org
    )
    
    # Synchroniser immédiatement pour mettre à jour le cache
    sync_communication_channels()
    
    console.print(f"[green]✔ Canal ajouté avec succès ! ID attribué : [bold]{new_chan['id']}[/bold][/green]")


@channels_app.command(name="setup")
def channels_setup() -> None:
    """Wizard interactif : crée un canal (email/Slack/WhatsApp), écrit config.yaml et teste la connexion."""
    from zab.services.channels_setup import run_channel_setup_wizard

    run_channel_setup_wizard()


_INVENTORY_SECTIONS: dict[str, str] = {
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
    "knowledge_sources": "knowledge_sources",
    "security": "security",
    "policies": "policies",
    "subscriptions": "subscriptions",
    "projects": "projects",
    "orgs": "orgs",
}


def _tilde_path(path: Path) -> str:
    try:
        home = Path.home().resolve()
        p = path.resolve()
        if p == home:
            return "~"
        rel = p.relative_to(home)
        return "~/" + str(rel).replace("\\", "/")
    except ValueError:
        return str(path)


def _open_path(path: Path) -> None:
    open_os_path(path)


def _local_tools_origin() -> tuple[Path, str]:
    user_cfg = config_dir() / "local-tools.yaml"
    if user_cfg.is_file():
        return user_cfg.resolve(), "utilisateur (~/.config/zab/local-tools.yaml)"
    pkg = zab_package_dir() / "local-tools.yaml"
    if pkg.is_file():
        return pkg.resolve(), "dépôt zab (exemple embarqué)"
    return user_cfg.resolve(), "emplacement par défaut (fichier absent)"


def _pretty_user_yaml(cfg: dict[str, Any]) -> str:
    clean = {k: v for k, v in cfg.items() if not str(k).startswith("_")}
    if not clean:
        return "(aucune clé ; fichier absent ou vide)"
    return yaml.safe_dump(clean, allow_unicode=True, sort_keys=False).rstrip()


def _resolve_inventory_section(raw: str) -> str:
    key = raw.strip().lower()
    section = _INVENTORY_SECTIONS.get(key)
    if not section:
        choices = ", ".join(sorted(_INVENTORY_SECTIONS))
        raise ValueError(f"section inconnue: {raw!r}. Choix: {choices}")
    return section


@app.command("config")
def config_cmd(
    *,
    open_user_config: bool = typer.Option(False, "--open", "-o", help="Ouvrir ~/.config/zab/config.yaml"),
    open_tools: bool = typer.Option(
        False,
        "--open-tools",
        help="(déprécié) Ouvre ~/.config/zab/config.yaml — même effet que --open",
        hidden=True,
    ),
    paths_only: bool = typer.Option(False, "--paths", "-p", help="Afficher uniquement les chemins (une paire clé=chem par ligne)"),
) -> None:
    """Affiche la configuration résolue (chemins, variables, contenu de config.yaml)."""
    sr_path, sr_rule = resolve_skills_root()
    cfg_path = user_config_path()
    cfg_raw = load_user_config()
    dd = data_dir()

    if paths_only:
        typer.echo(f"skills_root={sr_path}")
        typer.echo(f"skills_root_source={sr_rule}")
        typer.echo(f"config_yaml={cfg_path.resolve()}")
        typer.echo(f"config_dir={config_dir().resolve()}")
        typer.echo(f"data_dir={dd.resolve()}")
        typer.echo(f"zab_repo={zab_repo_root().resolve()}")
        return

    if open_user_config or open_tools:
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        _open_path(cfg_path)

    typer.echo(typer.style(" ╭────────────────────────────────────────────────────╮", fg=typer.colors.WHITE))
    typer.echo(typer.style(" │", fg=typer.colors.WHITE) + "  zab — configuration                               " + typer.style("│", fg=typer.colors.WHITE))
    typer.echo(typer.style(" ╰────────────────────────────────────────────────────╯", fg=typer.colors.WHITE))
    typer.echo("")

    if open_user_config or open_tools:
        typer.echo(typer.style("  (config.yaml ouvert dans l’application par défaut)", fg=typer.colors.GREEN))
        typer.echo("")

    typer.echo(typer.style("  Racine skills (effectif)", bold=True))
    typer.echo(f"    {_tilde_path(sr_path)}")
    typer.echo(typer.style(f"    ← {sr_rule}", dim=True))
    typer.echo("")
    typer.echo(typer.style("  Dashboard (données API)", bold=True))
    dash_sr = skills_root_from_config_file_only()
    if dash_sr is not None:
        typer.echo(f"    ancrage : {_tilde_path(dash_sr)}")
        typer.echo(typer.style("    ← skills-registry (adoptées) / skills_roots / plugins (premier chemin résolu)", dim=True))
    else:
        typer.echo(
            typer.style(
                "    Définissez skills_roots ou adoptez des skills (skills-registry.json) — voir docs/skills-registry-migration.md.",
                dim=True,
            )
        )
    typer.echo("")

    typer.echo(typer.style("  Variables d'environnement", bold=True))
    for name in ("ZAB_SKILLS_ROOT", "ZAB_INVOCATION_CWD", "ZAB_REPO", "ZAB_UI_DIST", "XDG_CONFIG_HOME"):
        raw = os.environ.get(name)
        if raw:
            typer.echo(f"    {typer.style(name, fg=typer.colors.CYAN)}={raw}")
        else:
            typer.echo(typer.style(f"    {name} (non défini)", dim=True))
    typer.echo("")

    typer.echo(typer.style("  Fichier de configuration", bold=True))
    cfg_exists = cfg_path.is_file()
    typer.echo(
        f"    {'●' if cfg_exists else '○'} "
        f"{typer.style('config.yaml', fg=typer.colors.CYAN)}  {_tilde_path(cfg_path)}"
        + ("" if cfg_exists else typer.style("  (absent)", dim=True))
    )
    typer.echo(
        f"    ● {typer.style('répertoire données', fg=typer.colors.CYAN)}  {_tilde_path(dd)}"
    )
    typer.echo(
        f"    ● {typer.style('dépôt zab (code)', fg=typer.colors.CYAN)}  {_tilde_path(zab_repo_root())}"
    )
    typer.echo("")

    if cfg_raw.get("_error") == "yaml_invalid":
        typer.echo(typer.style("  ⚠ YAML invalide dans config.yaml — corrigez le fichier.", fg=typer.colors.RED))
        typer.echo(typer.style(f"     {cfg_raw.get('path', '')}", dim=True))
        typer.echo("")
    else:
        typer.echo(typer.style("  Contenu de config.yaml", bold=True))
        block = _pretty_user_yaml(cfg_raw)
        for line in block.splitlines():
            typer.echo(typer.style("  │ ", dim=True) + line)
        typer.echo("")

    typer.echo(typer.style("  Édition", bold=True))
    typer.echo(f"    {typer.style('zab config --open', fg=typer.colors.GREEN)} → {_tilde_path(cfg_path)}")
    typer.echo(typer.style(f"    ou ouvrez directement : {_tilde_path(cfg_path)}", dim=True))


@app.command()
def doctor() -> None:
    """Check toolchain and optional zab configuration."""
    root = skills_root()
    typer.echo(f"SKILLS_ROOT = {root}")
    checks: list[tuple[str, object, str, bool]] = [
        ("orgs", root / "orgs", "dir", False),
        ("configs/cursor-mcp.json", root / "configs" / "cursor-mcp.json", "file", False),
    ]
    for name, path, kind, required in checks:
        p = Path(path)
        ok = p.is_dir() if kind == "dir" else p.is_file()
        mark = "OK" if ok else ("!!" if required else "--")
        typer.echo(f"  [{mark}] {name}: {p}")
    for bin_name in ("uv", "node", "npm"):
        loc = shutil.which(bin_name)
        typer.echo(f"  [{'OK' if loc else '!!'}] {bin_name}: {loc or 'absent'}")
    mp = shutil.which("mempalace")
    typer.echo(f"  [{'OK' if mp else '--'}] mempalace (optional): {mp or 'absent'}")
    if mp:
        try:
            proc = subprocess.run([mp, "--version"], capture_output=True, text=True, timeout=5)
            ver = (proc.stdout or proc.stderr or "").strip().splitlines()
            if ver:
                typer.echo(typer.style(f"      {ver[0][:120]}", dim=True))
        except (OSError, subprocess.TimeoutExpired):
            pass
    mp_mcp = shutil.which("mempalace-mcp")
    typer.echo(f"  [{'OK' if mp_mcp else '--'}] mempalace-mcp (optional): {mp_mcp or 'absent'}")
    if mp_mcp:
        try:
            proc = subprocess.run([mp_mcp, "-h"], capture_output=True, text=True, timeout=5)
            ver = (proc.stdout or proc.stderr or "").strip().splitlines()
            if ver:
                typer.echo(typer.style(f"      {ver[0][:120]}", dim=True))
        except (OSError, subprocess.TimeoutExpired):
            pass
    dsn_ok = bool(
        resolve_mehdi_memory_database_url(skills_root_from_config_file_only())
        or resolve_mehdi_memory_database_url(root)
    )
    typer.echo(
        f"  [{'OK' if dsn_ok else '--'}] ZAB_MEMORY_DATABASE_URL / MEHDI_MEMORY_DATABASE_URL: "
        f"{'present' if dsn_ok else 'absent (optional)'}"
    )


@app.command("cli-check")
def cli_check_cmd(
    config_path: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Fichier JSON de checks CLI auth (défaut: ~/.config/zab/cli-checks.json).",
    ),
    init: bool = typer.Option(False, "--init", help="Créer le fichier JSON d'exemple puis quitter."),
    force: bool = typer.Option(False, "--force", help="Avec --init, remplace le fichier existant."),
    open_config: bool = typer.Option(False, "--open", help="Ouvrir le fichier JSON dans l'application par défaut."),
    only: Optional[list[str]] = typer.Option(None, "--only", help="Limiter à un id ou label de check (répétable)."),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts."),
    strict: bool = typer.Option(False, "--strict", help="Quitter avec code 1 si au moins un check est KO."),
) -> None:
    """Valide les authentifications CLI depuis un fichier JSON déclaratif."""
    target = config_path.expanduser() if config_path else None
    if init:
        path = cli_check_svc.ensure_default_cli_checks_config(overwrite=force, path=target)
        if open_config:
            _open_path(path)
        payload = {"written": True, "path": str(path)}
        if json_out:
            typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            typer.echo(typer.style("Fichier cli-check prêt", fg=typer.colors.GREEN, bold=True))
            typer.echo(f"  {path}")
        return

    if open_config:
        path = cli_check_svc.ensure_default_cli_checks_config(path=target)
        _open_path(path)

    try:
        payload = cli_check_svc.run_cli_checks(target, only=only)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc

    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        typer.echo(typer.style("zab — CLI auth checks", bold=True))
        typer.echo(f"  config : {payload['config_path']}")
        typer.echo(
            f"  score  : {payload['percentage']}% · "
            f"{payload['ok']} OK · {payload['warn']} warn · {payload['fail']} KO"
        )
        for row in payload.get("checks") or []:
            status = str(row.get("status") or "?")
            color = (
                typer.colors.GREEN
                if status == "ok"
                else typer.colors.YELLOW
                if status in {"warn", "skipped"}
                else typer.colors.RED
            )
            typer.echo("")
            typer.echo(f"  [{typer.style(status.upper(), fg=color)}] {row.get('label') or row.get('id')}")
            typer.echo(f"      {row.get('message')}")
            url = row.get("url")
            if url:
                typer.echo(typer.style(f"      {url}", dim=True))
            detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
            cmd = detail.get("command")
            if isinstance(cmd, list) and cmd:
                typer.echo(typer.style("      $ " + " ".join(str(x) for x in cmd), dim=True))

    if strict and int(payload.get("fail") or 0) > 0:
        raise typer.Exit(1)


@app.command("cli-update-status")
def cli_update_status_cmd(
    config_path: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Fichier JSON de checks CLI (défaut: ~/.config/zab/cli-checks.json).",
    ),
    only: Optional[list[str]] = typer.Option(None, "--only", help="Limiter à un id, label ou binaire (répétable)."),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts."),
    markdown_out: bool = typer.Option(False, "--markdown", help="Afficher le rapport Markdown."),
    write_path: Optional[Path] = typer.Option(None, "--write", "-w", help="Écrire le rapport Markdown à cet emplacement."),
    network: bool = typer.Option(True, "--network/--no-network", help="Autoriser les sources réseau (npm, PyPI, GitHub, URL)."),
    timeout_seconds: float = typer.Option(8.0, "--timeout", help="Timeout par probe, en secondes."),
    strict: bool = typer.Option(False, "--strict", help="Quitter avec code 1 si un statut n'est pas vérifiable ou à jour."),
) -> None:
    """Documente pour chaque CLI suivi s'il est à jour, en retard, absent ou indéterminé."""
    target = config_path.expanduser() if config_path else None
    try:
        payload = cli_update_svc.run_cli_update_status(
            target,
            only=only,
            network=network,
            timeout_seconds=timeout_seconds,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc

    if write_path is not None:
        report_path = write_path.expanduser().resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(cli_update_svc.render_cli_update_markdown(payload), encoding="utf-8")
        payload["markdown_path"] = str(report_path)

    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    elif markdown_out:
        typer.echo(cli_update_svc.render_cli_update_markdown(payload).rstrip())
    else:
        counts = payload.get("counts") or {}
        typer.echo(typer.style("zab — CLI update status", bold=True))
        typer.echo(f"  config : {payload['config_path']}")
        typer.echo(
            f"  statut : {counts.get('up_to_date', 0)}/{payload.get('total', 0)} à jour · "
            f"{counts.get('outdated', 0)} à mettre à jour · "
            f"{counts.get('missing', 0)} absents · "
            f"{counts.get('unknown_latest', 0) + counts.get('unknown_local', 0)} indéterminés"
        )
        if payload.get("markdown_path"):
            typer.echo(f"  rapport: {payload['markdown_path']}")
        for row in payload.get("items") or []:
            status = str(row.get("status") or "?")
            color = (
                typer.colors.GREEN
                if status == "up_to_date"
                else typer.colors.RED
                if status in {"outdated", "missing"}
                else typer.colors.YELLOW
            )
            local = row.get("local_version") or row.get("local_version_raw") or "?"
            latest = row.get("latest_version") or "?"
            source = row.get("latest_source") or "unknown"
            typer.echo("")
            typer.echo(f"  [{typer.style(status.upper(), fg=color)}] {row.get('label') or row.get('binary')}")
            typer.echo(f"      local {local} · latest {latest} · source {source}")
            typer.echo(f"      {row.get('message')}")
            path = row.get("binary_path")
            if path:
                typer.echo(typer.style(f"      {path}", dim=True))

    if strict:
        counts = payload.get("counts") or {}
        not_verified_or_stale = (
            int(counts.get("outdated") or 0)
            + int(counts.get("missing") or 0)
            + int(counts.get("unknown_local") or 0)
            + int(counts.get("unknown_latest") or 0)
        )
        if not_verified_or_stale > 0:
            raise typer.Exit(1)


@app.command("dashboard")
def dashboard_cmd(
    host: str = typer.Option("127.0.0.1", help="Bind API"),
    port: int = typer.Option(8742, help="Port API"),
    dev: bool = typer.Option(False, "--dev", help="Affiche la commande pour lancer Vite en parallèle"),
    reload: bool = typer.Option(False, "--reload", "-r", help="Redémarrage automatique si le code Python change"),
    no_open: bool = typer.Option(False, "--no-open", help="Ne pas ouvrir le navigateur"),
) -> None:
    """Démarre le serveur FastAPI (dashboard API + SPA dist si buildée)."""
    if dev:
        typer.echo(
            "Mode dev : dans un second terminal, exécute :\n"
            f"  cd {zab_repo_root() / 'zab-ui'} && npm install && npm run dev\n"
            f"Le proxy Vite pointe vers http://{host}:{port}/api"
        )
    url = f"http://{host}:{port}/"
    if not no_open:
        if (zab_ui_dist_dir() / "index.html").is_file():
            webbrowser.open(url)
        else:
            webbrowser.open(f"http://{host}:{port}/api/health")
    uvicorn.run(
        "zab.api.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
    )

@app.command("gateway")
def gateway_cmd(
    host: str = typer.Option("127.0.0.1", help="Bind API"),
    port: int = typer.Option(8742, help="Port API"),
) -> None:
    """Démarre le serveur FastAPI en mode background/gateway (sans UI navigateur)."""
    typer.echo(f"Démarrage de Zab Gateway sur http://{host}:{port}...")
    uvicorn.run(
        "zab.api.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=False,
    )


@app.command("dashboard-dev")
def dashboard_dev_cmd(
    host: Optional[str] = typer.Option(None, help="Bind API (défaut 127.0.0.1, identique à `zab dashboard`)"),
    port: Optional[int] = typer.Option(
        None,
        help=(
            "Port API en mode dev (défaut 8750 ; `zab dashboard` reste sur 8742). "
            "Sans valeur explicite, le lanceur bascule sur un port libre si 8750 est pris."
        ),
    ),
    ui_port: Optional[int] = typer.Option(None, help="Port Vite (zab-ui), défaut 5280"),
) -> None:
    """Lance l’API en --reload et Vite (zab-ui) avec proxy /api dans le même terminal."""
    script = zab_repo_root() / "scripts" / "zab-dashboard-dev.sh"
    if not script.is_file():
        typer.echo(f"Script introuvable : {script}", err=True)
        raise typer.Exit(1)
    # N'exporter que ce que l'appelant a explicitement demandé : forcer les valeurs par
    # défaut rendrait tout port « explicite » et désactiverait le repli automatique.
    env = os.environ.copy()
    if host is not None:
        env["ZAB_DASHBOARD_HOST"] = host
    if port is not None:
        env["ZAB_DASHBOARD_PORT"] = str(port)
    if ui_port is not None:
        env["ZAB_UI_DEV_PORT"] = str(ui_port)
    root = str(zab_repo_root())
    if os.name == "posix":
        # `exec` plutôt qu'un sous-processus : un lanceur (Raycast, launchd) qui suit ce
        # PID envoie alors ses signaux directement au script, dont le trap libère les
        # ports. Avec un sous-processus, le signal s'arrêtait ici et laissait des orphelins.
        os.chdir(root)
        os.execve("/bin/bash", ["bash", str(script)], env)
    proc = subprocess.run(["bash", str(script)], cwd=root, env=env)
    raise typer.Exit(proc.returncode)


@app.command("run")
def run_cmd(
    smoke: bool = typer.Option(False, "--smoke", help="Exécute scripts/smoke_test_all_mcps.sh"),
) -> None:
    """Lance un script prédéfini (stdout/stderr hérités du terminal)."""
    root = skills_root()
    if smoke:
        script = scripts_dir() / "smoke_test_all_mcps.sh"
        if not script.is_file():
            typer.echo(f"Script absent : {script}", err=True)
            raise typer.Exit(1)
        proc = subprocess.run(["bash", str(script)], cwd=str(root))
        raise typer.Exit(proc.returncode)
    typer.echo("Indique une action, ex. : zab run --smoke", err=True)
    raise typer.Exit(1)


@app.command("sync")
def sync_cmd(
    *,
    json_out: bool = typer.Option(False, "--json", help="Affiche le résumé JSON"),
) -> None:
    """Reconstruit l'index YAML régénérable de l'univers zab."""
    path, state = sync_state()
    summary = state_summary(state)
    if json_out:
        typer.echo(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    counts = summary["counts"]
    typer.echo(typer.style("Index zab synchronisé", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"  Base    : {summary.get('database_path')}")
    typer.echo(f"  Export  : {path}")
    typer.echo(f"  Version : {summary.get('version')}")
    typer.echo(f"  Orgs    : {counts['orgs']}")
    typer.echo(f"  Projets : {counts['projects']}")
    typer.echo(f"  Skills  : {counts['skills']}")
    typer.echo(f"  Connecteurs : {counts['connectors']}")
    typer.echo(f"  Mémoire : {counts['memory_sources']}")


@app.command("context-pack")
def context_pack_cmd(
    *,
    org: Optional[str] = typer.Option(None, "--org", help="Filtrer sur une organisation"),
    project: Optional[str] = typer.Option(None, "--project", help="Filtrer sur un projet ou chemin"),
    query: Optional[str] = typer.Option(None, "--query", "-q", help="Filtrer sur une requête simple"),
    include: Optional[list[str]] = typer.Option(None, "--include", help="Section à inclure (répétable)"),
    limit: int = typer.Option(80, "--limit", min=1, max=300, help="Nombre maximal de skills"),
    stdout: bool = typer.Option(False, "--stdout", help="Écrire le Markdown complet sur stdout"),
    json_out: bool = typer.Option(False, "--json", help="Affiche le résumé JSON"),
) -> None:
    """Génère un pack Markdown local pour coller du contexte dans un agent web."""
    path, text = build_context_pack(org=org, project=project, query=query, include=include, limit=limit)
    payload = {
        "path": str(path),
        "bytes": len(text.encode("utf-8")),
        "org": org,
        "project": project,
        "query": query,
        "include": include or ["skills", "connectors", "code_tools", "memory_sources"],
        "limit": limit,
    }
    if stdout:
        typer.echo(text.rstrip())
        return
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(typer.style("Context Pack généré", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"  Fichier : {path}")
    typer.echo(f"  Taille  : {payload['bytes']} bytes")


@app.command("capabilities")
def capabilities_cmd(
    *,
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Expose le manifeste AI-native Core/CLI/MCP/API/UI de Zab."""
    payload = get_capabilities()
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(typer.style("zab — capability manifest", bold=True))
    typer.echo(f"  total    : {payload['summary']['total']}")
    typer.echo(f"  complete : {payload['summary']['complete']} · partial: {payload['summary']['partial']}")
    typer.echo("  json     : zab capabilities --json")
    for cap in payload.get("capabilities") or []:
        typer.echo(f"  · {cap.get('id')} [{cap.get('status')}] {cap.get('summary')}")


@app.command("source-health")
def source_health_cmd(
    *,
    refresh: bool = typer.Option(False, "--refresh", help="Relit explicitement les sources externes supportées"),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Expose le Source Health unifié de Zab."""
    payload = agent_context.source_health(refresh=refresh)
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    counts = payload.get("status_counts") or {}
    typer.echo(typer.style("zab source health", bold=True))
    typer.echo(f"  sources : {len(payload.get('sources') or [])}")
    typer.echo("  status  : " + " · ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
    typer.echo("  json    : zab source-health --json")


@logs_app.command("tail")
def logs_tail_cmd(
    *,
    file: str = typer.Option("requests", "--file", help="requests|cli|api|mcp|jobs|errors"),
    lines: int = typer.Option(100, "--lines", "-n", min=1, max=1000),
    level: Optional[str] = typer.Option(None, "--level", help="Niveau minimal DEBUG|INFO|WARNING|ERROR"),
    component: Optional[str] = typer.Option(None, "--component", help="Filtrer par composant"),
    surface: Optional[str] = typer.Option(None, "--surface", help="Filtrer par surface cli|api|mcp|jobs"),
    actor: Optional[str] = typer.Option(None, "--actor", help="Filtrer par acteur"),
    org: Optional[str] = typer.Option(None, "--org", help="Filtrer par organisation"),
    project: Optional[str] = typer.Option(None, "--project", help="Filtrer par projet"),
    status: Optional[str] = typer.Option(None, "--status", help="Filtrer par statut"),
    q: Optional[str] = typer.Option(None, "--q", help="Recherche texte"),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON"),
) -> None:
    """Affiche les derniers événements structurés Zab."""
    has_filters = any([level, component, surface, actor, org, project, status, q])
    if has_filters and file.strip().lower().replace(".jsonl", "") == "requests":
        payload = request_logs.query_events(
            surface=surface,
            component=component,
            level=level,
            actor=actor,
            org=org,
            project=project,
            status=status,
            q=q,
            limit=lines,
        )
    else:
        payload = request_logs.tail_file(file=file, lines=lines * 5 if has_filters else lines)
        if has_filters:
            events = request_logs.filter_events(
                [event for event in payload.get("events") or [] if isinstance(event, dict)],
                surface=surface,
                component=component,
                level=level,
                actor=actor,
                org=org,
                project=project,
                status=status,
                q=q,
            )[:lines]
            payload = {**payload, "events": events, "total": len(events)}
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    events = payload.get("events") or []
    typer.echo(typer.style(f"zab logs ({len(events)})", bold=True))
    for event in events:
        if isinstance(event, dict):
            typer.echo(_format_log_event(event))


@logs_app.command("query")
def logs_query_cmd(
    *,
    surface: Optional[str] = typer.Option(None, "--surface", help="Surface cli|api|mcp|jobs"),
    component: Optional[str] = typer.Option(None, "--component", help="Composant"),
    level: Optional[str] = typer.Option(None, "--level", help="Niveau minimal"),
    actor: Optional[str] = typer.Option(None, "--actor", help="Acteur"),
    org: Optional[str] = typer.Option(None, "--org", help="Organisation"),
    project: Optional[str] = typer.Option(None, "--project", help="Projet"),
    status: Optional[str] = typer.Option(None, "--status", help="Statut"),
    q: Optional[str] = typer.Option(None, "--q", help="Recherche texte"),
    since: Optional[str] = typer.Option(None, "--since", help="Depuis ex. 24h, 30m ou ISO timestamp"),
    limit: int = typer.Option(100, "--limit", min=1, max=1000),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON"),
) -> None:
    """Recherche dans l'index ou les fichiers de logs structurés."""
    payload = request_logs.query_events(
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
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(typer.style(f"zab logs query ({payload.get('total', 0)})", bold=True))
    for event in payload.get("events") or []:
        if isinstance(event, dict):
            typer.echo(_format_log_event(event))


@logs_app.command("summary")
def logs_summary_cmd(
    *,
    since: Optional[str] = typer.Option("24h", "--since", help="Fenêtre relative ou timestamp ISO"),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON"),
) -> None:
    """Synthèse des requêtes Zab récentes."""
    payload = request_logs.summary(since=since)
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(typer.style("zab logs summary", bold=True))
    typer.echo(f"  total : {payload.get('total', 0)}")
    for label, key in (("surfaces", "by_surface"), ("statuts", "by_status"), ("acteurs", "by_actor"), ("projets", "by_project")):
        values = payload.get(key) or []
        rendered = " · ".join(f"{row.get('id')}: {row.get('count')}" for row in values[:8] if isinstance(row, dict))
        typer.echo(f"  {label}: {rendered or '—'}")


def _format_log_event(event: dict[str, Any]) -> str:
    ts = str(event.get("ts") or "")[:19].replace("T", " ")
    level = str(event.get("level") or "INFO")
    component = str(event.get("component") or "")
    request = event.get("request") if isinstance(event.get("request"), dict) else {}
    result = event.get("result") if isinstance(event.get("result"), dict) else {}
    actor = event.get("actor") if isinstance(event.get("actor"), dict) else {}
    scope = event.get("scope") if isinstance(event.get("scope"), dict) else {}
    name = request.get("name") or request.get("path") or request.get("tool") or request.get("command") or "?"
    status = result.get("status") or "?"
    duration = result.get("duration_ms")
    actor_id = actor.get("id") or "?"
    project = scope.get("project_id") or scope.get("org") or "—"
    suffix = f" {duration}ms" if duration is not None else ""
    return f"{ts} {level:<7} {component:<16} {status:<7} {actor_id:<12} {project:<18} {name}{suffix}"


@app.command("research")
def research_cmd(
    query: str = typer.Argument(..., help="Question ou mission à transformer en research packet"),
    *,
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Nom ou chemin de projet"),
    mode: str = typer.Option("plan", "--mode", help="plan|debug|review|briefing|handoff"),
    max_tokens: int = typer.Option(6000, "--max-tokens", min=500, max=50000),
    refresh: bool = typer.Option(False, "--refresh", help="Relit explicitement les sources externes supportées"),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Construit un research packet déterministe, sourcé et freshness-aware."""
    payload = agent_context.research(query, project=project, mode=mode, max_tokens=max_tokens, refresh=refresh)
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(payload.get("context_packet_markdown", "").rstrip())


@app.command("features")
def features_cmd(
    *,
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Liste toutes les fonctionnalités zab et leurs commandes/API principales."""
    payload = catalog()
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(typer.style("zab — fonctionnalités", bold=True))
    typer.echo(typer.style(payload["positioning"], dim=True))
    typer.echo("")
    for item in payload["features"]:
        typer.echo(typer.style(f"{item['id']} [{item['category']}]", fg=typer.colors.CYAN, bold=True))
        typer.echo(f"  {item['summary']}")
        cli = item.get("cli") or []
        if cli:
            typer.echo("  CLI : " + " · ".join(str(x) for x in cli[:4]))
        api = item.get("api") or []
        if api:
            typer.echo("  API : " + " · ".join(str(x) for x in api[:4]))
        typer.echo("")


@app.command("agent-guide")
def agent_guide_cmd(
    *,
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Explique comment Claude Code, Codex ou un agent peut utiliser zab."""
    if json_out:
        typer.echo(json.dumps(agent_guide(), ensure_ascii=False, indent=2))
        return
    typer.echo(agent_guide_markdown().rstrip())


@app.command("inventory")
def inventory_cmd(
    section: str = typer.Argument(..., help="skills|connectors|tools|code-tools|models|projects|orgs|memory"),
    *,
    q: str = typer.Option("", "--q", help="Recherche simple"),
    tag: Optional[str] = typer.Option(None, "--tag", help="Filtrer par tag quand disponible"),
    installed: Optional[bool] = typer.Option(None, "--installed/--any-installed", help="Filtrer code-tools installés"),
    limit: int = typer.Option(50, "--limit", min=1, max=200),
    page: int = typer.Option(1, "--page", min=1),
    refresh: bool = typer.Option(False, "--refresh", help="Exécute zab sync avant de lire l'inventaire"),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Liste une section de l'index local-first."""
    try:
        state_section = _resolve_inventory_section(section)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e
    if refresh:
        sync_state()
    payload = list_section(state_section, page=page, limit=limit, q=q, tag=tag, installed=installed)
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(typer.style(f"Inventaire: {section}", bold=True))
    typer.echo(
        f"page {payload['pagination']['page']} · total {payload['pagination']['total']} · limit {payload['pagination']['limit']}"
    )
    for row in payload.get("data") or []:
        name = row.get("display_name") or row.get("id") or row.get("key")
        extra = row.get("path") or row.get("provider") or row.get("org") or ""
        typer.echo(f"  · {name}  {typer.style(str(extra), dim=True)}")


@app.command("inspect")
def inspect_cmd(
    section: str = typer.Argument(..., help="skills|connectors|tools|code-tools|models|projects|orgs|memory"),
    key: str = typer.Argument(..., help="Identifiant dans l'index"),
    *,
    refresh: bool = typer.Option(False, "--refresh", help="Exécute zab sync avant l'inspection"),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Affiche le détail d'un élément de l'index."""
    try:
        state_section = _resolve_inventory_section(section)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e
    if refresh:
        sync_state()
    row = get_section_item(state_section, key)
    if not row:
        typer.echo(f"élément introuvable: {section}/{key}", err=True)
        raise typer.Exit(1)
    if json_out:
        typer.echo(json.dumps(row, ensure_ascii=False, indent=2))
        return
    typer.echo(yaml.safe_dump(row, allow_unicode=True, sort_keys=False).rstrip())
    if state_section == "connectors":
        tags = row.get("tags") or []
        forms = row.get("forms") or []
        if "composio" in tags or any(str(f.get("kind", "")).lower() == "composio" for f in forms):
            slug_for_hint = str(row.get("id") or key)
            typer.echo("")
            typer.echo(typer.style("→ Connecteur Composio détecté", fg="magenta"))
            typer.echo(f"  zab composio hint {slug_for_hint}")
            typer.echo(f"  zab composio connections --toolkit {slug_for_hint} --active")


@app.command("search")
def search_cmd(
    query: str = typer.Argument("", help="Requête à chercher dans l'index zab"),
    *,
    section: Optional[list[str]] = typer.Option(None, "--section", help="Section à chercher (répétable)"),
    limit: int = typer.Option(20, "--limit", min=1, max=100),
    refresh: bool = typer.Option(False, "--refresh", help="Exécute zab sync avant la recherche"),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Recherche dans skills, projets, connecteurs, modèles, mémoire et politiques."""
    payload = agent_context.search(query, limit=limit, sections=section, refresh=refresh)
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(typer.style(f"Recherche zab: {query or '(tout)'}", bold=True))
    typer.echo(f"total {payload['total']} · limit {payload['limit']}")
    for row in payload.get("data") or []:
        name = row.get("display_name") or row.get("id") or row.get("name") or row.get("key")
        extra = row.get("path") or row.get("provider") or row.get("org") or ""
        typer.echo(f"  · [{row.get('section')}] {name}  {typer.style(str(extra), dim=True)}")


@tools_app.command("list")
def tools_list_cmd(
    *,
    q: str = typer.Option("", "--q", help="Recherche simple"),
    kind: Optional[str] = typer.Option(None, "--kind", help="Filtrer par kind"),
    status: Optional[str] = typer.Option(None, "--status", help="Filtrer par statut"),
    provider: Optional[str] = typer.Option(None, "--provider", help="Filtrer par provider"),
    limit: int = typer.Option(50, "--limit", min=1, max=200),
    page: int = typer.Option(1, "--page", min=1),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Liste le catalogue des tools actionnables Zab."""
    payload = tool_catalog.list_tools(page=page, limit=limit, q=q, kind=kind, status=status, provider=provider)
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(typer.style("Catalogue tools", bold=True))
    typer.echo(
        f"page {payload['pagination']['page']} · total {payload['pagination']['total']} · limit {payload['pagination']['limit']}"
    )
    for row in payload.get("data") or []:
        typer.echo(
            f"  · {row.get('id')}  {row.get('status')}  {row.get('primary') or '—'}"
            f"  {typer.style(str(row.get('availability_tag') or ''), dim=True)}"
        )


@tools_app.command("search")
def tools_search_cmd(
    query: str = typer.Argument(..., help="Requête à chercher dans le catalogue tools"),
    *,
    limit: int = typer.Option(20, "--limit", min=1, max=100),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Recherche les tools par intention, exemples, commandes et skills liés."""
    payload = tool_catalog.search_tools(query, limit=limit)
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(typer.style(f"Recherche tools: {query}", bold=True))
    typer.echo(f"total {payload['total']} · limit {limit}")
    for row in payload.get("data") or []:
        typer.echo(f"  · {row.get('id')}  {row.get('status')}  {row.get('label')}")


@tools_app.command("inspect")
def tools_inspect_cmd(
    tool_id: str = typer.Argument(..., help="Identifiant du tool"),
    *,
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Affiche le détail d'un tool actionnable."""
    payload = tool_catalog.get_tool(tool_id)
    if not payload:
        typer.echo(f"tool introuvable: {tool_id}", err=True)
        raise typer.Exit(1)
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False).rstrip())


@tools_app.command("validate")
def tools_validate_cmd(
    *,
    strict: bool = typer.Option(False, "--strict", help="Retourne un code erreur si les refs sont cassées"),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Valide les IDs, mots-clés, références de skills et commandes déclaratives."""
    payload = tool_catalog.validate_tools(strict=strict)
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        typer.echo(typer.style("Validation tools", bold=True))
        typer.echo(
            f"total {payload['summary']['total_tools']} · errors {payload['summary']['errors']} · warnings {payload['summary']['warnings']}"
        )
        for issue in payload.get("issues") or []:
            typer.echo(f"  · {issue.get('severity')} {issue.get('tool_id')}: {issue.get('code')} — {issue.get('message')}")
    if strict and int(payload.get("summary", {}).get("exit_status") or 0) != 0:
        raise typer.Exit(1)


@tools_app.command("check")
def tools_check_cmd(
    tool_id: Optional[str] = typer.Argument(None, help="Identifiant du tool à vérifier"),
    *,
    all: bool = typer.Option(False, "--all", help="Vérifie tous les tools"),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Teste les implementations read-only disponibles pour un tool ou tout le catalogue."""
    if all and tool_id:
        typer.echo("--all ne peut pas être combiné avec un tool_id", err=True)
        raise typer.Exit(1)
    if not all and not tool_id:
        typer.echo("précisez un tool_id ou utilisez --all", err=True)
        raise typer.Exit(1)
    payload = tool_checks.check_tools() if all else tool_checks.check_tool(str(tool_id or ""))
    if not payload:
        typer.echo("tool introuvable", err=True)
        raise typer.Exit(1)
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if all:
        typer.echo(typer.style("Checks tools", bold=True))
        typer.echo(
            f"total {payload['summary']['total']} · ok {payload['summary']['ok']} · warn {payload['summary']['warn']} · fail {payload['summary']['fail']}"
        )
        for row in payload.get("tools") or []:
            typer.echo(f"  · {row.get('tool_id')}  {row.get('status')}  {row.get('status_reason') or ''}")
    else:
        typer.echo(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False).rstrip())


@skill_app.command("new")
def skill_new_cmd(
    name: str = typer.Argument(..., help="Slug de la skill ([a-z0-9-])"),
    *,
    org: Optional[str] = typer.Option(None, "--org", help="Organisation logique (défaut: common)"),
    description: str = typer.Option("", "--description", "-d", help="Description courte pour le frontmatter"),
    force: bool = typer.Option(False, "--force", "-f", help="Remplacer un SKILL.md existant"),
    sync: bool = typer.Option(False, "--sync", help="Créer un commit local après création"),
    push: bool = typer.Option(False, "--push", help="Pousser vers origin après commit"),
    hermes_update: bool = typer.Option(False, "--hermes-update", help="Mettre à jour ~/.hermes/config.yaml après création"),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Scaffold un nouveau SKILL.md global dans le dépôt de skills configuré."""

    try:
        result = create_skill(name, org=org, description=description, force=force)
        settings = skills_sync_settings()
        sync_result = None
        if sync or (settings.get("auto_sync") and not push):
            sync_result = commit_and_push(
                result["repo_root"],
                f"skill: add {result['org']}/{result['id']}",
                paths=[result["path"]],
                push=push,
            )
        elif push:
            ensure_remote_origin(result["repo_root"], str(settings["git_remote"]))
            sync_result = commit_and_push(
                result["repo_root"],
                f"skill: add {result['org']}/{result['id']}",
                paths=[result["path"]],
                push=True,
            )
        hermes_result = None
        if hermes_update or settings.get("auto_hermes_update"):
            hermes_result = update_external_dirs(repo_root=result["repo_root"], apply=True)
    except (SkillScaffoldError, ValueError) as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e
    payload = {
        "skill": result,
        "git": sync_result.__dict__ if sync_result is not None else None,
        "hermes": hermes_result.__dict__ if hermes_result is not None else None,
    }
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(typer.style("Skill créée", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"  path : {result['path']}")
    if sync_result:
        typer.echo(f"  git  : committed={sync_result.committed} pushed={sync_result.pushed}")
        if sync_result.error:
            typer.echo(typer.style(f"         warning: {sync_result.error}", fg=typer.colors.YELLOW))
    if hermes_result:
        typer.echo(f"  hermes: changed={hermes_result.changed} config={hermes_result.config_path}")


@skill_app.command("new-global")
def skill_new_global_cmd(
    name: str = typer.Argument(..., help="Slug de la skill globale ([a-z0-9-])"),
    *,
    org: Optional[str] = typer.Option(None, "--org", help="Organisation logique (défaut: common)"),
    description: str = typer.Option("", "--description", "-d", help="Description courte pour le frontmatter"),
    force: bool = typer.Option(False, "--force", "-f", help="Remplacer un SKILL.md existant"),
    sync: bool = typer.Option(False, "--sync", help="Créer un commit local après création"),
    push: bool = typer.Option(False, "--push", help="Pousser vers origin après commit"),
    hermes_update: bool = typer.Option(False, "--hermes-update", help="Mettre à jour ~/.hermes/config.yaml après création"),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Alias explicite de `skill new` pour créer une skill globale, pas projet."""

    try:
        result = create_global_skill(name, org=org, description=description, force=force)
        settings = skills_sync_settings()
        sync_result = None
        if sync or (settings.get("auto_sync") and not push):
            sync_result = commit_and_push(
                result["repo_root"],
                f"skill: add {result['org']}/{result['id']}",
                paths=[result["path"]],
                push=push,
            )
        elif push:
            ensure_remote_origin(result["repo_root"], str(settings["git_remote"]))
            sync_result = commit_and_push(
                result["repo_root"],
                f"skill: add {result['org']}/{result['id']}",
                paths=[result["path"]],
                push=True,
            )
        hermes_result = None
        if hermes_update or settings.get("auto_hermes_update"):
            hermes_result = update_external_dirs(repo_root=result["repo_root"], apply=True)
    except (SkillScaffoldError, ValueError) as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e
    payload = {
        "skill": result,
        "git": sync_result.__dict__ if sync_result is not None else None,
        "hermes": hermes_result.__dict__ if hermes_result is not None else None,
    }
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(typer.style("Skill globale créée", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"  path : {result['path']}")
    if sync_result:
        typer.echo(f"  git  : committed={sync_result.committed} pushed={sync_result.pushed}")
        if sync_result.error:
            typer.echo(typer.style(f"         warning: {sync_result.error}", fg=typer.colors.YELLOW))
    if hermes_result:
        typer.echo(f"  hermes: changed={hermes_result.changed} config={hermes_result.config_path}")


@skill_app.command("list")
def skill_list_cmd(
    *,
    org: Optional[str] = typer.Option(None, "--org", help="Filtrer par organisation"),
    project: Optional[str] = typer.Option(None, "--project", help="Filtrer par projet/source"),
    query: Optional[str] = typer.Option(None, "--query", "-q", help="Filtrer par texte"),
    limit: int = typer.Option(200, "--limit", min=1, max=500),
    refresh: bool = typer.Option(False, "--refresh", help="Exécute zab sync avant de lire"),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Liste les skills sous forme de manifeste agent-compatible."""

    payload = agent_context.skills_manifest(org=org, project=project, query=query, limit=limit, refresh=refresh)
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(typer.style(f"Skills disponibles: {payload['total']}", bold=True))
    for row in payload.get("skills") or []:
        typer.echo(f"  · {row.get('key')}  {typer.style(str(row.get('path') or ''), dim=True)}")


@skill_app.command("sync")
def skill_sync_cmd(
    *,
    push: bool = typer.Option(False, "--push", help="Pousser vers origin après commit"),
    message: str = typer.Option("skill: sync", "--message", "-m", help="Message de commit"),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Commit local explicite du dépôt de skills, push seulement avec --push."""

    settings = skills_sync_settings()
    ensure_repo_initialized(str(settings["repo_root"]))
    if push:
        ensure_remote_origin(str(settings["repo_root"]), str(settings["git_remote"]))
    result = commit_and_push(str(settings["repo_root"]), message, push=push)
    if json_out:
        typer.echo(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
        return
    typer.echo(f"repo={result.repo_root} committed={result.committed} pushed={result.pushed}")
    if result.error:
        typer.echo(typer.style(result.error, fg=typer.colors.YELLOW))


@skill_app.command("hermes-update")
def skill_hermes_update_cmd(
    *,
    apply: bool = typer.Option(False, "--apply", help="Écrit la config Hermes (sinon dry-run)"),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Met à jour `skills.external_dirs` dans la config Hermes."""

    result = update_external_dirs(apply=apply)
    if json_out:
        typer.echo(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
        return
    mode = "apply" if apply else "dry-run"
    typer.echo(typer.style(f"Hermes skills.external_dirs ({mode})", bold=True))
    typer.echo(f"  config  : {result.config_path}")
    typer.echo(f"  changed : {result.changed}")
    for path in result.external_dirs:
        typer.echo(f"  · {path}")


@skill_app.command("broadcast")
def skill_broadcast_cmd(
    *,
    apply: bool = typer.Option(False, "--apply", help="Écrit les changements (sinon dry-run)"),
    targets: str = typer.Option(
        "claude,kimi",
        "--targets",
        help="Cibles séparées par virgule. Supportées : claude, kimi.",
    ),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Diffuse l'inventaire de skills (Hermes + external_dirs) vers d'autres CLIs."""

    parsed_targets = [t.strip() for t in targets.split(",") if t.strip()]
    valid = {"claude", "kimi"}
    unknown = [t for t in parsed_targets if t not in valid]
    if unknown:
        typer.echo(
            typer.style(
                f"Cibles inconnues: {', '.join(unknown)}. Valides : {', '.join(sorted(valid))}.",
                fg=typer.colors.RED,
            ),
            err=True,
        )
        raise typer.Exit(code=2)

    result = skills_broadcast.broadcast(targets=parsed_targets, dry_run=not apply)
    if json_out:
        typer.echo(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
        return

    mode = "apply" if apply else "dry-run"
    typer.echo(typer.style(f"Skills broadcast ({mode})", bold=True))
    typer.echo(f"  roots ({len(result.roots)}):")
    for r in result.roots:
        typer.echo(f"    · {r}")
    typer.echo(f"  skills découverts : {result.skill_count}")
    for tname, tres in result.targets.items():
        typer.echo(typer.style(f"  → {tname}", bold=True))
        if tname == "claude":
            typer.echo(f"      dir            : {tres['skills_dir']}")
            typer.echo(f"      créés          : {len(tres['created'])}")
            typer.echo(f"      mis à jour     : {len(tres['updated'])}")
            typer.echo(f"      supprimés      : {len(tres['removed'])}")
            typer.echo(f"      skip existant  : {len(tres['skipped_existing'])}")
            typer.echo(f"      total managés  : {tres['total_managed']}/{tres['total_desired']}")
        elif tname == "kimi":
            typer.echo(f"      config         : {tres['config_path']}")
            typer.echo(f"      changed        : {tres['changed']}")
            typer.echo(f"      extra_skill_dirs ({len(tres['extra_skill_dirs'])}):")
            for p in tres["extra_skill_dirs"]:
                typer.echo(f"        · {p}")


@app.command()
def scan(
    *,
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON (machine)"),
    root: Optional[str] = typer.Option(None, "--root", help="Sous-chemin sous ~ (HOME), ou chemin absolu contenu dans ~"),
    dir_path: Optional[str] = typer.Option(
        None,
        "--dir",
        help="Dossier quelconque à scanner (SKILL.md + CLIs + Agentpipe/Codexbar)",
    ),
    persist: bool = typer.Option(False, "--persist", help="Enregistrer le rapport dans ~/.local/share/zab/scan-last.yaml"),
) -> None:
    """Scan SKILL.md, CLIs, Agentpipe/Codexbar ; rafraîchit skills-registry.json (sauf --json)."""
    allow_any = bool(dir_path and str(dir_path).strip())
    scan_root_opt = Path(dir_path).expanduser() if allow_any else resolve_optional_scan_root(root)
    report = workspace_scan(scan_root_opt, allow_any_path=allow_any)

    if json_out:
        typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
        return

    for w in report.get("warnings") or []:
        typer.echo(typer.style(w, fg=typer.colors.YELLOW))

    typer.echo(f"Répertoire ~     : {report.get('user_home', '')}")
    typer.echo(f"Dépôt skills ref : {report['skills_root']}")
    typer.echo(f"Scan depuis      : {report['scan_root_resolved']}")
    typer.echo(f"Nb SKILL.md      : {report['skill_md_count']}")

    skills = report.get("skill_md_files") or []
    preview = skills[:60]
    for row in preview:
        typer.echo(f"  · {row['path']}")
    if len(skills) > len(preview):
        typer.echo(f"  … ({len(skills) - len(preview)} supplémentaires)")

    clis = report.get("clis") or {}
    zab_cmds = clis.get("zab_commands") or []
    typer.echo("Commandes zab    :")
    for c in zab_cmds[:30]:
        typer.echo(f"  · {c.get('name', '')}")

    scripts = clis.get("repo_scripts") or []
    typer.echo(f"Scripts repo     : {len(scripts)}")

    ap = report.get("agentpipe") or {}
    ap_cli = ap.get("cli_agentpipe_binary")
    typer.echo(
        f"Agentpipe        : présent={'oui' if ap.get('present') else 'non'} ({ap.get('path', '')})"
        + (f"\n  binaire agentpipe: {ap_cli}" if ap_cli else "\n  binaire agentpipe: (absent du PATH)")
    )
    nt = ap.get("agents_total")
    no = ap.get("agents_on_path")
    if isinstance(nt, int):
        typer.echo(f"  agents déclarés/sur PATH : {nt} / {no if isinstance(no, int) else '—'}")
    for agent in ap.get("agents") or []:
        state = typer.style("PATH", fg=typer.colors.GREEN) if agent.get("on_path") else "absent"
        typer.echo(f"  · {agent.get('id')} [{state}] probe={agent.get('probe_binary')}")

    cb = report.get("codexbar") or {}
    cb_cli = cb.get("cli_codexbar_binary")
    typer.echo(
        f"Codexbar JSON    : présent={'oui' if cb.get('present') else 'non'} ({cb.get('path', '')})"
        + (f"\n  binaire codexbar: {cb_cli}" if cb_cli else "\n  binaire codexbar: (absent du PATH)")
    )

    if not persist:
        typer.echo("")
        typer.echo(
            typer.style(
                "ℹ Ce scan n’écrit pas config.yaml. Lancez « zab sync » pour régénérer l’index Postgres.",
                fg=typer.colors.CYAN,
            )
        )
        typer.echo(
            typer.style("  Persistez le rapport : ", dim=True) + typer.style("zab scan --persist", fg=typer.colors.GREEN)
        )
        typer.echo(
            typer.style(
                "  Pour ne scanner qu’un dépôt : ajoutez --dir ~/chemin/vers/le/repo",
                dim=True,
            )
        )

    if persist:
        p_saved = persist_workspace_scan(report)
        typer.echo(typer.style(f"\nScan persisté : {p_saved}", fg=typer.colors.GREEN))

    try:
        info = skills_registry.refresh_registry_from_disk()
        typer.echo(
            typer.style(
                f"\nRegistre skills : {info.get('skills_count', 0)} entrée(s) — {info.get('registry_path', '')}",
                dim=True,
            )
        )
    except Exception as exc:
        typer.echo(typer.style(f"refresh skills-registry: {exc}", fg=typer.colors.YELLOW), err=True)


@skill_app.command("adopt")
def skill_adopt_cmd(
    key: str = typer.Argument(..., help="Clé registre (ex. flowmetrik:ma-skill)"),
    *,
    canonical: Optional[str] = typer.Option(None, "--canonical", help="Chemin SKILL.md canonique (optionnel)"),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON"),
) -> None:
    """Marque une skill comme adoptée dans skills-registry.json."""
    out = skills_registry.adopt_registry_key(key, canonical_path=canonical)
    if json_out:
        typer.echo(json.dumps(out, ensure_ascii=False, indent=2))
        return
    if not out.get("ok"):
        typer.echo(typer.style(str(out.get("error")), fg=typer.colors.RED), err=True)
        raise typer.Exit(1)
    typer.echo(typer.style("OK", fg=typer.colors.GREEN))


@skill_app.command("unadopt")
def skill_unadopt_cmd(
    key: str = typer.Argument(..., help="Clé registre"),
    *,
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON"),
) -> None:
    out = skills_registry.unadopt_registry_key(key)
    if json_out:
        typer.echo(json.dumps(out, ensure_ascii=False, indent=2))
        return
    if not out.get("ok"):
        typer.echo(typer.style(str(out.get("error")), fg=typer.colors.RED), err=True)
        raise typer.Exit(1)
    typer.echo(typer.style("OK", fg=typer.colors.GREEN))


@skill_app.command("ignore")
def skill_ignore_cmd(
    key: str = typer.Argument(..., help="Clé registre"),
    *,
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON"),
) -> None:
    out = skills_registry.ignore_registry_key(key)
    if json_out:
        typer.echo(json.dumps(out, ensure_ascii=False, indent=2))
        return
    if not out.get("ok"):
        typer.echo(typer.style(str(out.get("error")), fg=typer.colors.RED), err=True)
        raise typer.Exit(1)
    typer.echo(typer.style("OK", fg=typer.colors.GREEN))


@skill_app.command("unignore")
def skill_unignore_cmd(
    key: str = typer.Argument(..., help="Clé registre"),
    *,
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON"),
) -> None:
    out = skills_registry.unignore_registry_key(key)
    if json_out:
        typer.echo(json.dumps(out, ensure_ascii=False, indent=2))
        return
    if not out.get("ok"):
        typer.echo(typer.style(str(out.get("error")), fg=typer.colors.RED), err=True)
        raise typer.Exit(1)
    typer.echo(typer.style("OK", fg=typer.colors.GREEN))


@skill_app.command("resolve-conflict")
def skill_resolve_conflict_cmd(
    key: str = typer.Argument(..., help="Clé registre"),
    keep: str = typer.Option(..., "--keep", help="Chemin absolu du SKILL.md à conserver"),
    *,
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON"),
) -> None:
    out = skills_registry.resolve_conflict_keep_path(key, keep)
    if json_out:
        typer.echo(json.dumps(out, ensure_ascii=False, indent=2))
        return
    if not out.get("ok"):
        typer.echo(typer.style(str(out.get("error")), fg=typer.colors.RED), err=True)
        raise typer.Exit(1)
    typer.echo(typer.style("OK", fg=typer.colors.GREEN))


@skill_app.command("registry-show")
def skill_registry_show_cmd(
    *,
    status: Optional[str] = typer.Option(None, "--status", help="Filtrer par statut registre"),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON"),
) -> None:
    rows = skills_registry.query_registry(status=status)
    if json_out:
        typer.echo(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    for r in rows:
        typer.echo(f"{r.get('key')} [{r.get('status')}] {r.get('canonical_path') or ''}")


@skill_app.command("hermes-export")
def skill_hermes_export_cmd(
    *,
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON (fragment YAML en champ text)"),
) -> None:
    text = skills_registry.hermes_export_yaml_fragment()
    if json_out:
        typer.echo(json.dumps({"yaml": text}, ensure_ascii=False, indent=2))
        return
    typer.echo(text)


def _parse_mcp_target(raw: str) -> McpTarget:
    t = raw.strip().lower().replace("-", "_")
    if t in ("cursor",):
        return "cursor"
    if t in ("desktop", "claude", "claude_desktop"):
        return "desktop"
    raise ValueError(f"cible MCP inconnue : {raw!r} — utiliser cursor ou desktop")


@add_app.command("mcp")
def add_mcp_cmd(
    name: str = typer.Argument(..., help="Nom du serveur (clé dans mcpServers)"),
    target: str = typer.Option("cursor", "--target", "-t", help="cursor ou desktop (claude-desktop-mcp.json)"),
    url: Optional[str] = typer.Option(None, "--url", help="URL du serveur MCP (HTTP)"),
    command: Optional[str] = typer.Option(None, "--command", "-c", help="Commande stdio (ex. npx)"),
    args: Optional[str] = typer.Option(None, "--args", help="Arguments (quoting shell, ex. -y @scope/mcp)"),
    env: list[str] = typer.Option([], "--env", "-e", help="KEY=value pour le bloc env (stdio)"),
    force: bool = typer.Option(False, "--force", "-f", help="Remplacer une entrée existante"),
) -> None:
    """Ajoute une entrée dans configs/cursor-mcp.json ou claude-desktop-mcp.json du dépôt skills."""
    try:
        mcp_target = _parse_mcp_target(target)
        env_map = parse_env_flags(env) if env else None
        arg_list = parse_args_option(args)
        path = add_mcp_server(
            target=mcp_target,
            name=name,
            url=url,
            command=command,
            args=arg_list,
            env_pairs=env_map,
            force=force,
        )
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e
    typer.echo(f"Écrit : {path}")


@mempalace_app.command("doctor")
def mempalace_doctor_cmd(
    *,
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Vérifie mempalace et mempalace-mcp sur le PATH ; chemins des JSON MCP du dépôt skills."""
    payload = mempalace_mcp_snippet.doctor_payload(skills_configs_dir=configs_dir())
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(typer.style("MemPalace (CLI + MCP)", bold=True))
    typer.echo("")
    mp = payload["mempalace"]
    typer.echo(f"  [{'OK' if mp['on_path'] else '!!'}] mempalace: {mp.get('which') or 'absent'}")
    if mp.get("version_line"):
        typer.echo(typer.style(f"      {mp['version_line']}", dim=True))
    mcp = payload["mempalace_mcp"]
    typer.echo(f"  [{'OK' if mcp['on_path'] else '!!'}] mempalace-mcp: {mcp.get('which') or 'absent'}")
    if mcp.get("help_head"):
        typer.echo(typer.style(f"      {mcp['help_head']}", dim=True))
    paths = payload.get("mcp_config_paths") or {}
    if paths:
        typer.echo("")
        typer.echo(typer.style("  Fichiers MCP (dépôt skills, fusion sous mcpServers)", dim=True))
        typer.echo(f"    cursor          : {paths.get('cursor', '')}")
        typer.echo(f"    claude_desktop  : {paths.get('claude_desktop', '')}")
    typer.echo("")
    typer.echo(
        typer.style(
            "  Claude Code (hors JSON Cursor) : exécutez `mempalace mcp` pour la ligne `claude mcp add …`.",
            dim=True,
        )
    )


@mempalace_app.command("mcp-json")
def mempalace_mcp_json_cmd(
    *,
    palace: Optional[str] = typer.Option(None, "--palace", help="Répertoire palace explicite"),
    server_name: str = typer.Option("mempalace", "--name", "-n", help="Clé dans mcpServers"),
    target: str = typer.Option(
        "cursor",
        "--target",
        "-t",
        help="cursor ou desktop — indique le fichier JSON cible (rappel après le JSON)",
    ),
    paths_only: bool = typer.Option(False, "--paths", "-p", help="Afficher uniquement les chemins des JSON MCP skills"),
) -> None:
    """Affiche un document JSON { \"mcpServers\": { … } } pour fusion manuelle ou revue."""
    if paths_only:
        try:
            mt = _parse_mcp_target(target)
        except ValueError as e:
            typer.echo(str(e), err=True)
            raise typer.Exit(1) from e
        typer.echo(str(resolve_mcp_json_path(mt)))
        return
    try:
        text = mempalace_mcp_snippet.format_mcp_servers_json(server_name=server_name, palace=palace)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e
    typer.echo(text, nl=False)
    try:
        mt = _parse_mcp_target(target)
        hint_path = resolve_mcp_json_path(mt)
        typer.echo(typer.style(f"# Fusionner sous « mcpServers » dans : {hint_path}", dim=True))
    except ValueError:
        pass


@mempalace_app.command("mcp-install")
def mempalace_mcp_install_cmd(
    *,
    target: str = typer.Option("cursor", "--target", "-t", help="cursor ou desktop (claude-desktop-mcp.json)"),
    name: str = typer.Option("mempalace", "--name", "-n", help="Clé dans mcpServers"),
    palace: Optional[str] = typer.Option(None, "--palace", help="Répertoire palace explicite"),
    force: bool = typer.Option(False, "--force", "-f", help="Remplacer une entrée existante"),
) -> None:
    """Enregistre mempalace-mcp dans configs/cursor-mcp.json ou claude-desktop-mcp.json du dépôt skills."""
    try:
        mcp_target = _parse_mcp_target(target)
        block = mempalace_mcp_snippet.build_mcp_server_entry(palace=palace)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e
    try:
        path = add_mcp_server(
            target=mcp_target,
            name=name,
            url=None,
            command=block["command"],
            args=block.get("args"),
            env_pairs=None,
            force=force,
        )
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e
    typer.echo(f"Écrit : {path}")


@memory_app.command("sync-agents")
def memory_sync_agents_cmd(
    *,
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Collecte et compte sans écrire dans Postgres"),
    append: bool = typer.Option(False, "--append", help="Ne supprime pas les anciens documents agents avant import"),
    batch_id: str = typer.Option("agent-conversations-local", "--batch-id", help="export_batch_id écrit en base"),
) -> None:
    """Synchronise Cursor/Claude/Codex/Kimi/Hermes/Gemini CLI (conversations + plans/rules/skills) vers Postgres."""
    from zab.services.agent_memory_import import sync_agent_memory_to_postgres

    try:
        summary = sync_agent_memory_to_postgres(
            replace=not append,
            batch_id=batch_id,
            dry_run=dry_run,
        )
    except RuntimeError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e
    if json_out:
        typer.echo(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    typer.echo(typer.style("Mémoire agents synchronisée", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"  Batch       : {summary['batch_id']}")
    typer.echo(f"  Dry-run     : {summary['dry_run']}")
    typer.echo(f"  Replace     : {summary['replace']}")
    typer.echo(f"  Collectés   : {summary['documents_collected']} docs / {summary['chunks_collected']} chunks")
    typer.echo(f"  Supprimés   : {summary['deleted_previous_documents']}")
    typer.echo(f"  Insérés     : {summary['inserted_documents']} docs / {summary['inserted_chunks']} chunks")
    typer.echo("  Sources     :")
    for source, n in sorted(summary["source_counts"].items()):
        typer.echo(f"    - {source}: {n}")


@conversations_app.command("sync")
def conversations_sync_cmd(
    *,
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON (résumé final)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Compte sans écrire en base"),
    append: bool = typer.Option(False, "--append", help="Ne pas supprimer les documents des providers ciblés avant import"),
    with_mempalace: bool = typer.Option(False, "--with-mempalace", help="Lancer MemPalace conversations après Postgres"),
    workspace_storage_cursor: bool = typer.Option(
        False,
        "--workspace-storage-cursor",
        help="Non supporté (refusé)",
    ),
    providers: str = typer.Option(
        "",
        "--providers",
        help="Liste virgule : cursor,claude,codex,kimi,hermes,gemini",
    ),
    batch_id: str = typer.Option("agent-conversations-local", "--batch-id"),
) -> None:
    """Synchronise les conversations locales (Cursor, Claude, Codex, Kimi, Hermes, Gemini CLI) vers Postgres."""
    from zab.services.conversation_sync import run_sync

    prov_list = [p.strip() for p in providers.split(",") if p.strip()] or None
    try:
        summary = run_sync(
            dry_run=dry_run,
            append=append,
            with_mempalace=with_mempalace,
            workspace_storage_cursor=workspace_storage_cursor,
            providers=prov_list,
            batch_id=batch_id,
        )
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(2) from e
    except RuntimeError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e
    except Exception as e:  # noqa: BLE001
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e
    if json_out:
        typer.echo(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    typer.echo(typer.style("Synchronisation conversations terminée", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"  Dry-run     : {summary.get('dry_run')}")
    typer.echo(f"  Collectés   : {summary.get('documents_collected')} docs / {summary.get('chunks_collected')} chunks")
    typer.echo(f"  Insérés     : {summary.get('inserted_documents')} docs / {summary.get('inserted_chunks')} chunks")


@conversations_app.command("digest")
def conversations_digest_cmd(
    *,
    days: int = typer.Option(1, "--days", min=1, max=14, help="Fenetre locale en jours"),
    providers: str = typer.Option(
        "",
        "--providers",
        help="Liste virgule : cursor,claude,codex,kimi,hermes,gemini",
    ),
    limit: int = typer.Option(80, "--limit", min=1, max=300, help="Nombre maximal d'items affiches"),
    include_subagents: bool = typer.Option(False, "--include-subagents", help="Inclure les conversations de subagents"),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Digest local des conversations recentes, annote avec projets/orgs Zab."""
    from zab.services.conversation_digest import build_conversation_digest, format_conversation_digest_markdown
    from zab.services.conversations import parse_providers_arg

    prov_list = [p.strip() for p in providers.split(",") if p.strip()] or None
    try:
        prov_set = parse_providers_arg(prov_list)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(2) from e

    payload = build_conversation_digest(
        days=days,
        providers=prov_set,
        limit=limit,
        include_subagents=include_subagents,
    )
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(format_conversation_digest_markdown(payload).rstrip())


@conversations_app.command("obsidian-daily")
def conversations_obsidian_daily_cmd(
    *,
    date: Optional[str] = typer.Option(None, "--date", help="Jour local YYYY-MM-DD a traiter"),
    yesterday: bool = typer.Option(False, "--yesterday", help="Traiter la veille dans le fuseau donne"),
    timezone_name: str = typer.Option("Europe/Paris", "--timezone", help="Fuseau pour la journee locale"),
    providers: str = typer.Option(
        "",
        "--providers",
        help="Liste virgule : cursor,claude,codex,kimi,hermes,gemini",
    ),
    limit: int = typer.Option(200, "--limit", min=1, max=300, help="Nombre maximal de conversations detaillees"),
    batch_size: int = typer.Option(10, "--batch-size", min=1, max=50, help="Taille des paquets d'analyse locale"),
    include_subagents: bool = typer.Option(False, "--include-subagents", help="Inclure les conversations de subagents"),
    once_per_day: bool = typer.Option(False, "--once-per-day", help="No-op si la date cible a deja ete ecrite"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Construit le resultat sans ecrire dans Obsidian"),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour hooks/scripts"),
) -> None:
    """Ecrit le digest des conversations de la veille dans Obsidian."""
    from datetime import date as date_cls

    from zab.services.conversation_obsidian_daily import (
        write_obsidian_conversation_digest,
        yesterday_in_timezone,
    )
    from zab.services.conversations import parse_providers_arg

    prov_list = [p.strip() for p in providers.split(",") if p.strip()] or None
    try:
        prov_set = parse_providers_arg(prov_list)
        target_date = date_cls.fromisoformat(date) if date else None
        if target_date is None:
            target_date = yesterday_in_timezone(timezone_name)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(2) from e

    result = write_obsidian_conversation_digest(
        target_date=target_date,
        timezone_name=timezone_name,
        providers=prov_set,
        limit=limit,
        batch_size=batch_size,
        include_subagents=include_subagents,
        once_per_day=once_per_day,
        dry_run=dry_run,
    )
    if json_out:
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return
    status = str(result.get("status") or "?")
    typer.echo(typer.style(f"Digest Obsidian conversations : {status}", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"  Date          : {result.get('target_date')}")
    typer.echo(f"  Conversations : {result.get('shown_conversations', 0)}")
    typer.echo(f"  Providers     : {result.get('provider_counts', {})}")
    if result.get("detail_abs"):
        typer.echo(f"  Detail        : {result.get('detail_abs')}")
    if result.get("daily_abs"):
        typer.echo(f"  Daily         : {result.get('daily_abs')}")


@memory_app.command("search")
def memory_search_cmd(
    query: str = typer.Argument(..., help="Texte à chercher dans la mémoire Postgres"),
    *,
    limit: int = typer.Option(10, "--limit", "-n", min=1, max=50, help="Nombre de chunks retournés"),
    source: Optional[str] = typer.Option(None, "--source", help="Filtrer sur une source exacte"),
    wing: Optional[str] = typer.Option(None, "--wing", help="Filtrer sur un wing (match partiel)"),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Recherche dans la mémoire Postgres (conversations Cursor/Claude/Codex/Kimi, artefacts agents)."""
    from zab.services.memory_db import fetch_status, search_memory

    results = search_memory(query, limit=limit, source=source, wing=wing)
    status = fetch_status() if not results else None
    if json_out:
        typer.echo(
            json.dumps({"query": query, "results": results, "status": status}, ensure_ascii=False, indent=2)
        )
        return
    if not results:
        if status and not status.get("connected"):
            typer.echo(status.get("error") or "Mémoire Postgres indisponible.", err=True)
            raise typer.Exit(1)
        typer.echo("Aucun résultat.")
        return
    typer.echo(typer.style(f"Résultats mémoire pour « {query} »", bold=True))
    for i, r in enumerate(results, 1):
        typer.echo("")
        typer.echo(
            typer.style(f"[{i}] {r['source']}  {r.get('wing') or '—'} / {r.get('room') or '—'}", fg=typer.colors.CYAN)
        )
        typer.echo(typer.style(f"    document_id={r['document_id']} chunk={r['chunk_index']}", dim=True))
        if r.get("path"):
            typer.echo(typer.style(f"    path={r['path']}", dim=True))
        excerpt = str(r.get("content_excerpt") or "").replace("\n", " ")
        typer.echo(f"    {excerpt[:1000]}")


@memory_app.command("show")
def memory_show_cmd(
    document_id: str = typer.Argument(..., help="UUID du document mémoire"),
    *,
    chunk_limit: int = typer.Option(20, "--chunks", min=1, max=500, help="Nombre de chunks à afficher"),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Affiche un document mémoire et ses chunks."""
    from zab.services.memory_db import fetch_document_detail

    doc = fetch_document_detail(document_id, chunk_limit=chunk_limit)
    if doc is None:
        typer.echo("Document introuvable.", err=True)
        raise typer.Exit(1)
    if json_out:
        typer.echo(json.dumps({"document": doc}, ensure_ascii=False, indent=2))
        return
    typer.echo(typer.style(f"Document mémoire {doc['id']}", bold=True))
    typer.echo(f"  source : {doc['source']}")
    typer.echo(f"  wing   : {doc.get('wing') or '—'}")
    typer.echo(f"  room   : {doc.get('room') or '—'}")
    typer.echo(f"  path   : {doc.get('path') or '—'}")
    typer.echo("")
    for chunk in doc.get("chunks") or []:
        typer.echo(typer.style(f"--- chunk {chunk['chunk_index']} ---", fg=typer.colors.CYAN))
        typer.echo(str(chunk.get("content") or "").rstrip())
        typer.echo("")


@add_app.command("cli")
def add_cli_cmd(
    binary: str = typer.Argument(..., help="Nom du binaire (ex. gh)"),
    where: str = typer.Option(
        "local",
        "--where",
        "-w",
        help="local → local-tools.yaml ; config → ~/.config/zab/config.yaml",
    ),
) -> None:
    """Ajoute un binaire à cli_watchlist (scan which)."""
    w = where.strip().lower()
    try:
        if w in ("local", "local_tools", "yaml", "tools"):
            path = add_cli_watchlist(binary, where="local_tools")
        elif w in ("config", "user", "user_config", "global"):
            path = add_cli_watchlist(binary, where="user_config")
        else:
            typer.echo(f"Valeur --where inconnue : {where} (local ou config)", err=True)
            raise typer.Exit(code=1)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e
    typer.echo(f"Écrit : {path}")


@add_app.command("api")
def add_api_cmd(
    key: str = typer.Argument(..., help="Identifiant du proxy (ex. litellm)"),
    base_url: str = typer.Option(..., "--url", "-u", help="URL de base de l'API"),
    api_key_env: Optional[str] = typer.Option(None, "--key-env", help="Variable d'environnement pour la clé API"),
) -> None:
    """Ajoute une entrée proxies.* dans local-tools.yaml."""
    try:
        path = add_api_proxy(key, base_url, api_key_env)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e
    typer.echo(f"Écrit : {path}")


@add_app.command("env")
def add_env_cmd(
    name: str = typer.Argument(..., help="Nom de variable (ex. MY_SERVICE_TOKEN)"),
) -> None:
    """Enregistre une variable supplémentaire suivie dans l'onglet Sécurité (merged avec le catalogue zab)."""
    try:
        path = add_tracked_env(name)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e
    typer.echo(f"Écrit tracked_env_extra dans : {path}")


@add_app.command("skill")
def add_skill_cmd(
    name: str = typer.Argument(..., help="Slug de la skill à créer"),
    *,
    description: str = typer.Option("", "--description", "-d", help="Description courte"),
    project: Optional[str] = typer.Option(None, "--project", help="Chemin du projet si skill locale"),
    org: Optional[str] = typer.Option(None, "--org", help="Organisation pour skill globale"),
    global_scope: bool = typer.Option(False, "--global", help="Forcer placement global"),
    project_scope: bool = typer.Option(False, "--project-scope", help="Forcer placement projet"),
    ai_route: bool = typer.Option(False, "--ai-route", help="Laisser une IA locale choisir global vs projet"),
    sync_github: bool = typer.Option(False, "--sync-github", help="Commit/push si la skill est globale"),
    force: bool = typer.Option(False, "--force", "-f", help="Remplacer un SKILL.md existant"),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Crée une skill en choisissant explicitement ou via IA entre projet et global."""

    if global_scope and project_scope:
        typer.echo("--global et --project-scope sont incompatibles", err=True)
        raise typer.Exit(1)
    try:
        if global_scope:
            placement = choose_skill_placement(name, description, org=org, use_ai=False)
            placement.scope = "global"
            placement.org = org or placement.org or "common"
        elif project_scope:
            if not project:
                typer.echo("--project est requis avec --project-scope", err=True)
                raise typer.Exit(1)
            placement = choose_skill_placement(name, description, project_path=project, org=org, use_ai=False)
            placement.scope = "project"
        else:
            placement = choose_skill_placement(name, description, project_path=project, org=org, use_ai=ai_route)

        if placement.scope == "project":
            if not placement.project_path:
                typer.echo("Aucun projet cible pour une skill projet", err=True)
                raise typer.Exit(1)
            result = create_project_skill(name, project_path=placement.project_path, description=description, force=force)
            git_result = None
            register_path = None
        else:
            result = create_global_skill(name, org=placement.org, description=description, force=force)
            register_path = skills_registry.register_mirror_skill_path(result["path"])
            git_result = None
            if sync_github:
                settings = skills_sync_settings()
                ensure_remote_origin(result["repo_root"], str(settings["git_remote"]))
                git_result = commit_and_push(
                    result["repo_root"],
                    f"skill: add {result['org']}/{result['id']}",
                    paths=[result["path"]],
                    push=True,
                )
        sync_state()
    except (SkillScaffoldError, ValueError) as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e
    payload = {
        "skill": result,
        "placement": placement.__dict__,
        "registered_config": str(register_path) if register_path else None,
        "git": git_result.__dict__ if git_result else None,
    }
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(typer.style(f"Skill {placement.scope} créée", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"  path : {result['path']}")
    typer.echo(f"  reason: {placement.reason}")
    if git_result:
        typer.echo(f"  git  : committed={git_result.committed} pushed={git_result.pushed}")


@pm_env_app.command("sync")
def pm_env_sync_cmd(
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Remplace les jetons dans ~/.config/zab/.env même s’ils sont déjà renseignés",
    ),
) -> None:
    """Scanne projects_roots (+ skills/.env) et écrit GITLAB_TOKEN / LINEAR_API_KEY / NOTION_TOKEN dans ~/.config/zab/.env."""
    summary = sync_pm_tokens_to_user_dotenv(force=force)
    typer.echo(typer.style("Fusion ~/.config/zab/.env", bold=True))
    typer.echo(f"  Fichier : {summary['path']}")
    typer.echo(f"  Fichiers .env candidats lus : {summary['scanned_env_files']}")
    typer.echo(f"  Clés trouvées au scan : {', '.join(summary['keys_found_by_scan']) or '(aucune)'}")
    typer.echo(f"  Clés écrites / mises à jour : {', '.join(summary['keys_updated']) or '(aucune)'}")
    if summary.get("keys_skipped_already_present"):
        typer.echo(
            typer.style(
                f"  Ignorées (déjà présentes, sans --force) : {', '.join(summary['keys_skipped_already_present'])}",
                dim=True,
            )
        )
    typer.echo(typer.style("  Redémarrez le dashboard pour recharger le fichier si besoin.", dim=True))


@projects_app.command("list")
def projects_list_cmd(
    *,
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON (champs git_repo, git_branch, remote_host, origin_https, …)"),
) -> None:
    """Liste les projets découverts (même source que l’onglet « Projets » du dashboard)."""
    from zab.services.workspace_projects import discover_projects

    rows = discover_projects()
    if json_out:
        typer.echo(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    if not rows:
        typer.echo(
            "Aucun projet avec SKILL.md — vérifiez projects_roots dans ~/.config/zab/config.yaml "
            "puis `zab projects list` à nouveau.",
        )
        return
    typer.echo(typer.style("Projets (projects_roots)", bold=True))
    typer.echo("")
    for r in rows:
        path_s = str(r.get("path") or "")
        name = str(r.get("name") or "")
        org = str(r.get("org") or "")
        parent = r.get("workspace_parent")
        skills_n = len(r.get("skills") or [])
        git_ok = bool(r.get("git_repo"))
        branch = r.get("git_branch") or "—"
        remote = r.get("remote_host") or "—"
        origin = r.get("origin_https") or ""
        head = f"  {typer.style(name, fg=typer.colors.CYAN, bold=True)}  ({org})"
        if parent:
            head += f"  sous {parent}"
        typer.echo(head)
        try:
            shown_path = _tilde_path(Path(path_s))
        except (OSError, ValueError):
            shown_path = path_s
        typer.echo(f"    chemin       : {shown_path}")
        typer.echo(f"    skills       : {skills_n}")
        git_label = typer.style("oui", fg=typer.colors.GREEN) if git_ok else typer.style("non", dim=True)
        typer.echo(f"    dépôt git    : {git_label}   branche: {branch}   remote: {remote}")
        if origin:
            typer.echo(typer.style(f"    origin (web) : {origin}", dim=True))
        typer.echo("")


@agent_app.command("bootstrap")
def agent_bootstrap_cmd(
    *,
    refresh: bool = typer.Option(False, "--refresh", help="Exécute zab sync avant de produire le bootstrap"),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Point d'entrée recommandé pour Claude Code, Codex ou un autre agent."""
    payload = agent_context.agent_bootstrap(refresh=refresh)
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    counts = payload["state"]["counts"]
    typer.echo(typer.style("zab agent bootstrap", bold=True))
    typer.echo(f"  state : {payload['paths']['state_yaml']}")
    typer.echo(f"  skills: {counts.get('skills', 0)} · projects: {counts.get('projects', 0)} · connectors: {counts.get('connectors', 0)}")
    typer.echo("  next  : zab search <query> --json")


@agent_app.command("skills")
def agent_skills_cmd(
    *,
    org: Optional[str] = typer.Option(None, "--org", help="Filtrer par organisation"),
    project: Optional[str] = typer.Option(None, "--project", help="Filtrer par projet/source"),
    query: Optional[str] = typer.Option(None, "--query", "-q", help="Filtrer par texte"),
    limit: int = typer.Option(200, "--limit", min=1, max=500),
    refresh: bool = typer.Option(False, "--refresh", help="Exécute zab sync avant de produire le manifeste"),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Manifeste compact des skills disponibles pour un agent IA."""

    payload = agent_context.skills_manifest(org=org, project=project, query=query, limit=limit, refresh=refresh)
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(typer.style(f"zab skills manifest ({payload['total']})", bold=True))
    typer.echo("  inspect: zab inspect skills <key> --json")
    for row in payload.get("skills") or []:
        typer.echo(f"  · {row.get('key')} [{row.get('org')}] {row.get('description') or ''}")


@agent_app.command("handoff")
def agent_handoff_cmd(
    project: str = typer.Option(..., "--project", "-p", help="Nom ou chemin de projet"),
    *,
    limit: int = typer.Option(80, "--limit", min=1, max=300),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Compose un contexte projet prêt à donner à un agent."""
    payload = agent_context.project_handoff(project, limit=limit)
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if not payload.get("found"):
        typer.echo(f"Projet introuvable: {project}", err=True)
        raise typer.Exit(1)
    p = payload["project"]
    typer.echo(typer.style(f"Handoff projet: {p.get('name')}", bold=True))
    typer.echo(f"  chemin : {p.get('path')}")
    typer.echo(f"  org    : {p.get('org')}")
    typer.echo(f"  pack   : {payload['context_pack']['path']}")


@security_app.command("status")
def security_status_cmd(
    *,
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Affiche le statut sécurité local sans secrets bruts."""
    payload = agent_context.security_status()
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(typer.style("Sécurité zab", bold=True))
    typer.echo(f"  variables suivies : {payload['tracked_env_count']}")
    typer.echo(f"  présentes         : {len(payload['tracked_env_present'])}")
    typer.echo(f"  manquantes        : {len(payload['tracked_env_missing'])}")
    if payload.get("latest_report"):
        typer.echo(f"  dernier rapport   : {payload['latest_report']['key']}")


@security_app.command("locate")
def security_locate_cmd(
    query: str = typer.Argument(..., help="Nom ou intention à chercher (ex. payfit, qonto api key)"),
    *,
    limit: int = typer.Option(20, "--limit", min=1, max=100),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Localise des noms de variables sensibles sans afficher les valeurs brutes."""

    payload = agent_context.security_locate(query, limit=limit)
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(typer.style(f"Recherche secret: {query}", bold=True))
    typer.echo(f"  résultats : {payload['total']}")
    for row in payload.get("matches") or []:
        sources = row.get("sources") or []
        first_source = sources[0] if sources else {}
        where = first_source.get("path_display") or first_source.get("kind") or "source inconnue"
        line = first_source.get("line")
        line_text = f":{line}" if line else ""
        masked = row.get("masked") or "(vide/non présent)"
        typer.echo(f"  · {row.get('name')}  {masked}  {where}{line_text}")


@security_app.command("publish-check")
def security_publish_check_cmd(
    *,
    mode: str = typer.Option(
        "tracked",
        "--mode",
        help="Surface git à scanner : tracked, staged, worktree ou pre-push.",
    ),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON pour agents/scripts"),
) -> None:
    """Valide que la surface publiable ne contient ni secrets ni contenu privé."""
    import sys

    from zab.services.publish_guard import format_report, scan_publish_surface

    stdin_text = sys.stdin.read() if mode == "pre-push" else None
    try:
        payload = scan_publish_surface(mode=mode, pre_push_stdin=stdin_text)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    if json_out:
        typer.echo(json.dumps(payload.to_dict(), ensure_ascii=False, indent=2))
    else:
        typer.echo(format_report(payload))
    if not payload.ok:
        raise typer.Exit(1)


@mcp_app.command("serve")
def mcp_serve_cmd() -> None:
    """Expose les outils read-only zab via MCP stdio."""
    agent_context.run_mcp_stdio()


def _composio_cli_or_die() -> str:
    from zab.services.composio_connectors import composio_cli_path

    cli = composio_cli_path()
    if not cli:
        typer.echo(
            "composio cli introuvable — installe-la ou place le binaire dans ~/.composio/composio.",
            err=True,
        )
        raise typer.Exit(2)
    return cli


@composio_app.command("connections")
def composio_connections_cmd(
    *,
    toolkit: Optional[str] = typer.Option(None, "--toolkit", help="Filtrer par toolkit slug (gmail, notion, …)"),
    active: bool = typer.Option(False, "--active", help="N'afficher que les comptes ACTIVE"),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON brute"),
) -> None:
    """Liste les comptes Composio connectés (via la CLI locale)."""
    cli = _composio_cli_or_die()
    proc = subprocess.run([cli, "connections", "list"], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        typer.echo(proc.stderr.strip() or "composio connections list a échoué", err=True)
        raise typer.Exit(proc.returncode or 1)
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        typer.echo(f"sortie composio non-JSON : {exc}", err=True)
        raise typer.Exit(1) from exc
    if toolkit:
        payload = {toolkit: payload.get(toolkit, [])}
    if active:
        payload = {k: [c for c in v if str(c.get("status")) == "ACTIVE"] for k, v in payload.items()}
        payload = {k: v for k, v in payload.items() if v}
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(typer.style("Connections Composio", bold=True))
    for slug, entries in sorted(payload.items()):
        typer.echo(f"  {typer.style(slug, fg='cyan')} ({len(entries)})")
        for entry in entries:
            status = str(entry.get("status") or "—")
            word = str(entry.get("word_id") or "—")
            alias = entry.get("alias")
            line = f"    · {status:<10}  {word}"
            if alias:
                line += f"  alias={alias}"
            typer.echo(line)


@composio_app.command("whoami")
def composio_whoami_cmd(
    toolkit: str = typer.Option("gmail", "--toolkit", help="Toolkit slug (gmail, notion…)"),
    account: Optional[str] = typer.Option(
        None,
        "--account",
        help="Word_id du compte à identifier. Si omis, identifie tous les comptes actifs du toolkit.",
    ),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON"),
) -> None:
    """Résout l'identité (email, nom) d'un ou plusieurs comptes Composio."""
    if account:
        results = [composio_svc.resolve_account_identity(account, toolkit=toolkit)]
    else:
        accounts = composio_svc.fetch_connections_via_cli_enriched(
            toolkit=toolkit, active_only=True, resolve_identities=True
        )
        results = []
        for acc in accounts:
            rid = str(acc.get("id") or "").strip()
            ri = acc.get("resolved_identity")
            if isinstance(ri, dict):
                results.append(ri)
            elif rid:
                results.append(composio_svc.resolve_account_identity(rid, toolkit=toolkit))
    if json_out:
        typer.echo(json.dumps(results, ensure_ascii=False, indent=2))
        return
    typer.echo(typer.style(f"Identités Composio — {toolkit}", bold=True))
    for r in results:
        ac = r.get("account") or "unknown"
        em = r.get("email") or typer.style("inconnu", fg="red")
        method = r.get("method") or "—"
        status = "✅" if r.get("successful") else "❌"
        typer.echo(f"  {status} {typer.style(ac, fg='cyan')} → {em}  ({method})")


@composio_app.command("execute")
def composio_execute_cmd(
    slug: str = typer.Argument(..., help="Slug du tool (ex. GMAIL_FETCH_EMAILS)"),
    data: str = typer.Option("{}", "--data", "-d", help="Payload JSON ou @fichier.json"),
    *,
    account: Optional[str] = typer.Option(
        None,
        "--account",
        help="Compte Composio à cibler (alias, word_id ou account id) quand plusieurs comptes existent.",
    ),
    toolkit: Optional[str] = typer.Option(
        None,
        "--toolkit",
        help="Toolkit slug requis quand --all-accounts est utilisé.",
    ),
    all_accounts: bool = typer.Option(
        False,
        "--all-accounts",
        help="Itère sur tous les comptes actifs du toolkit et agrège les résultats.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Valide et prévisualise sans exécuter"),
    get_schema: bool = typer.Option(False, "--get-schema", help="Affiche le schéma CLI du tool"),
    required_only: bool = typer.Option(
        False,
        "--required-only",
        help="Avec --get-schema : ne montre que les champs requis (+ premier exemple).",
    ),
) -> None:
    """Passthrough vers `composio execute` (cli locale). Avec --all-accounts, itère sur tous les comptes du toolkit."""
    cli = _composio_cli_or_die()

    if all_accounts:
        if not toolkit:
            typer.echo("--all-accounts nécessite --toolkit <slug>", err=True)
            raise typer.Exit(2)
        accounts = composio_svc.fetch_connections_via_cli_enriched(
            toolkit=toolkit, active_only=True, resolve_identities=False
        )
        if not accounts:
            typer.echo(f"aucun compte actif trouvé pour {toolkit}", err=True)
            raise typer.Exit(1)
        results: list[dict[str, Any]] = []
        for acc in accounts:
            word_id = str(acc.get("id") or "").strip()
            if not word_id:
                continue
            cmd = [cli, "execute", slug, "-d", data, "--account", word_id]
            if dry_run:
                cmd.append("--dry-run")
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            entry: dict[str, Any] = {
                "account": word_id,
                "returncode": proc.returncode,
            }
            if proc.returncode == 0:
                try:
                    entry["data"] = json.loads(proc.stdout)
                except json.JSONDecodeError:
                    entry["stdout"] = proc.stdout
            else:
                entry["stderr"] = proc.stderr.strip()[:500]
                entry["stdout"] = proc.stdout.strip()[:500]
            results.append(entry)
        typer.echo(json.dumps(results, ensure_ascii=False, indent=2))
        return

    cmd = [cli, "execute", slug]
    if get_schema:
        cmd.append("--get-schema")
    else:
        cmd += ["-d", data]
        if account:
            cmd += ["--account", account]
        if dry_run:
            cmd.append("--dry-run")
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if get_schema and required_only and proc.returncode == 0:
        try:
            schema = json.loads(proc.stdout)
            props = schema.get("inputSchema", {}).get("properties", {}) or {}
            required = schema.get("inputSchema", {}).get("required", []) or []
            distilled = {
                "slug": schema.get("slug") or slug,
                "required": [
                    {
                        "name": name,
                        "type": props.get(name, {}).get("type"),
                        "description": (str(props.get(name, {}).get("description") or "").split(".")[0] or None),
                        "example": (props.get(name, {}).get("examples") or [None])[0],
                    }
                    for name in required
                ],
                "optional_count": max(0, len(props) - len(required)),
            }
            typer.echo(json.dumps(distilled, ensure_ascii=False, indent=2))
            return
        except (json.JSONDecodeError, AttributeError):
            typer.echo("⚠ schéma non parsable, fallback sur sortie brute :", err=True)
    if proc.stdout:
        typer.echo(proc.stdout, nl=False)
    if proc.stderr:
        typer.echo(proc.stderr, err=True, nl=False)
    if proc.returncode != 0:
        raise typer.Exit(proc.returncode)


@composio_app.command("call")
def composio_call_cmd(
    slug: str = typer.Argument(..., help="Slug du tool (ex. GMAIL_FETCH_EMAILS)"),
    data: str = typer.Option("{}", "--data", "-d", help="Payload JSON ou @fichier.json"),
    *,
    account: Optional[str] = typer.Option(
        None,
        "--account",
        help="connected_account_id (word_id, ex. gmail_piend-damara). Permet le multi-compte.",
    ),
    user_id: Optional[str] = typer.Option(None, "--user-id", help="user_id Composio (optionnel)"),
) -> None:
    """Exécute un tool Composio via la REST `/api/v3/tools/execute/<slug>` avec routage multi-compte."""
    from zab.services.composio_connectors import execute_tool_via_rest

    if data.startswith("@"):
        try:
            data_text = Path(data[1:]).expanduser().read_text(encoding="utf-8")
        except OSError as exc:
            typer.echo(f"impossible de lire {data}: {exc}", err=True)
            raise typer.Exit(2) from exc
    else:
        data_text = data
    try:
        arguments = json.loads(data_text or "{}")
    except json.JSONDecodeError as exc:
        typer.echo(f"payload JSON invalide: {exc}", err=True)
        raise typer.Exit(2) from exc
    if not isinstance(arguments, dict):
        typer.echo("payload doit être un objet JSON", err=True)
        raise typer.Exit(2)
    result = execute_tool_via_rest(slug, arguments, connected_account_id=account, user_id=user_id)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("successful", True):
        raise typer.Exit(1)


@composio_app.command("search")
def composio_search_cmd(
    query: list[str] = typer.Argument(..., help="Requêtes en langage naturel"),
    *,
    toolkits: Optional[str] = typer.Option(None, "--toolkits", help="Slugs séparés par virgule"),
    limit: int = typer.Option(5, "--limit", min=1, max=1000),
) -> None:
    """Passthrough vers `composio search`."""
    cli = _composio_cli_or_die()
    cmd = [cli, "search", *query, "--limit", str(limit)]
    if toolkits:
        cmd += ["--toolkits", toolkits]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.stdout:
        typer.echo(proc.stdout, nl=False)
    if proc.stderr:
        typer.echo(proc.stderr, err=True, nl=False)
    if proc.returncode != 0:
        raise typer.Exit(proc.returncode)


@composio_app.command("hint")
def composio_hint_cmd(
    toolkit: str = typer.Argument(..., help="Slug d'un connecteur (gmail, notion…) tel qu'exposé par zab"),
) -> None:
    """Affiche comment exploiter un connecteur Composio (CLI + REST API)."""
    cli = _composio_cli_or_die()
    typer.echo(typer.style(f"Connecteur {toolkit} via Composio", bold=True))
    typer.echo("  CLI :")
    typer.echo(f"    {cli} connections list                  # comptes liés")
    typer.echo(f"    {cli} link {toolkit}                    # lier un nouveau compte")
    typer.echo(f"    {cli} search 'list emails' --toolkits {toolkit} --limit 5")
    typer.echo(f"    {cli} execute <TOOL_SLUG> -d '{{...}}'")
    typer.echo("  REST API (base https://backend.composio.dev) :")
    typer.echo("    curl -H \"x-api-key: $COMPOSIO_API_KEY\" https://backend.composio.dev/api/v3/connected_accounts")
    typer.echo("    curl -H \"x-api-key: $COMPOSIO_API_KEY\" \\")
    typer.echo(f"      'https://backend.composio.dev/api/v3/toolkits?slugs={toolkit}'")
    typer.echo("  zab :")
    typer.echo(f"    zab composio connections --toolkit {toolkit} --active")
    typer.echo(f"    zab composio execute <TOOL_SLUG> -d '{{...}}'")


# ── Cloud Workstation sync helpers ───────────────────────────────────────────


def _ws_profiles_arg(profiles: Optional[list[str]]) -> list[str]:
    return profiles or ["zab", "dotfiles", "secrets-cli"]


@ws_sync_app.command("status")
def ws_sync_status_cmd(
    profile: Optional[list[str]] = typer.Option(None, "--profile", "-p", help="Profil à inspecter (répétable). Défaut: tous."),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON"),
) -> None:
    """Statut local/remote des profils de sync Workstation."""
    from zab.services import workstation_sync as ws

    payload: dict[str, Any] = {"profiles": {}}
    for prof in _ws_profiles_arg(profile):
        one = ws.status(prof)
        payload["machine"] = one.get("machine")
        payload["bucket"] = one.get("bucket")
        payload["profiles"].update(one.get("profiles") or {})
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(typer.style("Workstation sync status", bold=True))
    typer.echo(f"  machine: {payload.get('machine')}")
    typer.echo(f"  bucket : {payload.get('bucket')}")
    for prof, row in (payload.get("profiles") or {}).items():
        changed = row.get("local_changed_since_last_sync") or []
        remote = "présent" if row.get("remote_archive_sha256") else "absent"
        typer.echo(f"  · {prof}: local={row.get('local_files')} remote={remote} changed={len(changed)} encrypted={row.get('encrypted')}")
        if changed:
            for rel in changed[:8]:
                typer.echo(typer.style(f"      Δ {rel}", fg=typer.colors.YELLOW))
            if len(changed) > 8:
                typer.echo(typer.style(f"      … {len(changed) - 8} autres", dim=True))


@ws_sync_app.command("push")
def ws_sync_push_cmd(
    profile: Optional[list[str]] = typer.Option(None, "--profile", "-p", help="Profil à pousser (répétable). Défaut: tous."),
    force: bool = typer.Option(False, "--force", help="Pousser même si remote et local ont divergé."),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON"),
) -> None:
    """Pousse les profils locaux vers le bucket GCS hub."""
    from zab.services import workstation_sync as ws

    results = [ws.push(prof, force=force) for prof in _ws_profiles_arg(profile)]
    if json_out:
        typer.echo(json.dumps(results, ensure_ascii=False, indent=2))
        return
    for res in results:
        ok = res.get("ok")
        color = typer.colors.GREEN if ok else typer.colors.RED
        typer.echo(typer.style(f"{'OK' if ok else 'ERR'} push {res.get('profile')}", fg=color, bold=True))
        typer.echo(f"  {res.get('message') or res.get('archive_sha256') or res.get('reason')}")
        if res.get("local_changed"):
            typer.echo(f"  fichiers locaux modifiés: {len(res['local_changed'])}")
    if any(not r.get("ok") for r in results):
        raise typer.Exit(1)


@ws_sync_app.command("pull")
def ws_sync_pull_cmd(
    profile: Optional[list[str]] = typer.Option(None, "--profile", "-p", help="Profil à tirer (répétable). Défaut: tous."),
    force: bool = typer.Option(False, "--force", help="Appliquer sans préserver les conflits locaux."),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON"),
) -> None:
    """Tire les profils depuis le bucket GCS hub vers la machine locale."""
    from zab.services import workstation_sync as ws

    results = [ws.pull(prof, force=force) for prof in _ws_profiles_arg(profile)]
    if json_out:
        typer.echo(json.dumps(results, ensure_ascii=False, indent=2))
        return
    for res in results:
        ok = res.get("ok")
        color = typer.colors.GREEN if ok else typer.colors.RED
        typer.echo(typer.style(f"{'OK' if ok else 'ERR'} pull {res.get('profile')}", fg=color, bold=True))
        typer.echo(f"  {res.get('message') or res.get('archive_sha256') or res.get('reason')}")
        conflicts = res.get("conflicts") or []
        if conflicts:
            typer.echo(typer.style(f"  conflits préservés: {len(conflicts)}", fg=typer.colors.YELLOW))
            for c in conflicts[:8]:
                typer.echo(f"    {c}")
    if any(not r.get("ok") for r in results):
        raise typer.Exit(1)


@ws_app.command("secrets-help")
def ws_secrets_help_cmd() -> None:
    """Affiche la procédure d'activation du profil chiffré secrets-cli."""
    typer.echo(typer.style("Activation de zab ws sync --profile secrets-cli", bold=True))
    typer.echo("")
    typer.echo("Le profil secrets-cli est chiffré avant upload GCS. Il ne doit PAS être mis en cron tant que la clé n'est pas posée et testée.")
    typer.echo("")
    typer.echo("1) Sur le Mac, créer la clé locale si absente :")
    typer.echo("   mkdir -p ~/.config/zab")
    typer.echo("   umask 077")
    typer.echo("   openssl rand -base64 32 > ~/.config/zab/ws-sync.key")
    typer.echo("   chmod 600 ~/.config/zab/ws-sync.key")
    typer.echo("")
    typer.echo("2) Copier exactement la même clé sur la Workstation :")
    typer.echo("   mkdir -p /home/user/.config/zab")
    typer.echo("   # copier ~/.config/zab/ws-sync.key vers /home/user/.config/zab/ws-sync.key")
    typer.echo("   chmod 600 /home/user/.config/zab/ws-sync.key")
    typer.echo("")
    typer.echo("3) Tester explicitement, sans cron :")
    typer.echo("   zab ws sync push --profile secrets-cli")
    typer.echo("   zab ws sync status --profile secrets-cli")
    typer.echo("   zab ws sync pull --profile secrets-cli")
    typer.echo("")
    typer.echo("Fichiers couverts : .claude, .gemini, .codex, .config/gh, .config/firebase, .config/supabase, .config/composio, .config/scw, .aws, .ssh/config et clés SSH explicitement listées.")


@ws_app.command("cli-status")
def ws_cli_status_cmd(
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON"),
) -> None:
    """Compare cli_watchlist avec les binaires présents dans le PATH."""
    from zab.services import workstation_sync as ws

    payload = ws.cli_status()
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(typer.style("Workstation CLI status", bold=True))
    typer.echo(f"  présents: {payload['ok']}/{payload['total']}")
    missing = payload.get("missing") or []
    if missing:
        typer.echo(typer.style(f"  manquants: {len(missing)}", fg=typer.colors.YELLOW))
        for name in missing:
            typer.echo(f"    · {name}")
    else:
        typer.echo(typer.style("  tous les CLIs surveillés sont présents", fg=typer.colors.GREEN))


@ws_app.command("cli-install-missing")
def ws_cli_install_missing_cmd(
    dry_run: bool = typer.Option(False, "--dry-run", help="Afficher les installateurs sans exécuter."),
    name: Optional[list[str]] = typer.Option(None, "--name", "-n", help="Installer seulement ce CLI (répétable)."),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON"),
) -> None:
    """Installe les CLIs manquants connus depuis cli_watchlist."""
    from zab.services import workstation_sync as ws

    payload = ws.cli_install_missing(dry_run=dry_run, names=name)
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    for row in payload.get("results") or []:
        status = row.get("status")
        color = typer.colors.GREEN if status in {"installed", "already_present", "dry_run"} else typer.colors.YELLOW
        typer.echo(typer.style(f"{row.get('name')}: {status}", fg=color))
        if row.get("command"):
            typer.echo(typer.style("  " + " ".join(row["command"]), dim=True))


# ── VM de dev distante ───────────────────────────────────────────────────────


def _fmt_duration(seconds: Any) -> str:
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return "—"
    if total < 0:
        return "—"
    hours, rest = divmod(total, 3600)
    return f"{hours}h{rest // 60:02d}"


@vm_app.command("status")
def vm_status_cmd(
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON"),
) -> None:
    """État de la VM distante, connexions SSH et sessions de sync."""
    from zab.services import remote_vm

    payload = remote_vm.overview()
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if not payload.get("configured"):
        typer.echo(typer.style(payload["vm"].get("error") or "remote_vm non configuré", fg=typer.colors.YELLOW))
        raise typer.Exit(1)

    vm = payload["vm"]
    state = str(vm.get("status") or "—")
    color = typer.colors.GREEN if state == "RUNNING" else typer.colors.BRIGHT_BLACK
    typer.echo(typer.style(f"{vm.get('instance')} — {state}", bold=True, fg=color))
    typer.echo(f"  {vm.get('machine_type')} · {vm.get('vcpus')} vCPU · {vm.get('memory_gb')} Go RAM · {vm.get('disk_total_gb')} Go disque")
    typer.echo(f"  zone {vm.get('zone')} · projet {vm.get('project')}")
    if vm.get("session_seconds"):
        typer.echo(f"  session en cours: {_fmt_duration(vm['session_seconds'])} (démarrée {vm.get('last_start')})")
    elif vm.get("last_session_seconds"):
        typer.echo(typer.style(f"  dernière session: {_fmt_duration(vm['last_session_seconds'])}", dim=True))

    ssh = payload["ssh"]
    typer.echo(typer.style("SSH", bold=True))
    typer.echo(
        f"  control master: {ssh['control_master']['state']} · tunnels: {ssh.get('tunnels')} · "
        f"agents sync: {ssh.get('sync_agents')} · shells: {ssh.get('shells')}"
    )

    sync = payload["sync"]
    totals = sync.get("totals") or {}
    if sync.get("error"):
        typer.echo(typer.style(f"Sync: {sync['error']}", fg=typer.colors.YELLOW))
    else:
        typer.echo(typer.style("Sync", bold=True))
        typer.echo(
            f"  {totals.get('connected')}/{totals.get('sessions')} sessions connectées · "
            f"{totals.get('alpha_files')} fichiers local / {totals.get('beta_files')} distant · "
            f"écart {totals.get('file_delta')} · conflits {totals.get('conflicts')}"
        )
        for row in sync.get("sessions") or []:
            if row.get("conflicts") or row.get("problems") or row.get("last_error"):
                typer.echo(typer.style(f"    ⚠ {row['name']}: {row.get('last_error') or 'conflits/problèmes'}", fg=typer.colors.YELLOW))


@vm_app.command("cost")
def vm_cost_cmd(
    days: int = typer.Option(30, "--days", "-d", help="Fenêtre d'analyse en jours."),
    refresh: bool = typer.Option(False, "--refresh", help="Ignorer le cache et relancer la requête de facturation."),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON"),
) -> None:
    """Coût et heures d'exécution de la VM depuis l'export de facturation."""
    from zab.services import remote_vm

    payload = remote_vm.cost_report(days=days, refresh=refresh)
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if payload.get("error") and not payload.get("days"):
        typer.echo(typer.style(payload["error"], fg=typer.colors.YELLOW))
        raise typer.Exit(1)

    totals = payload.get("totals") or {}
    cur = payload.get("currency") or ""
    typer.echo(typer.style(f"Coût VM — fenêtre {payload.get('window_days')} j", bold=True))
    typer.echo(f"  mois en cours : {totals.get('mtd_cost')} {cur} · {totals.get('mtd_hours')} h")
    typer.echo(f"  7 derniers j  : {totals.get('last7_cost')} {cur} · {totals.get('last7_hours')} h")
    typer.echo(f"  taux allumée  : {totals.get('hourly_rate')} {cur}/h")
    typer.echo(f"  socle éteinte : {totals.get('fixed_daily_cost')} {cur}/j")
    typer.echo(f"  projection    : {totals.get('month_projection')} {cur} sur le mois")
    freshness = payload.get("freshness") or {}
    typer.echo(typer.style(f"  facturé jusqu'au {freshness.get('billed_through') or '—'}", dim=True))
    for row in (payload.get("by_sku") or [])[:6]:
        typer.echo(f"    · {row['sku']}: {round(row['cost'], 4)} {cur}")


@vm_app.command("sync")
def vm_sync_cmd(
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON"),
) -> None:
    """Détail des sessions de synchronisation avec la VM."""
    from zab.services import remote_vm

    payload = remote_vm.sync_state()
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if payload.get("error"):
        typer.echo(typer.style(payload["error"], fg=typer.colors.YELLOW))
        raise typer.Exit(1)
    for row in payload.get("sessions") or []:
        status = str(row.get("status") or "—")
        color = typer.colors.GREEN if status == "watching" else typer.colors.YELLOW
        typer.echo(typer.style(f"{row['name']}: {status}", fg=color))
        typer.echo(
            f"    local {row['alpha']['files']} fichiers · distant {row['beta']['files']} · "
            f"écart {row['file_delta']} · conflits {row['conflicts']}"
        )


# ── Gmail helpers ────────────────────────────────────────────────────────────

gmail_app = typer.Typer(help="Helpers Gmail pour Composio multi-compte.", no_args_is_help=True)
composio_app.add_typer(gmail_app, name="gmail")


@gmail_app.command("accounts")
def gmail_accounts_cmd(
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON"),
) -> None:
    """Liste tous les comptes Gmail actifs avec leurs emails résolus."""
    accounts = composio_svc.fetch_connections_via_cli_enriched(
        toolkit="gmail", active_only=True, resolve_identities=True
    )
    if json_out:
        typer.echo(json.dumps(accounts, ensure_ascii=False, indent=2))
        return
    typer.echo(typer.style("Comptes Gmail Composio", bold=True))
    for acc in accounts:
        wid = str(acc.get("id") or "—")
        ri = acc.get("resolved_identity") or {}
        email = ri.get("email") if ri.get("successful") else None
        status = str(acc.get("status") or "—").upper()
        label = acc.get("label") or ""
        line = f"  {status:<10}  {typer.style(wid, fg='cyan')}"
        if email:
            line += f"  → {typer.style(email, fg='green')}"
        elif label:
            line += f"  alias={label}"
        typer.echo(line)


@gmail_app.command("search")
def gmail_search_cmd(
    query: str = typer.Argument(..., help="Query Gmail (ex: from:orange subject:invoice)"),
    limit: int = typer.Option(5, "--limit", min=1, max=50),
    account: Optional[str] = typer.Option(None, "--account", help="Compte spécifique, sinon tous"),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON"),
) -> None:
    """Recherche Gmail via Composio, sur un compte ou tous."""
    cli = _composio_cli_or_die()
    payload = json.dumps({"query": query, "max_results": limit, "include_payload": False})
    if account:
        targets = [account]
    else:
        accounts = composio_svc.fetch_connections_via_cli_enriched(
            toolkit="gmail", active_only=True, resolve_identities=False
        )
        targets = [str(a.get("id") or "").strip() for a in accounts if a.get("id")]
    results: list[dict[str, Any]] = []
    for wid in targets:
        proc = subprocess.run(
            [cli, "execute", "GMAIL_FETCH_EMAILS", "-d", payload, "--account", wid],
            capture_output=True,
            text=True,
            check=False,
        )
        entry = {"account": wid, "returncode": proc.returncode}
        if proc.returncode == 0:
            try:
                entry["data"] = json.loads(proc.stdout)
            except json.JSONDecodeError:
                entry["stdout"] = proc.stdout
        else:
            entry["stderr"] = proc.stderr.strip()[:500]
        results.append(entry)
    if json_out:
        typer.echo(json.dumps(results, ensure_ascii=False, indent=2))
        return
    _render_gmail_messages(results, limit)


def _render_gmail_messages(results: list[dict[str, Any]], limit: int) -> None:
    for r in results:
        typer.echo(f"--- {typer.style(r['account'], fg='cyan')} ---")
        if r.get("data"):
            messages = r["data"].get("data", {}).get("messages", []) if isinstance(r["data"], dict) else []
            if not isinstance(messages, list):
                messages = []
            if not messages:
                typer.echo("  (aucun message)")
            for m in messages[:limit]:
                if isinstance(m, dict):
                    mid = m.get("messageId") or m.get("id") or "?"
                    subject = m.get("subject") or (m.get("preview") or {}).get("subject") or "(no subject)"
                    sender = m.get("sender") or "?"
                    ts = (m.get("messageTimestamp") or "")[:10]
                    line = f"  [{ts}] {mid}: {subject[:70]}"
                    if sender:
                        line += f"  (from: {sender[:40]})"
                    typer.echo(line)
        elif r.get("stderr"):
            typer.echo(f"  erreur: {r['stderr']}", err=True)


@gmail_app.command("last")
def gmail_last_cmd(
    limit: int = typer.Option(3, "--limit", min=1, max=20),
    account: Optional[str] = typer.Option(None, "--account", help="Compte spécifique, sinon tous"),
    json_out: bool = typer.Option(False, "--json", help="Sortie JSON"),
) -> None:
    """Récupère les derniers emails d'un ou tous les comptes Gmail."""
    cli = _composio_cli_or_die()
    payload = json.dumps({"max_results": limit, "include_payload": False})
    if account:
        targets = [account]
    else:
        accounts = composio_svc.fetch_connections_via_cli_enriched(
            toolkit="gmail", active_only=True, resolve_identities=False
        )
        targets = [str(a.get("id") or "").strip() for a in accounts if a.get("id")]
    results: list[dict[str, Any]] = []
    for wid in targets:
        proc = subprocess.run(
            [cli, "execute", "GMAIL_FETCH_EMAILS", "-d", payload, "--account", wid],
            capture_output=True,
            text=True,
            check=False,
        )
        entry = {"account": wid, "returncode": proc.returncode}
        if proc.returncode == 0:
            try:
                entry["data"] = json.loads(proc.stdout)
            except json.JSONDecodeError:
                entry["stdout"] = proc.stdout
        else:
            entry["stderr"] = proc.stderr.strip()[:500]
        results.append(entry)
    if json_out:
        typer.echo(json.dumps(results, ensure_ascii=False, indent=2))
        return
    _render_gmail_messages(results, limit)


@brain_app.command("status")
def brain_status(json_out: bool = typer.Option(False, "--json", help="Sortie JSON")) -> None:
    """Affiche le statut du brain Zab."""
    from zab.services.brain import status
    data = status()
    if json_out:
        typer.echo(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        typer.echo(yaml.dump(data, allow_unicode=True, sort_keys=False))

@brain_app.command("schema")
def brain_schema(json_out: bool = typer.Option(False, "--json", help="Sortie JSON")) -> None:
    """Affiche le schéma du brain Zab."""
    from zab.services.brain import schema
    data = schema()
    if json_out:
        typer.echo(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        typer.echo(yaml.dump(data, allow_unicode=True, sort_keys=False))

def main() -> None:
    from zab.user_config import ensure_user_config_exists

    ensure_user_config_exists()
    request_id, started = request_logs.log_cli_start()
    try:
        app()
    except typer.Exit as exc:
        exit_code = int(getattr(exc, "exit_code", 1) or 0)
        request_logs.log_cli_end(
            request_id,
            started,
            exit_code=exit_code,
            error=exc if exit_code else None,
        )
        raise
    except SystemExit as exc:
        raw_code = exc.code
        exit_code = raw_code if isinstance(raw_code, int) else (0 if raw_code is None else 1)
        request_logs.log_cli_end(
            request_id,
            started,
            exit_code=exit_code,
            error=exc if exit_code else None,
        )
        raise
    except BaseException as exc:
        request_logs.log_cli_end(request_id, started, exit_code=1, error=exc)
        raise
    else:
        request_logs.log_cli_end(request_id, started, exit_code=0)


if __name__ == "__main__":
    main()
