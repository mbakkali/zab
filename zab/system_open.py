"""Ouverture de chemins dans le gestionnaire de fichiers local (Finder, Explorer, xdg-open)."""

from __future__ import annotations

import os
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
