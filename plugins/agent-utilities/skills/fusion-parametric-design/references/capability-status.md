# Capability status

What this skill's operations can and cannot do, organized by its own lanes.
The connected Fusion MCP is dynamically discovered; every "supported" below
means "through the discovered capability, against the connected release."
`references/unsupported.md` carries the full detail behind each boundary.

## Ordinary modeling

| Operation | Status |
|---|---|
| Native parametric modeling — sketches, features, parameters, expressions, comments, attributes | Supported; small direct operations through MCP |
| Visual iteration | Supported through the live Fusion canvas plus MCP screenshots; there is no separate viewer, slider UI, or hot-reload browser |
| Native inspection — Measure, Interference, Section Analysis, Properties, feature and timeline health | Supported; results are read directly, never wrapped in a framework |
| Assemblies and motion | Supported as components, joints, limits, and named critical poses with native Interference per pose; no one-call joint-range sweep |
| Reusable design elements | Fusion-native: shared user parameters, derived/reference components, configurations, patterns; automatic duplicate-construction extraction is unsupported |
| Decision log and rejected options | A workflow (`DESIGN-STATE.md` in the lanes that keep one); no auto-regenerated summary card |

## Automation lane

| Operation | Status |
|---|---|
| Manifest validation, parameter sync, component scaffold | Supported; the scaffold intentionally does not generate a whole part |
| Inventory and verification transactions | Supported for B-Rep clearance, forbidden interference, expected-print-body, and timeline-health gates; complete FDM rules require a slicer or an existing analyzer |
| Report diffs | Supported as deterministic before/after semantic diffs of parameters, component paths, bodies, and unhealthy timeline items — not a B-Rep or feature-history diff |
| Variants | Supported and bounded: declared manifest `variants` (parameter sets or named Fusion Configurations) driven by `plan-variants`, with per-variant inventory, verification, optional export, and verified restoration. Configuration activation probes Fusion's configuration API and fails closed when the connected release lacks it |

## Release lane

| Operation | Status |
|---|---|
| Deterministic export | Supported where Fusion's export capability is exposed: `emit-export` generates the ExportManager transaction for STEP/3MF/STL with in-script hashing, no-overwrite outputs, and an evidence-bound handoff index |
| Installed PrusaSlicer profile queries | Supported, authoritative for the pinned PrusaSlicer 2.9.6 runtime: `prusaslicer-profiles` invokes the executable's `--query-printer-models` and `--query-print-filament-profiles` actions, preserves exact identifiers, and reports structured failures rather than guessing |
| Runtime and datadir evidence | Supported: query/project/slice results carry executable path and SHA-256, detected version, absolute datadir, deterministic profile-snapshot SHA-256, command kind, raw exit code/signal, and bounded stderr; executable or relevant profile changes fail closed as `snapshot_changed` |
| PrusaSlicer project handoff | Supported: `prusaslicer-project` writes a deterministic project 3MF from the verified export index plus declared intent — objects, orientation, plate grouping, presets by identifier, and bounding-box bed placement with fail-closed footprint/height checks. Presets are named, never cloned; the selected printer's `bed_shape`/`max_print_height` are read from the authoritative query and are not copied into project config |
| Offline profile resolution | Supported only when explicit: `--offline-profiles` uses the existing parser with `resolver: offline_parser`, `installed: false`, and compatibility `unknown`; it may generate an unsliced project but cannot be combined with `--slice` and is never an automatic downgrade |
| Headless slicing | Supported, opt-in (`--slice`): reports the produced G-code's own print time and filament use, bound to the project, runtime, and G-code hashes. The full printer/print/filament preset set is required — a partial set can segfault PrusaSlicer (exit 139), so the adapter refuses to invoke it that way |
| Slice optimization loop | Supported, opt-in (`prusaslicer-optimize`): enumerates orientation candidates (declared alternatives or all six bed contacts), derives a bounded settings variant set from declared `print_intent`, slices every candidate headlessly with all guards intact, ranks by a fixed per-intent objective over measured time/mass plus advisory mesh strength proxies, and reports the ranking bound to the full evidence chain including preset-file hashes. Hard-capped at 12 candidates per part; failed candidates rank last; an every-candidate failure is structured, never a crash |
| Binary G-code | Supported: `.bgcode` output is decoded in-process (gzip/deflate/heatshrink blocks) and parsed identically to ASCII; binary is the default slice output, ASCII stays selectable for debugging. A gzip-wrapped plain-text stream from a wrapper is also decoded rather than misread |
| Preset drift guard (optimizer) | Supported: resolved preset files are hashed at candidate-build time and re-verified before each slice invocation; changed profiles between build and slice are named structured failures |
| Multi-material support assignment | Partially supported: support material may be assigned to a numbered extruder validated against the printer preset's extruder count (soluble-support workflow). Painted enforcer/blocker regions remain unsupported: no deterministic headless encoding is proven |
| G-code tool audit | Supported conservatively after a text slice: bounded streaming recognizes complete `T<number>` selection lines and reports active tools plus a tool-change count only when flavor evidence is compatible; unknown or conflicting flavor evidence returns `available: false` |
| Print time and filament estimates | Only from a real slice; nothing is estimated without one |
| Printer and material profiles | Slicer-authoritative; this package never duplicates a machine or filament profile |
| Native PrusaSlicer project metadata | Deferred: painted facets (`FacetsAnnotation`), variable layer heights, FullSpectrum/ColorMix, and native arrangement transforms require a version-gated bridge with load → save → inspect semantic equality; no Python key approximation or `libslic3r` dependency is shipped |
| Structural and stress claims | Conservative FDM assumptions, coupons, and proof testing; Fusion simulation only where the user holds the extension that gates it |
| Material decision | Supported as a recorded decision (family, formulation, source, confidence, coupon, risk) per `references/material-selection.md`; the package ships no numeric property database and no filament profile |

The ownership boundary and pinned source areas are in
`references/prusaslicer-source-contract.md`; the current minimal project and
deferred native metadata boundary are in
`references/prusaslicer-3mf-contract.md`.

## Enclosure feature toolkit

The shipped enclosure feature toolkit (bosses/hardware, seams, retention,
supports, reinforcement, cutouts, strain relief, seals, vents, fit coupons,
patterns/mirrors) runs through the bundled Fusion add-in on ordinary public
Fusion features — never Autodesk extension-owned plastic features. Per-row
capability classifications, including what is deliberately rejected by
architecture and which native-extension paths remain unresolved entitlement
probes, are maintained in
`references/enclosure-feature-capability-matrix.md`; command/dispatch/lifecycle
behavior is in `references/enclosure-features.md`.

## Reconstruction lane

| Operation | Status |
|---|---|
| Scan capture and classification | Supported: immutable capture bound by SHA-256 (`emit-mesh-capture`), units and provenance recorded, one enforced path — `mesh-edit`, `faceted-brep`, or `parametric-rebuild` |
| Segmentation and fitting | Supported: Fusion's accurate face-group generation, then host-side sectioning and primitive fitting over `PolygonMesh` data. **Fusion's Mesh Section Sketch and Fit Curves to Mesh Section are UI-only — currently not exposed through the API** (`MeshSectionSketch`, `MeshPlaneCutFeature` do not exist; probe at time of use, and where genuinely UI-only they can be driven through a session's computer-use capability), so sectioning and fitting are this package's own arithmetic, fully testable offline |
| Parametric rebuild | Supported under stated conditions: datum-frame derivation from the fitted primitives, archetype planning, and Sketch API emission of extrudes, revolves, holes and fillets in one data-driven transaction. A hole needs `orientation.material_side == "inside"` (watertight mesh); a fillet needs both neighbours rebuilt; anything else is unreconstructed with a named gate, never approximated |
| Deviation grading | Supported on released APIs: `emit-mesh-deviation` grades a reconstruction against the immutable source in both directions with an asymmetric verdict — invented material is a hard failure, omitted detail is advisory. `PolygonMesh.compareWith` is **preview**-gated and cannot grade a B-Rep (a `BRepBody`'s mesh is a `TriangleMesh`, which has no `compareWith`), so it is corroboration only, never the mechanism |
| Editability proof | Supported: each parameter perturbed against its declared observable and restored; `check-editability` is the offline gate; `interactions_exercised` is always `false` |
| Coverage account | Supported: labels from the closed set `parametric-full` / `parametric-partial` / `reconstruction-refused`; the delivered fraction subtracts every planned archetype the build did not deliver |
| Coverage guarantee | None: coverage is partial in principle and is reported as a fraction with every unreconstructed region named |
