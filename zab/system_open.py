"""Ouverture de chemins, éditeurs et commandes terminal locales."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


def open_os_path(path: Path) -> None:
    p = path.expanduser().resolve()
    if sys.platform == "darwin":
        subprocess.run(["open", str(p)], check=False)
    elif sys.platform == "win32":
        os.startfile(str(p))
    else:
        subprocess.run(["xdg-open", str(p)], check=False)


def open_in_editor(path: Path, *, line: int | None = None) -> str:
    """
    Ouvre un fichier dans Cursor / VS Code à la ligne demandée, sinon via l’app par défaut.

    Retourne une courte étiquette : ``cursor``, ``code``, ``open``, ``startfile``, ``xdg-open``.
    """
    p = path.expanduser().resolve()
    loc = f"{p}:{line}" if line and line > 0 else str(p)
    for binary, flag in (("cursor", "-g"), ("code", "-g"), ("code", "--goto")):
        if shutil.which(binary):
            subprocess.run([binary, flag, loc], check=False)
            return binary
    open_os_path(p)
    if sys.platform == "darwin":
        return "open"
    if sys.platform == "win32":
        return "startfile"
    return "xdg-open"


def _applescript_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def open_command_in_terminal(command: list[str], *, cwd: Path | None = None, title: str | None = None) -> str:
    """Open a new terminal window/tab and run a command, keeping output visible."""
    if not command:
        raise ValueError("commande vide")
    workdir = (cwd or Path.home()).expanduser().resolve()
    if not workdir.is_dir():
        raise ValueError(f"cwd introuvable: {workdir}")

    argv = list(command)
    resolved = shutil.which(argv[0])
    if resolved:
        argv[0] = resolved
    command_line = shlex.join(argv)
    label = (title or "zab cli-check").replace("\n", " ").strip()
    display_line = "$ " + command_line
    script = (
        f"cd {shlex.quote(str(workdir))}; "
        f"printf '\\033]0;%s\\007' {shlex.quote(label)}; "
        f"printf '%s\\n' {shlex.quote(display_line)}; "
        f"{command_line}; "
        "status=$?; "
        "echo; "
        "echo \"[zab] exit $status\"; "
        "exec ${SHELL:-/bin/zsh} -l"
    )

    if sys.platform == "darwin":
        subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "Terminal" to activate',
                "-e",
                f'tell application "Terminal" to do script {_applescript_string(script)}',
            ],
            check=False,
        )
        return "terminal"

    if sys.platform == "win32":
        subprocess.Popen(["cmd", "/c", "start", "cmd", "/k", script], cwd=str(workdir))  # noqa: S603,S607
        return "cmd"

    for terminal in ("gnome-terminal", "konsole", "xfce4-terminal", "xterm"):
        found = shutil.which(terminal)
        if not found:
            continue
        if terminal == "gnome-terminal":
            subprocess.Popen([found, "--", "bash", "-lc", script], cwd=str(workdir))  # noqa: S603
        elif terminal == "konsole":
            subprocess.Popen([found, "-e", "bash", "-lc", script], cwd=str(workdir))  # noqa: S603
        else:
            subprocess.Popen([found, "-e", "bash", "-lc", script], cwd=str(workdir))  # noqa: S603
        return terminal

    raise RuntimeError("aucun terminal supporté trouvé")
