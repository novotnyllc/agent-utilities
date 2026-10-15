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

# Addresses and offsets.
if grep -nE '\b0x[0-9a-fA-F]{5,}\b' "$spec" >&2; then
  report "hex addresses found (describe behaviour, not locations)"
fi

# Disassembler/decompiler auto-names.
if grep -nE '\b(FUN|LAB|DAT|PTR|sub|loc|off|unk|byte|dword|qword)_[0-9a-fA-F]{4,}\b' "$spec" >&2; then
  report "decompiler symbol names found"
fi

# Code fences in source/assembly languages.
if grep -niE '^```[[:space:]]*(c|cpp|c\+\+|asm|nasm|x86|arm|js|javascript|ts|typescript|cs|csharp|java|kotlin|smali|il|cil|rust|go|swift|objc)[[:space:]]*$' "$spec" >&2; then
  report "code blocks found (SPEC.md describes behaviour; tables and prose only)"
fi

# Unfilled template placeholders that would leave the builder guessing.
if grep -nE '^\| *[0-9]+ *\| *\| *\|' "$spec" >&2; then
  report "empty worked-example rows"
fi

if [ -f "$deny" ]; then
  while IFS= read -r term || [ -n "$term" ]; do
    term="${term%%#*}"
    term="$(printf '%s' "$term" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    [ -z "$term" ] && continue
    if grep -nF -- "$term" "$spec" >&2; then
      report "denylisted term: $term"
    fi
  done < "$deny"
fi

if [ "$problems" -gt 0 ] && [ "${2:-}" != "--force" ]; then
  echo "WALL BLOCKED: $problems problem(s). Fix SPEC.md in Room A and rerun." >&2
  exit 1
fi

cp "$spec" "$root/builder/SPEC.md"
echo "WALL OK: SPEC.md copied to builder/ ($(wc -l < "$spec" | tr -d ' ') lines)"
