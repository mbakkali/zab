#!/usr/bin/env python3
"""
Enchaîne des ``mempalace mine`` — séquentiel sur le palace par défaut, ou **parallèle**
avec un **palace shard** par job (``mempalace --palace …``), car un seul writer est
autorisé sur un même répertoire palace.

Sources :
  - projets uniques issus de ``zab projects list --json`` (modes projects + convos) ;
  - chaque sous-dossier de ``~/.claude/projects`` (mode convos, Claude Code) ;
  - ``~/.codex`` (mode convos, Codex CLI) ;
  - ``~/Library/Application Support/Cursor/User/workspaceStorage`` (mode convos, Cursor UI).

Usage ::
  uv run python scripts/mempalace_batch_mine.py
  uv run python scripts/mempalace_batch_mine.py --dry-run
  uv run python scripts/mempalace_batch_mine.py --parallel 6 --shard-run ma-vague

Les shards vont sous ``~/.local/share/zab/mempalace-shards/<shard-run>/<clé>/``.
Le MCP MemPalace par défaut lit ``~/.mempalace/palace`` : les shards ne s’y mélangent pas
tant que tu ne pointes pas ``mempalace-mcp --palace`` vers un shard ou que tu ne fusionnes pas.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _data_dir() -> Path:
    xdg = Path(os.environ.get("XDG_DATA_HOME", "~/.local/share")).expanduser().resolve()
    d = xdg / "zab"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _log(msg: str, log_fp, *, lock: threading.Lock | None = None, also_print: bool = True) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}\n"
    if lock:
        with lock:
            log_fp.write(line)
            log_fp.flush()
    else:
        log_fp.write(line)
        log_fp.flush()
    if also_print:
        print(msg, flush=True)


def _wing_from_path(p: Path) -> str:
    try:
        rel = p.expanduser().resolve().relative_to(Path.home())
        return str(rel).replace("/", "__").replace(" ", "_")
    except ValueError:
        return p.resolve().name.replace(" ", "_")


def _job_key(directory: Path, mode: str, wing: str) -> str:
    raw = f"{directory.resolve()}|{mode}|{wing}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class MineJob:
    directory: Path
    mode: str
    wing: str
    agent: str

    @property
    def key(self) -> str:
        return _job_key(self.directory, self.mode, self.wing)


def _run_mine(
    directory: Path,
    *,
    mode: str,
    wing: str,
    agent: str,
    palace: Path | None,
    dry_run: bool,
    log_fp,
    log_lock: threading.Lock | None = None,
) -> int:
    directory = directory.expanduser().resolve()
    if not directory.is_dir():
        _log(f"SKIP (pas un dossier): {directory}", log_fp, lock=log_lock)
        return 0
    argv: list[str] = ["mempalace"]
    if palace is not None:
        argv.extend(["--palace", str(palace)])
    argv.extend(
        [
            "mine",
            str(directory),
            "--mode",
            mode,
            "--wing",
            wing,
            "--agent",
            agent,
        ]
    )
    _log(f"RUN {' '.join(argv)}", log_fp, lock=log_lock)
    if dry_run:
        return 0
    proc = subprocess.run(argv, text=True, timeout=86400)
    if proc.returncode != 0:
        _log(f"!! exit {proc.returncode} pour {directory} ({mode})", log_fp, lock=log_lock)
    return proc.returncode


def _zab_projects_json(repo_root: Path) -> list[dict]:
    proc = subprocess.run(
        ["uv", "run", "zab", "projects", "list", "--json"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or "zab projects list failed")
    data = json.loads(proc.stdout)
    if not isinstance(data, list):
        raise RuntimeError("unexpected JSON from zab projects")
    return data


def _collect_jobs(args: argparse.Namespace, repo_root: Path, log_fp, log_lock: threading.Lock | None) -> list[MineJob]:
    jobs: list[MineJob] = []

    rows = _zab_projects_json(repo_root)
    seen_paths: set[str] = set()
    projects: list[tuple[str, Path]] = []
    for r in rows:
        raw = r.get("path")
        if not raw or not isinstance(raw, str):
            continue
        p = Path(raw).expanduser().resolve()
        key = str(p)
        if key in seen_paths:
            continue
        seen_paths.add(key)
        projects.append((str(r.get("name") or p.name), p))

    _log(f"{len(projects)} projet(s) zab unique(s)", log_fp, lock=log_lock)
    for _name, p in projects:
        w = _wing_from_path(p)
        if not args.skip_projects_code:
            jobs.append(MineJob(directory=p, mode="projects", wing=w, agent="zab-batch"))
        jobs.append(MineJob(directory=p, mode="convos", wing=f"{w}__convos", agent="zab-batch"))

    claude_root = Path.home() / ".claude" / "projects"
    if claude_root.is_dir():
        subs = sorted([x for x in claude_root.iterdir() if x.is_dir() and not x.name.startswith(".")])
        _log(f"{len(subs)} dossier(s) Claude Code sous {claude_root}", log_fp, lock=log_lock)
        for sub in subs:
            w = "claude__" + sub.name.replace(" ", "_")
            jobs.append(MineJob(directory=sub, mode="convos", wing=w, agent="zab-batch-claude"))

    codex_home = Path.home() / ".codex"
    if codex_home.is_dir():
        jobs.append(MineJob(directory=codex_home, mode="convos", wing="codex__home", agent="zab-batch-codex"))

    if not args.skip_cursor_workspace:
        ws = Path.home() / "Library" / "Application Support" / "Cursor" / "User" / "workspaceStorage"
        if ws.is_dir():
            jobs.append(
                MineJob(
                    directory=ws,
                    mode="convos",
                    wing="cursor__workspaceStorage",
                    agent="zab-batch-cursor",
                )
            )
        else:
            _log(f"SKIP Cursor workspaceStorage (absent): {ws}", log_fp, lock=log_lock)

    return jobs


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch mempalace mine (zab + Claude + Codex + Cursor)")
    parser.add_argument("--dry-run", action="store_true", help="Affiche les commandes sans exécuter mempalace")
    parser.add_argument(
        "--skip-cursor-workspace",
        action="store_true",
        help="Ne pas miner Cursor workspaceStorage (très volumineux)",
    )
    parser.add_argument(
        "--skip-projects-code",
        action="store_true",
        help="Ne pas miner les projets zab en mode projects (seulement convos)",
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=1,
        metavar="N",
        help="Nombre de mines concurrents ; >1 impose un palace shard par job (voir --shard-run)",
    )
    parser.add_argument(
        "--shard-run",
        type=str,
        default="",
        help="Nom du sous-dossier sous mempalace-shards/ (défaut : horodatage UTC)",
    )
    parser.add_argument(
        "--shard-root",
        type=str,
        default="",
        help="Racine absolue des shards (rare ; défaut : ~/.local/share/zab/mempalace-shards/<shard-run>)",
    )
    args = parser.parse_args()

    if args.parallel < 1:
        print("--parallel doit être >= 1", file=sys.stderr)
        return 1
    if args.parallel > 1 and args.dry_run:
        print("Note : dry-run avec --parallel affiche les palaces shards prévus.", flush=True)

    if not shutil.which("mempalace"):
        print("mempalace absent du PATH — uv tool install mempalace", file=sys.stderr)
        return 1

    log_path = _data_dir() / "mempalace-batch.log"
    repo_root = _repo_root()
    log_lock = threading.Lock()

    shard_parent = Path(args.shard_root).expanduser().resolve() if args.shard_root.strip() else _data_dir() / "mempalace-shards"
    run_name = args.shard_run.strip() or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    shard_root = shard_parent / run_name

    failures = 0
    with log_path.open("a", encoding="utf-8") as log_fp:
        _log("======== batch start ========", log_fp, lock=log_lock)
        _log(
            f"dry_run={args.dry_run} parallel={args.parallel} shard_root={shard_root} repo={repo_root}",
            log_fp,
            lock=log_lock,
        )

        try:
            jobs = _collect_jobs(args, repo_root, log_fp, log_lock)
        except Exception as exc:
            _log(f"!! collect jobs: {exc}", log_fp, lock=log_lock)
            return 1

        _log(f"{len(jobs)} job(s) au total", log_fp, lock=log_lock)

        if args.parallel == 1:
            for job in jobs:
                failures += (
                    _run_mine(
                        job.directory,
                        mode=job.mode,
                        wing=job.wing,
                        agent=job.agent,
                        palace=None,
                        dry_run=args.dry_run,
                        log_fp=log_fp,
                        log_lock=log_lock,
                    )
                    != 0
                )
        else:
            shard_root.mkdir(parents=True, exist_ok=True)
            manifest = shard_root / "jobs-manifest.json"
            if not args.dry_run:
                manifest.write_text(
                    json.dumps(
                        [
                            {
                                "key": j.key,
                                "directory": str(j.directory.resolve()),
                                "mode": j.mode,
                                "wing": j.wing,
                                "palace": str((shard_root / j.key).resolve()),
                            }
                            for j in jobs
                        ],
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                _log(f"Manifeste shards : {manifest}", log_fp, lock=log_lock)

            def _worker(job: MineJob) -> tuple[str, int]:
                palace_dir = shard_root / job.key
                palace_dir.mkdir(parents=True, exist_ok=True)
                code = _run_mine(
                    job.directory,
                    mode=job.mode,
                    wing=job.wing,
                    agent=job.agent,
                    palace=palace_dir,
                    dry_run=args.dry_run,
                    log_fp=log_fp,
                    log_lock=log_lock,
                )
                return (job.key, code)

            with ThreadPoolExecutor(max_workers=args.parallel) as ex:
                futures = [ex.submit(_worker, j) for j in jobs]
                for fut in as_completed(futures):
                    try:
                        _key, code = fut.result()
                        if code != 0:
                            failures += 1
                    except Exception as exc:
                        failures += 1
                        _log(f"!! worker exception: {exc}", log_fp, lock=log_lock)

        _log(f"======== batch end (failures_flag={failures}) log={log_path} ========", log_fp, lock=log_lock)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
