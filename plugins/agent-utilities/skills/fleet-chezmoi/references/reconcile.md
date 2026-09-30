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
evidence the edit is intended.

## How a change's origin is decided

Changes happen one at a time, on one machine. For each live-edited file the
probe records the live digest and mtime, the mapped source file and its kind,
and when upstream (and the host's own checkout) last changed that source file.
Across all hosts, per file:

| Decision | When | What happens |
| --- | --- | --- |
| `capture` | The newest edit is newer than any upstream change to the source, every host that edited it holds the same content, the origin had pulled the latest change to that file, and the source is a plain file. | The origin host is `capture`; hosts that already hold the same content are `awaiting-capture`. `seal RUN capture` publishes it. |
| published | The edit already equals the upstream file. | A pull resolves it. |
| `source-newer` | Upstream changed the source after the edit. | The edit is stale. Overwriting it needs the owner (below). |
| `stale-base` | The edit did not start from the current upstream content: what chezmoi last wrote there (its entry state) differs from the upstream file, or the source revisions differ. Dates never decide this. | Capturing would discard that change: pull there, then reconcile by hand. |
| `competing` | Hosts hold different content. | The newest is proposed; a person decides. |
| `capture-manual` | The origin's source is a template, `modify_` script, encrypted, or a sensitive path. | Edit the source by hand (below). |

Timestamps choose between edits only after content, upstream history, and the
source kind agree; they never override a newer upstream change or a
disagreement between hosts. When the user asks to propagate settings, the
machine they are working on is the origin; in a `competing` decision, propose
its content.

### Managed settings files

A file an app rewrites (Claude Code's `settings.json`) is managed by a
`modify_` script that merges a plain JSON template of fleet-wide keys into the
host's file. Declare it in the source's `.fleet-chezmoi.json`:

```json
{"version": 1, "managed_json": [{"target": ".claude/settings.json",
  "managed": ".chezmoitemplates/claude-code-settings.json",
  "retired": ".chezmoitemplates/claude-code-settings.retired.json"}]}
```

The probe compares each host's values for the template's keys, one level into
objects (so each plugin or marketplace entry counts separately), with the last
20 published versions of the template. A value that matches a published
version means the host is behind; the apply fixes it. A value that matches
none is an edit, even when chezmoi reports nothing (an added entry survives
the merge). Per entry, across hosts, the same rules apply: newest edit newer
than upstream and agreed by every host is captured; different values are a
decision. Every key syncs, `env` included. A value that looks like a secret
(token shapes, private keys, or an `*API_KEY`/`*TOKEN`/`*PASSWORD`-style key
with a long value) is held back on its own and reported by name; the rest of
the capture still publishes. The user decides whether to commit it or keep it
in a secret manager. An optional `review_keys` list forces named keys to
review.
Edits to different entries on different hosts are all captured in one set.
The capture fetches only the approved entries, merges them into the template,
and records a removed entry in the `retired` file, which the `modify_` script
applies on every host. A removal from a file that declares no existing
`retired` file is refused, since no other host could apply it.

## Decide per path

- **Capture (automatic)**: `"$FC" seal RUN capture` lists each file, its
  origin host, and when it was edited. After one approval, `apply` fetches each
  file from its origin only if its digest still matches, writes it into the
  local source's mapped plain file, refuses and restores anything that looks
  like a secret (built-in patterns plus the repository's `scripts/scan-secrets`
  when present), commits once, pushes, and re-probes. The local source must be
  clean and at upstream. Nothing is captured into a template, a `modify_`
  script, or a sensitive path.
- **Source wins, live unchanged since the last write** (`X` blank):
  `"$FC" seal RUN targets HOST [TARGET...]`, show the user the exact argv,
  then `"$FC" apply RUN SET-ID`. The plan is
  `chezmoi --no-tty apply -- ABSOLUTE-TARGET...` (1-16 paths under the
  target's home) with the evidenced `chezmoi status -- TARGET...` digest
  sealed; Roundhouse 0.9.24+ refuses if it changed.
- **Source wins over a live edit** (`source-newer`, or a `competing` edit that
  lost): chezmoi will not overwrite a file edited since its last write without
  an interactive answer, and a sealed plan never adds `--force`, so
  `seal targets` refuses. The host's owner runs `chezmoi apply -- TARGET` in an
  interactive session on that host and confirms. Take a backup first.
- **`capture-manual`**: on the local source, edit the template or `modify_`
  script so it renders the origin's content. Compare with `evidence` digests,
  never by printing rendered files; never paste a rendered secret into the
  source. A new target: `chezmoi add -- TARGET` for that exact file only, with a
  `private_` name and a secret-manager template for anything sensitive. Show the
  user the non-secret diff; the user approves the commit and push.
- **`competing` or `stale-base`**: show the user the `decide` line and the
  `evidence` rows from each host, and ask. Merge disjoint edits in the source.
- **Deletion or sensitive path**: name each path to the user and get an
  explicit decision; keep sensitive directories `private_`.

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
