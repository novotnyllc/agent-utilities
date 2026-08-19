---
title: "feat: Optional PrusaSlicer plate and project 3MF adapter"
date: 2026-08-19
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
origin: https://github.com/novotnyllc/agent-utilities/issues/22
---

# Summary

Add an optional adapter that consumes verified exports (#24) plus slicer-neutral manufacturing intent (#18) and writes a real PrusaSlicer **project `.3mf`** — separate objects, applied build orientation, plate assignment, presets selected by identifier, and only justified per-object overrides. The project is built as a file, not by driving the slicer. The headless slice that issue #22 also asks for is **unavailable on this host** and returns an explicit unsupported result rather than invented numbers.

---

## Problem Frame

Fusion supplies geometry and intent; PrusaSlicer owns printer, filament, and process profiles. Duplicating those profiles in the manifest would drift and reinvent the slicer. What is missing is the translation step: turning verified per-body exports plus declared intent into a project a human can open in PrusaSlicer and see the same objects, placement, presets, and overrides.

---

## Verified host facts (filesystem-only recon; the slicer binary was never executed)

- A PrusaSlicer project `.3mf` is a zip containing `[Content_Types].xml`, `_rels/.rels`, `3D/3dmodel.model` (standard 3MF geometry), `Metadata/Slic3r_PE.config` (full config as `; key = value` lines), `Metadata/Slic3r_PE_model.config` (XML), and an optional `Metadata/thumbnail.png`.
- `Slic3r_PE_model.config` carries `<object id=… instances_count=…>` with `<metadata type="object" key=… value=…/>` and nested `<volume firstid= lastid=>` entries whose own metadata includes `name`, `volume_type`, and a 16-value `matrix`. **This is where per-object overrides live** — no CLI required to express them.
- Installed user presets: printer `Original Prusa XL - 5T Input Shaper HF0.4 & HF0.6 nozzles`; print `0.40 SPEED @XLIS HF0.6 mixed`; filament `Overture PETG @XL HF0.4 - Black`, `Overture PETG @XL HF0.4 - White`, `Polymlaker PETG @XL HF0.4`.
- `PrusaSlicer.ini` records the *selected* presets, and those may name **system** presets with no user `.ini` on disk (currently `Prusament PETG @XL HF0.4`, `0.20mm SPEED @XLIS HF0.4`). Preset discovery must therefore read both sources and must not assume a named preset has a user file.
- **PrusaSlicer 2.9.6 segfaults on headless slicing** on this machine: `Slic3r::CLI::process_actions` → `Print::export_gcode` → `EXC_BAD_ACCESS` in `optional<ConflictResult>::operator=`. Four crash reports were produced before probing stopped. The adapter must never execute the binary.

---

## Requirements

- **R1.** Consume an export index produced by #24 (`kind: export-handoff`, `ok: true`) whose artifacts carry `manufacturing_intent`. Verify each referenced 3MF artifact against its recorded `sha256` and `byte_size` before use; any mismatch, missing file, or intent-less index fails closed.
- **R2.** Emit a PrusaSlicer project `.3mf` with **one object per printable part**, never a merged mesh. Object names carry the part path; `instances_count` reflects the part's declared `quantity`.
- **R3.** Apply the declared build orientation: map `orientation.contact_face` to the rotation that puts that face on the plate, and write it into the object/volume `matrix`. Record the applied rotation in the result so it is auditable.
- **R4.** Assign objects to plates, honoring declared grouping. Parts whose `print_as` is `assembled` stay on one plate together; `separate` parts may be distributed. Placement is deterministic (no random arrangement) so a rerun produces identical bytes.
- **R5.** Select the user's installed printer, filament, and process presets **by identifier**, writing only the preset names into the project config — never a cloned copy of their settings. A requested preset that is neither a user `.ini` nor a selected system preset in `PrusaSlicer.ini` fails with a clear unsupported result naming what was missing and what is available.
- **R6.** Apply only justified per-object overrides, each traceable to declared intent: `support_material` / `support_material_buildplate_only` / `support_material_style` from `support_policy`, `fill_density` from `strength.infill_percent.target`, `perimeters` from `strength.min_perimeters`. Any override without a declared justification is rejected.
- **R7.** The slice step returns an **explicit unsupported result** — `{"supported": false, "reason": "...", "detail": "..."}` naming the segfault — never fabricated print time, filament mass, or G-code statistics. The adapter must not execute the PrusaSlicer binary under any code path.
- **R8.** Record the project's own SHA-256 and byte size, plus the source export-index hash and the per-artifact hashes it consumed, so the project is bound to the exact verified geometry.
- **R9.** Pure-Python, standard library only (the package declares no dependencies): `zipfile` + `xml.etree.ElementTree` for reading Fusion's exported 3MF meshes and writing the project. Deterministic zip output (fixed timestamps, sorted entries) so identical inputs yield identical bytes.

---

## Assumptions

- **Geometry source is the exported 3MF, not STEP.** Fusion's 3MF exports already contain meshes; the adapter merges those meshes into `3D/3dmodel.model` as separate objects. STEP artifacts are recorded as provenance but not parsed.
- **Orientation is axis-aligned.** `contact_face` yields one of six axis-aligned rotations; arbitrary orientations are out of scope for this issue.
- **Plate capacity is not modeled.** Plate assignment honors declared grouping only; the adapter does not compute whether objects physically fit, and says so rather than implying it validated placement.
- **Support style** defaults to PrusaSlicer's configured value unless intent explicitly names one; the adapter does not invent a style.

---

## Key Technical Decisions

1. **KTD1: Build the project as a file; never drive the slicer.** Forced by the verified segfault, and better regardless — file construction is deterministic and testable offline, whereas driving a GUI-oriented binary is neither. This also keeps the adapter honest about the boundary the skill already draws: Fusion is not the slicer.
2. **KTD2: The slice is an explicit unsupported result, not an omission.** `references/unsupported.md` already treats print time and filament mass as external, and the planner's `export-and-cost` phase expects "slicer estimate **or explicit unsupported result**." This lands in the existing vocabulary instead of inventing one.
3. **KTD3: Presets by name only.** The project config records preset identifiers; the user's actual profile settings are never copied into our artifacts, satisfying the issue's explicit non-goal.
4. **KTD4: Deterministic zip.** Fixed member timestamps and sorted entries so the same index plus the same intent produces byte-identical output — a rerun is verifiable rather than merely plausible.
5. **KTD5: Adapter is optional and separate.** New module `src/fusion_design/prusaslicer_project.py` plus a CLI subcommand; nothing in the existing export or verification path changes, so a user without PrusaSlicer is unaffected.

---

## Implementation Units

### U1. Project 3MF writer

**Goal:** `src/fusion_design/prusaslicer_project.py` that reads an export index plus its 3MF artifacts and writes a PrusaSlicer project `.3mf`.

**Requirements:** R1–R4, R8, R9; KTD1, KTD4.

**Files:**
- `plugins/agent-utilities/skills/fusion-parametric-design/src/fusion_design/prusaslicer_project.py`
- `plugins/agent-utilities/skills/fusion-parametric-design/tests/test_prusaslicer_project.py`

**Approach:** Validate the index (kind/ok/hashes/byte sizes) and fail closed on any mismatch. Parse each part's exported 3MF with `zipfile` + `ElementTree`, extracting its mesh. Compose `3D/3dmodel.model` with one `<object>` per part, applying the orientation rotation and plate offset to each object's transform. Write `Metadata/Slic3r_PE_model.config` with per-object name, `instances_count`, and override metadata. Write the zip deterministically (sorted entries, fixed timestamps).

**Test scenarios:** index round trip produces one object per part; hash mismatch on a referenced artifact fails closed; missing artifact file fails closed; index without `manufacturing_intent` fails closed; each of the six `contact_face` values yields its expected rotation; `quantity` maps to `instances_count`; `assembled` parts share a plate while `separate` parts may not; identical inputs produce byte-identical output; output refuses to overwrite an existing file.

---

### U2. Preset resolution and per-object overrides

**Goal:** Resolve presets by identifier from the user's configuration and translate declared intent into the allowed override set.

**Requirements:** R5, R6; KTD3.

**Files:** same module and test file as U1.

**Approach:** Read preset identifiers from the user `printer/`, `filament/`, `print/` directories **and** the selected-preset keys in `PrusaSlicer.ini` (a selected system preset has no user `.ini` — treat it as valid). Write only names into `Metadata/Slic3r_PE.config`. Translate intent to exactly the allowed override keys and reject anything else.

**Test scenarios:** a preset present only as a `PrusaSlicer.ini` selection resolves; an unknown preset fails with an unsupported result listing what is available; `support_policy` maps to the correct support keys for each of the four policies; infill and perimeter overrides come from `strength`; an override with no declared justification is rejected; no full profile settings appear anywhere in the output.

---

### U3. Unsupported slice result and CLI

**Goal:** A `prusaslicer-project` CLI subcommand, and a slice step that is explicitly unsupported.

**Requirements:** R7; KTD2, KTD5.

**Files:**
- `plugins/agent-utilities/skills/fusion-parametric-design/src/fusion_design/cli.py`
- `plugins/agent-utilities/skills/fusion-parametric-design/tests/test_cli.py`

**Approach:** `prusaslicer-project <manifest> --export-index <index.json> --output <project.3mf> [--printer/--filament/--print <name>]`. The result reports the project path, hashes, applied orientations, plate assignment, overrides, and a `slice` block that is always `{"supported": false, …}` naming the 2.9.6 segfault. **No code path executes the PrusaSlicer binary** — a test asserts the module contains no `subprocess`/`os.system`/`Popen` usage.

**Test scenarios:** happy path writes the project and reports hashes; unknown preset exits 2; missing index exits 2; the slice block is always unsupported and never carries time/mass; static check finds no process-execution API in the module.

---

### U4. Documentation

**Goal:** Document the adapter, its boundary, and the unavailable slice.

**Files:** `SKILL.md`, `references/capability-matrix.md`, `references/unsupported.md`, `docs/live-fusion-acceptance.md`, both plugin manifests (version bump).

**Approach:** Record that the adapter builds the project but does not slice; that print time and filament mass remain external and are currently unobtainable on this host; and that the user opens the project in PrusaSlicer to confirm objects, placement, presets, and overrides. Test expectation: none — prose; `tests/test_skill.py` invariants stay green.

---

## Verification Contract

- Offline gate: `scripts/test.sh` (repo final gate). No live Fusion needed — this unit consumes an already-produced index.
- Manual confirmation (user, when convenient): open the generated project in PrusaSlicer and confirm the same objects, placement, presets, and overrides. This is the issue's last acceptance criterion and cannot be automated here.

## Definition of Done

R1–R9 implemented and tested; no code path executes the slicer; the slice step returns an explicit unsupported result; docs record the boundary; merged PR with post-merge proof and marketplace repin.
