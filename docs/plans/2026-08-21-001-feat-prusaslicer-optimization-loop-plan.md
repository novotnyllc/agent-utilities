---
title: "feat: PrusaSlicer optimization loop - intent-driven candidate slicing and scoring"
date: 2026-08-21
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
---

# Summary

Extend the fusion-parametric-design PrusaSlicer integration from declare-and-execute to a bounded optimization loop: wider justified overrides driven by print intent, automatic orientation search, mesh-derived structural proxies, a slice-in-the-loop evaluator ranking real candidates by measured time/mass, full support-strategy expression (style, soluble/multi-material assignment, painted regions), printer-capability awareness, a pure-Python binary-G-code reader replacing forced ASCII output, and a preset-drift guard binding profile state into the slice evidence chain.

## Product Contract

### Problem Frame

The adapter today validates human-declared intent and executes one slice. Five settings keys are expressible; orientation is a single applied rotation; nothing compares candidates; binary G-code is disabled to keep parsing simple; preset state can change between build and slice undetected; multi-material and painted supports are unrepresentable. The owner needs optimal settings per scenario - fastest wall-clock while structurally sound, fine detail, enclosures - across printers, materials, and support strategies. The machinery to measure real slices with hash-bound evidence exists; what is missing is the decision layer around it.

### Requirements

- **R1.** Print intent (fast-structural / fine-detail / enclosure) extends the manifest schema and drives an expanded justified-override vocabulary: speed, layer height, support style (organic/grid/snug), seam, brim - every key still fail-closed, still requiring declared justification.
- **R2.** Orientation search: declared allowed_alternatives become real candidates; when none are declared, all six bed-contact orientations are enumerated. Every orientation is sliced and measured, never assumed.
- **R3.** Structural proxies computed from exported meshes (overhang-area fraction below threshold angle, maximum unsupported span, vertical wall fraction) rank candidates without waiting on physical coupons. Proxies are advisory ranking inputs, never printed structural claims; coupon doctrine is unchanged.
- **R4.** A slice-in-the-loop evaluator generates a bounded candidate set (orientation x intent-derived setting variants, hard-capped), slices each through the existing complete-profile-set path, ranks by a per-intent objective over measured time, mass, and proxy scores, and reports the ranking bound to the full evidence chain. Deterministic ordering.
- **R5.** Support-strategy depth: style keys map to PrusaSlicer values; support material may be assigned to a distinct extruder/filament (soluble workflow), validated against the printer extruder count; enforcer/blocker painted regions are expressible when their 3MF encoding can be produced deterministically (see KTD5).
- **R6.** Printer capability facts (extruder count, multi-head layout) read from the printer preset constrain candidate generation instead of being invisible.
- **R7.** A pure-Python binary-G-code reader decodes bgcode containers (gzip/deflate and heatshrink blocks) well enough to recover the trailing statistics block; slicing defaults to binary G-code, ASCII remains selectable, and statistics parsing works identically either way.
- **R8.** Preset-state drift guard: resolved preset files hashed at build time, carried in bindings, re-verified before slicing; changed profiles between build and slice are structured failures.
- **R9.** Release coupling honored: plugin manifests bumped, marketplace repin triggered, docs updated to describe the optimization lane and its boundaries.
- **R10.** Existing behavior preserved: current five-key path, segfault guard, hash-chain binding, deterministic zips, and all present tests remain green.

### Success Criteria

- An optimize run produces a ranked report whose numbers come from decoded binary-G-code statistics, with orientation and settings provenance per candidate.
- Every new override key traces to declared intent; unjustified keys fail closed by test.
- The drift guard demonstrably rejects a modified preset between build and slice.
- Physical-print acceptance remains explicitly human-owned; no report claims structural safety.

### Scope Boundaries

- Plate packing/nesting improvements deferred; the conservative packer stays.
- No new UI surface; deliverable is library + CLI.
- No estimated unsliced numbers enter any report.
- Windows binary auto-discovery remains out of scope (explicit flag continues).

## Planning Contract

### Key Technical Decisions

1. **KTD1 (session-settled):** Pure-Python stdlib-first throughout; the bgcode reader is in-package (zlib plus small heatshrink decoder), chosen over compiled dependencies or a TypeScript rewrite.
2. **KTD2 (session-settled):** All optimization evidence comes from real headless slices with the complete profile set; the partial-set refusal and hash-chain binding from the segfault fix are preserved verbatim.
3. **KTD3:** Bounded deterministic candidate space: intent derives a fixed variant matrix within preset-safe bounds, hard cap of 12 candidates per part, no open-ended search.
4. **KTD4:** Per-intent objective combines measured time, total mass, and proxy penalties with fixed weights recorded in the report; weights are constants in code, not user-tunable config.
5. **KTD5:** Painted-region support rides a feasibility gate: deterministic triangle-attribute encoding is probed first; if unreliable headless, explicit-regions keeps failing closed with an upgraded reason while style/soluble support ships regardless.
6. **KTD6:** Multi-material assignment maps support material to an extruder index validated against the declared extruder count; invalid indices fail closed.
7. **KTD7:** Drift guard hashes each resolved preset file at build time; slice time re-hashes and refuses on mismatch. Profile hashes join the evidence chain.
8. **KTD8:** Binary G-code becomes default slice output; ASCII stays available via explicit option; statistics extraction routes through the bgcode reader transparently.

### Assumptions

- The bgcode container follows the published open format (magic header, block table, per-block compression flags); deviations fail closed with ASCII as fallback.
- Heatshrink blocks carry window/lookup-bit parameters in headers; the decoder reads parameters rather than assuming them.
- Printer preset ini exposes enough extruder/filament list structure to validate counts without invoking the binary.

## Implementation Units

### U1. Binary G-code reader

**Goal:** New prusaslicer_bgcode.py decodes bgcode containers well enough to return the trailing statistics text; prusaslicer_slice.py gains a gcode_format option (default binary) and routes parsing through the reader.

**Files:**
- plugins/agent-utilities/skills/fusion-parametric-design/src/fusion_design/prusaslicer_bgcode.py
- plugins/agent-utilities/skills/fusion-parametric-design/src/fusion_design/prusaslicer_slice.py
- plugins/agent-utilities/skills/fusion-parametric-design/tests/test_prusaslicer_bgcode.py
- plugins/agent-utilities/skills/fusion-parametric-design/tests/test_prusaslicer_slice.py

**Approach:** Parse container header and block index; decode gzip/deflate via zlib; implement heatshrink decode from block-header parameters; concatenate gcode block payloads; hand the text to the existing summary_block / parse_gcode_statistics. Unknown block types are skipped; malformed containers raise a typed error surfacing as the existing structured failure shape. Fixtures are hand-built minimal containers constructed inside the tests.

**Test scenarios:** gzip-only container round-trips statistics; heatshrink container decodes with header-declared parameters; mixed block order tolerated; truncated or corrupt container raises named failure; the unconditional --binary-gcode=0 is gone and the ASCII option still produces identical parsed statistics; existing summary-parsing tests pass unchanged against reader output.

### U2. Intent schema and override-vocabulary extension

**Goal:** Manifest schema accepts print_intent plus extended strength/detail fields; ALLOWED_OVERRIDE_KEYS grows (speed, layer height, support style, seam, brim) with per-key justification rules; organic/grid/snug styles map to PrusaSlicer values.

**Files:**
- plugins/agent-utilities/skills/fusion-parametric-design/src/fusion_design/printable_parts.py
- plugins/agent-utilities/skills/fusion-parametric-design/src/fusion_design/prusaslicer_project.py
- plugins/agent-utilities/skills/fusion-parametric-design/schema/fusion-project.schema.json
- corresponding tests: test_printable_parts.py (or equivalent), test_prusaslicer_project.py

**Approach:** Follow the existing fail-closed validator pattern: new fields validated (enum intents, numeric bounds, justification linkage), unknown keys rejected, schema and Python kept in lockstep per the existing lockstep test. Overrides derive only from declared fields; each new key documents its justifying fields in the validation error when absent.

**Test scenarios:** each intent enum value accepted and rejected correctly; speed and layer-height overrides require intent-appropriate declarations; support style maps to expected PrusaSlicer values; unknown override key still exits 2 with the available-keys message; schema lockstep test extended.

### U3. Orientation enumeration and candidate generation

**Goal:** Candidate builder produces the orientation set (declared alternatives or all six faces) and the intent-derived setting variants (bounded per KTD3), yielding a deterministic candidate list consumed by U5.

**Files:**
- plugins/agent-utilities/skills/fusion-parametric-design/src/fusion_design/orientation_candidates.py (new)
- plugins/agent-utilities/skills/fusion-parametric-design/src/fusion_design/prusaslicer_project.py (rotation reuse)
- plugins/agent-utilities/skills/fusion-parametric-design/tests/test_orientation_candidates.py

**Approach:** Reuse rotation_for_contact_face; dedupe alternatives against the primary face; cap enforcement raises a named error rather than truncating silently. Setting variants expand only keys the extended vocabulary legally expresses for that intent.

**Test scenarios:** declared alternatives yield exactly those faces; empty alternatives yield all six unique faces; duplicate alternative rejected; cap breach fails named; candidate list byte-deterministic for identical inputs.

### U4. Mesh structural proxies

**Goal:** Offline proxy computation from exported meshes: overhang-area fraction below threshold angle, maximum unsupported span, vertical wall fraction; emitted per part into the candidate report.

**Files:**
- plugins/agent-utilities/skills/fusion-parametric-design/src/fusion_design/mesh_strength_proxies.py (new)
- plugins/agent-utilities/skills/fusion-parametric-design/tests/test_mesh_strength_proxies.py

**Approach:** Triangle-winding normal scan over the parsed 3MF mesh (zipfile plus ElementTree, matching existing mesh readers); threshold angle constant aligned with existing conservative assumptions; spans approximated by longest horizontal extent of downward-facing connected clusters. Advisory-only: report fields carry a proxy marker and never appear as structural claims.

**Test scenarios:** flat plate yields zero overhang fraction; tilted fixture yields expected fraction within tolerance; vertical wall fraction 1.0 for a box side; degenerate empty mesh fails closed; proxy markers present in output.

### U5. Slice-in-the-loop optimizer with drift guard

**Goal:** New prusaslicer_optimize.py orchestrates U3 candidates through build, slice, measure, rank; per-intent objective (KTD4) over measured time/mass/proxies; report bound to the full chain including preset-file hashes (KTD7 drift guard); CLI subcommand wired in cli.py.

**Files:**
- plugins/agent-utilities/skills/fusion-parametric-design/src/fusion_design/prusaslicer_optimize.py (new)
- plugins/agent-utilities/skills/fusion-parametric-design/src/fusion_design/cli.py (subcommand wiring)
- plugins/agent-utilities/skills/fusion-parametric-design/src/fusion_design/prusaslicer_project.py (preset hashing export)
- tests: test_prusaslicer_optimize.py, additions to test_cli.py

**Approach:** Each candidate gets its own project file (existing no-overwrite discipline; temp dir per run, cleaned on completion, retained on failure for diagnosis); slices run sequentially through slice_project preserving guards; ranking sorts deterministically by score then time then candidate id; per-candidate failures rank last with their failure recorded and never abort the whole run unless every candidate fails. Preset hashes are captured at resolve time and verified again immediately before each invocation; mismatch aborts with a structured failure naming the drifted preset.

**Test scenarios:** three-candidate fake-runner run ranks by injected times; all-fail run returns structured failure not crash; drift-guarded preset change aborts pre-invocation; report contains chain hashes and proxy markers; cap enforced end-to-end; CLI exits 0 with best-candidate summary and 2 when nothing sliced.

### U6. Support-strategy depth (multi-material plus painted-regions gate)

**Goal:** Soluble/multi-material support assignment validated against printer extruder count; painted enforcer/blocker regions behind the KTD5 feasibility gate.

**Files:**
- plugins/agent-utilities/skills/fusion-parametric-design/src/fusion_design/prusaslicer_project.py
- plugins/agent-utilities/skills/fusion-parametric-design/src/fusion_design/printable_parts.py (support material declaration fields)
- schema and tests as in U2

**Approach:** Extruder-count source is the printer preset ini extruder/filament list length; assignment writes per-volume extruder metadata following the multi-tool encoding observed in real projects (verified against the installed 2.9.6 writer during implementation). Painted regions: probe whether triangle-level support-painting attributes survive a deterministic headless write/read cycle; ship only if provable, else upgrade the refusal reason per KTD5. Must not regress the single-material path.

**Test scenarios:** valid extruder index assigned and serialized; out-of-range index fails closed; single-material project output byte-identical pre/post change (regression pin); painted-region probe outcome recorded either way; refusal reason names the missing capability when gate closes.

### U7. Documentation, release coupling, final gate

**Goal:** Docs describe the optimization lane honestly (what is measured, what remains human-owned); manifests bumped; repin triggered; full verification green.

**Files:**
- plugins/agent-utilities/skills/fusion-parametric-design/SKILL.md
- plugins/agent-utilities/skills/fusion-parametric-design/references/capability-status.md
- plugins/agent-utilities/skills/fusion-parametric-design/references/unsupported.md
- both plugin.json manifests (version bump)

**Approach:** Capability table gains the optimization row with its boundaries; SKILL.md documents the CLI subcommand, candidate caps, and the physical-acceptance boundary; release coupling per repo doc.

**Test scenarios:** skill-cleaner suite passes; frontmatter and name checks pass; no stale always-ASCII claims remain.

## Verification Contract

- Offline gate: full Python test suite for the skill plus the repo skill-cleaner command and manifest/frontmatter checks.
- Live gate (user-hosted, one bounded run): prusaslicer-optimize against the real Prusa XL datadir on a small project produces a ranked report with decoded binary-G-code statistics; captured as evidence in the PR description.
- Regression pins: single-material project output byte-identical pre/post (U6); existing slice tests green unchanged (U1).
- Physical print/dry-fit acceptance remains explicitly outside automated proof.

## Definition of Done

R1-R10 satisfied with tests; U1-U7 complete; live optimize run evidence attached; docs truthful about capabilities and boundaries; manifests bumped and marketplace repin confirmed; merged PR with post-merge proof (merge commit ancestor of origin/main, smallest post-merge check green).
