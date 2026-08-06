# Upstream attribution and refreshes

Most skills here began as adapted copies of `steipete/agent-scripts`. Two
files carry the provenance:

- [`upstreams.json`](../../upstreams.json) — the authoritative
  machine-readable ledger (repository, path, pinned commit, license per
  skill). `updatePolicy` is `review-only`.
- [`UPSTREAM.md`](../../UPSTREAM.md) — human-readable provenance, the copied
  skill table, and the adaptation notes.

## Rules

- Preserve upstream attribution when copying or refreshing a skill. Do not
  strip license or source references from a copied file.
- Never overwrite local adaptations blindly. Refresh by diffing the upstream
  skill folder against the local one and reapplying the local changes —
  removed maintainer-specific hosts, users, and repos; `$HOME` or
  plugin-relative paths; environment-driven 1Password routing.
- Record the reviewed commit in both `upstreams.json` and `UPSTREAM.md` when
  a refresh lands, so the next diff starts from the right base.

The weekly `.github/workflows/refresh-imported-skills` agentic workflow
checks these pins and opens a draft pull request only when an imported path
changes; it is a notifier, not an auto-merger.
