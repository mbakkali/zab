#!/usr/bin/env bash
# Inventory and optionally delete the old Cloud Workstations stack.
#
# Dry-run/list mode is the default. To delete:
#   CONFIRM_DELETE_WORKSTATIONS=1 DELETE_WORKSTATION_CONFIG=1 DELETE_WORKSTATION_CLUSTER=1 bash decommission-workstations.sh
#
# This does not remove Zab's local workstation_sync replication helpers.
set -euo pipefail

PROJECT="${GCP_PROJECT:-flowmetrik-all}"
REGION="${GCP_REGION:-europe-west9}"
CLUSTER="${WORKSTATION_CLUSTER:-mbakkali-cluster}"
CONFIG="${WORKSTATION_CONFIG:-mbakkali-dev-config}"
DELETE="${CONFIRM_DELETE_WORKSTATIONS:-0}"
DELETE_CONFIG="${DELETE_WORKSTATION_CONFIG:-0}"
DELETE_CLUSTER="${DELETE_WORKSTATION_CLUSTER:-0}"

echo "Project:  $PROJECT"
echo "Region:   $REGION"
echo "Cluster:  $CLUSTER"
echo "Config:   $CONFIG"
echo

echo "== Cloud Workstations inventory =="
WORKSTATIONS="$(
  gcloud workstations list \
    --project="$PROJECT" \
    --region="$REGION" \
    --cluster="$CLUSTER" \
    --config="$CONFIG" \
    --format='value(name)' || true
)"

if [[ -z "$WORKSTATIONS" ]]; then
  echo "No workstations found for this cluster/config."
else
  printf '%s\n' "$WORKSTATIONS"
fi
echo

echo "== Workstation config =="
gcloud workstations configs describe "$CONFIG" \
  --project="$PROJECT" \
  --region="$REGION" \
  --cluster="$CLUSTER" \
  --format='yaml(name,machineType,persistentDirectories,host,timeout,idleTimeout,runningTimeout)' || true
echo

echo "== Workstation cluster =="
gcloud workstations clusters describe "$CLUSTER" \
  --project="$PROJECT" \
  --region="$REGION" \
  --format='yaml(name,conditions,privateClusterConfig)' || true
echo

echo "== Matching Compute Engine disks to review/snapshot =="
gcloud compute disks list \
  --project="$PROJECT" \
  --filter='zone:(europe-west9-b OR europe-west9-c) AND (name~workstation OR name~mbakkali)' \
  --format='table(name,zone.basename(),type.basename(),sizeGb,status,users)' || true
echo

if [[ "$DELETE" != "1" ]]; then
  cat <<'EOF'
Dry run only. Snapshot anything valuable, then rerun with:
  CONFIRM_DELETE_WORKSTATIONS=1

Optional:
  DELETE_WORKSTATION_CONFIG=1
  DELETE_WORKSTATION_CLUSTER=1
EOF
  exit 0
fi

echo "== Deleting workstations =="
if [[ -n "$WORKSTATIONS" ]]; then
  while IFS= read -r full_name; do
    [[ -z "$full_name" ]] && continue
    workstation="${full_name##*/}"
    echo "Deleting workstation: $workstation"
    gcloud workstations delete "$workstation" \
      --project="$PROJECT" \
      --region="$REGION" \
      --cluster="$CLUSTER" \
      --config="$CONFIG" \
      --quiet
  done <<< "$WORKSTATIONS"
else
  echo "No workstation to delete."
fi

if [[ "$DELETE_CONFIG" == "1" ]]; then
  echo "== Deleting workstation config: $CONFIG =="
  gcloud workstations configs delete "$CONFIG" \
    --project="$PROJECT" \
    --region="$REGION" \
    --cluster="$CLUSTER" \
    --quiet
fi

if [[ "$DELETE_CLUSTER" == "1" ]]; then
  echo "== Deleting workstation cluster: $CLUSTER =="
  gcloud workstations clusters delete "$CLUSTER" \
    --project="$PROJECT" \
    --region="$REGION" \
    --quiet
fi

echo "Done. Re-check Billing SKUs after the next export cycle."
