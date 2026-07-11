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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from zab.paths import config_dir, local_tools_config_path
from zab.services.secrets_scan import scan_secret_presence
from zab.system_open import open_command_in_terminal
from zab.user_config import cli_watchlist_from_user_config, load_user_config, save_user_config

Status = str

_LEGACY_DEFAULT_CHECK_IDS = {
    "gog-gmail-work",
    "composio-connections",
    "fireflies-via-composio",
    "hubspot-live",
    "gitlab-client-project-zab",
    "pennylane",
    "qonto",
    "evolution-api-whatsapp",
}

_LOGIN_COMMANDS: dict[str, list[str]] = {
    "claude": ["claude", "auth", "login"],
    "codex": ["codex", "login"],
    "opencode": ["opencode", "providers", "login"],
    "qwen": ["qwen", "auth", "qwen-oauth"],
    "kimi": ["kimi", "login"],
    "gh": ["gh", "auth", "login"],
    "glab": ["glab", "auth", "login"],
    "composio": ["composio", "login"],
    "gcloud": ["gcloud", "auth", "login"],
    "aws": ["aws", "configure"],
    "docker": ["docker", "login"],
    "npm": ["npm", "login"],
    "pnpm": ["pnpm", "login"],
    "yarn": ["yarn", "npm", "login"],
    "vercel": ["vercel", "login"],
    "supabase": ["supabase", "login"],
    "firebase": ["firebase", "login"],
    "flyctl": ["flyctl", "auth", "login"],
    "ngrok": ["ngrok", "config", "add-authtoken"],
    "stripe": ["stripe", "login"],
}


def cli_checks_config_path() -> Path:
    """Default user config path for declarative CLI auth checks."""
    return config_dir() / "cli-checks.json"


def _merged_cli_watchlist_names() -> list[str]:
    names: list[str] = []
    p = local_tools_config_path()
    if p.is_file():
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            raw = doc.get("cli_watchlist") if isinstance(doc, dict) else None
            if isinstance(raw, list):
                for item in raw:
                    name = str(item).strip()
                    if name and name not in names:
                        names.append(name)
        except (OSError, yaml.YAMLError):
            pass
    for item in cli_watchlist_from_user_config():
        name = item.strip()
        if name and name not in names:
            names.append(name)
    return names


def _watchlist_check(name: str) -> dict[str, Any]:
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", name).strip("-").lower() or name
    row = {
        "id": f"cli-{slug}",
        "label": name,
        "category": "cli-watchlist",
        "binary": name,
        "command": [name, "--version"],
        "timeout_seconds": 5,
        "success": {"exit_codes": [0]},
        "failure_note": f"CLI {name} introuvable ou non exécutable depuis PATH.",
    }
    login_command = _LOGIN_COMMANDS.get(name)
    if login_command:
        row["login_command"] = login_command
    return row


def default_cli_checks_config() -> dict[str, Any]:
    """Return the example config used to bootstrap ``cli-checks.json``."""
    watchlist = _merged_cli_watchlist_names()
    return {
        "version": 1,
        "description": "Checks declaratifs generes depuis cli_watchlist. Modifiez les entrees pour ajouter des validations d'auth plus precises.",
        "source": "cli_watchlist",
        "checks": [_watchlist_check(name) for name in watchlist],
    }


def _check_binary_name(raw: dict[str, Any]) -> str:
    binary = str(raw.get("binary") or "").strip()
    if binary:
        return binary
    command = _command_list(raw.get("command"))
    if command:
        return Path(command[0]).name
    return str(raw.get("label") or raw.get("id") or "").strip()


def _sync_cli_watchlist_config(raw: dict[str, Any]) -> dict[str, Any]:
    """Return a cli-check config whose checks mirror the merged CLI watchlist."""
    by_binary: dict[str, dict[str, Any]] = {}
    existing = raw.get("checks")
    if isinstance(existing, list):
        for item in existing:
            if not isinstance(item, dict):
                continue
            binary = _check_binary_name(item)
            if binary and binary not in by_binary:
                by_binary[binary] = item

    checks: list[dict[str, Any]] = []
    for name in _merged_cli_watchlist_names():
        base = _watchlist_check(name)
        previous = by_binary.get(name)
        if previous:
            merged = {**base, **previous, "binary": name}
            if not _command_list(merged.get("command")):
                merged["command"] = base["command"]
            checks.append(merged)
        else:
            checks.append(base)

    return {
        **raw,
        "version": raw.get("version") or 1,
        "description": raw.get("description") or "Checks declaratifs generes depuis cli_watchlist.",
        "source": "cli_watchlist",
        "checks": checks,
    }


def _mutate_user_cli_watchlist(*, add: str | None = None, remove: str | None = None, replace: tuple[str, str] | None = None) -> Path:
    cfg = dict(load_user_config())
    cfg.pop("_error", None)
    raw = cfg.get("cli_watchlist")
    names = [str(item).strip() for item in raw if isinstance(item, str) and str(item).strip()] if isinstance(raw, list) else []

    if remove:
        names = [name for name in names if name != remove]
    if replace:
        old, new = replace
        names = [new if name == old else name for name in names]
    if add and add not in names:
        names.append(add)

    deduped: list[str] = []
    for name in names:
        if name and name not in deduped:
            deduped.append(name)
    cfg["cli_watchlist"] = deduped
    return save_user_config(cfg)


def _looks_like_legacy_default(raw: dict[str, Any]) -> bool:
    checks = raw.get("checks")
    if not isinstance(checks, list):
        return False
    ids = {str(item.get("id") or "").strip() for item in checks if isinstance(item, dict)}
    return len(ids & _LEGACY_DEFAULT_CHECK_IDS) >= 3


def ensure_default_cli_checks_config(*, overwrite: bool = False, path: Path | None = None) -> Path:
    """Create the default JSON config if missing, or overwrite it when requested."""
    target = (path or cli_checks_config_path()).expanduser().resolve()
    if target.is_file() and not overwrite:
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return target
        if isinstance(raw, dict) and _looks_like_legacy_default(raw):
            target.write_text(json.dumps(_sync_cli_watchlist_config({}), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(default_cli_checks_config(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def load_cli_checks_config(
    path: Path | None = None,
    *,
    create_default: bool = True,
    sync_watchlist: bool = True,
) -> tuple[Path, dict[str, Any]]:
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
    if sync_watchlist and (raw.get("source") == "cli_watchlist" or _looks_like_legacy_default(raw)):
        synced = _sync_cli_watchlist_config(raw if raw.get("source") == "cli_watchlist" else {})
        if synced != raw:
            save_cli_checks_config(synced, target)
            raw = synced
    return target, raw


def save_cli_checks_config(cfg: dict[str, Any], path: Path | None = None) -> Path:
    """Persist a complete CLI check config."""
    target = (path or cli_checks_config_path()).expanduser().resolve()
    checks = cfg.get("checks")
    if not isinstance(checks, list):
        raise ValueError("le fichier cli-check doit contenir une liste checks[]")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def _check_id(raw: dict[str, Any]) -> str:
    return str(raw.get("id") or raw.get("label") or "").strip()


def upsert_cli_check_config(check: dict[str, Any], *, previous_id: str | None = None, path: Path | None = None) -> dict[str, Any]:
    """Add or replace one check entry in ``checks[]`` and persist the config."""
    if not isinstance(check, dict):
        raise ValueError("le check doit etre un objet JSON")
    cid = _check_id(check)
    if not cid:
        raise ValueError("le check doit contenir id ou label")
    config_path, cfg = load_cli_checks_config(path)
    sync_watchlist = path is None and cfg.get("source") == "cli_watchlist"
    checks = cfg.get("checks")
    if not isinstance(checks, list):
        raise ValueError("le fichier cli-check doit contenir une liste checks[]")

    wanted = (previous_id or cid).strip()
    replace_index: int | None = None
    previous: dict[str, Any] | None = None
    for idx, raw in enumerate(checks):
        if isinstance(raw, dict) and _check_id(raw) == wanted:
            replace_index = idx
            previous = raw
            break

    for idx, raw in enumerate(checks):
        if idx != replace_index and isinstance(raw, dict) and _check_id(raw) == cid:
            raise ValueError(f"check deja existant: {cid}")

    if replace_index is None:
        checks.append(check)
    else:
        checks[replace_index] = check
    save_cli_checks_config(cfg, config_path)
    if sync_watchlist:
        new_name = _check_binary_name(check)
        old_name = _check_binary_name(previous) if previous else ""
        if previous and old_name and new_name and old_name != new_name:
            _mutate_user_cli_watchlist(replace=(old_name, new_name))
        elif new_name:
            _mutate_user_cli_watchlist(add=new_name)
    return {"path": str(config_path), "config": cfg, "check": check}


def delete_cli_check_config(check_id: str, path: Path | None = None) -> dict[str, Any]:
    """Remove one check entry from ``checks[]`` and persist the config."""
    wanted = check_id.strip()
    if not wanted:
        raise ValueError("check_id vide")
    config_path, cfg = load_cli_checks_config(path)
    sync_watchlist = path is None and cfg.get("source") == "cli_watchlist"
    checks = cfg.get("checks")
    if not isinstance(checks, list):
        raise ValueError("le fichier cli-check doit contenir une liste checks[]")
    for idx, raw in enumerate(checks):
        if isinstance(raw, dict) and _check_id(raw) == wanted:
            removed = checks.pop(idx)
            save_cli_checks_config(cfg, config_path)
            if sync_watchlist:
                name = _check_binary_name(removed)
                if name:
                    _mutate_user_cli_watchlist(remove=name)
            return {"path": str(config_path), "config": cfg, "removed": removed}
    raise KeyError(wanted)


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


def login_command_for_check(check_id: str, path: Path | None = None) -> dict[str, Any]:
    """Return the configured login command for one check without executing it."""
    config_path, raw = _find_check_config(check_id, path)
    command = _command_list(raw.get("login_command"))
    if not command:
        raise ValueError(f"aucune commande de login configurée pour {check_id}")
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


def open_check_login_terminal(check_id: str, path: Path | None = None) -> dict[str, Any]:
    """Open a new terminal running the configured login command for one CLI check."""
    payload = login_command_for_check(check_id, path)
    opened_with = open_command_in_terminal(
        list(payload["command"]),
        cwd=Path(str(payload["cwd"])),
        title=f"zab login: {payload['label']}",
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
    login_command = _command_list(raw.get("login_command"))
    if login_command:
        detail["login_command"] = login_command

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
    selected_raw: list[Any] = []
    for raw in checks_raw:
        if wanted:
            if not isinstance(raw, dict):
                continue
            rid = str(raw.get("id") or "").strip()
            label = str(raw.get("label") or "").strip()
            if rid not in wanted and label not in wanted:
                continue
        selected_raw.append(raw)

    env_names: list[str] = []
    for raw in selected_raw:
        if isinstance(raw, dict):
            env_names.extend(_string_list(raw.get("env_all")))
            env_names.extend(_string_list(raw.get("env_any")))
    env_presence = _env_presence_map(env_names)
    if len(selected_raw) <= 1:
        rows = [_check_one(raw, env_presence=env_presence) for raw in selected_raw]
    else:
        max_workers = min(8, len(selected_raw))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            rows = list(executor.map(lambda raw: _check_one(raw, env_presence=env_presence), selected_raw))

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
