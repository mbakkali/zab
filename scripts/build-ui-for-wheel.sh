#!/usr/bin/env bash
# Copy zab-ui/dist into the Python package for wheel packaging (optional).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/zab-ui/dist"
DEST="$ROOT/zab/ui_dist"

if [[ ! -d "$SRC" ]]; then
  echo "Missing $SRC — run: cd zab-ui && npm ci && npm run build" >&2
  exit 1
fi

rm -rf "$DEST"
cp -R "$SRC" "$DEST"
echo "Copied UI build to $DEST"
