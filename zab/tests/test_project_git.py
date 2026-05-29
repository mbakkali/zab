"""Métadonnées Git lues depuis le dépôt (sans binaire git)."""

from __future__ import annotations

from pathlib import Path

import yaml

from zab.services.project_git import (
    normalize_git_remote_to_https,
    project_git_metadata,
)


def test_normalize_git_remote_ssh_github() -> None:
    assert normalize_git_remote_to_https("git@github.com:acme/foo.git") == "https://github.com/acme/foo"


def test_normalize_https() -> None:
    assert normalize_git_remote_to_https("https://github.com/acme/bar.git") == "https://github.com/acme/bar"


def test_project_git_metadata_with_dot_git_dir(monkeypatch, tmp_path_factory) -> None:
    home = tmp_path_factory.mktemp("gitmeta-home")
    monkeypatch.setenv("HOME", str(home))
    proot = home / "projects"
    app = proot / "myapp"
    git = app / ".git"
    git.mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git / "config").write_text(
        '[remote "origin"]\n\turl = git@github.com:org/myapp.git\n',
        encoding="utf-8",
    )
    skill = app / "SKILL.md"
    skill.write_text("# s\n", encoding="utf-8")

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

    from zab.services.workspace_projects import discover_projects

    rows = discover_projects()
    assert len(rows) == 1
    r = rows[0]
    assert r["git_repo"] is True
    assert r["git_branch"] == "main"
    assert r["remote_host"] == "github"
    assert "github.com" in (r.get("origin_https") or "")


def test_project_git_metadata_no_git(monkeypatch, tmp_path_factory) -> None:
    home = tmp_path_factory.mktemp("nogit-home")
    monkeypatch.setenv("HOME", str(home))
    proot = home / "projects"
    app = proot / "plain"
    app.mkdir(parents=True)
    (app / "SKILL.md").write_text("# s\n", encoding="utf-8")
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
    from zab.services.workspace_projects import discover_projects

    rows = discover_projects()
    assert rows[0].get("git_repo") is False


def test_project_git_metadata_path_only(tmp_path: Path) -> None:
    p = tmp_path / "solo"
    p.mkdir()
    git = p / ".git"
    git.mkdir()
    (git / "HEAD").write_text("ref: refs/heads/dev\n", encoding="utf-8")
    (git / "config").write_text(
        '[remote "origin"]\n\turl = https://gitlab.com/grp/proj.git\n',
        encoding="utf-8",
    )
    meta = project_git_metadata(p)
    assert meta["git_repo"] is True
    assert meta["git_branch"] == "dev"
    assert meta["remote_host"] == "gitlab"
