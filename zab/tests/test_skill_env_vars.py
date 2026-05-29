"""Tests pour skill_env_vars (extraction + indexation des .env)."""

from __future__ import annotations

from pathlib import Path

import pytest

from zab.services import skill_env_vars as sev


def test_extract_env_var_names_basic() -> None:
    text = """
    | Variable | Description |
    | `QONTO_ID` | Org id |
    | `QONTO_SECRET_KEY` | Secret |
    Random ALLCAPS but not an env var: TODO, README, HTTP, API, JSON.
    Single token PASSWORD detected. Underscore NAME_WITH_UNDERSCORES detected.
    """
    out = sev.extract_env_var_names(text)
    assert "QONTO_ID" in out
    assert "QONTO_SECRET_KEY" in out
    assert "PASSWORD" in out
    assert "NAME_WITH_UNDERSCORES" in out
    assert "TODO" not in out
    assert "HTTP" not in out
    assert "API" not in out


def test_build_env_index_and_lookup(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    (root / "proj_a").mkdir(parents=True)
    (root / "proj_b").mkdir(parents=True)
    (root / "proj_a" / ".env").write_text("QONTO_ID=abc\nQONTO_SECRET_KEY=def\n# comment\nexport FOO=bar\n", encoding="utf-8")
    (root / "proj_b" / ".env").write_text("QONTO_ID=zzz\nOTHER=1\n", encoding="utf-8")
    skill = tmp_path / "SKILL.md"
    skill.write_text("Needs QONTO_ID and QONTO_SECRET_KEY and MISSING_VAR_TOKEN.", encoding="utf-8")
    idx = sev.build_env_index([root])
    assert sorted(idx["QONTO_ID"]) == sorted([str((root / "proj_a" / ".env").resolve()), str((root / "proj_b" / ".env").resolve())])
    assert idx["FOO"] == [str((root / "proj_a" / ".env").resolve())]
    out = sev.env_vars_for_skill(skill, idx)
    by_name = {v["name"]: v for v in out}
    assert by_name["QONTO_ID"]["present"] is True
    assert len(by_name["QONTO_ID"]["files"]) == 2
    assert by_name["QONTO_SECRET_KEY"]["present"] is True
    assert by_name["MISSING_VAR_TOKEN"]["present"] is False
    assert by_name["MISSING_VAR_TOKEN"]["files"] == []


def test_env_index_skips_noise_dirs(tmp_path: Path) -> None:
    root = tmp_path
    (root / "node_modules" / "inside").mkdir(parents=True)
    (root / "node_modules" / "inside" / ".env").write_text("HIDDEN=1\n")
    (root / "src").mkdir()
    (root / "src" / ".env").write_text("VISIBLE_TOKEN=1\n")
    idx = sev.build_env_index([root])
    assert "VISIBLE_TOKEN" in idx
    assert "HIDDEN" not in idx
