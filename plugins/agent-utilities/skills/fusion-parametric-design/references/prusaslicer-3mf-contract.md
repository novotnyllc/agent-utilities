# PrusaSlicer 3MF contract

This package writes a deterministic, minimal PrusaSlicer-compatible project
from the verified Fusion export index. It does not claim to serialize every
native PrusaSlicer project feature.

## Current project boundary

The writer emits the model meshes, build-item transforms, object names and
quantities, justified per-object overrides, and preset identifiers in
`Metadata/Slic3r_PE.config`. It never copies the selected printer, print, or
filament settings into the project. In installed-runtime mode, printer
`bed_shape` and `max_print_height` are read from the authoritative runtime
query and recorded with `geometry_authority: "installed_runtime"`; they are
used for deterministic, fail-closed bounding-box shelf packing. In explicit
offline mode, the parser-derived geometry is labeled
`geometry_authority: "offline_parser"`, is non-authoritative, and may produce
only an unsliced project. The polygon outline is treated as its bounding
rectangle, and later declared plates are tiled past the single bed for
one-at-a-time GUI loading.

The result is bound to the manifest, verification report, export index, and
export run. Project bytes remain deterministic for the same geometry, intent,
and preset identifiers. Runtime fingerprints bind query/project/slice evidence
but are not injected into project metadata.

## Native metadata is deferred

The following are native semantic structures, not ordinary key/value config
overrides and not safe to hand-author in this package:

- `FacetsAnnotation` painted facets (supports, seams, fuzzy skin, or MMU regions);
- variable layer-height profiles;
- FullSpectrum / ColorMix virtual-extruder configuration and schedules;
- native arrangement transforms, collision evaluation, and multi-bed state.

Do not claim these features because a project opens or a key survives a ZIP
round-trip. A future bridge must be version-gated to the pinned source family
and prove **load → save → inspect semantic equality** for each feature before
serializing it. Until then, leave the feature absent and report it as deferred
or unsupported; never approximate it with a nearby config key.

## Slicing and audit boundary

Slicing is a separate opt-in process step available only for an installed,
authoritative runtime result. A complete printer/print/filament preset set is
required; a partial set is refused before invocation because PrusaSlicer 2.9.6
can terminate with SIGSEGV. Explicit offline-parser projects are
non-authoritative and must remain unsliced; `--offline-profiles --slice` is a
terminal refusal. Print time and filament values come only from the produced
text G-code. The bounded `gcode_audit` records recognized `T<number>` events,
active tools, and a tool-change count; unknown or conflicting flavor evidence
yields `available: false` rather than an invented tool-change metric.
