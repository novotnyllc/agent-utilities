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
set -u
work=$(mktemp -d "${TMPDIR:-/tmp}/fleet-chezmoi-plugins.XXXXXX") || exit 70
trap 'rm -rf "$work"' EXIT HUP INT TERM

rc=0
if command -v roundhouse >/dev/null 2>&1; then
  roundhouse fleet-run --fast >/dev/null 2>&1 </dev/null || rc=$?
else
  rc=127
fi

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

jq -cn --argjson rc "$rc" --rawfile installed "$work/installed" --rawfile failed "$work/failed" '
  ($installed | split("\n") | map(select(length > 0))) as $i
  | ($failed | split("\n") | map(select(length > 0))) as $f
  | {schema:"fleet-chezmoi.plugins",version:1,ok:($rc == 0 and ($f | length) == 0),exit:$rc,
     installed:$i,failed:$f,
     error:(if $rc == 127 then "roundhouse is not on PATH" elif ($f | length) > 0 then "could not install: " + ($f | join(", ")) else null end)}'
