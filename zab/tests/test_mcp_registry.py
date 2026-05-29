"""Tests registre MCP."""

from __future__ import annotations

from pathlib import Path

import pytest

from zab.services import mcp_registry


def test_merge_scan_detected_and_orphan(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    reg = tmp_path / ".config" / "zab" / "mcp-registry.json"
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(
        '{"version": 1, "servers": {"gone": {"status": "detected", "fingerprint": "abc"}}}',
        encoding="utf-8",
    )
    scanned = {
        "here": [{"name": "here", "fingerprint": "fp1", "kind": "stdio"}],
    }
    mcp_registry.merge_scan_into_registry(scanned_by_slug=scanned, conflict_slugs=set())
    doc = mcp_registry.load_registry_document()
    assert doc["servers"]["here"]["status"] == "detected"
    assert doc["servers"]["gone"]["status"] == "orphan"


def test_merge_conflict(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    scanned = {
        "dup": [
            {"name": "dup", "fingerprint": "a", "kind": "stdio"},
            {"name": "dup", "fingerprint": "b", "kind": "stdio"},
        ],
    }
    mcp_registry.merge_scan_into_registry(scanned_by_slug=scanned, conflict_slugs={"dup"})
    doc = mcp_registry.load_registry_document()
    assert doc["servers"]["dup"]["status"] == "conflict"


def test_ignored_persists(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    reg = tmp_path / ".config" / "zab" / "mcp-registry.json"
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(
        '{"version": 1, "servers": {"secret": {"status": "ignored", "fingerprint": "x"}}}',
        encoding="utf-8",
    )
    scanned = {"secret": [{"name": "secret", "fingerprint": "y", "kind": "stdio"}]}
    mcp_registry.merge_scan_into_registry(scanned_by_slug=scanned, conflict_slugs=set())
    doc = mcp_registry.load_registry_document()
    assert doc["servers"]["secret"]["status"] == "ignored"
