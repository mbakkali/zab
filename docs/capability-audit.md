# Capability audit — method

How to check, surface by surface, what Zab actually does versus what its
capability manifest claims. Written to be repeatable by an agent with no prior
context, and public-safe: no private paths, no workspace data.

The manifest (`zab capabilities --json`) declares capabilities across five
surfaces — core, CLI, MCP, API, UI. The audit's job is to find where a declared
surface does not answer, answers something else, or answers far too slowly to be
usable.

## 1. Take the manifest as the checklist

```bash
uv run zab capabilities --json   # id, risk, core/cli/mcp/api/ui, status
uv run zab features --json       # coarser catalogue: cli + api per feature
```

Do not audit from memory or from the README. The manifest is the contract; a
mismatch between it and reality is itself a finding.

## 2. Exercise the CLI surface

Run every declared read command, capture exit code, wall time and JSON validity.
Skip anything that mutates external systems.

Rules that keep the result honest:

- A non-zero exit is not automatically a defect: `--json` may simply not exist on
  that command. Distinguish *the command failed* from *the audit invoked it
  wrong*, and record the second as a manifest parity gap rather than a bug.
- Command groups (`zab projects`, `zab mempalace`) need a subcommand. Passing a
  flag to the group is an audit error, not a product error.
- Record durations. A command that works but takes minutes is a finding.

## 3. Exercise the HTTP surface

Enumerate routes from the running server rather than from the source:

```bash
curl -s http://127.0.0.1:<port>/openapi.json
```

Probe every parameterless `GET`. Exclude streaming routes (`*/stream`) — they
never terminate and will look like hangs.

Three traps that produce false findings, all of which have bitten this audit:

- **Truncated reads.** Several payloads are hundreds of kilobytes. Reading a
  fixed prefix yields invalid JSON that looks like a serialization bug. Read the
  whole body.
- **Assumed payload shape.** Envelopes differ (`data` + `pagination` here,
  `items` there, `channels` elsewhere). Guessing the key and finding it absent
  reads as "endpoint returns nothing". Print the top-level keys first.
- **Self-inflicted contention.** Client-side timeouts do not cancel server-side
  work. A parallel sweep leaves heavy requests running and every later
  measurement is inflated. Re-measure anything slow **serially, on an idle
  server**, before calling it a performance defect.

A `422` on a route that requires a query parameter is expected, not a bug.

## 4. Exercise the UI surface

Drive the pages headlessly and screenshot each one; a page that renders but shows
`0`, `unknown` or an empty state everywhere is where the interesting defects
live. Compare each visible counter against the API that should feed it — a card
disagreeing with its own backend is a real defect and easy to miss by eye.

## 5. Exercise the scheduled routines

Recurring jobs fail silently: nothing is watching them.

- List them with their last exit status and last successful run.
- Treat a *stale* last-success date as failure even when the status looks fine.
- Check that each job's working directory and program arguments still exist.
  Relocating the repository is the single most common cause of a routine that
  has been quietly dead for days.
- Run the failing ones by hand: a job that works interactively but fails under
  the scheduler is almost always an environment problem (missing `PATH`, absent
  working directory), not a logic problem.

## 6. Judge data quality, not just liveness

For the domain objects the routines produce and consume, count how often each
field is empty across the whole set. A field empty on *every* record is either
dead weight or an unimplemented step; a status column with a single value across
every record means the lifecycle never advances.

Resist "fixing" data quality that is really configuration coverage. Before
proposing a matcher change, check what the unattributed records actually are —
if they are internal traffic, low attribution is correct behaviour.

## 7. Fix, prove, commit — in that order, one at a time

- Re-measure after each fix and keep the before/after numbers.
- Add a regression test that pins the behaviour, not the implementation.
- Commit each fix on its own, immediately. Other agents may be writing to the
  same worktree; uncommitted work is not safe.
- Record the finding in `AGENT_IMPROVEMENTS.md` with evidence, keeping it free of
  private data.

## 8. Report what was not fixed

Design questions (an unimplemented lifecycle, an empty audit-trail field) and
parity gaps belong in the report as open items, with the trade-off stated. A
rushed change to a contract is worse than a documented gap.
