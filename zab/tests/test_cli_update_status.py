from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from zab.cli import app
from zab.services import cli_update_status


def _write_spec(path: Path, *, latest: str) -> Path:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "checks": [
                    {
                        "id": "cli-demo",
                        "label": "demo",
                        "binary": "demo",
                        "command": ["demo", "--version"],
                        "update": {"source": "manual", "version": latest},
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_cli_update_status_up_to_date(tmp_path, monkeypatch) -> None:
    spec = _write_spec(tmp_path / "cli-checks.json", latest="1.2.3")
    monkeypatch.setattr(cli_update_status.shutil, "which", lambda name: "/usr/local/bin/demo" if name == "demo" else None)
    monkeypatch.setattr(
        cli_update_status,
        "_run_command",
        lambda command, *, timeout_seconds: {"returncode": 0, "stdout": "demo 1.2.3\n", "stderr": ""},
    )

    payload = cli_update_status.run_cli_update_status(spec, network=False)

    assert payload["contract"] == "cli-update-status"
    assert payload["counts"]["up_to_date"] == 1
    assert payload["all_up_to_date"] is True
    assert payload["items"][0]["status"] == "up_to_date"
    assert payload["items"][0]["latest_source"] == "manual"


def test_cli_update_status_outdated_markdown(tmp_path, monkeypatch) -> None:
    spec = _write_spec(tmp_path / "cli-checks.json", latest="1.3.0")
    monkeypatch.setattr(cli_update_status.shutil, "which", lambda name: "/usr/local/bin/demo" if name == "demo" else None)
    monkeypatch.setattr(
        cli_update_status,
        "_run_command",
        lambda command, *, timeout_seconds: {"returncode": 0, "stdout": "demo 1.2.3\n", "stderr": ""},
    )

    payload = cli_update_status.run_cli_update_status(spec, network=False)
    markdown = cli_update_status.render_cli_update_markdown(payload)

    assert payload["counts"]["outdated"] == 1
    assert payload["actionable"] == 1
    assert "| demo | outdated | 1.2.3 | 1.3.0 | manual |" in markdown


def test_cli_update_status_command_json_and_write(tmp_path, monkeypatch) -> None:
    spec = _write_spec(tmp_path / "cli-checks.json", latest="1.2.3")
    report = tmp_path / "report.md"
    monkeypatch.setattr(cli_update_status.shutil, "which", lambda name: "/usr/local/bin/demo" if name == "demo" else None)
    monkeypatch.setattr(
        cli_update_status,
        "_run_command",
        lambda command, *, timeout_seconds: {"returncode": 0, "stdout": "demo 1.2.3\n", "stderr": ""},
    )

    result = CliRunner().invoke(app, ["cli-update-status", "--config", str(spec), "--json", "--write", str(report)])

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["counts"]["up_to_date"] == 1
    assert payload["markdown_path"] == str(report.resolve())
    assert report.read_text(encoding="utf-8").startswith("# Zab CLI update status")
