"""Scan des outils CLI, scripts et commandes disponibles."""

from __future__ import annotations

import subprocess
import sys
from typing import Any

from zab.paths import scripts_dir, zab_package_dir


def _zab_cli_commands() -> list[dict[str, Any]]:
    """Extrait les commandes de `zab --help` via introspection subprocess."""
    out: list[dict[str, Any]] = []
    try:
        result = subprocess.run(
            [sys.executable, "-m", "zab.cli", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(zab_package_dir().parent),
        )
        help_text = result.stdout
        in_commands = False
        for line in help_text.splitlines():
            stripped = line.strip()
            if stripped.lower() == "commands" or "─ commands " in stripped.lower():
                in_commands = True
                continue
            if in_commands:
                if not stripped or stripped.startswith("╭") or stripped.startswith("╰"):
                    break
                # Rich/Typer boxed format : "│ doctor      Vérifie uv, node...│"
                cleaned = stripped.strip("│").strip()
                if not cleaned or cleaned.startswith("-") or cleaned.startswith("Options"):
                    continue
                parts = cleaned.split(None, 1)
                if len(parts) == 2:
                    cmd, desc = parts
                    if cmd not in ("Commands", "Arguments", "Options") and not cmd.startswith("-"):
                        out.append(
                            {
                                "id": f"zab-{cmd}",
                                "name": f"zab {cmd}",
                                "kind": "cli",
                                "description": desc.strip(),
                            }
                        )
    except Exception:
        pass
    return out


def _repo_scripts() -> list[dict[str, Any]]:
    """Liste les scripts exécutables du dossier scripts/."""
    out: list[dict[str, Any]] = []
    root = scripts_dir()
    if not root.is_dir():
        return out
    for path in sorted(root.iterdir()):
        if not path.is_file():
            continue
        is_executable = path.stat().st_mode & 0o111
        is_script = path.suffix in (".sh", ".py")
        if not (is_executable or is_script):
            continue
        desc = ""
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            for line in lines[:5]:
                stripped = line.strip()
                if stripped.startswith("# Description:") or stripped.startswith("# description:"):
                    desc = stripped.split(":", 1)[1].strip()
                    break
                if stripped.startswith("#") and not stripped.startswith("#!/") and len(stripped) > 2:
                    desc = stripped.lstrip("# ").strip()
        except Exception:
            pass
        out.append(
            {
                "id": f"script-{path.name}",
                "name": path.name,
                "kind": "script",
                "path": str(path),
                "description": desc or "Script du dépôt",
            }
        )
    return out


def scan_tools() -> dict[str, Any]:
    """Agrège CLI commands + scripts."""
    return {
        "cli_commands": _zab_cli_commands(),
        "scripts": _repo_scripts(),
    }
