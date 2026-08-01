from __future__ import annotations

from pathlib import Path

import yaml

from zab.services import workstation_sync as ws


def _config(tmp_path: Path, watchlist: list[str] | None) -> None:
    cfg_dir = tmp_path / ".config" / "zab"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    payload: dict = {}
    if watchlist is not None:
        payload["cli_watchlist"] = watchlist
    (cfg_dir / "config.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")


def test_empty_watchlist_is_reported_as_unconfigured(monkeypatch, tmp_path: Path) -> None:
    """Sans watchlist, « 0/0 » se lisait comme un succès sur une machine neuve."""
    monkeypatch.setenv("HOME", str(tmp_path))
    _config(tmp_path, None)

    payload = ws.cli_status()

    assert payload["total"] == 0
    assert payload["configured"] is False


def test_populated_watchlist_is_reported_as_configured(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _config(tmp_path, ["python3", "definitivement-absent-xyz"])

    payload = ws.cli_status()

    assert payload["configured"] is True
    assert payload["total"] == 2
    assert "definitivement-absent-xyz" in payload["missing"]


def test_watchlist_entries_all_have_an_installer_or_are_runtimes(monkeypatch, tmp_path: Path) -> None:
    """`gh` et `rg` restaient manquants sans moyen de les installer."""
    for name in ("gh", "rg"):
        assert name in ws.CLI_INSTALL_COMMANDS
