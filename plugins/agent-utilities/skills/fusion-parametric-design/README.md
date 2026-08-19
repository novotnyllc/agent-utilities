# Fusion Parametric Design Skill

A Fusion-native adaptation of the strongest workflow disciplines in Nurb: research before geometry, explicit measurement provenance, editable parameters, reference and packing models, functional keep-outs, numerical inspection, assembly verification, print-aware handoff, and honest unsupported-capability boundaries.

The central difference is architectural:

> **The Fusion document—not generated Python—is the editable CAD source of truth.**

Python emitted by this package is limited to small, idempotent transactions that inventory the document, synchronize user parameters, ensure the component scaffold, or run verification. Product geometry should live as ordinary Fusion sketches, constraints, features, components, joints, and configurations.

Project-specific geometry transactions are intentionally created against the connected Fusion release and its current API documentation; the host CLI does not ship a generic sketch/extrude generator that would become a second CAD source of truth.

## Package contents

```text
SKILL.md
references/
src/fusion_design/                 host-side manifest and script tooling
schema/fusion-project.schema.json
examples/electronics-enclosure/
templates/DESIGN-STATE.md
tests/
docs/
```

## What it preserves from the Nurb approach

- research and source provenance before fit-dependent design;
- a distinction between visual observation and dimensional proof;
- plain-language parameters;
- scans and downloaded meshes treated as evidence rather than recovered design intent;
- assemblies and obstacles checked together;
- fit coupons for provisional geometry;
- numerical checks and explicit handoff state;
- print cost/safety claims separated from what the CAD kernel can actually prove.

## What changes for Fusion

- User parameters and feature expressions replace Python keyword defaults.
- The Fusion timeline and component tree replace regenerated part functions.
- Fusion attributes retain source and managed-entity metadata.
- `REF__`, `PACK__`, and `KEEP__` components separate editable reference geometry, physical occupancy, and functional space.
- Fusion's measurement and interference APIs provide packing evidence.
- MCP scripts are discovered dynamically and used as short transactions.
- Print analysis remains external where Fusion does not provide an equivalent; slicing is delegated to PrusaSlicer through an opt-in adapter that reports the G-code's own statistics.

## Install the host tooling

Python 3.11 or later is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
```

The self-contained `scripts/fusion-design` wrapper is the preferred entrypoint
when this skill is installed as a plugin; it uses the bundled source tree and
does not require an editable install.

Available commands:

```text
scripts/fusion-design validate <manifest>
scripts/fusion-design plan <manifest>
scripts/fusion-design emit-inventory <manifest> [-o file.py]
scripts/fusion-design emit-parameter-sync <manifest> [-o file.py]
scripts/fusion-design emit-scaffold <manifest> [-o file.py]
scripts/fusion-design emit-verification <manifest> [-o file.py]
scripts/fusion-design emit-export <manifest> --verification-report <report.json> --verification-nonce <nonce> --export-dir <fusion-host-dir> [--format step|3mf|stl ...] [-o file.py]
scripts/fusion-design plan-variants <manifest> [--export-dir <fusion-host-dir>] [--format step|3mf|stl ...] [--on-failure stop|continue] [--slow-step-seconds N] [--reports-dir DIR] [-o plan.json]
scripts/fusion-design prusaslicer-project <manifest> --export-index <index.json> --output <project.3mf> [--printer NAME] [--filament NAME] [--print NAME] [--config-root DIR] [--slice] [--slicer-executable PATH]
scripts/fusion-design diff-reports <before.json> <after.json> [--allow-manifest-change]
scripts/fusion-design prepare-module-bundle <package-dir> <entry-module> [--cache-root DIR]
scripts/fusion-design emit-module-bootstrap <bundle.json> [-o bootstrap.py]
```

For reusable pure-Python helpers, prepare a content-addressed module bundle and
send the verified emitted bootstrap through Fusion's Python-execution
capability. The persistent cache is outside project repositories: on macOS it
defaults to `~/Library/Caches/fusion-parametric-design/mcp-modules`, and on
other POSIX systems to `$XDG_CACHE_HOME` or `~/.cache`. Set
`FUSION_MCP_MODULE_CACHE` to an absolute path to override it. The cache requires
POSIX owner/permission semantics and fails closed on native Windows. Bundles
accept regular `.py` files only; install native or third-party dependencies in
the host environment and pass only their results into Fusion.

Generated transactions print one delimited JSON report to stdout. Preflight
the Fusion execution capability with a unique sentinel and stop if the exact
sentinel is absent; an empty success response is not execution proof.

## Connect Fusion MCP

In Fusion, enable the local MCP server under `Preferences > General > API`. Autodesk currently documents the default endpoint as:

```text
http://127.0.0.1:27182/mcp
```

If the harness does not already expose a usable Fusion MCP connection, use
the external `roundhouse:mcp-shim` skill to register this endpoint. Install
Roundhouse first only when that skill is absent. Keep Fusion open for live CAD
operations and seed the shim's tool cache once with Fusion's MCP enabled.

Do not encode current MCP tool names in the skill. Autodesk documents dynamic tooling, so the agent must discover the current schemas at connection time.

## First workflow

```bash
./scripts/fusion-design validate examples/electronics-enclosure/fusion-project.json
./scripts/fusion-design plan examples/electronics-enclosure/fusion-project.json
./scripts/fusion-design emit-inventory examples/electronics-enclosure/fusion-project.json -o build/inventory.py
./scripts/fusion-design emit-parameter-sync examples/electronics-enclosure/fusion-project.json -o build/sync-parameters.py
./scripts/fusion-design emit-scaffold examples/electronics-enclosure/fusion-project.json -o build/scaffold.py
./scripts/fusion-design emit-verification examples/electronics-enclosure/fusion-project.json -o build/verify.py
cp templates/DESIGN-STATE.md DESIGN-STATE.md
```

Then, through the connected Fusion MCP:

1. run `inventory.py` using the discovered Python-execution capability;
2. save/version the document;
3. run `sync-parameters.py`;
4. run `scaffold.py`;
5. create the native Fusion reference and product feature groups;
6. run `verify.py` after the packing and product components contain geometry;
7. capture the delimited JSON reports and viewport images.

`emit-verification` prints a single-use nonce on stderr and embeds it in the script it emits. Keep it: `emit-export` requires that nonce, and only the report produced by running that script carries it, so an export cannot be bound to a report that never ran.

The example verification script will initially fail because the scaffold components are empty. That is intentional: existence is not a substitute for modeled geometry or fit evidence.

## Electronics packing model

Each installed object has both:

- an **editable authoring model** (`REF__...`) for dimensions, datums, mounting holes, and connector centers;
- an **exact or conservative packing model** (`PACK__...`) for occupancy, including a checkable B-Rep envelope for automated clash checks even when an exact mesh is also retained;
- one or more **functional keep-outs** (`KEEP__...`) for cable departure, insertion, service, thermal, RF, acoustic, or tool space. A genuinely keep-out-free datum/reference must carry an explicit rationale instead of an empty omission.

This directly addresses the common enclosure failure where a board fits but its plugs, wires, levers, fasteners, or removal path do not.

## Validation and tests

```bash
./scripts/test.sh
```

The helper sets the repository's `src/` layout explicitly, so it works from a
fresh checkout before an editable install. After `python3 -m pip install -e .`,
the same suite can also be run directly with `python3 -m unittest discover -s tests -v`.

The host tooling is tested offline. The generated scripts are syntax-checked, but this package was not executed against a live Fusion MCP session in the build environment. Run the included example in a saved, disposable Fusion document first and adjust only where the connected Fusion release's dynamically discovered API contract differs.

Use `docs/live-fusion-acceptance.md` for the exact positive and negative controls required before treating a connected Fusion release as validated.

## Important gaps

The package intentionally does not pretend to supply:

- a Nurb-style independent browser viewer with sliders;
- a complete FDM wall/overhang/support checker;
- slicer-independent time or filament estimates (the PrusaSlicer adapter reports what a real slice produced; nothing is estimated without one);
- trustworthy one-button FDM load ratings;
- automatic scan-to-parametric reconstruction;
- general semantic B-Rep or feature-history diffing;
- automatic joint-range sweeps without a mechanism-specific motion variable;
- a batch runner for all Fusion configurations/variants;
- an automatic skill updater or separate development launcher;
- a duplicate approximation of the slicer's authoritative printer/material profile;
- a bundled headless renderer and report compositor.

See `references/unsupported.md` for recommended fallbacks.

## Attribution

This is an independent implementation inspired by the publicly documented design workflow in [Shpigford/nurb](https://github.com/Shpigford/nurb). It does not include Nurb source code. See `THIRD_PARTY_NOTICES.md`.
