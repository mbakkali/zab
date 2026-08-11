"""Indexation MemPalace « Code & docs » : documents seulement (mode ``projects``).

- Texte intégral : ``.md``, ``.pdf``, ``.txt``
- ``.csv`` : descriptif (chemin relatif, en-têtes, nombre de lignes de données) — pas le corps
- Autres extensions (code source, JSON, etc.) : exclus de l’ingestion

Exécution typique : interpréteur Python du bundle ``uv tool install mempalace`` avec
``PYTHONPATH`` pointant vers la racine du paquet zab (voir ``jobs.build_argv_for_preset``).
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import io
import sys
from pathlib import Path
from typing import Any

_DOCS_FULL = frozenset({".md", ".txt"})
_PDF = frozenset({".pdf"})
_CSV = frozenset({".csv"})
_ALLOWED = _DOCS_FULL | _PDF | _CSV

_LINE_CAP = 2_000_000


def resolve_mempalace_interpreter() -> str | None:
    """Interpréteur où ``import mempalace`` fonctionne (outil uv ou venv courant)."""
    import shutil

    exe = shutil.which("mempalace")
    if exe:
        try:
            first = Path(exe).read_text(encoding="utf-8", errors="ignore").splitlines()[0]
            if first.startswith("#!"):
                cand = first[2:].strip()
                if cand and Path(cand).name != "env" and Path(cand).is_file():
                    return cand
        except OSError:
            pass
    if importlib.util.find_spec("mempalace") is not None:
        return sys.executable
    return None


def _csv_descriptif(path: Path, project_path: Path) -> str:
    rel = path.relative_to(project_path).as_posix()
    header_line = ""
    try:
        with path.open(encoding="utf-8", errors="replace", newline="") as fp:
            header_line = fp.readline()
    except OSError:
        pass
    cols: list[str] = []
    if header_line.strip():
        try:
            row = next(csv.reader(io.StringIO(header_line)), [])
            cols = [c.strip() for c in row if isinstance(c, str)]
        except csv.Error:
            cols = [header_line.strip()[:500]]
    shown = ", ".join(cols[:48])
    if len(cols) > 48:
        shown += ", …"

    data_lines = 0
    truncated = False
    try:
        with path.open(encoding="utf-8", errors="replace", newline="") as fp:
            next(fp, None)
            for i, _ in enumerate(fp):
                if i >= _LINE_CAP:
                    truncated = True
                    break
                data_lines = i + 1
    except OSError:
        data_lines = 0

    extra = f" (tronqué au-delà de {_LINE_CAP} lignes)" if truncated else ""
    return (
        "[CSV — descriptif uniquement ; contenu des lignes non indexé]\n\n"
        f"Fichier : {rel}\n"
        f"Colonnes (en-tête) : {shown or '(non déterminé)'}\n"
        f"Lignes après en-tête : {data_lines}{extra}\n"
    )


def _pdf_text(path: Path) -> str:
    for mod in ("pypdf", "PyPDF2"):
        try:
            reader_cls = __import__(mod, fromlist=["PdfReader"]).PdfReader
        except ImportError:
            continue
        try:
            reader = reader_cls(str(path))
            parts: list[str] = []
            for page in reader.pages[:80]:
                t = page.extract_text()
                if t:
                    parts.append(t)
            text = "\n".join(parts).strip()
            if text:
                return f"[PDF — texte extrait via {mod}]\n\n{text}"
        except Exception as exc:  # noqa: BLE001
            return f"[PDF — extraction échouée ({mod}) : {type(exc).__name__}]\n"
    return (
        "[PDF — texte non extrait : installez pypdf dans l’environnement mempalace "
        "(ex. uv pip install --python $(dirname $(which mempalace))/python pypdf) "
        "ou privilégiez des sources .md/.txt.]\n"
    )


def _filter_scan_files(project_dir: str, scanned: list[Path]) -> list[Path]:
    project_path = Path(project_dir).expanduser().resolve()
    out: list[Path] = []
    for p in scanned:
        suf = p.suffix.lower()
        if suf not in _ALLOWED:
            continue
        try:
            p.relative_to(project_path)
        except ValueError:
            continue
        out.append(p)
    return out


def run_docs_only_mine(
    project_dir: str,
    *,
    wing: str | None = None,
    palace_path: str | None = None,
    respect_gitignore: bool = True,
    include_ignored: list[str] | None = None,
    agent: str = "mempalace",
    limit: int = 0,
    dry_run: bool = False,
) -> None:
    from mempalace.config import MempalaceConfig
    from mempalace.miner import READABLE_EXTENSIONS, mine, scan_project
    import mempalace.miner as miner_mod

    palace = (palace_path or "").strip() or MempalaceConfig().palace_path

    orig_ext = frozenset(READABLE_EXTENSIONS)
    try:
        miner_mod.READABLE_EXTENSIONS = set(orig_ext) | {".pdf"}
        scanned = scan_project(
            project_dir,
            respect_gitignore=respect_gitignore,
            include_ignored=include_ignored,
        )
    finally:
        miner_mod.READABLE_EXTENSIONS = set(orig_ext)

    files = _filter_scan_files(project_dir, scanned)
    if limit > 0:
        files = files[:limit]

    print(
        "\n[zab] MemPalace mine (documents seulement) : .md, .pdf, .txt en texte ; "
        ".csv en descriptif ; code source et autres formats exclus.\n",
        file=sys.stderr,
    )

    overrides: dict[str, str] = {}
    orig_read_text = Path.read_text
    orig_process_file = miner_mod.process_file

    def _read_text_patch(self: Path, *a: Any, **kw: Any) -> str:
        key = str(Path(self).resolve())
        if key in overrides:
            return overrides[key]
        return orig_read_text(self, *a, **kw)

    def _process_file_wrapped(
        filepath: Path,
        project_path: Path,
        collection: Any,
        wing: str,
        rooms: list,
        agent: str,
        dry_run: bool,
        closets_col: Any = None,
    ) -> tuple:
        key = str(filepath.resolve())
        suf = filepath.suffix.lower()
        if suf == ".csv":
            overrides[key] = _csv_descriptif(filepath, project_path)
        elif suf == ".pdf":
            overrides[key] = _pdf_text(filepath)
        Path.read_text = _read_text_patch  # type: ignore[method-assign]
        try:
            return orig_process_file(
                filepath, project_path, collection, wing, rooms, agent, dry_run, closets_col
            )
        finally:
            Path.read_text = orig_read_text  # type: ignore[method-assign]
            overrides.pop(key, None)

    miner_mod.process_file = _process_file_wrapped  # type: ignore[method-assign]
    try:
        mine(
            project_dir,
            palace,
            wing_override=wing,
            agent=agent,
            limit=0,
            dry_run=dry_run,
            respect_gitignore=respect_gitignore,
            include_ignored=include_ignored,
            files=files,
        )
    finally:
        miner_mod.process_file = orig_process_file  # type: ignore[method-assign]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="mempalace mine — documents seulement (zab)")
    parser.add_argument("dir", help="Répertoire projet à indexer")
    parser.add_argument("--wing", default=None, help="Surcharge du nom de wing MemPalace")
    parser.add_argument("--palace", default=None, help="Chemin palace (défaut : config MemPalace)")
    parser.add_argument("--agent", default="mempalace", help="Valeur « added_by »")
    parser.add_argument("--limit", type=int, default=0, help="Nombre max de fichiers (0 = tous)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-gitignore", action="store_true", help="Ne pas respecter .gitignore")
    parser.add_argument(
        "--include-ignored",
        action="append",
        default=None,
        help="Chemins projet relatifs à inclure même s'ils sont ignorés (répétable ou CSV)",
    )
    args = parser.parse_args(argv)

    include_ignored: list[str] = []
    for raw in args.include_ignored or []:
        include_ignored.extend(part.strip() for part in raw.split(",") if part.strip())

    run_docs_only_mine(
        args.dir,
        wing=args.wing,
        palace_path=args.palace,
        respect_gitignore=not args.no_gitignore,
        include_ignored=include_ignored or None,
        agent=args.agent,
        limit=args.limit,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
