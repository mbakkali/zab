# Secrets: Google Secret Manager

Zab tracks a catalogue of environment variables (see `zab/secrets_catalog.py`)
and can move them between three places:

| Where | What lives there |
|---|---|
| project `.env` files | what an application actually reads at startup |
| `~/.config/zab/.env` | the local hub, merged from the above |
| Google Secret Manager | the reference — what survives losing a machine |

## Configure

```yaml
# ~/.config/zab/config.yaml
secret_manager:
  project: my-gcp-project
  prefix: zab-
```

Declare `project` explicitly. Without it, zab falls back to
`gcloud config get-value project`, which is rarely the project that holds your
secrets — and if the Secret Manager API is disabled there, every call fails
with an error about a project you never meant to use.

Authentication is whatever `gcloud` already uses: `gcloud auth login` on a
workstation, or the attached service account on a VM. Zab never handles a
credential file of its own.

## The reference scheme

A synced variable no longer holds its value on disk. It holds a reference:

```dotenv
QONTO_API_KEY=sm://my-gcp-project/zab-qonto-api-key
```

The project part is optional — `sm://zab-qonto-api-key` resolves against the
configured project, which keeps a `.env` portable between environments that
don't point at the same one.

Nothing resolves these references implicitly. An application that receives
`sm://...` as an API key will fail, and that is deliberate: `zab secrets pull`
is the step that turns references back into values, and it has to be asked for.
The Evolution preflight check rejects unresolved references for this reason.

## Commands

```bash
zab secrets status              # where each variable lives, and in what form
zab secrets collect --apply     # project .env files -> ~/.config/zab/.env
zab secrets push --apply        # plaintext -> Secret Manager, leaves sm:// behind
zab secrets pull --to path/.env --apply   # sm:// -> real values, in a target file
```

All four default to a dry run. `push` and `pull` do nothing without `--apply`.

`pull` writes plaintext secrets to disk. That is its purpose — a freshly cloned
repository has no `.env`, and something has to reconstitute it — but it means
the command belongs on a trusted machine only.

## What the Security dashboard shows

The Security tab lists every tracked variable with one of three states:

- **synced** — the value is a `sm://` reference;
- **pending** — a plaintext value sits in a `.env`;
- **missing** — nothing declares it.

Selecting a pending variable creates the secret if needed, then rewrites the
local `.env` in place. Values are never returned by the API, never logged, and
never written back to disk once referenced. The rewrite is atomic: a temporary
file, then a rename, so an interrupted write cannot leave a truncated `.env`.

## Migrating from Dashlane

Earlier versions used Dashlane through `dcli` plus a Playwright writer that
drove Chrome to create missing secrets. It required a signed-in graphical
session, so it did not work on a headless machine, and its vault sat outside
the rest of the infrastructure.

References changed scheme from `dl://` to `sm://`. Existing `dl://` entries are
not migrated automatically — they are plaintext-free but point at a vault zab
no longer reads. To move one over, put the value back in the `.env` by hand and
run `zab secrets push --apply`.
