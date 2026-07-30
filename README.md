# agent-utilities

Agent utility skills for Codex and Claude Code.

This plugin bundles adapted utility skills for Codex and Claude Code.
Most began as copies from `steipete/agent-scripts`. Adapted copies avoid
upstream-specific machine names, home paths, vault names, and package paths so
they can be used across Codex and Claude Code environments.

## Skills

- `browser-use`
- `create-cli`
- `delivery-director`
- `frontend-design`
- `goal-driven-delivery`
- `instruments-profiling`
- `native-app-performance`
- `one-password`
- `orchestrate`
- `oracle`
- `skill-cleaner`
- `sonos`
- `thermo-nuclear-code-quality-review`
- `thermo-nuclear-review`
- `thermos`

Fleet-aware `remote-mac` and `ssh-doctor` skills now live in the
`machine-utilities` plugin.

## Codex

This repo is published through the `novotnyllc` Codex marketplace. The Codex
plugin manifest lives at:

```text
plugins/agent-utilities/.codex-plugin/plugin.json
```

## Claude Code

Claude Code metadata lives at:

```text
plugins/agent-utilities/.claude-plugin/plugin.json
```

Marketplace catalogs live in the separate `novotnyllc/marketplace` repository.

For local development, symlink the skill folders from `plugins/agent-utilities/skills`
into `~/.claude/skills` if you want Claude Code to read the working checkout
directly.

## Upstream Refreshes

Use `UPSTREAM.md` and `upstreams.json` to compare adapted copies with their
listed sources. Do not overwrite local adaptations blindly; refresh by diffing
the upstream skill folder and reapplying the local configuration
changes.
