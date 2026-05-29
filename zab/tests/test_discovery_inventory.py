"""Découverte pilotée par skills-registry.json (et repli skills_roots)."""

from __future__ import annotations

import yaml

from zab.services import discovery


def test_list_orgs_from_skill_inventory(monkeypatch, tmp_path_factory) -> None:
    home = tmp_path_factory.mktemp("inv-home-orgs")
    monkeypatch.setenv("HOME", str(home))
    repo = home / "skills-repo"
    skill_a = repo / "orgs" / "acme" / "skills" / "payroll" / "SKILL.md"
    skill_b = repo / "orgs" / "acme" / "skills" / "hr" / "SKILL.md"
    skill_c = repo / ".cursor" / "skills" / "misc" / "SKILL.md"
    for p in (skill_a, skill_b, skill_c):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("---\nname: x\n---\n", encoding="utf-8")

    cfg_d = home / ".config" / "zab"
    cfg_d.mkdir(parents=True, exist_ok=True)
    (cfg_d / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "skills_roots": [],
                "skill_md_paths": [str(skill_a.resolve()), str(skill_b.resolve()), str(skill_c.resolve())],
                "claude_plugin_paths": [],
                "cli_watchlist": [],
                "tracked_env_extra": [],
                "skills_sync": {"repo_root": str(repo.resolve())},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    orgs = discovery.list_orgs_with_skills()
    assert len(orgs) == 2
    by_org = {o["org"]: o for o in orgs}
    assert len(by_org["acme"]["skills"]) == 2
    assert len(by_org["hors-org"]["skills"]) == 1


def test_discovery_repo_bases_from_skill_paths(monkeypatch, tmp_path_factory) -> None:
    home = tmp_path_factory.mktemp("inv-home-mcp")
    monkeypatch.setenv("HOME", str(home))
    repo = home / "skills-repo"
    (repo / "configs").mkdir(parents=True, exist_ok=True)
    (repo / "configs" / "cursor-mcp.json").write_text("{}", encoding="utf-8")
    md = repo / "orgs" / "x" / "skills" / "y" / "SKILL.md"
    md.parent.mkdir(parents=True)
    md.write_text("# s\n", encoding="utf-8")
    cfg_d = home / ".config" / "zab"
    cfg_d.mkdir(parents=True, exist_ok=True)
    (cfg_d / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "skills_roots": [],
                "skill_md_paths": [str(md.resolve())],
                "claude_plugin_paths": [],
                "cli_watchlist": [],
                "tracked_env_extra": [],
                "skills_sync": {"repo_root": str(repo.resolve())},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    bases = discovery.discovery_repo_bases()
    assert any(b.resolve() == repo.resolve() for b in bases)


def test_explicit_plugin_bundles(monkeypatch, tmp_path_factory) -> None:
    home = tmp_path_factory.mktemp("inv-home-plug")
    monkeypatch.setenv("HOME", str(home))
    plug = home / "plug" / "my-plugin"
    (plug / ".claude-plugin").mkdir(parents=True)
    (plug / ".claude-plugin" / "plugin.json").write_text("{}", encoding="utf-8")
    (plug / "skills" / "foo").mkdir(parents=True)
    (plug / "skills" / "foo" / "SKILL.md").write_text("# x\n", encoding="utf-8")
    cfg_d = home / ".config" / "zab"
    cfg_d.mkdir(parents=True, exist_ok=True)
    (cfg_d / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "skills_roots": [],
                "skill_md_paths": [],
                "claude_plugin_paths": [str(plug.resolve())],
                "cli_watchlist": [],
                "tracked_env_extra": [],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    bundles = discovery.list_claude_plugin_bundles()
    assert len(bundles) == 1
    assert bundles[0]["id"] == "my-plugin"
    assert bundles[0].get("fs_path")


def test_list_orgs_includes_common_skills_repo_layout(monkeypatch, tmp_path_factory) -> None:
    home = tmp_path_factory.mktemp("inv-home-common")
    monkeypatch.setenv("HOME", str(home))
    repo = home / "skills-repo"
    md = repo / "common" / "skills" / "shared" / "SKILL.md"
    md.parent.mkdir(parents=True)
    md.write_text("---\nname: shared\n---\n", encoding="utf-8")
    cfg_d = home / ".config" / "zab"
    cfg_d.mkdir(parents=True, exist_ok=True)
    (cfg_d / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "skills_roots": [str(repo.resolve())],
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

    orgs = discovery.list_orgs_with_skills()

    by_org = {o["org"]: o for o in orgs}
    assert by_org["common"]["skills"][0]["id"] == "shared"
    assert by_org["common"]["skills"][0]["path"] == "common/skills/shared/SKILL.md"
