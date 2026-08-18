# Manual live Fusion MCP smoke and acceptance procedure

The host package and generated scripts are verified offline, but final compatibility must be exercised in the connected Fusion release because the MCP tools and Fusion API surface are dynamic. Use a new, disposable parametric design.

This is a manual-only smoke/acceptance procedure. It requires a person at the
Fusion machine and is intentionally not a CI gate: CI has no running Fusion
application, its UI event loop, or its local MCP server.

Resolve `SKILL_DIR` to the directory containing the installed skill's
`SKILL.md`; the user's project directory may be elsewhere.

## Acceptance record

Record:

- Fusion release/build;
- local Fusion MCP server version or capability inventory;
- agent/client and connection endpoint;
- package version/commit;
- document name and version, if one is saved;
- each emitted report and screenshot;
- any API/schema difference and the smallest adapter change.

## 1. Discover and checkpoint

1. Enable the local Fusion MCP server.
2. Through the connected client, dynamically discover tools, resources, prompts,
   schemas, permissions, and current API-documentation access. Bind the result
   to the abstract capabilities in `references/mcp-adapter.md`; never assume a
   remembered or hard-coded Fusion tool name.
3. Execute a mandatory read-only Python script that prints a unique sentinel
   such as `FUSION_STDOUT_PROBE_<random>`. Record the complete raw MCP response.
   If the exact sentinel is absent, stop the acceptance with the raw response;
   an empty success response is not proof that a transaction ran.
4. Create a new parametric Design document whose document name exactly matches
   `project.fusion_document` in the manifest. Do not run this smoke against an
   existing user document. Do not save or version the document unless the user
   expressly instructed that action.
5. Capture the initial document inventory and viewport, or record the exact
   unavailable capability.

**Pass:** the client can read the active design, execute a read-only Python
script, capture output/errors, and return the exact sentinel on stdout.

## 2. Validate and emit transactions

From the package root:

```bash
"$SKILL_DIR/scripts/fusion-design" validate examples/electronics-enclosure/fusion-project.json
"$SKILL_DIR/scripts/fusion-design" plan examples/electronics-enclosure/fusion-project.json
"$SKILL_DIR/scripts/fusion-design" emit-inventory examples/electronics-enclosure/fusion-project.json -o build/inventory.py
"$SKILL_DIR/scripts/fusion-design" emit-parameter-sync examples/electronics-enclosure/fusion-project.json -o build/sync-parameters.py
"$SKILL_DIR/scripts/fusion-design" emit-scaffold examples/electronics-enclosure/fusion-project.json -o build/scaffold.py
"$SKILL_DIR/scripts/fusion-design" emit-verification examples/electronics-enclosure/fusion-project.json -o build/verify.py
```

Run each emitted script directly through the discovered Fusion Python tool and
retain its complete raw response. Accept exactly one JSON object between the
report delimiters and require its `kind`, `manifest_sha256`, and success state
to match the transaction.

**Pass:** validation reports `ok: true`; the plan has nine phases and is not
blocked; all four general transactions are emitted and the checked-in
example-specific positive-control script compiles.

### Pure-Python module cache smoke

Create a temporary package containing `__init__.py`, `helper.py`, and an
`entry.py` whose `run(context)` imports `helper.py` relatively and prints a
unique sentinel. Create a fresh disposable cache root outside every repository,
set its mode to 0700, and pass it with `--cache-root`. Run
`prepare-module-bundle <package> entry`, then
`emit-module-bootstrap <bundle.json>` and execute that bootstrap through the
discovered Fusion Python capability. Execute the same verified bootstrap a
second time, then change `helper.py`, prepare again, and execute the new
bundle.

**Pass:** both executions of the unchanged bundle return the first sentinel;
the changed source produces a different digest/package and returns the new
sentinel; relative imports succeed; no package entry remains in `sys.modules`;
no `__pycache__` is created; and the active document is unchanged. Tampering
with one `.py` file in this disposable cache must make
`emit-module-bootstrap` fail before Fusion execution. After recording the
result, remove only that exact disposable cache root; never tamper with or
delete the persistent default cache.

The steps below run emitted scripts directly and retain their MCP responses.

## 3. Read-only inventory

Run `inventory.py` through the discovered Fusion Python-execution capability.

**Pass:** exactly one JSON object appears between the report delimiters. It
reports a parametric design, document name, parameters, component paths,
geometry/bounds, duplicate semantic paths, and timeline health. Running
inventory must not create a parameter, component, body, feature, or timeline
item.

## 4. Parameter synchronization and idempotence

Run `sync-parameters.py`, retain its report, then run it a second time without changing the manifest.

**Pass:**

- first run creates the declared user parameters with comments and `fusion_parametric_design` attributes;
- Compute All completes with no unhealthy timeline item;
- second run reports every parameter unchanged;
- no duplicate parameter is created;
- a deliberate existing-unit conflict causes a clear failure rather than silently changing dimensional type.

## 5. Component scaffold and idempotence

Run `scaffold.py` twice.

**Pass:**

- first run creates only missing declared component paths;
- second run reports no creations;
- no existing geometry is deleted or moved;
- duplicate semantic occurrence paths are reported and block further scaffolding rather than choosing one silently.

## 6. Expected empty-model failure

Run `verify.py` immediately after scaffolding.

**Pass:** verification fails because expected print parts and checked components do not contain positive-volume solids. Empty components, mesh-only placeholders, and surface bodies must not satisfy the check.

## 7. Positive control geometry

Run `examples/electronics-enclosure/generated/positive_control.py` through the discovered Fusion Python capability. It creates simple native, positive-volume test solids in these components, using root-coordinate placements that make the example contract pass:

- `PACK__PD_TRIGGER__EXACT_OR_CONSERVATIVE`: a 35 × 13 × 5 mm box;
- `PACK__EKYLIN__EXACT_OR_CONSERVATIVE`: a 62 × 31 × 27 mm box, far from the PD box;
- `KEEP__USB_C_INSERTION`: a solid keep-out separated from `PROD__BASE`;
- `KEEP__EKYLIN_WIRE_BENDS`: a solid keep-out separated from `PROD__LID`;
- `PROD__BASE`, `PROD__LID`, and `VAL__PD_FIT_COUPON`: one solid each.

The script places the lid so its nearest point is at least 1.0 mm from the PD packing solid and keeps both forbidden keep-outs disjoint from their paired product component. These boxes are acceptance geometry, not a product design.

Run `positive_control.py` a second time, then run inventory and verification.

**Pass:** the first positive-control report lists all seven paths under `created`; the second lists them under `reused` with no duplicate bodies; verification reports positive-volume solids, no relevant path ambiguity, no unhealthy timeline item, clearance at or above 1.0 mm, zero forbidden interference, and overall `ok: true`.

## 8. Negative controls

Run each fault independently and undo it or recreate the disposable passing
document between faults; do not save the acceptance document.

### Clearance fault

Move or edit the lid so the PD-to-lid gap is less than 1.0 mm.

**Pass:** only the applicable clearance gate fails, with the measured distance in millimeters.

### Interference fault

Move one forbidden keep-out into its paired product solid.

**Pass:** the applicable interference gate reports one or more results, entity labels, and positive total interference volume in mm³.

### Timeline-health fault

Create or edit a feature so it has a warning or error, then Compute All.

**Pass:** the timeline item and message appear in the report and block verification. A suppressed or non-feature/unknown timeline entry is reported informationally rather than mislabeled healthy.

### Mesh-only fault

Remove the checking B-Rep from one checked component and retain only a mesh.

**Pass:** verification explicitly refuses the clearance/interference claim and says that a positive-volume root-context B-Rep envelope is required.

### Direct-design fault

In a disposable copy only, disable design history and run a mutation script.

**Pass:** parameter sync and scaffold refuse to switch design type or reconstruct the document.

## 9. Semantic report diff

Retain passing inventory as `before.json`; change one user parameter or product body; retain the new inventory as `after.json`.

```bash
"$SKILL_DIR/scripts/fusion-design" diff-reports before.json after.json
```

**Pass:** the diff identifies the changed parameter expression, component additions/removals, changed geometry summary, and newly unhealthy timeline records without claiming a full B-Rep/topology diff.

## 10. Export and handoff

Use the discovered export capability or Fusion UI to export the selected print bodies. Hash the outputs and complete `DESIGN-STATE.md`.

**Pass:** the handoff records the Fusion version, manifest hash, reports, screenshots, exact export hashes, slicer/profile evidence when available, provisional dimensions, unsupported checks, and every physical test as `not run`, `pass`, `fail`, or `not applicable`.

## 11. Restore the Fusion session

Close the disposable acceptance document without saving, reactivate the
document that was active before the smoke test, and read the open-document
inventory again.

**Pass:** the disposable document is closed, the prior document is active, and
its saved/modified state is unchanged from the initial checkpoint.

## Acceptance boundary

Passing this procedure validates the package against one recorded Fusion/MCP release. It does not prove FDM printability, electrical/thermal safety, physical fit, structural load capacity, comfort, ingress protection, or future Fusion-release compatibility. Those remain separate evidence gates.
