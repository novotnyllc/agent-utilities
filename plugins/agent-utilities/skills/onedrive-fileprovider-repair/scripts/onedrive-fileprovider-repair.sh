#!/bin/sh
# Diagnose File Provider churn and run FPCK only after an explicit confirmation.

set -u

mode=diagnose
confirm_repair=0
restart_after_repair=0
diagnostic_file=''
fpck_report=''
fpck_log=''
fpck_domain_unresolved=0

usage() {
  cat <<'EOF'
Usage: onedrive-fileprovider-repair.sh [--diagnose] [--repair --confirm-repair [--restart-after-repair]]

  --diagnose               Read-only process and File Provider evidence (default).
  --repair                 Run FPCK after the read-only checks pass.
  --confirm-repair         Required with --repair.
  --restart-after-repair   Restart OneDrive and fileproviderd after this FPCK run.
EOF
}

fail() {
  printf '%s\n' "$*" >&2
  exit 2
}

cleanup() {
  for temporary_file in "${diagnostic_file:-}" "${fpck_report:-}" "${fpck_log:-}"; do
    [ -z "$temporary_file" ] || rm -f "$temporary_file"
  done
}

trap cleanup EXIT HUP INT TERM

new_temp() {
  mktemp -t onedrive-fileprovider
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

validate_target() {
  documents_dir="$HOME/Documents"
  codex_dir="$documents_dir/Codex"

  [ -d "$documents_dir" ] || fail "Documents is not a directory."
  [ -d "$codex_dir" ] || fail "Documents/Codex is not a directory."
  [ ! -L "$codex_dir" ] || fail "Documents/Codex must remain a real directory, not a symlink."

  physical_documents=$(CDPATH= cd "$documents_dir" && pwd -P) || fail "Could not resolve the physical Documents path."
  physical_codex="$physical_documents/Codex"
  [ -d "$physical_codex" ] || fail "The physical Documents/Codex directory is unavailable."

  printf '%s\n' 'TARGET=physical Documents/Codex directory resolved'
}

process_snapshot() {
  process_lines=$(LC_ALL=C ps -A -o %cpu= -o %mem= -o comm= 2>/dev/null | awk -v threshold=20 '
    function track(name, cpu, mem) {
      cpu = $1 + 0
      mem = $2 + 0
      if (!(name in seen) || cpu > max_cpu[name]) {
        seen[name] = 1
        max_cpu[name] = cpu
        max_mem[name] = mem
      }
    }
    function emit(name, state) {
      if (name in seen) {
        state = max_cpu[name] >= threshold ? "high" : "not-high"
        printf "PROCESS=%s cpu=%.1f%% mem=%.1f%% evidence=%s\n", name, max_cpu[name], max_mem[name], state
      }
    }
    /fileproviderd/ { track("fileproviderd"); next }
    /suggestd/ { track("suggestd"); next }
    /OneDrive/ { track("OneDrive") }
    END {
      emit("fileproviderd")
      emit("suggestd")
      emit("OneDrive")
    }
  ')

  if [ -n "$process_lines" ]; then
    printf '%s\n' "$process_lines"
  else
    printf '%s\n' 'PROCESS_EVIDENCE=none'
  fi
}

evaluate_target() {
  diagnostic_file=$(new_temp) || fail "Could not create a temporary diagnostic file."

  if fileproviderctl evaluate "$physical_codex" >"$diagnostic_file" 2>&1; then
    printf '%s\n' 'EVALUATE=ok'
    awk -F '[:=]' '
      $1 ~ /^[[:space:]]*(isFolder|isSyncPaused|isUploading|isDownloading|isUploaded|isExcludedFromSync)[[:space:]]*$/ {
        key = $1
        value = $2
        gsub(/[[:space:]]/, "", key)
        gsub(/[[:space:]]/, "", value)
        if (value ~ /^(0|1|true|false)$/) {
          printf "EVALUATE_%s=%s\n", key, value
        }
      }
    ' "$diagnostic_file"
    if grep -Eqi 'uploadingError|downloadError' "$diagnostic_file"; then
      printf '%s\n' 'EVALUATE_PROVIDER_ERROR=present'
    fi
    return 0
  fi

  printf '%s\n' 'EVALUATE=failed'
  if grep -Fq 'No providerDomainID' "$diagnostic_file"; then
    printf '%s\n' 'EVALUATE_DOMAIN=unresolved'
  fi
  return 1
}

run_diagnosis() {
  require_command fileproviderctl
  validate_target
  process_snapshot
  evaluate_target
}

print_fpck_summary() {
  summary=$(for report_file in "$fpck_report" "$fpck_log"; do
    [ -f "$report_file" ] || continue
    awk -F ': *' '
      /^(status|numberOfFilesChecked|numberOfBrokenFilesInFSAndFSSnapshotCheck|numberOfBrokenFilesInFSSnapshotAndFPSnapshotCheck|numberOfBrokenFilesInReconciliationTableCheck|numberOfReconciliationTableEntries|pendingSetSize|superPendingSetSize|totalFixedFSSnapshotDiffs|totalFixedDiskBrokenInvariants):/ {
        value = $2
        gsub(/[[:space:]]/, "", value)
        if (value ~ /^[0-9]+$/) {
          printf "FPCK_%s=%s\n", $1, value
        }
      }
    ' "$report_file"
  done | sort -u)

  if [ -n "$summary" ]; then
    printf '%s\n' "$summary"
  else
    printf '%s\n' 'FPCK_SUMMARY=unavailable'
  fi

  if grep -Fq 'No providerDomainID' "$fpck_report" "$fpck_log"; then
    fpck_domain_unresolved=1
    printf '%s\n' 'FPCK_DOMAIN=unresolved'
  fi
}

restart_after_fpck() {
  printf '%s\n' 'RESTART=bounded OneDrive and fileproviderd only; Codex untouched'
  killall 'OneDrive File Provider' >/dev/null 2>&1 || :
  killall OneDrive >/dev/null 2>&1 || :
  killall fileproviderd >/dev/null 2>&1 || :
  attempts=0
  while pgrep -x OneDrive >/dev/null 2>&1 && [ "$attempts" -lt 30 ]; do
    sleep 1
    attempts=$((attempts + 1))
  done
  if pgrep -x OneDrive >/dev/null 2>&1; then
    printf '%s\n' 'RESTART_ONEDRIVE=shutdown-timeout; relaunch-not-attempted'
    return 1
  fi
  open -g -j -a OneDrive >/dev/null 2>&1 || printf '%s\n' 'RESTART_ONEDRIVE=relaunch-failed'
  sleep 2
  process_snapshot
}

run_repair() {
  restart_exit=0
  fpck_report=$(new_temp) || fail "Could not create a temporary FPCK report."
  fpck_log=$(new_temp) || fail "Could not create a temporary FPCK log."

  if fileproviderctl repair -a "$physical_documents" -P -d -v -o "$fpck_report" >"$fpck_log" 2>&1; then
    fpck_exit=0
  else
    fpck_exit=$?
  fi

  printf 'FPCK_EXIT=%s\n' "$fpck_exit"
  print_fpck_summary

  if [ "$fpck_exit" -ne 0 ]; then
    printf '%s\n' 'FPCK_RESULT=partial-or-failure'
    if [ "$fpck_domain_unresolved" -eq 1 ]; then
      printf '%s\n' 'RESTART=not-run; provider domain remains unresolved'
    fi
  else
    printf '%s\n' 'FPCK_RESULT=success'
  fi

  if [ "$restart_after_repair" -eq 1 ] && [ "$fpck_domain_unresolved" -eq 0 ]; then
    restart_after_fpck || restart_exit=$?
  elif [ "$restart_after_repair" -eq 0 ]; then
    printf '%s\n' 'RESTART=not-run; explicit --restart-after-repair is required'
  fi

  if [ "$fpck_exit" -eq 0 ] && [ "$restart_exit" -ne 0 ]; then
    return "$restart_exit"
  fi
  return "$fpck_exit"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --diagnose) mode=diagnose ;;
    --repair) mode=repair ;;
    --confirm-repair) confirm_repair=1 ;;
    --restart-after-repair) restart_after_repair=1 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; fail "Unknown option: $1" ;;
  esac
  shift
done

[ "$(uname)" = Darwin ] || fail 'This helper runs only on macOS.'
[ "$restart_after_repair" -eq 0 ] || [ "$mode" = repair ] || fail '--restart-after-repair requires --repair.'

if ! run_diagnosis; then
  exit 1
fi

if [ "$mode" = repair ]; then
  [ "$confirm_repair" -eq 1 ] || fail 'Repair requires explicit --confirm-repair.'
  run_repair
fi
