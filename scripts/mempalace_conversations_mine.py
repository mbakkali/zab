#!/usr/bin/env python3
"""Mine only agent conversations and agent context artifacts into MemPalace.

This intentionally avoids full source repositories. It targets Cursor agent
transcripts, Claude/Codex/Kimi session history, and small context directories
such as plans, rules and skills.
"""

from __future__ import annotations

import subprocess
import sys
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


PALACE = Path.home() / ".local/share/zab/mempalace-conversations"
LOG = Path.home() / ".local/share/zab/mempalace-context.log"
LOCK_TEXT = "is held by PID"
MAX_RETRIES = 20


@dataclass(frozen=True)
class Job:
    path: Path
    wing: str
    mode: str
    agent: str


def wing(text: str) -> str:
    return text.replace("/", "__").replace(" ", "_").replace(".", "_")


def log(message: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now(timezone.utc).isoformat()} {message}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fp:
        fp.write(line + "\n")


def run_mempalace_with_retry(argv: list[str], job: Job) -> int:
    """Run mempalace, retrying when the palace lock is still being released."""
    delay = 2.0
    for attempt in range(1, MAX_RETRIES + 1):
        proc = subprocess.run(argv, text=True, capture_output=True, timeout=86400)
        if proc.stdout:
            print(proc.stdout, end="", flush=True)
        if proc.stderr:
            print(proc.stderr, end="", file=sys.stderr, flush=True)
        combined = f"{proc.stdout}\n{proc.stderr}"
        if proc.returncode == 0:
            time.sleep(1.5)
            return 0
        if LOCK_TEXT in combined and attempt < MAX_RETRIES:
            log(
                f"LOCK retry={attempt}/{MAX_RETRIES - 1} sleep={delay:.1f}s "
                f"wing={job.wing} dir={job.path}"
            )
            time.sleep(delay)
            delay = min(delay * 1.5, 30.0)
            continue
        return proc.returncode
    return 1


def add(jobs: list[Job], seen: set[tuple[str, str, str]], path: Path, wing_name: str, mode: str, agent: str) -> None:
    p = path.expanduser().resolve()
    key = (str(p), wing_name, mode)
    if key in seen or not p.is_dir():
        return
    seen.add(key)
    jobs.append(Job(path=p, wing=wing_name, mode=mode, agent=agent))


def collect_jobs() -> list[Job]:
    jobs: list[Job] = []
    seen: set[tuple[str, str, str]] = set()

    cursor_root = Path.home() / ".cursor/projects"
    if cursor_root.is_dir():
        for d in sorted(cursor_root.glob("*/agent-transcripts")):
            if any(d.rglob("*.jsonl")):
                add(jobs, seen, d, "cursor_transcripts__" + wing(d.parent.name), "convos", "zab-cursor")
        for kind in ("plans", "rules", "skills"):
            for d in sorted(cursor_root.glob(f"*/{kind}")):
                add(jobs, seen, d, f"cursor_{kind}__" + wing(d.parent.name), "projects", "zab-cursor-context")

    # Project-level Cursor/Claude artifacts under known zab projects only.
    # Avoid recursive scans over ~/projects: some repos are huge and contain
    # vendored trees. `zab projects list` already resolves the intended project set.
    try:
        proc = subprocess.run(
            ["uv", "run", "zab", "projects", "list", "--json"],
            cwd=str(Path(__file__).resolve().parent.parent),
            capture_output=True,
            text=True,
            timeout=120,
        )
        project_rows = json.loads(proc.stdout) if proc.returncode == 0 else []
    except Exception:
        project_rows = []
    seen_project_paths: set[str] = set()
    for row in project_rows if isinstance(project_rows, list) else []:
        raw = row.get("path") if isinstance(row, dict) else None
        if not isinstance(raw, str) or raw in seen_project_paths:
            continue
        seen_project_paths.add(raw)
        project = Path(raw).expanduser()
        try:
            rel = project.resolve().relative_to(Path.home())
            project_key = wing(str(rel))
        except Exception:
            project_key = wing(project.name)
        for marker, label in (
            (".cursor/plans", "project_cursor_plans"),
            (".cursor/rules", "project_cursor_rules"),
            (".cursor/skills", "project_cursor_skills"),
            (".claude/skills", "project_claude_skills"),
        ):
            add(jobs, seen, project / marker, f"{label}__{project_key}", "projects", "zab-project-context")

    claude = Path.home() / ".claude/projects"
    if claude.is_dir():
        for d in sorted(x for x in claude.iterdir() if x.is_dir() and not x.name.startswith(".")):
            add(jobs, seen, d, "claude_transcripts__" + wing(d.name), "convos", "zab-claude")

    codex = Path.home() / ".codex"
    for sub, mode, label in (
        ("sessions", "convos", "codex_sessions"),
        ("rules", "projects", "codex_rules"),
        ("skills", "projects", "codex_skills"),
        ("memories", "projects", "codex_memories"),
    ):
        add(jobs, seen, codex / sub, label, mode, "zab-codex")

    kimi = Path.home() / ".kimi"
    for sub, mode, label in (
        ("user-history", "convos", "kimi_user_history"),
        ("sessions", "convos", "kimi_sessions"),
        ("plans", "projects", "kimi_plans"),
    ):
        add(jobs, seen, kimi / sub, label, mode, "zab-kimi")

    gem = Path.home() / ".gemini"
    if gem.is_dir():
        for sub in ("sessions", "chats", "history", "logs"):
            p = gem / sub
            if p.is_dir():
                add(jobs, seen, p, f"gemini_{sub}", "convos", "zab-gemini")

    hm = Path.home() / ".hermes" / "memories"
    if hm.is_dir():
        add(jobs, seen, hm, "hermes_memories", "projects", "zab-hermes-context")

    return jobs


def main() -> int:
    PALACE.parent.mkdir(parents=True, exist_ok=True)
    jobs = collect_jobs()
    log(f"context batch start palace={PALACE} jobs={len(jobs)}")
    failures = 0
    for job in jobs:
        argv = [
            "mempalace",
            "--palace",
            str(PALACE),
            "mine",
            str(job.path),
            "--mode",
            job.mode,
            "--wing",
            job.wing,
            "--agent",
            job.agent,
        ]
        log("RUN " + " ".join(argv))
        try:
            code = run_mempalace_with_retry(argv, job)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            log(f"EXC {type(exc).__name__}: {exc} dir={job.path}")
            continue
        if code:
            failures += 1
            log(f"FAIL code={code} dir={job.path}")
    log(f"context batch end failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
