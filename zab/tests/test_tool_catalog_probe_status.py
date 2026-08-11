"""Régression sur `_probe_status` pour la sonde `connector`.

Deux bugs distincts crashaient ce code avant correction :
- `any((shutil.which("composio") or composio_cli_path()) and env_keys)` appelait
  `any()` sur un booléen scalaire au lieu d'un itérable ; quand ni le binaire
  composio ni son chemin résolu n'existent, l'expression vaut `None` et
  `any(None)` lève `TypeError`.
- la branche "connecteur trouvé" utilisait `os.environ.get(...)` sans que le
  module `os` soit importé dans ce fichier, ce qui levait `NameError` dès
  qu'un outil déclarait un `env_keys` non vide pour un connecteur enregistré
  (c'est le cas réel de Fireflies).
"""

from __future__ import annotations

from zab.services import tool_catalog


def _connector_tool(env_keys: list[str]) -> dict:
    return {
        "id": "tool_fireflies",
        "probe": {"kind": "connector", "slug": "fireflies", "env_keys": env_keys},
    }


def test_probe_status_connector_missing_and_no_composio(monkeypatch) -> None:
    """Connecteur absent, ni CLI ni chemin composio résolus : ne doit pas lever."""
    monkeypatch.setattr(tool_catalog.connectors_aggregate, "get_connector", lambda slug: None)
    monkeypatch.setattr(tool_catalog.shutil, "which", lambda name: None)
    monkeypatch.setattr(tool_catalog, "composio_cli_path", lambda: None)

    assert tool_catalog._probe_status(_connector_tool(["FIREFLIES_API_KEY"])) == "fail"


def test_probe_status_connector_missing_with_composio_cli(monkeypatch) -> None:
    """Connecteur absent mais CLI composio disponible et env_keys déclarés -> warn."""
    monkeypatch.setattr(tool_catalog.connectors_aggregate, "get_connector", lambda slug: None)
    monkeypatch.setattr(tool_catalog.shutil, "which", lambda name: "/usr/bin/composio" if name == "composio" else None)

    assert tool_catalog._probe_status(_connector_tool(["FIREFLIES_API_KEY"])) == "warn"


def test_probe_status_connector_found_with_env_keys_missing(monkeypatch) -> None:
    """Connecteur enregistré, env_keys déclaré, variable absente : ne doit pas lever NameError."""
    monkeypatch.delenv("FIREFLIES_API_KEY", raising=False)
    monkeypatch.setattr(
        tool_catalog.connectors_aggregate,
        "get_connector",
        lambda slug: {"id": slug, "forms": []},
    )

    assert tool_catalog._probe_status(_connector_tool(["FIREFLIES_API_KEY"])) == "warn"


def test_probe_status_connector_found_with_env_ready(monkeypatch) -> None:
    """Connecteur enregistré et variable d'environnement présente -> ok."""
    monkeypatch.setenv("FIREFLIES_API_KEY", "secret-value-not-a-real-key")
    monkeypatch.setattr(
        tool_catalog.connectors_aggregate,
        "get_connector",
        lambda slug: {"id": slug, "forms": []},
    )

    assert tool_catalog._probe_status(_connector_tool(["FIREFLIES_API_KEY"])) == "ok"
