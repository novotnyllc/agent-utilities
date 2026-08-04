---
title: Oracle CLI Bootstrap - Plan
type: fix
date: 2026-08-03
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
---

# Oracle CLI Bootstrap - Plan

## Goal Capsule

- **Objective:** Make every Oracle skill invocation resolve a supported Oracle CLI at version 0.17.0 or newer without repeating package discovery in delivery tasks.
- **Authority:** The skill owns its narrow prerequisite lifecycle. Existing Oracle configuration, authentication, sessions, and browser state remain user-owned.
- **Execution profile:** Add one skill-local preflight helper, one hermetic acceptance test, and the minimum skill documentation needed to invoke the returned binary and avoid incompatible browser profile modes.
- **Terminal state:** The change is complete when missing, current, and stale installations follow the required lifecycle; local CLI smoke checks pass; and the source change passes review and CI.
- **Tail ownership:** Goal Driven Delivery owns delivery through merge and post-merge proof. This plan does not modify Compound Engineering or Fleet Privilege Brokers.

---

## Product Contract

### Summary

The Oracle skill will run one bounded preflight before its first Oracle command. The default path prefers the supported `steipete/tap/oracle` Homebrew formula and falls back to the supported `@steipete/oracle` npm package at the stable user-local prefix when Homebrew cannot repair the installation. It installs when absent, updates only below 0.17.0, and returns the exact executable path. Other installations remain supported through an explicit validation-only `ORACLE_BIN` override.

### Problem Frame

The skill requires Oracle 0.17.0 or newer but currently assumes that a bare `oracle` executable is already on `PATH`. That failed in the delegated Codex environment even though its normal login shell included user-local tools. Dependency discovery and repair therefore leak into every delivery task, and non-login shells can inherit different paths.

### Requirements

#### Invocation lifecycle

- R1. Every Oracle skill invocation must run one preflight before its first Oracle command and use the exact executable path returned by that preflight.
- R2. With no `ORACLE_BIN` override, the preflight must prefer `steipete/tap/oracle`, then use `@steipete/oracle` at `$HOME/.local` when Homebrew is unavailable or cannot repair a missing or stale formula.
- R3. An installed `steipete/tap/oracle` formula at or above 0.17.0 must produce no install or upgrade action.
- R4. The preflight must post-verify the resolved executable. An invalid explicit override fails immediately; the default path fails closed only after every supported package-manager repair path is unavailable or still produces an invalid, stale, or missing executable.
- R5. A caller-provided `ORACLE_BIN` must resolve to an absolute path to an executable regular file, pass version validation, and be returned without Homebrew mutation.
- R9. The default path must resolve Homebrew from supported canonical absolute locations and must not execute a conflicting PATH-shadowed `brew`.
- R10. Browser guidance must detect that nested `browser.manualLogin: true` conflicts with `--copy-profile`, preserve the user's config/auth state, and require one explicit profile mode instead of retrying the incompatible combination.

#### Safety and compatibility

- R6. Package lifecycle commands must not read, write, remove, or migrate `~/.oracle`, `ORACLE_HOME_DIR`, browser profiles, cookies, credentials, sessions, or project Oracle configuration.
- R7. The helper must prevent Homebrew cleanup, installed-dependent checks, and prompts while never uninstalling, reinstalling, adding a wrapper, editing shell startup files, or performing an unconditional upgrade.
- R8. The skill must remain usable by Codex and Claude Code and must not rely on an installed plugin-cache path.

### Acceptance Examples

- AE1. **Covers R1-R4 and R6-R7.** Given no installed formula, when preflight runs, then it performs one formula install, verifies Oracle 0.17.0 or newer, returns the exact formula binary, and leaves Oracle user state unchanged.
- AE2. **Covers R1, R3-R4, and R6-R7.** Given an installed `steipete/tap/oracle` formula at 0.17.0 or newer, when preflight runs twice, then both calls return the same executable and neither call installs nor upgrades anything.
- AE3. **Covers R1-R4 and R6-R7.** Given a Homebrew Oracle version below 0.17.0, when preflight runs, then it performs one minimum-version-bounded upgrade, post-verifies the result, and the second call is a no-op.
- AE4. **Covers R4-R5.** Given a missing, stale, or invalid `ORACLE_BIN` override, when preflight runs, then it fails without mutating Homebrew or Oracle user state.
- AE5. **Covers R2-R4 and R6-R7.** Given Homebrew cannot install or upgrade Oracle, when preflight runs twice, then the first call installs the pinned npm package at `$HOME/.local`, the second call returns the same binary without retrying Homebrew or npm, and Oracle user state remains unchanged.
- AE6. **Covers R6 and R10.** Given nested `browser.manualLogin: true`, when a copied profile is requested, then the skill explains the conflict and requires the user to choose a profile mode without editing config or auth state.

### Scope Boundaries

- Do not modify Compound Engineering, Fleet Privilege Brokers, installed plugin caches, dotfiles, or Oracle auth/config/session data.
- Do not add a daemon, hook, background updater, custom lock, package-manager abstraction, or fallback package manager.
- Do not fall back to npx, pnpm, or an arbitrary PATH binary. The only automatic fallback is the pinned upstream npm package at `$HOME/.local`.
- Do not bump or publish the plugin version as part of this focused source fix.

---

## Planning Contract

### Key Technical Decisions

- KTD1. **Preflight is part of Oracle skill entry.** Run the helper once per skill invocation and use its returned absolute path for later Oracle commands. (session-settled: user-directed — chosen over per-task dependency discovery: the prerequisite must repair itself instead of burdening every delivery task.) Governs R1 and R8.
- KTD2. **Homebrew is preferred; stable npm is the bounded fallback.** Resolve Homebrew from supported canonical absolute locations, reject PATH shadowing, and use the upstream-supported `steipete/tap/oracle` formula. Inspect the installed version before any network-capable mutation. Run missing and stale mutations with `--no-ask`, `HOMEBREW_NO_INSTALL_CLEANUP=1`, and `HOMEBREW_NO_INSTALLED_DEPENDENTS_CHECK=1`; use Homebrew's minimum-version upgrade option for the stale case. If Homebrew is unavailable or repair fails, install the pinned upstream npm package at `$HOME/.local`; a current npm binary short-circuits later failed Homebrew repairs. Governs R2-R4, R7, and R9.
- KTD3. **Explicit binary overrides are validation-only.** Preserve the existing `ORACLE_BIN` contract without replacing an unknown executable or silently installing a different binary behind the override. Governs R4-R5.
- KTD4. **Tests fake the lifecycle boundary.** Use a temporary fake Homebrew executable, formula prefix, and Oracle home so acceptance tests prove decisions and state preservation without network, browser login, credentials, or live package mutation. Governs R2-R7.
- KTD5. **Profile modes remain user-owned and mutually exclusive.** Treat nested `browser.manualLogin` as the effective config key, never rewrite it automatically, and do not combine it with `--copy-profile`. Governs R6 and R10.

### Assumptions

- The installed Homebrew version supports `brew upgrade --minimum-version`, as verified on the target host.
- Invoking the Oracle skill authorizes only the narrow prerequisite install or stale-version upgrade described by R2; API calls retain their separate explicit cost-consent rule.
- A clean non-login shell may omit Homebrew from `PATH`; using the returned absolute formula path makes the skill independent of that difference.

### Risks and Dependencies

- Homebrew may refresh tap metadata during an install or stale-version upgrade. Current installations avoid that path entirely because the helper checks the installed version first.
- Homebrew can reject installation for host toolchain reasons; the pinned stable-prefix npm fallback keeps the skill usable without changing Xcode or shell profiles.
- Upstream release and formula versions can diverge briefly. Post-verification prevents the skill from running a version below its documented minimum.
- `steipete/tap` is a third-party Homebrew tap. Installing the formula may add that tap to Homebrew; Homebrew's checksum verification and R4 post-verification are the accepted integrity controls, and an unreachable or invalid tap fails closed.
- The plugin's imported Oracle skill may be refreshed later. `UPSTREAM.md` adaptation notes must preserve this local bootstrap behavior during future refreshes if the implementation changes those notes.

---

## Implementation Units

### U1. Add bounded Oracle lifecycle preflight

- **Goal:** Implement the missing, current, stale, override, and failure decisions in one skill-local shell helper.
- **Requirements:** R2-R7, R9; KTD2-KTD4.
- **Dependencies:** None.
- **Files:** `plugins/agent-utilities/skills/oracle/scripts/ensure-oracle.sh`, `plugins/agent-utilities/skills/oracle/scripts/ensure-oracle.test.mjs`.
- **Approach:** Resolve the explicit override first. Otherwise locate Homebrew at supported canonical absolute paths, inspect only the named formula, compare numeric version components with 0.17.0, run the narrow install or minimum-version upgrade only when required, and fall back to the pinned stable-prefix npm package only when Homebrew is unavailable or repair fails. Emit only the post-verified absolute executable path on stdout.
- **Execution note:** Start with the hermetic missing/current/stale acceptance matrix; never manufacture those states against the live Homebrew installation.
- **Patterns to follow:** Skill-owned script and `node:test` pairing under `plugins/agent-utilities/skills/cleanup-codex/scripts/`; dependency-free assertions under `plugins/agent-utilities/skills/task-orchestrator/scripts/`.
- **Test scenarios:**
  - Covers AE1. A missing formula triggers one install, returns the exact executable, remains current on the second invocation, and preserves a byte-checked Oracle-state sentinel.
  - Covers AE2. Versions 0.17.0 and newer make zero mutation calls across repeated invocations.
  - Covers AE3. Version 0.16.x triggers one minimum-version upgrade, verifies the resulting version, and makes the second invocation a no-op.
  - Version 0.9.x is stale under numeric component comparison and cannot pass through lexical ordering.
  - Covers AE4. Relative, missing, non-regular, non-executable, stale, and invalid explicit overrides fail without Homebrew calls.
  - A fake `brew` earlier on PATH is never executed when a supported canonical Homebrew executable exists.
  - Missing and stale mutations carry the no-prompt, no-cleanup, and no-installed-dependent-check controls.
  - Missing Homebrew and failed or invalid Homebrew repairs fall back to npm; an invalid, stale, or missing npm result then fails closed with actionable diagnostics.
  - Failed Homebrew repair falls back once to the stable npm prefix, and a second invocation performs no package mutation or repeated Homebrew repair.
- **Verification:** The helper passes shell syntax validation and its focused Node test without network, live Homebrew mutation, or Oracle user-state changes.

### U2. Make preflight mandatory in the skill contract

- **Goal:** Ensure both supported agent harnesses run the helper before Oracle and retain the local adaptation during future upstream refreshes.
- **Requirements:** R1, R8, R10; KTD1, KTD5.
- **Dependencies:** U1.
- **Files:** `plugins/agent-utilities/skills/oracle/SKILL.md`, `README.md`, `UPSTREAM.md`.
- **Approach:** Add an early setup step that records the helper's returned absolute path in `ORACLE_CLI` and uses it for every subsequent Oracle command. Retain `ORACLE_BIN` only as the caller-owned validation-only override. Document the focused test command, local lifecycle adaptation, a safe redacted probe for nested `browser.manualLogin`, and the mutually exclusive manual-login/copied-profile modes without changing unrelated Oracle guidance or user state.
- **Patterns to follow:** The binary/install metadata shape in `plugins/agent-utilities/skills/one-password/SKILL.md`; repository validation commands in `README.md`; local adaptation notes in `UPSTREAM.md`.
- **Test scenarios:**
  - The skill names the helper as mandatory before its first Oracle command and does not retain a normal path that bypasses preflight.
  - The documented required version, helper minimum version, Homebrew formula, and focused test command remain consistent.
  - A safe probe reports only `browser.manualLogin=missing|true|false|invalid`, and nested `browser.manualLogin: true` is documented as incompatible with `--copy-profile`; no automatic config edit is recommended.
- **Verification:** Oracle skill frontmatter validates, both plugin manifests parse, the README command runs, and a source scan finds no changed normal workflow command that bypasses the preflight result.

---

## Verification Contract

| Gate | Scope | Done signal |
| --- | --- | --- |
| Focused lifecycle acceptance | `node --test plugins/agent-utilities/skills/oracle/scripts/ensure-oracle.test.mjs` | Missing, current, stale, Homebrew-to-npm fallback, override, failure, idempotency, and state-preservation cases pass offline. |
| Shell syntax | `bash -n plugins/agent-utilities/skills/oracle/scripts/ensure-oracle.sh` | The helper parses with the macOS system Bash. |
| Source validation | Changed skill frontmatter, both plugin manifest JSON files, and `git diff --check` | All maintained source artifacts validate with no installed-cache edits. |
| Live CLI no-op | Run the source helper, then `--version`, `--help --verbose`, and one no-cost `--dry-run summary` through its returned path | The live Homebrew 0.17.0 installation stays current and all CLI checks exit successfully. |
| Shell visibility | Compare bare command resolution in normal login and non-login zsh, then run the helper from a clean non-login zsh without Homebrew on `PATH` | Normal shells resolve the same `/opt/homebrew/bin/oracle`; the clean shell returns that same absolute formula path and successfully runs Oracle through it even when bare `oracle` is absent. |

---

## Definition of Done

- U1 and U2 satisfy their cited requirements and acceptance examples.
- Current Oracle installations take a local no-op path with no install or upgrade call.
- Missing and stale cases prefer `steipete/tap/oracle`, use the pinned stable-prefix npm fallback only when Homebrew cannot repair, then post-verify Oracle 0.17.0 or newer.
- Browser profile guidance detects the nested manual-login/copied-profile conflict without modifying user state.
- Oracle config, auth, browser profiles, and sessions remain unchanged.
- The focused tests, syntax check, source validations, live no-cost CLI checks, shell-visibility check, independent review, PR CI, merge proof, and post-merge smoke all pass.
- No abandoned helper, wrapper, shell-profile edit, package-manager abstraction, or unrelated change remains in the diff.
