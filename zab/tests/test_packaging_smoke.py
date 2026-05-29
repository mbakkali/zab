"""Smoke tests for installable zab package metadata and CLI entrypoint."""

from __future__ import annotations

import os
import subprocess
import sys
from importlib.metadata import version


def test_package_version() -> None:
    assert version("zab").startswith("0.")


def test_cli_help(tmp_path) -> None:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env.pop("XDG_CONFIG_HOME", None)
    env.pop("XDG_DATA_HOME", None)
    proc = subprocess.run(
        [sys.executable, "-m", "zab.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=env,
    )
    assert proc.returncode == 0
    assert "dashboard" in proc.stdout.lower()
