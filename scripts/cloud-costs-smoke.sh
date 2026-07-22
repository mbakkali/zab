#!/usr/bin/env bash
set -euo pipefail

GCP_CONFIG="${GCP_CONFIG:-zab-flowmetrik-costs}"
GCP_BILLING_ACCOUNTS="${GCP_BILLING_ACCOUNTS:-015127-B40F4A-7CB527,016C98-D0BEA0-3F18DB}"
GCP_BILLING_EXPORTS="${GCP_BILLING_EXPORTS:-flowmetrik-all:flowmetrik_billing_export,agile-ipmvp-prod:flowmetrik_billing_export}"

SCW_CONFIG_PATH="${SCW_CONFIG_PATH:-/Users/mbakkali/projects/credentials/scaleway-config.yaml}"
SCW_PROFILE="${SCW_PROFILE:-arpastrance-profile}"

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing command: $1" >&2
    exit 127
  fi
}

need gcloud
need bq
need scw
need jq

echo "== GCP / Flowmetrik =="
gcloud config configurations list \
  --format="table(name,is_active,properties.core.account,properties.core.project)" \
  | awk -v cfg="$GCP_CONFIG" 'NR == 1 || $1 == cfg { print }'

IFS="," read -r -a gcp_billing_accounts <<<"$GCP_BILLING_ACCOUNTS"
for account in "${gcp_billing_accounts[@]}"; do
  gcloud --configuration="$GCP_CONFIG" billing accounts describe "$account" \
    --format="table(name,displayName,open)"
done

IFS="," read -r -a gcp_billing_exports <<<"$GCP_BILLING_EXPORTS"
union_sql=""
for export_ref in "${gcp_billing_exports[@]}"; do
  project="${export_ref%%:*}"
  dataset="${export_ref#*:}"
  CLOUDSDK_ACTIVE_CONFIG_NAME="$GCP_CONFIG" bq --project_id="$project" show "${project}:${dataset}" >/dev/null
  select_sql="SELECT '${project}' AS export_project, '${dataset}' AS export_dataset, table_name FROM \`${project}.${dataset}.INFORMATION_SCHEMA.TABLES\`"
  if [[ -z "$union_sql" ]]; then
    union_sql="$select_sql"
  else
    union_sql="${union_sql} UNION ALL ${select_sql}"
  fi
done

tables_json="$(
  CLOUDSDK_ACTIVE_CONFIG_NAME="$GCP_CONFIG" bq query \
    --use_legacy_sql=false \
    --format=json \
    "${union_sql} ORDER BY export_project, export_dataset, table_name" \
    2>/dev/null
)"

table_count="$(jq 'length' <<<"$tables_json")"
if [[ "$table_count" == "0" ]]; then
  echo "Billing export datasets reachable, but no billing export tables are present yet."
else
  echo "Billing export tables:"
  jq -r '.[] | "  - \(.export_project).\(.export_dataset).\(.table_name)"' <<<"$tables_json"
fi

echo
echo "== Scaleway / ARP Astrance =="
projects_json="$(SCW_CONFIG_PATH="$SCW_CONFIG_PATH" SCW_PROFILE="$SCW_PROFILE" scw account project list -o json)"
consumption_json="$(SCW_CONFIG_PATH="$SCW_CONFIG_PATH" SCW_PROFILE="$SCW_PROFILE" scw billing consumption list -o json)"

jq -r --argjson projects "$projects_json" '
  def eur: ((.value.units // 0) + ((.value.nanos // 0) / 1000000000));
  ($projects | reduce .[] as $p ({}; .[$p.id] = $p.name)) as $names
  | group_by(.project_id)
  | map({
      project_id: .[0].project_id,
      project_name: ($names[.[0].project_id] // "unknown"),
      eur: (map(eur) | add)
    })
  | sort_by(-.eur)
  | .[:12][]
  | [.project_name, .project_id, (.eur | tostring)]
  | @tsv
' <<<"$consumption_json" \
  | awk 'BEGIN { printf "%-24s %-38s %10s\n", "PROJECT", "PROJECT_ID", "EUR"; }
         { printf "%-24s %-38s %10.2f\n", $1, $2, $3; }'
