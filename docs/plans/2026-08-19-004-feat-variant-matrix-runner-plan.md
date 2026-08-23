---
title: "feat: Batch verification and export for Fusion variants"
date: 2026-08-19
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
origin: https://github.com/novotnyllc/agent-utilities/issues/23
---

# Summary

Add a bounded variant-matrix runner: for each declared variant, activate its parameter set or Fusion configuration, compute, run the existing inventory and verification transactions, optionally invoke the deterministic export helper, and record identity-bound evidence per variant. The initially active variant is restored on success **and on failure**. One failing variant does not erase evidence already earned by earlier variants, but the overall run fails.

---

## Problem Frame

The skill verifies one active configuration at a time. A product family — three enclosure sizes, two mounting options — has no repeatable way to prove that every named variant still regenerates, verifies and exports. Today that is a manual loop a person performs and describes in prose, which is exactly the kind of evidence that rots silently.

---

## Requirements

- **R1.** A `variants` manifest section: each entry has a stable `id`, a human `description`, and exactly one explicit source — either `parameters` (a mapping of declared parameter names to expressions) or `configuration` (a named Fusion configuration). Never both, never neither; "invent a variant" is an explicit non-goal.
- **R2.** Every parameter named by a variant must exist in the manifest's `parameters`, and its expression must satisfy the same validation the base parameter does (units, non-empty, role-prefix rules unchanged). A variant may not introduce a parameter the manifest never declared.
- **R3.** The runner activates each variant, computes, then runs the existing inventory and verification transactions unchanged — it composes them, it does not reimplement them.
- **R4. Restore the initial state**, whichever way the run ends: completion, a failing variant, or an exception. The restore is verified (the active parameter values or configuration are read back and compared), and a failed restore is itself a loud failure — a document silently left on variant 3 is worse than a failed run.
- **R5.** Per-variant evidence is identity-bound and collision-free: every report and every export path carries the variant id and the manifest hash, so two variants can never overwrite each other's evidence and no artifact is ambiguous about which variant produced it.
- **R6.** A failing variant does not discard evidence already recorded for earlier variants. The matrix keeps what was earned, marks the failure, continues or stops per the declared policy, and the **overall run fails**.
- **R7.** The final matrix reports, per variant: compute health, timeline health, the verification failure tokens (empty when passing), export hashes when export was requested, and any unsupported check — plus an overall verdict that is passing only when every variant passed.
- **R8.** Export is optional and, when requested, uses the deterministic export helper from #24 unchanged, including its fail-closed guarantees (never overwrite, hash-bound, manifest-bound).
- **R9.** Bounded: a declared maximum number of variants per run, and a per-variant timeout, so a matrix cannot run unbounded against a live Fusion session.

---

## Assumptions

- **Parameter-set variants are the primary path.** They are expressible through the existing parameter-sync transaction and need no new Fusion surface. Named Fusion *configurations* are supported in the manifest and the runner, but their activation depends on Fusion's configuration API being present in the connected release — probe it, and fail closed with a clear message when absent rather than silently degrading to "no variant applied."
- **The runner orchestrates from the host**, emitting one transaction per step and consuming the existing stdout report protocol, rather than emitting one giant script that loops inside Fusion. That keeps each step's evidence separately attributable and lets a failure stop cleanly with the document in a known state.
- **Restoration captures the initial values first.** The initial parameter expressions (or active configuration) are read and recorded before the first variant is applied; that snapshot is the restore target and is part of the run's evidence.

---

## Key Technical Decisions

1. **KTD1: Compose, never reimplement.** The runner calls the existing inventory, verification and export emitters. A second implementation of verification that drifts from the first would be worse than no matrix at all.
2. **KTD2: Restoration is a verified step, not a `finally` block.** Reading the state back and comparing is the difference between "we tried to restore" and "we restored." The issue asks for restoration after *failure*, which is precisely when a best-effort cleanup is least trustworthy.
3. **KTD3: Evidence is per-variant and additive.** Earlier variants' reports are already written when a later one fails; the matrix records what happened rather than rolling back the record. R6 is a statement about *evidence*, not about geometry.
4. **KTD4: The overall verdict is conjunctive.** Passing requires every variant to pass. A matrix that reports "2 of 3 passed" as success is the failure mode this feature exists to prevent.

---

## Implementation Units

### U1. `variants` manifest section

**Goal:** Validation per R1–R2, in the established closed-world style.

**Files:** `src/fusion_design/variants.py` (new), `src/fusion_design/manifest.py`, `schema/fusion-project.schema.json`, `tests/test_manifest.py`.

**Approach:** Follow `printable_parts.py` and `material_decision.py` exactly — module-level constants, `_in_closed_set` for every membership test (never a bare `x not in SET`; that class has bitten this series twice), `_reject_unknown_fields`, kebab-case codes (`variant-duplicate-id`, `variant-source-ambiguous`, `variant-source-missing`, `variant-unknown-parameter`, `variant-invalid-expression`, `variants-exceed-maximum`). Re-export constants from `manifest.py`, extend the schema and the schema/validator parity test.

**Test scenarios:** valid parameter-set and configuration variants pass; both sources present rejected; neither rejected; duplicate ids rejected; a parameter not in `parameters` rejected; an expression failing base parameter rules rejected; manifests without the section stay valid; unhashable values in enum fields yield issues rather than `TypeError`; exceeding the declared maximum rejected.

---

### U2. Runner, restoration and the matrix record

**Goal:** R3–R7, R9.

**Files:** `src/fusion_design/variant_matrix.py` (new), `tests/test_variant_matrix.py`.

**Approach:** A host-side orchestrator producing an ordered plan of steps — capture initial state, then per variant (apply, compute, inventory, verify, optional export), then restore and verify. Each step is an existing emitter plus a report consumer. The matrix record accumulates per-variant rows as they complete, so a later failure cannot erase an earlier row. Restoration compares read-back state against the captured snapshot and fails loudly on mismatch. The runner is driven by an injected step-executor callable so the whole state machine is testable offline without Fusion.

**Test scenarios:** three variants all passing produce three rows and an overall pass; a middle variant failing keeps the first row, marks the second failed, and the overall verdict fails; restoration runs after a failure and after an exception; a failed restoration is itself reported as a failure; a restore whose read-back disagrees with the snapshot fails; per-variant export paths and report identities are unique and carry the variant id; exceeding the per-variant timeout fails that variant without corrupting the record; the conjunctive verdict never reports partial success as success.

---

### U3. CLI and live acceptance

**Goal:** Expose the runner and prove it live.

**Files:** `src/fusion_design/cli.py`, `tests/test_cli.py`, `docs/live-fusion-acceptance.md`, `SKILL.md` (including the §16 tool list — an omission there is a real defect, as `emit-export` demonstrated), `references/capability-matrix.md`, both plugin manifests.

**Approach:** `plan-variants <manifest> [--export-dir DIR] [--verification-report ...]` emitting the ordered step plan and the scripts each step needs, following the existing emitter conventions and path-aliasing rejection. Live acceptance covers the issue's criterion directly: **two enclosure sizes and one deliberately failing variant**, asserting that the failing variant does not erase the passing ones, that the overall run fails, and that the originally active state is restored.

**Test scenarios:** plan emitted for a valid manifest; a manifest without variants exits 2 with a clear message; path aliasing rejected; the plan's step order is capture → per-variant → restore.

---

## Verification Contract

- Offline gate: `scripts/test.sh` — the runner's state machine, including failure and restoration paths, is fully testable with an injected executor and no Fusion.
- Live gate (single Fusion instance): two enclosure sizes plus a deliberately failing variant; confirm per-variant evidence, the conjunctive failure, and verified restoration of the initially active state.

## Definition of Done

R1–R9 implemented and tested; the runner composes the existing transactions rather than reimplementing them; restoration verified by read-back on every exit path; per-variant evidence collision-free and identity-bound; partial success never reported as success; merged PR with post-merge proof and marketplace repin.
