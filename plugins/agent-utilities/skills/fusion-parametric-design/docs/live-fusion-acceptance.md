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
4. Create a new parametric Design document and set its name programmatically, in
   the same script that creates it, to exactly `project.fusion_document` from the
   manifest — assigning `document.name` takes effect immediately on an unsaved
   document, so the document does not have to be saved to satisfy the name gate
   that every emitted transaction enforces. Do not run this smoke against an
   existing user document. Do not save or version the document unless the user
   expressly instructed that action. If the name cannot be set, stop and report
   that: never edit `project.fusion_document` to match whatever Fusion called the
   document, because that changes the manifest hash and invalidates every report
   binding and the export gate.
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
"$SKILL_DIR/scripts/fusion-design" emit-verification examples/electronics-enclosure/fusion-project.json -o build/verify.py  # record the nonce it prints on stderr; step 10 needs it
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

**Pass:** the first positive-control report lists all seven paths under `created` and carries empty `duplicate_semantic_paths` and `scaffold_identity_failures` (both re-derived after the final event pump); the second lists them under `reused` with no duplicate bodies; neither run emits a second report block; verification reports exactly one solid per print part at or above its declared `minimum_volume_mm3`, no relevant path ambiguity, no unhealthy or suppressed timeline item, no suppressed checked occurrence, clearance at or above 1.0 mm, zero forbidden interference, and overall `ok: true`.

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

Then move one product component without changing its geometry and diff again. **Pass:** `bounds_changed` names that component, so a rigid move is not reported as "no change".

Then diff the two saved verification reports from step 7 (a passing one against a deliberately failing one, for example with a clearance minimum raised above what the design achieves). **Pass:** `ok_before`/`ok_after`, `failures_added`, and the affected `clearance_changed`/`interference_changed` entry all show the regression.

Finally, diff an inventory report against a verification report. **Pass:** the command exits 2 with a refusal naming both kinds, instead of printing invented component removals and parameter deletions.

## 10. Export and handoff

Run the deterministic export transaction against the verified document:

1. Save the passing verification report from step 7 to a file (the JSON between the report delimiters), then emit the export script bound to it, passing the nonce `emit-verification` printed on stderr in step 2:
   `"$SKILL_DIR/scripts/fusion-design" emit-export examples/electronics-enclosure/fusion-project.json --verification-report verify-report.json --verification-nonce <nonce from step 2> --export-dir <fusion-host dir> -o build/export.py`
   (the checked-in `generated/export.py` uses the placeholder `FUSION_EXPORT_DIR` directory and the committed sample report; live runs always re-emit with a real directory and the real report). Negative test: re-run with any other nonce value. **Pass:** exit 2, no script emitted.
2. Execute `build/export.py` through the MCP. **Pass:** the report is `kind: export-handoff`, `ok: true`; the enclosure base, lid, and fit coupon each produce the requested STEP/3MF files; `export-index__*.json` sits beside them; recomputing `shasum -a 256` on the Fusion host matches every `sha256` in the index; byte sizes match.
3. Append the report's `design_state_rows` to `DESIGN-STATE.md` `## Exports`.
4. Re-run the same script unchanged. **Pass:** it fails closed with `output-exists` and no file's bytes change.
5. Negative test: duplicate a body name inside one print-part component (or add a second solid body), re-emit, and run. **Pass:** the report fails with `ambiguous-body` and no file is written.
6. Confirm the index contains no slicing, print-time, mass, or physical-fit claims outside each artifact's declared `manufacturing_intent` — actual slicing results remain external evidence.
7. Confirm each artifact's `manufacturing_intent` matches the manifest's `printable_parts` entry and that the three example parts carry their differing intent (base `-Z`/no supports, lid `+Z`/build-plate-only, coupon `-Z`/protected fit surfaces), and that the verification report recorded `occurrence_transforms` for all three.
8. Confirm the index carries `material_decision` **once at index level** (not per artifact), matching the manifest's PETG decision including its `confidence`, `coupon_component`, and `unresolved_risks`, and that it names no filament, printer, or process profile.

**Pass:** the handoff records the Fusion version (or explicit `unsaved`), manifest hash, verification-report hash, export run ID, reports, screenshots, exact export hashes, slicer/profile evidence when available, provisional dimensions, unsupported checks, and every physical test as `not run`, `pass`, `fail`, or `not applicable`.

## 11. Optional PrusaSlicer project handoff

Only when PrusaSlicer is installed and the user wants the slicer handoff checked.

What is automated and what is not:

- **Automated:** project generation (which runs no process at all), the optional headless slice when `--slice` is passed, and every file, hash, and statistic check below.
- **Manual:** the GUI confirmation of objects, placement, bed fit, presets, and overrides. Only a human can eyeball those, so they are never recorded as passing on the agent's own inspection.

Generate the project from the export index produced in step 10:

```bash
"$SKILL_DIR/scripts/fusion-design" prusaslicer-project examples/electronics-enclosure/fusion-project.json \
  --export-index <export dir>/export-index__<run>.json \
  --output build/project.3mf \
  --printer "<installed printer preset>" \
  --filament "<installed filament preset>" \
  --print "<installed print preset>"
```

**Pass (project generation):** exit code 0; `build/project.3mf` exists; the printed JSON's `project_sha256`/`project_byte_size` match `shasum -a 256` and the on-disk size; `export_index_sha256` matches the index file; `verification_report_sha256` and `export_run_id` equal the index's own; every printable part appears once in `objects` with its declared `applied_rotation`, `instances_count`, its assigned `plate`, and justified `overrides` (`plate` is not a manifest field: the adapter derives it from `print_as`, so `assembled` parts share plate 1 and each `separate` part gets its own); and `slice` is `{"supported": true, "attempted": false, …}` with no print-time, mass, or G-code numbers anywhere in the payload. Re-running against an existing output fails closed instead of overwriting.

**Optional headless slice.** Re-run the same command with `--slice` appended (and a fresh `--output`, since neither the project nor its G-code is ever overwritten). All three presets must be named: PrusaSlicer exits 139 (SIGSEGV) with no output when given a partial set, so the adapter refuses to invoke it unless printer, print, and filament are all resolved.

**Pass (slice):** exit code 0; `slice.ok` is `true`; `slice.exit_code` is `0`; `slice.project_sha256` equals the payload's `project_sha256`, and `slice.bindings` repeats it alongside the payload's `export_index_sha256`, `manifest_sha256`, `verification_report_sha256`, and `export_run_id`; `slice.gcode_sha256`/`gcode_byte_size` match `shasum -a 256` and the on-disk size of `slice.gcode_path`; `slice.slicer_version` names the binary that ran; `slice.presets` are the requested ones; and every number under `slice.statistics` also appears verbatim in the G-code's own `; ` comment lines. Anything the G-code does not state appears in `absent_statistics` rather than as a value. A failed slice must instead show `ok: false` with `exit_code`, `failure`, and `stderr_tail`, no `statistics` key, and CLI exit code 2.

**Manual confirmation — the user does this, the agent does not:** open `build/project.3mf` in the PrusaSlicer GUI and confirm by eye that

1. the same objects are present, one per printable part, with the part paths as their names and no merged mesh;
2. placement matches the reported plates and orientations — each part rests on the bed on its declared contact face, and parts declared `assembled` sit together — **and every object instance fits inside the selected printer's bed**. The adapter cannot check this: bed geometry lives in the printer preset, which is referenced by name and never read, so plates march along +Y without bound and a large job can run off the bed. Confirm the fit by eye and rearrange in the GUI if needed;
3. the printer, filament, and print presets shown are the requested ones, with the user's own profile settings intact (the project names presets, it does not carry copies of them);
4. per-object settings show only the justified overrides — supports from the declared policy, infill from the declared target, perimeters from the declared minimum.

Where PrusaSlicer is not installed, or `--slice` was not used, slice in the GUI and record the resulting time/mass/statistics against the project's `sha256`. The agent must not report those numbers unless they came from the `--slice` G-code or the user supplied them from a GUI slice.

**Pass:** the user confirms 1–4. This is a human acceptance step; it is never recorded as passing on the agent's own inspection.

## 12. Variant matrix

Prove the family, not one member. Copy the example manifest and add three
variants: two enclosure sizes and one deliberately broken one.

```json
"variants": [
  {"id": "small", "description": "Compact enclosure.", "parameters": {"des_corner_radius": "3 mm"}},
  {"id": "large", "description": "Large enclosure.", "parameters": {"des_corner_radius": "8 mm"}},
  {"id": "broken", "description": "Deliberate failure: wall thicker than the corner radius allows.", "parameters": {"fab_wall_thickness": "40 mm"}}
]
```

1. Plan the run: `scripts/fusion-design plan-variants build/variants.json --export-dir <fusion-host dir> --on-failure continue -o build/variant-plan.json`.
   **Pass:** the step order is capture → per variant (apply, inventory, verify,
   export) → restore → verify-restore; every non-deferred step carries a
   compilable script; the export steps are deferred with their reason.
2. Before starting, note the Parameters dialog's expressions for **every**
   parameter the manifest declares, not just the overridden ones — `apply` runs
   the parameter sync, which writes all of them. These are the restore target.
3. Execute each planned step's script through the MCP in order, saving each
   report to `build/reports/<report_name>`. After each save, re-run
   `plan-variants ... --reports-dir build/reports` to fold the evidence and get
   the next step — including the export script, which the runner emits only once
   that variant's verification report exists.
   **Pass:** an intermediate fold exits 0 with `failures: []` while nothing has
   failed, and exits 2 with `variant-failed` from the first fold after `broken`'s
   verification report is saved — not only at the end. Every incomplete fold
   reports `restore.ok: false` with a reason saying the document has not been
   verifiably restored yet.
4. **Pass:** `small` and `large` produce `ok: true` rows with their own
   `manifest_sha256`, their own export directory under the export root, and
   distinct artifact hashes; `broken` produces an `ok: false` row naming the
   failing step and its verification failure tokens; the earlier rows are still
   present and unchanged; the overall record is `ok: false` with
   `variant-failed`; and `restore.verified` is `true` with an empty
   `mismatches`.
5. Confirm in the Fusion Parameters dialog by eye that both expressions are back
   to what step 2 recorded, and that the CLI exit code was 2.

**Pass:** a failing variant did not erase the evidence the passing ones earned,
the run reported failure rather than "2 of 3 passed", and the document is
verifiably back on the state it started from.

## 13. Mesh reconstruction — a marketplace STL with a dimensional modification

Only when a mesh workflow is being accepted. Use a downloaded marketplace STL (a
bracket or mount with at least one dimension to change), copied into the project
beside the manifest. **Record the Fusion version with every report in this
section: every mesh API used here is preview.**

The rebuild is no longer authored by hand. It is a pipeline of ten commands, run
in this order:

```
emit-capability-probe → emit-mesh-capture → emit-mesh-extract → fit-regions →
plan-reconstruction → emit-mesh-rebuild → emit-mesh-editability →
check-editability → emit-mesh-deviation → reconstruction-coverage
```

Each `emit-*` command writes a Fusion Python transaction that a person executes
inside Fusion through the discovered MCP capability; its report comes back on
stdout between the report delimiters and is saved to a file the next stage reads.
The five others — `fit-regions`, `plan-reconstruction`, `check-editability`,
`reconstruction-coverage`, and the `replan-without` recovery loop — are host-side
arithmetic and never touch Fusion. Every stage binds to the one before it by a
hash or a nonce, so **save each report to a file as it comes back**; a stage
whose input was retyped from a screen cannot be run.

This section is the procedure that *would* establish that the pipeline builds an
editable model from a marketplace mesh on one recorded Fusion release. Writing it
down establishes nothing. Only a completed live run with every report retained
does, and only for the release it ran against.

1. Add a `mesh_sources` record for the file — `sha256` of the bytes, `units` with
   its `unit_source` (a marketplace STL is almost always `declared` or `guess`,
   never `file`), `provenance: designed_export` for a modelled download or
   `capture` for a scan, and the identity `alignment_transform`. Then:
   `"$SKILL_DIR/scripts/fusion-design" emit-mesh-capture fusion-project.json -o build/mesh-capture.py`
   **Pass:** emission succeeds. Now change one byte of the STL and re-emit.
   **Pass:** the CLI exits 2 with `mesh-source-hash-mismatch` and writes nothing.
   Restore the file. A failure here means the manifest's digest and the file on
   disk have parted company; fix the file or record a new source, never edit the
   digest to match what is on disk.

2. Probe the runtime before spending a transaction on it:
   `"$SKILL_DIR/scripts/fusion-design" emit-capability-probe fusion-project.json --probe-spec build/probe.json -o build/probe.py`
   and execute it. The probe creates nothing (`creates_geometry: false`).
   **Pass:** `kind: capability-probe`, and `interpreter`, `packaging_tags`,
   `writable_sys_path`, `modules`, `apis`, `missing_apis`, `face_groups` and
   `dump_write_roundtrip` are all present and read. Record `fusion_version` and
   the whole of `missing_apis` verbatim: that list is the version-specific fact
   this section exists to capture, and it predicts exactly which later stage will
   fail closed. Read `ok_means` before quoting `ok: true` at anyone — `ok` here
   means the probe ran, not that anything is present. Without `--probe-spec`,
   `face_groups` and `dump_write_roundtrip` report `status: not-requested`; that
   is not a pass, and a run that skipped the spec has not shown that Fusion can
   write the dump the next step depends on.

3. Insert the mesh into the document and execute `build/mesh-capture.py`.
   **Pass:** `kind: mesh-capture`, `ok: true`, the Fusion version is recorded, and
   every body reports a triangle count and `isClosed`. Note the body's component
   path and name — this is the binding no manifest field supplies.
   **Negative control:** insert the same mesh a second time under a duplicated
   component path and re-run. **Pass:** the capture fails closed with
   `ambiguous-component-paths` rather than reporting a partial body list. A
   capture that cannot read the triangle count or `isClosed` fails with
   `mesh-evidence-unavailable`; the classification inputs are then unfillable
   except by assumption, so stop.

   **Watertightness is load-bearing, and this is the last step where it can be
   fixed.** A cylinder becomes a `hole` in the rebuild only when its fitted
   region carries `orientation.material_side: "inside"`, and that field is
   derived from the mesh's own winding — it is `null` on any mesh that is not
   closed and consistently wound. A region whose `material_side` is `null` stays
   unreconstructed behind the `material-side-unavailable` gate: the bore-or-boss
   question is left open rather than closed by eye, and **no hole is ever emitted
   from a mesh that is not watertight**, at any later stage, however good the
   fit. If `isClosed` is false here, repair or re-export the mesh, record it as a
   new `mesh_sources` entry with its own digest, and start this section again.
   Carrying an open mesh forward buys a rebuild with no holes in it and a
   coverage account that says so at the very end, after every expensive step.

4. Record the classification from the capture's own numbers (`watertight` from
   `isClosed`, `facet_count` from the triangle count) for a `dimensional` edit.
   **Pass:** the recorded path is `parametric-rebuild`, written before any
   geometry operation runs.

5. **Negative control on the gate.** Emit a faceted conversion against that
   record:
   `"$SKILL_DIR/scripts/fusion-design" emit-mesh-convert fusion-project.json --mesh-source-id <id> --classification build/classification.json --convert-spec build/convert.json`
   **Pass:** exit 2 with `classification-path-forbids-operation`; nothing is
   emitted. Then hand-edit the record's `path` to `faceted-brep` without touching
   its inputs. **Pass:** exit 2 with `classification-path-contradicts-inputs`.
   Finally point a valid record at a different `mesh_sources` entry. **Pass:**
   exit 2 with `classification-source-mismatch`.

6. **The faceted ladder, on purpose.** Classify a `boolean-mechanical` edit with a
   declared `facet_budget` above the mesh's facet count, emit the conversion, and
   execute it. **Pass:** either `ok: true` with `"label": "faceted"` and
   `"parametric": false`, or a refusal naming its reason *and* its alternative
   with no B-Rep body left in the document. If Fusion complains, its own
   `errorOrWarningMessage` must appear verbatim in the report — confirm no facet
   ceiling number originates from this package. Confirm the source mesh body is
   still present and unmodified.

7. Extract a hash-bound mesh dump from the immutable source body:

   ```bash
   "$SKILL_DIR/scripts/fusion-design" emit-mesh-extract fusion-project.json \
     --mesh-source-id <id> \
     --classification build/classification.json \
     --extract-spec build/extract.json \
     -o build/mesh-extract.py
   ```

   The extract spec declares `component_path`, `body_name`, `dump_dir`, and both
   `max_triangles` and `fallback_max_bytes` with their rationales. Execute the
   script. **Pass:** `kind: mesh-extract`, `ok: true`, `transport: "file"` with a
   `dump_path` and a `dump_sha256`, `checked` containing
   `dump-written-and-reread`, `source_mesh_body_present: true`, and
   `dihedral_statistics`/`connectivity_statistics` present. **Record
   `dump_sha256`: the entire rest of the pipeline hangs off it**, and it is
   supplied to the next stage as an argument precisely so it comes from the
   report rather than from the file's own bytes.

   A failure names which: `source-not-found` (the binding from step 3 is wrong),
   `mesh-evidence-unavailable` or `mesh-arrays-unreadable` (a preview API this
   Fusion does not expose — cross-check `missing_apis` from step 2),
   `mesh-arrays-inconsistent` (the mesh Fusion holds is malformed),
   `triangle-budget-exceeded` (decimate and re-capture as a *new* source with its
   own digest; never raise the budget to make it fit), or `dump-write-unavailable`
   followed by `dump-too-large-for-fallback` (Fusion could not write the file and
   the base64 fallback is over the declared ceiling — make `dump_dir` writable
   from Fusion). `source-mesh-consumed` is the serious one: the immutable source
   did not survive a read-only transaction, and the run stops there.

8. Fit primitives to the dump. Host-side; no Fusion:

   ```bash
   "$SKILL_DIR/scripts/fusion-design" fit-regions build/<dump file> \
     --dump-sha256 <dump_sha256 from step 7> \
     --spec build/detection.json \
     -o build/fit.json
   ```

   **Pass:** exit 0 and `refusal: null`. Read, in this order:
   `covered_area_fraction` (how much of the surface earned an accepted fit at
   all); `regions[].orientation.material_side` for every accepted cylinder —
   `"inside"` is a bore and the only thing that will become a hole, `"outside"` a
   boss, `null` an open question with `orientation.unavailable_reason` and
   `orientation.mesh_closed`/`mesh_winding` saying why (this is step 3 coming
   back); `unfitted_regions[].failed_gate`; `unclaimed.components` with their
   `dominant_curvature`; and `flags`, where `noise-model-inconsistent` or
   `angular-resolution-degraded` qualify every verdict downstream without
   stopping the run. (There is no `normals-unoriented` flag: nothing ever raised
   one, and the winding it would have judged is reported per region in
   `orientation` and per part in `mesh_orientation`, each with the reason it is
   unavailable.)

   Then read `disproof`, which is derived from the per-region evidence rather
   than asserted beside it: `gates[<gate>].ran` is how many accepted fits each
   gate actually judged and `skip_reasons` counts the rest under the reason the
   skipping block recorded. Both structure gates have a power floor — against
   residuals inside the measurement noise they have nothing to test — so on an
   exact tessellation it is normal for `residual-structure` and
   `heldout-residual` to have run on none of them. The gate names are the tokens
   in each region's own `fit.support.checked`: `radius-ratio`, `bounds-margin`,
   `relative-residual`, `simpler-primitive`, `support-span`,
   `support-span-floor`, `residual-structure`, `heldout-residual`,
   `nested-kind-parsimony`, `kind-promotion`, `parameter-uncertainty`,
   `cylinder-normal-tie-break` (the facet normals took a group the vertices had
   given to a sphere), `cylinder-normals-discrete` (the normals sweep, so this is
   not a prism of planar walls — the same token names the *rejection* when they
   do not), `normal-constrained-axis` (the axis came from the facet normals, not
   from the vertices) and `boundary-circle-corroboration` (the group's own
   boundary loop agrees with the fitted radius and axis; when it does not, the
   `boundary_circle.flag` is `boundary-circle-disagrees` and nothing is moved).
   `regime` says which measurement regime the run was in, whether you declared
   it, and whether that declaration overrode the mesh's own reading; it is
   carried into the program, because every noise floor above hangs off it.

   A refusal exits 2 with `refusal.reason` one of `triangle-budget-exceeded`,
   `mesh-degenerate`, `mesh-not-welded`, `feature-scale-below-noise`,
   `segmentation-coverage-insufficient`, or `fit-record-stage-failed`, each with
   its `alternative`. `segmentation-coverage-insufficient` is a statement about
   the shape, not the thresholds — a saddle-dominated remainder means no
   supported primitive fits it, and loosening the spec to get past it is
   fabrication. `fit-record-stage-failed` is a defect in this package, not a
   property of the mesh; report it with the stage it names.

9. Plan the reconstruction program. Host-side; no Fusion:

   ```bash
   "$SKILL_DIR/scripts/fusion-design" plan-reconstruction fusion-project.json \
     --fit-record build/fit.json \
     --program-spec build/program-spec.json \
     -o build/program.json
   ```

   The program spec carries `thresholds` (each a value with its rationale) and
   the `adopted` relationships. **Pass:** exit 0; `archetypes[]` carries `kind`
   values from `sketch-extrude`, `revolve`, `hole` and `fillet`;
   `covered_area_fraction` is the share those archetypes cover; `unreconstructed[]`
   names a `gate` for every region they do not; and `program_sha256`, `dump_sha256`
   and `manifest_sha256` are all present. Record `program_sha256`.

   Read every `unreconstructed[].gate` and confirm it is a sentence you agree
   with. The gate names are `material-side-unavailable` (the open mesh case from
   step 3), `plane-unmappable`, `hole-base-ambiguous`, `hole-base-not-extruded`,
   `hole-axis-oblique`, `hole-not-contained`, `hole-radius-absent`,
   `fillet-fit-unaccepted`, `fillet-neighbour-unreconstructed`,
   `fillet-neighbour-shared`, `fillet-radius-undeclared`,
   `fillet-radius-disagrees`, `fillet-edge-unidentified`, and
   `revolve-motion-unproven`, which carries the kinematic router's own reason
   after it: `motion-router-ambiguous`, `motion-router-signature-conflict`,
   `motion-extrusion`, `motion-helical`, `motion-none`, `motion-axis-mismatch`,
   `motion-evidence-undeclared` or `motion-evidence-unavailable`. **A gate is
   a result, not an error.** A refusal, by contrast, exits 2 printing a JSON
   record whose `reason` is one of `fit-record-malformed`,
   `fit-record-moments-unbound`,
   `fit-record-missing-axial-span`, `fit-record-missing-uncertainty`,
   `frame-no-accepted-fits`, `frame-ambiguous`, `frame-x-underdetermined`,
   `adoption-unmeasured`, `adoption-unlicensed`, `adoption-unsupported-target`,
   `adoption-conflict`, or `adoption-shift-exceeds-license`. Keep that record: it
   is the evidence, and each carries its own alternative.

10. Emit the rebuild transaction and run it:

    ```bash
    "$SKILL_DIR/scripts/fusion-design" emit-mesh-rebuild fusion-project.json \
      --mesh-source-id <id> \
      --classification build/classification.json \
      --program build/program.json \
      --rebuild-spec build/rebuild-spec.json \
      -o build/mesh-rebuild.py   # record the rebuild nonce it prints on stderr
    ```

    The rebuild spec names `component_name` (never the root: the source mesh
    stays where it is and the rebuild overlays it), `dump_path` for the same dump
    step 7 wrote, and the emission `thresholds` with their `rationale`. Emission
    refuses, exit 2 with no script written, on `program-schema-violation`,
    `program-order-invalid`, `program-order-cyclic`, `plane-unmappable`,
    `profile-not-closed`, `profile-not-found`, `profile-ambiguous`,
    `units-unsupported`, `cap-order-inverted`, `archetype-kind-unsupported`,
    `entity-resolution-ambiguous`, `parameter-name-collision`, or
    `program-parameter-unbound`.

    Execute the script. **Pass:** `kind: mesh-rebuild`, `ok: true`, `failures: []`,
    and `rebuild_nonce`, `dump_sha256`, `program_sha256` and `manifest_sha256`
    echoed back. Then look at what it actually built: `created` lists the
    component, every feature and its archetype id; `user_parameters` echoes each
    created parameter with the `expected_observable` it is supposed to drive;
    `sketches[]` carries `fully_constrained`, `rejected_constraints`,
    `rejection_budget` and `profile_displacement_mm` per sketch; `timeline`
    reports health; and `unreconstructed` is carried through from the program.

    **`fillets_skipped` is the one to read closely.** Fillets are individually
    optional: a fillet whose edge set does not resolve is recorded there with a
    `reason` of `parent-feature-missing`, `fillet-capability`,
    `entity-resolution-ambiguous` or `feature-failed`, and **the run still
    succeeds**. That is deliberate — nothing depends on a fillet — but each skip
    is an archetype that was planned and not delivered, and the coverage account
    in step 13 subtracts its area. A run with `ok: true` and a non-empty
    `fillets_skipped` has not built the model the program describes.

    A transaction-level failure rolls everything back and names itself:
    `rebuild-capability`, `dump-hash-mismatch`, `parameter-name-collision`,
    `entity-resolution-ambiguous`, `constraint-rejected-budget-exceeded`,
    `feature-failed`, `solver-unhealthy`, `profile-not-found`,
    `document-changed`, or `rollback-incomplete`. Save the refusal report;
    `rollback-incomplete` means the document still holds part of the failed
    emission and must be cleaned up by hand before anything else is run in it.

11. **The `replan-without` loop.** When step 10 refuses naming one archetype, the
    answer is not to hand-edit the program. Both refusal shapes feed the loop:
    the *emission-time* refusal `emit-mesh-rebuild` prints on stdout before any
    script is written (`refusal` and `detail`), and the *transaction* refusal
    report the run in Fusion emits (`failures` and `refusal_detail`). Several
    tokens — `entity-resolution-ambiguous`, `parameter-name-collision`,
    `profile-not-found` — occur on both sides. Save whichever one you got:

    ```bash
    "$SKILL_DIR/scripts/fusion-design" replan-without build/program.json \
      --refusal build/rebuild-refusal.json \
      -o build/program-2.json
    ```

    This moves the named archetype's regions into `unreconstructed`, writing the
    refusal token into each gate, and re-hashes the program. **Pass:** exit 0 and
    a `program_sha256` different from the original. Re-run step 10 against
    `build/program-2.json`; it mints a **new** rebuild nonce and invalidates the
    old one.

    It refuses, correctly, in three cases, and each means something specific:
    the refusal names no archetype (a capability, hash or document refusal is
    about the binding, not about one feature — there is nothing to replan);
    `document_state` is `dirty` (clean up the wreckage of the failed emission
    first, or the replan emits a second component beside it); or another
    archetype depends on the one being dropped (re-plan from the fit record at
    step 9 instead). Loop at most as many times as you can still explain: each
    pass buys a smaller model, and the coverage account will price it.

12. Prove the parameters actually drive the model:

    ```bash
    "$SKILL_DIR/scripts/fusion-design" emit-mesh-editability fusion-project.json \
      --rebuild-record build/rebuild-report.json \
      --editability-spec build/editability-spec.json \
      -o build/mesh-editability.py   # record the editability nonce from stderr
    ```

    The spec declares, per parameter, its `perturbation`, `expected_observable`
    (`volume`, `centroid` or `bbox`), `min_observable_change`,
    `expected_direction` and `rationale`, plus `observable_restore_epsilon`.
    Execute the script, save its report, then run the gate:

    ```bash
    "$SKILL_DIR/scripts/fusion-design" check-editability \
      --rebuild-record build/rebuild-report.json \
      --editability-report build/editability-report.json \
      --editability-nonce <nonce from emit-mesh-editability>
    ```

    **Pass:** exit 0 with `ok: true`, an empty `problems`, `checked` listing the
    parameters proven, and `not_exercised` listing the rest by name. Read
    `proves`: each checked parameter was perturbed, the model recomputed, its
    declared observable moved by at least the declared minimum, the parameter was
    restored and all three observables returned within epsilon. Nothing else is
    proven — parameters were perturbed one at a time, so `interactions_exercised`
    is `false` and must be.

    Failures come from a closed set: `editability-capability`,
    `rebuild-record-mismatch`, `parameter-inert`, `parameter-effect-reversed`,
    `parameter-broke-rebuild`, `parameter-not-restorable`, `body-count-changed`,
    `base-feature-detected`, `document-changed`. `parameter-inert` means the
    rebuild produced a parameter that drives nothing, which is the failure mode
    this whole section exists to catch. `base-feature-detected` means the body
    is imported geometry wearing a timeline — a faceted import being passed off
    as a rebuild. **Negative control:** hand-write a six-line editability report
    claiming `ok: true` and pass it to `check-editability`. **Pass:** exit 2 with
    problems naming the nonce and the hash chain; the gate cannot be satisfied by
    a file nobody ran.

13. Grade the rebuild against the immutable source:
    `"$SKILL_DIR/scripts/fusion-design" emit-mesh-deviation fusion-project.json --mesh-source-id <id> --classification build/classification.json --deviation-spec build/deviation.json`
    with thresholds declared for *this* part and a stated rationale. Execute it.
    **Pass, in one of three honest forms:**
    - `ok: true` with **both** directions reported separately, each carrying the
      question it answers, the declared thresholds echoed, and the omitted-detail
      finding advisory rather than fatal;
    - `ok: false` with `invented-material` and the coordinates of the offending
      points;
    - `ok: false` with `deviation-capability` (naming `PolygonMesh.compareWith`,
      `BRepBody.pointContainment` or a `PointContainment` member, plus the Fusion
      version), `deviation-unsigned-comparison`, or
      `sign-convention-unestablished` — each with the invented-material verdict
      reported `not-established` and carrying no `count` or `max_mm`.

    When the verdict passes, record the `sign_convention` it observed and its
    `sign_probe` tally. **This is the reading to sanity-check by hand once per
    Fusion version:** the polarity is measured against `BRepBody.pointContainment`
    rather than assumed, so confirm it matches a case you can see.

    **Fail** if any report states a single combined deviation number, if a missing
    `compareWith` or `PointContainment` is silently skipped, if an unsigned
    comparison is reported as a pass, or if `severity: "pass"` appears alongside
    an unestablished sign convention.

14. Compose the one account a person reads at the end. Host-side; no Fusion:

    ```bash
    "$SKILL_DIR/scripts/fusion-design" reconstruction-coverage build/program.json \
      --fit-record build/fit.json \
      --rebuild-report build/rebuild-report.json \
      --editability-verdict build/editability-verdict.json \
      -o build/coverage.json
    ```

    The JSON goes to the output; the prose summary goes to stderr on every run.
    **Pass:** exit 0 and `label` is `parametric-full` or `parametric-partial`.
    Read `delivered_area_fraction` — the program's coverage minus every archetype
    the build did not deliver, including every skipped fillet — then `stages`,
    which carries the fit, plan, build and editability stages separately, then
    `unreconstructed`, which lists each region with the gate that stopped it, and
    finally `claims_not_made`.

    **`parametric-partial` is a success and is reported under its own name.** It
    means part of the scan is now editable Fusion features and part is not, with
    every unreconstructed region named and gated — and the source mesh remains in
    the document as reference geometry over the rebuild. Do not treat it as a
    failed `parametric-full`, do not go back and loosen thresholds to promote it,
    and do not report it as "mostly reconstructed" without the fraction and the
    gate list beside it.

    `reconstruction-refused` exits 2 and means one of two things: the rebuild
    report is absent (a plan is not a model), or the rebuild refused and rolled
    back, in which case `delivered_area_fraction` is `0.0` however much was
    planned. **Negative control:** re-run omitting `--rebuild-report`. **Pass:**
    label `reconstruction-refused`, exit 2, and the fit and plan stages still
    reported — an absent stage is reported absent, never read as complete.

    Read `claims_not_made` aloud before quoting any of this. The account states
    what was rebuilt, not that it is dimensionally correct (step 13's question),
    not that the recovered feature tree is the original designer's — it is *a*
    parameterization consistent with the measured surface, never *the* original —
    and not that any parameter drives a rebuild unless step 12 exercised it.

15. Confirm `DESIGN-STATE.md` records the mesh source, its hash, the recorded
    path with its rationale, the bound Fusion body, the coverage label with its
    delivered fraction and its unreconstructed gates, and both deviation
    directions with the question each answers.

### The record this section owes

Beyond the acceptance record at the top of this document, retain:

- the connected **Fusion version**, copied from every report that carries one
  (`capability-probe`, `mesh-capture`, `mesh-extract`, `mesh-rebuild`), and the
  statement that **every mesh API used in this section is preview** — the probe's
  `missing_apis` and the extract report's `preview_apis` are the version-specific
  evidence, and neither is portable to another release;
- both **nonces**, each with the command that minted it and the report that
  echoed it back: the rebuild nonce from `emit-mesh-rebuild` and the editability
  nonce from `emit-mesh-editability`. A re-emission mints a new one and
  invalidates the old, so record which emission each report belongs to;
- **every hash in the chain**: the mesh source `sha256` from the manifest, the
  `manifest_sha256`, the `dump_sha256` from the extract report (and again from
  the fit record, the program and the rebuild report), the `program_sha256`
  before and after any `replan-without`, and a `shasum -a 256` of each saved
  report file;
- the exit code of every host-side command, since a refusal is a result here and
  exit 2 is how each of these commands reports one.

**Pass:** the source file is byte-identical to its recorded hash at the end of
the run, the source mesh body is unmodified and still present in the document, no
faceted result is described as parametric anywhere, no hole was emitted from a
mesh whose winding did not license one, the coverage label and its delivered
fraction are recorded together with every gate, and a fit coupon is still
outstanding before any mating claim.

## 14. Restore the Fusion session

Close the disposable acceptance document without saving, reactivate the
document that was active before the smoke test, and read the open-document
inventory again.

**Pass:** the disposable document is closed, the prior document is active, and
its saved/modified state is unchanged from the initial checkpoint.

## Acceptance boundary

Passing this procedure validates the package against one recorded Fusion/MCP release. It does not prove FDM printability, electrical/thermal safety, physical fit, structural load capacity, comfort, ingress protection, or future Fusion-release compatibility. Those remain separate evidence gates.
