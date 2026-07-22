"""Structured request logging for Zab surfaces.

JSONL files are the durable contract. SQLite/Postgres indexing is best-effort
and must never break the caller that is being observed.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from zab.paths import data_dir
from zab.user_config import load_user_config

LOG_FILES: dict[str, str] = {
    "requests": "requests.jsonl",
    "cli": "cli.jsonl",
    "api": "api.jsonl",
    "mcp": "mcp.jsonl",
    "jobs": "jobs.jsonl",
    "errors": "errors.jsonl",
}

LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
SECRET_KEY_PARTS = ("secret", "token", "key", "password", "passwd", "auth", "cookie", "bearer")
MAX_STRING = 240
MAX_LIST_ITEMS = 30
MAX_DEPTH = 5


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_dir() -> Path:
    raw = os.environ.get("ZAB_LOG_DIR", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (data_dir() / "logs").resolve()


def max_bytes() -> int:
    raw = os.environ.get("ZAB_LOG_MAX_BYTES", "").strip()
    if not raw:
        return 10 * 1024 * 1024
    try:
        return max(1024, int(raw))
    except ValueError:
        return 10 * 1024 * 1024


def backup_count() -> int:
    raw = os.environ.get("ZAB_LOG_BACKUP_COUNT", "").strip()
    if not raw:
        return 7
    try:
        return max(0, min(50, int(raw)))
    except ValueError:
        return 7


def log_path(name: str) -> Path:
    filename = LOG_FILES.get(name, LOG_FILES["requests"])
    return log_dir() / filename


def list_files() -> dict[str, Any]:
    root = log_dir()
    files: list[dict[str, Any]] = []
    for key, filename in LOG_FILES.items():
        p = root / filename
        exists = p.is_file()
        row: dict[str, Any] = {
            "id": key,
            "filename": filename,
            "path": str(p),
            "exists": exists,
            "bytes": 0,
            "updated_at": None,
        }
        if exists:
            try:
                st = p.stat()
                row["bytes"] = st.st_size
                row["updated_at"] = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
            except OSError:
                pass
        files.append(row)
    return {
        "contract": "zab-request-log-files",
        "contract_version": "1.0",
        "log_dir": str(root),
        "files": files,
    }


def stable_hash(value: Any) -> str:
    try:
        raw = json.dumps(_json_safe(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except TypeError:
        raw = str(value)
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()


def redact(value: Any, *, key: str | None = None, depth: int = 0) -> Any:
    if key and _is_secret_key(key):
        return "[redacted]"
    if depth > MAX_DEPTH:
        return {"truncated": True, "hash": stable_hash(value)}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str):
        if _looks_like_secret(value):
            return "[redacted]"
        if len(value) > MAX_STRING:
            return {
                "preview": value[:MAX_STRING],
                "truncated": True,
                "chars": len(value),
                "hash": stable_hash(value),
            }
        return value
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            k = str(raw_key)
            out[k] = redact(raw_value, key=k, depth=depth + 1)
        return out
    if isinstance(value, (list, tuple, set)):
        seq = list(value)
        out = [redact(v, depth=depth + 1) for v in seq[:MAX_LIST_ITEMS]]
        if len(seq) > MAX_LIST_ITEMS:
            out.append({"truncated": True, "items": len(seq), "hash": stable_hash(seq)})
        return out
    return str(value)


def redacted_args(args: Any) -> Any:
    return redact(args)


def input_hash(value: Any) -> str | None:
    if value is None:
        return None
    return stable_hash(value)


def actor_context(
    *,
    surface: str,
    source: str | None = None,
    client: str | None = None,
    request: Any | None = None,
) -> dict[str, Any]:
    headers: dict[str, str] = {}
    if request is not None:
        try:
            headers = {str(k).lower(): str(v) for k, v in request.headers.items()}
        except Exception:
            headers = {}
    env_actor = os.environ.get("ZAB_ACTOR_ID", "").strip()
    cfg_actor = _logging_config().get("default_actor")
    actor_id = (
        headers.get("x-zab-actor-id")
        or headers.get("x-zab-actor")
        or env_actor
        or (str(cfg_actor).strip() if cfg_actor else "")
        or getpass.getuser()
    )
    actor_kind = headers.get("x-zab-actor-kind") or os.environ.get("ZAB_ACTOR_KIND", "").strip()
    if not actor_kind:
        if surface == "mcp":
            actor_kind = "agent"
        elif surface == "api":
            actor_kind = "dashboard" if _looks_like_dashboard(headers) else "api"
        elif surface == "cli":
            actor_kind = "human"
        else:
            actor_kind = surface or "unknown"
    if client is None:
        client = headers.get("x-zab-client") or headers.get("user-agent")
    return {
        "kind": actor_kind,
        "id": actor_id,
        "client": client,
        "source": source,
        "pid": os.getpid(),
        "cwd": str(Path.cwd()),
    }


def resolve_scope(
    *,
    project: str | None = None,
    project_path: str | Path | None = None,
    local_project_path: str | Path | None = None,
    source_id: str | None = None,
    args: Any | None = None,
) -> dict[str, Any]:
    explicit_path = project_path or local_project_path
    arg_project, arg_path, arg_source = _scope_fields_from_args(args)
    candidate_project = project or arg_project
    candidate_path = explicit_path or arg_path
    task_source_id = source_id or arg_source
    # Hot path: la grande majorité des requêtes (dashboard GET sans paramètre de
    # scope) n'ont rien à résoudre. On évite alors totalement la lecture des
    # projets, qui reste coûteuse même via l'index. Cf. profilage middleware.
    if not (candidate_path or candidate_project or task_source_id):
        return {
            "org": None,
            "project_id": None,
            "project_path": None,
            "task_source_id": None,
            "resolution": "none",
        }
    projects = _project_rows()
    if candidate_path:
        resolved = _resolve_project_by_path(candidate_path, projects)
        if resolved:
            return {**resolved, "task_source_id": task_source_id, "resolution": "explicit_path"}
        return {
            "org": None,
            "project_id": candidate_project,
            "project_path": str(candidate_path),
            "task_source_id": task_source_id,
            "resolution": "explicit_path_unmatched",
        }
    if candidate_project:
        resolved = _resolve_project_by_alias(candidate_project, projects)
        if resolved:
            return {**resolved, "task_source_id": task_source_id, "resolution": "explicit_project"}
        return {
            "org": None,
            "project_id": str(candidate_project),
            "project_path": None,
            "task_source_id": task_source_id,
            "resolution": "explicit_project_unmatched",
        }
    if task_source_id:
        source_scope = _resolve_task_source(task_source_id, projects)
        if source_scope:
            return source_scope
    return {
        "org": None,
        "project_id": None,
        "project_path": None,
        "task_source_id": task_source_id,
        "resolution": "none",
    }


def build_event(
    *,
    surface: str,
    component: str,
    request: dict[str, Any],
    result: dict[str, Any] | None = None,
    actor: dict[str, Any] | None = None,
    scope: dict[str, Any] | None = None,
    level: str = "INFO",
    request_id: str | None = None,
    parent_request_id: str | None = None,
) -> dict[str, Any]:
    event_result = result or {}
    if "status" not in event_result:
        event_result["status"] = "ok"
    return {
        "event_id": uuid.uuid4().hex,
        "ts": now_utc(),
        "level": _norm_level(level),
        "component": component,
        "surface": surface,
        "request_id": request_id or uuid.uuid4().hex,
        "parent_request_id": parent_request_id,
        "actor": redact(actor or actor_context(surface=surface), key=None),
        "request": redact(request),
        "scope": scope or resolve_scope(args=request),
        "result": redact(event_result),
    }


def record_event(
    *,
    surface: str,
    component: str,
    request: dict[str, Any],
    result: dict[str, Any] | None = None,
    actor: dict[str, Any] | None = None,
    scope: dict[str, Any] | None = None,
    level: str = "INFO",
    request_id: str | None = None,
    parent_request_id: str | None = None,
    index: bool = True,
) -> dict[str, Any]:
    event = build_event(
        surface=surface,
        component=component,
        request=request,
        result=result,
        actor=actor,
        scope=scope,
        level=level,
        request_id=request_id,
        parent_request_id=parent_request_id,
    )
    _append_event_files(event)
    if index:
        _index_event_best_effort(event)
    return event


def tail_file(file: str = "requests", *, lines: int = 100) -> dict[str, Any]:
    key = _file_key(file)
    capped = max(1, min(1000, int(lines)))
    p = log_path(key)
    raw_lines = _tail_lines(p, capped)
    events: list[dict[str, Any]] = []
    for raw in raw_lines:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                events.append(parsed)
        except json.JSONDecodeError:
            events.append({"line": raw})
    return {
        "contract": "zab-request-log-tail",
        "contract_version": "1.0",
        "file": key,
        "path": str(p),
        "lines": raw_lines,
        "events": events,
    }


def filter_events(
    events: list[dict[str, Any]],
    *,
    surface: str | None = None,
    component: str | None = None,
    level: str | None = None,
    actor: str | None = None,
    org: str | None = None,
    project: str | None = None,
    status: str | None = None,
    q: str | None = None,
    since: str | None = None,
) -> list[dict[str, Any]]:
    filters = _filters_dict(
        surface=surface,
        component=component,
        level=level,
        actor=actor,
        org=org,
        project=project,
        status=status,
        q=q,
        since=since,
    )
    return [event for event in events if isinstance(event, dict) and _event_matches(event, filters)]


def query_events(
    *,
    surface: str | None = None,
    component: str | None = None,
    level: str | None = None,
    actor: str | None = None,
    org: str | None = None,
    project: str | None = None,
    status: str | None = None,
    q: str | None = None,
    since: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    filters = _filters_dict(
        surface=surface,
        component=component,
        level=level,
        actor=actor,
        org=org,
        project=project,
        status=status,
        q=q,
        since=since,
    )
    capped = max(1, min(1000, int(limit)))
    events = _query_index_best_effort(filters, limit=capped)
    source = "index"
    if events is None:
        events = _query_files(filters, limit=capped)
        source = "files"
    return {
        "contract": "zab-request-log-query",
        "contract_version": "1.0",
        "source": source,
        "filters": filters,
        "events": events,
        "total": len(events),
    }


def summary(*, since: str | None = "24h") -> dict[str, Any]:
    payload = query_events(since=since, limit=1000)
    events = payload.get("events") if isinstance(payload, dict) else []
    rows = [e for e in events if isinstance(e, dict)]
    return {
        "contract": "zab-request-log-summary",
        "contract_version": "1.0",
        "since": since,
        "source": payload.get("source"),
        "total": len(rows),
        "by_surface": _counter(rows, ("surface",)),
        "by_component": _counter(rows, ("component",)),
        "by_level": _counter(rows, ("level",)),
        "by_status": _counter(rows, ("result", "status")),
        "by_actor": _counter(rows, ("actor", "id")),
        "by_org": _counter(rows, ("scope", "org")),
        "by_project": _counter(rows, ("scope", "project_id")),
        "top_requests": _counter(rows, ("request", "name")),
        "errors": [
            e for e in rows
            if str(_nested(e, ("level",)) or "").upper() in {"ERROR", "CRITICAL"}
            or str(_nested(e, ("result", "status")) or "").lower() in {"error", "fail", "failed"}
        ][:20],
    }


def log_cli_start() -> tuple[str, float]:
    return uuid.uuid4().hex, time.monotonic()


def log_cli_end(request_id: str, started: float, *, exit_code: int | None = 0, error: BaseException | None = None) -> None:
    args = list(sys.argv[1:])
    command = " ".join(["zab", *args]) if args else "zab"
    duration = round((time.monotonic() - started) * 1000)
    status = "ok" if not error and (exit_code in (None, 0)) else "error"
    result: dict[str, Any] = {"status": status, "duration_ms": duration, "exit_code": exit_code}
    level = "INFO"
    if error is not None:
        result["error_type"] = type(error).__name__
        result["error_message"] = str(error)[:MAX_STRING]
        level = "ERROR"
    record_event(
        surface="cli",
        component="cli",
        level=level,
        request_id=request_id,
        actor=actor_context(surface="cli", source="direct"),
        scope=resolve_scope(args={"args": args, "cwd": str(Path.cwd())}),
        request={
            "name": args[0] if args else "root",
            "command": command,
            "args_redacted": redacted_args(args),
            "input_hash": input_hash(args),
        },
        result=result,
    )


def _append_event_files(event: dict[str, Any]) -> None:
    _append_jsonl("requests", event)
    surface = str(event.get("surface") or "").lower()
    if surface in ("cli", "api", "mcp", "jobs"):
        _append_jsonl(surface, event)
    level = str(event.get("level") or "").upper()
    status = str(_nested(event, ("result", "status")) or "").lower()
    if level in {"ERROR", "CRITICAL"} or status in {"error", "fail", "failed"}:
        _append_jsonl("errors", event)


def _append_jsonl(name: str, payload: dict[str, Any]) -> None:
    try:
        p = log_path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        _rotate_if_needed(p)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(_json_safe(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    except Exception:
        # Logging must never break the observed request.
        return


def _rotate_if_needed(path: Path) -> None:
    try:
        if not path.exists() or path.stat().st_size < max_bytes():
            return
        keep = backup_count()
        if keep <= 0:
            path.unlink(missing_ok=True)
            return
        for i in range(keep - 1, 0, -1):
            src = path.with_name(f"{path.name}.{i}")
            dst = path.with_name(f"{path.name}.{i + 1}")
            if src.exists():
                if i + 1 > keep:
                    src.unlink(missing_ok=True)
                else:
                    os.replace(src, dst)
        os.replace(path, path.with_name(f"{path.name}.1"))
    except OSError:
        return


def _index_event_best_effort(event: dict[str, Any]) -> None:
    try:
        from zab.services import postgres_store

        postgres_store.save_request_event(event)
    except Exception as exc:
        _append_jsonl(
            "errors",
            {
                "event_id": uuid.uuid4().hex,
                "ts": now_utc(),
                "level": "WARNING",
                "component": "logs.index",
                "surface": "logs",
                "request_id": event.get("request_id"),
                "parent_request_id": event.get("event_id"),
                "actor": {"kind": "system", "id": "zab", "client": None, "source": "request_logs", "pid": os.getpid(), "cwd": str(Path.cwd())},
                "request": {"name": "index_event", "input_hash": stable_hash(event)},
                "scope": event.get("scope") or {},
                "result": {"status": "error", "error_type": type(exc).__name__, "error_message": str(exc)[:MAX_STRING]},
            },
        )


def _query_index_best_effort(filters: dict[str, Any], *, limit: int) -> list[dict[str, Any]] | None:
    try:
        from zab.services import postgres_store

        return postgres_store.query_request_events(filters, limit=limit)
    except Exception:
        return None


def _query_files(filters: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for raw in reversed(_tail_lines(log_path("requests"), max(1000, limit * 5))):
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and _event_matches(event, filters):
            events.append(event)
            if len(events) >= limit:
                break
    return events


def _event_matches(event: dict[str, Any], filters: dict[str, Any]) -> bool:
    cutoff = _since_cutoff(filters.get("since"))
    if cutoff:
        ts = _parse_ts(str(event.get("ts") or ""))
        if ts and ts < cutoff:
            return False
    level_filter = filters.get("level")
    if level_filter:
        if LEVELS.get(str(event.get("level") or "INFO").upper(), 20) < LEVELS.get(str(level_filter).upper(), 20):
            return False
    checks = [
        ("surface", ("surface",)),
        ("component", ("component",)),
        ("actor", ("actor", "id")),
        ("org", ("scope", "org")),
        ("project", ("scope", "project_id")),
        ("status", ("result", "status")),
    ]
    for key, path in checks:
        wanted = filters.get(key)
        if wanted and str(wanted).lower() not in str(_nested(event, path) or "").lower():
            return False
    q = str(filters.get("q") or "").strip().lower()
    if q:
        haystack = json.dumps(event, ensure_ascii=False, sort_keys=True).lower()
        if q not in haystack:
            return False
    return True


def _tail_lines(path: Path, limit: int) -> list[str]:
    if not path.is_file():
        return []
    capped = max(1, min(5000, int(limit)))
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        return []
    return [line.rstrip("\n") for line in lines[-capped:]]


def _filters_dict(**kwargs: Any) -> dict[str, Any]:
    return {k: v for k, v in kwargs.items() if v not in (None, "", [])}


def _counter(rows: list[dict[str, Any]], path: tuple[str, ...]) -> list[dict[str, Any]]:
    c: Counter[str] = Counter()
    for row in rows:
        value = _nested(row, path)
        if value in (None, ""):
            value = "unknown"
        c[str(value)] += 1
    return [{"id": key, "count": count} for key, count in c.most_common(20)]


def _nested(value: Any, path: tuple[str, ...]) -> Any:
    cur = value
    for part in path:
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _file_key(raw: str) -> str:
    key = (raw or "requests").strip().lower().replace(".jsonl", "")
    return key if key in LOG_FILES else "requests"


def _norm_level(level: str) -> str:
    upper = str(level or "INFO").upper()
    return upper if upper in LEVELS else "INFO"


def _is_secret_key(key: str) -> bool:
    lk = key.lower()
    return any(part in lk for part in SECRET_KEY_PARTS)


def _looks_like_secret(value: str) -> bool:
    lowered = value.lower()
    if "bearer " in lowered:
        return True
    if value.startswith(("sk-", "sk_live_", "sk_test_", "xoxb-", "ghp_", "glpat-")):
        return True
    return False


def _looks_like_dashboard(headers: dict[str, str]) -> bool:
    referer = headers.get("referer", "")
    client = headers.get("x-zab-client", "")
    return "dashboard" in client.lower() or (bool(referer) and "/api/" not in referer and bool(headers.get("user-agent")))


def _logging_config() -> dict[str, Any]:
    try:
        raw = load_user_config().get("logging")
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


def _scope_fields_from_args(args: Any) -> tuple[str | None, str | Path | None, str | None]:
    if not isinstance(args, dict):
        return None, None, None
    project = args.get("project")
    project_path = args.get("project_path") or args.get("local_project_path")
    source_id = args.get("source_id")
    nested = args.get("args")
    if isinstance(nested, dict):
        nested_project, nested_path, nested_source = _scope_fields_from_args(nested)
        project = project or nested_project
        project_path = project_path or nested_path
        source_id = source_id or nested_source
    return (
        str(project) if project else None,
        project_path if project_path else None,
        str(source_id) if source_id else None,
    )


def _project_rows() -> list[dict[str, Any]]:
    """Projets pour la résolution de scope.

    Lecture priorisée depuis l'index Postgres/état (section ``projects``, ~15 ms)
    plutôt qu'un scan filesystem live (~4 s). Repli sur le scan uniquement si
    l'index est vide (jamais synchronisé).
    """
    try:
        from zab.services import postgres_store

        rows = postgres_store.list_state_section("projects")
        indexed = [x for x in rows if isinstance(x, dict)]
        if indexed:
            return indexed
    except Exception:
        pass
    try:
        from zab.services.workspace_projects import discover_projects

        return [x for x in discover_projects() if isinstance(x, dict)]
    except Exception:
        return []


def _resolve_project_by_path(raw_path: str | Path, projects: list[dict[str, Any]]) -> dict[str, Any] | None:
    try:
        candidate = Path(str(raw_path)).expanduser().resolve()
    except OSError:
        return None
    for project in projects:
        raw = project.get("path")
        if not raw:
            continue
        try:
            p = Path(str(raw)).expanduser().resolve()
        except OSError:
            continue
        if candidate == p or _is_relative_to(candidate, p):
            return _scope_from_project(project)
    return None


def _resolve_project_by_alias(alias: str, projects: list[dict[str, Any]]) -> dict[str, Any] | None:
    needle = alias.strip().lower()
    for project in projects:
        aliases = {str(project.get("id") or ""), str(project.get("name") or ""), str(project.get("path") or "")}
        aliases.update(str(x) for x in project.get("aliases") or [])
        if needle in {a.lower() for a in aliases if a}:
            return _scope_from_project(project)
    return None


def _resolve_task_source(source_id: str, projects: list[dict[str, Any]]) -> dict[str, Any] | None:
    try:
        sources = load_user_config().get("task_sources")
    except Exception:
        sources = None
    if not isinstance(sources, list):
        return None
    for src in sources:
        if not isinstance(src, dict):
            continue
        sid = str(src.get("id") or src.get("label") or "")
        if sid != source_id:
            continue
        local_path = src.get("local_project_path")
        project = src.get("project") or src.get("label")
        scope = _resolve_project_by_path(local_path, projects) if local_path else None
        if scope is None and project:
            scope = _resolve_project_by_alias(str(project), projects)
        if scope is None:
            scope = {
                "org": src.get("org"),
                "project_id": str(project or source_id),
                "project_path": str(local_path) if local_path else None,
            }
        scope["task_source_id"] = source_id
        scope["resolution"] = "task_source"
        return scope
    return None


def _scope_from_project(project: dict[str, Any]) -> dict[str, Any]:
    return {
        "org": project.get("org"),
        "project_id": project.get("id") or project.get("name"),
        "project_path": project.get("path"),
        "task_source_id": None,
        "resolution": "project",
    }


def _is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _since_cutoff(raw: Any) -> datetime | None:
    if raw in (None, ""):
        return None
    text = str(raw).strip().lower()
    if text.endswith(("s", "m", "h", "d")) and text[:-1].isdigit():
        value = int(text[:-1])
        unit = text[-1]
        delta = {
            "s": timedelta(seconds=value),
            "m": timedelta(minutes=value),
            "h": timedelta(hours=value),
            "d": timedelta(days=value),
        }[unit]
        return datetime.now(timezone.utc) - delta
    return _parse_ts(text)


def _parse_ts(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
