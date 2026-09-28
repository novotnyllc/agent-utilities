# Failure modes

Every code the probe reports, what causes it, and the fix. Blockers send the
host to `review`; findings only report.

## Blockers

| Code | Cause | Fix |
| --- | --- | --- |
| `login-shell-tools-missing` | A tool is not on PATH under the host's login shell (`$SHELL -lc`), which is where the Roundhouse executor and chezmoi run scripts execute. On macOS, fnm-managed tools such as `ocx` exist only once the zsh login profile initializes fnm. | Initialize the tool's PATH in the login profile (`.zprofile`, or a declarative path entry), not only in `.zshrc`. Never switch automation to `-i` interactive shells or hard-code `bash -lc`. Re-probe with `--require TOOL`. |
| `source-dirty` | Uncommitted changes in a non-gold host's source tree. | Find the writer (see `scheduled-source-writer`). Carry wanted changes to the gold's source and publish; discard the rest only with the user's explicit decision. Never auto-commit or reset. |
| `gold-source-dirty` | Uncommitted work on the gold. | The user reviews and commits it, or it is set aside; then publish. |
| `source-ahead`, `gold-unpublished` | Local commits not on upstream. | On the gold: the user pushes. Elsewhere: move the commits to the gold deliberately; never force-push or reset. |
| `source-fetch-failed`, `source-no-upstream`, `source-not-git` | Upstream state is unknown. | Fix the remote, credentials, or checkout, then re-probe. |
| `status-failed` | `chezmoi status` failed, usually a template error or a secret manager that needs a signed-in session. | Fix the template or sign in interactively on that host; never paste secrets to work around it. |
| `status-too-large` | More than 200 pending entries. | Too much to classify safely; reconcile in batches. |
| `external-rewritten` | A `.chezmoiexternal` `git-repo` (for example oh-my-tmux) whose upstream rewrote history. chezmoi's `pull --ff-only` fails and aborts the whole apply. The clone has no local, untracked, or ignored files, and every commit it holds came from upstream. | `"$FC" seal RUN reset HOST`, then `apply` ([reconcile](reconcile.md#blockers)). |
| `external-local-changes` | The same, but the clone has local changes or local commits. | Stop. Never reset; ask the user. |
| `gold-pending-apply` | The gold's source would change its live files. Its live state is authoritative, so this is a stale capture or a commit from elsewhere. | See stale captures below. Never apply over the gold. |

## Findings

| Code | Cause | Fix |
| --- | --- | --- |
| `scheduled-source-writer` | A launchd agent, systemd unit, or cron entry edits the source tree (for example a scheduled drift-adoption script with `--commit`, or a job running `apply --force`). Several hosts then collect the same uncommitted drift, and local commits diverge. | Make it report-only on non-gold hosts; on the gold, let it propose changes for the user to review and publish. It must not commit, push, or force-apply unattended. |
| `repeated-source-drift` | Several hosts share the same uncommitted source paths. | Almost always a scheduled writer; fix that, not each host. |
| `json-key-order` | An app rewrote a managed JSON file (for example Claude settings) with only key-order changes. chezmoi still counts it as a live edit and will not overwrite it non-interactively. | Fix the source, not the host: manage the file with the modify-template passthrough below, publish, and the drift disappears on every host. |
| `umask` | The effective chezmoi umask allows group/other write (WSL defaults to 002), causing permission-only drift and loosened files. | Set `umask = 0o022` in that host's chezmoi config and have bootstrap write it. |
| `sensitive-permissions` | A sensitive target (`.ssh`, `.gnupg`, `.aws`, `.docker`, …) has a source name without `private_`, or live group/other access. | Rename the source to `private_…` so apply keeps it 0700/0600. |
| `upstream-differs-from-gold` | This host's upstream ref is not the gold's HEAD. | Publish from the gold, or probe with fetch (the default). |
| `external-fetch-failed` | An external's upstream was unreachable. | Retry later; the external is left as is. |
| `external-behind` | A git-repo external has upstream commits chezmoi has not pulled yet. | Report only. The next sealed apply fast-forwards it once its `refreshPeriod` has elapsed. Do not run an unsealed `chezmoi apply --refresh-externals`: without targets it applies every pending entry, bypassing the plan, backup, and rechecks. |
| `plugin-marketplace-unregistered` | A marketplace declared in the synced harness settings is not registered. Claude Code registers `extraKnownMarketplaces` only on an interactive trusted start; headless runs never do. | Register and update it (`claude plugin marketplace add SOURCE`, `… update`; `codex plugin marketplace add`/`upgrade`) through the Roundhouse agents lane or the user's session. Do it before the chezmoi apply: plugin commands rewrite the settings file. |
| `plugin-not-installed` | A Claude plugin is enabled in the synced settings but not installed. | Install it, then re-probe; same ordering. |
| `plugin-missing-vs-gold`, `plugin-version-drift` | Installed plugins or versions differ from the gold for marketplaces the user declares. | Update through the Roundhouse agents lane (`roundhouse:fleet-update`). |

## Modify-template passthrough

App-written JSON should be managed by a `modify_` template that merges only the
managed keys and returns the file byte-for-byte when nothing managed changed:

```gotemplate
{{- /* chezmoi:modify-template */ -}}
{{- $current := dict -}}
{{- if .chezmoi.stdin -}}{{- $current = fromJson .chezmoi.stdin -}}{{- end -}}
{{- $merged := mergeOverwrite (deepCopy $current) (includeTemplate "managed.json" . | fromJson) -}}
{{- if and .chezmoi.stdin (eq (toJson $current) (toJson $merged)) -}}
{{-   .chezmoi.stdin -}}
{{- else -}}
{{-   toPrettyJson $merged -}}
{{- end -}}
```

## Stale captures

A template produced by a capture script (a portable manifest exported from the
gold's live config) goes stale when the gold changes afterwards; applying it
rolls the gold, then every host, back. Before applying anything that comes
from a capture, run the capture on the gold and require no diff against the
committed template. Capture only the allowlisted portable keys; auth,
accounts, caches, and host-specific profiles stay per host.

## Pipe truncation

A large export piped into a consumer that stops reading (or a buffer-bounded
reader) can be cut off, for example at 64 KiB, and the truncated result then
gets captured or applied. Write large exports to a private temporary file,
check its size or parse it completely, then read it. The probe and backup
scripts follow this rule.

## Installer edits and shared owners

An installer that appends a PATH block to a shell rc file creates live drift
that returns after every apply. Model it declaratively in the source (a PATH
entry that applies only if the directory exists) instead of adopting the raw
text. Likewise, when an installer and chezmoi both write one file (for example
a CLI launcher), pick one owner and remove the other; two owners guarantee
drift.
