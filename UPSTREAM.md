# Upstream Sources

The initial skill copies came from:

- Repository: `https://github.com/steipete/agent-scripts`
- Initial commit: `6e512e6fe0546471dfce5f48c9896c6ddce669cd`
- License: MIT

The `oracle` skill was refreshed from:

- Repository: `https://github.com/steipete/oracle`
- Commit: `bfa8f1de42669f151933afe9fe5843ecdf9933d2`
- Path: `skills/oracle`

The `babysit-pr` skill was copied from:

- Repository: `/Users/claire/dev/babysit-pr`
- Latest local refresh source: `/Users/claire/dev/codex/.codex/skills/babysit-pr`
- License: Apache-2.0

## Copied Skills

| Local skill | Upstream path |
| --- | --- |
| `babysit-pr` | `.codex/skills/babysit-pr` |
| `browser-use` | `skills/browser-use` |
| `create-cli` | `skills/create-cli` |
| `frontend-design` | `skills/frontend-design` |
| `instruments-profiling` | `skills/instruments-profiling` |
| `native-app-performance` | `skills/native-app-performance` |
| `one-password` | `skills/one-password` |
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
  Claire project roots without depending on one `~/Projects` layout.
