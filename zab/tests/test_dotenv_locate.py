"""Localisation de clés dans les fichiers .env."""

from pathlib import Path

from zab.services.dotenv_locate import dotenv_key_line


def test_dotenv_key_line_finds_export_and_comment(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("# header\nFOO=1\nexport BAR=2\n", encoding="utf-8")
    assert dotenv_key_line(env, "FOO") == 2
    assert dotenv_key_line(env, "BAR") == 3
    assert dotenv_key_line(env, "MISSING") is None
