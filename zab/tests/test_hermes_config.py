from __future__ import annotations

from pathlib import Path

import yaml

from zab.services.hermes_config import update_external_dirs


def test_update_external_dirs_merges_skill_dirs_with_backup(tmp_path: Path) -> None:
    cfg = tmp_path / "hermes" / "config.yaml"
    cfg.parent.mkdir()
    cfg.write_text(
        yaml.safe_dump({"server": {"port": 1234}, "skills": {"external_dirs": ["/old"]}}),
        encoding="utf-8",
    )
    repo = tmp_path / "skills"
    (repo / "orgs" / "acme" / "skills" / "alpha").mkdir(parents=True)
    (repo / "orgs" / "flowmetrik" / "skills" / "beta").mkdir(parents=True)
    (repo / "common" / "skills" / "shared").mkdir(parents=True)

    result = update_external_dirs(config_path=cfg, repo_root=repo, apply=True)

    assert result.changed is True
    assert result.backup_path is not None
    assert Path(result.backup_path).is_file()
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert data["server"]["port"] == 1234
    assert data["skills"]["external_dirs"] == [
        str((repo / "common" / "skills").resolve()),
        str((repo / "orgs" / "acme" / "skills").resolve()),
        str((repo / "orgs" / "flowmetrik" / "skills").resolve()),
    ]


def test_update_external_dirs_is_idempotent_and_supports_dry_run(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    repo = tmp_path / "skills"
    skills_dir = repo / "orgs" / "acme" / "skills"
    skills_dir.mkdir(parents=True)
    cfg.write_text(yaml.safe_dump({"skills": {"external_dirs": [str(skills_dir.resolve())]}}), encoding="utf-8")

    dry = update_external_dirs(config_path=cfg, repo_root=repo, apply=False)
    assert dry.changed is False
    assert dry.backup_path is None

    applied = update_external_dirs(config_path=cfg, repo_root=repo, apply=True)
    assert applied.changed is False
    assert applied.backup_path is None
