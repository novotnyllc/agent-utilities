# Nurb-to-Fusion capability matrix

This is a conceptual translation, not a claim that Fusion exposes same-named commands. The connected Fusion MCP is dynamically discovered; the package supplies the discipline, manifest, narrow Fusion Python transactions, and verification contract.

## Public Nurb command coverage

| Nurb discipline/tool | Fusion-native equivalent | Status in this package |
|---|---|---|
| Function defaults as parameters | Fusion user parameters, expressions, comments, and attributes | Supported |
| `measurements.toml` provenance | `fusion-project.json` sources plus parameter comments/attributes | Supported |
| `nurb new` | Validate a manifest, synchronize named parameters, and scaffold a stable component tree in a parametric Fusion document | Supported; intentionally does not generate a whole part |
| `nurb dev` | Keep one live Fusion document open; iterate in small timeline edits; use the Fusion canvas, parameter dialog, section analysis, visibility, and MCP screenshots | Partial; no separate hot-reload browser or generated slider UI |
| `nurb build` | Compute All, then inventory component paths, bodies, bounds, parameters, and timeline health | Supported |
| `nurb check` | Manifest verification plus B-Rep clearance, forbidden interference, expected-print-body, and timeline-health gates | Partial; complete FDM rules require external/custom analysis |
| `nurb inspect` | Read-only inventory script with root-context occurrences, bounds, body summaries, parameters, and timeline state | Supported for those measurements; face-local rendered findings need custom work |
| `nurb scan` | Import immutable mesh evidence (`fusion-design emit-mesh-capture`), record units/registration/provenance, record one reconstruction path before any geometry, derive only needed datums or sections, and build a conservative B-Rep checking envelope | Partial. Capture, classification, the faceted refusal ladder and the deviation verdict are supported. **Fusion's Mesh Section Sketch and Fit Curves to Mesh Section are UI-only — no API exists** (`MeshSectionSketch`, `MeshPlaneCutFeature` do not exist), so sectioning and primitive fitting are our own arithmetic over `PolygonMesh`. Coordinate-frame derivation from the fitted primitives and Sketch API emission are **not built** |
| `nurb rules` | `design-doctrine.md`, `material-selection.md`, the main skill, and `verification-contract.md` | Supported |
| `nurb api` | Discover the connected MCP schema and query current Fusion API documentation before scripting | Supported when those dynamic MCP capabilities are present |
| `nurb skill` | Install or update the Agent Utilities plugin, or install this skill through the agent harness's skill manager | Supported through the harness; no runtime printer of the skill |
| `nurb update` | Update the package from its versioned source, rerun tests, then reinstall the skill | Manual/version-control workflow; no automatic self-updater |
| `nurb card` | `DESIGN-STATE.md`, manifest source records, Fusion attributes, and generated inventory/verification reports | Supported as a workflow; no single auto-regenerated card command |
| `nurb diff` | Deterministic before/after semantic report diff for parameters, component paths, bodies, and unhealthy timeline items | Supported; not a complete B-Rep or feature-history diff |
| `nurb slice` | Export exact print bodies to 3MF/STL, then `fusion-design prusaslicer-project` builds a PrusaSlicer project 3MF (objects, orientation, plate grouping, presets by identifier, justified overrides) from the verified index | Supported, including a real headless slice with `--slice`, which reports the produced G-code's print time and filament use bound to the project and G-code hashes. The full printer/print/filament preset set is required — a partial set segfaults PrusaSlicer (exit 139), so the adapter refuses to invoke it that way |
| `nurb stress` | Fusion simulation where appropriate, conservative FDM assumptions, coupons, and proof testing | Not equivalent in core tooling |
| `nurb verify` | Run inventory and verification transactions, preserve machine-readable reports, collect required screenshots/sections, and complete the handoff ledger | Partial; print-specific and physical gates remain external/manual |
| `nurb render` | Capture the live Fusion viewport through MCP screenshot capability; use section analysis and component visibility for diagnostic views | Partial and capability-dependent; no bundled headless renderer |
| `nurb export` | `fusion-design emit-export` generates the deterministic Fusion ExportManager transaction for STEP/3MF/STL with in-script hashing, no-overwrite outputs, and an evidence-bound handoff index | Supported by Fusion when exposed; this host CLI emits the transaction but does not impersonate Fusion export |
| `nurb extract` | Refactor demonstrated repetition into shared user parameters, derived/reference components, configurations, or reusable feature patterns | Manual; automatic duplicate-construction extraction is unsupported |
| `nurb launcher` | Start Fusion normally, enable its MCP server, and connect the agent to the local endpoint | No separate equivalent; Fusion itself is the long-lived interactive host |

## Additional Nurb concepts

| Nurb concept | Fusion-native equivalent | Status in this package |
|---|---|---|
| Browser live viewer | Live Fusion canvas plus MCP screenshots | Partial; no second viewer |
| `nurb compare` / target ghost | `fusion-design emit-mesh-deviation` grades a reconstruction against the immutable source through `PolygonMesh.compareWith`, reporting both directions distinctly with an asymmetric verdict: invented material is a hard failure, omitted detail is advisory | Partial and release-dependent. `compareWith` is **preview-gated** (July 2026) and is the only API-level deviation mechanism Fusion exposes; its absence is a fail-closed unsupported result naming the API and the Fusion version, never a skipped check |
| Mesh Section Sketch / Fit Curves to Mesh Section | No API equivalent exists. Section polylines are computed from `PolygonMesh` node coordinates and triangle indices, and classified into lines and arcs in `mesh_fitting.py` | **UI-only in Fusion**; no emitted script may call them. Sketch API emission from those fits is not built |
| `@assembly` obstacle/joint sweep | Components, as-built joints/joints, limits, named motion parameters, and task-specific sampled interference | Supported as a workflow; each mechanism needs an explicit sweep variable |
| Shared `system.py` | Shared user parameters, derived/reference components, configurations, and intentionally reused features | Fusion-native |
| Card `Don't` history | Decision log and rejected-option section in `DESIGN-STATE.md` | Supported as a workflow |
| Variants | Declared `variants` in the manifest — a parameter-set override or a named Fusion Configuration — driven by `fusion-design plan-variants`, with per-variant inventory, verification, optional export, and verified restoration of the initially active state | Supported and bounded. Parameter sets are the primary path; configuration activation depends on Fusion's configuration API and fails closed when the connected release lacks it |
| `printer.toml` and global printer profile | Slicer-native machine/material profile plus project handoff metadata | External; do not duplicate a slicer's authoritative profile incompletely |
| Material choice | Manifest `material_decision` (family, formulation, source, confidence, coupon, risk) plus `references/material-selection.md` for requirement-driven selection | Supported as a recorded decision; the package ships no numeric property database and no filament profile |
| STEP/3MF output | Fusion B-Rep/mesh export with exact print-body selection and recorded hashes | Supported when the connected export capability exists |
| PrusaSlicer project handoff | `fusion-design prusaslicer-project` writes a deterministic project 3MF from the verified export index plus declared intent, binding it to the index and per-artifact hashes | Supported; presets are named, never cloned, and project construction launches no process at all |
| PrusaSlicer headless slicing (`--export-gcode`) | `fusion-design prusaslicer-project --slice` runs the binary and reports the G-code's own statistics with the project sha256, G-code sha256/size, preset identifiers, slicer version, and exit code | Supported, opt-in. Requires the whole preset set: `--printer-profile` alone exits 139 (SIGSEGV), all three plus `--datadir` exit 0, so an incomplete set is refused before execution. Failures are structured; statistics absent from the G-code are reported absent, never estimated |

## Parity boundary

The package deliberately preserves Nurb's high-value discipline—research, provenance, parametric source of truth, separate reference/packing/keep-out geometry, visible iteration, numerical verification, assembly checks, and honest physical-test boundaries—without recreating Nurb's build123d kernel, browser configurator, FDM analyzer, slicer integration, or stress estimator inside Fusion.
