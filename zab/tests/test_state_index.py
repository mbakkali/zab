import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from zab.cli import app
from zab.services import state_index


def test_sync_state_writes_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = tmp_path / "skills-repo"
    skill = repo / "orgs" / "acme" / "skills" / "alpha" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(
        "---\n"
        "name: alpha\n"
        "description: Alpha skill\n"
        "tags: [ops]\n"
        "uses_connectors: [linear]\n"
        "uses_models: [litellm-hosted]\n"
        "---\n"
        "# Alpha\n",
        encoding="utf-8",
    )
    (repo / "configs").mkdir(parents=True, exist_ok=True)
    (repo / "configs" / "cursor-mcp.json").write_text(
        json.dumps({"mcpServers": {"linear": {"command": "npx", "args": ["-y", "mcp-remote"]}}}),
        encoding="utf-8",
    )
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "skills_roots": [str(repo.resolve())],
                "projects_roots": [],
                "cli_watchlist": [],
                "tracked_env_extra": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    path, state = state_index.sync_state()

    assert path.is_file()
    assert state["version"] == state_index.STATE_VERSION
    assert "acme-alpha" in state["skills"]
    assert state["skills"]["acme-alpha"]["uses_connectors"] == ["linear"]
    assert "linear" in state["connectors"]
    assert "tools" in state
    assert "gmail-search" in state["tools"]
    assert "mcps" in state
    assert isinstance(state["mcps"].get("servers"), dict)
    assert "sync_status" in state["mcps"]
    persisted = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert persisted["skills"]["acme-alpha"]["description"] == "Alpha skill"


def test_sync_cli_json(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()
    result = runner.invoke(app, ["sync", "--json"])
    assert result.exit_code == 0
    assert '"counts"' in result.stdout
    assert (tmp_path / ".local" / "share" / "zab" / "state.yaml").is_file()


def test_context_pack_cli(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()
    result = runner.invoke(app, ["context-pack", "--limit", "5", "--json"])
    assert result.exit_code == 0
    assert '"bytes"' in result.stdout
    assert (tmp_path / ".local" / "share" / "zab" / "context-pack").is_dir()


def test_context_pack_includes_projects_orgs_and_knowledge(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    root = tmp_path / "projects"
    project = root / "zab"
    project.mkdir(parents=True)
    (project / "pyproject.toml").write_text("[project]\nname = \"zab\"\n", encoding="utf-8")
    vault = tmp_path / "ObsidianVault"
    (vault / "00_inbox").mkdir(parents=True)
    (vault / "10_daily").mkdir(parents=True)
    (vault / "50_notes").mkdir(parents=True)
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "projects_roots": [str(root)],
                "cli_watchlist": [],
                "tracked_env_extra": [],
                "obsidian": {"vault_path": str(vault)},
            }
        ),
        encoding="utf-8",
    )

    path, text = state_index.build_context_pack(project="zab", query="obsidian second brain", limit=10)

    assert path.is_file()
    assert "## Projects" in text
    assert "### zab" in text
    assert "## Knowledge Sources" in text
    assert "## Tools Catalog" in text
    assert "Obsidian Vault" in text


def test_agent_friendly_cli_commands(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()
    features = runner.invoke(app, ["features", "--json"])
    assert features.exit_code == 0
    assert '"features"' in features.stdout

    guide = runner.invoke(app, ["agent-guide", "--json"])
    assert guide.exit_code == 0
    assert "bootstrap_commands" in guide.stdout
    assert "zab agent skills --json" in guide.stdout

    inv = runner.invoke(app, ["inventory", "code-tools", "--json", "--limit", "3"])
    assert inv.exit_code == 0
    assert '"pagination"' in inv.stdout


def test_tools_catalog_cli_commands(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

    tools_list = runner.invoke(app, ["tools", "list", "--json", "--limit", "5"])
    assert tools_list.exit_code == 0
    list_payload = json.loads(tools_list.stdout)
    assert list_payload["contract"] == "tools-catalog"
    assert isinstance(list_payload["data"], list)
    assert len(list_payload["data"]) >= 1

    tools_search = runner.invoke(app, ["tools", "search", "gmail", "--json"])
    assert tools_search.exit_code == 0
    search_payload = json.loads(tools_search.stdout)
    assert search_payload["contract"] == "tools-catalog-search"
    assert search_payload["total"] >= 1

    tools_inspect = runner.invoke(app, ["tools", "inspect", "gmail-search", "--json"])
    assert tools_inspect.exit_code == 0
    inspect_payload = json.loads(tools_inspect.stdout)
    assert inspect_payload["contract"] == "tools-catalog-item"
    assert inspect_payload["tool"]["id"] == "gmail-search"

    tools_validate = runner.invoke(app, ["tools", "validate", "--json"])
    assert tools_validate.exit_code == 0
    validate_payload = json.loads(tools_validate.stdout)
    assert validate_payload["contract"] == "tools-catalog-validation"
    assert validate_payload["summary"]["total_tools"] >= 1

    tools_check = runner.invoke(app, ["tools", "check", "gmail-search", "--json"])
    assert tools_check.exit_code == 0
    check_payload = json.loads(tools_check.stdout)
    assert check_payload["contract"] == "tools-check"
    assert check_payload["tool_id"] == "gmail-search"


def test_agent_bootstrap_search_security_and_context_stdout(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SECRET_TOKEN", raising=False)
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump({"projects_roots": [], "cli_watchlist": [], "tracked_env_extra": ["SECRET_TOKEN"]}),
        encoding="utf-8",
    )
    runner = CliRunner()

    boot = runner.invoke(app, ["agent", "bootstrap", "--json"])
    assert boot.exit_code == 0
    boot_payload = json.loads(boot.stdout)
    assert boot_payload["contract"] == "agent-bootstrap"
    assert "SECRET_TOKEN" not in boot.stdout

    search = runner.invoke(app, ["search", "secrets", "--json"])
    assert search.exit_code == 0
    assert json.loads(search.stdout)["query"] == "secrets"

    sec = runner.invoke(app, ["security", "status", "--json"])
    assert sec.exit_code == 0
    sec_payload = json.loads(sec.stdout)
    assert "SECRET_TOKEN" in sec_payload["tracked_env_missing"]

    cp = runner.invoke(app, ["context-pack", "--query", "none", "--stdout"])
    assert cp.exit_code == 0
    assert "# zab Context Pack" in cp.stdout


def test_agent_handoff_cli(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    root = tmp_path / "projects"
    project = root / "acme-app"
    skill = project / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text("---\nname: acme-app\n---\n# Acme\n", encoding="utf-8")
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump({"projects_roots": [str(root)], "cli_watchlist": [], "tracked_env_extra": []}),
        encoding="utf-8",
    )
    runner = CliRunner()
    sync = runner.invoke(app, ["sync", "--json"])
    assert sync.exit_code == 0
    result = runner.invoke(app, ["agent", "handoff", "--project", "acme-app", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["found"] is True
    assert payload["project"]["name"] == "acme-app"


def test_agent_handoff_cli_resolves_repo_without_skills(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    root = tmp_path / "projects"
    project = root / "zab"
    project.mkdir(parents=True)
    (project / "pyproject.toml").write_text("[project]\nname = \"zab\"\n", encoding="utf-8")
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump({"projects_roots": [str(root)], "cli_watchlist": [], "tracked_env_extra": []}),
        encoding="utf-8",
    )
    runner = CliRunner()
    sync = runner.invoke(app, ["sync", "--json"])
    assert sync.exit_code == 0
    result = runner.invoke(app, ["agent", "handoff", "--project", "zab", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["found"] is True
    assert payload["project"]["name"] == "zab"
    assert payload["project"]["org"] == "zab"
