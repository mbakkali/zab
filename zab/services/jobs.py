"""Exécution de jobs shell (smoke, pytest, scripts) avec logs pour SSE."""

from __future__ import annotations

import queue
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from zab.paths import mehdi_context_root, skills_root_from_config_file_only


JobStatus = Literal["queued", "running", "done", "error", "cancelled"]


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
        }


def _reader(stream: Any, q: queue.Queue[str | None], label: str) -> None:
    try:
        for line in iter(stream.readline, ""):
            if not line:
                break
            q.put(f"[{label}] {line.rstrip()}")
    finally:
        stream.close()


def build_argv_for_preset(
    preset: str,
    extra: dict[str, Any] | None = None,
) -> tuple[list[str], str]:
    """Retourne (argv, cwd). Lève ValueError si preset ou args invalides."""
    extra = extra or {}
    if preset == "mempalace_install":
        return (["uv", "tool", "install", "mempalace"], str(Path.home()))
    root_opt = skills_root_from_config_file_only()
    if root_opt is None:
        raise ValueError(
            "skills_root doit être défini dans ~/.config/zab/config.yaml pour exécuter ce job depuis le dashboard."
        )
    root = root_opt
    scripts = root / "scripts"
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
            try:
                job._proc = subprocess.Popen(
                    argv,
                    cwd=cwd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )
                assert job._proc.stdout and job._proc.stderr
                t_out = threading.Thread(
                    target=_reader,
                    args=(job._proc.stdout, job.lines, "stdout"),
                    daemon=True,
                )
                t_err = threading.Thread(
                    target=_reader,
                    args=(job._proc.stderr, job.lines, "stderr"),
                    daemon=True,
                )
                t_out.start()
                t_err.start()
                code = job._proc.wait(timeout=3600)
                t_out.join(timeout=5)
                t_err.join(timeout=5)
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
