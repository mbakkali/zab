"""Sync des variables suivies vers un gestionnaire de secrets — Google Secret Manager.

Les fonctions de ce module ne retournent jamais une valeur de secret en clair.
Elles construisent un état masqué, lisible par un humain, et des plans d'action.

Le fournisseur précédent était Dashlane, piloté par `dcli` et par un writer
Playwright qui ouvrait Chrome pour créer les secrets manquants. Il a été retiré :
il exigeait une session graphique connectée, ne fonctionnait donc pas sur une
machine sans écran, et son coffre restait étranger au reste de l'infrastructure.
Secret Manager s'interroge par `gcloud`, avec l'identité déjà attachée à la
machine — aucune session à tenir, aucun mot de passe maître, et une révocation
qui se fait au même endroit que les autres accès.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROVIDER_ID = "gcp-secret-manager"
PROVIDER_LABEL = "Google Secret Manager"

#: Schéma de référence écrit dans les `.env` locaux à la place de la valeur.
REFERENCE_SCHEME = "sm://"
_REFERENCE_RE = re.compile(r"^sm://(?:(?P<project>[a-z0-9][a-z0-9-]{4,28}[a-z0-9])/)?(?P<secret>[A-Za-z0-9_-]{1,255})$")

#: Préfixe des identifiants créés par zab. Un secret préexistant peut toujours
#: être référencé à la main : la référence est explicite, le préfixe ne sert
#: qu'à nommer ce que zab crée lui-même.
DEFAULT_SECRET_PREFIX = "zab-"

_PROJECT_ENV = "ZAB_SECRET_MANAGER_PROJECT"
_PREFIX_ENV = "ZAB_SECRET_MANAGER_PREFIX"
_GCLOUD_TIMEOUT = 20.0


# ── utilitaires de présentation ───────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short_text(value: str, *, limit: int = 280) -> str:
    clean = " ".join(value.strip().split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3] + "..."


def _short_error(value: str, secret_value: str = "", *, limit: int = 160) -> str:
    text = value
    if secret_value:
        text = text.replace(secret_value, "[redacted]")
    return _short_text(text, limit=limit)


def _path_display(path: Path) -> str:
    try:
        return f"~/{path.resolve().relative_to(Path.home())}"
    except (ValueError, OSError):
        return str(path)


# ── résolution du projet et des identifiants ─────────────────────────────────

def _gcloud() -> str | None:
    return shutil.which("gcloud")


def secret_manager_project() -> str:
    """Projet GCP hébergeant les secrets.

    Ordre : ``$ZAB_SECRET_MANAGER_PROJECT`` → ``secret_manager.project`` dans
    ``~/.config/zab/config.yaml`` → projet actif de ``gcloud``. Vide si rien
    n'est configuré : le module reste inerte plutôt que d'écrire au mauvais
    endroit.
    """
    env = os.environ.get(_PROJECT_ENV, "").strip()
    if env:
        return env
    try:
        from zab.user_config import load_user_config

        cfg = load_user_config()
        block = cfg.get("secret_manager")
        if isinstance(block, dict):
            value = block.get("project")
            if isinstance(value, str) and value.strip():
                return value.strip()
    except Exception:  # noqa: BLE001, S110 — config illisible : on passe à la source suivante
        pass
    gcloud = _gcloud()
    if not gcloud:
        return ""
    try:
        proc = subprocess.run(
            [gcloud, "config", "get-value", "project"],
            capture_output=True, text=True, timeout=_GCLOUD_TIMEOUT, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    value = (proc.stdout or "").strip()
    return "" if value in ("", "(unset)") else value


def _secret_prefix() -> str:
    env = os.environ.get(_PREFIX_ENV)
    if env is not None:
        return env.strip()
    try:
        from zab.user_config import load_user_config

        block = load_user_config().get("secret_manager")
        if isinstance(block, dict):
            value = block.get("prefix")
            if isinstance(value, str):
                return value.strip()
    except Exception:  # noqa: BLE001, S110 — config illisible : on garde le préfixe par défaut
        pass
    return DEFAULT_SECRET_PREFIX


def secret_id_for_name(name: str) -> str:
    """Identifiant Secret Manager proposé pour une variable d'environnement.

    Secret Manager n'accepte que ``[A-Za-z0-9_-]`` sur 255 caractères. On
    minuscule et on remplace le reste par un tiret, ce qui rend l'identifiant
    lisible dans la console : ``QONTO_API_KEY`` → ``zab-qonto-api-key``.
    """
    clean = re.sub(r"[^A-Za-z0-9]+", "-", name.strip()).strip("-").lower()
    if not clean:
        clean = "variable"
    prefix = _secret_prefix()
    if prefix and clean.startswith(prefix):
        return clean[:255]
    return f"{prefix}{clean}"[:255]


def secret_reference_for_name(name: str, *, project: str | None = None) -> str:
    proj = project if project is not None else secret_manager_project()
    secret = secret_id_for_name(name)
    return f"{REFERENCE_SCHEME}{proj}/{secret}" if proj else f"{REFERENCE_SCHEME}{secret}"


def parse_secret_reference(reference: str) -> tuple[str, str] | None:
    """``sm://projet/identifiant`` → ``(projet, identifiant)``. ``None`` si invalide.

    Le projet est facultatif dans la référence : sans lui, celui de la
    configuration s'applique. Une référence sans projet reste donc portable
    entre deux environnements qui ne pointent pas le même.
    """
    m = _REFERENCE_RE.match(reference.strip())
    if not m:
        return None
    return (m.group("project") or secret_manager_project(), m.group("secret"))


def is_secret_reference(value: str) -> bool:
    return bool(_REFERENCE_RE.match(value.strip()))


def secret_console_url(project: str, secret_id: str) -> str:
    if not project or not secret_id:
        return "https://console.cloud.google.com/security/secret-manager"
    return (
        f"https://console.cloud.google.com/security/secret-manager/secret/{secret_id}"
        f"/versions?project={project}"
    )


# ── interrogation du fournisseur ─────────────────────────────────────────────

def _run_gcloud(args: list[str], *, timeout: float = _GCLOUD_TIMEOUT) -> tuple[bool, str, str]:
    gcloud = _gcloud()
    if not gcloud:
        return False, "", "gcloud_absent"
    try:
        proc = subprocess.run(
            [gcloud, *args], capture_output=True, text=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "", "timeout"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, "", _short_error(str(exc))
    if proc.returncode != 0:
        return False, "", _short_error(proc.stderr or proc.stdout or "echec_gcloud")
    return True, proc.stdout or "", ""


def secret_inventory(*, project: str | None = None, timeout: float = _GCLOUD_TIMEOUT) -> dict[str, Any]:
    """Liste les secrets du projet, sans jamais lire une seule valeur."""
    proj = project if project is not None else secret_manager_project()
    if not proj:
        return {
            "available": False, "status": "project_not_configured", "count": 0,
            "project": "", "items": [],
            "status_detail": (
                "Aucun projet GCP configuré : renseigner secret_manager.project dans "
                "~/.config/zab/config.yaml ou $ZAB_SECRET_MANAGER_PROJECT."
            ),
        }
    ok, out, err = _run_gcloud(
        ["secrets", "list", "--project", proj, "--format", "json(name)"], timeout=timeout
    )
    if not ok:
        status = "gcloud_missing" if err == "gcloud_absent" else "unavailable"
        return {
            "available": False, "status": status, "count": 0, "project": proj,
            "items": [], "status_detail": err or None,
        }
    try:
        raw = json.loads(out or "[]")
    except json.JSONDecodeError:
        return {
            "available": False, "status": "unreadable", "count": 0, "project": proj,
            "items": [], "status_detail": "sortie gcloud illisible",
        }
    items: list[dict[str, Any]] = []
    for entry in raw if isinstance(raw, list) else []:
        full = str((entry or {}).get("name") or "")
        secret_id = full.rsplit("/", 1)[-1] if full else ""
        if not secret_id:
            continue
        items.append({
            "secret_id": secret_id,
            "reference": f"{REFERENCE_SCHEME}{proj}/{secret_id}",
            "console_url": secret_console_url(proj, secret_id),
        })
    items.sort(key=lambda i: i["secret_id"])
    return {
        "available": True, "status": "ready", "count": len(items),
        "project": proj, "items": items, "status_detail": None,
    }


def secret_write_available() -> bool:
    """Vrai si `gcloud` est là et un projet configuré. La création est alors possible."""
    return bool(_gcloud()) and bool(secret_manager_project())


def secret_providers() -> list[dict[str, Any]]:
    """Rail des fournisseurs affiché par le dashboard."""
    gcloud = _gcloud()
    project = secret_manager_project()
    inventory = secret_inventory(project=project) if (gcloud and project) else None

    if not gcloud:
        status, label = "missing_cli", "gcloud absent"
    elif not project:
        status, label = "not_configured", "Projet GCP non configuré"
    elif inventory and inventory.get("available"):
        status, label = "ready", f"Connecté — projet {project}"
    else:
        status, label = "login_required", "Accès refusé ou API désactivée"

    return [
        {
            "id": PROVIDER_ID,
            "label": PROVIDER_LABEL,
            "available": bool(gcloud),
            "implemented": True,
            "enabled": True,
            "cli": "gcloud",
            "cli_path": gcloud,
            "project": project,
            "status": status,
            "status_label": label,
            "status_detail": (inventory or {}).get("status_detail"),
            "login_command": "gcloud auth login",
            "check_command": f"gcloud secrets list --project {project}" if project else "gcloud config get-value project",
            "capabilities": [
                "detect_references",
                "sync_plan",
                "write_local_references",
                "create_missing_secrets" if secret_write_available() else "create_missing_secrets_requires_gcloud",
            ],
            "limitations": [
                (
                    "Zab n'écrit jamais la valeur d'un secret dans un fichier : le .env local "
                    "reçoit une référence sm://, que l'application résout à l'exécution."
                ),
            ],
        },
        {"id": "dotenvx", "label": "dotenvx", "available": False, "implemented": False, "enabled": False},
        {"id": "op", "label": "1Password", "available": False, "implemented": False, "enabled": False},
        {"id": "sops", "label": "SOPS", "available": False, "implemented": False, "enabled": False},
    ]


# ── création d'un secret ─────────────────────────────────────────────────────

def create_secret(
    variable: dict[str, Any],
    *,
    value: str,
    project: str | None = None,
) -> dict[str, Any]:
    """Crée le secret et sa première version. Ne retourne aucune valeur en clair."""
    name = str(variable.get("name") or "").strip()
    if not name:
        return {"ok": False, "status": "failed", "reason": "nom_variable_absent"}
    if not value:
        return {"ok": False, "status": "failed", "reason": "valeur_vide"}

    proj = project if project is not None else secret_manager_project()
    if not proj:
        return {"ok": False, "status": "failed", "reason": "projet_non_configure"}
    gcloud = _gcloud()
    if not gcloud:
        return {"ok": False, "status": "failed", "reason": "gcloud_absent"}

    secret_id = secret_id_for_name(name)
    reference = f"{REFERENCE_SCHEME}{proj}/{secret_id}"

    exists, _, _ = _run_gcloud(["secrets", "describe", secret_id, "--project", proj])
    args = (
        ["secrets", "versions", "add", secret_id, "--project", proj, "--data-file=-"]
        if exists
        else ["secrets", "create", secret_id, "--project", proj,
              "--replication-policy=automatic", "--data-file=-"]
    )
    # La valeur passe par stdin : jamais par argv, où elle serait lisible dans
    # la table des processus par n'importe quel utilisateur de la machine.
    try:
        proc = subprocess.run(
            [gcloud, *args], input=value, capture_output=True, text=True, timeout=_GCLOUD_TIMEOUT, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "status": "failed", "reason": _short_error(str(exc), value)}
    if proc.returncode != 0:
        return {
            "ok": False, "status": "failed",
            "reason": _short_error(proc.stderr or proc.stdout or "echec_creation", value),
            "secret_id": secret_id, "secret_reference": reference,
        }
    return {
        "ok": True,
        "status": "version_added" if exists else "created",
        "secret_id": secret_id,
        "secret_reference": reference,
        "console_url": secret_console_url(proj, secret_id),
    }


def read_secret(reference: str, *, timeout: float = _GCLOUD_TIMEOUT) -> tuple[str | None, str]:
    """Lit la valeur derrière une référence. Réservé aux chemins qui en ont besoin.

    Retourne ``(valeur, "")`` ou ``(None, motif)``. Aucun appelant ne doit
    reverser le résultat dans un payload d'API.
    """
    parsed = parse_secret_reference(reference)
    if not parsed:
        return None, "reference_invalide"
    project, secret_id = parsed
    if not project:
        return None, "projet_non_configure"
    ok, out, err = _run_gcloud(
        ["secrets", "versions", "access", "latest", "--secret", secret_id, "--project", project],
        timeout=timeout,
    )
    if not ok:
        return None, err or "acces_refuse"
    return out, ""


# ── construction de l'état ───────────────────────────────────────────────────

def _reference_hint(value: str) -> str:
    parsed = parse_secret_reference(value)
    if not parsed:
        return ""
    project, secret_id = parsed
    return f"{project}/{secret_id}" if project else secret_id


def _note_template(variable: dict[str, Any], *, reference: str) -> str:
    name = str(variable.get("name") or "")
    sources = variable.get("sources") or []
    lines = [f"Variable suivie par zab : {name}", f"Référence locale : {reference}"]
    if sources:
        lines.append("Fichiers qui la déclarent :")
        for src in sources[:8]:
            path = src.get("path") if isinstance(src, dict) else src
            if path:
                lines.append(f"  - {_path_display(Path(str(path)))}")
    return "\n".join(lines)


def build_secret_sync_payload(
    variables: list[dict[str, Any]],
    raw_values_by_name: dict[str, str],
    *,
    generated_at_utc: str | None = None,
    inventory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """État de synchronisation des variables suivies.

    ``raw_values_by_name`` sert uniquement à reconnaître une référence déjà
    posée. Aucune valeur brute n'entre dans le retour.
    """
    generated = generated_at_utc or _now_iso()
    inv = inventory if isinstance(inventory, dict) else secret_inventory()
    project = str(inv.get("project") or "")
    known = {str(item.get("secret_id")): item for item in inv.get("items") or []}

    rows: list[dict[str, Any]] = []
    counts = {"synced": 0, "pending": 0, "missing": 0, "total": 0}

    for variable in variables:
        name = str(variable.get("name") or "")
        present = bool(variable.get("present"))
        raw = str(raw_values_by_name.get(name) or "").strip()
        referenced = is_secret_reference(raw)

        if referenced:
            status = "synced"
        elif present:
            status = "pending"
        else:
            status = "missing"
        counts[status] += 1
        counts["total"] += 1

        parsed = parse_secret_reference(raw) if referenced else None
        secret_id = parsed[1] if parsed else secret_id_for_name(name)
        reference = raw if referenced else secret_reference_for_name(name, project=project)
        in_provider = secret_id in known

        rows.append({
            "name": name,
            "status": status,
            "provider": PROVIDER_ID if referenced else None,
            "recommended_provider": PROVIDER_ID if status == "pending" else None,
            "secret_id": secret_id,
            "secret_reference": reference,
            "secret_reference_template": f"{name}={reference}" if name else reference,
            "console_url": secret_console_url(parsed[0] if parsed else project, secret_id),
            "match_status": "matched" if in_provider else "not_found",
            "reference_hint": _reference_hint(raw) if referenced else "",
            "note_template": _note_template(variable, reference=reference) if status == "pending" else "",
            "source_count": len(variable.get("sources") or []),
        })

    return {
        "provider": PROVIDER_ID,
        "status": "ok" if counts["pending"] == 0 else "needs_sync",
        "generated_at_utc": generated,
        "write_supported": secret_write_available(),
        "project": project,
        "inventory": {
            "available": bool(inv.get("available")),
            "status": inv.get("status") or "unknown",
            "count": int(inv.get("count") or 0),
            "project": project,
            "status_detail": inv.get("status_detail"),
            "items": list(inv.get("items") or []),
        },
        "counts": counts,
        "variables": rows,
        "manual_steps": [
            "Configurer secret_manager.project dans ~/.config/zab/config.yaml.",
            "S'authentifier : gcloud auth login (le poste, ou l'identité attachée sur une VM).",
            "La modale crée ensuite le secret manquant puis remplace la valeur locale par sa référence sm://.",
        ],
    }


def attach_secret_sync(
    variables: list[dict[str, Any]],
    raw_values_by_name: dict[str, str],
) -> dict[str, Any]:
    sync = build_secret_sync_payload(variables, raw_values_by_name)
    by_name = {str(row.get("name") or ""): row for row in sync["variables"]}
    for variable in variables:
        variable["sync"] = by_name.get(str(variable.get("name") or ""))
    return sync


def secret_sync_check(sync_payload: dict[str, Any], *, apply: bool = False) -> dict[str, Any]:
    pending = int(sync_payload.get("counts", {}).get("pending") or 0)
    can_write = secret_write_available()
    if apply and pending and not can_write:
        status = "action_required"
        message = (
            "Création impossible : installer gcloud et renseigner secret_manager.project "
            "dans ~/.config/zab/config.yaml."
        )
    elif apply and pending:
        status = "needs_sync"
        message = f"{pending} secret(s) seront créés puis référencés un par un."
    elif pending:
        status = "needs_sync"
        message = f"{pending} secret(s) à synchroniser vers {PROVIDER_LABEL}."
    else:
        status = "ok"
        message = "Aucune variable locale en attente de synchronisation."
    return {
        **sync_payload,
        "status": status,
        "apply_requested": bool(apply),
        "message": message,
        "providers": secret_providers(),
    }


# ── écriture de la référence dans les .env locaux ────────────────────────────

def _dotenv_line_parts(raw_line: str) -> tuple[str, str]:
    stripped = raw_line.rstrip("\n")
    newline = raw_line[len(stripped):]
    return stripped, newline


#: Valeur d'un ``.env`` suivie d'un commentaire de fin de ligne. Le commentaire
#: ne commence qu'après une espace, et jamais à l'intérieur de guillemets —
#: c'est la règle de python-dotenv, on la suit pour lire la ligne comme elle
#: sera lue à l'exécution.
_DOTENV_VALUE_RE = re.compile(
    r"""^(?P<valeur>\s*(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|[^\s#]*))(?P<commentaire>\s+#.*)?$"""
)


def _trailing_comment(rhs: str) -> str:
    """Commentaire de fin de ligne, s'il y en a un. Chaîne vide sinon."""
    m = _DOTENV_VALUE_RE.match(rhs)
    return (m.group("commentaire") or "") if m else ""


def _replace_dotenv_key(text: str, key: str, reference: str) -> tuple[str, bool]:
    lines = text.splitlines(keepends=True)
    changed = False
    for index, raw_line in enumerate(lines):
        stripped, newline = _dotenv_line_parts(raw_line)
        bare = stripped.strip()
        if bare.startswith("#") or "=" not in bare:
            continue
        candidate, rhs = bare.split("=", 1)
        candidate = candidate.strip()
        if candidate.startswith("export "):
            candidate = candidate[len("export "):].strip()
        if candidate != key:
            continue
        prefix = "export " if bare.startswith("export ") else ""
        # Le commentaire de fin de ligne survit au remplacement. Il porte
        # souvent la seule trace de l'origine de la clé ou de la procédure pour
        # la faire tourner ; l'écraser en même temps que la valeur revient à
        # perdre l'information au moment précis où elle redevient utile.
        lines[index] = f"{prefix}{key}={reference}{_trailing_comment(rhs)}{newline or ''}"
        changed = True
    return "".join(lines), changed


def apply_secret_reference(
    variables: list[dict[str, Any]],
    *,
    name: str,
    reference: str | None = None,
    allowed_paths: set[str] | None = None,
) -> dict[str, Any]:
    """Remplace la valeur en clair d'un .env par sa référence ``sm://``.

    Ne retourne ni ne journalise jamais l'ancienne valeur. Trois garde-fous sont
    conservés du fournisseur précédent, et méritent de l'être : le périmètre de
    chemins autorisés, le refus d'écrire ailleurs que dans un fichier nommé
    ``.env``, et l'écriture atomique par fichier temporaire puis ``replace`` —
    une interruption au mauvais moment laisserait sinon un ``.env`` tronqué,
    c'est-à-dire une application qui ne démarre plus.
    """
    clean_name = name.strip()
    row = next((v for v in variables if str(v.get("name") or "") == clean_name), None)
    if row is None:
        return {"name": clean_name, "status": "error", "reason": "variable_introuvable"}
    sync = row.get("sync") if isinstance(row.get("sync"), dict) else {}
    if sync.get("status") == "missing" or not row.get("present"):
        return {"name": clean_name, "status": "skipped", "reason": "variable_absente"}
    if sync.get("status") == "synced":
        return {"name": clean_name, "status": "skipped", "reason": "deja_synced"}

    ref = (reference or secret_reference_for_name(clean_name)).strip()
    if not is_secret_reference(ref):
        return {"name": clean_name, "status": "error", "reason": "reference_invalide"}

    file_sources: list[dict[str, Any]] = [
        source
        for source in row.get("sources") or []
        if isinstance(source, dict) and source.get("kind") == "file"
    ]
    if not file_sources:
        return {"name": clean_name, "status": "skipped", "reason": "source_process_only"}

    allowed = allowed_paths or set()
    by_path: dict[Path, set[str]] = {}
    skipped_sources: list[dict[str, Any]] = []
    for source in file_sources:
        raw_path = str(source.get("path") or "").strip()
        key = str(source.get("key") or clean_name).strip()
        if not raw_path or not key:
            skipped_sources.append({"reason": "source_incomplete"})
            continue
        try:
            path = Path(raw_path).expanduser().resolve()
        except OSError:
            skipped_sources.append({"path": raw_path, "key": key, "reason": "chemin_invalide"})
            continue
        if allowed and str(path) not in allowed:
            skipped_sources.append({"path": str(path), "key": key, "reason": "chemin_hors_perimetre"})
            continue
        if path.name != ".env":
            skipped_sources.append({"path": str(path), "key": key, "reason": "fichier_non_env"})
            continue
        by_path.setdefault(path, set()).add(key)

    changed_files: list[dict[str, Any]] = []
    for path, keys in sorted(by_path.items(), key=lambda item: str(item[0])):
        if not path.is_file():
            skipped_sources.append({"path": str(path), "reason": "fichier_absent"})
            continue
        try:
            original = path.read_text(encoding="utf-8")
        except OSError as exc:
            skipped_sources.append({"path": str(path), "reason": _short_text(str(exc), limit=120)})
            continue
        updated = original
        changed_keys: list[str] = []
        for key in sorted(keys):
            updated, changed = _replace_dotenv_key(updated, key, ref)
            if changed:
                changed_keys.append(key)
            else:
                skipped_sources.append({"path": str(path), "key": key, "reason": "cle_introuvable"})
        if not changed_keys or updated == original:
            continue
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        tmp_path = path.with_name(f".env.zab-secret-tmp-{ts}")
        try:
            st = path.stat()
            tmp_path.write_text(updated, encoding="utf-8")
            try:
                tmp_path.chmod(st.st_mode)
            except OSError:
                pass
            tmp_path.replace(path)
        except OSError as exc:
            try:
                tmp_path.unlink()
            except OSError:
                pass
            return {
                "name": clean_name,
                "status": "error",
                "reason": _short_text(str(exc), limit=160),
                "reference_hint": _reference_hint(ref),
            }
        changed_files.append(
            {
                "path": str(path),
                "path_display": _path_display(path),
                "keys": changed_keys,
                "storage": "secret_manager_reference",
            }
        )

    if not changed_files:
        return {
            "name": clean_name,
            "status": "skipped",
            "reason": "aucune_source_modifiee",
            "reference_hint": _reference_hint(ref),
            "skipped_sources": skipped_sources,
        }
    return {
        "name": clean_name,
        "status": "synced",
        "provider": PROVIDER_ID,
        "reference_hint": _reference_hint(ref),
        "changed_files": changed_files,
        "skipped_sources": skipped_sources,
    }


# ── presse-papiers ───────────────────────────────────────────────────────────

def copy_to_clipboard(value: str) -> tuple[bool, str | None]:
    """Copie une valeur dans le presse-papiers sans jamais la retourner."""
    if not value:
        return False, "valeur_vide"
    # macOS d'abord, puis Wayland et X11 : le dashboard tourne aussi bien sur le
    # poste que sur une machine distante avec un serveur graphique.
    candidates: list[list[str]] = []
    for binary, args in (("pbcopy", []), ("wl-copy", []), ("xclip", ["-selection", "clipboard"]), ("xsel", ["--clipboard", "--input"])):
        found = shutil.which(binary)
        if found:
            candidates.append([found, *args])
    if not candidates:
        return False, "clipboard_indisponible"
    last: str | None = None
    for cmd in candidates:
        try:
            proc = subprocess.run(cmd, input=value, text=True, capture_output=True, timeout=5, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            last = _short_error(str(exc), value)
            continue
        if proc.returncode == 0:
            return True, None
        last = _short_error(proc.stderr or "echec_copie", value)
    return False, last or "echec_copie"
