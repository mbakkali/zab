#!/usr/bin/env bash
set -u

repo="${ZAB_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
uv_bin="${UV_BIN:-$(command -v uv || true)}"
state_dir="${HOME}/.local/share/zab/conversation-daily-obsidian"
log="${state_dir}/hook.log"
lock="${state_dir}/hook.lock"

if [[ -z "${uv_bin}" ]]; then
  exit 0
fi

mkdir -p "${state_dir}"

(
  if ! mkdir "${lock}" 2>/dev/null; then
    exit 0
  fi
  trap 'rmdir "${lock}" 2>/dev/null || true' EXIT

  cd "${repo}" || exit 0
  "${uv_bin}" run zab conversations obsidian-daily \
    --yesterday \
    --once-per-day \
    --batch-size 10 \
    --limit 200 \
    --json >>"${log}" 2>&1
) >/dev/null 2>&1 &

exit 0
