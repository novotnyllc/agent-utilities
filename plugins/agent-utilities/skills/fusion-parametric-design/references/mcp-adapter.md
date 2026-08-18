# Fusion MCP adapter contract

Autodesk's Fusion MCP advertises dynamic tools. This skill therefore defines capabilities, not fixed tool names.

## Capability binding

At session start, discover and record the current tool/resource schemas. Bind tools only when their documented semantics match:

| Capability | Required behavior | Safe fallback |
|---|---|---|
| `READ_DOCUMENTATION` | Search/read current Fusion API documentation | Official Autodesk web documentation |
| `READ_ACTIVE_DOCUMENT` | Inspect active document/product/design state | Execute the read-only inventory script |
| `EXECUTE_FUSION_PYTHON` | Run Python in the active Fusion session and return output/errors | No safe modeling fallback; provide script for manual run |
| `CAPTURE_VIEW` | Return current or requested canvas image | Ask user for a Fusion screenshot |
| `SAVE_OR_VERSION` | Save current document or create a version/checkpoint | User saves manually before mutation |
| `UNDO_REDO` | Undo/redo recent document operations | Restore saved version/checkpoint |
| `IMPORT_EXPORT` | Import reference data or export manufacturing files | User performs the documented Fusion command |
| `DOCUMENT_MANAGEMENT` | Open/create/list documents or data items | User opens the intended document manually |

Do not bind a tool by name alone. Read its current schema, side effects, permissions, and result format.

## Transaction rules

Every mutation transaction must:

1. state its narrow goal;
2. verify the active design and target component;
3. refuse destructive design-type conversion;
4. find existing managed entities before creating new ones;
5. change only the required parameters/features;
6. run `Compute All`;
7. report changed entities and unhealthy timeline items;
8. preserve enough output for audit and diff;
9. be safe to run a second time.

Prefer one coherent feature group per transaction. Do not make hundreds of single-entity MCP calls when one tested Fusion script can atomically create the group. Conversely, do not pack the entire product into one opaque script.

## Main-thread responsiveness

Fusion runs both Python and TypeScript API scripts on its main thread. In bounded generated transactions, call `adsk.doEvents()` between coherent phases or top-level feature groups so Fusion can process queued display and UI messages. Do not yield halfway through creating or updating one managed entity.

Revalidate the same active document and Design after every yield; queued UI work can switch context while the transaction is paused. A single `computeAll()` remains blocking, so pump immediately before and after it rather than claiming progress within it.

`doEvents()` is not a design for an unbounded watcher, polling loop, or background job. Autodesk warns that repeatedly pumping events in a long-running loop can destabilize Fusion. Work that must remain alive should be a deliberate add-in using a worker thread for non-Fusion computation and a custom event to return API work to Fusion's main thread; never call Fusion API objects from the worker thread.

Official guidance: [Python-specific issues](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/PythonSpecific_UM.htm), [TypeScript-specific issues](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/TypeScriptSpecific_UM.htm), and [working in a separate thread](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/Threading_UM.htm).

## Python modules and dependencies

Fusion's embedded Python is its own runtime; do not assume that a module
available to the host Python is importable in Fusion. In the current live MCP
session, `os`, `tempfile`, `hashlib`, and `uuid` imported successfully, while
`secrets`, `sqlite3`, `numpy`, and `requests` did not. This is live evidence
for that Fusion installation, not a universal module inventory. Probe an
optional import in the live session before relying on it, and keep one-shot
MCP scripts to modules already proven there. Put heavy mesh or other
non-Fusion processing in the host environment and pass only its result into
Fusion.

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
compiled/native extensions are intentionally excluded. Do not call
`importlib.invalidate_caches()`; it triggered an unavailable
`importlib.metadata` import in the observed Fusion runtime. Run heavy mesh or
other non-Fusion processing in the host environment and pass only its result
into Fusion.

The bundle solves imports, not result transport. If the stdout sentinel is
missing, stop; do not treat a direct bootstrap's empty response as
machine-readable success.

## Read → decide → write → prove loop

1. **Read:** inventory, documentation, manifest, and current visual state.
2. **Decide:** identify one behavior or feature group and its measurable acceptance criteria.
3. **Write:** run the smallest idempotent transaction.
4. **Prove:** recompute, inspect health, measure, check interference, and capture visual evidence.
5. **Diff:** compare inventory reports when unintended scope is possible.

## Report protocol

Generated scripts print exactly delimited JSON:

```text
FUSION_DESIGN_REPORT_BEGIN
{...}
FUSION_DESIGN_REPORT_END
```

The agent should parse and retain that JSON. Do not rely only on prose emitted around it.

Preflight the execution capability with a unique printed sentinel. If the
exact sentinel is absent, stop and report the transport failure. Do not encode
exceptions as successful reports or treat an empty success response as proof
that a transaction ran.

## Permission policy

The local Fusion MCP has access to the live design session. Ask for the minimum persistent permissions that avoid repetitive prompts, typically documentation read, active-document read, Python execution, view capture, save/version, and undo. Keep file-system and network permissions separate from Fusion permissions.

## Error handling

When an API call fails:

1. inspect the returned exception and traceback;
2. query current official API documentation through the MCP;
3. inventory the target entity and design type;
4. reproduce with the smallest test geometry when safe;
5. fix one behavior;
6. rerun from the saved checkpoint when the failed transaction left partial geometry.

Do not guess at an obsolete API signature.
