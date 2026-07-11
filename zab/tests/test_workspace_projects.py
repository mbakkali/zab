"""Découverte projets locaux et inférence d’organisation."""

from __future__ import annotations

import yaml

from zab.services import discovery
from zab.services import skills_fs
from zab.services.workspace_projects import discover_projects, infer_org_slug, project_dir_is_under_projects_roots
from zab.user_config import clear_user_config_cache


def test_infer_org_slug(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg_d = tmp_path / ".config" / "zab"
    cfg_d.mkdir(parents=True, exist_ok=True)
    (cfg_d / "config.yaml").write_text(
        yaml.safe_dump({"organizations": ["work", "personal", "clients"]}),
        encoding="utf-8",
    )
    clear_user_config_cache()

    assert infer_org_slug("clients-portal") == "clients"
    assert infer_org_slug("work-website") == "work"
    assert infer_org_slug("personal-notes") == "personal"
    assert infer_org_slug("litellm") == "hors-org"
    assert infer_org_slug("zab") == "zab"


def test_discover_projects_includes_repo_markers_without_skills(monkeypatch, tmp_path_factory) -> None:
    home = tmp_path_factory.mktemp("wp-repo-marker")
    monkeypatch.setenv("HOME", str(home))
    proot = home / "projects"
    project = proot / "zab"
    project.mkdir(parents=True)
    (project / "pyproject.toml").write_text("[project]\nname = \"zab\"\n", encoding="utf-8")

    cfg_d = home / ".config" / "zab"
    cfg_d.mkdir(parents=True)
    (cfg_d / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "skills_roots": [],
                "projects_roots": [str(proot.resolve())],
                "skill_md_paths": [],
                "claude_plugin_paths": [],
                "cli_watchlist": [],
                "tracked_env_extra": [],
                "organizations": ["work"],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    rows = discover_projects()

    assert len(rows) == 1
    assert rows[0]["name"] == "zab"
    assert rows[0]["org"] == "zab"
    assert rows[0]["skills"] == []
    assert "project_markers" in rows[0]["detection_reasons"]


def test_discover_projects_cursor_claude(monkeypatch, tmp_path_factory) -> None:
    home = tmp_path_factory.mktemp("wp-home")
    monkeypatch.setenv("HOME", str(home))
    proot = home / "projects"
    proot.mkdir()
    p1 = proot / "work-app"
    p1.mkdir()
    cskill = p1 / ".cursor" / "skills" / "ctx" / "SKILL.md"
    cskill.parent.mkdir(parents=True)
    cskill.write_text("# c\n", encoding="utf-8")
    aclaude = p1 / ".claude" / "skills" / "other" / "SKILL.md"
    aclaude.parent.mkdir(parents=True)
    aclaude.write_text("# a\n", encoding="utf-8")

    cfg_d = home / ".config" / "zab"
    cfg_d.mkdir(parents=True)
    (cfg_d / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "skills_roots": [],
                "projects_roots": [str(proot.resolve())],
                "skill_md_paths": [],
                "claude_plugin_paths": [],
                "cli_watchlist": [],
                "tracked_env_extra": [],
                "organizations": ["work"],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    rows = discover_projects()
    assert len(rows) == 1
    assert rows[0]["name"] == "work-app"
    assert rows[0]["org"] == "work"
    assert rows[0].get("workspace_parent") is None
    assert len(rows[0]["skills"]) == 2
    ids = {s["id"] for s in rows[0]["skills"]}
    assert ids == {"ctx", "other"}


def test_discover_projects_excludes_global_skills_repo(monkeypatch, tmp_path_factory) -> None:
    home = tmp_path_factory.mktemp("wp-exclude-skills")
    monkeypatch.setenv("HOME", str(home))
    proot = home / "projects"
    proot.mkdir()
    global_repo = proot / "skills"
    rogue_project_skill = global_repo / ".cursor" / "skills" / "duplicate" / "SKILL.md"
    rogue_project_skill.parent.mkdir(parents=True)
    rogue_project_skill.write_text("# duplicate\n", encoding="utf-8")
    real_project = proot / "demo-app"
    real_skill = real_project / ".cursor" / "skills" / "ctx" / "SKILL.md"
    real_skill.parent.mkdir(parents=True)
    real_skill.write_text("# ctx\n", encoding="utf-8")

    cfg_d = home / ".config" / "zab"
    cfg_d.mkdir(parents=True)
    (cfg_d / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "projects_roots": [str(proot.resolve())],
                "skills_roots": [str(global_repo.resolve())],
                "skill_md_paths": [],
                "claude_plugin_paths": [],
                "cli_watchlist": [],
                "tracked_env_extra": [],
                "skills_sync": {"repo_root": str(global_repo.resolve())},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    rows = discover_projects()

    assert [row["name"] for row in rows] == ["demo-app"]


def test_discover_projects_nested_org(monkeypatch, tmp_path_factory) -> None:
    home = tmp_path_factory.mktemp("wp-nested")
    monkeypatch.setenv("HOME", str(home))
    proot = home / "projects"
    proot.mkdir()
    org = proot / "clients"
    org.mkdir()
    leaf = org / "acme-app"
    leaf.mkdir()
    skill = leaf / ".cursor" / "skills" / "bq" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# n\n", encoding="utf-8")

    cfg_d = home / ".config" / "zab"
    cfg_d.mkdir(parents=True)
    (cfg_d / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "skills_roots": [],
                "projects_roots": [str(proot.resolve())],
                "skill_md_paths": [],
                "claude_plugin_paths": [],
                "cli_watchlist": [],
                "tracked_env_extra": [],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    rows = discover_projects()
    assert len(rows) == 1
    assert rows[0]["name"] == "acme-app"
    assert rows[0]["org"] == "clients"
    assert rows[0]["workspace_parent"] == "clients"
    assert {s["id"] for s in rows[0]["skills"]} == {"bq"}


def test_project_dir_depth_two_allowed(monkeypatch, tmp_path_factory) -> None:
    home = tmp_path_factory.mktemp("wp-depth")
    monkeypatch.setenv("HOME", str(home))
    proot = home / "projects"
    leaf = proot / "clients" / "tooling"
    leaf.mkdir(parents=True)
    cfg_d = home / ".config" / "zab"
    cfg_d.mkdir(parents=True)
    (cfg_d / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "skills_roots": [],
                "projects_roots": [str(proot.resolve())],
                "skill_md_paths": [],
                "claude_plugin_paths": [],
                "cli_watchlist": [],
                "tracked_env_extra": [],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    assert project_dir_is_under_projects_roots(leaf) is True
    assert project_dir_is_under_projects_roots(leaf / "too" / "deep") is False


def test_merge_workspace_into_orgs(monkeypatch, tmp_path_factory) -> None:
    home = tmp_path_factory.mktemp("merge-home")
    monkeypatch.setenv("HOME", str(home))
    repo = home / "skills-repo"
    (repo / "orgs" / "acme" / "skills" / "legacy" / "SKILL.md").parent.mkdir(parents=True)
    (repo / "orgs" / "acme" / "skills" / "legacy" / "SKILL.md").write_text("# L\n", encoding="utf-8")

    proot = home / "projects"
    proot.mkdir()
    app = proot / "clients-ui"
    app.mkdir()
    ws = app / ".cursor" / "skills" / "clients-context" / "SKILL.md"
    ws.parent.mkdir(parents=True)
    ws.write_text("# W\n", encoding="utf-8")

    cfg_d = home / ".config" / "zab"
    cfg_d.mkdir(parents=True)
    (cfg_d / "config.yaml").write_text(
        yaml.safe_dump(
                {
                    "skills_roots": [str(repo.resolve())],
                    "projects_roots": [str(proot.resolve())],
                    "organizations": ["acme", "clients"],
                    "cli_watchlist": [],
                    "tracked_env_extra": [],
                },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    orgs = discovery.list_orgs_with_skills()
    by_org = {o["org"]: o for o in orgs}
    assert "acme" in by_org
    assert "clients" in by_org
    clients_skills = {s["id"]: s for s in by_org["clients"]["skills"]}
    assert "clients-context" in clients_skills
    assert clients_skills["clients-context"].get("source") == "workspace"


def test_resolve_skill_path_under_projects_roots(monkeypatch, tmp_path_factory) -> None:
    home = tmp_path_factory.mktemp("fs-home")
    monkeypatch.setenv("HOME", str(home))
    proot = home / "projects"
    app = proot / "demo"
    md = app / ".claude" / "skills" / "x" / "SKILL.md"
    md.parent.mkdir(parents=True)
    md.write_text("# z\n", encoding="utf-8")
    cfg_d = home / ".config" / "zab"
    cfg_d.mkdir(parents=True)
    (cfg_d / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "skills_roots": [],
                "projects_roots": [str(proot.resolve())],
                "skill_md_paths": [],
                "claude_plugin_paths": [],
                "cli_watchlist": [],
                "tracked_env_extra": [],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    got = skills_fs.resolve_skill_md_path(str(md.resolve()), must_exist=True)
    assert got.resolve() == md.resolve()
