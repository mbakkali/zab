"""Synchronisation Git explicite pour le dépôt de skills."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from zab.user_config import skills_sync_settings


@dataclass
class RepoInitResult:
    repo_root: str
    initialized: bool


@dataclass
class SyncResult:
    repo_root: str
    committed: bool
    pushed: bool
    error: str | None = None


_DEFAULT_GITIGNORE = """# Secrets locaux
.env
.env.*
*.key
credentials/

# Artefacts locaux
.DS_Store
__pycache__/
"""


def _run(repo: Path, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=repo, text=True, capture_output=True, check=check)


def _ensure_git_identity(repo: Path) -> None:
    try:
        _run(repo, ["git", "config", "user.email"])
        _run(repo, ["git", "config", "user.name"])
    except subprocess.CalledProcessError:
        # Configuration locale au repo temporaire seulement, pas de git config global.
        _run(repo, ["git", "config", "user.email", "zab@local.invalid"])
        _run(repo, ["git", "config", "user.name", "zab"])


def ensure_repo_initialized(repo_root: str | Path | None = None) -> RepoInitResult:
    settings = skills_sync_settings()
    root = Path(repo_root or settings["repo_root"]).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    initialized = not (root / ".git").is_dir()
    if initialized:
        _run(root, ["git", "init"])
    gitignore = root / ".gitignore"
    if not gitignore.is_file():
        gitignore.write_text(_DEFAULT_GITIGNORE, encoding="utf-8")
    _ensure_git_identity(root)
    if initialized:
        _run(root, ["git", "add", ".gitignore"])
        _run(root, ["git", "commit", "-m", "chore: initialize skills repository"], check=False)
    return RepoInitResult(repo_root=str(root), initialized=initialized)


def ensure_remote_origin(repo_root: str | Path | None = None, remote_url: str | None = None) -> str:
    settings = skills_sync_settings()
    root = Path(repo_root or settings["repo_root"]).expanduser().resolve()
    ensure_repo_initialized(root)
    url = remote_url or str(settings["git_remote"])
    current = _run(root, ["git", "remote", "get-url", "origin"], check=False)
    if current.returncode != 0:
        _run(root, ["git", "remote", "add", "origin", url])
    return url


def _relative_path(repo: Path, path: Path) -> str:
    try:
        return str(path.expanduser().resolve().relative_to(repo.resolve()))
    except ValueError as exc:
        raise ValueError(f"chemin hors du dépôt skills : {path}") from exc


def _secret_like(path: Path) -> bool:
    name = path.name.lower()
    lower = str(path).lower()
    if name == ".env" or name.startswith(".env.") or name.endswith(".key") or "credentials" in lower:
        return True
    if name.endswith(".json") and path.is_file():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return True
        return "private_key" in text or "client_secret" in text
    return False


def _staged_files(repo: Path) -> list[Path]:
    proc = _run(repo, ["git", "diff", "--cached", "--name-only"], check=False)
    if proc.returncode != 0:
        return []
    return [repo / line for line in proc.stdout.splitlines() if line.strip()]


def commit_and_push(
    repo_root: str | Path | None = None,
    message: str = "skill: sync",
    *,
    paths: list[str | Path] | None = None,
    push: bool = False,
) -> SyncResult:
    settings = skills_sync_settings()
    root = Path(repo_root or settings["repo_root"]).expanduser().resolve()
    ensure_repo_initialized(root)
    if paths:
        preflight_offenders = [str(Path(p)) for p in paths if _secret_like(Path(p))]
        if preflight_offenders:
            return SyncResult(
                str(root),
                committed=False,
                pushed=False,
                error=f"secret-like files refused: {', '.join(preflight_offenders)}",
            )
        rels = [_relative_path(root, Path(p)) for p in paths]
        add = _run(root, ["git", "add", *rels], check=False)
    else:
        add = _run(root, ["git", "add", "-A"], check=False)
    if add.returncode != 0:
        return SyncResult(str(root), committed=False, pushed=False, error=add.stderr.strip() or add.stdout.strip())
    offenders = [str(p) for p in _staged_files(root) if _secret_like(p)]
    if offenders:
        _run(root, ["git", "reset", "--", *[_relative_path(root, Path(p)) for p in offenders]], check=False)
        return SyncResult(str(root), committed=False, pushed=False, error=f"secret-like staged files refused: {', '.join(offenders)}")
    diff = _run(root, ["git", "diff", "--cached", "--quiet"], check=False)
    if diff.returncode == 0:
        return SyncResult(str(root), committed=False, pushed=False)
    commit = _run(root, ["git", "commit", "-m", message], check=False)
    if commit.returncode != 0:
        return SyncResult(str(root), committed=False, pushed=False, error=commit.stderr.strip() or commit.stdout.strip())
    if not push:
        return SyncResult(str(root), committed=True, pushed=False)
    ensure_remote_origin(root)
    pushed = _run(root, ["git", "push", "origin", "HEAD"], check=False)
    if pushed.returncode != 0:
        return SyncResult(str(root), committed=True, pushed=False, error=pushed.stderr.strip() or pushed.stdout.strip())
    return SyncResult(str(root), committed=True, pushed=True)
