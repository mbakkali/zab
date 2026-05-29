"""Tests CLI ``zab composio``."""

from __future__ import annotations

import subprocess

from typer.testing import CliRunner

from zab.cli import app
from zab.services import composio_connectors


def test_composio_execute_passes_account(monkeypatch) -> None:
    captured: dict[str, list[str]] = {}

    def fake_run(cmd, **kwargs):  # noqa: ANN001
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout='{"successful": true}\n', stderr="")

    monkeypatch.setattr(composio_connectors, "composio_cli_path", lambda: "/fake/composio")
    monkeypatch.setattr("zab.cli.subprocess.run", fake_run)

    runner = CliRunner()
    r = runner.invoke(
        app,
        [
            "composio",
            "execute",
            "GMAIL_FETCH_EMAILS",
            "--account",
            "gmail_betail-apse",
            "-d",
            '{"query":"hubspot"}',
        ],
    )

    assert r.exit_code == 0, r.stdout + r.stderr
    assert captured["cmd"] == [
        "/fake/composio",
        "execute",
        "GMAIL_FETCH_EMAILS",
        "-d",
        '{"query":"hubspot"}',
        "--account",
        "gmail_betail-apse",
    ]
