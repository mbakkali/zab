"""Tests agents CodexBar + endpoint usage."""

from __future__ import annotations

import json

import yaml
from fastapi.testclient import TestClient

from zab.api.app import create_app
from zab.services import agents_registry


def test_list_codexbar_agents_missing_config(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = tmp_path / ".config" / "zab"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.yaml").write_text(yaml.safe_dump({"cli_watchlist": []}), encoding="utf-8")
    out = agents_registry.list_codexbar_agents()
    assert out["present"] is False
    assert out["agents"] == []
    assert "error" in out


def test_list_codexbar_agents_resolves_which(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = tmp_path / ".config" / "zab"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.yaml").write_text(
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
                    {"id": "ghost", "enabled": False},
                ],
            }
        ),
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_cli = bin_dir / "claude"
    fake_cli.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    fake_cli.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    out = agents_registry.list_codexbar_agents()
    assert out["present"] is True
    assert len(out["agents"]) == 1
    assert out["agents"][0]["id"] == "claude"
    assert out["agents"][0]["on_path"] is True
    assert str(fake_cli.resolve()) in (out["agents"][0]["cli_path"] or "")


def test_agents_api_route(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = tmp_path / ".config" / "zab"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.yaml").write_text(yaml.safe_dump({"cli_watchlist": []}), encoding="utf-8")
    client = TestClient(create_app())
    r = client.get("/api/agents")
    assert r.status_code == 200
    body = r.json()
    assert "agents" in body


def test_codexbar_usage_invalid_provider():
    out = agents_registry.codexbar_usage_json("../x")
    assert out.get("ok") is False
    assert out.get("error") == "invalid_provider"
