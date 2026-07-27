"""Localisation de clés dans les fichiers .env."""

import os
from pathlib import Path

from zab.paths import config_dir
from zab.services.dotenv_locate import dotenv_key_line, load_standard_dotenvs_once, standard_dotenv_paths


def test_dotenv_key_line_finds_export_and_comment(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("# header\nFOO=1\nexport BAR=2\n", encoding="utf-8")
    assert dotenv_key_line(env, "FOO") == 2
    assert dotenv_key_line(env, "BAR") == 3
    assert dotenv_key_line(env, "MISSING") is None


def test_load_standard_dotenvs_once_reads_zab_env(monkeypatch) -> None:
    env = config_dir() / ".env"
    env.parent.mkdir(parents=True, exist_ok=True)
    env.write_text("ZAB_TEST_DOTENV_LOAD=present\n", encoding="utf-8")
    monkeypatch.delenv("ZAB_TEST_DOTENV_LOAD", raising=False)

    loaded = load_standard_dotenvs_once(force=True)

    assert env.resolve() in loaded
    assert os.environ["ZAB_TEST_DOTENV_LOAD"] == "present"


def test_standard_dotenv_paths_include_checkout_env(monkeypatch, tmp_path: Path) -> None:
    repo = tmp_path / "zab"
    repo.mkdir()
    monkeypatch.setattr("zab.services.dotenv_locate.zab_repo_root", lambda: repo)

    paths = standard_dotenv_paths()

    assert repo / ".env.local" in paths
    assert repo / ".env" in paths
