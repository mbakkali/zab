#!/usr/bin/env bash
# Pre-publish secret and PII scan for the zab repository.
# Usage: ./scripts/publish-check.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FAIL=0
RG_BASE=(rg -n -i --hidden --glob '!.git' --glob '!uv.lock' --glob '!node_modules' --glob '!dist' --glob '!.venv' --glob '!scripts/publish-check.sh')

scan_pattern() {
  local label="$1"
  local pattern="$2"
  shift 2
  if "${RG_BASE[@]}" "$@" "$pattern" . >/tmp/zab-publish-hit.txt 2>/dev/null; then
    echo "FAIL pattern: $label"
    head -20 /tmp/zab-publish-hit.txt
    FAIL=1
  fi
}

echo "== publish-check: forbidden patterns =="

scan_pattern "telegram bot token" '[0-9]{8,10}:[A-Za-z0-9_-]{35,}' --glob '!zab/tests/**'
scan_pattern "composio user api key" 'uak_[A-Za-z0-9]{8,}' --glob '!zab/tests/**'
scan_pattern "personal username" 'mbakkali' --glob '!zab/tests/**' --glob '!zab/CONNECTORS-PLAN.md'
scan_pattern "personal email" 'mehdi\.bakkali|mehdi@flowmetrik' --glob '!zab/tests/**'
scan_pattern "telegram user id" '8996436319'
scan_pattern "personal bot handle" 'Bakoutbot'
scan_pattern "personal home path" '/Users/mbakkali' --glob '!zab/CONNECTORS-PLAN.md'
scan_pattern "client gcp project" 'vg1np-apps-aibuygc-pprd-ce'

echo ""
echo "== publish-check: forbidden files =="
FORBIDDEN=(
  exampleconf.txt
  flowmetrik-openwebui/hermes-state/state.db
)
for f in "${FORBIDDEN[@]}"; do
  if [[ -e "$f" ]] && ! git check-ignore -q "$f" 2>/dev/null; then
    echo "FAIL forbidden file present (not ignored): $f"
    FAIL=1
  fi
done

if command -v gitleaks >/dev/null 2>&1; then
  echo ""
  echo "== publish-check: gitleaks =="
  if ! gitleaks detect --source . --no-banner --redact; then
    FAIL=1
  fi
else
  echo "gitleaks not installed — skipping (recommended: brew install gitleaks)"
fi

if [[ "$FAIL" -ne 0 ]]; then
  echo ""
  echo "publish-check FAILED"
  exit 1
fi

echo ""
echo "publish-check OK"
