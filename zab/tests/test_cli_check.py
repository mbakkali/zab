from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from zab.api.app import create_app
from zab.cli import app
from zab.paths import config_dir
from zab.services import cli_check
from zab.services.cli_check import run_cli_checks


def _write_spec(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "checks": [
                    {
                        "id": "python-ok",
                        "label": "Python OK",
                        "command": [sys.executable, "-c", "print('authenticated user')"],
                        "success": {"exit_codes": [0], "stdout_contains_any": ["authenticated"]},
                    },
                    {
                        "id": "missing-env",
                        "label": "Missing env",
                        "env_all": ["ZAB_TEST_CLI_CHECK_MISSING"],
                        "failure_note": "env missing",
                    },
                    {
                        "id": "env-only",
                        "label": "Env only",
                        "env_all": ["ZAB_TEST_CLI_CHECK_PRESENT"],
                    },
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def run_cli_checks_for_spec(spec: dict) -> dict:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "cli-checks.json"
        path.write_text(json.dumps({"version": 1, **spec}, ensure_ascii=False) + "\n", encoding="utf-8")
        return run_cli_checks(path, create_default=False)


def test_run_cli_checks_from_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ZAB_TEST_CLI_CHECK_PRESENT", "1")
    spec = _write_spec(tmp_path / "cli-checks.json")

    payload = run_cli_checks(spec, create_default=False)

    assert payload["contract"] == "cli-auth-checks"
    assert payload["total"] == 3
    assert payload["ok"] == 1
    assert payload["warn"] == 1
    assert payload["fail"] == 1
    rows = {row["id"]: row for row in payload["checks"]}
    assert rows["python-ok"]["status"] == "ok"
    assert rows["missing-env"]["message"] == "env missing"
    assert rows["env-only"]["status"] == "warn"


def test_env_checks_read_zab_env_file(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ZAB_TEST_CLI_CHECK_FILE_ONLY", raising=False)
    (config_dir() / ".env").write_text("ZAB_TEST_CLI_CHECK_FILE_ONLY=present\n", encoding="utf-8")
    spec = tmp_path / "cli-checks.json"
    spec.write_text(
        json.dumps(
            {
                "version": 1,
                "checks": [
                    {
                        "id": "file-env",
                        "label": "File env",
                        "env_all": ["ZAB_TEST_CLI_CHECK_FILE_ONLY"],
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    payload = run_cli_checks(spec, create_default=False)

    assert payload["warn"] == 1
    assert payload["fail"] == 0
    assert payload["checks"][0]["detail"]["env_all_present"] == ["ZAB_TEST_CLI_CHECK_FILE_ONLY"]


def test_cli_check_zab_task_source_ok(monkeypatch) -> None:
    monkeypatch.setattr(
        "zab.services.tasks_inbox.check_single_source",
        lambda source_id: {
            "id": source_id,
            "status": "ok",
            "items": [{"identifier": "#1"}, {"identifier": "#2"}],
            "token_present": True,
            "checked_at_utc": "2026-06-08T00:00:00+00:00",
        },
    )

    payload = run_cli_checks_for_spec(
        {
            "checks": [
                {
                    "id": "gitlab-source",
                    "label": "GitLab source",
                    "zab_task_source": "danmdata-gitlab",
                    "success_message": "source ok",
                }
            ]
        }
    )

    row = payload["checks"][0]
    assert row["status"] == "ok"
    assert row["message"] == "source ok"
    assert row["detail"]["item_count"] == 2
    assert row["detail"]["token_present"] is True


def test_cli_check_zab_task_source_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        "zab.services.tasks_inbox.check_single_source",
        lambda source_id: {
            "id": source_id,
            "status": "skipped",
            "reason": "variable TOKEN absente ou vide",
            "items": [],
            "token_present": False,
        },
    )

    payload = run_cli_checks_for_spec(
        {
            "checks": [
                {
                    "id": "gitlab-source",
                    "label": "GitLab source",
                    "zab_task_source": "danmdata-gitlab",
                }
            ]
        }
    )

    row = payload["checks"][0]
    assert row["status"] == "fail"
    assert "TOKEN" in row["message"]
    assert row["detail"]["source_status"] == "skipped"


def test_cli_check_command_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ZAB_TEST_CLI_CHECK_PRESENT", "1")
    spec = _write_spec(tmp_path / "cli-checks.json")

    result = CliRunner().invoke(app, ["cli-check", "--config", str(spec), "--json"])

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["total"] == 3
    assert payload["fail"] == 1


def test_cli_check_api(monkeypatch) -> None:
    monkeypatch.setenv("ZAB_TEST_CLI_CHECK_PRESENT", "1")
    spec = config_dir() / "cli-checks.json"
    _write_spec(spec)

    client = TestClient(create_app())
    response = client.get("/api/cli-check")

    assert response.status_code == 200
    payload = response.json()
    assert payload["contract"] == "cli-auth-checks"
    assert payload["total"] == 3
    assert payload["ok"] == 1


def test_open_terminal_for_check_uses_configured_command(monkeypatch) -> None:
    spec = config_dir() / "cli-checks.json"
    _write_spec(spec)
    captured: dict[str, object] = {}

    def fake_open(command, *, cwd=None, title=None):  # noqa: ANN001
        captured["command"] = list(command)
        captured["cwd"] = str(cwd)
        captured["title"] = title
        return "fake-terminal"

    monkeypatch.setattr(cli_check, "open_command_in_terminal", fake_open)

    result = cli_check.open_check_command_terminal("python-ok")

    assert result["opened"] is True
    assert result["opened_with"] == "fake-terminal"
    assert captured["command"] == [sys.executable, "-c", "print('authenticated user')"]
    assert captured["title"] == "zab: Python OK"


def test_cli_check_open_terminal_api(monkeypatch) -> None:
    spec = config_dir() / "cli-checks.json"
    _write_spec(spec)
    monkeypatch.setattr(cli_check, "open_command_in_terminal", lambda command, **kwargs: "fake-terminal")

    client = TestClient(create_app())
    response = client.post("/api/cli-check/python-ok/open-terminal")

    assert response.status_code == 200
    payload = response.json()
    assert payload["opened"] is True
    assert payload["command"] == [sys.executable, "-c", "print('authenticated user')"]

    no_command = client.post("/api/cli-check/env-only/open-terminal")
    assert no_command.status_code == 400
