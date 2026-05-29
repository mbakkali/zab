"""Sync conversations multi-provider (CLI + job dashboard).

Exécution : ``uv run python -m zab.services.conversation_sync --help``
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from zab.paths import zab_repo_root
from zab.services.agent_memory_import import sync_agent_memory_to_postgres
from zab.services.conversations import parse_providers_arg, record_sync_index


def _print(line: str) -> None:
    print(line, flush=True)


def _run_mempalace_conversations() -> int:
    root = zab_repo_root()
    script = root / "scripts" / "mempalace_conversations_mine.py"
    if not script.is_file():
        _print(f"[zab] Script MemPalace absent : {script}")
        return 1
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(root),
        text=True,
        timeout=86400,
    )
    return int(proc.returncode or 0)


def run_sync(
    *,
    dry_run: bool,
    append: bool,
    with_mempalace: bool,
    workspace_storage_cursor: bool,
    providers: list[str] | None,
    batch_id: str,
) -> dict[str, Any]:
    if workspace_storage_cursor:
        raise ValueError(
            "workspace_storage_cursor refusé par défaut (volume élevé). "
            "À activer explicitement dans une future version."
        )

    prov_set = parse_providers_arg(providers)
    _print("[zab] Discovery locale…")
    from zab.services.agent_memory_import import discover_provider_dry_run_summary

    disc = discover_provider_dry_run_summary(providers=prov_set)
    _print(json.dumps({"phase": "discovery", "data": disc}, ensure_ascii=False))

    _print("[zab] Synchronisation Postgres (agents)…")
    summary = sync_agent_memory_to_postgres(
        replace=not append,
        batch_id=batch_id,
        dry_run=dry_run,
        providers=prov_set,
    )
    summary["phase"] = "postgres"
    _print(json.dumps(summary, ensure_ascii=False))

    if not dry_run and summary.get("inserted_documents", 0) >= 0:
        record_sync_index(batch_id=batch_id, summary=summary, providers=prov_set)
        _print("[zab] Index compact conversations mis à jour.")

    if with_mempalace and not dry_run:
        _print("[zab] MemPalace (palace conversations dédié)…")
        code = _run_mempalace_conversations()
        summary["mempalace_exit_code"] = code
        if code != 0:
            _print(f"[zab] MemPalace terminé avec code {code}")
    elif with_mempalace and dry_run:
        _print("[zab] MemPalace ignoré en dry-run.")

    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Sync conversations agents vers Postgres / MemPalace.")
    p.add_argument("--dry-run", action="store_true", help="Compte sans écrire en base")
    p.add_argument("--append", action="store_true", help="Ne pas supprimer les documents existants des providers ciblés")
    p.add_argument("--with-mempalace", action="store_true", help="Lancer scripts/mempalace_conversations_mine.py après Postgres")
    p.add_argument(
        "--workspace-storage-cursor",
        action="store_true",
        help="Non supporté pour l’instant (refusé)",
    )
    p.add_argument(
        "--providers",
        type=str,
        default="",
        help="Liste séparée par des virgules : cursor,claude,codex,kimi,hermes,gemini",
    )
    p.add_argument("--batch-id", type=str, default="agent-conversations-local")
    p.add_argument("--json", action="store_true", help="Dernière ligne = résumé JSON uniquement")
    args = p.parse_args(argv)

    prov_list = [x.strip() for x in args.providers.split(",") if x.strip()] or None
    try:
        summary = run_sync(
            dry_run=args.dry_run,
            append=args.append,
            with_mempalace=args.with_mempalace,
            workspace_storage_cursor=args.workspace_storage_cursor,
            providers=prov_list,
            batch_id=args.batch_id,
        )
    except ValueError as e:
        _print(f"[zab] {e}")
        return 2
    except Exception as e:  # noqa: BLE001
        _print(f"[zab] Erreur : {e}")
        return 1

    if args.json:
        print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
