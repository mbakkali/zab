"""Lecture légère des métadonnées Git locales (sans dépendre du binaire git pour l’aperçu API)."""

from __future__ import annotations

import os
import shutil
import subprocess
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

RemoteHost = Literal["github", "gitlab", "other"]

_ACTIVITY_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
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
        ".turbo",
        "coverage",
        "site-packages",
    }
)


def _iso_from_timestamp(ts: float | int | None) -> str | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def _read_text_safe(path: Path, *, max_bytes: int = 256_000) -> str | None:
    try:
        raw = path.read_bytes()
        if len(raw) > max_bytes:
            raw = raw[:max_bytes]
        return raw.decode("utf-8", errors="replace")
    except OSError:
        return None


def _resolve_git_dir(project: Path) -> Path | None:
    """Répertoire ``.git`` effectif (workdir Git) pour ``project``."""
    git_entry = project / ".git"
    try:
        if git_entry.is_dir():
            return git_entry.resolve()
        if not git_entry.is_file():
            return None
    except OSError:
        return None
    text = _read_text_safe(git_entry, max_bytes=8_192)
    if not text:
        return None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("gitdir:"):
            rel = line.split("gitdir:", 1)[1].strip()
            try:
                return (git_entry.parent / rel).resolve()
            except OSError:
                return None
    return None


def _git_common_dir(git_dir: Path) -> Path:
    """Répertoire principal ``.git`` (objets partagés) pour worktrees."""
    commondir = git_dir / "commondir"
    raw = _read_text_safe(commondir, max_bytes=4_096)
    if raw:
        rel = raw.strip().splitlines()[0].strip()
        if rel:
            try:
                return (git_dir / rel).resolve()
            except OSError:
                pass
    return git_dir


def _read_branch_from_head(head_file: Path) -> str | None:
    raw = _read_text_safe(head_file, max_bytes=8_192)
    if not raw:
        return None
    line = raw.strip().splitlines()[0].strip() if raw.strip() else ""
    if line.startswith("ref: refs/heads/"):
        return line.removeprefix("ref: refs/heads/").strip() or None
    if line and not line.startswith("ref:"):
        return line[:64]
    return None


def _origin_url_from_config(config_path: Path) -> str | None:
    raw = _read_text_safe(config_path, max_bytes=512_000)
    if not raw:
        return None
    in_origin = False
    for line in raw.splitlines():
        s = line.strip()
        low = s.lower()
        if low.startswith("[") and low.endswith("]"):
            in_origin = low == '[remote "origin"]'
            continue
        if in_origin and low.startswith("url ="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
        if in_origin and low.startswith("["):
            in_origin = False
    return None


def _git_last_commit_iso(project_path: Path) -> str | None:
    git = shutil.which("git")
    if not git:
        return None
    try:
        proc = subprocess.run(
            [git, "-C", str(project_path), "log", "-1", "--format=%ct"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    value = (proc.stdout or "").strip().splitlines()
    if not value or not value[0].strip():
        return None
    try:
        return _iso_from_timestamp(int(value[0].strip()))
    except ValueError:
        return None


def _latest_mtime_under(path: Path, *, recursive: bool = False) -> float | None:
    try:
        if not path.exists():
            return None
    except OSError:
        return None
    latest: float | None = None
    try:
        latest = path.stat().st_mtime
    except OSError:
        pass
    if not recursive or not path.is_dir():
        return latest
    try:
        for dirpath, dirnames, filenames in os.walk(os.fspath(path), topdown=True, followlinks=False):
            dirnames[:] = sorted(d for d in dirnames if d not in _ACTIVITY_SKIP_DIRS)
            for name in filenames:
                p = Path(dirpath) / name
                try:
                    ts = p.stat().st_mtime
                except OSError:
                    continue
                if latest is None or ts > latest:
                    latest = ts
    except OSError:
        return latest
    return latest


def _git_metadata_activity_iso(git_dir: Path) -> str | None:
    common = _git_common_dir(git_dir)
    candidates: list[float] = []
    for p in (
        git_dir / "HEAD",
        git_dir / "index",
        git_dir / "ORIG_HEAD",
        common / "config",
        common / "packed-refs",
        common / "FETCH_HEAD",
    ):
        ts = _latest_mtime_under(p)
        if ts is not None:
            candidates.append(ts)
    for p in (git_dir / "refs", common / "refs"):
        ts = _latest_mtime_under(p, recursive=True)
        if ts is not None:
            candidates.append(ts)
    return _iso_from_timestamp(max(candidates) if candidates else None)


def project_file_activity(project_path: Path) -> dict[str, Any]:
    """Dernière modification de fichier sous projet, en ignorant les arbres lourds."""
    out: dict[str, Any] = {
        "last_activity_at_utc": None,
        "last_activity_source": None,
        "last_activity_path": None,
    }
    try:
        root = project_path.expanduser().resolve()
    except OSError:
        return out
    if not root.is_dir():
        return out

    latest_ts: float | None = None
    latest_path: Path | None = None
    try:
        for dirpath, dirnames, filenames in os.walk(os.fspath(root), topdown=True, followlinks=False):
            dirnames[:] = sorted(d for d in dirnames if d not in _ACTIVITY_SKIP_DIRS)
            for name in filenames:
                p = Path(dirpath) / name
                try:
                    ts = p.stat().st_mtime
                except OSError:
                    continue
                if latest_ts is None or ts > latest_ts:
                    latest_ts = ts
                    latest_path = p
    except OSError:
        return out

    out["last_activity_at_utc"] = _iso_from_timestamp(latest_ts)
    out["last_activity_source"] = "files" if latest_ts is not None else None
    if latest_path is not None:
        try:
            out["last_activity_path"] = str(latest_path.resolve().relative_to(root))
        except ValueError:
            out["last_activity_path"] = str(latest_path)
    return out


def _classify_remote_host(url: str) -> RemoteHost | None:
    u = url.strip().lower()
    if not u:
        return None
    if "github.com" in u or u.startswith("git@github.com:"):
        return "github"
    if "gitlab" in u or u.startswith("git@gitlab"):
        return "gitlab"
    try:
        if u.startswith("git@"):
            host = u.split("@", 1)[1].split(":", 1)[0]
        else:
            host = (urlparse(u).hostname or "").lower()
        if "github" in host:
            return "github"
        if "gitlab" in host:
            return "gitlab"
    except (IndexError, ValueError):
        pass
    return "other"


def normalize_git_remote_to_https(url: str) -> str | None:
    """Normalise ``remote.origin.url`` en URL https navigable (best-effort)."""
    u = url.strip()
    if not u:
        return None
    if u.startswith("git@"):
        try:
            rest = u.split("@", 1)[1]
            host, path = rest.split(":", 1)
        except ValueError:
            return None
        path = path.removesuffix(".git")
        return f"https://{host}/{path}"
    if u.startswith("ssh://"):
        try:
            parsed = urlparse(u)
            host = parsed.hostname
            path = (parsed.path or "").strip("/")
            if not host:
                return None
            return f"https://{host}/{path}".removesuffix(".git")
        except ValueError:
            return None
    if u.startswith("http://") or u.startswith("https://"):
        return u.removesuffix(".git")
    return None


def project_git_metadata(project_path: Path) -> dict[str, Any]:
    """
    Retourne ``git_repo``, ``git_branch``, ``remote_host``, ``origin_url`` (brut),
    ``origin_https`` (pour ouvrir le dépôt dans un navigateur).
    """
    out: dict[str, Any] = {
        "git_repo": False,
        "git_branch": None,
        "remote_host": None,
        "origin_url": None,
        "origin_https": None,
        "last_activity_at_utc": None,
        "last_activity_source": None,
        "last_activity_path": None,
    }
    try:
        root = project_path.expanduser().resolve()
    except OSError:
        return out
    if not root.is_dir():
        return out

    git_dir = _resolve_git_dir(root)
    if git_dir is None:
        return out

    out["git_repo"] = True
    commit_iso = _git_last_commit_iso(root)
    if commit_iso:
        out["last_activity_at_utc"] = commit_iso
        out["last_activity_source"] = "git_commit"
    else:
        meta_iso = _git_metadata_activity_iso(git_dir)
        if meta_iso:
            out["last_activity_at_utc"] = meta_iso
            out["last_activity_source"] = "git_metadata"
    common = _git_common_dir(git_dir)
    head_path = git_dir / "HEAD"
    out["git_branch"] = _read_branch_from_head(head_path)

    cfg = common / "config"
    origin = _origin_url_from_config(cfg)
    if origin:
        out["origin_url"] = origin
        out["origin_https"] = normalize_git_remote_to_https(origin)
        out["remote_host"] = _classify_remote_host(origin)

    return out


def open_project_origin_browser(project_path: Path) -> tuple[bool, str | None]:
    """Ouvre ``origin_https`` dans le navigateur par défaut. Retourne (ok, code_erreur)."""
    meta = project_git_metadata(project_path)
    url = meta.get("origin_https")
    if not isinstance(url, str) or not url.strip():
        return False, "remote_origin_introuvable"
    webbrowser.open(url.strip())
    return True, None


def run_pm_repo_tool(project_path: Path, tool: Literal["gh", "glab"]) -> tuple[int, str, str]:
    """
    Lance un outil de gestion de dépôt dans ``project_path`` (cwd).

    Retourne ``(code_retour, stdout+stderr, code_erreur)`` ; le dernier champ est vide si succès.
    """
    bin_name = "gh" if tool == "gh" else "glab"
    exe = shutil.which(bin_name)
    if not exe:
        return 127, "", f"{bin_name}_absent_du_path"

    cmd = [exe, "repo", "view", "--web"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(project_path.resolve()),
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except OSError as exc:
        return 1, "", str(exc)
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode, out, "" if proc.returncode == 0 else "commande_terminee_avec_erreur"
