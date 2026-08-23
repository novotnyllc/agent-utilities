---
title: Fable Review Launch Contract - Plan
type: fix
date: 2026-08-03
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
---

# Fable Review Launch Contract - Plan

## Goal Capsule

- **Objective:** Make the existing CE-owned Claude/Fable review route observable, MCP-isolated, bounded, and reusable from the shared Agent Utilities routing policy.
- **Authority:** The current host's authenticated Claude CLI and observed stream receipts are runtime evidence; repository policy and the existing no-new-runner decision constrain the source change.
- **Scope:** Change the shared routing reference, add one dependency-free receipt validator, and extend the existing contract test. Do not edit Oracle, Compound Engineering source/cache, authentication, user settings, or running processes.
- **Terminal state:** One focused PR with local contract checks and the live host acceptance evidence recorded in the PR description.

---

## Product Contract

### Problem Frame

The shipped workflows allow Fable only through a supported CE cross-model path but do not define the launch preflight, isolation flags, progress signal, success receipt, wall-clock bounds, or escalation behavior. Plain `claude -p` text output is silent until completion, and ordinary startup inherits the enabled Context7 plugin. A caller can therefore mistake buffered output for a startup hang and can start an unrelated MCP process.

### Requirements

- R1. Define one shared Claude subscription/Fable review launch contract inherited by Goal Driven Delivery, Task Orchestrator, and Thermos through `provider-task-routing.md`.
- R2. Require a secret-free, fail-closed decision table that verifies a supported CLI surface, `claude.ai` first-party authentication, the absence of provider redirect environment names, and an allowed managed-settings posture without exposing values. Unknown or redirected states block before egress.
- R3. Require the full `claude-fable-5` model ID, no `--fallback-model`, `--safe-mode`, strict empty MCP configuration, plan permissions, the fixed `Read,Grep,Glob` tool list, and `--no-session-persistence` for review launches; allow the minimal preflight canary to disable tools. Forbid `Bash`, `--bare`, direct Agent Utilities runners, and `--bg` in print mode.
- R4. Require streamed JSON progress and accept review evidence only when the process exits zero, `system.init.model` attests the required Fable identity, no `model_refusal_fallback` occurs, every assistant identity remains Fable, terminal model usage includes Fable and no unapproved primary/fallback family, and the terminal result is not an error. Claude's observed auxiliary Haiku title-generation usage is allowed but never satisfies the Fable requirement. On refusal fallback or a non-Fable assistant identity, the caller immediately terminates only its owned review process group and preserves the partial private stream.
- R5. Require external startup, idle, and total deadlines under the existing detached supervisor/log; ambiguous or charged attempts are inspected, never silently retried.
- R6. After a refusal only, allow exactly one fresh Fable-only attempt with a semantically equivalent defensive/read-only rephrase, a finite reason code, and private rationale. Any second refusal or other failure blocks and returns control; no Opus, Sol, or other model silently substitutes. A provider fallback may be charged and reported but never accepted as Fable evidence.

### Acceptance Examples

- AE1. A minimal no-tools Fable canary emits `system.init` and `result`, exits zero, and creates no Context7 process.
- AE2. A read-only review uses `Read`, reports `claude-fable-5`, completes under the caller watchdog, and creates no Context7 process.
- AE3. An invalid model is rejected because exit status is nonzero and `is_error` is true even if `subtype` says `success`.
- AE4. A stream that initializes as `claude-fable-5` and later emits `system.subtype:model_refusal_fallback` to Opus is rejected before its review is accepted.
- AE5. A stalled or silent launch reaches a bounded failure state with its private log/session evidence preserved and is not automatically respawned.

### Scope Boundaries

- No new Claude wrapper, model router, provider abstraction, authentication repair, or session manager.
- No changes to Oracle, Compound Engineering, user Claude configuration, Context7 installation, or unrelated processes.
- No live authenticated Claude calls in CI; live acceptance remains a host-scoped preflight.

---

## Planning Contract

- KTD1. Keep the contract in `provider-task-routing.md`, which all three model-launch workflows already consume, instead of copying launch prose into each skill.
- KTD2. Process launch, private logging, deadlines, and ownership-scoped termination remain with the caller's existing detached supervisor. A consumer whose CE adapter cannot preserve the raw stream and enforce this contract must report Fable unsupported and block; Agent Utilities does not add a Claude runner.
- KTD3. Treat stream events as progress only. Success is the conjunction of exit zero, required `system.init.model`, no refusal-fallback event, Fable-only assistant identities, allowed terminal model usage, and a terminal result whose `is_error` is not true. Do not reject the observed auxiliary Haiku title-generation entry or let it substitute for Fable.
- KTD4. Use safe mode plus strict empty MCP. `--bare` is ineligible because it disables OAuth/keychain auth, and `--bg` is incompatible with print mode.
- KTD5. Keep raw JSONL/debug output private; the routing receipt carries metadata and reason codes only.
- KTD6. Add one dependency-free stream receipt validator as the production owner of the identity/error predicate. It reads captured JSONL and never launches Claude, handles authentication, or owns process lifecycle.

---

## Implementation Units

### U1. Shared Fable launch contract

- **Goal:** Add the verified preflight, invocation, progress, deadline, receipt, and fallback/block rules.
- **Files:** `plugins/agent-utilities/references/provider-task-routing.md`
- **Patterns:** Preserve the file's transport/model separation and metadata-only receipt boundary.
- **Covers:** R1-R6, AE1-AE5, KTD1-KTD6.

### U2. Stream receipt validator

- **Goal:** Validate Fable-only JSONL evidence, including refusal fallback, assistant/model-usage drift, error results, missing/truncated terminal output, and success.
- **Files:** `plugins/agent-utilities/scripts/claude-fable-review-receipt.mjs`
- **Patterns:** Dependency-free Node CLI; consume a file or stdin; emit metadata-only success/failure without raw review content.
- **Covers:** R4-R6, AE1-AE5, KTD3, KTD5-KTD6.

### U3. Contract regression checks

- **Goal:** Pin the safety flags, success predicate, deadline strategy, escalation, and no-runner boundary without making authenticated calls in CI.
- **Files:** `plugins/agent-utilities/skills/task-orchestrator/scripts/delivery-contracts.test.mjs`
- **Patterns:** Reuse the existing dependency-free `node:test` assertions over shared workflow references and execute the production validator against inline JSONL fixtures.
- **Covers:** R1-R6, AE1-AE5.

---

## Verification Contract

| Gate | Command or evidence | Done signal |
|---|---|---|
| Shared contract | `node --test plugins/agent-utilities/skills/task-orchestrator/scripts/delivery-contracts.test.mjs` | All contract tests pass. |
| Patch hygiene | `git diff --check` | No whitespace errors. |
| Minimal live canary | Host-scoped safe/strict Fable prompt with no tools | Exit zero, Fable init receipt, non-error terminal result, no new Context7 PID. |
| Read-only live review | Host-scoped safe/strict Fable review using `Read` | Read tool observed, bounded completion, no new Context7 PID. |
| Failure canary | Unsupported model under an outer watchdog | Both the nonzero exit and error result are observed within the bound. |
| Refusal fallback | Production validator against a stream fixture with Fable init followed by `model_refusal_fallback` to Opus | Review evidence is rejected despite the valid initial identity. |

---

## Definition of Done

- The shared contract tells callers exactly how to preflight, launch, observe, bound, validate, detach, and escalate a Fable review.
- The production validator rejects refusal fallback, model drift, error output, nonzero exit evidence, and incomplete streams while returning only metadata.
- The contract preserves OAuth/keychain auth while disabling plugin, hook, and MCP customizations.
- Focused tests prevent regression to plain buffered output, init-only identity checks, subtype-only success, unbounded waiting, `--bare`, `--bg`, or a new Agent Utilities runner.
- Oracle, Compound Engineering, user configuration, and unrelated processes remain untouched.
