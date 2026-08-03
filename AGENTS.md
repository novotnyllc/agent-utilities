# AGENTS.md

## Repo Purpose

This repository owns the `agent-utilities` plugin for Codex and Claude Code.
It contains adapted copies of selected utility skills from
`steipete/agent-scripts`.

## Delivery Routing

When one of the workflow skills below is active, its two-emoji task-title
contract overrides this repository's general thread-title convention unless
the user supplies an exact title or a higher-priority harness rule applies.

- Use `agent-utilities:goal-driven-delivery` for one host-local lane. Explicit
  brainstorm, plan, diagnosis, review, or local-only requests stop at their
  requested artifact; generic implementation, bug-fix, or ship requests use
  `$compound-engineering:lfg` by default.
- Use `agent-utilities:task-orchestrator` only for multiple independently
  resumable tasks or remote task placement. It owns decomposition, routing,
  placement, concurrency, monitoring, synthesis, and evidence; it never
  executes child work. Each software-delivery child uses Goal Driven Delivery
  and inherits its LFG, model, checkpoint, and terminal policy.
- LFG owns plan through CI and review settlement. Goal Driven Delivery owns
  authorized merge and post-merge proof. A checkpoint push is not a PR or a
  completion signal.
- Use Sol High for orchestration by default, Sol Max for complex or risky
  coordination, Luna for most implementation with Max effort preferred and
  the actual effort disclosed, and separate Sol review;
  use Fable 5 only when the supported CE path verifies it.
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
