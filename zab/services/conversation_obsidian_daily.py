"""Ecriture Obsidian du digest quotidien des conversations agents."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date as date_cls, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from zab.paths import data_dir
from zab.services import obsidian_vault
from zab.services.agent_memory_import import AgentMemoryDocument
from zab.services.conversation_digest import build_conversation_digest_for_date

DEFAULT_DAILY_REL = "todos/Daily.md"
DEFAULT_DETAIL_DIR_REL = "todos/Agent conversations"

_WEEKDAYS_FR = ("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche")
_MONTHS_FR = (
    "",
    "janvier",
    "fevrier",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "aout",
    "septembre",
    "octobre",
    "novembre",
    "decembre",
)


def yesterday_in_timezone(timezone_name: str = "Europe/Paris", *, now: datetime | None = None) -> date_cls:
    try:
        tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"timezone inconnue : {timezone_name}") from exc
    ref = now.astimezone(tz) if now else datetime.now(tz)
    return ref.date() - timedelta(days=1)


def write_obsidian_conversation_digest(
    *,
    target_date: date_cls | None = None,
    timezone_name: str = "Europe/Paris",
    providers: frozenset[str] | None = None,
    limit: int = 200,
    batch_size: int = 10,
    include_subagents: bool = False,
    once_per_day: bool = False,
    dry_run: bool = False,
    daily_rel: str = DEFAULT_DAILY_REL,
    detail_dir_rel: str = DEFAULT_DETAIL_DIR_REL,
    vault: Path | None = None,
    documents: Iterable[AgentMemoryDocument] | None = None,
    projects: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Genere le digest de la veille et l'inscrit dans Obsidian."""

    day = target_date or yesterday_in_timezone(timezone_name)
    marker = _run_marker_path(day)
    if once_per_day and marker.is_file():
        previous = _read_json(marker)
        return {
            "status": "skipped",
            "reason": "already_ran",
            "target_date": day.isoformat(),
            "marker_path": str(marker),
            "previous": previous,
        }

    payload = build_conversation_digest_for_date(
        on=day,
        timezone_name=timezone_name,
        providers=providers,
        limit=limit,
        batch_size=batch_size,
        include_subagents=include_subagents,
        documents=documents,
        projects=projects,
    )

    vault_path = (vault or obsidian_vault.vault_path_resolved()).expanduser().resolve()
    detail_rel = _detail_rel(day, detail_dir_rel=detail_dir_rel)
    detail_abs = (vault_path / detail_rel).resolve()
    daily_abs = (vault_path / daily_rel).resolve()
    if not _is_within(detail_abs, vault_path) or not _is_within(daily_abs, vault_path):
        raise ValueError("chemin Obsidian hors vault")

    detail_markdown = format_obsidian_detail_markdown(payload)
    todo_block = format_daily_todo_block(payload, detail_rel=detail_rel)

    result = {
        "status": "dry_run" if dry_run else "written",
        "target_date": day.isoformat(),
        "timezone": timezone_name,
        "shown_conversations": payload.get("shown_conversations", 0),
        "retained_conversations": payload.get("retained_conversations", 0),
        "provider_counts": payload.get("retained_provider_counts", {}),
        "daily_rel": daily_rel,
        "detail_rel": detail_rel,
        "daily_abs": str(daily_abs),
        "detail_abs": str(detail_abs),
        "marker_path": str(marker),
        "batch_size": payload.get("batch_size"),
        "batches": payload.get("batches", []),
    }
    if dry_run:
        result["daily_block"] = todo_block
        result["detail_preview"] = "\n".join(detail_markdown.splitlines()[:80])
        return result

    detail_abs.parent.mkdir(parents=True, exist_ok=True)
    detail_abs.write_text(detail_markdown, encoding="utf-8")
    _upsert_daily_block(daily_abs, day=day, block=todo_block)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def format_daily_todo_block(payload: dict[str, Any], *, detail_rel: str) -> str:
    day = str(payload.get("target_date") or "")
    shown = int(payload.get("shown_conversations") or 0)
    providers = _format_counter(payload.get("retained_provider_counts") or {})
    project_bits = _top_project_bits(payload)
    summary = f"{shown} conversation(s)"
    if providers:
        summary += f", {providers}"
    if project_bits:
        summary += f", {project_bits}"
    link = _obsidian_link(detail_rel, f"conversations agents {day}")
    marker_start, marker_end = _markers(day)
    return "\n".join(
        [
            marker_start,
            f"- [ ] Digest agents {day} : {link} - {summary}",
            marker_end,
        ]
    )


def format_obsidian_detail_markdown(payload: dict[str, Any]) -> str:
    day = str(payload.get("target_date") or "")
    window = payload.get("window") or {}
    providers = _format_counter(payload.get("retained_provider_counts") or {}) or "aucun"
    shown = int(payload.get("shown_conversations") or 0)
    retained = int(payload.get("retained_conversations") or 0)
    scanned = int(payload.get("scanned_conversations") or 0)
    batches = payload.get("batches") or []
    lines = [
        "---",
        "type: conversation-digest",
        f"date: {day}",
        f"generated_at: {payload.get('generated_at')}",
        "---",
        "",
        f"# Conversations agents - {day}",
        "",
        f"- Fenetre : {window.get('local_since') or window.get('since')} -> {window.get('local_until') or window.get('until')}",
        f"- Conversations : {shown} affichee(s), {retained} retenue(s), {scanned} scannee(s)",
        f"- Outils agents : {providers}",
        f"- Analyse locale : {len(batches)} paquet(s) de {payload.get('batch_size') or 10}",
        "",
        "## Actions a traiter",
    ]
    todo_lines = _todo_digest_lines(payload)
    lines.extend(todo_lines or ["- [ ] Aucune conversation nette hier."])
    lines.extend(["", "## Conversations"])
    items = payload.get("items") or []
    if not items:
        lines.append("")
        lines.append("Aucune conversation nette sur cette journee.")
        return "\n".join(lines).rstrip() + "\n"

    for group, values in _group_items(items).items():
        lines.extend(["", f"### {_markdown_inline_text(group)}"])
        for item in values:
            stamp = _local_hm(str(item.get("updated_at") or ""), str(payload.get("timezone") or "Europe/Paris"))
            agent = _markdown_inline_text(str(item.get("agent_tool") or item.get("provider") or "?"))
            cid = _markdown_code_span(str(item.get("conversation_id") or "?"))
            org = item.get("org") or ""
            project = item.get("project") or ""
            reason = item.get("match_reason") or ""
            intent = _one_line(str(item.get("intent") or ""))
            meta = _compact_meta([("org", org), ("projet", project), ("raison", reason)])
            lines.append(f"- {stamp} | {agent} | id {cid}{meta} | {intent}")
    return "\n".join(lines).rstrip() + "\n"


def _todo_digest_lines(payload: dict[str, Any]) -> list[str]:
    items = payload.get("items") or []
    if not items:
        return []
    groups = _group_items(items)
    out: list[str] = []
    for group, values in list(groups.items())[:8]:
        intents = [_one_line(str(v.get("intent") or "")) for v in values[:2]]
        tail = "; ".join(x for x in intents if x)
        count = len(values)
        out.append(f"- [ ] {_markdown_inline_text(group)} : {count} conversation(s)" + (f" - {tail}" if tail else ""))
    return out


def _upsert_daily_block(path: Path, *, day: date_cls, block: str) -> None:
    if path.is_file():
        text = path.read_text(encoding="utf-8")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = "---\nsticker: emoji//1f4c6\nbanner:\n---\n## Todo en vrac : \n\n"

    marker_start, marker_end = _markers(day.isoformat())
    pattern = re.compile(rf"{re.escape(marker_start)}.*?{re.escape(marker_end)}\n?", re.DOTALL)
    if pattern.search(text):
        updated = pattern.sub(block.rstrip() + "\n", text)
    else:
        updated = _insert_block_under_day(text, day=day, block=block)
    path.write_text(updated.rstrip() + "\n", encoding="utf-8")


def _insert_block_under_day(text: str, *, day: date_cls, block: str) -> str:
    lines = text.splitlines()
    heading_idx = _find_day_heading(lines, day)
    if heading_idx is None:
        insert_at = _first_day_heading(lines)
        if insert_at is None:
            insert_at = len(lines)
        heading = _format_day_heading(day)
        new_lines = lines[:insert_at] + ["", heading, block, ""] + lines[insert_at:]
        return "\n".join(new_lines)
    new_lines = lines[: heading_idx + 1] + [block, ""] + lines[heading_idx + 1 :]
    return "\n".join(new_lines)


def _find_day_heading(lines: list[str], day: date_cls) -> int | None:
    month = _MONTHS_FR[day.month]
    day_re = re.compile(rf"^\*\*.*\b{day.day}\s+{re.escape(month)}\b", re.IGNORECASE)
    iso_re = re.compile(rf"^\*\*.*\b{re.escape(day.isoformat())}\b", re.IGNORECASE)
    for i, line in enumerate(lines):
        if day_re.search(line) or iso_re.search(line):
            return i
    return None


def _first_day_heading(lines: list[str]) -> int | None:
    heading_re = re.compile(
        r"^\*\*(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|monday|tuesday|wednesday|thursday|friday|saturday|sunday|sat|sun|mon|tue|wed|thu|fri)\b",
        re.IGNORECASE,
    )
    for i, line in enumerate(lines):
        if heading_re.search(line):
            return i
    return None


def _format_day_heading(day: date_cls) -> str:
    return f"**{_WEEKDAYS_FR[day.weekday()]} {day.day} {_MONTHS_FR[day.month]}**  "


def _group_items(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        org = str(item.get("org") or "").strip()
        project = str(item.get("project") or "").strip()
        if org and project:
            key = f"{org} / {project}"
        elif org:
            key = org
        elif project:
            key = project
        else:
            key = "Sans rattachement"
        grouped.setdefault(key, []).append(item)
    return dict(sorted(grouped.items(), key=lambda pair: (-len(pair[1]), pair[0].lower())))


def _top_project_bits(payload: dict[str, Any]) -> str:
    groups = _group_items(payload.get("items") or [])
    bits = [f"{_markdown_inline_text(key)} x{len(values)}" for key, values in groups.items() if key != "Sans rattachement"]
    return "; ".join(bits[:3])


def _format_counter(raw: dict[str, Any]) -> str:
    counts = Counter({str(k): int(v) for k, v in raw.items() if int(v or 0) > 0})
    return ", ".join(f"{k}:{v}" for k, v in counts.most_common())


def _compact_meta(values: list[tuple[str, str]]) -> str:
    parts = [
        f"{_markdown_inline_text(label)} {_markdown_code_span(value)}"
        for label, value in values
        if str(value or "").strip()
    ]
    return " | " + " | ".join(parts) if parts else ""


def _obsidian_link(rel: str, label: str) -> str:
    no_ext = rel[:-3] if rel.endswith(".md") else rel
    return f"[[{no_ext}|{label}]]"


def _detail_rel(day: date_cls, *, detail_dir_rel: str) -> str:
    return f"{detail_dir_rel.strip('/')}/{day.isoformat()} - conversations agents.md"


def _markers(day: str) -> tuple[str, str]:
    return (
        f"<!-- zab-conversation-digest:{day}:start -->",
        f"<!-- zab-conversation-digest:{day}:end -->",
    )


def _run_marker_path(day: date_cls) -> Path:
    return data_dir() / "conversation-daily-obsidian" / f"{day.isoformat()}.json"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _local_hm(iso_value: str, timezone_name: str) -> str:
    try:
        tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    try:
        text = iso_value[:-1] + "+00:00" if iso_value.endswith("Z") else iso_value
        dt = datetime.fromisoformat(text)
    except ValueError:
        return iso_value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(tz).strftime("%H:%M")


def _one_line(text: str) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    truncated = clean[:240].rstrip() + ("..." if len(clean) > 240 else "")
    return _markdown_inline_text(truncated)


def _markdown_inline_text(text: str) -> str:
    """Escape user/content snippets so a digest line cannot break Obsidian Markdown."""

    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("|", "/")
        .replace("`", "\\`")
    )


def _markdown_code_span(text: str) -> str:
    clean = re.sub(r"\s+", " ", str(text)).strip()
    if not clean:
        return "``"
    longest_ticks = max((len(match.group(0)) for match in re.finditer(r"`+", clean)), default=0)
    fence = "`" * (longest_ticks + 1)
    if clean.startswith("`") or clean.endswith("`"):
        clean = f" {clean} "
    return f"{fence}{clean}{fence}"


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False
