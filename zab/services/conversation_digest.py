"""Digest leger des conversations agents locales."""

from __future__ import annotations

import re
import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date as date_cls, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from zab.services.agent_memory_import import (
    AgentMemoryDocument,
    collect_agent_memory_documents,
)
from zab.services.conversation_ledger.intent_signals import AUTOMATED, BOILERPLATE, classify_intent
from zab.services.workspace_projects import discover_projects
from zab.user_config import organization_slug_set_from_user_config

MAX_INTENT_CHARS = 260
RECENT_CLOCK_SKEW = timedelta(minutes=5)
# Marge appliquée au filtre par date de modification des fichiers. Un transcript peut
# porter un horodatage interne postérieur à son mtime (horloge décalée, écriture
# différée) : on n'écarte sans le lire qu'un fichier plus vieux que la fenêtre de
# cette marge, ce qui garde le filtre invisible pour le résultat.
STALE_FILE_MARGIN = timedelta(days=2)


@dataclass(frozen=True)
class ConversationDigestItem:
    conversation_id: str
    agent_tool: str
    provider: str
    source: str
    wing: str
    path: str
    updated_at: str
    intent: str
    org: str | None
    project: str | None
    project_path: str | None
    match_reason: str | None
    user_message_count: int


def build_conversation_digest(
    *,
    days: int = 1,
    since: datetime | None = None,
    until: datetime | None = None,
    providers: frozenset[str] | None = None,
    now: datetime | None = None,
    limit: int = 80,
    batch_size: int = 10,
    include_subagents: bool = False,
    documents: Iterable[AgentMemoryDocument] | None = None,
    projects: list[dict[str, Any]] | None = None,
    cwd: str | None = None,
) -> dict[str, Any]:
    """Construit un digest local sans ecrire dans Postgres.

    `cwd`, si fourni, restreint le digest aux conversations dont le chemin du
    transcript ou l'identifiant de session (`wing`) porte le repertoire de
    travail donne. L'attribution `org`/`project` est semantique (alias, slug,
    contenu) et peut donc etiqueter une session lancee dans un sous-dossier
    avec le nom d'un projet different ; ce filtre repond a "quelles sessions
    ont vraiment tourne dans ce dossier", independamment de cette attribution.
    """

    now_utc = _ensure_aware(now or datetime.now(timezone.utc))
    window_since = _ensure_aware(since) if since is not None else now_utc - timedelta(days=max(1, int(days)))
    window_until = _ensure_aware(until) if until is not None else now_utc
    upper_bound = window_until if until is not None else window_until + RECENT_CLOCK_SKEW
    if window_until <= window_since:
        raise ValueError("until doit etre posterieur a since")
    lim = max(1, min(int(limit), 300))
    batch_n = max(1, min(int(batch_size), 50))
    collect_stats: dict[str, int] = {}
    if documents is not None:
        docs = list(documents)
    else:
        docs = collect_agent_memory_documents(
            providers=providers,
            modified_since=window_since - STALE_FILE_MARGIN,
            stats=collect_stats,
        )
    skipped_stale = int(collect_stats.get("skipped_stale", 0))
    project_rows = projects if projects is not None else discover_projects()
    cwd_norm = _normalize_match_text(cwd) if cwd and cwd.strip() else None

    items: list[ConversationDigestItem] = []
    scanned_conversations = 0
    skipped_subagents = 0
    provider_seen: Counter[str] = Counter()
    provider_retained: Counter[str] = Counter()

    for doc in docs:
        if doc.room != "conversation":
            continue
        scanned_conversations += 1
        provider = _provider(doc)
        provider_seen[provider] += 1
        if not include_subagents and _is_subagent(doc):
            skipped_subagents += 1
            continue
        updated_at = _document_updated_at(doc)
        if updated_at is None:
            continue
        if updated_at < window_since or updated_at >= upper_bound:
            continue
        user_messages = _useful_user_messages(doc)
        if not user_messages:
            continue
        intent = _intent_from_messages(user_messages)
        if not intent:
            continue
        if cwd_norm and cwd_norm not in _project_path_match_text(doc):
            continue
        match = _match_project(doc, intent, project_rows)
        provider_retained[provider] += 1
        items.append(
            ConversationDigestItem(
                conversation_id=_conversation_id(doc),
                agent_tool=_agent_tool(provider),
                provider=provider,
                source=doc.source,
                wing=doc.wing,
                path=str(doc.path),
                updated_at=updated_at.isoformat(),
                intent=intent,
                org=match.get("org"),
                project=match.get("project"),
                project_path=match.get("path"),
                match_reason=match.get("reason"),
                user_message_count=len(user_messages),
            )
        )

    items.sort(key=lambda item: item.updated_at, reverse=True)
    limited = items[:lim]

    org_counts: Counter[str] = Counter(item.org or "non-rattache" for item in limited)
    project_counts: Counter[str] = Counter(_project_key(item) for item in limited)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in limited:
        grouped[_project_key(item)].append(_item_dict(item))

    batches = [
        {
            "index": i // batch_n + 1,
            "count": len(limited[i : i + batch_n]),
            "conversation_ids": [item.conversation_id for item in limited[i : i + batch_n]],
        }
        for i in range(0, len(limited), batch_n)
    ]

    return {
        "generated_at": now_utc.isoformat(),
        "window": {
            "days": max(1, int(days)),
            "since": window_since.isoformat(),
            "until": window_until.isoformat(),
        },
        "cwd_filter": cwd.strip() if cwd and cwd.strip() else None,
        # `scanned` reste le total considéré, que le transcript ait été lu ou écarté
        # sur sa seule date de modification : les compteurs restent comparables d'une
        # version à l'autre, et le détail du raccourci est exposé séparément.
        "scanned_conversations": scanned_conversations + skipped_stale,
        "parsed_conversations": scanned_conversations,
        "skipped_stale_conversations": skipped_stale,
        "retained_conversations": len(items),
        "shown_conversations": len(limited),
        "batch_size": batch_n,
        "batches": batches,
        "skipped_subagents": skipped_subagents,
        "provider_counts": dict(sorted(provider_seen.items())),
        "retained_provider_counts": dict(sorted(provider_retained.items())),
        "org_counts": dict(org_counts.most_common()),
        "project_counts": dict(project_counts.most_common()),
        "items": [_item_dict(item) for item in limited],
        "groups": dict(grouped),
    }


def build_conversation_digest_for_date(
    *,
    on: date_cls,
    timezone_name: str = "Europe/Paris",
    providers: frozenset[str] | None = None,
    limit: int = 80,
    batch_size: int = 10,
    include_subagents: bool = False,
    documents: Iterable[AgentMemoryDocument] | None = None,
    projects: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Construit un digest pour une journee locale precise."""

    try:
        tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"timezone inconnue : {timezone_name}") from exc
    start_local = datetime(on.year, on.month, on.day, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    payload = build_conversation_digest(
        since=start_local.astimezone(timezone.utc),
        until=end_local.astimezone(timezone.utc),
        providers=providers,
        now=now,
        limit=limit,
        batch_size=batch_size,
        include_subagents=include_subagents,
        documents=documents,
        projects=projects,
    )
    payload["target_date"] = on.isoformat()
    payload["timezone"] = timezone_name
    payload["window"]["local_since"] = start_local.isoformat()
    payload["window"]["local_until"] = end_local.isoformat()
    return payload


def format_conversation_digest_markdown(payload: dict[str, Any]) -> str:
    """Rendu Markdown volontairement court pour usage quotidien."""

    window = payload.get("window") or {}
    since = _human_dt(str(window.get("since") or ""))
    until = _human_dt(str(window.get("until") or ""))
    shown = int(payload.get("shown_conversations") or 0)
    retained = int(payload.get("retained_conversations") or 0)
    scanned = int(payload.get("scanned_conversations") or 0)
    providers = ", ".join(
        f"{name}:{count}" for name, count in (payload.get("retained_provider_counts") or {}).items()
    ) or "aucun"

    lines = [
        f"# Digest conversations ({since} -> {until})",
        "",
        f"{shown} conversation(s) affichee(s), {retained} retenue(s), {scanned} scannee(s). Providers: {providers}.",
    ]
    if int(payload.get("skipped_subagents") or 0):
        lines.append(f"Subagents ignores: {payload['skipped_subagents']}.")
    if payload.get("cwd_filter"):
        lines.append(f"Filtre repertoire de travail: `{payload['cwd_filter']}`.")
    lines.extend(["", "## Ce que tu as essaye de faire"])

    groups = payload.get("groups") or {}
    if not groups:
        lines.append("")
        lines.append("- Rien de net dans la fenetre.")
        return "\n".join(lines).rstrip() + "\n"

    def group_sort_key(pair: tuple[str, list[dict[str, Any]]]) -> tuple[int, str]:
        key, values = pair
        latest = values[0].get("updated_at") if values else ""
        return (-len(values), key if latest else key)

    for group_key, values in sorted(groups.items(), key=group_sort_key):
        lines.extend(["", f"### {group_key}"])
        for item in values:
            stamp = _human_dt(str(item.get("updated_at") or ""))
            provider = item.get("agent_tool") or item.get("provider") or "?"
            cid = item.get("conversation_id") or "?"
            intent = item.get("intent") or ""
            lines.append(f"- {stamp} · {provider} · `{cid}`: {intent}")
    return "\n".join(lines).rstrip() + "\n"


def _provider(doc: AgentMemoryDocument) -> str:
    raw = doc.metadata.get("conversation_provider")
    return str(raw or doc.source.replace("_transcript", "")).strip() or "unknown"


def _agent_tool(provider: str) -> str:
    return {
        "cursor": "Cursor",
        "claude": "Claude Code",
        "codex": "Codex",
        "hermes": "Hermes",
        "gemini": "Gemini CLI",
        "kimi": "Kimi",
    }.get(provider, provider or "unknown")


def _conversation_id(doc: AgentMemoryDocument) -> str:
    for key in (
        "conversation_id",
        "session_id",
        "thread_id",
        "hermes_session_id",
    ):
        val = doc.metadata.get(key)
        if isinstance(val, (str, int)) and str(val).strip():
            return str(val).strip()

    for event in doc.raw_events:
        val = _conversation_session_id_from_obj(event)
        if val:
            return val
        payload = event.get("payload")
        if isinstance(payload, dict):
            val = _conversation_session_id_from_obj(payload)
            if val:
                return val

    stem = doc.path.stem.strip()
    if stem and stem.lower() not in {"history", "conversation", "transcript"}:
        return stem
    for event in doc.raw_events:
        val = _conversation_event_id_from_obj(event)
        if val:
            return val
        payload = event.get("payload")
        if isinstance(payload, dict):
            val = _conversation_event_id_from_obj(payload)
            if val:
                return val
    raw = f"{_provider(doc)}|{doc.source}|{doc.path}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _conversation_session_id_from_obj(obj: dict[str, Any]) -> str | None:
    for key in (
        "conversation_id",
        "session_id",
        "thread_id",
        "sessionId",
        "conversationId",
        "threadId",
    ):
        val = obj.get(key)
        if isinstance(val, (str, int)) and str(val).strip():
            return str(val).strip()
    return None


def _conversation_event_id_from_obj(obj: dict[str, Any]) -> str | None:
    for key in (
        "id",
        "uuid",
    ):
        val = obj.get(key)
        if isinstance(val, (str, int)) and str(val).strip():
            return str(val).strip()
    return None


def _is_subagent(doc: AgentMemoryDocument) -> bool:
    path = str(doc.path)
    return bool(doc.metadata.get("subagent")) or "/subagents/" in path or doc.wing.endswith("__subagents")


def _document_updated_at(doc: AgentMemoryDocument) -> datetime | None:
    candidates: list[datetime] = []
    mtime = _path_mtime(doc.path)
    if mtime:
        candidates.append(mtime)
    for msg in doc.messages:
        ts = _parse_timestamp(msg.get("timestamp"))
        if ts:
            candidates.append(ts)
    for event in doc.raw_events:
        ts = _parse_timestamp(event.get("timestamp"))
        if ts:
            candidates.append(ts)
        payload = event.get("payload")
        if isinstance(payload, dict):
            ts = _parse_timestamp(payload.get("timestamp"))
            if ts:
                candidates.append(ts)
    return max(candidates) if candidates else None


def _path_mtime(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _ensure_aware(value)
    if isinstance(value, (int, float)):
        raw = float(value)
        if raw <= 0:
            return None
        if raw > 10_000_000_000:
            raw = raw / 1000
        try:
            return datetime.fromtimestamp(raw, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if re.fullmatch(r"\d+(\.\d+)?", text):
            try:
                return _parse_timestamp(float(text))
            except ValueError:
                return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            return _ensure_aware(datetime.fromisoformat(text))
        except ValueError:
            return None
    return None


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _useful_user_messages(doc: AgentMemoryDocument) -> list[str]:
    raw_messages = _codex_user_messages(doc) if _provider(doc) == "codex" else []
    raw_messages.extend(
        str(msg.get("content") or "")
        for msg in doc.messages
        if str(msg.get("role") or "").lower() == "user"
    )
    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_messages:
        clean = _clean_user_message(raw)
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out


def _codex_user_messages(doc: AgentMemoryDocument) -> list[str]:
    out: list[str] = []
    for event in doc.raw_events:
        typ = event.get("type")
        payload = event.get("payload")
        if typ == "event_msg" and isinstance(payload, dict) and payload.get("type") == "user_message":
            text = payload.get("message")
            if isinstance(text, str):
                out.append(text)
            continue
        if typ != "response_item" or not isinstance(payload, dict):
            continue
        if payload.get("type") != "message" or payload.get("role") != "user":
            continue
        text = _payload_content_text(payload)
        if text:
            out.append(text)
    return out


def _payload_content_text(payload: dict[str, Any]) -> str:
    content = payload.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for part in content:
        if isinstance(part, str):
            parts.append(part)
            continue
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(p for p in parts if p.strip())


def _clean_user_message(text: str) -> str:
    s = text.replace("\r\n", "\n").strip()
    if not s:
        return ""
    request_marker = "## My request for Codex:"
    if request_marker in s:
        s = s.split(request_marker, 1)[1].strip()
    low = s.lower()
    if low.startswith(
        (
            "<environment_context>",
            "<permissions instructions>",
            "<app-context>",
            "<collaboration_mode>",
            "<apps_instructions>",
            "<skills_instructions>",
            "<plugins_instructions>",
            "### session_meta",
            "[important:",
            "# agents.md instructions",
            "this session is being continued from a previous conversation",
        )
    ):
        return ""
    if "filesystem sandboxing defines" in low or "you are codex" in low:
        return ""
    s = re.sub(r"</?command-[^>]+>", " ", s)
    s = re.sub(r"</?[^>\s]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) < 4:
        return ""
    return _redact_sensitive_text(s)


def _redact_sensitive_text(text: str) -> str:
    s = re.sub(r"(?i)([?&](?:key|api_key|token|secret|danm_key)=)[^&\s}]+", r"\1[redacted]", text)
    s = re.sub(
        r"(?i)\b((?:api[_-]?key|token|secret|danm_key|key)\s*[:=]\s*)[\"']?[^,\s&}]+",
        r"\1[redacted]",
        s,
    )
    s = re.sub(r"\bdanm_mcp_[A-Za-z0-9_./-]{8,}", "[redacted-danm-mcp-key]", s)
    return s


def _intent_from_messages(messages: list[str]) -> str:
    """Première tournure vraiment humaine : certains outils CLI injectent un bloc
    d'amorce (plugins recommandés, contexte d'environnement) avant le premier mot
    de l'utilisateur, ce qui rendait `intent` identique sur des dizaines de
    conversations sans rapport. On saute ce bruit plutôt que de le citer."""
    for msg in messages:
        s = msg.strip()
        if not s:
            continue
        if classify_intent(s) in (AUTOMATED, BOILERPLATE):
            continue
        if len(s) > MAX_INTENT_CHARS:
            return s[: MAX_INTENT_CHARS - 1].rstrip() + "..."
        return s
    return ""


def _match_project(
    doc: AgentMemoryDocument,
    intent: str,
    projects: list[dict[str, Any]],
) -> dict[str, str | None]:
    if not projects:
        return {"org": None, "project": None, "path": None, "reason": None}

    path_text = _project_path_match_text(doc)
    intent_text = _normalize_match_text(intent)
    content_text = _normalize_match_text(" ".join([intent, doc.content[:4000]]))
    best: tuple[int, dict[str, Any], str] | None = None
    for project in projects:
        name = str(project.get("name") or "")
        parent = str(project.get("workspace_parent") or "")
        aliases = [str(a) for a in project.get("aliases") or [] if str(a).strip()]
        project_path = str(project.get("path") or "")
        score = 0
        reasons: list[str] = []
        name_norm = _normalize_match_text(name)
        parent_norm = _normalize_match_text(parent)
        path_norm = _normalize_match_text(project_path)
        if name_norm and _contains_phrase(path_text, name_norm):
            score += 35
            reasons.append("chemin")
        if parent_norm and _contains_phrase(path_text, parent_norm):
            score += 12
            reasons.append("parent")
        if path_norm and project_path.lower() in doc.content.lower():
            score += 30
            reasons.append("contenu-chemin")
        if name_norm and _contains_phrase(intent_text, name_norm):
            score += 45
            reasons.append("intention")
        elif name_norm and _contains_phrase(content_text, name_norm):
            score += 15
            reasons.append("contenu")
        for alias in aliases:
            alias_norm = _normalize_match_text(alias)
            if not alias_norm or alias_norm in {"hors org", str(project.get("org") or "").lower()}:
                continue
            if _contains_phrase(intent_text, alias_norm):
                score += 10
            if _contains_phrase(content_text, alias_norm):
                score += 4
        if score <= 0:
            continue
        if best is None or score > best[0]:
            best = (score, project, ", ".join(dict.fromkeys(reasons)) or "alias")

    if best is None or best[0] < 12:
        org = _match_org(doc, intent, projects)
        return {"org": org, "project": None, "path": None, "reason": "org" if org else None}
    project = best[1]
    return {
        "org": _canonical_org(str(project.get("org") or "") or None),
        "project": str(project.get("name") or "") or None,
        "path": str(project.get("path") or "") or None,
        "reason": best[2],
    }


def _match_org(doc: AgentMemoryDocument, intent: str, projects: list[dict[str, Any]]) -> str | None:
    orgs = sorted({str(p.get("org") or "") for p in projects if p.get("org")})
    hay = _normalize_match_text(f"{_project_path_match_text(doc)} {intent} {doc.content[:2000]}")
    for org in orgs:
        if org and _contains_phrase(hay, _normalize_match_text(org)):
            return _canonical_org(org)
    return None


def _canonical_org(org: str | None) -> str | None:
    if not org:
        return None
    slug = org.strip().lower().replace(" ", "-")
    if not slug:
        return None
    allowed = organization_slug_set_from_user_config()
    if slug in allowed or slug == "hors-org":
        return slug
    return "hors-org"


def _project_path_match_text(doc: AgentMemoryDocument) -> str:
    path = str(doc.path)
    if "/.hermes/_zab_session_export/" in path:
        return _normalize_match_text(doc.wing)
    return _normalize_match_text(f"{path} {doc.wing}")


def _normalize_match_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


def _contains_phrase(haystack: str, needle: str) -> bool:
    if not haystack or not needle:
        return False
    return f" {needle} " in f" {haystack} "


def _project_key(item: ConversationDigestItem) -> str:
    org = item.org or "non-rattache"
    project = item.project or "sans-projet"
    return f"{org} / {project}"


def _item_dict(item: ConversationDigestItem) -> dict[str, Any]:
    return {
        "conversation_id": item.conversation_id,
        "agent_tool": item.agent_tool,
        "provider": item.provider,
        "source": item.source,
        "wing": item.wing,
        "path": item.path,
        "updated_at": item.updated_at,
        "intent": item.intent,
        "org": item.org,
        "project": item.project,
        "project_path": item.project_path,
        "match_reason": item.match_reason,
        "user_message_count": item.user_message_count,
    }


def _human_dt(iso_value: str) -> str:
    dt = _parse_timestamp(iso_value)
    if not dt:
        return iso_value
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")
