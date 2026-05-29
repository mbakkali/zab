from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from zab.cli import app
from zab.services import agent_context


def test_agent_skills_manifest_exposes_cross_project_skills(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = tmp_path / "skills"
    global_skill = repo / "orgs" / "flowmetrik" / "skills" / "billing" / "SKILL.md"
    global_skill.parent.mkdir(parents=True)
    global_skill.write_text(
        "---\nname: billing\ndescription: Billing workflow\ntags: [finance]\n---\n# Billing\n",
        encoding="utf-8",
    )
    project = tmp_path / "projects" / "flowmetrik-app"
    project_skill = project / ".cursor" / "skills" / "deploy" / "SKILL.md"
    project_skill.parent.mkdir(parents=True)
    project_skill.write_text("---\nname: deploy\ndescription: Deploy app\n---\n# Deploy\n", encoding="utf-8")
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "skills_roots": [str(repo.resolve())],
                "projects_roots": [str((tmp_path / "projects").resolve())],
                "skill_md_paths": [str(global_skill.resolve()), str(project_skill.resolve())],
                "claude_plugin_paths": [],
                "cli_watchlist": [],
                "tracked_env_extra": [],
                "skills_sync": {"repo_root": str(repo.resolve())},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    manifest = agent_context.skills_manifest(refresh=True)

    assert manifest["contract"] == "skills-manifest"
    assert manifest["total"] == 2
    assert {row["id"] for row in manifest["skills"]} == {"billing", "deploy"}
    by_id = {row["id"]: row for row in manifest["skills"]}
    assert by_id["billing"]["scope"] == "global"
    assert by_id["deploy"]["scope"] == "project"
    assert manifest["usage"]["inspect_command"] == "zab inspect skills <key> --json"


def test_agent_skills_cli_outputs_manifest_json(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(yaml.safe_dump({"projects_roots": [], "skills_roots": []}), encoding="utf-8")

    result = CliRunner().invoke(app, ["agent", "skills", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["contract"] == "skills-manifest"
    assert "usage" in payload


def test_skill_new_global_cli_creates_global_skill(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = tmp_path / "skills"
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "skills_roots": [str(repo.resolve())],
                "projects_roots": [],
                "skill_md_paths": [],
                "claude_plugin_paths": [],
                "cli_watchlist": [],
                "tracked_env_extra": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, ["skill", "new-global", "global-helper", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["skill"]["scope"] == "global"
    assert (repo / "common" / "skills" / "global-helper" / "SKILL.md").is_file()
