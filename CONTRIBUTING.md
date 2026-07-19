# Contributing to zab

Thank you for your interest in contributing to zab.

## Getting started

1. Fork the repository and clone your fork.
2. Install dependencies:

```bash
uv sync
```

3. Copy the example config:

```bash
mkdir -p ~/.config/zab
cp config.example.yaml ~/.config/zab/config.yaml
```

4. Run tests:

```bash
uv run pytest zab/tests -v
./scripts/publish-check.sh
```

## Pull request guidelines

- Keep changes focused and reviewable.
- Add or update tests for behavior changes.
- Do not commit secrets, personal paths, or private infrastructure identifiers.
- Run `./scripts/publish-check.sh` before opening a PR.
- Run `git config core.hooksPath .githooks` once per clone to enable the pre-push privacy guard.
- Update `README.md` when user-facing behavior or installation steps change.

## Code style

- Python: follow existing module patterns in `zab/`.
- TypeScript/React: follow patterns in `zab-ui/`.
- Prefer explicit configuration over hardcoded operator defaults.

## Reporting issues

Use GitHub Issues with:

- steps to reproduce
- expected vs actual behavior
- zab version and Python version

For security issues, see [SECURITY.md](SECURITY.md).
