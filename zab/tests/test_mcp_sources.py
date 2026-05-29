"""Tests scan MCP multi-sources."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zab.services import mcp_sources


def test_normalize_mcp_stdio(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    doc = {"mcpServers": {"x": {"command": "uvx", "args": ["foo"], "env": {"API_KEY": "x"}}}}
    items = mcp_sources.normalize_mcp_servers(doc, "t.json", config_file=None, source_kind="test")
    assert len(items) == 1
    assert items[0]["name"] == "x"
    assert items[0]["kind"] == "stdio"
    assert items[0]["transport_command"] == "uvx"
    assert items[0]["env_var_names"] == ["API_KEY"]


def test_list_mcp_servers_flat_includes_repo_and_cursor_user(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = tmp_path / "skills-repo"
    (repo / "configs").mkdir(parents=True, exist_ok=True)
    (repo / "configs" / "cursor-mcp.json").write_text(
        json.dumps({"mcpServers": {"repo-mcp": {"command": "npx", "args": ["-y", "pkg"]}}}),
        encoding="utf-8",
    )
    (repo / "configs" / "claude-desktop-mcp.json").write_text("{}", encoding="utf-8")
    cfg = tmp_path / ".config" / "zab"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.yaml").write_text(
        f"skills_roots: [{json.dumps(str(repo))}]\nprojects_roots: []\n",
        encoding="utf-8",
    )
    cur = tmp_path / ".cursor"
    cur.mkdir()
    (cur / "mcp.json").write_text(
        json.dumps({"mcpServers": {"cursor-only": {"command": "node", "args": ["server.js"]}}}),
        encoding="utf-8",
    )

    flat = mcp_sources.list_mcp_servers_flat()
    names = {s["name"] for s in flat}
    assert "repo-mcp" in names
    assert "cursor-only" in names
    kinds = {s["source_kind"] for s in flat if s["name"] == "repo-mcp"}
    assert "skills_repo_cursor" in kinds


def test_mcps_dir_hints(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = tmp_path / "skills-repo"
    (repo / "configs").mkdir(parents=True, exist_ok=True)
    (repo / "configs" / "cursor-mcp.json").write_text("{}", encoding="utf-8")
    (repo / "configs" / "claude-desktop-mcp.json").write_text("{}", encoding="utf-8")
    (repo / "mcps" / "pkg-a").mkdir(parents=True)
    cfg = tmp_path / ".config" / "zab"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.yaml").write_text(
        f"skills_roots: [{json.dumps(str(repo))}]\nprojects_roots: []\n",
        encoding="utf-8",
    )
    hints = mcp_sources.scan_mcps_packages_hints()
    assert len(hints) == 1
    assert hints[0]["package_count"] == 1
    assert "pkg-a" in hints[0]["package_names"]
