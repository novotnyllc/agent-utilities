#!/bin/sh
# fleet-chezmoi backup: preserve what an apply will change, on the target.
#
#   backup.sh SET-ID EXPECTED-STATUS-DIGEST [ABSOLUTE-TARGET...]
#
# With targets, status and diff are scoped to them (`chezmoi status -- ...`),
# the same bytes a targeted Roundhouse plan seals.
# Refuses unless `chezmoi status` still hashes to the sealed digest, then writes
# the rendered diff and an archive of every existing pending path into a
# private directory under the target's state root. Only the directory path and
# digests are printed: the backup can hold secrets and never leaves the host.
set -u

case ${1:-} in set-[0-9a-f]*) set_id=$1 ;; *) printf 'backup: invalid set ID\n' >&2; exit 64 ;; esac
case ${2:-} in ''|*[!0-9a-f]*) printf 'backup: invalid status digest\n' >&2; exit 64 ;; *) expected=$2 ;; esac
shift 2
for target in "$@"; do
  case $target in
    /*) ;;
    *) printf 'backup: targets must be absolute\n' >&2; exit 64 ;;
  esac
  case $target in */../*|*/..|*/./*) printf 'backup: unsafe target\n' >&2; exit 64 ;; esac
done
[ "$#" -eq 0 ] || set -- -- "$@"

sha_file() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d ' ' -f 1
  else shasum -a 256 "$1" | cut -d ' ' -f 1
  fi
}

fail() {
  jq -cn --arg error "$1" '{schema:"fleet-chezmoi.backup",version:1,ok:false,error:$error}'
  exit 0
}

status=$(mktemp "${TMPDIR:-/tmp}/fleet-chezmoi-status.XXXXXX") || fail "cannot create a temporary file"
trap 'rm -f "$status"' EXIT HUP INT TERM
chezmoi status "$@" >"$status" 2>/dev/null </dev/null || fail "chezmoi status failed"
[ "$(sha_file "$status")" = "$expected" ] ||
  fail "live state changed since the plan was sealed; nothing was applied"

state_root=${XDG_STATE_HOME:-$HOME/.local/state}/fleet-chezmoi/backups
{ mkdir -p "$state_root" && chmod 700 "$state_root" "${state_root%/backups}"; } || fail "cannot create backup root"
dir=$(mktemp -d "$state_root/$set_id.XXXXXX") || fail "cannot create backup directory"
mv "$status" "$dir/status" || fail "cannot record status"

dest=$(chezmoi dump-config --format json 2>/dev/null </dev/null | jq -r '.destDir // .destdir // empty')
[ -n "$dest" ] || dest=$HOME

chezmoi --no-pager diff "$@" >"$dir/diff.patch" 2>/dev/null </dev/null || fail "chezmoi diff failed"

: >"$dir/paths"
cut -c 4- "$dir/status" | while IFS= read -r rel; do
  [ -n "$rel" ] || continue
  # "./" keeps a name that starts with "-" from being read as a tar option.
  if [ -e "$dest/$rel" ] || [ -L "$dest/$rel" ]; then printf './%s\n' "$rel" >>"$dir/paths"; fi
done
entries=$(awk 'NF {n++} END {print n+0}' "$dir/paths")
if [ "$entries" -gt 0 ]; then
  # --no-recursion: a directory entry is pending for its mode, not its content.
  (cd "$dest" && tar -cf "$dir/files.tar" --no-recursion -T "$dir/paths") ||
    fail "archiving pending paths failed"
else
  tar -cf "$dir/files.tar" -T /dev/null
fi
chmod 600 "$dir"/* || fail "cannot restrict backup permissions"

jq -cn --arg dir "$dir" --arg dest "$dest" --arg diff "$(sha_file "$dir/diff.patch")" \
  --arg archive "$(sha_file "$dir/files.tar")" --argjson entries "$entries" \
  '{schema:"fleet-chezmoi.backup",version:1,ok:true,backup_dir:$dir,dest:$dest,
    diff_sha256:$diff,archive_sha256:$archive,archived_entries:$entries,
    restore:"cd DEST && tar -xpf BACKUP_DIR/files.tar"}'
