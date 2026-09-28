# Reconcile a review host

Load this only for hosts the probe classified `review`, and work only on the
paths and blockers it listed. Every other host stays on the fast path.

## Why the fast path is safe

A `chezmoi status` line is `XY path`. `X` compares chezmoi's last-written
state with the live file; `Y` says what apply would do (`A`, `M`, `D`, `R`).
`X` blank means nobody changed the file since chezmoi wrote it, so applying
the source loses nothing a person or app wrote. The classifier allows `apply`
only when every line has `X` blank and no line is a deletion (`Y` = `D`) or a sensitive path
(`.ssh`, `.gnupg`, `.aws`, `.kube`, `.config/gh`, `.netrc`, keys, tokens,
credentials). Then:

| Step | Check |
| --- | --- |
| `seal` | Roundhouse's own inventory has the probed source HEAD, a clean source, and the probed status digest; the plan is a full `chezmoi --no-tty apply` bound to that digest. |
| `apply` | The set ID and every plan's bytes still match. |
| backup | `chezmoi status` still hashes to the sealed digest, or the host is skipped before anything changes. |
| Roundhouse | Identity (hostname/user), executor integrity, and the sealed precondition digest are rechecked immediately before the argv runs. |

Pending run scripts (`Y` = `R`) are source intent and stay on the fast path,
but only if their tools resolve under the login shell (`--require TOOL`).

## Evidence

Collect the table in one call per host, for the classified conflicts (or name
destination-relative paths):

```sh
"$FC" evidence RUN HOST [TARGET...]
```

Each row gives the status code, the mapped source file and kind (`plain`,
`template`, `modify`), rendered and live SHA-256 (plus a canonical-JSON
comparison for `.json`), live mode, live and source mtimes, and the last
commits that touched the source file. Compare the same target on other hosts
by running evidence there too: cross-host agreement on a live digest is strong
evidence the edit is intended. Timestamps are evidence, never precedence.

## Decide per path

- **Source wins, live unchanged since the last write** (`X` blank):
  `"$FC" seal RUN targets HOST [TARGET...]`, show the user the exact argv,
  then `"$FC" apply RUN SET-ID`. The plan is
  `chezmoi --no-tty apply -- ABSOLUTE-TARGET...` (1-16 paths under the
  target's home) with the evidenced `chezmoi status -- TARGET...` digest
  sealed; Roundhouse 0.9.24+ refuses if it changed.
- **Source wins over a live edit** (`X` set): chezmoi will not overwrite it
  without an interactive answer, and a sealed plan never adds `--force`, so
  `seal targets` refuses. The host's owner runs `chezmoi apply -- TARGET` in an
  interactive session on that host and confirms each file. Take a backup first
  (`apply` does this for sealed stages; otherwise copy the file into a private
  directory on that host).
- **Live wins**: see below.
- **Both changed in disjoint regions**: merge deliberately in the gold's
  source (template or modify_ script), publish, then fast-path every host.
- **Same semantic region, or intent is unclear**: stop and ask the user.
- **Deletion or sensitive path**: name each path to the user and get an
  explicit decision; keep sensitive directories `private_`.

## Live wins

Live wins only by capturing into the gold host's source and publishing; never
run `chezmoi add` or `re-add` on another host, and never add a directory
recursively.

1. If the edit lives on another host, copy just that file to the gold into a
   private temporary directory (`mktemp -d`; `scp HOST:PATH "$tmp/"`). Never
   print it. Compare digests with the evidence row.
2. On the gold, update the source for that one target:
   - a plain file: `chezmoi re-add -- TARGET` when the gold's live copy is the
     desired content, otherwise copy the captured file into the mapped source
     path;
   - a template or modify_ script: edit the source by hand so it renders the
     desired content; never paste a rendered secret into the source;
   - a new target: `chezmoi add -- TARGET` for that exact file only; use a
     `private_` name and a secret-manager template for anything sensitive.
3. Run the source repository's secret scan if it has one, show the user
   `git diff --stat` and the non-secret diff, and let the user approve the
   commit and push. Never commit or push on your own.
4. Delete the temporary copy, re-probe, and fast-path the fleet.

## Blockers

Each blocker code has a cause and a fix in
[failure modes](failure-modes.md). The ones with a sealed remedy:

- `external-rewritten`: `"$FC" seal RUN reset HOST`, show the user the argv
  (`git -C PATH reset --hard --quiet UPSTREAM`), then `"$FC" apply RUN SET-ID`.
  Roundhouse 0.9.24+ seals it only when the clone has no local, untracked, or
  ignored files and every commit it holds came from upstream, binds its current
  HEAD, and rechecks all of that before resetting.
- `source-dirty`, `source-ahead`: reconcile the source repository first (see
  scheduled writers in failure modes); never reset or auto-commit it.
