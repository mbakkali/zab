# Secrets: a local hub, mirrored to Google Secret Manager

Zab tracks a catalogue of environment variables (`zab/secrets_catalog.py`) and
keeps them in one place, with a remote copy in case that place is lost.

| Where | Role |
|---|---|
| project `.env` files | where a value is first written, by whoever set it up |
| `~/.config/zab/.env` | **the hub — the source of truth.** Always plaintext. This is what scripts read. |
| Google Secret Manager | **a mirror.** A backup image, nothing reads from it at runtime. |

The direction of authority matters: the hub wins. The mirror exists so that
losing a machine does not lose a credential — it is never the thing an
application resolves against.

**Nothing is ever removed from disk.** An earlier design replaced the local
value with an `sm://` reference. That broke every consumer of the file and
inverted the two roles; it has been removed.

## Configure

```yaml
# ~/.config/zab/config.yaml
secret_manager:
  project: my-gcp-project
  prefix: zab-
  # Only needed for secrets that already exist under a different name.
  # Without it, the id is derived: QONTO_API_KEY -> zab-qonto-api-key,
  # which would not find a secret someone created as `qonto-prod-key`.
  map:
    QONTO_API_KEY: qonto-prod-key
```

Declare `project` explicitly. Without it, zab falls back to
`gcloud config get-value project`, which is rarely the project holding your
secrets — and if the Secret Manager API is disabled there, every call fails
naming a project you never chose.

Authentication is whatever `gcloud` already uses: `gcloud auth login` on a
workstation, the attached service account on a VM. Zab holds no credential
file of its own.

## Commands

```bash
zab secrets status                # where each variable lives, and in what form
zab secrets collect --apply       # project .env files -> the hub
zab secrets mirror --apply        # the hub -> Secret Manager (touches no file)
zab secrets restore --apply       # Secret Manager -> the hub, for what is missing
```

All four default to a dry run.

`collect` and `restore` never overwrite a value already in the hub — `collect`
takes `--force` if you mean to. Both update keys in place and append new ones,
so comments, ordering and trailing notes survive; a `.env` line often carries
the only record of where a key came from or how to rotate it.

`mirror` reads the hub and writes to the provider. It reads the current remote
version first and skips anything already identical, so running it repeatedly
costs nothing and creates no version churn.

### Backing up project `.env` files

```bash
zab secrets mirror --projects --apply    # secret-shaped names only
zab secrets mirror --projects --all --apply
```

The hub is flat, so it cannot hold two different `SECRET_KEY` values — on a
real workstation 12 names carry different values in different projects, and
collecting them would keep one and lose the rest. `--projects` sidesteps that
by naming each one `zab-<org>-<project>-<key>`.

By default it keeps only names that announce a secret — `KEY`, `TOKEN`,
`SECRET`, `PASSWORD`, `DSN`, `AUTH` and friends — because a port number costs
the same to store as a password. Override the pattern with
`secret_manager.sensitive_name_pattern`, or take everything with `--all`.

The filter reads the name, not the value, so a secret called `ARCHIVE_PATH`
escapes it. What it skips is therefore counted and listed rather than dropped
in silence: a quiet filter reads as full coverage when it is not.

## What the Security dashboard does

The Security tab lists every tracked variable and lets you mirror one. The
action creates the secret if it is missing and reports what happened. It does
not modify any `.env`, and values are never returned by the API, never logged,
and never written to a response.

## Shapes that do not belong in a `.env`

Secret Manager will happily hold a service-account JSON or an OAuth token
document. Those are files, consumed as files — a 2 KB JSON blob on a single
`.env` line is fragile and usually breaks the consumer that expected a path.
`restore` will fetch whatever the provider returns, so point it at scalar
secrets and keep document-shaped ones out of the tracked catalogue.

## Migrating from Dashlane

Earlier versions used Dashlane through `dcli` plus a Playwright writer that
drove Chrome to create missing secrets. It required a signed-in graphical
session, so it did not work on a headless machine, and its vault sat outside
the rest of the infrastructure.

If a `.env` still holds a `dl://` entry, it is a reference to a vault zab no
longer reads, and the value behind it is not in the hub. Put the real value
back in the file by hand, then `zab secrets collect --apply`.
