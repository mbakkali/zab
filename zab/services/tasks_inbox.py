"""Agrégation légère des tâches (GitLab, Linear, Notion) pour GET /api/tasks/inbox."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from zab.services.pm_env_sync import PM_KEYS, apply_pm_tokens_from_user_dotenv
from zab.user_config import task_sources_from_user_config

_TIMEOUT = 12.0
_PER_PAGE = 20

_NOTION_VERSION = "2022-06-28"


def _resolve_path_display(s: str | None) -> str | None:
    if not s or not isinstance(s, str) or not s.strip():
        return None
    try:
        return str(Path(s.strip()).expanduser().resolve())
    except OSError:
        return s.strip()


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _token_for(env_name: str) -> str | None:
    v = os.environ.get(env_name)
    if v is None or not str(v).strip():
        return None
    return str(v).strip()


def _gitlab_project_ref(entry: dict[str, Any]) -> str:
    pwn = entry.get("path_with_namespace")
    if isinstance(pwn, str) and pwn.strip():
        return quote(pwn.strip(), safe="")
    pid = entry.get("project_id")
    if pid is not None:
        return str(pid).strip()
    return ""


def _fetch_gitlab(host: str, project_ref: str, token: str, assignee_username: str | None) -> list[dict[str, Any]]:
    base = f"https://{host.rstrip('/')}/api/v4/projects/{project_ref}/issues"
    params: dict[str, str | int] = {
        "state": "opened",
        "per_page": _PER_PAGE,
        "order_by": "updated_at",
        "sort": "desc",
    }
    if assignee_username:
        params["assignee_username"] = assignee_username
    headers = {"PRIVATE-TOKEN": token}
    with httpx.Client(timeout=_TIMEOUT) as client:
        r = client.get(base, params=params, headers=headers)
        r.raise_for_status()
        data = r.json()
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        iid = row.get("iid")
        title = row.get("title")
        web = row.get("web_url")
        state = row.get("state")
        updated = row.get("updated_at")
        out.append(
            {
                "identifier": f"#{iid}" if iid is not None else "?",
                "title": str(title or "(sans titre)"),
                "url": str(web or ""),
                "state": str(state or ""),
                "updated_at": str(updated or ""),
            }
        )
    return out


def _fetch_linear(token: str, team_keys: list[str]) -> list[dict[str, Any]]:
    query = """
    query AssignedIssues($first: Int!) {
      viewer {
        issues(first: $first, filter: { assignee: { isMe: { eq: true } } }) {
          nodes {
            identifier
            title
            url
            updatedAt
            state { name type }
            team { key }
          }
        }
      }
    }
    """
    payload = {"query": query, "variables": {"first": max(_PER_PAGE, 40)}}
    headers = {"Authorization": token, "Content-Type": "application/json"}
    with httpx.Client(timeout=_TIMEOUT) as client:
        r = client.post("https://api.linear.app/graphql", json=payload, headers=headers)
        r.raise_for_status()
        body = r.json()
    if not isinstance(body, dict):
        return []
    errs = body.get("errors")
    if isinstance(errs, list) and errs:
        msg = errs[0].get("message") if isinstance(errs[0], dict) else str(errs[0])
        raise RuntimeError(msg or "Linear GraphQL error")
    data = body.get("data")
    if not isinstance(data, dict):
        return []
    viewer = data.get("viewer")
    if not isinstance(viewer, dict):
        return []
    issues = viewer.get("issues")
    if not isinstance(issues, dict):
        return []
    nodes = issues.get("nodes")
    if not isinstance(nodes, list):
        return []
    team_set = {k.upper() for k in team_keys} if team_keys else None
    out: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        team = node.get("team")
        tk = ""
        if isinstance(team, dict):
            tk = str(team.get("key") or "")
        if team_set is not None and tk.upper() not in team_set:
            continue
        st = node.get("state")
        st_type = ""
        st_name = ""
        if isinstance(st, dict):
            st_type = str(st.get("type") or "")
            st_name = str(st.get("name") or st_type or "")
        if st_type.lower() in ("completed", "canceled"):
            continue
        out.append(
            {
                "identifier": str(node.get("identifier") or ""),
                "title": str(node.get("title") or "(sans titre)"),
                "url": str(node.get("url") or ""),
                "state": st_name,
                "updated_at": str(node.get("updatedAt") or ""),
            }
        )
        if len(out) >= _PER_PAGE:
            break
    return out


def _notion_plain_title(prop_val: Any) -> str:
    if not isinstance(prop_val, dict):
        return ""
    if "title" in prop_val:
        parts = prop_val.get("title")
        if isinstance(parts, list):
            texts: list[str] = []
            for p in parts:
                if isinstance(p, dict) and p.get("plain_text"):
                    texts.append(str(p["plain_text"]))
            return "".join(texts) if texts else "(sans titre)"
    return "(sans titre)"


def _fetch_notion(database_id: str, token: str, title_prop: str) -> list[dict[str, Any]]:
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": _NOTION_VERSION,
        "Content-Type": "application/json",
    }
    body: dict[str, Any] = {
        "page_size": _PER_PAGE,
        "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}],
    }
    with httpx.Client(timeout=_TIMEOUT) as client:
        r = client.post(url, json=body, headers=headers)
        r.raise_for_status()
        data = r.json()
    if not isinstance(data, dict):
        return []
    results = data.get("results")
    if not isinstance(results, list):
        return []
    out: list[dict[str, Any]] = []
    for page in results:
        if not isinstance(page, dict):
            continue
        pid = page.get("id")
        props = page.get("properties")
        title = "(sans titre)"
        if isinstance(props, dict):
            tp = props.get(title_prop) or props.get("Name") or props.get("title")
            title = _notion_plain_title(tp)
        url_page = page.get("url")
        if not url_page and pid:
            url_page = f"https://www.notion.so/{str(pid).replace('-', '')}"
        last_edited = page.get("last_edited_time") or ""
        out.append(
            {
                "identifier": str(pid or "")[:12] + "…" if pid and len(str(pid)) > 12 else str(pid or ""),
                "title": title,
                "url": str(url_page or ""),
                "state": "",
                "updated_at": str(last_edited),
            }
        )
    return out


def fetch_tasks_inbox() -> dict[str, Any]:
    apply_pm_tokens_from_user_dotenv()
    sources_cfg, parse_errors = task_sources_from_user_config()
    env_hints = {n: bool(_token_for(n)) for n in PM_KEYS}

    blocks: list[dict[str, Any]] = []
    for entry in sources_cfg:
        sid = entry["id"]
        label = entry["label"]
        backend = entry["backend"]
        env_name = str(entry["env_token"])
        token = _token_for(env_name)

        base_meta: dict[str, Any] = {
            "id": sid,
            "label": label,
            "backend": backend,
            "routing_doc": entry.get("routing_doc"),
            "routing_doc_abs": _resolve_path_display(entry.get("routing_doc")),
            "mcp_hint": entry.get("mcp_hint"),
            "local_project_path": entry.get("local_project_path"),
            "local_project_path_abs": _resolve_path_display(entry.get("local_project_path")),
            "env_token": env_name,
            "items": [],
            "status": "skipped",
            "reason": None,
        }

        if not token:
            base_meta["reason"] = f"variable {env_name} absente ou vide"
            blocks.append(base_meta)
            continue

        try:
            if backend == "gitlab":
                host = str(entry.get("host") or "gitlab.com")
                ref = _gitlab_project_ref(entry)
                items = _fetch_gitlab(
                    host,
                    ref,
                    token,
                    entry.get("assignee_username"),
                )
            elif backend == "linear":
                items = _fetch_linear(token, list(entry.get("team_keys") or []))
            else:
                items = _fetch_notion(
                    str(entry["database_id"]),
                    token,
                    str(entry.get("notion_title_prop") or "Name"),
                )
            base_meta["items"] = items
            base_meta["status"] = "ok"
        except httpx.HTTPStatusError as e:
            base_meta["status"] = "error"
            base_meta["reason"] = f"HTTP {e.response.status_code}"
        except (httpx.RequestError, RuntimeError, OSError, ValueError, TypeError) as e:
            base_meta["status"] = "error"
            base_meta["reason"] = str(e)[:200]

        blocks.append(base_meta)

    return {
        "generated_at_utc": _iso_now(),
        "parse_errors": parse_errors,
        "env_hints": env_hints,
        "sources": blocks,
    }
