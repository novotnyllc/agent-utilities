# Verification contract

Scope: this contract governs the skill's automation and release lanes — the
generated verification transaction, the export binding, variants, and the
reconstruction gates. During ordinary modeling, inspection is native and
direct: Measure, Interference, Section Analysis, Properties, and feature
health, read straight from Fusion at sensible boundaries. The evidence
machinery below is applied when a release, handoff, repeatable generator, or
reconstruction requires it, and it is never a license to build agent-authored
validation — every check here is either a native Fusion result or a
fail-closed judgment shipped in this skill's tested tooling.

A release passes only the checks applicable to its intended use. “Generated successfully” is not a verification result.

## Digital model integrity

- Active product is a Fusion Design.
- Design type is parametric.
- The inventory and verification reports carry `document_saved_state` — the
  document's `isSaved`, current name, and dataFile identity (id, version,
  project and folder ids) — fail closed: an unreadable probe is reported as
  `available: false` with a named reason, never defaulted, because "unsaved"
  and "could not read" must not look alike. An unsaved working document at
  verification time means the document-save transaction was skipped; run it
  rather than exporting from a document a crash could erase.
- `Compute All` runs.
- No timeline error remains; warnings are individually explained.
- No *undeclared* timeline feature is suppressed. Suppression silently changes the shape away from the recorded intent, so `timeline-suppressed` fails closed unless the manifest declares `verification.allow_suppressed_timeline_features: true` — the escape hatch for designs that model configurations by suppression. Declared suppression is still recorded in `timeline.suppressed`.
- Required parameter names and expressions match the manifest.
- Managed components and print parts exist once at the intended paths.
- Each printable part resolves to exactly one positive-volume B-rep solid — closed by definition (`BRepBody.isSolid`; a surface body is open and never printable) — whose volume is at or above the declared `printable_parts[].minimum_volume_mm3` and whose name matches the declared `body_name` when one is given. A print part with no `printable_parts` entry fails: verification asserts declared expectations, never a bare "some body exists" threshold.
- The declared floor is itself cross-checked against geometry the author did not choose: a floor below `print_part_rules.minimum_volume_bounding_box_fraction` of the part's own B-Rep bounding-box volume fails as `implausible-declared-minimum`, so a forged floor cannot re-open the sliver hole. The report separates `print_part_expectations` (manifest-declared) from `print_part_rules` (skill-wide constants) so a reader can tell them apart.
- The verification report records each checked part's root-context occurrence transform (`occurrence_transforms`: raw Fusion `transform2.asArray()`, translation components in centimetres — deliberately unconverted, unlike the `*_mm` keys; the export index's per-artifact `transform` uses the same convention).
- When the manifest declares `printable_parts`, its paths exactly match `verification.expected_print_parts`, and a declared `body_name` matches the resolved solid at export (`body-name-mismatch` fails closed).
- No accidental visibility/selection state is being used as a substitute for geometry: the report records `occurrence_states` (`isSuppressed`/`isLightBulbOn`/`isVisible`) for every checked path. A suppressed checked occurrence fails closed as `suppressed-occurrence` unless its path is declared in `verification.allowed_suppressed_paths`, and a path whose state could not be read at all fails as `unreadable-occurrence-state` — a suppressed *or unknown* keep-out contributes no geometry to interference, so "zero interference" and "not in the model" would otherwise be indistinguishable.
- The report's `ok` is scoped to the gates it names in `checked`, and `checked` is derived from what that run actually performed. A gate the manifest never declared appears in `not_declared`, never in `checked`: "this project declares no clearance checks" is an honest gap and must never read as a passed check. Everything in `unchecked` — printability, structural, thermal, physical — stays `not run` until the sections below are satisfied by external analysis or a printed part. Report it as "passed the gates it declared", not as "verified".

### What the export's verification binding covers

`emit-export` binds three measured properties per print part out of the passing report — `brep_bounding_boxes_mm`, `geometry[path].total_solid_volume_mm3`, and `occurrence_transforms[path]` — and the generated transaction re-measures all three in the live design before exporting, failing closed on any drift (`bounds-drifted`, `volume-drifted`, `transform-drifted`).

This is a **sampling of properties, not a proof of identity.** A post-verification edit that preserves extent, volume, and placement — relocating a hole, exchanging a fillet for an equal-volume chamfer — is not detected, and the report's `clearance_results` and `interference_results` are not re-run at export time. Read the binding as evidence of *which* verification report justified the export, never as evidence that the exported geometry is the verified geometry. Re-run verification after any change that touches geometry.

### The evidence chain is transitive

Each artifact carries the bindings of the one before it, so a reader can walk backwards from a print job to the design that justified it:

`manifest_sha256` → verification report → export index (`manifest_sha256` + `verification_report_sha256` + `export_run_id`) → PrusaSlicer project (all three, carried forward) → slice (`bindings`, including the `project_sha256` re-checked against the file on disk).

A missing link fails closed at the hop that needed it: an index without `verification_report_sha256` or `export_run_id` cannot build a project, and a slice without a matching `project_sha256` is refused before the binary runs.

## Fit and packing

- Packing occurrences use recorded transforms.
- Every manufactured item has an authoring and packing representation.
- Every applicable connector/cable/tool/service/thermal/RF/motion keep-out exists.
- Minimum-distance checks meet the recorded requirement.
- Forbidden interference checks return zero.
- Intended contacts are documented and excluded from “forbidden” checks.
- Closed, open, and service states are checked. **Manual gate:** nothing in the generated transactions poses the assembly or switches configurations. Drive each state in Fusion yourself and re-run verification per state, declaring the occurrences and timeline features each state suppresses (`verification.allowed_suppressed_paths`, `verification.allow_suppressed_timeline_features`) so the state under test passes while undeclared suppression still fails.

## Mesh reconstruction deviation

When a body was rebuilt from or converted out of a mesh, grade it against the immutable source with `fusion-design emit-mesh-deviation`. The verdict is **asymmetric and two-directional**; record both numbers with the question each answers, and never collapse them into one:

- **Invented material** — rebuilt surface lying outside the source solid, beyond the declared `invented_material` threshold. **Hard failure**, naming coordinates.
- **Omitted detail** — scanned detail absent from the rebuild, beyond the declared `omitted_detail` threshold. **Advisory**: a rebuild models only the geometry the edit requires.

Rules that make the numbers mean something:

- Thresholds are declared per reconstruction with a rationale and recorded with the verdict; they are never module constants.
- Percentiles may use a strided sample; **any distance compared against a threshold is measured exactly**.
- Both directions are measured with released APIs. `PolygonMesh.compareWith` is preview and, for a B-Rep reconstruction, structurally unavailable — a `BRepBody`'s mesh is a `TriangleMesh`, which has no `compareWith`. It is corroboration only: recorded beside the native measurement, flagged when it disagrees, never preferred.
- Containment uses a native B-Rep query (`BRepBody.pointContainment`), not a mesh-only occurrence, so this stays consistent with the clearance/interference rule above. Inside means invented material and outside means omitted detail, and that mapping is **verified on the body itself** — a point far beyond the bounding box must read outside, and a pair straddling a tessellation facet must read one side each and both measure the step. When it does not reproduce, the run fails closed and the invented-material verdict is `not-established` — never a pass, never a fabricated number.
- The reconstruction's boundary is read through a tessellation whose `surfaceTolerance` is one tenth of the declared `invented_material` threshold and whose `maxSideLength` is the source mesh's median edge. Both are recorded, and so is the fact that Fusion does not report the tolerance it achieved.
- A small deviation in either direction is not a fitness claim. A fit coupon is still required before any claim of physical mating.

## Parametric robustness

Exercise representative parameter changes:

- minimum and maximum intended enclosure size;
- wall/clearance process variants;
- user-facing styling values;
- component revision or configuration if supported.

After each variant, recompute and verify the same invariants. A model is not meaningfully parametric if a small allowed change breaks the timeline or causes self-intersection.

## Printability

Record the intended build direction and evaluate:

- bed-contact stability;
- minimum walls/floors/roofs;
- boss/rib/clip dimensions;
- unsupported overhangs and bridges;
- support accessibility and removal;
- trapped volumes and drainage where relevant;
- first-layer and warping risk;
- seam/fit tolerance;
- hole/insert compensation;
- part orientation versus load path.

Core generated scripts do not claim these checks automatically. Use a configured slicer, an installed trusted add-in, an existing validated analyzer already present when the lane locked, manual measured review, or a physical coupon, and record the evidence — never an analyzer authored during the CAD task.

## Structural and safety

- Loads and supports are explicitly named.
- Connector insertion/pull loads reach grounded structure.
- Fastener loads reach bosses/walls with adequate edge distance.
- Layer orientation is compatible with likely tension/shear.
- Sharp body-facing or cable-contact edges are removed.
- Material temperature assumptions are compatible with nearby heat sources.
- Electrical insulation, fuse, wire gauge, and voltage separation are reviewed outside CAD by a qualified method.

Do not infer electrical or thermal safety solely from geometric clearance. Fusion simulation is extension-gated and its presence is never assumed: the base-tier structural evidence is conservative geometry, a coupon, or a physical proof test with an explicit safety factor.

## Physical validation

Mark each physical item `not run`, `pass`, or `fail`:

- actual component fit;
- cable/plug fit;
- fit coupon;
- fastener torque/retention;
- lid cycles;
- clip cycles;
- thermal soak;
- proof load;
- garment comfort/attachment;
- water/dust ingress when claimed.

Digital evidence cannot convert an unperformed physical test to `pass`.

## Reconstruction emission

`emit-mesh-rebuild` decides everything decidable without Fusion, host-side and
under test, and hands the transaction a fully-ordered build list it interprets
without making a single choice of its own. Anything not constructible exactly as
declared is a named refusal.

Planning refusals, before any transaction exists:
`program-schema-violation`, `program-order-invalid`, `program-order-cyclic`,
`program-parameter-unbound`, `plane-unmappable`, `units-unsupported`,
`cap-order-inverted`, `profile-not-found`, `profile-not-closed`,
`profile-ambiguous`, `entity-resolution-ambiguous`,
`archetype-kind-unsupported`, `parameter-name-collision`. Reading the mesh dump
additionally refuses `dump-hash-mismatch` before a single byte is parsed.

Two of those are worth naming. `units-unsupported` fires when a program declares
anything but millimetres: the dump format writes millimetres, so every number
reaching the emitter is a millimetre figure and relabelling them would put the
sketch geometry and the dimension driving it a conversion factor apart.
`cap-order-inverted` fires when the declared sketch-plane offset names the far
cap rather than the near one — detected by probing the mirrored station, and
named rather than silently flipped, because the extrude direction would still be
wrong and repairing a program inside the emitter is the improvisation this unit
exists to prevent.

Transaction refusals: `rebuild-capability` (naming the missing API member),
`parameter-name-collision` (checked live), `constraint-rejected-budget-exceeded`,
`feature-failed` (naming the archetype and Fusion's message), `solver-unhealthy`,
`profile-not-found`, `document-changed`, and `rollback-incomplete`.

On any refusal the transaction deletes everything it created in reverse creation
order — features, then sketches, then planes, then parameters, then the
component, because a user parameter a live dimension still references will not
delete. A half-emitted model differs from the program it claims to implement,
which would make every downstream hash binding a lie.

`created: []` states what the transaction *delivers*, and a refusal delivers
nothing. What the document still holds is a separate question and `created` must
not be read as answering it: `document_state` is `"rolled-back"` or `"dirty"`,
and a dirty report names what would not delete in `rollback_remaining`. A dirty
report also carries both tokens — the refusal first, then `rollback-incomplete`
— because the failed cleanup is a second thing that went wrong, not a
replacement for the reason. `replan-without` refuses a dirty report outright:
emitting a second component beside the wreckage of the first is not a replan.
`replan-without` turns the refusal into a smaller program — the failed archetype
moved to `unreconstructed` with the refusal token as its gate, coverage reduced,
a new program hash — so a second run is one explicit, recorded command away
rather than an improvisation inside Fusion.

Each applied sketch constraint records the deviation it snapped from, and the
displacement it actually caused; only displacement *in excess* of the snap counts
against the declared tolerance. Rejections are recorded individually with their
measurements, and `fully_constrained` is whatever the sketch reported — `true`,
`false`, or `"unavailable"` when the property is absent. It is never inferred.

Each sketch also reports `profile_displacement_mm`: how far the furthest sketch
point ended up from where the mesh section put it. Deleting a rejected constraint
removes the constraint, and whether Fusion also returns the geometry it already
moved is not something a script can establish — so the distance is measured and
reported rather than assumed to be zero. An under-constrained or wandered profile
is a recorded defect, not a refusal: the direct instruments for it are the
sketch's own `fully_constrained` flag, the deviation run against the immutable
source mesh, and the editability proof's restore assertion.

## Reconstruction editability

A reconstruction claims to be an editable model. `designType == ParametricDesignType`
does not establish that: it is equally true of a document holding one faceted
body and no timeline. The only evidence that counts is a measurement.

`emit-mesh-editability` perturbs one user parameter at a time and, per parameter:

1. records all three observables — volume, centroid and bounding-box extent —
   at the nominal expression;
2. sets the caller-declared perturbed value and recomputes;
3. asserts the parameter's **declared** observable moved by at least the
   declared minimum. Volume alone is the wrong instrument: a plane-offset or
   hole-position parameter can move a feature bodily through the part while
   preserving volume to within noise, and a volume-only test would report it
   inert and fail a correct model. The other two observables are recorded and
   asserted against nothing;
4. restores the original expression, recomputes, and asserts all three
   observables returned within the declared restore epsilon;
5. only then appends the parameter name to `checked`.

Record for each run:

- `checked` — parameters that completed all of steps 1-4. Nothing else may
  appear here.
- `not_exercised` — parameters the spec deliberately skipped, and every
  parameter after an aborted restore. These are unproven and the report says so.
- `restore_failure` on a parameter row, recorded separately from `failure` so a
  parameter that broke the rebuild *and* then would not restore keeps both
  attributions instead of the second erasing the first. Restoring means two
  things and both are checked: the observables come back within the epsilon, and
  the timeline is no sicker than it was before the perturbation.
- `unattributable_unhealthy` — timeline entries this perturbation broke whose
  name could not be read. They still count as broken. A nameless entry reading
  as "not one of ours, so nothing broke" would convert an absent API into a
  pass, and damage that predates the perturbation is excluded by comparing
  against a baseline taken before the expression changed.
- `failures` — from the closed set `parameter-inert`,
  `parameter-effect-reversed`, `parameter-broke-rebuild`,
  `parameter-not-restorable`, `body-count-changed`, `base-feature-detected`,
  `rebuild-record-mismatch`, `editability-capability`, `document-changed`. A
  break names **which parameter broke which feature**, by the feature's own
  deterministic name, with Fusion's own message.
- `interactions_exercised: false` — always. Parameters are perturbed one at a
  time; no interaction between two of them was exercised by this run.
- `entity_tokens` — per-parameter token re-resolution counts. These are a
  measurement of this run, never a guarantee of token stability.

`check-editability` is the gate. It matches the nonce `emit-mesh-editability`
minted and the manifest/dump/program/rebuild hash chain, and it re-derives every
name in `checked` from the row that recorded the measurement — the nonce proves
the report came from the emitted script, not that any individual name earned its
place. A name in `checked` with no row, a row that says it was not exercised, a
row carrying a failure, or a row with no restore measurement all fail the gate,
as does a report whose `ok` sits beside a failure, whose failures fall outside
the closed set, or that leaves a parameter neither proven nor named unexercised.
A spec in which every parameter declares `exercise: false` is rejected before
emission: a proof that exercises nothing proves nothing. A hand-written report
cannot satisfy the gate: the nonce exists only inside the source that emission
generated.

## Reconstruction coverage

`reconstruction-coverage` composes the fit record, the program, the rebuild
report and the editability verdict into one account, and returns a label from a
closed set: `parametric-full`, `parametric-partial`, `reconstruction-refused`.

What the account asserts:

- `delivered_area_fraction` — the program's own coverage, **minus every
  archetype the build did not deliver**. It is the fraction of the scan's
  surface area now standing as editable Fusion features, and it is never rounded
  up. A fillet that was planned and then skipped subtracts its region even
  though the build succeeded; a refused rebuild delivers zero however much was
  planned.
- `unreconstructed[]` — every region the program declined, with its gate, plus
  every archetype the build did not deliver, with its reason.
- `stages[]` — the four stages separately, so a reader can see *where* area was
  lost rather than only that it was.

What the account does **not** assert, stated in the account itself:

- That what was rebuilt is dimensionally correct. That is the deviation
  verdict's question and it is a separate instrument.
- That the recovered feature tree is the original designer's. It is *a*
  parameterization consistent with the measured surface, never *the* original.
- That any parameter drives a rebuild unless the editability proof exercised it.
  Coverage and editability are different axes and are carried side by side
  rather than folded into one number: a fully covered model whose parameters are
  all inert is not a better outcome than a partial model that edits.
- Anything at all when an input is absent. A missing fit record is reported
  missing, never read as full coverage; a missing rebuild report means nothing
  was built, and a plan is not a model.

The absent-input case is the one worth watching, because it is where an
optimistic reading is most tempting. Each absent stage carries an
`unavailable_reason` naming what is not known, and the label falls to
`reconstruction-refused` when no build ran.

## What the reconstruction pipeline has not established against live Fusion

Everything above is exercised offline against the stubbed-`adsk` harness, which
proves the decision surface and proves nothing whatever about Fusion's own
behaviour. `docs/live-fusion-acceptance.md` §13 is the procedure that would
settle these; until a run is recorded against a named Fusion version each is an
assumption and is labelled one here.

This list **extends** the emission and editability sections above rather than
restating them: those already cover the sketch solver, offset construction
planes, parameter binding, feature-owned face collections, reverse-order
rollback, `entityToken` stability and the physical-properties noise floor. What
this unit adds:

| Not established offline | Established by |
| --- | --- |
| That `HoleFeatures.createSimpleInput` with `setPositionBySketchPoint` and `setDistanceExtent` places a hole where the fitted bore is | a live run of a program carrying a hole archetype |
| That a hole's two origin-anchored position dimensions bind to user parameters and move the hole when edited | the editability loop over `recon_hole_*_x` / `_y`, whose declared observable is the centroid |
| That `FilletFeatures.addConstantRadiusEdgeSet` accepts an edge set gathered from two features' shared faces | a live run of a program carrying a fillet archetype |
| That `BRepEdge.tempId` identifies the same edge across two features within one transaction | the same run; a mismatch surfaces as `fillets_skipped` with `entity-resolution-ambiguous`, which is the honest failure mode rather than a wrong fillet |
| That `Feature.faces` is populated on a hole and on a revolve, not only on an extrude | the same run; an absent collection records `fillet-capability` and skips that fillet |
| That a real closed scan yields `orientation.material_side` values agreeing with the part's actual bores | a live run over a marketplace STL, comparing assigned holes against the model |
| That the coverage fraction on a real part is high enough to be useful | the same run. The number is the point of recording it, and a low one is a result rather than a failure |

Two further boundaries — offline facts rather than open questions — are recorded
here because they bound what a live run could show:

- **A fillet is skipped, not refused.** A run reporting `ok: true` with entries
  in `fillets_skipped` built less than its program declared. The coverage
  account subtracts them; a reader looking only at `ok` would not see it.
- **No emitted transaction starts a process.** Inside Fusion `sys.executable` is
  the Fusion binary. The hole and fillet paths add no exception, and the
  string-search suite over generated source covers them with everything else.

## Handoff

- Fusion document version/checkpoint recorded.
- Manifest hash recorded.
- Inventory and verification reports retained.
- Screenshots retained.
- Exports and hashes retained.
- Slicer profile and estimate retained when available.
- All provisional dimensions and unsupported checks listed.
