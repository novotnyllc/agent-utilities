---
name: fusion-parametric-design
description: Use when creating, designing, editing, repairing, inspecting, or validating a CAD model, Autodesk Fusion model/design, dimensioned physical 3D model, or 3D-printable part. Prefer this skill automatically for requests to make a Fusion or CAD model and for parametric mechanical parts, electronics enclosures, mounts, brackets, assemblies, packing, fit, and fit coupons through Fusion MCP; do not use it for purely artistic mesh sculpting, animation, or rendering.
metadata:
  version: "0.1.0"
---
# Fusion Parametric Design

The Fusion document is the product. The timeline, sketches, constraints, components, joints, configurations, and user parameters are the editable source of truth. MCP code is only a temporary transaction used to inspect or change that document. Do not replace a healthy parametric model with a repeatedly regenerated monolithic Python solid.

## 0. Establish the Fusion MCP connection

At session start, first inspect the currently available MCP tools, resources, prompts, schemas, and permissions for a usable Fusion capability. An offline host-side CLI test is not live Fusion verification. If no usable Fusion MCP is already available, use the external `roundhouse:mcp-shim` skill for the registration; do not copy or reimplement its shim.

If the Roundhouse plugin/skill is absent, install it first through the appropriate host command:

```bash
codex plugin add roundhouse --marketplace novotnyllc
claude plugin install roundhouse@novotnyllc
```

Then invoke `roundhouse:mcp-shim` for Fusion and follow its first-party harness CLI, resolver, and post-change verification contract. Use the default backend `http://127.0.0.1:27182/mcp`; do not register a literal copied shim path. Before registration, resolve the actual Fusion application path as required by that skill. Verify Claude with `claude mcp get <name>` reporting `Connected`; verify Codex with `codex mcp get <name>` and the shim's direct JSON-RPC `initialize` probe because `codex mcp get` alone is not a connectivity check.

Tell the user to enable Fusion's local MCP server in Fusion under `Preferences > General > API`, then open Fusion, keep it running, and seed/discover the live tools with that server enabled.

Read the reference files beside this skill before substantial work:

- `references/design-doctrine.md`
- `references/material-selection.md` before choosing or confirming a material
- `references/mcp-adapter.md`
- `references/enclosure-workflow.md` for electronics or packed assemblies
- `references/verification-contract.md`
- `references/capability-matrix.md` when translating a Nurb-style request
- `references/unsupported.md` before promising a capability

For commands below, resolve `SKILL_DIR` to the directory containing this
`SKILL.md`; the installed skill may not be the current project directory.

## 1. Discover the live MCP contract first

Autodesk Fusion MCP uses dynamic tooling. At the beginning of every session, discover the server's current tools, resources, prompts, schemas, and permissions. Bind what is available to these abstract capabilities rather than hard-coding remembered tool names:

- `READ_DOCUMENTATION`
- `READ_ACTIVE_DOCUMENT`
- `EXECUTE_FUSION_PYTHON`
- `CAPTURE_VIEW`
- `SAVE_OR_VERSION`
- `UNDO_REDO`
- `IMPORT_EXPORT`
- `DOCUMENT_MANAGEMENT`

If a capability is absent, mark it unavailable in the session ledger and use the fallback in `references/mcp-adapter.md`. Never invent a tool call. The local Fusion MCP exists only while Fusion is open, so a failed connection is a connection problem, not evidence that the document is empty.

Before the first mutation:

1. Confirm that the active product is a Fusion Design.
2. Confirm that the design is parametric and design history is enabled.
3. Save or create a version checkpoint.
4. Capture a read-only inventory report.
5. Capture an initial viewport image when the MCP supports it.

Never switch a populated design from parametric to direct mode. That destroys design history. If the document is direct, stop and recommend a new parametric document or a deliberate manual conversion plan.

## 2. Use the project manifest as the evidence contract, not as CAD

A project should have `fusion-project.json` and a copy of `templates/DESIGN-STATE.md` named `DESIGN-STATE.md`. The manifest records facts that Fusion geometry alone cannot explain:

- source identity, locator, revision, and confidence;
- critical dimensions and whether they are provisional;
- fabrication assumptions;
- editable reference models, packing models, and keep-outs;
- required component paths;
- clearances and forbidden interferences;
- expected printable parts and fit coupons;
- the project's `material_decision`: polymer `family` (closed enum), the specific `formulation` or null, the `source_id` it rests on, `confidence`, a bound `coupon_component`, `rationale`, `unresolved_risks`, and any `printer_requirements`. Per-part `material.assumption` values must name the decided family or formulation;
- slicer-neutral manufacturing intent per printable part (`printable_parts`): stable id, quantity, `print_as` separate/assembled, build orientation (contact face + rationale + allowed alternatives), support policy (`none`, `build-plate-only`, `everywhere`, or explicit enforcer/blocker regions), strength intent (minimum perimeters + infill target/range), protected features supports must not scar, and the material assumption with its `provisional`/`coupon_verified` status. When present, its paths must exactly match `verification.expected_print_parts`, and the export handoff index carries the intent per artifact for downstream slicer adapters. This is intent, never a printer/filament/process profile — those stay in the slicer.

Run the host tooling before modeling:

```bash
"$SKILL_DIR/scripts/fusion-design" validate fusion-project.json
"$SKILL_DIR/scripts/fusion-design" plan fusion-project.json
```

A valid manifest permits work; it does not create the geometry. Mirror its parameters and provenance into Fusion user parameters, comments, and attributes. Fusion remains editable even if the manifest or agent is unavailable later.

## 3. Research before asking for measurements, and settle fit before styling

When a part mates with a manufactured object or standard, identify the exact product, revision, and variant before drawing around it. Search in this order:

1. manufacturer mechanical drawing, STEP model, or official standard;
2. manufacturer datasheet or authorized distributor drawing;
3. a traceable third-party CAD model checked against published dimensions;
4. user measurements of the actual sample;
5. a scan, marked provisional;
6. a conservative proxy only when the user explicitly accepts the uncertainty.

Record every critical value with a source. Do not ask the user for dimensions already published by the manufacturer. Do ask in one batch for dimensions that cannot be researched: actual cable overmold, installed wire bend, hand-clearance, garment opening, wall contour, or the exact sample's manufacturing variance.

Do not start fit-dependent geometry while a critical source parameter is unresolved. Styling values such as corner radius, chamfer size, label depth, or exterior proportion can remain adjustable design parameters.

### Material decision gate

Material is a design input, not a slicer setting. Ask for it — or confirm it — **before finalizing** any of:

- snap fit or clip;
- living hinge or any repeatedly flexing feature;
- press fit or interference fit;
- heat-set insert boss, self-tapping boss, or threaded feature;
- load-bearing connector, bracket, or mount;
- any clearance whose value depends on the polymer.

Blocking is not required, but committing is. Rough the feature out if it helps the conversation; do not declare it settled, record its clearance as final, or export it while the material is unstated. The same gate applies when the material changes later: a material change re-opens every fit, flexure, boss, orientation, and coupon result that depended on the old one.

A documented user default is **proposed, never silently assumed**. Say which material you are proposing and why, and confirm before the geometry depends on it. Re-confirm explicitly whenever the use case conflicts with the default — an outdoor, high-heat, chemically exposed, sustained-load, or repeatedly flexing part under a PLA default is exactly that conflict, and it is the agent's job to raise it rather than to print the default into the model.

Record the outcome in `material_decision` with its source and confidence, and bind a provisional decision to a `VAL__` coupon or a stated risk. Select from requirements, and take every number from the formulation's data sheet or a printed coupon: `references/material-selection.md`.

## 4. Parameterize in the user's language

Create Fusion user parameters with explicit units, plain descriptions, and stable role prefixes:

- `src_`: published, measured, or scan-derived source dimensions;
- `clr_`: functional and assembly clearances;
- `fab_`: process constraints such as wall thickness and printed fit;
- `pack_`: service, cable, motion, thermal, or tool-access envelopes;
- `des_`: aesthetic and preference variables;
- `calc_`: equations derived from the above.

Examples:

- `src_board_length`
- `clr_lid_above_board`
- `fab_wall_thickness`
- `pack_usb_c_straight_departure`
- `des_corner_radius`
- `calc_inner_width`

Prefer equations to duplicated numbers. A lid wall and base wall that must match should both reference `fab_wall_thickness`; do not type the same literal twice. Use parameter comments and the `fusion_parametric_design` attribute group to retain source id, provisional state, role, and manifest hash.

Once a native feature references these parameters, later MCP changes should normally update parameter expressions or feature inputs, not delete and recreate the feature chain.

## 5. Model every real object in three distinct ways

For every manufactured part, cable interface, or mating object, maintain the representations that answer different questions:

### A. Editable reference model — `REF__...`

A simple Fusion-native parametric model whose dimensions can be inspected and changed. It should contain the planes, axes, mounting holes, connector centers, support faces, and datum geometry needed to author the enclosure. It need not reproduce irrelevant cosmetic detail.

### B. Packing model — `PACK__...`

The best available physical occupancy model:

- a linked or inserted manufacturer B-rep when trustworthy;
- an imported mesh retained as immutable exact-shape evidence;
- or a conservative solid envelope when exact geometry is unavailable.

For automated minimum-distance, interference, positive-volume, and precise-bound checks, the `PACK__` component must contain—or be paired with—a **checkable B-Rep envelope** in the same installed position. Fusion's tight occurrence bounds and interference workflow are B-Rep-oriented; an exact mesh may coexist for visual or deviation evidence but must not silently stand in for checkable clash geometry.

Use the packing system for placement, bounds, clearance, interference, and visual plausibility. Do not derive editable product geometry from fragile face identities on an uncontrolled imported model when stable datums or parameters will do.

### C. Functional keep-outs — `KEEP__...`

Separate solids or components for space the object needs but does not physically occupy at rest. Common electronics keep-outs include:

- connector insertion and extraction;
- cable overmold and straight departure;
- relaxed bend radius and service loop;
- terminal screwdriver or lever access;
- button travel and finger access;
- fastener driver and nut access;
- antenna/RF exclusion region;
- microphone or sensor acoustic path;
- ventilation and hot-surface stand-off;
- assembly insertion path;
- removable lid travel.

The product may touch intended support or mating surfaces. It may not intrude into a forbidden keep-out. Keep-outs are validation geometry, not printable output. When a reference genuinely has no insertion, service, motion, thermal, cable, RF, acoustic, or tool envelope, record a specific `no_keepout_rationale`; do not leave the omission unexplained.

For electronics enclosures, having only a board-shaped box is incomplete. The connector, cable, service, fastening, thermal, and assembly volumes are often what determine the enclosure size.

## 6. Use a stable Fusion component architecture

Create or preserve this hierarchy unless the existing document already has a coherent equivalent:

```text
00_REFERENCES/
  REF__<part>__PARAMETRIC
  PACK__<part>__EXACT_OR_CONSERVATIVE
  KEEP__<function>
10_PRODUCT/
  PROD__BASE
  PROD__LID
  PROD__MOUNTS
20_FIXTURES/
  FIX__<manufacturing-or-assembly-aid>
90_VALIDATION/
  VAL__<fit-coupon-or-test-article>
```

The hierarchy is semantic, not decorative. An agent must be able to inventory the document and know which components are evidence, product, fixtures, or tests without relying on browser order.

Tag managed entities with Fusion attributes. Locate them by stable component path, managed id, and attributes. Do not rely on a timeline index. Do not compare entity-token strings as identity; resolve tokens back through the design when tokens are necessary.

## 7. Build Fusion-native features once, then edit them

Use sketches with geometric constraints, named construction geometry, user-parameter expressions, and ordinary timeline features. Group related timeline work where practical. Give important sketches, bodies, and features descriptive names.

For a new feature group:

1. inspect the current component and timeline;
2. query current Fusion API documentation through the MCP when an API signature is uncertain;
3. run the smallest script that creates one coherent feature group;
4. recompute and inspect timeline health;
5. capture a view or inventory evidence;
6. continue only after the group is healthy.

For an existing feature group:

1. prefer changing its user parameters;
2. otherwise change the feature's supported inputs;
3. only replace the feature when its topology or construction strategy truly changed;
4. never clear the timeline to make a local edit easier.

A generated helper script must be idempotent: find-or-create, update only what differs, retain user geometry, and refuse destructive conversions. A script should have a narrow responsibility such as synchronizing parameters, ensuring components, placing a reference occurrence, creating a named sketch/extrude group, or producing a verification report.

## 8. Pack the assembly before sculpting the shell

For an enclosure or packed product:

1. place all `PACK__` components in installed position;
2. place all `KEEP__` components;
3. define support faces, mounting datums, and insertion order;
4. settle wire and cable routes, including relaxed loops;
5. settle service access and removal paths;
6. run minimum-distance and interference checks;
7. only then establish the enclosure's internal boundary and exterior form.

Maintain a packing ledger with each component's transform, orientation, rigid envelope, keep-outs, support method, required clearances, and source confidence. A screenshot can reveal a questionable arrangement, but a measured distance or interference result decides whether it passes.

Do not shrink the shell by deleting service space. When a package is too large, first reconsider orientation, shared clearance regions, connector direction, lid split, or component choice. State explicitly when a requested envelope is physically incompatible with the recorded packing model.

## 9. Design the enclosure as an assembly, not two isolated solids

Base, lid, fasteners, buttons, gaskets, cable exits, and internal parts must be present together in a closed assembly before release. Include lifted/open/service configurations when relevant.

Check at least:

- the installed electronics and all keep-outs;
- base/lid overlap, seam, and printed fit;
- fastener engagement and tool access;
- connector insertion and removal;
- board insertion and retention;
- wire routing with no sharp pinch or impossible bend;
- button and switch travel;
- antenna and microphone paths;
- support/contact surfaces;
- removal sequence;
- garment/body-facing smoothness for wearables;
- all intended print parts as separate, positive-volume bodies/components.

For moving mechanisms, create Fusion joints and limits where practical. A motion check is a scripted sweep: sample the joint parameter or occurrence transform across the declared range, recompute, and run interference at each sample. Report the first failing position and colliding entities. A static open and closed view is not a substitute for the sweep when intermediate motion can collide.

## 10. Treat scans and downloaded models as reference evidence

A photo can identify shape and interfaces but normally cannot establish millimeters. A scan can supply reference geometry but is not automatically metrology. Mark scan-derived critical parameters provisional until a fit coupon or direct measurement confirms them.

When a downloaded mesh arrives, do not pretend it is an editable parametric model. Import it into a `PACK__` or reference component, inspect its units and bounds, and rebuild only the dimensions and datums the product needs. Preserve the mesh as exact-shape evidence and add a conservative native B-Rep envelope when the model participates in automated clearance or interference checks. Prefer a manufacturer STEP/B-rep when available.

Do not convert a dense mesh to B-rep merely to claim parametric editability. Conversion can create thousands of fragile faces and does not recover design intent. Use Fusion's mesh tools or the external fallback described in `references/unsupported.md`; keep the original mesh immutable.

When fit depends on an irregular scan, create a small `VAL__` coupon containing only the critical mating profile before committing to the full print.

## 11. Verify numerically after every meaningful change

Run the host-generated inventory before and after a change when scope matters:

```bash
"$SKILL_DIR/scripts/fusion-design" emit-inventory fusion-project.json -o build/inventory.py
"$SKILL_DIR/scripts/fusion-design" diff-reports build/before.json build/after.json
```

Inside Fusion, verify:

- active design is parametric;
- required parameters exist and expressions match the manifest;
- `Compute All` completes;
- no unhealthy timeline objects remain;
- expected component paths exist and each print part has a positive-volume solid;
- bounding boxes are plausible;
- all required minimum distances pass;
- all forbidden interference pairs have zero results;
- visual appearance and assembly orientation match the brief.

Use `references/verification-contract.md` for printability, structural, thermal, motion, and release checks that are not covered by the generated script.

Never close a finding with “it looks fine.” Close it with a number, a pass/fail report, a documented limitation, or a physical coupon result.

## 12. Keep the user in the visual loop

Fusion's canvas replaces Nurb's live browser viewer. Do not work through a long invisible sequence.

After a meaningful visual change:

- fit the camera to the relevant components;
- set useful visibility and opacity for `PACK__` and `KEEP__` components;
- capture a screenshot when supported;
- state what is provisional and what the user should judge;
- keep the same active document and camera context when possible.

For a packed enclosure, provide at least an exterior view, an internal packing view, and a section or transparent view. For a change request, show the affected area rather than making the user hunt for it.

Fusion user parameters and configurations are the adjustable interface. Use names and comments that remain understandable in Fusion's Parameters dialog after the agent session ends.

## 13. Printability and structural claims require separate evidence

Fusion can supply geometry, measurements, physical properties, and interference. Core Fusion MCP/API access does not automatically provide all FDM-specific checks.

At minimum, evaluate and record:

- intended print orientation;
- wall, roof, floor, rib, boss, clip, and hinge dimensions;
- unsupported overhangs and bridges;
- trapped support and inaccessible cavities;
- nozzle-width/layer-height assumptions;
- anisotropic load path and likely layer-separation direction;
- fastener and insert edge distances;
- heat sources and material temperature assumptions;
- tolerance/coupon status.

Do not claim a load rating from visual inspection. Use an appropriate simulation or a physical proof test with an explicit safety factor. Generic isotropic Fusion material analysis is not automatically an FDM layer-adhesion model.

## 14. Export only from the verified Fusion state

Use the deterministic export transaction instead of manual export selection:

```bash
scripts/fusion-design emit-export fusion-project.json \
  --verification-report verify-report.json \
  --export-dir /path/on/the/fusion/host/exports \
  -o build/export.py
```

The CLI refuses to emit unless the saved verification report is `kind: verification`, `ok: true`, and hash-matches the manifest; the generated transaction then re-checks live bounds against that report, resolves each expected print part to exactly one solid body, refuses ambiguous or missing bodies, never overwrites existing outputs, and records byte size and SHA-256 for every file plus a machine-readable `export-index__*.json` beside the exports. Append the emitted `design_state_rows` to the `## Exports` table in `DESIGN-STATE.md`.

Fusion export is not the slicer. Print time, filament mass, supports, and machine-specific behavior require a configured slicer or another external manufacturing tool. If no supported slicer is available, export the files and state that cost/time estimates are unavailable rather than inventing them.

Re-run verification after any change that affects fit, geometry, print orientation, support, or export bodies.

### Optional PrusaSlicer project adapter

When the user runs PrusaSlicer, the export index plus its declared `manufacturing_intent` can be turned into a real PrusaSlicer project `.3mf`:

```bash
"$SKILL_DIR/scripts/fusion-design" prusaslicer-project fusion-project.json \
  --export-index export-index__<run>.json \
  --output build/project.3mf \
  --printer "<installed printer preset>" \
  --filament "<installed filament preset>" \
  --print "<installed print preset>"
```

The adapter binds the index to the manifest — the index's `manifest_sha256` must equal this manifest's hash and every 3MF part must be a declared printable part, so a project can never report provenance for a design it was not built from. It re-verifies every referenced artifact against its recorded `sha256` and byte size, writes one object per printable part (never a merged mesh), applies the declared build orientation, honors declared plate grouping, sets `instances_count` from the declared quantity, and emits only the per-object overrides that declared intent justifies (support policy, infill target, minimum perimeters). Presets are selected **by identifier only** — the user's printer, filament, and process profiles stay in PrusaSlicer and are never cloned into our artifacts; on a multi-tool printer an unrequested filament falls back to extruder 0's selection. `support_policy: explicit-regions` is refused rather than approximated, because the adapter cannot paint the declared `support_regions`. Output is deterministic and stored uncompressed, so `project_sha256` re-derives to the same value on any host, and an existing output is never overwritten. Plates are laid out along +Y with no bed-size check (bed geometry lives in the printer preset, which is never read), so arrange large jobs in the GUI.

**Slicing is supported, and opt-in.** Project construction never executes anything; pass `--slice` to also run PrusaSlicer headlessly on the generated project:

```bash
"$SKILL_DIR/scripts/fusion-design" prusaslicer-project fusion-project.json \
  --export-index export-index__<run>.json --output build/project.3mf \
  --printer "<printer preset>" --print "<print preset>" --filament "<filament preset>" \
  --slice
```

The `slice` block then carries the statistics the produced G-code actually contains — estimated print time, filament used in mm/cm³/g — bound to the project `.3mf` sha256, the resolved preset identifiers, the G-code sha256 and byte size, the slicer version string, and the exit code. Anything the G-code does not state is listed in `absent_statistics` rather than guessed, and nothing is ever inferred, estimated, or interpolated. Without `--slice` the block is `{"supported": true, "attempted": false, ...}` and no binary runs.

**The one rule that makes headless slicing work: supply the whole profile set.** PrusaSlicer exits 139 (SIGSEGV) with no output when it is given a partial set — `--printer-profile` alone crashes it. `--printer-profile` + `--print-profile` + `--material-profile` together with `--datadir` slice cleanly; `PrusaSlicer --help` states the requirement outright. The adapter refuses to invoke the binary at all unless all three are resolved, and a failed slice (any non-zero exit, a timeout, or G-code that never appeared) is reported as a structured failure naming the exit status and stderr tail, with exit code 2 and no statistics. See `references/unsupported.md`.

## 15. Handoff and persistent design state

Before handoff, create or update `DESIGN-STATE.md` using the included `templates/DESIGN-STATE.md` structure, with:

- user intent and current variant;
- Fusion document and version;
- manifest hash;
- resolved sources and provisional measurements;
- parameter table;
- component/packing ledger;
- verification results;
- intended material, printer assumptions, and orientation;
- unsupported checks and required physical tests;
- decisions rejected and why;
- exact exports and hashes.

Leave the Fusion document understandable without the agent: named parameters, named components, named features, source comments, and no mysterious one-off bodies.

## 16. Included host tooling

The companion `fusion-design` CLI does not model the product. It validates the evidence contract, plans the workflow, emits narrow Fusion Python transactions, and compares reports:

```text
"$SKILL_DIR/scripts/fusion-design" validate <manifest>
"$SKILL_DIR/scripts/fusion-design" plan <manifest>
"$SKILL_DIR/scripts/fusion-design" emit-inventory <manifest> [-o file.py]
"$SKILL_DIR/scripts/fusion-design" emit-parameter-sync <manifest> [-o file.py]
"$SKILL_DIR/scripts/fusion-design" emit-scaffold <manifest> [-o file.py]
"$SKILL_DIR/scripts/fusion-design" emit-verification <manifest> [-o file.py]
"$SKILL_DIR/scripts/fusion-design" emit-export <manifest> --verification-report <report.json> --export-dir <fusion-host-dir> [--format step|3mf|stl ...] [-o file.py]
"$SKILL_DIR/scripts/fusion-design" prusaslicer-project <manifest> --export-index <index.json> --output <project.3mf> [--printer NAME] [--filament NAME] [--print NAME] [--config-root DIR] [--slice] [--slicer-executable PATH]
"$SKILL_DIR/scripts/fusion-design" diff-reports <before.json> <after.json>
"$SKILL_DIR/scripts/fusion-design" prepare-module-bundle <package-dir> <entry-module>
"$SKILL_DIR/scripts/fusion-design" emit-module-bootstrap <bundle.json> [-o bootstrap.py]
```

When a Fusion transaction needs reusable custom code, use
`prepare-module-bundle` on a pure-Python package and execute the output of
`emit-module-bootstrap`. The content-addressed cache is persistent and outside
project repositories; `FUSION_MCP_MODULE_CACHE` may override its platform
user-cache location with an absolute path. It requires POSIX owner/permission
semantics and fails closed on native Windows. Emission and the generated
bootstrap verify the cached bundle before import. Do not bypass it, edit cache contents, call
`importlib.invalidate_caches()`, or place data/native modules in the bundle.
See `references/mcp-adapter.md` for the exact contract.

Pass emitted Fusion Python through the live MCP's discovered script-execution capability. Do not assume an execution tool name or argument schema. Capture the text between `FUSION_DESIGN_REPORT_BEGIN` and `FUSION_DESIGN_REPORT_END` as the machine-readable report.

Before the first real transaction, execute a tiny script that prints a unique
sentinel. If execution succeeds but the exact sentinel is absent, stop and
report the transport failure; do not treat an empty success response as proof
that a transaction ran. The complete manual, UI-responsiveness acceptance
sequence is in `docs/live-fusion-acceptance.md`.

The scripts intentionally refuse destructive design-type changes and contain no whole-timeline rebuild operation.
