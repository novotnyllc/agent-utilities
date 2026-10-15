#!/usr/bin/env bash
# Test the oracle: the clean tree must pass, and every planted mutant must fail.
# Mutants are patches in <builder>/oracle/mutants/*.patch (git apply format, paths
# relative to <builder>). A mutant counts only if it modifies existing
# implementation files: no new, deleted or renamed files, and nothing under
# tests/, test/ or oracle/. Each run uses its own throwaway copy, so the real tree
# is untouched. Set ORACLE_TIMEOUT=<seconds> to bound each run (needs timeout or
# gtimeout); a timed-out mutant counts as rejected.
set -uo pipefail

if [ $# -lt 2 ]; then
  echo "usage: check-oracle.sh <builder-dir> \"<test command>\" [min-mutants=3]" >&2
  exit 2
fi

builder="$(cd "$1" && pwd -P)"
test_cmd="$2"
min="${3:-3}"
case "$min" in
  ''|*[!0-9]*) echo "min-mutants must be a whole number (got: $min)" >&2; exit 2 ;;
esac

mutants=("$builder"/oracle/mutants/*.patch)
if [ ! -e "${mutants[0]}" ] || [ "${#mutants[@]}" -lt "$min" ]; then
  echo "ORACLE UNTESTED: need at least $min mutants in oracle/mutants/*.patch (constant, branch, boundary)" >&2
  exit 1
fi

timeout_cmd=""
if [ -n "${ORACLE_TIMEOUT:-}" ]; then
  timeout_cmd="$(command -v timeout || command -v gtimeout || true)"
  [ -n "$timeout_cmd" ] || echo "note: ORACLE_TIMEOUT set but no timeout/gtimeout found; running unbounded" >&2
fi

# Scratch space must not live inside the tree being copied.
tmp_base="$(cd "${TMPDIR:-/tmp}" && pwd -P)"
case "$tmp_base/" in "$builder"/*) tmp_base=/tmp ;; esac
scratch="$(mktemp -d "$tmp_base/oracle-check.XXXXXX")"
trap 'rm -rf "$scratch"' EXIT
# Keep git from finding an enclosing repository when applying patches to the copies.
unset GIT_DIR GIT_WORK_TREE
export GIT_CEILING_DIRECTORIES="$scratch"

# Returns the test command's status; 124 means it timed out.
run_in() {
  if [ -n "$timeout_cmd" ]; then
    (cd "$1" && "$timeout_cmd" "$ORACLE_TIMEOUT" bash -c "$test_cmd") >"$2" 2>&1
  else
    (cd "$1" && bash -c "$test_cmd") >"$2" 2>&1
  fi
}

copy_tree() {
  mkdir -p "$1"
  # Copy without .git so the test command can't touch the real repo.
  (cd "$builder" && tar --exclude=./.git -cf - .) | (cd "$1" && tar -xf -)
}

# Prints a reason and fails if the patch is not a behaviour mutant of existing code.
check_mutant_shape() {
  local dir="$1" patch="$2" summary numstat path
  summary="$(cd "$dir" && git apply --summary "$patch" 2>&1)" || { echo "does not parse: $summary"; return 1; }
  if printf '%s\n' "$summary" | grep -qE '^ (create|delete|rename|copy|mode change) '; then
    echo "creates, deletes, renames or re-modes files; mutate existing code instead"
    return 1
  fi
  numstat="$(cd "$dir" && git apply --numstat "$patch" 2>&1)" || { echo "does not parse: $numstat"; return 1; }
  [ -n "$numstat" ] || { echo "changes nothing"; return 1; }
  while IFS="$(printf '\t')" read -r _ _ path; do
    case "/$path" in
      */tests/*|*/test/*|/oracle/*)
        echo "touches $path; mutants must change implementation, not tests or oracle files"
        return 1 ;;
    esac
  done <<EOF
$numstat
EOF
}

clean="$scratch/baseline"
copy_tree "$clean"
run_in "$clean" "$scratch/baseline.log"
status=$?
if [ "$status" -ne 0 ]; then
  [ "$status" -eq 124 ] && [ -n "$timeout_cmd" ] && echo "(baseline timed out after ${ORACLE_TIMEOUT}s)" >&2
  echo "ORACLE BASELINE FAILED: tests fail on the unmodified tree. Log:" >&2
  tail -40 "$scratch/baseline.log" >&2
  exit 1
fi

rejected=0
broken=()
n=0
for patch in "${mutants[@]}"; do
  n=$((n + 1))
  name="$(basename "$patch" .patch)"
  dir="$scratch/mutant-$n"
  copy_tree "$dir"
  if ! reason="$(check_mutant_shape "$dir" "$patch")"; then
    echo "MUTANT INVALID: $name $reason" >&2
    broken+=("$name(invalid)")
    continue
  fi
  if ! (cd "$dir" && git apply --whitespace=nowarn "$patch" 2>"$scratch/mutant-$n.apply"); then
    echo "MUTANT INVALID: $name does not apply" >&2
    cat "$scratch/mutant-$n.apply" >&2
    broken+=("$name(invalid)")
    continue
  fi
  run_in "$dir" "$scratch/mutant-$n.log"
  status=$?
  if [ "$status" -eq 0 ]; then
    echo "MUTANT SURVIVED: $name passed the tests" >&2
    broken+=("$name")
  elif [ "$status" -eq 124 ] && [ -n "$timeout_cmd" ]; then
    echo "mutant rejected: $name (timeout)"
    rejected=$((rejected + 1))
  else
    echo "mutant rejected: $name"
    rejected=$((rejected + 1))
  fi
done

total="${#mutants[@]}"
if [ "${#broken[@]}" -gt 0 ]; then
  echo "ORACLE BROKEN: $rejected/$total mutants rejected; survived or invalid: ${broken[*]}. Fix the tests (or the mutants) before trusting any green run."
  exit 1
fi
echo "ORACLE OK: $rejected/$total mutants rejected"
