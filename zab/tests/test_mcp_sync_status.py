"""Tests payload sync-status MCP."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zab.services import mcp_sync_status


def test_sync_status_counts_sources(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = tmp_path / "skills-repo"
    (repo / "configs").mkdir(parents=True, exist_ok=True)
    (repo / "configs" / "cursor-mcp.json").write_text(
        json.dumps({"mcpServers": {"a": {"command": "c1", "args": []}}}),
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
        json.dumps({"mcpServers": {"b": {"command": "c2", "args": []}}}),
        encoding="utf-8",
    )

    payload = mcp_sync_status.mcp_sync_status_payload()
    assert payload["sources"]["cursor_user"]["exists"] is True
    assert payload["counts"]["servers_total"] >= 2
    assert "skills_repo_cursor" in (payload.get("sources_scanned_counts") or {})
    assert "cursor_user" in (payload.get("sources_scanned_counts") or {})


def test_mcp_list_payload_has_slugs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = tmp_path / "skills-repo"
    (repo / "configs").mkdir(parents=True, exist_ok=True)
    (repo / "configs" / "cursor-mcp.json").write_text(
        json.dumps({"mcpServers": {"MyServer": {"command": "x", "args": []}}}),
        encoding="utf-8",
    )
    (repo / "configs" / "claude-desktop-mcp.json").write_text("{}", encoding="utf-8")
    cfg = tmp_path / ".config" / "zab"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.yaml").write_text(
        f"skills_roots: [{json.dumps(str(repo))}]\nprojects_roots: []\n",
        encoding="utf-8",
    )
    out = mcp_sync_status.mcp_list_payload()
    assert out["total"] >= 1
    assert any(r.get("slug") == "myserver" for r in out["data"])
