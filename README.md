# agent-utilities

The toolbox: self-contained craft skills for Codex and Claude Code.

Each skill here is useful on its own, carries its own references and scripts,
and has no coupling to routing, orchestration, or the fleet. Most began as
adapted copies from `steipete/agent-scripts`; adaptations avoid
upstream-specific machine names, home paths, vault names, and package paths.

Delivery, model routing, task orchestration, cross-machine placement, fleet
readiness, deep review gates, Oracle, and Codex runtime hygiene live in the
sibling [`yardmaster`](https://github.com/novotnyllc/yardmaster) plugin.

## Skills

| Skill | Purpose |
| --- | --- |
| `browser-use` | Automate Chrome with the native browser tool or fallback bridge. |
| `create-cli` | Design predictable command-line arguments, help, output, and errors. |
| `frontend-design` | Build polished, non-generic web interfaces. |
| `instruments-profiling` | Profile macOS and iOS software with Instruments and `xctrace`. |
| `native-app-performance` | Diagnose native application performance and hotspots. |
| `one-password` | Read, store, and inject targeted secrets with the 1Password CLI. |
| `skill-cleaner` | Audit installed skills for usage, duplication, and description quality. |

## Install

```sh
codex plugin marketplace add novotnyllc/marketplace
codex plugin add agent-utilities --marketplace novotnyllc

claude plugin marketplace add novotnyllc/marketplace
claude plugin install agent-utilities@novotnyllc
```

Some skills have narrower requirements: 1Password needs `op` and `tmux`;
profiling skills require macOS or iOS tooling.

## Plugin metadata

```text
plugins/agent-utilities/.codex-plugin/plugin.json
plugins/agent-utilities/.claude-plugin/plugin.json
```

Marketplace catalogs live in the separate `novotnyllc/marketplace` repository.

For local development, point Codex at this plugin checkout or symlink
individual skill folders into `~/.agents/skills`; Claude Code can read
symlinked skill folders from `~/.claude/skills`.

## Validation

Validate both plugin manifests and each skill's YAML frontmatter before
publishing. Focused executable tests:

```sh
npx tsx plugins/agent-utilities/skills/skill-cleaner/scripts/skill-cleaner.test.ts
```

## Upstream Refreshes

Use `UPSTREAM.md` and `upstreams.json` to compare adapted copies with their
listed sources. Do not overwrite local adaptations blindly; refresh by diffing
the upstream skill folder and reapplying the local configuration changes.
