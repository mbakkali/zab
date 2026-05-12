"""Chemins du projet zab — package installable, données XDG, racine skills configurable."""

from __future__ import annotations

import os
from pathlib import Path


def xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser().resolve()


def xdg_data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", "~/.local/share")).expanduser().resolve()


def config_dir() -> Path:
    """~/.config/zab/"""
    return xdg_config_home() / "zab"


def data_dir() -> Path:
    """~/.local/share/zab/"""
    return xdg_data_home() / "zab"


def zab_repo_root() -> Path:
    """Racine du dépôt zab (parent du package Python `zab/`)."""
    return Path(__file__).resolve().parent.parent


def zab_ui_dist_dir() -> Path:
    """SPA buildée : zab-ui/dist à côté du package (même clone que le dépôt zab)."""
    env = os.environ.get("ZAB_UI_DIST", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return zab_repo_root() / "zab-ui" / "dist"


def zab_package_dir() -> Path:
    return Path(__file__).resolve().parent


def resolve_skills_root() -> tuple[Path, str]:
    """
    Retourne le répertoire skills effectif et une courte étiquette indiquant la règle appliquée.
    """
    env = os.environ.get("ZAB_SKILLS_ROOT", "").strip()
    if env:
        return Path(env).expanduser().resolve(), "variable d'environnement ZAB_SKILLS_ROOT"

    try:
        from zab.user_config import skills_root_from_user_config

        cfg_path = skills_root_from_user_config()
        if cfg_path:
            return Path(cfg_path).expanduser().resolve(), "fichier ~/.config/zab/config.yaml (skills_roots / skills_root)"
    except ImportError:
        pass

    inv = os.environ.get("ZAB_INVOCATION_CWD", "").strip()
    if inv:
        return Path(inv).expanduser().resolve(), "variable d'environnement ZAB_INVOCATION_CWD"

    return Path.cwd().resolve(), "répertoire courant du processus (cwd)"


def skills_root() -> Path:
    """
    Racine du dépôt skills (orgs/, mcps/, configs/, …).

    Ordre :
      1. $ZAB_SKILLS_ROOT
      2. ~/.config/zab/config.yaml → skills_roots[] ou skills_root (première entrée)
      3. $ZAB_INVOCATION_CWD (répertoire d’où la fonction shell `zab` a été appelée ;
         `uv run` change le cwd vers le dépôt zab)
      4. défaut : cwd du processus Python
    """
    return resolve_skills_root()[0]


def skills_roots_resolved_from_config() -> list[Path]:
    """
    Liste des racines skills déclarées dans ~/.config/zab/config.yaml (skills_roots + legacy skills_root).
    Ignore les chemins inexistants ou non répertoires.
    """
    from zab.user_config import skills_roots_strings_ordered

    out: list[Path] = []
    seen: set[str] = set()
    for s in skills_roots_strings_ordered():
        try:
            p = Path(s).expanduser().resolve()
        except OSError:
            continue
        if not p.is_dir():
            continue
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def skills_root_from_config_file_only() -> Path | None:
    """
    Ancre dashboard / jobs : première racine ``skills_roots``, sinon premier SKILL.md listé,
    sinon premier dossier plugin inventorié.
    """
    return dashboard_anchor_path()


def dashboard_anchor_path() -> Path | None:
    lst = skills_roots_resolved_from_config()
    if lst:
        return lst[0]
    from zab.user_config import claude_plugin_paths_resolved, skill_md_paths_resolved

    sm = skill_md_paths_resolved()
    if sm:
        from zab.services.inventory_config import infer_mcp_repo_base_from_skill_md

        base = infer_mcp_repo_base_from_skill_md(sm[0])
        if base is not None:
            return base
        return sm[0].parent
    cp = claude_plugin_paths_resolved()
    if cp:
        return cp[0]
    return None


def primary_repo_base_for_mcp_files() -> Path | None:
    """Premier dépôt avec ``configs/cursor-mcp.json`` (racines YAML ou déduit des SKILL.md inventoriés)."""
    lst = skills_roots_resolved_from_config()
    if lst:
        return lst[0]
    from zab.services.inventory_config import infer_mcp_repo_base_from_skill_md
    from zab.user_config import skill_md_paths_resolved

    for md in skill_md_paths_resolved():
        b = infer_mcp_repo_base_from_skill_md(md)
        if b is not None:
            return b
    return None


def dashboard_local_tools_config_path() -> Path:
    """
    Fichier local-tools utilisé par le dashboard : clé ``local_tools_path`` dans config.yaml,
    sinon ~/.config/zab/local-tools.yaml (sans repli sur le paquet zab).
    """
    from zab.user_config import local_tools_path_from_user_config

    raw = local_tools_path_from_user_config()
    if raw and str(raw).strip():
        return Path(raw.strip()).expanduser().resolve()
    return (config_dir() / "local-tools.yaml").expanduser().resolve()


def orgs_dir() -> Path:
    return skills_root() / "orgs"


def claude_plugins_dir() -> Path:
    return skills_root() / "claude-plugins"


def configs_dir() -> Path:
    return skills_root() / "configs"


def scripts_dir() -> Path:
    return skills_root() / "scripts"


def mcps_dir() -> Path:
    return skills_root() / "mcps"


def common_dir() -> Path:
    return skills_root() / "common"


def plugin_config_path() -> Path:
    return skills_root() / "plugin-config.yaml"


def user_home() -> Path:
    return Path.home().resolve()


def mehdi_context_root() -> Path:
    return Path.home() / ".mehdi-context"


def agentpipe_config_path() -> Path:
    return Path.home() / ".agentpipe.yaml"


def codexbar_config_path() -> Path:
    return Path.home() / ".codexbar" / "config.json"


def local_tools_config_path() -> Path:
    """
    Config locale des outils (proxies LLM, liste CLI à surveiller).
    Priorité : ~/.config/zab/local-tools.yaml puis zab/local-tools.yaml dans le dépôt zab.
    """
    user_cfg = config_dir() / "local-tools.yaml"
    if user_cfg.is_file():
        return user_cfg
    pkg_fallback = zab_package_dir() / "local-tools.yaml"
    if pkg_fallback.is_file():
        return pkg_fallback
    return user_cfg
