---
title: "design: U4+U5 — feature emission and the editability proof (issue #20 phase 2, PR 4)"
date: 2026-08-19
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
origin: https://github.com/novotnyllc/agent-utilities/issues/20
builds_on: docs/plans/2026-08-19-005-feat-mesh-parametric-reconstruction-plan.md
---

# Summary

This document designs U4 (feature emission: sketches, constraints, extrude, revolve) and U5 (editability verification by perturbation) from plan 005 — the pair the parent plan ships together as PR 4, because an emitter without its editability proof is exactly the "asserted more than it verified" failure this skill exists to prevent.

The emission strategy in one paragraph: **a smart host-side planner and a deliberately dumb Fusion-side executor.** Every decision that can be made offline is made offline — feature ordering, sketch-plane mapping into the datum frame, 2D profile projection, the constraint schedule, parameter naming, the dependency DAG — and is therefore provable under `scripts/test.sh` with no Fusion running. The generated transaction receives a fully-ordered, closed-vocabulary build script derived from the reconstruction program and does only four things: verify bindings (dump hash re-derived from the live mesh, program hash, manifest hash), construct (planes → sketches → constraints → dimensions → features, in the declared order), measure (solver acceptance, displacement, timeline health), and report. It makes no choices. Anything it cannot construct exactly as declared is a named refusal with full rollback, never an improvisation.

The model this produces is what the commercial tools produce: a real timeline of named features in a dedicated component, driven by named user parameters, with sketches constrained toward fully-constrained and every near-relationship snapped to an exact constraint within a declared tolerance. The proof that it is real is U5: perturb each parameter, recompute, observe a declared physical effect (volume, centroid, or bounding box — not volume alone, see D7), restore, recompute, observe the model return. `designType` is never evidence. A parameter that changes nothing is a failure. A failure names the parameter and the feature it broke, by the feature's own deterministic name.

Partial reconstruction is emitted, not refused: the program's declared archetypes are built in full, the source mesh stays in the document as reference geometry overlaying the rebuild, and the report carries `covered_area_fraction` plus the named unreconstructed regions. Unplanned partiality — a feature that fails mid-emission — refuses and rolls back, then the CLI offers an explicit, recorded replan without the failed archetype, so the honest partial result is one deliberate command away rather than a silent degradation.

# Problem Frame

Plan 005's U1–U3 produce numbers: a hash-bound mesh dump, robustly-detected primitives with inlier sets (U2, redirected to Efficient RANSAC per Schnabel, Wahl & Klein 2007 — coordinator direction, 2026-08-19), a datum frame, adopted relationships, and a versioned reconstruction program (R16). U4 is where numbers become a Fusion timeline a human can edit, and U5 is where that claim is proven rather than asserted.

This is an application-level job, not a kernel-level one. No library emits a Fusion timeline because a feature history is an application artifact — and the commercial tools (Geomagic Design X, QuickSurface/Revo Design Pro, Ansys SpaceClaim) demonstrate the job is tractable by implementing it themselves on top of a kernel. Our position is strictly better than theirs was: Fusion already owns the timeline, the sketch solver, the constraint engine, and the rebuild machinery. We do not build any of that. We drive it — through an API surface this skill has never exercised: `grep` confirms zero occurrences of `sketches.add`, `extrudeFeatures`, `geometricConstraints`, `sketchDimensions`, `revolveFeatures`, `holeFeatures`, or `constructionPlanes` anywhere in `src/` today (parent F2, re-verified). Everything below that touches those APIs is greenfield, and every behavioural claim about them is labelled as an assumption with the live step that settles it.

The four hard sub-problems, addressed head-on in D2–D7:

1. **Sketch planes cannot be conjured from arbitrary geometry in parametric mode** (the `setByPlane` trap, D2). Solved by emitting the entire model in the datum frame, where every plane is an offset or a rotation from origin geometry.
2. **Constraint sets can over-constrain (solver rejects) or under-constrain (model moves unpredictably when edited)** (D3). Solved by a layered schedule — topology by construction, then snapped geometric constraints, then dimensions — applied one at a time with displacement checks and rollback, aiming at `isFullyConstrained` and recording honestly when a sketch falls short.
3. **Face and edge identity across rebuilds is the classic trap** (D5). Mostly dissolved rather than solved: within the single forward pass of one transaction, every reference is resolved from the collections the just-created feature itself owns (`endFaces`, `sideFaces`), matched geometrically against the fitted primitive — no indices, no cross-rebuild survival needed. Where a reference must survive (U5, deviation), `entityToken` is recorded as evidence with its stability labelled an assumption and tested by the perturbation loop itself.
4. **Proving editability without over-claiming** (D7). Volume-only inertness testing is wrong — a hole-position parameter legitimately preserves volume — so each parameter declares its expected observable, and the proof asserts that observable moved and returned.

# Verified facts vs assumptions

Facts are things read in this repository on branch `feat/mesh-reconstruction-phase2` or confirmed by running a command in it. Assumptions — most of them about Fusion API behaviour that cannot be exercised offline — are individually labelled with what settles them. Nothing in the Assumptions list is load-bearing for the *architecture*; several are load-bearing for the *implementation*, and the design fails closed on each.

## Verified facts

**G1.** All plan-003 mesh modules are present and tracked on this branch — `mesh_fitting.py`, `mesh_source.py`, `mesh_deviation.py`, `mesh_convert.py`, `mesh_reconstruction.py` — and `mesh_fitting.py` is byte-identical to `feat/stl-reconstruction`'s copy (verified by `diff` against `git show`). The sibling branches `feat/mesh-u1`/`-u2`/`-u3` exist but currently contain **no new modules** — each is a bare merge of `feat/stl-reconstruction` into the phase2 base. Consequence: U4/U5 bind to plan 005's *declared* contracts (R16's program shape, U1's dump format), not to code, and the program validator is the negotiation surface (D9).

**G2.** `SketchEntity` (`mesh_fitting.py:532–570`) carries `kind ∈ {line, arc, circle}`, `start`, `end`, `residual`, `point_count`, and for arcs/circles `center`, `radius`, `mid` — and its docstring guarantees consecutive entities share endpoints exactly ("``start``/``end`` are the polyline's own points, so … a coincident constraint is trivially satisfiable"). This is the profile vocabulary U4 consumes, whatever upstream produces it (section-based or RANSAC-inlier-based).

**G3.** `PrimitiveFit` (`mesh_fitting.py:722–757`) carries `kind`, `accepted`, residuals, `extent`, `parameters`, `rejection` — rejections are data, never silence.

**G4.** The generated-transaction pattern is fixed and reusable: `_script_prelude` (`scripts.py:24`) embeds `MANIFEST_SHA256`, the `FUSION_DESIGN_REPORT_BEGIN`/`_END` stdout protocol (`scripts.py:10–11`), `DocumentChangedError`, `_require_target_document`, `_pump_events`; `_timeline_health` (`scripts.py:208–247`) already classifies unhealthy/suppressed/informational timeline items and captures `errorOrWarningMessage`.

**G5.** The `checked`-list discipline exists as precedent: the verification emitter builds `checked` from what the run actually performed and separates `not_declared` from `unchecked` (`scripts.py:967–997`). Note that the same report also emits `"is_parametric": design.designType == …` (`scripts.py:990`) as an informational field — the existing verify transaction is *allowed* to report it; U5's generated source must not contain `designType` at all (parent R11), asserted by string search.

**G6.** A nonce precedent exists: `emit_verification_script(manifest, nonce)` embeds `VERIFICATION_NONCE` (`scripts.py:653–668`), generated by the CLI (`cli.py` uses `secrets`). U4/U5 reuse this to make their reports non-forgeable-by-replay.

**G7.** Parameter manipulation precedent exists in-skill: the parameter-sync transaction reads and writes `design.userParameters` and `parameter.expression` (`scripts.py:379–452`). Reading and setting expressions is exercised territory; *creating* parameters and *binding dimensions to them* is not (see assumptions).

**G8.** Closed-set validation precedent: `manifest._in_closed_set` / `_reject_unknown_fields` (`manifest.py:175` ff., imported throughout), used by `mesh_reconstruction.py`'s classification records (`RECONSTRUCTION_PATHS`, `CLASSIFICATION_*_FIELDS`) and `require_classification` (`mesh_reconstruction.py:343`). The program validator copies this shape.

**G9.** The gate is `scripts/test.sh`: `python3 -m unittest discover -s tests -v` then `python3 -m compileall -q src tests`. Not pytest. Examples are byte-pinned to emitters (parent F8; `tests/test_golden_path.py`, `tests/test_scripts.py`).

**G10.** The CLI pattern is `subparsers.add_parser(...)` + `_cmd_*` handlers (`cli.py:396` ff.); mesh commands `emit-mesh-capture`, `emit-mesh-convert`, `emit-mesh-deviation` already exist to be followed.

**G11.** The existing example transaction that creates geometry (`positive_control.py:287–306`, parent F10) uses `TemporaryBRepManager` inside a `baseFeatures` edit block — the exact anti-pattern R9 bans for reconstruction, and the reason the U4/U5 generated sources carry string-search tests asserting `baseFeatures` is absent.

**G12.** Inside Fusion, `sys.executable` is the Fusion binary (parent plan, hard constraint). Neither generated transaction starts a process; both are pure construct-measure-report scripts. This is a design invariant tested by string search for `subprocess`, `os.system`, `os.exec`, `Popen` over generated source.

## Assumptions — not facts, each with its settling step

Every entry below is an API-behaviour claim from Autodesk documentation or training knowledge, not from this repository, and **the implementation must treat each as falsifiable**. Where an assumption fails, the named fail-closed token fires; no assumption failure produces silent degradation.

**B1. `ConstructionPlaneInput.setByPlane` does not work in parametric design mode** (documented as direct-edit-only). The design *does not use it* (D2), so this assumption failing in our favour merely opens an optimization. Settled by: a U0-style probe extension if ever needed; until then, moot by construction.

**B2. `constructionPlanes.add` with `setByOffset(originPlane, ValueInput.createByString(expr))` creates a parametric plane whose offset follows the expression**, and the root/new component exposes `xYConstructionPlane`/`xZConstructionPlane`/`yZConstructionPlane` and `x/y/zConstructionAxis`. Load-bearing for D2. Settled by: U4's first live run; refusal token `rebuild-capability` names the missing member if the `getattr` probe fails, and `feature-failed` names the plane if creation raises.

**B3. Passing an existing `SketchPoint` as the start of the next `addByTwoPoints`/`addByThreePoints` call produces topologically shared endpoints** (merged sketch points), giving closed-profile connectivity without explicit coincident constraints. Settled by: U4 live run; fallback is explicit `addCoincident` per junction, which the constraint schedule already contains as its first layer — the fallback changes cost, not correctness.

**B4. A sketch dimension's `parameter.expression` can be assigned a user-parameter name, and `extrudeFeatures` distance extents accept `ValueInput.createByString("<param>")`**, so both sketch dimensions and feature extents can be driven by named user parameters. Load-bearing for D6 and for U5's entire premise. Settled by: U4 live run; failure is `feature-failed`/`constraint-rejected` naming the binding.

**B5. `ExtrudeFeature.startFaces`/`endFaces`/`sideFaces` (and `RevolveFeature.faces`) are populated immediately after the feature is created, within the same script execution.** Load-bearing for D5's face resolution. Settled by: U4 live run (hole placement is the first consumer).

**B6. `entityToken` values recorded on faces/bodies remain resolvable via `design.findEntityByToken` after a `computeAll` that follows a parameter change, within the same document.** *Not* load-bearing for construction — only for cross-transaction evidence. Settled by: U5's perturbation loop itself, which resolves recorded tokens after each recompute and reports per-token resolution as measured fact (`entity_tokens: {resolved, unresolved}`) rather than assuming either way.

**B7. `Sketch.isFullyConstrained` is readable and meaningful after constraints and dimensions are applied.** Settled by: U4 live run. If absent, the report records `fully_constrained: "unavailable"` — never a fabricated boolean (the `getattr`-probe-refuses rule applies: an absent property is reported absent, not compared).

**B8. Features, sketches, construction planes, and user parameters support `deleteMe()`, and deleting in reverse creation order removes dependents before dependencies** (a user parameter deletes only after the dimensions referencing it are gone). Load-bearing for rollback (D8). Settled by: U4 live run of a deliberately failing program in acceptance testing; if a `deleteMe` fails, the report downgrades to `rollback-incomplete` naming what remains — loud, never silent.

**B9. `body.physicalProperties` (with an explicit accuracy argument) yields volume and centroid stable enough that a restored model returns within a declared epsilon.** Load-bearing for D7. Settled by: U5 live run; the epsilon is caller-declared with a rationale precisely because this noise floor is unknown offline.

**B10. `design.timeline` items expose the created feature entities such that a deterministically-named feature (`feature.name = "recon_..."`) can be found again by name in U5.** Settled by: U5 live run; `rebuild-record-mismatch` fires if any recorded name is missing.

**B11. `HoleFeatures.createSimpleInput(diameter)` positioned by a sketch point, with parametric diameter and depth, behaves as documented.** Load-bearing only for the hole archetype (this PR — see the sequencing disagreement below). Settled by: U4 live run; failure refuses that archetype by token, and the part replans to `sketch-extrude` cut or `unreconstructed` explicitly.

**B12. The reconstruction program U3 delivers will match the schema in D9.** G1 shows U3 does not exist yet; this is a contract, not an observation. Settled by: the program validator — any divergence is a loud `program-schema-violation` at the first joint test, not a runtime surprise inside Fusion.

# Requirements

These extend plan 005's R8–R15 (all of which stay in force) with the precision U4/U5 need. Numbered E1… to avoid colliding with the parent's R-numbers.

- **E1. The executor makes no decisions.** The emitted transaction contains a fully-ordered build list. It never reorders, never substitutes an archetype, never invents a plane, never picks a constraint to drop on its own initiative (the displacement-rollback of a *single declared* constraint per D3 is a measurement outcome, recorded, not a choice). Anything not constructible exactly as declared is a named refusal.

- **E2. All geometry is emitted in the datum frame, inside a dedicated component.** A new component (name declared in the program, default `Reconstruction`) holds every emitted feature; its occurrence transform is set to the datum→world transform so the rebuild overlays the source mesh. The source mesh body is never modified, moved, or hidden.

- **E3. Sketch planes come only from origin geometry**: an origin construction plane, an offset from one (parameter-driven), or an offset plane rotated about an origin axis by a declared angle. A program plane not expressible this way is refused *host-side at planning time* with `plane-unmappable`, and its archetype is declared `unreconstructed` with that gate named — before any transaction is generated.

- **E4. Every dimension and every feature extent is bound to a named user parameter.** No magic numbers in the timeline. Parameters are created first, in one deterministic pass, with deterministic names, explicit units, and a comment carrying the program id of the archetype they drive. A name collision with a pre-existing user parameter refuses `parameter-name-collision` before construction begins.

- **E5. Constraints are layered and incremental** (D3): topology by construction; snapped geometric constraints (each carrying the measured deviation it snapped from); dimensions last. One at a time, displacement-checked, rolled back individually and recorded on rejection (parent R10/KTD7). The per-sketch outcome records `fully_constrained` and the full list of applied, rejected, and fallback entries.

- **E6. Feature order is a host-side deterministic total order** derived from the dependency DAG (D4), embedded in the program, tested offline for determinism and for topological validity. The executor follows it literally.

- **E7. Face and edge references are resolved geometrically from feature-owned collections** at the moment of consumption, matched against fitted primitives within a declared `entity_match_tolerance`; positional indices into `body.faces`/`body.edges` never appear in generated source (string-search-tested). Resolved references have their `entityToken` recorded as evidence.

- **E8. The rebuild transaction re-derives the mesh dump hash from the live mesh** before creating anything, using the identical canonical serializer the host writer uses (single-sourced — see U4 files), and refuses `dump-hash-mismatch` naming the first differing section (header/vertices/triangles) on any difference.

- **E9. The rebuild record is the bridge to U5**: it carries manifest, dump, and program hashes; the created component name; every feature's deterministic name, archetype id, and consumed references (with tokens); every user parameter with nominal expression; per-sketch constraint outcomes; and the report nonce. U5 refuses `rebuild-record-mismatch` when the live document does not contain exactly the named component, features, and parameters.

- **E10. Editability is proven per parameter against a declared observable** (D7): volume, centroid displacement, or bounding box extent — caller-declared per parameter with a rationale, perturbed by a caller-declared amount with a rationale, asserted to move beyond a declared minimum and to return within a declared epsilon after restore. A parameter whose declared observable does not move is `parameter-inert` — a failure, never a warning.

- **E11. An editability failure names the parameter and the feature.** After a failed recompute, the transaction walks the timeline, collects unhealthy items with their feature names and `errorOrWarningMessage`, maps names back through the rebuild record, restores the parameter, recomputes, and reports `parameter-broke-rebuild` with `{parameter, features: [...], messages: [...]}`. If the restore itself fails, `parameter-not-restorable` reports loudly, the loop aborts, and remaining parameters are listed `not_exercised` — never silently skipped.

- **E12. `checked` is constructed by the code that ran the check** (parent R12), enforced by the stub-raise test. U5's `checked` lists parameter names only after perturb-assert-restore-assert completed. U4's `created` lists entities only after their creation call returned and the entity was re-read.

- **E13. The reports carry a nonce and full hash bindings** (G6 pattern): manifest, dump, program, and (for U5) rebuild-record hashes, plus the CLI-generated nonce the host validates. A report without the expected nonce is rejected host-side.

- **E14. Every threshold is caller-declared with a rationale** (parent R15). U4/U5's set: `constraint_displacement_tolerance`, `snap_tolerance_deg`, `snap_tolerance_mm`, `constraint_rejection_budget`, `entity_match_tolerance`, per-parameter `perturbation` (value + rationale + `expected_observable` + `min_observable_change`), `observable_restore_epsilon`. Validation rejects any threshold without a rationale string.

- **E15. Neither generated transaction starts a process, imports beyond stdlib+adsk, or contains `baseFeatures`, `designType`, `subprocess`, `os.system`, or `TemporaryBRepManager`** — all asserted by string search over generated source in the offline suite (G11, G12).

- **E16. `getattr` capability probes refuse rather than default.** The specific defect shape from tonight's P1s is banned by construction: no `getattr(obj, name, None)` whose result flows into a comparison, sum, or boolean context. Every probe is `value = getattr(obj, name, _MISSING)` followed by an explicit `if value is _MISSING: refuse('rebuild-capability', name)` branch before any use. A lint-style offline test greps generated source for `getattr(` and asserts each occurrence sits in the probe template shape.

# Key Technical Decisions

## D1 — Smart host planner, dumb executor

All intelligence lives host-side in `mesh_rebuild.py`'s planning half: datum-frame projection of profiles into 2D sketch coordinates, plane mapping (E3), the constraint schedule, parameter naming and deduplication, the dependency DAG and its total order, join/cut operation selection (consumed from the program — U3 owns orientation), and the hole-placement sketch design. The output of planning is an **emission plan**: a JSON-serializable, closed-vocabulary structure embedded into the generated transaction as data (via the existing `_json_literal` pattern), never as generated control flow.

Why: this is the only split in which the hard 90% of U4 is provable under `scripts/test.sh`. The Fusion-side executor is a fixed interpreter over the emission plan — one code path, exercised offline against the stubbed-`adsk` harness with every refusal branch driven, and byte-pinned as a checked-in example. The alternative — generating bespoke Python per model — makes every reconstruction a new untested program. Rejected.

The cost, stated honestly: a dumb executor cannot adapt when Fusion disagrees with the plan (a solver rejection, a failed feature). That is deliberate. Adaptation happens host-side, in a second explicit plan→emit cycle (D8's replan loop), where it is visible, recorded, and testable — not inside Fusion where it would be improvisation.

## D2 — Datum-aligned construction, because `setByPlane` is a trap and the datum frame makes it unnecessary

The naive design — "make a construction plane at the fitted cap plane" via `ConstructionPlaneInput.setByPlane` — does not work in parametric mode (B1, a documented limitation). The commercial tools solve plane placement by exactly the move U3 already makes: derive the coordinate system *from the fits*, then express everything in it.

So U4 transforms all program geometry into the datum frame host-side. In that frame, by construction of U3's frame derivation, extrude cap planes are parallel to a datum plane at an offset, and revolve axes coincide with a datum axis or lie in a datum plane. Sketch planes become:

- `origin plane` (offset 0) — sketch directly on `xYConstructionPlane` etc.;
- `origin plane + offset` — `setByOffset` with a parameter-driven `ValueInput` (B2), so the cap position itself is editable;
- `origin plane + offset + rotation about a datum axis` — `setByAngle` from the datum axis against the offset plane, angle parameter-driven.

Anything else refuses host-side as `plane-unmappable` (E3) and the archetype is declared unreconstructed with that named gate. This is a real scope edge and it is honest to state its size: on datum-frame-aligned mechanical parts — the class U3's frame derivation succeeds on at all — the overwhelming majority of planned planes fall in the first two buckets, because the frame was *derived from these very fits*. A part whose features are systematically oblique to its own datum frame is a part U3's frame derivation already struggled with. The v2 escape hatch (three-point construction planes through a scaffold sketch) is documented in `unsupported.md` as future work, not silently attempted.

The rebuilt component's occurrence transform is set to datum→world (E2) so the model overlays the mesh for deviation grading, and that transform is recorded in the report using the same raw-`asArray` convention as `occurrence_transforms` in verification.

Units: the dump and program carry mm; the Fusion API's `Point3D`/geometry layer is cm and `ValueInput.createByString` takes explicit units. Rule: every expression in generated source carries an explicit unit string (`"12.5 mm"`, `"90 deg"`); every raw `Point3D` coordinate is converted mm→cm host-side inside the emission plan, and the plan records `"units_note": "point coordinates are cm (Fusion API convention); expressions carry explicit units"` so a reader of the checked-in example is not misled.

## D3 — The constraint ladder: topology by construction, snapped geometry, dimensions last — applied one at a time

The goal state per sketch is **fully constrained**, because an under-constrained sketch moves unpredictably under edit — it looks parametric and is not. The failure to avoid on the other side is over-constraint, which the solver rejects. The design threads this with three layers and an incremental application protocol.

**Layer 0 — topology by construction.** Profile curves are created chained: each subsequent entity receives the previous entity's end `SketchPoint` object as its start (B3), and a closed profile's last entity receives the first entity's start point. G2 guarantees the coordinates agree exactly, so this is always geometrically satisfiable. If B3 fails live, the fallback is one explicit `addCoincident` per junction — layer 0 becomes layer 1's first entries, nothing else changes.

**Layer 1 — snapped geometric constraints, from the program's adopted relationships plus per-sketch idealization.** Each is a *snap*: the measured geometry deviates from the exact relationship by some amount below the declared snap tolerance (`snap_tolerance_deg` for angular, `snap_tolerance_mm` for metric), and applying the constraint moves geometry by up to that much, deliberately. Each applied constraint records `snapped_from` — the measured deviation it erased. The vocabulary, in fixed application order:

1. `horizontal` / `vertical` — lines within `snap_tolerance_deg` of the sketch's datum-aligned axes. Applied first because they anchor orientation cheaply and rarely conflict.
2. `perpendicular` / `parallel` — between profile lines, from adopted relationships or measured within tolerance.
3. `tangent` — at line–arc junctions whose measured tangency deviation is within tolerance (the default at fillet-like junctions `classify_polyline` produces).
4. `concentric` — arcs/circles whose fitted centers coincide within `snap_tolerance_mm`, and circles concentric with an adopted coaxial relationship's axis point.
5. `equal` — radii/lengths from adopted `equal_radius` relationships: the constraint that turns four hole radii into one editable value.
6. `symmetry` — about a datum centerline, only when the program adopted a symmetric relationship (never inferred sketch-locally).

**Layer 2 — dimensions, in deterministic order:** radial/diameter dimensions first, then linear distances anchored to the sketch origin (which is datum geometry, hence stable), then angles. Every dimension is bound to a user parameter (E4). The planner computes the *intended* dimension set from the entity list and the layer-1 schedule — the set that would take an ideal solver to zero remaining DOF without redundancy: e.g. a rectangle with two `horizontal`, two `vertical`, and chained coincidences needs exactly two linear dimensions plus an anchor pair to the origin.

**The conflict policy** — the part the coordinator asked to be designed properly rather than retreated from:

- **Application is one entity at a time** with a displacement check: read back all sketch point positions after each apply; if any moved beyond `constraint_displacement_tolerance`, delete that constraint/dimension, record `{kind, entities, measured_displacement}` in `rejected_constraints`, and continue. A snap is *expected* to move geometry up to its recorded `snapped_from`; the displacement tolerance therefore applies to the *excess* beyond the snap: `displacement - snapped_from > tolerance` rejects. This distinction is what lets us snap ambitiously without letting the solver drag the profile somewhere new.
- **Rejections are budgeted**: more than `constraint_rejection_budget` rejections in one sketch refuses the archetype (`constraint-rejected-budget-exceeded`) — a sketch where the solver fights the plan wholesale is evidence the plan is wrong, and emitting its remnant would be improvisation (E1).
- **A solver error (exception) on apply** is treated identically to a displacement rejection: delete, record, continue — the API surface makes over-constraint indistinguishable from other rejections, and both are handled by the same recorded rollback.
- **After all layers**, read `isFullyConstrained` (B7). If false, apply the *fallback pins*: origin-anchored driven dimensions on the still-free endpoints, in deterministic order, each recorded in `fallback_pins`. If still false after pins, record `fully_constrained: false` — a **recorded defect, not a refusal**. Rationale: an under-constrained sketch still extrudes, and U5's restore check is precisely the instrument that measures whether the under-constraint is harmful — geometry that wanders under perturbation fails the observable-restore assertion. Refusing here would discard a probably-good model on an indirect signal when a direct measurement is one unit away. The result label, however, may not claim full constraint: the report's per-sketch record is what the doctrine points users at.

**What makes this honest rather than hopeful:** every constraint that survived did so under a measured displacement bound; every one that did not survive is named with its measurement; and the sketch's final constraint state is a recorded boolean, not an inference.

## D4 — Feature ordering: a dependency DAG with a deterministic total order, computed host-side

The order features are created is the parametric structure. It is derived, not guessed:

1. **Nodes** are the program's archetype instances. **Base nodes** are `new-body` operations (the first) and `join` operations; **cut nodes** are cut extrudes and holes; **finishing nodes** are fillets (U6/PR5 emission, but ordered now — the DAG doesn't care when the emitter learns to build them).
2. **Edges:**
   - every cut/join depends on the base body it modifies — established host-side by containment: the cut region's inlier centroid (from U2's inlier sets) lies inside the base archetype's fitted volume, or within `entity_match_tolerance` of its boundary;
   - a hole depends on the archetype owning its entry face (the fitted plane its axis pierces, matched host-side by axis–plane intersection against cap planes);
   - a fillet depends on both archetypes owning its adjacent faces;
   - a sketch plane defined by offset from another feature's cap depends on nothing extra — offsets come from origin geometry (D2), which deliberately removes a whole class of inter-feature plane dependencies.
3. **Root selection:** the base node with the largest supporting area is the first feature — the same heuristic Design X applies ("the big prismatic/turned core first"), and deterministic because support area comes from the fit record.
4. **Total order:** topological sort with tie-break `(dag_depth, -support_area, archetype_id)` where `archetype_id` is the region-hash-derived identifier — no dict-iteration order, no temp ids (parent A3 discipline).
5. The order is embedded in the program (`order` is an explicit list) and the planner *re-derives and cross-checks* it at emission time, refusing `program-order-invalid` on mismatch — so a hand-edited program cannot smuggle an unsound order into Fusion.

Cycles cannot arise from the edge set above (cuts depend on bases, fillets on both, bases on nothing), but the sort still detects and refuses `program-order-cyclic` rather than assuming — a malformed program is an input, not an impossibility.

## D5 — Face and edge identity: resolve at consumption from feature-owned collections; record tokens as evidence

The classic trap is indexing `body.faces` and watching indices shuffle on rebuild. The design sidesteps the trap for construction and instruments it for evidence:

- **Within the emission transaction** (the only place references are *consumed* in PR 4), every reference is resolved immediately after the prerequisite feature is created, from that feature's own collections: `endFaces`/`startFaces`/`sideFaces` for extrudes, `faces` for revolves (B5). Resolution is geometric: among the candidate faces, take the one whose surface type matches the fitted primitive and whose sampled point lies within `entity_match_tolerance` of the fitted surface. Zero or multiple matches refuse `entity-resolution-ambiguous` naming the feature and the candidates' surface types — never "take the first".
- **Holes**: the entry face is resolved as above from the host feature's cap; the placement is a sketch point on a sketch created *on that resolved face's fitted plane equivalent* — i.e., on the same datum-offset construction plane the cap was built from, which exists independently of face identity. The point is dimensioned to the datum origin (two driven linear dimensions → hole-position parameters). This means hole *placement* never references a B-Rep face at all; only the hole feature's target body does. Position edits survive any rebuild by construction.
- **Fillets** (ordered now, emitted in PR 5): edge resolution = the shared edges of the two parent features' face sets, filtered by proximity to the fitted adjacency curve. Same ambiguity refusal.
- **Evidence**: every resolved reference's `entityToken` goes into the rebuild record (E9). U5 re-resolves tokens after each recompute and reports the outcome as data (B6) — the token stability question is thereby *measured by the feature's own verification loop* instead of assumed in either direction. If tokens prove unstable, the rebuild record's names+geometry remain the durable identity, and the doctrine says so.

## D6 — The parameter model: few, shared, named, and unit-explicit

Parameters are the user's edit surface; their design is UX, not plumbing.

- **Naming**: `recon_<archetype-role>_<n>_<quantity>` — e.g. `recon_base_1_depth`, `recon_hole_2_dia`, `recon_hole_2_x`, `recon_plate_1_width`. Deterministic from the program order; recorded in the rebuild record; collision with existing user parameters refuses (E4).
- **Sharing**: an adopted `equal_radius` relationship produces *one* parameter driving several dimensions (via `equal` constraints where in one sketch, via shared expression where across sketches). An adopted coaxial pair shares position parameters. This — not raw dimension count — is what makes the model feel intentional, and it comes free from U3's adoption records.
- **Units**: every parameter is created with an explicit unit and its nominal value from the fitted geometry, with a comment naming the archetype id and the fit it came from — a user hovering a parameter sees where the number came from.
- **What is parameterized**: sketch dimensions, extrude/revolve extents, construction-plane offsets (cap positions), hole diameters/depths/positions. What is not: the datum frame itself (it is the reference, not an edit target) — recorded in doctrine.

## D7 — The perturbation proof: declared observables, one parameter at a time, restore-verified, feature-attributed

Plan 005's R11 asserts volume change as the inertness test. **That is wrong for a class of parameters this design deliberately emits: position parameters** (hole x/y, cap offsets on symmetric bodies) can change the model materially while preserving volume to within noise. A volume-only test would brand them inert and fail a correct model — the opposite over-claim. The design generalizes R11 rather than weakening it:

Each parameter's spec declares `expected_observable ∈ {volume, centroid, bbox}` with a rationale, plus `min_observable_change` and the perturbation itself. Volume for size-like parameters; centroid displacement (mm) for position-like; bbox extent for outer-envelope parameters. Doctrine guidance: perturb by 5–10% of nominal, with expected effect at least 100× the restore epsilon, and the CLI validates the arithmetic consistency of each spec (a declared `min_observable_change` below `observable_restore_epsilon` is rejected as unmeasurable — you cannot assert a change smaller than the noise you tolerate on restore).

The loop, per parameter, in rebuild-record order:

1. Baseline: timeline health (G4's `_timeline_health`), body count, and all three observables via `physicalProperties` at the highest accuracy setting (B9), plus the parameter's current expression — which must equal the rebuild record's nominal, else `rebuild-record-mismatch`.
2. Set perturbed expression; `computeAll()`; `_pump_events`.
3. On exception or unhealthy timeline: walk the timeline, collect unhealthy features by deterministic name + `errorOrWarningMessage`, map to rebuild-record archetypes, record `parameter-broke-rebuild {parameter, features, messages}` (E11); restore; recompute; continue to verdict.
4. Otherwise assert: body count unchanged (`body-count-changed` failure); declared observable moved by ≥ `min_observable_change` (`parameter-inert` failure); when the spec declares an expected direction, the sign matches (`parameter-effect-reversed` failure). The two undeclared observables are *recorded*, not asserted — evidence without over-claim.
5. Restore original expression; `computeAll()`; assert all three observables return within `observable_restore_epsilon` (`parameter-not-restorable` — failure, loop aborts, remaining parameters reported `not_exercised`, document left at original expressions).
6. Re-resolve this parameter's features' entity tokens; record resolution outcomes (D5/B6).
7. **Only now** append the parameter name to `checked` (E12).

After the loop, two whole-model checks: every rebuild-record body is backed exclusively by timeline entries of the emitted feature types and no `baseFeature` (string comparison of feature `objectType`s against a closed allow-list — `base-feature-detected` failure); and the component/feature/parameter census still matches the rebuild record.

What the report refuses to claim, written into it: `interactions_exercised: false` (parameters were perturbed one at a time; joint perturbation is future work); parameters in `not_exercised` are unproven; token resolution results are measurements, not guarantees; and there is no `parametric: true` boolean anywhere — the label is the parent's closed set plus this report's per-parameter verdicts.

Forgeability: the report embeds the CLI nonce (E13/G6) and every upstream hash; the host-side validator (offline-testable) checks nonce, hashes, and that `checked` ⊆ declared parameters with no failure tokens — the six-line-forgery hole is closed by binding the report to a value that exists only in this emission's generated source.

## D8 — Failure, refusal, and the replan loop: planned partiality succeeds; unplanned partiality refuses, then replans explicitly

Two different situations, two different behaviours, and the distinction is the design:

**Planned partiality** — the program itself declares some regions `unreconstructed` (U3's honest output). Emission builds everything the program declares, succeeds, and the result is `parametric-partial` with `covered_area_fraction` and the unreconstructed list carried into the report. The user gets: an editable model of the recovered features, the source mesh overlaid as reference geometry in the same document (E2 — this *is* the "reference geometry" outcome the commercial tools ship), and a report naming each unrecovered region with area fraction, bounding box, and failed gate. This is a success, and the doctrine says so in those words.

**Unplanned partiality** — a feature fails *during* emission (`feature-failed`, `constraint-rejected-budget-exceeded`, `entity-resolution-ambiguous`, `solver-unhealthy`). The transaction rolls back everything it created — features, sketches, planes, parameters, the component — in reverse creation order (B8), reports the named refusal with the failing archetype id and Fusion's message, and produces **no geometry**. Argument: a half-emitted model differs from the declared program, so shipping it would make the program hash a lie and every downstream binding unsound; and the failure point was chosen by the solver, not by anyone accountable. The refusal is not the end of the workflow, though: the CLI's `replan-without` flow takes the refusal report plus the program and emits a *new* program (new hash, failed archetype moved to `unreconstructed` with the refusal token as its gate, coverage fraction recalculated) for a second emission run. One explicit, recorded command — ambition delivered through a visible loop rather than through in-Fusion improvisation.

**The closed refusal vocabulary** (validated, documented in doctrine):

- U4 planning (host-side, before any transaction): `program-version-unsupported`, `program-schema-violation`, `program-order-invalid`, `program-order-cyclic`, `plane-unmappable`, `parameter-name-collision` (when detectable from the manifest), `profile-not-closed` (a profile whose entities do not chain closed is not a profile and is never force-closed).
- U4 transaction: `rebuild-capability` (named missing API member), `dump-hash-mismatch` (named section), `parameter-name-collision` (live check), `entity-resolution-ambiguous`, `constraint-rejected-budget-exceeded`, `feature-failed`, `solver-unhealthy`, `document-changed` (existing `DocumentChangedError`), `rollback-incomplete` (B8 failure — a refusal that additionally names what it could not clean up).
- U5: `editability-capability`, `rebuild-record-mismatch`, and the failure verdicts `parameter-inert`, `parameter-effect-reversed`, `parameter-broke-rebuild`, `parameter-not-restorable`, `body-count-changed`, `base-feature-detected`.

## D9 — The program contract U4 consumes, stated now so U3 and U4 collide loudly, not quietly

G1: U3 does not exist yet, so this is the negotiated interface, enforced by U4's validator with the `_reject_unknown_fields`/`_in_closed_set` pattern (G8). U4 requires of the program (superset of parent R16):

- header: `program_version` (int; U4 v1 accepts exactly 1), `dump_sha256`, `manifest_sha256`, `program_sha256` (canonical sorted-key JSON, `manifest_sha256` convention), `datum` {origin, axes, derivation record}, `covered_area_fraction`, `unreconstructed[]` {region id, area fraction, bbox, gate};
- `user_parameters[]`: name, quantity kind, unit, nominal, rationale, driving archetype ids (shared parameters list several);
- `archetypes[]`: `id` (region-hash-derived), `kind ∈ {sketch-extrude, revolve, hole, fillet}`, `operation ∈ {new-body, join, cut}`, `plane` {datum plane, offset, optional rotation axis+angle} for sketch-bearing kinds, `profile` {ordered `SketchEntity` dicts (G2 vocabulary), `closed: true}` where applicable, `extent`/`axis`/`diameter`/`radius` fields per kind with parameter bindings, `constraints[]` (adopted relationships localized to this sketch, each with measured deviation), `dependencies[]` (archetype ids);
- `order[]`: explicit total order over archetype ids (cross-checked per D4);
- declared thresholds with rationales (E14 set, plus U2/U3's, carried for the evidence chain).

Anything unknown, missing, or out-of-vocabulary refuses `program-schema-violation` naming the path. The validator is pure host-side stdlib and fully offline-tested — it is also where the RANSAC redirect is absorbed: U4 is indifferent to whether profiles came from mesh sections or from RANSAC inlier-boundary projections, because the contract is the entity list, not its provenance.

# Implementation Units

Both units land in PR 4 together, per the parent's sequencing and for the parent's reason. Within the PR, U4's host planner lands first (fully offline-tested), then the executor template, then U5.

## U4 — `mesh_rebuild.py`: program validator, emission planner, and the rebuild transaction

**Files:** `src/fusion_design/mesh_rebuild.py` (new: validator, planner, emitter, embedded executor template), `src/fusion_design/mesh_dump.py` (shared canonical serializer — single source used by both the U1 writer and the embedded re-hash; if U1's branch lands a different filename, the joint PR reconciles here), `src/fusion_design/cli.py` (`emit-mesh-rebuild`, `replan-without`), `schema/fusion-project.schema.json` (if the manifest grows a reconstruction section), `tests/test_mesh_rebuild.py`, regenerated byte-pinned example under `examples/electronics-enclosure/generated/` (a small synthetic program checked in with its emitted transaction).

**CLI:** `fusion-design emit-mesh-rebuild <manifest> --classification <c.json> --program <program.json> --rebuild-spec <spec.json>` (spec carries E14's emission thresholds + output paths + nonce handling); `fusion-design replan-without <program.json> --refusal <report.json>` (D8).

**Host planner responsibilities (all offline-tested):** program validation (D9); datum-frame projection and 2D sketch coordinates; plane mapping with `plane-unmappable` (E3); profile chain-closure check (`profile-not-closed`); constraint schedule construction (D3 layers, deterministic order); dimension-set derivation; parameter table with deterministic names and dedup (D6); DAG + total order + cross-check (D4); emission-plan serialization.

**Executor responsibilities (template, offline-executed against stubbed adsk):** prelude checks (G4) + classification gate (`require_classification`, `parametric-rebuild` only); capability probes per E16; live dump re-hash (E8); parameter creation pass; per-archetype construction in declared order with per-step displacement checks, entity resolution, deterministic feature naming, `_pump_events_periodically`; rollback protocol (D8); report assembly with `created` built append-after-success and nonce+hashes (E12/E13).

**Test scenarios** (extending the parent's): box program → one plane, one sketch, four chained lines, `horizontal`×2 + `vertical`×2, two dimensions + origin anchors, one new-body extrude, `fully_constrained: true` in the stub; turned-part program → revolve about `zConstructionAxis` with axis-containing plane; hole program → placement sketch dimensioned to origin, hole depends on base in the order; profile that does not chain → `profile-not-closed`, no transaction generated; oblique plane → `plane-unmappable`, archetype re-declared unreconstructed host-side; program with shuffled `order` → `program-order-invalid`; cyclic hand-made program → `program-order-cyclic`; unknown archetype kind / unknown key / wrong version → `program-schema-violation` naming the path; stubbed displacement beyond tolerance → constraint deleted and recorded, emission continues; rejections beyond budget → refusal + full rollback (stub records deletions in reverse creation order — asserted); stubbed feature-creation raise mid-run → every prior creation deleted, `feature-failed` names the archetype; dump-hash mismatch stub → refusal before any creation; determinism: identical program emits byte-identical transaction twice, and shuffled-input program (same content, different JSON order) emits identical plan; string-search suite: no `baseFeatures`, `designType`, `TemporaryBRepManager`, `subprocess`, `os.system`, `body.faces[`, bare `getattr(..., None)` (E15/E16); byte-pinned example matches emitter.

**Live-Fusion dependency: YES** for solver acceptance (B2–B5, B8, B11) — everything else offline. **Size: L** (the largest single unit in this PR; the planner is the bulk and is pure).

## U5 — `mesh_editability.py`: the perturbation proof

**Files:** `src/fusion_design/mesh_editability.py` (new: spec validator, emitter, host-side report validator), `src/fusion_design/cli.py` (`emit-mesh-editability`, plus report validation on ingest), `references/verification-contract.md` (new "Reconstruction editability" section), `tests/test_mesh_editability.py`.

**CLI:** `fusion-design emit-mesh-editability <manifest> --rebuild-record <r.json> --editability-spec <spec.json>`; spec per D7 (per-parameter perturbation, expected observable, min change, rationale; `observable_restore_epsilon`); CLI validates spec arithmetic (E14/D7) and generates the nonce.

**Transaction:** exactly D7's loop, plus the whole-model base-feature and census checks, `checked` built append-after-success, nonce + all four hashes in the report.

**Host-side validator** (offline): nonce match, hash chain match, `checked` ⊆ declared, failure tokens ⇒ non-passing verdict, `not_exercised` + `interactions_exercised: false` present. This is the function the orchestrating agent calls; it cannot pass a report that asserts more than it ran.

**Test scenarios:** stub with three parameters, one inert → `checked` has two entries, verdict fails, inert parameter named; stub whose `computeAll` raises on parameter 2 → parameter 2 absent from `checked`, `parameter-broke-rebuild` names the stub's unhealthy feature name and message, parameters 3+ listed `not_exercised` after restore (R12 enforcing test); stub whose restore leaves volume outside epsilon → `parameter-not-restorable`, loop aborted, document expressions restored-attempted state reported; position-parameter stub with volume unchanged but centroid moved → passes (the D7 generalization's regression test); declared-direction stub with reversed sign → `parameter-effect-reversed`; base-feature-backed body stub → `base-feature-detected`; census mismatch stub → `rebuild-record-mismatch` before any perturbation; token re-resolution recorded for both resolve and fail stubs without affecting the verdict; report validator rejects wrong nonce, missing hash, `checked` superset; string search: `designType` absent from generated source.

**Live-Fusion dependency: YES** for the actual proof (B6, B9, B10). **Size: M.**

# Verification Contract

**Offline (`scripts/test.sh`, unittest + compileall):** everything in both units' test scenario lists — program validation, planning determinism, plane mapping, constraint scheduling, DAG ordering, all refusal paths of both generated transactions driven through the stubbed-`adsk` harness, rollback ordering, `checked`/`created` append-after-success enforcement, report validator, string-search invariants, byte-pinned examples. This covers the full decision surface of the feature.

**Not established offline — stated, not implied**, each with the live step that establishes it:

| Not established offline | Established by |
| --- | --- |
| Solver accepts the layered constraint schedule on real sketches (parent A6) | U4 live run; per-constraint displacement records are the measurement |
| B2 offset/angle construction planes are parametric and parameter-driven | U4 live run |
| B3 shared-SketchPoint chaining; B4 parameter binding of dimensions and extents | U4 live run |
| B5 feature-owned face collections populate within the transaction | U4 live run (hole archetype) |
| B8 reverse-order `deleteMe` rollback completes | U4 live run of a deliberately failing program (acceptance step) |
| B6 entityToken stability across recompute | U5 loop, reported as measurement |
| B9 physicalProperties noise floor vs restore epsilon | U5 live run |
| A parameter change actually rebuilds the model (the feature's central claim) | U5 live perturbation loop |

**What the reports never claim:** no `parametric: true` boolean; `ok` scoped to `checked`; unexercised parameters and interactions named as unexercised; coverage stated as a fraction with the unreconstructed list; token stability reported as per-run measurement; `designType` nowhere in generated source.

# Definition of Done

E1–E16 implemented and offline-tested; both transactions byte-pinned as examples; `emit-mesh-rebuild`, `replan-without`, and `emit-mesh-editability` wired into the CLI following G10's pattern; `references/verification-contract.md` gains the editability section and `references/unsupported.md` records `plane-unmappable`'s v2 escape hatch and the interactions-unexercised boundary; the closed refusal vocabulary documented; live acceptance (with U6/PR 5's end-to-end case per the parent): a program emitted into a named Fusion version producing a timeline of named features in a dedicated component, every declared parameter surviving the perturbation loop, the report validated by the host-side validator, and the result label carrying an honest coverage fraction. `scripts/test.sh` green throughout; no new dependency anywhere.

# Where this design disagrees with the parent plan

1. **R11's inertness test (volume-only) is replaced by declared observables** (D7). Volume-only would fail correct position parameters — an over-claim in the failure direction. The generalization is strictly stronger: it still catches dead parameters, and it additionally catches a sign-reversed effect when the caller declares direction.
2. **KTD8's construction-plane story was unstated and hides a real API trap.** The parent's `sketch-extrude` row implies making a plane "at the cap plane"; `setByPlane` cannot do that in parametric mode (B1). D2's datum-aligned strategy is the correction, and it adds the honest scope edge `plane-unmappable`.
3. **Hole emission should move from U6/PR 5 into this PR.** The face-resolution and placement-sketch machinery (D5) is built here regardless; holes are the most common mechanical feature and the first real consumer of B5; and D6's shared-diameter parameters are the strongest editability demonstration U5 can exercise. Recommend PR 4 = sketch-extrude + revolve + hole; PR 5 = fillet + coverage/doctrine/acceptance. Fillets stay out of PR 4 because edge resolution and per-fillet optionality are genuinely separate work.
4. **`sketch-underconstrained` is a recorded defect, not a refusal** (D3). The parent is silent on this case; the design chooses emission + honest record + U5 measurement over refusal, and gives the argument.
5. **Mid-emission failure refuses (parent R14 upheld) but gains the explicit `replan-without` loop** (D8) — the parent's refusal-only story leaves the user with nothing after a single solver disagreement; the loop delivers the commercial-tool outcome (mostly-reconstructed model + reference geometry) without ever improvising inside Fusion.
6. **The parent's Fusion-side executor is kept but demoted further than the parent implies**: the plan text has the transaction "following the established pattern" per archetype; this design fixes the executor as a single data-driven interpreter over an emission plan (D1), because bespoke generated control flow per model would defeat the byte-pinning and stub-execution disciplines that make the offline gate meaningful.

# Hardest unresolved risks

1. **Solver behaviour under the snap-and-check protocol is unmeasured** (parent A6, B2–B4). The design turns it into per-constraint measurements with budgeted rollback, but if Fusion's solver rejects or distorts at rates far above expectation on real profiles, `constraint-rejected-budget-exceeded` becomes the common path and the replan loop degrades models toward under-constrained or unreconstructed. Mitigation is measurement-first: the first live runs report every displacement, giving real numbers to tune `snap_tolerance_*` and the budget against. This is the risk that decides whether PR 4's live acceptance is a day or a week.
2. **The U3 contract is negotiated against code that does not exist** (G1, B12). The validator makes divergence loud, but a semantic mismatch — e.g., U3 emitting profiles as raw polylines rather than classified entities, or omitting operation/orientation — costs a cross-branch rework cycle at integration. Mitigation: land D9's validator early and hand U3's worker the fixture programs from U4's test suite as their conformance target.
3. **Rollback completeness rests on B8.** If `deleteMe` fails for some entity class mid-refusal, the document is left dirty and `rollback-incomplete` is the honest-but-unsatisfying outcome; there is no API-level transaction to lean on from a script. Mitigation: the deliberately-failing acceptance run exercises rollback before any real user does; and the emission order (parameters first, features in DAG order) is chosen so reverse deletion has well-defined dependents at every step.

# Not achievable within these constraints

- **Adaptive in-Fusion recovery** (retry a feature with altered geometry when the solver objects): excluded by E1/D1 on principle — adaptation without offline testability is improvisation. The replan loop is the constrained substitute.
- **Guaranteed fully-constrained sketches**: the solver is a black box; D3 aims at full constraint and records the truth. A guarantee would require our own DOF analysis — a constraint-solver project the parent already rules out.
- **Cross-session face identity guarantees**: `entityToken` stability is measured, not promised (B6/D5); the durable identity is deterministic names + fitted geometry.
- **Joint-parameter interaction proof**: U5 v1 perturbs one parameter at a time and says so (`interactions_exercised: false`). Pairwise perturbation is a straightforward v2 of the same loop, deferred for run-time (n² recomputes), not difficulty.
- **Oblique sketch planes** (`plane-unmappable`, D2): bounded by the parametric-mode construction-plane API, with a documented v2 escape hatch (scaffold-sketch three-point planes) — a named API limitation, not general pessimism.
