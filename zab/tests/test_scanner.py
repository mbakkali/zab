"""Tests du scanner SKILL.md depuis ~ et vérif Agentpipe."""

from __future__ import annotations

from pathlib import Path

from zab.services.scanner import (
    resolve_optional_scan_root,
    scan_agentpipe,
    scan_skill_md_files,
    workspace_scan,
)


def test_scan_skill_md_respects_ignore_dirs(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ZAB_SKILLS_ROOT", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "seen" / "skills" / "a").mkdir(parents=True)
    (tmp_path / "seen" / "skills" / "a" / "SKILL.md").write_text("# x\n", encoding="utf-8")
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "SKILL.md").write_text("# noisy\n", encoding="utf-8")

    hits = scan_skill_md_files(tmp_path)
    paths = [h["path"] for h in hits]
    assert "seen/skills/a/SKILL.md" in paths
    assert all("node_modules" not in p for p in paths)


def test_resolve_optional_scan_root_relative_to_home(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "projects" / "foo").mkdir(parents=True)
    rp = resolve_optional_scan_root("projects/foo")
    assert rp is not None
    assert rp == (tmp_path / "projects" / "foo").resolve()


def test_workspace_scan_warns_on_out_of_tree_root(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("ZAB_SKILLS_ROOT", str(tmp_path))
    outsider = tmp_path.parent / f"{tmp_path.name}-outside-zab-scan"
    report = workspace_scan(outsider)
    assert report.get("warnings")
    assert report["skill_md_count"] >= 0
    assert report["scan_root_resolved"] == str(tmp_path.resolve())


def test_workspace_scan_defaults_to_home(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("ZAB_SKILLS_ROOT", str(tmp_path / "skills-repo"))
    (tmp_path / "skills-repo").mkdir(parents=True, exist_ok=True)
    (tmp_path / "x").mkdir(parents=True)
    (tmp_path / "x" / "SKILL.md").write_text("# s\n", encoding="utf-8")
    report = workspace_scan(None)
    assert report["scan_root_resolved"] == str(tmp_path.resolve())
    assert report["user_home"] == str(tmp_path.resolve())
    paths = [h["path"] for h in report["skill_md_files"]]
    assert "x/SKILL.md" in paths


def test_scan_agentpipe_shape():
    ap = scan_agentpipe()
    assert isinstance(ap["agents"], list)
    assert "present" in ap and "path" in ap
    assert "agents_total" in ap and "agents_on_path" in ap
    assert "cli_agentpipe_binary" in ap
    assert "coding_models_flat" in ap
    assert isinstance(ap["coding_models_flat"], list)


def test_scan_agentpipe_extracts_models(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    ap_yaml = tmp_path / ".agentpipe.yaml"
    ap_yaml.write_text(
        """version: "1.0"
agents:
  - id: claude
    type: claude
    model: claude-opus-4-6
  - id: gemini
    type: gemini
    models:
      - gemini-2.5-pro
      - gemini-flash
""",
        encoding="utf-8",
    )
    data = scan_agentpipe()
    assert data["present"] is True
    flat = sorted(data["coding_models_flat"])
    assert flat == ["claude-opus-4-6", "gemini-2.5-pro", "gemini-flash"]
    by_id = {a["id"]: a for a in data["agents"]}
    assert by_id["claude"]["coding_models"] == ["claude-opus-4-6"]
    assert set(by_id["gemini"]["coding_models"]) == {"gemini-2.5-pro", "gemini-flash"}


def test_scan_agentpipe_respects_config_override(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    custom = tmp_path / "custom-ap.yaml"
    custom.write_text(
        'agents:\n  - id: x\n    type: cursor\n    model: test-model\n',
        encoding="utf-8",
    )
    cfg_dir.joinpath("config.yaml").write_text(
        f"skills_roots: []\ncli_watchlist: []\ntracked_env_extra: []\nagentpipe_config_path: {custom}\n",
        encoding="utf-8",
    )
    data = scan_agentpipe()
    assert data["path"] == str(custom.resolve())
    assert "test-model" in data["coding_models_flat"]
