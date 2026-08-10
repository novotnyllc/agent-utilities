# Upstream Sources

`upstreams.json` is the authoritative machine-readable source ledger. This
document records human-readable provenance and adaptation notes.

The GitHub Agentic Workflow source in
`.github/workflows/refresh-imported-skills.md` compiles to the adjacent
`.lock.yml` workflow. It checks these pins weekly with the keyless GitHub
Copilot engine, preserves local adaptations, and opens a draft pull request
only when an imported path changes.

The agent-scripts imports were most recently reviewed against:

- Repository: `https://github.com/steipete/agent-scripts`
- Commit: `bce6015dbde00c15cdfef6d1fff72b247831f97e`
- License: MIT

Oracle, the thermos family, and the delivery/orchestration skills moved to
the [`railyard`](https://github.com/novotnyllc/railyard) plugin; their
upstream ledger and adaptation notes moved with them. Fleet, transport, and
UniFi administration live in
[`roundhouse`](https://github.com/novotnyllc/roundhouse).

## Copied Skills

| Local skill | Upstream path |
| --- | --- |
| `browser-use` | `skills/browser-use` |
| `create-cli` | `skills/create-cli` |
| `frontend-design` | `skills/frontend-design` |
| `instruments-profiling` | `skills/instruments-profiling` |
| `native-app-performance` | `skills/native-app-performance` |
| `one-password` | `skills/one-password` |
| `skill-cleaner` | `skills/skill-cleaner` |

## Adaptation Notes

- Removed Peter-specific host, service, user, and repo assumptions.
- Replaced fixed home paths with `$HOME` or plugin-relative paths.
- Replaced fixed 1Password vault/account assumptions with environment-driven
  routing.
- Updated `skill-cleaner` to discover the installed plugin root and common
  project roots without depending on one `~/Projects` layout.
- Retained portable browser and 1Password routing while adapting generic
  service-account prompt isolation and root-only skill auditing.
