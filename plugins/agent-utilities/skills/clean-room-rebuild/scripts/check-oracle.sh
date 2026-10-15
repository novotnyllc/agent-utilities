#!/usr/bin/env bash
# Test the oracle: the clean tree must pass, and every planted mutant must fail.
# Mutants are patches in <builder>/oracle/mutants/*.patch (git apply format, paths
# relative to <builder>). Each runs in a throwaway copy, so the real tree is untouched.
set -uo pipefail

if [ $# -lt 2 ]; then
  echo "usage: check-oracle.sh <builder-dir> \"<test command>\" [min-mutants=3]" >&2
  exit 2
fi

builder="$(cd "$1" && pwd)"
test_cmd="$2"
min="${3:-3}"
mutants=("$builder"/oracle/mutants/*.patch)

if [ ! -e "${mutants[0]}" ] || [ "${#mutants[@]}" -lt "$min" ]; then
  echo "ORACLE UNTESTED: need at least $min mutants in oracle/mutants/*.patch (constant, branch, boundary)" >&2
  exit 1
fi

scratch="$(mktemp -d "${TMPDIR:-/tmp}/oracle-check.XXXXXX")"
trap 'rm -rf "$scratch"' EXIT

run_in() { (cd "$1" && bash -c "$test_cmd") >"$2" 2>&1; }

copy_tree() {
  mkdir -p "$1"
  # Copy without .git so the test command can't touch the real repo.
  (cd "$builder" && tar --exclude=./.git -cf - .) | (cd "$1" && tar -xf -)
}

clean="$scratch/clean"
copy_tree "$clean"
if ! run_in "$clean" "$scratch/clean.log"; then
  echo "ORACLE BASELINE FAILED: tests fail on the unmodified tree. Log:" >&2
  tail -40 "$scratch/clean.log" >&2
  exit 1
fi

rejected=0
broken=()
for patch in "${mutants[@]}"; do
  name="$(basename "$patch" .patch)"
  dir="$scratch/$name"
  copy_tree "$dir"
  if ! (cd "$dir" && git apply --whitespace=nowarn "$patch" 2>"$scratch/$name.apply"); then
    echo "MUTANT INVALID: $name does not apply" >&2
    cat "$scratch/$name.apply" >&2
    broken+=("$name(invalid)")
    continue
  fi
  if run_in "$dir" "$scratch/$name.log"; then
    echo "MUTANT SURVIVED: $name passed the tests" >&2
    broken+=("$name")
  else
    echo "mutant rejected: $name"
    rejected=$((rejected + 1))
  fi
done

total="${#mutants[@]}"
if [ "${#broken[@]}" -gt 0 ]; then
  echo "ORACLE BROKEN: $rejected/$total mutants rejected; survived or invalid: ${broken[*]}. Fix the tests before trusting any green run."
  exit 1
fi
echo "ORACLE OK: $rejected/$total mutants rejected"
