# Agent Improvements

This file is a public-safe roadmap of frictions observed by agents while using Zab.
Do not add user data, private workspace data, secrets, raw logs, or customer context.

## 2026-07-23 - Repair moved editable CLI install

- Trigger: debug
- Context: a local checkout was moved, while the global `zab` command still used an editable install pointing at the previous checkout path.
- Observation: `zab` failed with `ModuleNotFoundError: No module named 'zab'`; `uv run zab ...` still worked from the repository because the package was on the current working directory.
- Improvement: refresh the global CLI with `uv tool install --reinstall --editable . --python "$(command -v python3.11)"`, document the reinstall command, and make `scripts/install-zab-shell.sh` smoke-test an existing `zab` binary before trusting it.
- Evidence: `zab --help`, `zab workpacket rule --json`, and `zab doctor` pass from a directory outside the checkout after reinstall; `uv run pytest zab/tests -q` passes; `npm run build` passes in `zab-ui`.
- Status: verified
- Fix commit: this commit

## 2026-07-23 - Reuse dashboard UI conventions

- Trigger: mention
- Context: an agent used the public dashboard code as a visual and structural reference for another local operational interface.
- Observation: the compact sidebar, Geist typography, Tailwind v4 tokens, shadcn primitives and dense table patterns were straightforward to identify and reuse without copying domain data.
- Improvement: keep the UI stack and reusable primitives explicit in `zab-ui/package.json` and `src/components/ui/`; no product change was required during this interaction.
- Evidence: read-only inspection of the UI package, navigation and primitive components; the consuming interface passed its independent TypeScript build and responsive browser checks.
- Status: verified
