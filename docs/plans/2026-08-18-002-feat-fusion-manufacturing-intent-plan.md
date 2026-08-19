---
title: "feat: Slicer-neutral printable-part and manufacturing intent"
date: 2026-08-18
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
origin: https://github.com/novotnyllc/agent-utilities/issues/18
---

# Summary

Extend the fusion-project manifest with a slicer-neutral `printable_parts` section — stable identity, quantity, orientation, support policy, strength intent, protected features, and material assumptions per part — validated fail-closed, verified against live geometry (root-context transforms recorded), and carried into the export handoff index so any slicer adapter (#22 first) can consume it without a printer/filament/process profile ever entering the manifest.

---

## Problem Frame

The manifest records only `verification.expected_print_parts` (component paths). An agent has no structured way to state what should be printed and why — orientation, supports, strength, protected surfaces — before a particular slicer translates it. Issue #24's export handoff carries geometry identity but no build intent; issue #22's PrusaSlicer adapter needs that intent as input.

---

## Requirements

- **R1.** New optional top-level manifest section `printable_parts`: a list of part objects with stable `id`, `path` (component-tree path), optional `body_name`, and `quantity` (integer ≥ 1, default 1). Validation rejects duplicate ids, duplicate paths, paths absent from `component_tree`, and any mismatch with `verification.expected_print_parts` (when `printable_parts` is present, its path set must equal the expected-print-parts set — one source of truth for *which* parts, two layers of *what about them*).
- **R2.** Per part: `print_as` (`separate` | `assembled`), `orientation` `{contact_face: one of +X,-X,+Y,-Y,+Z,-Z; rationale: non-empty string; allowed_alternatives: list of the same enum, not containing contact_face}`.
- **R3.** Per part: `support_policy` — `none` | `build-plate-only` | `everywhere` | `explicit-regions`; `explicit-regions` requires a non-empty `support_regions` list of `{kind: enforcer|blocker, description}`.
- **R4.** Per part: `strength` `{min_perimeters: integer ≥ 1, infill_percent: {target: 0–100, min?: ≤ target, max?: ≥ target}}` — intent, not a slicer profile.
- **R5.** Per part: `protected_features` list of `{kind: critical-surface|hole|bridge|overhang|mating-face|cosmetic-face, description}` (may be empty) that support placement must protect.
- **R6.** Per part: `material` `{assumption: non-empty string (e.g. "PETG"), source_id?: declared manifest source, status: provisional|coupon_verified}` — links geometry-relevant material assumptions to an explicit decision; the full material gate is issue #21, which will build on this field.
- **R7.** The generated verification transaction records root-context occurrence transforms (16-tuple, nullable) for every expected print part alongside the existing bounds, and fails no differently otherwise (pure additive report key).
- **R8.** The export handoff index (issue #24's `emit-export`) carries a `manufacturing_intent` block per artifact when the manifest declares `printable_parts` — the slicer-neutral handoff consumable by #22 — and omits it (key absent) when the manifest doesn't. No printer, filament, or process profile fields exist anywhere in the manifest or index.
- **R9.** Schema JSON and hand-written validator updated together, kept honest by a NEW dependency-free parity test (schema enum/property sets asserted equal to the validator's module-level constants); existing manifests without `printable_parts` remain valid (`schema_version` stays 1); all existing emitters/tests keep passing byte-guards after regeneration.

---

## Assumptions

Headless-planned; inferred bets recorded:

- **`printable_parts` is a new optional top-level section**, not a reshape of `verification.expected_print_parts` — reshaping would break every existing manifest and generated script for no gain; the equality check keeps the two consistent.
- **Orientation is an axis enum + rationale**, not a quaternion/matrix — slicer-neutral minimum the issue asks for; #22 maps it to PrusaSlicer rotations.
- **`body_name` is an optional identity assertion, not disambiguation**: it is checked *after* single-solid resolution succeeds — a multi-solid component still fails `ambiguous-body` regardless of the declared name; a resolved solid whose name mismatches fails `body-name-mismatch`. It never widens which bodies are exportable.
- **Transform unit convention**: `occurrence_transforms` (verify report) and the export index's `transform` both record raw Fusion `transform2.asArray()` — translation components in **centimetres** (Fusion internal units), unconverted, unlike the `*_mm` keys. U4 documents this in `references/verification-contract.md`.
- **Forbidden-claim guard is scoped**: the index-key sweep skips the `manufacturing_intent` subtree (declared intent such as `support_policy` is slicer-neutral input, not a slicing claim); `supports`/`support_policy`/`printer`/`filament`/`process_profile` remain forbidden everywhere else.
- **`print_as` and `quantity` are declarative intent** consumed by adapters (#22): `assembled` marks parts an adapter must keep grouped as one printed object cluster; `quantity` multiplies at plate-arrangement time, never at export (each part exports once).
- The live enclosure example demonstrates three parts with different intent: base (`-Z` contact, no supports), lid (`+Z` contact, build-plate-only), coupon (`-Z`, none, cosmetic top face protected).

---

## Key Technical Decisions

1. **KTD1: One part list, two layers.** `verification.expected_print_parts` stays the geometric verification hook; `printable_parts` adds intent. Set-equality validation prevents drift. (Chosen over merging into one section: avoids schema_version bump and mass regeneration of checked-in scripts for consumers that don't need intent.)
2. **KTD2: Intent flows through the export index, not a new artifact.** #22 consumes verified exports + intent; the index is already identity/hash-bound, so embedding `manufacturing_intent` there gives the adapter one evidence-bound input. Emit-time embedding keeps the generated script a pure function of manifest + config (byte-guard safe).
3. **KTD3: Closed enums everywhere** (`print_as`, `contact_face`, `support_policy`, `support_regions.kind`, `protected_features.kind`, `material.status`) — mirrors the repo's closed-world validator style; unknown values fail validation rather than passing as strings.
4. **KTD4: Transforms recorded via the existing `transform2` pattern** (`positive_control._require_identity_transform` reads it; verify will record it nullable) — additive report keys only, no failure-token changes in verify.

---

## Implementation Units

### U1. Manifest validation and schema for `printable_parts`

**Goal:** `manifest.py` validates the new section per R1–R6; `schema/fusion-project.schema.json` mirrors it; lockstep tests.

**Requirements:** R1–R6, R9; KTD1, KTD3.

**Dependencies:** None.

**Files:**
- `plugins/agent-utilities/skills/fusion-parametric-design/src/fusion_design/manifest.py`
- `plugins/agent-utilities/skills/fusion-parametric-design/schema/fusion-project.schema.json`
- `plugins/agent-utilities/skills/fusion-parametric-design/tests/test_manifest.py`

**Approach:** Follow the existing closed-world validator style (`_reject_unknown_fields`, `ValidationIssue` codes). New issue codes, kebab-case like existing ones (e.g. `printable-part-duplicate-id`, `printable-part-unknown-path`, `printable-parts-mismatch-expected`, `printable-part-invalid-orientation`, `printable-part-invalid-support-policy`, `printable-part-invalid-strength`, `printable-part-invalid-material`). Add a `Manifest.printable_parts` property (empty tuple/list when absent).

**Test scenarios:**
- Valid manifest without `printable_parts` still validates (back-compat).
- Valid three-part section validates.
- Each rejection: duplicate id, duplicate path, path not in component_tree, path-set ≠ expected_print_parts, bad contact_face, contact_face repeated in allowed_alternatives, unknown support_policy, `explicit-regions` with empty/missing regions, min_perimeters 0, infill target 101 / min > target / max < target, unknown protected-feature kind, empty material assumption, unknown material status, `source_id` not among declared sources, unknown extra field anywhere in the section.
- Schema cross-check cases in test_manifest.py stay in lockstep (same fixtures validated both ways where the file already does that).

**Verification:** `scripts/test.sh` green.

---

### U2. Example manifest intent + verification transform recording

**Goal:** The enclosure example declares three printable parts with different intent; `emit_verification_script` records root-context transforms for expected print parts.

**Requirements:** R7, R9; KTD4; live example per assumption 4.

**Dependencies:** U1.

**Files:**
- `plugins/agent-utilities/skills/fusion-parametric-design/examples/electronics-enclosure/fusion-project.json`
- `plugins/agent-utilities/skills/fusion-parametric-design/src/fusion_design/scripts.py`
- `plugins/agent-utilities/skills/fusion-parametric-design/examples/electronics-enclosure/generated/` (regenerate all — manifest hash changes every checked-in script)
- `plugins/agent-utilities/skills/fusion-parametric-design/examples/electronics-enclosure/sample-verification-report.json` (regenerate)
- `plugins/agent-utilities/skills/fusion-parametric-design/tests/test_scripts.py`
- `plugins/agent-utilities/skills/fusion-parametric-design/tests/test_golden_path.py`

**Approach:** Verify emitter gains a `occurrence_transforms` report key ({path: 16-float list or null}) built from `getattr(occurrence, "transform2", None)` for relevant paths — additive, no new failure tokens. Changing the example manifest changes `manifest_sha256`, so every checked-in generated script regenerates (byte-guards enforce it); the sample verification report regenerates too.

**Test scenarios:**
- Emitted verify script contains `transform2` and `occurrence_transforms`.
- Fake-adsk run records a 16-tuple for an occurrence with transform2 and null without it.
- Byte-equality guards green after regeneration; digest embedded in all scripts matches new manifest hash.
- Example manifest validates with the new section.

**Verification:** `scripts/test.sh` green.

---

### U3. Manufacturing intent in the export handoff index

**Goal:** `emit_export_script` embeds each part's intent; the index carries `manufacturing_intent` per artifact; `body_name` (when declared) must match the resolved solid.

**Requirements:** R8; KTD2; assumption 3.

**Dependencies:** U1, U2.

**Files:**
- `plugins/agent-utilities/skills/fusion-parametric-design/src/fusion_design/export_handoff.py`
- `plugins/agent-utilities/skills/fusion-parametric-design/tests/test_export_handoff.py`
- `plugins/agent-utilities/skills/fusion-parametric-design/examples/electronics-enclosure/generated/export.py` (regenerate again in U3 — the emitter change alters bytes beyond the manifest hash; byte-equality guards must be green after)

**Approach:** At emit time, when `manifest.printable_parts` is non-empty, attach the part's intent object (id, quantity, print_as, orientation, support_policy(+regions), strength, protected_features, material) to the embedded part spec; runtime copies it into each artifact's index entry as `manufacturing_intent` and enforces declared `body_name` against the resolved solid (`ambiguous-body`-style failure token `body-name-mismatch`). No intent → no key (index shape for intent-less manifests unchanged).

**Test scenarios:**
- With intent: index entries carry `manufacturing_intent` matching the manifest; still no slicer/profile keys (extend the forbidden-key check with `printer`, `filament`, `process_profile`).
- Without intent (synthetic manifest): index has no `manufacturing_intent` key.
- Declared `body_name` mismatch → fail closed before export, no files.
- Declared `body_name` match → exports.

**Verification:** `scripts/test.sh` green.

---

### U4. Docs and live acceptance

**Goal:** SKILL.md and references describe the intent contract; live acceptance extends §10.

**Requirements:** issue acceptance ("handoff is slicer-neutral…"); R8 non-goal statements.

**Dependencies:** U1–U3.

**Files:**
- `plugins/agent-utilities/skills/fusion-parametric-design/SKILL.md`
- `plugins/agent-utilities/skills/fusion-parametric-design/references/verification-contract.md`
- `plugins/agent-utilities/skills/fusion-parametric-design/docs/live-fusion-acceptance.md`
- `plugins/agent-utilities/skills/fusion-parametric-design/examples/electronics-enclosure/README.md`
- `plugins/agent-utilities/.claude-plugin/plugin.json`, `plugins/agent-utilities/.codex-plugin/plugin.json` (version bump per release coupling)

**Approach:** Document the section's fields and the it-is-not-a-slicer-profile boundary; acceptance §10 adds "confirm the index's manufacturing_intent matches the manifest and records the three parts' differing orientation/support intent". Bump manifests (0.7.0 → 0.8.0).

**Test scenarios:** Test expectation: none — docs/template prose; `tests/test_skill.py` invariants stay green.

**Verification:** `scripts/test.sh` green; live gate below.

---

## Verification Contract

- Offline: `scripts/test.sh` (repo final gate).
- Live (single Fusion instance): rerun the golden path (sync → scaffold → positive control → verify) with the updated manifest; verify report records `occurrence_transforms`; emit-export against the live verify report; index carries the three parts' differing `manufacturing_intent`; no slicing/profile claims. Fail-closed body-name negative optional (covered offline).

## Definition of Done

R1–R9 implemented and tested; all checked-in generated artifacts regenerated and byte-guard green; live acceptance recorded; no printer/filament/process profile anywhere; merged PR with post-merge proof + marketplace repin.
