# Unsupported or partial capabilities and recommended fallbacks

Status date: 2026-08-21. Fusion and its MCP expose dynamic capabilities; verify the connected Fusion release and MCP schema rather than treating this file as a fixed tool catalog.

## Fixed MCP tool names

**Status:** Unsupported assumption.

Autodesk documents dynamic tooling. Discover and bind the current schema at connection time. Keep adapter logic in the agent/skill instead of hard-coding one client's current tool names.

## Separate browser viewer with generated sliders

**Status:** No direct equivalent in the core Fusion MCP.

Use the live Fusion canvas, Parameters dialog, configurations, visibility/opacity, section analysis, and MCP screenshots. Build an optional Fusion palette add-in only when a separate review UI proves necessary.

## Separate development server or launcher

**Status:** Not needed and not included.

Fusion is already the long-lived interactive CAD host. Start Fusion normally, enable its MCP server, connect the agent, and keep one document open through the iteration. An operating-system launcher may automate those startup steps, but it is outside this package: the live Fusion canvas is the viewer.

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

**Status:** External to Fusion; installed-runtime queries supported.

The package does not duplicate `printer.toml` as an incomplete model of a slicer's machine, nozzle, filament, process, and support settings. `prusaslicer-profiles` asks the installed PrusaSlicer 2.9.6 runtime for printer models and compatible print/filament identifiers, preserving the exact identifiers it emits. Keep the authoritative profile in the slicer that will generate the print job. Record the slicer/profile identifiers and versions in the handoff, then attach time, mass, support, and warning results to the exact exported-body hashes.

## Installed PrusaSlicer profile queries and fingerprints

**Status:** Supported for the pinned PrusaSlicer 2.9.6 runtime.

`PrusaSlicerRuntime` is the only profile-query process boundary. It requires an
explicit absolute datadir, probes the `--help` banner, and then invokes
`--query-printer-models` and `--query-print-filament-profiles` with `shell=False`,
a timeout, and bounded output. Every result carries executable path and
SHA-256, detected version, datadir, profile-snapshot SHA-256, command kind, raw
exit code/signal, and bounded stderr. The snapshot is deterministic over
`PrusaSlicer.ini` plus sorted `.ini` files under `printer/`, `print/`,
`filament/`, and `vendor/`.

The normalized outcomes are distinct: `not_found`, `timeout`, `nonzero_exit`,
`signal_crash`, `malformed_json`, `missing_app_config`,
`profile_not_resolvable`, `snapshot_changed`, `unsupported_version`, and
`success`. A valid schema-conforming query payload is success even when the
PrusaSlicer process returns raw exit code `1`; invalid or empty exit-`1` output
is not success. A runtime or snapshot failure stops project construction and
never selects another datadir or silently downgrades to the parser.

The existing `.ini`/vendor parser remains available only through the explicit
`--offline-profiles` flag. That result is `resolver: offline_parser`,
`installed: false`, and compatibility `unknown`; it may generate an unsliced
project only, and `--offline-profiles --slice` is refused.

See `references/prusaslicer-source-contract.md` for pinned source ownership and
`references/prusaslicer-3mf-contract.md` for the project/native metadata boundary.

## Complete FDM printability checker

**Status:** Not supplied by the core package.

Fusion can expose B-Rep geometry, face normals, bounds, and measurements, but robust minimum-wall, bridge, overhang, trapped-support, and machine-specific checks need an analyzer or slicer. Recommended path:

1. export the exact print bodies;
2. run the configured slicer's analysis, an installed trusted Fusion add-in, or an existing validated analyzer already present when the lane locks;
3. cover the remainder with manual measured review or a physical coupon;
4. store results in the verification report.

Do not author a B-Rep, mesh, or FDM analyzer during a CAD task. Developing a new analyzer is a separate software-engineering request; its implementation and testing do not occur inside the modeling or release run.

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
- **Execution is confined to two modules.** `prusaslicer_runtime.py` owns installed profile queries and `prusaslicer_slice.py` owns slicing. Project construction (`prusaslicer_project.py`) and CLI dispatch remain process-free; a structural AST test keeps the process boundary explicit.
- **`subprocess.run` with an argument list.** No `shell=True`, no string interpolation into a shell, and a timeout so a hung slicer cannot block forever.
- **Statistics come only from whole lines of the produced G-code's trailing summary block.** PrusaSlicer writes them as one contiguous run of `; key = value` comments at the end of the file, ahead of the `prusaslicer_config` dump, and only that run is parsed. The anchor is structural, not a window: a profile's custom *start* G-code sits at the top of the file, separated from the run by the extrusion moves, so it is excluded for a 200-byte G-code exactly as for a 200-megabyte one — selecting a tail window would exclude nothing at all in the small case, and small parts routinely slice well under the window size. The file is read through a bounded head/tail window (the middle is extrusion moves and can be hundreds of megabytes) and both windows are trimmed to line boundaries first: a window cut mid-line would otherwise turn a truncated number into a syntactically valid, wrong one -- a real `41.9 g` read as `4.0 g`. `gcode_window` reports how much of the file was read, and a slice that yields no readable statistic is `ok: false` rather than `ok: true` with an empty block -- "the statistics were outside the window" must not be indistinguishable from "the slicer wrote none". Anything the G-code does not state is listed in `absent_statistics`. Nothing is inferred, estimated, or interpolated from the project file, the mesh, or a previous print.
- **The slice is bound to the project it claims to have sliced.** `slice_project` takes a `bindings` map, re-hashes the file on disk against its `project_sha256`, and refuses to run if it changed since the project was built. The map -- export index, manifest, verification report, export run -- is echoed into the result, so a slice block lifted out of one report has something to contradict it.
- **Binary G-code is the default output and is decoded in-process.** The earlier `--binary-gcode=0` force is gone (2026-08-21): bgcode containers (gzip/deflate and heatshrink blocks alike) are decoded by the package's own reader, so the statistics block is read identically from either flavor. ASCII remains selectable for debugging. A gzip-wrapped plain-text stream is decoded too rather than misread as a corrupt container.
- **The tool audit is conservative.** After a text slice, `gcode_audit` streams complete lines and recognizes only standard `T<number>` selections when the flavor evidence is compatible. It reports observed tools and a tool-change count; unknown or conflicting flavor evidence returns `available: false`.
- **Failure is structured, never a fabricated number.** A non-zero exit (139/SIGSEGV included), a timeout, or a missing output file yields `ok: false` with the exit status and stderr tail, and the CLI exits 2.

Without `--slice`, nothing is executed and the block reads `{"supported": true, "attempted": false, ...}`.

Where PrusaSlicer is not installed, `slice_project` returns an explicit unavailable result; obtain the numbers from a manual GUI slice and record them against the project's `sha256` instead.

## Native PrusaSlicer project metadata bridge

**Status:** Deferred and unsupported in the Python package.

Painted facets (`FacetsAnnotation`), variable layer-height profiles,
FullSpectrum/ColorMix virtual extruders, and native arrangement transforms are
semantic 3MF structures, not ordinary config keys. A project opening in the GUI
or preserving an unknown key is not proof. See
`references/prusaslicer-3mf-contract.md`: a future bridge must be version-gated
and prove load → save → inspect semantic equality against the pinned source
family. This wave adds no `libslic3r` dependency, copied slicer algorithms, or
empty C++ scaffold.

## FDM-specific structural load rating

**Status:** No trustworthy one-button equivalent.

Fusion simulation can be useful when material, boundary conditions, mesh, and load are appropriate, but ordinary isotropic material analysis does not automatically model printed-layer adhesion, process defects, or insert/fastener behavior. Use conservative geometry, appropriate simulation, coupons, and proof tests. State safety factors and uncertainty.

## Headless rendering and verification bundle

**Status:** Partial and MCP-capability-dependent.

The skill can request Fusion viewport screenshots and section views when the connected MCP exposes those capabilities. The package does not include a standalone headless renderer or automatically compose every numerical result and image into one report. Preserve machine-readable inventory/verification JSON, capture the required views in the live document, and link them in the handoff. A separate report generator can be added without moving CAD ownership out of Fusion.

## Imported mesh references

**Status:** Limited reference support.

Keep imported meshes as packing or inspection evidence, and repair them only as
needed for that reference use. They are not a substitute for native B-Rep
authoring. Prefer a manufacturer-provided STEP/B-Rep model when available.

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

**Status:** Not supplied; native poses are the ordinary path.

Fusion supports components, joints, transforms, measurements, and interference, but this package does not guess each mechanism's motion variable. For ordinary modeling, drive the joint through the user-relevant critical poses with Fusion's native joint controls and run native Interference at each named pose, including intermediate poses when the mechanism's geometry makes an intermediate collision credible. An automated sampled motion sweep requires an explicit automation request and unchanged pre-existing tooling; when no such tooling exists, report the capability boundary instead of writing a task-specific sweep.

## Automatic duplicate-feature extraction

**Status:** Unsupported.

After two or more parts reveal genuinely shared logic, refactor into shared user parameters, a derived/reference component, configuration, or reusable feature strategy. Do not prebuild a generic system before the design demonstrates the commonality.

## Arbitrary conformal double-curved cutout

**Status:** Ordinary native modeling preferred; not a toolkit recipe.

Fusion provides `Sketch.projectToSurface`, so a person can project a loop onto
a curved wall and build a conformal opening through surface and trim features.
What the toolkit deliberately does not do is turn an arbitrary projected loop
on an arbitrary double-curved wall into a bounded, reliable recipe: profile
orientation, offset behavior, and trim topology vary too much per wall to give
the abstraction recurring enclosure value. Axis-projected cuts through curved
walls remain supported recipes (`references/enclosure-features.md`); a truly
conformal opening is modeled natively with projection + surface workflow.

## Arbitrary freeform dovetail / bayonet

**Status:** Scoped recipes only; arbitrary freeform spatial joinery is
ordinary native modeling.

Dovetail and sliding-key recipes require a linear or tangent-continuous rail
path. Bayonet recipes require a common cylindrical axis with explicit lug
count, insertion distance, locking rotation, lug geometry, and slot clearance.
An arbitrary three-dimensional dovetail or bayonet track — freeform rails,
non-cylindrical bayonet surfaces, discontinuous frames — would need a general
swept-joinery engine with robust corner handling to be safe; that is rejected
by architecture rather than deferred. Model those natively where a design needs
them.

## Automatic arbitrary whole-cell vent clipping

**Status:** Rejected by architecture.

For `whole_cells` boundary policy over an arbitrary freeform region,
automatically deciding which patterned cells fall inside the region is a
general polygon-containment/filtering engine — exactly the parallel geometry
analyzer this package refuses to become. Rectangular/circular bounded regions
may use their parametric limits; clipped regions use an explicit mask body;
freeform regions accept explicit suppressed indices from the user or refuse.

## Specialized extension-feature entitlement boundaries (Snap/Lip/Rest)

**Status:** No established public creation APIs; extension UI only;
base recipes are the supported path.

Autodesk documents Snap Fit, Lip, and Rest as Design Extension UI commands.
The public API documentation searched during the design pass established no
specialized creation collections analogous to `BossFeatures` for any of them
(and Boss itself remains an unresolved *entitlement* probe even though its API
exists). The toolkit therefore never depends on these objects: base recipes
reproduce the geometry with ordinary features. If a current build exposes a
specialized collection, it may be probed live as an optional, separately
identified adapter path — never silently substituted for the base recipe.
Plastic Rules are intentionally not depended upon in any form; the toolkit's
own FDM evidence model replaces them (`references/enclosure-feature-rules.md`).

## Louver arrays

**Status:** Ordinary native modeling preferred; not a toolkit recipe.

A louver combines opening geometry, directional hood geometry, airflow intent,
print orientation, and support concerns. A reusable recipe would offer little
beyond the actual native sketch/extrude/pattern workflow while adding real
design-policy ambiguity (airflow direction, hood angle, support strategy).
Model louvers natively; vent arrays over bounded planar regions remain
supported toolkit recipes.

## Long-running autonomous workflow inside the MCP server

**Status:** Unsupported by design.

The MCP server executes explicit requests; the agent/skill owns the plan, checkpoints, decisions, and loop. Keep state in the manifest, Fusion document, reports, and `DESIGN-STATE.md`.
