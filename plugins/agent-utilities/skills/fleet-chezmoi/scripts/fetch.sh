#!/bin/sh
# fleet-chezmoi fetch: hand one live file to the controller for a capture.
#
#   fetch.sh RELATIVE-TARGET EXPECTED-SHA256 EXPECTED-HOSTNAME EXPECTED-USER
#
# Emits the file base64-encoded inside one JSON line, only if it is a regular
# file of at most 1 MiB whose digest still equals the one that was approved.
# The controller decodes it straight into the source tree; nothing prints it.
set -u

fail() {
  jq -cn --arg error "$1" '{schema:"fleet-chezmoi.fetch",version:1,ok:false,error:$error}'
  exit 0
}
sha_file() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d ' ' -f 1
  else shasum -a 256 "$1" | cut -d ' ' -f 1
  fi
}

# Nothing is read unless this host is the one the controller verified: the
# SSH alias may resolve elsewhere since the probe.
case "$(hostname 2>/dev/null || uname -n)|$(id -un)" in
  "${3:-}|${4:-}") [ -n "${3:-}" ] && [ "${3:-}" != null ] || fail "identity does not match the verified host" ;;
  *) fail "identity does not match the verified host" ;;
esac
rel=${1:-}
expected=${2:-}
case $rel in ''|/*|-*|..|../*|*/../*|*/..) fail "unsafe target" ;; esac
case $expected in ''|*[!0-9a-f]*) fail "invalid digest" ;; esac

dest=$(chezmoi dump-config --format json 2>/dev/null </dev/null | jq -r '.destDir // .destdir // empty')
[ -n "$dest" ] || dest=$HOME
live=$dest/$rel
[ -f "$live" ] && [ ! -L "$live" ] || fail "not a regular file"
size=$(wc -c <"$live" | tr -d ' ')
[ "$size" -le 1048576 ] || fail "larger than 1 MiB"
[ "$(sha_file "$live")" = "$expected" ] || fail "changed since it was approved"

base64 <"$live" | tr -d '\n' | jq -Rsc '{schema:"fleet-chezmoi.fetch",version:1,ok:true,b64:.}'
