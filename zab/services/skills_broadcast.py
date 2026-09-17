"""Diffuse l'inventaire de skills (Hermes + external_dirs) vers d'autres CLIs.

Cible actuelle :
- ``claude`` : symlinks plats sous ``~/.claude/skills/<name>`` vers le SKILL.md
  parent, avec marqueur ``.zab-managed.json`` pour ne toucher qu'aux entrées
  posées par zab. Skips silencieusement les entrées préexistantes non
  managées (skills perso, symlinks vers ``.agents/skills``).
- ``kimi`` : remplace la clé ``extra_skill_dirs`` dans ``~/.kimi/config.toml``
  par la liste des roots agrégés (preserve les autres lignes via regex,
  pas de round-trip TOML qui mangerait les commentaires).

Le périmètre des skills est :
- ``~/.hermes/skills/``
- Chaque entrée de ``skills.external_dirs`` dans ``~/.hermes/config.yaml``
- ``~/.config/secondbrain/skills/`` (skills perso versionnés)

Politique d'exposition (``~/.config/zab/skills-policy.yml``, ou ``$ZAB_SKILLS_POLICY``) :
un skill global est chargé dans **chaque** session Claude, quel que soit le projet, et
il gagne sur un skill de projet du même nom. Diffuser tout le magasin Hermes revient
donc à charger ses skills internes partout, et à masquer les versions à jour des skills
de projet par des copies plus anciennes. Avec ``claude.mode: allowlist``, seuls les noms de
``claude.global`` sont diffusés ; les autres entrées managées sont retirées au passage
suivant. Sans fichier, ou avec ``mode: all``, le comportement historique est conservé.

Idempotent. Safe à appeler depuis cron / launchd quotidien.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from zab.services.skills_scan import iter_skill_md_recursive

CLAUDE_SKILLS_DIR = Path("~/.claude/skills").expanduser()
KIMI_CONFIG_PATH = Path("~/.kimi/config.toml").expanduser()
HERMES_CONFIG_PATH = Path("~/.hermes/config.yaml").expanduser()
SECONDBRAIN_SKILLS_DIR = Path("~/.config/secondbrain/skills").expanduser()
MARKER_FILENAME = ".zab-managed.json"
HERMES_DEFAULT_SKILLS_ROOT = Path("~/.hermes/skills").expanduser()
DEFAULT_POLICY_PATH = Path("~/.config/zab/skills-policy.yml")


@dataclass
class ClaudeResult:
    target: str = "claude"
    skills_dir: str = ""
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    skipped_existing: list[str] = field(default_factory=list)
    skipped_dup_name: list[str] = field(default_factory=list)
    policy: str = "all"
    filtered_out: int = 0
    allowlist_missing: list[str] = field(default_factory=list)
    total_desired: int = 0
    total_managed: int = 0
    dry_run: bool = False


@dataclass
class KimiResult:
    target: str = "kimi"
    config_path: str = ""
    extra_skill_dirs: list[str] = field(default_factory=list)
    changed: bool = False
    dry_run: bool = False


@dataclass
class BroadcastResult:
    roots: list[str] = field(default_factory=list)
    skill_count: int = 0
    targets: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False


def discover_skill_roots() -> list[Path]:
    roots: list[Path] = []
    if HERMES_DEFAULT_SKILLS_ROOT.is_dir():
        roots.append(HERMES_DEFAULT_SKILLS_ROOT)
    if HERMES_CONFIG_PATH.is_file():
        try:
            data = yaml.safe_load(HERMES_CONFIG_PATH.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            data = {}
        external = ((data.get("skills") or {}).get("external_dirs")) or []
        for entry in external:
            if not isinstance(entry, str):
                continue
            p = Path(entry).expanduser()
            if p.is_dir() and p not in roots:
                roots.append(p)
    if SECONDBRAIN_SKILLS_DIR.is_dir() and SECONDBRAIN_SKILLS_DIR not in roots:
        roots.append(SECONDBRAIN_SKILLS_DIR)
    return roots


def enumerate_skills(roots: list[Path]) -> tuple[list[tuple[str, Path]], list[str]]:
    """(name, abs_path_to_skill_dir). First-wins on name collisions; dupes returned separately."""
    seen: dict[str, Path] = {}
    dupes: list[str] = []
    for root in roots:
        for skill_md in iter_skill_md_recursive(root):
            skill_dir = skill_md.parent
            name = skill_dir.name
            if name in seen:
                if seen[name] != skill_dir:
                    dupes.append(f"{name} (kept {seen[name]}, ignored {skill_dir})")
                continue
            seen[name] = skill_dir
    return sorted(seen.items()), dupes


def policy_path() -> Path:
    return Path(os.environ.get("ZAB_SKILLS_POLICY") or DEFAULT_POLICY_PATH).expanduser()


def load_claude_allowlist(path: Path | None = None) -> set[str] | None:
    """Noms autorisés en global pour Claude, ou ``None`` si tout est diffusé.

    Un fichier illisible ne doit pas vider ``~/.claude/skills`` : il lève, et le
    passage quotidien échoue bruyamment au lieu de tout retirer en silence.
    """
    path = path or policy_path()
    if not path.is_file():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    claude = data.get("claude") or {}
    if (claude.get("mode") or "all") != "allowlist":
        return None
    names = claude.get("global")
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise ValueError(f"{path} : claude.global doit être une liste de noms de skills")
    return {n.strip() for n in names if n.strip()}


def _read_marker(marker_path: Path) -> dict[str, str]:
    if not marker_path.is_file():
        return {}
    try:
        data = json.loads(marker_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    syms = data.get("symlinks") if isinstance(data, dict) else None
    return syms if isinstance(syms, dict) else {}


def broadcast_claude(
    skills: list[tuple[str, Path]],
    *,
    target_dir: Path = CLAUDE_SKILLS_DIR,
    dry_run: bool = False,
    allowlist: set[str] | None = None,
) -> ClaudeResult:
    result = ClaudeResult(skills_dir=str(target_dir), dry_run=dry_run)
    if allowlist is not None:
        available = {name for name, _ in skills}
        result.policy = "allowlist"
        result.filtered_out = sum(1 for name, _ in skills if name not in allowlist)
        result.allowlist_missing = sorted(allowlist - available)
        skills = [(name, path) for name, path in skills if name in allowlist]
    result.total_desired = len(skills)
    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)
    marker_path = target_dir / MARKER_FILENAME
    prior_managed = _read_marker(marker_path) if target_dir.exists() else {}
    desired = {name: str(path.resolve()) for name, path in skills}
    new_managed: dict[str, str] = {}

    for name, target_path in desired.items():
        link = target_dir / name
        if link.is_symlink():
            current = str(Path(link).resolve()) if link.exists() else ""
            if current == target_path:
                new_managed[name] = target_path
                continue
            if name in prior_managed:
                if not dry_run:
                    link.unlink()
                    link.symlink_to(target_path)
                result.updated.append(name)
                new_managed[name] = target_path
            else:
                # Symlink pre-existant pointant ailleurs (.agents/skills/...) — on respecte.
                result.skipped_existing.append(name)
            continue
        if link.exists():
            # Vrai dossier / fichier — on respecte.
            result.skipped_existing.append(name)
            continue
        # Pas d'entrée — on crée.
        if not dry_run:
            link.symlink_to(target_path)
        result.created.append(name)
        new_managed[name] = target_path

    # Cleanup : entrées zab-managed qui n'existent plus dans la source.
    for name in prior_managed:
        if name in desired:
            continue
        link = target_dir / name
        if link.is_symlink():
            if not dry_run:
                link.unlink()
            result.removed.append(name)

    if not dry_run:
        marker_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "updated_at_utc": datetime.now(timezone.utc).isoformat(),
                    "managed_by": "zab skill broadcast",
                    "symlinks": new_managed,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    result.total_managed = len(new_managed)
    return result


def broadcast_kimi(
    roots: list[Path],
    *,
    config_path: Path = KIMI_CONFIG_PATH,
    dry_run: bool = False,
) -> KimiResult:
    paths = [str(r) for r in roots]
    result = KimiResult(config_path=str(config_path), extra_skill_dirs=paths, dry_run=dry_run)
    if not config_path.is_file():
        return result
    text = config_path.read_text(encoding="utf-8")
    paths_inline = ", ".join(f'"{p}"' for p in paths)
    new_line = f"extra_skill_dirs = [{paths_inline}]"
    pattern = re.compile(r"^extra_skill_dirs\s*=\s*\[[^\]]*\]", re.MULTILINE)
    if pattern.search(text):
        new_text = pattern.sub(new_line, text, count=1)
    else:
        new_text = text.rstrip() + "\n" + new_line + "\n"
    if new_text != text:
        result.changed = True
        if not dry_run:
            config_path.write_text(new_text, encoding="utf-8")
    return result


def broadcast(
    targets: list[str] | None = None,
    *,
    dry_run: bool = False,
) -> BroadcastResult:
    targets = targets or ["claude", "kimi"]
    roots = discover_skill_roots()
    skills, _dupes = enumerate_skills(roots)
    result = BroadcastResult(
        roots=[str(r) for r in roots],
        skill_count=len(skills),
        dry_run=dry_run,
    )
    if "claude" in targets:
        result.targets["claude"] = broadcast_claude(
            skills, dry_run=dry_run, allowlist=load_claude_allowlist()
        ).__dict__
    if "kimi" in targets:
        result.targets["kimi"] = broadcast_kimi(roots, dry_run=dry_run).__dict__
    return result
