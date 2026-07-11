"""Update-status report for CLIs tracked by ``cli_watchlist``."""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from zab.services import cli_check

Status = str

_VERSION_RE = re.compile(r"(?<![A-Za-z0-9])v?(\d+(?:\.\d+){0,5}(?:[-+][A-Za-z0-9_.-]+)?)")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _string(value: Any) -> str:
    return str(value or "").strip()


def _command_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return shlex.split(value)
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def _first_line(text: str, *, limit: int = 240) -> str:
    for line in text.splitlines():
        cleaned = line.strip()
        if cleaned:
            return cleaned[:limit]
    return ""


def extract_version(text: str) -> str | None:
    """Extract the first semver-ish version from command or API text."""
    match = _VERSION_RE.search(text or "")
    return match.group(1) if match else None


def _version_key(version: str | None) -> tuple[int, ...] | None:
    if not version:
        return None
    core = re.split(r"[-+]", version.strip().lstrip("v"), maxsplit=1)[0]
    parts: list[int] = []
    for raw in core.split("."):
        if not raw.isdigit():
            return None
        parts.append(int(raw))
    return tuple(parts) if parts else None


def compare_versions(local: str | None, latest: str | None) -> int | None:
    """Return -1/0/1 when comparable, otherwise ``None``."""
    local_key = _version_key(local)
    latest_key = _version_key(latest)
    if local_key is None or latest_key is None:
        if local and latest and local.strip().lstrip("v") == latest.strip().lstrip("v"):
            return 0
        return None
    width = max(len(local_key), len(latest_key))
    left = local_key + (0,) * (width - len(local_key))
    right = latest_key + (0,) * (width - len(latest_key))
    if left == right:
        return 0
    return -1 if left < right else 1


def _run_command(command: list[str], *, timeout_seconds: float) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        return {
            "returncode": proc.returncode,
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "returncode": None,
            "stdout": exc.stdout if isinstance(exc.stdout, str) else "",
            "stderr": exc.stderr if isinstance(exc.stderr, str) else "",
            "error": f"timeout after {timeout_seconds:g}s",
        }
    except OSError as exc:
        return {"returncode": None, "stdout": "", "stderr": "", "error": str(exc)}


def _binary_path(binary: str) -> str | None:
    if not binary:
        return None
    if "/" in binary:
        path = Path(binary).expanduser()
        return str(path) if path.is_file() and path.exists() else None
    return shutil.which(binary)


def _version_command(raw: dict[str, Any], *, binary: str, binary_path: str) -> list[str]:
    command = _command_list(raw.get("version_command"))
    if not command:
        command = _command_list(raw.get("command"))
    if not command:
        command = [binary, "--version"]

    if command and binary_path and Path(command[0]).name == Path(binary).name:
        return [binary_path, *command[1:]]
    return command


def _read_local_version(raw: dict[str, Any], *, binary: str, binary_path: str, timeout_seconds: float) -> dict[str, Any]:
    command = _version_command(raw, binary=binary, binary_path=binary_path)
    result = _run_command(command, timeout_seconds=timeout_seconds)
    combined = "\n".join(part for part in (result.get("stdout"), result.get("stderr")) if isinstance(part, str))
    return {
        "command": command,
        "returncode": result.get("returncode"),
        "raw": _first_line(combined),
        "version": extract_version(combined),
        "error": result.get("error"),
    }


def _normalize_update_config(raw: dict[str, Any]) -> dict[str, Any]:
    update = raw.get("update") or raw.get("latest")
    if isinstance(update, str):
        return {"source": "manual", "version": update}
    if isinstance(update, dict):
        return dict(update)

    source = _string(raw.get("latest_source") or raw.get("update_source"))
    if source:
        out = {"source": source}
        for key in ("version", "package", "formula", "cask", "repo", "url", "json_path", "command"):
            if raw.get(key) is not None:
                out[key] = raw.get(key)
        return out
    if raw.get("latest_version") is not None:
        return {"source": "manual", "version": raw.get("latest_version")}
    return {}


def _json_path(data: Any, path: str) -> Any:
    current = data
    for part in path.split("."):
        key = part.strip()
        if not key:
            continue
        if isinstance(current, dict):
            current = current.get(key)
        elif isinstance(current, list) and key.isdigit():
            current = current[int(key)]
        else:
            return None
    return current


def _latest_from_brew(config: dict[str, Any], *, name: str, timeout_seconds: float) -> dict[str, Any]:
    package = _string(config.get("formula") or config.get("cask") or config.get("package") or name)
    brew = shutil.which("brew")
    if not brew:
        return {"source": "brew", "package": package, "error": "brew not found"}
    result = _run_command([brew, "info", "--json=v2", package], timeout_seconds=timeout_seconds)
    if result.get("returncode") != 0:
        return {
            "source": "brew",
            "package": package,
            "error": _first_line(str(result.get("stderr") or result.get("stdout") or result.get("error") or "")),
        }
    try:
        data = json.loads(str(result.get("stdout") or "{}"))
    except json.JSONDecodeError as exc:
        return {"source": "brew", "package": package, "error": f"invalid brew JSON: {exc}"}

    for section in ("formulae", "casks"):
        rows = data.get(section)
        if isinstance(rows, list) and rows:
            row = rows[0] if isinstance(rows[0], dict) else {}
            version = row.get("version") if section == "casks" else (row.get("versions") or {}).get("stable")
            if version:
                return {"source": "brew", "package": package, "version": str(version)}
    return {"source": "brew", "package": package, "error": "no version in brew response"}


def _latest_from_npm(config: dict[str, Any], *, name: str, network: bool, timeout_seconds: float) -> dict[str, Any]:
    package = _string(config.get("package") or name)
    if not network:
        return {"source": "npm", "package": package, "error": "network disabled"}
    npm = shutil.which("npm")
    if not npm:
        return {"source": "npm", "package": package, "error": "npm not found"}
    result = _run_command([npm, "view", package, "version", "--silent"], timeout_seconds=timeout_seconds)
    text = _first_line(str(result.get("stdout") or result.get("stderr") or result.get("error") or ""))
    version = extract_version(text)
    if result.get("returncode") == 0 and version:
        return {"source": "npm", "package": package, "version": version}
    return {"source": "npm", "package": package, "error": text or "npm view failed"}


def _latest_from_pypi(config: dict[str, Any], *, name: str, network: bool, timeout_seconds: float) -> dict[str, Any]:
    package = _string(config.get("package") or name)
    if not network:
        return {"source": "pypi", "package": package, "error": "network disabled"}
    try:
        response = httpx.get(f"https://pypi.org/pypi/{package}/json", timeout=timeout_seconds)
        response.raise_for_status()
        version = str((response.json().get("info") or {}).get("version") or "").strip()
    except (httpx.HTTPError, ValueError) as exc:
        return {"source": "pypi", "package": package, "error": str(exc)}
    return {"source": "pypi", "package": package, "version": version} if version else {"source": "pypi", "package": package, "error": "no version in PyPI response"}


def _latest_from_github(config: dict[str, Any], *, network: bool, timeout_seconds: float) -> dict[str, Any]:
    repo = _string(config.get("repo"))
    if not repo:
        return {"source": "github", "error": "missing repo"}
    if not network:
        return {"source": "github", "repo": repo, "error": "network disabled"}
    try:
        response = httpx.get(
            f"https://api.github.com/repos/{repo}/releases/latest",
            headers={"Accept": "application/vnd.github+json"},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return {"source": "github", "repo": repo, "error": str(exc)}
    raw = str(data.get("tag_name") or data.get("name") or "").strip()
    version = extract_version(raw) or raw.lstrip("v")
    return {"source": "github", "repo": repo, "version": version} if version else {"source": "github", "repo": repo, "error": "no release version"}


def _latest_from_url(config: dict[str, Any], *, network: bool, timeout_seconds: float) -> dict[str, Any]:
    url = _string(config.get("url"))
    if not url:
        return {"source": "url", "error": "missing url"}
    if not network:
        return {"source": "url", "url": url, "error": "network disabled"}
    try:
        response = httpx.get(url, timeout=timeout_seconds)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return {"source": "url", "url": url, "error": str(exc)}

    path = _string(config.get("json_path"))
    if path:
        try:
            value = _json_path(response.json(), path)
        except ValueError as exc:
            return {"source": "url", "url": url, "error": f"invalid JSON: {exc}"}
        version = extract_version(str(value or "")) or _string(value)
    else:
        version = extract_version(response.text)
    return {"source": "url", "url": url, "version": version} if version else {"source": "url", "url": url, "error": "no version in response"}


def _latest_from_command(config: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]:
    command = _command_list(config.get("command"))
    if not command:
        return {"source": "command", "error": "missing command"}
    result = _run_command(command, timeout_seconds=timeout_seconds)
    combined = "\n".join(part for part in (result.get("stdout"), result.get("stderr")) if isinstance(part, str))
    version = extract_version(combined)
    if version:
        return {"source": "command", "command": command, "version": version}
    return {
        "source": "command",
        "command": command,
        "error": _first_line(combined) or result.get("error") or "command returned no version",
    }


def _infer_npm_package(binary_path: str) -> str | None:
    parts = Path(binary_path).resolve().parts
    if "node_modules" not in parts:
        return None
    idx = parts.index("node_modules")
    if idx + 1 >= len(parts):
        return None
    first = parts[idx + 1]
    if first.startswith("@") and idx + 2 < len(parts):
        return f"{first}/{parts[idx + 2]}"
    if first != ".bin":
        return first
    return None


def _auto_latest_config(*, name: str, binary_path: str) -> dict[str, Any]:
    npm_package = _infer_npm_package(binary_path)
    if npm_package:
        return {"source": "npm", "package": npm_package, "inferred": True}
    if shutil.which("brew"):
        return {"source": "brew", "package": name, "inferred": True}
    return {}


def _latest_version(
    config: dict[str, Any],
    *,
    name: str,
    binary_path: str,
    network: bool,
    timeout_seconds: float,
) -> dict[str, Any]:
    latest_config = dict(config) if config else _auto_latest_config(name=name, binary_path=binary_path)
    source = _string(latest_config.get("source")).lower()
    if not source:
        return {"source": "unknown", "error": "no update source configured"}
    if source in {"manual", "static"}:
        version = _string(latest_config.get("version") or latest_config.get("latest_version"))
        return {"source": "manual", "version": version} if version else {"source": "manual", "error": "missing version"}
    if source == "brew":
        return _latest_from_brew(latest_config, name=name, timeout_seconds=timeout_seconds)
    if source == "npm":
        return _latest_from_npm(latest_config, name=name, network=network, timeout_seconds=timeout_seconds)
    if source == "pypi":
        return _latest_from_pypi(latest_config, name=name, network=network, timeout_seconds=timeout_seconds)
    if source == "github":
        return _latest_from_github(latest_config, network=network, timeout_seconds=timeout_seconds)
    if source == "url":
        return _latest_from_url(latest_config, network=network, timeout_seconds=timeout_seconds)
    if source == "command":
        return _latest_from_command(latest_config, timeout_seconds=timeout_seconds)
    return {"source": source, "error": f"unsupported update source: {source}"}


def _status_message(status: Status, *, local: str | None, latest: str | None, source: str) -> str:
    if status == "up_to_date":
        return f"a jour ({local})"
    if status == "outdated":
        return f"mise a jour disponible: {local or '?'} -> {latest}"
    if status == "ahead":
        return f"version locale plus recente que {source}: {local} > {latest}"
    if status == "missing":
        return "CLI introuvable dans PATH"
    if status == "unknown_local":
        return "version locale non detectee"
    if status == "unknown_latest":
        return "derniere version non determinee"
    return "verification impossible"


def _check_one(raw: dict[str, Any], *, network: bool, timeout_seconds: float) -> dict[str, Any]:
    cid = _string(raw.get("id") or raw.get("label") or "cli")
    label = _string(raw.get("label") or cid)
    binary = _string(raw.get("binary")) or (Path(_command_list(raw.get("command"))[0]).name if _command_list(raw.get("command")) else label)
    path = _binary_path(binary)
    update_config = _normalize_update_config(raw)
    detail: dict[str, Any] = {"update_config": update_config}

    if not path:
        return {
            "id": cid,
            "label": label,
            "binary": binary,
            "binary_path": None,
            "status": "missing",
            "message": _status_message("missing", local=None, latest=None, source=""),
            "local_version": None,
            "latest_version": None,
            "latest_source": _string(update_config.get("source") or "unknown"),
            "detail": detail,
        }

    local = _read_local_version(raw, binary=binary, binary_path=path, timeout_seconds=timeout_seconds)
    detail["local"] = local
    local_version = local.get("version")
    if not local_version:
        return {
            "id": cid,
            "label": label,
            "binary": binary,
            "binary_path": path,
            "status": "unknown_local",
            "message": _status_message("unknown_local", local=None, latest=None, source=""),
            "local_version": None,
            "local_version_raw": local.get("raw"),
            "latest_version": None,
            "latest_source": _string(update_config.get("source") or "unknown"),
            "detail": detail,
        }

    latest = _latest_version(
        update_config,
        name=binary,
        binary_path=path,
        network=network,
        timeout_seconds=timeout_seconds,
    )
    detail["latest"] = latest
    latest_version = _string(latest.get("version")) or None
    latest_source = _string(latest.get("source") or "unknown")
    if not latest_version:
        return {
            "id": cid,
            "label": label,
            "binary": binary,
            "binary_path": path,
            "status": "unknown_latest",
            "message": _status_message("unknown_latest", local=local_version, latest=None, source=latest_source),
            "local_version": local_version,
            "local_version_raw": local.get("raw"),
            "latest_version": None,
            "latest_source": latest_source,
            "detail": detail,
        }

    comparison = compare_versions(str(local_version), latest_version)
    status: Status
    if comparison is None:
        status = "up_to_date" if str(local_version).lstrip("v") == latest_version.lstrip("v") else "unknown_latest"
    elif comparison < 0:
        status = "outdated"
    elif comparison > 0:
        status = "ahead"
    else:
        status = "up_to_date"

    return {
        "id": cid,
        "label": label,
        "binary": binary,
        "binary_path": path,
        "status": status,
        "message": _status_message(status, local=str(local_version), latest=latest_version, source=latest_source),
        "local_version": str(local_version),
        "local_version_raw": local.get("raw"),
        "latest_version": latest_version,
        "latest_source": latest_source,
        "detail": detail,
    }


def _matches_only(raw: dict[str, Any], wanted: set[str]) -> bool:
    if not wanted:
        return True
    values = {
        _string(raw.get("id")).lower(),
        _string(raw.get("label")).lower(),
        _string(raw.get("binary")).lower(),
    }
    command = _command_list(raw.get("command"))
    if command:
        values.add(Path(command[0]).name.lower())
    return bool(values & wanted)


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    statuses = ("up_to_date", "outdated", "ahead", "missing", "unknown_local", "unknown_latest")
    return {status: sum(1 for row in rows if row.get("status") == status) for status in statuses}


def run_cli_update_status(
    path: Path | None = None,
    *,
    only: list[str] | None = None,
    network: bool = True,
    timeout_seconds: float = 8.0,
    max_workers: int = 8,
) -> dict[str, Any]:
    """Build an update-status payload for configured CLI checks."""
    config_path, cfg = cli_check.load_cli_checks_config(path)
    checks = [row for row in (cfg.get("checks") or []) if isinstance(row, dict)]
    wanted = {item.strip().lower() for item in (only or []) if item and item.strip()}
    selected = [row for row in checks if _matches_only(row, wanted)]
    if wanted and not selected:
        raise ValueError(f"aucun CLI suivi ne correspond a: {', '.join(sorted(wanted))}")

    workers = max(1, min(max_workers, len(selected) or 1))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        rows = list(executor.map(lambda row: _check_one(row, network=network, timeout_seconds=timeout_seconds), selected))

    counts = _counts(rows)
    actionable = counts["outdated"] + counts["missing"]
    return {
        "contract": "cli-update-status",
        "version": 1,
        "generated_at_utc": _now(),
        "config_path": str(config_path),
        "network": network,
        "total": len(rows),
        "counts": counts,
        "actionable": actionable,
        "all_up_to_date": bool(rows) and actionable == 0 and counts["unknown_local"] == 0 and counts["unknown_latest"] == 0,
        "items": rows,
    }


def _md_escape(value: Any) -> str:
    text = str(value if value is not None else "")
    return text.replace("|", "\\|").replace("\n", " ").strip()


def render_cli_update_markdown(payload: dict[str, Any]) -> str:
    """Render a compact Markdown report for humans or daily notes."""
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    lines = [
        "# Zab CLI update status",
        "",
        f"- Generated: {_md_escape(payload.get('generated_at_utc'))}",
        f"- Config: `{_md_escape(payload.get('config_path'))}`",
        f"- Summary: {payload.get('total', 0)} tracked, {counts.get('up_to_date', 0)} up to date, {counts.get('outdated', 0)} outdated, {counts.get('missing', 0)} missing, {counts.get('unknown_latest', 0)} unknown latest",
        "",
        "| CLI | Status | Local | Latest | Source | Path | Note |",
        "|---|---:|---:|---:|---|---|---|",
    ]
    for row in payload.get("items") or []:
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_escape(row.get("label") or row.get("binary") or row.get("id")),
                    _md_escape(row.get("status")),
                    _md_escape(row.get("local_version") or row.get("local_version_raw") or "-"),
                    _md_escape(row.get("latest_version") or "-"),
                    _md_escape(row.get("latest_source") or "-"),
                    f"`{_md_escape(row.get('binary_path') or '-')}`",
                    _md_escape(row.get("message") or ""),
                ]
            )
            + " |"
        )
    return "\n".join(lines).rstrip() + "\n"
