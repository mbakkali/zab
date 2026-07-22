#!/usr/bin/env bash
# Démarre l'API FastAPI (reload) puis le serveur Vite de zab-ui avec proxy /api.
# Usage : depuis la racine du dépôt — `uv run zab dashboard-dev` ou `./scripts/zab-dashboard-dev.sh`
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

API_HOST="${ZAB_DASHBOARD_HOST:-127.0.0.1}"
API_PORT="${ZAB_DASHBOARD_PORT:-8750}"
UI_HOST="${ZAB_UI_DEV_HOST:-127.0.0.1}"
UI_PORT="${ZAB_UI_DEV_PORT:-5280}"
export ZAB_API_ORIGIN="http://${API_HOST}:${API_PORT}"
export ZAB_UI_DEV_HOST="${UI_HOST}"
export ZAB_UI_DEV_PORT="${UI_PORT}"

# Le script est souvent invoqué avec un `uv` hors PATH (agents, launchers) : résoudre explicitement.
UV_BIN="${ZAB_UV_BIN:-${UV_BIN:-}}"
if [[ -z "${UV_BIN}" ]]; then
  UV_BIN="$(command -v uv 2>/dev/null || true)"
fi
if [[ -z "${UV_BIN}" && -x "${HOME}/.local/bin/uv" ]]; then
  UV_BIN="${HOME}/.local/bin/uv"
fi
if [[ -z "${UV_BIN}" && -x "${HOME}/.cargo/bin/uv" ]]; then
  UV_BIN="${HOME}/.cargo/bin/uv"
fi
if [[ -z "${UV_BIN}" ]]; then
  echo "uv introuvable : ajoutez-le au PATH ou définissez ZAB_UV_BIN" >&2
  exit 1
fi

UVICORN_PID=""
cleanup() {
  if [[ -n "$UVICORN_PID" ]] && kill -0 "$UVICORN_PID" 2>/dev/null; then
    kill "$UVICORN_PID" 2>/dev/null || true
    wait "$UVICORN_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "→ API zab : http://${API_HOST}:${API_PORT}/ (reload Python)"
"${UV_BIN}" run zab dashboard --no-open --host "$API_HOST" --port "$API_PORT" --reload &
UVICORN_PID=$!

echo "→ Attente de /api/health …"
for _ in $(seq 1 120); do
  if curl -sf "${ZAB_API_ORIGIN}/api/health" >/dev/null; then
    break
  fi
  sleep 0.25
done

UI_DIR="$ROOT/zab-ui"
if [[ ! -d "$UI_DIR" ]]; then
  echo "Répertoire zab-ui introuvable : $UI_DIR" >&2
  exit 1
fi

if [[ ! -d "$UI_DIR/node_modules" ]]; then
  echo "→ npm install dans zab-ui …"
  (cd "$UI_DIR" && npm install)
fi

echo "→ Vite http://${UI_HOST}:${UI_PORT}/ (proxy /api → ${ZAB_API_ORIGIN})"
# Sous `uv run`, PATH peut placer le Node « helper » de l’IDE (souvent x64/Rosetta) avant un Node
# arm64 natif — Rolldown/Vite 8 charge alors des bindings @rolldown/binding-* incompatibles.
# Ne pas se fier à `uname -m` (Rosetta / agents peuvent mentir) : préférer Homebrew si présent.
if [[ "$(uname -s)" == Darwin ]]; then
  if [[ -x /opt/homebrew/bin/node ]]; then
    export PATH="/opt/homebrew/bin:${PATH}"
  elif [[ -x /usr/local/bin/node ]]; then
    export PATH="/usr/local/bin:${PATH}"
  fi
fi
(cd "$UI_DIR" && exec npm run dev)
