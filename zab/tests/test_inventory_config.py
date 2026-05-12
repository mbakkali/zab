"""Helpers inventaire SKILL.md / bundles Claude."""

from pathlib import Path

from zab.services.inventory_config import (
    collect_plugin_roots_from_skill_paths,
    infer_claude_plugin_bundle_root,
    infer_mcp_repo_base_from_skill_md,
)


def test_infer_plugin_bundle_root(tmp_path: Path) -> None:
    plug = tmp_path / "p"
    (plug / ".claude-plugin").mkdir(parents=True)
    (plug / ".claude-plugin" / "plugin.json").write_text("{}", encoding="utf-8")
    md = plug / "skills" / "z" / "SKILL.md"
    md.parent.mkdir(parents=True)
    md.write_text("# a\n", encoding="utf-8")
    assert infer_claude_plugin_bundle_root(md) == plug.resolve()


def test_infer_mcp_base(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    (repo / "configs").mkdir(parents=True)
    (repo / "configs" / "cursor-mcp.json").write_text("{}", encoding="utf-8")
    md = repo / "a" / "SKILL.md"
    md.parent.mkdir(parents=True)
    md.write_text("# b\n", encoding="utf-8")
    assert infer_mcp_repo_base_from_skill_md(md) == repo.resolve()


def test_collect_plugin_roots_dedup(tmp_path: Path) -> None:
    plug = tmp_path / "pl"
    (plug / ".claude-plugin").mkdir(parents=True)
    (plug / ".claude-plugin" / "plugin.json").write_text("{}", encoding="utf-8")
    m1 = plug / "skills" / "a" / "SKILL.md"
    m2 = plug / "skills" / "b" / "SKILL.md"
    m1.parent.mkdir(parents=True)
    m2.parent.mkdir(parents=True)
    m1.write_text("#\n", encoding="utf-8")
    m2.write_text("#\n", encoding="utf-8")
    roots = collect_plugin_roots_from_skill_paths([m1, m2])
    assert len(roots) == 1
