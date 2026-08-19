---
title: "feat: Material selection gate and material-aware CAD recommendations"
date: 2026-08-19
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
origin: https://github.com/novotnyllc/agent-utilities/issues/21
---

# Summary

Make material an **early, recorded decision** rather than a late slicer choice. Add a project-level `material_decision` to the manifest (chosen material, polymer family vs specific formulation, source and confidence, coupon linkage, unresolved risk), validate it fail-closed, require it before any geometry whose correctness depends on material, and add a doctrine reference that drives requirement-driven recommendations with their design consequences.

---

## Problem Frame

Filament choice changes the geometry that works. Snap fits, living hinges, press fits, connector retention, heat-set inserts, wall thickness, creep margin, thermal clearance, and support strategy are all wrong for the wrong material. The skill currently carries only `project.material` (a free string) and, since #18, a per-part `material.assumption`/`status`. Nothing forces the decision to happen before material-dependent geometry is committed, and nothing records *why* a material was chosen or how much the numbers behind it can be trusted.

---

## Requirements

- **R1.** New optional top-level `material_decision` object: `family` (closed enum: `PLA`, `PLA_SILK`, `PETG`, `TPU`, `ASA`, `ABS`, `PC`, `PC_CF`, `PA`, `PA_CF`, `PET_CF`, `OTHER`), `formulation` (free string naming the specific manufacturer product, or null when only the family is settled), `source_id` (a declared manifest source), `confidence` (reuse the existing `SOURCE_CONFIDENCES` vocabulary), `coupon_component` (a component-tree path, or null), `rationale` (non-empty), and `unresolved_risks` (list of strings, may be empty).
- **R2.** Validation fails closed on: unknown family; `formulation` present but blank; `source_id` not among declared sources; `coupon_component` not in `component_tree`; empty `rationale`; `OTHER` family without a `formulation` (an unnamed "other" material has no properties to reason from).
- **R3.** **Filled-material safety gate.** Any `*_CF` family (and `PA`, which is hygroscopic enough to matter) must carry at least one entry in `unresolved_risks` **or** an explicit `printer_requirements` string naming the abrasion-resistant nozzle and, for `PA*`, drying. Carbon- and glass-filled materials are not drop-in; the manifest must not present them as if they were.
- **R4.** **TPU specificity.** Family `TPU` requires `formulation` to be non-null and its `rationale` to state the needed hardness or flex behavior. "TPU" alone is not a material decision.
- **R5.** **Provisional-value binding.** When `confidence` is `provisional`, at least one of: a `coupon_component`, or a non-empty `unresolved_risks`. A provisional material decision may never look settled.
- **R6.** Per-part `material.assumption` (added in #18) must be **consistent** with the project decision when both are present: the part's assumption must name the decided family or formulation. A part claiming PETG under an ASA decision is a validation error, not a silent divergence.
- **R7.** The export handoff index carries the material decision alongside the existing manufacturing intent, so a downstream adapter and the DESIGN-STATE record both see the chosen material, its confidence, and its unresolved risk.
- **R8.** A doctrine reference (`references/material-selection.md`) covering the families in the issue with their **design consequences** — stiffness/toughness, creep, flex fatigue, heat and UV resistance, warping and enclosure need, moisture and drying, abrasion and nozzle requirements, layer adhesion, dimensional behavior, support removal — written as requirement-driven selection guidance, not a spec sheet. It states plainly that published generic tolerances are not measured truth and must be bound to a named source or a printed coupon.
- **R9.** SKILL.md gains the decision gate: material must be asked or confirmed **before finalizing** any snap, clip, living hinge, press fit, insert boss, or load-bearing connector; a documented user default is proposed rather than silently assumed, and is re-confirmed when the use case conflicts with it.
- **R10.** Schema and validator updated in lockstep with a parity test, as established in #18. Manifests without `material_decision` stay valid.

---

## Assumptions

- **Family enum, free-text formulation.** The polymer family is closed (it drives the doctrine); the specific manufacturer product is open text, since new filaments appear constantly. This is exactly the family-vs-formulation distinction the issue asks for.
- **No property database.** The skill does not ship numeric material properties — it records the decision, its provenance, and its risk, and points at the manufacturer's technical data sheet. Shipping numbers we cannot verify would be the "generic internet tolerances as measured truth" failure the issue names.
- **The gate is doctrine, not code.** No code can detect "the user is about to finalize a snap fit." R9 lands in SKILL.md as a workflow obligation; what code enforces is that the *recorded* decision is complete and self-consistent (R1–R6).
- Reuses `SOURCE_CONFIDENCES` rather than inventing a parallel confidence vocabulary.

---

## Key Technical Decisions

1. **KTD1: Record the decision, don't simulate the material.** The manifest captures family, formulation, provenance, confidence, coupon, and unresolved risk. It never asserts a modulus or a shrinkage figure. This keeps the skill inside what it can actually evidence and matches its existing refusal to claim structural performance without physical proof.
2. **KTD2: Consistency over duplication.** #18's per-part `material.assumption` stays; R6 makes the project decision authoritative and the parts checked against it, so the two cannot silently diverge.
3. **KTD3: Filled and flexible materials get their own gates.** R3 and R4 exist because those are the two families where a nominally valid decision is most often practically wrong — a CF filament with no nozzle plan, or "TPU" with no hardness.
4. **KTD4: Doctrine in a reference, gate in SKILL.md.** Matches how the skill already separates `references/design-doctrine.md` from the workflow steps.

---

## Implementation Units

### U1. `material_decision` validation and schema

**Goal:** Closed-world validation per R1–R5, mirrored in the JSON schema, with the parity test extended.

**Files:** `src/fusion_design/material_decision.py` (new — keeps `manifest.py` from regrowing past 1000 lines, as established when `printable_parts.py` was split out), `src/fusion_design/manifest.py`, `schema/fusion-project.schema.json`, `tests/test_manifest.py`.

**Approach:** Follow `printable_parts.py` exactly — module-level closed enums, `_in_closed_set` for every membership test (the unhashable-value crash class found in #18 must not reappear), `_reject_unknown_fields`, kebab-case issue codes (`material-decision-unknown-family`, `-invalid-formulation`, `-unknown-source`, `-unknown-coupon`, `-missing-rationale`, `-filled-material-unguarded`, `-tpu-underspecified`, `-provisional-unbound`). Re-export constants from `manifest.py` and add the allowed-field set to the schema parity test.

**Test scenarios:** valid decision passes; manifest without the section still valid; each R2 rejection; `OTHER` without formulation rejected; `PA_CF` without risks or printer requirements rejected, and accepted with either; `TPU` without formulation rejected, and without hardness language in rationale rejected; `provisional` with neither coupon nor risks rejected; unhashable (dict/list) values in every enum field yield issues rather than `TypeError`; unknown nested field rejected.

---

### U2. Part-to-decision consistency and handoff propagation

**Goal:** R6 consistency check; R7 propagation into the export index.

**Files:** `src/fusion_design/material_decision.py`, `src/fusion_design/printable_parts.py`, `src/fusion_design/export_handoff.py`, `tests/test_manifest.py`, `tests/test_export_handoff.py`.

**Approach:** Cross-check runs where both are present (issue code `material-decision-part-mismatch`), matching case-insensitively against family and formulation. `emit_export_script` embeds the decision once at index level (not per artifact — it is a project-level fact); the index gains `material_decision`. Extend the forbidden-claim key sweep so the new block cannot smuggle a filament profile.

**Test scenarios:** consistent part assumption passes; a part naming a different family fails; parts pass when no project decision exists (back-compat); index carries the decision; index omits the key when the manifest declares none; no printer/filament/process-profile keys appear.

---

### U3. Doctrine reference and workflow gate

**Goal:** R8, R9.

**Files:** `references/material-selection.md` (new), `SKILL.md`, `references/design-doctrine.md`, `references/capability-matrix.md`, `templates/DESIGN-STATE.md`, `docs/live-fusion-acceptance.md`, both plugin manifests (bump).

**Approach:** The reference covers each family with its design consequences and when to prefer it, written as selection guidance keyed to requirements (outdoor, heat, flex, wear, load, cosmetic). It states the family-vs-formulation rule, that specialty filled materials require the manufacturer's technical data sheet, that ambiguous trade names inherit nothing, and that clearances must trace to a named source or a printed coupon. SKILL.md adds the decision gate before material-dependent features and the propose-don't-assume rule for a documented default. DESIGN-STATE gains a material row. `tests/test_skill.py` already asserts that every `references/*.md` named in SKILL.md exists — the new file must be referenced there.

**Test scenarios:** Test expectation: none for prose, but `tests/test_skill.py` invariants must stay green, and add an assertion that `references/material-selection.md` is referenced from SKILL.md.

---

### U4. Live example: PETG snap-fit and its counterexample

**Goal:** The issue's final acceptance criterion — a worked case plus a case where the material changes the design decision.

**Files:** `examples/electronics-enclosure/fusion-project.json`, `examples/electronics-enclosure/README.md`, regenerated `examples/electronics-enclosure/generated/*` and `sample-verification-report.json`.

**Approach:** The enclosure declares a PETG decision with its rationale (snap-fit lid needs PETG's toughness and strain recovery; PLA would be brittle at the snap). README documents the counterexample explicitly: under ASA the same lid needs different clearance for outdoor thermal cycling, under TPU the snap geometry stops making sense entirely, and under PLA the snap risks brittle failure — showing the decision driving geometry rather than trailing it. Changing the manifest changes `manifest_sha256`, so every checked-in generated script and the sample report regenerate.

**Test scenarios:** example manifest validates with the decision; byte-equality guards green after regeneration; the export index for the example carries the PETG decision.

---

## Verification Contract

- Offline gate: `scripts/test.sh` (repo final gate).
- Live (single Fusion instance): re-run the golden path with the updated manifest and confirm the export index carries the material decision. No new Fusion API surface is exercised.

## Definition of Done

R1–R10 implemented and tested; no numeric material properties shipped; the decision is recorded with provenance, confidence, coupon and risk; filled and flexible families gated; doctrine reference written and referenced from SKILL.md; example demonstrates the decision changing geometry; merged PR with post-merge proof and marketplace repin.
