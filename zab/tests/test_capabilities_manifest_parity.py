"""Épingle des écarts de parité connus du manifeste `zab capabilities`.

`docs/capability-audit.md` documentait deux capacités dont le champ `cli`
mentait sur ce que la CLI sait faire :
- `tasks.sources_status` déclarait `zab config --json`, alors que `zab config`
  n'a jamais eu de mode JSON et n'affiche pas le statut des sources de tâches.
- `channels.list` déclarait `zab channels list` alors que la commande n'avait
  aucun mode JSON, en contradiction avec le contrat global `json_cli: true`
  affiché par le manifeste.

Ces tests vérifient que la commande déclarée existe réellement et répond en
JSON valide, pour que le manifeste et la CLI ne puissent plus diverger en
silence.
"""

from __future__ import annotations

import json
import shlex

from typer.testing import CliRunner

from zab.cli import app
from zab.services.capabilities import get_capabilities
from zab.services.system_check import run_system_check

runner = CliRunner()


def _cli_for(capability_id: str) -> str:
    manifest = get_capabilities()
    for cap in manifest["capabilities"]:
        if cap["id"] == capability_id:
            return cap["cli"]
    raise AssertionError(f"capability {capability_id} absente du manifeste")


def test_tasks_sources_status_cli_matches_manifest_and_returns_json(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cli_command = _cli_for("tasks.sources_status")
    args = shlex.split(cli_command)[1:]  # drop the leading "zab"

    result = runner.invoke(app, args)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["contract"] == "zab-task-sources-status"
    assert "sources" in payload


def test_channels_list_cli_matches_manifest_contract_and_returns_json(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    manifest = get_capabilities()
    assert manifest["contracts"]["json_cli"] is True
    cli_command = _cli_for("channels.list")

    result = runner.invoke(app, shlex.split(cli_command)[1:] + ["--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "channels" in payload


def test_system_check_capability_does_not_falsely_claim_a_cli_form() -> None:
    """`zab doctor` is a separate, older toolchain/config check: it never calls
    `run_system_check()` and has no `--json` output shaped like its payload
    (`checks`, `percentage`, `score`). The manifest used to declare
    `cli="zab doctor"` for this capability, which read as CLI parity that
    does not exist. Pin both sides so neither can silently regress: the
    manifest must not re-claim a CLI form until one actually calls
    `run_system_check()`, and `doctor`'s output keys must stay distinct from
    the real payload's keys."""
    manifest = get_capabilities()
    cap = next(c for c in manifest["capabilities"] if c["id"] == "system.check")
    assert cap["cli"] is None
    assert cap["parity_notes"]
    assert "run_system_check" in cap["parity_notes"]

    payload = run_system_check()
    assert {"checks", "percentage", "score", "total"} <= payload.keys()

    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "--json" not in result.output
    assert "percentage" not in result.output.lower()
