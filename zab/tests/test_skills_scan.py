"""Tests du scan récursif des SKILL.md."""

from __future__ import annotations

from pathlib import Path

import pytest

from zab.services import skills_registry
from zab.services.skills_scan import collect_skill_md_under_repo, iter_skill_md_recursive


def _write_skill(path: Path, *, name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: {name}\n---\n# {name}\n", encoding="utf-8")


def test_iter_skill_md_recursive_finds_nested_category_skill(tmp_path: Path) -> None:
    md = tmp_path / "apple" / "chrome-applescript-control" / "SKILL.md"
    _write_skill(md, name="chrome-applescript-control")
    found = iter_skill_md_recursive(tmp_path / "apple")
    assert [p.resolve() for p in found] == [md.resolve()]


def test_iter_skill_md_recursive_skips_archive(tmp_path: Path) -> None:
    visible = tmp_path / "creative" / "logo" / "SKILL.md"
    hidden = tmp_path / ".archive" / "old" / "SKILL.md"
    _write_skill(visible, name="logo")
    _write_skill(hidden, name="old")
    found = iter_skill_md_recursive(tmp_path)
    assert [p.resolve() for p in found] == [visible.resolve()]


def test_collect_skill_md_under_repo_includes_orgs_common_and_categories(tmp_path: Path) -> None:
    repo = tmp_path / "skills"
    _write_skill(repo / "common" / "skills" / "shared" / "SKILL.md", name="shared")
    _write_skill(repo / "orgs" / "carrefour" / "skills" / "spend" / "SKILL.md", name="spend")
    _write_skill(repo / "apple" / "chrome-applescript-control" / "SKILL.md", name="chrome-applescript-control")
    _write_skill(repo / "watchdog-heartbeat" / "SKILL.md", name="watchdog-heartbeat")

    found = {str(p.resolve()) for p in collect_skill_md_under_repo(repo)}
    assert str((repo / "common" / "skills" / "shared" / "SKILL.md").resolve()) in found
    assert str((repo / "orgs" / "carrefour" / "skills" / "spend" / "SKILL.md").resolve()) in found
    assert str((repo / "apple" / "chrome-applescript-control" / "SKILL.md").resolve()) in found
    assert str((repo / "watchdog-heartbeat" / "SKILL.md").resolve()) in found


def test_infer_org_slug_for_category_layout(tmp_path: Path) -> None:
    repo = tmp_path / "skills"
    md = repo / "apple" / "chrome-applescript-control" / "SKILL.md"
    _write_skill(md, name="chrome-applescript-control")
    assert skills_registry.infer_org_slug_for_skill_file(md, repo) == "apple"


def test_refresh_registry_from_disk_indexes_category_skill(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = tmp_path / "mirror"
    md = repo / "apple" / "chrome-applescript-control" / "SKILL.md"
    _write_skill(md, name="chrome-applescript-control")

    reg = tmp_path / "skills-registry.json"
    monkeypatch.setattr(skills_registry, "registry_path", lambda: reg)
    reg.write_text('{"version": 1, "updated_at": "t", "skills": []}', encoding="utf-8")
    monkeypatch.setattr(
        "zab.services.skills_registry.skills_sync_settings",
        lambda: {
            "repo_root": str(repo),
            "hermes_config_path": str(tmp_path / ".hermes" / "config.yaml"),
            "git_remote": "",
            "auto_sync": False,
            "auto_hermes_update": False,
            "notify": False,
            "notify_channel": "evolution",
        },
    )
    monkeypatch.setattr(
        "zab.services.workspace_projects.discover_projects",
        lambda: [],
    )

    skills_registry.refresh_registry_from_disk()
    rows = skills_registry.query_registry()
    hit = next((r for r in rows if r.get("slug") == "chrome-applescript-control"), None)
    assert hit is not None
    assert hit.get("org") == "apple"
    assert hit.get("status") == "candidate"
    assert str(md.resolve()) in {str(s.get("path")) for s in hit.get("sources") or [] if isinstance(s, dict)}
