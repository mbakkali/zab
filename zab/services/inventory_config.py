"""Chemins explicites SKILL.md / bundles Claude (config.yaml) — inférences pour MCP et plugins."""

from __future__ import annotations

from pathlib import Path


def infer_claude_plugin_bundle_root(skill_md: Path) -> Path | None:
    """Remonte depuis le SKILL.md jusqu’au dossier plugin (contient ``.claude-plugin/plugin.json``)."""
    cur = skill_md.resolve().parent
    for _ in range(64):
        try:
            meta = cur / ".claude-plugin" / "plugin.json"
            if meta.is_file():
                return cur
        except OSError:
            break
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    return None


def infer_mcp_repo_base_from_skill_md(skill_md: Path) -> Path | None:
    """Remonte jusqu’à un dossier qui contient ``configs/cursor-mcp.json`` (dépôt skills classique)."""
    cur = skill_md.resolve().parent
    for _ in range(64):
        try:
            cfg = cur / "configs" / "cursor-mcp.json"
            if cfg.is_file():
                return cur
        except OSError:
            break
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    return None


def collect_plugin_roots_from_skill_paths(skill_mds: list[Path]) -> list[Path]:
    seen: dict[str, Path] = {}
    for md in skill_mds:
        try:
            r = infer_claude_plugin_bundle_root(md)
        except OSError:
            continue
        if r is None:
            continue
        key = str(r.resolve())
        if key not in seen:
            seen[key] = r.resolve()
    return sorted(seen.values(), key=lambda p: str(p).lower())
