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

## Mesh deviation comparison (`PolygonMesh.compareWith`)

**Status:** Supported where present, and **preview-gated**.

`PolygonMesh.compareWith(other, transform, transformOther)` (July 2026) returns the signed distance from every node of one mesh to the closest point on another, in centimetres. It is the **only** API-level deviation mechanism in Fusion, it has no UI equivalent, and like every mesh feature class it is flagged preview — Autodesk's own guidance is never to deliver programs that use preview capabilities.

`fusion-design emit-mesh-deviation` therefore fails closed rather than degrading:

- when `compareWith` is absent, the report is `deviation-capability` with the API name and the connected Fusion version — never a silent skip and never a fabricated number;
- when the connected Fusion returns only unsigned magnitudes, or when the sign convention cannot be established by probing `BRepBody.pointContainment` against the returned signs, invented material cannot be separated from omitted detail, so the invented-material verdict is reported `not-established` rather than as a pass. The polarity is never assumed: nothing documents it, and assuming it turns invented material into a pass under an inverted convention;
- the two directions are reported as distinct questions and are never collapsed into a single "deviation: X mm". A small maximum deviation from the reconstruction to the scan does not establish that the reconstruction captured every scanned feature.

Facet ceilings are likewise never hardcoded: the widely-cited 10,000/50,000 numbers are unverified and version-specific, so the faceted refusal ladder quotes `errorOrWarningMessage`/`healthState` from Fusion itself. `MeshConvertFeatures.add` and `MeshGenerateFaceGroupsFeatures.add` are documented to return null for non-parametric operations even when the operation succeeded, and the emitted transaction handles that rather than assuming a feature object.

## Editable arbitrary downloaded mesh

**Status:** Unsupported in the sense users usually mean.

Mesh conversion may produce a faceted B-Rep and does not recover sketches, constraints, or design intent. Keep the mesh as `PACK__` evidence or rebuild a native model. Prefer STEP/B-Rep from the manufacturer.

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
