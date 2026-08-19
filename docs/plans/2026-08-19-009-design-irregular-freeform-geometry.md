---
title: "design: irregular and freeform geometry — the archetype ladder beyond five primitives (issue #20)"
date: 2026-08-19
artifact_contract: ce-unified-plan/v1
artifact_readiness: design
execution: code
origin: https://github.com/novotnyllc/agent-utilities/issues/20
builds_on: docs/plans/2026-08-19-005-feat-mesh-parametric-reconstruction-plan.md, docs/plans/2026-08-19-006-design-u4-u5-feature-emission.md, docs/plans/2026-08-19-007-research-reconstruction-algorithms.md, docs/plans/2026-08-19-008-research-prior-art-landscape.md
---

# Summary

The issue-#20 pipeline reconstructs only what decomposes into plane / cylinder / sphere / cone / torus, emitted through four archetypes (`sketch-extrude`, `revolve`, `hole`, `fillet`). On a real scanned part that vocabulary claims a fraction of the surface and honestly reports the rest as `unreconstructed` — honest, and disappointing. The user's requirement is that it handle irregular shapes.

The design is a **ladder of five rungs**, ordered by value per unit of new machinery, with a single linear test — the **kinematic-surface router** — deciding which rung a region is offered:

1. **Arbitrary closed profiles** (lines + arcs + fitted splines) for `sketch-extrude` and `revolve`. One new sketch-entity kind, one new region test, and the largest coverage win available anywhere in this problem: most "irregular" mechanical geometry is an irregular *outline*, not an irregular *surface*.
2. **Extrude with taper**, then **loft** between classified sections on parallel datum-offset planes.
3. **Sweep**, restricted to circular-profile pipes (constant-radius tube along a curved spine).
4. **Ruled surfaces** — deliberately *not* a rung: a ruled transition is a two-section loft, already covered. No dedicated machinery.
5. **True freeform** — stays reference mesh in the document, and the reasons are structural, not timid: the only API route for fitted surface data into a parametric Fusion design is a base feature, which this codebase bans (R9/E15), and a fitted NURBS patch would not be "parametric" in the sense the user means even if it could be emitted. This document says precisely what each rung's output *is* editable as, because "parametric" means three different things across the ladder and conflating them is the over-claim this codebase is repeatedly audited for.

Everything below rung 5 is stdlib-tractable with the existing linear-algebra kernel (one 6×6 eigen extension of the existing 3×3 Jacobi, one tridiagonal solve). Coverage expectation on a typical machined or molded mechanical part: rung 0 claims ~60–80% of surface area today; rung 1 lifts that to ~80–90%; rungs 2–3 add a few points each; the remainder is honestly-labelled reference mesh — which matches what Design X and QuickSurface ship, where hybrid output (features + labelled remainder) is the documented normal case, not a failure.

# Problem frame

Three facts shape everything:

1. **The profile machinery already exists.** `section_mesh` produces chained polylines with named degeneracies; `classify_polyline` greedily splits a polyline into line and arc runs against a caller tolerance (`mesh_fitting.py:652`). The gap is exactly one entity kind: a run that is neither line nor arc within tolerance currently has no answer, so any region whose section needs one is unreconstructable regardless of how prismatic it is.

2. **The emission architecture already supports irregularity everywhere except the profile vocabulary.** 006's planner/executor split, datum-offset sketch planes (E3), the constraint ladder with the recorded-defect path for under-constrained sketches (D3), partial reconstruction as a first-class outcome (D8) — none of these assumed profiles are lines and arcs. A spline-bearing sketch will rarely be fully constrained, and D3 *already* decided that case: emit, record `fully_constrained: false`, let U5's perturbation loop measure whether it is harmful. The hard policy questions were answered before this document.

3. **The router signal already exists.** U2 computes per-vertex HK curvature signatures (Besl–Jain) and per-region dominant signatures, used as bias-not-veto ranking (`mesh_segmentation.py:375–397`). A region reported "saddle, and no supported primitive fits a saddle" is today a dead end; below it becomes the entry ticket to the ladder.

## Verified facts (this repository, today)

- **F1.** `ENTITY_KINDS = {"line", "arc", "circle"}` (`mesh_fitting.py:55`); `SketchEntity` guarantees consecutive entities share endpoint coordinates exactly (its docstring, relied on by 006 G2/B3).
- **F2.** `classify_polyline` is greedy longest-run, line-vs-arc, with a `ponytail:` note flagging its O(n²) refits (`mesh_fitting.py:702–707`). It has no fallback kind: an unfittable stretch degrades into many short line segments, each within tolerance — a polygonal approximation wearing a classification.
- **F3.** `ARCHETYPE_KINDS = {"sketch-extrude", "revolve", "hole", "fillet"}` (`reconstruction_program.py:84`), enforced by the closed-vocabulary validator (`_check_vocabulary`), with `_ARCHETYPE_FIELDS` per-kind field sets. `plan_archetypes` assigns only `sketch-extrude` and `revolve`; everything else falls to `unreconstructed` with a named reason (`reconstruction_program.py:854`).
- **F4.** The segmentation record carries per-region `orientation`, inlier sets, and unclaimed regions with dominant curvature signature; `_RANKED_KINDS` biases fit order by signature and never vetoes.
- **F5.** The linear kernel is: 3×3 cyclic Jacobi (`_symmetric_eigen`), Gauss–Jordan with partial pivoting on centred/scaled data (`_solve`), 2-D least-squares circle, line fit. 007 §13.2 additionally specifies a Levenberg–Marquardt engine over JᵀJ for U2's refinement.
- **F6.** 007 §11.2 budgets the whole pipeline at 2–6 minutes for 200k vertices in CPython and names the two levers (principled subsampling; the numpy escape hatch that is not this document's to take). §12.2 names "large SVD (e.g., NURBS surface fitting)" as the signal to stop being pure Python.
- **F7.** 005's Not-achievable list makes freeform a "permanent refusal", with two reasons: NURBS fitting is not a stdlib project, and auto-surfacing produces the featureless dummy CAD the user is avoiding. This document *narrows* that refusal (rungs 1–3 remove most of what used to fall into it) and re-grounds what remains (see rung 5) — it does not overturn it.
- **F8.** 008 §2.5/§3: the abandoned US20070285425A1 teaches, unprotected and in patent-level detail, the exact loop this design extends — section → split polyline into **line/arc/curve** segments by curvature distribution → constrained sketch → **extrude/revolve/loft** → boolean merge → deviation check. §5.1: Design X's wizard set is Extrusion, Revolution, **Sweep, Loft, Pipe** — the commercial validation of this exact ladder. US6996505 (expired 2023) is the free blueprint for mesh→NURBS quilting if rung 5 is ever revisited.

## Fusion API assumptions — labelled, with the probe that settles each

House rule (006): API claims that cannot be verified offline are assumptions with settling steps, and every one fails closed.

- **C1. `sketch.sketchCurves.sketchFittedSplines.add(points)`** (an `ObjectCollection` of `Point3D`) creates an **editable** degree-3 NURBS interpolant through the fit points, and the created spline exposes `geometry`/`evaluator` so the transaction can sample it immediately. Load-bearing for rung 1. Settled by: first live run; the in-transaction deviation check (below) is the enforcement. Contrast: `sketchFixedSplines.addByNurbsCurve` creates a **fixed** (non-editable) spline — explicitly *not* used, because a fixed spline is frozen geometry wearing a sketch entity, the exact over-claim to avoid.
- **C2.** A fitted spline's end fit points can be the shared `SketchPoint` of an adjacent line/arc (006 B3 analog), and `geometricConstraints.addTangent` accepts spline–line and spline–arc pairs. Fallback per 006: explicit coincident constraints; tangency simply not applied when rejected (recorded, D3 path).
- **C3.** `sketch.profiles` recognizes closed loops containing fitted splines, and `extrudeFeatures`/`revolveFeatures`/`loftFeatures` accept such profiles. Settled by first live run; refusal token `feature-failed`.
- **C4.** `ExtrudeFeatureInput.taperAngle` accepts a `ValueInput.createByString` expression (parameter-driven taper). Settled by live run.
- **C5.** `loftFeatures.createInput` with profile sections on parallel datum-offset construction planes produces a loft that **recomputes when a section sketch or plane-offset parameter changes**. Load-bearing for rung 2's editability claim. Settled by a U5-style perturbation on a loft plane offset.
- **C6.** A 3-D path for `sweepFeatures` can be built from a fitted spline through 3-D points (3-D sketch) plus `Path.create`, and the swept profile can live on a construction plane at the path start. Load-bearing for rung 3. Settled by live run.
- **C7.** Spline **fit points are live sketch points**: they can be moved/dimensioned via the API, and moving one recomputes dependent features. Load-bearing for the "point-editable" claim and for the U5 extension below. Settled by U5's fit-point perturbation.
- **C8.** The Fusion API exposes **no creation path for T-spline (Form) bodies** — Forms are UI-only. Expected-absent; a `getattr` probe records it. Consequence: no T-spline rung exists to design.

# The kinematic-surface router — one linear test that routes extrude, revolve, taper, and helix

Every rung-1/2 detection question ("is this region an extrusion? a revolution? something in between?") is a special case of one classical question: *is this surface invariant under a one-parameter rigid motion?* (Pottmann & Randrup, *Computing* 60, 1998 — academic, free.) A rigid motion's velocity field is `v(x) = c̄ + c × x`; the surface is swept by that motion iff every surface normal is orthogonal to the field: `n(x) · v(x) = 0`.

That condition is **linear in the six unknowns** `(c, c̄)`. With samples `(xᵢ, nᵢ)` (region vertices and their U2 trimmed-PCA normals):

```
n · (c̄ + c × x) = n·c̄ + c·(x × n)        # scalar per sample
row aᵢ = [ xᵢ × nᵢ  ,  nᵢ ] ∈ R⁶          # xᵢ centred at region centroid, scaled by extent
M = Σ aᵢ aᵢᵀ  (6×6 symmetric)
(λ_min, w) = smallest eigenpair of M       # w = (c, c̄), |w| = 1
```

The 6×6 symmetric eigenproblem is the existing 3×3 cyclic Jacobi generalized to n×n — the same sweep over off-diagonal pairs, ~30 lines of change, no new numerics. Accumulating M is one O(N) pass. Centring and scaling `x` before building rows is mandatory (it is also the house precedent from `_solve`): the two halves of the row otherwise mix units and the pitch below comes out in garbage units. Recovered quantities are un-scaled afterwards.

**Classification from `(c, c̄)`**, with `p = (c·c̄)/|c|²` (the pitch):

| Structure | Motion | Region verdict |
| --- | --- | --- |
| `c ≈ 0`, `c̄ ≠ 0` | translation along `c̄` | **extrusion**, direction `c̄` |
| `c ≠ 0`, `p ≈ 0` | rotation; axis dir `c/‖c‖`, axis point `(c × c̄)/‖c‖²` | **revolution** about that axis |
| `c ≠ 0`, `p ≠ 0` | screw motion, pitch `p` | **helical** (thread/coil) — reported, not emitted (v1) |
| `λ_min` large | no invariant motion | falls through toward loft / pipe / freeform |

Gates, in the house style (every threshold caller-declared with a rationale; defaults tied to measured noise, not magic):

- **Residual gate:** `sqrt(λ_min / N)` is an RMS of `n·v` over unit-normalized samples — an angular quantity. Accept only when it is within a declared multiple of U2's measured normal-noise floor `σ_θ` (007 §4.2). This is the same "gates from the noise model" discipline as everything else in 007.
- **Eigengap gate:** planes, spheres, and cylinders make `M` rank-deficient (a plane admits a 3-parameter family of invariant motions; a sphere any rotation about its centre). The router runs **only on regions the primitive stage disclaimed**, so hitting a degenerate spectrum means the primitive stage and the router disagree — refuse routing for that region (`router-ambiguous`, recorded with both eigenvalues) rather than pick an eigenvector arbitrarily. Never a guess.
- **`c ≈ 0` and `p ≈ 0`** are declared thresholds on the scaled quantities, each with its rationale, both recorded in the region record with the measured values — the record must let a reviewer see how close the call was (007 §12.3 discipline).
- **HK bias, not veto** (existing doctrine): a region whose dominant signature is `peak-pit` (doubly curved, same sign) cannot be an extrusion; the router still runs, but the signature orders how much verification the verdict gets and gives the refusal message its vocabulary. A doubly-curved signature *with* a passing translational fit is a contradiction worth flagging loudly (`router-signature-conflict`, recorded, routed to the more conservative outcome: fall through).

The router's verdict is a *proposal*; each rung then applies its own confirmation (profile-constancy, section classification) before an archetype is planned. Propose → verify → refuse is the shape of everything else in this pipeline; the router is not an exception.

# The ladder

## Rung 1 — arbitrary closed profiles: `spline` joins `line` and `arc`

**This is the highest-value change in this document.** An irregularly-outlined bracket, cam, gasket, cover plate, extruded-aluminium profile, or curved-walled pocket is fully parametric geometry — a 2-D outline extruded — that today reports as `unclaimed` because its section has runs no line or arc explains. The fix touches one classifier, one entity vocabulary, and the emission planner's profile path; the entire downstream architecture (constraints, planes, extents, parameters, U5) was already designed for it.

### 1a. Classifier extension: three-way segmentation with curvature-driven split points

`classify_polyline` gains a third kind. The algorithm (replacing pure greedy where it matters, per 008 recommendation 6, from the INUS disclosure):

1. **Split-point detection first.** Compute discrete turning angle at each interior polyline vertex (the `_sharpest_corner` machinery, applied everywhere rather than once). Mark as *breakpoints*: corners above a declared angle threshold, and extrema of the smoothed discrete curvature (the INUS "curvature distribution" rule). Breakpoints are where entities may meet; the greedy fitter no longer decides segment boundaries by accident of fit order.
2. **Per-span classification, simplest-first with the existing tolerance:** line, then arc (existing fits), then **spline** as the residual kind. A span that a line or arc explains within tolerance never becomes a spline — the exact `_SIMPLER_KINDS` discipline lifted from primitive fitting: a richer entity through points a simpler one explains is an artefact.
3. **Adjacent spline spans merge**; adjacent line/arc spans keep the existing greedy contest.

The new entity:

```python
SketchEntity(
    kind="spline",
    start=..., end=...,             # polyline's own points, shared with neighbours (F1 invariant)
    residual=...,                   # worst deviation of the span's points from the host-side interpolant
    point_count=...,                # points in the span
    fit_points=(...),               # the selected dominant points, ordered, including start/end
    tangent_start=None|Vec3,        # measured end tangents, carried so emission can
    tangent_end=None|Vec3,          #   propose (never force) tangency to neighbours
)
```

`ENTITY_KINDS` grows to `{"line", "arc", "circle", "spline"}`; program schema bumps to version 2 (D9's validator makes the old/new boundary loud).

### 1b. Fit-point selection: interpolate through few dominant points, never approximate through many

Fusion's editable spline is a **fitted spline: an interpolant through fit points** (C1). So the host-side question is not "what approximating B-spline fits these points" but "what is the *smallest* set of fit points whose interpolant stays within tolerance of the section polyline". That is dominant-point selection (Park & Lee's adaptive dominant-point B-spline fitting is the citable form; the greedy version below is sufficient and simpler):

```python
def select_fit_points(span_pts, tol, min_spacing):
    # Start minimal: endpoints + curvature-extrema breakpoints inside the span.
    knots = [0, *curvature_extrema(span_pts), len(span_pts) - 1]
    while True:
        interp = natural_cubic_through(span_pts, knots)   # tridiagonal solve, O(k)
        worst_i, worst_d = max_deviation(span_pts, interp)  # O(n) point-to-curve
        if worst_d <= tol:
            return knots, worst_d
        if too_close(worst_i, knots, min_spacing):
            return None            # cannot meet tol without spacing below the noise floor -> refuse
        insort(knots, worst_i)     # add the worst offender as a new fit point; repeat
```

Two declared gates keep scanner noise out of the curve — the "wiggle" question answered concretely:

- **`spline_tolerance`** — max deviation of the interpolant from section points. Floor: `max(declared value, 3·σ̂)` where σ̂ is U2's measured noise scale. Chasing the polyline below 3σ̂ is fitting noise by construction, so the floor is not optional.
- **`min_fit_point_spacing`** — minimum arc-length between fit points. Floor tied to 007 §12.1's feature-size floor (~10·σ̂): a fit point pair closer than the smallest resolvable feature is reproducing noise texture. When the loop cannot meet tolerance without violating spacing, the span **refuses to be a spline** and the region falls through (`profile-unresolvable`, with both measured numbers) — never a 400-point spline that is a mesh in sketch clothing.
- **`max_fit_points_per_profile`** (declared, rationale required; doctrine default ~60): the editability budget. A profile needing more is not something a human will ever edit point-by-point; refusing it to reference-mesh is more honest than emitting it.

A held-out check in the existing disproof style (refit the interpolant on alternate section points, measure on the others) guards against a section polyline whose "shape" is one noisy traverse; it reuses the `_heldout_residual` pattern verbatim on curves.

Host-side cubic interpolation is a tridiagonal solve — O(k), stdlib, and *not* claimed to equal Fusion's interpolant. It is the planner's estimate; the authority is:

### 1c. In-transaction verification: measure Fusion's spline, don't predict it

Fusion's fitted-spline parameterization (knot placement, end conditions) is not documented to the precision this pipeline requires, and the honest design does not guess. After creating each spline, the executor samples the created curve's evaluator at parameter stations and measures the max distance to the span's section points:

```python
spline = fitted_splines.add(fit_point_collection)
ev = spline.geometry.evaluator                     # C1
worst = max_distance(sample(ev, k), span_points)   # both in sketch coords
if worst > spline_tolerance * SLACK:               # SLACK declared, rationale: interpolant family differs
    refuse("profile-spline-deviation", entity_id, worst)   # rolls back per D8
```

The planner's host-side estimate makes refusals rare; the in-transaction measurement makes the tolerance claim *true*. This is the same measure-don't-assume shape as the dump re-hash (E8).

### 1d. Emission and constraints

- Profile loops may mix all four kinds. Chaining via shared `SketchPoint`s is unchanged (F1/B3); a spline's end fit point is the shared point.
- Constraint ladder (006 D3) applies as-is: lines/arcs get their full schedule; splines contribute endpoint coincidence (layer 0) and *proposed* tangency at junctions where the measured tangent deviation is within `snap_tolerance_deg` (layer 1, `snapped_from` recorded, C2). Nothing else — a spline is not dimensioned.
- Spline-bearing sketches will generally report `fully_constrained: false`. **That path already exists as a recorded defect, not a refusal** (D3), and U5 measures whether it is harmful. No new policy is invented here; that is a design feature of this rung, not an accident.
- `plan_archetypes`' extrude/revolve grouping extends to router-verdict regions: an extrusion-verdict region contributes side walls; caps are found by the existing `_extrude_caps` logic against adjacent planar regions; the profile comes from `section_mesh` at a mid-station between caps, classified by the extended classifier. Revolution-verdict regions section on a plane containing the recovered axis; the half-profile's `(ρ, z)` points classify in 2-D. Both verdicts get a **constancy confirmation** first: extrusion — sections at 3 declared stations must agree within tolerance (point-to-polyline Hausdorff, small-n O(n²), fine); revolution — binned-by-z spread of ρ must stay within tolerance. Confirmation failure falls through to rung 2 with the measured disagreement attached (which is exactly the loft signal).

**Where rung 1 stops paying:** it doesn't, within its own scope — it is nearly pure win, riding entirely on existing architecture. Its boundary is the fit-point budget: profiles that cannot be captured under `max_fit_points_per_profile` and the spacing floor are declared out of scope and fall to freeform, by measurement, with the numbers recorded.

## Rung 2 — taper, then loft

### 2a. Tapered extrusion — the cheap sibling, taken first

If sections along the extrusion axis are *scaled* copies of one another about a common centre, and scale is linear in station, the region is a Fusion extrude with a taper angle — one parameter, no new feature machinery (C4). Detect during rung 1's constancy confirmation (it is the cheapest failure mode of "sections agree"): per-station similarity transform (scale s(z) about fitted centre), linearity check on s(z). Emit as `sketch-extrude` with `taper_angle` bound to a user parameter. Fully dimension-driven; full U5 proof applies. Ponytail note: this one conditional catches draft angles on molded parts — a large fraction of real "extrusion that isn't quite" — for ~zero cost.

### 2b. Loft between classified sections

**Detection.** Reached by fall-through: the router found no invariant motion (or the constancy check failed), but the region is smooth, elongated along an axis (PCA long axis or a datum axis), and `section_mesh` at stations along that axis yields *closed, classifiable* profiles (rung-1 classifier, same budgets). If the sections themselves refuse classification, the region is not a loft — fall through to rung 3/5.

**Section-count selection** — the honest mechanism, because the host cannot evaluate Fusion's loft surface and does not pretend to:

1. Plan starts minimal: **two end sections + one mid section** on parallel datum-offset planes (E3-compatible by construction — this is why the planes are parallel offsets and not local Frenet frames).
2. Emit; run the **existing deviation machinery** (`mesh_deviation`) between the lofted body and the source mesh region.
3. Where deviation exceeds the declared threshold, the CLI's replan loop (D8's `replan-without` pattern, extended to `replan-with-sections`) inserts a section at the worst-deviation station and re-emits. Explicit, recorded, one command per iteration — adaptation lives host-side in the visible loop, never inside Fusion (E1).
4. **`max_loft_sections`** (declared; doctrine default 6) caps the loop. A region still failing deviation at the cap is declared `unreconstructed` with the achieved deviation recorded. Rationale, stated in doctrine: a 20-section loft of 60-point spline profiles is a frozen shape wearing a feature — the model stops being *editable in intent* long before it stops being *emittable*, and the cap is where this design draws that line deliberately.

**Editability meaning (recorded per archetype, see the honesty table):** section profiles are point-editable sketches; section plane offsets are dimension-driven parameters (loft "stations" are real edit handles, C5); section *count* is fixed at emission. Guide rails and end-tangency conditions: v1 emits none — `references/unsupported.md` records it. A loft without rails is the simplest loft Fusion offers and the only one whose behaviour under section edits is predictable enough to verify.

**Where rung 2 stops paying:** at `max_loft_sections`. The paying zone is transitions and tapered/blended housings whose cross-sections are simple; the non-paying zone (many sections, complex profiles) is better served by honest reference mesh, and the deviation-driven loop finds the boundary by measurement instead of opinion.

## Rung 3 — sweep, restricted to circular-profile pipes

**Scope decision up front:** general sweep recovery (arbitrary constant profile along an arbitrary path) requires establishing a moving-frame correspondence along an unknown spine — genuinely hard, low incidence on mechanical parts, and Design X ships "Pipe" as its own wizard for the same reason. v1 recovers **pipes**: constant-radius circular profile along a smooth spine. Tubes, handles, wire channels, hydraulic runs.

**Detection.** HK signature is the trigger: `ridge-valley` region (one principal curvature ≈ constant 1/r, the other varying) that the cylinder/torus fits *rejected* (a straight tube is a cylinder — already claimed; a constant-curvature bent tube is a torus — already claimed; a pipe is what remains). Estimate r robustly from the near-constant principal curvature (median of 1/κ₁ over the region, spread gated).

**Spine recovery**, with its noise problem stated: centre estimates `cᵢ = xᵢ − r·nᵢ` amplify normal noise by r. Mitigations, in order: average `cᵢ` over neighbourhoods before fitting (the grid index exists); fit the spine as a rung-1 dominant-point spline in 3-D with tolerance floored by the *amplified* noise `r·σ_θ` (not σ̂ — using the un-amplified floor here would be fitting noise while citing the wrong noise); refuse (`spine-untraceable`) when the spread of centre estimates across the tube's own diameter says the spine is not a curve. Branching junctions (tees) are refused at spine-tracing time — a junction in the centre-estimate adjacency graph splits the region and each branch is retried separately, the junction region itself falling to freeform.

**Emission (C6):** 3-D sketch fitted spline for the path; profile circle (diameter → user parameter) on a plane at the path start; `sweepFeatures`. Editability: **diameter is dimension-driven** (full U5 proof); the path is point-editable.

**Where rung 3 stops paying:** exactly at its scope edge. Non-circular constant profiles and variable-radius pipes are recorded in `unsupported.md` with the reason (moving-frame correspondence; variable-radius canal fitting) rather than attempted badly.

## Rung 4 — ruled / developable: not a rung

A ruled transition between two profile curves is a two-section loft — rung 2 already emits it, and Fusion's loft of two sections *is* the ruled surface. Developable-specific machinery (flanges, bends, unrollable surfaces) is sheet-metal territory with its own feature vocabulary this pipeline does not target. No machinery is built; one paragraph in doctrine says why. (YAGNI, and deliberately so: every commercial tool folds ruled into loft.)

## Rung 5 — true freeform: reference mesh, and what "parametric" cannot mean

The remainder — doubly-curved, no invariant motion, sections unclassifiable, no constant tube radius — is organic geometry. The options, weighed honestly:

1. **Reference mesh in-document (chosen).** Already built: D8's planned partiality keeps the source mesh overlaid in the same document, and the report names each freeform region with area fraction, bbox, and — new, cheap — its dominant HK signature and measured curvature statistics, so the record says "saddle-dominated organic region, 12% of area" rather than "nothing fit". Cost: zero new machinery. This is also QuickSurface's documented normal case (hybrid output), minus their auto-surfaced quilt.

2. **Fitted NURBS patch quilt (rejected, with the reasons on the record).**
   - *Emission is structurally blocked.* The only API routes for arbitrary fitted surface data into a Fusion design are `TemporaryBRepManager` inside a base feature, or an imported dumb body — both are exactly what R9/E15 ban, for the good reason that they produce history-free geometry. C8: no T-spline creation API exists. There is no third route. A pipeline that fit beautiful patches host-side would still have no honest way to deliver them parametrically.
   - *The mathematics is the named pure-Python wall.* Curve fitting is trivial (tridiagonal / banded, O(n)); **surface** fitting over an arbitrary region requires parameterizing the region (a sparse linear system in ~10⁴–10⁵ unknowns — harmonic/conformal mapping) and then tensor-product least squares. 007 §12.2 already names large linear algebra of this class as the signal to stop being pure Python; iterative solvers in CPython at this size are tens of minutes per region and a numerical-robustness project besides. The expired US6996505 is the free blueprint should the dependency posture ever change — recorded as the revisit path, not attempted now.
   - *And it would not be "parametric" in the user's sense even if both walls fell.* A NURBS patch is editable by control-point dragging — sculpting, not design intent. No dimension drives it; no relationship constrains it; U5's perturbation proof has nothing to perturb. Design X's own auto-surface output is the "1-to-1 dummy CAD" the issue's user explicitly did not want (005, Not-achievable 1). Emitting it *labelled as a feature* would be the precise over-claim this codebase's audit history exists to prevent.

**What the user gets at this stop:** an editable model of everything rungs 0–3 recovered, the mesh remainder visible and labelled in the same document, and a report whose coverage fraction and per-region reasons are falsifiable. That is the designed boundary, and the doctrine states it as an outcome, not an apology.

# What "parametric" means at each rung — the honesty table

Recorded per archetype in the program and surfaced in the report; the result label never flattens these into one word.

| Output | Dimension-driven (U5-provable parameters) | Point-editable (live geometry, manual affordance) | Frozen at emission | U5 proof |
| --- | --- | --- | --- | --- |
| primitive extrude / revolve / hole / fillet (rung 0) | profile dims, extents, plane offsets, diameters, radii | — | — | full (existing) |
| spline-profile extrude / revolve (rung 1) | extents, plane offsets, line/arc dims | spline fit points | fit-point count | full on parameters **+ fit-point perturbation** (below) |
| tapered extrude (rung 2a) | + taper angle | as above | as above | full |
| loft (rung 2b) | section plane offsets | section profiles (as rung 1) | section count, no rails | plane-offset perturbation + fit-point perturbation |
| pipe sweep (rung 3) | profile diameter | path fit points | path topology | diameter perturbation + path-point perturbation |
| freeform remainder (rung 5) | — | — | everything (reference mesh) | none; excluded from coverage, named in report |

**U5 extension — the fit-point perturbation.** "Point-editable" is itself a claim, and it gets the same treatment as every other claim: for each spline-bearing sketch, U5 moves one declared fit point by a declared offset along the profile-plane normal to the curve (C7), recomputes, asserts the declared observable (centroid or bbox — never volume, position-class parameters per D7's own correction) moves beyond its floor, restores, asserts return within epsilon. A spline whose fit points move nothing is frozen geometry wearing an editable label — `spline-inert`, a failure. This closes the loop on the one editability meaning the existing U5 could not see.

# Vocabulary, schema, and refusal deltas

- `ENTITY_KINDS` += `spline` (fields per 1a; validator extends `_ARCHETYPE_FIELDS` for profile entries).
- `ARCHETYPE_KINDS` += `loft`, `sweep`; `sketch-extrude` gains optional `taper_angle`; program `program_version` → 2 (D9 validator makes v1 consumers refuse loudly).
- Region records gain a `routing` block: router eigenvalues, `(c, c̄, p)` scaled and unscaled, verdict, confirmation measurements, HK signature carried alongside — every close call inspectable.
- New refusal tokens (closed set, documented): `router-ambiguous`, `router-signature-conflict`, `profile-unresolvable`, `profile-spline-deviation`, `loft-sections-exceeded`, `spine-untraceable`, `sweep-branching-spine`, `spline-inert`.
- New declared thresholds (all with rationale strings, E14): `router_residual_sigma_factor`, `router_eigengap_min`, `spline_tolerance`, `min_fit_point_spacing`, `max_fit_points_per_profile`, `section_agreement_tolerance`, `max_loft_sections`, `loft_deviation_threshold`, `pipe_radius_spread_max`, `spline_fitpoint_perturbation` (U5).

# Stdlib tractability — what is cheap, what is heavy, what is a wall

| Piece | Method | Complexity | Verdict |
| --- | --- | --- | --- |
| Router accumulation | one pass over region samples | O(N) | cheap |
| 6×6 symmetric eigen | n×n cyclic Jacobi (generalize existing 3×3) | O(1) per region | cheap, ~30 lines |
| Curvature extrema on sections | smoothed discrete turning angle | O(n) per polyline | cheap |
| Cubic interpolant | tridiagonal solve | O(k) | cheap |
| Dominant-point loop | insert-worst, refit | O(k·n) per span, n = section points (hundreds) | cheap |
| Section constancy / Hausdorff | point-to-polyline | O(n²) small-n | cheap |
| Spine recovery | neighbourhood-averaged centres + 3-D spline | O(N) + spline | moderate |
| Loft refinement | re-emission + existing deviation pass per iteration | minutes per iteration (live Fusion in the loop) | the slow loop, bounded by `max_loft_sections` |
| NURBS **surface** fit | region parameterization: sparse solve, 10⁴–10⁵ unknowns | tens of minutes+, robustness project | **wall** (007 §12.2), not attempted |

Nothing in rungs 1–3 moves 007 §11.2's 2–6 minute budget materially: the router is one O(N) pass per unclaimed region, and everything profile-shaped operates on section polylines (hundreds of points), not the mesh.

# Prior art position

Every mechanism above is either already in this codebase, or freely implementable with a citation on file:

- Section → **line/arc/curve** split by curvature distribution → constrained sketch → extrude/revolve/**loft**: US20070285425A1, abandoned, no US protection (008 §2.5/§4.2) — the direct license for rungs 1–2's shape.
- Kinematic/invariant-surface classification (translational/rotational/helical from the normal field): Pottmann & Randrup 1998 and the line-geometry literature — academic.
- Dominant-point B-spline fitting: Park & Lee (CAD 2007) — academic; the greedy insert-worst variant is folklore-simple.
- Curve/surface algorithm reference: Piegl & Tiller, *The NURBS Book* — published algorithms, free to implement.
- Pipe/loft/sweep as the wizard vocabulary beyond primitives: Design X and QuickSurface published workflows (008 §5) — validation that this ladder is the commercial ladder.
- Mesh→NURBS quilting, if ever revisited: US6996505, expired 2023 — free blueprint on file.
- 008 §4's conclusion stands: no live patent covers this pipeline; the two live families claim mechanisms (interactive per-operation accuracy display; T-NURCC conversion) this design still does not touch.

# Verification contract

**Offline (`scripts/test.sh`):** router on synthetic regions with known motions (extrusion, revolution, helix, plane-degenerate → `router-ambiguous`); noisy-normal router robustness at declared σ_θ; classifier three-way splits on synthetic sections (rounded-rectangle → lines+arcs, cam lobe → lines+arcs+splines, pure-noise wiggle → refuses spline via spacing floor); dominant-point loop determinism and budget refusal; held-out curve check; taper detection linearity; loft section planning and `replan-with-sections` program deltas; spine recovery on synthetic bent tubes incl. branch refusal; program-v2 validator round-trips and v1 rejection; emission-plan determinism; string-search invariants extended (`sketchFixedSplines` **banned** in generated source — the fixed-spline shortcut must never quietly replace the editable one); byte-pinned examples for one spline-profile extrude, one loft, one pipe.

**Live (labelled, per assumption):** C1–C8 probes; the in-transaction spline deviation check on a real section; loft recompute under plane-offset change (C5); U5 fit-point perturbation (C7); pipe sweep end-to-end. Each failure lands on a named refusal token, never a fallback.

# Sequencing

- **PR 6 — rung 1 + router** (`classify_polyline` extension, `spline` entity, n×n Jacobi, router + confirmations in segmentation, planner/emitter profile path, U5 fit-point perturbation). Size **L**. The coverage win lives here.
- **PR 7 — taper + loft** (constancy→taper detection, loft planning, `replan-with-sections`, deviation loop wiring). Size **M**. Depends on PR 6's classifier.
- **PR 8 — pipe sweep** (tube trigger, spine recovery, 3-D path emission). Size **M**, independent of PR 7.
- Freeform reporting upgrade (signature + stats on unreconstructed regions) is a small addition inside PR 6.

# Report-back summary

- **Ladder and where each rung stops paying:** (1) arbitrary profiles — pure win, bounded only by the fit-point/spacing budgets; (2a) taper — near-free; (2b) loft — pays until `max_loft_sections`, boundary found by measured deviation; (3) sweep — pays for circular pipes only, scope edge declared; (4) ruled — never pays as its own rung (it is a 2-section loft); (5) freeform — NURBS emission does not pay at all here (API-blocked by the base-feature ban, mathematically a pure-Python wall, and not "parametric" in the user's sense regardless); reference mesh is the designed stop.
- **Single highest-value addition:** rung 1 — spline-capable profiles behind the kinematic router. It converts the most common real-world failure ("irregular outline, perfectly prismatic") from 0% to full recovery using machinery that is ~80% already built.
- **Expected coverage of a typical mechanical part:** rung 0 today ~60–80% (machined) / ~30–50% (molded); +rung 1 → ~80–90%; +taper/loft → +2–8%; +pipe sweep → +2–5%; remainder 5–15% honestly-labelled reference mesh. Organic/styled parts invert these numbers, and the report's per-region signatures say so per part.
- **Three hardest unresolved problems:** (1) Fusion's fitted-spline interpolant is unknown offline — solved structurally by in-transaction measurement + refusal, but `SLACK` and the refusal rate are only tunable live; (2) loft section-count selection without host-side loft evaluation — the deviation-driven replan loop is honest but slow (live Fusion per iteration) and the `max_loft_sections` cap is a judgment call the doctrine must own; (3) pipe spine recovery under noise amplified by tube radius — the averaging/tolerance/refusal ladder is designed, but where real scans land on it is unmeasured.
- **Genuinely out of reach, with reasons:** parametric emission of fitted freeform surfaces (no non-banned API route; base features are history-free by nature — structural); NURBS *surface* fitting at scan scale in pure Python (sparse solves at 10⁴–10⁵ unknowns — the named §12.2 wall); T-spline/Form creation (no API — C8); general non-circular sweeps and variable-radius pipes (moving-frame correspondence — deferred with the reason recorded, not denied forever).
