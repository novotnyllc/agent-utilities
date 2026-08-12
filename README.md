<img src="docs/assets/agent-utilities.png" alt="agent-utilities" width="130" align="right"/>

# agent-utilities

The toolbox: self-contained craft skills for Codex and Claude Code.

Each skill here is useful on its own, carries its own references and scripts,
and has no coupling to routing, orchestration, or the fleet. Most began as
adapted copies from `steipete/agent-scripts`; adaptations avoid
upstream-specific machine names, home paths, vault names, and package paths.

Delivery, model routing, orchestration, review gates, Oracle, and Codex
runtime hygiene live in the sibling
[`railyard`](https://github.com/novotnyllc/railyard) plugin; fleet
readiness, machine administration, and UniFi in
[`roundhouse`](https://github.com/novotnyllc/roundhouse).

## Skills

| Skill | Purpose |
| --- | --- |
| `browser-use` | Automate Chrome with the native browser tool or fallback bridge. |
| `create-cli` | Design predictable command-line arguments, help, output, and errors. |
| `frontend-design` | Build polished, non-generic web interfaces. |
| `instruments-profiling` | Profile macOS and iOS software with Instruments and `xctrace`. |
| `native-app-performance` | Diagnose native application performance and hotspots. |
| `onedrive-fileprovider-repair` | Diagnose and safely repair macOS OneDrive File Provider churn. |
| `one-password` | Read, store, and inject targeted secrets with the 1Password CLI. |
| `skill-cleaner` | Audit installed skills for usage, duplication, and description quality. |
| `fleet-chezmoi` | Reconcile chezmoi source and live-state drift with roundhouse when present. |

### Why the OneDrive repair skill exists

Codex can create and actively use `~/Documents/Codex`. When Documents is
OneDrive-backed on macOS, that real working directory is also a File Provider
sync target. Repeated workspace changes, cloud hydration, and stale provider
reconciliation can then drive sustained CPU in OneDrive, `fileproviderd`, and
`suggestd`. The `onedrive-fileprovider-repair` skill captures the bounded
diagnosis and FPCK repair while preserving the real Codex directory, keeping
Documents backed up, and never quitting Codex.

Adjacent open `openai/codex` issues document the upstream product constraints;
none currently describes this exact `suggestd`/FPCK failure loop:

- [#20880](https://github.com/openai/codex/issues/20880) — the app recreates `~/Documents/Codex` on launch.
- [#28857](https://github.com/openai/codex/issues/28857) — make the default artifact/output directory configurable.
- [#15159](https://github.com/openai/codex/issues/15159) — broad searches can hydrate macOS CloudStorage trees.
- [#28729](https://github.com/openai/codex/issues/28729) — warn about active workspaces in cloud-synced folders.
- [#32853](https://github.com/openai/codex/issues/32853) — restored macOS OneDrive File Provider workspaces can fail after relaunch.

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

## License

MIT — see [LICENSE](LICENSE), which preserves the upstream copyright notice
for the skills adapted from `steipete/agent-scripts`.

One exception: the `frontend-design` skill is Apache-2.0 (Copyright 2024
Anthropic PBC) and keeps its own
[LICENSE.txt](plugins/agent-utilities/skills/frontend-design/LICENSE.txt).
Every incorporation is itemized in
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
