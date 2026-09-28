#!/bin/sh
# fleet-chezmoi fetch-json: hand the changed entries of a managed JSON settings
# file to the controller for a capture.
#
#   fetch-json.sh RELATIVE-TARGET ENTRIES-JSON EXPECTED-HOSTNAME EXPECTED-USER
#
# ENTRIES-JSON is [{path:[KEY] or [KEY,SUBKEY], state:"set"|"removed", digest}].
# Each value is emitted (canonical JSON, base64) only if its digest still equals
# the approved one and the entry still exists, and a removed entry only if it
# is still absent. Nothing else in the file leaves this host, and nothing
# prints the values.
set -u

fail() {
  jq -cn --arg error "$1" '{schema:"fleet-chezmoi.fetch-json",version:1,ok:false,error:$error}'
  exit 0
}
sha_file() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d ' ' -f 1
  else shasum -a 256 "$1" | cut -d ' ' -f 1
  fi
}

# Nothing is read unless this host is the one the controller verified: the
# SSH alias may resolve elsewhere since the probe.
# this_host_is HOST USER — this machine is HOST/USER. On native Windows (Git
# for Windows sh) the names are COMPUTERNAME/USERNAME, compared
# case-insensitively, exactly as Roundhouse's Windows executor compares them.
this_host_is() {
  [ -n "$1" ] && [ "$1" != null ] && [ -n "$2" ] && [ "$2" != null ] || return 1
  case $(uname -s) in
    MINGW*|MSYS*|CYGWIN*)
      [ "$(printf '%s|%s' "${COMPUTERNAME:-$(hostname)}" "${USERNAME:-$(id -un)}" | tr '[:upper:]' '[:lower:]')" = \
        "$(printf '%s|%s' "$1" "$2" | tr '[:upper:]' '[:lower:]')" ] ;;
    *) [ "$(hostname 2>/dev/null || uname -n)" = "$1" ] && [ "$(id -un)" = "$2" ] ;;
  esac
}
this_host_is "${3:-}" "${4:-}" || fail "identity does not match the verified host"
rel=${1:-}
entries=${2:-}
case $rel in ''|/*|-*|..|../*|*/../*|*/..) fail "unsafe target" ;; esac
printf '%s' "$entries" | jq -e 'type == "array" and length > 0 and all(.[];
  (.path | type == "array" and length >= 1 and length <= 2 and all(.[]; type == "string")) and
  (.state | IN("set","removed")))' >/dev/null 2>&1 || fail "invalid entries"

dest=$(chezmoi dump-config --format json 2>/dev/null </dev/null | jq -r '.destDir // .destdir // empty')
[ -n "$dest" ] || dest=$HOME
live=$dest/$rel
[ -f "$live" ] && [ ! -L "$live" ] || fail "not a regular file"
jq -e 'type == "object"' "$live" >/dev/null 2>&1 || fail "not a JSON object"

work=$(mktemp -d "${TMPDIR:-/tmp}/fleet-chezmoi-fetch.XXXXXX") || fail "no temporary directory"
trap 'rm -rf "$work"' EXIT HUP INT TERM
: >"$work/out"
printf '%s' "$entries" | jq -c '.[]' >"$work/entries"
while IFS= read -r entry; do
  path=$(printf '%s' "$entry" | jq -c '.path')
  state=$(printf '%s' "$entry" | jq -r '.state')
  if [ "$state" = removed ]; then
    # Absent, not merely null: a recreated null value is a change.
    jq -e --argjson p "$path" '
      if ($p | length) == 1 then has($p[0]) | not
      else (.[$p[0]] | type) != "object" or (.[$p[0]] | has($p[1]) | not) end' "$live" >/dev/null 2>&1 ||
      fail "an approved removal is no longer absent"
    jq -cn --argjson p "$path" '{path:$p,state:"removed",b64:""}' >>"$work/out"
  else
    # Present, not merely null: a deleted entry is a change.
    jq -e --argjson p "$path" '
      if ($p | length) == 1 then has($p[0])
      else (.[$p[0]] | type) == "object" and (.[$p[0]] | has($p[1])) end' "$live" >/dev/null 2>&1 ||
      fail "an approved entry is no longer present"
    # The same canonical form (keys sorted) the probe digested.
    jq -c --argjson p "$path" 'def canon: if type == "object" then to_entries | sort_by(.key) | map(.value |= canon) | from_entries
        elif type == "array" then map(canon) else . end;
      getpath($p) | canon | tojson' "$live" | jq -r . >"$work/value" ||
      fail "cannot read an approved entry"
    printf '%s' "$(cat "$work/value")" >"$work/value.raw"
    [ "$(sha_file "$work/value.raw")" = "$(printf '%s' "$entry" | jq -r '.digest')" ] ||
      fail "an approved entry changed since it was approved"
    base64 <"$work/value.raw" | tr -d '\n' |
      jq -Rc --argjson p "$path" '{path:$p,state:"set",b64:.}' >>"$work/out"
  fi
done <"$work/entries"
jq -sc '{schema:"fleet-chezmoi.fetch-json",version:1,ok:true,entries:.}' "$work/out"
