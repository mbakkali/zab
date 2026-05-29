"""Pont de configuration entre zab et Hermes."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from zab.user_config import skills_sync_settings


@dataclass
class HermesConfigResult:
    config_path: str
    external_dirs: list[str]
    changed: bool
    dry_run: bool
    backup_path: str | None = None


def discover_hermes_external_dirs(repo_root: str | Path | None = None) -> list[str]:
    settings = skills_sync_settings()
    root = Path(repo_root or settings["repo_root"]).expanduser().resolve()
    orgs = root / "orgs"
    out: list[str] = []
    common = root / "common" / "skills"
    if common.is_dir():
        out.append(str(common.resolve()))
    if not orgs.is_dir():
        return out
    for org_dir in sorted(orgs.iterdir(), key=lambda p: p.name.casefold()):
        skills_dir = org_dir / "skills"
        if not skills_dir.is_dir():
            continue
        out.append(str(skills_dir.resolve()))
    return out


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return raw if isinstance(raw, dict) else {}


def _write_yaml_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    os.replace(tmp, path)


def update_external_dirs(
    *,
    config_path: str | Path | None = None,
    repo_root: str | Path | None = None,
    apply: bool = False,
) -> HermesConfigResult:
    settings = skills_sync_settings()
    cfg_path = Path(config_path or settings["hermes_config_path"]).expanduser().resolve()
    desired = discover_hermes_external_dirs(repo_root or settings["repo_root"])
    doc = _read_yaml(cfg_path)
    skills = doc.get("skills") if isinstance(doc.get("skills"), dict) else {}
    current = skills.get("external_dirs") if isinstance(skills.get("external_dirs"), list) else []
    current_norm = [str(x) for x in current]
    changed = current_norm != desired
    backup: str | None = None
    if changed and apply:
        if cfg_path.is_file():
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_path = cfg_path.with_suffix(cfg_path.suffix + f".bak.{ts}")
            backup_path.write_text(cfg_path.read_text(encoding="utf-8"), encoding="utf-8")
            backup = str(backup_path)
        doc["skills"] = {**skills, "external_dirs": desired}
        _write_yaml_atomic(cfg_path, doc)
    return HermesConfigResult(
        config_path=str(cfg_path),
        external_dirs=desired,
        changed=changed,
        dry_run=not apply,
        backup_path=backup,
    )
