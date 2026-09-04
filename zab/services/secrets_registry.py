"""Le registre des connecteurs dont zab n'était pas au courant.

`zab security status` savait dire qu'une variable manquait, mais il ne savait
pas quelles variables **devaient** exister : la liste était figée dans
`secrets_catalog.py`, 42 noms écrits à la main. Deux conséquences mesurées le
2026-09-04 :

  · `ATTIO_API_KEY` et `FIREFLIES_API_KEY` n'y figuraient pas, alors que deux
    canaux du ledger en dépendent — le statut ne les regardait jamais ;
  · zab connaissait 25 connecteurs là où le registre de l'organisation en
    déclare 36, et répondait « clé absente » pour `attio` quand la clé existe :
    elle vit dans un coffre que zab ne balayait pas.

Ce module lit un registre **externe et déclaratif**, dont le chemin se pose en
configuration (`connectors_registry`). zab reste générique ; il apprend
seulement où l'autorité vit. Sans cette clé, rien ne change.

Le registre ne contient aucune valeur : uniquement des noms de variables et des
chemins de coffres. C'est précisément ce qu'il faut pour dire « la donnée est
là » sans jamais la lire.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from zab.user_config import load_user_config

# Les clés du registre qui portent un nom de variable d'environnement. Chacune
# accepte une chaîne ou une liste : `qonto` en déclare deux.
_CLES_ENV = ("api", "env")


def registry_path() -> Path | None:
    """Le registre déclaré en configuration, s'il existe."""
    try:
        brut = (load_user_config() or {}).get("connectors_registry")
    except Exception:
        return None
    if not brut:
        return None
    chemin = Path(str(brut)).expanduser()
    return chemin if chemin.is_file() else None


def load_registry() -> dict[str, Any] | None:
    chemin = registry_path()
    if chemin is None:
        return None
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _noms_dune_entree(valeur: Any) -> list[str]:
    if isinstance(valeur, str):
        return [valeur]
    if isinstance(valeur, list):
        return [str(v) for v in valeur if isinstance(v, str)]
    if isinstance(valeur, dict):
        return _noms_dune_entree(valeur.get("env"))
    return []


def tracked_names() -> list[str]:
    """Les variables que le registre dit nécessaires, connecteur par connecteur."""
    registre = load_registry()
    if not registre:
        return []
    noms: list[str] = []
    for connecteur in registre.get("connectors") or []:
        if not isinstance(connecteur, dict):
            continue
        for cle in _CLES_ENV:
            noms.extend(_noms_dune_entree(connecteur.get(cle)))
    return sorted({n for n in noms if n})


def connectors_by_env() -> dict[str, list[str]]:
    """Quelle variable sert à quel connecteur — pour nommer ce qui manque.

    « `FULLENRICH_API_KEY` absente » ne dit rien ; « FullEnrich est hors
    service, sa clé manque » dit quoi réparer.
    """
    registre = load_registry()
    if not registre:
        return {}
    par_var: dict[str, list[str]] = {}
    for connecteur in registre.get("connectors") or []:
        if not isinstance(connecteur, dict):
            continue
        ident = str(connecteur.get("id") or "")
        for cle in _CLES_ENV:
            for nom in _noms_dune_entree(connecteur.get(cle)):
                par_var.setdefault(nom, [])
                if ident and ident not in par_var[nom]:
                    par_var[nom].append(ident)
    return par_var


def vault_paths() -> list[Path]:
    """Les coffres déclarés par le registre, en chemins absolus.

    Un chemin relatif se résout depuis le dépôt qui porte le registre — c'est
    ainsi qu'il est écrit (`.secrets/cockpit.env`, par exemple), et le résoudre
    depuis le répertoire courant donnerait un fichier différent à chaque appel.
    """
    registre = load_registry()
    ancre = registry_path()
    if not registre or ancre is None:
        return []
    racine = ancre.parent.parent  # <dépôt>/connectors/registry.json
    coffres: list[Path] = []
    for coffre in ((registre.get("engine") or {}).get("vaults") or {}).values():
        brut = (coffre or {}).get("path") if isinstance(coffre, dict) else None
        if not brut or "*" in str(brut):
            continue  # un motif de fichiers n'est pas un `.env` à lire
        chemin = Path(str(brut)).expanduser()
        if not chemin.is_absolute():
            chemin = racine / chemin
        coffres.append(chemin)
    return coffres


def summary() -> dict[str, Any]:
    """Ce que le registre apporte, pour que `security status` puisse le dire."""
    registre = load_registry()
    chemin = registry_path()
    if not registre:
        return {"present": False, "path": str(chemin) if chemin else None}
    return {
        "present": True,
        "path": str(chemin),
        "connectors": len(registre.get("connectors") or []),
        "tracked_names": len(tracked_names()),
        "vaults": [str(p) for p in vault_paths()],
    }


def _cles_dun_fichier(chemin: Path) -> set[str]:
    """Les noms de variables non vides d'un `.env`, sans jamais garder la valeur."""
    cles: set[str] = set()
    try:
        texte = chemin.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return cles
    for ligne in texte.splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        nom, _, valeur = ligne.partition("=")
        if valeur.strip().strip("\"'"):
            cles.add(nom.strip().removeprefix("export ").strip())
    return cles


def connector_env_present(connector_id: str) -> tuple[bool, str]:
    """Les variables d'un connecteur sont-elles résolvables ici ?

    Regarde l'environnement du processus, puis les coffres déclarés par le
    registre. C'est ce second passage qui manquait : le contrôle d'`attio`
    interrogeait `os.environ["ATTIO_API_KEY"]` et répondait « absente » pendant
    que la clé, nommée autrement, dormait dans un coffre jamais ouvert.

    Ne rend qu'un booléen et un motif : aucune valeur ne sort d'ici.
    """
    import os

    attendus = [
        nom for nom, ids in connectors_by_env().items() if connector_id in ids
    ]
    if not attendus:
        return False, f"{connector_id}=inconnu_du_registre"

    manquants: list[str] = []
    disponibles: set[str] = {
        nom for nom in attendus if (os.environ.get(nom) or "").strip()
    }
    if len(disponibles) < len(attendus):
        for coffre in vault_paths():
            disponibles |= _cles_dun_fichier(coffre) & set(attendus)

    manquants = [nom for nom in attendus if nom not in disponibles]
    if manquants:
        # Dernier recours : le relevé de sécurité, qui balaie tous les `.env`
        # de la machine et pas seulement les coffres déclarés. C'est lui qui
        # sait qu'une clé peut vivre dans un `.env` de projet, hors coffre déclaré.
        manquants = [n for n in manquants if not _vu_dans_inventaire(n)]
    if manquants:
        return False, f"{connector_id}_env_manquant={','.join(sorted(manquants))}"
    return True, f"{connector_id}_env=present"


def _vu_dans_inventaire(nom: str) -> bool:
    """Le dernier relevé de cette machine a-t-il vu cette variable ?

    Le relevé est daté et stocké ; le consulter coûte une lecture, là où
    rebalayer tous les `.env` coûterait une vingtaine de secondes à chaque
    contrôle de canal.
    """
    try:
        from zab.services import secrets_inventory

        inventaire = secrets_inventory.load() or {}
    except Exception:
        return False
    return bool(((inventaire.get("variables") or {}).get(nom) or {}).get("present"))
