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

Two Claude Code plugin hooks ship with the plugin as mechanical nudges — a
gate on the Fusion execute tool (process-spawning constructs refused;
oversized ad hoc scripts refused unless they carry the shipped lane tooling's
report signature) and a warn-only reminder on ordinary-modeling artifact
writes. They fail open; the doctrine is the cross-harness authority.

## The conditional lanes: automation, release, reconstruction

Everything below this line is lane tooling, activated only by an explicit
request — a repeatable generator or batch run (automation), an evidence-bound
manufacturing handoff (release), or rebuilding a scanned mesh as editable CAD
(reconstruction). None of it runs for ordinary modeling or visual edits. A
lane's machinery is fail-closed by design: manifests declare intent,
generated transactions refuse rather than improvise, and every artifact binds
to the evidence behind it.

### The evidence contract

A lane-managed project keeps `fusion-project.json` (validated against
`schema/fusion-project.schema.json`) recording what geometry alone cannot
explain — sources, provisional dimensions, clearances, forbidden
interferences, the material decision, per-part manufacturing intent — and a
`DESIGN-STATE.md` (from `templates/DESIGN-STATE.md`) as the handoff ledger.
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
scripts/fusion-design plan <manifest>
scripts/fusion-design emit-inventory <manifest> [-o file.py]
scripts/fusion-design emit-parameter-sync <manifest> [-o file.py]
scripts/fusion-design emit-scaffold <manifest> [-o file.py]
scripts/fusion-design emit-document-save <manifest> [--document-id <recorded dataFile id>] [-o file.py]
scripts/fusion-design emit-verification <manifest> [-o file.py]
scripts/fusion-design emit-capability-probe <manifest> [--probe-spec <probe.json>] [-o file.py]
scripts/fusion-design emit-mesh-capture <manifest> [-o file.py]
scripts/fusion-design emit-mesh-face-groups <manifest> --mesh-source-id <id> --classification <classification.json> --face-group-spec <face-groups.json> [-o file.py]
scripts/fusion-design emit-mesh-extract <manifest> --mesh-source-id <id> --classification <classification.json> --extract-spec <extract.json> [-o file.py]
scripts/fusion-design emit-mesh-convert <manifest> --mesh-source-id <id> --classification <classification.json> --convert-spec <convert.json> [-o file.py]
scripts/fusion-design emit-mesh-deviation <manifest> --mesh-source-id <id> --classification <classification.json> --deviation-spec <deviation.json> [-o file.py]
scripts/fusion-design plan-reconstruction <manifest> --fit-record <fit.json> --program-spec <program-spec.json> [-o program.json]
scripts/fusion-design emit-mesh-rebuild <manifest> --mesh-source-id <id> --classification <classification.json> --program <program.json> --rebuild-spec <rebuild.json> [-o file.py]
scripts/fusion-design replan-without <program.json> --refusal <refusal-report.json> [-o program-2.json]
scripts/fusion-design emit-mesh-editability <manifest> --rebuild-record <rebuild-report.json> --editability-spec <editability.json> [-o file.py]
scripts/fusion-design check-editability --rebuild-record <rebuild-report.json> --editability-report <report.json> --editability-nonce <nonce>
scripts/fusion-design reconstruction-coverage <program.json> [--fit-record <fit.json>] [--rebuild-report <rebuild-report.json>] [--editability-verdict <verdict.json>] [-o account.json]
scripts/fusion-design emit-export <manifest> --verification-report <report.json> --verification-nonce <nonce> --export-dir <fusion-host-dir> [--format step|3mf|stl ...] [-o file.py]
scripts/fusion-design plan-variants <manifest> [--export-dir <fusion-host-dir>] [--format step|3mf|stl ...] [--on-failure stop|continue] [--slow-step-seconds N] [--reports-dir DIR] [-o plan.json]
scripts/fusion-design prusaslicer-project <manifest> --export-index <index.json> --output <project.3mf> [--printer NAME] [--filament NAME] [--print NAME] [--config-root DIR] [--slice] [--slicer-executable PATH]
scripts/fusion-design fit-regions <dump> --dump-sha256 <hex> --spec <detection.json> [-o fit-record.json]
scripts/fusion-design diff-reports <before.json> <after.json> [--allow-manifest-change]
scripts/fusion-design prepare-module-bundle <package-dir> <entry-module> [--cache-root DIR]
scripts/fusion-design emit-module-bootstrap <bundle.json> [-o bootstrap.py]
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
report and fails closed on drift; `prusaslicer-project` turns the export index
plus declared manufacturing intent into a real PrusaSlicer project, presets by
identifier and never cloned, and `--slice` runs a real headless slice whose
G-code statistics are reported as produced, never estimated. `plan-variants`
drives a declared product family through per-variant verification with
verified restoration.

### Reconstruction: mesh → editable CAD

The reconstruction lane rebuilds a scanned part as native feature history
under an enforced classification gate, staged as capture → accurate
face-group segmentation → extraction → fitting → planning → one data-driven
rebuild transaction → a measured editability proof → a coverage account with
a closed label set. Every stage refuses rather than approximates, and
`references/mesh-reconstruction.md` is the sole normative contract.
`docs/live-fusion-acceptance.md` carries the live acceptance procedure.

### An example, end to end

`examples/electronics-enclosure/` holds a lane-managed manifest to walk the
machinery: `validate` and `plan` it, emit and run inventory, parameter sync,
scaffold, and verification through the connected MCP, and read the delimited
reports. The example verification fails while the scaffold components are
empty — intentionally: existence is not a substitute for modeled geometry or
fit evidence. The modeling between those transactions is ordinary native
Fusion work, exactly as in the default lane.

## Validation and tests

```bash
./scripts/test.sh
```

The suite runs offline against a stubbed API and covers the manifest
contract, transaction emitters, reconstruction pipeline, and the plugin's
Claude-side hooks; it works from a fresh checkout before any install. The
generated scripts are syntax-checked offline, so run the included example in a
saved, disposable Fusion document before treating a connected Fusion release
as validated — `docs/live-fusion-acceptance.md` has the exact positive and
negative controls.

## Important gaps

The package intentionally does not pretend to supply:

- an independent browser viewer with sliders;
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

See `references/unsupported.md` for the fallbacks, and
`references/capability-status.md` for the full status by lane.

## Credit

The skill's early direction drew inspiration from Josh Pigford's
[nurb](https://github.com/Shpigford/nurb) — with thanks. See
`THIRD_PARTY_NOTICES.md`.
