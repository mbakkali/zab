"""Exécution de jobs shell (smoke, pytest, scripts) avec logs pour SSE."""

from __future__ import annotations

import os
import queue
import shutil
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from zab.paths import data_dir, mehdi_context_root, skills_root_from_config_file_only, zab_package_dir, zab_repo_root
from zab.services.mempalace_mine_projects_docs import resolve_mempalace_interpreter
from zab.services.workspace_projects import project_dir_is_under_projects_roots


JobStatus = Literal["queued", "running", "done", "error", "cancelled"]


def _which_or_raise(binary: str, install_hint: str) -> str:
    found = shutil.which(binary)
    if not found:
        raise ValueError(f"{binary} introuvable sur le PATH. {install_hint}")
    return found

# MemPalace n'autorise qu'un writer sur ~/.mempalace/palace ; on sérialise les jobs dashboard.
_MEMPALACE_PALACE_LOCK = threading.Lock()


@dataclass
class Job:
    id: str
    preset: str
    status: JobStatus = "queued"
    exit_code: int | None = None
    error: str | None = None
    argv: list[str] = field(default_factory=list)
    cwd: str = ""
    lines: queue.Queue[str | None] = field(default_factory=queue.Queue)
    output_lines: list[str] = field(default_factory=list)
    report_path: str | None = None
    _proc: subprocess.Popen[str] | None = None

    def to_summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "preset": self.preset,
            "status": self.status,
            "exit_code": self.exit_code,
            "error": self.error,
            "argv": self.argv,
            "cwd": self.cwd,
            "report_path": self.report_path,
        }


def _reader(stream: Any, q: queue.Queue[str | None], output_lines: list[str], label: str) -> None:
    try:
        for line in iter(stream.readline, ""):
            if not line:
                break
            formatted = f"[{label}] {line.rstrip()}"
            output_lines.append(formatted)
            q.put(formatted)
    finally:
        stream.close()


def _security_report_dir() -> Path:
    p = data_dir() / "security-last"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _security_report_key(job: Job) -> str:
    raw = job.preset
    if job.cwd:
        raw = f"{raw}-{Path(job.cwd).name}"
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in raw).strip("-") or job.preset


def _write_security_report(job: Job) -> None:
    if not job.preset.startswith("security_"):
        return
    report = _security_report_dir() / f"{_security_report_key(job)}.json"
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "summary": job.to_summary(),
        "lines": job.output_lines,
    }
    import json

    report.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    job.report_path = str(report)


def list_security_reports() -> list[dict[str, Any]]:
    root = _security_report_dir()
    rows: list[dict[str, Any]] = []
    for p in sorted(root.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            rows.append(
                {
                    "key": p.stem,
                    "path": str(p),
                    "updated_at_utc": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(),
                    "bytes": p.stat().st_size,
                }
            )
        except OSError:
            continue
    return rows


def read_security_report(key: str | None = None) -> dict[str, Any]:
    root = _security_report_dir()
    target: Path | None = None
    if key:
        safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in key).strip("-")
        candidate = root / f"{safe}.json"
        if candidate.is_file():
            target = candidate
    else:
        reports = sorted(root.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)
        target = reports[0] if reports else None
    if target is None:
        return {"present": False}
    import json

    return {"present": True, "key": target.stem, **json.loads(target.read_text(encoding="utf-8"))}


def _project_path_from_extra(extra: dict[str, Any], preset: str) -> Path:
    raw = extra.get("project_path")
    if not raw or not isinstance(raw, str):
        raise ValueError(f"{preset} requiert project_path (chaîne)")
    p = Path(raw).expanduser().resolve()
    if not p.is_dir():
        raise ValueError(f"Dossier projet introuvable : {p}")
    if not project_dir_is_under_projects_roots(p):
        raise ValueError("project_path doit être un projet sous projects_roots (1 ou 2 niveaux)")
    return p


def build_argv_for_preset(
    preset: str,
    extra: dict[str, Any] | None = None,
) -> tuple[list[str], str]:
    """Retourne (argv, cwd). Lève ValueError si preset ou args invalides."""
    extra = extra or {}
    if preset == "conversation_sync":
        zroot = zab_package_dir().parent
        argv = ["uv", "run", "python", "-m", "zab.services.conversation_sync"]
        if extra.get("dry_run"):
            argv.append("--dry-run")
        if extra.get("append"):
            argv.append("--append")
        if extra.get("with_mempalace"):
            argv.append("--with-mempalace")
        if extra.get("workspace_storage_cursor"):
            argv.append("--workspace-storage-cursor")
        prov = extra.get("providers")
        if isinstance(prov, list) and prov:
            argv.extend(["--providers", ",".join(str(x) for x in prov)])
        elif isinstance(prov, str) and prov.strip():
            argv.extend(["--providers", prov.strip()])
        bid = extra.get("batch_id")
        if isinstance(bid, str) and bid.strip():
            argv.extend(["--batch-id", bid.strip()])
        return (argv, str(zroot))
    if preset == "mempalace_install":
        return (["uv", "tool", "install", "mempalace"], str(Path.home()))
    if preset == "mempalace_mine":
        p = _project_path_from_extra(extra, preset)
        mode = extra.get("mode", "projects")
        if mode not in ("projects", "convos"):
            raise ValueError("mode doit être projects ou convos")
        wing_raw = extra.get("wing")
        if mode == "projects":
            interp = resolve_mempalace_interpreter()
            if interp:
                argv = [interp, "-m", "zab.services.mempalace_mine_projects_docs", str(p)]
                if isinstance(wing_raw, str) and wing_raw.strip():
                    argv.extend(["--wing", wing_raw.strip()])
                return (argv, str(p))
        argv = ["mempalace", "mine", str(p), "--mode", str(mode)]
        if isinstance(wing_raw, str) and wing_raw.strip():
            argv.extend(["--wing", wing_raw.strip()])
        return (argv, str(p))
    if preset == "security_osv_zab":
        zroot = zab_repo_root()
        exe = _which_or_raise(
            "osv-scanner",
            "Installez OSV-Scanner (ex. brew install osv-scanner) — https://google.github.io/osv-scanner/",
        )
        return ([exe, "-r", "."], str(zroot))
    if preset == "security_npm_audit_zab_ui":
        ui = zab_repo_root() / "zab-ui"
        if not ui.is_dir():
            raise ValueError(f"Dossier zab-ui introuvable : {ui} (clone du dépôt zab attendu)")
        npm = _which_or_raise("npm", "Installez Node.js / npm.")
        return ([npm, "audit"], str(ui))
    if preset == "security_gitleaks_zab":
        zroot = zab_repo_root()
        exe = _which_or_raise("gitleaks", "Installez Gitleaks (ex. brew install gitleaks).")
        return ([exe, "detect", "--source", str(zroot), "--redact", "-v"], str(zroot))
    if preset == "security_pip_audit_zab":
        zroot = zab_repo_root()
        uv = _which_or_raise("uv", "Installez uv pour exécuter pip-audit dans l’environnement du projet.")
        return ([uv, "run", "--with", "pip-audit", "pip-audit"], str(zroot))
    if preset == "security_osv_project":
        p = _project_path_from_extra(extra, preset)
        exe = _which_or_raise(
            "osv-scanner",
            "Installez OSV-Scanner (ex. brew install osv-scanner) — https://google.github.io/osv-scanner/",
        )
        return ([exe, "-r", "."], str(p))
    if preset == "security_npm_audit_project":
        p = _project_path_from_extra(extra, preset)
        if not (p / "package.json").is_file():
            raise ValueError(f"package.json introuvable dans : {p}")
        npm = _which_or_raise("npm", "Installez Node.js / npm.")
        return ([npm, "audit"], str(p))
    if preset == "security_gitleaks_project":
        p = _project_path_from_extra(extra, preset)
        exe = _which_or_raise("gitleaks", "Installez Gitleaks (ex. brew install gitleaks).")
        return ([exe, "detect", "--source", str(p), "--redact", "-v"], str(p))
    if preset == "flowmetrik_openwebui_compose_up":
        p = _project_path_from_extra(extra, preset)
        _which_or_raise("docker", "Installez Docker (Docker Desktop ou docker CLI avec le plugin compose v2).")
        if not (p / "docker-compose.yml").is_file():
            raise ValueError(f"docker-compose.yml introuvable dans : {p}")
        return (
            ["docker", "compose", "up", "-d", "--build"],
            str(p),
        )
    if preset == "flowmetrik_openwebui_compose_down":
        p = _project_path_from_extra(extra, preset)
        _which_or_raise("docker", "Installez Docker (Docker Desktop ou docker CLI avec le plugin compose v2).")
        return (
            ["docker", "compose", "down"],
            str(p),
        )
    root_opt = skills_root_from_config_file_only()
    if root_opt is None:
        raise ValueError(
            "skills_root doit être défini dans ~/.config/zab/config.yaml pour exécuter ce job depuis le dashboard."
        )
    root = root_opt
    scripts = root / "scripts"
    if preset == "security_osv_skills":
        exe = _which_or_raise(
            "osv-scanner",
            "Installez OSV-Scanner (ex. brew install osv-scanner) — https://google.github.io/osv-scanner/",
        )
        return ([exe, "-r", "."], str(root.resolve()))
    if preset == "smoke_mcps":
        return (
            ["bash", str(scripts / "smoke_test_all_mcps.sh")],
            str(root),
        )
    if preset == "gateway_pytest":
        gw = root / "mcps" / "flowmetrik-gateway"
        return (
            ["bash", "-c", "uv sync --all-groups -q && uv run pytest tests/ -v"],
            str(gw),
        )
    if preset == "sync_mcps_litellm":
        return (
            ["bash", str(scripts / "sync-mcps-to-litellm.sh")],
            str(root),
        )
    if preset == "build_plugins":
        return (["bash", str(root / "build-plugins.sh")], str(root))
    if preset == "google_oauth_mehdi_context":
        ctx = mehdi_context_root()
        script = ctx / "scripts" / "generate_context.py"
        if not script.is_file():
            raise ValueError(f"Script absent : {script}")
        return (
            ["uv", "run", "python", str(script), "--google-login"],
            str(ctx),
        )
    if preset == "memory_import":
        raw = extra.get("jsonl_path")
        if not raw or not isinstance(raw, str):
            raise ValueError("memory_import requiert jsonl_path (chaîne)")
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = (root / raw).resolve()
        else:
            p = p.resolve()
        try:
            p.relative_to(root)
        except ValueError:
            try:
                p.relative_to(Path.home())
            except ValueError as exc:
                raise ValueError("jsonl_path doit être sous le repo skills ou $HOME") from exc
        if not p.is_file():
            raise ValueError(f"Fichier introuvable : {p}")
        if not str(p).lower().endswith(".jsonl"):
            raise ValueError("Le fichier doit se terminer par .jsonl")
        imp = scripts / "import_memory_jsonl.py"
        return (
            ["uv", "run", "python", str(imp), str(p)],
            str(root),
        )
    raise ValueError(f"preset inconnu : {preset}")


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def start(
        self,
        preset: str,
        extra: dict[str, Any] | None = None,
    ) -> Job:
        argv, cwd = build_argv_for_preset(preset, extra)
        jid = uuid.uuid4().hex[:12]
        job = Job(id=jid, preset=preset, argv=argv, cwd=cwd)
        self._jobs[jid] = job

        def run() -> None:
            job.status = "running"
            palace_lock_held = False
            try:
                if job.preset == "mempalace_mine":
                    job.lines.put(
                        "[zab] Le palace MemPalace par défaut (~/.mempalace/palace) n’accepte qu’un seul "
                        "« mine » à la fois. Attente si une autre indexation (zab ou terminal) est en cours…"
                    )
                    _MEMPALACE_PALACE_LOCK.acquire()
                    palace_lock_held = True
                    job.lines.put("[zab] Verrou palace côté zab acquis — démarrage de mempalace mine.")
                run_env = os.environ.copy()
                if any("mempalace_mine_projects_docs" in str(x) for x in argv) or any(
                    "zab.services.conversation_sync" in str(x) for x in argv
                ):
                    root = str(zab_package_dir().parent)
                    prev = run_env.get("PYTHONPATH", "")
                    run_env["PYTHONPATH"] = f"{root}{os.pathsep}{prev}" if prev.strip() else root
                job._proc = subprocess.Popen(
                    argv,
                    cwd=cwd,
                    env=run_env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )
                assert job._proc.stdout and job._proc.stderr
                t_out = threading.Thread(
                    target=_reader,
                    args=(job._proc.stdout, job.lines, job.output_lines, "stdout"),
                    daemon=True,
                )
                t_err = threading.Thread(
                    target=_reader,
                    args=(job._proc.stderr, job.lines, job.output_lines, "stderr"),
                    daemon=True,
                )
                t_out.start()
                t_err.start()
                code = job._proc.wait(timeout=3600)
                t_out.join(timeout=5)
                t_err.join(timeout=5)
                if job.preset == "mempalace_install" and code != 0 and shutil.which("mempalace"):
                    job.lines.put(
                        "[zab] mempalace est déjà disponible sur le PATH — "
                        "le code de sortie de uv est ignoré (souvent « déjà installé » selon la version d’uv)."
                    )
                    code = 0
                job.exit_code = code
                job.status = "done" if code == 0 else "error"
            except subprocess.TimeoutExpired:
                if job._proc:
                    job._proc.kill()
                job.status = "error"
                job.exit_code = -1
                job.error = "timeout"
            except Exception as e:  # noqa: BLE001
                job.status = "error"
                job.error = str(e)
            finally:
                try:
                    _write_security_report(job)
                except Exception as e:  # noqa: BLE001
                    job.lines.put(f"[zab] Rapport sécurité non persisté : {e}")
                if palace_lock_held:
                    _MEMPALACE_PALACE_LOCK.release()
                job.lines.put(None)

        threading.Thread(target=run, daemon=True).start()
        return job

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job or job.status not in ("queued", "running"):
            return False
        if job._proc and job._proc.poll() is None:
            job._proc.terminate()
            try:
                job._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                job._proc.kill()
        job.status = "cancelled"
        job.lines.put(None)
        return True

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)


store = JobStore()
