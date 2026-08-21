# Fusion MCP adapter contract

MCP is transport. It is the channel through which the agent operates Fusion —
never a programming environment in its own right. A Python snippet sent over it
is short, direct, limited to one native operation or one tightly related
feature sequence, and readable as the equivalent of a skilled user action in
Fusion. Python sent over MCP must not become a CAD application, a
geometry-generation framework, a persistent transaction system, a validation
framework, a reporting framework, or a replacement for the Fusion browser and
timeline. The generated transactions described below serve the skill's
automation and release lanes; ordinary modeling is small direct operations.

Autodesk's Fusion MCP advertises dynamic tools. This skill therefore defines capabilities, not fixed tool names.

## Capability binding

At session start, discover and record the current tool/resource schemas. Bind tools only when their documented semantics match:

| Capability | Required behavior | Safe fallback |
|---|---|---|
| `READ_DOCUMENTATION` | Search/read current Fusion API documentation | Official Autodesk web documentation |
| `READ_ACTIVE_DOCUMENT` | Inspect active document/product/design state | Ordinary lane: the smallest inline read-only probe that answers the immediate question; machinery lanes: the generated inventory transaction |
| `EXECUTE_FUSION_PYTHON` | Run Python in the active Fusion session and return output/errors | No modeling fallback: stop. In the ordinary lane, do not write or hand the user a persistent script as a substitute |
| `CAPTURE_VIEW` | Return current or requested canvas image | Capture the Fusion window through the session's computer-use capability; without one, ask the user for a screenshot |
| `SAVE_OR_VERSION` | Save current document or create a version/checkpoint | Ordinary lane: `Document.save`/`saveAs` inline, or Fusion's own UI; machinery lanes: the `emit-document-save` transaction; only when nothing is available, the user saves manually before mutation |
| `UNDO_REDO` | Undo/redo recent document operations | Fusion Undo through the capability or UI; never restore an older document version automatically — without a bounded recovery mechanism, stop before a risky mutation |
| `IMPORT_EXPORT` | Import reference data or export manufacturing files | Drive the documented Fusion command through the session's computer-use capability and verify the result; without one, ask the user to run it |
| `DOCUMENT_MANAGEMENT` | Open/create/list documents or data items | Drive the open/create through the session's computer-use capability; without one, the user opens the intended document |

Do not bind a tool by name alone. Read its current schema, side effects, permissions, and result format.

### apiDocumentation query grammar

Probe the live `READ_DOCUMENTATION` schema at session start; remembered grammar is never authoritative. Always qualify an `apiDocumentation` query with both `apiCategory` and `filter`. A bare `searchPattern` has returned success-with-no-content; treat that shape as unreliable, never as proof that the API member does not exist. Do not retry a synonym ladder unqualified: identify the owning class, put its fully qualified namespace in `filter`, and request the relevant category. Example shape:

> {"queryType":"apiDocumentation","apiCategory":"member","searchPattern":"setOneSideExtent","filter":"adsk.fusion.ExtrudeFeatureInput"}

This is [verified-live, August 2026] against the local Fusion MCP, not an Autodesk specification of the server behavior.

## Ordinary-lane execution

Ordinary modeling does not use generated transaction contracts.

- Read the active document with the smallest inline read-only probe that answers the immediate question; do not run generated inventory.
- Save directly through the discovered save capability, `Document.save`/`Document.saveAs`, or Fusion's own UI; do not invoke a manifest-backed save emitter.
- If Fusion Python execution is unavailable, stop; do not write or hand the user a persistent script as a fallback.
- Use Fusion Undo/Redo through the available capability or UI; do not restore an older document version automatically, and stop before a risky mutation when no bounded recovery mechanism exists.

An ordinary-lane snippet confirms the active document, active Design, and intended target component; performs one visible edit; reads the created or edited feature's native health or error; and returns no audit schema, diff report, or persistent state. Ordinary snippets are single-use actions and need not be idempotent — idempotence, managed-entity discovery, report protocols, and deterministic reruns belong only to generated lane transactions.

Run `Compute All` and inspect timeline-wide health after a coherent feature group, before a fit claim, before a user review checkpoint, and before release — not after every individual feature.

## Units at the API boundary

Fusion user-facing dimensions use explicit units or named parameters.

- Prefer `ValueInput.createByString` with an explicit unit or parameter expression for dimensional feature inputs.
- Bare real-valued API lengths are Fusion database centimetres and bare real-valued angles are radians. Use them only when the API specifically requires database units, and perform the conversion once at the boundary.
- Label and convert all dimensional readbacks before reporting them to the user.
- Never mix user millimetres with API centimetres inside feature-construction arithmetic.

## Generated lane transaction rules

These rules govern generated lane transactions only. Every mutation transaction must:

1. state its narrow goal;
2. verify the active design and target component;
3. refuse destructive design-type conversion;
4. find existing managed entities before creating new ones;
5. change only the required parameters/features;
6. run `Compute All`;
7. report changed entities and unhealthy timeline items;
8. preserve enough output for audit and diff;
9. be safe to run a second time.

Prefer one coherent feature group per transaction. Do not make hundreds of single-entity MCP calls when one script can atomically create the group. Conversely, never pack the entire product into one opaque script: a monolithic product-construction transaction is the anti-pattern this contract exists to prevent, whatever lane it appears in.

## Main-thread responsiveness

Fusion runs both Python and TypeScript API scripts on its main thread. In bounded generated transactions, call `adsk.doEvents()` between coherent phases or top-level feature groups so Fusion can process queued display and UI messages. Do not yield halfway through creating or updating one managed entity.

Revalidate the same active document and Design after every yield; queued UI work can switch context while the transaction is paused. A single `computeAll()` remains blocking, so pump immediately before and after it rather than claiming progress within it.

`doEvents()` is not a design for an unbounded watcher, polling loop, or background job. Autodesk warns that repeatedly pumping events in a long-running loop can destabilize Fusion. Work that must remain alive should be a deliberate add-in using a worker thread for non-Fusion computation and a custom event to return API work to Fusion's main thread; never call Fusion API objects from the worker thread.

Official guidance: [Python-specific issues](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/PythonSpecific_UM.htm), [TypeScript-specific issues](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/TypeScriptSpecific_UM.htm), and [working in a separate thread](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/Threading_UM.htm).

## Python modules and dependencies

Fusion's embedded Python is its own runtime; do not assume that a module
available to the host Python is importable in Fusion. **Probe it — never quote a
note, including this one.** Run `emit-capability-probe` against the live Fusion
and read its report. That command exists because any written module inventory
goes stale the day Fusion auto-updates its interpreter, and a stale inventory
drives wrong architecture decisions.

What a live probe finds on one recorded configuration, kept here as an example
of what only a probe can establish: `secrets`, `sqlite3`, `ctypes` and
`ensurepip` all import. `numpy` raised a plain
`ModuleNotFoundError` — **not installed**, which is a different fact from
unloadable, and it was corrected by installing a matching wheel: numpy 2.5.2 from
a `cp314` / `macosx_11_0_arm64` wheel imported inside Fusion and ran
`linalg.eigh`, so the compiled LAPACK path executes. Fusion's Python there was
3.14.0, `EXT_SUFFIX = .cpython-314-darwin.so`, and `sysconfig.get_platform()`
reported `macosx-10.15-universal2` — note that the reported platform is *not* the
wheel tag that loaded. `sys.path` already contained a user-writable
`~/Library/Application Support/Autodesk/Autodesk Fusion 360/MyScripts/ManuallyInstalled/`.

**Third-party dependencies, if a feature ever wants one, are pip's job and need
nothing built here.** Cross-target install is one command that resolves
transitively against foreign tags:

```bash
python3 -m pip install --only-binary=:all: \
  --python-version <probed> --implementation <probed> --abi <probed> \
  --platform <probed> --target <dir> <packages>
```

Every `<probed>` value comes from the capability probe's `pip_tags`, never from a
literal in this document or in code. Fusion auto-updates its interpreter, so a
hardcoded `cp314` becomes a `ModuleNotFoundError` that reads as "not installed" —
the exact confusion that produced the wrong note above. Install from a pinned
lock with `--require-hashes`, and record the resolved set and its hashes against
the Fusion version it was resolved for.

The standing guidance is unchanged, but it does **not** rest on a capability
claim: put heavy mesh or other non-Fusion processing in the host environment and
pass only its result into Fusion. The reasons are that host-side numerics are
fully testable offline with no Fusion running, that the host's Python does not
move without the user, and that a wheel has to *exist* for Fusion's interpreter
on the day you need it — a real constraint today, where numpy publishes a `cp314`
wheel and scipy does not.

Autodesk's [Python-specific issues](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/PythonSpecific_UM.htm)
guidance about copying pure-Python modules beside a script does not directly
apply to API `execute` strings: a live probe found `__file__`, `__package__`,
and `__spec__` unset. For reusable pure-Python code, prepare a package bundle:

```bash
bundle_json="$("$SKILL_DIR/scripts/fusion-design" prepare-module-bundle ./my_package entry)"
bundle_file="$(printf '%s\n' "$bundle_json" | python3 -c \
  'import json,sys; print(json.load(sys.stdin)["bundle_file"])')"
"$SKILL_DIR/scripts/fusion-design" emit-module-bootstrap "$bundle_file" -o bootstrap.py
```

The source directory must be a package with `__init__.py`; `entry` identifies
`entry.py` (or a dotted submodule) defining `run(context)`. Send the emitted
bootstrap source through the dynamically discovered Python execution
capability. It temporarily adds the content-addressed package to `sys.path`,
supports relative imports, disables bytecode writes, and restores `sys.path`,
the bytecode flag, and its `sys.modules` entries even on failure. Emission
verifies every cached module before generating the bootstrap; the emitted
bootstrap rechecks the exact module inventory and hashes immediately before
import. Do not edit cached bundles.

The cache persists across projects and MCP sessions outside repositories. Its
platform user-cache default can be overridden only with an absolute
`FUSION_MCP_MODULE_CACHE`. This cache requires POSIX owner/permission semantics
and fails closed on native Windows. Only regular `.py` files are supported;
data files, symlinks, hard links, package-manager installation, and
compiled/native extensions are outside this cache's scope — **not** beyond
Fusion's capability. The cache delivers *our own* pure-Python code with content
addressing and verified imports; third-party wheels, native extensions included,
are pip's job, and pip already does them against probed tags (see above). Do not call
`importlib.invalidate_caches()`; it triggered an unavailable
`importlib.metadata` import in the observed Fusion runtime. Run heavy mesh or
other non-Fusion processing in the host environment and pass only its result
into Fusion.

The bundle solves imports, not result transport. If the stdout sentinel is
missing, stop; do not treat a direct bootstrap's empty response as
machine-readable success.

## Read → decide → write → inspect loop

1. **Read:** active document state, current visual state, and the exact documentation needed for the next action.
2. **Decide:** identify one visible edit.
3. **Write:** perform the smallest direct native operation.
4. **Inspect:** read the native feature result and capture the visible state.

Read manifests, generated inventories, and report diffs only in the lane that owns them.

## Report protocol

Generated scripts print exactly delimited JSON:

```text
FUSION_DESIGN_REPORT_BEGIN
{...}
FUSION_DESIGN_REPORT_END
```

The agent should parse and retain that JSON. Do not rely only on prose emitted around it.

A run can print more than one such block, so parse every one and treat the last
as the transaction's final word. Positive control emits a second block whenever
it created geometry and then failed; its `cleanup` field always carries the same
five keys (`performed`, `reason`, `deleted`, `errors`, `left_behind`), and
`left_behind` names every entity still in the document. Scaffolding has no
rollback by design, so its failure block reports `created` and `left_behind`
too. Only the verification and export reports are verdicts: the inventory
report carries no `ok` on the success path (it is a survey) and `ok: false`
only when the transaction itself failed.

Preflight the execution capability with a unique printed sentinel. If the
exact sentinel is absent, stop and report the transport failure. Do not encode
exceptions as successful reports or treat an empty success response as proof
that a transaction ran.

### The 180-second transport ceiling, and the tee that survives it

**Measured:** `AccurateGenerateFaceGroupsType` on a 524,614-triangle scan ran
330 seconds. The MCP transport gives up at **180 seconds**. The grouping was
applied to the document and the successful report was discarded, so the pipeline
was stuck on an operation that had already done its work, with no way to learn
what it had produced. Any mesh transaction on a real capture — grouping,
extraction, rebuild — can exceed the ceiling.

**Recovery path:** every generated transaction's `_emit` also writes the report
JSON to a file beside the transaction's own inputs, and names that file in the
stdout report as `report_tee_path`. The name is
`fusion-design-report-<kind>-<manifest-sha12>-<run-id>.json`, where the run id
is bound at run time from the process id and the clock — **one file per run**,
not one per kind. Two agents driving the same transaction kind against the same
manifest into the same directory is a hazard this adapter treats as supported,
and a name without the run id resolved both of them to one path: their writes
interleaved, and a recovery read could return the other run's report as if it
were yours. The report is written whole to a `.partial` file and moved into
place with `os.replace`, so a reader arriving mid-write sees either the previous
report or the new one and never half of either. When a call times out:

1. do not re-run the transaction — it may have mutated the document already;
2. read the **newest** file in the declared directory matching
   `fusion-design-report-<kind>-<manifest-sha12>-*.json`;
3. validate it as below before using it — including that it describes the work
   you asked for, since a concurrent run leaves its own file beside yours.

**A unique name stops clobbering; it does not establish ownership.** The run id
is bound inside the transaction and travels back on stdout, which is the channel
a timeout loses — so after a timeout the caller cannot say which of two files
its own run wrote, and two concurrent runs of the same kind against the same
manifest produce two reports that both satisfy every binding check. The way a
caller gets an exact file is the one it already controls: **give each concurrent
run its own `report_dir`**. Every transaction takes that directory from its own
declaration, so two agents that pass two directories never share a candidate
set. Where they do share one and two files match your bindings, the honest
outcome is that you cannot tell them apart: re-establish state from the document
rather than pick one. The report carries `run_id` so that ambiguity is visible
rather than silent.

The directory comes from the transaction's own declaration: `dump_dir` for
extraction and the capability probe, the dump's own directory for a rebuild, and
`report_dir` for face-group generation, which writes no file of its own and
therefore has nothing to sit beside unless the caller names a directory. A
transaction with no declared directory reports `report_tee_path: null` with
`report_tee_unavailable_reason`, which is a statement rather than a silence. The
export transaction deliberately does not tee: its contract is that the export
directory holds nothing of ours before it runs, and a report written into it
would break its own preflight.

A tee that cannot be written is never fatal — the report carries
`report_tee_error` and stdout is unchanged. Losing the tee must not lose the
transaction.

### Reports are per-stdout, so validate every block you parse

**Measured hazard:** two agents driving one Fusion session **interleave report
blocks**. The `FUSION_DESIGN_REPORT_BEGIN` / `..._END` delimiter contract is per
*stdout stream*, not per caller, and Fusion has one. A block appearing in your
response may have been printed by somebody else's transaction.

Therefore, before acting on any parsed block:

- check `kind` against the transaction you ran, and
- check `manifest_sha256` (and, where the report carries them, `dump_sha256` and
  the document name) against the document you are working on.

A block that does not match is **foreign: reject it, do not parse it further,
and do not treat it as your transaction's answer**. Do not merge two blocks of
the same kind. A concurrent-agent run must expect foreign blocks and say in its
notes that it did — "the last block wins" is only true on a stdout with one
writer, and a foreign block that happens to be last is the failure this rule
exists to prevent. If no block matches, the transaction's own answer is in the
tee file, which is per-directory and per-kind and therefore not shared.

## Permission policy

The local Fusion MCP has access to the live design session. Ask for the minimum persistent permissions that avoid repetitive prompts, typically documentation read, active-document read, Python execution, view capture, save/version, and undo. Keep file-system and network permissions separate from Fusion permissions.

## Error handling

When an ordinary-lane API call fails:

1. read the returned exception and traceback;
2. read the one current official API entry for that call (the Autodesk product-help MCP's `search_help_content` when that capability is connected);
3. verify the active document, Design, target component, and required object type with a read-only probe;
4. correct the call once against the actual target.

Do not create test geometry, a probe harness, a diagnostic component, or a reproduction project. Do not search forums or unrelated API areas. If the corrected call fails or requires broader investigation, show the failure and stop. Do not guess at an obsolete API signature.

Generated lanes follow only their documented refusal and retry contract.
