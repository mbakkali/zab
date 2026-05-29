"""Ouverture de chemins dans le gestionnaire de fichiers ou l’éditeur local."""

from __future__ import annotations

import os
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
