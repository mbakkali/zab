"""Tests unitaires du registre skills (fichier JSON isolé)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zab.services import skills_registry


def _minimal_skill_md(path: Path, *, name: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: {name}\n---\n# {name}\n", encoding="utf-8")


def test_save_load_roundtrip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    reg = tmp_path / "skills-registry.json"
    monkeypatch.setattr(skills_registry, "registry_path", lambda: reg)
    doc = {"version": 1, "updated_at": "t0", "skills": []}
    skills_registry.save_registry_document(doc)
    assert reg.is_file()
    loaded = skills_registry.load_registry_document()
    assert loaded["version"] == 1
    assert isinstance(loaded.get("skills"), list)


def test_adopt_unadopt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    reg = tmp_path / "skills-registry.json"
    monkeypatch.setattr(skills_registry, "registry_path", lambda: reg)
    md = tmp_path / "demo" / "SKILL.md"
    _minimal_skill_md(md)
    key = "acme:demo"
    skills_registry.replace_skills_entries(
        {
            key: {
                "key": key,
                "org": "acme",
                "slug": "demo",
                "status": "candidate",
                "canonical_path": None,
                "sources": [
                    {
                        "kind": "workspace",
                        "path": str(md.resolve()),
                        "project": "p1",
                        "last_seen_at": skills_registry.utc_now_iso(),
                    }
                ],
                "sync": {},
                "tags": [],
                "description": None,
                "frontmatter_name": None,
            }
        }
    )
    out = skills_registry.adopt_registry_key(key, canonical_path=str(md.resolve()))
    assert out.get("ok") is True
    rows = skills_registry.query_registry(status="adopted")
    assert any(r.get("key") == key for r in rows)
    out2 = skills_registry.unadopt_registry_key(key)
    assert out2.get("ok") is True
    rows_c = skills_registry.query_registry(status="candidate")
    assert any(r.get("key") == key for r in rows_c)


def test_registry_counts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    reg = tmp_path / "skills-registry.json"
    monkeypatch.setattr(skills_registry, "registry_path", lambda: reg)
    reg.write_text(
        json.dumps(
            {
                "version": 1,
                "updated_at": "t",
                "skills": [
                    {"key": "a:a1", "org": "a", "slug": "a1", "status": "adopted", "sources": []},
                    {"key": "b:b1", "org": "b", "slug": "b1", "status": "candidate", "sources": []},
                    {"key": "c:c1", "org": "c", "slug": "c1", "status": "ignored", "sources": []},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    c = skills_registry.registry_counts()
    assert c["adopted"] == 1 and c["candidate"] == 1 and c["ignored"] == 1 and c["total"] == 3


def test_hermes_export_yaml_contains_external_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    reg = tmp_path / "skills-registry.json"
    monkeypatch.setattr(skills_registry, "registry_path", lambda: reg)
    reg.write_text(json.dumps({"version": 1, "updated_at": "t", "skills": []}), encoding="utf-8")
    monkeypatch.setattr(
        "zab.user_config.skills_sync_settings",
        lambda: {
            "repo_root": str(tmp_path / "mirror"),
            "hermes_config_path": str(tmp_path / ".hermes" / "config.yaml"),
            "git_remote": "",
            "auto_sync": False,
            "auto_hermes_update": False,
            "notify": False,
            "notify_channel": "evolution",
        },
    )
    (tmp_path / "mirror" / "common" / "skills").mkdir(parents=True)
    yaml = skills_registry.hermes_export_yaml_fragment()
    assert "external_dirs:" in yaml
    assert "skills:" in yaml
