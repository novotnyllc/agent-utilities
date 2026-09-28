#!/bin/sh
# fleet-chezmoi evidence: the per-target evidence table for conflicting paths.
#
#   evidence.sh RELATIVE-TARGET...
#
# For each destination-relative target: its status code, mapped source file,
# whether that file is a template or modify_ script, rendered and live digests
# (plus canonical-JSON digests for .json), modes, mtimes, and the last commits
# that touched the source file. Digests only: no content, rendered output, or
# diff is printed.
set -u

sha_file() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d ' ' -f 1
  else shasum -a 256 "$1" | cut -d ' ' -f 1
  fi
}
mtime() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || printf '0\n'; }
mode() { stat -c %a "$1" 2>/dev/null || stat -f %Lp "$1" 2>/dev/null || printf 'unknown\n'; }

work=$(mktemp -d "${TMPDIR:-/tmp}/fleet-chezmoi-evidence.XXXXXX") || exit 70
trap 'rm -rf "$work"' EXIT HUP INT TERM
dest=$(chezmoi dump-config --format json 2>/dev/null </dev/null | jq -r '.destDir // .destdir // empty')
[ -n "$dest" ] || dest=$HOME
src=$(chezmoi source-path </dev/null)

: >"$work/rows"
: >"$work/targets"
for rel in "$@"; do
  case $rel in
    /*|-*|..|../*|*/../*|*/..) printf 'evidence: refusing unsafe target %s\n' "$rel" >&2; continue ;;
  esac
  printf '%s\n' "$dest/$rel" >>"$work/targets"
  live=$dest/$rel
  status_line=$(chezmoi status -- "$live" 2>/dev/null </dev/null | head -n 1)
  source_file=$(chezmoi source-path -- "$live" 2>/dev/null </dev/null || true)
  source_rel=${source_file#"$src"/}
  kind=plain
  case $(basename -- "$source_file") in
    modify_*) kind=modify ;;
    *.tmpl) kind=template ;;
  esac
  rendered='' rendered_json='' live_digest='' live_json='' live_mode='' live_mtime=0
  if chezmoi cat -- "$live" >"$work/rendered" 2>/dev/null </dev/null; then
    rendered=$(sha_file "$work/rendered")
    case $rel in *.json) jq -S . "$work/rendered" >"$work/c" 2>/dev/null && rendered_json=$(sha_file "$work/c") ;; esac
  fi
  if [ -f "$live" ]; then
    live_digest=$(sha_file "$live")
    live_mode=$(mode "$live")
    live_mtime=$(mtime "$live")
    case $rel in *.json) jq -S . "$live" >"$work/c" 2>/dev/null && live_json=$(sha_file "$work/c") ;; esac
  fi
  rm -f "$work/rendered" "$work/c"
  source_mtime=0
  [ -z "$source_file" ] || [ ! -e "$source_file" ] || source_mtime=$(mtime "$source_file")
  history='[]'
  if [ -n "$source_file" ]; then
    history=$(git -C "$src" log -3 --format='%h%x09%cs%x09%s' -- "$source_rel" 2>/dev/null |
      jq -Rsc 'split("\n") | map(select(length > 0) | split("\t") | {commit:.[0],date:.[1],subject:.[2]})')
  fi
  jq -cn --arg target "$rel" --arg status "$status_line" --arg source "$source_rel" --arg kind "$kind" \
    --arg rendered "$rendered" --arg live "$live_digest" --arg rendered_json "$rendered_json" \
    --arg live_json "$live_json" --arg live_mode "$live_mode" --argjson live_mtime "$live_mtime" \
    --argjson source_mtime "$source_mtime" --argjson history "$history" '
    {target:$target,status:$status,source:$source,kind:$kind,
     rendered_sha256:$rendered,live_sha256:$live,
     canonical_json_equal:(if $rendered_json != "" and $live_json != "" then $rendered_json == $live_json else null end),
     live_mode:$live_mode,live_mtime:$live_mtime,source_mtime:$source_mtime,history:$history}' \
    >>"$work/rows"
done
# The digest a targeted Roundhouse plan seals: `chezmoi status -- TARGET...`.
status_digest=''
if [ -s "$work/targets" ]; then
  set --
  while IFS= read -r target; do set -- "$@" "$target"; done <"$work/targets"
  chezmoi status -- "$@" >"$work/status" 2>/dev/null </dev/null && status_digest=$(sha_file "$work/status")
fi
jq -sc --arg dest "$dest" --arg status_digest "$status_digest" \
  '{schema:"fleet-chezmoi.evidence",version:1,dest:$dest,status_digest:$status_digest,targets:.}' "$work/rows"
