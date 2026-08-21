---
title: "research: robust mesh-to-parametric reconstruction mathematics — detection-first, uncertainty-carried, disproof-gated"
date: 2026-08-19
artifact_contract: ce-research/v1
execution: research
origin: https://github.com/novotnyllc/agent-utilities/issues/20
revises: docs/plans/2026-08-19-005-feat-mesh-parametric-reconstruction-plan.md (KTD4, KTD5, KTD6, R3–R7)
incorporates: docs/plans/2026-08-19-008-research-prior-art-landscape.md (GlobFit staged
  re-fit, Lukács–Martin–Marshall torus, Besl–Jain HK pre-classification, NIST oracles)
status: specification — no production code in this document; reference estimator
  implementations included where an equation alone would be ambiguous
---

# Robust reconstruction mathematics

This document specifies, to implementation precision, the mathematics that turns
a noisy scanned triangle mesh into fitted, related, snapped, uncertainty-carrying
primitives — the input to plan 005's reconstruction program. It **revises plan
005's segmentation-first architecture**: plan 005 gated the whole pipeline on
crease-based segmentation and refused when per-triangle normal jitter approached
the crease threshold (its KTD5). The physics in that argument is correct and is
re-derived below; the conclusion was wrong, because per-triangle normals were
never the right estimator and segmentation was never the right first stage.

**The revised spine, in one paragraph.** Estimate the mesh's noise scale σ from
the data (§3). Estimate per-vertex normals by trimmed PCA over neighbourhoods
sized *from σ*, which drives normal noise down by two orders of magnitude
relative to per-triangle normals, plus a Besl–Jain HK curvature-sign signature
per point with noise-adaptive dead zones (§4). Detect primitives — plane,
sphere, cylinder, cone, **torus** — directly by Efficient RANSAC
(Schnabel–Wahl–Klein 2007): localized minimal-set sampling over an octree with
HK-signature candidate ranking, connected-inlier scoring, probabilistic
stopping, greedy cascade extraction (§5). Each RANSAC candidate is *proposed
and scored* robustly, then *refined* by exact least-squares fitters — the four
existing ones in `mesh_fitting.py` plus a Lukács–Martin–Marshall-style torus
fit specified here — iterated to an inlier-set fixed point (§5.8).
Segmentation is then a *refinement*: points are assigned to competing detected
primitives by a smoothness-regularized labeling, and what nothing explains is
declared unclaimed with its curvature signature, never absorbed (§6). Every
fitted parameter carries a covariance from the least-squares normal equations,
inflated for spatially correlated residuals (§7). Relations — coaxial,
concentric, parallel, perpendicular, tangent, symmetric, equal-radius — are
detected by χ² tests on parameter differences under those covariances; adopted
relations are enforced **GlobFit-style: in staged priority order (orientation,
then placement, then equality), each stage followed by a constrained re-fit of
every affected primitive with rollback of any relation that pushes a member
outside its noise bound** — the re-fit realized by parameter elimination and
small Levenberg–Marquardt solves per Benkő et al. 2002's sequential
formulation, specified with Jacobians. Near-canonical values snap only when a
statistical test licenses the snap *and* the snap grid is identifiable at the
data's precision (§8). The
datum frame derives from the fitted features with uncertainty-aware margins and
quantized tie-breaks (§9). Three disproof gates get real statistical
formulations, including Moran's I for residual spatial structure and a
nested-kind parsimony test (§10). Complexity and pure-Python feasibility are
stated per stage (§11); honest limits in §12; reference implementations in
§13; interface deltas against plan 005 in §14; sources, oracles and the
licensing posture in §15.

Everything here is pure Python standard library, deterministic under a seeded
RNG (§2.3), and builds on the linear-algebra kernel that `mesh_fitting.py`
already hand-rolls: `_symmetric_eigen` (cyclic Jacobi 3×3), `_solve`
(Gauss–Jordan with partial pivoting), `_fit_circle_2d`, `_fit_plane`,
`_fit_sphere`, `_fit_cylinder`, `_fit_cone`. Where something new is needed —
a grid spatial index, an octree, a Levenberg–Marquardt engine over ≤ ~12
parameters — it is specified with update equations and conditioning caveats.

Units follow the module's convention: lengths in the caller's units, angles in
radians internally and degrees in reports. σ always denotes the estimated
1-sigma point noise normal to the surface.

---

## 1. Why detection-first, concretely

Plan 005's refusal arithmetic: point noise σ on triangles of edge ℓ induces
per-triangle normal jitter ≈ arctan(2σ/ℓ) ≈ 11° at σ = 0.05 mm, ℓ = 0.5 mm,
which swamps a 15° crease threshold. True. Two things follow from re-examining
which estimator that jitter belongs to:

1. **Normal noise averages down as 1/(h√k) with neighbourhood size** (derived
   in §4.2). A PCA normal over a radius-2 mm neighbourhood (~60 vertices at
   ℓ = 0.5 mm) has angular noise ≈ 0.4° on the same scan. The 11° figure is a
   property of the worst possible estimator, not of the data.
2. **RANSAC does not need segmentation to exist first.** It needs a distance
   band ε ≈ 3σ and a *loose* normal-compatibility check (α ≈ 20–30°), both of
   which survive noise that would destroy crease detection. Region boundaries
   fall out of detection instead of feeding it. This is exactly the structure
   of every commercial system that works on real scans, and of the canonical
   published method we adopt.

The crease-based region growing of plan 005 KTD4 is **demoted, not deleted**:
its dihedral statistics still provide one of the two noise estimators (§3.2),
and creases still provide seeds for the segmentation refinement (§6). The
noise-limited *refusal* is replaced by a noise-limited *degradation report*:
the pipeline states the σ it measured and the smallest feature scale it can
resolve at that σ (§12.1), and only refuses when even detection is impossible
(σ comparable to the part's feature dimensions, §12.2).

---

## 2. Data model, notation, determinism

### 2.1 Inputs

From the plan-005 U1 dump: vertices `V = (v_0 … v_{N-1})` (float64 triples),
triangles `T = (t_0 … t_{F-1})` (index triples), optional face-group ids. All
algorithms below operate on:

- **P**: the working point set. Default: the vertex set, deduplicated by exact
  coordinate equality (scanners emit duplicated vertices across triangle
  fans). Each point carries `index` (its position in the deduplicated array —
  the universal deterministic sort key), an area weight `w_i` (one third of the
  summed area of incident triangles), and after §4 a unit normal `n_i` with a
  quality flag.
- **Adjacency**: `edge → (tri, tri)` map built in one pass over T with sorted
  vertex-pair keys (the plan-005 U2 structure, unchanged); vertex→triangle
  incidence likewise.
- ℓ_med: median edge length, computed once, used as the mesh's sampling scale.

### 2.2 Scale normalization

Every solver below **centres and scales** its data first: subtract the
centroid, divide by `s = extent/2` where extent is the bbox diagonal of the
point subset being fitted. All conditioning thresholds (pivot floors, LM
damping) are stated in this normalized frame; parameters are mapped back
afterwards. This is already `mesh_fitting.py`'s convention (`_fit_sphere`,
`_fit_circle_2d`) and it is what makes the `1e-12` pivot floor in `_solve` a
conditioning test rather than a units guess.

### 2.3 Determinism

Randomness enters at exactly four places: RANSAC minimal-set sampling (§5.4),
scoring subsample selection (§5.6), held-out splitting (§10.3), and nothing
else. Each stage gets its own `random.Random` seeded as

```python
seed = int.from_bytes(hashlib.sha256(f"{dump_sha256}:{stage_name}".encode()).digest()[:8], "big")
rng = random.Random(seed)
```

so a rerun on the same dump is bit-identical, and stages cannot perturb each
other's streams. Additional rules, each of which has bitten someone:

- Never iterate a `dict`/`set` where order reaches output; iterate sorted keys
  or index order. (Python dicts are insertion-ordered, but insertion order must
  itself be deterministic — index order makes it so by construction.)
- All priority ties break by candidate serial number (a monotone counter), then
  point index.
- Floating-point comparisons that pick winners (datum tie-breaks, snap-grid
  selection) compare **quantized** values: `round(v / (1e-9 * extent))` — so a
  last-bit difference cannot flip an ordering between runs on different
  platforms (§9.3).
- No threads, no `os`-dependent ordering, no wall-clock anywhere in the math.

---

## 3. Noise-scale estimation

σ is the foundation: it sizes neighbourhoods (§4), the RANSAC band ε (§5.5),
the unclaimed threshold (§6), the covariance scale (§7), and every statistical
test (§8, §10). Two independent estimators, cross-checked. **[Scoped
2026-08-21, Amendment §2: σ̂ here is the *local point-jitter* scale, and it
legitimately sizes the local consumers (neighbourhoods, ε). Form error,
spatial correlation structure, held-out independence, and parameter
covariance are distinct estimands with their own estimators — design -002
§A.4/§B.1. No single scalar automatically calibrates every consumer.]**

### 3.1 Estimator A — local-plane residual (primary)

Sample `m = min(2000, N)` points deterministically (every ⌊N/m⌋-th point by
index). For each sample point p, collect its neighbourhood of the `k_σ = 16`
nearest points (grid index, §11.1) — deliberately small, so that surface
curvature contaminates the estimate as little as possible. Compute the
covariance (existing `_covariance`) and its smallest eigenvalue λ₀ (existing
`_symmetric_eigen`). For a true plane with iid Gaussian normal noise, the
plane fit absorbs 3 degrees of freedom, so the unbiased local estimate is

    σ̂_p² = λ₀ · k_σ / (k_σ − 3).

The global estimate is the **median** over samples (robust against the
minority of samples that straddle an edge or a tight fillet, whose λ₀ is
inflated by geometry, not noise):

    σ̂_A = median_p( σ̂_p )        # note: median of the *std*, not the variance

Bias caveat: on a curved region of curvature κ, the plane residual picks up a
sagitta term ≈ κ h²/8 where h is the neighbourhood radius. With k_σ = 16 at
density ρ ≈ 2/(√3 ℓ²), h ≈ 1.7 ℓ, so the contamination is ≈ 0.36 κ ℓ². At
ℓ = 0.5 mm this is < 0.01 mm for any κ < 0.1/mm (radius > 10 mm) — negligible
for the surfaces that dominate a mechanical part, and the median suppresses
the rest. Do **not** enlarge k_σ to "stabilize" this estimator; that trades
its bias floor away.

### 3.2 Estimator B — dihedral statistics (cross-check)

Derivation of the per-triangle jitter first, because both plan 005 and this
document lean on it. Model the surface locally as a height field; a triangle
normal estimates the gradient from three noisy heights on a baseline ~ℓ. For
an equilateral triangle with iid vertex noise σ normal to the surface, the
two gradient components each have std ≈ 1.6 σ/ℓ, so the normal tilt magnitude
has std

    σ_tri ≈ 2.3 σ/ℓ   (radians, small-angle).           (3.1)

At σ/ℓ = 0.1 this is 0.23 rad ≈ 13°, the plan's "~11°" within modelling slop.

Adjacent triangles have nearly independent jitter (they share one edge), so
the dihedral angle across an interior edge inside a smooth region is
approximately half-normal with scale √2 σ_tri. The median of |X| for
X ~ N(0, s) is 0.6745 s, hence

    θ_med ≈ 0.6745 · √2 · 2.3 · σ/ℓ ≈ 2.2 σ/ℓ
    σ̂_B  = θ_med · ℓ_med / 2.2                         (3.2)

computed over all interior edges (real creases are a small minority of edges
on a mechanical part and the median ignores them; this is plan 005 R4's
statistic, reused with its calibration made explicit).

### 3.3 Cross-check and output

Report both. If `max(σ̂_A, σ̂_B) / min(σ̂_A, σ̂_B) > 2`, flag
`noise-model-inconsistent` in the record — the noise is anisotropic, banded
(structured-light stripe artifacts), or the mesh has been smoothed already.
The pipeline continues with `σ̂ = max(σ̂_A, σ̂_B)` (the conservative choice:
every downstream band widens), but every statistical verdict in §8/§10
carries the flag, because their calibration assumes roughly iid noise.

Failure mode and guard: a mesh that was *already* decimated/smoothed by the
scanner has σ̂ far below the true measurement error, making later χ² tests
overconfident. No estimator can see error that was filtered out upstream; the
guard is the correlated-residual inflation of §7.3, which catches the residue
of smoothing (spatially correlated residuals) and inflates variances
accordingly.

---

## 4. Normals and curvature that survive noise

### 4.1 Neighbourhood normal by trimmed PCA

For each point p: collect neighbours within radius h (chosen in §4.2). Fit a
plane by PCA (`_centroid`, `_covariance`, `_symmetric_eigen`; normal =
eigenvector of λ₀). Then **trim**: discard neighbours whose distance to that
plane exceeds 2.5 σ̂, and refit once. Two passes total — more buys nothing.

Orientation: PCA normals are unoriented. Orient each by majority vote of the
incident triangles' winding normals (area-weighted sum, take the sign of the
dot product). On an unoriented mesh (`isOriented` false) normals remain
unoriented and every consumer below that needs orientation (hole
classification per plan 005 KTD8, inward/outward tests) refuses — the
detection machinery itself only ever uses normals through `|cos|`, so it is
unaffected.

Edge-adjacency flag: after trimming, if the residual RMS about the local
plane still exceeds `2 σ̂`, the neighbourhood straddles a crease or tight
fillet and the normal is unreliable. Set `edge_adjacent = True`. Such points
still participate in RANSAC distance scoring but are **exempted from the
normal-compatibility check** (§5.5) — otherwise every point within h of a
crease fails the check and boundary support is systematically eaten.

### 4.2 Sizing h from σ̂ — the estimator-variance derivation

Plane-fit tilt variance: heights z_i = s·x_i + noise over a disk of radius h
with k points; the LS slope has Var(ŝ) = σ²/Σx_i², and for a uniform disk
Σx_i² ≈ k h²/4. So the angular noise per tilt component is

    σ_θ(h) ≈ 2σ / (h √k),   with  k ≈ ρ π h²,  ρ ≈ 2/(√3 ℓ_med²)     (4.1)

i.e. σ_θ ≈ 2σ/(√(πρ) h²): normal noise falls as **1/h²**. Choose h as the
smallest value satisfying a target angular noise θ_tgt:

    h = sqrt( 2 σ̂ / (√(πρ) · θ_tgt) ),   θ_tgt = α/5                  (4.2)

where α is the RANSAC normal-compatibility half-angle (§5.5); the /5 keeps
the check's false-rejection rate negligible. Clamp:

- h ≥ 2.5 ℓ_med (below that, k < ~10 and (4.1) is invalid);
- h ≤ f_min/2, where f_min is the caller-declared **minimum feature size**
  (plan 005 R15 threshold, new name `min_feature_size`, with rationale).
  Normals averaged over more than half a feature describe neither of its
  sides.

If the two clamps conflict — the σ̂ needed to hit θ_tgt requires h > f_min/2
— take h = f_min/2, recompute the achievable σ_θ from (4.1), and widen α to
5 σ_θ. The record states the achieved σ_θ. This is the graceful degradation
that replaces plan 005's refusal: noise costs angular resolution, stated in
numbers, rather than costing the whole run.

Worked instance (the contested scan): σ = 0.05 mm, ℓ = 0.5 mm, ρ ≈ 4.6/mm².
For θ_tgt = 4° = 0.07 rad: h = sqrt(0.1/(3.8·0.07)) ≈ 0.61 mm → clamped to
2.5 ℓ = 1.25 mm; then k ≈ 22 and σ_θ ≈ 2·0.05/(1.25·4.7) ≈ 0.017 rad ≈ 1°.
**Per-triangle 13° becomes 1° at a 1.25 mm support radius.** That is the
whole argument against the old refusal, in one line of arithmetic.

### 4.3 Curvature by local quadric (hints only)

In the trimmed-PCA frame (normal n, tangent basis u, v from `_frame`), fit

    z = a x² + b x y + c y² + d x + e y

by least squares over the neighbourhood (5×5 normal equations via `_solve`;
centre and scale by h first, §2.2). The shape operator is approximated by
S = [[2a, b], [b, 2c]]; principal curvatures κ₁ ≥ κ₂ are its eigenvalues
(closed form for 2×2: κ = (2a+2c)/2 ± sqrt(((2a−2c)/2)² + b²)).

Estimator noise: by the same Σx⁴-type argument as (4.1),
σ_κ ≈ c₀ σ/(h²√k) with c₀ ≈ 6. At the worked instance: σ_κ ≈ 0.04/mm — you
can tell a 5 mm radius from a flat, not a 20 mm radius from a 25 mm one.
**Therefore curvature is used for candidate ranking and refusal diagnostics**
(§4.4, §5.4) and never as an acceptance gate. Any design that gates on
scanned curvature at these noise levels is gating on noise; this is a named
non-goal.

### 4.4 HK signature (Besl–Jain 1988), noise-adaptive

From κ₁, κ₂ form mean curvature H = (κ₁+κ₂)/2 and Gaussian K = κ₁κ₂, and
quantize each to a sign with a **dead zone sized by the estimator noise**:

    sgn_σ(H) = 0 if |H| ≤ 2 σ_κ, else sign(H)
    sgn_σ(K) = 0 if |K| ≤ 2 σ_κ · (|κ₁| + |κ₂| + 2 σ_κ), else sign(K)

(the K dead zone is the first-order propagated noise of a product). The
(sgn H, sgn K) pair classifies the local surface type per Besl & Jain
(*Segmentation through variable-order surface fitting*, PAMI 1988):

| sgn H | sgn K | type | compatible primitives |
| --- | --- | --- | --- |
| 0 | 0 | flat | plane |
| ± | 0 | ridge/valley | cylinder, cone, torus (outer/inner) |
| ± | + | peak/pit | sphere, torus |
| any | − | saddle | torus (inner region) — else none supported |

Aggregate per neighbourhood cell (the §11.1 grid): the cell's signature is
the majority pair plus the fraction voting for it. Two uses, neither a gate:

1. **Candidate ranking in RANSAC** (§5.4): a sampled first point's signature
   reorders/prunes which minimal-set constructions are attempted, shrinking
   both wasted candidates and the per-region disproof matrix.
2. **Refusal diagnostics** (§6): an unclaimed region reports its dominant
   signature, so the record can say "saddle signature — no supported
   primitive fits a saddle" instead of "nothing fit". That sentence is worth
   the whole subsection.

The dead zones make the classifier degrade honestly: as σ grows, more of the
part reads `(0, 0)`-ambiguous, the ranking prunes less, and RANSAC simply
tries more kinds — cost rises, correctness does not fall.

---

## 5. Robust primitive detection — Efficient RANSAC, specified

Base method: R. Schnabel, R. Wahl, R. Klein, *Efficient RANSAC for
Point-Cloud Shape Detection*, Computer Graphics Forum 26(2), 2007. We adopt
its four pillars — minimal sets with normals, localized octree sampling,
connected-inlier scoring, probabilistic stop/extract — and specify each for
this codebase. Where our choice differs from the paper it is called out with
the reason.

Primitive kinds: plane, sphere, cylinder, cone, **torus**. The torus is new
— `PRIMITIVE_KINDS` gains it, and plan 005's refusal 5 is revised (§14):
without a torus, every fillet on a real part becomes unreconstructed area,
and real parts are planes and cylinders joined by fillets. Only the
circular-tube torus is in scope (fixed minor radius); variable-radius and
elliptical blends remain refused. A detected torus is *emitted* not as torus
geometry but as a **fillet feature on the shared edge of its two adjacent
primary regions, radius = minor radius** (§6, plan 005 KTD8 revised) — the
Design X behaviour, and the only form that is parametric in Fusion.

### 5.1 Minimal sample sets

Oriented points (point + unit normal) shrink every minimal set:

| Primitive | Minimal set | Free parameters |
| --- | --- | --- |
| plane    | 3 points (normals used only to validate) | 3 |
| sphere   | 2 oriented points | 4 |
| cylinder | 2 oriented points | 5 |
| cone     | 3 oriented points | 6 |
| torus    | 4 oriented points | 7 |

Every construction below must **reject degenerate samples cheaply** rather
than produce a wild candidate; the degeneracy tests are part of the spec.

**Plane from 3 points.** n = unit((p₂−p₁)×(p₃−p₁)); reject if the cross
product's norm < 1e-6·(pairwise-distance scale)² (collinear). Validate:
require |n·nᵢ| ≥ cos α for all three sampled normals — a plane through three
points whose measured normals disagree with it is a chord through curved
surface, not a plane; rejecting here is what keeps plane candidates from
poisoning cylinders.

**Sphere from 2 oriented points.** The centre lies near both normal lines
pᵢ + t nᵢ. Solve the closest-approach problem: with d = p₂ − p₁,
b = n₁·n₂, denominator D = 1 − b²:

    t₁ = (n₁·d − b (n₂·d)) / D
    t₂ = (b (n₁·d) − n₂·d) / D
    c  = ½ (p₁ + t₁ n₁  +  p₂ + t₂ n₂)
    r  = ½ (|c − p₁| + |c − p₂|)

Reject if D < 1e-4 (near-parallel normals: centre unobservable), if the two
line-foot points are farther apart than 2ε (the "lines don't meet" test), or
if | |c−p₁| − |c−p₂| | > 2ε.

**Cylinder from 2 oriented points.** Axis direction a = unit(n₁ × n₂);
reject if ‖n₁×n₂‖ < 1e-2 (parallel normals — the two points see the same
generator line; axis unobservable). Project into the plane ⊥ a:
p̂ᵢ = pᵢ − (pᵢ·a) a, n̂ᵢ = unit(nᵢ − (nᵢ·a) a). Intersect the two 2-D lines
p̂ᵢ + t n̂ᵢ (2×2 solve; reject if near-parallel after projection). Centre =
intersection; r = |p̂₁ − centre|; reject if | |p̂₂ − centre| − r | > 2ε.

**Cone from 3 oriented points.** The three tangent planes all pass through
the apex: solve the 3×3 system nᵢ · x = nᵢ · pᵢ for apex c (`_solve`;
singular ⇒ normals coplanar ⇒ this sample describes a cylinder — reject, a
cylinder candidate will find it). Axis: the unit vectors uᵢ = unit(pᵢ − c)
lie on a circle of the unit sphere; a = unit((u₂−u₁)×(u₃−u₁)), sign fixed so
a·(u₁+u₂+u₃) > 0. Half-angle ω = (1/3) Σᵢ arccos(clamp(a·uᵢ)). Reject if
ω < ω_min (default 0.5°: below the taper identifiability floor, it is a
cylinder — mirrors `min_taper_ratio`) or ω > 89°, or if the apex lies farther
than `bounds_margin_ratio · extent` outside the sample's bbox (reuse of the
existing gate philosophy at proposal time, where it is cheapest).

**Torus from 4 oriented points.** Property used: every surface normal line
of a torus intersects the axis. Construction:

1. For each of the C(4,2) = 6 pairs of normal lines pᵢ + t nᵢ, compute the
   closest-approach segment (the §13.1 `sphere_from_2` arithmetic). Reject
   the pair if the gap exceeds 2ε; keep the midpoint. Require ≥ 4 surviving
   midpoints (fewer means the sample is not torus-consistent).
2. Fit a line through the midpoints by PCA (`_centroid` + `_symmetric_eigen`,
   largest-eigenvalue direction) → axis (c₀, a). Reject if the midpoints'
   RMS distance to that line exceeds 2ε (normal lines meeting at a *point*
   rather than a line is the sphere degeneracy; nearly parallel normal lines
   with far-flung midpoints is the cylinder/plane degeneracy — both must
   fall through to the simpler kinds' candidates, not become wild tori).
3. Map each sample point to the axial half-plane: ρᵢ = distance to axis,
   tᵢ = station along axis. The torus is a circle in (ρ, t): fit
   `_fit_circle_2d` to the 4 points → (R, t₀, r). Reject if the 4th
   residual exceeds 2ε, if r ≥ R − 2ε (spindle/self-intersecting), or if
   R > max_radius_ratio · extent (the flat-strip pathology, same gate as
   circles).

The torus centre is c = c₀ + t₀ a; parameters (c, a, R, r).

### 5.2 Distance and normal functions used in scoring

For a candidate with parameters θ, each point contributes
d(p, θ) = orthogonal distance and the surface normal direction at the foot
point. All four are closed-form:

- plane (n, δ): d = |n·p − δ|; surface normal n.
- sphere (c, r): d = | |p−c| − r |; surface normal unit(p−c).
- cylinder (c, a, r): v = (p−c) − ((p−c)·a) a; d = | ‖v‖ − r |; normal unit(v).
- cone (apex x₀, axis a, ω): w = p−x₀, t = w·a, ρ = ‖w − t a‖;
  d = |ρ cos ω − t sin ω|; normal = unit(v̂ cos ω − a sin ω) with v̂ the unit
  radial. Points with t < 0 (behind the apex) are never inliers.
- torus (c, a, R, r): w = p−c, t = w·a, ρ = ‖w − t a‖, q = sqrt((ρ−R)² + t²);
  d = |q − r|; normal = unit( ((ρ−R)/q) v̂ + (t/q) a ). q = 0 (a point on the
  tube's spine circle) contributes d = r with an arbitrary normal — never an
  inlier at any sane ε, so no special case is needed beyond guarding the
  division (skip the point when q < 1e-12·extent).

### 5.3 Octree

Purpose: localized sampling (§5.4) and blocked held-out splits (§10.3).

- Root cube: the bbox cube of P, expanded 1% to keep boundary points strictly
  interior; child indexing by the standard 3-bit octant code with half-open
  intervals `[lo, mid)` / `[mid, hi]` so a point on a split plane has exactly
  one home.
- Build by inserting points in index order; split a leaf when it exceeds
  `n_leaf = 32` points; maximum depth `d_max = min(10, ceil(log2(extent / (4 σ̂))))`
  — cells smaller than ~4σ̂ are noise-sized and sampling from them yields
  degenerate minimal sets.
- Store per node: point-index list (leaves), child pointers, level. Memory is
  O(N + nodes); at 300 k points ≈ tens of MB of Python lists — fine.
- Deletion is lazy: a global `dead` bytearray flags extracted points; a node's
  live count is refreshed on visit; the whole octree is rebuilt from live
  points when live fraction < 0.5 (amortized O(N) total across the cascade).

### 5.4 Localized sampling

Uniform k-tuples almost never land on one small shape: the naive single-draw
success probability is (n/N)^(k−1) for a shape with n of N points. Localized
sampling replaces it with roughly (n/N)·P_cell, orders of magnitude larger.

Procedure per candidate (one draw from the stage RNG each step, in this
order, so the stream is reproducible):

1. Draw the first point p₁ uniformly from live points (draw an index; skip
   dead by retry — retries consume RNG draws deterministically).
2. Draw an octree level ℓ from the adaptive distribution
   P(ℓ) ∝ s_ℓ + 1, where s_ℓ counts candidates drawn from level ℓ that
   later became the best-so-far for their kind. (This is the paper's learned
   level distribution with add-one smoothing; initialize all s_ℓ = 0.)
3. Take C = the ancestor cell of p₁ at level ℓ; draw the remaining k−1
   sample points uniformly from C's live points (retry-on-dead as above; if C
   has fewer than k live points, resample the level — bounded by L retries,
   then abandon the candidate, counting it toward T).
4. Run the §5.1 construction + degeneracy tests for **each primitive kind in
   the fixed order plane, cylinder, sphere, cone, torus** on the same sample
   where the sample size permits (plane/sphere/cylinder share the first 2–3
   points; cone and torus draw their 3rd/4th oriented points from the same
   cell). Each surviving construction becomes one candidate with a serial
   number.

HK ranking (from §4.4): the sampled p₁'s signature prunes constructions —
`(0,0)` skips sphere/cone/torus; `(±,0)` skips sphere; `(±,+)` skips plane
and cone; `(·,−)` attempts torus only; an ambiguous/minority signature prunes
nothing. Pruning is per-sample only — a kind is never vetoed globally,
because signatures are noisy and the dead zones (§4.4) already encode how
noisy. Additionally, `(±,+)` seeds the sphere radius sanity check with
1/κ̄ and `(±,0)` seeds the cylinder radius check with 1/|κ₁|.

### 5.5 Score function

A candidate's score is the size of the **largest connected component** of its
inlier set, where a point p (with normal n_p, unless `edge_adjacent`) is an
inlier iff

    d(p, θ) ≤ ε         with ε = 3 σ̂         (distance band)
    |n_p · n_surf(p)| ≥ cos α                 (normal compatibility)

α default: `max(20°, 5 σ_θ)` with σ_θ from §4.2 — loose on purpose; the
normal check exists to stop a plane candidate claiming the shoulder of a
cylinder, not to re-litigate segmentation. Both ε and α are caller-declarable
(R15) with these defaults and rationales.

**Connectivity bitmap.** Project inliers into the candidate's 2-D chart:

- plane: (u·p, v·p) in the plane frame;
- cylinder: (t, r·φ) — axial station and unrolled arc length, φ wrapping;
- sphere: octahedral equal-area map (fold the unit direction's octant into a
  square; standard octahedral mapping — no singular seams that split real
  components);
- cone: (slant length s = t/cos ω, r̄·φ) with r̄ the mid-band radius; φ wraps;
- torus: (R·φ, r·ψ) — major angle φ = atan2 of the point's axis-plane
  position, minor angle ψ = atan2(t, ρ−R); both coordinates wrap.

Rasterize at bit size β = 2 ℓ_med per cell into a dict keyed by integer cell
coordinates; flood-fill (BFS, 4-connectivity, with wraparound in φ for
cylinder/cone, in both coordinates for torus, and octant-edge stitching for
sphere) from the seed cell
containing p₁; score = number of inlier points whose cells belong to that
component. Using the largest *connected* count is what stops one candidate
plane from harvesting coplanar-but-disjoint faces on opposite sides of the
part — the single most common false merge in naive RANSAC.

### 5.6 Lazy scoring on subsamples

Full scoring is O(N) per candidate and dominates naive implementations.
Score candidates on a fixed random subsample S of size s = min(4096, N)
(drawn once per stage from the RNG, sorted by index), extrapolate

    n̂ = n_S · N / s,      SD(n̂) ≈ (N/s) · sqrt( n_S (1 − n_S/s) )

and keep candidates in a max-heap keyed by the **optimistic bound**
n̂ + 2·SD(n̂) (ties by serial). Only when a candidate reaches the top of the
heap *and* its optimistic bound exceeds the best fully-scored value is it
fully scored (connected component over all live points). This is the paper's
lazy evaluation reduced to one subsample tier — simpler than its recursive
octree-subset scheme, costs at most one extra full scoring per extraction,
and in pure Python simplicity wins.

### 5.7 Stopping and cascade extraction

Let p̂(n) be a conservative lower bound on the probability that one sampling
round proposes a candidate matching a shape with n live points. With
localized sampling over L usable octree levels:

    p̂(n) = (n / N_live) · (1/L) · 2^{−(k−1)}                       (5.1)

(the shape covers ≥ half the points of *some* cell at *some* level; drawing
that level costs 1/L, and each subsequent in-cell draw hits the shape with
probability ≥ ½). After T candidates of a given kind, the probability a
size-n shape was missed is bounded by

    P_miss(n, T) = (1 − p̂(n))^T.                                   (5.2)

Two thresholds, both caller-declared with rationale (R15):

- **Extraction.** Extract the current best candidate (fully scored, size
  n_best) when P_miss(n_best, T) ≤ η_extract (default 0.01): the chance an
  undiscovered candidate could beat it is below η. On extraction: run the
  refinement loop (§5.8); assign its final inliers; mark them dead; clear the
  scoring subsample entries that died and re-extrapolate remaining heap
  entries against N_live (candidates whose construction points died are
  discarded — their serial numbers retire).
- **Termination.** Stop generating candidates when P_miss(τ, T) ≤ η_stop
  (default 0.01) for the minimum interesting size τ = max(50,
  ⌈0.2 · f_min² · ρ⌉) — a shape smaller than τ points cannot pass the §10
  support gates anyway, so hunting it is wasted work.

The cascade is greedy largest-first. Known greedy failure mode: a large
plane can steal the flank points of an adjacent large cylinder (both within
ε where they meet tangentially), starving the cylinder. The guard is §6:
after all extractions, assignment is re-opened globally with all accepted
primitives competing, so cascade order affects *discovery* but not the final
labeling.

### 5.8 Composition with the exact fitters — propose, refine, iterate

RANSAC candidates are crude (built from k points). Refinement:

```
S_0 = connected inliers of the RANSAC candidate
repeat j = 0, 1, …, 9:
    θ_{j+1} = exact least-squares fit of the kind to S_j
              (existing _fit_plane / _fit_sphere / _fit_cylinder / _fit_cone,
               called directly on the point list, plus the new _fit_torus
               below — gates OFF at this stage; gating happens once, in §10)
    S_{j+1} = connected inliers of θ_{j+1}   (same ε, α, bitmap as §5.5)
    stop when S_{j+1} == S_j                  (fixed point)
       or when the parameter step is below tolerance:
          axis/normal rotation < 1e-9 rad, |Δr|/r < 1e-12, |Δc| < 1e-12·extent
keep the (θ, S) pair with the highest connected-inlier count seen; ties by
lower RMS, then by iteration index (earliest).
```

This loop is not guaranteed monotone (the inlier set is a step function of
θ), which is why the criterion is *fixed point or best-seen*, bounded at 10
iterations — in practice 2–4. It is deterministic: S is a sorted index list,
the fitters are deterministic, and tie-breaks are total.

The cone fitter caveat: `_fit_cone`'s slab-based taper profile needs several
distinct axial stations; a RANSAC cone whose inliers span < 3 slabs will fail
to refine. Treat a refine failure as candidate rejection (the shape re-enters
the pool as smaller candidates or ends unclaimed) — never fall back to the
raw RANSAC parameters, which carry no least-squares meaning.

**`_fit_torus` — the new exact fitter** (Lukács–Martin–Marshall 1998
lineage: minimize a first-order approximation of true geometric distance,
with degeneracy-safe demotion rather than blowup). No closed form exists;
the fit is the §13.2 LM engine over the 7-parameter residual of §7.1
(torus row), initialized from the RANSAC candidate (which is why the torus,
unlike the other kinds, is *only* reachable through detection — there is no
sensible cold-start). Two-step initialization refinement before LM: (a)
re-estimate the axis by the normal-line-midpoint construction of §5.1 over
*all* inliers (each inlier's normal line vs. the current axis: foot-point
scatter re-fits the line by PCA); (b) re-fit the (ρ, t) circle over all
inliers with `_fit_circle_2d`. Then LM polishes. Degeneracy demotions,
tested after convergence on the covariance (§7):

- σ_R ≥ R, or R > max_radius_ratio · extent  →  re-fit as **cylinder**
  (tube straightens as R → ∞), report `torus-demoted-cylinder`;
- R ≤ 2 σ_R  →  re-fit as **sphere** (R → 0 is the spindle/sphere limit),
  report `torus-demoted-sphere`;
- r ≥ R (self-intersecting spindle)  →  reject `torus-spindle`.

The model-comparison test that licenses a torus over a nested simpler kind
is in §10.4.

Output of §5: a list of accepted primitive instances
(kind, θ_refined, inlier index set, bitmap chart), plus the live/dead state.

---

## 6. Segmentation as refinement

Detection produces overlapping claims and orphans; segmentation resolves
them. It is a labeling problem over triangles (triangles, not points — the
downstream program reasons in surface area and mesh topology).

**Label set**: one label per accepted primitive + `unclaimed`.

**Energy.** For triangle f with area A_f, barycenter b_f, area-weighted
normal m_f, and label ℓ:

    D(f, ℓ)  = A_f · [ d(b_f, θ_ℓ)² / σ̂²  +  λ_n · angle(m_f, n_surf(b_f))² / σ_θ² ]   for primitives
    D(f, ∅)  = A_f · χ²_cut                                        for unclaimed
    E(labeling) = Σ_f D(f, ℓ_f)  +  λ_s Σ_{(f,g) adjacent} A_{fg} · [ℓ_f ≠ ℓ_g]

with χ²_cut = 9 (a triangle worse than 3σ̂ from every primitive prefers
unclaimed), λ_n = 0.25 (normals are supporting evidence, not primary),
λ_s = 1 with A_{fg} the shared edge length over ℓ_med (Potts smoothness in
units of "one typical edge"), all caller-declarable.

**Minimization: ICM (iterated conditional modes).** Exact multi-label
minimization is graph-cut α-expansion, which needs a max-flow solver —
implementable in stdlib but large, slow in Python, and unnecessary: the data
terms here are strong (primitives are 3σ apart except in blend bands), so
ICM's local minima are confined to 1–2-triangle boundary jitter.

    repeat until no change or 10 sweeps:
        for f in triangle-index order:
            ℓ_f ← argmin over {labels of primitives whose distance at b_f ≤ 5ε} ∪ {∅, current}
                  of D(f, ℓ) + λ_s Σ_{g∈N(f)} A_{fg}[ℓ ≠ ℓ_g]

Energy strictly decreases per accepted move, the state space is finite, so it
terminates; the fixed sweep order makes it deterministic. `ponytail:` ICM in
place of α-expansion — upgrade path is an α-expansion pass if boundary
quality on real scans proves insufficient, at the cost of a max-flow
implementation (~300 lines, O(V E²) worst case but fine on these graphs).

**Candidate pruning per triangle** ("labels within 5ε") uses the primitives'
inlier bitmaps: only primitives whose chart bitmap has an occupied cell
within 2 cells of the triangle's projection are considered — O(1) per label
test, keeps the sweep O(F · few).

**Connectivity enforcement.** After ICM, split each primitive's triangle set
into connected components (BFS over adjacency); components smaller than τ
triangles or than `min_support_area` revert to unclaimed. A primitive left
with nothing is dropped (and reported as `detected-then-dissolved` — that is
evidence of a marginal detection, worth surfacing).

**Boundary resolution between adjacent primitives.** Where two primitives'
bands overlap (tangent blends, crease neighbourhoods), the energy decides;
the *statistic to report* per boundary is the sign pattern of d(b_f, θ_A) −
d(b_f, θ_B) along the boundary strip. A clean boundary has this difference
crossing zero once transversally; a blend band has a monotone ramp wider
than 4ε.

**Blend bands.** Constant-radius fillets are detected as **tori** (§5) —
along a straight edge the blend is a cylinder segment, along a circular edge
a torus, and both are in the primitive set, so most fillets are claimed by
detection, not orphaned. What this paragraph handles is the remainder: a
strip matching the ramp signature that *no* torus/cylinder claimed (variable
radius, elliptical blend, chamfer-like transitions). Such strips are
relabeled `unclaimed` with sub-kind `blend-band`, width recorded. Emission
mapping for the claimed case (revises plan 005 KTD8): a torus (or blend
cylinder) whose region is adjacent to exactly two accepted primary regions,
tangent to both within the §8.1 test, becomes a **fillet feature on the
shared edge with radius = the minor radius** — parametric and editable —
never torus surface geometry. A torus not in that adjacency pattern (e.g. an
O-ring groove) is reported as a torus fit but emitted as `unreconstructed`
until an archetype exists for it.

**Points explained by nothing** stay `unclaimed`, aggregated into connected
components, each reported with area fraction, bbox, and dominant HK
signature (§4.4) — "saddle signature, no supported primitive" is a refusal
message; "nothing fit" is not. Feeds R13 coverage directly. Unclaimed is a
first-class outcome, never an error.

Crease seeds: where the dihedral field (from §3.2's pass) shows edges above
`max(25°, 6·2.2 σ̂/ℓ_med)` — i.e., genuinely above the noise floor — those
edges are pinned as label boundaries in ICM (moves that would place the same
label on both sides pay an extra λ_s each sweep). On clean meshes this
recovers plan 005's crease behaviour exactly; on noisy meshes the pin
threshold rises out of reach and the term vanishes. One mechanism, both
regimes.

---

## 7. Uncertainty: covariances that mean something

### 7.1 Covariance from the normal equations

Every refined primitive gets a Gauss–Newton pass (one iteration suffices at
the least-squares optimum the exact fitter already found) purely to obtain J,
the Jacobian of the orthogonal-distance residuals r ∈ R^n with respect to the
minimal parameterization (below). Then

    σ_r²  = (rᵀr) / (n − p)                (residual variance, p = #params)
    Σ_θ   = σ_r² · (Jᵀ J)^{-1}             (parameter covariance)          (7.1)

(JᵀJ)⁻¹ via `_solve` on p ≤ 6 columns of the identity; in the centred/scaled
frame (§2.2) so the pivot floor is meaningful. Minimal parameterizations —
these matter, because gauge freedom makes JᵀJ singular in naive coordinates:

- **plane** (3): tilt (δu, δv) about the fitted normal in the `_frame` basis,
  offset δd. Residual rᵢ = n·pᵢ − d ⇒ ∂rᵢ = (u·p̃ᵢ, v·p̃ᵢ, −1) with p̃ centred.
- **sphere** (4): centre (3), radius.  ∂rᵢ = (−unit(pᵢ−c), −1).
- **cylinder** (5): axis-point offsets (c_u, c_v) in the plane ⊥ axis through
  the centroid projection (kills the slide-along-axis gauge), axis tilt
  (θ₁, θ₂), radius. With wᵢ = pᵢ − c, tᵢ = wᵢ·a, vᵢ = wᵢ − tᵢ a, v̂ᵢ = vᵢ/‖vᵢ‖:

      ∂rᵢ/∂c_u = −v̂ᵢ·u      ∂rᵢ/∂c_v = −v̂ᵢ·v
      ∂rᵢ/∂θ₁  = −tᵢ (v̂ᵢ·u)  ∂rᵢ/∂θ₂  = −tᵢ (v̂ᵢ·v)
      ∂rᵢ/∂r   = −1                                             (7.2)

- **cone** (6): axis-point (c_u, c_v) at the centroid projection, tilt
  (θ₁, θ₂), **radius-at-reference R** (not apex!), half-angle ω, with signed
  residual rᵢ = (ρᵢ − R − tᵢ tan ω) cos ω. Jacobian:

      ∂rᵢ/∂c_u = −cos ω (v̂ᵢ·u) + sin ω (a·u)·0   → −cos ω (v̂ᵢ·u)
      ∂rᵢ/∂θ₁  = −(tᵢ cos ω + ρᵢ sin ω)(v̂ᵢ·u)     (and ·v for θ₂, c_v)
      ∂rᵢ/∂R   = −cos ω
      ∂rᵢ/∂ω   = −(ρᵢ − R − tᵢ tan ω) sin ω − tᵢ / cos ω        (7.3)

  This (R, ω) form is finite at ω → 0 (the cylinder limit) and is the
  **required** cone parameterization everywhere in §7–§8. The apex, when
  reported, is the derived quantity x₀ = c − (R/ tan ω) a with covariance by
  the delta method (§7.2) — its variance correctly blows up as ω → 0, which
  is the honest statement that a near-cylinder's apex is unknowable.

- **torus** (7): centre (3, as (c_u, c_v) ⊥ the axis plus c_t along it),
  tilt (θ₁, θ₂), major radius R, minor radius r. With w = p − c, t = w·a,
  ρ = ‖w − t a‖, q = sqrt((ρ−R)² + t²), residual rᵢ = q − r:

      ∂rᵢ/∂c_u = −[ ((ρ−R)/q)(v̂ᵢ·u) ]     ∂rᵢ/∂c_t = −(t/q)
      ∂rᵢ/∂θ₁  = ((v̂ᵢ·u)/q) · ( t R )      (and ·v forms for c_v, θ₂;
                                            derived via ∂t = ρ(v̂·δa),
                                            ∂ρ = −t(v̂·δa))
      ∂rᵢ/∂R   = −(ρ−R)/q
      ∂rᵢ/∂r   = −1                                              (7.3b)

  Note ∂rᵢ/∂θ₁ vanishes as R → 0 (sphere limit: tilt unobservable) and
  ∂rᵢ/∂R saturates at ±1 as R → ∞ (cylinder limit: R and c_u confound).
  Both degeneracies are exactly the §5.8 demotion triggers; the covariance
  reports them before they become numerical failures.

### 7.2 Delta method for derived quantities

For any derived scalar or small vector g(θ) (apex position, axis-to-axis
distance, diameter = 2r, angle between two fitted directions):

    Σ_g = G Σ_θ Gᵀ,   G = ∂g/∂θ                                    (7.4)

with G computed analytically where trivial and by central differences
(step = 1e-6 in the scaled frame) otherwise. Cross-feature quantities use
the block-diagonal Σ of the two independent fits; after a joint constrained
fit (§8.4) they use that fit's joint Σ, which is the point of doing it.

### 7.3 Correlated residuals — the n_eff inflation

(7.1) assumes independent residuals. Scanner noise and any upstream
smoothing correlate neighbours, making Σ_θ optimistic — and every snap test
then over-snaps. First-order correction: compute the mean lag-1 residual
correlation over the mesh adjacency restricted to the inlier set,

    ρ̄ = ( Σ_{(i,j) adjacent} rᵢ rⱼ / m ) / ( Σᵢ rᵢ² / n ),

and inflate:  n_eff = n (1 − ρ̄)/(1 + ρ̄)   (Bartlett's AR(1) approximation),
Σ_θ ← Σ_θ · (n / n_eff), clamped to n_eff ≥ p + 1. This is approximate — the
true correlation structure is 2-D, not AR(1) — and it is flagged as such in
the record (`covariance_inflation = n/n_eff`). It is also the honest reason
§8's z-thresholds default conservative (z = 3, not 1.96).

---

## 8. Relationship inference, constrained re-fitting, snapping

### 8.1 The relation tests — tolerance from covariance, never a magic constant

Each relation is a null hypothesis about a parameter-difference vector Δ with
covariance Σ_Δ from §7 (block sum of the two features' covariances, delta
method for the mapping). Test statistic

    Tstat = Δᵀ Σ_Δ⁻¹ Δ   ~ χ²_q under H₀  (q = dim Δ)               (8.1)

Accept the relation as *statistically consistent* iff Tstat ≤ χ²_q(1 − α′),
with α′ Šidák-corrected for the m relation hypotheses actually tested across
the model: α′ = 1 − (1 − α)^{1/m}, α default 0.001 (conservative per §7.3).
χ² quantiles: for the q ∈ {1,2,3,4} needed here, tabulate the four constants
(no scipy): χ²(0.999) = 10.83, 13.82, 16.27, 18.47; interpolation for the
Šidák-adjusted level uses the Wilson–Hilferty approximation
χ²_q(1−α′) ≈ q (1 − 2/(9q) + z_{1−α′} sqrt(2/(9q)))³, with z from the
stdlib-computable inverse via `statistics.NormalDist().inv_cdf` (stdlib since
3.8 — no hand-rolled erfinv needed).

Per relation, Δ and q:

| Relation | Δ | q |
| --- | --- | --- |
| parallel (2 directions) | tilt components (θ₁, θ₂) of axis B in axis A's tangent frame | 2 |
| perpendicular | (a_A·a_B) minus 0, expressed as the 1-D angle deviation from 90° | 1 |
| coaxial (2 axes) | (θ₁, θ₂, o_u, o_v): relative tilt + perpendicular offset of the two axis lines evaluated at the midpoint of their footpoints | 4 |
| concentric (2 centres) | c_A − c_B | 3 |
| equal radius | r_A − r_B | 1 |
| tangent (cylinder–plane) | dist(axis, plane) − r | 1 |
| tangent (cylinder–cylinder, external/internal) | ‖axis offset‖ − (r_A ± r_B) | 1 |
| symmetric (mirror) | see §8.3 | varies |

The second channel: **declared intent tolerance.** On a machined part two
bores meant coaxial can be measurably 20 µm off while σ_fit is 5 µm — the χ²
test then correctly says the *data* distinguishes them, yet the *intent* is
still coaxial. So each relation also passes if its physical deviation (the
natural scalar: axis offset, angle, radius difference) is below the
caller-declared `intent_tolerance` for that relation class (R15, with
rationale). Relations accepted this way are labeled `deviation-significant`:
the record states both that the relation was adopted and that the part
measurably violates it. Statistical channel and intent channel are both
recorded per proposal; neither is silent.

Candidate generation is O(pairs) over accepted features (dozens, not
thousands): all pairs are tested for the relations their kinds admit;
`propose_design_intent`'s existing pair loop is the shape to extend, its
fixed 2°/2% constants replaced by (8.1) + intent tolerances.

### 8.2 Pattern relations: bolt circles and equal spacing

After equal-radius clusters form (union of pairwise-accepted equal-radius
relations — take connected components of that graph), for each cluster of
≥ 3 coaxial-parallel cylinders: fit a circle to their axis footpoints in the
plane ⊥ the common direction (`_fit_circle_2d`), test each centre's residual
against its positional covariance (χ²_2 each), and test angular spacings for
equality (all gaps vs mean gap, χ² with the delta-method gap variances). A
passing cluster becomes one `bolt-circle` proposal carrying centre, radius,
count, phase — the single highest-value "intent" structure on real parts.

### 8.3 Mirror symmetry

Generate candidate mirror planes from every pair of same-kind features: the
perpendicular bisector plane of the two centres/axis-footpoints, with normal
along the centre-difference (planes: bisector of the two planes). Cluster
candidates (two planes are the same candidate if their normals agree within
the merged angular covariances and offsets within positional ones — the §8.1
test applied to plane pairs). For each surviving candidate M with ≥ 2
supporting pairs: reflect **every** accepted feature through M, greedily
match reflected features to originals of the same kind (nearest in parameter
space, each used once), and form the joint statistic
Σ_matched Δᵀ Σ_Δ⁻¹ Δ ~ χ²_{Σq}. Features left unmatched count against a
declared coverage fraction (default: matched features must carry ≥ 60% of
total fitted area). This replaces `_symmetry_proposal`'s two hardcoded cases
with one mechanism and is the R7 generalization.

### 8.4 Constrained re-fitting — the optimization, specified

**Principle: parameter elimination, not Lagrange multipliers.** Every adopted
relation is realized by *substituting* shared parameters, so the joint
problem stays an unconstrained small least squares — no multiplier
saddle-point machinery, no constraint drift, and the joint covariance falls
out of the same normal equations.

Substitution table (composable):

| Adopted relation | Joint parameterization |
| --- | --- |
| coaxial cylinders/cones | one shared axis (c_u, c_v, θ₁, θ₂); per-feature radius (+ per-cone R, ω) |
| parallel axes/normals | one shared direction (θ₁, θ₂); per-feature positions |
| perpendicular | feature B's direction parameterized as a unit vector in the plane ⊥ A's direction: one angle ψ (B's direction = cos ψ u_A + sin ψ v_A), A's tilt params shared into the frame |
| concentric spheres | one shared centre; per-feature radius |
| equal radius | one shared r |
| tangent (cyl–plane) | eliminate the cylinder radius: r ≔ n·c_axis − d (signed distance of axis to plane); the cylinder residual's ∂/∂r column redistributes onto the plane's (tilt, offset) and the axis-position columns by the chain rule |
| symmetric | reflected features share the mirrored parameters: for each matched pair, keep one feature's parameters + the mirror plane's 3; the partner's residuals are computed through the reflection map |
| bolt circle | member axis footpoints ≔ centre + R_bc (cos(φ₀ + 2πk/K), sin(φ₀ + 2πk/K)); members contribute residuals through (centre, R_bc, φ₀) |

**Cluster formation.** Build a graph: features are nodes, adopted relations
are edges; each connected component is one joint problem. Component
parameter count p_joint stays small (a fully related part might reach ~30;
the normal equations are p×p and `_solve` handles that — Gauss–Jordan at
p = 30 is 30³ ≈ 3·10⁴ ops, trivial).

**Solver: Levenberg–Marquardt.** Residual vector stacks every member
feature's orthogonal-distance residuals over its inlier points (weights: 1/σ̂
uniformly; per-point weighting buys nothing under a global noise model).
Update equations:

    solve  (Jᵀ J + λ diag(JᵀJ)) δ = −Jᵀ r          (via _solve)
    θ_try = θ ⊞ δ        (⊞ = apply tilts as rotations, renormalize directions)
    if cost(θ_try) < cost(θ):  θ ← θ_try;  λ ← λ/3
    else:                                   λ ← 10 λ  (retry, same iteration)
    stop when |Δcost|/cost < 1e-12  or ‖δ‖_∞ < 1e-10  or 50 iterations
              or λ > 1e8  (declare `refit-diverged`, keep pre-constraint fits,
                           drop the relation adoption, report it)

Conditioning caveats, each with its guard:

- The normal equations square J's condition number. Guard: all data centred
  and scaled (§2.2); tilt parameters are dimensionless angles and positions
  are in extent units, so diag(JᵀJ) entries are commensurate and Marquardt
  scaling (λ·diag, not λ·I) equalizes the rest.
- Shallow-arc cylinders make (c_u, c_v, r) columns near-collinear (the
  1/φ² pathology of §10.1) — the joint fit inherits it. Guard: features must
  pass §10's support gate *before* entering relation adoption; a feature that
  cannot stand alone cannot stiffen a cluster.
- ω → 0 cones: (7.3)'s ∂/∂ω column ≈ −tᵢ/1 stays finite, but ω can step
  negative; clamp ω ≥ 0 by folding (ω ← |ω|, axis flip) inside ⊞.

**Staged adoption in GlobFit's priority order.** (Li, Wu, Chrysanthou,
Sharf, Cohen-Or, Mitra, *GlobFit*, SIGGRAPH 2011 — the published answer to
exactly this problem.) Relations are adopted in three strict stages, each
stage completing — including its re-fits and rollbacks — before the next
begins:

1. **Orientation**: parallel, perpendicular, canonical-direction snaps
   (§8.5 applied to axes/normals), equal-angle. These involve only
   direction parameters, so their constrained re-fits are the
   best-conditioned and their adoption stabilizes everything downstream.
2. **Placement**: coaxial, concentric, coplanar-offset, tangent, mirror
   symmetry, bolt-circle positions. Solved with the stage-1 orientation
   substitutions already frozen in.
3. **Equality**: equal radius, dimension/value snaps (§8.5 on lengths and
   radii), bolt-circle radius/phase.

Within a stage, proposals are processed most-confident first (ascending
Tstat/χ²_crit, ties by relation-kind order then sorted feature-name pair —
deterministic). Adopt one; **re-fit the affected cluster** under all
adopted substitutions (the LM solve above — this is the "simultaneous
re-fit" of GlobFit, done per cluster rather than globally because clusters
are independent by construction; Benkő, Kós, Várady, Andor, Martin, CAGD
19(3) 2002 establish that this sequential parameter-elimination formulation
converges without a general nonlinear-programming solver, which is what
makes it stdlib-tractable). Then **re-test all not-yet-adopted proposals
against the updated parameters and covariances** — an adopted relation can
strengthen or kill a marginal one. O(m²) re-tests at m ≈ dozens: negligible.

**Rollback on the noise bound.** After each cluster re-fit, every member
must still fit its own data. The test is the nested-model F statistic per
member: adopting the relation removed q_m effective parameters from member
m's fit, so under H₀ (the relation is real)

    F_m = ( (SSR_m^constrained − SSR_m^free) / q_m ) / ( SSR_m^free / (n_eff,m − p_m) )

is F(q_m, n_eff,m − p_m)-distributed; reject — roll the relation back,
restore the previous parameters, mark the proposal `refit-rejected` with
F_m recorded — when F_m exceeds the (1 − α′) quantile (Wilson–Hilferty via
the χ² approximation q·F ~ χ²_q at these dof). This is GlobFit's
"stays within its noise bound" made exact: the bound *is* the member's own
residual variance, with the §7.3 n_eff inflation carried through. A
declared backstop `joint_rms_growth` (default 25%) also rejects — the F
test is the principled gate, the RMS cap is the guard against the F test's
own assumptions failing (§7.3).

### 8.5 Snapping near-canonical values

Candidate canonicals: axis directions against the datum axes and declared
canonical angles ({0, 30, 45, 60, 90}° by default); lengths/radii/offsets
against a declared grid ladder G = (1, 0.5, 0.25, 0.1, 0.05) in caller
units — both R15 thresholds with rationale (metric shop vs imperial shop
ladders differ, and the module must not assume).

For parameter x with std σ_x (post-inflation, post-joint-fit), candidate
value x₀ (grid: x₀ = round(x/g)·g):

    snap iff   |x − x₀| / σ_x ≤ z_crit        (consistency)
         and   g ≥ 2 · z_crit · σ_x           (identifiability)         (8.2)

with z_crit from the same Šidák α′ as §8.1 over the number of snap tests.
The identifiability condition is the anti-invention rule made precise: when
the grid step is finer than the data's own 2z confidence width, *multiple*
grid values are consistent and choosing one would be inventing precision —
so the ladder is walked coarse-to-fine and stops at the last identifiable
step. A 2.997 mm radius with σ = 0.002 mm snaps to 3.0 at g = 0.25 and at
g = 0.05 (|Δ|=0.003 ≤ 3·0.002 fails… Tstat = 1.5 ≤ z, passes; g = 0.05 ≥
2·3·0.002 = 0.012, identifiable) → snapped to 3.000, both tests recorded. An
axis 0.4° off Z with σ_θ = 0.05° does **not** snap (8σ away): the record
proposes nothing and the 0.4° stands — if the caller's intent tolerance
channel (§8.1) covers 0.4°, it may adopt via that channel, labeled
`deviation-significant`, never silently.

A snap is an adopted relation like any other: it enters §8.4 as a parameter
substitution (the value becomes a constant, the column leaves J), the
cluster re-fits, remaining proposals re-test. Every snap records: measured
value, snapped value, σ_x, z, the grid step, and which channel licensed it.

---

## 9. Datum frame derivation

Plan 005 U3's total order stands (primary axis from the dominant cylinder
else largest plane; origin from the perpendicular plane nearest the bbox
minimum; X from the largest parallel plane else second cylinder; refusals
`frame-ambiguous` / `frame-x-underdetermined`). Three refinements from this
document's machinery:

1. **Scores carry uncertainty.** Candidate score for the primary axis is
   `radius × axial_span` (cylinders) or supporting area (planes), and the
   winner–runner-up margin is measured in units of the *propagated score
   std* (delta method over the two candidates' Σ_θ). `frame_margin` is then
   a dimensionless z, default 3 — the same conservatism as everywhere else —
   instead of an arbitrary score difference.
2. **Snapped and constrained parameters feed the frame**, not raw fits: the
   frame derives after §8, so a bolt circle's shared axis — not four subtly
   different ones — defines Z, which is both more stable and more intentional.
3. **Tie-breaks compare quantized values** (§2.3): lexicographic on
   `round(v/(1e-9·extent))` of the canonicalized direction then anchor —
   never raw floats, never dict order, never face-group ids.

The frame record carries winner, runner-up, margin-in-z, and the chain of
rules that fired — reproducible and auditable.

---

## 10. The disproof gates, made rigorous

All three run per accepted primitive after refinement (§5.8) and again after
joint re-fitting (§8.4) for any feature whose parameters moved. Failure
returns `accepted=False` with the named rejection on the existing
`PrimitiveFit` shape, plus the new `support` dict (plan 005 U2 interface
change 3) carrying the numbers.

### 10.1 Support span — uncertainty-driven, with the arc derivation

The principled statement is not "span ≥ 60°" but "the parameters this fit
claims must be determined by the data to the precision downstream use
needs." Both are enforced; the second is primary.

Arc scaling law (why tiny spans are hopeless): for a circle observed over
half-angle φ with n points of noise σ, write the chord L ≈ 2Rφ and sagitta
s = R(1−cos φ) ≈ Rφ²/2; the fit determines R essentially through s, and
∂R/∂s ≈ −R/s, so

    σ_R ≈ σ_s · R/s ≈ c σ / (φ² √n),  c ≈ 4–8.                    (10.1)

At φ = 10°, σ = 0.05 mm, n = 500: σ_R ≈ 5 mm·(σ-units) — the radius is
unknown to millimetres. The gate:

- **Primary**: relative parameter uncertainty from Σ_θ (§7): reject when
  σ_R/R > `max_radius_rel_sigma` (default 0.02, declared) or the axis tilt
  σ_θ > `max_axis_sigma` (default 1°). This is (10.1) computed exactly
  rather than by scaling law.
- **Hard floor** (because Σ_θ itself is untrustworthy exactly where it
  reports disaster — near-singular JᵀJ): angular span about the axis
  (2π − largest angular gap over a 64-bin histogram of inlier φ, wraparound)
  ≥ `min_angular_span` (default 60°); axial span ≥ 2 R or ≥ 4 ℓ_med,
  whichever is larger, for cylinders/cones; solid-angle occupancy ≥ declared
  fraction for spheres (octahedral-map bins); area/extent² ≥ declared for
  planes. Floors are declared thresholds with rationale (R15).

### 10.2 Residual structure — Moran's I on the mesh graph

Structured residuals mean the wrong primitive kind even at flattering RMS
(the shallow-cone-as-cylinder case). Formal test: spatial autocorrelation of
the signed residuals rᵢ over the inlier adjacency graph (points adjacent if
mesh-adjacent and both inliers), binary symmetric weights.

    I = (n / S₀) · ( Σ_{ij} w_ij rᵢ rⱼ ) / ( Σᵢ rᵢ² ),   S₀ = Σ_{ij} w_ij
    E[I] = −1/(n−1)
    Var[I] = [n² S₁ − n S₂ + 3 S₀²] / [S₀² (n²−1)] − E[I]²          (10.2)
      with (binary symmetric)  S₁ = 2 S₀,   S₂ = 4 Σᵢ dᵢ²  (dᵢ = degree)
    z_I = (I − E[I]) / sqrt(Var[I])

Reject `residual-structure` when z_I > `moran_z_max`. Default 6 — not 2 —
for a stated reason: scanner noise is itself mildly spatially correlated, so
the iid null is conservative-false; the empirical calibration is to compute
z_I on the mesh's own largest accepted plane (planes are the kind that is
almost never wrongly chosen) and require other features' z_I ≤ that baseline
+ declared slack. Both the absolute cap and the baseline comparison are in
the record. A wrong-kind fit produces z_I in the hundreds (every residual
agrees in sign with its neighbours over whole bands); the gate has enormous
separation in practice, which is why a crude threshold is safe.

Complement (cheap, directional, kept from plan 005 R5): bin residuals along
each chart coordinate (16 bins); per-bin mean beyond 4 σ̂/√n_bin in ≥ 2
adjacent bins also rejects, and *names the coordinate* — which tells the
implementer whether the error is axial (cone-vs-cylinder) or azimuthal
(off-axis), the most actionable diagnostic in the whole gate set.

### 10.3 Held-out residual — spatially blocked

Random point-splits are optimistic under correlated noise (each held-out
point has an in-sample neighbour 0.5 mm away). Split spatially instead:
checkerboard by octree cell parity at the level whose cells are ≈ 8 ℓ_med
(parity = (ix+iy+iz) mod 2 of the cell coordinates). Fit on A, evaluate RMS
on B; swap; gate:

    max(RMS_B|A, RMS_A|B) / RMS_in-sample ≤ heldout_ratio_max   (default 1.5)

Rejection name `heldout-residual`. The threshold's rationale: under a
correct model with n ≫ p the ratio concentrates near 1 with spread
O(√(p/n) + block-correlation slack); 1.5 is far outside that for the n ≥ τ
this pipeline accepts, while an overfit small-support fit fails immediately.
The split is deterministic (octree is deterministic; parity is arithmetic).

### 10.4 Nested-kind parsimony — which primitive kind wins

**[Superseded 2026-08-21, Amendment §1: these are singular/boundary limits,
not regular nests — the F statistic below is replaced by spatially blocked
held-out comparison and/or a parametric bootstrap under the simpler kind.
The parsimony *principle*, the Jaccard trigger, and the demotion vocabulary
stand.]**

The kinds nest: cylinder ⊂ cone (ω = 0), cylinder ⊂ torus (R → ∞),
sphere ⊂ torus (R = 0). When both a simpler and a richer kind survive the
gates on essentially the same point set (inlier Jaccard ≥ 0.8), the richer
kind is kept **only** if the nested-model F test justifies its extra
parameters:

    F = ( (SSR_simple − SSR_rich) / Δp ) / ( SSR_rich / (n_eff − p_rich) )
    keep the richer kind iff F > F_{Δp, n_eff − p_rich}(1 − α′)

with Δp the parameter-count difference (1 for cone-over-cylinder, 2 for
torus-over-cylinder, 3 for torus-over-sphere) and the same n_eff inflation
as everywhere. Ties and non-nested overlaps (e.g. cone vs torus) fall back
to the extraction cascade's connected-inlier score, ties by lower RMS, then
by kind order. This test, plus the §5.8 demotions, is what distinguishes a
torus from a cylinder or sphere *by evidence*: a fillet band with genuine
major curvature passes; a straight blend does not sprout an R = 10⁶ torus.

---

## 11. Data structures, complexity, budget

### 11.1 Spatial index for fixed-radius neighbourhoods: uniform grid, not kd-tree

Every neighbourhood query in this pipeline is *fixed-radius* (h, ε-bands, β
cells) — the regime where a hash grid beats a kd-tree, and in pure Python by
a wide margin (no recursion, no node objects; dict of `(ix,iy,iz) →
list[int]`). Cell size = h; a query gathers 27 cells and filters. Build
O(N); query O(k̄). kd-trees are specified *nowhere* in this design;
`ponytail:` uniform grid everywhere — revisit only if a future stage needs
k-NN with wildly nonuniform density, and then the octree (§5.3) already
exists to subdivide.

### 11.2 Stage complexities and the pure-Python budget

N points, F ≈ 2N triangles, E ≈ 3N edges; k̄ = mean neighbourhood ≈ 20–60;
T = RANSAC candidates (hundreds to low thousands); s = 4096 subsample;
m = features (dozens).

| Stage | Complexity | 200k-vertex estimate (CPython, ~2·10⁷ flops/s effective) |
| --- | --- | --- |
| dedup, adjacency, dihedrals | O(F) | 3–6 s |
| grid build + noise estimate | O(N) + O(m_σ k_σ) | 2–4 s |
| normals (trimmed PCA, 2 passes) | O(N k̄) — **dominant** | 40–120 s |
| curvature quadrics | O(N k̄) (shares gathers with normals) | +30–60 s |
| octree build (+1 rebuild) | O(N d_max) | 3–6 s |
| RANSAC candidates | O(T (k + s)) | 5–30 s |
| full scores + refinement | O(extractions · iters · N) ≈ O(10·3·N) | 30–90 s |
| ICM segmentation | O(sweeps · F · labels_local) | 10–30 s |
| covariances, relations, LM refits | O(m² + Σ n_f p²·iters) | 5–20 s |
| gates (Moran, held-out, span) | O(E + N) | 5–15 s |

**Total: roughly 2–6 minutes at 200 k vertices**, dominated by normal/
curvature estimation and refinement scoring — a batch analysis step in a
workflow where a human reads the fit record before anything is emitted; plan
005 already accepted "tens of seconds" as fine and this is the honest
larger number for the richer pipeline. Two levers if measurement (plan 005
A5's benchmark) comes back worse:

1. **Deterministic subsampling** is statistically principled here — fitting
   is estimation, and (4.1)/(7.1) tell you exactly what precision a subset
   buys. Poisson-disk-by-grid (keep first point per cell of size ℓ_target,
   index order) to ~50 k points cuts every O(N k̄) stage ~4× while σ_R grows
   only as √(N/N′). The full point set is still used for the final
   per-feature refinement and gates (single O(N) passes).
2. The plan-005 escape hatch (numpy host-side as a differential-tested
   `[fast]` extra) remains available and is not this document's to decide.

Memory: the working set is ~15 floats + small ints per point → ~100–150 MB
of Python objects at 300 k points using tuples; use parallel `array('d')`
arrays for coordinates/normals if measurement shows list-of-tuple overhead
biting. `ponytail:` tuples first, arrays when measured.

---

## 12. What this design handles, and what it honestly does not

### 12.1 The noise claim, with its arithmetic

**Claim: this design produces correct, gated, uncertainty-carrying fits at
point noise up to σ ≈ ℓ_med (noise comparable to the triangle edge length),
and resolves features down to ~10 σ; the contested case σ = 0.05 mm on
ℓ = 0.5 mm triangles is handled with an order of magnitude of margin.**
**[Conditioned 2026-08-21, Amendment §2: the ~10σ floor is the
iid-point-noise regime bound its derivation actually supports — it is not a
universal identifiability law. Resolution reporting is the measured
detector power conditional on regime.]**

Reasoning, stage by stage at the contested case:

- Normals: §4.2's worked instance gives σ_θ ≈ 1° at h = 1.25 mm — RANSAC's
  α ≈ 20° check operates at 20× margin; even σ = ℓ (0.5 mm noise!) yields
  σ_θ ≈ 10° at the same h, still inside α.
- Detection: the ε = 3σ̂ band is a *relative* construction; RANSAC's
  probability arithmetic (5.1–5.2) involves only counts. Noise does not
  degrade detection until distinct surfaces are closer than ~2ε ≈ 6σ — i.e.
  until *features* shrink toward the noise, which is the real limit:
  a step, wall, or radius difference below ~6–10 σ cannot be separated from
  the surface it adjoins by any distance-band method (information-theoretic,
  not implementational: within the patch, the two hypotheses differ by less
  than the noise). At σ = 0.05 mm that floor is 0.3–0.5 mm — smaller than
  the mesh's own triangles.
- Parameters: (7.1) gives σ_R ≈ σ·c/√n_eff; a 10 mm-radius boss sampled by
  5 000 effective points at σ = 0.05 mm carries σ_R ≈ few µm — snapping and
  relations operate far above their identifiability floors (8.2).
- What actually degrades first as σ grows: curvature hints die (already
  non-load-bearing by design), blend-band boundaries (§6) widen as 4ε, and
  small-feature recovery recedes as the 10σ floor rises. All three degrade
  *gradually and reportedly* — the record carries σ̂, the achieved σ_θ, and
  the feature-size floor 10σ̂, so the caller knows what a given scan can
  support before asking for it.

Refusal is reserved for the genuine cliff: σ̂ within a declared factor of
`min_feature_size` (the 10σ floor crossing the features the caller declared
they need), and the `noise-model-inconsistent` flag combined with failed
gates — replacing plan 005's blanket `segmentation-noise-limited` refusal,
which fired on the estimator, not on the information content.
**[Conditioned 2026-08-21, Amendment §2: this refusal rule inherits the
same regime conditioning as the reporting language — where a measured
regime-specific detector-power record exists, the refusal fires from that
record, not from the iid 10σ̂ arithmetic, which remains only the no-record
fallback. A feature the measured power supports is never refused by the
fallback formula.]**

### 12.2 Genuinely out of reach in pure Python, with reasons

1. **Exact multi-label MRF segmentation (graph-cut α-expansion) at 200 k+
   triangles.** Needs a max-flow solver; BK-style max-flow is ~300 lines and
   O(minutes) per expansion sweep in CPython at this size. Fallback chosen:
   ICM (§6) — deterministic, fast, and within 1–2 boundary triangles of
   optimal when data terms are 3σ-separated, which §5's gates guarantee.
   Cost: slightly ragged boundaries in blend bands, which §6's blend-band
   detection absorbs. Not a capability gap for this pipeline's outputs.
2. **General dense SVD / large eigenproblems.** Not needed: every eigen
   problem here is symmetric 3×3 (Jacobi, exists) or 2×2 (closed form);
   every solve is p ≤ ~30 (Gauss–Jordan, exists); LM works off JᵀJ. A future
   stage needing large SVD (e.g., NURBS surface fitting) would be the
   signal to stop being pure-Python — and freeform is already a permanent
   refusal (plan 005, Not-achievable 1).
3. **Meshes beyond ~500 k–1 M vertices in interactive time.** The O(N k̄)
   stages reach 10–30 minutes. Fallback: the principled subsampling of
   §11.2 (precision cost stated by the formulas, not guessed); beyond that,
   decimation with the plan-005 KTD5 re-hash discipline. This is a
   wall-clock statement, not a correctness one — nothing in the mathematics
   breaks at scale.

### 12.3 The three hardest numerical risks

1. **Nested-kind degeneracy: cone at ω → 0, torus at R → ∞ and R → 0.**
   The cone's apex flies to infinity and ∂r/∂ω becomes collinear with the
   axial-tilt columns on short patches; the torus's R confounds with axis
   position as R → ∞ and its tilt becomes unobservable as R → 0 — in each
   case JᵀJ approaches singularity along the degeneracy direction. Guards:
   degeneracy-finite parameterizations ((R, ω) for the cone, (7.3);
   centre-form for the torus, (7.3b)); covariance-triggered **demotion to
   the nested simpler kind** (`cone-unidentifiable` → cylinder,
   `torus-demoted-cylinder`/`-sphere`, §5.8) rather than reporting fantasy
   parameters; and the §10.4 F test, which refuses to prefer the richer
   kind without evidence in the first place.
2. **Shallow-arc conditioning in circle/cylinder fits.** (10.1): σ_R grows
   as 1/φ², and before it grows, JᵀJ's (c_u, c_v, r) block becomes
   near-collinear — the covariance you would use to *detect* the problem is
   itself computed from a near-singular matrix. Guards: the hard span floors
   of §10.1 run *before* any covariance is trusted; `_solve`'s pivot floor
   in the scaled frame refuses the worst cases outright; and the existing
   `max_radius_ratio` gate catches the flat-strip-fits-a-metre-circle
   presentation of the same disease.
3. **Covariance validity under correlated residuals.** Every snap and
   relation test stands on Σ_θ; naive (7.1) is optimistic by n/n_eff, and
   the §7.3 inflation is a first-order patch (AR(1) on a 2-D field), so
   Tstat calibration is approximate. Guards: conservative z defaults (3+),
   Šidák correction over the tested family, the identifiability condition
   (8.2) — which prevents the worst *consequence* (inventing precision) even
   when σ_x is underestimated — and the empirical-baseline calibration of
   Moran's I (§10.2). Residual risk: marginal snaps near the threshold can
   flip between runs on different scans of the same part; they are recorded
   with their Tstat precisely so a reviewer can see how close the call was.

---

## 13. Reference implementations

Included where prose + equations leave construction ambiguity. These are
specification artifacts, not production code; production homes are the
plan-005 U2 modules.

### 13.1 Sphere and cylinder from two oriented points (§5.1)

```python
def sphere_from_2(p1, n1, p2, n2, eps):
    d = _sub(p2, p1); b = _dot(n1, n2); D = 1.0 - b * b
    if D < 1e-4:
        return None                     # parallel normals: centre unobservable
    t1 = (_dot(n1, d) - b * _dot(n2, d)) / D
    t2 = (b * _dot(n1, d) - _dot(n2, d)) / D
    q1 = _add(p1, _scale(n1, t1)); q2 = _add(p2, _scale(n2, t2))
    if _length(_sub(q1, q2)) > 2.0 * eps:
        return None                     # normal lines do not meet
    c = _scale(_add(q1, q2), 0.5)
    r1, r2 = _length(_sub(p1, c)), _length(_sub(p2, c))
    if abs(r1 - r2) > 2.0 * eps or min(r1, r2) <= 0.0:
        return None
    return c, 0.5 * (r1 + r2)

def cylinder_from_2(p1, n1, p2, n2, eps):
    a = _unit(_cross(n1, n2))
    if a is None or _length(_cross(n1, n2)) < 1e-2:
        return None                     # same generator line: axis unobservable
    def proj(p):  # into plane ⊥ a through origin
        return _sub(p, _scale(a, _dot(p, a)))
    q1, q2 = proj(p1), proj(p2)
    m1 = _unit(proj(n1)); m2 = _unit(proj(n2))
    if m1 is None or m2 is None:
        return None
    # intersect q1 + t1*m1 = q2 + t2*m2 in the 2-D subspace (least squares 2x2)
    u, v = _frame(a)
    A = [[_dot(m1, u), -_dot(m2, u)], [_dot(m1, v), -_dot(m2, v)]]
    rhs = [_dot(_sub(q2, q1), u), _dot(_sub(q2, q1), v)]
    sol = _solve(A, rhs)
    if sol is None:
        return None
    centre = _add(q1, _scale(m1, sol[0]))
    r = _length(_sub(q1, centre))
    if r <= 0.0 or abs(_length(_sub(q2, centre)) - r) > 2.0 * eps:
        return None
    return centre, a, r
```

### 13.2 Levenberg–Marquardt engine (§8.4) — the whole solver

```python
def lm(residuals_and_jacobian, theta0, apply_step, max_iter=50):
    """residuals_and_jacobian(theta) -> (r: list[float], J: list[list[float]]);
    apply_step(theta, delta) -> theta  (rotational params renormalized inside).
    Deterministic; no RNG. Returns (theta, cost, converged)."""
    theta = theta0
    r, J = residuals_and_jacobian(theta)
    cost = sum(x * x for x in r)
    lam = 1e-3
    for _ in range(max_iter):
        p = len(J[0])
        JtJ = [[sum(J[i][a] * J[i][b] for i in range(len(r))) for b in range(p)] for a in range(p)]
        Jtr = [sum(J[i][a] * r[i] for i in range(len(r))) for a in range(p)]
        stepped = False
        while lam <= 1e8:
            A = [[JtJ[a][b] + (lam * JtJ[a][a] if a == b else 0.0) for b in range(p)] for a in range(p)]
            delta = _solve(A, [-g for g in Jtr])
            if delta is not None:
                trial = apply_step(theta, delta)
                r_t, J_t = residuals_and_jacobian(trial)
                cost_t = sum(x * x for x in r_t)
                if cost_t < cost:
                    if cost - cost_t < 1e-12 * cost or max(abs(d) for d in delta) < 1e-10:
                        return trial, cost_t, True
                    theta, r, J, cost = trial, r_t, J_t, cost_t
                    lam /= 3.0
                    stepped = True
                    break
            lam *= 10.0
        if not stepped:
            return theta, cost, False   # refit-diverged: caller drops the relation
    return theta, cost, True
```

Cylinder residual/Jacobian callback per (7.2); cone per (7.3); joint
problems stack member callbacks column-blocked per §8.4's substitution
table.

### 13.3 Moran's I with variance (§10.2)

```python
def moran(residuals, adjacency_pairs):
    """residuals: dict point_index -> signed residual (inliers only);
    adjacency_pairs: iterable of (i, j), i < j, both inliers, mesh-adjacent."""
    n = len(residuals)
    mean = sum(residuals.values()) / n
    r = {i: v - mean for i, v in residuals.items()}
    s_cross, s0, deg = 0.0, 0, {}
    for i, j in adjacency_pairs:
        s_cross += 2.0 * r[i] * r[j]          # symmetric: count both directions
        s0 += 2
        deg[i] = deg.get(i, 0) + 1; deg[j] = deg.get(j, 0) + 1
    s_sq = sum(v * v for v in r.values())
    if s0 == 0 or s_sq == 0.0:
        return None
    I = (n / s0) * (s_cross / s_sq)
    e_i = -1.0 / (n - 1)
    s1 = 2.0 * s0
    s2 = 4.0 * sum(d * d for d in deg.values())
    var = (n * n * s1 - n * s2 + 3.0 * s0 * s0) / (s0 * s0 * (n * n - 1.0)) - e_i * e_i
    if var <= 0.0:
        return None
    return I, e_i, (I - e_i) / math.sqrt(var)
```

---

## 14. Interface deltas against plan 005

Small and mostly additive; plan 005's U2 interface changes stand, with these
revisions:

1. **R4 revised**: the noise floor is measured by §3's two estimators and
   *reported*; the refusal condition changes from "noise floor within a
   factor of the crease threshold" to "σ̂ · 10 ≥ min_feature_size" plus the
   §3.3 inconsistency flag. `segmentation-noise-limited` is superseded by
   `feature-scale-below-noise` and `noise-model-inconsistent`.
2. **KTD4 revised**: crease-based region growing is demoted from primary
   segmentation to (a) the dihedral noise estimator and (b) ICM boundary
   pins (§6). `triangleFaceGroupTempIds` remains a checked comparison input
   (agreement statistic unchanged).
3. **KTD6 subsumed**: the three gates keep their names; support span becomes
   uncertainty-primary with hard floors (§10.1), residual structure becomes
   Moran's I + directional bins (§10.2), held-out becomes spatially blocked
   (§10.3).
4. **`PrimitiveFit.support`** additionally carries: σ per parameter (the
   diagonal of Σ_θ mapped to reporting units), `covariance_inflation`,
   `moran_z`, `heldout_ratio`, spans.
5. **New R15 thresholds** (each with rationale, per the existing rule):
   `min_feature_size`, `ransac_eta_extract`, `ransac_eta_stop`,
   `normal_alpha_deg`, `snap_grid_ladder`, `canonical_angles_deg`,
   `intent_tolerance.*` per relation class, `joint_rms_growth`,
   `moran_z_max`, `heldout_ratio_max`, `max_radius_rel_sigma`,
   `max_axis_sigma_deg`, `min_angular_span_deg`.
6. **New `INTENT_KINDS`**: `concentric`, `tangent`, `equal_radius`,
   `bolt_circle` join the existing five; every proposal gains
   `tstat`, `dof`, `channel` (`statistical` | `intent-tolerance`), adopted
   ones gain `stage` (orientation | placement | equality) and `F_m` per
   member from the §8.4 rollback test, and snaps gain the (8.2) pair of
   test results.
7. **`PRIMITIVE_KINDS` gains `torus`**, with the new `_fit_torus` (§5.8,
   §7.1) and the demotion vocabulary `torus-demoted-cylinder`,
   `torus-demoted-sphere`, `torus-spindle`. Plan 005's "Not achievable 5"
   (torus fitting) is **revised**: the circular-tube torus is in scope and
   maps to the fillet archetype (§6); variable-radius and elliptical blends
   remain refused, and that half of the entry stands. KTD8's fillet row
   changes from "adjacency and near-constant width, not torus fitting" to
   "torus/blend-cylinder detection, emitted as `filletFeatures` with radius
   = minor radius".
8. **`classify_polyline` improvement** (small, separable, from the abandoned
   INUS application US20070285425A1 via document 008): before the greedy
   line/arc pass, compute discrete curvature along the section polyline
   (turning angle per unit length over a ±3-point window) and force split
   points at its local extrema above the noise floor. This fixes the known
   greedy failure of a gentle arc being absorbed into a line run. The
   greedy classifier is otherwise unchanged.

Nothing in `mesh_fitting.py`'s existing public surface breaks: the exact
fitters are called as-is inside §5.8, the gates compose with `_apply_gates`'s
pattern, and the linear kernel (`_solve`, `_symmetric_eigen`,
`_fit_circle_2d`, `_frame`, `_canonical_direction`) is used unmodified
throughout.

---

## 15. Sources, correctness oracles, licensing

Method sources (all freely implementable; see document 008 for the full
prior-art landscape and patent posture — headline: **no live patent is
relevant to any mechanism specified here**, and the closest on-point
disclosure, US20070285425A1 (INUS 2006, the Design-X-lineage
section→sketch→feature workflow), was abandoned and never granted):

- Schnabel, Wahl, Klein, *Efficient RANSAC for Point-Cloud Shape
  Detection*, CGF 26(2), 2007 — §5. The **paper** is free to implement; the
  authors' code is research-use-only and CGAL's reimplementation is GPL —
  both are reference-only, never copied.
- Li, Wu, Chrysanthou, Sharf, Cohen-Or, Mitra, *GlobFit*, SIGGRAPH 2011 —
  §8.4's staged order and rollback-on-noise-bound.
- Benkő, Kós, Várady, Andor, Martin, *Constrained fitting in reverse
  engineering*, CAGD 19(3), 2002 — §8.4's sequential parameter-elimination
  formulation.
- Lukács, Martin, Marshall, *Faithful least-squares fitting of spheres,
  cylinders, cones and tori*, ECCV 1998 — §5.8/§7.1 torus fit and
  degeneracy demotions.
- Besl, Jain, *Segmentation through variable-order surface fitting*, PAMI
  10(2), 1988 — §4.4's HK signatures.
- Shakarji, *Least-squares fitting algorithms of the NIST algorithm testing
  system*, J. Res. NIST 103:633, 1998 — **the correctness oracle**: US
  government work, public domain, the reference CMM-grade
  orthogonal-distance fits. The test suite for every estimator specified
  here should include fixtures checked against NIST reference results
  (published test data) in addition to the synthetic analytic meshes.
- PCL `sample_consensus` (BSD-3-Clause) and Open3D (MIT) are
  license-compatible secondary oracles for generating expected outputs on
  shared test fixtures; the stdlib-only rule keeps them out of the tree,
  not out of the test-design process.
- CADFit (arXiv 2605.01171, 2026) independently converged on the same
  fit-validate-refuse loop as the disproof gates here and in plan 005 —
  cited so a future reader knows the architecture matches the current
  frontier rather than being invented ad hoc.

---

## Amendment — deep-research reconciliation incorporation (2026-08-21)

*Source: `docs/reviews/2026-08-21-deep-research-reconciliation.md` (finding
4; adoptions 6–7; abandonments 3–4). Markers were placed at §3, §10.4 and
§12.1; this section carries the substance. Everything else in this document
stands — in particular §8.4's relation-rollback F test is examined and
retained (§1 below), and §7.3's AR(1) inflation was already flagged
approximate and already superseded-when-a-record-exists by design -002
§A.4/§B.1.*

### §1 Nested-kind model selection without the singular F test (adoption 7)

§10.4 treated cylinder ⊂ cone (ω = 0), cylinder ⊂ torus (R → ∞), and
sphere ⊂ torus (R = 0) as ordinary nested models. They are not: R → ∞ is a
singular limit (the parameter leaves the space; R confounds with axis
position — this document's own §7.1/§12.3 says so), and ω = 0 places the
parameter on a boundary where identifiability changes. The classical
finite-sample F distribution is not licensed merely by writing one model as
a limiting case of another. §10.4's statistic is replaced by, in precedence
order:

1. **Spatially blocked held-out predictive comparison** — the §10.3
   machinery, applied to the pair: fit both kinds on the same non-validation
   blocks (block scale from the -002 correlation record's held-out
   derivation where it exists, the ≈ 8 ℓ_med default otherwise), compare
   held-out RMS; the richer kind is kept only when its held-out advantage
   exceeds a declared margin (`nested_kind_heldout_margin`,
   `experimental-default` under -002 §B.2).
2. **Parametric bootstrap under the simpler kind** where held-out support is
   too thin to be decisive: simulate replicates from the fitted simpler
   model plus the measured scan-error model — the correlation record's
   noise structure where a record exists; in the no-record regime (the
   regime dispatch determined calibration unnecessary — clean
   tessellations), the measured σ̂ iid model, which is then the *licensed*
   noise model rather than a forbidden substitute. Fit both kinds to each
   replicate and compare the observed richer-kind improvement against the
   simulated null distribution. Replicate count and seed discipline per
   KTD-8; blocks per -002 §A.4. **Where calibration ran and refused**
   (`correlation-model-unidentified`): neither path is licensed — the
   comparison fails closed to the simpler kind, recorded
   `nested-kind-comparison-unlicensed` (the parsimony default is the
   conservative verdict, exactly as the §5.8 demotions already prefer the
   simpler kind at the identifiability boundary).

The verdict is recorded as **model-selection evidence** (`nested-kind
comparison`, with both scores, the margin, and the method used) — never as
an exact classical p-value whose assumptions are unverified. The §5.8
covariance-triggered demotions (`torus-demoted-cylinder`, `-sphere`,
`cone-unidentifiable`) are unchanged — they fire on identifiability, which
is precisely where they belong. **§8.4's per-member rollback survives as a
regular nest but not as a classical calibration**: adopting a relation
constrains parameters in the *interior* of one model's space, so the
singular-limit objection above does not apply — yet under spatially
correlated residuals the constrained/free SSR ratio is still not
F-distributed, and substituting n_eff into the denominator degrees of
freedom does not make it so. Where a frozen -002 §A.4 correlation record
exists, the rollback verdict is therefore computed by the same machinery
as above — blocked held-out comparison of the constrained vs free fits,
or a parametric bootstrap of the F statistic under the constrained model
with the record's noise structure (equivalently, GLS whitening at the
recorded range where implementable) — and recorded as model-selection
evidence. The classical F with n_eff substitution remains only the
no-record fallback (a regime where calibration was never required — a
calibration that ran and refused, `correlation-model-unidentified`, fails
closed per -002 §A.4 instead), flagged approximate exactly as §7.3 already
flags its own inflation; the `joint_rms_growth` backstop is retained unconditionally
in both modes.

### §2 σ scoped; resolution claims made regime-conditional (adoption 6; abandonment 4)

- σ̂ (§3) remains the local point-jitter scale and keeps its local
  consumers. The claim it loses is universality: form error (the -002
  σ_form lane), spatial correlation structure (-002 §A.4's frozen record),
  held-out independence, and parameter covariance are consumer-specific
  estimands; §7.3's global n/n_eff inflation is the fallback when no
  correlation record exists, exactly as -002 §A.4 already provides.
- The "~10σ" feature-resolution floor (§12.1) is retained as what its
  derivation supports — a distance-band separability bound under iid point
  noise — and abandoned as a universal claim. Identifiability depends on
  support area, sampling density, feature geometry, direction, spatial
  correlation, repeated evidence, and prior structure. The reported number
  is the **measured detector power in the relevant regime**: per feature
  family, from the detector's own accept/refuse behaviour on fixtures with
  known ground truth (the -002 §B.2 sweep fixtures serve double duty), and
  the record reports that conditional power beside σ̂ rather than a single
  10σ̂ line. A caller-facing floor derived from iid arithmetic on a
  correlated scan is exactly the substitution this corpus refuses
  elsewhere. This conditioning binds **every downstream consumer of the
  floor**, by name: the spline fit-point spacing floor ("spacing floor at
  10σ̂") of designs 009/010 reads the regime-specific power record where
  one exists and retains the 10σ̂ arithmetic only as the licensed iid
  fallback — otherwise those consumers would reject recoverable profiles
  the measured power supports, or admit noise-scale detail where the
  measured regime is worse than iid.

### §3 Threshold defaults under the sweep rule

This document's declared defaults that change acceptance topology
(`moran_z_max`, `heldout_ratio_max`, the §10.1 span floors,
`min_feature_size`/`min_resolvable_surface_scale`, the nested-kind margin
above) carry the `experimental-default` label under design -002 §B.2's
protocol until swept; the sweep record then backs them. The rename
`min_feature_size` → `min_resolvable_surface_scale` (registered in the
2026-08-20 review file §3) rides the first PR that touches the spec schema.
