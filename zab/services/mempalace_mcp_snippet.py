"""Fragment JSON MCP pour MemPalace (binaire ``mempalace-mcp``)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

MEMPALACE_MCP_BIN = "mempalace-mcp"
MEMPALACE_CLI_BIN = "mempalace"


def resolve_mempalace_mcp_binary() -> str | None:
    return shutil.which(MEMPALACE_MCP_BIN)


def resolve_mempalace_cli_binary() -> str | None:
    return shutil.which(MEMPALACE_CLI_BIN)


def _version_line(binary: str) -> str | None:
    try:
        proc = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=5)
        text = (proc.stdout or proc.stderr or "").strip().splitlines()
        return text[0][:200] if text else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _help_head(binary: str) -> str | None:
    """``mempalace-mcp`` ne doit pas recevoir ``--version`` (démarre le serveur). On utilise ``-h``."""
    try:
        proc = subprocess.run([binary, "-h"], capture_output=True, text=True, timeout=5)
        text = (proc.stdout or proc.stderr or "").strip().splitlines()
        return text[0][:200] if text else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def build_mcp_server_entry(*, palace: str | None = None, binary_path: str | None = None) -> dict[str, Any]:
    """
    Bloc serveur stdio pour ``mcpServers`` (clé à fournir par l’appelant).

    :param palace: chemin palace optionnel (absolu après résolution).
    :param binary_path: surcharge pour les tests (sinon ``which mempalace-mcp``).
    """
    exe = (binary_path or "").strip() or resolve_mempalace_mcp_binary()
    if not exe:
        raise ValueError(
            "Binaire mempalace-mcp introuvable sur le PATH. Installez MemPalace : uv tool install mempalace"
        )
    block: dict[str, Any] = {"command": exe}
    if palace and str(palace).strip():
        p = Path(palace).expanduser().resolve()
        block["args"] = ["--palace", str(p)]
    return block


def mcp_servers_document(*, server_name: str, palace: str | None = None, binary_path: str | None = None) -> dict[str, Any]:
    """Document JSON minimal à fusionner : ``{\"mcpServers\": { … }}``."""
    key = server_name.strip() or "mempalace"
    return {"mcpServers": {key: build_mcp_server_entry(palace=palace, binary_path=binary_path)}}


def format_mcp_servers_json(*, server_name: str, palace: str | None = None, binary_path: str | None = None) -> str:
    return json.dumps(
        mcp_servers_document(server_name=server_name, palace=palace, binary_path=binary_path),
        ensure_ascii=False,
        indent=2,
    ) + "\n"


def doctor_payload(*, skills_configs_dir: Path | None) -> dict[str, Any]:
    """Données pour ``zab mempalace doctor`` (texte ou --json)."""
    mp = resolve_mempalace_cli_binary()
    mcp = resolve_mempalace_mcp_binary()
    out: dict[str, Any] = {
        "mempalace": {"on_path": mp is not None, "which": mp, "version_line": _version_line(mp) if mp else None},
        "mempalace_mcp": {
            "on_path": mcp is not None,
            "which": mcp,
            "help_head": _help_head(mcp) if mcp else None,
        },
    }
    if skills_configs_dir is not None:
        cur = skills_configs_dir / "cursor-mcp.json"
        desk = skills_configs_dir / "claude-desktop-mcp.json"
        out["mcp_config_paths"] = {
            "cursor": str(cur),
            "claude_desktop": str(desk),
        }
    return out
