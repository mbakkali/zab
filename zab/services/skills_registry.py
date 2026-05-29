"""Registre unique des skills (~/.config/zab/skills-registry.json) — source de vérité locale."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml

from zab.paths import config_dir, data_dir
from zab.services.skills_scan import collect_skill_md_under_repo, iter_skill_md_recursive
from zab.user_config import load_user_config, save_user_config, skills_sync_settings, user_config_path

REGISTRY_VERSION = 1
DEFAULT_FILENAME = "skills-registry.json"

SkillStatus = Literal["candidate", "adopted", "mirrored", "published", "ignored", "conflict"]
SourceKind = Literal[
    "mirror",
    "workspace",
    "cursor_global",
    "claude_global",
    "kimi_global",
    "hermes_external",
    "config_legacy",
]


def registry_path() -> Path:
    cfg = load_user_config()
    raw = cfg.get("skills_registry_path")
    if isinstance(raw, str) and raw.strip():
        return Path(raw.strip()).expanduser().resolve()
    return (config_dir() / DEFAULT_FILENAME).resolve()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc_now_iso() -> str:
    return _utc_now()


def infer_org_slug_for_skill_file(skill_md: Path, repo_root: Path) -> str | None:
    return _infer_org_from_mirror(skill_md, repo_root)


def replace_skills_entries(by_key: dict[str, dict[str, Any]]) -> None:
    doc = load_registry_document()
    _write_skills_dict(doc, by_key)
    save_registry_document(doc)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _infer_org_from_mirror(skill_md: Path, repo_root: Path) -> str | None:
    try:
        rel = skill_md.resolve().relative_to(repo_root.resolve())
    except ValueError:
        parts = skill_md.resolve().parts
        for i, part in enumerate(parts):
            if part == "orgs" and i + 2 < len(parts) and parts[i + 2] == "skills":
                return parts[i + 1]
        return None
    parts = rel.parts
    if len(parts) >= 3 and parts[0] == "common" and parts[1] == "skills":
        return "common"
    if len(parts) >= 4 and parts[0] == "orgs" and parts[2] == "skills":
        return parts[1]
    # Layout Hermes par catégorie : <category>/<skill>/SKILL.md
    if len(parts) >= 3 and parts[0] not in ("orgs", "common") and not parts[0].startswith("."):
        return parts[0]
    return None


def _collect_skill_md_under_repo(repo: Path) -> list[Path]:
    return collect_skill_md_under_repo(repo)


def _hermes_external_dirs(cfg_path: Path) -> list[str]:
    doc = _read_yaml(cfg_path)
    skills = doc.get("skills") if isinstance(doc.get("skills"), dict) else {}
    raw = skills.get("external_dirs") if isinstance(skills.get("external_dirs"), list) else []
    return [str(x) for x in raw if isinstance(x, str) and x.strip()]


def _short_hash(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return hashlib.sha256(data).hexdigest()[:16]


def _make_key(org: str, slug: str) -> str:
    o = org.strip().lower() or "hors-org"
    s = slug.strip().lower() or "unknown"
    return f"{o}:{s}"


def _normalize_skill_entry(raw: dict[str, Any]) -> dict[str, Any]:
    key = str(raw.get("key") or "").strip()
    org = str(raw.get("org") or "hors-org").strip() or "hors-org"
    slug = str(raw.get("slug") or "").strip() or (key.split(":", 1)[1] if ":" in key else "unknown")
    if not key:
        key = _make_key(org, slug)
    status = str(raw.get("status") or "candidate").strip().lower()
    if status not in ("candidate", "adopted", "mirrored", "published", "ignored", "conflict"):
        status = "candidate"
    sources = raw.get("sources")
    if not isinstance(sources, list):
        sources = []
    norm_sources: list[dict[str, Any]] = []
    for s in sources:
        if not isinstance(s, dict):
            continue
        kind = str(s.get("kind") or "workspace").strip().lower()
        if kind not in (
            "mirror",
            "workspace",
            "cursor_global",
            "claude_global",
            "kimi_global",
            "hermes_external",
            "config_legacy",
        ):
            kind = "workspace"
        p = str(s.get("path") or "").strip()
        if not p:
            continue
        norm_sources.append(
            {
                "kind": kind,
                "path": p,
                "project": str(s.get("project") or "").strip() or None,
                "last_seen_at": str(s.get("last_seen_at") or _utc_now()),
            }
        )
    sync = raw.get("sync") if isinstance(raw.get("sync"), dict) else {}
    return {
        "key": key,
        "org": org,
        "slug": slug,
        "status": status,
        "canonical_path": raw.get("canonical_path"),
        "sources": norm_sources,
        "sync": sync,
        "tags": raw.get("tags") if isinstance(raw.get("tags"), list) else [],
        "description": raw.get("description"),
        "frontmatter_name": raw.get("frontmatter_name"),
    }


def load_registry_document() -> dict[str, Any]:
    p = registry_path()
    if not p.is_file():
        return {"version": REGISTRY_VERSION, "updated_at": _utc_now(), "skills": []}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"version": REGISTRY_VERSION, "updated_at": _utc_now(), "skills": []}
    if not isinstance(raw, dict):
        return {"version": REGISTRY_VERSION, "updated_at": _utc_now(), "skills": []}
    skills = raw.get("skills")
    if not isinstance(skills, list):
        skills = []
    raw["skills"] = [_normalize_skill_entry(dict(x)) for x in skills if isinstance(x, dict)]
    raw["version"] = int(raw.get("version") or REGISTRY_VERSION)
    return raw


def save_registry_document(doc: dict[str, Any]) -> Path:
    p = registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    doc = dict(doc)
    doc["version"] = REGISTRY_VERSION
    doc["updated_at"] = _utc_now()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, p)
    return p


def _skills_by_key(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for s in doc.get("skills") or []:
        if not isinstance(s, dict):
            continue
        k = str(s.get("key") or "").strip()
        if k:
            out[k] = s
    return out


def _write_skills_dict(doc: dict[str, Any], by_key: dict[str, dict[str, Any]]) -> None:
    doc["skills"] = sorted(by_key.values(), key=lambda x: str(x.get("key") or "").lower())


def _ensure_registry_file_exists() -> Path:
    """Crée skills-registry.json + migration YAML si absent."""
    p = registry_path()
    if p.is_file():
        return p
    doc = _migrate_from_legacy_config()
    save_registry_document(doc)
    _strip_legacy_inventory_keys_if_present()
    return p


def ensure_registry_and_migrate() -> Path:
    return _ensure_registry_file_exists()


def _migrate_from_legacy_config() -> dict[str, Any]:
    cfg = load_user_config()
    by_key: dict[str, dict[str, Any]] = {}
    legacy_paths: list[str] = []
    raw = cfg.get("skill_md_paths")
    if isinstance(raw, list):
        for x in raw:
            if isinstance(x, str) and x.strip():
                legacy_paths.append(x.strip())
    for s in legacy_paths:
        try:
            md = Path(s).expanduser().resolve()
        except OSError:
            continue
        if not md.is_file() or md.name != "SKILL.md":
            continue
        slug = md.parent.name
        org = "hors-org"
        settings = skills_sync_settings()
        try:
            rr = Path(str(settings["repo_root"])).expanduser().resolve()
            hint = _infer_org_from_mirror(md, rr)
            if hint:
                org = hint
        except OSError:
            pass
        key = _make_key(org, slug)
        by_key[key] = {
            "key": key,
            "org": org,
            "slug": slug,
            "status": "adopted",
            "canonical_path": str(md),
            "sources": [{"kind": "config_legacy", "path": str(md), "project": None, "last_seen_at": _utc_now()}],
            "sync": {},
            "tags": [],
            "description": None,
            "frontmatter_name": None,
        }
    return {"version": REGISTRY_VERSION, "updated_at": _utc_now(), "skills": list(by_key.values())}


def _strip_legacy_inventory_keys_if_present() -> None:
    cfg = load_user_config()
    if not isinstance(cfg, dict):
        return
    if "skill_md_paths" not in cfg:
        return
    cfg = dict(cfg)
    cfg.pop("skill_md_paths", None)
    # claude_plugin_paths reste utile pour les plugins — le plan demande de retirer les deux au profit du registre pour skills ;
    # on conserve claude_plugin_paths si l’utilisateur en avait (non couvert par le registre skills).
    save_user_config(cfg)


def _backup_user_config() -> Path | None:
    src = user_config_path()
    if not src.is_file():
        return None
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dst = src.with_suffix(src.suffix + f".bak.{ts}")
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return dst


def migrate_strip_legacy_keys_from_config(*, force_backup: bool = True) -> dict[str, Any]:
    """Retire skill_md_paths du YAML après migration (sauvegarde horodatée si demandé)."""
    cfg = load_user_config()
    if "skill_md_paths" not in cfg:
        return {"changed": False, "backup_path": None}
    if force_backup:
        backup = _backup_user_config()
    else:
        backup = None
    cfg = dict(cfg)
    cfg.pop("skill_md_paths", None)
    save_user_config(cfg)
    log = data_dir() / "skills-registry-migration.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as fh:
        fh.write(f"{_utc_now()} stripped skill_md_paths backup={backup}\n")
    return {"changed": True, "backup_path": str(backup) if backup else None}


def adopted_skill_md_paths_resolved() -> list[Path]:
    """Chemins SKILL.md exposés agents / MCP (statuts adopted|mirrored|published)."""
    _ensure_registry_file_exists()
    doc = load_registry_document()
    out: list[Path] = []
    seen: set[str] = set()
    for s in doc.get("skills") or []:
        if not isinstance(s, dict):
            continue
        if str(s.get("status") or "") not in ("adopted", "mirrored", "published"):
            continue
        cp = s.get("canonical_path")
        if not isinstance(cp, str) or not cp.strip():
            continue
        try:
            p = Path(cp).expanduser().resolve()
        except OSError:
            continue
        if not p.is_file():
            continue
        k = str(p)
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
    return out


def allowed_absolute_skill_paths_for_api() -> set[str]:
    """Chemins absolus autorisés pour lecture/écriture SKILL (hors dépôt relatif)."""
    _ensure_registry_file_exists()
    doc = load_registry_document()
    allowed: set[str] = set()
    for s in doc.get("skills") or []:
        if not isinstance(s, dict):
            continue
        if str(s.get("status") or "").lower() == "ignored":
            continue
        cp = s.get("canonical_path")
        if isinstance(cp, str) and cp.strip():
            try:
                allowed.add(str(Path(cp).expanduser().resolve()))
            except OSError:
                allowed.add(cp.strip())
        for src in s.get("sources") or []:
            if not isinstance(src, dict):
                continue
            p = src.get("path")
            if isinstance(p, str) and p.strip():
                try:
                    allowed.add(str(Path(p).expanduser().resolve()))
                except OSError:
                    allowed.add(p.strip())
    return allowed


def query_registry(
    *,
    status: str | None = None,
    org: str | None = None,
    project: str | None = None,
) -> list[dict[str, Any]]:
    doc = load_registry_document()
    st = status.strip().lower() if isinstance(status, str) and status.strip() else None
    org_n = org.strip().lower() if isinstance(org, str) and org.strip() else None
    proj_n = project.strip().lower() if isinstance(project, str) and project.strip() else None
    rows: list[dict[str, Any]] = []
    for s in doc.get("skills") or []:
        if not isinstance(s, dict):
            continue
        if st and str(s.get("status") or "").lower() != st:
            continue
        if org_n and str(s.get("org") or "").lower() != org_n:
            continue
        if proj_n:
            hay = " ".join(
                str(x.get("project") or "") + " " + str(x.get("path") or "")
                for x in (s.get("sources") or [])
                if isinstance(x, dict)
            ).lower()
            if proj_n not in hay:
                continue
        rows.append(dict(s))
    rows.sort(key=lambda x: str(x.get("key") or "").lower())
    return rows


def _merge_source(entry: dict[str, Any], *, kind: str, path: str, project: str | None) -> None:
    sources: list[dict[str, Any]] = list(entry.get("sources") or [])
    try:
        path_res = str(Path(path).expanduser().resolve())
    except OSError:
        path_res = path
    for i, src in enumerate(sources):
        if not isinstance(src, dict):
            continue
        if str(src.get("path") or "").strip() == path_res or str(src.get("path") or "").strip() == path.strip():
            sources[i] = {
                **src,
                "kind": kind,
                "path": path_res,
                "project": project or src.get("project"),
                "last_seen_at": _utc_now(),
            }
            entry["sources"] = sources
            return
    sources.append(
        {
            "kind": kind,
            "path": path_res,
            "project": project,
            "last_seen_at": _utc_now(),
        }
    )
    entry["sources"] = sources


def refresh_registry_from_disk() -> dict[str, Any]:
    """Upsert des sources depuis miroir, workspace, agents globaux, Hermes (lecture)."""
    _ensure_registry_file_exists()
    doc = load_registry_document()
    by_key = _skills_by_key(doc)

    settings = skills_sync_settings()
    repo_root = Path(str(settings["repo_root"])).expanduser().resolve()
    hermes_cfg = Path(str(settings["hermes_config_path"])).expanduser().resolve()

    for md in _collect_skill_md_under_repo(repo_root):
        org = _infer_org_from_mirror(md, repo_root) or "common"
        slug = md.parent.name
        key = _make_key(org, slug)
        entry = by_key.get(key) or {
            "key": key,
            "org": org,
            "slug": slug,
            "status": "candidate",
            "canonical_path": None,
            "sources": [],
            "sync": {},
            "tags": [],
            "description": None,
            "frontmatter_name": None,
        }
        if str(entry.get("status") or "") == "ignored":
            by_key[key] = entry
            continue
        _merge_source(entry, kind="mirror", path=str(md.resolve()), project=None)
        if str(entry.get("status") or "") == "candidate" and not entry.get("canonical_path"):
            entry["canonical_path"] = str(md.resolve())
        by_key[key] = entry

    from zab.services.workspace_projects import discover_projects

    for proj in discover_projects():
        org_raw = str(proj.get("org") or "hors-org")
        project_name = str(proj.get("name") or "")
        for row in proj.get("skills") or []:
            if not isinstance(row, dict):
                continue
            ap = str(row.get("path") or "")
            if not ap:
                continue
            try:
                md = Path(ap).expanduser().resolve()
            except OSError:
                continue
            if not md.is_file() or md.name != "SKILL.md":
                continue
            slug = str(row.get("id") or md.parent.name)
            key = _make_key(org_raw, slug)
            entry = by_key.get(key) or {
                "key": key,
                "org": org_raw,
                "slug": slug,
                "status": "candidate",
                "canonical_path": None,
                "sources": [],
                "sync": {},
                "tags": [],
                "description": None,
                "frontmatter_name": None,
            }
            if str(entry.get("status") or "") == "ignored":
                by_key[key] = entry
                continue
            _merge_source(entry, kind="workspace", path=str(md), project=project_name or None)
            by_key[key] = entry

    home = Path.home()
    for agent, kind in (
        (home / ".cursor" / "skills", "cursor_global"),
        (home / ".claude" / "skills", "claude_global"),
        (home / ".kimi" / "skills", "kimi_global"),
    ):
        org_slug = kind.replace("_global", "")
        for md in iter_skill_md_recursive(agent):
            slug = md.parent.name
            key = _make_key(org_slug, slug)
            entry = by_key.get(key) or {
                "key": key,
                "org": org_slug,
                "slug": slug,
                "status": "candidate",
                "canonical_path": None,
                "sources": [],
                "sync": {},
                "tags": [],
                "description": None,
                "frontmatter_name": None,
            }
            if str(entry.get("status") or "") == "ignored":
                by_key[key] = entry
                continue
            _merge_source(entry, kind=kind, path=str(md.resolve()), project=None)
            by_key[key] = entry

    for d in _hermes_external_dirs(hermes_cfg):
        p = Path(d).expanduser()
        if not p.is_dir():
            continue
        for md in iter_skill_md_recursive(p):
            slug = md.parent.name
            org = _infer_org_from_mirror(md, repo_root) or "hermes"
            key = _make_key(org, slug)
            entry = by_key.get(key) or {
                "key": key,
                "org": org,
                "slug": slug,
                "status": "candidate",
                "canonical_path": None,
                "sources": [],
                "sync": {},
                "tags": [],
                "description": None,
                "frontmatter_name": None,
            }
            if str(entry.get("status") or "") == "ignored":
                by_key[key] = entry
                continue
            _merge_source(entry, kind="hermes_external", path=str(md.resolve()), project=None)
            by_key[key] = entry

    _recompute_hashes_and_conflicts(by_key, repo_root=repo_root, hermes_cfg=hermes_cfg)
    _write_skills_dict(doc, by_key)
    save_registry_document(doc)
    path = registry_path()
    return {"registry_path": str(path), "skills_count": len(by_key)}


def _recompute_hashes_and_conflicts(
    by_key: dict[str, dict[str, Any]],
    *,
    repo_root: Path,
    hermes_cfg: Path,
) -> None:
    hermes_dirs_resolved: set[str] = set()
    for d in _hermes_external_dirs(hermes_cfg):
        try:
            hermes_dirs_resolved.add(str(Path(d).expanduser().resolve()))
        except OSError:
            continue

    for entry in by_key.values():
        if str(entry.get("status") or "") == "ignored":
            continue
        hashes: list[str] = []
        for src in entry.get("sources") or []:
            if not isinstance(src, dict):
                continue
            p = src.get("path")
            if not isinstance(p, str) or not p.strip():
                continue
            try:
                pp = Path(p).expanduser().resolve()
            except OSError:
                continue
            if pp.is_file():
                h = _short_hash(pp)
                if h:
                    hashes.append(h)
        uniq = {x for x in hashes}
        st = str(entry.get("status") or "candidate")
        if len(uniq) >= 2 and st not in ("ignored",):
            entry["status"] = "conflict"
        cp = entry.get("canonical_path")
        mirror_present = False
        hermes_exposed = False
        if isinstance(cp, str) and cp.strip():
            try:
                cpr = Path(cp).expanduser().resolve()
                if cpr.is_file():
                    mirror_present = _path_under_repo(cpr, repo_root)
                    parent = str(cpr.parent.resolve())
                    for hd in hermes_dirs_resolved:
                        if parent == hd or parent.startswith(hd + os.sep):
                            hermes_exposed = True
                            break
            except OSError:
                pass
        sync = dict(entry.get("sync") or {})
        sync["mirror"] = {"present": mirror_present}
        sync["hermes"] = {"exposed": hermes_exposed}
        entry["sync"] = sync


def _path_under_repo(p: Path, repo: Path) -> bool:
    try:
        p.resolve().relative_to(repo.resolve())
        return True
    except ValueError:
        return False


def adopt_registry_key(key: str, *, canonical_path: str | None = None) -> dict[str, Any]:
    _ensure_registry_file_exists()
    doc = load_registry_document()
    by_key = _skills_by_key(doc)
    entry = by_key.get(key.strip())
    if not entry:
        return {"ok": False, "error": "unknown_key"}
    if str(entry.get("status") or "") == "ignored":
        return {"ok": False, "error": "ignored_entry"}
    cp = canonical_path
    if not cp:
        for src in entry.get("sources") or []:
            if isinstance(src, dict) and str(src.get("kind") or "") == "mirror":
                cp = str(src.get("path") or "")
                if cp:
                    break
        if not cp:
            for src in entry.get("sources") or []:
                if isinstance(src, dict):
                    cp = str(src.get("path") or "")
                    if cp:
                        break
    entry["status"] = "adopted"
    if cp:
        entry["canonical_path"] = str(Path(cp).expanduser().resolve())
    _write_skills_dict(doc, by_key)
    save_registry_document(doc)
    return {"ok": True, "entry": entry}


def unadopt_registry_key(key: str) -> dict[str, Any]:
    _ensure_registry_file_exists()
    doc = load_registry_document()
    by_key = _skills_by_key(doc)
    entry = by_key.get(key.strip())
    if not entry:
        return {"ok": False, "error": "unknown_key"}
    entry["status"] = "candidate"
    entry["canonical_path"] = None
    _write_skills_dict(doc, by_key)
    save_registry_document(doc)
    return {"ok": True, "entry": entry}


def ignore_registry_key(key: str) -> dict[str, Any]:
    _ensure_registry_file_exists()
    doc = load_registry_document()
    by_key = _skills_by_key(doc)
    entry = by_key.get(key.strip())
    if not entry:
        return {"ok": False, "error": "unknown_key"}
    entry["status"] = "ignored"
    _write_skills_dict(doc, by_key)
    save_registry_document(doc)
    return {"ok": True, "entry": entry}


def unignore_registry_key(key: str) -> dict[str, Any]:
    _ensure_registry_file_exists()
    doc = load_registry_document()
    by_key = _skills_by_key(doc)
    entry = by_key.get(key.strip())
    if not entry:
        return {"ok": False, "error": "unknown_key"}
    entry["status"] = "candidate"
    _write_skills_dict(doc, by_key)
    save_registry_document(doc)
    return {"ok": True, "entry": entry}


def resolve_conflict_keep_path(key: str, keep_path: str) -> dict[str, Any]:
    _ensure_registry_file_exists()
    doc = load_registry_document()
    by_key = _skills_by_key(doc)
    entry = by_key.get(key.strip())
    if not entry:
        return {"ok": False, "error": "unknown_key"}
    try:
        keep = Path(keep_path).expanduser().resolve()
    except OSError:
        return {"ok": False, "error": "bad_path"}
    if not keep.is_file():
        return {"ok": False, "error": "not_a_file"}
    new_sources: list[dict[str, Any]] = []
    for src in entry.get("sources") or []:
        if not isinstance(src, dict):
            continue
        try:
            sp = Path(str(src.get("path") or "")).expanduser().resolve()
        except OSError:
            continue
        if sp == keep:
            new_sources.append({**src, "last_seen_at": _utc_now()})
    if not new_sources:
        new_sources.append({"kind": "workspace", "path": str(keep), "project": None, "last_seen_at": _utc_now()})
    entry["sources"] = new_sources
    entry["status"] = "adopted"
    entry["canonical_path"] = str(keep)
    entry.pop("conflict", None)
    _write_skills_dict(doc, by_key)
    save_registry_document(doc)
    return {"ok": True, "entry": entry}


def register_mirror_skill_path(path: str | Path) -> Path:
    """Après import vers le miroir : adopte l’entrée registre correspondante."""
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        return registry_path()
    settings = skills_sync_settings()
    repo_root = Path(str(settings["repo_root"])).expanduser().resolve()
    org = _infer_org_from_mirror(p, repo_root) or "common"
    slug = p.parent.name
    key = _make_key(org, slug)
    _ensure_registry_file_exists()
    refresh_registry_from_disk()
    doc = load_registry_document()
    by_key = _skills_by_key(doc)
    entry = by_key.get(key) or {
        "key": key,
        "org": org,
        "slug": slug,
        "status": "adopted",
        "canonical_path": str(p),
        "sources": [],
        "sync": {},
        "tags": [],
        "description": None,
        "frontmatter_name": None,
    }
    by_key[key] = entry
    _merge_source(entry, kind="mirror", path=str(p), project=None)
    entry["status"] = "mirrored"
    entry["canonical_path"] = str(p)
    _write_skills_dict(doc, by_key)
    save_registry_document(doc)
    return registry_path()


def hermes_export_yaml_fragment() -> str:
    from zab.services.hermes_config import discover_hermes_external_dirs

    settings = skills_sync_settings()
    repo = Path(str(settings["repo_root"])).expanduser().resolve()
    dirs = discover_hermes_external_dirs(repo)
    lines = ["skills:", "  external_dirs:"]
    for d in dirs:
        lines.append(f"    - {d}")
    return "\n".join(lines) + "\n"


def registry_counts() -> dict[str, int]:
    doc = load_registry_document()
    c = {"candidate": 0, "adopted": 0, "mirrored": 0, "published": 0, "ignored": 0, "conflict": 0, "total": 0}
    for s in doc.get("skills") or []:
        if not isinstance(s, dict):
            continue
        st = str(s.get("status") or "candidate").lower()
        c["total"] += 1
        if st in c:
            c[st] += 1
    return c
