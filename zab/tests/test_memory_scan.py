"""Tests du bloc memory_stack."""

from pathlib import Path

from zab.services.memory_scan import build_memory_stack, resolve_mehdi_memory_database_url


def test_build_memory_stack_shape(tmp_path, monkeypatch):
    monkeypatch.delenv("MEHDI_MEMORY_DATABASE_URL", raising=False)
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "import_memory_jsonl.py").write_text("# x", encoding="utf-8")

    stack = build_memory_stack(tmp_path)
    assert "mempalace" in stack
    assert "on_path" in stack["mempalace"]
    assert stack["MEHDI_MEMORY_DATABASE_URL_configured"] is False
    assert stack["postgres_probe"]["skipped_reason"] == "dsn_absent"
    assert stack["skills_scripts"]["import_memory_jsonl_exists"] is True
    assert stack["skills_scripts"]["extract_mempalace_to_jsonl_exists"] is False


def test_resolve_database_url_from_parent_env(tmp_path, monkeypatch):
    monkeypatch.delenv("MEHDI_MEMORY_DATABASE_URL", raising=False)
    skill_dir = tmp_path / "common" / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (tmp_path / ".env").write_text("MEHDI_MEMORY_DATABASE_URL=postgresql://user:pass@localhost/db\n", encoding="utf-8")

    assert resolve_mehdi_memory_database_url(skill_dir) == "postgresql://user:pass@localhost/db"
