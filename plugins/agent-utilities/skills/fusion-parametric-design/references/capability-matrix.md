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
| `nurb scan` | Import immutable mesh evidence, record units/registration/provenance, derive only needed datums or sections, and build a conservative B-Rep checking envelope | Partial; general scan cleanup/section extraction may be external |
| `nurb rules` | `design-doctrine.md`, the main skill, and `verification-contract.md` | Supported |
| `nurb api` | Discover the connected MCP schema and query current Fusion API documentation before scripting | Supported when those dynamic MCP capabilities are present |
| `nurb skill` | Install this versioned skill directory with `scripts/install-skill.sh` | Supported for local installation; no runtime printer of the skill |
| `nurb update` | Update the package from its versioned source, rerun tests, then reinstall the skill | Manual/version-control workflow; no automatic self-updater |
| `nurb card` | `DESIGN-STATE.md`, manifest source records, Fusion attributes, and generated inventory/verification reports | Supported as a workflow; no single auto-regenerated card command |
| `nurb diff` | Deterministic before/after semantic report diff for parameters, component paths, bodies, and unhealthy timeline items | Supported; not a complete B-Rep or feature-history diff |
| `nurb slice` | Export exact print bodies to 3MF/STL and invoke a configured external slicer/profile | External dependency |
| `nurb stress` | Fusion simulation where appropriate, conservative FDM assumptions, coupons, and proof testing | Not equivalent in core tooling |
| `nurb verify` | Run inventory and verification transactions, preserve machine-readable reports, collect required screenshots/sections, and complete the handoff ledger | Partial; print-specific and physical gates remain external/manual |
| `nurb render` | Capture the live Fusion viewport through MCP screenshot capability; use section analysis and component visibility for diagnostic views | Partial and capability-dependent; no bundled headless renderer |
| `nurb export` | Fusion ExportManager or the connected MCP export capability for STEP/3MF/STL, followed by hashes and report linkage | Supported by Fusion when exposed; this host CLI does not impersonate Fusion export |
| `nurb extract` | Refactor demonstrated repetition into shared user parameters, derived/reference components, configurations, or reusable feature patterns | Manual; automatic duplicate-construction extraction is unsupported |
| `nurb launcher` | Start Fusion normally, enable its MCP server, and connect the agent to the local endpoint | No separate equivalent; Fusion itself is the long-lived interactive host |

## Additional Nurb concepts

| Nurb concept | Fusion-native equivalent | Status in this package |
|---|---|---|
| Browser live viewer | Live Fusion canvas plus MCP screenshots | Partial; no second viewer |
| `nurb compare` / target ghost | Fusion mesh comparison where available, external mesh deviation, and separately reported reference-to-envelope conservatism | Partial and release-dependent |
| `@assembly` obstacle/joint sweep | Components, as-built joints/joints, limits, named motion parameters, and task-specific sampled interference | Supported as a workflow; each mechanism needs an explicit sweep variable |
| Shared `system.py` | Shared user parameters, derived/reference components, configurations, and intentionally reused features | Fusion-native |
| Card `Don't` history | Decision log and rejected-option section in `DESIGN-STATE.md` | Supported as a workflow |
| Variants | Fusion Configurations when available, or named parameter sets captured in the manifest and applied one at a time | Partial; no batch variant runner in the host CLI |
| `printer.toml` and global printer profile | Slicer-native machine/material profile plus project handoff metadata | External; do not duplicate a slicer's authoritative profile incompletely |
| STEP/3MF output | Fusion B-Rep/mesh export with exact print-body selection and recorded hashes | Supported when the connected export capability exists |

## Parity boundary

The package deliberately preserves Nurb's high-value discipline—research, provenance, parametric source of truth, separate reference/packing/keep-out geometry, visible iteration, numerical verification, assembly checks, and honest physical-test boundaries—without recreating Nurb's build123d kernel, browser configurator, FDM analyzer, slicer integration, or stress estimator inside Fusion.
