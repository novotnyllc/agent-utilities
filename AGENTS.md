# AGENTS.md

`agent-utilities` is the toolbox: self-contained craft skills for Codex and
Claude Code — browser automation, CLI design, frontend design, native
profiling, 1Password, skill auditing. Plugin source lives under
`plugins/agent-utilities/`; everything else is documentation.

## Always

- Keep each skill self-contained: its references and scripts live inside its
  own directory. The self-containment test — could this skill be dropped into
  a session alone and still work? — is what keeps a skill in this repo rather
  than in [`railyard`](https://github.com/novotnyllc/railyard) or
  [`roundhouse`](https://github.com/novotnyllc/roundhouse).
- Do not hard-code maintainer-local secrets, host names, vault names, or
  machine inventory. Use environment variables or user-owned config paths.
- Never treat the installed plugin cache as the source repo for release work.
- Any change under `plugins/` bumps both plugin manifests and repins the
  marketplace; docs-only changes do neither —
  [release coupling](docs/agents/release-coupling.md).

## Verify

This repo has no validation CI — the checks below are the gate.

```sh
npx tsx plugins/agent-utilities/skills/skill-cleaner/scripts/skill-cleaner.test.ts
```

Plus: both plugin manifests parse as JSON, and every
`plugins/agent-utilities/skills/*/SKILL.md` has valid YAML frontmatter whose
`name` matches its directory.

## Deeper

- [Charter and boundaries](docs/agents/charter.md) — what belongs here,
  what belongs in `railyard` or `roundhouse`
- [Skill authoring](docs/agents/skill-authoring.md) — both-harness rule,
  self-containment, secrets, validation
- [Release coupling](docs/agents/release-coupling.md) — version bump, repin,
  docs-only exemption
- [Upstream attribution](docs/agents/upstream-attribution.md) — provenance
  ledger and how to refresh an adapted skill
