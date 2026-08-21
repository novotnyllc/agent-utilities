#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$root/src${PYTHONPATH:+:$PYTHONPATH}"

cd "$root"
if [ $# -eq 0 ]; then
  python3 -m unittest discover -s tests -v
  python3 -m compileall -q src tests

  # The plugin's hooks ship beside the skill and load in both harnesses; their
  # tests run here because this is the repo's gate. Skipped when node is absent
  # (the hooks are mechanical nudges; doctrine is the authority).
  hooks_dir="$root/../../hooks"
  if command -v node >/dev/null 2>&1 && [ -d "$hooks_dir" ]; then
    node --test "$hooks_dir"/*.test.mjs
  fi
else
  areas=()
  for arg in "$@"; do
    areas+=("$(printf '%s' "$arg" | tr '-' '_')")
  done
  for area in "${areas[@]}"; do
    if ! compgen -G "tests/test_${area}*.py" >/dev/null; then
      echo "error: no test module matches area '$area' (looked for tests/test_${area}*.py)" >&2
      exit 1
    fi
  done
  for area in "${areas[@]}"; do
    python3 -m unittest discover -s tests -p "test_${area}*.py" -v
  done
fi
