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
   If the exact sentinel is returned, select the stdout-working branch. If
   execution succeeds but stdout is empty, record that as the known stdout
   limitation and select the empty-stdout branch below. If the probe cannot be
   run or its result is otherwise unusable, do not assume stdout works: use the
   report-file fallback only where its platform and shared-filesystem checks
   pass, or stop the acceptance with explicit failure evidence.
4. Create a new parametric Design document whose document name exactly matches
   `project.fusion_document` in the manifest. Do not run this smoke against an
   existing user document. Do not save or version the document unless the user
   expressly instructed that action.
5. Capture the initial document inventory and viewport, or record the exact
   unavailable capability.

**Pass:** the client can read the active design, execute a read-only Python
script, and capture output/errors. Either the sentinel is returned on stdout,
or every report-producing transaction produces fresh valid JSON at its
explicitly selected report path; an empty successful MCP response alone does
not pass.

For the report-file fallback, use the report-session helper below. The helper
is POSIX-only and fails closed when its required file semantics are unavailable.
Accept JSON only when `report_run_id`, `kind`, and `manifest_sha256` match the prepared
session. Never reuse a report directory, run ID, or target filename across
acceptance transactions.

## 2. Validate and prepare one report session

From the package root:

```bash
"$SKILL_DIR/scripts/fusion-design" validate examples/electronics-enclosure/fusion-project.json
"$SKILL_DIR/scripts/fusion-design" plan examples/electronics-enclosure/fusion-project.json
"$SKILL_DIR/scripts/fusion-design" emit-inventory examples/electronics-enclosure/fusion-project.json -o build/inventory.py
"$SKILL_DIR/scripts/fusion-design" emit-parameter-sync examples/electronics-enclosure/fusion-project.json -o build/sync-parameters.py
"$SKILL_DIR/scripts/fusion-design" emit-scaffold examples/electronics-enclosure/fusion-project.json -o build/scaffold.py
"$SKILL_DIR/scripts/fusion-design" emit-verification examples/electronics-enclosure/fusion-project.json -o build/verify.py
```

The stdout-working branch runs each emitted script directly through the
discovered Fusion Python tool and parses its delimited response. The
empty-stdout branch runs the complete report-session sequence below
independently for `inventory`, `parameter-sync`, `scaffold`, and
`verification`. Every transaction gets a fresh session; no stdout-only step is
required in this branch.

For each transaction, call `prepare-report-session` with that transaction's
kind, send the returned script to Fusion, then verify and clean up the exact
session in that order. It creates a private 0700 directory, 0600
metadata/script files, a strict random run ID, and an absent report target.
Keep the returned metadata path; do not reconstruct any paths or IDs by hand:

```bash
set -euo pipefail
manifest="examples/electronics-enclosure/fusion-project.json"
session_json="$("$SKILL_DIR/scripts/fusion-design" \
  prepare-report-session "$manifest" inventory)"
session_file="$(printf '%s\n' "$session_json" | python3 -c \
  'import json,sys; print(json.load(sys.stdin)["session_file"])')"
script_file="$(printf '%s\n' "$session_json" | python3 -c \
  'import json,sys; print(json.load(sys.stdin)["script"])')"
printf '%s\n' "$session_json"
```

Send the contents of `"$script_file"` to the dynamically discovered Fusion
Python tool, and retain its complete raw response. Then verify and clean up
through the helper, in that order:

```bash
"$SKILL_DIR/scripts/fusion-design" verify-report-session "$session_file" \
  > inventory-report.json
"$SKILL_DIR/scripts/fusion-design" cleanup-report-session "$session_file"
```

Repeat that complete sequence three more times with fresh values for
`parameter-sync`, `scaffold`, and `verification` (and distinct report output
files). The CLI's `scaffold` session is verified under the canonical report
kind `component-scaffold`. Never reuse a session file, generated script, run
ID, report path, or report directory between transactions.

`verify-report-session` accepts exactly one JSON object only when its
`report_run_id`, `kind`, and `manifest_sha256` match the prepared session. It
never deletes artifacts. Cleanup removes only the exact generated files and
empty private directory; it rejects symlinks, hard-link aliases, path aliases,
escapes, and unexpected entries. If verification fails, retain the session and
raw MCP response for evidence and do not force cleanup.

**Pass:** validation reports `ok: true`; the plan has nine phases and is not blocked; all four scripts are emitted.

### Pure-Python module cache smoke

Create a temporary package containing `__init__.py`, `helper.py`, and an
`entry.py` whose `run(context)` imports `helper.py` relatively and prints a
unique sentinel. Create a fresh disposable cache root outside every repository,
set its mode to 0700, and pass it with `--cache-root`. Run
`prepare-module-bundle <package> entry`, then
`emit-module-bootstrap <bundle.json>` and execute that bootstrap through the
discovered Fusion Python capability. Execute the same verified bootstrap a
second time, then change `helper.py`, prepare again, and execute the new
bundle. This direct sentinel smoke applies only to the stdout-working branch.
On an empty-stdout build, record the transport limitation and exercise cached
code only as a helper from a report-capable top-level transaction.

**Pass:** both executions of the unchanged bundle return the first sentinel;
the changed source produces a different digest/package and returns the new
sentinel; relative imports succeed; no package entry remains in `sys.modules`;
no `__pycache__` is created; and the active document is unchanged. Tampering
with one `.py` file in this disposable cache must make
`emit-module-bootstrap` fail before Fusion execution. After recording the
result, remove only that exact disposable cache root; never tamper with or
delete the persistent default cache.

For the stdout-working branch, the steps below run the emitted scripts directly
and retain their MCP responses. For the empty-stdout branch, each occurrence
of a report-producing run below means: prepare a fresh session for that kind,
send its generated script to Fusion, verify the exact session, retain the
report, and then clean up that session. Do not substitute an empty MCP
response or a stdout-only check.

## 3. Read-only inventory

Run `inventory.py` through the discovered Fusion Python-execution capability.

**Pass:** in the stdout-working branch, exactly one JSON object appears between
the report delimiters; in the empty-stdout branch, `verify-report-session`
returns exactly one identity-matching JSON object. It reports a parametric
design, document name, parameters, component paths, geometry/bounds, duplicate
semantic paths, and timeline health. Running inventory must not create a
parameter, component, body, feature, or timeline item.

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
