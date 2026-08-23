# Fusion Parametric Design Skill

The skill is an expert Fusion user operating Fusion through MCP. Fusion owns
the model, feature history, geometry, inspection, and validation; MCP is
transport carrying small bounded operations, each the equivalent of one
skilled user action. The agent organizes real parts as reusable linked Fusion
components, searches for existing manufacturer CAD, places files in the
correct Fusion project, models directly with native features, asks Fusion for
measurements and interference, and shows the user the result quickly. The
agent never writes its own validation framework.

> **The Fusion document — not Python — is the product and the editable CAD
> source of truth.**

## The ordinary modeling loop

Ordinary work — design this, model this, change this, fix this, make it look
like this — is interactive Fusion operation, and it is the default lane:

- **Data placement first.** Hub, project, and file decided before geometry;
  the working document is named and saved, never left `Untitled`. In this
  lane, Fusion itself is the identity store — the saved document in the Data
  Panel is the durable record.
- **Purchased parts are sourced, not guessed.** Insert Fastener and native
  part sources first, then manufacturer and distributor CAD, into a shared
  linked-component catalog. Fidelity is fitness-for-purpose: a named
  provisional envelope is a legitimate occupancy component, and sourcing never
  delays the visible-result loop.
- **Native features, built and edited directly.** Sketches, extrudes, lofts,
  shells, fillets, holes, patterns, joints — small MCP operations, each one
  visible edit. Joinery is decided and modeled, not proposed, with engineered
  fastener-free joins (snap skirts, ring-snaps, dovetails) as a house
  specialty and adhesive never a default. Wiring is real swept geometry with
  recorded electrical metadata where it matters to the design.
- **Native inspection only.** Measure, Interference, Section Analysis,
  Properties, feature and timeline health — read directly, never wrapped in an
  agent-authored layer. Assembled-fit validation is part of done.
- **The screenshot heartbeat.** Progress is the user seeing the model:
  a capture after every meaningful change, drafts in minutes, hard stop
  conditions and a two-approach attempt budget, the user's judgment steering
  every iteration.
- **Zero artifacts.** Ordinary modeling creates no agent-authored persistent
  host artifact anywhere — no manifests, scripts, reports, or state files.
  The Fusion document and the conversation hold everything.

The full operating rules are `SKILL.md`; the doctrine references beside it
(`references/`) carry design method, data placement and cataloging, add-ins,
material selection, wiring, and capability status.

## Connect Fusion MCP

In Fusion, enable the local MCP server under `Preferences > General > API`.
Autodesk currently documents the default endpoint as:

```text
http://127.0.0.1:27182/mcp
```

If the harness does not already expose a usable Fusion MCP connection, use the
external `roundhouse:mcp-shim` skill to register this endpoint. Install
Roundhouse first only when that skill is absent. Keep Fusion open for live CAD
operations and seed the shim's tool cache once with Fusion's MCP enabled.

Do not encode current MCP tool names in the skill. Autodesk documents dynamic
tooling, so the agent discovers the current schemas at connection time.

Two plugin hooks ship as mechanical nudges, registered by the plugin in both
harnesses — Claude Code and Codex share the hook contract, and both manifests
reference the same `hooks/hooks.json`: a gate on the Fusion execute tool
(process-spawning constructs refused; oversized ad hoc scripts refused unless
they carry the shipped lane tooling's report signature) and a warn-only
reminder on ordinary-modeling artifact writes, riding the Write/Edit tools
where the harness exposes them. They fail open; the doctrine is the
cross-harness authority.

## The conditional lanes: automation and release

Everything below this line is lane tooling, activated only by an explicit
request — a repeatable generator or batch run (automation) or an
evidence-bound manufacturing handoff (release). None of it runs for ordinary
modeling or visual edits. A lane's machinery is fail-closed by design:
manifests declare intent, generated transactions refuse rather than
improvise, and every artifact binds to the evidence behind it.

### The evidence contract

A lane-managed design keeps a manifest — any `*.fusion-project.json`, one per
design, with bare `fusion-project.json` the natural single-design name —
validated against `schema/fusion-project.schema.json` and recording what
geometry alone cannot
explain — sources, provisional dimensions, clearances, forbidden
interferences, the material decision, per-part manufacturing intent — and a
state ledger (from `templates/DESIGN-STATE.md`) as the handoff record — any
`*.design-state.md`, one per design, bare `DESIGN-STATE.md` the natural name
in a single-design directory.
The manifest permits work; it does not create geometry, and the Fusion
document stays editable without it.

### The host CLI

The companion `fusion-design` CLI validates the evidence contract, plans lane
workflows, emits narrow single-purpose Fusion transactions — each bounded,
report-emitting, and designed to refuse rather than improvise — and compares
reports. The self-contained `scripts/fusion-design` wrapper runs from the
installed plugin without any install; for development, Python 3.11+ and
`python3 -m pip install -e .` also work.

Available commands:

```text
scripts/fusion-design validate <manifest>
scripts/fusion-design emit-inventory <manifest> [-o file.py]
scripts/fusion-design emit-parameter-sync <manifest> [-o file.py]
scripts/fusion-design emit-scaffold <manifest> [-o file.py]
scripts/fusion-design emit-document-save <manifest> [--document-id <recorded dataFile id>] [-o file.py]
scripts/fusion-design emit-verification <manifest> [-o file.py]
scripts/fusion-design emit-export <manifest> --verification-report <report.json> --verification-nonce <nonce> --export-dir <fusion-host-dir> [--format step|3mf|stl ...] [-o file.py]
scripts/fusion-design plan-variants <manifest> [--export-dir <fusion-host-dir>] [--format step|3mf|stl ...] [--on-failure stop|continue] [--slow-step-seconds N] [--reports-dir DIR] [-o plan.json]
scripts/fusion-design prusaslicer-project <manifest> --export-index <index.json> --output <project.3mf> [--printer NAME] [--filament NAME] [--print NAME] [--config-root DIR] [--slice] [--slicer-executable PATH] [--offline-profiles]
scripts/fusion-design prusaslicer-optimize <manifest> --export-index <index.json> [--intent fast-structural|fine-detail|enclosure] [--printer NAME] [--filament NAME] [--print NAME] [--config-root DIR] [--datadir DIR] [--slicer-executable PATH] [--gcode-format binary|ascii]
scripts/fusion-design prusaslicer-profiles --config-root DIR [--printer NAME] [--slicer-executable PATH]
scripts/fusion-design diff-reports <before.json> <after.json> [--allow-manifest-change]
scripts/fusion-design prepare-module-bundle <package-dir> <entry-module> [--cache-root DIR]
scripts/fusion-design emit-module-bootstrap <bundle.json> [-o bootstrap.py]
scripts/fusion-design enclosure-addin-status
scripts/fusion-design install-enclosure-addin --target <absolute-add-in-dir> [--force]
```

Generated transactions print delimited JSON reports to stdout and tee them
beside their inputs for transport-timeout recovery; the exact report protocol,
module-bundle contract, and units boundary are in
`references/mcp-adapter.md`. `emit-verification` mints a single-use nonce that
`emit-export` requires, so an export binds only to a report produced by
actually running the emitted verification — the full chain manifest →
verification → export → PrusaSlicer project → slice is described in
`references/verification-contract.md`.

### Release: verified export and slicing

`emit-export` re-measures each printable part against its passing verification
report and fails closed on drift. `prusaslicer-profiles` queries the installed
PrusaSlicer 2.9.6 runtime and reports exact profile identifiers plus executable
and datadir fingerprints; `prusaslicer-project` consumes that authoritative
inventory, keeps profiles by identifier, and fails closed on bed-footprint or
height overflow. `--offline-profiles` is an explicit non-installed,
non-authoritative, unsliced fallback only. `--slice` runs a real headless slice
whose G-code statistics and conservative tool audit are reported as produced,
never estimated. Native painted facets, variable layer heights, FullSpectrum,
and arrangement metadata remain deferred until a version-gated native bridge
proves semantic round-trip equality. `plan-variants` drives a declared product
family through per-variant verification with verified restoration.

### An example, end to end

`examples/electronics-enclosure/` holds a lane-managed manifest to walk the
machinery: `validate` it, then emit and run inventory, parameter sync,
scaffold, and verification through the connected MCP, and read the delimited
reports. The example verification fails while the scaffold components are
empty — intentionally: existence is not a substitute for modeled geometry or
fit evidence. The modeling between those transactions is ordinary native
Fusion work, exactly as in the default lane.

## Validation and tests

```bash
./scripts/test.sh
```

The no-argument form is the full release gate: the suite runs offline against
a stubbed API and covers the manifest contract, transaction emitters,
the plugin's plugin hooks; it works from a fresh checkout before any install.
To run one area during an edit loop, name its module fragment (underscores;
hyphens are accepted):

```bash
./scripts/test.sh manifest cli        # several areas
```

Filtered runs skip the syntax check and hook tests — those are release-gate
stages, so run the full form before committing. The
generated scripts are syntax-checked offline, so run the included example in a
saved, disposable Fusion document before treating a connected Fusion release
as validated — `docs/live-fusion-acceptance.md` has the exact live controls.

## Important gaps

The package intentionally does not pretend to supply:

- an independent browser viewer with sliders;
- a complete FDM wall/overhang/support checker;
- slicer-independent time or filament estimates (the PrusaSlicer adapter reports what a real slice produced; nothing is estimated without one);
- trustworthy one-button FDM load ratings;
- general semantic B-Rep or feature-history diffing;
- automatic joint-range sweeps without a mechanism-specific motion variable;
- a batch runner for all Fusion configurations/variants;
- an automatic skill updater or separate development launcher;
- a duplicate approximation of the slicer's authoritative printer/material profile;
- a bundled headless renderer and report compositor.

See `references/unsupported.md` for the fallbacks, and
`references/capability-status.md` for the full status by lane.
