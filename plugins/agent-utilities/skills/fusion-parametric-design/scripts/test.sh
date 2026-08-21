#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$root/src${PYTHONPATH:+:$PYTHONPATH}"

cd "$root"
python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests

# The plugin's Claude-side hooks ship beside the skill; their tests run here
# because this is the repo's gate. Skipped when node is absent (the hooks
# themselves are Claude-only conveniences; doctrine is the authority).
hooks_dir="$root/../../hooks"
if command -v node >/dev/null 2>&1 && [ -d "$hooks_dir" ]; then
  node --test "$hooks_dir"/*.test.mjs
fi
