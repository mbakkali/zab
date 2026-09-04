"""Le registre externe de connecteurs : ce qu'il apporte au statut sécurité.

Sans lui, la liste des variables attendues était figée dans le code — 42 noms
écrits à la main, dont ni `ATTIO_API_KEY` ni `FIREFLIES_API_KEY`, alors que deux
canaux du ledger en dépendent. Et les coffres qu'il déclare n'étaient pas
balayés : zab répondait « clé absente » pour une clé bien rangée.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from zab.paths import config_dir
from zab.services import secrets_registry

REGISTRE = {
    "engine": {
        "vaults": {
            "principal": {"path": "~/.config/zab/.env"},
            "cockpit": {"path": ".secrets/cockpit.env"},
            "comptes": {"path": ".secrets/credentials/*.json"},
        }
    },
    "connectors": [
        {"id": "attio", "api": {"env": "acme_attio_api_key"}},
        {"id": "qonto", "api": {"env": ["QONTO_ID", "QONTO_SECRET_KEY"]}},
        {"id": "zab", "cli": "zab"},
    ],
}


@pytest.fixture()
def registre_declare(tmp_path: Path) -> Path:
    """Pose un registre et le déclare dans la configuration isolée du test."""
    depot = tmp_path / "cowork"
    (depot / "connectors").mkdir(parents=True)
    chemin = depot / "connectors" / "registry.json"
    chemin.write_text(json.dumps(REGISTRE), encoding="utf-8")

    cfg = config_dir() / "config.yaml"
    donnees = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    donnees["connectors_registry"] = str(chemin)
    cfg.write_text(yaml.safe_dump(donnees, allow_unicode=True), encoding="utf-8")
    return chemin


def test_sans_registre_rien_ne_change() -> None:
    """La clé est facultative : zab reste générique s'il n'en a pas."""
    assert secrets_registry.registry_path() is None
    assert secrets_registry.tracked_names() == []
    assert secrets_registry.vault_paths() == []
    assert secrets_registry.summary()["present"] is False


def test_les_noms_de_variables_viennent_du_registre(registre_declare: Path) -> None:
    noms = secrets_registry.tracked_names()
    assert "acme_attio_api_key" in noms
    # Un connecteur peut en déclarer plusieurs : Qonto en a deux.
    assert "QONTO_ID" in noms and "QONTO_SECRET_KEY" in noms
    # Un connecteur sans clé d'API n'ajoute rien.
    assert len(noms) == 3


def test_chaque_variable_nomme_le_connecteur_quelle_sert(
    registre_declare: Path,
) -> None:
    """« FULLENRICH_API_KEY absente » ne dit rien ; nommer le service dit quoi réparer."""
    par_var = secrets_registry.connectors_by_env()
    assert par_var["acme_attio_api_key"] == ["attio"]
    assert par_var["QONTO_SECRET_KEY"] == ["qonto"]


def test_les_coffres_relatifs_se_resolvent_depuis_le_depot(
    registre_declare: Path,
) -> None:
    """Résolus depuis le répertoire courant, ils désigneraient un autre fichier."""
    coffres = [str(p) for p in secrets_registry.vault_paths()]
    depot = registre_declare.parent.parent
    assert str(depot / ".secrets/cockpit.env") in coffres
    assert str(Path.home() / ".config/zab/.env") in coffres
    # Un motif de fichiers n'est pas un `.env` à lire.
    assert not any("*" in c for c in coffres)


def test_le_statut_securite_suit_les_variables_du_registre(
    registre_declare: Path,
) -> None:
    from zab.user_config import tracked_env_names_for_security

    suivies = tracked_env_names_for_security()
    assert "acme_attio_api_key" in suivies
    assert "QONTO_ID" in suivies


def test_un_registre_illisible_ne_casse_rien(tmp_path: Path) -> None:
    """Un fichier corrompu ne doit pas empêcher `security status` de répondre."""
    chemin = tmp_path / "registry.json"
    chemin.write_text("{ ceci n'est pas du json", encoding="utf-8")
    cfg = config_dir() / "config.yaml"
    donnees = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    donnees["connectors_registry"] = str(chemin)
    cfg.write_text(yaml.safe_dump(donnees, allow_unicode=True), encoding="utf-8")

    assert secrets_registry.load_registry() is None
    assert secrets_registry.tracked_names() == []
