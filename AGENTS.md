# AGENTS.md

## Repo Purpose

This repository owns the `agent-utilities` plugin for Codex and Claude Code.
It contains Claire-adapted copies of selected utility skills from
`steipete/agent-scripts`.

## Release Coupling

When changing the plugin version, update both:

- `plugins/agent-utilities/.codex-plugin/plugin.json`
- `plugins/agent-utilities/.claude-plugin/plugin.json`
- `.claude-plugin/marketplace.json`
- `/Users/claire/dev/marketplace/.agents/plugins/plugin-versions.json`

If the plugin is newly added or renamed, also update:

- `/Users/claire/dev/marketplace/.agents/plugins/marketplace.json`
- `/Users/claire/dev/marketplace/README.md`

Never treat the installed Codex plugin cache under `~/.codex/plugins/cache` as
the source repo for release work.

## Skill Editing Rules

- Keep skills usable by both Codex and Claude Code unless a skill explicitly
  documents an agent-specific branch.
- Do not hard-code Claire's local secrets, host names, vault names, or machine
  inventory. Use environment variables or user-owned config paths.
- Preserve upstream attribution when copying or refreshing skills.
- Validate JSON manifests and frontmatter before committing.
