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
- expected printable parts and fit coupons.

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

Use Fusion's export capability to produce STEP and 3MF/STL as required. Record document version, manifest hash, export path, and file hash in the handoff.

Fusion export is not the slicer. Print time, filament mass, supports, and machine-specific behavior require a configured slicer or another external manufacturing tool. If no supported slicer is available, export the files and state that cost/time estimates are unavailable rather than inventing them.

Re-run verification after any change that affects fit, geometry, print orientation, support, or export bodies.

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
"$SKILL_DIR/scripts/fusion-design" diff-reports <before.json> <after.json>
```

The four `emit-*` commands accept the paired
`--report-path /absolute/path/report.json --report-run-id <opaque-id>` when a
host-side JSON file is needed. For **every execution**, the caller creates a
cryptographically random run ID, a new private `mktemp -d` directory, and a
previously nonexistent report file inside it. The path and ID are validated at
generation and embedded in the script; the default remains delimited stdout.
The CLI and Fusion process must share the filesystem (the localhost MCP
transport does not copy files between hosts). The generated transaction refuses
an existing or symlinked report target, atomically publishes exactly one JSON
object, and visibly raises an error if the destination cannot be written.

Pass emitted Fusion Python through the live MCP's discovered script-execution capability. Do not assume an execution tool name or argument schema. Capture the text between `FUSION_DESIGN_REPORT_BEGIN` and `FUSION_DESIGN_REPORT_END` as the machine-readable report.

Before the first real transaction, execute a tiny script that prints a unique
sentinel. If the MCP reports success but returns no stdout, regenerate each
transaction with a new `--report-path`/`--report-run-id` pair inside a
host-created private temporary directory. Parse the resulting JSON file and
accept it only when `report_run_id`, `kind`, and `manifest_sha256` match the
generated transaction; then remove the exact file and `rmdir` the exact empty
directory after retaining the parsed report. Do not use this fallback unless
Fusion and the MCP client are confirmed to share the same local filesystem.

The scripts intentionally refuse destructive design-type changes and contain no whole-timeline rebuild operation.
