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
- Commit: `35c46c647a6448face3dae580e0502816b164e54` (`browser-use`, `frontend-design`, `one-password`);
  `create-cli`, `instruments-profiling`, `native-app-performance`, and
  `skill-cleaner` are unchanged since `dc4f583a2c1a6f3a93e81a972eee89f59aca32f7`
- License: MIT

The thermos family and delivery/orchestration skills live in
[`railyard`](https://github.com/novotnyllc/railyard). Fleet, transport, and
UniFi administration live in
[`roundhouse`](https://github.com/novotnyllc/roundhouse); the optional personal
chezmoi integration lives here as `fleet-chezmoi`.

Railyard supplied the `cleanup-codex` implementation and the local Oracle
adaptations at commit `aa9079f10941526b20627fafebb9a761429cfe76`.
The Oracle skill text tracks `steipete/oracle` at commit
`370a0a93da640ad08fc1b9f63dc3d74e1979915b` (MIT). Preserve its skill-local
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
- `browser-use`: kept the native-browser-first / direct-DevTools-last route.
  Did not import upstream's OpenClaw extension relay documentation or its
  `auto-allow.py` helper (it automatically clicks Chrome's "Allow remote
  debugging?" security prompt, which conflicts with this skill's rule never to
  loop approvals). Carried forward the 60s/30s default timeout clarification
  and the `mcporter daemon stop` recovery guidance.
- `frontend-design`: adopted upstream's trigger-oriented description.
- `one-password`: upstream removed `skills/one-password` at `55a8735`
  ("remove private one-password workflow from public skills"). The local skill
  is already a generalized, environment-driven adaptation and is retained as a
  locally maintained skill; its pin is advanced to the reviewed upstream tip
  so the weekly check stays quiet. The path no longer exists upstream.
- `oracle`: upstream's changes since the previous pin target the GPT-5.6 Sol
  flow, which this adaptation replaced with the GPT-6 Pro consult flow and a
  skill-local installer. Carried forward only the `--browser-no-focus` and
  browser upload bundling notes; kept the installer, binary override, and
  browser profile preferences.
