from __future__ import annotations

import subprocess
from pathlib import Path

from zab.services.skills_git_sync import commit_and_push, ensure_remote_origin, ensure_repo_initialized


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def test_ensure_repo_initialized_creates_gitignore_and_commit(tmp_path: Path) -> None:
    repo = tmp_path / "skills"
    repo.mkdir()

    result = ensure_repo_initialized(repo)

    assert result.initialized is True
    assert (repo / ".git").is_dir()
    ignore = (repo / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in ignore
    assert "credentials/" in ignore
    assert _git(repo, "rev-parse", "--is-inside-work-tree") == "true"


def test_commit_and_push_commits_targeted_paths_and_reports_push_failure(tmp_path: Path) -> None:
    repo = tmp_path / "skills"
    repo.mkdir()
    ensure_repo_initialized(repo)
    ensure_remote_origin(repo, "git@example.invalid:missing/repo.git")
    skill = repo / "orgs" / "acme" / "skills" / "alpha" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: alpha\n---\n# Alpha\n", encoding="utf-8")

    result = commit_and_push(repo, "skill: add acme/alpha", paths=[skill], push=True)

    assert result.committed is True
    assert result.pushed is False
    assert result.error
    assert "skill: add acme/alpha" in _git(repo, "log", "-1", "--pretty=%s")


def test_commit_and_push_refuses_staged_secret_like_files(tmp_path: Path) -> None:
    repo = tmp_path / "skills"
    repo.mkdir()
    ensure_repo_initialized(repo)
    secret = repo / ".env"
    secret.write_text("TOKEN=secret\n", encoding="utf-8")

    result = commit_and_push(repo, "bad", paths=[secret], push=False)

    assert result.committed is False
    assert result.pushed is False
    assert result.error and "secret" in result.error.lower()
