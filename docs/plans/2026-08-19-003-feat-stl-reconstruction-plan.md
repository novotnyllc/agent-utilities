---
title: "feat: STL reconstruction — choose mesh edit, B-Rep conversion, or parametric rebuild"
date: 2026-08-19
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
origin: https://github.com/novotnyllc/agent-utilities/issues/20
---

# Summary

Add a bounded mesh-reconstruction workflow that **classifies the requested edit before converting anything**, records that choice as evidence, and executes only the path it chose: keep it a mesh, convert to faceted B-Rep, or rebuild the required geometry parametrically from extracted datums and sections. The source mesh is captured immutably with its hash, units, scale and coordinate frame before any edit. Every reconstruction is graded against that immutable source with an asymmetric verdict — omitted detail is advisory, invented material is a hard failure.

---

## Problem Frame

Downloaded and scanned STLs are routinely treated as though mesh-to-B-Rep conversion recovered an editable design. It does not. Dense conversion yields faceted, fragile geometry with no sketches, constraints, feature history, or design intent: a cylinder returns as a many-sided prism with no circular edge to select, and a fillet becomes thousands of facets. The skill currently has no mesh path at all, so an agent asked to "modify this STL" has nothing to follow and will reach for conversion because it is the one obvious button.

---

## Research basis

Two independent studies informed this plan; both are load-bearing and both changed it.

**Upstream prior art (`Shpigford/nurb`).** PR #41 built exactly the automatic primitive fitter this issue might tempt us toward — adjacency-grown planes, axis-constrained least-squares cylinders, curvature splitting, pitch detection. **It was closed and never merged**, and its fitter does not exist on main today. What upstream ships instead is measurement (`scan`: size, watertightness, units with a stated source, Douglas-Peucker cross-sections), a mesh→B-Rep **refusal ladder** with named reasons and a triangle ceiling, and a report-only comparison. The agent does the fitting; the tool measures. That is a strong signal about where the difficulty actually sits.

The single best idea in the abandoned PR — and upstream **lost it** in the rewrite — is the **asymmetric verdict**: rebuilt surface far from the original but *inside* it is omitted detail (advisory); rebuilt surface outside the original solid is *invented material* (hard failure, non-zero exit). Its companion rule matters as much: distances that feed a percentile may be sampled, but any distance compared against a threshold must be exact.

Upstream also has two gaps we must fill: **no content hashing anywhere** (provenance is a file path, so a moved file fails open and a changed file is silently re-measured), and **no path classification in code** — its three-way distinction lives only in prose addressed to a model.

**Commercial reference implementations.** "Revo Design Pro" is an OEM rebrand of **QUICKSURFACE** (KVS Ltd.), Windows-only; QUICKSURFACE's documentation is the primary source for its behavior. The mature reference is **Geomagic Design X**, and its command set validates this issue's thesis directly: `Auto Surfacing` blankets a mesh in NURBS patches and produces solids that "don't have a feature tree or shape identification" — a *"1-to-1 dummy CAD version of the mesh"* — while `Solid Primitive` fitting plus `Mesh Sketch` produce real features. **Three separate commands, and the tool makes the user choose.** Nobody automates that choice.

Both tools derive the coordinate frame **from fitted primitives** rather than aligning first, and both treat deviation as continuous feedback rather than a final gate. Geomagic's `Auto Sketch` — section polyline → line/arc classification → **automatic constraint inference** — is the step that actually recovers design intent, and it is a premium-gated feature in the reference implementation. That is where the difficulty is, and where AI judgment is worth spending.

---

## Fusion capability boundary (decisive, and it reshapes the plan)

- **`MeshConvertMethodTypes`** offers `Faceted`, `Prismatic`, and `Organic` (Organic needs the Design Extension). `ParametricFeatureMeshConvertOperationType` sounds like it recovers parameters; it does not — it only means the *convert operation* re-runs when the mesh changes. The resulting body has no sketches, dimensions, or constraints. The issue's thesis is correct.
- **Fusion's only native parametric route from a mesh — `Create Mesh Section Sketch` and `Fit Curves to Mesh Section` — has no API.** Both are UI-only; there is no `MeshSectionSketch` class and nothing on `Sketch` that creates one. `MeshPlaneCutFeature` is likewise absent. A skill driving Fusion over MCP cannot use them.
- **But the raw material is scriptable.** `MeshBody.mesh` returns a `PolygonMesh` exposing `nodeCoordinates`, `triangleNodeIndices`, and **`triangleFaceGroupTempIds`** — Fusion's own segmentation, readable per triangle. `MeshGenerateFaceGroupsFeature` (preview) produces those groups, and its `Accurate` method's `boundaryTolerance` is documented as being "used during the fitting of the primitives" — Fusion fits primitives internally but **never exposes the fit**, only the grouping.
- **The Sketch API is fully scriptable**, including geometric constraints and dimensions. So the UI-only gap is only the *section extraction*, which is ordinary plane–mesh intersection arithmetic we can do ourselves from `PolygonMesh` data.
- **`PolygonMesh.compareWith(other, transform, transformOther)`** (July 2026, **preview**) returns the signed distance from every node of one mesh to the closest point on another, in centimetres. This is the deviation mechanism, it is API-only with no UI equivalent, and it makes the compare-to-source requirement implementable.
- **Facet ceilings are unverified.** Secondary sources report a warning near 10,000 facets and an error at 50,000, but Autodesk's own pages state no number. `MeshConvertFeature` exposes `errorOrWarningMessage` and `healthState` — **read the refusal from Fusion, never hardcode a threshold.**
- Every mesh feature class is flagged **preview** ("never deliver programs that use preview capabilities"), and `MeshConvertFeatures.add` / `MeshGenerateFaceGroupsFeatures.add` **return null for non-parametric operations** even though the operation succeeds.

**Consequence:** path (c) is built on our own section extraction and fitting over `PolygonMesh`, emitting real constrained sketches through the Sketch API — not on Fusion's mesh tools.

---

## Requirements

- **R1. Immutable capture before anything.** Record source path, **SHA-256 of the file bytes**, triangle count, watertightness, oriented bounding box, and volume. The source mesh body is never modified, converted in place, or overwritten; every later operation works on a copy. Re-running against a changed file must fail closed on the hash, not silently re-measure.
- **R2. Units, scale and frame are stated, never assumed.** STL carries no unit. Record the unit together with **how it was determined** — `declared` (user or manifest), `file` (a format that carries it, e.g. 3MF), or `guess` (with the heuristic and the threshold that produced it) — and print that reason in the report. Record the applied alignment transform as part of the coordinate-frame evidence.
- **R3. Provenance is an input, not a derivation.** The workflow must record whether the mesh is a *designed export* or a *capture* (scan/photogrammetry), because **no mesh statistic distinguishes them** — a designed model scores like a capture on every computable measure. This flag governs whether fitted dimensions may be treated as exact or must stay provisional until a coupon proves them.
- **R4. Classify the edit before converting, and record the choice.** Exactly one of `mesh-edit`, `faceted-brep`, or `parametric-rebuild`, with a recorded rationale and the inputs that drove it. The classification is written to evidence *before* any geometry operation runs. An unclassified run cannot proceed.
- **R5. Prefer manufacturer B-Rep.** If a STEP or other B-Rep source exists, the workflow says so and prefers it — while recording explicitly that **STEP does not restore design intent**, and that a bundled STEP may not match the mesh people actually printed. Which source was trusted, and why, is recorded.
- **R6. Path A — mesh edit.** Keep the body a mesh, use Fusion's mesh tools, and never claim a parametric result. Legitimate when the object is a fixture to clear rather than a design to change.
- **R7. Path B — faceted conversion, with a refusal ladder.** Convert only after named, ordered checks: convertible source, watertight (else surface not solid), positive signed volume, facet count within what Fusion itself accepts — **read from `errorOrWarningMessage`/`healthState`, not a hardcoded limit** — and an *editability* check that measures whether the result has selectable faces to work with rather than merely that conversion succeeded. Each refusal names the reason and the alternative. The handoff labels the result **faceted**, never parametric.
- **R8. Path C — parametric rebuild.** Extract datums and sections from the immutable mesh, fit analytic primitives (plane, cylinder, cone, sphere) to face groups, derive the coordinate frame *from those primitives*, and emit **real constrained sketches and features** through the Sketch API. Only the geometry the edit actually requires is rebuilt — this is explicitly not a whole-part auto-converter.
- **R9. Design-intent inference is proposed, never asserted.** Near-coaxial, near-perpendicular, near-symmetric, and near-nominal values (is 10.03 mm meant to be 10?) are surfaced as **proposals with their deviations**, for confirmation. Snapping silently is how a scan-shaped model masquerades as a designed one.
- **R10. Asymmetric verdict against the immutable source.** Compare the reconstruction to the source via `PolygonMesh.compareWith`. Rebuilt material lying **outside** the source solid is *invented geometry* → hard failure naming the location. Source detail absent from the rebuild is *omitted detail* → advisory. Any distance compared against a threshold is exact; sampled distances feed percentiles only. Thresholds are declared and recorded, never global constants.
- **R11. Clearance and interference claims use a native positive-volume B-Rep envelope**, never a mesh-only occurrence — the existing verification contract already requires this, and it applies unchanged here.
- **R12. The handoff distinguishes the three outcomes** — mesh cleanup, faceted conversion, and true parametric reconstruction — and never lets the second be reported as the third. A fit coupon is required before any claim of physical mating.
- **R13. Preview-API honesty.** Every Fusion mesh feature used is preview and may move. Record the Fusion version with the evidence and fail closed with a clear message when an expected API is absent, rather than silently degrading.

---

## Non-goals

A universal automatic STL-to-parametric converter. Upstream built the fitter and abandoned it; the commercial tools gate constraint inference behind their premium tier and still require a human to choose the path. This workflow automates capture, classification, refusal, extraction and grading — and leaves intent inference as a proposal for judgment.

---

## Key Technical Decisions

1. **KTD1: Classification is a recorded gate, not a suggestion.** Both reference tools expose three separate commands and make the user choose; neither automates it. We automate the *recording and enforcement* of the choice, not the choice itself. This is the requirement no prior art implements in code.
2. **KTD2: Build path C on `PolygonMesh` + our own sectioning + the Sketch API.** Fusion's native mesh-to-sketch tools are UI-only, so they are unavailable to a skill driving the API. Plane–mesh intersection is arithmetic we control, and sketches with real constraints are fully scriptable — which is also what makes R9's proposals expressible as actual geometric constraints.
3. **KTD3: Read refusals from Fusion, never hardcode facet ceilings.** The widely-cited 10k/50k numbers are unverified and version-specific; `errorOrWarningMessage` and `healthState` are authoritative and self-updating.
4. **KTD4: Revive the asymmetric verdict that upstream dropped.** Invented material is categorically worse than omitted detail, and only a solid-containment test distinguishes them — otherwise the wall under a dropped boss reads as a false positive. Fusion gives us genuine B-Rep containment instead of a hand-rolled winding number.
5. **KTD5: Hash the bytes.** No upstream version binds a rebuild to specific source content. Without it, a changed source is silently re-measured and every downstream claim is unmoored.
6. **KTD6: Provenance is declared.** Since no statistic separates a designed export from a scan, the flag is an input that governs confidence, and fitted values from a capture stay provisional until a coupon proves them — reusing the material-decision confidence vocabulary from issue #21.

---

## Implementation Units

### U1. Immutable capture and provenance record

**Goal:** Manifest surface plus a read-only Fusion transaction that captures the source before any edit.

**Requirements:** R1–R3, R13.

**Files:** `src/fusion_design/mesh_source.py` (new), `src/fusion_design/manifest.py`, `schema/fusion-project.schema.json`, `tests/test_mesh_source.py`, `tests/test_manifest.py`.

**Approach:** A `mesh_sources` manifest section — id, path, sha256, `units` with `unit_source` (`declared`/`file`/`guess`), `provenance` (`designed_export`/`capture`), optional `brep_source` per R5, and the recorded alignment transform. Validation follows the `printable_parts.py` pattern exactly: closed enums via `_in_closed_set`, `_reject_unknown_fields`, kebab-case codes. The generated read-only transaction reports triangle count, `isClosed`, `isOriented`, `volume`, `orientedMinimumBoundingBox`, and the Fusion version, using the existing stdout report protocol.

**Test scenarios:** hash mismatch against the recorded value fails closed; missing unit source rejected; `guess` without a stated heuristic rejected; unknown provenance rejected; unhashable values in every enum yield issues not `TypeError`; the emitted script contains no mutating API call.

---

### U2. Path classification gate

**Goal:** Record exactly one path with its rationale, before any geometry operation.

**Requirements:** R4, R12.

**Files:** `src/fusion_design/mesh_reconstruction.py` (new), `tests/test_mesh_reconstruction.py`, `references/mesh-reconstruction.md` (new).

**Approach:** A `classify(request, source_record) -> Classification` returning the path, rationale, and the inputs that drove it (edit kind, provenance, watertightness, facet count, whether a B-Rep source exists). The doctrine reference carries the decision guidance — local/cosmetic edit or clearance-only use → `mesh-edit`; low-facet mechanical part needing a boolean → `faceted-brep`; dimensional or structural change → `parametric-rebuild`. Downstream entry points **refuse to run without a classification record**, which is what makes this a gate rather than advice.

**Test scenarios:** each path selected for its archetype; an unclassified request refuses; a classification whose rationale is empty is rejected; the record round-trips into the handoff.

---

### U3. Path B — faceted conversion with a refusal ladder

**Goal:** Convert only when it will produce something usable, and label it faceted.

**Requirements:** R7, R12, R13.

**Files:** `src/fusion_design/mesh_reconstruction.py`, tests.

**Approach:** Ordered named refusals — non-convertible source, not watertight (surface not solid), negative signed volume (inverted normals), and Fusion's own conversion complaint surfaced from `errorOrWarningMessage`/`healthState`. Then an **editability check**: count the faces on the result and compare against the face groups, so "converted successfully into 9,000 unselectable facets" is reported as a poor outcome rather than a success. Handle the documented `add` → `null` return for non-parametric operations rather than assuming a feature object.

**Test scenarios:** each refusal fires with its named reason and no geometry is created; a low-facet prismatic mesh converts and is labeled `faceted`; a dense mesh is refused with Fusion's own message quoted; the result is never labeled parametric.

---

### U4. Path C — section extraction, primitive fitting, constrained sketch emission

**Goal:** Rebuild only the geometry the edit requires, parametrically.

**Requirements:** R8, R9, R11.

**Files:** `src/fusion_design/mesh_reconstruction.py` (or a sibling if it grows past ~700 lines), tests.

**Approach:** Read `PolygonMesh` node coordinates, triangle indices and `triangleFaceGroupTempIds`. Per face group, fit plane / cylinder / cone / sphere by least squares with a **relative** residual gate plus sanity gates (a near-flat strip fits an enormous circle centred outside the part — reject when the fitted axis lies outside the part bounds). Derive the coordinate frame from the fitted primitives, per both reference tools. Compute plane–mesh section polylines ourselves, classify segments into lines and arcs, and emit **real sketch geometry with geometric constraints and dimensions** through the Sketch API.

Per R9, coaxiality, perpendicularity, symmetry and nominal-value snapping are emitted as **proposals with their measured deviation** for confirmation — never applied silently.

**Execution note:** build the section-extraction and fitting math offline against synthetic meshes with known answers (a box, a cylinder, a cylinder at a known angle) before touching Fusion; the geometry is where the bugs will be, and it is fully testable without the live API.

**Test scenarios:** a synthetic box yields six planes with correct normals and offsets; a synthetic cylinder yields the correct axis and radius; an off-axis cylinder is either fitted correctly or explicitly reported unfitted, never silently wrong; a near-flat strip is rejected rather than fitted as a huge circle; sections through known geometry produce the expected polylines; near-coaxial features surface as a proposal carrying the deviation rather than being snapped.

---

### U5. Deviation verification and the asymmetric verdict

**Goal:** Grade the reconstruction against the immutable source, honestly.

**Requirements:** R10, R11, R12.

**Files:** `src/fusion_design/mesh_reconstruction.py`, tests, `references/verification-contract.md`.

**Approach:** Tessellate the reconstruction and call `PolygonMesh.compareWith` against the source. Split by containment: rebuilt material outside the source solid is **invented** → hard failure naming coordinates; source detail missing from the rebuild is **omitted** → advisory. Containment uses a native B-Rep query, satisfying R11. Percentiles may use sampled distances; **any value compared against a threshold is measured exactly**. Thresholds are declared per reconstruction and recorded with the verdict — not module constants. Fail closed with a clear message when `compareWith` is unavailable in the connected Fusion.

**Test scenarios:** a rebuild with material outside the source fails and names the location; a rebuild missing a boss is advisory, not a failure; the wall beneath a dropped boss does not false-positive as invented; a missing `compareWith` API fails closed rather than skipping the check; declared thresholds appear in the verdict record.

---

### U6. Doctrine, workflow and acceptance

**Goal:** The agent-facing surface.

**Files:** `references/mesh-reconstruction.md`, `SKILL.md`, `references/capability-matrix.md`, `references/unsupported.md`, `templates/DESIGN-STATE.md`, `docs/live-fusion-acceptance.md`, both plugin manifests.

**Approach:** Doctrine states plainly what conversion does and does not recover, the three paths and when each is right, that STEP does not restore design intent, that a bundled STEP may not match the shipped mesh, and that a capture's fitted values stay provisional until a coupon proves them. `unsupported.md` records what we deliberately do not do: whole-part auto-conversion, organic/freeform surface recovery, and automatic design-intent assertion. `SKILL.md` adds the classification gate. Live acceptance covers a marketplace STL with a dimensional modification, per the issue's acceptance criterion. Add the new reference to SKILL.md — `tests/test_skill.py` asserts every referenced file exists.

---

## Verification Contract

- Offline gate: `scripts/test.sh`. The geometry math (sectioning, fitting, verdict logic) is tested against synthetic meshes with known analytic answers — no Fusion required.
- Live gate (single Fusion instance): the issue's acceptance case — a marketplace STL with a dimensional modification — exercising capture, classification, the chosen path, and the deviation verdict. Record the Fusion version, since every mesh API used is preview.

## Definition of Done

R1–R13 implemented and tested; the chosen path recorded before any geometry operation; the source mesh never modified and bound by hash; units and provenance stated with their source; faceted results never reported as parametric; the asymmetric verdict enforced with exact measurement at the threshold; a fit coupon required before any mating claim; merged PR with post-merge proof and marketplace repin.
