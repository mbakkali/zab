# Hermes Gateway → Cloud Run (optional deployment)

Deploy an always-on Hermes gateway on Cloud Run with zab MCP, Composio, and optional Cloud SQL memory.

**Status: optional operator tooling — not required for zab itself.**

## Files

| File | Purpose |
|------|---------|
| `Dockerfile.hermes-gateway` | `FROM hermes-agent:base` + zab + Composio + skills bundle |
| `config.container.yaml` | Minimal in-image Hermes config |
| `create-secrets.sh` | Create GCP Secret Manager secrets |
| `deploy-hermes-gateway.sh` | Build, push, deploy |
| `decommission-workstations.sh` | List/delete the old Cloud Workstations stack after snapshot review |

## Environment variables

Set before running the deploy scripts:

```bash
export GCP_PROJECT=your-gcp-project
export GCP_REGION=europe-west9
export GCP_SQL_INSTANCE=your-project:region:your-instance
export ZAB_SKILLS_ROOT=~/skills
export ZAB_PROJECTS_ROOT=~/projects
export TELEGRAM_ALLOWED_USERS=123456789   # optional
export VERTEX_SA_PATH=~/credentials/vertex-sa.json
```

## Telegram bot token

A Telegram bot allows **exactly one** long-poll consumer. If you also run a local gateway, either:

1. use a **second bot** for cloud (recommended), or
2. switch cloud to webhook mode and stop the local gateway, or
3. replace the local gateway entirely with cloud.

## Run order

```bash
cd deploy/hermes-gateway
bash create-secrets.sh
bash deploy-hermes-gateway.sh
```

Review billing implications (`--min-instances=1` keeps one instance warm).

## Exiting Cloud Workstations

Use this when the Hermes gateway moves away from Cloud Workstations. Zab's
replication helpers are intentionally kept: `zab ws sync ...` and
`zab/services/workstation_sync.py` remain useful as a Mac <-> GCS replication
path, even if the Cloud Workstations control plane is removed.

Default target:

```bash
export GCP_PROJECT=flowmetrik-all
export GCP_REGION=europe-west9
export WORKSTATION_CLUSTER=mbakkali-cluster
export WORKSTATION_CONFIG=mbakkali-dev-config
```

First run a read-only inventory:

```bash
bash decommission-workstations.sh
```

Before deleting, snapshot any disk or persistent directory you still need. The
script prints matching Compute Engine disks, but Cloud Workstations persistent
home storage can be managed by the Workstations service, so review the Google
Cloud console as well.

Then delete the stack:

```bash
export CONFIRM_DELETE_WORKSTATIONS=1
export DELETE_WORKSTATION_CONFIG=1
export DELETE_WORKSTATION_CLUSTER=1
bash decommission-workstations.sh
```

This order matters: workstations first, then config, then cluster. Removing the
cluster is what stops the Cloud Workstations control-plane billing.
