#!/bin/sh
# fleet-chezmoi converge-plugins: bring this host's plugins to what the fleet
# declares, now.
#
# 1. Roundhouse fleet-run owns the plugins its fleet store declares: it
#    registers their marketplaces, installs, updates, and enables them, with
#    catalog-identity and hook-trust checks. It already runs every 20 minutes;
#    this runs the same fast pass immediately.
# 2. Claude plugins that the synced settings enable (enabledPlugins, captured
#    from whichever host enabled them) but this host lacks are installed, after
#    registering their marketplace from the synced extraKnownMarketplaces.
#    Nothing is installed that the user's own settings do not enable.
#
#   converge-plugins.sh EXPECTED-HOSTNAME EXPECTED-USER
#
# Nothing changes unless this host is the one the controller verified.
set -u
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
if ! this_host_is "${1:-}" "${2:-}"; then
  jq -cn '{schema:"fleet-chezmoi.plugins",version:1,ok:false,exit:65,installed:[],failed:[],
    error:"identity does not match the verified host; nothing was changed"}'
  exit 0
fi
work=$(mktemp -d "${TMPDIR:-/tmp}/fleet-chezmoi-plugins.XXXXXX") || exit 70
trap 'rm -rf "$work"' EXIT HUP INT TERM

rc=0 skipped=''
case $(uname -s) in
  # Roundhouse's fleet-run is a POSIX maintenance pass, and it is what
  # converges Codex plugins; native Windows has neither here, so only the
  # Claude installs below run, and Codex is reported as not converged.
  MINGW*|MSYS*|CYGWIN*)
    ! command -v codex >/dev/null 2>&1 ||
      skipped="codex: native Windows Codex plugins follow Roundhouse's native refresh (fleet-agents), not this step" ;;
  *)
    if command -v roundhouse >/dev/null 2>&1; then
      roundhouse fleet-run --fast >/dev/null 2>&1 </dev/null || rc=$?
    else
      rc=127
    fi ;;
esac

: >"$work/installed"
: >"$work/failed"
settings=${CLAUDE_CONFIG_DIR:-$HOME/.claude}/settings.json
if command -v claude >/dev/null 2>&1 && [ -f "$settings" ]; then
  claude plugin list --json 2>/dev/null </dev/null | jq -r '.[].id' >"$work/have" 2>/dev/null || : >"$work/have"
  jq -r '(.enabledPlugins // {}) | to_entries[] | select(.value == true) | .key' "$settings" 2>/dev/null |
    while IFS= read -r id; do
      case $id in *[!A-Za-z0-9._@-]*|-*|'') continue ;; esac
      grep -qx -- "$id" "$work/have" && continue
      market=${id##*@}
      if ! claude plugin marketplace list --json 2>/dev/null </dev/null |
        jq -e --arg m "$market" 'any(.[]; .name == $m)' >/dev/null 2>&1; then
        # A declared ref (branch or tag) is kept with #ref.
        source=$(jq -r --arg m "$market" '.extraKnownMarketplaces[$m].source // empty |
          ((.ref // "") | if . == "" then "" else "#" + . end) as $ref |
          if .source == "github" then .repo + $ref elif .source == "git" then .url + $ref
          elif .source == "directory" then .path elif .source == "url" then .url else empty end' "$settings" 2>/dev/null)
        case $source in
          ''|-*|*[[:space:]]*) printf '%s\n' "$id" >>"$work/failed"; continue ;;
          *'#'*) case ${source##*#} in ''|*[!A-Za-z0-9._/-]*) printf '%s\n' "$id" >>"$work/failed"; continue ;; esac ;;
        esac
        claude plugin marketplace add "$source" >/dev/null 2>&1 </dev/null || { printf '%s\n' "$id" >>"$work/failed"; continue; }
      fi
      if claude plugin install "$id" --scope user >/dev/null 2>&1 </dev/null &&
        claude plugin list --json 2>/dev/null </dev/null | jq -e --arg id "$id" 'any(.[]; .id == $id)' >/dev/null 2>&1; then
        printf '%s\n' "$id" >>"$work/installed"
      else
        printf '%s\n' "$id" >>"$work/failed"
      fi
    done
fi

jq -cn --argjson rc "$rc" --rawfile installed "$work/installed" --rawfile failed "$work/failed" --arg skipped "$skipped" '
  ($installed | split("\n") | map(select(length > 0))) as $i
  | ($failed | split("\n") | map(select(length > 0))) as $f
  | {schema:"fleet-chezmoi.plugins",version:1,ok:($rc == 0 and ($f | length) == 0),exit:$rc,
     installed:$i,failed:$f,skipped:(if $skipped == "" then [] else [$skipped] end),
     error:(if $rc == 127 then "roundhouse is not on PATH" elif ($f | length) > 0 then "could not install: " + ($f | join(", ")) else null end)}'
