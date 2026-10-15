#!/usr/bin/env bash
# Lint reader/SPEC.md for things that must not cross the wall, then copy it to builder/.
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: cross-wall.sh <root-dir> [--force]" >&2
  exit 2
fi

root="$(cd "$1" && pwd)"
spec="$root/reader/SPEC.md"
deny="$root/wall/denylist.txt"
[ -f "$spec" ] || { echo "missing $spec" >&2; exit 1; }

problems=0
report() { echo "WALL: $1" >&2; problems=$((problems + 1)); }

# This lint catches common leaks; it is not exhaustive. Reading the spec is the real check.
B='(^|[^[:alnum:]])'

# Addresses and offsets.
if grep -nE "${B}0x[0-9a-fA-F]{5,}" "$spec" >&2; then
  report "hex addresses found (describe behaviour, not locations)"
fi

# Disassembler/decompiler auto-names, variables, mangled symbols, ObjC selectors.
if grep -nE "${B}(thunk_|j_)?_*(FUN|LAB|DAT|PTR|sub|loc|off|unk|byte|dword|qword)_[0-9a-fA-F]{4,}|${B}nullsub_[0-9]+" "$spec" >&2; then
  report "decompiler symbol names found"
fi
if grep -nE "${B}(param_[0-9]+|local_[0-9a-fA-F]+|[a-z]{1,2}Var[0-9]+)([^[:alnum:]_]|\$)" "$spec" >&2; then
  report "decompiler variable names found"
fi
if grep -nE '__Z[A-Za-z0-9_]{3,}|\$s[0-9]+[A-Za-z]|[-+]\[[A-Za-z_][A-Za-z0-9_]* [A-Za-z_:]+\]' "$spec" >&2; then
  report "mangled symbols or Objective-C selectors found"
fi

# Code blocks of any kind: SPEC.md is tables and prose only.
if grep -nE '^[[:space:]]*(```|~~~)|<pre|<code' "$spec" >&2; then
  report "code blocks found (SPEC.md describes behaviour; tables and prose only)"
fi
if grep -nE '^(    |	)[[:space:]]*[^|[:space:]-].*[;{}][[:space:]]*$' "$spec" >&2; then
  report "indented code found"
fi

# Unfilled template placeholders that would leave the builder guessing.
if grep -nE '^\| *[0-9]+ *\| *\| *\|' "$spec" >&2; then
  report "empty worked-example rows"
fi

terms=0
if [ -f "$deny" ]; then
  while IFS= read -r term || [ -n "$term" ]; do
    term="$(printf '%s' "$term" | tr -d '\r' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    case "$term" in ''|'#'*) continue ;; esac
    terms=$((terms + 1))
    if grep -niF -- "$term" "$spec" >&2; then
      report "denylisted term: $term"
    fi
  done < "$deny"
fi
[ "$terms" -gt 0 ] || echo "note: wall/denylist.txt has no terms; add the original's names as you find them" >&2

if [ "$problems" -gt 0 ] && [ "${2:-}" != "--force" ]; then
  echo "WALL BLOCKED: $problems problem(s). Fix SPEC.md in Room A and rerun." >&2
  exit 1
fi

cp "$spec" "$root/builder/SPEC.md"
lines="$(wc -l < "$spec" | tr -d ' ')"
if [ "$problems" -gt 0 ]; then
  echo "WALL FORCED: $problems problem(s) overridden; SPEC.md copied to builder/ ($lines lines)"
else
  echo "WALL OK: SPEC.md copied to builder/ ($lines lines, $terms denylist terms checked)"
fi
