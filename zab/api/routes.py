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
from fastapi import APIRouter, Body, HTTPException, Query, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from typer.testing import CliRunner

from zab.cli import app as zab_cli_app
from zab.paths import skills_root_from_config_file_only
from zab.services import config_snapshots, connectors_aggregate, discovery, jobs, memory_db, scan_persist, scanner, skills_fs, tools_probe, tools_scan
from zab.services.pm_env_sync import sync_pm_tokens_to_user_dotenv
from zab.services.tasks_inbox import fetch_tasks_inbox
from zab.services.workspace_projects import path_is_under_projects_roots, project_dir_is_under_projects_roots
from zab.system_open import open_os_path
from zab.user_config import (
    load_user_config,
    merge_models_discovery_from_workspace_scan,
    merge_projects_roots_into_config,
    save_user_config,
    skill_md_paths_resolved,
    tracked_env_names_for_security,
    user_config_path,
)

router = APIRouter()


def _dashboard_skills_root() -> Path | None:
    return skills_root_from_config_file_only()


def _require_dashboard_skills_root() -> Path:
    r = _dashboard_skills_root()
    if r is None:
        raise HTTPException(
            status_code=503,
            detail="Définissez skill_md_paths / claude_plugin_paths ou skills_roots dans ~/.config/zab/config.yaml pour cette action.",
        )
    return r


def _require_skills_anchor_or_project_path(path: str) -> None:
    """Lecture/écriture SKILL : ancre dépôt skills sauf chemin absolu autorisé (skill_md_paths ou projects_roots)."""
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
            allowed = {str(x.resolve()) for x in skill_md_paths_resolved()}
            if str(r) in allowed:
                return
    if skills_root_from_config_file_only() is None:
        raise HTTPException(
            status_code=503,
            detail="Définissez skill_md_paths / skills_roots dans ~/.config/zab/config.yaml, "
            "ou passez un chemin absolu vers un SKILL.md sous projects_roots.",
        )


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "zab"}


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


@router.get("/overview")
def overview(response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return discovery.overview()


@router.get("/tasks/inbox")
def tasks_inbox(response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return fetch_tasks_inbox()


class PmEnvSyncBody(BaseModel):
    force: bool = Field(False, description="Remplace les jetons PM même s’ils existent déjà dans ~/.config/zab/.env")


@router.post("/tasks/pm-env/sync")
def tasks_pm_env_sync(body: PmEnvSyncBody = Body(default_factory=PmEnvSyncBody)) -> dict[str, Any]:
    """Scanne les .env sous projects_roots (+ skills/.env) et fusionne GITLAB_TOKEN / LINEAR_API_KEY / NOTION_TOKEN dans ~/.config/zab/.env."""
    return sync_pm_tokens_to_user_dotenv(force=body.force)


@router.get("/orgs")
def orgs() -> list[dict[str, Any]]:
    return discovery.list_orgs_with_skills()


@router.get("/plugins")
def plugins() -> list[dict[str, Any]]:
    return discovery.list_claude_plugin_bundles()


@router.get("/mcp")
def mcp() -> dict[str, Any]:
    return discovery.list_mcp_configs()


@router.get("/connectors")
def connectors_api(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    q: str = "",
    kind: str | None = Query(None),
    tag: str | None = Query(None),
) -> dict[str, Any]:
    return connectors_aggregate.list_connectors(page=page, limit=limit, q=q, kind=kind, tag=tag)


@router.get("/connectors/{slug}")
def connectors_detail(slug: str) -> dict[str, Any]:
    row = connectors_aggregate.get_connector(slug)
    if not row:
        raise HTTPException(status_code=404, detail="connecteur inconnu")
    return row


@router.get("/config/files")
def config_files_snapshot_list() -> list[dict[str, Any]]:
    return config_snapshots.list_config_files()


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
        description="smoke_mcps|gateway_pytest|sync_mcps_litellm|build_plugins|google_oauth_mehdi_context|memory_import|mempalace_install",
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


def _mask_value(val: str) -> str:
    v = val.strip()
    if not v:
        return ""
    if len(v) <= 4:
        return "****"
    return "****" + v[-4:]


def _dotenv_file_values() -> dict[str, str | None]:
    root = _dashboard_skills_root()
    if root is None:
        return {}
    env_path = root / ".env"
    if not env_path.is_file():
        return {}
    raw = dotenv_values(env_path)
    return {str(k): v for k, v in raw.items() if k}


def _skills_dotenv_path() -> Path:
    root = _require_dashboard_skills_root().resolve()
    target = (root / ".env").resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="chemin .env invalide") from exc
    if target.name != ".env":
        raise HTTPException(status_code=400, detail="seul le fichier .env à la racine skills est éditable")
    return target


@router.get("/security/env")
def security_env() -> dict[str, Any]:
    file_vals = _dotenv_file_values()
    rows: list[dict[str, Any]] = []
    for name in tracked_env_names_for_security():
        raw_os = os.environ.get(name)
        raw_file = file_vals.get(name)
        from_os = raw_os is not None and str(raw_os).strip() != ""
        from_file = raw_file is not None and str(raw_file).strip() != ""
        present = from_os or from_file
        raw_for_mask = str(raw_os) if from_os else (str(raw_file) if from_file else "")
        rows.append(
            {
                "name": name,
                "present": present,
                "in_process": from_os,
                "in_file": from_file,
                "masked": _mask_value(raw_for_mask) if present else "",
            }
        )
    return {"variables": rows}


@router.get("/security/env-file")
def security_env_file() -> dict[str, Any]:
    """Contenu brut de skills/.env — réservé au dashboard local (secret en clair)."""
    path = _skills_dotenv_path()
    exists = path.is_file()
    content = path.read_text(encoding="utf-8") if exists else ""
    root = _require_dashboard_skills_root().resolve()
    try:
        path_display = str(path.relative_to(root))
    except ValueError:
        path_display = str(path)
    return {
        "path": str(path),
        "path_display": path_display,
        "exists": exists,
        "content": content,
    }


class EnvFilePutBody(BaseModel):
    content: str


@router.put("/security/env-file")
def security_env_file_put(body: EnvFilePutBody) -> dict[str, Any]:
    """Écrit skills/.env (sauvegarde horodatée si le fichier existait déjà)."""
    path = _skills_dotenv_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup: str | None = None
    if path.is_file():
        backup_path = path.with_name(f".env.zab-backup-{ts}")
        shutil.copy2(path, backup_path)
        backup = str(backup_path)
    path.write_text(body.content, encoding="utf-8")
    root = _require_dashboard_skills_root().resolve()
    rel_backup: str | None = None
    if backup:
        bp = Path(backup)
        try:
            rel_backup = str(bp.relative_to(root))
        except ValueError:
            rel_backup = backup
    return {
        "path": str(path),
        "written": True,
        "backup": rel_backup,
    }


@router.get("/skills/file")
def skill_get(
    path: str = Query(..., description="Chemin relatif sous le dépôt (orgs/… ou claude-plugins/…) ou absolu si listé dans skill_md_paths / sous projects_roots"),
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


@router.get("/scan/last")
def scan_last() -> dict[str, Any]:
    """Dernier scan persisté (si présent)."""
    prev = scan_persist.load_last_scan()
    if prev is None:
        return {"present": False}
    return {"present": True, **prev}


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
    text = (result.stdout or "") + (result.stderr or "")
    if result.exit_code != 0 and not text.strip():
        raise HTTPException(status_code=500, detail="Échec zab --help")
    return {"text": text.strip() or "(vide)"}


@router.get("/tools/probe")
def tools_probe_route(kind: str = Query(...)) -> dict[str, Any]:
    if kind not in ("litellm", "openrouter"):
        raise HTTPException(status_code=400, detail="kind doit être litellm ou openrouter")
    return tools_probe.probe_models(kind)


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
