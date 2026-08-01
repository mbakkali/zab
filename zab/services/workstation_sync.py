"""Bidirectional sync helpers for Mac <-> Cloud Workstation.

The sync model is deliberately conservative:
- GCS is the durable hub.
- Each profile has one "latest" archive and manifest.
- Local state tracks the remote artifact and file hashes from the last pull/push.
- Pull preserves locally modified files as conflict copies before overwriting.
- Push refuses if remote changed since local state and local files changed, unless forced.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import tarfile
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

from zab.paths import config_dir, data_dir
from zab.user_config import load_user_config

DEFAULT_BUCKET = ""
STATE_PATH = data_dir() / "workstation-sync" / "state.json"

PROFILE_PATHS: dict[str, list[str]] = {
    "zab": [
        ".config/zab/config.yaml",
        ".config/zab/local-tools.yaml",
        ".local/share/zab/scan-last.yaml",
        ".local/share/zab/scan-proposed-skills-roots.yaml",
    ],
    "dotfiles": [
        ".gitconfig",
        ".gitignore_global",
        ".tmux.conf",
        ".config/starship.toml",
        "bin",
    ],
    "secrets-cli": [
        ".claude",
        ".gemini",
        ".codex",
        ".config/gh",
        ".config/firebase",
        ".config/supabase",
        ".config/composio",
        ".config/scw",
        ".aws",
        ".ssh/config",
        ".ssh/id_ed25519",
        ".ssh/id_ed25519.pub",
        ".ssh/id_rsa",
        ".ssh/id_rsa.pub",
    ],
}

EXCLUDE_PATTERNS = [
    "*/node_modules/*",
    "*/.venv/*",
    "*/__pycache__/*",
    "*/.git/*",
    "*/.DS_Store",
    "*/.cache/*",
    "*/cache/*",
    "*/logs/*",
    "*/Logs/*",
    "*/venv/*",
    "*/.pytest_cache/*",
    "*/.mypy_cache/*",
    "*/.ruff_cache/*",
    "*/Cache/*",
    ".claude/file-history/*",
    ".claude/backups/*",
    ".gemini/tmp/*",
]

CLI_INSTALL_COMMANDS: dict[str, list[str]] = {
    "ruff": ["uv", "tool", "install", "ruff"],
    "pytest": ["uv", "tool", "install", "pytest"],
    "streamlit": ["uv", "tool", "install", "streamlit"],
    "jupyter": ["uv", "tool", "install", "jupyter-core"],
    "composio": ["uv", "tool", "install", "composio-core"],
    "duckdb": ["bash", "-lc", "mkdir -p ~/.local/bin && curl -fsSL https://github.com/duckdb/duckdb/releases/latest/download/duckdb_cli-linux-amd64.zip -o /tmp/duckdb.zip && unzip -o /tmp/duckdb.zip -d ~/.local/bin && chmod +x ~/.local/bin/duckdb && rm -f /tmp/duckdb.zip"],
    "pnpm": ["npm", "install", "-g", "pnpm"],
    "vercel": ["npm", "install", "-g", "vercel"],
    "ngrok": ["npm", "install", "-g", "ngrok"],
    "playwright": ["npm", "install", "-g", "playwright"],
    "flyctl": ["bash", "-lc", "curl -L https://fly.io/install.sh | sh && mkdir -p ~/.local/bin && cp ~/.fly/bin/flyctl ~/.local/bin/flyctl"],
    "aws": ["bash", "-lc", "curl -fsSL https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip -o /tmp/awscliv2.zip && unzip -q -o /tmp/awscliv2.zip -d /tmp && sudo /tmp/aws/install --update && rm -rf /tmp/aws /tmp/awscliv2.zip"],
    "supabase": ["bash", "-lc", "mkdir -p ~/.local/bin && curl -fsSL https://github.com/supabase/cli/releases/latest/download/supabase_linux_amd64.tar.gz -o /tmp/supabase.tar.gz && tar -xzf /tmp/supabase.tar.gz -C ~/.local/bin supabase && chmod +x ~/.local/bin/supabase && rm -f /tmp/supabase.tar.gz"],
    "stripe": ["bash", "-lc", "mkdir -p ~/.local/bin && curl -fsSL https://github.com/stripe/stripe-cli/releases/download/v1.22.0/stripe_1.22.0_linux_x86_64.tar.gz -o /tmp/stripe.tar.gz && tar -xzf /tmp/stripe.tar.gz -C ~/.local/bin stripe && chmod +x ~/.local/bin/stripe && rm -f /tmp/stripe.tar.gz"],
    "ollama": ["bash", "-lc", "command -v zstd >/dev/null || sudo apt-get update && sudo apt-get install -y zstd; curl -fsSL https://ollama.com/install.sh | sh"],
    "glab": ["bash", "-lc", "mkdir -p ~/.local/bin && curl -fsSL https://gitlab.com/gitlab-org/cli/-/releases/v1.40.0/downloads/glab_1.40.0_Linux_x86_64.tar.gz -o /tmp/glab.tar.gz && tar -xzf /tmp/glab.tar.gz -C /tmp && mv /tmp/bin/glab ~/.local/bin/glab && chmod +x ~/.local/bin/glab && rm -rf /tmp/glab.tar.gz /tmp/bin /tmp/share"],
    "poetry": ["uv", "tool", "install", "poetry"],
    "ffmpeg": ["bash", "-lc", "sudo apt-get update && sudo apt-get install -y ffmpeg"],
    "psql": ["bash", "-lc", "sudo apt-get update && sudo apt-get install -y postgresql-client"],
    "redis-cli": ["bash", "-lc", "sudo apt-get update && sudo apt-get install -y redis-tools"],
    "docker-compose": ["bash", "-lc", "sudo apt-get update && sudo apt-get install -y docker-compose-plugin || true; mkdir -p ~/.local/bin; printf '#!/usr/bin/env bash\nexec docker compose \"$@\"\n' > ~/.local/bin/docker-compose; chmod +x ~/.local/bin/docker-compose"],
    "pyenv": ["bash", "-lc", "curl -fsSL https://pyenv.run | bash"],
    "hermes": ["bash", "-lc", "mkdir -p ~/.hermes && if [ ! -d ~/.hermes/hermes-agent ]; then git clone https://github.com/NousResearch/hermes-agent.git ~/.hermes/hermes-agent 2>&1; fi && cd ~/.hermes/hermes-agent && python3 -m venv venv && venv/bin/pip install -e . 2>&1 | tail -3 && mkdir -p ~/.local/bin && printf '#!/usr/bin/env bash\\nunset PYTHONPATH PYTHONHOME\\nH=\"${HOME}/.hermes\"\\nVENV=\"${H}/hermes-agent/venv\"\\nPY=\"${VENV}/bin/python\"\\nTOK=\"${H}/scripts/vertex_access_token.py\"\\nif [[ -f \"${H}/.env.vertex\" ]]; then set -a; . \"${H}/.env.vertex\"; set +a; fi\\nif [[ -n \"${GOOGLE_APPLICATION_CREDENTIALS:-}\" && -f \"${TOK}\" && -z \"${VERTEX_ACCESS_TOKEN:-}\" ]]; then eval \"$(\"${PY}\" \"${TOK}\" 2>/dev/null)\" 2>/dev/null || true; fi\\nif [[ -z \"${ANTHROPIC_API_KEY:-}\" && -n \"${CLAUDE_CODE_API_KEY:-}\" ]]; then export ANTHROPIC_API_KEY=\"${CLAUDE_CODE_API_KEY}\"; fi\\nexec \"${VENV}/bin/hermes\" \"$@\"\\n' > ~/.local/bin/hermes && chmod +x ~/.local/bin/hermes"],
    "cn": ["npm", "install", "-g", "@continuedev/cli"],
    "mempalace": ["uv", "tool", "install", "mempalace"],
    # `gemini` figurait dans la watchlist sans installateur : il etait signale
    # manquant a chaque passage, sans aucun moyen de l'obtenir.
    "gemini": ["npm", "install", "-g", "@google/gemini-cli"],
    "conda": ["bash", "-lc", "curl -fsSL https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -o /tmp/miniconda.sh && bash /tmp/miniconda.sh -b -p $HOME/miniconda3 && rm /tmp/miniconda.sh && $HOME/miniconda3/bin/conda init bash 2>&1 | tail -1"],
}


@dataclass
class SyncSettings:
    bucket: str
    profiles: list[str]
    passphrase_file: Path


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _machine_id() -> str:
    env = os.environ.get("ZAB_WS_SYNC_MACHINE", "").strip()
    if env:
        return env
    host = socket.gethostname().split(".")[0]
    system = platform.system().lower() or "machine"
    return f"{system}-{host}"


def _home() -> Path:
    return Path.home().resolve()


def settings() -> SyncSettings:
    cfg = load_user_config()
    raw = cfg.get("workstation_sync") if isinstance(cfg, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    bucket = str(os.environ.get("ZAB_WS_SYNC_BUCKET") or raw.get("bucket") or DEFAULT_BUCKET).rstrip("/")
    profiles_raw = raw.get("profiles")
    profiles = profiles_raw if isinstance(profiles_raw, list) else list(PROFILE_PATHS)
    passphrase_file = Path(
        os.environ.get("ZAB_WS_SYNC_PASSPHRASE_FILE")
        or raw.get("passphrase_file")
        or (config_dir() / "ws-sync.key")
    ).expanduser()
    return SyncSettings(bucket=bucket, profiles=[str(p) for p in profiles], passphrase_file=passphrase_file)


def _state_load() -> dict[str, Any]:
    if not STATE_PATH.is_file():
        return {"profiles": {}}
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {"profiles": {}}


def _state_save(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def _sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_excluded(rel: str) -> bool:
    norm = rel.replace("\\", "/")
    return any(fnmatch.fnmatch(norm, pat) for pat in EXCLUDE_PATTERNS)


def _profile_roots(profile: str) -> list[Path]:
    if profile not in PROFILE_PATHS:
        raise ValueError(f"profil inconnu: {profile}. Choix: {', '.join(PROFILE_PATHS)}")
    home = _home()
    roots: list[Path] = []
    for rel in PROFILE_PATHS[profile]:
        p = home / rel
        if p.exists():
            roots.append(p)
    return roots


def _iter_profile_files(profile: str) -> list[tuple[Path, str]]:
    home = _home()
    out: list[tuple[Path, str]] = []
    for root in _profile_roots(profile):
        if root.is_file() or root.is_symlink():
            rel = root.relative_to(home).as_posix()
            if not _is_excluded(rel):
                out.append((root, rel))
        elif root.is_dir():
            for p in root.rglob("*"):
                if not (p.is_file() or p.is_symlink()):
                    continue
                rel = p.relative_to(home).as_posix()
                if not _is_excluded(rel):
                    out.append((p, rel))
    out.sort(key=lambda x: x[1])
    return out


def local_manifest(profile: str) -> dict[str, Any]:
    files: dict[str, Any] = {}
    for path, rel in _iter_profile_files(profile):
        try:
            st = path.lstat()
            files[rel] = {
                "sha256": _sha256_path(path) if path.is_file() else None,
                "size": st.st_size,
                "mode": oct(st.st_mode & 0o777),
                "mtime": int(st.st_mtime),
            }
        except OSError:
            continue
    return {
        "profile": profile,
        "machine": _machine_id(),
        "home": str(_home()),
        "created_at": _now(),
        "files": files,
    }


def _remote_prefix(profile: str) -> str:
    return f"{settings().bucket}/sync/{profile}"


def _remote_manifest_uri(profile: str) -> str:
    return f"{_remote_prefix(profile)}/latest.manifest.json"


def _remote_archive_uri(profile: str, encrypted: bool | None = None) -> str:
    suffix = ".tar.gz.enc" if (encrypted if encrypted is not None else profile == "secrets-cli") else ".tar.gz"
    return f"{_remote_prefix(profile)}/latest{suffix}"


def _run(cmd: list[str], *, input_text: str | None = None, timeout: int = 300, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, input=input_text, text=True, capture_output=True, timeout=timeout)
    if check and proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"commande échouée ({proc.returncode}): {' '.join(cmd)}\n{msg}")
    return proc


def _gcloud_storage_cp(src: str, dst: str, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = _run(["gcloud", "storage", "cp", src, dst], timeout=600, check=False)
    if proc.returncode == 0:
        return proc
    try:
        _gcs_cp_with_adc(src, dst)
        return subprocess.CompletedProcess(["gcs-adc-cp", src, dst], 0, "", "")
    except Exception as exc:
        if check:
            msg = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(f"gcloud storage cp a échoué, fallback ADC aussi: {exc}\n{msg}") from exc
        return proc


def _parse_gs_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("gs://"):
        raise ValueError(f"URI GCS attendue: {uri}")
    rest = uri[5:]
    bucket, _, obj = rest.partition("/")
    if not bucket or not obj:
        raise ValueError(f"URI GCS incomplète: {uri}")
    return bucket, obj


def _adc_token() -> str:
    try:
        import google.auth
        from google.auth.transport.requests import Request
    except Exception as exc:  # pragma: no cover - dépend de l'env runtime
        raise RuntimeError("google-auth indisponible pour le fallback ADC") from exc
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(Request())
    token = getattr(creds, "token", None)
    if not token:
        raise RuntimeError("impossible d'obtenir un token ADC/metadata")
    return str(token)


def _http_request(url: str, *, method: str = "GET", data: bytes | None = None, content_type: str | None = None) -> bytes:
    headers = {"Authorization": f"Bearer {_adc_token()}"}
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=600) as resp:  # noqa: S310 - URL GCS contrôlée par config utilisateur
        return resp.read()


def _gcs_cp_with_adc(src: str, dst: str) -> None:
    """Minimal GCS cp fallback using Application Default Credentials/metadata."""
    if src.startswith("gs://") and not dst.startswith("gs://"):
        bucket, obj = _parse_gs_uri(src)
        url = "https://storage.googleapis.com/storage/v1/b/{}/o/{}?alt=media".format(
            urllib.parse.quote(bucket, safe=""),
            urllib.parse.quote(obj, safe=""),
        )
        data = _http_request(url)
        path = Path(dst).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return
    if dst.startswith("gs://") and not src.startswith("gs://"):
        bucket, obj = _parse_gs_uri(dst)
        data = Path(src).expanduser().read_bytes()
        url = "https://storage.googleapis.com/upload/storage/v1/b/{}/o?uploadType=media&name={}".format(
            urllib.parse.quote(bucket, safe=""),
            urllib.parse.quote(obj, safe=""),
        )
        _http_request(url, method="POST", data=data, content_type="application/octet-stream")
        return
    raise ValueError("fallback ADC supporte seulement gs:// ↔ fichier local")


def _download_remote_manifest(profile: str) -> dict[str, Any] | None:
    with tempfile.TemporaryDirectory() as td:
        dest = Path(td) / "manifest.json"
        proc = _gcloud_storage_cp(_remote_manifest_uri(profile), str(dest), check=False)
        if proc.returncode != 0 or not dest.is_file():
            return None
        return json.loads(dest.read_text())


def _artifact_sha(path: Path) -> str:
    return _sha256_path(path)


def _passphrase() -> str:
    env = os.environ.get("ZAB_WS_SYNC_PASSPHRASE")
    if env:
        return env
    pf = settings().passphrase_file
    if pf.is_file():
        return pf.read_text().strip()
    raise RuntimeError(
        "profil secrets-cli: passphrase absente. Définis ZAB_WS_SYNC_PASSPHRASE "
        f"ou crée {pf} (chmod 600) sur chaque machine."
    )


def _encrypt(src: Path, dst: Path) -> None:
    _run([
        "openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-salt",
        "-in", str(src), "-out", str(dst), "-pass", "stdin",
    ], input_text=_passphrase())


def _decrypt(src: Path, dst: Path) -> None:
    _run([
        "openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2",
        "-in", str(src), "-out", str(dst), "-pass", "stdin",
    ], input_text=_passphrase())


def _make_archive(profile: str, dest: Path) -> dict[str, Any]:
    manifest = local_manifest(profile)
    home = _home()
    with tarfile.open(dest, "w:gz") as tf:
        for path, rel in _iter_profile_files(profile):
            tf.add(path, arcname=rel, recursive=False)
    manifest["archive_sha256"] = _artifact_sha(dest)
    return manifest


def _changed_local(profile: str, current: dict[str, Any], state_profile: dict[str, Any] | None) -> list[str]:
    previous_files = (state_profile or {}).get("files") or {}
    current_files = current.get("files") or {}
    changed: list[str] = []
    keys = sorted(set(previous_files) | set(current_files))
    for key in keys:
        if (previous_files.get(key) or {}).get("sha256") != (current_files.get(key) or {}).get("sha256"):
            changed.append(key)
    return changed


def status(profile: str | None = None) -> dict[str, Any]:
    st = _state_load()
    profiles = [profile] if profile else list(PROFILE_PATHS)
    out: dict[str, Any] = {"machine": _machine_id(), "bucket": settings().bucket, "profiles": {}}
    for prof in profiles:
        current = local_manifest(prof)
        sp = (st.get("profiles") or {}).get(prof) or {}
        remote = _download_remote_manifest(prof)
        out["profiles"][prof] = {
            "local_files": len(current.get("files") or {}),
            "local_changed_since_last_sync": _changed_local(prof, current, sp),
            "last_remote_sha256": sp.get("remote_archive_sha256"),
            "remote_archive_sha256": (remote or {}).get("archive_sha256"),
            "remote_machine": (remote or {}).get("machine"),
            "remote_created_at": (remote or {}).get("created_at"),
            "encrypted": prof == "secrets-cli",
        }
    return out


def push(profile: str, *, force: bool = False) -> dict[str, Any]:
    current = local_manifest(profile)
    st = _state_load()
    sp = (st.get("profiles") or {}).get(profile) or {}
    remote = _download_remote_manifest(profile)
    local_changed = _changed_local(profile, current, sp)
    remote_sha = (remote or {}).get("archive_sha256")
    if remote_sha and sp.get("remote_archive_sha256") and remote_sha != sp.get("remote_archive_sha256") and local_changed and not force:
        return {
            "ok": False,
            "profile": profile,
            "reason": "remote_changed_and_local_changed",
            "message": "Le remote a changé depuis le dernier sync et des fichiers locaux ont changé. Lance d'abord `zab ws sync pull` ou utilise --force.",
            "local_changed": local_changed,
            "remote_archive_sha256": remote_sha,
            "last_remote_sha256": sp.get("remote_archive_sha256"),
        }
    with tempfile.TemporaryDirectory() as td:
        tar_path = Path(td) / "latest.tar.gz"
        manifest = _make_archive(profile, tar_path)
        upload_path = tar_path
        encrypted = profile == "secrets-cli"
        if encrypted:
            enc_path = Path(td) / "latest.tar.gz.enc"
            _encrypt(tar_path, enc_path)
            upload_path = enc_path
            manifest["encrypted"] = True
            manifest["encryption"] = "openssl enc -aes-256-cbc -pbkdf2 -salt"
            manifest["archive_sha256"] = _artifact_sha(enc_path)
        manifest_path = Path(td) / "latest.manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        _gcloud_storage_cp(str(upload_path), _remote_archive_uri(profile, encrypted=encrypted))
        _gcloud_storage_cp(str(manifest_path), _remote_manifest_uri(profile))
    st.setdefault("profiles", {})[profile] = {
        "remote_archive_sha256": manifest["archive_sha256"],
        "files": manifest.get("files") or {},
        "synced_at": _now(),
        "direction": "push",
    }
    _state_save(st)
    return {"ok": True, "profile": profile, "files": len(manifest.get("files") or {}), "archive_sha256": manifest["archive_sha256"]}


def _safe_extract_members(tf: tarfile.TarFile, dest: Path) -> list[tarfile.TarInfo]:
    members: list[tarfile.TarInfo] = []
    base = dest.resolve()
    for m in tf.getmembers():
        target = (dest / m.name).resolve()
        if not str(target).startswith(str(base) + os.sep) and target != base:
            raise RuntimeError(f"archive unsafe path: {m.name}")
        members.append(m)
    return members


def _copy_pulled_file(src: Path, dst: Path, rel: str, remote: dict[str, Any]) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    remote_home = str(remote.get("home") or "")
    local_home = str(_home())
    if rel == ".config/zab/config.yaml" and remote_home and remote_home != local_home:
        text = src.read_text(encoding="utf-8", errors="ignore")
        text = text.replace(remote_home, local_home)
        # Also cover the two known home roots in case the remote manifest is old.
        text = text.replace("/home/user", local_home)
        dst.write_text(text, encoding="utf-8")
        return
    shutil.copy2(src, dst, follow_symlinks=False)


def pull(profile: str, *, force: bool = False) -> dict[str, Any]:
    remote = _download_remote_manifest(profile)
    if not remote:
        return {"ok": False, "profile": profile, "reason": "no_remote", "message": "Aucun manifest remote trouvé."}
    st = _state_load()
    sp = (st.get("profiles") or {}).get(profile) or {}
    current = local_manifest(profile)
    local_changed = _changed_local(profile, current, sp)
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        downloaded = td_path / ("latest.tar.gz.enc" if profile == "secrets-cli" else "latest.tar.gz")
        archive = td_path / "latest.tar.gz"
        _gcloud_storage_cp(_remote_archive_uri(profile, encrypted=profile == "secrets-cli"), str(downloaded))
        if profile == "secrets-cli":
            _decrypt(downloaded, archive)
        else:
            archive = downloaded
        extract_dir = td_path / "extract"
        extract_dir.mkdir()
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(extract_dir, members=_safe_extract_members(tf, extract_dir))
        conflicts: list[str] = []
        home = _home()
        remote_files = remote.get("files") or {}
        previous_files = sp.get("files") or {}
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        for rel in sorted(remote_files):
            src = extract_dir / rel
            if not src.exists():
                continue
            dst = home / rel
            local_sha = current.get("files", {}).get(rel, {}).get("sha256")
            previous_sha = (previous_files.get(rel) or {}).get("sha256")
            remote_sha = (remote_files.get(rel) or {}).get("sha256")
            if dst.exists() and local_sha and previous_sha and local_sha != previous_sha and remote_sha != previous_sha and local_sha != remote_sha and not force:
                conflict = dst.with_name(dst.name + f".conflict-{_machine_id()}-{stamp}")
                conflict.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dst, conflict)
                conflicts.append(str(conflict))
            dst.parent.mkdir(parents=True, exist_ok=True)
            _copy_pulled_file(src, dst, rel, remote)
    applied = local_manifest(profile)
    st.setdefault("profiles", {})[profile] = {
        "remote_archive_sha256": remote.get("archive_sha256"),
        "files": applied.get("files") or {},
        "synced_at": _now(),
        "direction": "pull",
    }
    _state_save(st)
    return {"ok": True, "profile": profile, "files": len(remote.get("files") or {}), "conflicts": conflicts, "archive_sha256": remote.get("archive_sha256")}


def cli_watchlist() -> list[str]:
    cfg = load_user_config()
    raw = cfg.get("cli_watchlist") if isinstance(cfg, dict) else None
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        s = str(item).strip()
        if s and s not in out:
            out.append(s)
    return out


def cli_status() -> dict[str, Any]:
    items = cli_watchlist()
    rows = []
    for name in items:
        path = shutil.which(name)
        rows.append({"name": name, "ok": bool(path), "path": path})
    return {
        "total": len(rows),
        "ok": sum(1 for r in rows if r["ok"]),
        "missing": [r["name"] for r in rows if not r["ok"]],
        "items": rows,
    }


def cli_install_missing(*, dry_run: bool = False, names: list[str] | None = None) -> dict[str, Any]:
    status_payload = cli_status()
    missing = names or status_payload["missing"]
    results = []
    env = os.environ.copy()
    env["PATH"] = f"{Path.home() / '.local/bin'}:{Path.home() / '.npm-global/bin'}:{env.get('PATH', '')}"
    for name in missing:
        if shutil.which(name, path=env["PATH"]):
            results.append({"name": name, "status": "already_present"})
            continue
        cmd = CLI_INSTALL_COMMANDS.get(name)
        if not cmd:
            results.append({"name": name, "status": "unknown_installer"})
            continue
        if dry_run:
            results.append({"name": name, "status": "dry_run", "command": cmd})
            continue
        proc = subprocess.run(cmd, text=True, capture_output=True, env=env, timeout=900)
        results.append({
            "name": name,
            "status": "installed" if proc.returncode == 0 else "failed",
            "returncode": proc.returncode,
            "stdout_tail": (proc.stdout or "")[-1000:],
            "stderr_tail": (proc.stderr or "")[-1000:],
            "command": cmd,
        })
    return {"dry_run": dry_run, "results": results}
