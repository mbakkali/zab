"""Chemins security_env_paths (config + API Sécurité)."""

from __future__ import annotations

import yaml
from fastapi.testclient import TestClient

from zab.api.app import create_app
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
