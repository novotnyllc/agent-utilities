# Unsupported or partial capabilities and recommended fallbacks

Status date: 2026-08-17. Fusion and its MCP expose dynamic capabilities; verify the connected Fusion release and MCP schema rather than treating this file as a fixed tool catalog.

## Fixed MCP tool names

**Status:** Unsupported assumption.

Autodesk documents dynamic tooling. Discover and bind the current schema at connection time. Keep adapter logic in the agent/skill instead of hard-coding one client's current tool names.

## Separate browser viewer with generated sliders

**Status:** No direct equivalent in the core Fusion MCP.

Use the live Fusion canvas, Parameters dialog, configurations, visibility/opacity, section analysis, and MCP screenshots. Build an optional Fusion palette add-in only when a separate review UI proves necessary.

## Separate development server or launcher

**Status:** Not needed and not included.

Fusion is already the long-lived interactive CAD host. Start Fusion normally, enable its MCP server, connect the agent, and keep one document open through the iteration. An operating-system launcher may automate those startup steps, but it would not reproduce Nurb's independent hot-reload viewer and is outside this package.

## Automatic skill update and synchronization

**Status:** Unsupported automation.

Install and update this skill through the agent harness's plugin or skill manager. The skill does not phone home, overwrite local changes, or silently update itself. Recommended release discipline:

1. obtain a tagged or commit-pinned package;
2. review its change log and diff;
3. run `./scripts/test.sh`;
4. update the plugin or skill through the harness;
5. record the package version or commit in project evidence.

## Batch variant runner

**Status:** Supported and bounded, with two real limits.

`fusion-design plan-variants` runs a declared family: capture the initial state,
then per variant apply, compute, inventory, verify and optionally export, then
restore and verify the restoration by read-back. Evidence is additive and
identity-bound, and the verdict is conjunctive — passing requires every variant.
Two boundaries remain:

1. **Configuration variants depend on a Fusion API that may be absent.** The
   activation transaction probes `Design.configurationTable` and its rows'
   `activate()`, and fails closed with a clear message rather than silently
   applying nothing. It also fails when a configuration table drives managed
   parameters away from their manifest expressions, because verification reports
   that as a parameter mismatch. Declare such a family as parameter-set variants.
2. **The matrix does not invent variants.** Each entry names its own parameters
   or configuration, and a manifest may declare at most 16 variants. A 17th is a
   validation failure (`variants-exceed-maximum`), and the planner refuses the
   same manifest again even when validation was skipped, so a matrix cannot run
   unbounded against a live session.

The runner also refuses to start when the initial expression of a parameter some
variant overrides cannot be read: a run that could not be restored must not
begin. Sync the base parameters first.

## Authoritative printer and material profiles

**Status:** External.

The package does not duplicate `printer.toml` as an incomplete model of a slicer's machine, nozzle, filament, process, and support settings. Keep the authoritative profile in the slicer that will generate the print job. Record the slicer/profile identifiers and versions in the handoff, then attach time, mass, support, and warning results to the exact exported-body hashes.

## Complete FDM printability checker

**Status:** Not supplied by the core package.

Fusion can expose B-Rep geometry, face normals, bounds, and measurements, but robust minimum-wall, bridge, overhang, trapped-support, and machine-specific checks need a custom analyzer or slicer. Recommended path:

1. export the exact print bodies;
2. run the configured slicer's analysis;
3. add targeted B-Rep or mesh checks only for recurring high-value rules;
4. store results in the verification report.

## Print time and filament mass

**Status:** External.

Fusion exports manufacturing geometry but is not a replacement for the printer's slicer. Use PrusaSlicer, OrcaSlicer, Bambu Studio, CuraEngine, or another command-line/profile workflow where available. PrusaSlicer's CLI is usable on this host and this package drives it directly — see the next section — so these numbers come from a real headless slice bound to the project hash. Only PrusaSlicer has been exercised here; nothing has been tested about the others either way, and no adapter is bundled for them. Where no slicer runs, report that the estimate was not produced rather than inventing one.

## Headless slicing from the PrusaSlicer CLI

**Status:** Supported, opt-in — *provided the whole profile set is passed*.

The earlier conclusion recorded here ("PrusaSlicer 2.9.6 segfaults during headless slicing, so the binary is never executed") was wrong about the cause and therefore wrong about the capability. The segfault is triggered by an **incomplete profile set**, not by headless slicing:

| invocation | result |
| --- | --- |
| `--printer-profile` alone | exit 139 (SIGSEGV), no output, no G-code |
| `--printer-profile` + `--print-profile` + `--material-profile` + `--datadir` | exit 0, valid G-code |

`PrusaSlicer --help` states the requirement outright: *"To load configuration from profiles, you need to set whole banch of presets"* (sic). Verified on this host against both the user's real presets and built-in defaults, PrusaSlicer 2.9.6.

So `fusion-design prusaslicer-project --slice` runs the slicer and reports what the G-code says:

```json
{"slice": {"supported": true, "attempted": true, "ok": true,
           "exit_code": 0, "slicer_version": "PrusaSlicer 2.9.6",
           "project_sha256": "...", "gcode_sha256": "...", "gcode_byte_size": 228122,
           "bindings": {"project_sha256": "...", "export_index_sha256": "...",
                        "manifest_sha256": "...", "verification_report_sha256": "...",
                        "export_run_id": "..."},
           "gcode_window": {"head_bytes": 8192, "tail_bytes": 228122, "whole_file_read": true},
           "chain_complete": true,
           "presets": {"printer": "...", "print": "...", "filament": "..."},
           "statistics": {"estimated_printing_time_normal": "17m 59s",
                          "filament_used_g_total": 4.69, "filament_used_mm_total": 1536.63},
           "absent_statistics": [], "warnings": []}}
```

How the boundary is held:

- **The incomplete profile set is refused, not attempted.** `require_complete_profile_set` raises before anything is executed when printer, print, or filament is missing. That refusal is the fix for the crash, and it is tested by name. A *complete but unresolvable* set is a different failure and was measured separately on PrusaSlicer 2.9.6 (2026-08-19): three names that resolve to nothing exit **1**, not 139, with `Error while loading config from profiles: Printer profile 'X' wasn't found.` -- with and without `--datadir`. So the guard checks completeness, which is what crashes; resolvability failures arrive as an ordinary structured failure with that message as the stderr tail.
- **A `--datadir` is always supplied.** A plain-dict `presets` argument used to drop it silently, resolving names in PrusaSlicer's default configuration rather than the one they were validated against; that call is now refused.
- **Execution is confined to one module.** `prusaslicer_slice.py` is the only file in the package permitted to touch a process-execution API; project construction (`prusaslicer_project.py`, `cli.py`, everything `build_project` calls) still contains none, and a structural AST test enforces exactly that split.
- **`subprocess.run` with an argument list.** No `shell=True`, no string interpolation into a shell, and a timeout so a hung slicer cannot block forever.
- **Statistics come only from whole lines of the produced G-code's trailing summary block.** PrusaSlicer writes them as one contiguous run of `; key = value` comments at the end of the file, ahead of the `prusaslicer_config` dump, and only that run is parsed. The anchor is structural, not a window: a profile's custom *start* G-code sits at the top of the file, separated from the run by the extrusion moves, so it is excluded for a 200-byte G-code exactly as for a 200-megabyte one — selecting a tail window would exclude nothing at all in the small case, and small parts routinely slice well under the window size. The file is read through a bounded head/tail window (the middle is extrusion moves and can be hundreds of megabytes) and both windows are trimmed to line boundaries first: a window cut mid-line would otherwise turn a truncated number into a syntactically valid, wrong one -- a real `41.9 g` read as `4.0 g`. `gcode_window` reports how much of the file was read, and a slice that yields no readable statistic is `ok: false` rather than `ok: true` with an empty block -- "the statistics were outside the window" must not be indistinguishable from "the slicer wrote none". Anything the G-code does not state is listed in `absent_statistics`. Nothing is inferred, estimated, or interpolated from the project file, the mesh, or a previous print.
- **The slice is bound to the project it claims to have sliced.** `slice_project` takes a `bindings` map, re-hashes the file on disk against its `project_sha256`, and refuses to run if it changed since the project was built. The map -- export index, manifest, verification report, export run -- is echoed into the result, so a slice block lifted out of one report has something to contradict it.
- **`--binary-gcode=0` is forced.** The Original Prusa XL presets default to binary G-code, whose statistics are not readable as `; ` comments.
- **Failure is structured, never a fabricated number.** A non-zero exit (139/SIGSEGV included), a timeout, or a missing output file yields `ok: false` with the exit status and stderr tail, and the CLI exits 2.

Without `--slice`, nothing is executed and the block reads `{"supported": true, "attempted": false, ...}`.

Where PrusaSlicer is not installed, `slice_project` returns an explicit unavailable result; obtain the numbers from a manual GUI slice and record them against the project's `sha256` instead.

## FDM-specific structural load rating

**Status:** No trustworthy one-button equivalent.

Fusion simulation can be useful when material, boundary conditions, mesh, and load are appropriate, but ordinary isotropic material analysis does not automatically model printed-layer adhesion, process defects, or insert/fastener behavior. Use conservative geometry, appropriate simulation, coupons, and proof tests. State safety factors and uncertainty.

## Headless rendering and verification bundle

**Status:** Partial and MCP-capability-dependent.

The skill can request Fusion viewport screenshots and section views when the connected MCP exposes those capabilities. The package does not include a standalone headless renderer or automatically compose every numerical result and image into one report. Preserve machine-readable inventory/verification JSON, capture the required views in the live document, and link them in the handoff. A separate report generator can be added without moving CAD ownership out of Fusion.

## Automatic scan-to-parametric reconstruction

**Status:** Unsupported as a reliable general workflow.

Import the scan as immutable mesh reference, establish coordinate system and scale, extract only needed sections/datums, rebuild native sketches/features, and validate with a fit coupon. Use external mesh tools for cleaning, registration, or cross-section extraction when Fusion API coverage is insufficient.

What this package *does* supply is in `references/mesh-reconstruction.md`: immutable capture bound by SHA-256, an enforced three-way classification gate, the faceted refusal ladder, offline sectioning and primitive fitting, design-intent proposals, and the asymmetric deviation verdict. What it deliberately does not supply:

- whole-part auto-conversion — the abandoned upstream fitter and both commercial references agree this is where the difficulty sits;
- organic and freeform surface recovery;
- automatic assertion of design intent — coaxiality, perpendicularity, symmetry and nominal-value snapping are surfaced as proposals carrying their measured deviation, never applied silently;
- coordinate-frame derivation from the fitted primitives — **not implemented**, despite being how both reference tools establish their frame;
- Sketch API emission from the fits — **not implemented**; the fits and proposals stay host-side data today.

## Fusion Mesh Section Sketch and Fit Curves to Mesh Section

**Status:** UI-only. No API exists, so a skill driving Fusion over MCP cannot use them.

`Create Mesh Section Sketch` and `Fit Curves to Mesh Section` are Fusion's only native parametric route from a mesh, and both are UI-only: there is no `MeshSectionSketch` class, nothing on `Sketch` that creates one, and no `MeshPlaneCutFeature`. Never emit a script that calls them.

The raw material *is* scriptable, which is why the fallback is our own arithmetic rather than an external tool: `MeshBody.mesh` returns a `PolygonMesh` exposing `nodeCoordinates`, `triangleNodeIndices` and `triangleFaceGroupTempIds` — Fusion's own segmentation, readable per triangle. Plane–mesh intersection and least-squares primitive fitting over that data live in `src/fusion_design/mesh_fitting.py` and are fully testable offline against synthetic meshes with known analytic answers. Fusion fits primitives internally for `MeshGenerateFaceGroupsFeature` but never exposes the fit, only the grouping.

## Face-group segmentation: measured 2026-08-19, and now the segmentation source

**Status:** Supported, cheap, far better than its default suggests, and adopted.

`emit-mesh-face-groups` runs it and `fit-regions` consumes it. The package's own
RANSAC/ICM segmentation layer is **deleted** — the numbers below are why — and a
dump with no grouping is refused `face-groups-absent` rather than segmented by a
fallback nobody measured. What is *not* delegated is the judgement: every group
Fusion returns still passes support floors, Moran's I, the blocked held-out
refit, the parsimony F test and the uncertainty gate before it is a fit.

Re-measured 2026-08-19 with both pipelines run over identical dumps of the same
11 STLs at the same declared thresholds: area-weighted coverage rose from
**41.7% to 62.5%**, regions offered to the fitters from 47 to 1,069, regions
accepted through every gate from 38 to 268, and accepted cylinders from 0 to 4.
POD-B-BASE went from one region at 2.3% to 188 regions at 69.1%. The remaining
839 groups of the 1,908 carry fewer than four points, which is below what a
least-squares fit needs at all, and land in `unclaimed` rather than anywhere
that could be mistaken for a fit.

`MeshGenerateFaceGroupsFeatures.createInput` takes the **MeshBody itself**, not
an `ObjectCollection`; a collection raises `2 : InternalValidationError :
meshBody`. Measured, not inferred from `MeshConvertFeatures`, which does take a
collection.

`MeshGenerateFaceGroupsFeatureInput.meshGenerateFaceGroupsMethodType` **is
readable and settable**, and it is the knob that matters. The three numeric
knobs are not: `angleThreshold`, `minimumFaceGroupSize` and `boundaryTolerance`
all raise `RuntimeError: 2 : InternalValidationError` on get, and reject every
value on set. The method enum does not.

The default is `FastGenerateFaceGroupsType` (angle-threshold clustering).
`AccurateGenerateFaceGroupsType` matches mesh faces to analytic primitives.
Measured over the 11 real production STLs in the Coat electronics-enclosure set
(444 to 16,562 triangles):

| | Fast (default) | Accurate |
|---|---|---|
| face groups, 11 parts | 976 | 1,908 |
| segmentation time | 0.004–0.06 s | 0.03–1.92 s |
| prismatic `MeshConvertFeature` → one healthy solid | 2 of 11 | 10 of 11 |
| worst volume error where a solid *was* produced | +7.6%, reported healthy | −0.14% |
| prismatic convert time, POD-A1-BASE | 33.4 s | 0.30 s |

The prismatic convert consumes these groups — "face groups are used to infer
prismatic features" — so the earlier finding that prismatic convert produces no
solid on real STLs is a finding about the *default grouping*, not about convert.
Under `Accurate`, convert is both correct and one to two orders of magnitude
faster, because it is handed a segmentation instead of having to infer one.

`PolygonMesh.triangleFaceGroupTempIds` delivers the result as one `FaceGroup`
tempId per triangle, in `triangleNodeIndices` order, and `MeshBody.faceGroups`
carries each group's `area`, `centroid`, `boundingBox` and `isPlanar`. That is
a complete region assignment for our own fitters, with no inference needed. The
tempIds partition the triangles and then stop existing: region identity stays a
hash of sorted triangle indices bound to the dump, because a temp id is not
stable across sessions.

The method is set explicitly on every run and read back off the input before the
feature is added; a release where it does not stick refuses rather than grouping
by an unannounced Fast. In a direct-modeling design
`MeshGenerateFaceGroupsFeatures.add()` returns `None` while still applying, so
the return value is never read.

Fed those regions, `mesh_fitting.fit_primitive` accepted a fit on **1,908 of
1,908** groups — every group, on every part — and every one of the 383 cylinders
came back with a radius one-sigma inside the skill's own `max_radius_rel_sigma`
of 2%. One caveat, and it is the whole caveat: on a bore or round tessellated
with only two rings of vertices and no intermediate samples, a sphere passes
exactly through the same points as the cylinder, and `fit_face_group` ranks by
residual alone, so the sphere wins by the eighth decimal. 367 of 367 such
groups are cylinders, and the group's own facet normals say so unambiguously —
every one within 5° of perpendicular to the cylinder axis. **The vertices alone
cannot separate sphere from cylinder here; the facet normals can.** Any use of
these regions has to carry that tie-break, and `fit_face_group` now does: given
the group's facet normals and a caller-declared
`cylinder_normal_perpendicular_deg`, a sphere that ranks first loses the group to
an accepted cylinder whose axis every facet normal is perpendicular to. The
evidence is recorded on the fit (`support.normal_tie_break`), and unreadable or
tilted normals leave the ranking exactly where it was.

The second thing the grouping changed is where the fillets are. Fusion delivers
an edge round as a **partial-arc cylinder**, not a torus -- that is the 298-group
bucket -- so a fillet candidate is a torus *or* a cylinder whose measured
`angular_span_deg` is inside the declared `max_fillet_arc_deg`. A bore or a boss
closes on itself and a round never does, which is the measurement that separates
them. The evidence discipline is unchanged: two accepted non-blend neighbours or
it is an ordinary fit.

**The normals are fit data, not only a tie-break.** Using them only to rank
kinds left 367 groups selecting a cylinder with its true radius and then being
refused for support span, because two rings of vertices determine a *radius*
without determining an *axis*. That refusal was correct about the vertices and
wrong about the mesh: every facet normal on a cylinder is perpendicular to its
axis by construction, so the facets between the two rings determine the axis
exactly. `mesh_fitting.normal_constrained_axis` takes the area-weighted
second moment `A = sum w n n^T`, reads the axis off its smallest eigenvector, and
reports the closed-form Gauss-Newton sigma `sigma_theta * sqrt(1/l1 + 1/l2)` in
the tangent plane -- so the determinacy of the axis is `l1 / trace`, one half for
a full ring of facets and falling to zero for a sliver. With the direction
pinned, the radius and axis point are the module's existing exact 2-D circle fit.

The `min_axial_span_ratio` floor is untouched and still applied to every fit
whose axis came from the vertices. What changed is that a fit whose axis came
from the normals, at a caller-declared `min_normal_axis_eigengap`, records the
floor as *measured and not applied* along with the evidence that replaced it: the
floor asks "how long a cylinder must be before its axis is determined", and that
question is about a determination this fit did not make.

Measured over the same 11 parts: 251 cylinders survive every gate where 4 did,
76 of the 85 full-turn bores are recovered where none were, 114 fillet candidates
where one was found, and area coverage rises from 62.5% to 70.5%. No declared
threshold changed value.

**What this still does not buy.** (Nine of the 85 full-turn bores were still
refused here, by the Moran and held-out gates operating on residuals at the
mesh's own float32 quantization. That is fixed: those gates now decline to judge
a residual field lying entirely inside the measured `vertex_precision_floor`, and
all 85 are recovered — see `references/mesh-reconstruction.md`.) Fusion's
grouping on these parts delivers each edge round as a
*single* group, so the chain assembly that would join a fragmented round into one
fillet has nothing to join and every chain has one member; on a grouping that
does fragment, it would. And no cone or torus takes its axis from the normals:
the router recovers a surface of revolution's axis from the same accumulation,
but no cone or torus survives any gate on any of the 11 parts, so wiring it would
mean declaring the router's five thresholds to drive a path with no measured
instances.

## Mesh deviation comparison (`PolygonMesh.compareWith`)

**Status:** Unusable for the case it exists for, and **preview-gated**.

`PolygonMesh.compareWith(other, transform, transformOther)` (July 2026) returns the signed distance from every node of one mesh to the closest point on another, in centimetres. It is flagged preview, like every mesh feature class, and Autodesk's own guidance is never to deliver programs that use preview capabilities.

It also **cannot grade a B-Rep reconstruction at all**, which is the primary case. `compareWith` is defined on `PolygonMesh`; only `MeshBody.mesh` returns one. Everything a `BRepBody` offers through its `meshManager` is a `TriangleMesh`, and on Fusion 2705.0.108 `hasattr(adsk.fusion.TriangleMesh, "compareWith")` is **`False`**. A reconstruction is a B-Rep, so the comparison was never reachable for it.

`fusion-design emit-mesh-deviation` therefore measures both directions itself, with released APIs, and keeps `compareWith` only as a **corroboration** path: it runs when both bodies happen to expose a `PolygonMesh` that has it, its result is recorded beside the native measurement, and a disagreement is flagged rather than resolved in `compareWith`'s favour. When it is unavailable the report says so by name and the verdict is unaffected.

## Point-to-surface and point-to-mesh distance

**Status:** Both unsupported for this question; measured, not assumed.

Every one of these was tried on Fusion 2705.0.108 and the numbers are why the deviation verdict computes its own distances:

- `MeasureManager.measureMinimumDistance(point, BRepBody)` returns **zero for any point inside the solid** — and a scanned vertex inside the reconstruction is exactly the invented-material case the verdict has to size.
- `MeasureManager.measureMinimumDistance(point, BRepFace)` measures the face's **untrimmed** underlying surface. On a box with a boss, a point 3 mm inside the hole of the annular top face measured **0.0 mm** to that face. `MeasureResults.positionOne` came back as the query point, so the answer cannot even be post-filtered against `isParameterOnFace`.
- `MeasureManager.measureMinimumDistance(point, MeshBody)` raises `3 : measurement failed`, and against a `PolygonMesh` or a display `TriangleMesh` it raises `3 : invalid argument geometryTwo`. A closed mesh fares no better than an open one.

So the reconstruction's boundary is taken from `MeshManager.createMeshCalculator()` at a declared `surfaceTolerance` and `maxSideLength`, and every distance is a point-to-triangle computation in the transaction, stdlib only. The tessellation is an approximation of the exact B-Rep, bounded by that tolerance, and the report carries the number.

`TriangleMesh.surfaceTolerance` raises `2 : InternalValidationError : res` rather than reporting what was achieved, so the report records the requested tolerance and states plainly that the achieved one was not reported — it never copies the request into the achieved slot.

Facet ceilings are likewise never hardcoded: the widely-cited 10,000/50,000 numbers are unverified and version-specific, so the faceted refusal ladder quotes `errorOrWarningMessage`/`healthState` from Fusion itself. `MeshConvertFeatures.add` and `MeshGenerateFaceGroupsFeatures.add` are documented to return null for non-parametric operations even when the operation succeeded, and the emitted transaction handles that rather than assuming a feature object.

## Editable arbitrary downloaded mesh

**Status:** Unsupported in the sense users usually mean.

Mesh conversion may produce a faceted B-Rep and does not recover sketches, constraints, or design intent. Keep the mesh as packing evidence or rebuild a native model. Prefer STEP/B-Rep from the manufacturer.

## Mesh-only automated clearance and interference

**Status:** Unsupported by the included verifier.

Fusion can retain meshes and can include them in broad bounding-box queries, but the package's precise bounds, positive-volume checks, minimum-distance gate, and interference analysis deliberately require root-context B-Rep geometry. When the best source is a mesh:

1. preserve the original mesh as immutable exact-shape evidence;
2. create a conservative native B-Rep occupancy envelope in the same installed position;
3. run automated clearance and interference against that envelope;
4. use mesh deviation or visual inspection separately when exact surface fidelity matters.

Do not report a mesh-only occurrence as digitally clash-checked merely because it is visible in Fusion.

## Semantic model diff

**Status:** Partial.

The included report diff catches parameters, component paths, body summaries, and timeline health. Newer Fusion releases expose mesh comparison for deviation, but this is mesh-to-mesh and release-dependent. For release evidence, combine:

- inventory report diff;
- exported file hashes;
- mesh deviation when available;
- screenshots;
- Fusion version history.

## One-call joint-range collision sweep

**Status:** Custom workflow.

Fusion supports components, joints, transforms, measurements, and interference, but this package does not guess each mechanism's motion variable. Write a task-specific sampled sweep and report the first collision position.

## Automatic duplicate-feature extraction

**Status:** Unsupported.

After two or more parts reveal genuinely shared logic, refactor into shared user parameters, a derived/reference component, configuration, or reusable feature strategy. Do not prebuild a generic system before the design demonstrates the commonality.

## Long-running autonomous workflow inside the MCP server

**Status:** Unsupported by design.

The MCP server executes explicit requests; the agent/skill owns the plan, checkpoints, decisions, and loop. Keep state in the manifest, Fusion document, reports, and `DESIGN-STATE.md`.

## Oblique sketch planes in a parametric reconstruction

**Status:** Unsupported in v1; bounded by the Fusion API.

`ConstructionPlaneInput.setByPlane` is direct-edit-only, so in a parametric
design every sketch plane must be an origin plane or an offset from one. A
reconstruction whose cap plane is oblique to every datum axis is declared
`plane-unmappable` host-side, before any transaction exists, and its regions
become unreconstructed with that gate named.

The escape hatch is known and deliberately not attempted: a scaffold sketch
carrying three points, with a construction plane through them. It is future
work rather than an improvisation, because a scaffold sketch is itself geometry
that would have to be planned, constrained and verified.

## Hole and fillet emission from a reconstruction program

**Status:** Built — under the named conditions below, outside which they refuse.

This entry previously read "not yet emitted", on the grounds that hole
classification needs triangle winding to tell a bore from a boss and that
evidence was not in the fit record. The evidence *is* in the fit record — the
fitting stage measures `orientation.material_side` per region — and the planner
now reads it. Both kinds emit. What remains unsupported is narrower, and worth
stating precisely, because each of these leaves a region unreconstructed under
the named gate rather than producing an approximate feature:

1. **A hole in a mesh that is not watertight.** `material_side` is `null` on an
   open or inconsistently wound mesh, and a cylinder of unknown side is left
   unreconstructed with `material-side-unavailable`. Fix the scan, not the
   threshold.
2. **A hole in a program with more than one base body** —
   `hole-base-ambiguous`. Nothing in the fit record says which body a bore is a
   hole in, and choosing would be a guess.
3. **A hole in a revolved body** — `hole-base-not-extruded`. A bore coaxial with
   a revolve is already part of its half-profile; a non-coaxial bore against a
   revolved body is a real feature and is not placed here.
4. **A hole whose axis is oblique to its body's extrusion direction**
   (`hole-axis-oblique`) or that reaches outside the body it would cut
   (`hole-not-contained`).
5. **A fillet whose two neighbours were not both rebuilt**
   (`fillet-neighbour-unreconstructed`) — without two rebuilt neighbours there is
   no edge. **Or whose neighbours are surfaces of one archetype whose faces this
   emitter cannot partition** (`fillet-neighbour-shared`): an edge between two
   faces of a *single* feature is rounded where that feature is a
   `sketch-extrude` — its `startFaces`, `endFaces` and `sideFaces` name the edge,
   and the plan records its caps in station order so the right one is picked —
   but a `revolve` exposes no such partition and an edge inside one is not
   nameable. Blend fragments are pooled **per edge**, which the fit record's own
   `fillet.chain_id` names -- a chain is a run of adjacent fragments that agree
   in radius and lie between the same two primaries, which is one rounded edge.
   Two edges between the same pair of face sets are two fillets, each carrying
   its own radius; the fragments of one edge are pooled into one fillet, and only
   when an `equal_radius_tolerance` is declared and they agree inside it
   (`fillet-radius-undeclared`, `fillet-radius-disagrees`). A record that names no
   chain for a pair carrying more than one fragment cannot say which fragments
   share an edge and is refused (`fillet-edge-unidentified`). **Or whose
   own blend surface another archetype already rebuilds** — a partial-arc
   cylinder can be a side of an extrude or the wall of a bore, where a torus
   never could, and a region rebuilt twice is counted twice in the coverage
   account. That last case names no gate: the region *is* reconstructed, by the
   archetype that claimed it, so it never reaches `unreconstructed` at all.
6. **A fillet whose parent features share no edge in the built solid.** Recorded
   in the rebuild report's `fillets_skipped` and subtracted from coverage. The
   blend fit said the two surfaces meet and the built solid says they do not;
   rounding some other nearby edge would invent the geometry the measurement
   failed to find.
7. **Variable-radius and elliptical blends.** Fillets are proposed by adjacency
   and near-constant width, which is enough for a `filletFeatures` radius and
   not enough to certify anything richer.

Fillets are the one archetype that is *individually optional*: nothing depends
on a finishing feature, so a fillet that cannot be placed costs its own region
and nothing downstream. Every other archetype carries dependents, which is why
every other failure rolls the whole build back.

## Guaranteed full coverage of any part

**Status:** Structurally impossible, and `parametric-partial` exists because of it.

`reconstruction-coverage` returns `parametric-full`, `parametric-partial` or
`reconstruction-refused`. The middle label is the honest common case and it is a
**success**: part of the scan stands as editable features, the rest is listed
with the gate that stopped it, and the source mesh stays in the document as
reference geometry over the rebuild.

Any promise of full coverage on an arbitrary part would be the claim this whole
pipeline is a correction to. The coverage arithmetic therefore runs one
direction only — each stage may lose area and can never gain any — so an
archetype that was planned and not delivered subtracts its region even when the
build otherwise succeeded.

## Adopted 3-D relationships as sketch constraints

**Status:** Carried as evidence, not enforced.

The reconstruction program names its adopted relationships by region hash. A
mesh section returns points, not regions, and the emitter receives the program
and the dump but never the fit record — so nothing in it can say which sketch
entity came from which region. Adopted constraints are carried into the report
with `localized: false` and are never claimed to have been enforced. The sketch
constraints that *are* applied were measured independently from the 2-D section,
each recording the deviation it snapped from.

## Joint-parameter interaction in the editability proof

**Status:** Not exercised.

The perturbation loop changes one parameter at a time and reports
`interactions_exercised: false`. Pairwise perturbation is the same loop run
n-squared times; it is deferred for run time, not for difficulty.
