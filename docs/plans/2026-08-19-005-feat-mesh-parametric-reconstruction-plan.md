---
title: "feat: mesh-to-parametric reconstruction — segmentation, datum frame, feature emission, editability proof"
date: 2026-08-19
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
origin: https://github.com/novotnyllc/agent-utilities/issues/20
supersedes_none: true
builds_on: docs/plans/2026-08-19-003-feat-stl-reconstruction-plan.md
---

# Summary

Plan 003 shipped the **analysis** half of issue #20: immutable capture, the three-way classification gate, the faceted refusal ladder, the asymmetric deviation verdict, and 1474 lines of validated pure-Python sectioning, primitive fitting and design-intent proposal. None of it is wired to anything, and none of it emits geometry.

This plan builds the **reconstruction** half: get the mesh out of Fusion into a hash-bound dump, segment it into regions, fit and *disprove* a primitive per region, derive a datum frame with deterministic tie-breaks, infer relationships, emit real constrained sketches and extrude/revolve/hole features through the Sketch API, and prove the result is editable by **changing a parameter and recomputing** — not by asserting a document-level fact.

Partial reconstruction is a first-class declared outcome. A run that honestly rebuilds 70% of a part and names the other 30% as unreconstructed is a success with a stated coverage fraction; a run that silently fits a cylinder to something that is not a cylinder is the failure this plan is designed around.

Three decisions in here are worth reading before the rest:

- **The architecture is a hybrid** (KTD1): host-side stdlib for all numerics — segmentation, fitting, inference, datum derivation, fully testable offline under `scripts/test.sh` with no Fusion running — and a **versioned, hash-bound, closed-vocabulary reconstruction program** handed to Fusion, whose API does all B-Rep construction and solving. That program is part of the evidence chain, not a convenience format.
- **No new dependency — and note that the recommendation survived its premise being falsified** (KTD2). The first draft argued partly that numpy *cannot* load in Fusion. That was wrong: a live probe (F4) loaded numpy 2.5.2 from a `cp314` wheel and ran compiled LAPACK inside Fusion. The recommendation is unchanged because it never rested on that claim. What holds it up: **offline testability** — U2, the crux, is fully provable under `scripts/test.sh` with no Fusion running; **nurb's empirical result** — the full OCCT + numpy + scipy stack and still no editable timeline, because no library has one; and a **new argument the corrections created** — the risk is wheel *availability*, not delivery: delivery is one pip command (F4b), but scipy has no `cp314` wheel today (F4c), and Fusion auto-updates its Python on a schedule upstream maintainers do not follow.
- **Segmentation on noisy scan data is the crux, and it is gated before it runs** (KTD5): when the mesh's own measured normal-noise floor approaches the declared crease threshold, region boundaries *are* the noise and every downstream residual is consistent with the wrong region. That case refuses. Some real scans will refuse, and that is correct.

---

## Problem Frame

Plan 003's own doctrine already says where it stops. `references/mesh-reconstruction.md` lines 101–102 state it plainly: *"Coordinate-frame derivation from the fitted primitives is not implemented … Sketch API emission is not implemented."* `references/unsupported.md` repeats it. So the gap is documented; what is missing is the work.

What exists today, verified by reading the code rather than by report:

- `src/fusion_design/mesh_fitting.py` (1474 lines) implements plane–mesh sectioning with named degeneracy handling, greedy line/arc polyline classification, least-squares plane/cylinder/cone/sphere fitting with relative-residual + radius-ratio + bounds-margin gates, and `propose_design_intent` covering coaxial / parallel / perpendicular / symmetric / nominal.
- **It has no production caller.** `grep -rn 'mesh_fitting'` across the skill returns only `tests/test_mesh_fitting.py` and three prose mentions in `references/`. It is dead code with a good test suite.
- **No Fusion construction API is called anywhere.** `grep` for `sketches.add`, `sketchCurves`, `addByTwoPoints`, `geometricConstraints`, `sketchDimensions`, `extrudeFeatures`, `revolveFeatures`, `loftFeatures`, `constructionPlanes`, `holeFeatures`, `filletFeatures` across `src/` and `references/` returns **zero hits**. The only `createInput` in `src/` is `mesh_convert.py:278`, the faceted convert the skill refuses.
- **Nothing transports mesh data.** `mesh_source.py` reports triangle *counts* from inside Fusion; `mesh_deviation.py` reads `nodeCoordinates` inside Fusion and returns percentiles. No path moves vertices and triangles to the host where `mesh_fitting.py` lives. The fitting code and the data it needs are in different processes.

So the pipeline has a head (capture, classification), a tail (deviation verdict), and a fully-tested middle that is not connected to either end and could not be, because the wire does not exist.

---

## Verified facts vs assumptions

Facts are things I read in this repository, in Autodesk's documentation as already recorded by plan 003, or confirmed by running a command. Assumptions are things I believe but have not proven, and each is marked with what would settle it.

### Verified facts

**F1.** `mesh_fitting.py` has no importer outside its own test file. Confirmed by `grep -rn 'mesh_fitting'` over the whole skill directory.

**F2.** No Fusion sketch or feature construction API appears anywhere in the skill. Confirmed by grep over all construction verbs listed above.

**F3.** `mesh_fitting.propose_design_intent` already emits **five** of the seven relationship kinds this plan needs: `INTENT_KINDS = {"coaxial", "parallel", "perpendicular", "symmetric", "nominal"}` (`mesh_fitting.py:42`). **Correction to the brief:** the "only parallel plane pairs and parallel-axis cylinder pairs" limitation is specific to `_symmetry_proposal` (`mesh_fitting.py:1414–1474`), which handles exactly those two cases and returns `None` otherwise. Coaxial, parallel and perpendicular are general over any two fits with a direction. **Genuinely missing: `tangent` and `equal_radius`.**

**F4. — CORRECTED 2026-08-19 by live probe. The earlier version of this fact was wrong, and it was load-bearing.** Fusion's embedded Python **runs third-party wheels, including native extensions.** See `docs/solutions/fusion-python-supports-wheels.md`. Probed live:

- Fusion's Python is **3.14.0**; `EXT_SUFFIX = .cpython-314-darwin.so`; `sysconfig.get_platform() = macosx-10.15-universal2`.
- `secrets`, `sqlite3`, `ctypes` and `ensurepip` **all import**. The `references/mcp-adapter.md:50–58` note claiming `secrets` and `sqlite3` failed is **stale and must be corrected in U6**.
- `numpy` raised `ModuleNotFoundError` — **not installed**, not unloadable. A different problem entirely.
- `sys.path` already contains a user-writable directory: `~/Library/Application Support/Autodesk/Autodesk Fusion 360/MyScripts/ManuallyInstalled/`.
- Installing the `cp314` / `macosx_11_0_arm64` numpy 2.5.2 wheel and putting it on `sys.path` inside a Fusion script gives a working `numpy.linalg.eigh` — **the compiled LAPACK path executes**.

The real constraint is a packaging one: **the wheel must match Fusion's interpreter tags, not the host's.** What the original note's *guidance* recommended — heavy processing host-side — remains sound advice, but for reasons that have nothing to do with capability (KTD2).

**F4b. — added 2026-08-19. Cross-target dependency installation for Fusion is a solved problem, and the tool is pip.** Verified by running it:

```bash
python3 -m pip install --only-binary=:all: \
  --python-version 3.14 --implementation cp --abi cp314 \
  --platform macosx_11_0_arm64 --target <dir> <packages>
```

- `pandas` → resolved `numpy-2.5.2`, `pandas-3.0.5`, `python_dateutil-2.9.0.post0`, `six-1.17.0`. **Transitive resolution works against foreign tags**, not just single-wheel downloads.
- `trimesh` → resolved `trimesh-5.0.0` + `numpy-2.5.2`.
- `scipy` → **no `cp314` / `arm64` wheel exists yet.** See F4c.

The install target needs no invention either: `~/Library/Application Support/Autodesk/Autodesk Fusion 360/MyScripts/ManuallyInstalled/` is **already on Fusion's `sys.path`** (F4), and installing anywhere plus a `sys.path.insert` also works — numpy 2.5.2 was imported and ran `linalg.eigh` inside Fusion from `/tmp`.

**F4c. — the one real constraint, and it is live today.** Fusion runs Python **3.14.0**, new enough that parts of the scientific stack have not published wheels for it. numpy has. trimesh has. **scipy has not.** This is temporary and discoverable by running the command above — and it is a present fact, not a hypothetical risk.

**F5.** The module-bundle cache refuses native extensions: `references/mcp-adapter.md:86–88`, *"Only regular `.py` files are supported … compiled/native extensions are intentionally excluded."* Given F4 and F4b this is a **scope boundary, not a capability gap**: `module_cache.py` exists to deliver *our own* code with content addressing, `O_NOFOLLOW`, ownership checks and verified imports. Third-party wheels are pip's job, and pip already does them better than a bespoke mechanism would.

**F6.** The host-side entry point is `scripts/fusion-design`, a 7-line `/bin/sh` shim that sets `PYTHONPATH` and runs `python3 -m fusion_design.cli`. There is no venv, no `pyproject.toml` install step, and no dependency resolution anywhere in the skill.

**F7.** The gate is `plugins/agent-utilities/skills/fusion-parametric-design/scripts/test.sh`: `python3 -m unittest discover -s tests -v` followed by `python3 -m compileall -q src tests`. Not pytest.

**F8.** Example scripts are byte-pinned. `tests/test_golden_path.py:35–48` asserts `emit_positive_control_script(manifest) == (GENERATED / "positive_control.py").read_text(...)` and likewise for `export.py`. `tests/test_scripts.py:85–97` pins the rest. Any emitter change requires regenerating the checked-in example.

**F9.** `mesh_convert.py:123–131` already reads `PolygonMesh.triangleFaceGroupTempIds` — but only to count distinct groups. **Fusion's own per-triangle segmentation is already reachable and already partly plumbed.**

**F10.** `positive_control.py:287–306` creates geometry via `TemporaryBRepManager.get().createBox()` inside a `component.features.baseFeatures.add()` edit block. This is the skill's existing pattern for putting a temporary B-Rep into a parametric design — and it is **not parametric geometry**. A base feature is an opaque container; its body recomputes without responding to any parameter. This is directly relevant to R11.

**F11.** `mesh_source.py:451–476` already captures `isClosed`, `isOriented`, `volume`, `triangleCount` and the oriented bounding box per mesh body, with an `unavailable` list rather than nulls.

**F12.** `PolygonMesh.compareWith` is preview (July 2026) and `mesh_deviation.py:397` already records its sign convention as *an assumption to confirm once per Fusion version* — the existing code is already honest about this.

**F13.** Fusion's Mesh Section Sketch and Fit Curves to Mesh Section are UI-only; there is no `MeshSectionSketch`, nothing on `Sketch` that creates one, and no `MeshPlaneCutFeature` (`references/unsupported.md`, plan 003's capability boundary).

### Assumptions — not facts

**A1. `triangleFaceGroupTempIds` is populated on an arbitrary imported mesh.** The name says *temp ids*, and plan 003 records that `MeshGenerateFaceGroupsFeature` is what produces them. A freshly imported STL that has never had that feature run may report a single group covering every triangle, or none at all. **Settled by:** running U1's extraction against a marketplace STL in live Fusion and recording the group histogram. Until then, U2 must not depend on Fusion's grouping being present or meaningful.

**A2. Fusion's face grouping is good enough to fit against on a noisy scan.** Plan 003 records that `MeshGenerateFaceGroupsFeature`'s `Accurate` method has a `boundaryTolerance` "used during the fitting of the primitives", so Fusion fits internally — but it never exposes the fit, only the grouping, and we have no measurement of that grouping's quality on scan data. **Settled by:** the same live run, comparing Fusion's groups against our own segmentation on the same mesh.

**A3. Temp ids are not stable across sessions or across a mesh edit.** The naming strongly implies this and Fusion's `tempId` convention elsewhere confirms the pattern, but I have not verified it for this specific property. **Consequence either way:** region identity in the fit record must be re-derived geometrically (by a canonical hash of the region's sorted triangle indices in the hash-bound dump), never carried by temp id. Designing for the pessimistic case costs nothing.

**A4. Writing a file from inside Fusion's Python and reading it from the host works.** `os` and `tempfile` are confirmed importable (F4) and Fusion runs on the same machine as the MCP host, so this should hold. **Settled by:** U1's first live run. If it does not hold, the fallback is chunked base64 over the existing stdout report protocol, which is slower and size-limited but needs no new capability — U1 must implement the sentinel that tells them apart rather than assuming.

**A5. A pure-Python pipeline is fast enough at a realistic triangle count.** I have not benchmarked it. Region growing is O(n) dict operations; fit-driven splitting re-runs eigen-decomposition per candidate subregion and is the expensive part. **Settled by:** a benchmark in U2 against synthetic meshes at 10k / 50k / 200k triangles, recorded in the plan's follow-up. Design response: a **caller-declared triangle budget** that refuses above it rather than running for an unbounded time.

**A6. Fusion's sketch solver will accept our inferred constraint sets.** It may reject an over-constrained sketch, or silently move geometry to satisfy a constraint. **Settled by:** U5's live run. Design response in KTD7: constraints are applied one at a time with a geometry-displacement check and per-constraint rollback, never as a batch.

---

## Prior art

### `Shpigford/nurb` — investigated directly, and the findings changed this plan

The repository was cloned and read (`gh` CLI worked; no inference from the name was needed). Everything below is from the source at `main` as of 2026-08-18 (version 0.21.0) and from PR #41 at ref `issue-39`.

**What it is.** "Agentic CAD for 3D printing": Python 3.13+, a CLI plus a local WebSocket viewer, plus a skill file it installs into `~/.claude/skills/nurb/`. Not an MCP server. The model is that **an LLM hand-writes build123d Python part files**; nurb builds them, runs printability checks, serves a live viewer with parameter sliders, and exports.

**What it sits on — and this is the finding that settles KTD2.** Four declared dependencies: `build123d>=0.11.1`, `trimesh>=4.12.2`, `watchdog`, `websockets`. Transitively that pulls **`cadquery-ocp-novtk` 7.9.3.1.1 — OpenCASCADE 7.9 Python bindings** — plus numpy 2.5.1, scipy 1.18.0, scikit-learn 1.9.0, lib3mf, ezdxf.

So nurb has the entire heavy toolchain: OCCT, numpy, scipy, trimesh. **And it still cannot deliver an editable CAD timeline.** Its export formats are `3mf`, `stl`, `step`, `glb`; the STEP opens in Fusion as a dumb solid with no feature tree. The only thing in nurb that is genuinely parametric is **the Python source file** — `nurb dev` gives a slider per parameter and writes the number back into the `.py`. That is a legitimate design, and it is not what issue #20 asks for. This is empirical confirmation of KTD2's argument rather than a prediction: **a second B-Rep kernel does not produce a Fusion timeline, no matter how good it is.**

**How much of the chain `main` implements today — blunt answer: none of it.** `src/` is 9,062 lines across 24 files.

| Stage | Status on `main` | Evidence |
| --- | --- | --- |
| Mesh segmentation | **Absent** | No adjacency graph, no region growing, no union-find anywhere in `src/` |
| Primitive classification | **Absent** | Nothing classifies plane/cylinder/sphere/cone from a mesh. `probe.py` inspects faces of an *already-built B-Rep part*, never a mesh |
| Primitive fitting | **Absent** | No `lstsq`, no circle/plane/cylinder fit in `src/` |
| Constraint inference | **Absent** | No pitch, grid, coaxiality or symmetry detection |
| Feature emission | **Prose instructions to an LLM** | `src/nurb/skill.md` tells the agent in English "I can't edit that file directly, but I can measure it and rebuild it"; the agent then hand-writes build123d |

What `main` *does* have is measurement: `scan.py` (321 lines) loads STL/OBJ/GLB, resolves units, welds vertices, and slices **one** section plane; `compare.py` (166 lines) samples 1,500 points per side and reports exact point-to-triangle distance in both directions with a viewer ghost overlay; `mesh.py` (174 lines) is an `import_stl` that converts flat-faced meshes under a 2,000-triangle ceiling and refuses everything else by name. It measures the gap. It does not close it.

**PR #41 — closed unmerged, and it matters who filed the issue.** Opened 2026-07-29 by the repo owner from branch `issue-39`, 12 files, **+974/−9**, titled "Reverse-engineer a downloaded mesh into a part, with a graded loop". It closes issue #39, *"Reverse engineer mesh (STL) into parametric"* — **filed by clairernovotny**. It was closed on 2026-08-12 with the comment "Worked in a first pass at this very thing!" eight seconds beforehand. `merged: false`.

Its 554-line `mesh.py` did implement real work: union-find region grouping over `face_adjacency`; `planes()` merging adjacent faces at `n_a · n_b > 0.99999`; `_split_by_curvature()` clustering implied bend radii on a **log scale** and cutting at gaps greater than `log(1.8)`; `cylinders()` doing least-squares circle fits with a `resid > 0.02·r` rejection gate; `_pitches()` inferring repeated bore spacings; `_inside()` implementing a generalized winding number via the van Oosterom–Strackee solid-angle sum; and `compare()` with `ADDED_LIMIT = 0.5` — the asymmetric verdict, with a nonzero exit on invented material.

**What survived to `main`: only the compare loop and the viewer ghost — and they lost their teeth.** The owner shipped smaller independent reimplementations (PRs #92, #93, #100) *before* closing #41. `main`'s `compare.py` has **no `ADDED_LIMIT`, no winding-number containment test, and no pass/fail at all** — it is symmetric and advisory. Every piece of the fitting chain — `planes()`, `cylinders()`, `_fit_circle()`, `_split_by_curvature()`, `_pitches()`, `_inside()` — is gone, confirmed by grep across all of `src/nurb/*.py`.

**Three things we take from this, and one we must not.**

1. **The asymmetric verdict was the best idea in the abandoned PR, and upstream lost it.** Plan 003 already revived it (its KTD4, R10) — that judgement is now confirmed against the actual code rather than a summary.
2. **PR #41's cylinder detection was axis-aligned only.** It tested `|n · axis| < 0.02` against each principal axis X/Y/Z in turn, so **arbitrary-axis cylinders were never detected at all**. Our `mesh_fitting._search_axis` (`mesh_fitting.py:999`) already fits an arbitrary axis. We are ahead of the abandoned prior art on the single hardest fitting case, which is a real reason for confidence in U2.
3. **It had no RANSAC and no denoising** — a plain least-squares fit with one residual gate. That is precisely the configuration KTD6's disproof gates exist to correct, and it is a fair guess at why the approach did not hold up well enough to merge.
4. **License: `LicenseRef-FSL-1.1-MIT` — the Functional Source License, which is not OSI open source.** No code from nurb, on `main` or in PR #41, may be copied into this repository. Architecture observations are fine; text and implementations are not. This is a hard constraint on U2's implementation and should be stated in the PR description.

**Honest caveat:** the investigation did not run nurb's test suite (Python 3.13 + OCCT wheels), so its "281 tests passing" claim is the author's, unverified. The clone was `--depth 1`; history claims come from the commits API for the three relevant paths.

### Commercial references (from plan 003's research, unchanged)

QUICKSURFACE (rebranded as Revo Design Pro) and Geomagic Design X both:

- expose **three separate commands** for the three outcomes and make the human choose — nobody automates that choice;
- derive the coordinate frame **from fitted primitives** rather than aligning first;
- gate **automatic constraint inference** (`Auto Sketch`: section polyline → line/arc classification → constraint inference) behind their premium tier, which tells you where the difficulty and the value both sit;
- treat deviation as continuous feedback, not a final pass/fail gate.

Design X's `Auto Surfacing` is explicitly documented as producing a solid that has *no feature tree or shape identification* — a 1-to-1 dummy CAD version of the mesh. That is the outcome this plan exists to avoid, and it is worth noting that the mature commercial tool ships it as a labelled, separate command rather than pretending it is reconstruction.

---

## Requirements

Requirements here extend plan 003's R1–R13, which stay in force unchanged. Where this plan completes an unfinished 003 requirement, the mapping is named.

- **R1. Mesh data reaches the host, bound by hash.** A read-only Fusion transaction writes an indexed mesh dump — vertices, triangle indices, per-triangle face-group ids where available, the mesh body binding, units, and the applied transform — and reports its SHA-256. The host reader refuses a dump whose bytes do not hash to the recorded value. Every downstream artifact (fit record, reconstruction program, emitted transaction, verification report) carries that dump hash, and the emission transaction **re-derives the dump hash from the live mesh** and refuses if it changed. *(Completes the transport that 003 never needed.)*

- **R2. A declared triangle budget, refused rather than exceeded.** The caller declares `max_triangles` with a rationale. Above it the extraction refuses with `triangle-budget-exceeded`, naming the count and the budget, and offering decimation as the alternative.

  **Rationale re-derived 2026-08-19**, because the original one leaned on the now-falsified F4. The budget was introduced as a mitigation for pure-Python slowness; numpy is available both host-side and in Fusion, so that reason is weakened and is no longer the primary one. Two reasons survive independently and are why the budget stays:

  1. **Fit-driven splitting is superlinear, not linear.** Vectorized per-triangle arithmetic does not bound a recursive subdivision search. `split_recursion_depth` bounds the depth; the triangle budget bounds its base.
  2. **Beyond a density, extra triangles are noise samples rather than extra information.** A 2M-triangle scan of a part with twelve planar faces and four holes carries no more recoverable *design* than a 200k one — it carries more noise, which KTD5's gate then has to fight. The budget is partly a statement about what the algorithm can honestly use.

  What changes: the budget's *number* must be chosen from U2's benchmark against **what the algorithm can use**, not from what pure Python can survive, and its declared rationale must say which of the two reasons above the caller is invoking. A budget justified as "otherwise it is slow" is now the wrong rationale and should be rejected in review.

- **R3. Segmentation is explicit about its source and its quality.** Regions come from Fusion's `triangleFaceGroupTempIds` when present and non-degenerate, or from our own crease-based region growing, and the record names which. A grouping that puts every triangle in one region is **degenerate, not segmentation**, and is reported as such. Region identity in the record is a canonical hash of the region's sorted triangle indices, never a Fusion temp id.

- **R4. Noise is measured before segmentation is trusted.** The extraction computes a normal-noise floor from the mesh itself (median absolute dihedral angle over all interior edges) and compares it against the caller-declared crease threshold. When the noise floor is within a declared factor of the crease threshold, segmentation is reported `noise-limited` and the run refuses rather than producing regions whose boundaries are noise. Smoothing and decimation are offered as the alternatives, both declared and both recorded.

- **R5. A fit must survive disproof, not just pass a residual.** Beyond 003's existing relative-residual / radius-ratio / bounds-margin gates, every accepted fit additionally passes: **support span** (a cylinder fitted to a narrow arc of surface is not evidence of a cylinder — the angular/areal span of supporting points must exceed a declared minimum), **residual structure** (residuals binned along the primitive's own parameterization must have per-bin means within the noise floor; a systematically signed residual pattern means the wrong primitive even when RMS looks fine), and **held-out residual** (fit on a random half, measure on the other; a materially worse held-out residual means the fit is over-parameterized for the data). A fit failing any of these is `accepted=False` with the named reason — never a silent success.

- **R6. Datum frame derived from the fits, deterministically, or refused.** Origin and axes come from the fitted primitives, with a total, documented tie-break order. When the margin between the best and second-best candidate for any axis is below a declared threshold, the frame is reported `frame-ambiguous` and the run refuses rather than picking. The frame record carries the winning candidate, the runner-up, and the margin. *(Completes plan 003's R8, second half.)*

- **R7. Relationship inference covers seven kinds and stays proposals.** Extend `INTENT_KINDS` with `tangent` and `equal_radius`, and generalize `_symmetry_proposal` beyond its two current cases. Every proposal carries its measured deviation and is never applied without being adopted into the reconstruction program by an explicit decision that is itself recorded. *(Extends plan 003's R9.)*

- **R8. Every reconstruction maps to a named feature archetype, or is declared unreconstructed.** The reconstruction program states, per region group, which archetype it became — `sketch-extrude`, `revolve`, `hole`, `fillet`, or `unreconstructed` — and why. A region that fits nothing is not dropped; it is listed with its area fraction, bounding box, and the gate it failed.

- **R9. Real features, never base features.** Emission uses `sketches.add`, `sketchCurves`, `geometricConstraints`, `sketchDimensions`, `extrudeFeatures`, `revolveFeatures`, `holeFeatures`, `filletFeatures`. It never uses `baseFeatures` + `TemporaryBRepManager` for reconstructed geometry (F10), because a base-feature body is opaque to parameters and would pass a naive parametric check while being uneditable.

- **R10. Constraints are applied incrementally with rollback.** One constraint or dimension at a time, each followed by a geometry-displacement check against a declared tolerance and a solver-health read. A constraint that moves geometry beyond tolerance, or that the solver rejects, is removed and reported — never left in, never batched and hoped for.

- **R11. Editability is proven by perturbation, not by assertion.** For each emitted user parameter the verification transaction: records the baseline (timeline health, body count, volume, bounding box); sets a caller-declared perturbed value with a stated rationale; recomputes; asserts no timeline error, unchanged body count, and that the **volume actually changed** — a parameter that recomputes cleanly and changes nothing is a dead parameter and is a failure; restores the original; recomputes; asserts the volume returns within a declared epsilon. The report names exactly which parameters were exercised. `designType == ParametricDesignType` is never accepted as evidence of anything, because it is true of a faceted body too.

- **R12. The verification report's `checked` list is constructed by the code that ran the checks.** Each entry is appended inside the block that performed its check, after it succeeded. A check that raises leaves no entry. This is enforced by a test that stubs a raising check and asserts its name is absent from `checked` — not by review discipline.

- **R13. Partial reconstruction is a declared outcome with a coverage number.** The result label is one of `parametric-full`, `parametric-partial`, or `reconstruction-refused`, each carrying `covered_area_fraction` computed from the summed area of reconstructed regions over total mesh area. `parametric-partial` is a success, and it is never abbreviated to `parametric`.

- **R14. Refusal is honest and total.** When reconstruction cannot honestly complete — noise-limited, frame-ambiguous, budget-exceeded, no archetype matched, solver rejected the constraint set, a capability probe failed — the run produces **no geometry** and a named refusal with its alternative. A partially-emitted timeline is rolled back. The refusal vocabulary is closed and documented, following the faceted ladder's precedent.

- **R15. Every threshold is caller-declared with a rationale.** `max_triangles`, `crease_threshold_deg`, `noise_factor`, `min_support_span`, `residual_structure_tolerance`, `heldout_residual_ratio`, `split_recursion_depth`, `frame_margin`, `constraint_displacement_tolerance`, `parameter_perturbation` (per parameter), `volume_restore_epsilon`. None is a module constant. Each carries a `rationale` string, and validation rejects a threshold without one — the sibling requirement a reviewer already flagged as missing elsewhere in this skill.

- **R16. The reconstruction program is a versioned, hash-bound, closed-vocabulary data artifact.** It carries `program_version`, the mesh dump SHA-256 it was fitted from, the manifest SHA-256, its own canonical SHA-256, the archetype plan, the adopted relationships, the declared thresholds with their rationales, the unreconstructed region list, and `covered_area_fraction`. It is data, never executable code. The Fusion-side executor refuses an unrecognized `program_version`, refuses any unknown key or out-of-set value, and refuses when the live mesh no longer hashes to the recorded dump. It never best-efforts a program it does not fully understand. *(See KTD1.)*

- **R17. Runtime facts are probed live and recorded against a Fusion version, never assumed from documentation.** A read-only probe records the embedded interpreter's **tag set** (version, implementation, `EXT_SUFFIX`, platform, and `packaging.tags.sys_tags()` where available), its **writable `sys.path` entries**, and which of the mesh and construction APIs this plan needs are present. The result is written into the evidence chain and referenced by every downstream record — not into a doc comment. A stale note is treated as falsifiable: `references/mcp-adapter.md`'s claim that `secrets`, `sqlite3` and `numpy` do not import was **disproved by live probe** (F4) and is corrected in U0. *(Settles A1 and A4 as a by-product.)*

---

## Key Technical Decisions

### KTD1 — Architecture: host-side numerics, Fusion-side construction, and a versioned reconstruction program between them

This is the load-bearing decision, and it is a **hybrid**, not a dependency question. The dependency question (KTD2) only becomes answerable once the split is fixed.

- **Host side** — extraction parsing, segmentation, classification, fitting, disproof gates, relationship inference, datum derivation, and archetype planning. Runs under `scripts/test.sh` with no Fusion required.
- **Fusion side** — receives a **reconstruction program** and executes it through the ordinary generated-transaction pattern: sketches, constraints, dimensions, extrudes, revolves, holes, fillets, and the perturbation proof. Stdlib plus the Fusion API only.

`references/mcp-adapter.md:56–58` already prescribes exactly this in prose: *"Put heavy mesh or other non-Fusion processing in the host environment and pass only its result into Fusion."* This plan is that sentence made structural.

**The reconstruction program is therefore the most important design artifact in this plan, and it is part of the evidence chain.** It is not a convenience format. Requirements on it, held to the same standard as everything else:

- **Versioned.** A `program_version` integer in the header. A Fusion-side executor that does not recognize the version refuses with `program-version-unsupported` naming both versions. It never best-efforts a newer program.
- **Hash-bound in both directions.** It carries the mesh dump SHA-256 it was fitted from, the manifest SHA-256, and its own canonical SHA-256 (over sorted-key JSON, matching `scripts.manifest_sha256`'s existing convention). The Fusion-side executor **re-derives the dump hash from the live mesh** and refuses on mismatch (R1). This is what stops a hash sitting beside content from an unbound source.
- **Closed vocabulary, fail-closed on anything unknown.** Every archetype, constraint kind, feature type and threshold name comes from a closed set validated with the existing `manifest._in_closed_set` / `_reject_unknown_fields` pattern. An unrecognized key is a refusal, not an ignored field. `printable_parts.py` is the precedent to copy.
- **Self-describing about what it does not cover.** It carries the `unreconstructed` region list and the `covered_area_fraction` (R13), so the executor cannot produce a result that claims more coverage than the program declared.
- **Declarative, never executable.** It is data, not Python. The Fusion-side executor is a fixed, byte-pinned emitter output that interprets it. A program that could carry code would make the whole verification chain meaningless.

**What Fusion's own API removes the need for** — the half of the argument that makes stdlib sufficient rather than merely tolerable:

| Would-be dependency job | Fusion supplies instead |
| --- | --- |
| B-Rep construction, booleans, solid modelling | `extrudeFeatures`, `revolveFeatures`, `holeFeatures`, `combineFeatures` — producing *timeline entries*, which is the actual deliverable |
| Constraint solving | Fusion's sketch solver, via `geometricConstraints` / `sketchDimensions` |
| Point-in-solid queries | `BRepBody.pointContainment` (already used, `mesh_deviation.py:327`) |
| Nearest-surface distance over a whole mesh | `PolygonMesh.compareWith` (already used, preview-gated) |
| Temporary/scratch geometry | `TemporaryBRepManager` (already used, `positive_control.py:287`) |
| Mesh segmentation | `triangleFaceGroupTempIds` (already read, `mesh_convert.py:123`) — quality unverified, A1/A2 |

What remains for us is: parse a dump, group triangles, fit analytic primitives, disprove them, reason about relationships, emit a program. All of it is arithmetic on floats.

### KTD2 — Dependencies: no new dependency for this feature; and the two packaging questions have different answers

**Recommendation: build this feature with the standard library only.** Not from conservatism — from evidence, and the strongest piece of it is new.

**The decisive evidence is nurb itself.** nurb ships OCCT 7.9, numpy 2.5.1, scipy 1.18.0 and trimesh — the complete toolkit — and its exports are `3mf`, `stl`, `step`, `glb`. Its STEP opens in Fusion as a dumb solid with no feature tree. Its only genuinely parametric artifact is a Python source file with slider-editable numbers. **Having the full library stack did not get it an editable CAD timeline, because no library has one — Fusion's timeline is a Fusion API product.** This is no longer an argument; it is an observed outcome in the closest comparable project.

And the second half: nurb's own attempt at the fitting chain (PR #41, +974 lines, with numpy and scipy available) was **closed unmerged by its author** and its fitting code deleted from `main`. Access to numpy was never the binding constraint on that problem.

**Why OCCT / CadQuery / build123d is wrong for this goal at any performance level.** Anything a second B-Rep kernel builds enters Fusion as an imported solid or a `TemporaryBRepManager` base-feature body — and F10 shows a base-feature body is opaque to parameters, while plan 003's doctrine already records that STEP does not restore design intent. It would produce a better reconstruction that arrives dead. Rejected on the goal, not on the packaging.

**Where numpy would genuinely help — stated accurately, now that it is actually available.** numpy would *not* meaningfully help the fitting math: the eigen-decompositions are 3×3 and the least-squares systems are 4×4, where per-call overhead roughly cancels the advantage. Where it **would** help is the per-triangle work in U1/U2 — normals, areas, edge adjacency, dihedral angles. Those are tight Python loops and numpy would vectorize them perhaps 20–50×.

The honest estimate (A5, to be measured, not asserted): at 200k triangles, per-triangle arithmetic at roughly 30 float operations each is on the order of 3–8 seconds in CPython; adjacency construction is ~600k dict operations, 1–2 seconds; region growing about a second. **Tens of seconds for a 200k-triangle mesh**, in a workflow where the user reads the fit record before anything is emitted. That is acceptable. So numpy buys **speed on a stage whose speed is already adequate**, and it buys nothing on the stage that is actually hard.

**The remaining argument, corrected twice and now resting on something true: the risk is wheel *availability*, not wheel *delivery*.**

An earlier draft of this section claimed that resolving wheels for Fusion's tag set was "reimplementing a slice of pip". **That was wrong.** F4b shows it is four flags — `--python-version` / `--implementation` / `--abi` / `--platform` with `--target` — and that pip performs full *transitive* resolution against foreign tags. Delivery is a solved problem.

What is not solved is that **the wheel has to exist**. F4c is the live proof: Fusion runs Python 3.14.0, and against `cp314`/`arm64` today numpy resolves, trimesh resolves, and **scipy does not — no wheel published**. Fusion auto-updates, so on the day it moves to 3.15 the entire set re-enters that gap, and **the duration of the gap is set by upstream maintainers, not by us**. Re-pinning is cheap. Waiting for a wheel that does not exist is not, and it lands as a broken critical path on a user's machine after an update our CI cannot see.

Host-side Python is under the user's control and does not move without them. That is a genuine architectural argument for the host-side split; it is honest rather than a workaround; and it points at the same conclusion the nurb finding did — **do not put the design's critical path on a dependency that may have no wheel for Fusion's interpreter on any given day.**

**Question 1: what is in scope for the skill's packaging? Three separate problems, three different answers — and the first two changed completely once the premises were corrected.**

*(a) In-Fusion third-party dependencies — already solved, by pip. Build nothing.* Both earlier drafts of this subsection were wrong: the first said native code could not run, the second said delivering it meant reimplementing resolution. F4 and F4b disprove both. Cross-target install is one command with four flags, it resolves transitively, and the target directory is already on Fusion's `sys.path`. **There is no mechanism to design and none to extend.**

If a future feature does take an in-Fusion dependency, the honest engineering that remains is small and none of it is resolution:

- **probe the triple, never hardcode it.** Fusion auto-updates and `cp314`/`arm64` will move; U0 already records `(version, abi, platform)` for exactly this, and those values feed pip's flags directly;
- **install from a pinned lock with `--require-hashes`, not a fresh resolve per run.** This is where the skill's existing evidence discipline genuinely applies — a reproducible, auditable install rather than "whatever PyPI served today";
- **record the resolved set with its hashes in the evidence chain**, alongside the Fusion version it was resolved for.

That is a small, well-understood piece of work. It is simply not needed here.

*(b) `module_cache.py` stays `.py`-only — as a scope boundary, not a capability gap.* It exists to deliver **our own** code with content addressing, `O_NOFOLLOW`, ownership checks and verified imports, and it is good at that. Third-party wheels are pip's job. `references/unsupported.md` should state this as scope — *"the module bundle carries our own pure-Python code; third-party dependencies are installed with pip against Fusion's probed interpreter tags (see `docs/solutions/fusion-python-supports-wheels.md`)"* — and must **not** describe it as something Fusion or the cache is incapable of.

*(c) Host-side dependencies — ordinary Python packaging, as a separate small PR, and not a prerequisite for this feature.* Unchanged by the new evidence. The user has said they want a proper mechanism, and they should have one; it is just not on this feature's critical path. The correct shape, when it is built:

- a `pyproject.toml` in the skill declaring the package with **zero required dependencies** and named extras (`fusion-design[fast]` → numpy);
- `scripts/fusion-design` keeps working with a bare `python3` and no install, exactly as today (F6) — an import-guarded optional path, never a hard import;
- **every optional acceleration is recorded in the report** it influenced, so evidence states which code path produced it. An unrecorded fast path is an unbound claim;
- a differential test asserting the stdlib and accelerated paths produce **bit-identical** output over the synthetic fixtures. An optional dependency that changes results is not an optimization, it is a second implementation;
- extras never gate a capability. If a feature only works with the extra installed, the extra is a required dependency wearing a disguise.

That is roughly a small PR and can land any time, before or after this work. **This plan does not depend on it.**

**Question 2: the numpy availability question is settled — numpy loads. What U0 now probes instead is the thing that actually varies.** The remaining unknown is not "can native code run" but **"can we resolve and verify a wheel set for Fusion's exact tags, reproducibly, and where does it live"** — and the inputs to that answer change per install and per Fusion update. U0 therefore records the interpreter's **tag set** (`packaging.tags.sys_tags()` when importable, else `sys.version_info` + `sys.implementation` + `EXT_SUFFIX` + `sysconfig.get_platform()`), the **writable `sys.path` entries** and their ownership, and the Fusion version they belong to. That record is what makes a future Python bump *detectable* rather than a surprise, and it costs one read-only script.

**So what actually changed in the recommendation? Nothing — and the reasons that survive were never the numpy one.** Stated plainly, since that is what was asked:

1. **Offline testability.** U2 is the crux, the largest and riskiest unit, and it is fully provable under `scripts/test.sh` **with no Fusion running at all**. Any move of numerics into Fusion trades that away. This was always the strongest reason and it never touched numpy.
2. **nurb's empirical result.** The full OCCT + numpy + scipy stack, and still no editable timeline, because no library has one.
3. **The wheel-availability argument above** — live, not hypothetical: scipy has no `cp314` wheel today (F4c), and Fusion's next auto-update puts the whole set back in that gap on a schedule upstream maintainers control, not us.
4. **We do not need it.** Constant-factor speedup on an adequate stage.

**What the corrections genuinely widen: the escape hatch, which now has two doors and both are cheap.** If U2's benchmark comes back materially worse than the estimate, the options are no longer just a host-side `[fast]` extra — an in-Fusion wheel path is demonstrated to work (F4, F4b) and costs one pip invocation, so per-triangle arithmetic could move *into* the extraction transaction, with the wire then carrying regions rather than raw triangles and the dump shrinking by an order of magnitude. That is a real, viable, **inexpensive** option held in reserve. Take it only on a measurement, and take it knowing the cost is not the install — it is accepting F4c's availability risk on the critical path.

**What would overrule me.** A U2 benchmark far worse than estimated, or a real corpus routinely above 500k triangles where decimation destroys the features that matter. Both are measurements, and U2 is where they get made. What would *not* change my mind at any measurement is OCCT — that one is rejected on the goal, not on performance.

### KTD3 — The wire is a hashed file dump, not JSON over stdout

`nodeCoordinates` for a 200k-triangle mesh is roughly 300k floats plus 600k indices. As JSON through the existing stdout report protocol that is 10+ MB of text through an MCP channel — fragile, slow, and it would swamp the report the protocol exists to deliver. Instead, the extraction transaction writes a compact indexed dump to a caller-declared directory using `struct` (confirmed-stdlib) and reports only its path, byte length, SHA-256, and the summary counts through the normal report protocol. The host reads and re-hashes it.

This also fixes a class of dishonesty the parent flagged: a hash printed beside content from an unbound source. Here the hash covers the exact bytes the host parses, and the emission transaction recomputes the dump from the live mesh and compares — so a mesh edited between fit and emit is caught, not assumed away.

**Fallback, implemented not assumed (A4):** if writing the file fails, the transaction reports `dump-write-unavailable` with the exception, and the host falls back to chunked base64 over stdout with a declared chunk count and a per-chunk hash. The fallback is size-limited and says so.

### KTD4 — Segmentation: crease-based region growing, with Fusion's grouping as a *checked* input, not a trusted one

Two candidate sources, and the honest position is to use both and compare rather than pick blind:

1. **Fusion's `triangleFaceGroupTempIds`.** Free, already plumbed (F9), and produced by a feature that fits primitives internally. But A1 and A2 are unverified: it may be one group, and its quality on scan data is unmeasured.
2. **Our own crease-based region growing.** Build edge→triangle adjacency (one pass, dict of sorted vertex-pair). Compute per-triangle area-weighted normals. Grow regions across edges whose **dihedral angle** is below a caller-declared crease threshold, seeded from the largest unassigned triangle.

Crease-based growing is chosen over normal-clustering because it is correct about the thing that matters: a cylinder's normals sweep through 360°, so any absolute normal-similarity threshold either shatters the cylinder or merges everything. Dihedral angle across a shared edge is local and scale-free, and it separates at real edges while keeping smooth surfaces whole.

**Its known and honest limitation:** tangent-continuous features do not separate by crease. A fillet blending a cylinder into a plane has near-zero dihedral everywhere, so it grows into one region with both. That is handled by the **second pass: fit-driven splitting.** Attempt a fit on the whole region; if it fails the R5 gates, split it. Splitting uses the residual field — points whose residual sign flips systematically mark the boundary of the wrong-primitive part — and recurses to a declared depth, refusing rather than recursing forever.

Both sources are computed when Fusion's grouping is available, and the record carries an agreement statistic (per-triangle label agreement under optimal label matching). Disagreement is reported, not resolved silently. This is how A2 gets settled by evidence instead of by hope.

### KTD5 — Noise gating comes before segmentation, because segmentation on noise is the silent failure

This is the crux the brief asked me not to skip, so here it is concretely.

Crease detection works only when the dihedral angle at a real edge exceeds the angular jitter that noise puts into the surface. For a scan with point noise `σ` on triangles of edge length `ℓ`, the induced normal jitter goes roughly as `arctan(σ/ℓ)`. At `σ = 0.05 mm` on `0.5 mm` triangles that is about 11° — which swamps a 15° crease threshold. Segmentation then produces regions whose boundaries are noise, and every downstream fit is confidently wrong in a way no residual check catches, because the residuals of a bad region are perfectly consistent with the bad region.

The gate is computable from the mesh alone. On a mechanical part, the overwhelming majority of interior edges lie inside smooth surfaces, so the **median absolute dihedral angle over all interior edges is a direct estimate of the noise floor**. Compare it against the declared crease threshold; when `noise_floor * noise_factor >= crease_threshold`, refuse with `segmentation-noise-limited`, reporting both numbers.

The alternatives are offered, declared and recorded rather than applied silently:

- **Normal smoothing** over the k-ring. Averages noise down roughly as `1/√k` but also rounds real creases, so it is capped and its k is recorded.
- **Decimation** to longer edges, which raises effective SNR directly. Decimation changes the geometry, so it produces a *new dump with a new hash*, and the fit record binds to that hash while the deviation verdict still grades against the original. This keeps R1's chain intact through a lossy step.

Being honest here has a cost: some real scans will refuse. That is the correct outcome for this skill. A refusal naming a measured noise floor is more useful than a confident cylinder that is not a cylinder.

### KTD6 — Three disproof gates, because a passing residual is not evidence

R5's gates exist because the failure mode the parent named — *"quietly fits a cylinder to something that is not a cylinder"* — is not caught by RMS residual. All three are cheap and stdlib:

- **Support span.** A cylinder fitted to a 20° arc of surface has a tiny residual and means nothing. Measure the angular span of supporting points about the fitted axis (and for planes, the areal extent relative to the fitted plane's own scale). Refuse below a declared minimum.
- **Residual structure.** Bin residuals along the primitive's own parameterization (axial station and angular station for a cylinder; the two in-plane axes for a plane). Per-bin means should sit within the noise floor. A smooth, systematically-signed pattern is the unmistakable signature of the wrong primitive with a flattering RMS.
- **Held-out residual.** Fit on a random half of the region's points (seeded deterministically from the region hash so results are reproducible), evaluate on the other half. A held-out residual materially worse than in-sample means the fit is over-parameterized for the evidence.

Each has a caller-declared threshold with a rationale. Each failure is a named `rejection` on the existing `PrimitiveFit`, which already carries that field — so this is an extension of a shape that exists, not a new one.

### KTD7 — Constraints applied one at a time, with displacement checks and rollback

Fusion's solver is a black box that may reject an over-constrained sketch, or accept it and *move the geometry*. Both are silent failures if constraints are batched. So: apply one constraint or dimension, read back the sketch geometry, compare against the pre-constraint positions, and if any point moved beyond the declared `constraint_displacement_tolerance`, delete the constraint and record it as `constraint-rejected` with the measured displacement. This turns A6 from a risk into a measurement.

The order matters and is fixed: coincidences from shared polyline endpoints first (they are trivially satisfiable by construction — `SketchEntity.start`/`end` are the polyline's own points, per `mesh_fitting.py:536–538`), then tangency at line/arc junctions, then the inferred relationships in decreasing confidence, then driven dimensions last.

### KTD8 — Feature archetype mapping, stated explicitly

| Fitted region group | Archetype | Emission |
| --- | --- | --- |
| Two parallel planes plus side surfaces perpendicular to them | `sketch-extrude` | Sketch on the near cap plane; profile from a mesh section taken between the caps; extrude to the far cap's offset |
| Cylinders/cones/planes all coaxial about one axis | `revolve` | Sketch on a plane containing the axis; profile from one side of the axial section, classified to lines/arcs; revolve 360° |
| Cylinder whose surface faces inward, normal to a planar face, in an oriented mesh | `hole` | `holeFeatures` on the host face, positioned by the axis, sized by the fitted diameter |
| Smooth region tangent to two accepted neighbours with near-constant width | `fillet` | `filletFeatures` on the corresponding edge, radius proposed from the region width |
| Anything else | `unreconstructed` | Nothing emitted; listed with area fraction and failed gate |

Two constraints on this table. **Hole classification requires an oriented mesh** — inward vs outward needs triangle winding, and `isOriented` is already captured (F11). An unoriented mesh refuses to classify holes rather than guessing, and those cylinders fall through to `sketch-extrude` cuts or `unreconstructed`. **Fillets are emitted last and are individually optional** — a fillet that fails to apply is recorded and skipped, and the model without it is still valid. Fillet detection here is by geometric adjacency and near-constant width, *not* by torus fitting; `PRIMITIVE_KINDS` gains no torus in this plan.

### KTD9 — The timeline we produce is *an* honest parameterization, not *the* original

Worth stating in the doctrine because it manages the expectation that otherwise gets set: a boss can be modelled as an extrude or as a revolve, and both rebuild the same surface with different edit affordances. We recover a feature tree consistent with the measured geometry. We do not recover the designer's intent, and no tool does. What we owe the user is that the tree we produce is *editable and rebuilds correctly*, which is what R11 measures.

### KTD10 — Verification asserts only what it ran

Following the parent's audit findings, three specific mechanisms rather than a principle:

1. R12's construction rule for the `checked` list, enforced by a test that makes a check raise and asserts its absence.
2. R11's perturbation test asserts a **volume change**, so a dead parameter fails. A parameter that recomputes without effect is the exact shape of "asserted more than it verified" with geometry attached.
3. R1's round-trip hash binding, so the content the verdict describes is provably the content that was fitted. The emission transaction recomputes the dump hash from the live mesh; a mismatch refuses.

And one negative rule: the reconstruction report must never contain a top-level boolean like `"parametric": true`. It contains a label from the closed set in R13 and a coverage fraction, both of which are falsifiable.

---

## Implementation Units

Six units across **five PRs**. Sequencing is chosen so each PR lands something a user can run, and so the riskiest unit (U2) lands before anything depends on its output shape.

Live-Fusion dependency is marked per unit. **U1 and U5 cannot be fully validated offline.** U2, U3 and U4 are pure arithmetic and are fully offline-testable — that is deliberate, and it is why the hard algorithmic work is separated from the API work rather than mixed into it.

---

### U0 — Live runtime capability probe *(PR 1)*

**Goal:** Record the runtime facts that actually vary per install and per Fusion update, so no later decision rests on a stale note. **Revised 2026-08-19:** the numpy-availability question this unit originally existed to answer is now settled (F4) — numpy loads and executes compiled LAPACK inside Fusion. What remains unknown, and what this unit now probes, is the **interpreter tag set and writable path**, which is what any future wheel decision would have to resolve against and what a Fusion auto-update silently changes.

**Requirements:** R17. Assumptions settled or narrowed: A1, A4.

**Files:** `src/fusion_design/mesh_probe.py` (new), `src/fusion_design/cli.py`, `references/mcp-adapter.md` (**stale-note correction**, see below), `tests/test_mesh_probe.py`.

**Approach:** `fusion-design emit-capability-probe <manifest>` emits a read-only transaction that records, for the connected Fusion:

- `Application.version`, plus `sys.version_info`, `sys.implementation`, `sysconfig.get_config_var("EXT_SUFFIX")` and `sysconfig.get_platform()`;
- the **interpreter `(version, abi, platform)` triple**, plus `packaging.tags.sys_tags()` when `packaging` is importable. These are the exact values pip's `--python-version` / `--abi` / `--platform` flags take (F4b), so recording them is what lets any future in-Fusion install be *probed* rather than hardcoded — and Fusion auto-updates, so a hardcoded `cp314`/`arm64` would silently rot. Note the triple **cannot be derived from the host**: Fusion reports `macosx-10.15-universal2` yet loads a `macosx_11_0_arm64` wheel;
- the **writable `sys.path` entries**, with owner and mode for each — F4 found `~/Library/Application Support/Autodesk/Autodesk Fusion 360/MyScripts/ManuallyInstalled/` already present and user-writable;
- presence via `getattr` of every API this plan needs: `MeshBody.mesh`, `PolygonMesh.nodeCoordinates` / `.triangleNodeIndices` / `.triangleFaceGroupTempIds` / `.compareWith`, `Component.sketches`, `Sketch.sketchCurves` / `.geometricConstraints` / `.sketchDimensions`, `Features.extrudeFeatures` / `.revolveFeatures` / `.holeFeatures` / `.filletFeatures`, `Component.constructionPlanes`, `BRepBody.pointContainment`;
- for a named mesh body when one is bound: the `triangleFaceGroupTempIds` histogram (settles A1) and a write-and-read-back round trip into the declared dump directory (settles A4).

It does **not** probe `numpy` as a capability question — that is answered (F4), and installing it needs no mechanism from us (F4b). It records the triple, which is pip's input and the thing a Fusion update changes.

The report is a probe record keyed by Fusion version, retained as evidence and referenced by every downstream artifact. It creates nothing and modifies nothing.

**Why this is its own unit rather than a line in U1:** every mesh and construction API here is preview and may move between Fusion releases, and Fusion auto-updates. A probe record keyed by version is what makes a bump *detectable* instead of a field failure. It is also the cheapest possible live run — no geometry, no risk — which makes it the right first thing to ask a user to execute.

**Also in this unit: correct the stale note.** `references/mcp-adapter.md:50–58` currently states that `secrets` and `sqlite3` do not import in Fusion and implies numpy cannot. F4 disproves all three. Replace the note with the probed facts, cite `docs/solutions/fusion-python-supports-wheels.md`, and keep the *guidance* (heavy processing host-side) while re-deriving it from KTD2's real reasons — offline testability, nurb's empirical result, and F4c's wheel-availability risk — rather than from a false capability claim. The replacement note must also say how third-party deps *would* be installed if ever wanted (pip with probed tags), so the next reader does not re-derive the same wrong conclusion. A stale note that drove an architecture decision is exactly the kind of thing this skill's doctrine says to fail closed on.

**What changes on each outcome, decided now so the result is not re-litigated later:**

| Probe result | Response |
| --- | --- |
| Tag set matches F4 (`cp314`, macOS, arm64/universal2) | Record it as the baseline. Nothing changes; KTD2 stands. |
| Tag set differs, or differs on a later run | Record both and flag the change. A moved interpreter is the event that would invalidate any in-Fusion wheel set — the whole reason this is recorded (KTD2). |
| No writable `sys.path` entry | Record it. Removes the in-Fusion escape-hatch door entirely; nothing else changes, because we are not walking through it. |
| Face groups are one group or absent (A1 likely) | U2's own segmentation is the primary path, not the fallback. The agreement statistic is unavailable and is reported so. |
| Face groups are rich and plausible | U2 still computes its own and reports agreement; Fusion's grouping is a checked input, never a trusted one (KTD4). |
| File write-back fails (A4) | U1 implements the chunked-base64 stdout fallback as the primary wire, with its declared size ceiling. |
| A construction API is absent | Named in `unsupported.md` against that Fusion version; the archetypes depending on it refuse rather than substitute. |

**Live-Fusion dependency: YES** — that is the entire point. Offline coverage: the generated source compiles and runs against the stubbed-`adsk` harness, with stubs for available, unavailable and raising imports, and a stub missing each probed API in turn.

**Test scenarios:** a raising import is reported `unavailable` with its message, not omitted; a missing API is named individually rather than collapsed into one "capabilities missing"; the probe script contains no mutating API call, asserted by string search; the probe record round-trips into the evidence chain.

**Size:** S.

---

### U1 — Mesh extraction and hash-bound transport *(PR 1)*

**Goal:** Get vertices, triangles and face-group ids out of Fusion into a hashed dump the host can read, with a triangle budget.

**Requirements:** R1, R2, R15. Assumptions settled: A1, A4.

**Files:** `src/fusion_design/mesh_extract.py` (new, emitter + in-Fusion `run`), `src/fusion_design/mesh_dump.py` (new, host-side reader/writer, shared format), `src/fusion_design/cli.py`, `schema/fusion-project.schema.json`, `tests/test_mesh_extract.py`, `tests/test_mesh_dump.py`.

**Approach:** New command `fusion-design emit-mesh-extract <manifest> --classification <c.json> --extract-spec <spec.json>`. The spec declares the body binding (reusing `mesh_convert.py`'s `component_path`/`body_name` shape), the output directory, and `max_triangles` with its rationale. The emitted transaction:

- runs the existing classification gate via `mesh_reconstruction.require_classification`, permitting only `parametric-rebuild`;
- probes `MeshBody.mesh`, `nodeCoordinates`, `triangleNodeIndices`, `triangleFaceGroupTempIds` with `getattr`, refusing with named reasons rather than defaulting;
- refuses `triangle-budget-exceeded` before reading any coordinate array, so an oversized mesh costs nothing;
- writes a `struct`-packed dump with a versioned header (magic, format version, counts, unit string, unit source, the 16-float transform) followed by float64 vertices, uint32 triangle indices, and uint32 face-group ids — or a sentinel count of zero when grouping is unavailable, which is *reported*, never silently treated as one group;
- computes SHA-256 over the written bytes and emits it in the report, along with the face-group histogram (which settles A1) and the interior-edge dihedral statistics needed by R4's noise floor;
- writes nothing else, mutates nothing, and leaves the source mesh untouched.

The host-side `mesh_dump.py` reads the format, re-hashes, and refuses on mismatch or unknown format version.

**Live-Fusion dependency: YES**, for the extraction transaction itself. Offline coverage is the emitter's generated source (executed against the existing stubbed-`adsk` harness in `tests/test_scripts.py:26`), the dump format round-trip, and every refusal path.

**Test scenarios:** budget refusal fires before coordinates are read; a missing `triangleFaceGroupTempIds` produces a reported-absent grouping, not a fabricated single group; a dump whose bytes are altered by one byte fails the host reader's hash check; an unknown format version refuses; the emitted script contains no mutating API call; `dump-write-unavailable` falls back to chunked base64 with per-chunk hashes; the report carries the dihedral statistics.

**Size:** M.

---

### U2 — Segmentation, noise gating, and disproof-gated fitting *(PR 2)*

**Goal:** Turn a dump into a **fit record**: regions, their fits, their rejections, and an honest statement of segmentation quality. This is the crux of the whole plan.

**Requirements:** R3, R4, R5, R15. Assumptions settled: A2, A3, A5.

**Files:** `src/fusion_design/mesh_segmentation.py` (new), `src/fusion_design/mesh_fitting.py` (extended — see interface changes below), `src/fusion_design/cli.py`, `tests/test_mesh_segmentation.py`, `tests/test_mesh_fitting.py`.

**Interface changes required in `mesh_fitting.py`** — this is what "make it callable" concretely means, and it is small because the module was written for this:

1. **Nothing needs to change in `fit_primitive`, `fit_face_group`, `best_fit`, `section_mesh`, `classify_polyline` or `propose_nominal`.** They already take points and caller-supplied gates as keyword arguments with no module-constant enforcement, and they already return rejections as data. This is why the module is reusable rather than rewritable.
2. **Add three gates to `_apply_gates`**, plumbed through `fit_primitive`'s existing keyword pattern: `min_support_span`, `residual_structure_tolerance`, `heldout_residual_ratio`. Each defaults to a `DEFAULT_*` module constant *for backward compatibility of the existing tests only*; the new caller declares all three. Each adds a distinct `rejection` string.
3. **`PrimitiveFit` gains a `support: dict[str, float]` field** carrying the measured span, the per-bin residual means, and the held-out residual — so a caller can see *why* a fit was accepted, not just that it was.
4. **`INTENT_KINDS` gains `tangent` and `equal_radius`** (R7, delivered in U3).
5. `propose_design_intent`'s `features` mapping is keyed by region hash rather than an arbitrary caller string. That is already just a `str`, so it is a convention change, not a signature change.

No function is deleted, no signature is broken, and the existing 705-line test file continues to pass.

**Segmentation approach:** as KTD4. Edge→triangle adjacency; per-triangle area-weighted normals; interior-edge dihedral histogram; R4's noise gate *first*; crease-based region growing; optional declared normal smoothing; fit-driven recursive splitting to a declared depth. When Fusion's grouping is present, compute it in parallel and report the agreement statistic (A2).

**Benchmark (settles A5):** synthetic meshes at 10k / 50k / 200k triangles, timed in the test suite as a *reported* number, not an asserted one — a timing assertion is a flaky test. The number informs the default `max_triangles` rationale in the doctrine.

**Live-Fusion dependency: NO.** Entirely arithmetic over a dump. Fixtures are synthetic meshes with known analytic answers, plus noise-injected variants of the same.

**Test scenarios:** a synthetic box segments to exactly six regions and six planes with correct normals and offsets; a synthetic cylinder-on-a-plate segments to a cylinder plus two planes; a tangent fillet between cylinder and plane initially grows into one region and is correctly split by the fit-driven pass; a mesh with injected noise above the declared factor refuses `segmentation-noise-limited` and produces **no regions**; a cylinder fitted to a 20° arc is rejected for support span; a shallow cone presented as a cylinder is rejected by residual structure even though its RMS passes; an over-parameterized fit is rejected by held-out residual; a Fusion grouping of one group is reported degenerate rather than used; region hashes are stable across two runs over the same dump and independent of face-group temp ids (A3); recursion depth is bounded and refuses rather than exceeding it.

**Size:** L. This is the largest and riskiest unit and it deserves its own PR with nothing else in it.

---

### U3 — Datum frame and relationship inference *(PR 3)*

**Goal:** A coordinate frame derived from the fits with deterministic tie-breaks, and the full seven-kind relationship set.

**Requirements:** R6, R7, R15.

**Files:** `src/fusion_design/mesh_datum.py` (new), `src/fusion_design/reconstruction_program.py` (new — the versioned artifact and its validator, per R16), `src/fusion_design/mesh_fitting.py` (intent kinds, generalized symmetry), `tests/test_mesh_datum.py`, `tests/test_mesh_fitting.py`.

**Frame derivation, stated as a total order:**

- **Primary axis (Z):** the accepted cylinder maximizing `radius × axial_span`; ties broken by larger supporting area, then by lexicographic order of the canonicalized direction, then of the anchor point. If no cylinder is accepted, the normal of the plane with the largest supporting area, same tie-breaks.
- **Origin:** the intersection of the primary axis with the accepted plane most nearly perpendicular to it and closest to the part's bounding-box minimum along that axis. If no such plane, the centroid of the largest plane; if no plane at all, the centroid of all accepted fits' supporting points.
- **Secondary axis (X):** the normal of the largest plane parallel to the primary axis, orthogonalized against Z. Failing that, the perpendicular component of the vector from the origin to the second cylinder's axis — a bolt pattern gives a natural X. Failing that, `frame-x-underdetermined`, which is a refusal, not a default to global X.
- Every candidate is scored, and the **margin** between winner and runner-up is compared against the declared `frame_margin`. Below it: `frame-ambiguous`, refuse, report both candidates and the margin.

Tie-breaks never consult dict iteration order or face-group temp ids (A3). Determinism is a tested property, not a hope.

**Relationship inference:** generalize `_symmetry_proposal` beyond its plane-pair and cylinder-pair cases; add `tangent` (a plane and a cylinder whose axis-to-plane distance equals the radius within tolerance; two cylinders whose axis separation equals the sum or difference of radii) and `equal_radius` (two cylinders/cones/spheres whose radii differ within tolerance — the proposal that turns four separate hole diameters into one driven parameter, which is a large part of what makes a model feel intentional).

The unit also produces the **reconstruction program**: which regions group into which archetype (KTD8), which proposals are adopted, and which relationships become sketch constraints versus shared user parameters. Adoption is an explicit recorded decision per proposal — the proposal itself stays a proposal.

**Live-Fusion dependency: NO.**

**Test scenarios:** a symmetric part with two equally good axis candidates refuses `frame-ambiguous` rather than picking; the same dump yields a bit-identical frame across runs and across shuffled region ordering; a bolt circle yields an X from the second cylinder; a part with no plane parallel to Z refuses `frame-x-underdetermined`; a cylinder tangent to a plane produces a `tangent` proposal with its measured deviation; four near-equal hole radii produce `equal_radius` proposals; an unadopted proposal never appears in the reconstruction program's constraint list.

**Size:** M.

---

### U4 — Feature emission: sketches, constraints, extrude and revolve *(PR 4, with U5)*

**Goal:** Turn a reconstruction program into real Fusion features.

**Requirements:** R8, R9, R10, R13, R14, R15.

**Files:** `src/fusion_design/mesh_rebuild.py` (new, emitter + in-Fusion `run`), `src/fusion_design/cli.py`, `tests/test_mesh_rebuild.py`, and a regenerated example under `examples/`.

**Approach:** `fusion-design emit-mesh-rebuild <manifest> --classification <c.json> --program <program.json>`. The emitted transaction follows the established pattern exactly — `_script_prelude`, `FUSION_DESIGN_REPORT_BEGIN/END`, `getattr` capability probes that refuse rather than default, `_pump_events` between feature groups, fail-closed tokens, full rollback on any refusal.

Per archetype:

- **`sketch-extrude`:** create a `ConstructionPlane` at the cap plane's offset along its normal; `sketches.add`; emit `sketchCurves.sketchLines`/`sketchArcs`/`sketchCircles` from the `SketchEntity` tuple that `classify_polyline` already produces; apply constraints incrementally per KTD7; add driven dimensions bound to named user parameters; `extrudeFeatures` between the two cap offsets, cut or join per the region's orientation.
- **`revolve`:** construction plane containing the primary axis; profile from the axial section's one side; `revolveFeatures` at 360°.
- Section profiles come from `mesh_fitting.section_mesh` + `classify_polyline` — already written, already tested, finally called.

**Refusals**, each rolling back everything created: `rebuild-capability` (a probed API absent), `dump-hash-mismatch` (R1's round-trip check — the live mesh no longer matches the dump the plan was fitted from), `profile-not-closed` (a section that did not chain into a closed loop is not a profile and is never force-closed), `constraint-rejected` beyond a declared count, `solver-unhealthy`, `feature-failed`.

**Live-Fusion dependency: YES** for execution. Offline coverage: the generated source compiles and executes against the stubbed-`adsk` harness with every refusal path exercised, plus the byte-pinned example (F8) regenerated and asserted.

**Test scenarios:** a plan for a box emits one sketch with four lines, four coincidences, two dimensions, and one extrude; a plan for a turned part emits a revolve; a section that fails to close refuses and creates nothing; a constraint that displaces geometry beyond tolerance is removed and reported; a dump hash mismatch refuses before any sketch is created; a mid-emission feature failure rolls back every prior feature in the group; the emitted script contains no `baseFeatures` call (R9), asserted by string search over the generated source; the byte-pinned example matches its emitter.

**Size:** L.

---

### U5 — Editability verification by perturbation *(PR 4, with U4)*

**Goal:** Prove the result is genuinely parametric by changing parameters and recomputing.

**Requirements:** R11, R12, R14, R15.

**Files:** `src/fusion_design/mesh_editability.py` (new), `src/fusion_design/cli.py`, `references/verification-contract.md`, `tests/test_mesh_editability.py`.

**Approach:** `fusion-design emit-mesh-editability <manifest> --rebuild-record <r.json> --editability-spec <spec.json>`, where the spec declares, per parameter, a perturbed value and its rationale, plus `volume_restore_epsilon`. The transaction, per parameter:

1. read baseline: `timelineHealth`, body count, `volume`, bounding box, and the parameter's expression;
2. set the perturbed value; `computeAll()`; `_pump_events` around it;
3. assert no timeline error, body count unchanged, and **`abs(volume - baseline_volume) > 0`** — a parameter that changes nothing is `parameter-inert`, a **failure**;
4. restore the original expression; `computeAll()`;
5. assert volume returns within `volume_restore_epsilon` — otherwise `parameter-not-restorable`, a failure, and the document is left with the original expression and the failure reported loudly;
6. **only now** append this parameter's name to `checked`.

It additionally asserts that every body named in the rebuild record is backed by timeline entries of type sketch/extrude/revolve/hole/fillet and **not** by a base feature (R9/F10), and it carries the dump hash, manifest hash and rebuild-record hash forward.

It never reads `design.designType` as evidence.

**Live-Fusion dependency: YES.** Offline coverage: the stubbed harness drives every branch, including a stub whose `computeAll` raises mid-loop, asserting the raising parameter is absent from `checked` (R12's enforcing test), and a stub whose volume does not change, asserting `parameter-inert`.

**Test scenarios:** as above, plus — a report for a design where one of three parameters is inert lists two in `checked` and fails; a base-feature-backed body fails the feature-type check; a restore that does not return the volume fails; `designType` appears nowhere in the generated source, asserted by string search.

**Size:** M.

---

### U6 — Partial reconstruction, holes, fillets, doctrine and live acceptance *(PR 5)*

**Goal:** The remaining archetypes, the coverage reporting, and the agent-facing surface.

**Requirements:** R8, R13, R14, and the doctrine obligations.

**Files:** `src/fusion_design/mesh_rebuild.py` (hole and fillet archetypes), `references/mesh-reconstruction.md`, `references/unsupported.md`, `references/capability-matrix.md`, `SKILL.md`, `templates/DESIGN-STATE.md`, `docs/live-fusion-acceptance.md`, both plugin manifests, `tests/test_skill.py`.

**Approach:** Hole classification per KTD8, gated on `isOriented` and refusing to classify rather than guessing on an unoriented mesh. Fillets emitted last, individually optional, detected by adjacency and near-constant width rather than by torus fitting. `covered_area_fraction` computed and reported; the label set `parametric-full` / `parametric-partial` / `reconstruction-refused` wired through the handoff so `parametric-partial` can never be abbreviated.

Doctrine updates: replace `references/mesh-reconstruction.md`'s "What is not built here" section with what is now built and what still is not; state KTD9 (we recover *a* parameterization, not *the* original) plainly; document the closed refusal vocabulary; document every declared threshold and what a sensible rationale looks like. `references/unsupported.md` records the standing refusals: freeform/organic recovery, torus fitting, constraint solving of our own, whole-part guarantees, and operation above the declared noise floor.

Live acceptance in `docs/live-fusion-acceptance.md`: a marketplace STL taken through capture → classification → extract → segment → fit → frame → plan → rebuild → editability → deviation, with the Fusion version recorded (every mesh API involved is preview) and both the coverage fraction and the unreconstructed regions listed.

**Live-Fusion dependency: YES** for the acceptance case; NO for the archetype code and the doctrine.

**Size:** M.

---

## Sequencing and relative size

| PR | Units | Size | Lands something usable? |
| --- | --- | --- | --- |
| 1 | U0 + U1 | S + M | Yes — a recorded capability probe against the user's actual Fusion, and `emit-mesh-extract` to pull a mesh out and inspect its face groups and noise floor host-side. Settles A1 and A4, and records the interpreter tag set that a Fusion auto-update would change. U0 lands first within the PR so U1's fallbacks respond to real answers. |
| 2 | U2 | **L** | Yes — `fit-regions` produces a fit record from a dump with **no Fusion needed at all**. This is the crux; it lands alone. Settles A2, A3, A5. |
| 3 | U3 | M | Yes — a datum frame and a full reconstruction program, reviewable before a single feature is emitted. |
| 4 | U4 + U5 | **L** | Yes — the first genuinely editable body, *with* its perturbation proof. These ship together deliberately: an emitter without its editability proof is exactly the "asserts more than it verified" failure. Settles A6. |
| 5 | U6 | M | Yes — holes, fillets, coverage reporting, doctrine, live acceptance. |

Total: one small, three medium and two large units. **PR 2 is the one to over-resource**; PRs 1, 3 and 5 are mostly mechanical once their contracts are fixed. PR 4 is large mostly in API surface rather than in difficulty — the hard thinking is all in PR 2.

**Independent and optional, not on this critical path:** the host-side packaging PR described in KTD2 (a `pyproject.toml` with zero required dependencies and an import-guarded `[fast]` extra). It can land before, between, or after any of these, or never. It is listed here so it is not silently forgotten, not because anything waits on it.

**Licensing constraint on every PR here:** `Shpigford/nurb` is licensed `LicenseRef-FSL-1.1-MIT` — the Functional Source License, **not OSI open source**. No code from it, on `main` or in the closed PR #41, may be copied into this repository. Architectural observations are fine and are cited above; implementations and text are not. State this explicitly in each PR description that touches segmentation or fitting, because that is where the temptation would be.

---

## Verification Contract

**Offline gate** — `plugins/agent-utilities/skills/fusion-parametric-design/scripts/test.sh` (unittest + compileall, F7). Covers:

- every dump format round-trip, hash check and refusal;
- all segmentation, noise-gating, fitting and disproof-gate behaviour against synthetic meshes with known analytic answers and their noise-injected variants;
- datum-frame determinism and every ambiguity refusal;
- all seven relationship kinds;
- every generated transaction's source compiled and executed against the stubbed-`adsk` harness, with **every refusal path** exercised;
- the byte-pinned example regenerated and asserted (F8);
- R12's enforcing test: a stub whose check raises leaves no `checked` entry;
- string-search assertions over generated source that `baseFeatures` and `designType` do not appear.

- the reconstruction program's schema: an unknown `program_version`, an unknown key, and an out-of-set value each refuse (R16), tested against a hand-authored malformed program;
- the probe record's shape, including a raising import reported as `unavailable` with its message.

**Explicitly not established offline**, and stated as such rather than implied — each with the unit that establishes it live, so none of these hides inside an otherwise-testable step:

| Not established offline | Established by |
| --- | --- |
| Whether `triangleFaceGroupTempIds` is populated or meaningful on a real imported mesh (A1, A2) | **U0** probe + **U2** agreement statistic |
| Whether a file written from Fusion's Python is readable by the host (A4) | **U0** write/read-back round trip |
| Whether `numpy` imports in the user's Fusion (F4 is one prior session) | **U0** probe |
| Whether every construction API this plan needs exists in the connected Fusion | **U0** probe |
| Whether Fusion's sketch solver accepts our constraint sets (A6) | **U4** live run |
| Whether any emitted feature actually builds | **U4** live run |
| Whether a parameter change actually rebuilds the model | **U5** live perturbation loop |

**Live gate** (single Fusion instance, version recorded, every mesh API preview): the issue's acceptance case — a marketplace STL with a dimensional modification, taken end to end, producing an editable timeline whose parameter change is proven by U5's perturbation loop, and graded against the immutable source by the existing asymmetric deviation verdict.

**What the verification does not claim**, written into the report itself:

- coverage below 100% is stated as a fraction with the unreconstructed regions listed; it is never rounded up to "reconstructed";
- a passing perturbation proves the named parameters rebuild, and nothing about parameters that were not exercised;
- a small deviation in either direction is not a fitness claim; a fit coupon is still required before any mating claim (plan 003's R12, unchanged);
- the recovered timeline is *a* parameterization consistent with the surface, not the original design intent (KTD9).

---

## Definition of Done

R1–R17 implemented and tested. A live capability probe is recorded against the user's actual Fusion version and every downstream artifact references it. The reconstruction program is versioned, hash-bound in both directions, closed-vocabulary, declarative-only, and refuses anything it does not fully understand. Mesh data reaches the host bound by a hash that the emission transaction re-derives from the live mesh. Segmentation names its source and refuses when the measured noise floor makes it meaningless. Every accepted fit survived support-span, residual-structure and held-out disproof. The datum frame is derived from the fits, deterministic, and refuses when ambiguous. Seven relationship kinds are proposed with their deviations and adopted only by recorded decision. Emission produces sketches, constraints, dimensions, extrudes, revolves, holes and fillets — and never a base feature. Editability is proven by changing each declared parameter, recomputing, observing a volume change, restoring, and recomputing again; the `checked` list contains only parameters that actually completed that loop. Partial reconstruction reports a coverage fraction and lists what it did not rebuild. Every threshold is caller-declared with a rationale. Doctrine and `unsupported.md` state both what is now built and what remains refused. Live acceptance recorded against a named Fusion version. Merged PRs with post-merge proof and marketplace repin.

---

## Not achievable within these constraints — and why

These are conclusions, not deferrals. Each names the reason.

1. **Freeform and organic surface recovery.** NURBS patch fitting at usable quality is not a stdlib project, and Fusion's own `Organic` mesh-convert method requires the Design Extension. More fundamentally, it is the wrong goal: Design X's `Auto Surfacing` produces exactly the featureless "1-to-1 dummy CAD" the user is trying to avoid. Freeform regions are `unreconstructed` and counted against coverage. **Permanent refusal.**

2. **A constraint solver of our own.** Fusion's sketch solver is the solver, and it is a black box that can reject or silently satisfy. We can only apply incrementally and check (KTD7). Anything more would mean reimplementing a geometric constraint solver in stdlib Python, which is a project, not a unit.

3. **Recovering the original designer's intent.** We recover a feature tree consistent with the measured surface. A boss modelled as an extrude and the same boss modelled as a revolve are indistinguishable from the outside. No tool solves this; QUICKSURFACE and Design X both put a human in the loop precisely here.

4. **Fully automatic operation on arbitrary noisy scans.** KTD5's arithmetic is the reason: when the normal-noise floor approaches the crease threshold, segmentation boundaries *are* the noise, and no downstream check catches it because every residual is consistent with the wrong region. Above that floor the run refuses. This will refuse on some real scans, and that is the correct behaviour for a skill whose doctrine is refusal over invention.

5. **Torus fitting, and therefore true fillet-surface recovery.** Fillets are proposed by geometric adjacency and near-constant width, which is enough to emit a `filletFeatures` radius but not enough to certify a variable-radius or elliptical blend. Those fall to `unreconstructed`.

6. **Any use of Fusion's Mesh Section Sketch or Fit Curves to Mesh Section.** UI-only, no API (F13). Structural, unchangeable.

7. **Stable region identity across Fusion sessions via face-group temp ids.** They are temp ids (A3). Region identity is re-derived geometrically instead, which costs a hash and removes the dependency entirely.

8. **A guaranteed 100% coverage on any part.** `parametric-partial` exists because it is the honest common case, and any promise otherwise would be the thing this whole plan is a correction to.

9. **OCCT, CadQuery, build123d or any second B-Rep kernel** — not "not achievable" but **actively counterproductive** (KTD2), and now empirically so: nurb ships OCCT 7.9 and exports STEP that opens in Fusion as a dumb solid. Anything a second kernel builds enters Fusion as an imported solid or a base-feature body, both history-free and uneditable. It would produce a better reconstruction that arrives dead.

10. **~~numpy or scipy inside Fusion's interpreter.~~ — REMOVED 2026-08-19 for numpy. This entry was wrong.** numpy 2.5.2 loaded from a `cp314` / `macosx_11_0_arm64` wheel and executed compiled LAPACK inside Fusion (F4), and installing it needs nothing built — one pip command with four flags, into a directory already on Fusion's `sys.path` (F4b). Kept struck through rather than deleted, because a plan that quietly removes its wrong claims teaches nothing. We still do not take the dependency (KTD2) — for reasons of testability, maintenance and need, **not** capability.

    **But scipy specifically is genuinely unavailable right now**, and that is a different statement: no `cp314` / `arm64` wheel has been published (F4c). It is temporary, it is checkable by running the pip command, and it is the single best illustration of why F4c and not F4 is the argument that matters. Any design that had put scipy on its critical path would be blocked today, through nobody's fault and on nobody's schedule.

11. **~~Growing the module bundle into a dependency mechanism.~~ — REMOVED 2026-08-19. This entry was wrong twice over.** It is neither impossible nor expensive, and more to the point **nothing needs to be built**: pip installs third-party wheels for Fusion's interpreter with four flags and full transitive resolution (F4b), into a directory already on Fusion's `sys.path` (F4). Kept struck through rather than deleted, because a plan that quietly removes its wrong claims teaches nothing. **What is actually true:** `module_cache.py` stays `.py`-only as a **scope boundary** — it carries our own code with hash verification and verified imports; third-party wheels are pip's job. `references/unsupported.md` must record that as scope, never as a capability gap. The remaining real constraint is F4c: the wheel has to *exist* for Fusion's Python, and today scipy's does not.

12. **nurb's model — "the parametric artifact is a Python source file."** Genuinely viable, and explicitly rejected for this issue. nurb's parametric object is a build123d `.py` with slider-editable numbers; what reaches CAD is a faceted or dumb-solid export. The user asked for *"a parametric thing we can edit"* in Fusion, and Fusion's timeline is the only thing that satisfies that. Naming this here because it is the road not taken, and it is a reasonable road for a different product.
