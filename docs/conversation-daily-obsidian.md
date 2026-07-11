# Daily conversation digest to Obsidian

Zab can build a local daily digest from agent conversations and write it to
Obsidian. The routine is designed for a local daily workflow:

- read yesterday's local conversations from Cursor, Claude Code, Codex, Hermes,
  Gemini CLI and Kimi when available;
- infer the Zab project and canonical organization for each conversation;
- keep unmatched conversations under `hors-org` or with no project when no
  project can be inferred;
- write one detailed Obsidian note for the day;
- insert one short todo line under the matching day in `todos/Daily.md`;
- run in batches of 10 and record conversation ids for traceability;
- avoid API calls, `zab conversations sync`, and Postgres mutations.

## Main command

```bash
uv run zab conversations obsidian-daily \
  --yesterday \
  --once-per-day \
  --batch-size 10 \
  --limit 200 \
  --json
```

Useful variants:

```bash
# Preview without writing to Obsidian.
uv run zab conversations obsidian-daily --date 2026-06-24 --dry-run --json

# Force-refresh a specific day. This rewrites the detail note and replaces the
# marked block in the daily note without duplicating it.
uv run zab conversations obsidian-daily --date 2026-06-24 --json

# Confirm the daily guard is active.
uv run zab conversations obsidian-daily --date 2026-06-24 --once-per-day --json
```

## Output locations

The Obsidian vault comes from `obsidian.vault_path` in
`~/.config/zab/config.yaml`.

Default paths inside the vault:

- daily page: `todos/Daily.md`
- detail notes: `todos/Agent conversations/YYYY-MM-DD - conversations agents.md`

The daily page block is wrapped with markers:

```markdown
<!-- zab-conversation-digest:YYYY-MM-DD:start -->
- [ ] Digest agents YYYY-MM-DD : [[todos/Agent conversations/YYYY-MM-DD - conversations agents|conversations agents YYYY-MM-DD]] - ...
<!-- zab-conversation-digest:YYYY-MM-DD:end -->
```

Those markers make the write idempotent. Re-running for the same date replaces
the block instead of appending a duplicate.

## Startup hook

Codex can run the routine through a local `UserPromptSubmit` hook:

```json
{
  "type": "command",
  "command": "\"/absolute/path/to/zab/scripts/zab-codex-daily-digest-hook.sh\""
}
```

The script:

- starts in the background so the prompt is not blocked;
- uses a lock directory under `~/.local/share/zab/conversation-daily-obsidian`;
- calls `zab conversations obsidian-daily --yesterday --once-per-day`;
- writes logs to `~/.local/share/zab/conversation-daily-obsidian/hook.log`.

## Codex automation fallback

The Codex automation `digest-conversations-zab` also runs daily at 08:30 local
time. It calls the same `--once-per-day` command, so it acts as a fallback if
Codex was not opened earlier. If the hook already ran, the automation returns
`status: skipped`.

## Project and org attribution

Attribution uses Zab project discovery from `projects_roots`.

Rules:

- project matches can come from transcript path, working directory, content, or
  explicit project names;
- organization names are canonicalized with `organizations` from Zab config;
- unknown organizations become `hors-org`;
- conversations with no project evidence keep `project: null`.

## Test checklist

```bash
uv run pytest zab/tests/test_conversation_digest.py zab/tests/test_conversation_obsidian_daily.py -q
uv run zab conversations obsidian-daily --date 2026-06-24 --dry-run --json
uv run zab conversations obsidian-daily --date 2026-06-24 --once-per-day --json
bash -n scripts/zab-codex-daily-digest-hook.sh
python -m json.tool ~/.codex/hooks.json >/dev/null
```

For a live hook smoke test:

```bash
scripts/zab-codex-daily-digest-hook.sh
tail -n 80 ~/.local/share/zab/conversation-daily-obsidian/hook.log
```

## Rollback

To disable the startup routine, remove the
`scripts/zab-codex-daily-digest-hook.sh` command from
`~/.codex/hooks.json`.

To rerun a day after fixing attribution or formatting, delete the marker:

```bash
rm ~/.local/share/zab/conversation-daily-obsidian/YYYY-MM-DD.json
uv run zab conversations obsidian-daily --date YYYY-MM-DD --once-per-day --json
```
