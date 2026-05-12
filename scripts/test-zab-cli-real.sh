#!/usr/bin/env bash
# Tests CLI zab en conditions réelles (doctor).
# Prérequis : exécuter depuis la racine du dépôt zab, ou ZAB_SKILLS_ROOT défini.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "=== uv sync (racine zab) ==="
uv sync -q

echo "=== zab doctor ==="
uv run zab doctor

echo "=== OK ==="
echo "Pour smoke MCP : depuis ton dépôt skills — ZAB_SKILLS_ROOT=\$HOME/projects/skills uv run --directory \"$ROOT\" zab run --smoke"
