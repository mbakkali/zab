#!/usr/bin/env bash
# Phase 2d — create GCP Secret Manager secrets for the Hermes gateway.
# Run ONCE (idempotent: re-running adds a new version). Review before running.
#
#   bash create-secrets.sh
#
# Reads sensitive values from your local Hermes config so nothing is
# hardcoded in git.
set -euo pipefail

PROJECT="${GCP_PROJECT:-your-gcp-project}"
HERMES_ENV="${HERMES_ENV:-$HOME/.hermes/.env}"
VERTEX_SA="${VERTEX_SA_PATH:-$GOOGLE_APPLICATION_CREDENTIALS}"

_get_env() { grep -E "^$1=" "$HERMES_ENV" | head -1 | cut -d= -f2- | sed "s/^'//;s/'$//"; }

create_or_update() {  # name  value
  local name="$1" value="$2"
  if gcloud secrets describe "$name" --project="$PROJECT" >/dev/null 2>&1; then
    printf '%s' "$value" | gcloud secrets versions add "$name" --project="$PROJECT" --data-file=- >/dev/null
    echo "  ↻ updated $name (new version)"
  else
    printf '%s' "$value" | gcloud secrets create "$name" --project="$PROJECT" \
      --replication-policy=automatic --data-file=- >/dev/null
    echo "  ✓ created $name"
  fi
}

echo "Project: $PROJECT"

# 1. Telegram bot token — see DECISION in README: a SECOND bot is strongly
#    recommended so cloud + local don't fight over one long-poll connection.
TG_TOKEN="$(_get_env TELEGRAM_BOT_TOKEN)"
echo ">> hermes-telegram-token  (currently the SAME token as local — change if using a 2nd bot)"
create_or_update "hermes-telegram-token" "$TG_TOKEN"

# 2. OpenRouter key (auxiliary models / fallback)
OR_KEY="$(_get_env OPENROUTER_API_KEY)"
[ -n "$OR_KEY" ] && create_or_update "hermes-openrouter-key" "$OR_KEY" || echo "  (skip openrouter — not set)"

# 3. Vertex SA JSON (so the container can mint its own VERTEX_ACCESS_TOKEN)
if [ -f "$VERTEX_SA" ]; then
  create_or_update "hermes-vertex-sa" "$(cat "$VERTEX_SA")"
else
  echo "  ⚠ Vertex SA not found at $VERTEX_SA — skipping hermes-vertex-sa"
fi

# 4. Reuse existing mehdi-mcp-reader-socket-dsn for Cloud SQL memory (no-op here)
echo ">> reusing existing secret: mehdi-mcp-reader-socket-dsn (Cloud SQL DSN)"

echo "Done. Verify: gcloud secrets list --project=$PROJECT"
