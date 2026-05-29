"""Découverte et opérations sur le vault Obsidian de l'utilisateur.

Pose les briques RO + append-only utilisées par le MCP `obsidian` et par les
routes API zab. Pas d'écriture destructive ici — voir `allow_full_write` côté
config.
"""

from __future__ import annotations

from datetime import date as date_cls
from pathlib import Path
from typing import Any

import yaml

from zab.user_config import load_user_config

DEFAULT_VAULT_PATH = "~/ObsidianVault"
DEFAULT_INBOX_DIR = "00_inbox"
DEFAULT_DAILY_DIR = "10_daily"
DEFAULT_DAILY_TEMPLATE = "90_meta/templates/daily.md"

EXPECTED_DIRS = (
    "00_inbox",
    "10_daily",
    "20_projects",
    "30_areas",
    "40_resources",
    "50_notes",
    "90_meta",
)


def _obsidian_cfg() -> dict[str, Any]:
    cfg = load_user_config()
    raw = cfg.get("obsidian")
    return raw if isinstance(raw, dict) else {}


def vault_path_string() -> str:
    raw = _obsidian_cfg().get("vault_path")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return DEFAULT_VAULT_PATH


def vault_path_resolved() -> Path:
    return Path(vault_path_string()).expanduser().resolve()


def allow_full_write() -> bool:
    return bool(_obsidian_cfg().get("allow_full_write", False))


def inbox_dir_relative() -> str:
    raw = _obsidian_cfg().get("inbox_dir")
    if isinstance(raw, str) and raw.strip():
        return raw.strip().strip("/")
    return DEFAULT_INBOX_DIR


def daily_dir_relative() -> str:
    raw = _obsidian_cfg().get("daily_dir")
    if isinstance(raw, str) and raw.strip():
        return raw.strip().strip("/")
    return DEFAULT_DAILY_DIR


def daily_template_relative() -> str:
    raw = _obsidian_cfg().get("daily_template")
    if isinstance(raw, str) and raw.strip():
        return raw.strip().strip("/")
    return DEFAULT_DAILY_TEMPLATE


def vault_exists() -> bool:
    return vault_path_resolved().is_dir()


def validate_vault(path: Path | None = None) -> dict[str, Any]:
    """Retourne un payload listant la présence des dossiers attendus."""
    p = (path or vault_path_resolved())
    if not p.is_dir():
        return {"ok": False, "reason": "missing_vault_dir", "path": str(p)}
    missing = [d for d in EXPECTED_DIRS if not (p / d).is_dir()]
    return {
        "ok": not missing,
        "path": str(p),
        "missing_dirs": missing,
        "expected_dirs": list(EXPECTED_DIRS),
    }


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _safe_relative(vault: Path, rel: str) -> Path:
    """Resolve `rel` à l'intérieur du vault. Lève ValueError sur traversal."""
    candidate = (vault / rel).resolve()
    if not _is_within(candidate, vault):
        raise ValueError(f"path escapes vault: {rel!r}")
    return candidate


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Découpe `---\n...\n---\n` du début. Retourne (front, body)."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    raw = text[4:end]
    body = text[end + 4 :].lstrip("\n")
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError:
        return {}, text
    return (data if isinstance(data, dict) else {}), body


def read_note(rel: str, *, vault: Path | None = None) -> dict[str, Any]:
    v = vault or vault_path_resolved()
    p = _safe_relative(v, rel)
    if not p.is_file():
        return {"ok": False, "reason": "not_found", "rel": rel}
    text = p.read_text(encoding="utf-8")
    front, body = parse_frontmatter(text)
    return {
        "ok": True,
        "rel": rel,
        "abs": str(p),
        "frontmatter": front,
        "body": body,
        "raw": text,
    }


def list_notes(
    *,
    vault: Path | None = None,
    subdir: str | None = None,
    limit: int = 500,
) -> list[str]:
    v = vault or vault_path_resolved()
    if not v.is_dir():
        return []
    root = _safe_relative(v, subdir) if subdir else v
    if not root.is_dir():
        return []
    out: list[str] = []
    for p in sorted(root.rglob("*.md")):
        if any(part.startswith(".") or part == "_attachments" for part in p.relative_to(v).parts):
            continue
        out.append(str(p.relative_to(v)))
        if len(out) >= limit:
            break
    return out


def vault_search(
    query: str,
    *,
    vault: Path | None = None,
    limit: int = 100,
    case_sensitive: bool = False,
) -> list[dict[str, Any]]:
    """Recherche substring sur tous les `.md` du vault. Retourne hits avec contexte."""
    v = vault or vault_path_resolved()
    if not v.is_dir() or not query:
        return []
    needle = query if case_sensitive else query.lower()
    hits: list[dict[str, Any]] = []
    for p in sorted(v.rglob("*.md")):
        if any(part.startswith(".") or part == "_attachments" for part in p.relative_to(v).parts):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        hay = text if case_sensitive else text.lower()
        if needle not in hay:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            hay_line = line if case_sensitive else line.lower()
            if needle in hay_line:
                hits.append(
                    {
                        "rel": str(p.relative_to(v)),
                        "line": lineno,
                        "text": line.strip()[:300],
                    }
                )
                if len(hits) >= limit:
                    return hits
    return hits


def daily_note_path(*, on: date_cls | None = None, vault: Path | None = None) -> Path:
    v = vault or vault_path_resolved()
    d = on or date_cls.today()
    return v / daily_dir_relative() / f"{d.isoformat()}.md"


def _render_template(template_text: str, *, date_iso: str, slug: str = "", title: str = "") -> str:
    return (
        template_text.replace("{{date}}", date_iso)
        .replace("{{slug}}", slug)
        .replace("{{title}}", title or slug)
    )


def ensure_daily_note(*, on: date_cls | None = None, vault: Path | None = None) -> Path:
    """Crée la daily note du jour si absente, en utilisant le template configuré."""
    v = vault or vault_path_resolved()
    d = on or date_cls.today()
    target = daily_note_path(on=d, vault=v)
    if target.is_file():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    template_path = v / daily_template_relative()
    if template_path.is_file():
        text = _render_template(template_path.read_text(encoding="utf-8"), date_iso=d.isoformat())
    else:
        text = f"# {d.isoformat()}\n\n"
    target.write_text(text, encoding="utf-8")
    return target


def daily_append(block: str, *, on: date_cls | None = None, vault: Path | None = None) -> Path:
    """Append d'un bloc Markdown à la daily note (crée si absente). Append-only."""
    target = ensure_daily_note(on=on, vault=vault)
    sep = "" if target.read_text(encoding="utf-8").endswith("\n") else "\n"
    with target.open("a", encoding="utf-8") as fh:
        fh.write(f"{sep}{block.rstrip()}\n")
    return target


def inbox_create(filename: str, body: str, *, vault: Path | None = None) -> Path:
    """Crée un nouveau fichier dans 00_inbox/. Refuse l'écrasement."""
    v = vault or vault_path_resolved()
    safe = filename.strip().lstrip("/").replace("..", "")
    if not safe or "/" in safe or "\\" in safe:
        raise ValueError(f"invalid inbox filename: {filename!r}")
    if not safe.endswith(".md"):
        safe = f"{safe}.md"
    inbox = v / inbox_dir_relative()
    inbox.mkdir(parents=True, exist_ok=True)
    target = inbox / safe
    if target.exists():
        raise FileExistsError(str(target))
    target.write_text(body if body.endswith("\n") else body + "\n", encoding="utf-8")
    return target


def doctor_payload() -> dict[str, Any]:
    v = vault_path_resolved()
    info = validate_vault(v)
    notes_count = 0
    daily_today: str | None = None
    if v.is_dir():
        notes_count = sum(1 for _ in v.rglob("*.md"))
        today_path = daily_note_path(vault=v)
        if today_path.is_file():
            daily_today = str(today_path.relative_to(v))
    return {
        "vault_path": str(v),
        "exists": v.is_dir(),
        "validation": info,
        "notes_count": notes_count,
        "allow_full_write": allow_full_write(),
        "daily_today": daily_today,
        "obsidian_url": f"obsidian://open?vault={v.name}" if v.is_dir() else None,
    }
