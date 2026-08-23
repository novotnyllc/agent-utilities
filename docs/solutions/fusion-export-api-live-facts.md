---
title: Live-verified Fusion export API facts
date: 2026-08-18
category: fusion
---

# Live-verified Fusion export API facts (from issue #24 delivery)

Facts proven against a live Fusion instance while delivering deterministic export (PR #26); reuse them in #18/#22/#23 instead of re-discovering:

- `ExportManager.createSTEPExportOptions(filename, geometry)` **rejects a root-context occurrence proxy** — pass `occurrence.component`. Record the occurrence transform beside the artifact to keep the assembly frame recoverable. Mesh options take the reverse argument order: `createC3MFExportOptions(geometry, filename)`, `createSTLExportOptions(geometry, filename)`, and accept a `BRepBody`.
- Fusion **auto-uniquifies duplicate body names** created via the API within a component (`NAME` → `NAME (1)`), so a duplicate-body-name fail-closed branch is mostly reachable only through multiple-solids ambiguity; keep both guards.
- `BRepBody.deleteMe()` on a body inside a finished base feature can raise `InternalValidationError`; use timeline **undo** to roll back acceptance-test mutations instead.
- Fusion-runtime Python imports `hashlib`, `os`, `uuid` fine; `secrets` does **not** import. Run identity: `uuid.uuid4().hex` computed at run time (emit-time IDs break checked-in byte-equality guards).
- The MCP server appends extra stdout lines (its own sentinel + `ACTIVE_DOCUMENT=...`) after script output; the delimiter-based report protocol tolerates this — never assume script stdout is the only stdout.
- `document.name` is settable on an unsaved document created via `app.documents.add(...)`, which is how the disposable golden-path document acquires the manifest's `fusion_document` name.
- Evidence-binding pattern that works host-side-light: CLI validates + hashes the verification report and embeds identities into the generated transaction; the transaction re-checks live bounds, writes exports + `export-index__*.json` with `open(..., "x")` semantics, and hashes bytes in-process (the Fusion host owns the bytes; the CLI may not share its filesystem).
