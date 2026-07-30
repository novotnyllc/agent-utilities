# agent-utilities

Agent utility skills for Codex and Claude Code.

This plugin bundles adapted utility skills for Codex and Claude Code.
Most began as copies from `steipete/agent-scripts`. Adapted copies avoid
upstream-specific machine names, home paths, vault names, and package paths so
they can be used across Codex and Claude Code environments.

## Skills

| Skill | Purpose |
| --- | --- |
| `browser-use` | Automate Chrome with the native browser tool or fallback bridge. |
| `create-cli` | Design predictable command-line arguments, help, output, and errors. |
| `delivery-director` | Coordinate delivery across tasks, hosts, pull requests, and dependencies. |
| `frontend-design` | Build polished, non-generic web interfaces. |
| `goal-driven-delivery` | Drive implementation through planning, review, validation, and PR readiness. |
| `instruments-profiling` | Profile macOS and iOS software with Instruments and `xctrace`. |
| `native-app-performance` | Diagnose native application performance and hotspots. |
| `one-password` | Read, store, and inject targeted secrets with the 1Password CLI. |
| `orchestrate` | Coordinate multiple agents on substantial work. |
| `oracle` | Request a second-model review of selected prompts and files. |
| `skill-cleaner` | Audit installed skills for usage, duplication, and description quality. |
| `sonos` | Search, queue, group, and control Sonos playback. |
| `thermo-nuclear-code-quality-review` | Perform a strict maintainability and structure review. |
| `thermo-nuclear-review` | Perform a deep correctness and security review. |
| `thermos` | Run and synthesize both thermo-nuclear reviews. |

Fleet-aware `remote-mac` and `ssh-doctor` skills now live in the
`machine-utilities` plugin.

## Install

```sh
codex plugin marketplace add novotnyllc/marketplace
codex plugin add agent-utilities --marketplace novotnyllc

claude plugin marketplace add novotnyllc/marketplace
claude plugin install agent-utilities@novotnyllc
```

Some skills have narrower requirements: 1Password needs `op` and `tmux`; Sonos
needs its CLI; profiling skills require macOS or iOS tooling; and
`goal-driven-delivery` requires Compound Engineering 3.20 or newer. Oracle
sends only the files selected for its second-model review, whose output must
still be verified.

## Plugin metadata

```text
plugins/agent-utilities/.codex-plugin/plugin.json
plugins/agent-utilities/.claude-plugin/plugin.json
```

Marketplace catalogs live in the separate `novotnyllc/marketplace` repository.

For local development, point Codex at this plugin checkout or symlink individual
skill folders into `~/.agents/skills`; Claude Code can read symlinked skill
folders from `~/.claude/skills`.

## Validation

Validate both plugin manifests and each skill's YAML frontmatter before
publishing. The repository has one executable behavior test:

```sh
npx tsx plugins/agent-utilities/skills/skill-cleaner/scripts/skill-cleaner.test.ts
```

This is not a repository-wide test suite.

## Upstream Refreshes

Use `UPSTREAM.md` and `upstreams.json` to compare adapted copies with their
listed sources. Do not overwrite local adaptations blindly; refresh by diffing
the upstream skill folder and reapplying the local configuration
changes.
