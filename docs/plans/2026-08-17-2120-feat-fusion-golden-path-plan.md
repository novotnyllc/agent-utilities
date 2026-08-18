---
title: "feat: Add a live Fusion project golden path"
date: 2026-08-17
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
---

# Summary

Turn the existing electronics-enclosure example into a repeatable project-level acceptance path that proves manifest validation, generated transactions, real positive-volume Fusion geometry, verification, and idempotence against a disposable live document.

## Problem Frame

The skill has strong unit coverage and a comprehensive manual acceptance document, but its positive control still asks a tester to construct geometry by hand. That leaves the most important manifest-to-Fusion path difficult to repeat and easy to perform inconsistently.

## Requirements

- **R1.** Reuse `examples/electronics-enclosure/fusion-project.json` as the canonical fixture.
- **R2.** Provide a generated or checked-in live-only transaction that creates the fixture's positive-control B-Rep solids without touching an existing user document.
- **R3.** Prove the positive path, a second idempotent run, and the existing empty-model negative control through machine-readable reports.
- **R4.** Keep manufacturing intent slicer-neutral; PrusaSlicer translation and STL reconstruction remain separate follow-up issues.

## Scope Boundaries

In scope: one disposable live-Fusion golden path, its offline contract test, and concise acceptance instructions.

### Deferred to Follow-Up Work

- STL reconstruction and mesh-to-parametric decision support.
- Slicer-neutral printable-part/orientation/support intent beyond what the fixture needs.
- PrusaSlicer plate/project generation and profile translation.
- Variant batch verification/export and native Windows module-cache coverage.

## Key Technical Decisions

1. **KTD1: Extend the existing example.** (session-settled: user-approved — chosen over a second fixture: the existing enclosure already exercises parameters, assemblies, clearances, interference, and fit coupons.)
2. **KTD2: Live Fusion remains a manual release gate.** CI proves script generation and contract consistency; only a running Fusion instance proves the API and geometry path.
3. **KTD3: Do not add slicer behavior here.** The golden path stops at verified printable bodies and recorded manufacturing intent.

## Implementation Units

### U1. Executable positive-control fixture

**Goal:** Create the exact B-Rep solids and placements required by the enclosure manifest in a disposable parametric Fusion document.

**Requirements:** R1, R2, R3; KTD1, KTD2.

**Dependencies:** None.

**Files:**

- `plugins/agent-utilities/skills/fusion-parametric-design/examples/electronics-enclosure/`
- `plugins/agent-utilities/skills/fusion-parametric-design/tests/test_golden_path.py`
- `plugins/agent-utilities/skills/fusion-parametric-design/docs/live-fusion-acceptance.md`

**Approach:** Reuse the stdout-delimited manifest-identity contract. Add only the missing example-specific positive-control geometry transaction, with event pumping and active-document validation matching existing generated scripts.

**Execution note:** Prove the script contract offline first, then run it through the live MCP in a newly created disposable document and restore the previously active document.

**Test scenarios:**

1. The canonical manifest validates and all generated scripts compile.
2. The positive-control builder names every required component and dimension from the manifest contract and compiles offline.
3. Live execution creates positive-volume solids; verification returns `ok: true`.
4. A second live execution is idempotent and leaves no duplicate bodies or components.
5. Running verification before the builder preserves the expected empty-model failure.

**Verification:** The host test is repeatable without Fusion, and the recorded live run returns identity-bound reports for the negative and positive controls.

### U2. Release and installed-byte proof

**Goal:** Publish the skill change under a new plugin version and prove the marketplace and installed artifact resolve to the merged bytes.

**Requirements:** R3.

**Dependencies:** U1.

**Files:**

- `plugins/agent-utilities/.codex-plugin/plugin.json`
- `plugins/agent-utilities/.claude-plugin/plugin.json`
- Marketplace manifests updated by `scripts/repin` after source merge.

**Approach:** Run the scoped Fusion suite, repository skill gate, live MCP acceptance, deep pre-commit review, source PR settlement, marketplace repin, and installed-byte comparison.

**Test scenarios:**

1. Both plugin manifests parse and carry the same new version.
2. The complete Fusion test suite and skill-cleaner gate pass unmasked.
3. Marketplace pins the actual merged source SHA and passes its repin check.
4. Installed golden-path files match the merged source bytes.

**Verification:** Source and marketplace PRs are merged, and post-merge source, catalog, and installed states are independently proven.

## Verification Contract

- Offline: canonical fixture validation, emitted-script compilation, focused golden-path test, full Fusion suite, skill-cleaner gate, manifest/frontmatter checks.
- Live: new disposable parametric document, empty-model negative control, positive-control build, passing verification, idempotent rerun, machine-readable report identity, and restoration of the user's prior active document.
- Release: merged source SHA, marketplace pin/version, and installed-byte equality.

## Definition of Done

- The existing example has one documented command/path that builds and verifies its positive control in live Fusion.
- Offline coverage fails if the manifest and builder drift.
- The live run is recorded with exact Fusion/MCP version and reports.
- Focused deferred GitHub issues exist for STL reconstruction, generic manufacturing intent, PrusaSlicer translation, variants, and Windows module-cache support.
- The versioned plugin is merged, repinned, installed, and byte-verified.
