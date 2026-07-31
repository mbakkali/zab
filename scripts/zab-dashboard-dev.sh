#!/usr/bin/env bash
# Démarre l'API FastAPI (reload) puis le serveur Vite de zab-ui avec proxy /api.
# Usage : depuis la racine du dépôt — `uv run zab dashboard-dev` ou `./scripts/zab-dashboard-dev.sh`
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

API_HOST="${ZAB_DASHBOARD_HOST:-127.0.0.1}"
API_PORT="${ZAB_DASHBOARD_PORT:-8750}"
API_PORT_EXPLICIT=0
[[ -n "${ZAB_DASHBOARD_PORT:-}" ]] && API_PORT_EXPLICIT=1
UI_HOST="${ZAB_UI_DEV_HOST:-127.0.0.1}"
UI_PORT="${ZAB_UI_DEV_PORT:-5280}"

port_available() {
  /usr/bin/python3 - "$1" "$2" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])
family = socket.AF_INET6 if ":" in host else socket.AF_INET
with socket.socket(family, socket.SOCK_STREAM) as sock:
    # Même option que uvicorn et Vite : sans elle, un port simplement en TIME_WAIT
    # après un arrêt récent était annoncé « occupé » alors que le serveur peut s'y lier.
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError:
        raise SystemExit(1)
PY
}

# Le port peut être tenu par une API zab encore vivante (session précédente dont le
# serveur Vite est mort, process orphelin, autre terminal). Dans ce cas il faut la
# réutiliser au lieu d'échouer : c'est le mode d'échec le plus fréquent des lanceurs.
api_is_zab() {
  curl -sf --max-time 2 "http://${1}:${2}/api/health" 2>/dev/null \
    | grep -q '"service"[[:space:]]*:[[:space:]]*"zab"'
}

# `|| true` obligatoire : sous `set -o pipefail`, un lsof sans résultat ferait échouer
# tout le script depuis une simple ligne de diagnostic.
describe_port_holder() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP "-iTCP:${1}" -sTCP:LISTEN 2>/dev/null | tail -n +2 | head -3 || true
  fi
  return 0
}

REUSE_API=0
if ! port_available "$API_HOST" "$API_PORT"; then
  if api_is_zab "$API_HOST" "$API_PORT"; then
    REUSE_API=1
    echo "→ API zab déjà en écoute sur ${API_HOST}:${API_PORT} — réutilisation (pas de second serveur)."
    echo "  Note : cette API n'est pas en --reload. Pour une API dev dédiée : zab dashboard-dev --port 8751"
  elif [[ "$API_PORT_EXPLICIT" == "1" ]]; then
    echo "Port API explicite ${API_HOST}:${API_PORT} occupé par un service qui n'est pas l'API zab." >&2
    describe_port_holder "$API_PORT" >&2
    echo "Libère le port, ou relance sans ZAB_DASHBOARD_PORT pour un repli automatique." >&2
    exit 1
  else
    for candidate in $(seq 8751 8799); do
      if port_available "$API_HOST" "$candidate"; then
        API_PORT="$candidate"
        echo "→ Port 8750 occupé ; API dev isolée sur ${API_PORT}"
        break
      fi
    done
    if ! port_available "$API_HOST" "$API_PORT"; then
      echo "Aucun port API disponible entre 8751 et 8799" >&2
      exit 1
    fi
  fi
fi

if ! port_available "$UI_HOST" "$UI_PORT"; then
  echo "→ Port UI ${UI_HOST}:${UI_PORT} occupé ; Vite en choisira un autre (voir la ligne « Local: » ci-dessous)." >&2
  describe_port_holder "$UI_PORT" >&2
fi

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
VITE_PID=""
# `uv run` et `npm` relaient la commande à un enfant : tuer le seul PID direct laisserait
# l'API ou Vite vivants et les ports occupés pour les lancements suivants. On tue l'arbre.
kill_tree() {
  local pid="$1"
  local child
  for child in $(pgrep -P "$pid" 2>/dev/null); do
    kill_tree "$child"
  done
  kill "$pid" 2>/dev/null || true
}

cleanup() {
  local pid
  for pid in "$VITE_PID" "$UVICORN_PID"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill_tree "$pid"
      wait "$pid" 2>/dev/null || true
    fi
  done
}
trap cleanup EXIT INT TERM

if [[ "$REUSE_API" == "0" ]]; then
  echo "→ API zab : http://${API_HOST}:${API_PORT}/ (reload Python)"
  "${UV_BIN}" run zab dashboard --no-open --host "$API_HOST" --port "$API_PORT" --reload &
  UVICORN_PID=$!

  echo "→ Attente de /api/health …"
  API_READY=0
  for _ in $(seq 1 120); do
    if curl -sf "${ZAB_API_ORIGIN}/api/health" >/dev/null; then
      API_READY=1
      break
    fi
    if ! kill -0 "$UVICORN_PID" 2>/dev/null; then
      break
    fi
    sleep 0.25
  done
  if [[ "$API_READY" != "1" ]]; then
    echo "L'API zab n'a pas répondu sur ${ZAB_API_ORIGIN}/api/health — abandon." >&2
    exit 1
  fi
fi

UI_DIR="$ROOT/zab-ui"
if [[ ! -d "$UI_DIR" ]]; then
  echo "Répertoire zab-ui introuvable : $UI_DIR" >&2
  exit 1
fi

# Sous `uv run`, PATH peut placer le Node « helper » de l’IDE (souvent x64/Rosetta) avant un Node
# arm64 natif — Rolldown/Vite 8 charge alors des bindings @rolldown/binding-* incompatibles.
# Ne pas se fier à `uname -m` (Rosetta / agents peuvent mentir) : préférer Homebrew si présent.
# Résolu avant tout appel npm : lancé depuis un launcher (Raycast, launchd), le PATH hérité
# peut ne contenir ni node ni npm.
if [[ "$(uname -s)" == Darwin ]]; then
  if [[ -x /opt/homebrew/bin/node ]]; then
    export PATH="/opt/homebrew/bin:${PATH}"
  elif [[ -x /usr/local/bin/node ]]; then
    export PATH="/usr/local/bin:${PATH}"
  fi
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm introuvable : ajoutez Node au PATH (ex. /opt/homebrew/bin) pour lancer zab-ui." >&2
  exit 1
fi

if [[ ! -d "$UI_DIR/node_modules" ]]; then
  echo "→ npm install dans zab-ui …"
  (cd "$UI_DIR" && npm install)
fi

echo "→ Vite http://${UI_HOST}:${UI_PORT}/ (proxy /api → ${ZAB_API_ORIGIN})"
# Pas de `exec` : il remplacerait ce shell et neutraliserait le trap de nettoyage.
# Sans lui, la mort de Vite laissait l'API orpheline (PPID 1), qui gardait le port
# et faisait échouer tous les lancements suivants.
if [[ -t 0 ]]; then
  # Terminal interactif : Vite au premier plan, pour garder son TTY et ses raccourcis.
  (cd "$UI_DIR" && npm run dev)
else
  # Lanceur sans TTY (Raycast, launchd, nohup) : Vite en arrière-plan, sinon un SIGTERM
  # sur ce script resterait différé jusqu'à la fin de Vite et laisserait tout en vie.
  (cd "$UI_DIR" && npm run dev) </dev/null &
  VITE_PID=$!
  wait "$VITE_PID" || true
fi
