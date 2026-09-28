#!/bin/sh
# fleet-chezmoi probe: one read-only inventory batch for the host it runs on.
#
# Emits exactly one JSON object on stdout. It reports paths, status codes,
# commit IDs, modes, and SHA-256 digests only. It never prints file content,
# rendered templates, diffs, or chezmoi data values: anything that could hold a
# secret is hashed inside a private temporary directory and deleted.
#
# Read-only for live state and the source working tree. With the default
# --fetch it runs `git fetch`, which updates remote-tracking refs only.
#
# Deliberately no global `umask`: chezmoi computes permission drift from the
# process umask, so changing it would change `chezmoi status` and break the
# digest match against the Roundhouse collector. mktemp creates private files.
set -u

fetch=true
plugins=false
required="chezmoi git jq"
while [ "$#" -gt 0 ]; do
  case $1 in
    --no-fetch) fetch=false ;;
    --plugins) plugins=true ;;
    --require)
      [ "$#" -ge 2 ] || { printf 'probe: --require needs a tool name\n' >&2; exit 64; }
      case $2 in *[!A-Za-z0-9._+-]*|'') printf 'probe: invalid tool name\n' >&2; exit 64 ;; esac
      required="$required $2"
      shift
      ;;
    *) printf 'probe: unknown argument: %s\n' "$1" >&2; exit 64 ;;
  esac
  shift
done

work=$(mktemp -d "${TMPDIR:-/tmp}/fleet-chezmoi-probe.XXXXXX") || exit 70
trap 'rm -rf "$work"' EXIT HUP INT TERM

export GIT_TERMINAL_PROMPT=0 GIT_OPTIONAL_LOCKS=0
export GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh -o BatchMode=yes -o ConnectTimeout=10}"

sha_file() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d ' ' -f 1
  else shasum -a 256 "$1" | cut -d ' ' -f 1
  fi
}

file_mode() {
  stat -c %a "$1" 2>/dev/null || stat -f %Lp "$1" 2>/dev/null || printf 'unknown\n'
}

missing=
for tool in $required; do
  command -v "$tool" >/dev/null 2>&1 || missing="$missing $tool"
done
host_name=$(hostname 2>/dev/null || uname -n)
user_name=$(id -un)
os_name=$(uname -s)
wsl=false
if [ -r /proc/version ] && grep -qi microsoft /proc/version 2>/dev/null; then wsl=true; fi
shell_umask=$(umask)

if ! command -v jq >/dev/null 2>&1; then
  # Without jq nothing else can be reported safely; emit the minimum by hand.
  printf '{"schema":"fleet-chezmoi.probe","version":1,"identity":{"hostname":"%s","user":"%s"},"login_shell":{"shell":"%s","missing_tools":["jq"]},"error":"jq_missing"}\n' \
    "$host_name" "$user_name" "${SHELL:-}"
  exit 0
fi

# shellcheck disable=SC2086 # word-split the space-separated tool list
missing_json=$(printf '%s\n' $missing | jq -Rsc 'split("\n") | map(select(length > 0))')
identity=$(jq -cn --arg hostname "$host_name" --arg user "$user_name" --arg os "$os_name" \
  --argjson wsl "$wsl" '{hostname:$hostname,user:$user,os:$os,wsl:$wsl}')
login_shell=$(jq -cn --arg shell "${SHELL:-}" --argjson missing "$missing_json" \
  '{shell:$shell,missing_tools:$missing}')

emit() {
  # emit ERROR [SOURCE-JSON]
  jq -cn --argjson identity "$identity" --argjson login_shell "$login_shell" \
    --arg error "$1" \
    '{schema:"fleet-chezmoi.probe",version:1,identity:$identity,
      login_shell:$login_shell,error:$error}'
}

if ! command -v chezmoi >/dev/null 2>&1; then emit chezmoi_missing; exit 0; fi

# Only three keys leave dump-config; its .data section can hold secrets and is
# never written to disk or printed.
if ! config=$(chezmoi dump-config --format json 2>/dev/null |
  jq -c '{destDir:(.destDir // .destdir // ""),sourceDir:(.sourceDir // .sourcedir // ""),
          umask:(.umask // null)}'); then
  emit chezmoi_config_unreadable
  exit 0
fi
dest=$(printf '%s' "$config" | jq -r '.destDir')
[ -n "$dest" ] || dest=$HOME
src=$(chezmoi source-path 2>/dev/null) || src=$(printf '%s' "$config" | jq -r '.sourceDir')
chezmoi_umask=$(printf '%s' "$config" | jq -r '.umask // empty')

# --- source repository -------------------------------------------------------
fetch_state=skipped
head='' upstream='' upstream_head='' ahead=0 behind=0 dirty_count=0
: >"$work/dirty"
if git -C "$src" rev-parse --git-dir >/dev/null 2>&1; then
  head=$(git -C "$src" rev-parse HEAD 2>/dev/null || true)
  upstream=$(git -C "$src" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)
  if [ "$fetch" = true ] && [ -n "$upstream" ]; then
    if git -C "$src" fetch --quiet 2>/dev/null; then fetch_state=ok; else fetch_state=failed; fi
  fi
  if [ -n "$upstream" ]; then
    upstream_head=$(git -C "$src" rev-parse '@{u}' 2>/dev/null || true)
    counts=$(git -C "$src" rev-list --left-right --count 'HEAD...@{u}' 2>/dev/null || printf '0 0')
    ahead=${counts%%[!0-9]*}
    behind=${counts##*[!0-9]}
  fi
  git -C "$src" status --porcelain=v1 2>/dev/null | cut -c 4- >"$work/dirty"
  dirty_count=$(awk 'NF {n++} END {print n+0}' "$work/dirty")
  source_state=git
else
  source_state=not_git
fi
dirty_json=$(head -n 100 "$work/dirty" | jq -Rsc 'split("\n") | map(select(length > 0))')
source_json=$(jq -cn --arg path "$src" --arg state "$source_state" --arg head "$head" \
  --arg upstream "$upstream" --arg upstream_head "$upstream_head" --arg fetch "$fetch_state" \
  --argjson ahead "${ahead:-0}" --argjson behind "${behind:-0}" \
  --argjson dirty_count "$dirty_count" --argjson dirty "$dirty_json" \
  '{path:$path,state:$state,head:$head,upstream:$upstream,upstream_head:$upstream_head,
    fetch:$fetch,ahead:$ahead,behind:$behind,dirty_count:$dirty_count,dirty:$dirty}')

# --- live status: the same command and bytes the Roundhouse collector hashes ---
status_ok=true
if ! chezmoi status >"$work/status" 2>"$work/status.err"; then status_ok=false; fi
status_digest=$(sha_file "$work/status")
status_count=$(awk 'NF {n++} END {print n+0}' "$work/status")
status_lines=$(head -n 200 "$work/status" |
  awk 'NF {printf "%s\t%s\t%s\n", substr($0,1,1), substr($0,2,1), substr($0,4)}' |
  jq -Rsc 'split("\n") | map(select(length > 0) | split("\t") |
    {live:.[0],target:.[1],path:.[2]})')

diff_digest=
if [ "$status_ok" = true ] && [ "$status_count" -gt 0 ]; then
  if chezmoi --no-pager diff >"$work/diff" 2>/dev/null; then diff_digest=$(sha_file "$work/diff"); fi
  rm -f "$work/diff"
fi

# JSON targets whose only difference is key order: compare canonical forms by
# digest, never by content.
: >"$work/keyorder"
printf '%s' "$status_lines" | jq -r '.[] | select(.target == "M" and (.path | endswith(".json"))) | .path' |
  head -n 20 | while IFS= read -r rel; do
    live=$dest/$rel
    [ -f "$live" ] || continue
    chezmoi cat -- "$live" >"$work/rendered" 2>/dev/null || continue
    if jq -S . "$work/rendered" >"$work/a" 2>/dev/null && jq -S . "$live" >"$work/b" 2>/dev/null &&
      [ "$(sha_file "$work/a")" = "$(sha_file "$work/b")" ]; then
      printf '%s\n' "$rel" >>"$work/keyorder"
    fi
    rm -f "$work/rendered" "$work/a" "$work/b"
  done
keyorder_json=$(jq -Rsc 'split("\n") | map(select(length > 0))' "$work/keyorder")

# Live edits: what changed, when, and where it maps in the source. The fleet
# classifier compares these across hosts to find where each change came from.
: >"$work/edits"
printf '%s' "$status_lines" | jq -r '.[] | select(.live != " " and .target != " ") | .path' |
  head -n 50 | while IFS= read -r rel; do
    live=$dest/$rel
    live_sha='' live_mtime=0 kind=plain
    if [ -f "$live" ] && [ ! -L "$live" ]; then
      live_sha=$(sha_file "$live")
      live_mtime=$(stat -c %Y "$live" 2>/dev/null || stat -f %m "$live" 2>/dev/null || printf '0')
    else
      kind=not-a-file
    fi
    source_file=$(chezmoi source-path -- "$live" 2>/dev/null </dev/null || true)
    source_rel=${source_file#"$src"/}
    case $(basename -- "$source_file") in
      modify_*) kind=modify ;;
      *.tmpl) kind=template ;;
      encrypted_*|*.age|*.asc) kind=encrypted ;;
      symlink_*) kind=symlink ;;
      '') kind=unmapped ;;
    esac
    upstream_time=0 head_time=0 upstream_sha=''
    if [ -n "$source_file" ]; then
      head_time=$(git -C "$src" log -1 --format=%ct HEAD -- "$source_rel" 2>/dev/null || true)
      head_time=${head_time:-0}
      if [ -n "$upstream" ]; then
        upstream_time=$(git -C "$src" log -1 --format=%ct '@{u}' -- "$source_rel" 2>/dev/null || true)
        upstream_time=${upstream_time:-0}
        # For a plain source the upstream file is the target itself: an edit that
        # already equals it has been published and only needs a pull.
        if [ "$kind" = plain ] && git -C "$src" show "@{u}:$source_rel" >"$work/upstream-file" 2>/dev/null; then
          upstream_sha=$(sha_file "$work/upstream-file")
        fi
        rm -f "$work/upstream-file"
      fi
    fi
    jq -cn --arg path "$rel" --arg sha "$live_sha" --argjson mtime "$live_mtime" --arg source "$source_rel" \
      --arg kind "$kind" --argjson upstream_time "$upstream_time" --argjson head_time "$head_time" \
      --arg upstream_sha "$upstream_sha" \
      '{path:$path,live_sha256:$sha,live_mtime:$mtime,source:$source,kind:$kind,
        source_upstream_time:$upstream_time,source_head_time:$head_time,upstream_sha256:$upstream_sha}' >>"$work/edits"
  done
edits_json=$(jq -sc '.' "$work/edits")

# --- managed JSON settings (fleet-wide keys of app-written files) --------------
# A source repository can declare, in .fleet-chezmoi.json, app-written JSON
# files whose modify_ script merges a plain JSON template of fleet-wide keys.
# For each such file, compare this host's values for those keys (one level into
# objects) with every recent published version of the template. A value that
# matches some published version is just behind; one that matches none was
# edited here. Only paths, states, times, and value digests leave this host.
: >"$work/managed"
if [ -f "$src/.fleet-chezmoi.json" ]; then
  ref=HEAD
  [ -z "$upstream" ] || ref='@{u}'
  jq -c '.managed_json[]?' "$src/.fleet-chezmoi.json" 2>/dev/null >"$work/managed-specs" || : >"$work/managed-specs"
  while IFS= read -r spec; do
    m_target=$(printf '%s' "$spec" | jq -r '.target // empty')
    m_managed=$(printf '%s' "$spec" | jq -r '.managed // empty')
    m_review=$(printf '%s' "$spec" | jq -c '.review_keys // []')
    case $m_target$m_managed in *..*|/*) continue ;; esac
    m_live=$dest/$m_target
    [ -n "$m_target" ] && [ -n "$m_managed" ] && [ -f "$m_live" ] && [ ! -L "$m_live" ] || continue
    jq -e 'type == "object"' "$m_live" >/dev/null 2>&1 || continue
    : >"$work/versions"
    git -C "$src" log --format='%H %ct' -n 20 "$ref" -- "$m_managed" 2>/dev/null |
      while read -r commit ctime; do
        git -C "$src" show "$commit:$m_managed" 2>/dev/null |
          jq -c --argjson t "$ctime" 'select(type == "object") | {time:$t,doc:.}' >>"$work/versions" 2>/dev/null || :
      done
    [ -s "$work/versions" ] || continue
    m_mtime=$(stat -c %Y "$m_live" 2>/dev/null || stat -f %m "$m_live" 2>/dev/null || printf '0')
    jq -rn --slurpfile v "$work/versions" --slurpfile l "$m_live" --argjson review "$m_review" '
      def flat: to_entries | map(
        if (.value | type) == "object" then
          (.key as $k | .value | to_entries | map({key: ([$k, .key] | tojson), value: (.value | tojson)}))
        else [{key: ([.key] | tojson), value: (.value | tojson)}] end) | add // [] | from_entries;
      ($v | sort_by(-.time)) as $vs
      | ($vs | map(.doc | flat)) as $hist
      | ($vs[0].doc | keys) as $keys
      | ($l[0] | with_entries(select(.key as $k | $keys | index($k) != null)) | flat) as $lf
      | ($hist[0]) as $uf
      | ([$lf, $uf] | map(keys) | add | unique)[] as $p
      | ($lf[$p] // "#absent") as $lv
      | select($lv != ($uf[$p] // "#absent"))
      | select(($hist | map(.[$p] // "#absent") | index($lv)) == null)
      | ([range(0; ($hist | length) - 1) | select(($hist[.][$p] // "#absent") != ($hist[. + 1][$p] // "#absent"))]
          | if length > 0 then $vs[.[0]].time else $vs[-1].time end) as $pt
      | [$p, (if $lv == "#absent" then "removed" else "set" end), ($lv | @base64), ($pt | tostring),
         (($p | fromjson)[0] as $k | $review | index($k) != null | tostring)] | @tsv
    ' >"$work/managed-edits" 2>/dev/null || : >"$work/managed-edits"
    [ -s "$work/managed-edits" ] || continue
    : >"$work/managed-rows"
    while IFS="$(printf '\t')" read -r m_path m_state m_value m_ptime m_isreview; do
      if [ "$m_state" = removed ]; then
        m_sha=absent
      else
        printf '%s' "$m_value" | base64 --decode >"$work/value" 2>/dev/null
        m_sha=$(sha_file "$work/value")
        rm -f "$work/value"
      fi
      jq -cn --argjson path "$m_path" --arg state "$m_state" --arg sha "$m_sha" \
        --argjson ptime "$m_ptime" --argjson review "$m_isreview" \
        '{path:$path,state:$state,value_sha256:$sha,upstream_path_time:$ptime,review:$review}' >>"$work/managed-rows"
    done <"$work/managed-edits"
    jq -cn --arg target "$m_target" --arg managed "$m_managed" --argjson mtime "$m_mtime" \
      --slurpfile edits "$work/managed-rows" \
      '{target:$target,managed:$managed,live_mtime:$mtime,edits:$edits}' >>"$work/managed"
  done <"$work/managed-specs"
fi
managed_json=$(jq -sc '.' "$work/managed")

# --- git-repo externals ------------------------------------------------------
: >"$work/externals"
chezmoi managed --include=externals --path-style=absolute 2>/dev/null |
  while IFS= read -r ext; do
    [ -d "$ext/.git" ] || continue
    ext_fetch=skipped
    if [ "$fetch" = true ]; then
      if git -C "$ext" fetch --quiet 2>/dev/null; then ext_fetch=ok; else ext_fetch=failed; fi
    fi
    ext_head=$(git -C "$ext" rev-parse HEAD 2>/dev/null || true)
    ext_up=$(git -C "$ext" rev-parse '@{u}' 2>/dev/null || true)
    # Ignored and untracked files count: a hard reset overwrites an ignored local
    # file whose path the rewritten upstream now tracks. A failed status is
    # never read as clean.
    if git -C "$ext" status --porcelain --ignored --untracked-files=all >"$work/ext-status" 2>/dev/null; then
      ext_dirty=$(awk 'NF {n++} END {print n+0}' "$work/ext-status")
    else
      ext_dirty=1
    fi
    ext_ahead=0 ext_behind=0 upstream_origin=false state=no-upstream
    if [ -n "$ext_up" ]; then
      counts=$(git -C "$ext" rev-list --left-right --count 'HEAD...@{u}' 2>/dev/null || printf '0 0')
      ext_ahead=${counts%%[!0-9]*}
      ext_behind=${counts##*[!0-9]}
      # HEAD's commits all came from upstream when the branch was only ever moved
      # by clone or fast-forward and HEAD is (an ancestor of) a tip upstream
      # delivered. Evidence: the branch reflog, plus old/new values the
      # remote-tracking ref's reflog recorded when a fetch force-updated it.
      up_ref=$(git -C "$ext" rev-parse --symbolic-full-name '@{u}' 2>/dev/null || true)
      branch_ref=$(git -C "$ext" symbolic-ref -q HEAD 2>/dev/null || true)
      branch_log=$(git -C "$ext" rev-parse --git-path "logs/$branch_ref" 2>/dev/null || true)
      up_log=$(git -C "$ext" rev-parse --git-path "logs/$up_ref" 2>/dev/null || true)
      case $branch_log in /*) ;; *) branch_log=$ext/$branch_log ;; esac
      case $up_log in /*) ;; *) up_log=$ext/$up_log ;; esac
      local_writes=true
      : >"$work/tips"
      : >"$work/up-tips"
      : >"$work/resets"
      if [ -f "$up_log" ]; then
        awk '{print $1; print $2}' "$up_log" >"$work/up-tips"
        cat "$work/up-tips" >>"$work/tips"
      fi
      if [ -n "$branch_ref" ] && [ -f "$branch_log" ]; then
        local_writes=false
        # Reflog lines: OLD NEW IDENT<TAB>MESSAGE.
        awk -F '\t' '{split($1, f, " "); print f[2] "\t" $2}' "$branch_log" >"$work/branch-log"
        while IFS="$(printf '\t')" read -r new message; do
          case $message in
            # Match the reflog operation, never a commit subject.
            "clone: "*|"pull: Fast-forward"|"pull "*": Fast-forward") printf '%s\n' "$new" >>"$work/tips" ;;
            # An earlier sealed reset: upstream-delivered only if it moved to a
            # commit the upstream ref itself recorded.
            "reset: moving to "*) printf '%s\n' "$new" >>"$work/resets" ;;
            *) local_writes=true ;;
          esac
        done <"$work/branch-log"
        while IFS= read -r target; do
          grep -qx -- "$target" "$work/up-tips" || local_writes=true
        done <"$work/resets"
      fi
      if [ "$local_writes" = false ]; then
        for tip in $(grep -v '^0*$' "$work/tips" | sort -u | head -n 400); do
          if git -C "$ext" merge-base --is-ancestor "$ext_head" "$tip" 2>/dev/null; then
            upstream_origin=true
            break
          fi
        done
      fi
      if [ "$ext_ahead" -eq 0 ]; then
        if [ "$ext_dirty" -gt 0 ]; then state=dirty
        elif [ "$ext_behind" -eq 0 ]; then state=current
        else state=behind
        fi
      elif [ "$ext_dirty" -eq 0 ] && [ "$upstream_origin" = true ]; then
        # Upstream rewrote history: chezmoi's `pull --ff-only` will fail.
        state=rewritten-resettable
      else
        state=rewritten-local-changes
      fi
    fi
    jq -cn --arg path "$ext" --arg state "$state" --arg head "$ext_head" --arg upstream_head "$ext_up" \
      --arg fetch "$ext_fetch" --argjson dirty_count "$ext_dirty" --argjson ahead "$ext_ahead" \
      --argjson behind "$ext_behind" --argjson upstream_origin "$upstream_origin" \
      '{path:$path,state:$state,head:$head,upstream_head:$upstream_head,fetch:$fetch,
        dirty_count:$dirty_count,ahead:$ahead,behind:$behind,local_commits_from_upstream:$upstream_origin}' \
      >>"$work/externals"
  done
externals_json=$(jq -sc '.' "$work/externals")

# --- permission hygiene ------------------------------------------------------
# chezmoi reports umask in decimal; 18 == 0o022. Group/other write bits in the
# effective umask cause permission-only drift and loosen created files.
umask_json=$(jq -cn --arg shell "$shell_umask" --arg chezmoi "$chezmoi_umask" '
  ($chezmoi | if . == "" then null else tonumber end) as $u |
  {shell:$shell,chezmoi:(if $u == null then null else ($u | tostring) end),
   chezmoi_octal:(if $u == null then null else
     ("0o" + ([($u / 64 | floor) % 8, ($u / 8 | floor) % 8, $u % 8] | map(tostring) | join(""))) end),
   allows_group_or_other_write:(if $u == null then null else
     ((($u / 8 | floor) % 8) as $g | ($u % 8) as $o |
      (($g / 2 | floor) % 2 == 0) or (($o / 2 | floor) % 2 == 0)) end)}')

: >"$work/sensitive"
for rel in .ssh .gnupg .aws .kube .docker .config/gh .config/op .password-store .netrc .pgpass; do
  live=$dest/$rel
  [ -e "$live" ] || continue
  source_file=$(chezmoi source-path -- "$live" 2>/dev/null) || continue
  name=$(basename -- "$source_file")
  mode=$(file_mode "$live")
  case $name in
    private_*) private=true ;;
    *) private=false ;;
  esac
  loose=false
  case $mode in
    unknown) ;;
    *) [ "$(( 0$mode & 077 ))" -eq 0 ] || loose=true ;;
  esac
  if [ "$private" = false ] || [ "$loose" = true ]; then
    jq -cn --arg target "$rel" --arg source_name "$name" --arg mode "$mode" \
      --argjson private "$private" --argjson loose "$loose" \
      '{target:$target,source_name:$source_name,live_mode:$mode,private_prefix:$private,
        group_or_other_access:$loose}' >>"$work/sensitive"
  fi
done
sensitive_json=$(jq -sc '.' "$work/sensitive")

# --- scheduled writers to the source tree ------------------------------------
: >"$work/writers"
scan_writer() {
  # scan_writer KIND LABEL FILE
  if grep -qE "chezmoi|dotfiles|$(printf '%s' "$src" | sed 's/[][\.*^$/]/\\&/g')" "$3" 2>/dev/null; then
    flags=$(grep -oE -- '--commit|--push|apply --force|apply -f|re-add|adopt[a-z-]*|chezmoi add' "$3" 2>/dev/null |
      sort -u | jq -Rsc 'split("\n") | map(select(length > 0))')
    jq -cn --arg kind "$1" --arg label "$2" --argjson flags "$flags" \
      '{kind:$kind,label:$label,flags:$flags}' >>"$work/writers"
  fi
}
for plist in "$HOME"/Library/LaunchAgents/*.plist; do
  [ -f "$plist" ] || continue
  scan_writer launchd "$(basename -- "$plist" .plist)" "$plist"
done
for unit in "$HOME"/.config/systemd/user/*.service; do
  [ -f "$unit" ] || continue
  scan_writer systemd "$(basename -- "$unit")" "$unit"
done
if crontab -l >"$work/crontab" 2>/dev/null; then scan_writer cron crontab "$work/crontab"; fi
writers_json=$(jq -sc '[.[] | select((.flags | length) > 0)]' "$work/writers")

# --- agent plugin registration -----------------------------------------------
# Declared marketplaces/plugins synced by chezmoi only take effect once each
# harness registers and installs them (Claude Code registers
# extraKnownMarketplaces only on an interactive trusted start). Names and
# versions only: settings files can hold credentials, so only map keys leave jq.
# Opt-in (--plugins): the harness CLIs take seconds per host.
plugins_json=null
[ "$plugins" = false ] || plugins_json='{}'
if [ "$plugins" = true ] && command -v claude >/dev/null 2>&1; then
  declared_mp='[]' enabled='[]'
  if [ -f "$HOME/.claude/settings.json" ]; then
    declared_mp=$(jq -c '(.extraKnownMarketplaces // {}) | keys' "$HOME/.claude/settings.json" 2>/dev/null || printf '[]')
    enabled=$(jq -c '(.enabledPlugins // {}) | to_entries | map(select(.value == true) | .key)' \
      "$HOME/.claude/settings.json" 2>/dev/null || printf '[]')
  fi
  registered=$(claude plugin marketplace list --json 2>/dev/null </dev/null | jq -c 'map(.name)' 2>/dev/null || printf 'null')
  installed=$(claude plugin list --json 2>/dev/null </dev/null |
    jq -c 'map({key:.id,value:{version,enabled}}) | from_entries' 2>/dev/null || printf 'null')
  plugins_json=$(jq -cn --argjson p "$plugins_json" --argjson d "$declared_mp" --argjson e "$enabled" \
    --argjson r "$registered" --argjson i "$installed" \
    '$p + {claude:{declared_marketplaces:$d,enabled:$e,registered_marketplaces:$r,installed:$i}}')
fi
if [ "$plugins" = true ] && command -v codex >/dev/null 2>&1; then
  declared_mp='[]' enabled='[]'
  if [ -f "$HOME/.codex/config.toml" ]; then
    declared_mp=$(sed -n 's/^\[marketplaces\.\([A-Za-z0-9._-]*\)\][[:space:]]*$/\1/p' "$HOME/.codex/config.toml" |
      jq -Rsc 'split("\n") | map(select(length > 0))')
    # Only [plugins."ID"] tables that set enabled = true.
    enabled=$(awk '
      /^\[/ { id = ""; if (match($0, /^\[plugins\."[^"]+"\]/)) id = substr($0, 11, RLENGTH - 12); next }
      id != "" && /^[[:space:]]*enabled[[:space:]]*=[[:space:]]*true/ { print id; id = "" }
    ' "$HOME/.codex/config.toml" | jq -Rsc 'split("\n") | map(select(length > 0))')
  fi
  # Marketplaces the Codex app itself ships (bundled, runtime, curated) differ by
  # app version and platform on purpose; only user-declared ones are compared.
  codex_markets=$(codex plugin marketplace list --json 2>/dev/null </dev/null || true)
  runtime=$(printf '%s' "$codex_markets" | jq -c '[.marketplaces[]? |
    select(.marketplaceSource.sourceType == null or ((.root // "") | test("/codex-runtimes/|/bundled-marketplaces/"))) | .name]' \
    2>/dev/null || printf '[]')
  registered=$(printf '%s' "$codex_markets" | jq -c --argjson rt "$runtime" \
    '.marketplaces | map(.name) - $rt' 2>/dev/null || printf 'null')
  declared_mp=$(jq -cn --argjson d "$declared_mp" --argjson rt "$runtime" '$d - $rt')
  installed=$(codex plugin list --json 2>/dev/null </dev/null | jq -c --argjson rt "$runtime" '
    .installed | map(select((.marketplaceName // (.pluginId | split("@") | last)) as $m | $rt | index($m) | not))
    | map({key:.pluginId,value:{version,enabled}}) | from_entries' 2>/dev/null || printf 'null')
  plugins_json=$(jq -cn --argjson p "$plugins_json" --argjson d "$declared_mp" --argjson e "$enabled" \
    --argjson r "$registered" --argjson i "$installed" \
    '$p + {codex:{declared_marketplaces:$d,enabled:$e,registered_marketplaces:$r,installed:$i}}')
fi

status_json=$(jq -cn --argjson ok "$status_ok" --arg digest "$status_digest" \
  --argjson count "$status_count" --argjson lines "$status_lines" --arg diff_digest "$diff_digest" \
  --argjson keyorder "$keyorder_json" --argjson edits "$edits_json" \
  '{ok:$ok,digest:$digest,count:$count,truncated:($count > ($lines | length)),lines:$lines,
    diff_digest:$diff_digest,json_key_order_only:$keyorder,edits:$edits}')

jq -cn --argjson identity "$identity" --argjson login_shell "$login_shell" \
  --arg dest "$dest" --argjson source "$source_json" --argjson status "$status_json" --argjson managed "$managed_json" \
  --argjson externals "$externals_json" --argjson umask "$umask_json" \
  --argjson sensitive "$sensitive_json" --argjson writers "$writers_json" --argjson plugins "$plugins_json" \
  '{schema:"fleet-chezmoi.probe",version:1,identity:$identity,login_shell:$login_shell,
    dest:$dest,source:$source,status:$status,managed_json:$managed,externals:$externals,umask:$umask,
    sensitive_without_private:$sensitive,scheduled_source_writers:$writers,plugins:$plugins}'
