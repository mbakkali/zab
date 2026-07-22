# Dashlane Secret Writer

Zab can create missing Dashlane Secrets through a local Playwright writer:

```bash
scripts/dashlane-secret-writer.mjs
```

The writer reads one JSON payload from stdin and never accepts the secret value
through argv:

```json
{
  "name": "QONTO_SECRET_KEY",
  "title": "Z_QONTO_SECRET_KEY",
  "value": "...",
  "note": "optional"
}
```

It returns redacted metadata only:

```json
{"ok":true,"title":"Z_QONTO_SECRET_KEY","reference":"dl://Z_QONTO_SECRET_KEY","web_url":"https://app.dashlane.com/#/credentials"}
```

## Default local mode

When Node and `zab-ui/node_modules/playwright` exist, Zab auto-detects this
writer and reports Dashlane `write_supported=true`.

On macOS, when the regular Google Chrome application is already running, the
writer uses AppleScript mode by default so it can target the existing signed-in
Chrome session. Otherwise it launches headed Google Chrome with a persistent Zab
profile:

```bash
~/.local/share/zab/dashlane-writer-profile
```

On the first run, sign in to Dashlane in that Chrome window. The session is then
reused by later syncs.

## AppleScript mode

AppleScript mode opens or reuses Dashlane at:

```bash
https://app.dashlane.com/#/credentials
```

Force it with:

```bash
export DASHLANE_WRITER_MODE=applescript
```

Chrome must allow JavaScript from Apple Events:

```text
Chrome > View > Developer > Allow JavaScript from Apple Events
```

Probe the current Chrome session without sending a secret:

```bash
node scripts/dashlane-secret-writer.mjs --probe-applescript
```

If Chrome still reports the setting as disabled after enabling it, restart
Chrome once and rerun the probe.

## Dedicated Chrome session

Recent Chrome builds refuse DevTools remote debugging on the default Chrome
profile. Zab therefore uses a dedicated Chrome profile for the writer:

```bash
~/.local/share/zab/dashlane-writer-profile
```

Launch it with:

```bash
open -na "Google Chrome" --args \
  --user-data-dir="$HOME/.local/share/zab/dashlane-writer-profile" \
  --remote-debugging-port=9222 \
  "https://app.dashlane.com/#/credentials"
```

Sign in to Dashlane once in that window; the writer profile then preserves the
session for later syncs.

If you intentionally run another non-default Chrome profile with a CDP port, the
writer can attach to it. If `http://127.0.0.1:9222` is open, the writer attaches
automatically.

Explicit forms are also supported:

```bash
export DASHLANE_WRITER_ATTACH_CHROME=1
export DASHLANE_WRITER_CDP_URL="http://127.0.0.1:9222"
```

Then start/restart the Zab dashboard from the same shell so the environment is
visible to the API process.

## Override the writer

To force a custom writer:

```bash
export ZAB_DASHLANE_SECRET_CREATE_COMMAND="/absolute/path/to/writer"
```

The command must read the JSON payload from stdin and create one Dashlane Secret.
Do not pass secret values through command-line arguments.

## Smoke test

This dry-run verifies the contract without opening Dashlane and without printing
the secret value:

```bash
printf '%s' '{"name":"QONTO_SECRET_KEY","title":"Z_QONTO_SECRET_KEY","value":"secret"}' \
  | node scripts/dashlane-secret-writer.mjs --dry-run
```
