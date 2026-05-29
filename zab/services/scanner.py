"""Scan depuis le répertoire utilisateur (~) : SKILL.md, CLIs zab/repo, vérif Agentpipe/Codexbar."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

from zab.paths import (
    config_dir,
    data_dir,
    local_tools_config_path,
    skills_root,
    user_home,
    zab_package_dir,
)
from zab.services import cursor_scan, memory_scan, tools_scan
from zab.services.workspace_projects import discover_projects
from zab.user_config import cli_watchlist_from_user_config, load_user_config

# Répertoires à ne pas parcourir (volumétrie / bruit)
_SCAN_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".svn",
        ".hg",
        "node_modules",
        "venv",
        ".venv",
        "__pycache__",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        "dist",
        "build",
        ".next",
        "target",
        ".cargo",
        "site-packages",
    }
)


# À la racine de ~/ uniquement : ne pas descendre dans ces dossiers volumineux
_HOME_TOPLEVEL_SKIP: frozenset[str] = frozenset(
    {
        "Library",
        "Applications",
        "Movies",
        "Music",
        "Pictures",
        "Public",
        ".Trash",
    }
)


_HEAVY_DOT_DIRS: frozenset[str] = frozenset(
    {
        ".Trash",
        ".cache",
        ".npm",
        ".yarn",
        ".cargo",
        ".rustup",
        ".gem",
        ".nuget",
        ".vscode-test",
        ".Steam",
        ".steam",
    }
)


def _walk_base_under_home(base: Path, hp: Path) -> bool:
    br = base.resolve()
    hp_r = hp.resolve()
    return br == hp_r or hp_r in br.parents


def _prune_walk_dirnames(dirnames: list[str], *, base: Path, dirpath: str, hp: Path) -> None:
    br = base.resolve()
    hp_r = hp.resolve()
    cur = Path(dirpath).resolve()
    under_home = _walk_base_under_home(br, hp_r)

    out: list[str] = []
    for d in sorted(dirnames):
        if d in _SCAN_SKIP_DIRS or d in _HEAVY_DOT_DIRS:
            continue
        if not under_home and d.startswith("."):
            continue
        if br == hp_r and cur == hp_r and d in _HOME_TOPLEVEL_SKIP:
            continue
        out.append(d)
    dirnames[:] = out


# agentpipe (~/.agentpipe.yaml ou agentpipe_config_path) → préfixe binaire pour `which`
_MODEL_KEYS: tuple[str, ...] = (
    "model",
    "coding_model",
    "default_model",
    "llm_model",
    "primary_model",
    "anthropic_model",
    "openai_model",
    "chat_model",
)


def _agentpipe_yaml_path_for_scan() -> Path:
    cfg = load_user_config()
    raw = cfg.get("agentpipe_config_path")
    if isinstance(raw, str) and raw.strip():
        return Path(raw.strip()).expanduser().resolve()
    return Path.home() / ".agentpipe.yaml"


def _codexbar_config_path_for_scan() -> Path:
    cfg = load_user_config()
    raw = cfg.get("codexbar_config_path")
    if isinstance(raw, str) and raw.strip():
        return Path(raw.strip()).expanduser().resolve()
    return Path.home() / ".codexbar" / "config.json"


def _coding_models_from_agent(item: dict[str, Any], *, depth: int = 0) -> list[str]:
    """Extrait les identifiants de modèles « coding » déclarés dans un bloc agent agentpipe."""
    if depth > 6 or not isinstance(item, dict):
        return []
    out: list[str] = []
    for k in _MODEL_KEYS:
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            out.append(v.strip())
    m = item.get("models")
    if isinstance(m, list):
        for x in m:
            if isinstance(x, str) and x.strip():
                out.append(x.strip())
            elif isinstance(x, dict):
                nm = x.get("name") or x.get("id") or x.get("model")
                if isinstance(nm, str) and nm.strip():
                    out.append(nm.strip())
    for subkey in ("options", "config", "settings", "env", "provider"):
        sub = item.get(subkey)
        if isinstance(sub, dict):
            out.extend(_coding_models_from_agent(sub, depth=depth + 1))
    seen: set[str] = set()
    uniq: list[str] = []
    for x in out:
        key = x.casefold()
        if key not in seen:
            seen.add(key)
            uniq.append(x)
    return uniq


def _probe_codexbar_cli(binary: str | None) -> dict[str, Any]:
    """Teste le CLI codexbar : ``--version`` et ``config validate`` (best-effort)."""
    if not binary:
        return {"ran": False, "reason": "codexbar_absent_du_path"}
    env = {**os.environ, "NO_COLOR": "1", "TERM": "dumb"}
    out: dict[str, Any] = {"ran": True, "binary": binary}
    try:
        r = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=15, env=env)
        out["version_exit_code"] = r.returncode
        out["version_stdout"] = (r.stdout or "").strip()[:4000]
        out["version_stderr"] = (r.stderr or "").strip()[:2000]
    except (OSError, subprocess.TimeoutExpired) as e:
        out["version_error"] = str(e)
    try:
        r2 = subprocess.run(
            [binary, "config", "validate", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=45,
            env=env,
        )
        out["validate_exit_code"] = r2.returncode
        raw_json = (r2.stdout or "").strip()
        out["validate_stdout_preview"] = raw_json[:12000]
        out["validate_stderr_preview"] = ((r2.stderr or "").strip())[:4000]
        if raw_json.startswith("{") or raw_json.startswith("["):
            try:
                out["validate_json"] = json.loads(raw_json)
            except json.JSONDecodeError:
                out["validate_json_parse_error"] = True
    except (OSError, subprocess.TimeoutExpired) as e:
        out["validate_error"] = str(e)
    return out


_AGENT_TYPE_TO_BIN_HINT: dict[str, str] = {
    "claude": "claude",
    "claude-code": "claude",
    "cursor": "cursor",
    "gemini": "gemini",
    "google-gemini": "gemini",
    "vertex": "gemini",
    "vertexai": "gemini",
    "kimi": "kimi",
    "qwen": "qwen",
    "factory": "factory",
    "continue": "continue",
    "continue-dev": "continue",
    "continue.dev": "continue",
    "continue_dev": "continue",
    "continuedev": "continue",
    "codex": "codex",
}


def _safe_relative(path: Path, base: Path) -> Path | None:
    try:
        return path.resolve().relative_to(base.resolve())
    except ValueError:
        return None


def _rel_contains_skip(rel: Path) -> bool:
    return any(part in _SCAN_SKIP_DIRS for part in rel.parts)


def scan_skill_md_files(root: Path) -> list[dict[str, Any]]:
    """
    Liste tous les fichiers nommés exactement SKILL.md sous root (ignore node_modules, .git…).
    """
    base = root.resolve()
    if not base.is_dir():
        return []

    hits: list[dict[str, Any]] = []
    base_s = os.fspath(base)
    hp = user_home().resolve()
    try:
        for dirpath, dirnames, filenames in os.walk(base_s, topdown=True, followlinks=False):
            _prune_walk_dirnames(dirnames, base=base, dirpath=dirpath, hp=hp)
            if "SKILL.md" not in filenames:
                continue
            p = Path(dirpath) / "SKILL.md"
            try:
                if not p.is_file():
                    continue
            except OSError:
                continue
            rel = _safe_relative(p, base)
            if rel is None or _rel_contains_skip(rel):
                continue
            try:
                size = int(p.stat().st_size)
            except OSError:
                size = 0
            hits.append({"path": str(rel).replace("\\", "/"), "size_bytes": size})
    except OSError:
        return []

    hits.sort(key=lambda x: x["path"].lower())
    return hits


def _agent_binary_from_item(item: dict[str, Any]) -> str | None:
    cmd = item.get("command") or item.get("bin") or item.get("binary")
    if isinstance(cmd, str) and cmd.strip():
        first = cmd.strip().split()[0]
        name = Path(first).name.split()[0]
        return name


def _probe_agent_binary(agent_id: str, typ: str, item: dict[str, Any]) -> tuple[str | None, str | None]:
    hinted = item.get("type")
    typed = str(typ or hinted or "").strip().lower()
    bin_candidate = _agent_binary_from_item(item)
    candidates: list[str] = []
    if bin_candidate:
        candidates.append(bin_candidate)
    if typed and typed in _AGENT_TYPE_TO_BIN_HINT:
        h = _AGENT_TYPE_TO_BIN_HINT[typed]
        if h not in candidates:
            candidates.append(h)
    if typed and typed not in candidates:
        candidates.append(typed)
    aid = agent_id.strip()
    if aid:
        dashed = aid.replace("_", "-")
        if dashed not in candidates:
            candidates.append(dashed)

    seen: list[str] = []
    chosen_first: str | None = None
    for c in candidates:
        if not c or c in seen:
            continue
        seen.append(c)
        if chosen_first is None:
            chosen_first = c
        w = shutil.which(c)
        if w:
            return c, w
    return chosen_first, None


def _normalize_agent_entries(data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    agents_raw = data.get("agents")
    if isinstance(agents_raw, list):
        for i, item in enumerate(agents_raw):
            if isinstance(item, dict):
                cmd = item.get("command")
                cmd0 = ""
                if isinstance(cmd, str) and cmd.strip():
                    parts = cmd.strip().split()
                    if parts:
                        cmd0 = Path(parts[0]).name
                nid = item.get("id") or item.get("name") or item.get("type") or cmd0
                name = nid if isinstance(nid, str) and nid.strip() else f"agent-{i}"
                out.append((name.strip(), item))
    elif isinstance(agents_raw, dict):
        for name, item in agents_raw.items():
            if isinstance(item, dict):
                out.append((str(name), item))
            elif item is None:
                out.append((str(name), {}))
    else:
        for key, val in data.items():
            if key.lower() in ("version", "schema"):
                continue
            if isinstance(val, dict) and isinstance(key, str):
                out.append((key, val))
    return out


def scan_agentpipe() -> dict[str, Any]:
    path = _agentpipe_yaml_path_for_scan()
    cli_bin = shutil.which("agentpipe")

    def _baseline(
        *,
        present: bool,
        agents_list: list[dict[str, Any]],
        error: str | None,
        raw_doc: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        yaml_ver = None
        if isinstance(raw_doc, dict):
            v = raw_doc.get("version")
            if isinstance(v, (str, int, float)):
                yaml_ver = v
        n_ok = sum(1 for a in agents_list if a.get("on_path"))
        flat: list[str] = []
        seen_f: set[str] = set()
        for ag in agents_list:
            cms = ag.get("coding_models")
            if not isinstance(cms, list):
                continue
            for m in cms:
                if not isinstance(m, str) or not m.strip():
                    continue
                ms = m.strip()
                k = ms.casefold()
                if k not in seen_f:
                    seen_f.add(k)
                    flat.append(ms)
        return {
            "present": present,
            "path": str(path),
            "agents": agents_list,
            "error": error,
            "agents_total": len(agents_list),
            "agents_on_path": n_ok,
            "cli_agentpipe_binary": cli_bin,
            "yaml_version": yaml_ver,
            "coding_models_flat": flat,
        }

    if not path.is_file():
        return _baseline(present=False, agents_list=[], error=None)

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError) as e:
        return _baseline(present=True, agents_list=[], error=str(e))

    if not isinstance(raw, dict):
        return _baseline(present=True, agents_list=[], error="not_a_mapping")

    entries = _normalize_agent_entries(raw)
    agents: list[dict[str, Any]] = []
    for aid, item in entries:
        typ = str(item.get("type") or "")
        probe_name, loc = _probe_agent_binary(aid, typ, item)
        cms = _coding_models_from_agent(item)
        agents.append(
            {
                "id": aid,
                "type": typ or None,
                "probe_binary": probe_name,
                "on_path": loc is not None,
                "which_path": loc,
                "coding_models": cms,
            }
        )

    agents.sort(key=lambda x: x["id"].lower())
    return _baseline(present=True, agents_list=agents, error=None, raw_doc=raw)


def scan_codexbar_stub() -> dict[str, Any]:
    """Résumé ~/.codexbar/config.json + test CLI ``codexbar --version`` et ``codexbar config validate``."""
    path = _codexbar_config_path_for_scan()
    cli = shutil.which("codexbar")
    cli_probe = _probe_codexbar_cli(cli)
    if not path.is_file():
        return {
            "present": False,
            "path": str(path),
            "top_level_keys": [],
            "cli_codexbar_binary": cli,
            "cli_probe": cli_probe,
        }
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        keys = sorted(doc.keys()) if isinstance(doc, dict) else []
        return {"present": True, "path": str(path), "top_level_keys": keys, "cli_codexbar_binary": cli, "cli_probe": cli_probe}
    except (json.JSONDecodeError, OSError):
        return {
            "present": True,
            "path": str(path),
            "top_level_keys": [],
            "_error": "invalid_json",
            "cli_codexbar_binary": cli,
            "cli_probe": cli_probe,
        }


def _clis_aggregate() -> dict[str, Any]:
    scan = tools_scan.scan_tools()
    return {
        "zab_commands": scan.get("cli_commands") or [],
        "repo_scripts": scan.get("scripts") or [],
    }


def _merged_watchlist_names() -> list[str]:
    names: list[str] = []
    p = local_tools_config_path()
    if p.is_file():
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            wl = doc.get("cli_watchlist")
            if isinstance(wl, list):
                for x in wl:
                    if isinstance(x, str) and x.strip() and x.strip() not in names:
                        names.append(x.strip())
        except yaml.YAMLError:
            pass
    for x in cli_watchlist_from_user_config():
        if x not in names:
            names.append(x)
    return names


def scan_cli_watchlist() -> list[dict[str, Any]]:
    """Sonde `which` pour les binaires déclarés (YAML + config utilisateur)."""
    out: list[dict[str, Any]] = []
    for name in _merged_watchlist_names():
        loc = shutil.which(name)
        out.append({"name": name, "on_path": loc is not None, "which_path": loc})
    out.sort(key=lambda x: x["name"].lower())
    return out


def _allowed_scan_root(candidate: Path) -> Path | None:
    """Lecture réservée à ~/ et ses sous-répertoires (sandbox dashboard / API)."""
    hp = user_home().resolve()
    rp = candidate.expanduser().resolve()
    try:
        rp.relative_to(hp)
        return rp
    except ValueError:
        if rp == hp:
            return rp
    return None


def resolve_optional_scan_root(rel: str | Path | None) -> Path | None:
    """Chemin depuis ~ : relatifs résolus contre user_home."""
    if rel is None or str(rel).strip() == "":
        return None
    p = Path(rel).expanduser()
    if not p.is_absolute():
        p = (user_home() / p).resolve()
    else:
        p = p.resolve()
    return p


def workspace_scan(root: Path | None = None, *, allow_any_path: bool = False) -> dict[str, Any]:
    """
    Point d'entrée : SKILL.md depuis le répertoire personnel (~); Agentpipe/Codexbar lus hors arbre fichiers.
    """
    hp = user_home().resolve()
    sr = skills_root()
    sr_res = sr.resolve()
    warnings: list[str] = []
    if root is None:
        base = hp
    else:
        rp = Path(root).expanduser().resolve()
        if allow_any_path:
            if rp.is_dir():
                base = rp
            else:
                base = hp
                warnings.append(f"répertoire de scan invalide ({rp}) — utilisation de {hp}")
        else:
            ok = _allowed_scan_root(Path(root))
            if ok is None:
                base = hp
                warnings.append(f"chemin hors du répertoire utilisateur (~) ignoré — utilisation de {hp}")
            else:
                base = ok.resolve()

    skills = scan_skill_md_files(base)
    ap = scan_agentpipe()
    cb = scan_codexbar_stub()

    clis_block = _clis_aggregate()
    clis_block["watchlist"] = scan_cli_watchlist()

    payload: dict[str, Any] = {
        "scan_root_resolved": str(base.resolve()),
        "user_home": str(hp),
        "skills_root": str(sr_res),
        "zab_repo_root": str(zab_package_dir().resolve().parent),
        "package_dir": str(zab_package_dir().resolve()),
        "config_dir": str(config_dir()),
        "data_dir": str(data_dir()),
        "skill_md_count": len(skills),
        "skill_md_files": skills,
        "workspace_projects": discover_projects(),
        "clis": clis_block,
        "agentpipe": ap,
        "codexbar": cb,
        "cursor_cody": cursor_scan.scan_cursor_cody(),
        "memory_stack": memory_scan.build_memory_stack(sr_res),
    }
    if warnings:
        payload["warnings"] = warnings
    return payload
