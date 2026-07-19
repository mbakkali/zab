#!/usr/bin/env bash
# Pre-publish secret and private-content scan for the zab repository.
# Usage:
#   ./scripts/publish-check.sh
#   ./scripts/publish-check.sh --pre-push   # used by .githooks/pre-push
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODE="tracked"
if [[ "${1:-}" == "--pre-push" ]]; then
  MODE="pre-push"
  shift
fi

PYTHON_BIN="${PYTHON:-python3}"
exec "$PYTHON_BIN" -m zab.services.publish_guard --mode "$MODE" "$@"
