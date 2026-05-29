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
