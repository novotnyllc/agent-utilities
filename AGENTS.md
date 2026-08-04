# AGENTS.md

## Repo Purpose

This repository owns the `agent-utilities` plugin for Codex and Claude Code.
It contains adapted copies of selected utility skills from
`steipete/agent-scripts`.

## Delivery Routing

When one of the workflow skills below is active, its two-emoji task-title
contract overrides this repository's general thread-title convention unless
the user supplies an exact title or a higher-priority harness rule applies.

- Run the read-only `agent-utilities:model-routing` intake on every software
  delivery turn. Explicit workflow and terminal instructions win. Configured
  fleet/account delivery enters `agent-utilities:task-orchestrator`, even when
  it fast-paths one lane; explicit local/no-fleet or no-config single-host work
  enters `agent-utilities:goal-driven-delivery` directly.
- Task Orchestrator owns decomposition, project allocation, placement,
  concurrency, monitoring, synthesis, and evidence; it never executes child
  work. Each software-delivery child uses Goal Driven Delivery and consumes its
  immutable route, budget lease, checkpoint, and terminal policy.
- LFG owns plan through CI and review settlement. Goal Driven Delivery owns
  authorized merge and post-merge proof. A checkpoint push is not a PR or a
  completion signal.
- `agent-utilities/model-routing/v1` is the only operational model/effort,
  budget, and transport policy. Its no-config profile preserves the shipped
  Sol/Luna defaults and attested unavailable-Luna substitution without probing
  optional providers. Consumers must not copy its constants or ranking logic.
- Compound Engineering remains unchanged. When a frozen route selects GLM or
  Claude, Agent Utilities may override only the named CE execution step. GLM
  uses its admitted separate task; Claude uses CE's existing attested
  read-only adapter and otherwise remains `transport_unsupported`. Return the
  normal CE artifact shape; CE retains workflow, persona, review, and terminal
  authority.
- For a dependent stack against a GitHub upstream, install and verify
  `gh-stack` before dispatching when it is missing:

  ```bash
  gh extension install github/gh-stack --force
  gh skill install github/gh-stack --all --agent codex --scope user --force
  gh stack --version
  gh skill list --agent codex --scope user
  ```

  On hosts that use Claude Code, additionally install and verify its copy with
  `gh skill install github/gh-stack --all --agent claude-code --scope user --force`
  and `gh skill list --agent claude-code --scope user`.

## Release Coupling

When changing the plugin version, update both:

- `plugins/agent-utilities/.codex-plugin/plugin.json`
- `plugins/agent-utilities/.claude-plugin/plugin.json`
- `<marketplace-repo>/.agents/plugins/marketplace.json`
- `<marketplace-repo>/.agents/plugins/plugin-versions.json`
- `<marketplace-repo>/.claude-plugin/marketplace.json`

If the plugin is newly added or renamed, also update:

- `<marketplace-repo>/README.md`

Never treat the installed Codex plugin cache under `~/.codex/plugins/cache` as
the source repo for release work.

## Skill Editing Rules

- Keep skills usable by both Codex and Claude Code unless a skill explicitly
  documents an agent-specific branch.
- Do not hard-code maintainer-local secrets, host names, vault names, or machine
  inventory. Use environment variables or user-owned config paths.
- Preserve upstream attribution when copying or refreshing skills.
- Validate JSON manifests and frontmatter before committing.
