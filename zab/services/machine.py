"""Où zab tourne — Mac de travail, VM cowork, ou machine quelconque.

Zab tourne aux deux endroits, avec le même code et la même configuration, et
c'est justement le problème : rien à l'écran ne dit lequel on regarde. Deux
onglets ouverts côte à côte sont indiscernables, et on répare alors la mauvaise
machine.

Ce n'est pas cosmétique. Plusieurs sources **n'existent que d'un côté** :

  · iMessage lit `~/Library/Messages/chat.db`, qui n'existe que sur macOS. Sur
    la VM le canal remonte en `error`, et rien ne dit que l'erreur est normale ;
  · les clés de coffre et les sessions OAuth sont propres à chaque machine ;
  · un `dist/` construit d'un côté n'est pas synchronisé de l'autre.

Savoir où l'on est transforme « c'est cassé » en « ça ne peut pas marcher
ici », et ces deux phrases n'appellent pas le même geste.
"""

from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any

# Le nom d'hôte de la VM cowork. Il sert de marqueur POSITIF : deviner « Linux
# donc VM » se tromperait sur n'importe quel autre poste Linux.
HOTE_VM = "flowmetrik-cowork-linux"


def _nom_tailscale() -> str | None:
    """Le nom court de la machine sur le tailnet, s'il répond.

    Borné à 5 s et jamais fatal : `tailscale` peut être absent, arrêté, ou
    lent. Un indicateur de machine qui fait attendre l'écran d'accueil serait
    pire que pas d'indicateur.
    """
    binaire = shutil.which("tailscale")
    if not binaire:
        return None
    try:
        proc = subprocess.run(
            [binaire, "status", "--self", "--peers=false", "--json"],
            capture_output=True, text=True, timeout=5, check=False,
            stdin=subprocess.DEVNULL,
        )
        if proc.returncode != 0:
            return None
        import json

        self_ = (json.loads(proc.stdout) or {}).get("Self") or {}
        nom = str(self_.get("DNSName") or "").strip(".")
        return nom.split(".")[0] or None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def get_machine() -> dict[str, Any]:
    """Décrire la machine qui exécute zab, et ce qui n'y est pas disponible."""
    systeme = platform.system()
    hote = socket.gethostname()
    court = hote.split(".")[0]

    if systeme == "Darwin":
        genre, libelle = "mac", "Mac"
    elif court == HOTE_VM or court.startswith("flowmetrik-cowork"):
        genre, libelle = "vm", "VM cowork"
    else:
        genre, libelle = "autre", court or systeme

    # Les sources qui ne peuvent pas fonctionner ici, et pourquoi. Une source
    # absente par nature n'est pas une panne — la confondre avec une panne fait
    # chercher une réparation qui n'existe pas.
    #
    # `motifs` est la liste des identifiants sous lesquels la source apparaît
    # ailleurs, et elle n'est pas décorative : le canal iMessage porte
    # `channel_type: ios_messages` et `channel_id: imessage-local`. Un écran
    # qui ne chercherait que « imessage » ne le reconnaîtrait pas, et
    # afficherait une pastille rouge pour une source qui ne peut pas exister.
    indisponibles: list[dict[str, Any]] = []
    if genre != "mac":
        indisponibles.append({
            "source": "imessage",
            "motifs": ["imessage", "ios_messages", "messages-local"],
            "raison": "`~/Library/Messages/chat.db` n'existe que sur macOS",
        })
        indisponibles.append({
            "source": "apple-contacts",
            "motifs": ["apple-contacts", "apple_contacts", "addressbook"],
            "raison": "le carnet Apple n'est lisible que depuis macOS",
        })

    return {
        "contract": "zab-machine",
        "contract_version": "1.0",
        "genre": genre,
        "libelle": libelle,
        "hote": court,
        "systeme": systeme,
        "version_systeme": platform.release(),
        "architecture": platform.machine(),
        "utilisateur": os.environ.get("USER") or os.environ.get("LOGNAME") or "",
        "home": str(Path.home()),
        "tailscale": _nom_tailscale(),
        "sources_indisponibles": indisponibles,
    }
