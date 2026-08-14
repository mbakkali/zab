"""Point unique pour les variables suivies : les recenser, les pousser, les redistribuer.

Trois mouvements, et ils ne servent pas la même situation :

``collect``  les ``.env`` des projets → ``~/.config/zab/.env``. C'est l'ancien
             ``pm-env sync``, élargi de quatre jetons de gestion de projet à
             tout le catalogue suivi.
``push``     une valeur en clair → Secret Manager, puis la valeur locale est
             remplacée par sa référence ``sm://``. Le secret cesse d'exister
             en clair sur le disque.
``pull``     une référence ``sm://`` → la valeur, écrite dans un ``.env`` cible.
             C'est ce qui manquait : sur une machine neuve, un dépôt fraîchement
             cloné n'a aucun ``.env``, et rien ne savait les reconstituer.

``pull`` écrit des secrets en clair : c'est son objet, et c'est pourquoi il
exige ``--apply`` et une cible explicite.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from zab.paths import config_dir, skills_root_from_config_file_only
from zab.services import security_secret_sync as provider
from zab.user_config import projects_roots_resolved, tracked_env_names_for_security


def user_dotenv_path() -> Path:
    return config_dir() / ".env"


def _quote_dotenv_value(val: str) -> str:
    v = val.strip()
    if not v:
        return '""'
    if any(c in v for c in "\n\r\"") or " " in v or "#" in v:
        escaped = v.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return v


#: Dossiers qu'on ne traverse jamais : dépendances, caches, artefacts. Sans
#: cette liste, un seul `node_modules` ajoute des milliers de `.env` d'exemples
#: fournis par des paquets tiers, qui ne sont pas les secrets de personne.
_DOSSIERS_IGNORES = frozenset({
    "node_modules", ".venv", "venv", ".git", "__pycache__", "site-packages",
    ".next", ".nuxt", ".turbo", "dist", "build", "coverage", "target", ".cache",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "vendor", "Pods",
    ".Trash-1001", "skills-vendor", ".terraform",
})

#: Profondeur maximale sous une racine. Six suffit pour
#: `racine/espace/projet/service/sous-service/.env` ; au-delà on ramasse des
#: fixtures de test plutôt que de la configuration.
_PROFONDEUR_MAX = 6


def _racines_de_recherche() -> list[Path]:
    """Racines à balayer : celles déclarées à zab, plus le dépôt skills."""
    racines: list[Path] = []
    vues: set[str] = set()
    for candidat in list(projects_roots_resolved()) + [skills_root_from_config_file_only()]:
        if candidat is None:
            continue
        try:
            resolue = Path(candidat).expanduser().resolve()
        except OSError:
            continue
        if resolue.is_dir() and str(resolue) not in vues:
            vues.add(str(resolue))
            racines.append(resolue)
    return racines


def _env_files() -> list[Path]:
    """Tous les ``.env`` sous les racines déclarées, **liens symboliques suivis**.

    La version précédente s'arrêtait à trois niveaux et ne suivait aucun lien.
    Sur un poste réel elle voyait 10 fichiers sur 27 : tout ce qui vit plus
    profond — `espace/projet/backend/.env` — et tout ce qui n'est atteignable
    que par un lien, comme les dossiers agrégés sous `clients/_cowork-links/`,
    lui échappait sans que rien ne le signale.

    Suivre les liens impose deux précautions : dédoublonner sur le chemin réel,
    puisqu'un même fichier est souvent atteignable par plusieurs chemins, et
    mémoriser les répertoires déjà visités, sans quoi un lien qui pointe vers un
    ancêtre fait tourner la descente indéfiniment.
    """
    trouves: dict[str, Path] = {}
    repertoires_vus: set[str] = set()

    def descendre(dossier: Path, profondeur: int) -> None:
        if profondeur > _PROFONDEUR_MAX:
            return
        try:
            reel = str(dossier.resolve())
        except OSError:
            return
        if reel in repertoires_vus:
            return
        repertoires_vus.add(reel)
        try:
            entrees = sorted(dossier.iterdir(), key=lambda p: p.name.casefold())
        except OSError:
            return
        for entree in entrees:
            nom = entree.name
            try:
                if entree.is_file() and nom == ".env":
                    cle = str(entree.resolve())
                    trouves.setdefault(cle, entree.resolve())
                elif entree.is_dir() and nom not in _DOSSIERS_IGNORES:
                    descendre(entree, profondeur + 1)
            except OSError:
                continue

    for racine in _racines_de_recherche():
        descendre(racine, 0)
    return [trouves[k] for k in sorted(trouves)]


def provenance_de(path: Path) -> dict[str, str]:
    """Organisation, projet et chemin déduits de l'emplacement d'un ``.env``.

    La convention ``<org>-cowork`` du poste porte l'organisation ; en dessous,
    le premier sous-dossier nomme le projet. Hors convention, le premier
    segment sous la racine fait office de projet et l'organisation reste vide —
    mieux vaut un champ absent qu'une organisation inventée.
    """
    try:
        resolu = path.resolve()
    except OSError:
        resolu = path
    segments: list[str] = []
    for racine in _racines_de_recherche():
        try:
            segments = list(resolu.relative_to(racine).parts)
            break
        except ValueError:
            continue
    if not segments:
        segments = [resolu.parent.name]
    dossiers = segments[:-1] if segments and segments[-1] == ".env" else segments

    org = ""
    projet = dossiers[0] if dossiers else ""
    if projet.endswith("-cowork"):
        org = projet[: -len("-cowork")]
        if len(dossiers) > 1:
            projet = dossiers[1]
    try:
        affiche = str(resolu.relative_to(Path.home()))
    except ValueError:
        affiche = str(resolu)
    return {"org": org, "project": projet, "path": affiche}


def scan_tracked_values(
    names: tuple[str, ...] | None = None,
    *,
    include_user_dotenv: bool = True,
) -> dict[str, Any]:
    """Recense où vit chaque variable suivie, et sous quelle forme.

    Ne retourne aucune valeur : seulement sa nature — référence, valeur en clair,
    ou absente — et les fichiers qui la déclarent.

    ``~/.config/zab/.env`` est inclus par défaut : l'omettre faisait dire à
    ``status`` qu'une variable était absente alors qu'elle y était renseignée,
    ce qui est le contraire de ce qu'on attend d'un état.
    """
    tracked = names or tracked_env_names_for_security()
    files = list(_env_files())
    if include_user_dotenv:
        user_env = user_dotenv_path()
        if user_env.is_file() and str(user_env.resolve()) not in {str(f) for f in files}:
            files.append(user_env.resolve())
    rows: dict[str, dict[str, Any]] = {
        name: {"name": name, "state": "missing", "files": [], "reference": None}
        for name in tracked
    }

    for path in files:
        try:
            values = dotenv_values(path)
        except OSError:
            continue
        for name in tracked:
            raw = values.get(name)
            if raw is None or not str(raw).strip():
                continue
            value = str(raw).strip()
            row = rows[name]
            row["files"].append(str(path))
            if provider.is_secret_reference(value):
                # Une référence l'emporte : c'est l'état visé.
                row["state"] = "referenced"
                row["reference"] = value
            elif row["state"] != "referenced":
                row["state"] = "plain"

    # L'environnement du processus compte aussi : une variable exportée par le
    # shell est présente pour l'application, même si aucun .env ne la déclare.
    for name in tracked:
        if rows[name]["state"] == "missing" and str(os.environ.get(name, "")).strip():
            rows[name]["state"] = "process"

    counts = {"referenced": 0, "plain": 0, "process": 0, "missing": 0}
    for row in rows.values():
        counts[row["state"]] += 1
    return {
        "scanned_files": [str(p) for p in files],
        "counts": counts,
        "variables": [rows[name] for name in tracked],
    }


def _upsert_dotenv(path: Path, valeurs: dict[str, str], *, entete: str = "") -> list[str]:
    """Met à jour les clés en place et ajoute les nouvelles à la fin.

    Ne réécrit jamais le fichier de zéro. La version précédente le reconstruisait
    en lignes triées ``K=V`` : elle effaçait au passage tous les commentaires et
    l'ordre voulu, c'est-à-dire la seule chose qui rendait le fichier lisible.
    """
    texte = path.read_text(encoding="utf-8") if path.is_file() else ""
    lignes = texte.splitlines(keepends=True)
    restantes = dict(valeurs)
    touchees: list[str] = []

    for index, brute in enumerate(lignes):
        nu = brute.strip()
        if not nu or nu.startswith("#") or "=" not in nu:
            continue
        cle, reste = nu.split("=", 1)
        cle = cle.strip()
        prefixe = ""
        if cle.startswith("export "):
            prefixe, cle = "export ", cle[len("export "):].strip()
        if cle not in restantes:
            continue
        fin = brute[len(brute.rstrip("\n")):]
        commentaire = provider._trailing_comment(reste)
        lignes[index] = f"{prefixe}{cle}={_quote_dotenv_value(restantes.pop(cle))}{commentaire}{fin}"
        touchees.append(cle)

    if restantes:
        bloc = ("\n" + entete + "\n") if entete else "\n"
        bloc += "\n".join(f"{k}={_quote_dotenv_value(v)}" for k, v in sorted(restantes.items())) + "\n"
        lignes.append(("" if texte.endswith("\n") or not texte else "\n") + bloc)
        touchees.extend(sorted(restantes))

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lignes), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return touchees


def collect_to_user_dotenv(*, force: bool = False, apply: bool = True) -> dict[str, Any]:
    """Fusionne les valeurs des ``.env`` projets vers le collecteur."""
    tracked = tracked_env_names_for_security()
    trouvees: dict[str, str] = {}
    fichiers = _env_files()
    origines: dict[str, Path] = {}
    for path in fichiers:
        try:
            values = dotenv_values(path)
        except OSError:
            continue
        for name in tracked:
            if name in trouvees:
                continue
            raw = values.get(name)
            if raw is not None and str(raw).strip():
                trouvees[name] = str(raw).strip()
                origines[name] = path

    cible = user_dotenv_path()
    existantes = dotenv_values(cible) if cible.is_file() else {}
    presentes = {k for k, v in existantes.items() if v is not None and str(v).strip()}
    provenances = _charger_provenances()

    a_ecrire: dict[str, str] = {}
    ignorees: list[str] = []
    for name in tracked:
        valeur = trouvees.get(name)
        if not valeur:
            continue
        if name in presentes and not force:
            ignorees.append(name)
            continue
        if str(existantes.get(name) or "") != valeur:
            a_ecrire[name] = valeur

    ecrites: list[str] = []
    if apply and a_ecrire:
        ecrites = _upsert_dotenv(
            cible, a_ecrire, entete="# Collectées depuis les .env projets (zab secrets collect)."
        )
        # La provenance se perd à la collecte : une fois la valeur dans le
        # collecteur, plus rien ne dit de quel projet elle venait. On la note
        # à côté, au moment où on la connaît encore.
        for nom in a_ecrire:
            origine = origines.get(nom)
            if origine is not None:
                provenances[nom] = {**provenance_de(origine), "collected": _aujourdhui()}
        _ecrire_provenances(provenances)

    return {
        "path": str(cible),
        "applied": bool(apply and a_ecrire),
        "scanned_files": len(fichiers),
        "keys_updated": ecrites if apply else sorted(a_ecrire),
        "keys_skipped_already_present": ignorees,
        "keys_found": sorted(trouvees),
        "keys_missing": [n for n in tracked if n not in trouvees],
    }


def mirror_to_provider(
    names: tuple[str, ...] | None = None,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Recopie le collecteur vers Secret Manager. **Ne touche à aucun fichier local.**

    C'est une image de secours, pas un déplacement : la valeur reste en clair
    dans le collecteur, qui est ce que lisent les scripts. Une version précédente
    remplaçait la valeur locale par une référence ``sm://`` — cela retirait le
    secret du disque, donc cassait tout ce qui le lisait, et inversait le rôle
    des deux dépôts.
    """
    cible = user_dotenv_path()
    valeurs = dotenv_values(cible) if cible.is_file() else {}
    # Par défaut, **tout** ce que contient le collecteur, pas seulement le
    # catalogue suivi. Une sauvegarde qui ne couvre qu'une partie du fichier
    # laisse le reste sans copie sans jamais le dire — et « suivi » sert à
    # décider ce que le tableau de bord affiche, pas ce qui mérite d'exister
    # ailleurs.
    tracked = names or tuple(
        k for k, v in valeurs.items() if v is not None and str(v).strip()
    )
    project = provider.secret_manager_project()
    provenances = _charger_provenances()
    resultats: list[dict[str, Any]] = []

    for name in tracked:
        brute = valeurs.get(name)
        valeur = str(brute).strip() if brute is not None else ""
        if not valeur:
            continue
        secret_id = _secret_id_for(name)
        entree = {"name": name, "secret_id": secret_id, "status": "would_mirror"}
        if not apply:
            resultats.append(entree)
            continue
        if not project:
            entree.update(status="error", reason="projet_non_configure")
            resultats.append(entree)
            continue
        amont, motif = provider.read_secret(f"sm://{project}/{secret_id}")
        if amont is not None and amont.strip() == valeur:
            entree.update(status="deja_a_jour")
            resultats.append(entree)
            continue
        marques = provenances.get(name) or {}
        cree = provider.create_secret(
            {"name": name},
            value=valeur,
            project=project,
            labels={
                "zab-org": marques.get("org", ""),
                "zab-project": marques.get("project", ""),
                "zab-collected": marques.get("collected", ""),
            },
            annotations={
                "zab-source": marques.get("path", ""),
                "zab-mirrored-at": _maintenant(),
            },
        )
        if not cree.get("ok"):
            entree.update(status="error", reason=cree.get("reason"))
        else:
            entree.update(status="mirrored", secret_status=cree.get("status"))
        resultats.append(entree)

    return {"project": project, "applied": apply, "source": str(cible), "results": resultats}


def restore_from_provider(
    names: tuple[str, ...] | None = None,
    *,
    target: Path | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Ramène dans le collecteur ce qui existe dans Secret Manager et lui manque.

    Ne recouvre jamais une valeur déjà présente : le collecteur fait foi, le
    miroir ne sert qu'à combler un trou.
    """
    cible = Path(target).expanduser() if target is not None else user_dotenv_path()
    valeurs = dotenv_values(cible) if cible.is_file() else {}
    presentes = {k for k, v in valeurs.items() if v is not None and str(v).strip()}
    tracked = names or tracked_env_names_for_security()
    project = provider.secret_manager_project()

    resultats: list[dict[str, Any]] = []
    a_ecrire: dict[str, str] = {}
    for name in tracked:
        if name in presentes:
            resultats.append({"name": name, "status": "skipped", "reason": "deja_dans_le_collecteur"})
            continue
        if not project:
            resultats.append({"name": name, "status": "skipped", "reason": "projet_non_configure"})
            continue
        secret_id = _secret_id_for(name)
        if not apply:
            resultats.append({"name": name, "status": "would_restore", "secret_id": secret_id})
            continue
        valeur, motif = provider.read_secret(f"sm://{project}/{secret_id}")
        if valeur is None:
            resultats.append({"name": name, "status": "absent_du_miroir", "secret_id": secret_id})
            continue
        a_ecrire[name] = valeur.strip()
        resultats.append({"name": name, "status": "restored", "secret_id": secret_id})

    if apply and a_ecrire:
        _upsert_dotenv(cible, a_ecrire, entete="# Ramenées de Secret Manager (zab secrets restore).")

    return {"target": str(cible), "project": project, "applied": apply, "results": resultats}


def _secret_id_for(name: str) -> str:
    """Identifiant du secret : la correspondance déclarée, sinon celle dérivée du nom.

    Sans cette table, un secret créé hors de zab — donc sans le préfixe — était
    invisible : l'identifiant dérivé ne pointait sur rien.
    """
    try:
        from zab.user_config import load_user_config

        bloc = load_user_config().get("secret_manager")
        if isinstance(bloc, dict):
            table = bloc.get("map")
            if isinstance(table, dict):
                declare = table.get(name)
                if isinstance(declare, str) and declare.strip():
                    return declare.strip()
    except Exception:  # noqa: BLE001, S110 — config illisible : on dérive du nom
        pass
    return provider.secret_id_for_name(name)


def provenance_path() -> Path:
    """Fiche d'origine des valeurs du collecteur. Ne contient aucune valeur."""
    return config_dir() / "secrets-provenance.json"


def _aujourdhui() -> str:
    return _maintenant()[:10]


def _maintenant() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _charger_provenances() -> dict[str, dict[str, str]]:
    import json

    chemin = provenance_path()
    if not chemin.is_file():
        return {}
    try:
        charge = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return charge if isinstance(charge, dict) else {}


def _ecrire_provenances(donnees: dict[str, dict[str, str]]) -> None:
    import json

    chemin = provenance_path()
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(donnees, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")


def mirror_projects_to_provider(
    *,
    apply: bool = False,
    include_hub_keys: bool = False,
) -> dict[str, Any]:
    """Sauvegarde chaque ``.env`` projet, sous un identifiant nommé par projet.

    Le collecteur est plat : il ne peut pas tenir deux ``SECRET_KEY`` de valeurs
    différentes. Douze noms sont dans ce cas sur un poste réel, et les fusionner
    en garderait un seul — donc en perdrait onze. Le miroir n'a pas cette
    limite : ``zab-<org>-<projet>-<cle>`` distingue ce que le collecteur
    confond, et les étiquettes disent d'où chaque valeur vient.

    Par défaut, les clés déjà présentes dans le collecteur sont sautées : elles
    sont sauvegardées par ``mirror``, sous leur nom court.
    """
    project = provider.secret_manager_project()
    hub = user_dotenv_path()
    cles_hub = {
        k for k, v in (dotenv_values(hub) if hub.is_file() else {}).items()
        if v is not None and str(v).strip()
    }
    resultats: list[dict[str, Any]] = []
    horodatage = _maintenant()

    for fichier in _env_files():
        if str(fichier) == str(hub):
            continue
        marques = provenance_de(fichier)
        try:
            valeurs = dotenv_values(fichier)
        except OSError:
            continue
        for nom, brute in (valeurs or {}).items():
            valeur = str(brute).strip() if brute is not None else ""
            if not valeur:
                continue
            if nom in cles_hub and not include_hub_keys:
                continue
            secret_id = provider.sanitize_label(
                "-".join(x for x in (marques["org"], marques["project"], nom) if x),
                limite=255,
            )
            entree = {
                "name": nom, "secret_id": secret_id,
                "org": marques["org"], "project": marques["project"],
                "path": marques["path"], "status": "would_mirror",
            }
            if not apply:
                resultats.append(entree)
                continue
            if not project:
                entree.update(status="error", reason="projet_non_configure")
                resultats.append(entree)
                continue
            amont, _ = provider.read_secret(f"sm://{project}/{secret_id}")
            if amont is not None and amont.strip() == valeur:
                entree.update(status="deja_a_jour")
                resultats.append(entree)
                continue
            cree = provider.create_secret(
                {"name": nom}, value=valeur, project=project,
                labels={
                    "zab-org": marques["org"], "zab-project": marques["project"],
                    "zab-collected": horodatage[:10], "zab-kind": "project-env",
                },
                annotations={
                    "zab-source": marques["path"], "zab-var": nom,
                    "zab-mirrored-at": horodatage,
                },
            )
            entree.update(
                status="mirrored" if cree.get("ok") else "error",
                reason=None if cree.get("ok") else cree.get("reason"),
            )
            resultats.append(entree)

    return {"project": project, "applied": apply, "results": resultats}
