#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${ZAB_E2E_PORT:-18742}"
cd "$ROOT"
if [[ ! -f zab-ui/dist/index.html ]]; then
  (cd zab-ui && npm ci && npm run build)
fi
exec uv run zab dashboard --no-open --host 127.0.0.1 --port "$PORT"
