#!/usr/bin/env bash
# fleet-chezmoi self-test. Builds a throwaway HOME with a real chezmoi source,
# a bare origin, and a stub Roundhouse CLI, then drives probe/classify/seal/apply
# through the safe path and every classified failure mode. Prints PASS.
set -euo pipefail

here=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
command -v chezmoi >/dev/null || { echo "SKIP: chezmoi not installed"; exit 0; }
command -v jq >/dev/null || { echo "FAIL: jq required"; exit 1; }

T=$(mktemp -d "${TMPDIR:-/tmp}/fleet-chezmoi-test.XXXXXX")
trap 'rm -rf "$T"' EXIT
export HOME=$T/home XDG_CONFIG_HOME=$T/home/.config XDG_STATE_HOME=$T/home/.local/state
unset XDG_DATA_HOME XDG_CACHE_HOME CHEZMOI_SOURCE_DIR
export GIT_CONFIG_GLOBAL=$T/gitconfig GIT_CONFIG_NOSYSTEM=1
git config --global user.name test
git config --global user.email test@example.invalid
git config --global init.defaultBranch main
git config --global protocol.file.allow always
mkdir -p "$HOME/.config/chezmoi"
: >"$HOME/.config/chezmoi/chezmoi.toml"

SECRET=S3CR3T-canary-7f1e
fc=$here/fleet-chezmoi
src=$HOME/.local/share/chezmoi
fails=0
fail() { printf 'FAIL: %s\n' "$*"; fails=$((fails + 1)); }
check() {
  local what=$1 negate=false
  shift
  if [ "$1" = '!' ]; then negate=true; shift; fi
  if "$@"; then [ "$negate" = false ] || fail "$what"; else [ "$negate" = true ] || fail "$what"; fi
}
class_of() { jq -r --arg h "$2" '.[] | select(.host == $h) | .class' "$1/classes.json"; }
field() { jq -r --arg h "$2" ".[] | select(.host == \$h) | $3" "$1/classes.json"; }
no_secret() { ! grep -rq -- "$SECRET" "$1"; }

# --- origin, gold working copy, and the host's source -------------------------
git init -q --bare "$T/origin.git"
git clone -q "$T/origin.git" "$T/gold" 2>/dev/null
printf 'a\n' >"$T/gold/dot_a"
printf 'b\n' >"$T/gold/dot_b"
printf '{"x":1,"y":2}\n' >"$T/gold/dot_j.json"
printf 'secret = "%s"\n' "$SECRET" >"$T/gold/.chezmoidata.toml"
printf 'token={{ .secret }}\nv1\n' >"$T/gold/dot_greeting.tmpl"
git -C "$T/gold" add -A && git -C "$T/gold" commit -qm init && git -C "$T/gold" push -q origin main
git clone -q "$T/origin.git" "$src"
chezmoi apply --no-tty

host=$(hostname 2>/dev/null || uname -n)
user=$(id -un)
jq -n --arg host "$host" --arg user "$user" '{version:1,machines:{
  h1:{platform:"linux",transport:"local",expected_hostname:$host,expected_user:$user},
  h3:{platform:"linux",transport:"local",expected_hostname:"not-this-host",expected_user:$user},
  win:{platform:"windows",transport:"codex-remote-control"}}}' >"$T/rh.json"
chmod 600 "$T/rh.json"
export ROUNDHOUSE_CONFIG=$T/rh.json

run=$T/run
probe() { "$fc" probe --run "$run" "$@" >"$T/probe.out" 2>&1 || { cat "$T/probe.out"; fail "probe exited nonzero"; }; }

# 1. in sync
probe h1
check "clean host is in-sync" [ "$(class_of "$run" h1)" = in-sync ]

# 2. identity mismatch and unsupported transport
probe h1 h3 win
check "wrong hostname is identity-mismatch" [ "$(class_of "$run" h3)" = identity-mismatch ]
check "native Windows has no fast path" [ "$(class_of "$run" win)" = unsupported ]

# 3. upstream advanced: pull
printf 'b2\n' >"$T/gold/dot_b"
printf 'token={{ .secret }}\nv2\n' >"$T/gold/dot_greeting.tmpl"
git -C "$T/gold" commit -qam change && git -C "$T/gold" push -q origin main
probe h1
check "behind clean source is pull" [ "$(class_of "$run" h1)" = pull ]
check "pull reports one commit behind" [ "$(field "$run" h1 .source.behind)" = 1 ]

# 4. stub Roundhouse: collect/seal/apply with the real sandbox state
mkdir -p "$T/bin"
cat >"$T/bin/roundhouse" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
log=$STUB_LOG
case $1 in
  collect)
    target=$3
    src=$(chezmoi source-path)
    head=$(git -C "$src" rev-parse HEAD)
    dirty=$(git -C "$src" status --porcelain | wc -l | tr -d ' ')
    chezmoi status >"$STUB_DIR/status"
    digest=$( (sha256sum 2>/dev/null || shasum -a 256) <"$STUB_DIR/status" | cut -d ' ' -f 1)
    out=${@: -1}
    externals=$(sh "$STUB_PROBE" --no-fetch | jq -c '.externals')
    jq -cn --arg t "$target" --arg head "$head" --argjson dirty "$dirty" --arg d "$digest" \
      --argjson externals "$externals" '
      {host_id:$t,kind:"file",id:"chezmoi:source",status:"present",data:{head:$head,dirty_count:$dirty}},
      {host_id:$t,kind:"chezmoi_state",id:"live",status:"present",data:{status_digest:{value:$d}}},
      ($externals[] | {host_id:$t,kind:"chezmoi_external",id:.path,status:"present",data:.})' >"$out"
    printf 'collect %s\n' "$target" >>"$log"
    ;;
  seal-plan)
    body=$(jq -cS --slurpfile s "$3" '{schema:"roundhouse.plan",target,domain,operations,
      bound:[$s[] | {kind,id,data}]}' "$2")
    digest=$(printf '%s' "$body" | jq -cS . | (sha256sum 2>/dev/null || shasum -a 256) | cut -d ' ' -f 1)
    jq -n --argjson b "$body" --arg d "$digest" '$b + {plan_id:("plan-" + $d[0:16]),plan_digest:{algorithm:"sha256",value:$d}}' >"$4"
    printf 'seal %s\n' "$(jq -r .target "$2")" >>"$log"
    ;;
  apply-plan)
    plan=$2 id=$3 out=$4
    [ "$(jq -r .plan_id "$plan")" = "$id" ] || { echo "stub: wrong plan id" >&2; exit 64; }
    printf 'apply %s %s backups=%s\n' "$(jq -r .target "$plan")" "$id" \
      "$(ls "$XDG_STATE_HOME/fleet-chezmoi/backups" 2>/dev/null | wc -l | tr -d ' ')" >>"$log"
    # The real executor rechecks the sealed preconditions here; so does the stub.
    src=$(chezmoi source-path)
    while IFS= read -r op; do
      case $(jq -r .type <<<"$op") in
        chezmoi-pull) chezmoi git -- pull --ff-only -q ;;
        chezmoi-apply)
          if jq -e 'has("targets")' <<<"$op" >/dev/null; then
            mapfile -t targets < <(jq -r '.targets[]' <<<"$op")
            chezmoi status -- "${targets[@]}" >"$STUB_DIR/status"
            digest=$( (sha256sum 2>/dev/null || shasum -a 256) <"$STUB_DIR/status" | cut -d ' ' -f 1)
            [ "$digest" = "$(jq -r .status_digest <<<"$op")" ] || { echo "stub: targets changed" >&2; exit 65; }
            chezmoi --no-tty apply -- "${targets[@]}"
            continue
          fi
          chezmoi status >"$STUB_DIR/status"
          digest=$( (sha256sum 2>/dev/null || shasum -a 256) <"$STUB_DIR/status" | cut -d ' ' -f 1)
          jq -e --arg d "$digest" 'any(.bound[]; .kind == "chezmoi_state" and .data.status_digest.value == $d)' \
            "$plan" >/dev/null || { echo "stub: precondition changed" >&2; exit 65; }
          chezmoi --no-tty apply ;;
        chezmoi-external-reset)
          path=$(jq -r .id <<<"$op") head=$(jq -r .upstream_head <<<"$op") sealed=$(jq -r .head <<<"$op")
          [ -z "$(git -C "$path" status --porcelain --ignored)" ] && [ "$(git -C "$path" rev-parse '@{u}')" = "$head" ] &&
            [ "$(git -C "$path" rev-parse HEAD)" = "$sealed" ] ||
            { echo "stub: external changed" >&2; exit 65; }
          git -C "$path" reset --hard --quiet "$head" ;;
      esac
    done < <(jq -c '.operations[]' "$plan")
    jq -cn --arg id "$id" '{kind:"operation",id:("apply:" + $id),status:"present"}' >"$out"
    ;;
  *) echo "stub: unsupported $1" >&2; exit 64 ;;
esac
STUB
chmod +x "$T/bin/roundhouse"
mkdir -p "$T/stub"
export ROUNDHOUSE_CLI=$T/bin/roundhouse STUB_LOG=$T/stub.log STUB_DIR=$T/stub STUB_PROBE=$here/probe.sh
: >"$STUB_LOG"

"$fc" seal "$run" pull >"$T/seal.out"
set_id=$(awk 'END {print $1}' "$T/seal.out")
[ -z "${DEBUG:-}" ] || { cat "$T/seal.out"; cat "$run"/logs/*.seal.log 2>/dev/null; }
check "seal prints a set ID" grep -Eq '^set-[0-9a-f]{16}$' <<<"$set_id"
if "$fc" apply "$run" set-0000000000000000 >/dev/null 2>&1; then fail "apply accepted an unknown set ID"; fi
cp "$run/sets/pull/plans/h1.json" "$T/plan.bak"
jq '.operations[0].argv += ["--rebase"]' "$T/plan.bak" >"$run/sets/pull/plans/h1.json"
if "$fc" apply "$run" "$set_id" >/dev/null 2>&1; then fail "apply accepted a tampered plan"; fi
cp "$T/plan.bak" "$run/sets/pull/plans/h1.json"
check "tampered plan never reached the executor" ! grep -q '^apply' "$STUB_LOG"
"$fc" apply "$run" "$set_id" >"$T/apply.out"
[ -z "${DEBUG:-}" ] || { cat "$T/apply.out" "$STUB_LOG"; cat "$run"/logs/*; }
check "pull set applied" grep -q "^apply h1 $(jq -r .plan_id "$run/sets/pull/plans/h1.json")" "$STUB_LOG"
check "post-pull reprobe classifies apply" [ "$(class_of "$run" h1)" = apply ]
check "source-driven entries are listed" [ "$(field "$run" h1 '.pending["source-driven"] | sort | join(",")')" = ".b,.greeting" ]
check "no secret in probe output or run records" no_secret "$run"

# 5. race: a live edit after sealing must stop that host before it mutates
"$fc" seal "$run" apply >"$T/seal.out"
set_id=$(awk 'END {print $1}' "$T/seal.out")
[ -z "${DEBUG:-}" ] || { cat "$T/seal.out"; cat "$run"/logs/*.seal.log 2>/dev/null; }
printf 'edited-after-seal\n' >"$HOME/.b"
if "$fc" apply "$run" "$set_id" >"$T/apply.out" 2>&1; then fail "apply exited 0 with a skipped host"; fi
check "changed live state is skipped" grep -q 'skipped' "$T/apply.out"
check "live edit survived" grep -q edited-after-seal "$HOME/.b"
check "skipped host never reached the executor" [ "$(grep -c '^apply' "$STUB_LOG")" = 1 ]
check "live edit is now a review conflict" [ "$(field "$run" h1 '.conflicts | join(",")')" = .b ]
"$fc" evidence "$run" h1 >"$T/evidence.out"
check "evidence covers the conflict" [ "$(jq -r '.targets[0] | [.target, .kind, (.rendered_sha256 != .live_sha256)] | join(",")' "$run/evidence/h1.json")" = ".b,plain,true" ]
check "evidence records source history" [ "$(jq -r '.targets[0].history[0].subject' "$run/evidence/h1.json")" = change ]
if "$fc" evidence "$run" h1 ../etc/passwd >/dev/null 2>&1; then fail "evidence accepted a traversal target"; fi
check "refused evidence kept the prior record" [ "$(jq -r '.targets[0].target' "$run/evidence/h1.json")" = .b ]
check "no secret in evidence" no_secret "$run"
# A sealed plan never overwrites a live edit: that needs the owner.
"$fc" seal "$run" targets h1 >"$T/seal.out" 2>&1 || true
[ -z "${DEBUG:-}" ] || { cat "$T/seal.out"; jq -c ".targets[]|{target,status}" "$run/evidence/h1.json"; }
check "targeted seal refuses a live-edited path" grep -q "live-edited targets need the owner" "$T/seal.out"
chezmoi apply --no-tty --force -- "$HOME/.b"   # test-only reset of the sandbox

# 6. safe apply: backup precedes the executor, then the host is in sync
probe h1
"$fc" seal "$run" apply >"$T/seal.out"
set_id=$(awk 'END {print $1}' "$T/seal.out")
[ -z "${DEBUG:-}" ] || { cat "$T/seal.out"; cat "$run"/logs/*.seal.log 2>/dev/null; }
"$fc" apply "$run" "$set_id" >"$T/apply.out"
check "apply ran after exactly one backup" grep -q '^apply h1 plan-[0-9a-f]* backups=1' "$STUB_LOG"
check "host converged" [ "$(class_of "$run" h1)" = in-sync ]
backup_dir=$(jq -r '.backup_dir' "$run/sets/apply/results/h1.backup.json")
check "backup is private" [ "$(stat -c %a "$backup_dir" 2>/dev/null || stat -f %Lp "$backup_dir")" = 700 ]
check "backup archived the pending file" grep -qx ./.greeting <(tar -tf "$backup_dir/files.tar")
check "no secret in apply output or run records" no_secret "$run"
check "no secret on stdout" no_secret "$T/apply.out"

# 6b. targeted source-driven apply of an evidenced path, backed up first
printf 'a2\n' >"$T/gold/dot_a"
git -C "$T/gold" commit -qam a2 && git -C "$T/gold" push -q origin main
chezmoi git -- pull -q --ff-only
probe h1
"$fc" evidence "$run" h1 .a >/dev/null
"$fc" seal "$run" targets h1 >"$T/seal.out"
set_id=$(awk 'END {print $1}' "$T/seal.out")
dest=$(jq -r .dest "$run/evidence/h1.json")
check "evidence destination is this HOME" [ "$(cd "$dest" && pwd -P)" = "$(cd "$HOME" && pwd -P)" ]
check "targeted plan names the exact absolute path" \
  [ "$(jq -r '.hosts[0].targets | join(",")' "$run/sets/targets-h1/set.json")" = "$dest/.a" ]
"$fc" apply "$run" "$set_id" >"$T/apply.out"
check "targeted apply updated the path" [ "$(cat "$HOME/.a")" = a2 ]
tb=$(jq -r '.backup_dir' "$run/sets/targets-h1/results/h1.backup.json")
check "targeted backup kept the prior content" [ "$(cd "$tb" && tar -xOf files.tar ./.a)" = a ]
check "host converged after targeted apply" [ "$(class_of "$run" h1)" = in-sync ]

# 7. JSON key order only is semantically equal: apply with a finding
printf '{"y":2,"x":1}\n' >"$HOME/.j.json"
probe h1
check "key-order-only JSON with a live edit needs review" [ "$(field "$run" h1 '.conflicts | join(",")')" = .j.json ]
"$fc" evidence "$run" h1 >/dev/null
check "evidence shows the JSON is canonically equal" [ "$(jq -r '.targets[0].canonical_json_equal' "$run/evidence/h1.json")" = true ]
check "key-order finding" [ "$(field "$run" h1 '[.findings[].code] | index("json-key-order") != null')" = true ]
chezmoi apply --no-tty --force -- "$HOME/.j.json"

# 8. dirty source, and the same drift on two hosts
printf 'x\n' >"$src/dot_adopted"
probe h1
check "dirty source is review" [ "$(field "$run" h1 '[.blockers[].code] | join(",")')" = source-dirty ]
jq '.host = "h2"' "$run/probes/h1.json" >"$run/probes/h2.json"
"$fc" classify "$run" >/dev/null
check "repeated drift across hosts is reported" \
  [ "$(field "$run" h2 '[.findings[].code] | index("repeated-source-drift") != null')" = true ]
rm -f "$run/probes/h2.json" "$src/dot_adopted"

# 9. umask 002 is reported
(umask 002 && "$fc" probe --run "$run" h1 >/dev/null)
check "group-writable umask is reported" [ "$(field "$run" h1 '[.findings[].code] | index("umask") != null')" = true ]

# 10. git-repo external whose upstream rewrote history
git init -q "$T/up" && printf 'v1\n' >"$T/up/f" && git -C "$T/up" add f && git -C "$T/up" commit -qm one
printf '[".ext"]\n  type = "git-repo"\n  url = "file://%s/up"\n  [".ext".pull]\n    args = ["--ff-only"]\n' "$T" \
  >"$T/gold/.chezmoiexternal.toml"
git -C "$T/gold" add -A && git -C "$T/gold" commit -qm ext && git -C "$T/gold" push -q origin main
chezmoi git -- pull -q --ff-only && chezmoi apply --no-tty >/dev/null 2>&1
git -C "$T/up" commit -q --amend -m rewritten
probe h1
[ -z "${DEBUG:-}" ] || { jq '.[0] | {class,blockers,conflicts,pending}' "$run/classes.json"; jq '.probe.externals' "$run/probes/h1.json"; }
check "rewritten external is detected" [ "$(field "$run" h1 '[.blockers[].code] | join(",")')" = external-rewritten ]
"$fc" seal "$run" reset h1 >"$T/seal.out"
set_id=$(awk 'END {print $1}' "$T/seal.out")
[ -z "${DEBUG:-}" ] || { cat "$T/seal.out"; cat "$run"/logs/*.seal.log 2>/dev/null; }
"$fc" apply "$run" "$set_id" >"$T/apply.out"
check "sealed reset moved the external to upstream" \
  [ "$(git -C "$HOME/.ext" rev-parse HEAD)" = "$(git -C "$T/up" rev-parse HEAD)" ]
check "external is current after reset" [ "$(jq -r '.probe.externals[0].state' "$run/probes/h1.json")" = current ]
git -C "$T/up" commit -q --amend -m rewritten-again
probe h1
check "rewritten again is resettable" [ "$(field "$run" h1 '[.blockers[].code] | join(",")')" = external-rewritten ]
[ -z "${DEBUG:-}" ] || jq ".[0].blockers" "$run/classes.json"
printf 'kept\n' >"$HOME/.ext/local-only" && printf 'local-only\n' >>"$HOME/.ext/.git/info/exclude"
probe h1
check "an ignored local file blocks the reset" [ "$(field "$run" h1 '[.blockers[].code] | join(",")')" = external-local-changes ]
rm -f "$HOME/.ext/local-only"
git -C "$HOME/.ext" -c user.name=t -c user.email=t@example.invalid commit -q --allow-empty -m Fast-forward
probe h1
check "a local Fast-forward-subject commit is not upstream history" \
  [ "$(field "$run" h1 '[.blockers[].code] | join(",")')" = external-local-changes ]
git -C "$HOME/.ext" reset -q --hard HEAD~1
probe h1
printf 'local\n' >"$HOME/.ext/f"
probe h1
check "rewritten external with local changes is not resettable" \
  [ "$(field "$run" h1 '[.blockers[].code] | join(",")')" = external-local-changes ]
git -C "$HOME/.ext" checkout -q -- f && git -C "$HOME/.ext" reset -q --hard '@{u}'

# 11. deletions and sensitive targets need review; loose sensitive dirs are reported
printf '.b\n' >"$T/gold/.chezmoiremove" && git -C "$T/gold" rm -q dot_b
mkdir -p "$T/gold/dot_ssh" && printf 'Host x\n' >"$T/gold/dot_ssh/config"
git -C "$T/gold" add -A && git -C "$T/gold" commit -qm remove && git -C "$T/gold" push -q origin main
chezmoi git -- pull -q --ff-only
probe h1
[ -z "${DEBUG:-}" ] || { jq '.[0] | {class,blockers,conflicts,pending}' "$run/classes.json"; chezmoi status; }
check "deletion and sensitive target are conflicts" \
  [ "$(field "$run" h1 '.conflicts | sort | join(",")')" = ".b,.ssh,.ssh/config" ]
check "review class" [ "$(class_of "$run" h1)" = review ]
printf 'broken {{\n' >"$src/dot_broken.tmpl"
probe h1
check "failed chezmoi status is never in-sync" [ "$(field "$run" h1 '[.blockers[].code] | index("status-failed") != null')" = true ]
rm -f "$src/dot_broken.tmpl"

# 12. gold host: pending changes on the gold are never fast-pathed
"$fc" probe --run "$run" --gold h1 h1 >/dev/null
check "gold pending apply is review" \
  [ "$(field "$run" h1 '[.blockers[].code] | index("gold-pending-apply") != null')" = true ]

# 12b. arguments survive the payload framing: spaces and quotes in a target
mkdir -p "$T/gold/space dir" && printf 'x\n' >"$T/gold/space dir/it's.txt"
git -C "$T/gold" add -A && git -C "$T/gold" commit -qm spaced && git -C "$T/gold" push -q origin main
chezmoi git -- pull -q --ff-only
"$fc" evidence "$run" h1 "space dir/it's.txt" >/dev/null
check "a spaced, quoted target reaches the host intact" \
  [ "$(jq -r '.targets[0] | [.target, .source] | join("|")' "$run/evidence/h1.json")" = "space dir/it's.txt|space dir/it's.txt" ]

# 13. plugin registration against the gold host (classifier only)
jq -n '[
  {host:"gold",transport:"ssh",gold:true,expected:null,error:null,probe:{identity:{},source:{head:"a",upstream_head:"a"},
    status:{ok:true,lines:[]},plugins:{claude:{declared_marketplaces:["mk"],enabled:["p@mk","q@mk"],
      registered_marketplaces:["mk"],installed:{"p@mk":{version:"2",enabled:true},"q@mk":{version:"1",enabled:true},
      "s@synced":{version:"1",enabled:true}}}}}},
  {host:"h",transport:"ssh",gold:false,expected:null,error:null,probe:{identity:{},source:{head:"a",upstream_head:"a"},
    status:{ok:true,lines:[]},plugins:{claude:{declared_marketplaces:["mk"],enabled:["p@mk","q@mk"],
      registered_marketplaces:[],installed:{"p@mk":{version:"1",enabled:true}}}}}}]' |
  jq -f "$here/classify.jq" >"$T/plugins.json"
check "unregistered declared marketplace" [ "$(jq -r '.[1].findings | map(select(.code == "plugin-marketplace-unregistered")) | length' "$T/plugins.json")" = 1 ]
check "enabled but not installed" [ "$(jq -r '.[1].findings[] | select(.code == "plugin-not-installed") | .detail' "$T/plugins.json")" = "claude: enabled but not installed: q@mk" ]
check "version drift against gold, scoped to declared marketplaces" \
  [ "$(jq -r '.[1].findings[] | select(.code == "plugin-version-drift") | .detail' "$T/plugins.json")" = "claude: p@mk 1 (gold 2)" ]
check "account-synced plugins are out of scope" ! grep -q 's@synced' <(jq -r '.[1].findings[].detail' "$T/plugins.json")
check "plugin findings do not block" [ "$(jq -r '.[1].class' "$T/plugins.json")" = in-sync ]

# 14. review fixes: .docker subtree, per-harness plugin scope, behind externals
jq -n '[
  {host:"gold",transport:"ssh",gold:true,expected:null,error:null,probe:{identity:{},source:{head:"a",upstream_head:"a"},
    status:{ok:true,lines:[]},plugins:{claude:{declared_marketplaces:["mk"],enabled:[],registered_marketplaces:["mk"],installed:{}},
      codex:{declared_marketplaces:["cx"],enabled:[],registered_marketplaces:["cx"],installed:{"p@cx":{version:"2",enabled:true}}}}}},
  {host:"h",transport:"ssh",gold:false,expected:null,error:null,probe:{identity:{},source:{head:"a",upstream_head:"a"},
    status:{ok:true,lines:[{live:" ",target:"M",path:".docker/contexts/meta.json"}]},
    externals:[{path:"/x",state:"behind",behind:2,fetch:"ok"}],
    plugins:{codex:{declared_marketplaces:["cx"],enabled:[],registered_marketplaces:["cx"],installed:{"p@cx":{version:"1",enabled:true}}}}}}]' |
  jq -f "$here/classify.jq" >"$T/review-fixes.json"
check "any .docker path is sensitive" [ "$(jq -r '.[1].conflicts | join(",")' "$T/review-fixes.json")" = .docker/contexts/meta.json ]
check "Codex drift is scoped by the gold's Codex marketplaces" \
  [ "$(jq -r '.[1].findings[] | select(.code == "plugin-version-drift") | .detail' "$T/review-fixes.json")" = "codex: p@cx 1 (gold 2)" ]
check "a behind external is reported" [ "$(jq -r '[.[1].findings[].code] | index("external-behind") != null' "$T/review-fixes.json")" = true ]

check "no secret anywhere in run records" no_secret "$run"

if [ "$fails" -eq 0 ]; then echo PASS; else echo "FAILED: $fails"; exit 1; fi
