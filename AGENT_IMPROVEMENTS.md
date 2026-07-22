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
