# Mesh reconstruction

## What conversion does and does not recover

Mesh-to-B-Rep conversion recovers a shape. It recovers no sketches, no constraints, no dimensions, and no feature history. A cylinder comes back as a many-sided prism with no circular edge to select; a fillet comes back as thousands of facets. `ParametricFeatureMeshConvertOperationType` only means the convert operation re-runs when the mesh changes — it does not restore parameters.

A converted body is **faceted**, never parametric, and must never be reported as parametric.

## Capture before anything

Before any edit, record the source in `mesh_sources`:

- `sha256` of the file bytes. A moved or edited file fails closed on the hash; it is never silently re-measured.
- `units` with `unit_source` — `declared`, `file`, or `guess`. An STL carries no unit, so a 1000x scale error validates clean. A `guess` must name the heuristic and the threshold that produced it, and that reason is printed with every capture report.
- `provenance` — `designed_export` or `capture`. **No mesh statistic distinguishes them**: a designed model scores like a scan on every computable measure. It is a declared input, and it governs confidence — fitted values from a capture stay provisional until a coupon proves them.
- `alignment_transform`, the applied coordinate-frame evidence. Record the identity when nothing was moved.
- `brep_source` when a STEP or other B-Rep exists. Prefer it, and record that it does not restore design intent and may not match the mesh people actually printed.

The source mesh body is never modified, converted in place, or overwritten. The capture transaction is read-only: it reports triangle count, `isClosed`, `isOriented`, volume, the oriented minimum bounding box, and the Fusion version, and it creates nothing. Every mesh API it touches is preview; a value it could not read is reported absent, never guessed.

`emit-mesh-capture` re-hashes every declared source before it emits anything, so a file swapped or edited after capture stops the workflow instead of producing a confident transaction carrying a stale digest.

Two things the capture *cannot* do, stated here so nobody assumes otherwise:

- **`mesh_sources` records the file, not the Fusion body.** No manifest field binds a record to a mesh body. The binding is established by hand from the capture report's component paths and body names, and it is what `emit-mesh-convert` and `emit-mesh-deviation` take as their `body_name`/`component_path` spec. That binding is unusable while `duplicate_semantic_paths` is non-empty, so the capture refuses in that case rather than reporting a partial body list as a success.
- **Triangle count and `isClosed` are gate inputs, not optional evidence.** A capture that cannot read them fails closed with `mesh-evidence-unavailable`, because the only other way to fill the classification request would be to assume them. `isOriented`, volume and the bounding box stay optional.

## Choose the path, then record it

Classification happens **before** any geometry operation, and downstream entry points refuse to run without the record. Exactly one path:

| Situation | Path |
| --- | --- |
| Local or cosmetic edit; the object is a fixture to clear rather than a design to change; clearance-only use | `mesh-edit` |
| Watertight, low-facet mechanical part needing a boolean, below a **declared** facet budget | `faceted-brep` |
| Dimensional or structural change; or a boolean on a mesh that is not watertight or is over budget | `parametric-rebuild` |

Facet ceilings are declared per request, never a module constant: the widely-cited 10k/50k numbers are unverified and version-specific, and Fusion's own `errorOrWarningMessage`/`healthState` are the authority at conversion time.

Both mature commercial tools expose three separate commands and make the human choose. What is automated here is the *recording and enforcement* of the choice, not the choice itself.

### What the gate actually enforces

A classification record is `{"path": ..., "rationale": ..., "inputs": {...}}`, where `inputs` carries `edit_kind`, `provenance`, `watertight`, `facet_count`, `brep_source_available`, `source_id`, `source_sha256`, and `facet_budget` exactly when the edit kind is `boolean-mechanical`. Every geometry entry point calls the gate with the operation name, the paths it implements, and the mesh-source record it is about to touch, and the gate refuses when:

| Refusal | Meaning |
| --- | --- |
| `classification-required` | Nothing was classified. An unclassified run does not proceed. |
| `classification-invalid-inputs` | A recorded input is not a value the decision could have been made from. |
| `classification-path-contradicts-inputs` | The recorded inputs decide a different path than the record claims. This is what stops a faceted conversion being recorded as a parametric rebuild. |
| `classification-path-forbids-operation` | A decision exists, but not one this operation implements. Proving *a* choice was made is not proving it permits *this* operation. |
| `classification-source-mismatch` | The classification was decided for a different mesh source. One stale record must not authorize geometry on any mesh in the project. |

The path is **re-derived** from the recorded inputs on every rehydration, so a hand-authored record is safe: it is checked against the same decision function that produced it.

## Path notes

- **`mesh-edit`** — keep the body a mesh, use Fusion's mesh tools, and never claim a parametric result. Clearance and interference claims still require a native positive-volume B-Rep envelope, never a mesh-only occurrence.
- **`faceted-brep`** — convert only after the named refusal ladder, and label the result faceted. "Converted successfully into 9,000 unselectable facets" is a poor outcome, not a success.
- **`parametric-rebuild`** — rebuild only the geometry the edit requires, from datums and sections extracted from the immutable source. This is not a whole-part auto-converter. Near-coaxial, near-perpendicular, near-symmetric, and near-nominal values are surfaced as proposals carrying their deviation, never snapped silently.

## The faceted refusal ladder

`emit-mesh-convert` refuses unless the recorded classification chose `faceted-brep` for this exact source, then the emitted transaction runs the rungs only live Fusion can answer. Each refusal names its reason **and its alternative**, and a refusal after the convert call rolls the created bodies back:

| Rung | Refusal | Why |
| --- | --- | --- |
| 1 | `source-not-found` | The declared component path or body name does not resolve. Re-read the capture report and bind again. |
| 2 | `mesh-convert-capability` | `Features.meshConvertFeatures`, `ObjectCollection`, or `MeshConvertMethodTypes` is absent. Every mesh feature class is preview; a missing name is an adapter/API mismatch, not proof Fusion cannot convert. |
| 3 | `not-convertible-source` | The named body is not a mesh body. |
| 4 | `mesh-evidence-unavailable` | The preview properties the ladder itself reads are unreadable, so the ladder cannot run and nothing is converted. |
| 5 | `not-watertight` | Conversion yields a surface body, not a solid. Repair the mesh or rebuild. |
| 6 | `non-positive-volume` | The signed volume is not positive, so the normals are inverted. |
| 7 | `face-groups-unavailable` | Fusion's own face grouping is what editability is measured against. |
| 8 | `fusion-refused-conversion` | Fusion's own `errorOrWarningMessage`/`healthState` complained, quoted verbatim. **No facet ceiling is hardcoded anywhere**: the widely-cited 10k/50k numbers are unverified and version-specific. |
| 9 | `conversion-produced-nothing` | No B-Rep body appeared. `add()` returning null is documented for non-parametric operations, but a missing body is a real failure. |
| 10 | `not-editable` | Faces per face group exceeded the **declared** `max_faces_per_face_group`, which must carry a `rationale` — a ceiling nobody justified can be set high enough that the rung never fires. "Converted successfully into 9,000 unselectable facets" is a poor outcome, not a success. |
| 11 | `source-mesh-consumed` | The immutable source must survive every operation. An unreadable `isValid` fails here too: absent is not proof the source survived. |
| — | `cleanup-incomplete` | A rolled-back refusal re-enumerates the component and reports any body that survived, rather than inferring emptiness from the absence of a `deleteMe` exception. |

A success is labeled `"label": "faceted", "parametric": false`, and the report carries the note that the body has no sketches, constraints, dimensions, or feature history.

**That label has no downstream consumer.** The manifest has no field marking a print part faceted, and `emit-export` never reads this report, so the exported body arrives labelled as nothing. Carry the label into `DESIGN-STATE.md` and the handoff by hand. (`is_parametric` in the verification report is the design-level fact and is true of a faceted body, so it does not stand in for this.)

## The deviation verdict is asymmetric, and reports two questions

`emit-mesh-deviation` grades a reconstruction against the immutable source and reports **two directions that answer different questions**. They are never collapsed into one "deviation: X mm" that reads as a fitness certificate:

- **`reconstruction_to_source`** — how far the reconstructed surface sits from the nearest scanned surface. This answers whether the rebuild stayed on the scan. It says **nothing** about scanned detail the rebuild never modelled.
- **`source_to_reconstruction`** — how far each scanned point sits from the reconstruction, and whether it lies inside the reconstructed solid (a native `BRepBody.pointContainment` query when the reconstruction is a B-Rep). This answers whether the rebuild captured what was scanned. It says **nothing** about material the rebuild added where the scan has no points.

The verdict is asymmetric: rebuilt material **outside** the source is *invented geometry* — a hard failure naming coordinates — while scanned detail absent from the rebuild is *omitted detail* — advisory, because a rebuild models only the geometry the edit requires. This is also why the wall beneath a dropped boss does not false-positive: it is omitted in one direction and dead-on in the other.

Thresholds (`invented_material`, `omitted_detail`, `percentile_sample_limit`) are **declared per reconstruction with a rationale** and recorded with the verdict, never module constants. Percentiles may be computed from a strided sample; every comparison against a threshold scans the exact per-node values.

### The sign convention is measured, not assumed

Nothing documents which sign `compareWith` uses for "outside", and assuming it is how an inverted convention turns invented material into a pass. The run reads the convention off the native containment query instead: every source node whose distance clears the invented-material threshold has an independent inside/outside answer from `BRepBody.pointContainment`, and the observed pairing decides whether positive or negative means outside. The observed convention and the sample tally are recorded in the verdict.

If no reconstructed node lies further than the threshold from the source **in either direction**, no sign reading could change the answer, so the verdict passes without establishing a convention and says so.

Three fail-closed cases produce no verdict rather than a number:

- **`deviation-capability`** — `PolygonMesh.compareWith` is a **preview** API (July 2026) and is the *only* API-level deviation mechanism Fusion has. `BRepBody.pointContainment` and both `PointContainment` members are equally required: containment is the only evidence here that does not rest on the sign, and it is what establishes the sign. A missing enum must never read as "nothing was outside", so each is a hard capability, never a conditional. The refusal names the API and the connected Fusion version.
- **`deviation-unsigned-comparison`** — the connected Fusion returned only unsigned magnitudes, which cannot separate invented material from omitted detail.
- **`sign-convention-unestablished`** — material lies beyond the threshold, but the containment probe and the returned signs did not agree on which sign means outside.

In all three the invented-material verdict is `not-established`, never a pass, and it carries no `count` or `max_mm` that could be misread as a zero.

## What is not built here

- **Fusion's Mesh Section Sketch and Fit Curves to Mesh Section are UI-only.** There is no `MeshSectionSketch` class, nothing on `Sketch` that creates one, and no `MeshPlaneCutFeature`. No emitted script calls them, and none ever should. The sectioning and fitting in `mesh_fitting.py` are our own arithmetic over `PolygonMesh` data for exactly this reason.
- **Coordinate-frame derivation from the fitted primitives is not implemented.** `mesh_fitting.py` fits planes, cylinders, cones and spheres and proposes design intent, but it does not derive a coordinate frame from those fits — the second half of R8 is absent.
- **Sketch API emission is not implemented.** No constrained sketch or dimension is emitted from a fit today. The fits and proposals are host-side data; turning them into Fusion sketch geometry is still to be built.
- **Whole-part auto-conversion, organic/freeform surface recovery, and automatic design-intent assertion are deliberately out of scope.** See `references/unsupported.md`.

## Honesty rules

- The handoff distinguishes mesh cleanup, faceted conversion, and true parametric reconstruction. The second is never reported as the third.
- A fit coupon is required before any claim of physical mating.
- A missing preview API fails closed with a clear message rather than degrading silently.
- Clearance and interference claims still require a native positive-volume B-Rep envelope, never a mesh-only occurrence.
