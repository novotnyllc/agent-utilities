# Live Fusion MCP acceptance procedure

The host package and generated scripts are verified offline, but final compatibility must be exercised in the connected Fusion release because the MCP tools and Fusion API surface are dynamic. Use a new, saved, disposable parametric design.

Resolve `SKILL_DIR` to the directory containing the installed skill's
`SKILL.md`; the user's project directory may be elsewhere.

## Acceptance record

Record:

- Fusion release/build;
- local Fusion MCP server version or capability inventory;
- agent/client and connection endpoint;
- package version/commit;
- document name and saved version;
- each emitted report and screenshot;
- any API/schema difference and the smallest adapter change.

## 1. Discover and checkpoint

1. Enable the local Fusion MCP server.
2. Discover tools, resources, prompts, schemas, permissions, and current API-documentation access.
3. Bind the discovered operations to the abstract capabilities in `references/mcp-adapter.md`.
4. Execute a read-only Python script that prints a unique sentinel. If the MCP
   reports success with empty stdout, use a new private temporary directory,
   previously nonexistent report filename, and cryptographically random
   `--report-run-id` for each remaining acceptance script.
5. Create and save a new parametric Design document.
6. Capture the initial document inventory and viewport.

**Pass:** the client can read the active design, execute a read-only Python
script, capture output/errors, and save or version the document. Either the
sentinel is returned on stdout, or the generated script produces fresh valid
JSON at the explicitly selected report path; an empty successful MCP response
alone does not pass.

For the report-file fallback, accept the JSON only when `report_run_id` equals
the ID supplied for that exact execution, `kind` equals the expected
transaction, and `manifest_sha256` equals the generated script's manifest
hash. After retaining the parsed report, remove that exact file and `rmdir` its
exact empty private directory. Never reuse a report directory, run ID, or
target filename across acceptance transactions.

## 2. Validate and emit

From the package root:

```bash
"$SKILL_DIR/scripts/fusion-design" validate examples/electronics-enclosure/fusion-project.json
"$SKILL_DIR/scripts/fusion-design" plan examples/electronics-enclosure/fusion-project.json
"$SKILL_DIR/scripts/fusion-design" emit-inventory examples/electronics-enclosure/fusion-project.json -o build/inventory.py
"$SKILL_DIR/scripts/fusion-design" emit-parameter-sync examples/electronics-enclosure/fusion-project.json -o build/sync-parameters.py
"$SKILL_DIR/scripts/fusion-design" emit-scaffold examples/electronics-enclosure/fusion-project.json -o build/scaffold.py
"$SKILL_DIR/scripts/fusion-design" emit-verification examples/electronics-enclosure/fusion-project.json -o build/verify.py
```

If the sentinel preflight found dropped stdout, replace each emission above
with a distinct report-file invocation. For example, the inventory execution
uses one private directory, one previously nonexistent target, and one random
run ID:

```bash
report_dir="$(mktemp -d)"
report_path="$report_dir/inventory.json"
report_run_id="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
"$SKILL_DIR/scripts/fusion-design" emit-inventory examples/electronics-enclosure/fusion-project.json \
  --report-path "$report_path" --report-run-id "$report_run_id" -o build/inventory.py
```

Run Fusion, parse and identity-check this report as described above, then run
`rm -f -- "$report_path"` and `rmdir -- "$report_dir"`. Repeat with a new
directory, target, and ID for every other transaction.

**Pass:** validation reports `ok: true`; the plan has nine phases and is not blocked; all four scripts are emitted.

## 3. Read-only inventory

Run `inventory.py` through the discovered Fusion Python-execution capability.

**Pass:** exactly one JSON object appears between the report delimiters; it reports a parametric design, document name, parameters, component paths, geometry/bounds, duplicate semantic paths, and timeline health. Running inventory must not create a parameter, component, body, feature, or timeline item.

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

Create simple native, positive-volume test solids in these components, using root-coordinate placements that make the example contract pass:

- `PACK__PD_TRIGGER__EXACT_OR_CONSERVATIVE`: a 35 × 13 × 5 mm box;
- `PACK__EKYLIN__EXACT_OR_CONSERVATIVE`: a 62 × 31 × 27 mm box, far from the PD box;
- `KEEP__USB_C_INSERTION`: a solid keep-out separated from `PROD__BASE`;
- `KEEP__EKYLIN_WIRE_BENDS`: a solid keep-out separated from `PROD__LID`;
- `PROD__BASE`, `PROD__LID`, and `VAL__PD_FIT_COUPON`: one solid each.

Place the lid so its nearest point is at least 1.0 mm from the PD packing solid. Keep both forbidden keep-outs disjoint from their paired product component.

Run Compute All, inventory, and verification.

**Pass:** verification reports positive-volume solids, no relevant path ambiguity, no unhealthy timeline item, clearance at or above 1.0 mm, zero forbidden interference, and overall `ok: true`.

## 8. Negative controls

Run each fault independently and restore the saved passing state between faults.

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

## Acceptance boundary

Passing this procedure validates the package against one recorded Fusion/MCP release. It does not prove FDM printability, electrical/thermal safety, physical fit, structural load capacity, comfort, ingress protection, or future Fusion-release compatibility. Those remain separate evidence gates.
