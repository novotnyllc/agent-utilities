---
title: Fusion Report Session Helper - Plan
type: feat
date: 2026-08-17
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
---

# Fusion Report Session Helper - Plan

## Goal Capsule

- **Objective:** Make Fusion MCP report-file fallback safe and repeatable, prove it manually against a running Fusion instance, and publish the source and marketplace update.
- **Authority:** The existing Fusion report protocol and dynamic MCP discovery requirements remain authoritative.
- **Stop conditions:** Stop on report-contract mismatch, unsafe path state, unavailable live Fusion execution, signing failure, or review findings that change scope.
- **Tail ownership:** Merge Agent Utilities first, repin the marketplace to the merged source SHA, then verify the resolved SHA and installed skill bytes.

---

## Product Contract

### Summary

Add a small report-session helper around the existing generated-script contract and document one manual live-Fusion smoke workflow. Do not add STL reconstruction behavior or guidance in this release.

### Problem Frame

Fusion MCP execution may return empty standard output even when a script runs. The existing file-report fallback is correct but requires agents to assemble and clean up security-sensitive paths by hand.

### Requirements

**Report sessions**

- R1. The CLI prepares a private session containing one generated script, one absent report target, and metadata bound to a random lowercase 64-hex run ID.
- R2. The CLI verifies exactly one regular JSON report whose kind, run ID, and manifest hash match the prepared session.
- R3. Verification never deletes session artifacts.
- R4. Cleanup removes only the exact known regular files and then the exact empty session directory, rejecting aliases, symlinks, escapes, and unexpected entries.

**Live proof and delivery**

- R5. The manual smoke workflow dynamically discovers the Fusion execution capability, probes standard output, exercises one inventory report session, verifies the result, cleans up safely, and confirms Fusion remains responsive.
- R6. The live smoke remains manual-only and is never represented as a CI gate.
- R7. Both plugin manifests advance together, and the marketplace is repinned only after the source merge to the actual merged commit SHA.

### Key Decisions

- **Use a report-session helper.** (session-settled: user-approved — chosen over repeated ad-hoc path and token assembly: central validation reduces agent error.) Governs R1-R4.
- **Keep live Fusion validation manual.** (session-settled: user-approved — chosen over a CI requirement: CI has no running Fusion application.) Governs R5-R6.
- **Defer STL reconstruction changes.** (session-settled: user-directed — chosen over adding Nurb or mesh-remodeling guidance now: the user has not decided whether the skill should own it.)

### Scope Boundaries

- In scope: report-session preparation, verification, cleanup, focused tests, manual smoke documentation, version coupling, merge, repin, and post-merge proof.
- Out of scope: STL reconstruction implementation, Nurb integration, mesh conversion automation, fixed MCP tool names, and a standalone installer.

### Acceptance Examples

- AE1. Given a valid manifest and report kind, preparing a session returns private metadata plus a generated script whose report path and run ID are bound to that session.
- AE2. Given a report with a mismatched run ID, verification fails and leaves every artifact intact.
- AE3. Given an unexpected file or symlink in the session, cleanup fails without deleting the unsafe entry.
- AE4. Given running Fusion and a dynamically discovered Python execution tool, the smoke workflow retrieves and verifies an inventory report and Fusion remains interactive.

---

## Planning Contract

### Key Technical Decisions

- KTD1. Extend the existing Python CLI and script emitters; add no dependency. This keeps the report protocol in one implementation.
- KTD2. Use operating-system permissions, exclusive creation, regular-file checks, canonical-path checks, and exact allowlists at the filesystem trust boundary.
- KTD3. Treat a new disposable Fusion document whose name matches the manifest as one acceptance precondition; it may remain unsaved. Do not save or version it without express user authorization.
- KTD4. Preserve dynamic MCP discovery through the Roundhouse shim; registration metadata alone is not connectivity proof.

### Assumptions

- The current Fusion MCP Python execution capability remains available through dynamic discovery when Fusion and its MCP integration are enabled.
- The marketplace checkout is clean when the repin begins.

### Risks and Dependencies

- Fusion's empty stdout behavior may persist; the report file is the machine-readable fallback, not a claim that stdout is fixed.
- A live smoke cannot prove broad Fusion-version compatibility. It proves the current package commit against the recorded local Fusion build and MCP inventory.
- Roundhouse dynamic discovery work is external to this release and must not be bypassed with a hard-coded tool name.

---

## Implementation Units

### U1. Report session lifecycle

- **Goal:** Add safe prepare, verify, and cleanup commands around the existing report contract.
- **Requirements:** R1-R4; AE1-AE3; KTD1-KTD2.
- **Dependencies:** None.
- **Files:** `plugins/agent-utilities/skills/fusion-parametric-design/src/fusion_design/cli.py`, `plugins/agent-utilities/skills/fusion-parametric-design/src/fusion_design/scripts.py`, `plugins/agent-utilities/skills/fusion-parametric-design/tests/test_cli.py`, `plugins/agent-utilities/skills/fusion-parametric-design/tests/test_scripts.py`.
- **Approach:** Reuse manifest loading, manifest hashing, and the four existing script emitters. Validate every path and file type at each lifecycle boundary.
- **Test scenarios:**
  - Covers AE1. Prepare each supported kind and confirm strict ID format, private modes, bound script content, and an absent report target.
  - Covers AE2. Verify valid output, malformed JSON, multiple JSON values, mismatched kind, mismatched run ID, mismatched manifest hash, symlinks, and non-regular files without deletion.
  - Covers AE3. Clean a valid session, tolerate an already-absent session, and reject aliases, escapes, symlinks, and unexpected entries without partial unsafe deletion.
- **Verification:** Focused Fusion skill tests and Python compilation pass with no new dependency.

### U2. Manual live-Fusion smoke workflow

- **Goal:** Replace ad-hoc report fallback instructions with one bounded manual acceptance path.
- **Requirements:** R5-R6; AE4; KTD3-KTD4.
- **Dependencies:** U1.
- **Files:** `plugins/agent-utilities/skills/fusion-parametric-design/SKILL.md`, `plugins/agent-utilities/skills/fusion-parametric-design/README.md`, `plugins/agent-utilities/skills/fusion-parametric-design/docs/live-fusion-acceptance.md`.
- **Approach:** Start from dynamic capability discovery, record a unique stdout probe, prepare one inventory session, execute the generated Python in a new disposable document, verify, clean up, and record UI responsiveness. Leave it unsaved unless the user expressly authorizes saving or versioning.
- **Execution note:** Run this only with a person present and Fusion open; do not add it to CI.
- **Test scenarios:**
  - Covers AE4. A live disposable document produces a verified inventory report and remains responsive after event pumping; saving or versioning is not part of acceptance without express authorization.
  - An unavailable execution capability or report mismatch produces explicit failure evidence and no compatibility claim.
- **Verification:** The checked-in workflow is executable as written against the current live Fusion instance, and the run evidence records Fusion build, capabilities, endpoint/client, package commit, document, reports, and deviations.

### U3. Source and marketplace release

- **Goal:** Publish the plugin change and bind marketplace metadata to the merged source bytes.
- **Requirements:** R7.
- **Dependencies:** U1, U2.
- **Files:** `plugins/agent-utilities/.codex-plugin/plugin.json`, `plugins/agent-utilities/.claude-plugin/plugin.json`; target repo `marketplace`: `.agents/plugins/marketplace.json`, `.claude-plugin/marketplace.json`, `.agents/plugins/plugin-versions.json`.
- **Approach:** Bump both source manifests to 0.6.8, review and merge source, then use the marketplace repin tool with the actual merged source SHA.
- **Execution note:** Prefer smoke-first evidence before publication because the live dependency cannot run in CI.
- **Test scenarios:**
  - Both source manifests parse and carry the same version.
  - Marketplace repin checks and self-tests agree on version 0.6.8 and the exact 40-character source SHA.
  - Installed nested skill bytes resolve to the released source after refresh.
- **Verification:** Source and marketplace changes are merged, remote main contains both merges, and resolved marketplace/install evidence matches the merged source bytes.

---

## Verification Contract

- Run `plugins/agent-utilities/skills/fusion-parametric-design/scripts/test.sh` for the focused Python suite and compile check.
- Run `npx tsx plugins/agent-utilities/skills/skill-cleaner/scripts/skill-cleaner.test.ts` for repository skill validation.
- Parse both plugin manifests and validate every skill frontmatter name against its directory.
- Run the manual live-Fusion inventory smoke and retain its evidence.
- Run the marketplace repin check and self-test after the source merge.
- Run adversarial pre-commit review and independent Sol review before merge.

---

## Definition of Done

- U1 and U2 satisfy their test scenarios without weakening the existing report contract.
- Agent Utilities 0.6.8 is merged and proven on remote main.
- Marketplace metadata is repinned to the actual merged Agent Utilities SHA, merged, and proven on remote main.
- The current installed skill resolves to the released bytes, not merely the released version string.
- No abandoned installer, checksum manifest, STL reconstruction code, or speculative mesh workflow appears in the diff.
