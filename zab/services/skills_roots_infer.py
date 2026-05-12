"""Déduit des racines « dépôt skills » (dossiers contenant orgs/) depuis les SKILL.md trouvés au scan."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from zab.paths import data_dir


PROPOSED_FILENAME = "scan-proposed-skills-roots.yaml"


def proposed_roots_path() -> Path:
    return data_dir() / PROPOSED_FILENAME


def _ancestors_chain_from_skill_to_scan_base(leaf_dir: Path, scan_base: Path) -> list[Path]:
    """Chaîne leaf_dir → … → scan_base (inclus si sous-arbre)."""
    start = leaf_dir.resolve()
    base_r = scan_base.resolve()
    try:
        start.relative_to(base_r)
    except ValueError:
        return [base_r]

    out: list[Path] = []
    cur: Path | None = start
    while cur is not None:
        out.append(cur)
        if cur == base_r:
            break
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    if base_r not in out:
        out.append(base_r)
    return out


def infer_skills_repo_roots(scan_base: Path, skill_md_relative_paths: list[str]) -> list[Path]:
    """
    Pour chaque SKILL.md (chemin relatif au répertoire scanné), remonte jusqu’à trouver
    un ancêtre qui contient ``orgs/``, sinon utilise la racine de scan.
    """
    base_r = scan_base.resolve()
    dedup: dict[str, Path] = {}
    for rel in skill_md_relative_paths:
        rel_s = str(rel).replace("\\", "/").strip()
        if not rel_s:
            continue
        full_md = (base_r / rel_s).resolve()
        if not full_md.is_file():
            continue
        chain = _ancestors_chain_from_skill_to_scan_base(full_md.parent, base_r)
        chosen = base_r
        for c in chain:
            try:
                if (c / "orgs").is_dir():
                    chosen = c.resolve()
                    break
            except OSError:
                continue
        key = str(chosen)
        if key not in dedup:
            dedup[key] = chosen
    return sorted(dedup.values(), key=lambda p: str(p).lower())


def persist_proposed_roots(
    *,
    scan_root: Path,
    roots: list[Path],
    skill_md_abs_paths: list[str],
    claude_plugin_abs_paths: list[str],
    skill_md_count: int,
    skill_samples: list[str],
) -> Path:
    data_dir().mkdir(parents=True, exist_ok=True)
    p = proposed_roots_path()
    envelope: dict[str, Any] = {
        "proposed_at_utc": datetime.now(timezone.utc).isoformat(),
        "scan_root": str(scan_root.resolve()),
        "skill_md_count": skill_md_count,
        "skill_md_samples": skill_samples[:40],
        "roots": [str(r.resolve()) for r in roots],
        "skill_md_paths": sorted({str(Path(x).expanduser().resolve()) for x in skill_md_abs_paths if x and str(x).strip()}),
        "claude_plugin_paths": sorted({str(Path(x).expanduser().resolve()) for x in claude_plugin_abs_paths if x and str(x).strip()}),
    }
    p.write_text(yaml.safe_dump(envelope, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return p


def load_proposed_roots() -> dict[str, Any] | None:
    p = proposed_roots_path()
    if not p.is_file():
        return None
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except (yaml.YAMLError, OSError):
        return None


def roots_from_proposal(doc: dict[str, Any]) -> list[str]:
    raw = doc.get("roots")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for x in raw:
        if isinstance(x, str) and x.strip():
            out.append(x.strip())
    return out


def skill_md_paths_from_proposal(doc: dict[str, Any]) -> list[str]:
    raw = doc.get("skill_md_paths")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for x in raw:
        if isinstance(x, str) and x.strip():
            out.append(x.strip())
    return out


def claude_plugin_paths_from_proposal(doc: dict[str, Any]) -> list[str]:
    raw = doc.get("claude_plugin_paths")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for x in raw:
        if isinstance(x, str) and x.strip():
            out.append(x.strip())
    return out
