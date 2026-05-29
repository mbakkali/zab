"""ensure_user_config_exists et modèle par défaut."""

import pytest

from zab.user_config import (
    ensure_user_config_exists,
    load_user_config,
    merge_scan_inventory_into_config,
    user_config_path,
)


def test_ensure_creates_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    home = tmp_path_factory.mktemp("empty-home")
    monkeypatch.setenv("HOME", str(home))
    created = ensure_user_config_exists()
    assert created is not None
    assert created.resolve() == user_config_path().resolve()
    assert user_config_path().is_file()
    again = ensure_user_config_exists()
    assert again is None


def test_default_yaml_loads(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    home = tmp_path_factory.mktemp("empty-home2")
    monkeypatch.setenv("HOME", str(home))
    ensure_user_config_exists()
    cfg = load_user_config()
    assert "_error" not in cfg
    assert cfg.get("cli_watchlist") == []
    assert cfg.get("tracked_env_extra") == []
    assert cfg.get("skills_roots") == []
    assert cfg.get("skill_md_paths") in (None, [])
    assert cfg.get("claude_plugin_paths") == []


def test_merge_scan_inventory_clears_skills_roots(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    import yaml

    home = tmp_path_factory.mktemp("cfg-inv")
    monkeypatch.setenv("HOME", str(home))
    cfg_d = home / ".config" / "zab"
    cfg_d.mkdir(parents=True)
    md = home / "w" / "SKILL.md"
    md.parent.mkdir(parents=True)
    md.write_text("---\nname: t\n---\n", encoding="utf-8")
    (cfg_d / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "skills_roots": ["/tmp/legacy"],
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
    merge_scan_inventory_into_config([str(md.resolve())], claude_plugin_abs_paths=[])
    cfg = load_user_config()
    assert cfg.get("skills_roots") == []
    assert cfg.get("skill_md_paths") in (None, [])
    from zab.services import skills_registry

    adopted = {str(p) for p in skills_registry.adopted_skill_md_paths_resolved()}
    assert str(md.resolve()) in adopted
