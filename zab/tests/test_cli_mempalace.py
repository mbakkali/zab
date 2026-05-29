"""Tests CLI ``zab mempalace`` et module ``mempalace_mcp_snippet``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from zab.cli import app
from zab.services import mempalace_mcp_snippet


def test_build_mcp_server_entry_with_palace(tmp_path: Path) -> None:
    pal = tmp_path / "my_palace"
    pal.mkdir()
    block = mempalace_mcp_snippet.build_mcp_server_entry(palace=str(pal), binary_path="/fake/mempalace-mcp")
    assert block["command"] == "/fake/mempalace-mcp"
    assert block["args"] == ["--palace", str(pal.resolve())]


def test_build_mcp_server_entry_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mempalace_mcp_snippet, "resolve_mempalace_mcp_binary", lambda: None)
    with pytest.raises(ValueError, match="mempalace-mcp"):
        mempalace_mcp_snippet.build_mcp_server_entry()


def test_mempalace_mcp_json_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mempalace_mcp_snippet, "resolve_mempalace_mcp_binary", lambda: "/x/mempalace-mcp")
    runner = CliRunner()
    r = runner.invoke(app, ["mempalace", "mcp-json", "-n", "mp"])
    assert r.exit_code == 0, r.stdout + r.stderr
    doc = json.loads(r.stdout.split("#", 1)[0].strip())
    assert "mcpServers" in doc
    assert doc["mcpServers"]["mp"]["command"] == "/x/mempalace-mcp"


def test_mempalace_mcp_install_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from zab.services import cli_add

    repo = tmp_path / "skills"
    cfg = repo / "configs"
    cfg.mkdir(parents=True)
    monkeypatch.setattr(cli_add, "configs_dir", lambda: cfg)
    monkeypatch.setattr(mempalace_mcp_snippet, "resolve_mempalace_mcp_binary", lambda: "/fake/mempalace-mcp")

    runner = CliRunner()
    r = runner.invoke(app, ["mempalace", "mcp-install", "-t", "cursor", "-n", "memtest", "--force"])
    assert r.exit_code == 0, r.stdout + r.stderr
    doc = json.loads((cfg / "cursor-mcp.json").read_text(encoding="utf-8"))
    assert doc["mcpServers"]["memtest"]["command"] == "/fake/mempalace-mcp"


def test_mempalace_doctor_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from zab import paths as zab_paths

    repo = tmp_path / "sr"
    (repo / "configs").mkdir(parents=True)

    def _cfg() -> Path:
        return repo / "configs"

    monkeypatch.setattr(zab_paths, "configs_dir", _cfg)
    monkeypatch.setattr(mempalace_mcp_snippet, "resolve_mempalace_cli_binary", lambda: "/a/mempalace")
    monkeypatch.setattr(mempalace_mcp_snippet, "resolve_mempalace_mcp_binary", lambda: "/b/mempalace-mcp")
    monkeypatch.setattr(mempalace_mcp_snippet, "_version_line", lambda _b: "MemPalace 9.9.9")
    monkeypatch.setattr(mempalace_mcp_snippet, "_help_head", lambda _b: "usage: mempalace-mcp")

    runner = CliRunner()
    r = runner.invoke(app, ["mempalace", "doctor", "--json"])
    assert r.exit_code == 0
    data = json.loads(r.stdout)
    assert data["mempalace"]["which"] == "/a/mempalace"
    assert data["mempalace_mcp"]["which"] == "/b/mempalace-mcp"
    assert "cursor-mcp.json" in data["mcp_config_paths"]["cursor"]
