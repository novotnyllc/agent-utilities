# Failure recovery judgment

Recover at the smallest native level that still preserves the intended design. Read the document before acting; a failed feature, stale timeline marker, MCP
disconnect, and unrecoverable design history are different problems.

## Use the smallest recovery that fits

| Condition | Native response |
|---|---|
| Immediate mistaken command or edit | Undo it once; use Redo only when the undo itself was mistaken |
| One responsible feature has wrong inputs or references | Edit Feature or Edit Sketch; delete only after checking downstream dependents |
| The failure begins somewhere upstream | Roll the timeline marker back temporarily to isolate the first bad feature, then restore it to the intended end |
| A suspect feature may be poisoning downstream geometry | Suppress it, observe the upstream model, then unsuppress or edit it |
 | Fusion crashes or MCP disconnects | Reconnect and inspect the live document first; only reopen saved state if Fusion actually lost the in-memory document. A transport disconnect alone does not mean edits are gone |
 | History is unrecoverable or governing assumptions changed | Stop, describe the target version and what newer work would be abandoned, and obtain explicit user approval before restoring |

## Undo immediate mistakes

Use Undo while the mistaken operation is still the top committed action. Do not unwind a long sequence blindly. After each undo, look at the viewport and
timeline so the document, not memory, decides whether the target state was
reached.

Undo is not a feature-repair strategy once valid downstream work exists. Edit
the responsible feature instead of erasing unrelated later work.

## Repair the owner

When one sketch or feature owns the error, edit its dimensions, parameters, selection set, or references. Prefer Edit Feature over replacement when the
construction strategy remains valid.

Before deleting a feature, inspect its dependents. Deletion can remove or
invalidate downstream features; the smaller edit is usually the safer repair.
Run Compute All after the correction and read the first remaining error.

## Diagnose upstream with temporary state

Record the current timeline-marker position, then move backward only far enough to identify the first unhealthy feature. A rolled-back model is a
diagnostic view, not a finished state.

Restore the marker to the intended end before final measurement, screenshot,
save, or handoff. Reacquire faces, edges, bodies, and occurrence proxies after
the timeline moves or recomputes; topology references may have changed.

Suppress a suspect feature when the question is whether the upstream design
is healthy without it. Fusion also suppresses dependent downstream features;
that consequence is evidence of dependency, not permission to leave the
design silently disabled.

## Resume after interruption

After an application crash, reopen the latest saved document and inspect the timeline tail, active component, browser state, and viewport. State what, if anything, was lost since the last save, then continue from the surviving model. After a transport-only disconnect (MCP shim lost but Fusion still running), reconnect and inspect the live active document first; do not reopen from disk because that may discard unsaved edits still in memory.

## Restore versions only for real resets

Use document-version restore when the current history cannot be repaired
safely, corruption makes the timeline unusable, or the governing source
dimensions and assumptions have changed enough that later work is invalid.
Version restore abandons newer edits; identify the target version and the lost
work before committing to it.

Do not restore a version for an isolated bad feature, a temporary rollback, or
a reconnect. Those have smaller native recoveries.
Version restore abandons all work after the target point; never perform it
without explicit user confirmation of the target version and the lost scope.

## Sources

- [Timeline](https://help.autodesk.com/view/fusion360/ENU/?guid=GUID-9B42F68A-0B65-4B57-88A5-4D5B4C5D6E7A)
- [Undo/Redo](https://help.autodesk.com/view/fusion360/ENU/?guid=GUID-F6FC7E15-3B69-4B69-B6A5-4C6D7E3C4E5)
