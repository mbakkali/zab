from pathlib import Path


from zab.paths import orgs_dir, resolve_skills_root, skills_root


def test_resolve_skills_root_matches_skills_root(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ZAB_SKILLS_ROOT", raising=False)
    monkeypatch.delenv("ZAB_INVOCATION_CWD", raising=False)
    from zab import user_config

    def _empty() -> dict:
        return {}

    monkeypatch.setattr(user_config, "load_user_config", _empty)
    monkeypatch.chdir(tmp_path)
    path, rule = resolve_skills_root()
    assert path.resolve() == tmp_path.resolve()
    assert "cwd" in rule.lower()
    assert skills_root().resolve() == path.resolve()


def test_skills_root_env_override(monkeypatch, tmp_path: Path) -> None:
    fake = tmp_path / "fake-skills"
    fake.mkdir()
    (fake / "orgs").mkdir()
    monkeypatch.setenv("ZAB_SKILLS_ROOT", str(fake))
    root = skills_root()
    assert root.resolve() == fake.resolve()
    assert orgs_dir() == fake / "orgs"


def test_skills_root_default_is_cwd(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ZAB_SKILLS_ROOT", raising=False)
    # Évite la lecture du vrai ~/.config/zab/config.yaml pendant les tests
    from zab import user_config

    def _empty() -> dict:
        return {}

    monkeypatch.setattr(user_config, "load_user_config", _empty)
    monkeypatch.chdir(tmp_path)
    root = skills_root()
    assert root.resolve() == tmp_path.resolve()


def test_dashboard_anchor_from_skill_md_finds_repo_root(monkeypatch, tmp_path: Path) -> None:
    """Quand skills_roots est vide, l’ancre dashboard doit être la racine du dépôt (configs/cursor-mcp.json), pas le dossier du SKILL.md."""
    repo = tmp_path / "skills"
    skill_dir = repo / "pack" / "foo-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# x\n", encoding="utf-8")
    (repo / "configs").mkdir(parents=True)
    (repo / "configs" / "cursor-mcp.json").write_text("{}\n", encoding="utf-8")

    from zab import user_config
    from zab.services import skills_registry

    def fake_load() -> dict:
        return {"skills_roots": [], "claude_plugin_paths": []}

    monkeypatch.setattr(user_config, "load_user_config", fake_load)
    monkeypatch.setattr(
        skills_registry,
        "adopted_skill_md_paths_resolved",
        lambda: [(skill_dir / "SKILL.md").resolve()],
    )

    from zab.paths import dashboard_anchor_path

    assert dashboard_anchor_path() == repo.resolve()


def test_skills_root_honors_zab_invocation_cwd(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ZAB_SKILLS_ROOT", raising=False)
    monkeypatch.delenv("ZAB_INVOCATION_CWD", raising=False)
    from zab import user_config

    def _empty() -> dict:
        return {}

    monkeypatch.setattr(user_config, "load_user_config", _empty)
    (tmp_path / "inner").mkdir()
    monkeypatch.chdir(tmp_path / "inner")
    monkeypatch.setenv("ZAB_INVOCATION_CWD", str(tmp_path / "invoked-from"))
    root = skills_root()
    assert root.resolve() == (tmp_path / "invoked-from").resolve()
