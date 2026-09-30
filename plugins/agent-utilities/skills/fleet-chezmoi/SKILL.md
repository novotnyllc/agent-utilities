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
- Native Windows work runs as native Windows processes only: over the WSL
  interop lane or Codex remote control, never as WSL-side execution.

## Fast path

No host is special: a change can start on any machine. The probe records, for
every live-edited file, when it changed and what upstream last did to its
source, and the classifier works out per file where each change came from.

1. `"$FC" probe HOST...` — probe every host you sync, in one call: one
   read-only batch per host, in parallel, in the environment its executor uses
   (the login shell for SSH hosts, the controller's own environment for a local
   host). Add `--plugins` to compare Claude/Codex plugin registration and
   versions across the fleet; `--require TOOL` for tools run scripts need.
2. Act on each host's class, in this order:
   - `capture`: this host is where a change was made (its edit is the newest,
     newer than upstream, and every host that has it agrees). Run
     `"$FC" seal RUN capture`, show the user what is captured from where, get
     one approval, then `"$FC" apply RUN SET-ID`. It copies each file from its
     origin into the local source, secret-scans, commits, pushes, and re-probes.
     App-written settings declared in the source's `.fleet-chezmoi.json` (for
     example Claude's `settings.json`) are captured per entry: a changed,
     added, or removed entry is merged into the template from the host that
     changed it, and removals reach every host through the retired list. Only
     a value that looks like a secret is held back and reported by name.
   - `pull`: clean source strictly behind upstream. `"$FC" seal RUN pull`,
     then `"$FC" apply RUN SET-ID`; no live file changes, so the sync request
     covers it.
   - Plugins, after any capture or pull and before sealing `apply`: run
     `"$FC" plugins RUN` (identity-verified hosts only), because plugin
     commands rewrite settings. It runs Roundhouse's plugin convergence now (it
     also runs every 20 minutes), installs any Claude plugin the synced
     settings enable but the host lacks, and re-probes; seal from that state.
   - `apply`: every pending entry is source-driven. `"$FC" seal RUN apply`,
     show the user the per-host list and set ID, get one approval, then
     `"$FC" apply RUN SET-ID`.
   - `awaiting-capture`: the host already has a change that is being
     published; it converges after the capture and a pull.
   - `review`: only these hosts, and only their listed paths, decisions, and
     blockers, follow [reconcile](references/reconcile.md).
   - `in-sync`: nothing to do. `identity-mismatch`, `unreachable`: stop for
     that host and report. `unsupported`: see Windows below.
3. Report the final table, every `decide` line, and every finding.

Why each step is safe, and how origins are decided:
[reconcile](references/reconcile.md).

## Propagating settings

When chezmoi-managed settings must reach every host, they already exist on
some host. Prefer the machine the user is working on as the origin, but only
when the probe classifies it `capture` (its edit starts from current
upstream). Otherwise the origin is whichever host the probe classifies
`capture`, and a disagreement goes to `review`. The origin is never a fixed
host, and not necessarily the source repository.

- Probe, capture from the origin (capture commits and pushes directly; no PR
  is needed), then pull and apply everywhere else through the fast path.
- Only fleet-wide values come from the origin. Machine-specific values, such
  as absolute paths or per-OS settings, stay templated per host; a file that
  mixes both is `capture-manual` or a disjoint merge.
- Never rebuild settings that already exist on a host, and never write new
  scripts to reproduce them.
- For a managed app config whose source repository ships a capture helper
  (for example an OpenCodex portable-settings capture command), run that
  helper instead of editing the template by hand, but only when the origin is
  the machine you are on. A remote origin goes through `seal RUN capture`
  like any other file; never run a helper there as a direct remote command.
- Other hosts receive only source that is pushed upstream, through sealed
  plans. Never stage ad-hoc payloads and run them on hosts.

## Blockers and findings

Blockers force `review`; findings only report. Every code's cause and fix is
in [failure modes](references/failure-modes.md).

## Windows and privileged lanes

A native Windows machine with a `wsl_interop_via` sibling is on the fast path
like any host (transport `interop`): the controller SSHes to the WSL sibling,
which only launches Git for Windows `sh` by full path from `/mnt/c`, so every
payload runs as a native process in the logged-in session, with its Entra
token. It needs Git for Windows and a logged-in user (logoff stops WSL; the
host then reads `unreachable`). Names compare case-insensitively, as
Roundhouse's Windows executor does; mode and umask checks do not apply;
`seal ... targets` and `reset` are refused there, and `apply` runs through
Roundhouse's `apply-interop-plan`: seal skips the host until the installed
Roundhouse (0.9.25 or later) provides it. Without a WSL
sibling, a `codex-remote-control` target follows
[Codex remote control](references/codex-remote-control.md), and Claude
reports it `unsupported`. Protected broker, SFTP, S4U profile-bundle, and
privilege lifecycle work follows [privileged lanes](references/privileged-lanes.md).

## Verify

`apply` ends with a fresh probe of every host it touched: expect `in-sync`.
Also check auth/tool health the change could affect.
