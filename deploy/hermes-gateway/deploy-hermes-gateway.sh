#!/usr/bin/env bash
# Phase 2b/2c — build, push, and deploy the Hermes gateway to Cloud Run.
# REVIEW the README and the DECISIONS before running. This creates BILLABLE,
# always-on infrastructure (--min-instances=1).
set -euo pipefail

PROJECT="${GCP_PROJECT:-your-gcp-project}"
REGION="${GCP_REGION:-europe-west9}"
REPO="${REGION}-docker.pkg.dev/${PROJECT}/your-registry"
IMAGE="${REPO}/hermes-gateway:latest"
SQL_INSTANCE="${GCP_SQL_INSTANCE:-your-project:region:your-instance}"
HERMES_SRC="${HERMES_SRC:-$HOME/.hermes/hermes-agent}"
ZAB_SRC="${ZAB_SRC:-$(cd "$(dirname "$0")/../.." && pwd)}"
SKILLS_SRC="${ZAB_SKILLS_ROOT:-$HOME/skills}"
PROJECTS_SRC="${ZAB_PROJECTS_ROOT:-$HOME/projects}"
HOME_SCAN="${HOME}"
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "== 1/7 build Hermes base image =="
docker build -t hermes-agent:base "$HERMES_SRC"

echo "== 2/7 stage zab into build context (no .venv/.git) =="
rsync -a --delete \
  --exclude '.venv' --exclude '.git' --exclude 'node_modules' \
  --exclude 'zab-ui/node_modules' --exclude '__pycache__' \
  "$ZAB_SRC"/ "$HERE/zab"/

echo "== 3/7 stage skills bundle =="
rsync -a --delete \
  --exclude '.git' --exclude '.venv' --exclude 'node_modules' \
  --exclude '__pycache__' --exclude '.DS_Store' \
  "$SKILLS_SRC"/ "$HERE/skills"/

echo "== 4/7 stage projects + home scan context =="
# Projects: selective sync to keep image size reasonable
rsync -a --delete \
  --exclude '.git' --exclude '.venv' --exclude 'node_modules' \
  --exclude '__pycache__' --exclude '.DS_Store' \
  --exclude '*/data/*' --exclude '*/.cursor/*' \
  "$PROJECTS_SRC"/ "$HERE/projects"/

# Home scan: minimal — only dotfiles and config relevant to agent context
mkdir -p "$HERE/home"
rsync -a --delete \
  --include '.zshrc' --include '.bashrc' --include '.profile' \
  --include '.gitconfig' --include '.ssh/config' \
  --include '.config/***' --include '.hermes/***' \
  --exclude '*' \
  "$HOME_SCAN"/ "$HERE/home"/

echo "== 5/7 build gateway image =="
docker build -f "$HERE/Dockerfile.hermes-gateway" -t "$IMAGE" "$HERE"

echo "== 6/7 push to Artifact Registry =="
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
docker push "$IMAGE"

echo "== 7/7 deploy to Cloud Run =="
# DECISION (see README §Telegram conflict): long polling vs webhook, and
# whether this uses a SECOND bot token. Defaults below assume a 2nd bot in
# long-poll mode with min-instances=1.
gcloud run deploy hermes-gateway \
  --project="$PROJECT" \
  --region="$REGION" \
  --image="$IMAGE" \
  --add-cloudsql-instances="$SQL_INSTANCE" \
  --set-secrets="TELEGRAM_BOT_TOKEN=hermes-telegram-token:latest" \
  --set-secrets="OPENROUTER_API_KEY=hermes-openrouter-key:latest" \
  --set-secrets="MEHDI_MEMORY_DATABASE_URL=mehdi-mcp-reader-socket-dsn:latest" \
  --set-secrets="/secrets/vertex-sa.json=hermes-vertex-sa:latest" \
  --set-env-vars="GOOGLE_APPLICATION_CREDENTIALS=/secrets/vertex-sa.json" \
  --set-env-vars="TELEGRAM_ALLOWED_USERS=${TELEGRAM_ALLOWED_USERS:-}" \
  --set-env-vars="HERMES_HOME=/opt/data" \
  --set-env-vars="ZAB_SKILLS_ROOT=/config/skills" \
  --set-env-vars="ZAB_PROJECTS_ROOT=/workspace/projects" \
  --min-instances=1 \
  --max-instances=1 \
  --memory=2Gi \
  --cpu=2 \
  --timeout=3600 \
  --no-allow-unauthenticated

echo "Deployed. URL:"
gcloud run services describe hermes-gateway --project="$PROJECT" --region="$REGION" \
  --format='value(status.url)'
echo
echo "If using WEBHOOK mode, now set TELEGRAM_WEBHOOK_URL=<url>/telegram and"
echo "TELEGRAM_WEBHOOK_SECRET via another 'gcloud run services update'."
