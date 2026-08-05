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
- Commit: `c46ea65b6323e8a2b6f441f8b6449ae731bc8f81`
- License: MIT

Oracle, the thermos family, and the delivery/orchestration skills moved to
the `yardmaster` plugin; their upstream ledger moved with them. Fleet,
transport, and UniFi administration live in `roundhouse`.

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
- Replaced fixed Oracle package/repo/account examples with `ORACLE_*`
  configuration knobs.
- Added Oracle's portable, skill-local lifecycle bootstrap: resolve the active
  installed skill directory, run `scripts/ensure-oracle.sh` once, and invoke
  only its returned absolute Oracle 0.17.0-or-newer path. It prefers
  `steipete/tap/oracle`, has a bounded `$HOME/.local` npm fallback, treats an
  explicit `ORACLE_BIN` as validation-only, and preserves user-owned Oracle
  configuration, authentication, sessions, and browser state.
- Added local Oracle browser-profile guidance: honor nested
  `browser.manualLogin`, never combine it with `--copy-profile`, and leave any
  profile-mode or authentication change to the user.
- Updated `skill-cleaner` to discover the installed plugin root and common
  project roots without depending on one `~/Projects` layout.
- Retained portable browser and 1Password routing while adapting generic
  service-account prompt isolation and root-only skill auditing.
- Thermos and its two reviewer rubrics are tracked from Cursor's
  `cursor/plugins` at `fa16d695b35ccf4ea179d976e5aaee0834a25b0b`. Their local
  wrappers retain provider/model-routing-safe dispatch, explicitly branch
  Codex explorer work from Claude execution, package for both harnesses, and
  preserve deterministic frozen review-packet and coverage-portfolio behavior
  where applicable. Cursor's `disable-model-invocation: true` frontmatter is
  deliberately handled by those wrappers rather than copied as an
  unconditional local restriction. Refresh review presents these expected
  adaptations and never raw-copies over them; any other upstream drift remains
  reviewable.
