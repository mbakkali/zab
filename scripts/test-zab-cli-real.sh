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

echo "=== zab sync ==="
uv run zab sync --json

echo "=== zab config paths ==="
uv run zab config --paths

echo "=== zab features / agent-guide / inventory ==="
uv run zab features --json >/dev/null
uv run zab agent-guide --json >/dev/null
uv run zab inventory skills --limit 5 --json >/dev/null
uv run zab inventory connectors --limit 5 --json >/dev/null
uv run zab inventory code-tools --limit 5 --json >/dev/null

echo "=== zab context-pack ==="
uv run zab context-pack --limit 20 --json

echo "=== OK ==="
echo "For smoke MCP: from your skills repo — ZAB_SKILLS_ROOT=\$HOME/skills uv run --directory \"$ROOT\" zab run --smoke"
