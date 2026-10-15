#!/usr/bin/env bash
# Test the oracle: the clean tree must pass, and every planted mutant must fail.
#
# Mutants are patches in <builder>/oracle/mutants/*.patch (git apply format, paths
# relative to <builder>). A mutant counts only if it modifies existing files under
# the implementation directory (ORACLE_IMPL_DIR, default src) that are not test
# files: no new, deleted or renamed files. Each run uses its own throwaway copy
# (symlinks followed), so the real tree is untouched.
#
# Optional environment:
#   ORACLE_IMPL_DIR=<dir>   implementation directory mutants must stay in (default src)
#   ORACLE_BUILD="<cmd>"    build/compile/parse check; a mutant that fails it is
#                           invalid, because a broken build proves nothing about the tests
#   ORACLE_TIMEOUT=<secs>   bound each run (needs timeout or gtimeout); a timed-out
#                           mutant counts as rejected
set -uo pipefail

if [ $# -lt 2 ]; then
  echo "usage: check-oracle.sh <builder-dir> \"<test command>\" [min-mutants=3]" >&2
  exit 2
fi

builder="$(cd "$1" && pwd -P)" || exit 2
test_cmd="$2"
min="${3:-3}"
case "$min" in
  ''|*[!0-9]*) echo "min-mutants must be a whole number (got: $min)" >&2; exit 2 ;;
esac
impl_dir="${ORACLE_IMPL_DIR-src}"
impl_dir="${impl_dir%/}"
build_cmd="${ORACLE_BUILD:-}"

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
tmp_base="$(cd "${TMPDIR:-/tmp}" 2>/dev/null && pwd -P)" || tmp_base=/tmp
case "$tmp_base/" in "$builder"/*) tmp_base=/tmp ;; esac
scratch="$(mktemp -d "$tmp_base/oracle-check.XXXXXX")" && [ -n "$scratch" ] || {
  echo "cannot create a scratch directory under $tmp_base" >&2
  exit 1
}
trap 'rm -rf "$scratch"' EXIT
# Keep git from finding an enclosing repository when reading or applying patches.
unset GIT_DIR GIT_WORK_TREE
export GIT_CEILING_DIRECTORIES="$scratch"

# Runs a command in a directory, logging output; returns its status (124 = timed out).
run_in() {
  if [ -n "$timeout_cmd" ]; then
    (cd "$1" && "$timeout_cmd" "$ORACLE_TIMEOUT" bash -c "$2") >"$3" 2>&1
  else
    (cd "$1" && bash -c "$2") >"$3" 2>&1
  fi
}

copy_tree() {
  mkdir -p "$1"
  # Skip .git so tests can't touch the real repo; follow symlinks so writes stay in the copy.
  (cd "$builder" && tar -h --exclude=./.git -cf - .) | (cd "$1" && tar -xf -)
}

# Prints a reason and fails unless the patch only modifies implementation files.
check_mutant_shape() {
  local patch="$1" summary path count=0
  summary="$(cd "$scratch" && git apply --summary "$patch" 2>&1)" || { echo "does not parse: $summary"; return 1; }
  if printf '%s\n' "$summary" | grep -qE '^ (create|delete|rename|copy|mode change) '; then
    echo "creates, deletes, renames or re-modes files; mutate existing code instead"
    return 1
  fi
  # NUL-separated records keep unusual file names unquoted: "added<TAB>deleted<TAB>path".
  while IFS= read -r -d '' rec; do
    path="${rec#*	}"; path="${path#*	}"
    count=$((count + 1))
    if [ -n "$impl_dir" ]; then
      case "$path" in
        "$impl_dir"/*) ;;
        *) echo "touches $path; mutants must stay under $impl_dir/ (set ORACLE_IMPL_DIR)"; return 1 ;;
      esac
    fi
    case "/$path" in
      */tests/*|*/test/*|*/__tests__/*|*/spec/*|/oracle/*|*_test.*|*.test.*|*.spec.*|*/test_*|*_spec.*)
        echo "touches $path; mutants must change implementation, not tests or oracle files"
        return 1 ;;
    esac
  done < <(cd "$scratch" && git apply --numstat -z "$patch" 2>/dev/null)
  [ "$count" -gt 0 ] || { echo "changes nothing"; return 1; }
}

baseline="$scratch/baseline"
copy_tree "$baseline"
if [ -n "$build_cmd" ] && ! run_in "$baseline" "$build_cmd" "$scratch/baseline-build.log"; then
  echo "ORACLE BASELINE FAILED: ORACLE_BUILD fails on the unmodified tree. Log:" >&2
  tail -40 "$scratch/baseline-build.log" >&2
  exit 1
fi
run_in "$baseline" "$test_cmd" "$scratch/baseline.log"
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
  if ! reason="$(check_mutant_shape "$patch")"; then
    echo "MUTANT INVALID: $name $reason" >&2
    broken+=("$name(invalid)")
    continue
  fi
  dir="$scratch/mutant-$n"
  copy_tree "$dir"
  if ! (cd "$dir" && git apply --whitespace=nowarn "$patch" 2>"$scratch/mutant-$n.apply"); then
    echo "MUTANT INVALID: $name does not apply" >&2
    cat "$scratch/mutant-$n.apply" >&2
    broken+=("$name(invalid)")
    continue
  fi
  if [ -n "$build_cmd" ] && ! run_in "$dir" "$build_cmd" "$scratch/mutant-$n-build.log"; then
    echo "MUTANT INVALID: $name does not build (ORACLE_BUILD failed); plant a behaviour change that still runs" >&2
    broken+=("$name(invalid)")
    continue
  fi
  run_in "$dir" "$test_cmd" "$scratch/mutant-$n.log"
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
[ -n "$build_cmd" ] || echo "note: no ORACLE_BUILD set, so a mutant that merely fails to build would also count as rejected" >&2
echo "ORACLE OK: $rejected/$total mutants rejected"
