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

**Status:** Partial.

Fusion Configurations can represent families where available; named parameter sets can cover simpler cases. The host CLI does not iterate every configuration, regenerate every export, or build a per-variant verification matrix. For release work, activate one named configuration or parameter set at a time, compute, verify, export, hash, and record the results. Add a project-specific batch driver only when the family warrants it.

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

Fusion exports manufacturing geometry but is not a replacement for the printer's slicer. Use PrusaSlicer, OrcaSlicer, Bambu Studio, CuraEngine, or another supported command-line/profile workflow where available. When no reliable CLI/profile is present, report that the estimate was not produced. On this host no slicer CLI is usable — see the next section — so these numbers currently come only from a manual GUI slice.

## Headless slicing from the PrusaSlicer CLI

**Status:** Unsupported on this host; the binary is never executed.

PrusaSlicer 2.9.6 segfaults during headless slicing on this machine: `Slic3r::CLI::process_actions` → `Print::export_gcode` → `EXC_BAD_ACCESS` in `optional<ConflictResult>::operator=`. Four crash reports were produced before probing stopped. The `fusion-design prusaslicer-project` adapter therefore contains **no process-execution API at all** — not `subprocess`, not `os.system`, not `Popen`, not even `--help` — and its result always carries:

```json
{"slice": {"supported": false, "reason": "...", "detail": "..."}}
```

What is supported is project *generation*: the adapter builds a PrusaSlicer project `.3mf` from the verified export index plus declared `manufacturing_intent`, with one object per printable part, the declared build orientation applied, declared plate grouping, presets selected by identifier only, and only per-object overrides that declared intent justifies.

Fallback for print time, filament mass, supports, and G-code statistics:

1. generate the project with `fusion-design prusaslicer-project`;
2. open that `.3mf` in the PrusaSlicer GUI by hand;
3. slice there and read the statistics from the application;
4. record them in the handoff against the project's recorded `sha256`.

Never infer, estimate, or interpolate those numbers from the project file, the mesh, or a previous print.

## FDM-specific structural load rating

**Status:** No trustworthy one-button equivalent.

Fusion simulation can be useful when material, boundary conditions, mesh, and load are appropriate, but ordinary isotropic material analysis does not automatically model printed-layer adhesion, process defects, or insert/fastener behavior. Use conservative geometry, appropriate simulation, coupons, and proof tests. State safety factors and uncertainty.

## Headless rendering and verification bundle

**Status:** Partial and MCP-capability-dependent.

The skill can request Fusion viewport screenshots and section views when the connected MCP exposes those capabilities. The package does not include a standalone headless renderer or automatically compose every numerical result and image into one report. Preserve machine-readable inventory/verification JSON, capture the required views in the live document, and link them in the handoff. A separate report generator can be added without moving CAD ownership out of Fusion.

## Automatic scan-to-parametric reconstruction

**Status:** Unsupported as a reliable general workflow.

Import the scan as immutable mesh reference, establish coordinate system and scale, extract only needed sections/datums, rebuild native sketches/features, and validate with a fit coupon. Use external mesh tools for cleaning, registration, or cross-section extraction when Fusion API coverage is insufficient.

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
