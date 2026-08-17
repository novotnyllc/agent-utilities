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

Preflight the execution capability with a unique printed sentinel. Some Fusion
MCP builds acknowledge successful Python execution while returning empty
stdout. When that exact failure is observed, make a new private directory on
the shared local filesystem for **each execution**, select a previously
nonexistent report filename inside it, and create a cryptographically random
caller-supplied `report_run_id`. Emit with the paired `--report-path` and
`--report-run-id` arguments. The generated script atomically publishes one
JSON object and refuses existing targets and symlinks. Parse the file and
accept it only if its `report_run_id`, expected transaction `kind`, and
`manifest_sha256` all match. Retain the parsed report, then remove the exact
report file and `rmdir` the exact empty private directory. Treat a missing,
stale, malformed, mismatched, symlinked, or non-local report file as a failed
transaction. Do not encode exceptions as successful reports.

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
