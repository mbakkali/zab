from __future__ import annotations

from pathlib import Path

import yaml

from fastapi.testclient import TestClient

from zab.api.app import create_app
from zab.services import skills_sync_status
from zab.services.skills_git_sync import ensure_remote_origin, ensure_repo_initialized
from zab.user_config import skills_sync_settings


def test_skills_sync_status_payload_structure(tmp_path) -> None:
    """HOME isolé (conftest) : skills-repo + hermes minimal."""
    repo = tmp_path / "skills-repo"
    (repo / "common" / "skills" / "alpha").mkdir(parents=True)
    (repo / "common" / "skills" / "alpha" / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: d\n---\n\n# A\n",
        encoding="utf-8",
    )
    ensure_repo_initialized(repo)

    hermes = tmp_path / ".hermes" / "config.yaml"
    hermes.parent.mkdir(parents=True)
    hermes.write_text(yaml.safe_dump({"skills": {"external_dirs": []}}), encoding="utf-8")

    payload = skills_sync_status.skills_sync_status_payload()
    assert payload["global_repo"]["skill_md_count"] >= 1
    assert payload["global_repo"]["git"]["is_git_repo"] is True
    assert "desired_external_dirs" in payload["hermes"]
    assert "cursor_global" in payload and "claude_global" in payload and "kimi_global" in payload


def test_skills_sync_hints_per_skill(tmp_path) -> None:
    """Hermes couvre le chemin ; Git suivi ; slug parallèle sous ~/.cursor/skills."""
    import subprocess

    repo = tmp_path / "skills-repo"
    org_skills = repo / "orgs" / "acme" / "skills"
    md = org_skills / "hinted" / "SKILL.md"
    md.parent.mkdir(parents=True)
    md.write_text("---\nname: hinted\n---\n", encoding="utf-8")

    cur = tmp_path / ".cursor" / "skills" / "hinted" / "SKILL.md"
    cur.parent.mkdir(parents=True)
    cur.write_text("---\nname: hinted\n---\n", encoding="utf-8")

    hermes = tmp_path / ".hermes" / "config.yaml"
    hermes.parent.mkdir(parents=True)
    hermes.write_text(
        yaml.safe_dump({"skills": {"external_dirs": [str(org_skills.resolve())]}}),
        encoding="utf-8",
    )

    ensure_repo_initialized(repo)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "skill hinted"], cwd=repo, check=True)

    from zab.services import state_index

    state_index.sync_state()

    hints_payload = skills_sync_status.skills_sync_hints_payload(limit=100)
    key = str(md.resolve())
    assert key in hints_payload["hints"]
    h = hints_payload["hints"][key]
    assert h["global_repo"] is True
    assert h["hermes_external_dir"] is True
    assert h["cursor_global_path"] is False
    assert h["cursor_global_slug_parallel"] is True
    assert h["github"]["applicable"] is True
    assert h["github"]["tracked"] is True
    assert h["github"]["file_clean"] is True


def test_scan_imports_from_cursor_global(tmp_path) -> None:
    src = tmp_path / ".cursor" / "skills" / "cursoronly" / "SKILL.md"
    src.parent.mkdir(parents=True)
    src.write_text("---\nname: cursoronly\ndescription: t\n---\n\n# Cursor only\n", encoding="utf-8")

    repo = tmp_path / "skills-repo"
    ensure_repo_initialized(repo)

    report = skills_sync_status.scan_external_dirs_import_and_sync()
    dest = repo / "common" / "skills" / "cursoronly" / "SKILL.md"
    assert dest.is_file()
    assert any(x.get("slug") == "cursoronly" for x in report["imported"])

    report2 = skills_sync_status.scan_external_dirs_import_and_sync()
    assert len(report2["imported"]) == 0
    assert len(report2["skipped_existing"]) >= 1


def test_scan_imports_from_kimi_global(tmp_path) -> None:
    src = tmp_path / ".kimi" / "skills" / "kimionly" / "SKILL.md"
    src.parent.mkdir(parents=True)
    src.write_text("---\nname: kimionly\ndescription: t\n---\n\n# Kimi only\n", encoding="utf-8")

    repo = tmp_path / "skills-repo"
    ensure_repo_initialized(repo)

    report = skills_sync_status.scan_external_dirs_import_and_sync()
    dest = repo / "common" / "skills" / "kimionly" / "SKILL.md"
    assert dest.is_file()
    assert any(x.get("slug") == "kimionly" for x in report["imported"])


def test_github_sync_explicit_push_attempt_no_network_success(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "solo-skills"
    repo.mkdir()
    ensure_repo_initialized(repo)
    ensure_remote_origin(repo, "git@example.invalid:missing/skills.git")
    f = repo / "orgs" / "acme" / "skills" / "beta" / "SKILL.md"
    f.parent.mkdir(parents=True)
    f.write_text("---\nname: beta\n---\n", encoding="utf-8")

    def fake_settings() -> dict:
        return {
            "repo_root": str(repo),
            "git_remote": "git@example.invalid:missing/skills.git",
            "hermes_config_path": str(tmp_path / ".hermes" / "config.yaml"),
            "auto_sync": False,
            "auto_hermes_update": False,
            "notify": False,
            "notify_channel": "evolution",
        }

    monkeypatch.setattr("zab.user_config.skills_sync_settings", fake_settings)
    monkeypatch.setattr("zab.services.skills_sync_status.skills_sync_settings", fake_settings)
    monkeypatch.setattr("zab.services.skills_git_sync.skills_sync_settings", fake_settings)

    out = skills_sync_status.github_sync_explicit(message="test commit")
    assert out["committed"] is True
    assert out["pushed"] is False
    assert out.get("error")


def test_api_skills_sync_endpoints(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "skills-repo"
    ensure_repo_initialized(repo)
    (repo / "common" / "skills" / "apihit").mkdir(parents=True)
    (repo / "common" / "skills" / "apihit" / "SKILL.md").write_text("---\nname: apihit\n---\n", encoding="utf-8")

    cur = tmp_path / ".cursor" / "skills" / "fromapi" / "SKILL.md"
    cur.parent.mkdir(parents=True)
    cur.write_text("---\nname: fromapi\n---\n", encoding="utf-8")

    hermes = tmp_path / ".hermes" / "config.yaml"
    hermes.parent.mkdir(parents=True)
    hermes.write_text(yaml.safe_dump({"skills": {"external_dirs": []}}), encoding="utf-8")

    def fake_settings() -> dict:
        return {
            "repo_root": str(repo.resolve()),
            "git_remote": "git@example.invalid:x/y.git",
            "hermes_config_path": str(hermes.resolve()),
            "auto_sync": False,
            "auto_hermes_update": False,
            "notify": False,
            "notify_channel": "evolution",
        }

    monkeypatch.setattr("zab.user_config.skills_sync_settings", fake_settings)
    monkeypatch.setattr("zab.services.skills_sync_status.skills_sync_settings", fake_settings)
    monkeypatch.setattr("zab.services.hermes_config.skills_sync_settings", fake_settings)
    monkeypatch.setattr("zab.services.skills_git_sync.skills_sync_settings", fake_settings)

    client = TestClient(create_app())
    r = client.get("/api/skills/sync-status")
    assert r.status_code == 200
    body = r.json()
    assert body["global_repo"]["skill_md_count"] >= 1

    r_hints = client.get("/api/skills/sync-hints?limit=50")
    assert r_hints.status_code == 200
    assert "hints" in r_hints.json()

    r_scan = client.post("/api/skills/scan-external-dirs")
    assert r_scan.status_code == 200
    scan = r_scan.json()
    assert "imported" in scan and any(x.get("slug") == "fromapi" for x in scan["imported"])

    r_h = client.post("/api/skills/hermes-update", json={"apply": True})
    assert r_h.status_code == 200
    data = yaml.safe_load(hermes.read_text(encoding="utf-8"))
    assert isinstance(data["skills"]["external_dirs"], list)
    assert str((repo / "common" / "skills").resolve()) in data["skills"]["external_dirs"]

    ensure_remote_origin(repo, "git@example.invalid:missing/skills.git")
    r_git = client.post("/api/skills/github-sync", json={"message": "ci test"})
    assert r_git.status_code == 200
    git_payload = r_git.json()
    assert git_payload.get("committed") in (True, False)
    assert git_payload.get("pushed") is False


def _write_zab_config_with_projects(tmp_path: Path, projects_root: Path, repo: Path, hermes: Path) -> None:
    import yaml as _yaml

    cfg_d = tmp_path / ".config" / "zab"
    cfg_d.mkdir(parents=True, exist_ok=True)
    (cfg_d / "config.yaml").write_text(
        _yaml.safe_dump(
            {
                "skills_roots": [str(repo.resolve())],
                "projects_roots": [str(projects_root.resolve())],
                "skills_sync": {
                    "repo_root": str(repo.resolve()),
                    "git_remote": "git@example.invalid:x/y.git",
                    "hermes_config_path": str(hermes.resolve()),
                    "auto_hermes_update": True,
                    "notify": False,
                    "notify_channel": "evolution",
                },
                "cli_watchlist": [],
                "tracked_env_extra": [],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_auto_sync_imports_carrefour_project_skill_to_orgs(tmp_path, monkeypatch) -> None:
    """Skill sous projects/carrefour/danmdata/.cursor/skills/... → orgs/carrefour/skills/<slug>."""
    import yaml as _yaml

    projects_root = tmp_path / "projects"
    danm = projects_root / "carrefour" / "danmdata"
    skill_src = danm / ".cursor" / "skills" / "data-uat-bigquery" / "SKILL.md"
    skill_src.parent.mkdir(parents=True)
    skill_src.write_text(
        "---\nname: data-uat-bigquery\ndescription: BQ UAT\n---\n\n# Skill\n",
        encoding="utf-8",
    )

    repo = tmp_path / "skills-repo"
    ensure_repo_initialized(repo)
    (repo / "common" / "skills").mkdir(parents=True, exist_ok=True)

    hermes = tmp_path / ".hermes" / "config.yaml"
    hermes.parent.mkdir(parents=True)
    hermes.write_text(_yaml.safe_dump({"skills": {"external_dirs": []}}), encoding="utf-8")

    _write_zab_config_with_projects(tmp_path, projects_root, repo, hermes)

    monkeypatch.setattr("zab.services.hermes_config.skills_sync_settings", skills_sync_settings)

    report = skills_sync_status.auto_sync_project_skills()
    dest = repo / "orgs" / "carrefour" / "skills" / "data-uat-bigquery" / "SKILL.md"
    assert dest.is_file()
    assert any(x.get("slug") == "data-uat-bigquery" for x in report["imported"])
    assert report["imported"][0].get("org") == "carrefour"
    assert report["imported"][0].get("project") == "danmdata"
    data = _yaml.safe_load(hermes.read_text(encoding="utf-8"))
    assert str((repo / "orgs" / "carrefour" / "skills").resolve()) in data["skills"]["external_dirs"]
    assert report.get("notification", {}).get("skipped") is True


def test_auto_sync_skips_noise_paths(tmp_path, monkeypatch) -> None:
    import yaml as _yaml

    projects_root = tmp_path / "projects"
    # Sous .cursor, un dossier hermes-docker peut être parcouru (non caché par « dot »).
    noise1 = (
        projects_root
        / "flowmetrik"
        / "hermes-webui"
        / ".cursor"
        / "hermes-docker"
        / "skills"
        / "noise-skill"
        / "SKILL.md"
    )
    noise1.parent.mkdir(parents=True)
    noise1.write_text("---\nname: noise-skill\n---\n", encoding="utf-8")

    tpl = projects_root / "carrefour" / "danm-skills" / ".cursor" / "templates" / "skill" / "SKILL.md"
    tpl.parent.mkdir(parents=True)
    tpl.write_text("---\nname: tpl\n---\n", encoding="utf-8")

    ok_skill = projects_root / "carrefour" / "app" / ".cursor" / "skills" / "keep-me" / "SKILL.md"
    ok_skill.parent.mkdir(parents=True)
    ok_skill.write_text("---\nname: keep-me\n---\n", encoding="utf-8")

    repo = tmp_path / "skills-repo"
    ensure_repo_initialized(repo)
    (repo / "common" / "skills").mkdir(parents=True, exist_ok=True)

    hermes = tmp_path / ".hermes" / "config.yaml"
    hermes.parent.mkdir(parents=True)
    hermes.write_text(_yaml.safe_dump({"skills": {"external_dirs": []}}), encoding="utf-8")

    _write_zab_config_with_projects(tmp_path, projects_root, repo, hermes)
    monkeypatch.setattr("zab.services.hermes_config.skills_sync_settings", skills_sync_settings)

    report = skills_sync_status.auto_sync_project_skills()
    slugs = {x.get("slug") for x in report["imported"]}
    assert "noise-skill" not in slugs
    assert "tpl" not in slugs
    assert "keep-me" in slugs


def test_api_skills_auto_sync_endpoint(tmp_path, monkeypatch) -> None:
    import yaml as _yaml

    projects_root = tmp_path / "projects"
    danm = projects_root / "carrefour" / "danmdata"
    skill_src = danm / ".cursor" / "skills" / "gitlab-pm" / "SKILL.md"
    skill_src.parent.mkdir(parents=True)
    skill_src.write_text("---\nname: gitlab-pm\n---\n", encoding="utf-8")

    repo = tmp_path / "skills-repo"
    ensure_repo_initialized(repo)
    (repo / "common" / "skills").mkdir(parents=True, exist_ok=True)

    hermes = tmp_path / ".hermes" / "config.yaml"
    hermes.parent.mkdir(parents=True)
    hermes.write_text(_yaml.safe_dump({"skills": {"external_dirs": []}}), encoding="utf-8")

    _write_zab_config_with_projects(tmp_path, projects_root, repo, hermes)

    def fake_settings() -> dict:
        return {
            "repo_root": str(repo.resolve()),
            "git_remote": "git@example.invalid:x/y.git",
            "hermes_config_path": str(hermes.resolve()),
            "auto_sync": False,
            "auto_hermes_update": False,
            "notify": False,
            "notify_channel": "evolution",
        }

    monkeypatch.setattr("zab.user_config.skills_sync_settings", fake_settings)
    monkeypatch.setattr("zab.services.skills_sync_status.skills_sync_settings", fake_settings)
    monkeypatch.setattr("zab.services.hermes_config.skills_sync_settings", fake_settings)
    monkeypatch.setattr("zab.services.skills_git_sync.skills_sync_settings", fake_settings)

    client = TestClient(create_app())
    r = client.post("/api/skills/auto-sync")
    assert r.status_code == 200
    body = r.json()
    assert any(x.get("slug") == "gitlab-pm" for x in body.get("imported", []))
    assert "hermes" in body
