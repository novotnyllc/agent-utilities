# fleet-chezmoi classifier. Input: an array of probe records
#   {host, transport, expected:{hostname,user}|null, probe:{...}|null, error:string|null}
# Output: an array of per-host decisions, one per input record, in input order.
#
# No host is special. A change can start on any machine, one at a time, so each
# live-edited path is resolved across the whole fleet:
#
#   capture          the newest live edit is newer than any upstream change to
#                    that source file, and every host that edited it holds the
#                    same content: that host is the origin; capture its file
#                    into the source and publish it
#   source-newer     upstream changed the source after this live edit: the edit
#                    is stale; overwriting it needs the host owner's confirmation
#   competing        hosts hold different live content for the path: propose the
#                    newest, but a person decides
#   capture-manual   the origin's source is a template, modify_ script, or
#                    sensitive path: edit the source by hand
#   stale-base       the origin edited the file without having pulled a newer
#                    upstream change to its source; capturing would discard
#                    that change, so pull and reconcile first
#
# Classes:
#   unreachable        probe did not return a usable record
#   unsupported        transport has no fast path (native Windows uses remote control)
#   identity-mismatch  hostname/user differ from the configured expectation: stop
#   review             blockers or conflicts; reconcile the listed paths only
#   capture            this host is the origin of changes to publish
#   pull               clean source strictly behind upstream: seal a ff-only pull
#   awaiting-capture   this host holds a change that is (or is about to be)
#                      published from elsewhere
#   in-sync            nothing to do
#   apply              every pending entry is source-driven: seal a full apply
#                      bound to the exact status digest
#
# A status line is `XY path`. X compares chezmoi's last-written state with the
# live file (X != " " means the live file changed since chezmoi last wrote it).
# Y compares live with the target (what apply would do: A, M, D, R).

def sensitive_path:
  test("^(\\.ssh|\\.gnupg|\\.aws|\\.kube|\\.docker|\\.config/gh|\\.config/op|\\.password-store)(/|$)")
  or test("^(\\.netrc|\\.pgpass)$")
  or test("(^|/)(id_[A-Za-z0-9_-]+|[^/]*\\.(pem|key|p12|pfx))$")
  or test("(?i)(^|/)[^/]*(credential|secret|token|auth)[^/]*$");

def reason($code; $detail): {code:$code,detail:$detail};

def when($t): if ($t // 0) > 0 then ($t | todate) else "unknown time" end;

# Version order for plugin versions: numeric where numeric.
def vkey: tostring | split(".") | map(tonumber? // .);

# Keep plugin IDs (NAME@MARKETPLACE) whose marketplace is in $scope.
def scoped($scope): map(select((split("@") | last) as $m | $scope | index($m) != null));

. as $records
# --- fleet-wide facts --------------------------------------------------------
# Source trees that carry the same uncommitted paths on several hosts point at a
# scheduled writer, not at a person.
| ($records | map(select((.probe.source.dirty_count // 0) > 0) | .probe.source.dirty | sort)
  | group_by(.) | map(select(length > 1) | .[0])) as $repeated_dirty
| ($records | map(.probe.source.upstream_head // empty | select(. != "")) | unique) as $upstream_views
# Per-path origin decisions from every host's live edits.
# An edit whose content already equals upstream has been published: a pull
# resolves it, so it takes no part in deciding anything.
| ($records | map(.host as $h | (.probe.status.edits // [])[]
    | select((.upstream_sha256 // "") != "" and .live_sha256 == .upstream_sha256) | "\($h)\t\(.path)")) as $published
| ($records | map(.host as $h | (.probe.status.edits // [])[]
    | select((.upstream_sha256 // "") == "" or .live_sha256 != .upstream_sha256) | . + {host:$h}) | flatten
  | group_by(.path)
  | map(
      (max_by(.live_mtime)) as $newest
      | (map(.source_upstream_time) | max) as $source_time
      | (map(.live_sha256) | unique) as $digests
      | {key: .[0].path,
         value: {
           decision: (
             if $source_time > $newest.live_mtime then "source-newer"
             elif ($newest.source_head_time // 0) < ($newest.source_upstream_time // 0) then "stale-base"
             # Templates and modify_ scripts render per host, so their live
             # contents differ by design; compare digests only for plain files.
             elif $newest.kind != "plain" or ($newest.path | sensitive_path) then "capture-manual"
             elif ($digests | length) > 1 then "competing"
             else "capture" end),
           origin: $newest.host, mtime: $newest.live_mtime, digest: $newest.live_sha256,
           source: $newest.source, kind: $newest.kind, source_time: $source_time,
           hosts: map(.host)}})
  | from_entries) as $decisions
# Managed JSON settings: per (file, entry) across hosts. Only entries a host
# changed (its value matches no published version) take part.
| ($records | map(.host as $h | (.probe.managed_json // [])[] | . as $m
    | .edits[] | . + {host: $h, target: $m.target, managed: $m.managed, live_mtime: $m.live_mtime}) | flatten
  | group_by([.target, (.path | tojson)])
  | map(
      (max_by(.live_mtime)) as $newest
      | (map(.value_sha256) | unique) as $values
      | {key: ([.[0].target, (.[0].path | tojson)] | tojson),
         value: {
           decision: (
             if $newest.upstream_path_time > $newest.live_mtime then "source-newer"
             elif any(.[]; .review) then "capture-manual"
             elif ($values | length) > 1 then "competing"
             else "capture" end),
           origin: $newest.host, mtime: $newest.live_mtime, source: $newest.managed, kind: "managed-json",
           source_time: $newest.upstream_path_time, target: $newest.target, entry: $newest.path,
           state: $newest.state, digest: $newest.value_sha256, hosts: map(.host)}})
  | from_entries) as $mdecisions
# Plugin baselines: what any host has installed from the marketplaces the fleet
# declares for that harness, and the newest version seen.
| ([$records[] | .probe.plugins // {} | keys[]] | unique) as $harnesses
| (reduce $harnesses[] as $hn ({};
    .[$hn] = {
      scope: ([$records[] | .probe.plugins[$hn].declared_marketplaces // [] | .[]] | unique),
      installed: ([$records[] | .host as $h | (.probe.plugins[$hn].installed // {}) | to_entries[]
        | select(.value.enabled == true) | {id: .key, version: .value.version, host: $h}]
        | group_by(.id) | map({key: .[0].id, value: {hosts: map(.host), newest: (max_by(.version | vkey))}})
        | from_entries)
    })) as $plugin_baseline

| $records | map(
  . as $r
  | ($r.probe // {}) as $p
  | ($p.status.json_key_order_only // []) as $keyorder
  # This host's managed-settings edits, each with its fleet decision.
  | [ ($p.managed_json // [])[] | . as $m | .edits[]
      | $mdecisions[([$m.target, (.path | tojson)] | tojson)] + {mine: .} ] as $medits
  | ($medits | map(.target) | unique) as $mtargets
  | ( [ $medits[] | if .decision != "capture" then "conflict"
        elif .origin == $r.host then "capture" else "captured-elsewhere" end ]
      | if index("conflict") != null then "managed-conflict"
        elif index("capture") != null then "capture"
        elif length > 0 then "captured-elsewhere" else null end ) as $mkind
  | [ ($p.status.lines // [])[]
      | . as $l
      | ($decisions[$l.path] // null) as $d
      | . + {kind: (
          if $l.target == " " then "benign"
          elif $l.target == "D" then "deletion"
          elif $l.live == " " then
            (if ($l.path | sensitive_path) then "sensitive"
             elif $l.target == "R" then "run-script" else "source-driven" end)
          elif ($mtargets | index($l.path)) != null then
            (if $mkind == "managed-conflict" then "managed-review" else $mkind end)
          elif ([($p.managed_json // [])[].target] | index($l.path)) != null then "stale-live-edit"
          elif ($keyorder | index($l.path)) != null then "json-key-order"
          elif ($published | index("\($r.host)\t\($l.path)")) != null then "published"
          elif $d == null then "live-edit"
          elif $d.decision == "capture" then
            (if $d.origin == $r.host then "capture" else "captured-elsewhere" end)
          elif $d.decision == "source-newer" then "stale-live-edit"
          elif $d.decision == "competing" then "competing-edit"
          elif $d.decision == "stale-base" then "stale-base"
          else "capture-manual" end)}
    ] as $lines
  | [
      ( $p.umask.allows_group_or_other_write // false | select(.)
        | reason("umask"; "effective chezmoi umask \($p.umask.chezmoi_octal) permits group/other write; set `umask = 0o022` in this host's chezmoi config")),
      ( $p.sensitive_without_private // [] | .[]
        | reason("sensitive-permissions"; "\(.target): source \(.source_name), live mode \(.live_mode); use a private_ source name")),
      ( $p.scheduled_source_writers // [] | .[]
        | reason("scheduled-source-writer"; "\(.kind) \(.label) edits the source tree (\(.flags | join(", "))); scheduled jobs should only report")),
      ( $keyorder[] | reason("json-key-order"; "\(.): only key order differs; manage it with a modify_ template that returns .chezmoi.stdin unchanged when nothing managed changed")),
      ( $p.externals // [] | .[] | select(.fetch == "failed")
        | reason("external-fetch-failed"; .path)),
      ( $p.externals // [] | .[] | select(.state == "behind")
        | reason("external-behind"; "\(.path): \(.behind) upstream commit(s) not pulled; the next sealed apply fast-forwards it once its refreshPeriod elapses")),
      ( if (($p.source.dirty // []) | sort) as $dd | ($dd | length) > 0 and any($repeated_dirty[]; . == $dd) then
          reason("repeated-source-drift"; "same uncommitted paths on several hosts: \($p.source.dirty | join(", "))")
        else empty end ),
      ( if ($upstream_views | length) > 1 and ($p.source.upstream_head // "") != "" then
          reason("upstream-views-differ"; "hosts see different upstream commits (this one: \($p.source.upstream_head[0:12])); probe with fetch")
        else empty end ),
      ( ($p.plugins // {}) | to_entries[] | .key as $harness | .value as $h
        | ($plugin_baseline[$harness]) as $base
        | ( ($h.declared_marketplaces - ($h.registered_marketplaces // [])) | select(length > 0 and $h.registered_marketplaces != null)
            | reason("plugin-marketplace-unregistered"; "\($harness): declared but not registered: \(join(", ")); Roundhouse fleet-run registers it from the declared source") ),
          # Claude's enabledPlugins is the synced declaration; Codex config also
          # carries stale stanzas, so Codex is judged against the rest of the fleet.
          ( select($harness == "claude") | ($h.enabled - (($h.installed // {}) | keys) | scoped($base.scope))
            | select(length > 0 and $h.installed != null)
            | reason("plugin-not-installed"; "\($harness): enabled but not installed: \(join(", "))") ),
          ( [ $base.installed | keys[] ] - (($h.installed // {}) | keys) | scoped($base.scope)
            | select(length > 0 and $h.installed != null)
            | reason("plugin-missing"; "\($harness): installed elsewhere in the fleet, missing here: \(map(. + " (" + ($base.installed[.].hosts | join(", ")) + ")") | join(", "))") ),
          ( [ ($h.installed // {}) | to_entries[] | .key as $id | .value.version as $v
              | ($base.installed[$id].newest // null) as $n
              | select($n != null and $v != null and ($v | vkey) < ($n.version | vkey) and ([$id] | scoped($base.scope) | length) > 0)
              | "\($id) \($v) (newest \($n.version) on \($n.host))" ]
            | select(length > 0)
            | reason("plugin-version-drift"; "\($harness): \(join(", "))") ) )
    ] as $findings
  | [
      ( if ($p.login_shell.missing_tools // []) | length > 0 then
          reason("login-shell-tools-missing"; "not on PATH \(if $r.transport == "local" then "in the controller's environment" else "under the host's login shell" end): \($p.login_shell.missing_tools | join(", "))")
        else empty end ),
      ( if $p.source.state == "not_git" then reason("source-not-git"; $p.source.path) else empty end ),
      ( if ($p.source.upstream // "") == "" and $p.source.state == "git" then reason("source-no-upstream"; $p.source.path) else empty end ),
      ( if $p.source.fetch == "failed" then reason("source-fetch-failed"; "upstream state unknown") else empty end ),
      ( if ($p.source.dirty_count // 0) > 0 then
          reason("source-dirty"; "\($p.source.dirty_count) uncommitted: \($p.source.dirty | join(", "))")
        else empty end ),
      ( if ($p.source.ahead // 0) > 0 then
          reason("source-ahead"; "\($p.source.ahead) local commit(s) not on \($p.source.upstream); push them")
        else empty end ),
      ( if $p.status.ok == false then reason("status-failed"; "chezmoi status failed") else empty end ),
      ( if $p.status.truncated // false then reason("status-too-large"; "\($p.status.count) entries") else empty end ),
      ( $p.externals // [] | .[] | select(.state == "rewritten-resettable")
        | reason("external-rewritten"; "\(.path): upstream rewrote history; clone has no local files and every commit came from upstream, so a sealed reset to \(.upstream_head[0:12]) is safe")),
      ( $p.externals // [] | .[] | select(.state == "rewritten-local-changes" or .state == "dirty")
        | reason("external-local-changes"; "\(.path): \(.state); stop, do not reset"))
    ] as $blockers
  | ($lines | map(select(.kind | IN("live-edit","json-key-order","deletion","sensitive",
      "stale-live-edit","competing-edit","capture-manual","stale-base","managed-review")))) as $conflicts
  # A managed-settings edit can exist with no status line at all (an added map
  # entry survives the merge), so the host's own edits decide too.
  | ([ $medits[] | select(.decision != "capture") | .target ] | unique) as $mconflict_targets
  | (($conflicts | map(.path)) + $mconflict_targets | unique) as $conflict_paths
  | ([ $medits[] | select(.decision == "capture" and .origin == $r.host) ]) as $mcaptures
  | {
      host: $r.host,
      transport: $r.transport,
      class: (
        if $r.transport == "codex-remote-control" or $r.transport == "windows" then "unsupported"
        elif $r.probe == null or ($p.error // null) != null then "unreachable"
        elif $r.expected != null and ($r.expected.hostname != $p.identity.hostname or $r.expected.user != $p.identity.user) then "identity-mismatch"
        elif ($blockers | length) > 0 or ($conflict_paths | length) > 0 then "review"
        elif any($lines[]; .kind == "capture") or ($mcaptures | length) > 0 then "capture"
        elif ($p.source.behind // 0) > 0 then "pull"
        elif any($lines[]; .kind == "captured-elsewhere" or .kind == "published")
          or any($medits[]; .decision == "capture") then "awaiting-capture"
        elif ($lines | map(select(.kind != "benign")) | length) == 0 then "in-sync"
        else "apply" end),
      error: ($r.error // $p.error // null),
      identity: ($p.identity // null),
      source: (if $p.source then $p.source | {head,upstream_head,ahead,behind,dirty_count} else null end),
      status_digest: ($p.status.digest // null),
      diff_digest: ($p.status.diff_digest // null),
      pending: ($lines | group_by(.kind) | map({key:.[0].kind,value:(map(.path))}) | from_entries),
      captures: ([ $lines[] | select(.kind == "capture" and (.path as $pp | $mtargets | index($pp)) == null)
        | .path as $path | $decisions[$path]
        | {type: "file", path: $path, source, digest, mtime} ]
        + ($mcaptures | group_by(.target) | map({type: "json", path: .[0].target, source: .[0].source,
            mtime: .[0].mtime, entries: map({path: .entry, state, digest})}))),
      decisions: ([ $lines[] | select(.kind | IN("stale-live-edit","competing-edit","capture-manual","stale-base","captured-elsewhere"))
        | select((.path as $pp | $mtargets | index($pp)) == null)
        | .path as $path | $decisions[$path] + {path: $path} ]
        + [ $medits[] | . + {path: "\(.target) \(.entry | join("."))"} ])
        | map(.
        | . + {summary: (
            if .decision == "source-newer" then "upstream changed \(.source) at \(when(.source_time)), after this edit at \(when(.mtime)); overwriting it needs the owner"
            elif .decision == "competing" then "different edits on \(.hosts | join(", ")); newest is \(.origin) at \(when(.mtime)); a person decides"
            elif .decision == "capture-manual" and .kind == "managed-json" then "\(.origin) changed it at \(when(.mtime)); this key is reviewed by hand before it is published"
            elif .decision == "capture-manual" then "\(.origin) changed it at \(when(.mtime)); \(.source) is a \(.kind) source, so edit it by hand"
            elif .decision == "stale-base" then "\(.origin) changed it at \(when(.mtime)) without the newer upstream change to \(.source); pull there, then reconcile"
            else "\(.origin) publishes this change (edited at \(when(.mtime)))" end)}),
      conflicts: $conflict_paths,
      blockers: $blockers,
      findings: $findings
    }
)
