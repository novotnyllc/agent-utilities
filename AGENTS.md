# AGENTS.md

## Charter

`agent-utilities` is the toolbox: self-contained craft skills any single agent
session can pick up — how to drive a browser, design a CLI or a frontend,
profile a native app, handle 1Password secrets, or audit skills.

**Belongs here:** skills that are useful on their own, carry their own
references and scripts inside their skill directory, and have no coupling to
routing, orchestration, or the fleet.

**Belongs elsewhere:** everything about delivering work — model routing,
delivery, orchestration, cross-machine placement, review gates, Oracle, and
Codex runtime hygiene live in
[`railyard`](https://github.com/novotnyllc/railyard); fleet readiness,
machine administration, and UniFi live in
[`roundhouse`](https://github.com/novotnyllc/roundhouse). If a new skill needs
the router, the fleet CLI, or dispatch semantics, it goes there, not here.

## Release Coupling

When changing the plugin version, update both:

- `plugins/agent-utilities/.codex-plugin/plugin.json`
- `plugins/agent-utilities/.claude-plugin/plugin.json`
- `<marketplace-repo>/.agents/plugins/marketplace.json`
- `<marketplace-repo>/.agents/plugins/plugin-versions.json`
- `<marketplace-repo>/.claude-plugin/marketplace.json`

Never treat the installed plugin cache as the source repo for release work.

## Skill Editing Rules

- Keep skills usable by both Codex and Claude Code unless a skill explicitly
  documents an agent-specific branch.
- Keep each skill self-contained: its references and scripts live inside its
  own directory.
- Do not hard-code maintainer-local secrets, host names, vault names, or
  machine inventory. Use environment variables or user-owned config paths.
- Preserve upstream attribution when copying or refreshing skills.
- Validate JSON manifests and frontmatter before committing.
