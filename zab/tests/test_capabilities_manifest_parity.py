"""Épingle deux écarts de parité connus du manifeste `zab capabilities`.

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
