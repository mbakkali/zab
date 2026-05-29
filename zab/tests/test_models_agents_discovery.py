"""Fusion découverte agentpipe + codexbar."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from zab.api.app import create_app
from zab.services import models_agents_discovery


def test_build_agents_discovery_merges(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump({"cli_watchlist": [], "codexbar_config_path": str(tmp_path / "cb.json")}),
        encoding="utf-8",
    )
    cb = tmp_path / "cb.json"
    cb.write_text(
        json.dumps(
            {
                "version": 1,
                "providers": [
                    {"id": "claude", "enabled": True},
                    {"id": "gemini", "enabled": True},
                ],
            }
        ),
        encoding="utf-8",
    )
    ap_yaml = tmp_path / ".agentpipe.yaml"
    ap_yaml.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "agents": [
                    {"id": "gemini", "type": "gemini", "model": "gemini-2.0-flash"},
                    {"id": "continue-dev", "type": "continue-dev"},
                ],
            }
        ),
        encoding="utf-8",
    )
    out = models_agents_discovery.build_agents_discovery()
    rows = out.get("rows") or []
    by_id = {r["id"]: r for r in rows}
    assert "gemini" in by_id
    g = by_id["gemini"]
    assert "agentpipe" in g["sources"] and "codexbar" in g["sources"]
    assert g["codexbar_usage_id"] == "gemini"
    c = by_id["continue-dev"]
    assert c["sources"] == ["agentpipe"]
    assert c["codexbar_usage_id"] is None


def test_agents_discovery_route(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(yaml.safe_dump({"cli_watchlist": []}), encoding="utf-8")
    client = TestClient(create_app())
    r = client.get("/api/agents/discovery")
    assert r.status_code == 200
    body = r.json()
    assert "rows" in body
