"""Tests pour zab.services.cli_add (commandes `zab add`)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from zab import user_config
from zab.services import cli_add


def test_add_mcp_http(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "skills"
    cfg_dir = root / "configs"
    monkeypatch.setattr(cli_add, "configs_dir", lambda: cfg_dir)

    path = cli_add.add_mcp_server(
        target="cursor",
        name="fetch",
        url="https://example.com/mcp",
        command=None,
        args=None,
        env_pairs=None,
        force=False,
    )
    assert path == cfg_dir / "cursor-mcp.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["mcpServers"]["fetch"]["url"] == "https://example.com/mcp"


def test_add_mcp_stdio_with_args(monkeypatch, tmp_path: Path) -> None:
    cfg_dir = tmp_path / "cfg"
    monkeypatch.setattr(cli_add, "configs_dir", lambda: cfg_dir)

    cli_add.add_mcp_server(
        target="desktop",
        name="demo",
        url=None,
        command="npx",
        args=["-y", "@x/mcp"],
        env_pairs={"API_KEY": "secret"},
        force=False,
    )
    doc = json.loads((cfg_dir / "claude-desktop-mcp.json").read_text(encoding="utf-8"))
    srv = doc["mcpServers"]["demo"]
    assert srv["command"] == "npx"
    assert srv["args"] == ["-y", "@x/mcp"]
    assert srv["env"]["API_KEY"] == "secret"


def test_add_mcp_rejects_duplicate(monkeypatch, tmp_path: Path) -> None:
    cfg_dir = tmp_path / "c"
    monkeypatch.setattr(cli_add, "configs_dir", lambda: cfg_dir)
    cli_add.add_mcp_server(
        target="cursor", name="a", url="http://u", command=None, args=None, env_pairs=None, force=False
    )
    with pytest.raises(ValueError, match="existe déjà"):
        cli_add.add_mcp_server(
            target="cursor",
            name="a",
            url="http://v",
            command=None,
            args=None,
            env_pairs=None,
            force=False,
        )


def test_parse_args_option() -> None:
    assert cli_add.parse_args_option(None) is None
    assert cli_add.parse_args_option('  -y @pkg/foo  ') == ["-y", "@pkg/foo"]


def test_add_cli_local_tools(monkeypatch, tmp_path: Path) -> None:
    lt = tmp_path / "local-tools.yaml"
    monkeypatch.setattr(cli_add, "local_tools_config_path", lambda: lt)

    cli_add.add_cli_watchlist("gh", where="local_tools")
    data = yaml.safe_load(lt.read_text(encoding="utf-8"))
    assert data["cli_watchlist"] == ["gh"]

    cli_add.add_cli_watchlist("kubectl", where="local_tools")
    data = yaml.safe_load(lt.read_text(encoding="utf-8"))
    assert data["cli_watchlist"] == ["gh", "kubectl"]


def test_add_api_proxy_merges(monkeypatch, tmp_path: Path) -> None:
    lt = tmp_path / "lt.yaml"
    lt.write_text(
        yaml.safe_dump({"cli_watchlist": ["gh"], "proxies": {"old": {"base_url": "https://x"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli_add, "local_tools_config_path", lambda: lt)

    cli_add.add_api_proxy("litellm", "https://l.example/v1", "OPENAI_API_KEY")
    data = yaml.safe_load(lt.read_text(encoding="utf-8"))
    assert data["proxies"]["old"]["base_url"] == "https://x"
    assert data["proxies"]["litellm"]["base_url"] == "https://l.example/v1"
    assert data["proxies"]["litellm"]["api_key_env"] == "OPENAI_API_KEY"


def test_add_tracked_env(monkeypatch, tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.yaml"
    monkeypatch.setattr(user_config, "user_config_path", lambda: cfg_file)

    user_config.save_user_config({"skills_root": "/tmp/x"})
    cli_add.add_tracked_env("CUSTOM_KEY")
    cfg = user_config.load_user_config()
    assert cfg.get("tracked_env_extra") == ["CUSTOM_KEY"]
    assert cfg.get("skills_root") == "/tmp/x"
