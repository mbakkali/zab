"""Tests filtrage « documents seulement » MemPalace (zab)."""

from __future__ import annotations

from pathlib import Path

from zab.services.mempalace_mine_projects_docs import _csv_descriptif, _filter_scan_files


def test_csv_descriptif_counts(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    f = root / "data.csv"
    f.write_text("a,b,c\n1,2,3\n4,5,6\n", encoding="utf-8")
    text = _csv_descriptif(f, root)
    assert "a, b, c" in text or "a,b,c" in text
    assert "Lignes après en-tête : 2" in text
    assert "non indexé" in text


def test_filter_scan_files_keeps_only_allowed(tmp_path: Path) -> None:
    root = tmp_path / "p"
    root.mkdir()
    (root / "a.md").write_text("x", encoding="utf-8")
    (root / "b.py").write_text("x = 1", encoding="utf-8")
    scanned = [root / "a.md", root / "b.py", root / "c.txt"]
    (root / "c.txt").write_text("y", encoding="utf-8")
    out = _filter_scan_files(str(root), scanned)
    assert set(out) == {root / "a.md", root / "c.txt"}
