---
name: fleet-chezmoi
description: Inspect, compare, and deliberately reconcile chezmoi source and live-state drift across configured machines. Use for chezmoi status, diff, pull, add, apply, source-repository drift, or post-apply verification.
---

# Fleet Chezmoi

Set `SKILL_DIR` to the absolute directory containing this `SKILL.md` and
`FC="$SKILL_DIR/scripts/fleet-chezmoi"`; the shell working directory is not
the skill directory. Probing needs `chezmoi`, `git`, `jq`, and SSH. Mutating
another host needs the Roundhouse CLI (`ROUNDHOUSE_CLI`, default
`roundhouse`); without it, mutate only the local host.

## Invariants

- Never print or bundle secret values. The scripts emit paths, status codes,
  commit IDs, and digests; never paste `chezmoi diff`/`cat`/`dump-config`,
  `.chezmoidata*`, or rendered files. Backups stay on their host.
- Mutate a host only after Roundhouse verifies its configured hostname/user,
  and only after backing up its pending files and rendered diff.
- No blanket `chezmoi add`, no newest-wins: timestamps are evidence only.
- No force-reset, `apply --force`, auto-commit, or auto-push of user drift.
- Remote mutation runs only as a sealed Roundhouse plan with exact argv; its
  executor rechecks the sealed preconditions immediately before mutating.
- Targeted applies name 1-16 absolute paths under the target's home, with no
  flags or traversal.
- Never ask for or relay a sudo or Administrator password.
- Native Windows uses Codex remote control only; never fall back to WSL.

## Fast path

1. `"$FC" probe --gold GOLD HOST...` — one read-only batch per host, in
   parallel, under each login shell. Add `--plugins` to compare Claude/Codex
   plugin registration and versions against the gold; `--require TOOL` for
   tools run scripts need.
2. Act on each host's class:
   - `in-sync`: nothing to do.
   - `pull`: clean source strictly behind upstream. `"$FC" seal RUN pull`,
     then `"$FC" apply RUN SET-ID`; no live file changes, so the sync request
     covers it. Apply re-probes those hosts.
   - `apply`: every pending entry is source-driven. `"$FC" seal RUN apply`,
     show the user the per-host list and set ID, get one approval, then
     `"$FC" apply RUN SET-ID`.
   - `review`: only these hosts, and only their listed paths and blockers,
     follow [reconcile](references/reconcile.md).
   - `identity-mismatch`, `unreachable`: stop for that host and report.
   - `unsupported`: see Windows below.
3. Report the final table and every finding. `in-sync`, `pull`, and `apply`
   hosts need no evidence table.

The classifier allows `apply` only when every `chezmoi status` line shows no
live edit since chezmoi last wrote it (first column blank), and none is a
deletion or sensitive path. Seal requires
Roundhouse's own inventory to match the probed HEAD and status digest; the
backup step and the executor each recheck that digest before mutating. See
[reconcile](references/reconcile.md#why-the-fast-path-is-safe).

## Gold host

The gold host's live state is authoritative. `gold-pending-apply` means its
source disagrees with its live files (a stale capture or a foreign commit):
recapture or review, never apply over it. Publishing from the gold is the
user's reviewed commit and push. Live wins elsewhere only by capturing into the
gold's source first ([live wins](references/reconcile.md#live-wins)).

## Blockers and findings

Blockers force `review`; findings only report. Every code's cause and fix is
in [failure modes](references/failure-modes.md).

## Windows and privileged lanes

Load these only when such a target is in scope. A native Windows target on
`codex-remote-control` follows
[Codex remote control](references/codex-remote-control.md); Claude reports it
unsupported. Protected broker, SFTP, S4U profile-bundle, and privilege
lifecycle work follows [privileged lanes](references/privileged-lanes.md).

## Verify

`apply` ends with a fresh probe of every host it touched: expect `in-sync`.
Also check auth/tool health the change could affect.
