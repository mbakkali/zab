"""Smoke tests for installable zab package metadata and CLI entrypoint."""

from __future__ import annotations

import subprocess
import sys
from importlib.metadata import version


def test_package_version() -> None:
    assert version("zab").startswith("0.")


def test_cli_help() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "zab.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0
    assert "dashboard" in proc.stdout.lower()
