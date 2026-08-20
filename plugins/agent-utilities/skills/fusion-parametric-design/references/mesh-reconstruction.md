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

- **`source_to_reconstruction`** — how far each scanned vertex sits from the reconstruction's boundary, and whether it is inside or outside the reconstructed solid. This answers whether the rebuild captured what was scanned, and whether it put material where the scan says the part ends. It says **nothing** about rebuilt surface standing where the scan has no points at all. This is the signed direction, and the verdict rests on it.
- **`reconstruction_to_source`** — how far the reconstructed surface sits from the nearest scanned surface. This answers whether the rebuild stayed on the scan. It is **unsigned**, so it carries `attribution: "not-established"`: a rebuilt sample far from every scanned triangle may be invented material or a region the rebuild deliberately simplified, and this direction does not decide which.

The verdict is asymmetric: rebuilt material **outside** the source is *invented geometry* — a hard failure naming coordinates — while scanned detail absent from the rebuild is *omitted detail* — advisory, because a rebuild models only the geometry the edit requires. This is also why the wall beneath a dropped boss does not false-positive: it is omitted in one direction and dead-on in the other.

Thresholds (`invented_material`, `omitted_detail`, `percentile_sample_limit`) are **declared per reconstruction with a rationale** and recorded with the verdict, never module constants. Percentiles may be computed from a strided sample; every comparison against a threshold scans the exact per-vertex values.

### How the two directions are measured

Fusion answers no distance question this verdict can use — `measureMinimumDistance` returns zero for interior points against a body, measures the *untrimmed* surface against a face, and refuses a mesh outright; `PolygonMesh.compareWith` is preview and is not defined for a B-Rep's `TriangleMesh` at all. `references/unsupported.md` records each of those with the numbers that show it.

So the reconstruction's boundary comes from `MeshManager.createMeshCalculator()`, and every distance is a point-to-triangle computation inside the transaction, stdlib only:

- **`surfaceTolerance`** is one tenth of the declared `invented_material` threshold — the tessellation must not contribute a tenth of the deviation it is used to measure. It is recorded, and so is the fact that this Fusion refuses to report the tolerance it achieved.
- **`maxSideLength`** is the **source mesh's own median triangle edge**, so the rebuilt surface is sampled at the scan's resolution and the sampling cannot step over a feature the scan was able to express. Direction 2's samples are that tessellation's own nodes.
- Direction 1 uses **every** scanned vertex, not a sample.

`PolygonMesh.compareWith` is kept as corroboration only. Where it exists and runs, its maximum is recorded beside the native one and a disagreement is flagged; the native measurement stands.

**The numerics run inside the transaction, not host-side.** The sides can only be read where the B-Rep is, so the transaction has to run in Fusion anyway; and it reads the source's vertices and triangles from the same `PolygonMesh` the hash-bound dump is written from, in one pass, with no transport in between. A dump is how those numbers reach a host process — when there is no host process the hash defends a journey nothing takes. The distance code is stdlib only: numpy inside Fusion is a probed capability (`emit-capability-probe` records it per Fusion version), and a verdict must not rest on a dependency that can be absent. It costs about 0.07 ms per query, flat from 800 to 12,800 triangles.

### The containment convention is verified, not assumed

The whole asymmetry turns on one mapping: **a scanned vertex inside the reconstruction means the rebuild put solid where the scan says the part ends — invented material; a scanned vertex outside means the scan carries something the rebuild does not reach — omitted detail. `PointOnPointContainment` is neither, and measures zero.** An inverted reading would report invented material as omitted detail and pass.

So the transaction proves it on the actual body before reading a side, against two answers known by construction:

1. a point pushed a full bounding-box diagonal beyond the body's own bounding box must read outside, whatever the enum is named;
2. a point stepped `invented_material` along a tessellation facet's normal and a point stepped the same distance against it must straddle that facet — one inside, one outside — and **both must measure that distance from the boundary**, by the same point-to-triangle code the verdict uses. The facet is the largest one whose inradius clears twice the step, so no neighbouring facet can be the nearer boundary.

The probe, its epsilon, its tolerance and its measured numbers are recorded under `containment_convention`, with `sign_convention_verified`. When it does not reproduce, the run fails closed.

These fail-closed cases stop before anything is measured and emit **no `verdict` key at all** — an absent verdict is the one thing that cannot be misread as a zero:

- **`body-not-found`** — a declared component path or body name does not resolve.
- **`deviation-frames-differ`** — one of the two bindings resolves through a non-identity occurrence or body transform. Node coordinates, the reconstruction's tessellation and `pointContainment` are each read in their own body's local frame and nothing here composes a transform, so two identical parts in different assembly positions would compare as a perfect match. The matrices are recorded and the run refuses.
- **`deviation-capability`** — `BRepBody.pointContainment`, all three `PointContainment` members, `BRepBody.meshManager` and `MeshManager.createMeshCalculator` are each hard capabilities. A missing enum must never read as "nothing was outside", so each is checked by name and never conditionally. The refusal names the API and the connected Fusion version.
- **`tessellation-failed`** — the reconstruction's boundary could not be produced, so there is nothing to measure against and nothing here is a zero.
- **`deviation-comparison-empty`** — the source carries no vertices, no triangles, or no measurable edge.
- **`containment-query-failed`** — `pointContainment` raised on a point this run had to classify, or answered a scanned vertex with a value outside the three-member `PointContainment` vocabulary. Such a vertex carries no evidence about invented or omitted material, and a verdict that counted it as nothing would be a pass over material nobody classified.

Two cases do emit a verdict, because they got far enough to measure and then found a premise unproven. A handler must read the `verdict` key on these rather than assume it is absent:

- **`omitted-detail-unclassified`** — a reconstruction sample past the *omitted-detail* threshold could not be classified against the source solid. The two thresholds are declared independently and either may be the smaller, so such a sample can fall outside the invented-material classification entirely; it carries its own token because the invented verdict beside it may be perfectly established, and a handler must not be told the wrong one failed. That is also why the verdict is emitted: the invented-material half is a measured result and stands, while the omitted half reads `not-established`. Losing the whole verdict to report half of it would throw away the half that was proven.
- **`sign-convention-unestablished`** — the containment probe did not reproduce its known answers on this body. Both halves of the verdict are reported `not-established`: invented material carries no `count` or `max_mm`, and omitted detail is `not-established` too, because it is counted from the vertices that read OUTSIDE and which enum means outside is exactly what was not established.

And one more is a refusal for a different reason again. **`invented-material-unclassified`** — the signed direction reads scanned *vertices*, and a scan carries only the ones it captured, so material invented *between* two of them leaves each one on the reconstruction's boundary and every signed depth at zero. The reverse direction is measured over the reconstruction's own tessellation and does see it. That direction is unsigned — it cannot tell invented material from deliberate simplification, so it never reports a failure — but when it puts samples past the `invented_material` threshold while no scanned vertex is inside, the absence of invented material is not established, and the verdict says so with `unclassified_reconstruction_samples` rather than passing.

**Omission accounts for some of those samples, and each sample is classified to find out which.** When the rebuild leaves out an outward feature the scan carries, the surface it leaves in that feature's place is a rebuilt surface far from any scanned triangle — on a manifold scan there are no base-face triangles under a fused boss for it to be near — so the reverse direction reads exactly what invented material reads. The signed direction already saw that omission, as scanned vertices *outside* the reconstruction. A comparison of the two *maxima* cannot separate them — a maximum carries no spatial attribution, so a 3 mm omission would account for a 2 mm invention beside it — so every sample past the threshold is classified individually against the source solid by **ray parity** over the source's own triangles: a rebuilt surface standing where an omitted feature used to be lies *inside* the scanned solid, and invented material lies outside it. All inside means the omission accounts for all of them and the run passes with its omitted-detail advisory — and the samples that *raise* that advisory are re-counted against the separately declared `omitted_detail` threshold, since the classification above answers the invented-material question at the invented-material threshold; any one outside, or any the parity cannot answer (an open surface has no inside), and the run fails closed. The counts are recorded as `unclassified_inside_source`, `unclassified_outside_source` and `unclassified_unresolved`.

## What the reconstruction pipeline builds

Inside Fusion, first: `emit-mesh-face-groups` runs `MeshGenerateFaceGroups` on the mesh body with `AccurateGenerateFaceGroupsType` set explicitly, and `emit-mesh-extract` then writes the hash-bound dump carrying that grouping, one id per triangle. Host-side, with no Fusion running: `fit-regions` fits an analytic primitive to each of those groups behind the disproof gates; `plan-reconstruction` derives a datum frame from the accepted fits and assigns them to archetypes; `reconstruction-coverage` composes the final account. Back inside Fusion: `emit-mesh-rebuild` builds the timeline, `emit-mesh-editability` proves each parameter drives it, and `emit-mesh-deviation` grades the result against the immutable source.

**The regions come from Fusion; the judgement does not.** Both paths were run end to end over the same dumps of the same 11 production STLs, at the same declared thresholds:

| | RANSAC/ICM (deleted) | face groups, vertices only | face groups, normals as fit data |
| --- | --- | --- | --- |
| regions offered to the fitters, 11 parts | 47 | 1,069 (of 1,908 groups; the rest carry fewer than four points, which is below what a least-squares fit needs) | 1,069 |
| regions accepted through every gate | 38 | 268 | **619** |
| area-weighted coverage, 11 parts | **41.7%** | **62.5%** | **70.5%** |
| cylinders accepted, 11 parts | 0 | 4 | **251** |
| full-turn bores accepted (of 85 present) | 0 | 0 | **76** |
| fillet candidates | 0 | 1 | **114** |
| POD-A2-BASE | 8 regions, 27.4% | 105 regions, 36.6% | 105 regions, 50.8% |
| POD-B-BASE | 1 region, 2.3% | 188 regions, 69.1% | 188 regions, 72.1% |

All 24 thresholds the middle column declared carry the same values in the right
one; the seven the right column adds are new evidence, not loosened old evidence,
and each is caller-declared with its rationale.

The table above is the **pre-prism-filter** measurement. After
`cylinder-normals-discrete`, its right column's 619 accepted regions are 598 and
its 251 cylinders are 230, and 66 planned holes are 45. The difference is
21 hexagonal M3 nut pockets — 5.700 mm across flats, 12 facets each, spread over
five of the eleven parts — that the vertices read as 6.58 mm round bores because
a hexagon's corners lie exactly on its circumscribed circle. They are refused
`cylinder-normals-discrete` below, and nothing else in the table moves: 1,069
regions offered, 114 fillet candidates, 3 fillets and 10 extrudes are unchanged
and no part changes the gate it stops at. Every other number quoted from that
table in this document is its pre-filter value unless it says otherwise.

So the segmentation layer is deleted and the grouping is the input. What survives untouched is the part Fusion has no opinion about: support floors, Moran's I on the mesh graph, the spatially blocked held-out refit, the nested-kind parsimony F test, and the parameter-uncertainty gate all still run on every group, and a group that fails one is recorded with the gate that killed it. *Run* is not assumed: both structure gates have a power floor — against residuals an order of magnitude inside the measurement noise they have nothing to test, and they say so instead of passing — so `disproof.gates` counts, per gate, how many accepted fits it actually judged and why it skipped the rest, derived from each region's own `checked` list rather than asserted beside it. On the honeycomb organiser that floor skipped Moran and the held-out refit on all 39 accepted planes. That gap between 1,069 fitted and 268 accepted -- the table's *left* column, before the normals became fit data; 619 in the right column and 598 after the prism filter -- is the gates doing their job, not a loss: `fit_primitive` alone accepts nearly everything, and the disproof gates are the difference between a fit and a *justified* fit. A dump that carries no grouping is refused `face-groups-absent` rather than segmented by a fallback nobody measured.

**Two things the vertices cannot decide, and what decides them.** On a bore or a round tessellated with two vertex rings and no intermediate samples, every vertex lies exactly on a sphere as well as on the cylinder — the shield's r=2.0 corner rounds fit a sphere of radius 2.15407 at rms 0.0 — so ranking by residual hands 367 of 367 such groups to the sphere, and all 367 are cylinders. The facet normals settle it: every one is within 5 degrees of perpendicular to the cylinder axis, which no sphere's are, and the angle is caller-declared as `cylinder_normal_perpendicular_deg`. Re-measured against the live grouping of all 11 parts: 367 groups ranked a sphere first, a cylinder was accepted on every one of them, and the tie-break moved all 367 — the worst facet normal in the set sits 0.0 degrees off perpendicular, and radii collapse from the sqrt(2)-inflated sphere values to clean nominals (4.2426 to 3.0, 10.084 to 10.0, 6.4288 to 6.2). Most of those cylinders are then still refused for support span: two rings of vertices carry the *radius* but not enough axial evidence to determine an axis. The tie-break fixes the kind; it does not manufacture evidence, and it was never meant to. Separately, the grouping delivers edge rounds as **partial-arc cylinders** rather than tori, so a fillet candidate is now a torus *or* a cylinder whose measured `angular_span_deg` is inside the declared `max_fillet_arc_deg` — a bore closes on itself and a round never does. The evidence discipline is unchanged: either way a fillet still needs two accepted neighbours that are themselves features.

**The normals are fit data, not only a tie-break.** Every facet normal on a
cylinder is perpendicular to its axis by construction, so a bore tessellated as
two vertex rings — which determines a radius and no axis — has the axis sitting
in the facets between the rings. `normal_constrained_axis` accumulates the
area-weighted second moment `A = sum w n n^T` (weights are facet areas over their
own mean, so the trace is an effective facet count), takes the axis from its
smallest eigenvector, and reports the closed-form Gauss-Newton sigma
`sigma_theta * sqrt(1/l1 + 1/l2)` in the tangent plane, where `sigma_theta^2 =
l0 / (W - 2)` floored by a caller-declared measurement precision. The
determinacy of the axis is the eigengap `l1 / trace`: one half for a full ring of
facets, zero for a sliver. With the direction pinned, radius and axis point stay
the module's existing exact 2-D circle fit. The same accumulation, read as the
whole 6×6 `n·(c̄ + c×x) = 0` system, is `route_kinematic_surface` — Pottmann and
Randrup's kinematic router, which answers extrusion, revolution and helix in one
eigenproblem and refuses a plane or a cylinder outright, because their invariant
motions form a family and no eigenvector describes a family.

`min_axial_span_ratio` is untouched and still applied to every fit whose axis
came from the vertices. A fit whose axis came from the normals records the floor
as **measured and not applied**, with the eigengap that replaced it: the floor
asks how long a cylinder must be *before its axis is determined*, and that is a
question about a determination this fit did not make.

**Two measurement regimes, decided from evidence and never silently.** An STL
written by a solid modeller has vertices on the analytic surface to float
precision and a bimodal dihedral distribution — facet pairs from one planar face
meet at exactly zero. A scan has neither. `record.regime` carries the decision,
both readings behind it, and any caller override (`regime: auto|tessellation|scan`).
Three consequences follow. `noise-model-inconsistent` no longer fires on a
noise-free mesh, where the two estimators are *meant* to disagree because one
absorbs curvature and the other measures the facet turn angle: it fired on all 11
production parts and now fires on none.

**The regime decides which estimator `sigma` comes from, and it is detected
before the selection rather than after it.** Estimator B declares its own
domain — "real creases are a small minority of interior edges on a mechanical
part, so the median sees only the noise" — and on a honeycomb that is false:
61.5% of the vendor honeycomb organiser's 834 interior edges are genuine 60°
cell walls, the median interior dihedral is 59.99993°, and estimator B returned
13.108 mm of "noise" for a mesh whose quadric estimator returned exactly 0.0 and
whose regime detector said *tessellation*. Ten sigma is the recoverable feature
size, so the pipeline refused a 169 mm part `feature-scale-below-noise` claiming
131 mm was unrecoverable, and its STL is byte-equivalent to the vendor's own
STEP to 3.2e-08 of area. `sigma` was `max(quadric, dihedral)` computed **before**
the regime was known, so the check that already suppressed the *flag* never saw
the *value*. In the `tessellation` regime `sigma` is now the quadric estimator
alone — the only one estimating noise there — and the dihedral reading becomes
`surface_scale`, which is where a facet turn angle belongs and which is what it
already reached through `sigma` in both regimes. Every power floor is therefore
exactly where it was: re-measured over the eleven production dumps, all 1,069
regions, 619 acceptances, 114 fillet candidates and every coverage figure are
unchanged. In the `scan` regime the conservative maximum stands. Both estimators
are always recorded, with `noise.sigma_estimator` and
`noise.sigma_estimator_reason` saying which was chosen and why. No declared
threshold moved: this is a selection, not a tolerance.

And `sigma` is floored at the precision
the coordinates are *stored* at (`vertex_precision_rel`; a binary STL holds
float32). Without that floor the residual-structure gates spend their power
testing the file format — quantization is deterministic and therefore
systematically signed, and it refused 56 of the 85 full-turn bores for "azimuthal
structure" that was the quantization of a perfectly round hole.

**A prism of planar walls fits the cylinder its own corners lie on.** A regular
polygon's corners lie *exactly* on its circumscribed circle, so a hexagonal
pocket delivered as one face group fits a cylinder of that circumradius at
float-noise residual — and a sphere through the same corners just as exactly.
Every gate that reads vertices passes it, because to the vertices it really is a
cylinder. Measured: six 26 mm across-corners hex pockets on the honeycomb
organiser came back as six 26 mm round bores, and 21 M3 nut pockets across five
of the eleven production parts (5.700 mm across flats, 12 facets each) came back
as 6.58 mm round holes. The facet normals refute all of them: they sit within
`cylinder_normal_perpendicular_deg` of perpendicular to one axis — which is what
says the facets are arranged *around* an axis at all, and what excludes a real
sphere — but occupy only six discrete directions where a cylinder's sweep. The
refusal is `cylinder-normals-discrete`, it is a verdict about the *group* so the
sphere falls with the cylinder, and `support.normal_direction_spread` records the
facet count, the distinct-direction count, the arc they cover and the
directions-per-turn it was judged on. The threshold is the caller's
`min_cylinder_normal_directions_per_turn`: a genuine tessellated circle carries
one normal direction per facet, and at eight per turn a facet already spans 45°,
coarser than any exporter's chord tolerance. Measured over the eleven parts the
distribution is bimodal with nothing in between — the 230 genuine cylinders carry
29.6 to 108 directions per turn at radii from 1.15 mm to 10 mm, and the 21 hex
pockets carry 7.2. Either side of the declared 8.0 the nearest measurements are
13% away — a 7-sided prism carries 8.17 and passes, an 8-sided one 9.14 — and
that band is asserted in the tests rather than left to be discovered by a part.

Directions are merged at the run's own floor on a facet normal's direction, by
**complete** linkage: a direction joins the open cluster only while it stays
within the floor of that cluster's *first* member, so no cluster is ever wider
than the floor it was merged at. Single linkage chains instead — in the scan
regime the floor is the mesh's own normal noise, routinely wider than the azimuth
spacing of a fine tessellation, and a genuine 360-facet cylinder collapsed into
one direction, zero per turn, and was refused as a prism.

**Group boundaries are free evidence.** The loop between a bore and the face it
breaks through is a circle, and it is shared with the neighbouring group rather
than being one more reading of the bore's own wall. `support.boundary_circle`
fits that loop in its *own* best-fit plane and reports the radius and the angle to
the fitted axis, so the two readings are independent. Agreement strengthens the
fit; disagreement beyond the declared `boundary_circle_sigmas` is the named flag
`boundary-circle-disagrees`, never a silent preference for either number, and a
loop that is not a circle at all yields no corroboration rather than a
disagreement. Measured: 105 of 251 accepted turned surfaces have a circular
boundary loop, and 103 of those agree.

**A fillet is a chain, not a fragment.** Fusion's grouping can cut one edge round
into a run of partial-arc cylinder groups, and marking them one at a time gives
one "fillet" per tessellation artefact. Blends are assembled into chains first —
adjacent, radii agreeing within the declared `max_fillet_radius_rel_spread`, and
lying between the same two primaries — and the chain is the candidate, carrying a
`chain_id` and the area-weighted radius. The evidence discipline is applied to
the chain and is otherwise unchanged: exactly two accepted non-blend neighbours,
or it is an ordinary run of fits and says so. On these 11 parts the accurate
grouping already delivers one group per round, so every chain has one member; the
assembly matters for a grouping that fragments.

The archetype vocabulary is closed and all four kinds now emit:

| Archetype | Assigned when | Emitted as |
| --- | --- | --- |
| `sketch-extrude` | two parallel cap planes, with side surfaces perpendicular to them | a sketch on an origin plane or a parameter-driven offset from one, then an extrude |
| `revolve` | at least two accepted fits coaxial with the primary axis, one of which is a turned surface that is **not** a bore, *and* the group's own facet normals shown invariant under a single rotation about that axis | a half-profile sketch containing the axis, then a revolve |
| `hole` | an accepted cylinder whose `orientation.material_side` is `"inside"`, lying wholly within one extruded body, its axis along that body's extrusion direction | a placement point dimensioned to the sketch origin, then a hole feature with parametric diameter and depth |
| `fillet` | an accepted blend — a torus, or a cylinder sweeping less arc than the declared `max_fillet_arc_deg` — adjacent to exactly two non-blend primaries, both of which this program rebuilt | a constant-radius fillet on the edge those two features share |

### What makes a bore a bore

`hole` sat in the vocabulary unassignable for two units, because telling a bore from a boss means knowing which side of the surface the material is on, and shape alone never says. `fit-regions` measures it: the signed volume of a closed, consistently wound mesh gives its winding an outward direction, and comparing that against a region's own surface normals yields `orientation.material_side` — `"inside"` for a bore, `"outside"` for a boss.

**It is `null` on an open or inconsistently wound mesh, and on every plane** (a plane encloses no volume, so it has an outward direction but no inside). When it is `null` on a cylinder the region is left unreconstructed carrying `material-side-unavailable` and the fitting stage's own reason for the absence. It is never guessed. The practical consequence belongs on a capture checklist rather than buried here: **a scan that is not watertight can never produce a hole.**

The same fail-closed rule runs the other way, which is the half that is easy to get wrong. A cylinder of *unknown* side is treated exactly as it was before this evidence existed — it can still join a revolve or an extrude group — because "unknown" is not "inward", and changing behaviour on absent evidence is the same defect wearing the opposite sign.

### Partial reconstruction is a first-class outcome

`reconstruction-coverage` composes the four stages that each know a different part of the answer, and returns one of a closed label set:

- **`parametric-full`** — every region carrying an accepted fit was planned and built.
- **`parametric-partial`** — some was rebuilt and some was not. **This is a success.** It has its own name so it can never be reported as a reconstruction with a footnote: the unreconstructed regions are listed with the gate that stopped each one, and the source mesh stays in the document as reference geometry over the rebuild.
- **`reconstruction-refused`** — the rebuild refused and rolled back, or was never run. Delivered area is zero however much was planned.

The arithmetic runs one direction only: each stage may lose area relative to the one before it and can never gain any. A fillet that was planned and then skipped at build time subtracts its region *even though the build succeeded* — counting a planned-but-undelivered archetype as reconstructed would be exactly the over-claim this pipeline exists to prevent.

### A revolve is earned before precedence is consulted

Precedence decides between two archetypes the evidence *both* supports. It is not a licence to claim one the evidence does not support at all, and that distinction is where this stage went wrong for two units: any plane perpendicular to the primary axis counted as a surface of revolution about it. The first live acceptance run planned an 80 × 50 × 10 rectangular plate as a 360-degree revolve of radius 10 — 77% of its area — which then died at emission with `entity-resolution-ambiguous`; on the eleven-part benchmark two rectangular lids planned as revolves, and since a revolve's faces cannot be partitioned into named sets, all 61 remaining fillet candidates gated `fillet-neighbour-shared` inside them.

A perpendicular cap is *consistent with* a revolve. It is not evidence for one, and no amount of normal data can make it so: a plane's normals are ±z on an annulus and on a rectangular plate alike. Two measurements now stand between a coaxial group and a `revolve`, and both read evidence the record already carries:

1. **A cap's footprint, not its normal.** A disc or annulus swept about the axis is centred on the axis, so its axis-aligned bounding box is centred on it. Measured across the eleven benchmark parts, every large coaxial plane's box centre sat 23 to 160 mm off the candidate axis — the caps were plates perpendicular to it, and not one part was turned. The tolerance is the caller's already-declared `offset_tolerance`, which is the same question it was declared for.
2. **The group's own invariant motion.** Pottmann and Randrup's kinematic router answers extrusion, revolution and helix from one 6×6 eigenproblem over facet normals; `route_kinematic_surface` runs it over one region's facets at fitting time. The planner has no triangles, so every region now carries the router's *sufficient statistic* for its own facets: `sum over facets of area · b bᵀ` with `b = [x × n, n]`, twenty-one numbers, additive across regions and re-centrable by a congruence — exactly so in the algebra, and to relative rounding in floats: summing the blocks and routing the union of the facets agree to 2.0e-16 relative on the seam test's own group, about one ulp, which is what the seam test asserts rather than an absolute number of decimal places. The planner sums the blocks of a candidate group through `route_kinematic_group` — the entry point that takes summed blocks rather than facets — and requires a `revolution` verdict whose recovered axis is the datum axis. A verdict of translation plans `sketch-extrude` however many caps are perpendicular; `router-ambiguous` — the invariant motions form a family rather than a single one — falls through to the next archetype in the precedence, with the router's record carried on whichever archetype claims the regions. Never a silent choice.

The area weighting is what makes the second test bite: a 4 mm² corner round cannot certify a 2000 mm² plate as a solid of revolution, because the eigengap that says "one motion, not a family" is proportional to how much *surface* pins the axis. Its five gates are declared by the caller under `thresholds.motion_evidence`; undeclared means no revolve is claimed, and the program records that rather than falling back on precedence.

### We recover *a* parameterization, not *the* original

A boss modelled as an extrude and the same boss modelled as a revolve are indistinguishable from the outside. The archetype precedence is therefore a **stated rule**, not a discovery: revolve is tried before sketch-extrude once it is earned, and bores are classified before the extrude group chooses its side surfaces. The result is a feature tree consistent with the measured surface. It is not a claim about what the original designer did, and nothing in the pipeline reports one.

### Every threshold is caller-declared, with its rationale

No stage carries a tuned constant. Each threshold arrives in a spec file as `{"value": ..., "rationale": "..."}`, and validation rejects a bare number — a module constant with extra steps is still a module constant. A rationale that reads like one says what measurement or shop tolerance the number came from and what changes if it moves: *"three sigma: a deviation beyond it is not explained by fit noise"* qualifies; *"seems about right"* does not, and the point of requiring the field is that the difference is visible in review.

## What is not built here

- **Fusion's Mesh Section Sketch and Fit Curves to Mesh Section are UI-only.** There is no `MeshSectionSketch` class, nothing on `Sketch` that creates one, and no `MeshPlaneCutFeature`. No emitted script calls them, and none ever should. The sectioning and fitting in `mesh_fitting.py` are our own arithmetic over `PolygonMesh` data for exactly this reason.
- **Torus fitting does not certify a fillet surface.** A fillet is proposed by adjacency and near-constant width, which is enough to emit a `filletFeatures` radius and not enough to certify a variable-radius or elliptical blend. Those stay unreconstructed.
- **A fillet's edge is found, not measured.** The emitter rounds the edges the two parent features share in the built solid. Where they share none, the fillet is skipped by name — never rounded onto some other edge that happened to be nearby.
- **Oblique sketch planes are refused rather than approximated** (`plane-unmappable`). See `references/unsupported.md`.
- **Whole-part auto-conversion, organic/freeform surface recovery, and automatic design-intent assertion are deliberately out of scope.** See `references/unsupported.md`.

## Honesty rules

- The handoff distinguishes mesh cleanup, faceted conversion, and true parametric reconstruction. The second is never reported as the third.
- A fit coupon is required before any claim of physical mating.
- A missing preview API fails closed with a clear message rather than degrading silently.
- Clearance and interference claims still require a native positive-volume B-Rep envelope, never a mesh-only occurrence.
