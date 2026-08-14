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


def _env_files() -> list[Path]:
    """``.env`` des racines de projets, sur trois niveaux, plus celui du dépôt skills.

    Trois niveaux parce qu'un dépôt peut vivre sous ``racine/org/projet`` — c'est
    le cas de plusieurs ici. Au-delà, on balaierait des dépendances vendorisées.
    """
    out: list[Path] = []
    seen: set[str] = set()

    def _add(path: Path) -> None:
        try:
            resolved = path.resolve()
        except OSError:
            return
        key = str(resolved)
        if key in seen or not resolved.is_file():
            return
        seen.add(key)
        out.append(resolved)

    def _children(path: Path) -> list[Path]:
        try:
            return sorted(
                (p for p in path.iterdir() if p.is_dir() and not p.name.startswith(".")),
                key=lambda x: x.name.casefold(),
            )
        except OSError:
            return []

    for root in projects_roots_resolved():
        try:
            root_r = root.resolve()
        except OSError:
            continue
        _add(root_r / ".env")
        for level1 in _children(root_r):
            _add(level1 / ".env")
            for level2 in _children(level1):
                _add(level2 / ".env")

    skills = skills_root_from_config_file_only()
    if skills is not None:
        _add(skills / ".env")
    return out


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

    cible = user_dotenv_path()
    existantes = dotenv_values(cible) if cible.is_file() else {}
    presentes = {k for k, v in existantes.items() if v is not None and str(v).strip()}

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
        cree = provider.create_secret({"name": name}, value=valeur, project=project)
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
