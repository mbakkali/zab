"""Service de gestion et d'agrégation de crons multi-sources (Hermes, launchd, GCP, etc.) avec support Postgres."""

from __future__ import annotations

import json
import os
import plistlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from zab.paths import config_dir, user_home
from zab.services import postgres_store as local_db
from zab.services.memory_db import _url_or_none, _pg_connect_timeout, memory_psycopg_available

DEFAULT_GCP_PROJECT = ""
DEFAULT_GCP_LOCATION = "europe-west1"


def registry_path() -> Path:
    """Retourne le chemin absolu du fichier de registre des crons."""
    return (config_dir() / "crons-registry.json").resolve()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _launchd_domain() -> str:
    return f"gui/{os.getuid()}"


def _launchctl_print(label: str) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["launchctl", "print", f"{_launchd_domain()}/{label}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as exc:
        return {"loaded": False, "error": str(exc)}

    data: dict[str, Any] = {
        "loaded": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    if result.returncode != 0:
        return data

    for raw in result.stdout.splitlines():
        line = raw.strip()
        if line.startswith("state = "):
            data["state"] = line.split("=", 1)[1].strip()
        elif line.startswith("runs = "):
            value = line.split("=", 1)[1].strip()
            data["runs"] = int(value) if value.isdigit() else value
        elif line.startswith("last exit code = "):
            data["last_exit_code"] = line.split("=", 1)[1].strip()
        elif line.startswith("run interval = "):
            data["run_interval"] = line.split("=", 1)[1].strip()
    return data


def _format_duration(seconds: int) -> str:
    if seconds % 3600 == 0:
        return f"every {seconds // 3600}h"
    if seconds % 60 == 0:
        return f"every {seconds // 60}m"
    return f"every {seconds}s"


def _format_launchd_calendar(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(_format_launchd_calendar(item) for item in value)
    if not isinstance(value, dict):
        return str(value)

    hour = value.get("Hour")
    minute = value.get("Minute")
    weekday = value.get("Weekday")
    day = value.get("Day")
    month = value.get("Month")
    if hour is not None and minute is not None and not any(x is not None for x in (weekday, day, month)):
        return f"daily {int(hour):02d}:{int(minute):02d}"

    parts = []
    for key in ("Minute", "Hour", "Weekday", "Day", "Month"):
        if key in value:
            parts.append(f"{key}={value[key]}")
    return "calendar " + " ".join(parts)


def _format_launchd_schedule(plist: dict[str, Any]) -> str:
    parts: list[str] = []
    interval = plist.get("StartInterval")
    if isinstance(interval, int):
        parts.append(_format_duration(interval))
    if "StartCalendarInterval" in plist:
        parts.append(_format_launchd_calendar(plist["StartCalendarInterval"]))
    if plist.get("RunAtLoad"):
        parts.append("run at load")
    return " + ".join(parts) if parts else "manual"


def _read_launchd_run_status(job_arg: str) -> dict[str, Any]:
    path = user_home() / ".local" / "share" / "zab" / "launchd-runs" / f"{job_arg}.json"
    data = _read_json(path)
    if data:
        data["status_path"] = str(path)
    return data


def _scan_launchd_zab_crons() -> list[dict[str, Any]]:
    launch_agents = user_home() / "Library" / "LaunchAgents"
    crons: list[dict[str, Any]] = []
    for plist_path in sorted(launch_agents.glob("ai.zab.*.plist")):
        try:
            with plist_path.open("rb") as fh:
                plist = plistlib.load(fh)
        except Exception as exc:
            crons.append({
                "id": f"launchd-{plist_path.stem}",
                "name": plist_path.stem,
                "source": "launchd",
                "schedule": "unknown",
                "enabled": False,
                "status": "error",
                "last_run": None,
                "next_run": None,
                "details": {"plist_path": str(plist_path), "error": str(exc)},
            })
            continue

        label = str(plist.get("Label") or plist_path.stem)
        args = [str(x) for x in plist.get("ProgramArguments") or []]
        job_arg = args[1] if len(args) > 1 and args[0].endswith("zab_launchd_run.sh") else label
        launchd = _launchctl_print(label)
        run_status = _read_launchd_run_status(job_arg)
        last_exit_code = str(launchd.get("last_exit_code") or "")

        enabled = bool(launchd.get("loaded"))
        status = "paused"
        if enabled:
            status = "active"
            if run_status.get("result") == "ok":
                status = "ok"
            if run_status.get("result") == "error" or (
                last_exit_code and last_exit_code not in {"0", "(never exited)"}
            ):
                status = "error"

        crons.append({
            "id": f"launchd-{label}",
            "name": label,
            "source": "launchd",
            "schedule": _format_launchd_schedule(plist),
            "enabled": enabled,
            "status": status,
            "last_run": run_status.get("finished_at"),
            "next_run": None,
            "details": {
                "label": label,
                "job_arg": job_arg,
                "plist_path": str(plist_path),
                "program_arguments": args,
                "working_directory": plist.get("WorkingDirectory"),
                "stdout_path": run_status.get("stdout_path") or plist.get("StandardOutPath"),
                "stderr_path": run_status.get("stderr_path") or plist.get("StandardErrorPath"),
                "status_path": run_status.get("status_path"),
                "launchd_state": launchd.get("state"),
                "launchd_runs": launchd.get("runs"),
                "launchd_last_exit_code": launchd.get("last_exit_code"),
            },
        })
    return crons


def _tail_text(path: str | None, *, lines: int = 80) -> str:
    if not path:
        return ""
    p = Path(path).expanduser()
    if not p.is_file():
        return ""
    try:
        return "\n".join(p.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except Exception as exc:
        return f"(unable to read {p}: {exc})"


# ==========================================
# GESTION DES SCHÉMAS ET DES DONNÉES POSTGRES
# ==========================================

def ensure_postgres_crons_schema(conn) -> None:
    """S'assure de l'existence des tables zab_crons et zab_cron_runs."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS zab_crons (
                id VARCHAR(128) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                source VARCHAR(64) NOT NULL,
                schedule VARCHAR(128) NOT NULL,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                status VARCHAR(64) NOT NULL,
                last_run VARCHAR(128),
                next_run VARCHAR(128),
                details JSONB,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS zab_cron_runs (
                id SERIAL PRIMARY KEY,
                cron_id VARCHAR(128) NOT NULL,
                timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                status VARCHAR(64) NOT NULL,
                content TEXT NOT NULL,
                stdout TEXT,
                stderr TEXT
            );
        """)
        conn.commit()


def save_crons_to_postgres(crons_list: list[dict[str, Any]]) -> bool:
    """Enregistre la liste de crons dans la base de données Postgres."""
    if not memory_psycopg_available():
        return False
    url = _url_or_none()
    if not url:
        return False
    
    try:
        import psycopg
        from psycopg.types.json import Jsonb
        
        with psycopg.connect(url, connect_timeout=_pg_connect_timeout()) as conn:
            ensure_postgres_crons_schema(conn)
            with conn.cursor() as cur:
                for c in crons_list:
                    cur.execute("""
                        INSERT INTO zab_crons (id, name, source, schedule, enabled, status, last_run, next_run, details, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            name = EXCLUDED.name,
                            source = EXCLUDED.source,
                            schedule = EXCLUDED.schedule,
                            enabled = EXCLUDED.enabled,
                            status = EXCLUDED.status,
                            last_run = EXCLUDED.last_run,
                            next_run = EXCLUDED.next_run,
                            details = EXCLUDED.details,
                            updated_at = EXCLUDED.updated_at
                    """, (
                        c["id"],
                        c["name"],
                        c["source"],
                        c["schedule"],
                        c["enabled"],
                        c["status"],
                        c["last_run"],
                        c["next_run"],
                        Jsonb(c["details"]),
                        datetime.now(timezone.utc)
                    ))
                conn.commit()
            return True
    except Exception as e:
        print(f"[Crons PG] Erreur lors de la sauvegarde Postgres : {e}")
        return False


def load_crons_from_postgres() -> list[dict[str, Any]] | None:
    """Charge les crons depuis la table Postgres zab_crons."""
    if not memory_psycopg_available():
        return None
    url = _url_or_none()
    if not url:
        return None
        
    try:
        import psycopg
        with psycopg.connect(url, connect_timeout=_pg_connect_timeout()) as conn:
            ensure_postgres_crons_schema(conn)
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, name, source, schedule, enabled, status, last_run, next_run, details 
                    FROM zab_crons
                    ORDER BY source, name ASC
                """)
                rows = cur.fetchall()
                
                crons = []
                for r in rows:
                    crons.append({
                        "id": r[0],
                        "name": r[1],
                        "source": r[2],
                        "schedule": r[3],
                        "enabled": r[4],
                        "status": r[5],
                        "last_run": r[6],
                        "next_run": r[7],
                        "details": r[8] if isinstance(r[8], dict) else {}
                    })
                return crons
    except Exception as e:
        print(f"[Crons PG] Erreur lors de la lecture des crons Postgres : {e}")
        return None


def save_cron_run_to_postgres(cron_id: str, status: str, content: str, stdout: str | None = None, stderr: str | None = None) -> bool:
    """Enregistre un historique d'exécution (run log) dans Postgres."""
    if not memory_psycopg_available():
        return False
    url = _url_or_none()
    if not url:
        return False
        
    try:
        import psycopg
        with psycopg.connect(url, connect_timeout=_pg_connect_timeout()) as conn:
            ensure_postgres_crons_schema(conn)
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO zab_cron_runs (cron_id, status, content, stdout, stderr, timestamp)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    cron_id,
                    status,
                    content,
                    stdout,
                    stderr,
                    datetime.now(timezone.utc)
                ))
                conn.commit()
            return True
    except Exception as e:
        print(f"[Crons PG] Erreur sauvegarde du run Postgres : {e}")
        return False


def load_cron_runs_from_postgres(cron_id: str) -> list[dict[str, Any]]:
    """Charge les runs enregistrés dans Postgres pour un cron_id."""
    if not memory_psycopg_available():
        return []
    url = _url_or_none()
    if not url:
        return []
        
    try:
        import psycopg
        with psycopg.connect(url, connect_timeout=_pg_connect_timeout()) as conn:
            ensure_postgres_crons_schema(conn)
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT timestamp, status, content 
                    FROM zab_cron_runs
                    WHERE cron_id = %s
                    ORDER BY timestamp DESC
                    LIMIT 20
                """, (cron_id,))
                rows = cur.fetchall()
                
                runs = []
                for r in rows:
                    runs.append({
                        "timestamp": r[0].isoformat() if r[0] is not None else datetime.now(timezone.utc).isoformat(),
                        "status": r[1],
                        "content": r[2]
                    })
                return runs
    except Exception as e:
        print(f"[Crons PG] Erreur chargement des runs Postgres : {e}")
        return []


# ==========================================
# SERVICE D'AGRÉGATION ET D'EXÉCUTION
# ==========================================

def load_cached_crons() -> list[dict[str, Any]]:
    """Charge les crons depuis Postgres canonique, puis importe le registre legacy si vide."""
    local_crons = local_db.load_crons()
    if local_crons:
        return local_crons

    reg = registry_path()
    if not reg.is_file():
        return scan_and_save_crons()
    doc = _read_json(reg)
    crons = doc.get("crons", [])
    if isinstance(crons, list):
        clean = [x for x in crons if isinstance(x, dict)]
        local_db.replace_crons(clean)
        return clean
    return []


def scan_and_save_crons() -> list[dict[str, Any]]:
    """Scanne les sources de crons (Hermes, launchd, GCP Cloud Scheduler) et met à jour Postgres."""
    crons: list[dict[str, Any]] = []

    # 1) Scan Hermes Crons
    hermes_jobs_path = Path.home() / ".hermes" / "cron" / "jobs.json"
    if hermes_jobs_path.is_file():
        try:
            h_data = json.loads(hermes_jobs_path.read_text(encoding="utf-8"))
            for job in h_data.get("jobs", []):
                jid = job.get("id", "")
                name = job.get("name", f"hermes-{jid}")
                schedule_expr = job.get("schedule", {}).get("display") or job.get("schedule_display") or ""
                enabled = job.get("enabled", True)
                
                # Statut du cron
                status = "ok"
                if not enabled:
                    status = "paused"
                elif job.get("last_status") == "error" or job.get("last_error"):
                    status = "error"

                crons.append({
                    "id": f"hermes-{jid}",
                    "name": name,
                    "source": "hermes",
                    "schedule": schedule_expr,
                    "enabled": enabled,
                    "status": status,
                    "last_run": job.get("last_run_at"),
                    "next_run": job.get("next_run_at"),
                    "details": {
                        "prompt": job.get("prompt", ""),
                        "skills": job.get("skills", []),
                        "script": job.get("script"),
                        "deliver": job.get("deliver"),
                        "workdir": job.get("workdir"),
                        "original_id": jid
                    }
                })
        except Exception as e:
            print(f"[Crons Scan] Erreur lors du scan Hermes : {e}")

    # 2) Scan launchd LaunchAgents Zab
    try:
        crons.extend(_scan_launchd_zab_crons())
    except Exception as e:
        print(f"[Crons Scan] Erreur lors du scan launchd : {e}")

    # 3) Scan GCP Cloud Scheduler Crons
    try:
        cmd = [
            "gcloud", "scheduler", "jobs", "list",
            f"--location={DEFAULT_GCP_LOCATION}",
            f"--project={DEFAULT_GCP_PROJECT}",
            "--format=json"
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            gcp_jobs = json.loads(r.stdout)
            for job in gcp_jobs:
                full_name = job.get("name", "")
                name = full_name.split("/")[-1] if "/" in full_name else full_name
                schedule_expr = job.get("schedule", "")
                state = job.get("state", "DISABLED")
                enabled = (state == "ENABLED")
                
                # Statut
                status = "active" if enabled else "paused"
                
                last_run = job.get("lastAttemptTime")
                next_run = job.get("scheduleTime")
                
                uri = job.get("httpTarget", {}).get("uri")
                service_account = job.get("httpTarget", {}).get("oauthToken", {}).get("serviceAccountEmail")

                crons.append({
                    "id": f"gcp-{name}",
                    "name": name,
                    "source": "gcp",
                    "schedule": schedule_expr,
                    "enabled": enabled,
                    "status": status,
                    "last_run": last_run,
                    "next_run": next_run,
                    "details": {
                        "project": DEFAULT_GCP_PROJECT,
                        "location": DEFAULT_GCP_LOCATION,
                        "uri": uri,
                        "service_account": service_account,
                        "raw_name": full_name
                    }
                })
    except Exception as e:
        print(f"[Crons Scan] Erreur lors du scan GCP Scheduler : {e}")

    # Tri par source puis par nom
    crons.sort(key=lambda x: (x["source"], x["name"].lower()))

    # Sauvegarde dans le registre local (JSON)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "crons": crons
    }
    _write_json_atomic(registry_path(), payload)
    local_db.replace_crons(crons)

    return crons


def get_cron_logs(cron_id: str) -> list[dict[str, Any]]:
    """Récupère l'historique et le contenu des logs pour un cron spécifique."""
    runs = local_db.load_cron_runs(cron_id)
    
    other_runs: list[dict[str, Any]] = []

    if cron_id.startswith("hermes-"):
        # Source Hermes : lecture des fichiers Markdown de sorties
        job_id = cron_id.replace("hermes-", "")
        output_dir = Path.home() / ".hermes" / "cron" / "output" / job_id
        if output_dir.is_dir():
            try:
                for file in sorted(output_dir.iterdir(), key=lambda f: f.name, reverse=True):
                    if file.is_file() and file.suffix == ".md":
                        dt_part = file.stem.replace("_", " ").replace("-", ":")
                        if len(dt_part) >= 19:
                            dt_part = dt_part[:10] + " " + dt_part[11:].replace(":", "-", 2)
                        
                        content = file.read_text(encoding="utf-8")
                        other_runs.append({
                            "timestamp": dt_part,
                            "status": "ok",
                            "content": content
                        })
            except Exception as e:
                print(f"[Crons Logs] Erreur lecture logs Hermes {job_id} : {e}")

    elif cron_id.startswith("launchd-"):
        label = cron_id.replace("launchd-", "", 1)
        cron = next((c for c in load_cached_crons() if c.get("id") == cron_id), None)
        details = cron.get("details", {}) if cron else {}
        job_arg = str(details.get("job_arg") or label)
        run_status = _read_launchd_run_status(job_arg)
        stdout_tail = _tail_text(details.get("stdout_path") or run_status.get("stdout_path"))
        stderr_tail = _tail_text(details.get("stderr_path") or run_status.get("stderr_path"))
        status = str((run_status.get("result") or (cron or {}).get("status") or "unknown"))
        timestamp = str(run_status.get("finished_at") or datetime.now(timezone.utc).isoformat())
        content = (
            f"# launchd Zab Cron: {label}\n\n"
            f"**Status:** {status.upper()}\n"
            f"**Schedule:** {(cron or {}).get('schedule', 'unknown')}\n"
            f"**Last Run:** {run_status.get('finished_at') or 'never'}\n"
            f"**Exit Code:** {run_status.get('exit_code', 'n/a')}\n"
            f"**Plist:** {details.get('plist_path', 'unknown')}\n\n"
            "## Last Status JSON\n\n"
            "```json\n"
            + json.dumps(run_status or {}, indent=2, ensure_ascii=False)
            + "\n```\n\n"
            "## stdout tail\n\n"
            "```text\n"
            + (stdout_tail or "(empty)")
            + "\n```\n\n"
            "## stderr tail\n\n"
            "```text\n"
            + (stderr_tail or "(empty)")
            + "\n```\n"
        )
        other_runs.append({
            "timestamp": timestamp,
            "status": status,
            "content": content,
        })

    elif cron_id.startswith("gcp-"):
        # Source GCP Cloud Run : exécution de gcloud logging read
        job_name = cron_id.replace("gcp-", "")
        job_target = job_name
        if "danm-watchdog" in job_name:
            job_target = "danm-watchdog"
        elif "document-registry-refresh" in job_name:
            job_target = "document-registry-refresh"

        try:
            cmd = [
                "gcloud", "logging", "read",
                f'resource.type="cloud_run_job" AND resource.labels.job_name="{job_target}"',
                "--limit=100",
                "--format=json",
                f"--project={DEFAULT_GCP_PROJECT}"
            ]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            if r.returncode == 0:
                log_entries = json.loads(r.stdout)
                execution_groups: dict[str, list[dict[str, Any]]] = {}
                for entry in log_entries:
                    labels = entry.get("labels", {})
                    exec_name = labels.get("run.googleapis.com/execution_name") or entry.get("insertId", "unknown")[:15]
                    
                    if exec_name not in execution_groups:
                        execution_groups[exec_name] = []
                    execution_groups[exec_name].append(entry)

                sorted_groups = []
                for exec_id, entries in execution_groups.items():
                    entries.sort(key=lambda x: x.get("timestamp", ""))
                    earliest_ts = entries[0].get("timestamp", "")
                    sorted_groups.append((earliest_ts, exec_id, entries))
                
                sorted_groups.sort(key=lambda x: x[0], reverse=True)

                for ts, exec_id, entries in sorted_groups[:15]:
                    lines: list[str] = []
                    severity = "INFO"
                    
                    for entry in entries:
                        payload_msg = entry.get("textPayload") or ""
                        if not payload_msg and isinstance(entry.get("jsonPayload"), dict):
                            payload_msg = entry["jsonPayload"].get("message") or str(entry["jsonPayload"])
                        
                        ts_raw = entry.get("timestamp", "")
                        ts_disp = ts_raw[11:19] if len(ts_raw) >= 19 else ts_raw
                        
                        sev = entry.get("severity", "INFO")
                        if sev in ("ERROR", "CRITICAL"):
                            severity = "ERROR"
                        elif sev == "WARNING" and severity != "ERROR":
                            severity = "WARNING"

                        if payload_msg:
                            lines.append(f"[{ts_disp}] [{sev}] {payload_msg}")

                    status = "ok"
                    if severity == "ERROR":
                        status = "error"
                    elif severity == "WARNING":
                        status = "warning"

                    formatted_content = (
                        f"# Cloud Run Job Execution: {exec_id}\n\n"
                        f"**Job Target:** {job_target}\n"
                        f"**Execution Timestamp:** {ts}\n"
                        f"**Status:** {status.upper()}\n\n"
                        f"## Execution Logs\n\n"
                        "```text\n" + "\n".join(lines) + "\n```"
                    )

                    other_runs.append({
                        "timestamp": ts,
                        "status": status,
                        "content": formatted_content
                    })
        except Exception as e:
            print(f"[Crons Logs] Erreur lors de la récupération des logs GCP {job_name} : {e}")

    # Fusionner sans doublonner sur le timestamp
    seen_timestamps = {r["timestamp"].replace("Z", "")[:19] for r in runs}
    for r in other_runs:
        ts_clean = r["timestamp"].replace("Z", "").replace("T", " ")[:19]
        if not any(ts_clean in existing.replace("Z", "").replace("T", " ")[:19] for existing in seen_timestamps):
            runs.append(r)

    # Trier par date décroissante
    runs.sort(key=lambda x: x["timestamp"], reverse=True)
    return runs


def run_cron_now(cron_id: str) -> dict[str, Any]:
    """Déclenche immédiatement l'exécution d'un cron et archive le rapport dans Postgres."""
    if cron_id.startswith("hermes-"):
        job_id = cron_id.replace("hermes-", "")
        try:
            crons = load_cached_crons()
            job_name = job_id
            for c in crons:
                if c["id"] == cron_id:
                    job_name = c["name"]
                    break

            cmd = ["hermes", "cron", "run", job_id, "--accept-hooks"]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            
            status = "ok" if r.returncode == 0 else "error"
            content = (
                f"# Manual Hermes Run: {job_name}\n\n"
                f"**Triggered At:** {datetime.now(timezone.utc).isoformat()}\n"
                f"**Job Target ID:** {job_id}\n"
                f"**Status:** {status.upper()}\n\n"
                f"## Standard Output (stdout)\n```text\n{r.stdout or '(vide)'}\n```\n\n"
                f"## Error Output (stderr)\n```text\n{r.stderr or '(vide)'}\n```\n"
            )
            
            local_db.save_cron_run(cron_id, status, content, r.stdout, r.stderr)
            
            if r.returncode == 0:
                scan_and_save_crons()
                return {"success": True, "stdout": r.stdout, "stderr": r.stderr}
            else:
                return {"success": False, "error": f"Exit code {r.returncode}", "stdout": r.stdout, "stderr": r.stderr}
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif cron_id.startswith("launchd-"):
        label = cron_id.replace("launchd-", "", 1)
        try:
            crons = load_cached_crons()
            cron = next((c for c in crons if c.get("id") == cron_id), None)
            details = cron.get("details", {}) if cron else {}
            job_arg = str(details.get("job_arg") or "")
            if not job_arg:
                return {"success": False, "error": f"Impossible de trouver l'argument job launchd pour {label}"}

            script = user_home() / ".hermes" / "scripts" / "zab_launchd_run.sh"
            r = subprocess.run([str(script), job_arg], capture_output=True, text=True, timeout=900)

            status = "ok" if r.returncode == 0 else "error"
            content = (
                f"# Manual launchd-compatible Zab Run: {label}\n\n"
                f"**Triggered At:** {datetime.now(timezone.utc).isoformat()}\n"
                f"**Job Arg:** {job_arg}\n"
                f"**Status:** {status.upper()}\n\n"
                f"## Standard Output (stdout)\n```text\n{r.stdout or '(vide)'}\n```\n\n"
                f"## Error Output (stderr)\n```text\n{r.stderr or '(vide)'}\n```\n"
            )
            local_db.save_cron_run(cron_id, status, content, r.stdout, r.stderr)
            scan_and_save_crons()
            if r.returncode == 0:
                return {"success": True, "stdout": r.stdout, "stderr": r.stderr}
            return {"success": False, "error": f"Exit code {r.returncode}", "stdout": r.stdout, "stderr": r.stderr}
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif cron_id.startswith("gcp-"):
        job_name = cron_id.replace("gcp-", "")
        try:
            cmd = [
                "gcloud", "scheduler", "jobs", "run", job_name,
                f"--location={DEFAULT_GCP_LOCATION}",
                f"--project={DEFAULT_GCP_PROJECT}"
            ]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            status = "ok" if r.returncode == 0 else "error"
            content = (
                f"# Manual GCP Cloud Scheduler Run: {job_name}\n\n"
                f"**Triggered At:** {datetime.now(timezone.utc).isoformat()}\n"
                f"**Status:** {status.upper()}\n\n"
                f"## Subprocess Execution Output (stdout)\n```text\n{r.stdout or '(vide)'}\n```\n\n"
                f"## Subprocess Error Output (stderr)\n```text\n{r.stderr or '(vide)'}\n```\n"
            )
            
            local_db.save_cron_run(cron_id, status, content, r.stdout, r.stderr)
            
            if r.returncode == 0:
                scan_and_save_crons()
                return {"success": True, "stdout": r.stdout, "stderr": r.stderr}
            else:
                return {"success": False, "error": f"Exit code {r.returncode}", "stdout": r.stdout, "stderr": r.stderr}
        except Exception as e:
            return {"success": False, "error": str(e)}

    return {"success": False, "error": "Source de cron inconnue"}
