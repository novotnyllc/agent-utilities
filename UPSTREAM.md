# Upstream Sources

`upstreams.json` is the authoritative machine-readable source ledger. This
document records human-readable provenance and adaptation notes.

The GitHub Agentic Workflow source in
`.github/workflows/refresh-imported-skills.md` compiles to the adjacent
`.lock.yml` workflow. It checks these pins weekly with the keyless GitHub
Copilot engine, preserves local adaptations, and opens a draft pull request
only when an imported path changes.

The initial skill copies came from:

- Repository: `https://github.com/steipete/agent-scripts`
- Initial commit: `6e512e6fe0546471dfce5f48c9896c6ddce669cd`
- License: MIT

The `oracle` skill was refreshed from:

- Repository: `https://github.com/steipete/oracle`
- Commit: `bfa8f1de42669f151933afe9fe5843ecdf9933d2`
- Path: `skills/oracle`

The `orchestrate` skill was copied and adapted from:

- Repository: `https://github.com/provencher/codex-skills`
- Commit: `8aa6c42b73781c905c55f8a1253a18127079ac21`
- Path: `orchestrate`
- License: MIT

## Copied Skills

| Local skill | Upstream path |
| --- | --- |
| `browser-use` | `skills/browser-use` |
| `create-cli` | `skills/create-cli` |
| `frontend-design` | `skills/frontend-design` |
| `instruments-profiling` | `skills/instruments-profiling` |
| `native-app-performance` | `skills/native-app-performance` |
| `one-password` | `skills/one-password` |
| `orchestrate` | `orchestrate` |
| `oracle` | `skills/oracle` |
| `remote-mac` | `skills/remote-mac` |
| `skill-cleaner` | `skills/skill-cleaner` |
| `sonos` | `skills/sonos` |
| `ssh-doctor` | `skills/ssh-doctor` |

## Adaptation Notes

- Removed Peter-specific host, service, user, and repo assumptions.
- Replaced fixed home paths with `$HOME` or plugin-relative paths.
- Replaced fixed 1Password vault/account assumptions with environment-driven
  routing.
- Replaced fixed Oracle package/repo/account examples with `ORACLE_*`
  configuration knobs.
- Updated `skill-cleaner` to discover the installed plugin root and common
  project roots without depending on one `~/Projects` layout.
- Added a Claude Code branch to `orchestrate` while preserving the upstream
  Codex delegation settings.
