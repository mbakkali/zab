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


def collect_to_user_dotenv(*, force: bool = False, apply: bool = True) -> dict[str, Any]:
    """Fusionne les valeurs trouvées dans les projets vers ``~/.config/zab/.env``."""
    tracked = tracked_env_names_for_security()
    found: dict[str, str] = {}
    for path in _env_files():
        try:
            values = dotenv_values(path)
        except OSError:
            continue
        for name in tracked:
            if name in found:
                continue
            raw = values.get(name)
            if raw is not None and str(raw).strip():
                found[name] = str(raw).strip()

    target = user_dotenv_path()
    existing = dotenv_values(target) if target.is_file() else {}
    merged: dict[str, str] = {
        str(k): str(v).strip() for k, v in existing.items() if v is not None and str(v).strip()
    }

    updated: list[str] = []
    skipped: list[str] = []
    for name in tracked:
        value = found.get(name)
        if not value:
            continue
        if merged.get(name) and not force:
            skipped.append(name)
            continue
        if merged.get(name) != value:
            merged[name] = value
            updated.append(name)

    if apply and updated:
        target.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"{k}={_quote_dotenv_value(v)}" for k, v in sorted(merged.items())]
        target.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        try:
            target.chmod(0o600)
        except OSError:
            pass

    return {
        "path": str(target),
        "applied": bool(apply and updated),
        "scanned_files": len(_env_files()),
        "keys_updated": updated,
        "keys_skipped_already_present": skipped,
        "keys_found": sorted(found),
        "keys_missing": [n for n in tracked if n not in found],
    }


def push_to_provider(
    names: tuple[str, ...] | None = None,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Pousse chaque valeur en clair vers Secret Manager et pose la référence."""
    scan = scan_tracked_values(names, include_user_dotenv=False)
    project = provider.secret_manager_project()
    results: list[dict[str, Any]] = []

    for row in scan["variables"]:
        if row["state"] != "plain":
            continue
        name = row["name"]
        secret_id = provider.secret_id_for_name(name)
        reference = provider.secret_reference_for_name(name, project=project)
        entry = {
            "name": name, "secret_id": secret_id, "reference": reference,
            "files": row["files"], "status": "would_push",
        }
        if not apply:
            results.append(entry)
            continue
        if not project:
            entry.update(status="error", reason="projet_non_configure")
            results.append(entry)
            continue

        value = _first_plain_value(name, row["files"])
        if not value:
            entry.update(status="error", reason="valeur_introuvable")
            results.append(entry)
            continue
        created = provider.create_secret({"name": name}, value=value, project=project)
        if not created.get("ok"):
            entry.update(status="error", reason=created.get("reason"))
            results.append(entry)
            continue
        entry["reference"] = created.get("secret_reference") or reference
        rewritten = [
            path for path in row["files"]
            if _rewrite_dotenv_key(Path(path), name, entry["reference"])
        ]
        entry.update(status="pushed", secret_status=created.get("status"), rewritten=rewritten)
        results.append(entry)

    return {"project": project, "applied": apply, "results": results}


def pull_from_provider(
    target: Path,
    names: tuple[str, ...] | None = None,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Résout les références connues et écrit les valeurs dans un ``.env`` cible.

    Écrit des secrets en clair, délibérément : c'est ce qui permet à un dépôt
    fraîchement cloné de démarrer. À n'utiliser que sur une machine de confiance.
    """
    scan = scan_tracked_values(names)
    tracked = names or tracked_env_names_for_security()
    project = provider.secret_manager_project()
    target = Path(target).expanduser()

    existing = dotenv_values(target) if target.is_file() else {}
    merged: dict[str, str] = {
        str(k): str(v).strip() for k, v in existing.items() if v is not None and str(v).strip()
    }

    by_name = {row["name"]: row for row in scan["variables"]}
    results: list[dict[str, Any]] = []
    for name in tracked:
        row = by_name.get(name) or {}
        reference = row.get("reference") or (
            provider.secret_reference_for_name(name, project=project) if project else ""
        )
        current = merged.get(name, "")
        if current and not provider.is_secret_reference(current):
            results.append({"name": name, "status": "skipped", "reason": "deja_en_clair"})
            continue
        if not reference:
            results.append({"name": name, "status": "skipped", "reason": "aucune_reference"})
            continue
        if not apply:
            results.append({"name": name, "status": "would_pull", "reference": reference})
            continue
        value, reason = provider.read_secret(reference)
        if value is None:
            results.append({"name": name, "status": "error", "reason": reason, "reference": reference})
            continue
        merged[name] = value.strip()
        results.append({"name": name, "status": "pulled", "reference": reference})

    if apply and any(r["status"] == "pulled" for r in results):
        target.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"{k}={_quote_dotenv_value(v)}" for k, v in sorted(merged.items())]
        target.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        try:
            target.chmod(0o600)
        except OSError:
            pass

    return {"target": str(target), "project": project, "applied": apply, "results": results}


def _first_plain_value(name: str, files: list[str]) -> str:
    for path in files:
        try:
            values = dotenv_values(Path(path))
        except OSError:
            continue
        raw = values.get(name)
        if raw is None:
            continue
        value = str(raw).strip()
        if value and not provider.is_secret_reference(value):
            return value
    return str(os.environ.get(name, "")).strip()


def _rewrite_dotenv_key(path: Path, key: str, reference: str) -> bool:
    """Remplace la valeur d'une clé par sa référence, sans toucher au reste du fichier."""
    try:
        original = path.read_text(encoding="utf-8")
    except OSError:
        return False
    updated, changed = provider._replace_dotenv_key(original, key, reference)
    if not changed or updated == original:
        return False
    # Même écriture atomique que le tableau de bord : un .env tronqué est une
    # application qui ne démarre plus.
    tmp = path.with_name(f"{path.name}.zab-secret-tmp")
    try:
        mode = path.stat().st_mode
        tmp.write_text(updated, encoding="utf-8")
        try:
            tmp.chmod(mode)
        except OSError:
            pass
        tmp.replace(path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        return False
    return True
