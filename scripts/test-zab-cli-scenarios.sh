#!/usr/bin/env bash
# Scénarios : CLI zab + API dashboard locale.
# Usage : depuis la racine du dépôt zab — ./scripts/test-zab-cli-scenarios.sh
# Optionnel : ZAB_RUN_SMOKE=1 pour lancer zab run --smoke (nécessite ZAB_SKILLS_ROOT vers un repo skills complet).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${ZAB_SCENARIO_PORT:-19942}"
BASE="http://127.0.0.1:${PORT}"
ZAB_PID=""

cleanup() {
  if [[ -n "$ZAB_PID" ]] && kill -0 "$ZAB_PID" 2>/dev/null; then
    kill "$ZAB_PID" 2>/dev/null || true
    wait "$ZAB_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

echo "=== 1) Sync + doctor ==="
uv sync -q
uv run zab doctor
uv run zab sync --json

echo ""
echo "=== 2) Dashboard API (port $PORT) ==="
uv run zab dashboard --no-open --host 127.0.0.1 --port "$PORT" &
ZAB_PID=$!
for _ in $(seq 1 40); do
  if curl -sf "$BASE/api/health" >/dev/null; then
    break
  fi
  sleep 0.25
done
if ! curl -sf "$BASE/api/health" >/dev/null; then
  echo "ERREUR: l'API ne répond pas sur $BASE" >&2
  exit 1
fi

ask() {
  local title="$1"
  local path="$2"
  shift 2
  echo ""
  echo "--- Question : $title ---"
  curl -sS "$BASE$path" | python3 -c "$@"
}

echo ""
echo "=== 3) Extraits API ==="

ask "Health ?" "/api/health" "import json,sys; d=json.load(sys.stdin); print(d)"

ask "State index ?" "/api/state" \
  "import json,sys; d=json.load(sys.stdin); print('counts:', d.get('counts', {})); assert d.get('version')"

ask "Feature catalog ?" "/api/features" \
  "import json,sys; d=json.load(sys.stdin); print(len(d.get('features', [])), 'fonctionnalité(s)'); assert d.get('features')"

ask "Agent guide ?" "/api/agent-guide" \
  "import json,sys; d=json.load(sys.stdin); print(len(d.get('bootstrap_commands', [])), 'commande(s) bootstrap'); assert d.get('bootstrap_commands')"

ask "Skills index ?" "/api/skills?limit=3" \
  "import json,sys; d=json.load(sys.stdin); print(d.get('pagination', {}).get('total', 0), 'skill(s) indexée(s)')"

ask "Code tools ?" "/api/code-tools?limit=5" \
  "import json,sys; d=json.load(sys.stdin); print(d.get('pagination', {}).get('total', 0), 'outil(s)')"

echo ""
echo "--- Action : Context Pack ---"
curl -sS -X POST "$BASE/api/context-pack" \
  -H 'content-type: application/json' \
  -d '{"limit": 20}' | python3 -c "import json,sys; d=json.load(sys.stdin); print('path:', d.get('path')); print('bytes:', d.get('bytes')); assert d.get('bytes', 0) > 0"

ask "Scan (persist=0) — cursor_cody présent ?" "/api/scan" \
  "import json,sys; d=json.load(sys.stdin); print('cursor_cody keys:', list((d.get('cursor_cody') or {}).keys())[:8])"

ask "Combien d'organisations ?" "/api/orgs" "import json,sys; d=json.load(sys.stdin); print(len(d), 'org(s)')"

ask "Combien de connecteurs ?" "/api/connectors?limit=5" \
  "import json,sys; d=json.load(sys.stdin); print(d.get('pagination', {}).get('total', 0), 'connecteur(s)')"

ask "Mémoire configurée ?" "/api/memory/status" \
  "import json,sys; d=json.load(sys.stdin); print('configured:', d.get('configured'), 'connected:', d.get('connected'))"

if [[ "${ZAB_RUN_SMOKE:-}" == "1" ]]; then
  echo ""
  echo "=== 4) Smoke MCP ==="
  uv run zab run --smoke
fi

echo ""
echo "=== OK ==="
