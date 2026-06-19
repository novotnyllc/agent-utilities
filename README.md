# agent-utilities

Agent utility skills for Codex and Claude Code.

This plugin bundles Claire-adapted utility skills originally copied from
`steipete/agent-scripts`. The adapted copies avoid Peter-specific machine names,
home paths, vault names, and package paths so they can be used from Claire's
Codex and Claude Code environments.

## Skills

- `browser-use`
- `create-cli`
- `frontend-design`
- `instruments-profiling`
- `native-app-performance`
- `one-password`
- `oracle`
- `remote-mac`
- `skill-cleaner`
- `sonos`
- `ssh-doctor`

## Codex

This repo is published through the `novotnyllc` Codex marketplace. The Codex
plugin manifest lives at:

```text
plugins/agent-utilities/.codex-plugin/plugin.json
```

## Claude Code

Claude Code metadata lives at:

```text
.claude-plugin/marketplace.json
plugins/agent-utilities/.claude-plugin/plugin.json
```

For local development, symlink the skill folders from `plugins/agent-utilities/skills`
into `~/.claude/skills` if you want Claude Code to read the working checkout
directly.

## Upstream Refreshes

Use `UPSTREAM.md` to compare these adapted copies with the original
`steipete/agent-scripts` skills. Do not overwrite local adaptations blindly;
refresh by diffing the upstream skill folder and reapplying the Claire-specific
configuration changes.
