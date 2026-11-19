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
- Commit: `dc4f583a2c1a6f3a93e81a972eee89f59aca32f7`
- License: MIT

The thermos family and delivery/orchestration skills live in
[`railyard`](https://github.com/novotnyllc/railyard). Fleet, transport, and
UniFi administration live in
[`roundhouse`](https://github.com/novotnyllc/roundhouse); the optional personal
chezmoi integration lives here as `fleet-chezmoi`.

Railyard supplied the `cleanup-codex` implementation and the local Oracle
adaptations at commit `aa9079f10941526b20627fafebb9a761429cfe76`.
The Oracle skill text tracks `steipete/oracle` at commit
`0f0bdb6a752efb2c736ec4dcaa6d3cc29743d851` (MIT). Preserve its skill-local
installer, explicit binary override, and browser profile preferences when
refreshing the skill.

## Copied Skills

| Local skill | Upstream path |
| --- | --- |
| `browser-use` | `skills/browser-use` |
| `create-cli` | `skills/create-cli` |
| `frontend-design` | `skills/frontend-design` |
| `instruments-profiling` | `skills/instruments-profiling` |
| `native-app-performance` | `skills/native-app-performance` |
| `one-password` | `skills/one-password` |
| `oracle` | `skills/oracle` in `steipete/oracle` |
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
