from __future__ import annotations

import subprocess
from pathlib import Path

from zab.services.publish_guard import format_report, scan_publish_surface


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _init_repo(repo: Path) -> None:
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")


def test_tracked_scan_reports_without_raw_secret(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    secret = "sk-proj-" + "A" * 40
    (tmp_path / "token.txt").write_text(f"OPENAI_API_KEY={secret}\n", encoding="utf-8")
    _git(tmp_path, "add", "token.txt")
    _git(tmp_path, "commit", "-m", "add token fixture")

    result = scan_publish_surface(mode="tracked", repo=tmp_path)
    report = format_report(result)

    assert not result.ok
    assert "secret.openai" in report
    assert secret not in report


def test_staged_scan_blocks_operator_artifacts(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-m", "initial")

    (tmp_path / "agent.md").write_text("local notes\n", encoding="utf-8")
    _git(tmp_path, "add", "agent.md")

    result = scan_publish_surface(mode="staged", repo=tmp_path)

    assert not result.ok
    assert {finding.rule_id for finding in result.findings} == {"path.operator_note"}


def test_test_like_placeholder_secret_is_not_flagged(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "test_example.py").write_text('TOKEN = "sk-test-secret-value"\n', encoding="utf-8")
    _git(tmp_path, "add", "test_example.py")
    _git(tmp_path, "commit", "-m", "add placeholder")

    result = scan_publish_surface(mode="tracked", repo=tmp_path)

    assert result.ok
