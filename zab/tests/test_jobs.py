import pytest

from zab.paths import skills_root_from_config_file_only
from zab.services.jobs import build_argv_for_preset


def test_unknown_preset():
    with pytest.raises(ValueError, match="inconnu"):
        build_argv_for_preset("nope", {})


def test_smoke_argv():
    argv, cwd = build_argv_for_preset("smoke_mcps", None)
    assert "smoke_test_all_mcps.sh" in argv[-1]
    assert cwd == str(skills_root_from_config_file_only().resolve())
