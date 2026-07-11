"""Agrégation légère des tâches (GitLab, Linear, Notion) pour GET /api/tasks/inbox."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from dotenv import dotenv_values

from zab.paths import data_dir
from zab.services.env_token_locate import candidate_env_files_for_task_source, fallbacks_for_backend
from zab.services import postgres_store as local_db
from zab.services.pm_env_sync import PM_SCAN_KEYS, apply_pm_tokens_from_user_dotenv
from zab.user_config import task_sources_from_user_config

_TIMEOUT = 12.0
_PER_PAGE = 100

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


def _token_from_env_file(path: Path, key: str) -> str | None:
    """Lit une clé dans un .env sans jamais exposer la valeur dans les sorties."""
    if not path.is_file():
        return None
    try:
        vals = dotenv_values(path)
    except OSError:
        return None
    value = vals.get(key)
    if value is None or not str(value).strip():
        return None
    return str(value).strip()


def _token_for_with_fallbacks(
    env_name: str,
    fallbacks: list[str],
    *,
    local_project_path: str | None = None,
) -> str | None:
    """Récupère un token depuis le processus puis les .env candidats.

    Priorité : variable primaire, puis fallbacks backend. Pour chaque clé,
    essayer d'abord l'environnement du processus, puis les .env sûrs associés
    à la source (`local_project_path/.env`, ~/.config/zab/.env, ~/.env, etc.).
    """
    files = candidate_env_files_for_task_source(local_project_path=local_project_path)
    for name in [env_name] + fallbacks:
        tok = _token_for(name)
        if tok:
            return tok
        for path in files:
            tok = _token_from_env_file(path, name)
            if tok:
                return tok
    return None


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
                "source_label": "GitLab",
            }
        )
    return out


def _linear_authorization_value(raw: str) -> str:
    """Linear attend la clé API telle quelle dans Authorization, sans préfixe ``Bearer``."""
    t = (raw or "").strip()
    if t.lower().startswith("bearer "):
        return t[7:].strip()
    return t


def _fetch_linear(token: str, team_keys: list[str], project_id: str | None = None) -> list[dict[str, Any]]:
    if project_id:
        query = """
        query ProjectIssues($id: String!, $first: Int!) {
          project(id: $id) {
            id
            name
            issues(first: $first, filter: { state: { type: { neq: "completed" } } }) {
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
        payload = {"query": query, "variables": {"id": project_id, "first": max(_PER_PAGE, 40)}}
    else:
        query = """
        query AssignedIssues($first: Int!) {
          viewer {
            assignedIssues(first: $first) {
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
        
    headers = {"Authorization": _linear_authorization_value(token), "Content-Type": "application/json"}
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

    if project_id:
        project_data = data.get("project")
        if not isinstance(project_data, dict):
            return []
        nodes = project_data.get("issues", {}).get("nodes")
    else:
        viewer = data.get("viewer")
        if not isinstance(viewer, dict):
            return []
        issues_block = viewer.get("assignedIssues")
        if not isinstance(issues_block, dict):
            return []
        nodes = issues_block.get("nodes")

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
        if team_set is not None and tk.upper() not in team_set and not project_id:
            continue
        st = node.get("state")
        st_type = ""
        st_name = ""
        if isinstance(st, dict):
            st_type = str(st.get("type") or "")
            st_name = str(st.get("name") or "")
        if st_type in ("completed", "canceled"):
            continue
        out.append(
            {
                "identifier": str(node.get("identifier") or ""),
                "title": str(node.get("title") or "(sans titre)"),
                "url": str(node.get("url") or ""),
                "state": st_name,
                "updated_at": str(node.get("updatedAt") or ""),
                "source_label": "Linear",
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
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            # Include Notion API error body for debugging
            detail = ""
            try:
                err_body = r.json()
                detail = f" — {json.dumps(err_body, ensure_ascii=False)[:300]}"
            except Exception:
                pass
            raise httpx.HTTPStatusError(
                f"Notion API: HTTP {r.status_code}{detail}",
                request=e.request,
                response=e.response,
            ) from None
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
            tp = None
            for k, v in props.items():
                if isinstance(v, dict) and v.get("type") == "title":
                    tp = v
                    break
            if tp is None:
                tp = props.get(title_prop) or props.get("Name") or props.get("title")
            title = _notion_plain_title(tp)
        url_page = page.get("url")
        if not url_page and pid:
            url_page = f"https://www.notion.so/{str(pid).replace('-', '')}"
        last_edited = page.get("last_edited_time") or ""
        pid_str = str(pid or "")
        display_id = f"{pid_str[:8]}…{pid_str[-6:]}" if pid_str and len(pid_str) > 18 else pid_str
        out.append(
            {
                "identifier": pid_str,
                "display_identifier": display_id,
                "title": title,
                "url": str(url_page or ""),
                "state": "",
                "updated_at": str(last_edited),
                "source_label": "Notion",
            }
        )
    return out


def _fetch_github(token: str, repos: list[str]) -> list[dict[str, Any]]:
    """Récupère les issues assignées de repos GitHub."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    out: list[dict[str, Any]] = []
    with httpx.Client(timeout=_TIMEOUT) as client:
        # Issues assignées à l'utilisateur
        r = client.get(
            "https://api.github.com/issues?filter=assigned&state=open&per_page=20&sort=updated&direction=desc",
            headers=headers,
        )
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            return []
        for row in data:
            if not isinstance(row, dict):
                continue
            repo = row.get("repository", {})
            repo_name = repo.get("full_name", "")
            if repos and repo_name not in repos:
                continue
            issue_num = row.get("number")
            title = row.get("title")
            web = row.get("html_url")
            state = row.get("state")
            updated = row.get("updated_at")
            out.append({
                "identifier": f"{repo_name}#{issue_num}" if repo_name else f"#{issue_num}",
                "title": str(title or "(sans titre)"),
                "url": str(web or ""),
                "state": str(state or ""),
                "updated_at": str(updated or ""),
                "source_label": "GitHub",
            })
            if len(out) >= _PER_PAGE:
                break
    return out


def _resolve_token_for_entry(entry: dict[str, Any]) -> tuple[str | None, list[str]]:
    """Retourne (token, fallbacks_essayés) pour une entrée task_sources."""
    backend = entry["backend"]
    env_name = str(entry["env_token"])
    fallbacks = fallbacks_for_backend(backend)
    return _token_for_with_fallbacks(
        env_name,
        fallbacks,
        local_project_path=entry.get("local_project_path"),
    ), fallbacks


def _build_source_meta(entry: dict[str, Any]) -> dict[str, Any]:
    """Métadonnées de base d'une source (sans status / items)."""
    return {
        "id": entry["id"],
        "label": entry["label"],
        "backend": entry["backend"],
        "routing_doc": entry.get("routing_doc"),
        "routing_doc_abs": _resolve_path_display(entry.get("routing_doc")),
        "mcp_hint": entry.get("mcp_hint"),
        "local_project_path": entry.get("local_project_path"),
        "local_project_path_abs": _resolve_path_display(entry.get("local_project_path")),
        "url": entry.get("url"),
        "env_token": str(entry["env_token"]),
        "items": [],
        "status": "skipped",
        "reason": None,
    }


def _fetch_items_for_entry(entry: dict[str, Any], token: str) -> list[dict[str, Any]]:
    """Délègue au fetcher backend approprié pour une entrée donnée."""
    backend = entry["backend"]
    if backend == "gitlab":
        host = str(entry.get("host") or "gitlab.com")
        ref = _gitlab_project_ref(entry)
        return _fetch_gitlab(host, ref, token, entry.get("assignee_username"))
    if backend == "linear":
        project_id = None
        url_val = entry.get("url")
        if isinstance(url_val, str) and "linear.app" in url_val:
            import re

            m = re.search(r"/project/([^/]+)", url_val)
            if m:
                project_id = m.group(1)
        return _fetch_linear(token, list(entry.get("team_keys") or []), project_id=project_id)
    if backend == "github":
        return _fetch_github(token, list(entry.get("repos") or []))
    return _fetch_notion(
        str(entry["database_id"]),
        token,
        str(entry.get("notion_title_prop") or "Name"),
    )


def _run_source_check(entry: dict[str, Any]) -> dict[str, Any]:
    """Exécute une vérification de connectivité pour une seule source.

    Retourne le bloc enrichi (status, reason, items) — utilisable pour rebrancher
    une ligne dans le cache existant.
    """
    meta = _build_source_meta(entry)
    token, _fallbacks = _resolve_token_for_entry(entry)
    if not token:
        meta["reason"] = f"variable {meta['env_token']} absente ou vide"
        return meta
    try:
        items = _fetch_items_for_entry(entry, token)
        meta["items"] = items
        meta["status"] = "ok"
    except httpx.HTTPStatusError as e:
        meta["status"] = "error"
        meta["reason"] = f"HTTP {e.response.status_code}"
    except (httpx.RequestError, RuntimeError, OSError, ValueError, TypeError) as e:
        meta["status"] = "error"
        meta["reason"] = str(e)[:200]
    return meta


def check_single_source(source_id: str) -> dict[str, Any]:
    """Vérifie une seule source (par id) sans toucher au cache complet.

    Met à jour le bloc correspondant dans ``tasks_cache.json`` si présent, pour
    que l'inbox reflète immédiatement le résultat sans re-synchroniser tout.

    Lève ``KeyError`` si l'id n'existe pas dans ``task_sources``.
    """
    apply_pm_tokens_from_user_dotenv()
    sources_cfg, _parse_errors = task_sources_from_user_config()
    entry = next((s for s in sources_cfg if s["id"] == source_id), None)
    if entry is None:
        raise KeyError(source_id)

    meta = _run_source_check(entry)
    meta["checked_at_utc"] = _iso_now()
    meta["token_present"] = bool(_resolve_token_for_entry(entry)[0])

    cache_path = data_dir() / "tasks_cache.json"
    if cache_path.exists():
        try:
            with cache_path.open("r", encoding="utf-8") as f:
                cached = json.load(f)
        except (OSError, json.JSONDecodeError):
            cached = None
        if isinstance(cached, dict):
            blocks = cached.get("sources")
            if isinstance(blocks, list):
                replaced = False
                for i, b in enumerate(blocks):
                    if isinstance(b, dict) and b.get("id") == source_id:
                        blocks[i] = {**b, **{k: v for k, v in meta.items() if k != "checked_at_utc"}}
                        replaced = True
                        break
                if replaced:
                    try:
                        with cache_path.open("w", encoding="utf-8") as f:
                            json.dump(cached, f, ensure_ascii=False, indent=2)
                    except OSError:
                        pass

    return meta


def sync_tasks_inbox() -> dict[str, Any]:
    apply_pm_tokens_from_user_dotenv()
    sources_cfg, parse_errors = task_sources_from_user_config()
    hint_names: set[str] = set(PM_SCAN_KEYS)
    for entry in sources_cfg:
        et = entry.get("env_token")
        if et:
            hint_names.add(str(et))
    env_hints = {n: bool(_token_for(n)) for n in sorted(hint_names)}
    for entry in sources_cfg:
        et = entry.get("env_token")
        if et:
            env_hints[str(et)] = bool(_resolve_token_for_entry(entry)[0])

    blocks: list[dict[str, Any]] = []
    all_items: list[dict[str, Any]] = []

    for entry in sources_cfg:
        meta = _run_source_check(entry)
        if meta["status"] == "ok":
            all_items.extend(meta["items"])
        blocks.append(meta)

    # Trier toutes les tâches par date de mise à jour décroissante
    def _sort_key(item: dict[str, Any]) -> str:
        return item.get("updated_at") or ""

    all_items_sorted = sorted(all_items, key=_sort_key, reverse=True)

    result = {
        "generated_at_utc": _iso_now(),
        "parse_errors": parse_errors,
        "env_hints": env_hints,
        "sources": blocks,
        "all_tasks": all_items_sorted,
        "total_count": len(all_items_sorted),
    }

    cache_path = data_dir() / "tasks_cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with cache_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    local_db.replace_tasks_cache(result)

    return result

def fetch_tasks_inbox() -> dict[str, Any]:
    cached_db = local_db.load_tasks_cache()
    if cached_db is not None:
        return cached_db
    cache_path = data_dir() / "tasks_cache.json"
    if cache_path.exists():
        try:
            with cache_path.open("r", encoding="utf-8") as f:
                cached = json.load(f)
            if isinstance(cached, dict):
                local_db.replace_tasks_cache(cached)
                return cached
        except Exception:
            pass
    return sync_tasks_inbox()
