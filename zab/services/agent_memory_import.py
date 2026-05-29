"""Import conversations/artefacts d'agents locaux vers Postgres mehdi_memory_*."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, FrozenSet

from zab.paths import skills_root, skills_root_from_config_file_only
from zab.services.conversations_archive import (
    delete_archive_for_providers,
    ensure_conversations_archive_schema,
    upsert_conversation_archive,
)
from zab.services.memory_scan import resolve_mehdi_memory_database_url

AGENT_MEMORY_SOURCES = (
    "cursor_agent_transcript",
    "claude_code_transcript",
    "codex_transcript",
    "kimi_transcript",
    "hermes_transcript",
    "gemini_cli_transcript",
    "agent_context_artifact",
)

DEFAULT_BATCH_ID = "agent-conversations-local"
MAX_DOC_CHARS = 450_000
CHUNK_SIZE = 7_000
CHUNK_OVERLAP = 500

# Identifiants pour filtrer la collecte / la sync partielle
PROVIDER_CURSOR = "cursor"
PROVIDER_CLAUDE = "claude"
PROVIDER_CODEX = "codex"
PROVIDER_KIMI = "kimi"
PROVIDER_HERMES = "hermes"
PROVIDER_GEMINI = "gemini"

ALL_CONVERSATION_PROVIDERS: FrozenSet[str] = frozenset(
    {
        PROVIDER_CURSOR,
        PROVIDER_CLAUDE,
        PROVIDER_CODEX,
        PROVIDER_KIMI,
        PROVIDER_HERMES,
        PROVIDER_GEMINI,
    }
)

# Sources indexées dans l’archive `zab_conversations` (transcripts seulement).
ARCHIVE_DOCUMENT_SOURCES: FrozenSet[str] = frozenset(
    {
        "cursor_agent_transcript",
        "claude_code_transcript",
        "codex_transcript",
        "kimi_transcript",
        "hermes_transcript",
        "gemini_cli_transcript",
    }
)

_GEMINI_SKIP_SUBSTR = (
    "oauth",
    "credential",
    "service-account",
    "service_account",
    ".env",
    "/tmp/",
    "\\tmp\\",
)


@dataclass(frozen=True)
class AgentMemoryDocument:
    source: str
    wing: str
    room: str
    path: Path
    content: str
    metadata: dict[str, Any]
    raw_events: tuple[dict[str, Any], ...] = ()
    messages: tuple[dict[str, Any], ...] = ()


def _message_label(role: str, *, tool_result: bool = False) -> str:
    r = (role or "").lower()
    if r == "user":
        return "You"
    if r == "assistant":
        return "Agent"
    if r == "tool":
        return "Tool result" if tool_result else "Tool call"
    if r == "system":
        return "System"
    return role or "Message"


def _timestamp_from_obj(obj: dict[str, Any], msg: Any) -> str | None:
    for key in ("timestamp", "created_at", "createdAt", "time", "date"):
        val = obj.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
        if isinstance(val, (int, float)):
            return str(val)
    if isinstance(msg, dict):
        for key in ("timestamp", "created_at", "createdAt", "time", "date"):
            val = msg.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
            if isinstance(val, (int, float)):
                return str(val)
    return None


def _conversation_message(
    *,
    role: str,
    content: str,
    timestamp: str | None,
    tool_name: str | None = None,
    label: str | None = None,
    line: int | None = None,
) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "role": role,
        "label": label or _message_label(role),
        "content": content.strip(),
    }
    if timestamp:
        msg["timestamp"] = timestamp
    if tool_name:
        msg["tool_name"] = tool_name
    if line is not None:
        msg["line"] = line
    return msg


def _messages_from_content(role: str, msg: Any, *, timestamp: str | None, line: int) -> list[dict[str, Any]]:
    """Transforme un `message.content` JSONL en bulles lisibles humainement."""
    if isinstance(msg, dict):
        content = msg.get("content")
    else:
        content = msg

    if not isinstance(content, list):
        text = _extract_content(msg)
        return [_conversation_message(role=role, content=text, timestamp=timestamp, line=line)] if text else []

    out: list[dict[str, Any]] = []
    text_parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            text = _extract_content(item)
            if text:
                text_parts.append(text)
            continue

        typ = item.get("type")
        if typ == "text" and isinstance(item.get("text"), str):
            text_parts.append(item["text"])
            continue

        if typ == "tool_use":
            if text_parts:
                out.append(_conversation_message(role=role, content="\n".join(text_parts), timestamp=timestamp, line=line))
                text_parts = []
            tool_name = str(item.get("name") or "tool")
            payload = json.dumps(item.get("input") or {}, ensure_ascii=False, indent=2)
            out.append(
                _conversation_message(
                    role="tool",
                    label="Tool call",
                    tool_name=tool_name,
                    content=payload,
                    timestamp=timestamp,
                    line=line,
                )
            )
            continue

        if typ == "tool_result":
            if text_parts:
                out.append(_conversation_message(role=role, content="\n".join(text_parts), timestamp=timestamp, line=line))
                text_parts = []
            out.append(
                _conversation_message(
                    role="tool",
                    label="Tool result",
                    content=_extract_content(item.get("content")),
                    timestamp=timestamp,
                    line=line,
                )
            )
            continue

        text = _extract_content(item)
        if text:
            text_parts.append(text)

    if text_parts:
        out.append(_conversation_message(role=role, content="\n".join(text_parts), timestamp=timestamp, line=line))
    return out


def _meta(provider: str, **extra: Any) -> dict[str, Any]:
    return {"conversation_provider": provider, **extra}


def _clean(text: str) -> str:
    return re.sub(r"\n{4,}", "\n\n\n", text.replace("\r\n", "\n")).strip()


def _extract_content(value: Any, *, depth: int = 0) -> str:
    if depth > 4 or value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                typ = item.get("type")
                if typ == "text" and isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif typ == "tool_use":
                    payload = json.dumps(item.get("input"), ensure_ascii=False)[:1200]
                    parts.append(f"[tool_use {item.get('name', '')} input={payload}]")
                elif typ == "tool_result":
                    parts.append(f"[tool_result {_extract_content(item.get('content'), depth=depth + 1)[:2000]}]")
                else:
                    text = _extract_content(item.get("text") or item.get("content") or item, depth=depth + 1)
                    if text:
                        parts.append(text)
            else:
                text = _extract_content(item, depth=depth + 1)
                if text:
                    parts.append(text)
        return "\n".join(parts)
    if isinstance(value, dict):
        for key in ("text", "content", "message", "output", "result"):
            if key in value:
                text = _extract_content(value[key], depth=depth + 1)
                if text:
                    return text
        return json.dumps(value, ensure_ascii=False)[:4000]
    return ""


def parse_jsonl_transcript(path: Path) -> str:
    text, _raw, _messages = _parse_jsonl_transcript_arrays(path)
    return text


def _parse_jsonl_transcript_arrays(path: Path) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """Texte concaténé, événements JSONL bruts (1 entrée / ligne), bulles structurées."""
    parts: list[str] = []
    raw_events: list[dict[str, Any]] = []
    messages: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", errors="ignore") as fp:
        for i, line in enumerate(fp, 1):
            raw = line.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                parts.append(f"[line {i}] {raw}")
                raw_events.append({"_parse_error": "json_decode", "line": i, "snippet": raw[:800]})
                continue
            raw_events.append(obj)
            role = obj.get("role") or obj.get("type") or obj.get("source") or "entry"
            msg = obj.get("message", obj)
            text = _extract_content(msg)
            if text:
                parts.append(f"### {role} (line {i})\n{text}")
            messages.extend(_messages_from_content(str(role), msg, timestamp=_timestamp_from_obj(obj, msg), line=i))
    return _clean("\n\n".join(parts)), raw_events, [m for m in messages if m.get("content")]


def parse_jsonl_transcript_structured(path: Path) -> tuple[str, list[dict[str, Any]]]:
    text, _raw, messages = _parse_jsonl_transcript_arrays(path)
    return text, messages


def _parse_text_file(path: Path) -> str:
    try:
        return _clean(path.read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return ""


def _iter_chunks(text: str) -> list[str]:
    text = text[:MAX_DOC_CHARS]
    if len(text) <= CHUNK_SIZE:
        return [text] if text else []
    out: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + CHUNK_SIZE)
        out.append(text[start:end])
        if end == len(text):
            break
        start = max(0, end - CHUNK_OVERLAP)
    return out


def _wing(text: str) -> str:
    return text.replace("/", "__").replace(" ", "_").replace(".", "_")


def _cursor_wing(path: Path) -> str:
    try:
        return "cursor__" + path.relative_to(Path.home() / ".cursor" / "projects").parts[0]
    except Exception:
        return "cursor"


def _interesting_files(root: Path) -> list[Path]:
    allowed = {".md", ".mdc", ".txt", ".json", ".jsonl"}
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in allowed)


def _hermes_virtual_path(session_id: str) -> Path:
    return Path.home() / ".hermes" / "_zab_session_export" / f"{session_id}.jsonl"


def _hermes_session_to_text(session: dict[str, Any], messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    title = session.get("title") or session.get("id") or "session"
    src = session.get("source") or "cli"
    model = session.get("model") or ""
    parts.append(f"### session_meta\nHermes session `{session.get('id')}` source={src} model={model}\ntitle={title}\n")
    for i, msg in enumerate(messages, 1):
        role = msg.get("role") or "entry"
        content = msg.get("content") or ""
        if role == "tool":
            tool_name = msg.get("tool_name") or msg.get("tool_call_id") or "tool"
            parts.append(f"### tool (line {i}) [{tool_name}]\n{content[:4000]}")
            continue
        parts.append(f"### {role} (line {i})\n{content}")
    return _clean("\n\n".join(parts))


def _hermes_session_to_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, msg in enumerate(messages, 1):
        role = str(msg.get("role") or "entry")
        content = str(msg.get("content") or "")
        if not content.strip():
            continue
        timestamp_val = msg.get("timestamp")
        timestamp = str(timestamp_val) if timestamp_val is not None else None
        if role == "tool":
            tool_name = str(msg.get("tool_name") or msg.get("tool_call_id") or "tool")
            out.append(
                _conversation_message(
                    role="tool",
                    label="Tool result",
                    tool_name=tool_name,
                    content=content[:4000],
                    timestamp=timestamp,
                    line=i,
                )
            )
        else:
            out.append(_conversation_message(role=role, content=content, timestamp=timestamp, line=i))
    return out


def collect_cursor_documents() -> list[AgentMemoryDocument]:
    docs: list[AgentMemoryDocument] = []
    home = Path.home()
    cursor_root = home / ".cursor" / "projects"
    if cursor_root.exists():
        for path in sorted(cursor_root.glob("*/agent-transcripts/**/*.jsonl")):
            content, raw_events, messages = _parse_jsonl_transcript_arrays(path)
            if content:
                docs.append(
                    AgentMemoryDocument(
                        source="cursor_agent_transcript",
                        wing=_cursor_wing(path),
                        room="conversation",
                        path=path,
                        content=content,
                        metadata=_meta(
                            PROVIDER_CURSOR,
                            kind="cursor_agent_transcript",
                            subagent="/subagents/" in str(path),
                            messages=list(messages),
                        ),
                        raw_events=tuple(raw_events),
                        messages=tuple(messages),
                    )
                )
        for kind in ("plans", "rules", "skills"):
            for directory in sorted(cursor_root.glob(f"*/{kind}")):
                for path in _interesting_files(directory):
                    content = parse_jsonl_transcript(path) if path.suffix.lower() == ".jsonl" else _parse_text_file(path)
                    if content:
                        docs.append(
                            AgentMemoryDocument(
                                source="agent_context_artifact",
                                wing=_cursor_wing(directory / "dummy"),
                                room=kind,
                                path=path,
                                content=content,
                                metadata=_meta(PROVIDER_CURSOR, kind=f"cursor_{kind}"),
                            )
                        )
    return docs


def collect_claude_documents() -> list[AgentMemoryDocument]:
    docs: list[AgentMemoryDocument] = []
    claude = Path.home() / ".claude" / "projects"
    if claude.exists():
        for path in sorted(claude.glob("**/*.jsonl")):
            content, raw_events, messages = _parse_jsonl_transcript_arrays(path)
            if content:
                docs.append(
                    AgentMemoryDocument(
                        source="claude_code_transcript",
                        wing="claude__" + _wing(path.parent.name),
                        room="conversation",
                        path=path,
                        content=content,
                        metadata=_meta(PROVIDER_CLAUDE, kind="claude_code_transcript", messages=list(messages)),
                        raw_events=tuple(raw_events),
                        messages=tuple(messages),
                    )
                )
    return docs


def collect_codex_documents() -> list[AgentMemoryDocument]:
    docs: list[AgentMemoryDocument] = []
    codex = Path.home() / ".codex"
    for path in sorted((codex / "sessions").glob("**/*.jsonl")) if (codex / "sessions").exists() else []:
        content, raw_events, messages = _parse_jsonl_transcript_arrays(path)
        if content:
            docs.append(
                AgentMemoryDocument(
                    "codex_transcript",
                    "codex__sessions",
                    "conversation",
                    path,
                    content,
                    _meta(PROVIDER_CODEX, kind="codex_session", messages=list(messages)),
                    raw_events=tuple(raw_events),
                    messages=tuple(messages),
                )
            )
    history = codex / "history.jsonl"
    if history.exists():
        content, raw_events, messages = _parse_jsonl_transcript_arrays(history)
        if content:
            docs.append(
                AgentMemoryDocument(
                    "codex_transcript",
                    "codex__history",
                    "conversation",
                    history,
                    content,
                    _meta(PROVIDER_CODEX, kind="codex_history", messages=list(messages)),
                    raw_events=tuple(raw_events),
                    messages=tuple(messages),
                )
            )
    for kind in ("rules", "skills", "memories"):
        directory = codex / kind
        if directory.exists():
            for path in _interesting_files(directory):
                content = parse_jsonl_transcript(path) if path.suffix.lower() == ".jsonl" else _parse_text_file(path)
                if content:
                    docs.append(
                        AgentMemoryDocument(
                            "agent_context_artifact",
                            f"codex__{kind}",
                            kind,
                            path,
                            content,
                            _meta(PROVIDER_CODEX, kind=f"codex_{kind}"),
                        )
                    )
    return docs


def collect_kimi_documents() -> list[AgentMemoryDocument]:
    docs: list[AgentMemoryDocument] = []
    kimi = Path.home() / ".kimi"
    for directory, room in ((kimi / "user-history", "conversation"), (kimi / "sessions", "conversation"), (kimi / "plans", "plans")):
        if directory.exists():
            for path in _interesting_files(directory):
                if path.suffix.lower() == ".jsonl":
                    content, raw_events, messages = _parse_jsonl_transcript_arrays(path)
                else:
                    content, raw_events, messages = _parse_text_file(path), [], []
                if content:
                    source = "kimi_transcript" if room == "conversation" else "agent_context_artifact"
                    docs.append(
                        AgentMemoryDocument(
                            source,
                            "kimi__" + directory.name,
                            room,
                            path,
                            content,
                            _meta(PROVIDER_KIMI, kind=f"kimi_{directory.name}", messages=list(messages)),
                            raw_events=tuple(raw_events),
                            messages=tuple(messages),
                        )
                    )
    return docs


def _collect_hermes_documents_strict() -> list[AgentMemoryDocument]:
    docs: list[AgentMemoryDocument] = []
    db_path = Path.home() / ".hermes" / "state.db"
    if not db_path.is_file():
        return docs
    uri = f"file:{db_path}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    except sqlite3.Error:
        return docs
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cur.fetchall()}
        if "sessions" not in tables or "messages" not in tables:
            return docs
        sessions = conn.execute("SELECT * FROM sessions ORDER BY rowid DESC").fetchall()
        for srow in sessions:
            sid = srow["id"]
            messages = conn.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY COALESCE(timestamp, 0)",
                (sid,),
            ).fetchall()
            if not messages:
                continue
            session_dict = dict(srow)
            msg_dicts = [dict(m) for m in messages]
            content = _hermes_session_to_text(session_dict, msg_dicts)
            structured_messages = _hermes_session_to_messages(msg_dicts)
            if not content:
                continue
            wing = "hermes__" + _wing(str(sid))
            vpath = _hermes_virtual_path(str(sid))
            title = session_dict.get("title")
            title_s = str(title).strip() if title is not None else ""
            docs.append(
                AgentMemoryDocument(
                    source="hermes_transcript",
                    wing=wing,
                    room="conversation",
                    path=vpath,
                    content=content,
                    metadata=_meta(
                        PROVIDER_HERMES,
                        kind="hermes_session",
                        hermes_session_id=str(sid),
                        hermes_source=str(session_dict.get("source") or ""),
                        title=title_s or None,
                        messages=structured_messages,
                    ),
                    raw_events=tuple(msg_dicts),
                    messages=tuple(structured_messages),
                )
            )
    finally:
        conn.close()
    return docs


def collect_hermes_documents() -> list[AgentMemoryDocument]:
    try:
        return _collect_hermes_documents_strict()
    except sqlite3.Error:
        return []


def _gemini_path_skipped(path: Path) -> str | None:
    low = str(path).lower()
    for frag in _GEMINI_SKIP_SUBSTR:
        if frag in low:
            return f"chemin_exclu:{frag}"
    return None


def collect_gemini_cli_documents() -> list[AgentMemoryDocument]:
    """Collecte conservative : uniquement des .jsonl sous ~/.gemini hors chemins sensibles, contenu parsable."""
    docs: list[AgentMemoryDocument] = []
    root = Path.home() / ".gemini"
    if not root.is_dir():
        return docs
    for path in sorted(root.rglob("*.jsonl")):
        skip = _gemini_path_skipped(path)
        if skip:
            continue
        try:
            if path.stat().st_size > 5_000_000:
                continue
        except OSError:
            continue
        content, raw_events, messages = _parse_jsonl_transcript_arrays(path)
        if len(content.strip()) < 40:
            continue
        rel = path.relative_to(root)
        wing = "gemini__" + _wing("__".join(rel.parts))
        docs.append(
            AgentMemoryDocument(
                source="gemini_cli_transcript",
                wing=wing,
                room="conversation",
                path=path,
                content=content,
                metadata=_meta(PROVIDER_GEMINI, kind="gemini_jsonl", messages=list(messages)),
                raw_events=tuple(raw_events),
                messages=tuple(messages),
            )
        )
    return docs


def discover_gemini_cli_status() -> dict[str, Any]:
    """État discovery Gemini CLI sans ingérer de secrets."""
    root = Path.home() / ".gemini"
    if not root.is_dir():
        return {"present": False, "status": "missing", "jsonl_candidates": 0, "ingestable_jsonl": 0, "reason": None}
    candidates = 0
    ingestable = 0
    for path in root.rglob("*.jsonl"):
        candidates += 1
        if _gemini_path_skipped(path):
            continue
        try:
            if path.stat().st_size > 5_000_000:
                continue
        except OSError:
            continue
        txt = parse_jsonl_transcript(path)
        if len(txt.strip()) >= 40:
            ingestable += 1
    if ingestable > 0:
        status = "ready"
        reason = None
    elif candidates > 0:
        status = "unsupported_format"
        reason = "jsonl présents mais aucun transcript exploitable (filtres ou format)"
    else:
        status = "detected"
        reason = "dossier .gemini sans .jsonl candidat"
    return {
        "present": True,
        "status": status,
        "jsonl_candidates": candidates,
        "ingestable_jsonl": ingestable,
        "reason": reason,
    }


def _collect_agent_memory_documents_with_failures(
    *,
    providers: FrozenSet[str] | None = None,
) -> tuple[list[AgentMemoryDocument], dict[str, str], FrozenSet[str]]:
    want = ALL_CONVERSATION_PROVIDERS if providers is None else providers
    docs: list[AgentMemoryDocument] = []
    failed: dict[str, str] = {}
    collectors = {
        PROVIDER_CURSOR: collect_cursor_documents,
        PROVIDER_CLAUDE: collect_claude_documents,
        PROVIDER_CODEX: collect_codex_documents,
        PROVIDER_KIMI: collect_kimi_documents,
        PROVIDER_HERMES: _collect_hermes_documents_strict,
        PROVIDER_GEMINI: collect_gemini_cli_documents,
    }
    for provider in (
        PROVIDER_CURSOR,
        PROVIDER_CLAUDE,
        PROVIDER_CODEX,
        PROVIDER_KIMI,
        PROVIDER_HERMES,
        PROVIDER_GEMINI,
    ):
        if provider not in want:
            continue
        try:
            docs.extend(collectors[provider]())
        except Exception as exc:  # noqa: BLE001 - provider isolation: one corrupt source must not kill sync.
            failed[provider] = str(exc) or type(exc).__name__
    successful = frozenset(p for p in want if p not in failed)
    return docs, failed, successful


def collect_agent_memory_documents(*, providers: FrozenSet[str] | None = None) -> list[AgentMemoryDocument]:
    docs, _failed, _successful = _collect_agent_memory_documents_with_failures(providers=providers)
    return docs


def discover_provider_dry_run_summary(*, providers: FrozenSet[str] | None = None) -> dict[str, Any]:
    """Compteurs et chemins d'échantillon pour dry-run / health (sans Postgres)."""
    want = ALL_CONVERSATION_PROVIDERS if providers is None else providers
    home = Path.home()
    out: dict[str, Any] = {"providers": {}}

    if PROVIDER_CURSOR in want:
        cr = home / ".cursor" / "projects"
        n_jsonl = 0
        sample: list[str] = []
        if cr.is_dir():
            for p in sorted(cr.glob("*/agent-transcripts/**/*.jsonl")):
                n_jsonl += 1
                if len(sample) < 5:
                    sample.append(str(p))
        out["providers"][PROVIDER_CURSOR] = {
            "paths_detected": cr.is_dir(),
            "agent_transcript_jsonl": n_jsonl,
            "sample_paths": sample,
        }

    if PROVIDER_CLAUDE in want:
        cl = home / ".claude" / "projects"
        n = 0
        sample: list[str] = []
        if cl.is_dir():
            for p in cl.rglob("*.jsonl"):
                n += 1
                if len(sample) < 5:
                    sample.append(str(p))
        out["providers"][PROVIDER_CLAUDE] = {"paths_detected": cl.is_dir(), "jsonl_files": n, "sample_paths": sample}

    if PROVIDER_CODEX in want:
        cx = home / ".codex"
        n_sess = len(list((cx / "sessions").rglob("*.jsonl"))) if (cx / "sessions").is_dir() else 0
        out["providers"][PROVIDER_CODEX] = {
            "paths_detected": cx.is_dir(),
            "session_jsonl": n_sess,
            "history_jsonl": (cx / "history.jsonl").is_file(),
        }

    if PROVIDER_KIMI in want:
        km = home / ".kimi"
        out["providers"][PROVIDER_KIMI] = {"paths_detected": km.is_dir()}

    if PROVIDER_HERMES in want:
        db = home / ".hermes" / "state.db"
        sess_n = 0
        if db.is_file():
            try:
                conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, check_same_thread=False)
                try:
                    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                    tnames = {r[0] for r in rows}
                    if "sessions" in tnames:
                        sess_n = int(conn.execute("SELECT count(*) FROM sessions").fetchone()[0])
                finally:
                    conn.close()
            except sqlite3.Error:
                sess_n = -1
        out["providers"][PROVIDER_HERMES] = {"state_db_present": db.is_file(), "session_rows_estimate": sess_n}

    if PROVIDER_GEMINI in want:
        out["providers"][PROVIDER_GEMINI] = discover_gemini_cli_status()

    return out


def _delete_documents_for_providers(cur: Any, providers: FrozenSet[str]) -> int:
    """Supprime les documents agents pour les providers demandés (sync partielle)."""
    total = 0
    if PROVIDER_CURSOR in providers:
        cur.execute(
            """
            DELETE FROM mehdi_memory_documents
            WHERE source = 'cursor_agent_transcript'
               OR (source = 'agent_context_artifact' AND wing LIKE 'cursor%%')
            """
        )
        total += cur.rowcount
    if PROVIDER_CLAUDE in providers:
        cur.execute("DELETE FROM mehdi_memory_documents WHERE source = 'claude_code_transcript'")
        total += cur.rowcount
    if PROVIDER_CODEX in providers:
        cur.execute(
            """
            DELETE FROM mehdi_memory_documents
            WHERE source = 'codex_transcript'
               OR (source = 'agent_context_artifact' AND wing LIKE 'codex%%')
            """
        )
        total += cur.rowcount
    if PROVIDER_KIMI in providers:
        cur.execute(
            """
            DELETE FROM mehdi_memory_documents
            WHERE source = 'kimi_transcript'
               OR (source = 'agent_context_artifact' AND wing LIKE 'kimi%%')
            """
        )
        total += cur.rowcount
    if PROVIDER_HERMES in providers:
        cur.execute("DELETE FROM mehdi_memory_documents WHERE source = 'hermes_transcript'")
        total += cur.rowcount
    if PROVIDER_GEMINI in providers:
        cur.execute("DELETE FROM mehdi_memory_documents WHERE source = 'gemini_cli_transcript'")
        total += cur.rowcount
    return total


def _conversation_doc_should_archive(doc: AgentMemoryDocument) -> bool:
    return doc.room == "conversation" and doc.source in ARCHIVE_DOCUMENT_SOURCES


def _path_updated_at_utc(path: Path) -> datetime | None:
    try:
        if path.is_file():
            return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        pass
    return None


def _archive_title_from_doc(doc: AgentMemoryDocument) -> str | None:
    raw = doc.metadata.get("title")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    stem = doc.path.stem
    return stem if stem else None


def _archive_metadata_stub(doc: AgentMemoryDocument, *, content_len: int) -> dict[str, Any]:
    """Métadonnées archive (sans liste `messages`, portée dans la colonne dédiée)."""
    out: dict[str, Any] = {"path": str(doc.path), "chars": content_len}
    for k, v in doc.metadata.items():
        if k == "messages":
            continue
        out[k] = v
    return out


def _messages_for_archive(doc: AgentMemoryDocument) -> list[dict[str, Any]]:
    if doc.messages:
        return [dict(m) for m in doc.messages]
    m = doc.metadata.get("messages")
    if isinstance(m, list):
        return [dict(x) if isinstance(x, dict) else {"content": str(x)} for x in m]
    return []


def sync_agent_memory_to_postgres(
    *,
    replace: bool = True,
    batch_id: str = DEFAULT_BATCH_ID,
    dry_run: bool = False,
    providers: FrozenSet[str] | None = None,
) -> dict[str, Any]:
    docs, failed_providers, successful_providers = _collect_agent_memory_documents_with_failures(providers=providers)
    source_counts: dict[str, int] = {}
    for doc in docs:
        source_counts[doc.source] = source_counts.get(doc.source, 0) + 1
    chunk_count = sum(len(_iter_chunks(doc.content)) for doc in docs)
    summary: dict[str, Any] = {
        "batch_id": batch_id,
        "documents_collected": len(docs),
        "chunks_collected": chunk_count,
        "source_counts": source_counts,
        "replace": replace,
        "dry_run": dry_run,
        "providers": sorted(successful_providers) if providers else None,
        "failed_providers": failed_providers,
        "deleted_previous_documents": 0,
        "deleted_previous_archive_rows": 0,
        "inserted_documents": 0,
        "inserted_chunks": 0,
        "inserted_archive_documents": 0,
    }
    if dry_run:
        return summary

    url = resolve_mehdi_memory_database_url(skills_root_from_config_file_only()) or resolve_mehdi_memory_database_url(
        skills_root()
    )
    if not url:
        raise RuntimeError("MEHDI_MEMORY_DATABASE_URL absent (processus ou .env skills).")
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("psycopg absent ; exécuter `uv sync --extra memory`.") from exc

    with psycopg.connect(url, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            ensure_conversations_archive_schema(cur)
            if replace:
                summary["deleted_previous_archive_rows"] = delete_archive_for_providers(
                    cur, successful_providers
                )
                summary["deleted_previous_documents"] = _delete_documents_for_providers(cur, successful_providers)
            synced_now = datetime.now(timezone.utc)
            for doc in docs:
                content = doc.content[:MAX_DOC_CHARS]
                if not content:
                    continue
                doc_id = uuid.uuid4()
                h = hashlib.sha256((doc.source + "|" + str(doc.path) + "|" + content).encode("utf-8")).hexdigest()[:32]
                meta = {**doc.metadata, "path": str(doc.path), "chars": len(content)}
                if _conversation_doc_should_archive(doc):
                    prov = str(meta.get("conversation_provider") or "unknown")
                    archive_meta = _archive_metadata_stub(doc, content_len=len(content))
                    archive_meta["export_batch_id"] = batch_id
                    conv_uuid = upsert_conversation_archive(
                        cur,
                        provider=prov,
                        source=doc.source,
                        source_path=str(doc.path),
                        source_hash=h,
                        wing=doc.wing,
                        room=doc.room,
                        title=_archive_title_from_doc(doc),
                        started_at=None,
                        updated_at=_path_updated_at_utc(doc.path),
                        raw_events=[dict(x) for x in doc.raw_events] if doc.raw_events else [],
                        messages=_messages_for_archive(doc),
                        metadata=archive_meta,
                        synced_at=synced_now,
                    )
                    meta["conversation_id"] = str(conv_uuid)
                    summary["inserted_archive_documents"] += 1
                cur.execute(
                    """
                    INSERT INTO mehdi_memory_documents (id, source, export_batch_id, wing, room, content_hash, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        doc_id,
                        doc.source,
                        batch_id,
                        doc.wing,
                        doc.room,
                        h,
                        json.dumps(meta, ensure_ascii=False, default=str),
                    ),
                )
                summary["inserted_documents"] += 1
                for idx, chunk in enumerate(_iter_chunks(content)):
                    cur.execute(
                        """
                        INSERT INTO mehdi_memory_chunks (id, document_id, content, metadata, chunk_index)
                        VALUES (%s, %s, %s, %s::jsonb, %s)
                        """,
                        (
                            uuid.uuid4(),
                            doc_id,
                            chunk,
                            json.dumps(meta, ensure_ascii=False, default=str),
                            idx,
                        ),
                    )
                    summary["inserted_chunks"] += 1
        conn.commit()
    return summary
