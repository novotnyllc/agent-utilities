# PrusaSlicer source contract

This reference is pinned to PrusaSlicer **2.9.6**, commit
`b028299c770b8380ee81c921a2867d522f288123`. It records source ownership for
the release lane; it is not a copy of PrusaSlicer algorithms and it does not
make the Python package a `libslic3r` build.

## Ownership map

| Concern | Pinned source areas | Contract for this skill |
|---|---|---|
| CLI actions and profile-query JSON | `src/CLI/ProcessActions.cpp`, `src/CLI/ProfilesSharingUtils.cpp`, `src/libslic3r/PrintConfig.cpp` | The installed executable owns query behavior and output shape for `--query-printer-models` and `--query-print-filament-profiles`. |
| Preset loading and compatibility | `src/libslic3r/PresetBundle.cpp`, `src/libslic3r/Preset.hpp`, `src/libslic3r/PrintConfig.cpp` | Installed presets, inheritance, variants, machine geometry, and print/filament compatibility remain slicer-authoritative. Preserve identifiers exactly as emitted. |
| Project and native 3MF metadata | `src/libslic3r/Format/3mf.cpp`, `src/libslic3r/Format/3mf.hpp`, `src/libslic3r/Model.hpp` | PrusaSlicer owns load/save semantics for transforms, object metadata, layer-height profiles, painted-facet annotations, and native project metadata. See `prusaslicer-3mf-contract.md`. |
| Supports and process semantics | `src/libslic3r/Support/SupportMaterial.cpp`, `src/libslic3r/Support/TreeSupport.cpp`, `src/libslic3r/PrintObject.cpp`, `src/libslic3r/PrintConfig.cpp` | Support generation, flow, walls, infill, and other process behavior are delegated to the selected installed profile and slicer. |
| Tool ordering and wipe behavior | `src/libslic3r/GCode/ToolOrdering.cpp`, `src/libslic3r/GCode/WipeTower.cpp`, `src/libslic3r/GCode/WipeTowerIntegration.cpp` | Tool ordering, wipe structures, and purge behavior are observed from the real slice; they are not reimplemented here. |
| FullSpectrum / virtual extruders | `src/libslic3r/Feature/FullSpectrum/VirtualExtruder.cpp`, `src/libslic3r/Feature/FullSpectrum/VirtualExtruder.hpp`, `src/libslic3r/Format/3mf.cpp` | FullSpectrum and ColorMix metadata are native project semantics, not ordinary config overrides. |
| Arrangement and bed transforms | `src/slic3r-arrange-wrapper/src/ModelArrange.cpp`, arrange-wrapper headers, `resources/data/printer_gantries/` | Native arrangement owns collision-aware transforms and multi-bed behavior. The current adapter performs only its documented deterministic bounding-box layout. |

## Runtime evidence boundary

The package invokes the installed binary through the small process boundary in
`prusaslicer_runtime.py` and records the executable path and SHA-256, detected
version, absolute datadir, deterministic profile-snapshot SHA-256, command kind,
raw exit code/signal, and bounded stderr. The snapshot covers `PrusaSlicer.ini`
and sorted `.ini` files under `printer/`, `print/`, `filament/`, and `vendor/`.
Queries are authoritative only for the pinned 2.9.6 runtime. A changed
executable or snapshot is a terminal `snapshot_changed` result; it never causes
an automatic datadir or parser fallback.

The Python project writer remains process-free. The existing `.ini`/vendor
parser is available only through the explicit `--offline-profiles` mode, which
produces an unsliced, non-installed, non-authoritative result with compatibility
`unknown`.

## What this contract does not grant

Source knowledge does not authorize copied slicer logic, a generated
`PrintConfigDef` catalog, a `libslic3r` dependency, or an empty C++ bridge.
Native metadata is deferred until a version-gated bridge demonstrates
load → save → inspect semantic equality against the pinned PrusaSlicer family.
