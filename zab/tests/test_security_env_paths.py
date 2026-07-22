"""Chemins security_env_paths (config + API Sécurité)."""

from __future__ import annotations

import yaml
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from zab.api.app import create_app
from zab.cli import app
from zab.services import agent_context
from zab.services.secrets_scan import locate_secret_names
from zab.user_config import security_env_paths_resolved, security_env_paths_strings_ordered


def test_security_env_paths_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    skills = tmp_path / "skills"
    (skills / "orgs").mkdir(parents=True)
    (skills / "common").mkdir(parents=True)
    skill_md = skills / "common" / "skills" / "demo" / "SKILL.md"
    skill_md.parent.mkdir(parents=True)
    skill_md.write_text("---\nname: demo\n---\n", encoding="utf-8")
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "skills_roots": [],
                "skill_md_paths": [str(skill_md.resolve())],
                "cli_watchlist": [],
            }
        ),
        encoding="utf-8",
    )
    ordered = security_env_paths_strings_ordered()
    assert any("skills" in p for p in ordered)
    assert any(".hermes" in p for p in ordered)
    resolved = security_env_paths_resolved()
    assert (skills / ".env").resolve() in resolved


def test_security_env_paths_explicit_list(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    hermes_env = tmp_path / ".hermes" / ".env"
    hermes_env.parent.mkdir(parents=True)
    hermes_env.write_text("HERMES_KEY=1\n", encoding="utf-8")
    skills_env = tmp_path / "skills" / ".env"
    skills_env.parent.mkdir(parents=True)
    skills_env.write_text("SKILLS_KEY=1\n", encoding="utf-8")
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "security_env_paths": [str(skills_env), str(hermes_env)],
                "cli_watchlist": [],
            }
        ),
        encoding="utf-8",
    )
    assert len(security_env_paths_resolved()) == 2


def test_security_env_files_api(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    skills = tmp_path / "skills"
    skills.mkdir()
    hermes = tmp_path / ".hermes"
    hermes.mkdir()
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "security_env_paths": [
                    str((skills / ".env").resolve()),
                    str((hermes / ".env").resolve()),
                ],
                "cli_watchlist": [],
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(create_app())
    r = client.get("/api/security/env-files")
    assert r.status_code == 200
    files = r.json()["files"]
    assert len(files) == 2
    assert files[0]["exists"] is False

    r2 = client.put(
        f"/api/security/env-file?path={files[1]['path']}",
        json={"content": "X=hermes\n"},
    )
    assert r2.status_code == 200
    r3 = client.get(f"/api/security/env-file?path={files[1]['path']}")
    assert r3.json()["content"] == "X=hermes\n"


def test_security_locate_finds_untracked_env_name_without_value(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    env_path = tmp_path / ".env"
    raw_secret = "payfit-secret-value"
    env_path.write_text(f"MEHDI_PAYFIT_APIKEY={raw_secret}\n", encoding="utf-8")
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump({"security_env_paths": [str(env_path.resolve())], "cli_watchlist": []}),
        encoding="utf-8",
    )

    payload = locate_secret_names("api key payfit")

    assert payload["contract"] == "security-secret-locate"
    assert payload["total"] == 1
    match = payload["matches"][0]
    assert match["name"] == "MEHDI_PAYFIT_APIKEY"
    assert match["present"] is True
    assert match["sources"][0]["line"] == 1
    dumped = str(payload)
    assert raw_secret not in dumped
    assert match["masked"].endswith("alue")


def test_security_locate_cli_api_mcp_and_search(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    env_path = tmp_path / ".env"
    raw_secret = "payfit-secret-value"
    env_path.write_text(f"MEHDI_PAYFIT_APIKEY={raw_secret}\n", encoding="utf-8")
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump({"security_env_paths": [str(env_path.resolve())], "cli_watchlist": []}),
        encoding="utf-8",
    )

    runner = CliRunner()
    cli = runner.invoke(app, ["security", "locate", "payfit", "--json"])
    assert cli.exit_code == 0, cli.output
    assert raw_secret not in cli.stdout
    assert "MEHDI_PAYFIT_APIKEY" in cli.stdout

    search_cli = runner.invoke(app, ["search", "payfit", "--json"])
    assert search_cli.exit_code == 0, search_cli.output
    assert raw_secret not in search_cli.stdout
    assert "MEHDI_PAYFIT_APIKEY" in search_cli.stdout

    client = TestClient(create_app())
    api = client.get("/api/security/locate?q=payfit")
    assert api.status_code == 200
    assert api.json()["matches"][0]["name"] == "MEHDI_PAYFIT_APIKEY"
    assert raw_secret not in api.text

    mcp = agent_context.call_mcp_tool("security_locate", {"query": "payfit"})
    assert mcp["matches"][0]["name"] == "MEHDI_PAYFIT_APIKEY"
    assert raw_secret not in str(mcp)

    search = agent_context.search("payfit", limit=5)
    assert any(row.get("section") == "security" and row.get("key") == "MEHDI_PAYFIT_APIKEY" for row in search["data"])
    assert raw_secret not in str(search)
