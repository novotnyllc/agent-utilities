---
title: Keep Codex-only hooks out of Claude plugin discovery
date: 2026-08-03
category: tooling-decisions
module: Plugin packaging
problem_type: tooling_decision
component: tooling
severity: medium
applies_when:
  - A plugin source is loaded by both Codex and Claude Code.
  - A lifecycle hook belongs to Codex only while skills remain shared.
tags: [codex-plugins, claude-code, plugin-hooks, dual-host-packaging, validator-drift]
---

# Keep Codex-only hooks out of Claude plugin discovery

## Context

Agent Utilities is one source plugin for Codex and Claude Code. Its cleanup
skill is shared, but the root `SessionEnd` adapter is Codex-only: Codex must
discover one exact-session cleanup hook and Claude must discover none. This
boundary is required by
[the runtime-cleanup plan](../../plans/2026-08-02-001-fix-codex-runtime-cleanup-plan.md).

Codex 0.146 exhibits a contract mismatch around that boundary. Its
[manifest parser](https://github.com/openai/codex/blob/rust-v0.146.0/codex-rs/core-plugins/src/manifest.rs#L34-L55)
and [hook loader](https://github.com/openai/codex/blob/rust-v0.146.0/codex-rs/core-plugins/src/loader.rs#L1150-L1205)
accept an explicit manifest hook path, while the bundled
[plugin validator](https://github.com/openai/codex/blob/rust-v0.146.0/codex-rs/skills/src/assets/samples/plugin-creator/scripts/validate_plugin.py#L95-L111)
rejects the same `hooks` field. The mismatch is tracked upstream in
[openai/codex#27141](https://github.com/openai/codex/issues/27141).

## Guidance

Keep the host-specific hook outside the shared conventional root and select it
only from the Codex manifest:

```text
plugins/agent-utilities/
├── .codex-plugin/plugin.json    # "hooks": "./codex/hooks.json"
├── .claude-plugin/plugin.json   # shared skills; no hooks field
├── codex/hooks.json             # one Codex SessionEnd hook
└── skills/cleanup-codex/        # shared skill
```

The source contract is visible at
`plugins/agent-utilities/.codex-plugin/plugin.json:27`,
`plugins/agent-utilities/.claude-plugin/plugin.json`, and
`plugins/agent-utilities/codex/hooks.json:4`. The hook command is bounded to
`cleanup --hook` with a three-second timeout. It terminates only exact same-user
PIDs tagged with the ending session's `CODEX_THREAD_ID`; it cannot route to
whole-server reap or recycle.

Treat loader behavior and schema validation as separate release gates:

1. Install into an isolated host configuration and inspect the effective
   component inventory with the host's own loader.
2. Run the bundled validator and preserve its exact result.
3. If runtime discovery is correct but the required validator rejects a
   supported field, hold that gate as externally blocked. Do not move
   executable lifecycle behavior to a shared path merely to make validation
   green.
4. Recheck both hosts whenever either loader or validator version changes.

The `plugin packaging exposes one Codex SessionEnd hook and no Claude hook`
test in `plugins/agent-utilities/skills/cleanup-codex/scripts/cleanup-codex.test.mjs`
asserts the explicit Codex path, one cleanup `SessionEnd` event, and no
Claude manifest hook. The adjacent `Claude loader excludes the Codex-only
SessionEnd hook` test asserts Claude output `Hooks (0)`.

## Why This Matters

Both hosts auto-discover a conventional `hooks` directory containing
`hooks.json`. In
isolated checks, putting the hook there made Claude Code 2.1.220 report
`Hooks (1) SessionEnd`. That layout passes the stale Codex validator but
violates the host boundary.

The explicit Codex-only path produced the required effective inventories:
Codex 0.146 `hooks/list` returned one plugin `SessionEnd` hook from
`plugins/agent-utilities/codex/hooks.json`, while Claude reported 14 skills and
`Hooks (0)`. The bundled
validator alone returned:

```text
Plugin validation failed:
- plugin.json field `hooks` is not accepted by plugin validation
```

This is an external tooling blocker, not evidence that a cross-host hook leak
is acceptable. Runtime correctness cannot waive an explicit validation gate,
and a green validator cannot compensate for the wrong host loading executable
lifecycle behavior.

## When to Apply

Use this pattern when one plugin root serves both hosts, a hook belongs to
Codex only, and the supported Codex runtime accepts an explicit hook path.
Prefer the conventional root when both hosts should run the same hook. Prefer
separate plugin roots only when independently versioned host packages are an
accepted product boundary.

Remove the workaround only after proving the replacement layout still yields
exactly one intended Codex hook and zero Claude hooks.

## Examples

| Layout | Codex | Claude | Decision |
| --- | --- | --- | --- |
| Conventional `hooks` directory | Validator passes; hook loads | `Hooks (1)` | Reject for a Codex-only hook. |
| Separate host plugin roots | Can isolate | Can isolate | Use only when separate packaging is already in scope. |
| Explicit `plugins/agent-utilities/codex/hooks.json`, no conventional root | Hook loads; stale validator fails | `Hooks (0)` | Functionally correct; hold the validator gate. |

## Related

- [Runtime-cleanup implementation plan](../../plans/2026-08-02-001-fix-codex-runtime-cleanup-plan.md)
- [Agent Utilities release and dual-host rules](../../../AGENTS.md)
- [Cleanup skill contract](../../../plugins/agent-utilities/skills/cleanup-codex/SKILL.md)
- [Claude plugin hook locations](https://code.claude.com/docs/en/plugins-reference#hooks)
- [Upstream validator mismatch](https://github.com/openai/codex/issues/27141)
