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
| `cleanup-codex` | Inspect macOS Codex app-server resources and perform separately authorized exact-identity cleanup. |
| `create-cli` | Design predictable command-line arguments, help, output, and errors. |
| `task-orchestrator` | Orchestrate independently resumable tasks across projects and machines to a verified objective. |
| `frontend-design` | Build polished, non-generic web interfaces. |
| `goal-driven-delivery` | Route one lane and drive generic implementation through LFG, merge, and post-merge proof. |
| `instruments-profiling` | Profile macOS and iOS software with Instruments and `xctrace`. |
| `native-app-performance` | Diagnose native application performance and hotspots. |
| `one-password` | Read, store, and inject targeted secrets with the 1Password CLI. |
| `oracle` | Request a second-model review of selected prompts and files. |
| `skill-cleaner` | Audit installed skills for usage, duplication, and description quality. |
| `thermo-nuclear-code-quality-review` | Perform a strict maintainability and structure review. |
| `thermo-nuclear-review` | Perform a deep correctness and security review. |
| `thermos` | Run and synthesize both thermo-nuclear reviews. |

Fleet Readiness, including fleet-aware `remote-mac` and `ssh-doctor` skills,
lives in the `machine-utilities` plugin.

## Delivery workflows

See [Task Orchestrator, Goal Driven Delivery, and Fleet Readiness](docs/delivery-workflows.md)
for the decision rules, cross-host model, and why `orchestrate` is not a third
workflow.

## Install

```sh
codex plugin marketplace add novotnyllc/marketplace
codex plugin add agent-utilities --marketplace novotnyllc

claude plugin marketplace add novotnyllc/marketplace
claude plugin install agent-utilities@novotnyllc
```

Some skills have narrower requirements: 1Password needs `op` and `tmux`;
profiling skills require macOS or iOS tooling; and
`goal-driven-delivery` requires Compound Engineering 3.20 or newer. Oracle
sends only the files selected for its second-model review, whose output must
still be verified.

`cleanup-codex` is macOS-only. Codex runs a bounded root `SessionEnd` hook that
terminates only same-user processes carrying the ending task's exact
`CODEX_THREAD_ID`, escalates exact survivors from `TERM` to `KILL`, and stores
one private latest receipt per app-server identity. It never signals or
restarts the shared app-server. Set
`AGENT_UTILITIES_CLEANUP_CODEX_HOOK_DISABLED=1` to disable that cleanup. Claude
exposes the skill for explicit invocation and does not install the Codex
lifecycle hook. Recycle additionally requires a
trusted machine-provided descriptor attestor; Agent Utilities does not install
or change launcher and descriptor-limit configuration. Managed recycle fails
closed because the current native restart command cannot compare-and-swap the
receipt-bound PID and start time; unmanaged mode is never used as a fallback.

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
publishing. The repository has focused executable behavior tests:

```sh
node --test plugins/agent-utilities/skills/task-orchestrator/scripts/delivery-contracts.test.mjs
npx tsx plugins/agent-utilities/skills/skill-cleaner/scripts/skill-cleaner.test.ts
node --test plugins/agent-utilities/skills/cleanup-codex/scripts/cleanup-codex.test.mjs
```

These are not a repository-wide test suite.

## Upstream Refreshes

Use `UPSTREAM.md` and `upstreams.json` to compare adapted copies with their
listed sources. Do not overwrite local adaptations blindly; refresh by diffing
the upstream skill folder and reapplying the local configuration
changes.
