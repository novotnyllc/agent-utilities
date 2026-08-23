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
"$SKILL_DIR/scripts/fusion-design" emit-inventory examples/electronics-enclosure/fusion-project.json -o build/inventory.py
"$SKILL_DIR/scripts/fusion-design" emit-parameter-sync examples/electronics-enclosure/fusion-project.json -o build/sync-parameters.py
"$SKILL_DIR/scripts/fusion-design" emit-scaffold examples/electronics-enclosure/fusion-project.json -o build/scaffold.py
"$SKILL_DIR/scripts/fusion-design" emit-verification examples/electronics-enclosure/fusion-project.json -o build/verify.py  # record the nonce it prints on stderr; step 10 needs it
```

Run each emitted script directly through the discovered Fusion Python tool and
retain its complete raw response. Accept exactly one JSON object between the
report delimiters and require its `kind`, `manifest_sha256`, and success state
to match the transaction.

**Pass:** validation reports `ok: true`; all four general transactions are emitted; each emitted
script executes through the discovered Fusion Python capability and returns the expected report
kind, manifest hash, and transaction-specific success state; and the checked-in example-specific
positive-control script compiles. Emission and compilation alone never pass this gate — a
malformed transaction is caught only by running it and reading its report.

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

- `PD Trigger Envelope`: a 35 × 13 × 5 mm box;
- `EKYLIN Converter Envelope`: a 62 × 31 × 27 mm box, far from the PD box;
- `USB-C Insertion Keep-Out`: a solid keep-out separated from `Base`;
- `EKYLIN Wire Bend Keep-Out`: a solid keep-out separated from `Lid`;
- `Base`, `Lid`, and `PD Fit Coupon`: one solid each.

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

## 11. Optional PrusaSlicer project handoff: installed runtime or explicit offline-unsliced mode

Run the installed-runtime branch when PrusaSlicer is available and the user
wants authoritative profile and slice evidence. If that query surface is
unavailable, run the explicit offline-unsliced branch; it remains
non-authoritative and cannot authorize a slice.

What is automated and what is not:

- **Installed-runtime automated:** installed profile queries and runtime fingerprint, project generation (which runs no process at all), coarse printer-bed footprint/height checks, the optional headless slice when `--slice` is passed, the bounded G-code tool audit, and every file, hash, and statistic check below.
- **Offline-unsliced automated:** explicit parser-based project generation, with `profile_resolution.geometry_authority: "offline_parser"`, `installed: false`, unknown compatibility, and no slice attempt. `--offline-profiles --slice` is refused.
- **Manual:** for installed-runtime projects, GUI confirmation of objects, contact-face orientation, native arrangement, presets, and overrides. Physical fit and collision-accurate nesting are still human/physical acceptance, so they are never recorded as passing on the agent's own inspection.

### Installed-runtime profile preflight

Run the authoritative profile query first, with an explicit absolute datadir:

```bash
"$SKILL_DIR/scripts/fusion-design" prusaslicer-profiles \
  --config-root /absolute/path/to/PrusaSlicer-config \
  --printer "<exact installed printer preset>"
```

**Pass:** the result is `ok: true`, `resolver: "prusaslicer"`, and
`installed: true`; the requested printer identifier is present; compatible
print and filament identifiers are listed; and `runtime` records PrusaSlicer
`2.9.6`, executable path plus SHA-256, the same absolute datadir, the
profile-snapshot SHA-256, command kind, raw exit code/signal, and bounded
stderr. A query failure is terminal and must not be retried against another
datadir or silently downgraded.

If the installed query surface is unavailable, the only fallback is explicit
offline mode with the existing parser:

```bash
"$SKILL_DIR/scripts/fusion-design" prusaslicer-project examples/electronics-enclosure/fusion-project.json \
  --export-index <export dir>/export-index__<run>.json \
  --output build/project-offline.3mf \
  --config-root /absolute/path/to/PrusaSlicer-config \
  --printer "<known preset identifier>" \
  --filament "<known filament identifier>" \
  --print "<known print identifier>" \
  --offline-profiles
```

**Pass (offline only):** `profile_resolution` is
`{"resolver":"offline_parser","installed":false,"geometry_authority":"offline_parser","compatibility":"unknown"}`;
the project is explicitly unsliced; and `--offline-profiles --slice` is
refused. Do not present this result as proof that a profile is installed.

Generate the project from the export index produced in step 10:

```bash
"$SKILL_DIR/scripts/fusion-design" prusaslicer-project examples/electronics-enclosure/fusion-project.json \
  --export-index <export dir>/export-index__<run>.json \
  --output build/project.3mf \
  --config-root /absolute/path/to/PrusaSlicer-config \
  --printer "<installed printer preset>" \
  --filament "<installed filament preset>" \
  --print "<installed print preset>"
```

**Pass (installed-runtime project generation):** exit code 0; `build/project.3mf` exists; the printed JSON's `project_sha256`/`project_byte_size` match `shasum -a 256` and the on-disk size; `export_index_sha256` matches the index file; `verification_report_sha256` and `export_run_id` equal the index's own; `profile_resolution` names `resolver: "prusaslicer"`, `installed: true`, `geometry_authority: "installed_runtime"`, and the requested exact identifiers; `runtime` carries the query fingerprint; `printer_geometry` records the selected `bed_shape`/dimensions and maximum height used for placement; every printable part appears once in `objects` with its declared `applied_rotation`, `instances_count`, its assigned `plate`, and justified `overrides` (`plate` is not a manifest field: the adapter derives it from `print_as`, so `assembled` parts share plate 1 and each `separate` part gets its own); and `slice` is `{"supported": true, "attempted": false, …}` with no print-time, mass, or G-code numbers anywhere in the payload. Re-running against an existing output fails closed instead of overwriting.

**Optional headless slice.** Re-run the same command with `--slice` appended (and a fresh `--output`, since neither the project nor its G-code is ever overwritten). All three presets must be named: PrusaSlicer exits 139 (SIGSEGV) with no output when given a partial set, so the adapter refuses to invoke it unless printer, print, and filament are all resolved.

**Pass (slice):** exit code 0; `slice.ok` is `true`; `slice.exit_code` is `0`; `slice.project_sha256` equals the payload's `project_sha256`, and `slice.bindings` repeats it alongside the payload's `export_index_sha256`, `manifest_sha256`, `verification_report_sha256`, and `export_run_id`; `slice.runtime_evidence` names the same executable/datadir fingerprints and `runtime_fingerprint_before`/`runtime_fingerprint_after` show no drift; `slice.gcode_sha256`/`gcode_byte_size` match `shasum -a 256` and the on-disk size of `slice.gcode_path`; `slice.slicer_version` names the binary that ran; `slice.presets` are the requested ones; and every number under `slice.statistics` also appears verbatim in the G-code's own `; ` comment lines. `slice.gcode_audit` records recognized active tools and a tool-change count, or explicitly reports `available: false` for unknown/conflicting flavor evidence. Anything the G-code does not state appears in `absent_statistics` rather than as a value. A failed slice must instead show `ok: false` with `exit_code`, `failure`, and `stderr_tail`, no `statistics` key, and CLI exit code 2.

**Manual confirmation for installed-runtime projects — the user does this, the agent does not:** open `build/project.3mf` in the PrusaSlicer GUI and confirm by eye that

1. the same objects are present, one per printable part, with the part paths as their names and no merged mesh;
2. placement matches the reported plates and orientations — each part rests on the bed on its declared contact face, and parts declared `assembled` sit together. The adapter has already read the selected printer's `bed_shape` and `max_print_height` and failed closed on coarse bounding-box footprint/height overflow; it does not prove polygon-accurate collision nesting, physical fit, or the quality of later one-at-a-time plate loading. Confirm the native arrangement by eye and rearrange in the GUI if needed;
3. the printer, filament, and print presets shown are the requested ones, with the user's own profile settings intact (the project names presets, it does not carry copies of them);
4. per-object settings show only the justified overrides — supports from the declared policy, infill from the declared target, perimeters from the declared minimum.

If an installed-runtime project was generated without `--slice`, the user may
slice it in the GUI and record the resulting time/mass/statistics against the
project's `sha256`. An explicit offline-parser project must remain unsliced;
it is not evidence that the named profiles are installed and must not be used
to authorize a slice. The agent must not report numbers unless they came from
the `--slice` G-code or the user supplied them from a GUI slice of an
installed-runtime project.

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

## 13. Restore the Fusion session

Close the disposable acceptance document without saving, reactivate the
document that was active before the smoke test, and read the open-document
inventory again.

**Pass:** the disposable document is closed, the prior document is active, and
its saved/modified state is unchanged from the initial checkpoint.

## 14. Enclosure feature toolkit live acceptance

**These runs REQUIRE a live Fusion host with the bundled `AgentUtilitiesEnclosure`
add-in installed, and have NOT been executed by this implementation pass.** The
fixtures, record schema, and matrix below are the templates for the next live
session; recording a pass without a live run would be fabrication. Use a fresh
disposable parametric document per fixture group, exactly as in the earlier
sections.

### License/entitlement probe fixtures

Run one identical disposable fixture on a base account (no Design Extension)
and, when available, on the same Fusion build with extension trial/entitlement:

```python
# Pseudocode: identical disposable geometry and script on both accounts.
features = root.features

record("fusion_version", app.version)
record("design_extension_ui", probe_own_command_visibility_without_executing_hidden_ids())

record("boss_member", hasattr(features, "bossFeatures"))
if hasattr(features, "bossFeatures"):
    boss_input = features.bossFeatures.createInput()
    # Populate the smallest documented, known-good boss fixture.
    try:
        result = features.bossFeatures.add(boss_input)
        record("boss_result_types", [x.objectType for x in result])
        record("boss_native_health", ...)
    except Exception as exc:
        record("exception_type", type(exc).__name__)
        record("exception_message", str(exc))

for candidate in ("snapFitFeatures", "lipFeatures", "restFeatures"):
    record(candidate, hasattr(features, candidate))

record("design_plastic_rules", hasattr(design, "designPlasticRules"))
```

| Probe state | Purpose |
|---|---|
| Base Fusion, no Design Extension | establishes true base behavior |
| Same Fusion build, extension trial/entitlement | differentiates entitlement from API misuse |
| Public API only | no command-ID invocation |
| Any relevant preview API enabled/disabled | documents preview exposure but does not make it a core dependency |
| Save/reopen/edit | proves persistence and native feature editability |

An entitlement conclusion is allowed **only** when the same known-good
transaction succeeds with entitlement and fails without it, with identical
geometry/build/API signature. A transaction that fails both ways is an
API/geometry problem, not license evidence. No hidden command IDs,
`executeTextCommand` tricks, private modules, or undocumented entitlement paths
belong in this probe.

### Fixed live-record schema fields

Every case records this fixed schema (no field omitted, no invented fields):

```text
Fusion build
account/extension state
document/version
fixture ID
operation request JSON
pre-operation body count
expected native feature sequence
managed parameters
managed feature ID
timeline group(s)
post-operation body count
BRepBody.isSolid for claimed solid bodies
created-feature health
Compute All result
one named Measure/Interference observation if the fixture calls for it
parameter edit performed
post-edit health
save/close/reopen result
manual editability observation
Undo result
Redo result where relevant
final screenshot
raw Fusion exception on failure
```

### Representative live matrix

All rows below are required observations for their family; `unchanged` body
counts mean relative to that fixture's own pre-operation state. Expected native
sequences name the ordinary public features the recipe must create.

| Fixture | Operation / expected native sequence | Expected bodies | Required edit/failure observation |
|---|---|---:|---|
| flat enclosure | support boss → sketch/extrude/combine | 1 base | OD edit |
| rounded enclosure | same near filleted wall | 1 | wall radius change must recompute or fail visibly |
| lofted enclosure | landing pad to selected inner surface | 1 | loft change; no closest-face guess |
| variable-height enclosure | support `to_entity` | 1 | roof height edit follows native target |
| M3 heat-insert boss | boss + sourced insert bore | 1 | bore coupon status remains provisional |
| angled countersunk M3 boss | axis plane + boss + countersink/seat | 1 | exterior angle change |
| coordinated base/lid pair | shared axis + two sides | 1 each | mating-height edit updates both |
| captive hex nut | boss + hex pocket | 1 | AF clearance edit |
| captive square nut | boss + square pocket | 1 | insertion slot edit |
| thread-forming boss | boss + manufacturer pilot | 1 | absent pilot source refuses |
| native tapped boss | boss + Hole/Thread | 1 | thread spec edit |
| PCB standoff | boss to PCB plane | 1 | PCB plane height edit |
| open boss | outer + through bore | 1 | boss height edit |
| wall-connected/ribbed boss | boss + reinforcement | 1 | wall shift |
| simple lip/groove | planar offsets + join/cut | 1 each | clearance edit |
| tongue/groove | same family | 1 each | engagement edit |
| skirt/channel | skirt join + channel cut | 1 each | depth edit |
| bump-snap skirt | skirt/channel + discrete retention | 1 each | bump engagement edit |
| labyrinth | multiple planar wall/channel passes | 1 each | seam width edit |
| splash overlap | overlapping seam geometry | 1 each | warning: no ingress claim |
| nonplanar tangent seam | sweep join/cut | 1 each | path edit |
| sharp nonplanar seam | explicit segments | 1 each | unsupported unsegmented corner refuses |
| port-interrupted seam | port → exclusion datums → split seam | 1 each | move/resize port |
| hinge/latch interruption | explicit delimiters | 1 each | delimiter movement |
| registration key | key + receiver cut | 1 each | offset edit |
| anti-shear stop | stop + receiver | 1 each | stop-height edit |
| flat gasket | channel cut + land | 1 | groove width edit |
| O-ring channel | sourced cross-section cut | 1 | missing seal source/provisional evidence observed |
| cantilever snap | beam + hook + receiver | 1 each | thickness/engagement edit |
| hidden snap | beam/hook internal receiver | 1 each | missing release access warning/refusal |
| annular snap | revolve rings | 1 each | engagement edit |
| slotted annular | ring + slots/pattern | 1 each | slot count edit |
| fingered lock ring | ring + finger slots/pattern | 1 each | count edit |
| keyed ring | annular + key/notch | 1 each | rotation-key edit |
| press ring | concentric fit pair | 1 each | coupon required |
| interference ring | same, signed interference | 1 each | interference value edit |
| dovetail | male rail + female cut | 1 each | sliding-clearance edit |
| sliding key | rail/key + stop | 1 each | stop edit |
| bayonet | lugs/pattern + swept L-slots | 1 each | rotation/slot clearance edit |
| PCB edge rest | support tool + explicit join | 1 | PCB elevation edit |
| PCB corner rest | same | 1 | board-outline edit |
| local curved landing | flat pad to curved shell | 1 | shell curvature edit |
| converter shelf | shelf + gusset | 1 | component height edit |
| cylindrical cradle | saddle profile + join | 1 | cylinder diameter edit |
| keepout-trimmed support | support + explicit cut(s) | 1 | keepout movement |
| rectangular port | sketch + cut | 1 | width/height edit |
| rounded port | sketch arcs + cut | 1 | corner-radius edit |
| circular port | circle + cut | 1 | diameter edit |
| angled-wall port | axis-normal cut | 1 | wall-angle edit |
| curved-wall axis cut | planar cutter intersects curved shell | 1 | curvature edit |
| arbitrary conformal curved cut | refusal/ordinary modeling | unchanged | `unsupported-conformal-cutout` |
| connector recess | cut + shallow recess + holes | 1 | flange depth edit |
| strain-relief saddle | saddle + optional hardware | 1 | cable OD edit |
| zip-tie anchor | slots + bridge | 1 | slot dimensions edit |
| bend-radius guide | guide path + wall | 1 | radius edit |
| flex fingers | cantilever primitive | 1 | physical proof remains outstanding |
| rib/gusset | new tool + join + root fillet | 1 | thickness edit |
| boss-wall rib | reinforcement dependency | 1 | boss movement |
| slot vent array | seed cut + native pattern | 1 | count/pitch edit |
| circular vent array | seed + pattern | 1 | pitch edit |
| hex vent region | staggered native patterns | 1 | aperture edit |
| bounded clipped vent | tool pattern + mask + cut | 1 | region resize |
| arbitrary whole-cell vent | explicit suppression or refusal | 1 | no containment engine |
| fit coupon | labeled stations + common coupon body | 1 coupon | explicit candidate list edit |
| coupon result update | attributes/parameter comment only | unchanged | acceptance requires user-observed result |
| rectangular pattern | managed source + PatternFeature | unchanged target count | count edit |
| circular boss pattern | source + CircularPattern | unchanged | count edit |
| path pattern | source + PathPattern | unchanged | path edit |
| mirror | source + MirrorFeature | unchanged | mirror-plane edit |
| mirrored handed retention | mirror or refusal based on recipe | unchanged | verify handed behavior |
| configuration size change | activate row + reacquire | unchanged | resize enclosure |
| configuration topology loss | activate row causing source disappearance | unchanged | must refuse, never guess |
| save/reopen | all representative families | unchanged | feature discovery by attrs |
| manual native edit | alter managed feature manually | unchanged | inspect reports divergence |
| safe recipe upgrade | parameter-only migration | unchanged | recipe version updates |
| unsafe upgrade | remove/alter managed entity | unchanged | `manual-edit-prevents-update` |
| upstream feature deletion | delete managed port used by seam | unchanged | deletion must refuse while dependent exists |
| direct design | attempt managed create | unchanged | `invalid-design-type` |
| ambiguous occurrence | repeated component without context | unchanged | `assembly-context-required` |
| base no extension | every base recipe | normal | succeeds without plastic extension |
| native Boss API base probe | Autodesk BossFeature | probe-specific | entitlement result recorded |
| native Boss API entitled | same fixture | probe-specific | comparison control |

### Positive-case acceptance criteria

For every positive recipe case, `Compute All` must finish with no new warning
or error inside the managed group, every claimed output body must satisfy
`BRepBody.isSolid`, unrelated bodies must remain untouched, save/reopen must
retain the managed relationships (rediscovery by attributes, not timeline
index), and a representative master-parameter edit must change the intended
feature and recompute cleanly. These checks align with the repository's
existing native-verification doctrine and are necessary but not sufficient:
release claims still route through the full verification contract and physical
evidence gates.

## Acceptance boundary

Passing this procedure validates the package against one recorded Fusion/MCP release. It does not prove FDM printability, electrical/thermal safety, physical fit, structural load capacity, comfort, ingress protection, or future Fusion-release compatibility. Those remain separate evidence gates.
