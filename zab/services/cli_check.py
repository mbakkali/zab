"""Declarative CLI authentication checks.

The config is JSON on purpose: agents and local scripts can edit it without
needing to understand the rest of Zab's YAML configuration.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from zab.paths import config_dir
from zab.services.secrets_scan import scan_secret_presence
from zab.system_open import open_command_in_terminal

Status = str


def cli_checks_config_path() -> Path:
    """Default user config path for declarative CLI auth checks."""
    return config_dir() / "cli-checks.json"


def default_cli_checks_config() -> dict[str, Any]:
    """Return the example config used to bootstrap ``cli-checks.json``."""
    return {
        "version": 1,
        "description": "Checks declaratifs pour valider les authentifications CLI locales.",
        "checks": [
            {
                "id": "gog-gmail-flowmetrik",
                "label": "gog / Gmail Flowmetrik",
                "category": "messaging",
                "url": "https://mail.google.com/mail/u/mehdi@flowmetrik.com",
                "command": [
                    "gog",
                    "gmail",
                    "labels",
                    "list",
                    "--account",
                    "mehdi@flowmetrik.com",
                    "--json",
                    "--no-input",
                ],
                "timeout_seconds": 8,
                "success": {
                    "exit_codes": [0],
                    "combined_contains_any": ["\"labels\"", "INBOX"],
                    "combined_not_contains_any": ["no auth", "unauthorized", "not authenticated", "forbidden", "invalid_grant"],
                },
                "failure_note": "Echec d'auth: no auth for gmail mehdi@flowmetrik.com.",
            },
            {
                "id": "composio-connections",
                "label": "Composio",
                "category": "connectors",
                "url": "https://app.composio.dev/connections",
                "command": ["composio", "connections", "list"],
                "timeout_seconds": 8,
                "success": {
                    "exit_codes": [0],
                    "combined_contains_any": ["ACTIVE", "active"],
                    "combined_not_contains_any": ["0 active", "no connections", "aucune connexion"],
                },
                "failure_note": "Aucune connexion lisible, 0 active; Gmail/Google Calendar/Fireflies/HubSpot via Composio inutilisables.",
            },
            {
                "id": "fireflies-via-composio",
                "label": "Fireflies via Composio",
                "category": "meetings",
                "command": ["composio", "connections", "list"],
                "timeout_seconds": 8,
                "success": {
                    "exit_codes": [0],
                    "combined_contains_any": ["fireflies", "FIREFLIES"],
                    "combined_not_contains_any": ["0 active", "no connections", "aucune connexion"],
                },
                "failure_note": "Pas verifie live si Composio n'est pas connecte.",
            },
            {
                "id": "hubspot-live",
                "label": "HubSpot",
                "category": "crm",
                "env_any": ["HUBSPOT_ACCESS_TOKEN", "HUBSPOT_API_KEY"],
                "command": ["composio", "connections", "list"],
                "timeout_seconds": 8,
                "success": {
                    "exit_codes": [0],
                    "combined_contains_any": ["hubspot", "HUBSPOT"],
                    "combined_not_contains_any": ["0 active", "no connections", "aucune connexion"],
                },
                "failure_note": "Credentials possibles, mais aucun appel live HubSpot confirme cote Zab.",
            },
            {
                "id": "gitlab-carrefour-danmdata-zab",
                "label": "GitLab Carrefour/Danmdata via Zab",
                "category": "project-management",
                "zab_task_source": "danmdata-gitlab",
                "success_message": "Source GitLab Carrefour lisible via Zab.",
                "failure_note": "Source GitLab Carrefour non lisible via Zab.",
            },
            {
                "id": "pennylane",
                "label": "Pennylane",
                "category": "finance",
                "env_all": ["PENNYLANE_API_KEY"],
                "failure_note": "PENNYLANE_API_KEY manque cote Zab ou smoke reseau Pennylane non abouti.",
            },
            {
                "id": "qonto",
                "label": "Qonto",
                "category": "finance",
                "env_any": ["QONTO_API_KEY", "QONTO_LOGIN", "QONTO_SECRET_KEY"],
                "failure_note": "Credentials presents possibles, mais paiement/transactions non verifies live.",
            },
            {
                "id": "evolution-api-whatsapp",
                "label": "Evolution API / WhatsApp",
                "category": "messaging",
                "env_any": ["EVOLUTION_API_KEY", "EVOLUTION_API_URL", "EVOLUTION_INSTANCE"],
                "failure_note": "Credentials presents possibles, mais non utilises pour lire/chercher les echanges.",
            },
        ],
    }


def ensure_default_cli_checks_config(*, overwrite: bool = False, path: Path | None = None) -> Path:
    """Create the default JSON config if missing, or overwrite it when requested."""
    target = (path or cli_checks_config_path()).expanduser().resolve()
    if target.is_file() and not overwrite:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(default_cli_checks_config(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def load_cli_checks_config(path: Path | None = None, *, create_default: bool = True) -> tuple[Path, dict[str, Any]]:
    """Load a CLI check config, bootstrapping the default file when needed."""
    target = (path or cli_checks_config_path()).expanduser().resolve()
    if not target.is_file() and create_default:
        ensure_default_cli_checks_config(path=target)
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"fichier cli-check introuvable: {target}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON cli-check invalide: {target} ({exc})") from exc
    if not isinstance(raw, dict):
        raise ValueError("le fichier cli-check doit contenir un objet JSON a la racine")
    checks = raw.get("checks")
    if not isinstance(checks, list):
        raise ValueError("le fichier cli-check doit contenir une liste checks[]")
    return target, raw


def _find_check_config(check_id: str, path: Path | None = None) -> tuple[Path, dict[str, Any]]:
    target, cfg = load_cli_checks_config(path)
    wanted = check_id.strip()
    if not wanted:
        raise ValueError("check_id vide")
    for raw in cfg.get("checks") or []:
        if isinstance(raw, dict) and str(raw.get("id") or "").strip() == wanted:
            return target, raw
    raise KeyError(wanted)


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        s = value.strip()
        return [s] if s else []
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        s = str(item).strip()
        if s:
            out.append(s)
    return out


def _command_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return shlex.split(value)
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def command_for_check(check_id: str, path: Path | None = None) -> dict[str, Any]:
    """Return the configured terminal command for one check without executing it."""
    config_path, raw = _find_check_config(check_id, path)
    command = _command_list(raw.get("command"))
    if not command:
        raise ValueError(f"aucune commande configurée pour {check_id}")
    cwd_raw = str(raw.get("cwd") or "").strip()
    cwd = str(Path(cwd_raw).expanduser().resolve()) if cwd_raw else str(Path.home())
    return {
        "id": str(raw.get("id") or check_id),
        "label": str(raw.get("label") or check_id),
        "command": command,
        "cwd": cwd,
        "config_path": str(config_path),
    }


def open_check_command_terminal(check_id: str, path: Path | None = None) -> dict[str, Any]:
    """Open a new terminal running the command configured for one CLI check."""
    payload = command_for_check(check_id, path)
    opened_with = open_command_in_terminal(
        list(payload["command"]),
        cwd=Path(str(payload["cwd"])),
        title=f"zab: {payload['label']}",
    )
    return {**payload, "opened": True, "opened_with": opened_with}


_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization)(['\"\s:=]+)([^\s,'\"]{8,})"),
    re.compile(r"(?i)(bearer\s+)([a-z0-9._~+/=-]{12,})"),
]


def _redact(text: str, limit: int = 1200) -> str:
    out = text[-limit:] if len(text) > limit else text
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", out)
    return out


def _contains(text: str, needle: str, *, case_sensitive: bool) -> bool:
    if case_sensitive:
        return needle in text
    return needle.lower() in text.lower()


def _missing_contains_any(text: str, needles: list[str], *, case_sensitive: bool) -> bool:
    return bool(needles) and not any(_contains(text, needle, case_sensitive=case_sensitive) for needle in needles)


def _missing_contains_all(text: str, needles: list[str], *, case_sensitive: bool) -> list[str]:
    return [needle for needle in needles if not _contains(text, needle, case_sensitive=case_sensitive)]


def _forbidden_hits(text: str, needles: list[str], *, case_sensitive: bool) -> list[str]:
    return [needle for needle in needles if _contains(text, needle, case_sensitive=case_sensitive)]


def _status_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "ok": sum(1 for row in rows if row.get("status") == "ok"),
        "warn": sum(1 for row in rows if row.get("status") == "warn"),
        "fail": sum(1 for row in rows if row.get("status") == "fail"),
        "skipped": sum(1 for row in rows if row.get("status") == "skipped"),
    }


def _item(
    *,
    id: str,
    label: str,
    category: str,
    status: Status,
    message: str,
    detail: dict[str, Any] | None = None,
    url: str | None = None,
) -> dict[str, Any]:
    return {
        "id": id,
        "label": label,
        "category": category,
        "status": status,
        "message": message,
        "url": url,
        "detail": detail or {},
    }


def _env_presence_map(names: list[str]) -> dict[str, dict[str, Any]]:
    if not names:
        return {}
    try:
        scan = scan_secret_presence(tuple(names))
    except Exception:
        return {}
    rows = scan.get("variables")
    if not isinstance(rows, list):
        return {}
    return {str(row.get("name")): row for row in rows if isinstance(row, dict)}


def _env_present(name: str, env_presence: dict[str, dict[str, Any]]) -> bool:
    row = env_presence.get(name)
    if row is not None:
        return bool(row.get("present"))
    return bool(os.environ.get(name))


def _check_one(raw: Any, *, env_presence: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return _item(
            id="invalid",
            label="Check invalide",
            category="cli",
            status="fail",
            message="Chaque entree checks[] doit etre un objet JSON",
        )

    cid = str(raw.get("id") or raw.get("label") or "cli-check").strip()
    label = str(raw.get("label") or cid).strip()
    category = str(raw.get("category") or "cli").strip()
    url = str(raw.get("url") or "").strip() or None
    detail: dict[str, Any] = {
        "description": raw.get("description"),
        "failure_note": raw.get("failure_note"),
    }

    if raw.get("enabled") is False:
        return _item(id=cid, label=label, category=category, status="skipped", message="Check desactive", detail=detail, url=url)

    env_all = _string_list(raw.get("env_all"))
    env_any = _string_list(raw.get("env_any"))
    env_presence = env_presence or {}
    missing_all = [name for name in env_all if not _env_present(name, env_presence)]
    present_any = [name for name in env_any if _env_present(name, env_presence)]
    if missing_all:
        detail["missing_env"] = missing_all
        return _item(
            id=cid,
            label=label,
            category=category,
            status=str(raw.get("missing_env_status") or "fail"),
            message=str(raw.get("failure_note") or f"Variables manquantes: {', '.join(missing_all)}"),
            detail=detail,
            url=url,
        )
    if env_any and not present_any:
        detail["missing_env_any"] = env_any
        return _item(
            id=cid,
            label=label,
            category=category,
            status=str(raw.get("missing_env_status") or "fail"),
            message=str(raw.get("failure_note") or f"Aucune variable presente parmi: {', '.join(env_any)}"),
            detail=detail,
            url=url,
        )
    if env_all:
        detail["env_all_present"] = env_all
    if env_any:
        detail["env_any_present"] = present_any

    task_source_id = str(raw.get("zab_task_source") or "").strip()
    if task_source_id:
        detail["zab_task_source"] = task_source_id
        try:
            from zab.services.tasks_inbox import check_single_source

            source = check_single_source(task_source_id)
        except KeyError:
            return _item(
                id=cid,
                label=label,
                category=category,
                status="fail",
                message=str(raw.get("failure_note") or f"Source Zab inconnue: {task_source_id}"),
                detail=detail,
                url=url,
            )
        except Exception as exc:
            detail["error"] = str(exc)[:300]
            return _item(
                id=cid,
                label=label,
                category=category,
                status="fail",
                message=str(raw.get("failure_note") or f"Check source Zab impossible: {type(exc).__name__}"),
                detail=detail,
                url=url,
            )
        source_status = str(source.get("status") or "")
        item_count = len(source.get("items") or []) if isinstance(source.get("items"), list) else 0
        detail.update(
            {
                "source_status": source_status,
                "source_reason": source.get("reason"),
                "item_count": item_count,
                "token_present": bool(source.get("token_present")),
                "checked_at_utc": source.get("checked_at_utc"),
            }
        )
        if source_status == "ok":
            return _item(
                id=cid,
                label=label,
                category=category,
                status="ok",
                message=str(raw.get("success_message") or f"Source Zab OK ({item_count} items)"),
                detail=detail,
                url=url,
            )
        return _item(
            id=cid,
            label=label,
            category=category,
            status=str(raw.get("source_error_status") or "fail"),
            message=str(raw.get("failure_note") or source.get("reason") or f"Source Zab {source_status}"),
            detail=detail,
            url=url,
        )

    command = _command_list(raw.get("command"))
    detail["command"] = command
    if not command:
        status = str(raw.get("no_command_status") or "warn")
        msg = str(raw.get("success_message") or raw.get("failure_note") or "Variables presentes; aucun test live configure")
        return _item(id=cid, label=label, category=category, status=status, message=msg, detail=detail, url=url)

    binary = str(raw.get("binary") or command[0]).strip()
    binary_path = shutil.which(binary)
    detail["binary"] = binary
    detail["binary_path"] = binary_path
    if not binary_path:
        return _item(
            id=cid,
            label=label,
            category=category,
            status=str(raw.get("missing_binary_status") or "fail"),
            message=str(raw.get("failure_note") or f"CLI introuvable sur PATH: {binary}"),
            detail=detail,
            url=url,
        )

    timeout = raw.get("timeout_seconds", 10)
    try:
        timeout_f = min(max(float(timeout), 1.0), 120.0)
    except (TypeError, ValueError):
        timeout_f = 10.0
    cwd_raw = str(raw.get("cwd") or "").strip()
    cwd = str(Path(cwd_raw).expanduser().resolve()) if cwd_raw else None
    detail["timeout_seconds"] = timeout_f
    if cwd:
        detail["cwd"] = cwd

    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout_f, check=False, cwd=cwd)
    except subprocess.TimeoutExpired:
        return _item(
            id=cid,
            label=label,
            category=category,
            status="fail",
            message=str(raw.get("failure_note") or f"Timeout apres {timeout_f:.0f}s"),
            detail=detail,
            url=url,
        )
    except OSError as exc:
        detail["error"] = str(exc)
        return _item(
            id=cid,
            label=label,
            category=category,
            status="fail",
            message=str(raw.get("failure_note") or f"Execution impossible: {type(exc).__name__}"),
            detail=detail,
            url=url,
        )

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    combined = f"{stdout}\n{stderr}"
    detail.update(
        {
            "exit_code": proc.returncode,
            "stdout_tail": _redact(stdout),
            "stderr_tail": _redact(stderr),
        }
    )

    success = raw.get("success") if isinstance(raw.get("success"), dict) else {}
    exit_codes_raw = success.get("exit_codes", [0])
    exit_codes = [int(x) for x in exit_codes_raw] if isinstance(exit_codes_raw, list) else [0]
    case_sensitive = bool(success.get("case_sensitive", False))
    reasons: list[str] = []
    if proc.returncode not in exit_codes:
        reasons.append(f"exit {proc.returncode} hors {exit_codes}")

    targets = {
        "stdout": stdout,
        "stderr": stderr,
        "combined": combined,
    }
    for name, text in targets.items():
        any_key = f"{name}_contains_any"
        all_key = f"{name}_contains_all"
        not_key = f"{name}_not_contains_any"
        if _missing_contains_any(text, _string_list(success.get(any_key)), case_sensitive=case_sensitive):
            reasons.append(f"{any_key} non satisfait")
        missing = _missing_contains_all(text, _string_list(success.get(all_key)), case_sensitive=case_sensitive)
        if missing:
            reasons.append(f"{all_key} manquant: {', '.join(missing[:3])}")
        forbidden = _forbidden_hits(text, _string_list(success.get(not_key)), case_sensitive=case_sensitive)
        if forbidden:
            reasons.append(f"{not_key} detecte: {', '.join(forbidden[:3])}")

    if reasons:
        detail["reasons"] = reasons
        return _item(
            id=cid,
            label=label,
            category=category,
            status="fail",
            message=str(raw.get("failure_note") or "; ".join(reasons)),
            detail=detail,
            url=url,
        )

    return _item(
        id=cid,
        label=label,
        category=category,
        status="ok",
        message=str(raw.get("success_message") or "Auth CLI validee"),
        detail=detail,
        url=url,
    )


def run_cli_checks(
    path: Path | None = None,
    *,
    create_default: bool = True,
    only: list[str] | None = None,
) -> dict[str, Any]:
    """Run all configured CLI auth checks and return an aggregate payload."""
    config_path, cfg = load_cli_checks_config(path, create_default=create_default)
    wanted = {item.strip() for item in (only or []) if item.strip()}
    checks_raw = cfg.get("checks") if isinstance(cfg.get("checks"), list) else []
    env_names: list[str] = []
    for raw in checks_raw:
        if isinstance(raw, dict):
            env_names.extend(_string_list(raw.get("env_all")))
            env_names.extend(_string_list(raw.get("env_any")))
    env_presence = _env_presence_map(env_names)
    rows: list[dict[str, Any]] = []
    for raw in checks_raw:
        if wanted and isinstance(raw, dict):
            rid = str(raw.get("id") or "").strip()
            label = str(raw.get("label") or "").strip()
            if rid not in wanted and label not in wanted:
                continue
        rows.append(_check_one(raw, env_presence=env_presence))

    counts = _status_counts(rows)
    weights = {"ok": 1.0, "warn": 0.5, "fail": 0.0, "skipped": 0.0}
    score = sum(weights.get(str(row.get("status")), 0.0) for row in rows)
    percentage = round((score / len(rows)) * 100) if rows else 0
    return {
        "contract": "cli-auth-checks",
        "contract_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "config_path": str(config_path),
        "total": len(rows),
        "percentage": percentage,
        "score": score,
        **counts,
        "checks": rows,
    }
