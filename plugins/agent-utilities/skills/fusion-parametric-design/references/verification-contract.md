# Verification contract

Scope: this contract governs the skill's automation and release lanes — the
generated verification transaction, the export binding, variants, and the
release gates. During ordinary modeling, inspection is native and
direct: Measure, Interference, Section Analysis, Properties, and feature
health, read straight from Fusion at sensible boundaries. The evidence
machinery below is applied when a release, handoff, repeatable generator
requires it, and it is never a license to build agent-authored
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

### Enclosure feature results are not release verification

When the enclosure feature toolkit creates or edits a managed feature group,
the `FeatureResult` it returns — created-feature health, `BRepBody.isSolid` on
claimed outputs, expected local body count — is a **create-time result check**,
not release verification. It answers "did this operation build what it just
declared", not "is the document ready to hand off". Release still requires
this contract's own gates: Compute All with no unhealthy timeline, the
verification transaction, export binding, and every applicable physical item.
Managed coupons remain **physical evidence** under this contract: a coupon's
`generated` status is a print-job declaration, its `accepted` status exists
only after a user records a measured result, and no geometry result ever
converts a `not run` physical item to `pass`.

Ingress claims (water/dust) never upgrade from geometry alone. A seal channel,
splash-overlap seam, or labyrinth the toolkit builds is light-path or drainage
geometry; the `water/dust ingress` physical item stays `not run` until a real
ingress test is performed and recorded — exactly as this contract already
requires for every other physical claim.

- Packing occurrences use recorded transforms.
- Every manufactured item has an authoring and packing representation.
- Every applicable connector/cable/tool/service/thermal/RF/motion keep-out exists.
- Minimum-distance checks meet the recorded requirement.
- Forbidden interference checks return zero.
- Intended contacts are documented and excluded from “forbidden” checks.
- Closed, open, and service states are checked. **Manual gate:** nothing in the generated transactions poses the assembly or switches configurations. Drive each state in Fusion yourself and re-run verification per state, declaring the occurrences and timeline features each state suppresses (`verification.allowed_suppressed_paths`, `verification.allow_suppressed_timeline_features`) so the state under test passes while undeclared suppression still fails.

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

## Handoff

- Fusion document version/checkpoint recorded.
- Manifest hash recorded.
- Inventory and verification reports retained.
- Screenshots retained.
- Exports and hashes retained.
- Slicer profile and estimate retained when available.
- All provisional dimensions and unsupported checks listed.
