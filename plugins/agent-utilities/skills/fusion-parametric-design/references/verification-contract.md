# Verification contract

A release passes only the checks applicable to its intended use. “Generated successfully” is not a verification result.

## Digital model integrity

- Active product is a Fusion Design.
- Design type is parametric.
- `Compute All` runs.
- No timeline error remains; warnings are individually explained.
- Required parameter names and expressions match the manifest.
- Managed components and print parts exist once at the intended paths.
- Each printable part has the intended positive-volume B-rep body count.
- The verification report records each checked part's root-context occurrence transform (`occurrence_transforms`: raw Fusion `transform2.asArray()`, translation components in centimetres — deliberately unconverted, unlike the `*_mm` keys; the export index's per-artifact `transform` uses the same convention).
- When the manifest declares `printable_parts`, its paths exactly match `verification.expected_print_parts`, and a declared `body_name` matches the resolved solid at export (`body-name-mismatch` fails closed).
- No accidental visibility/selection state is being used as a substitute for geometry.
- The report's `ok` is scoped to the gates it names in `checked`, and `checked` is derived from what that run actually performed. A gate the manifest never declared appears in `not_declared`, never in `checked`: "this project declares no clearance checks" is an honest gap and must never read as a passed check. Everything in `unchecked` — printability, structural, thermal, physical — stays `not run` until the sections below are satisfied by external analysis or a printed part. Report it as "passed the gates it declared", not as "verified".

## Fit and packing

- Packing occurrences use recorded transforms.
- Every manufactured item has an authoring and packing representation.
- Every applicable connector/cable/tool/service/thermal/RF/motion keep-out exists.
- Minimum-distance checks meet the recorded requirement.
- Forbidden interference checks return zero.
- Intended contacts are documented and excluded from “forbidden” checks.
- Closed, open, and service states are checked.

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

Core generated scripts do not claim these checks automatically. Use a slicer, custom analyzer, or manual measured review and record the evidence.

## Structural and safety

- Loads and supports are explicitly named.
- Connector insertion/pull loads reach grounded structure.
- Fastener loads reach bosses/walls with adequate edge distance.
- Layer orientation is compatible with likely tension/shear.
- Sharp body-facing or cable-contact edges are removed.
- Material temperature assumptions are compatible with nearby heat sources.
- Electrical insulation, fuse, wire gauge, and voltage separation are reviewed outside CAD by a qualified method.

Do not infer electrical or thermal safety solely from geometric clearance.

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
