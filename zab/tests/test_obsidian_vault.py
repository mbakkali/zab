"""Tests du module obsidian_vault."""

from __future__ import annotations

from datetime import date as date_cls
from pathlib import Path

import pytest

from zab.services import obsidian_vault as ov


def _setup_vault(home: Path) -> Path:
    vault = home / "ObsidianVault"
    for d in ov.EXPECTED_DIRS:
        (vault / d).mkdir(parents=True, exist_ok=True)
    (vault / "_attachments").mkdir(exist_ok=True)
    (vault / "90_meta" / "templates").mkdir(parents=True, exist_ok=True)
    (vault / "90_meta" / "templates" / "daily.md").write_text(
        "---\ntype: daily\ncreated: {{date}}\n---\n\n# {{date}}\n\n## Notes\n",
        encoding="utf-8",
    )
    cfg = home / ".config" / "zab"
    cfg.mkdir(parents=True)
    (cfg / "config.yaml").write_text(
        f"obsidian:\n  vault_path: {vault}\n  allow_full_write: false\n",
        encoding="utf-8",
    )
    return vault


def test_validate_vault_ok(monkeypatch, tmp_path_factory) -> None:
    home = tmp_path_factory.mktemp("vault-home")
    monkeypatch.setenv("HOME", str(home))
    vault = _setup_vault(home)
    info = ov.validate_vault(vault)
    assert info["ok"] is True
    assert info["missing_dirs"] == []


def test_validate_vault_missing_dirs(monkeypatch, tmp_path_factory) -> None:
    home = tmp_path_factory.mktemp("vault-home")
    monkeypatch.setenv("HOME", str(home))
    vault = home / "ObsidianVault"
    vault.mkdir()
    (vault / "00_inbox").mkdir()
    info = ov.validate_vault(vault)
    assert info["ok"] is False
    assert "10_daily" in info["missing_dirs"]


def test_parse_frontmatter_roundtrip() -> None:
    text = "---\nname: foo\ntags: [a, b]\n---\n\n# Body\nlorem\n"
    front, body = ov.parse_frontmatter(text)
    assert front == {"name": "foo", "tags": ["a", "b"]}
    assert body.startswith("# Body")


def test_parse_frontmatter_absent() -> None:
    front, body = ov.parse_frontmatter("# Just a title\n")
    assert front == {}
    assert body == "# Just a title\n"


def test_read_note(monkeypatch, tmp_path_factory) -> None:
    home = tmp_path_factory.mktemp("vault-home")
    monkeypatch.setenv("HOME", str(home))
    vault = _setup_vault(home)
    note = vault / "50_notes" / "hello.md"
    note.write_text("---\nname: hello\n---\n\n# Hello\n", encoding="utf-8")
    out = ov.read_note("50_notes/hello.md", vault=vault)
    assert out["ok"] is True
    assert out["frontmatter"] == {"name": "hello"}
    assert "Hello" in out["body"]


def test_read_note_traversal_blocked(monkeypatch, tmp_path_factory) -> None:
    home = tmp_path_factory.mktemp("vault-home")
    monkeypatch.setenv("HOME", str(home))
    vault = _setup_vault(home)
    (home / "secret.md").write_text("nope", encoding="utf-8")
    with pytest.raises(ValueError):
        ov.read_note("../secret.md", vault=vault)


def test_list_notes(monkeypatch, tmp_path_factory) -> None:
    home = tmp_path_factory.mktemp("vault-home")
    monkeypatch.setenv("HOME", str(home))
    vault = _setup_vault(home)
    (vault / "50_notes" / "a.md").write_text("a", encoding="utf-8")
    (vault / "20_projects" / "p.md").write_text("p", encoding="utf-8")
    (vault / "_attachments" / "img-note.md").write_text("skip", encoding="utf-8")
    out = ov.list_notes(vault=vault)
    assert "50_notes/a.md" in out
    assert "20_projects/p.md" in out
    assert not any("_attachments" in x for x in out)


def test_vault_search(monkeypatch, tmp_path_factory) -> None:
    home = tmp_path_factory.mktemp("vault-home")
    monkeypatch.setenv("HOME", str(home))
    vault = _setup_vault(home)
    (vault / "50_notes" / "n.md").write_text("Some MCP idea here\nAnother line\n", encoding="utf-8")
    hits = ov.vault_search("mcp", vault=vault)
    assert any(h["rel"] == "50_notes/n.md" and h["line"] == 1 for h in hits)


def test_ensure_daily_note_creates_with_template(monkeypatch, tmp_path_factory) -> None:
    home = tmp_path_factory.mktemp("vault-home")
    monkeypatch.setenv("HOME", str(home))
    vault = _setup_vault(home)
    on = date_cls(2026, 5, 14)
    target = ov.ensure_daily_note(on=on, vault=vault)
    assert target.is_file()
    assert target.name == "2026-05-14.md"
    text = target.read_text(encoding="utf-8")
    assert "2026-05-14" in text
    assert "{{date}}" not in text


def test_daily_append(monkeypatch, tmp_path_factory) -> None:
    home = tmp_path_factory.mktemp("vault-home")
    monkeypatch.setenv("HOME", str(home))
    vault = _setup_vault(home)
    on = date_cls(2026, 5, 14)
    ov.daily_append("- premier point", on=on, vault=vault)
    ov.daily_append("- second point", on=on, vault=vault)
    text = (vault / "10_daily" / "2026-05-14.md").read_text(encoding="utf-8")
    assert "premier point" in text and "second point" in text


def test_inbox_create_refuses_overwrite_and_paths(monkeypatch, tmp_path_factory) -> None:
    home = tmp_path_factory.mktemp("vault-home")
    monkeypatch.setenv("HOME", str(home))
    vault = _setup_vault(home)
    ov.inbox_create("idea", "body\n", vault=vault)
    assert (vault / "00_inbox" / "idea.md").is_file()
    with pytest.raises(FileExistsError):
        ov.inbox_create("idea.md", "again", vault=vault)
    with pytest.raises(ValueError):
        ov.inbox_create("sub/foo.md", "x", vault=vault)
    with pytest.raises(ValueError):
        ov.inbox_create("../escape.md", "x", vault=vault)


def test_doctor_payload(monkeypatch, tmp_path_factory) -> None:
    home = tmp_path_factory.mktemp("vault-home")
    monkeypatch.setenv("HOME", str(home))
    vault = _setup_vault(home)
    (vault / "50_notes" / "x.md").write_text("hi", encoding="utf-8")
    payload = ov.doctor_payload()
    assert payload["exists"] is True
    assert payload["notes_count"] >= 1
    assert payload["allow_full_write"] is False
    assert payload["validation"]["ok"] is True
