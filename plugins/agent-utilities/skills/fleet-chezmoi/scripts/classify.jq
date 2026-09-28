# fleet-chezmoi classifier. Input: an array of probe records
#   {host, transport, gold, expected:{hostname,user}|null, probe:{...}|null, error:string|null}
# Output: an array of per-host decisions, one per input record, in input order.
#
# Classes:
#   unreachable        probe did not return a usable record
#   unsupported        transport has no fast path (native Windows uses remote control)
#   identity-mismatch  hostname/user differ from the configured expectation: stop
#   in-sync            source equals upstream and chezmoi status is empty
#   pull               clean source strictly behind upstream: seal a ff-only pull
#   apply              every pending entry is source-driven: seal a full apply
#                      bound to the exact status digest
#   review             anything else: reconcile the listed paths/reasons only
#
# A status line is `XY path`. X compares chezmoi's last-written state with the
# live file (X != " " means the live file changed since chezmoi last wrote it).
# Y compares live with the target (what apply would do: A, M, D, R).

def sensitive_path:
  test("^(\\.ssh|\\.gnupg|\\.aws|\\.kube|\\.docker|\\.config/gh|\\.config/op|\\.password-store)(/|$)")
  or test("^(\\.netrc|\\.pgpass)$")
  or test("(^|/)(id_[A-Za-z0-9_-]+|[^/]*\\.(pem|key|p12|pfx))$")
  or test("(?i)(^|/)[^/]*(credential|secret|token|auth)[^/]*$");

def line_kind($keyorder):
  if .target == " " then "benign"
  elif .target == "D" then "deletion"
  elif (.path | sensitive_path) then "sensitive"
  elif .live == " " then (if .target == "R" then "run-script" else "source-driven" end)
  elif (.path as $p | $keyorder | index($p)) != null then "json-key-order"
  else "live-edit"
  end;

def reason($code; $detail): {code:$code,detail:$detail};

# Keep plugin IDs (NAME@MARKETPLACE) whose marketplace is in $scope.
def scoped($scope): map(select((split("@") | last) as $m | $scope | index($m) != null));

# Source trees that carry the same uncommitted paths on several hosts point at a
# scheduled writer (for example a drift-adoption agent), not at a person.
(map(select((.probe.source.dirty_count // 0) > 0) | .probe.source.dirty | sort)
  | group_by(.) | map(select(length > 1) | .[0])) as $repeated_dirty
| (map(select(.gold and .probe != null) | .probe.source.head) | first // null) as $gold_head
| (map(select(.gold and .probe != null) | .probe.plugins // {}) | first // {}) as $gold_plugins
# Compare only plugins from marketplaces the gold host declares for that same
# harness; account-synced and runtime-bundled plugins differ by host on purpose.

| map(
  . as $r
  | ($r.probe // {}) as $p
  | ($p.status.json_key_order_only // []) as $keyorder
  | [($p.status.lines // [])[] | . + {kind:line_kind($keyorder)}] as $lines
  | [
      ( $p.umask.allows_group_or_other_write // false | select(.)
        | reason("umask"; "effective chezmoi umask \($p.umask.chezmoi_octal) permits group/other write; set `umask = 0o022` in this host's chezmoi config")),
      ( $p.sensitive_without_private // [] | .[]
        | reason("sensitive-permissions"; "\(.target): source \(.source_name), live mode \(.live_mode); use a private_ source name")),
      ( $p.scheduled_source_writers // [] | .[]
        | reason("scheduled-source-writer"; "\(.kind) \(.label) edits the source tree (\(.flags | join(", "))); keep non-gold hosts report-only")),
      ( $keyorder[] | reason("json-key-order"; "\(.): only key order differs; manage it with a modify_ template that returns .chezmoi.stdin unchanged when nothing managed changed")),
      ( $p.externals // [] | .[] | select(.fetch == "failed")
        | reason("external-fetch-failed"; .path)),
      ( $p.externals // [] | .[] | select(.state == "behind")
        | reason("external-behind"; "\(.path): \(.behind) upstream commit(s) not pulled; the next sealed apply fast-forwards it once its refreshPeriod elapses")),
      ( if (($p.source.dirty // []) | sort) as $d | ($d | length) > 0 and any($repeated_dirty[]; . == $d) then
          reason("repeated-source-drift"; "same uncommitted paths on several hosts: \($p.source.dirty | join(", "))")
        else empty end ),
      ( ($p.plugins // {}) | to_entries[] | .key as $harness | .value as $h
        | ($gold_plugins[$harness].declared_marketplaces // []) as $scope
        | ( ($h.declared_marketplaces - ($h.registered_marketplaces // [])) | select(length > 0 and $h.registered_marketplaces != null)
            | reason("plugin-marketplace-unregistered"; "\($harness): declared but not registered: \(join(", ")); register and update before applying (plugin commands rewrite the harness settings)") ),
          # Claude's enabledPlugins is the synced declaration; Codex config also
          # carries stale stanzas, so Codex is judged against the gold instead.
          ( select($harness == "claude") | ($h.enabled - (($h.installed // {}) | keys) | scoped($scope))
            | select(length > 0 and $h.installed != null)
            | reason("plugin-not-installed"; "\($harness): enabled but not installed: \(join(", "))") ),
          ( [ ($gold_plugins[$harness].installed // {}) | to_entries[] | select(.value.enabled == true) | .key ]
            - (($h.installed // {}) | keys) | scoped($scope)
            | select(length > 0 and $h.installed != null and ($r.gold | not))
            | reason("plugin-missing-vs-gold"; "\($harness): installed on the gold host, missing here: \(join(", "))") ),
          ( [ ($h.installed // {}) | to_entries[] | .key as $id | .value.version as $v
              | ($gold_plugins[$harness].installed[$id].version // null) as $g
              | select($g != null and $v != null and $g != $v and ([$id] | scoped($scope) | length) > 0)
              | "\($id) \($v) (gold \($g))" ]
            | select(length > 0 and ($r.gold | not))
            | reason("plugin-version-drift"; "\($harness): \(join(", "))") ) ),
      ( if $gold_head != null and ($r.gold | not) and $p.source.upstream_head != null
          and $p.source.upstream_head != "" and $p.source.upstream_head != $gold_head then
          reason("upstream-differs-from-gold"; "this host sees upstream at \($p.source.upstream_head[0:12]) but gold HEAD is \($gold_head[0:12]): publish from the gold host, or probe with fetch")
        else empty end )
    ] as $findings
  | [
      ( if ($p.login_shell.missing_tools // []) | length > 0 then
          reason("login-shell-tools-missing"; "not on PATH under the login shell: \($p.login_shell.missing_tools | join(", "))")
        else empty end ),
      ( if $p.source.state == "not_git" then reason("source-not-git"; $p.source.path) else empty end ),
      ( if ($p.source.upstream // "") == "" and $p.source.state == "git" then reason("source-no-upstream"; $p.source.path) else empty end ),
      ( if $p.source.fetch == "failed" then reason("source-fetch-failed"; "upstream state unknown") else empty end ),
      ( if ($p.source.dirty_count // 0) > 0 then
          reason(if $r.gold then "gold-source-dirty" else "source-dirty" end;
            "\($p.source.dirty_count) uncommitted: \($p.source.dirty | join(", "))")
        else empty end ),
      ( if ($p.source.ahead // 0) > 0 then
          reason(if $r.gold then "gold-unpublished" else "source-ahead" end;
            "\($p.source.ahead) local commit(s) not on \($p.source.upstream)")
        else empty end ),
      ( if $p.status.ok == false then reason("status-failed"; "chezmoi status failed") else empty end ),
      ( if $p.status.truncated // false then reason("status-too-large"; "\($p.status.count) entries") else empty end ),
      ( $p.externals // [] | .[] | select(.state == "rewritten-resettable")
        | reason("external-rewritten"; "\(.path): upstream rewrote history; clone is clean and every local commit came from upstream, so a sealed reset to \(.upstream_head[0:12]) is safe")),
      ( $p.externals // [] | .[] | select(.state == "rewritten-local-changes" or .state == "dirty")
        | reason("external-local-changes"; "\(.path): \(.state); stop, do not reset")),
      ( if $r.gold and ($lines | map(select(.kind != "benign")) | length) > 0 then
          reason("gold-pending-apply"; "the gold host's live state is authoritative; recapture or review before applying: \($lines | map(select(.kind != "benign") | .path) | join(", "))")
        else empty end )
    ] as $blockers
  # chezmoi prompts before overwriting any file edited since its last write, so
  # semantically equal JSON with a live edit cannot take a non-interactive apply.
  | ($lines | map(select(.kind | IN("live-edit","json-key-order","deletion","sensitive")))) as $conflicts
  | {
      host: $r.host,
      transport: $r.transport,
      gold: ($r.gold // false),
      class: (
        if $r.transport == "codex-remote-control" or $r.transport == "windows" then "unsupported"
        elif $r.probe == null or ($p.error // null) != null then "unreachable"
        elif $r.expected != null and ($r.expected.hostname != $p.identity.hostname or $r.expected.user != $p.identity.user) then "identity-mismatch"
        elif ($blockers | length) > 0 then "review"
        elif ($p.source.behind // 0) > 0 then "pull"
        elif ($lines | length) == 0 then "in-sync"
        elif ($conflicts | length) == 0 then "apply"
        else "review" end),
      error: ($r.error // $p.error // null),
      identity: ($p.identity // null),
      source: (if $p.source then $p.source | {head,upstream_head,ahead,behind,dirty_count} else null end),
      status_digest: ($p.status.digest // null),
      diff_digest: ($p.status.diff_digest // null),
      pending: ($lines | group_by(.kind) | map({key:.[0].kind,value:(map(.path))}) | from_entries),
      conflicts: ($conflicts | map(.path)),
      blockers: $blockers,
      findings: $findings
    }
)
