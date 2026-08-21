---
title: "design: scan-regime segmentation — panel verdict and synthesis (issue #20)"
date: 2026-08-20
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
execution: code
origin: https://github.com/novotnyllc/agent-utilities/issues/20
builds_on: docs/plans/2026-08-19-007-research-reconstruction-algorithms.md,
  docs/plans/2026-08-19-010-design-fusion-native-architecture.md
inputs: "panel proposals A (algorithms literature), B (reverse-engineering practice),
  C (systems architecture); run artifacts for Dig-Next-2 (fit.json, fit-diag.json,
  coverage.json, fg-histogram.json, fit-spec.json, rebuild-refusal.json)"
status: judged synthesis — scoring, winning design, and PR sequence; no production
  code in this document
---

# Scan segmentation: verdict and synthesis

Judge's charge: score the panel's candidates against declared criteria, synthesize
the winning design, and sequence it into PRs an implementation worker executes one
at a time, each leaving the tree green and something measured better.

Module paths below are relative to
`plugins/agent-utilities/skills/fusion-parametric-design/src/fusion_design/`.

---

## 1. Verified facts vs assumptions

### 1.1 Verified (re-checked against the artifacts during judging, not taken from the proposals)

- **F1.** Dig-Next-2: 524,614 triangles / 262,271 vertices, welded, manifold,
  158 boundary edges, median |dihedral| 2.66°, p90 13.22° (`mesh-extract-report.json`).
- **F2.** GFG produced 4,532 groups; the largest is 448,122 triangles = 78.97% of
  area; 2,347 groups under 10 triangles (`fg-histogram.json`, `fit.json.regions`).
- **F3.** The mega-group's best fit is a **plane, rejected** at relative residual
  0.0484 vs the 0.02 gate (`fit-diag.json` largest region, 12,715.7 mm², accepted:
  false). It is the board's two faces 1.6 mm apart plus the edge band — B's area
  arithmetic (two faces ≈ 11,054 mm² of 16,102 mm² total) is consistent.
- **F4.** `covered_area_fraction = 0.0388`; 443 accepted fits, all planes, all
  ≤ 99 triangles (`fit.json`).
- **F5.** σ was taken from the dihedral estimator at **0.005366 mm** with
  `estimators_disagree: true` (quadric said 0.0022), while the parallel lane
  measures true form error on flat faces at **0.033–0.076 mm rms** — σ is 6–14×
  too small and every σ-derived band inherited that (`fit.json.noise`; A §0).
- **F6.** Refusal census, re-tallied from `coverage.json` (n = 2,605):
  **1,598 held-out ratio failures, 609 held-out blocked-no-fit, 286
  residual-structure (Moran), 54 support-floors, 10 parameter-uncertainty, ~48
  relative-residual**. This **corrects proposal A**, which attributed ~2,255 to
  blocked-no-fit: the underpowered-vs-disproved power floor addresses 609
  regions, not 2,255; the other 1,598 are genuine ratio failures that the σ fix
  (shipment 1) addresses. A's "power floor may double accepted planes on its
  own" is therefore overstated; the σ fix carries most of that weight.
- **F7.** B's Moran-vs-area trend is real and monotone: z = 54.1 at 83.1 mm²
  (rejected), 34.6 at 31.4 mm² (rejected), 19.8 at 13.8 mm² (rejected), 15.8 at
  18.9 mm² (**accepted**) — the accept boundary on this part sits between
  z ≈ 16 and z ≈ 20, and the gate already bites two orders of magnitude below
  board-face area (`fit-diag.json`). B's extrapolation (board face z ≈ 440
  under the iid null) stands.
- **F8.** The relationships enumerator is an unguarded upper-triangle pair loop
  over all accepted fits (`mesh_fitting.py:propose_design_intent`, sorted names,
  `for second in names[index+1:]`), 2° angle tolerance, offset tolerance 2% of
  extent, no spatial gate on parallel/perpendicular/symmetric — 104,014 proposals,
  156.6 MB, no downstream consumer (verified in source and `program.json` size).
- **F9.** Regime detection (`_detect_regime`) correctly said "scan", and it
  already runs *upstream* of the segmentation: `noise-scale` precedes
  `face-groups` in `STAGES`, and `_stage_noise_scale` stores the verdict in
  `state["regime"]` (`mesh_segmentation.py:1652–1653`, `STAGES` at :145). The
  gap is not where it runs but that nothing downstream dispatches on it —
  `_stage_face_groups` never reads `state["regime"]`; only `_stage_disproof`
  does (:1911). So PR 1 wires the existing pre-segmentation value into
  dispatch; it does not relocate the detection (C §2.3, corrected).
- **F10.** `rebuild-refusal.json`: the section at z = 5.173 mm closed 15 loops,
  0 matched to holes, `delivered_area_fraction = 0.0`. This is the 2.5D
  multi-loop emitter lane's scope (PR 3 pending there), **not this design's**.
- **F11.** Declared thresholds in `fit-spec.json` as the proposals quote them:
  `min_feature_size = 1.6`, `min_angular_span_deg = 60`, `moran_z_max = 6`,
  `max_relative_residual = 0.02`, `normal_alpha_deg = 25`.
- **F12.** Patents (B, taken at B's word on the reading, flagged for FTO
  routing): **US11017535B2 (Carestream/Dental Imaging, granted, live)** claims
  fit → remove accepted → run a **modified segmentation procedure** on the
  residual → repeat. **US20070285425A1** covers 2D section segmentation, not 3D
  auto-segment — the prior-art doc `2026-08-19-008` misreads it (follow-up, §11).

### 1.2 Assumptions (labelled, each with the measurement that settles it)

- **A1.** B's percolation arithmetic (leak-free wall needs ≈ 13°; percolation
  ceiling ≈ 2.66°; even textbook 3.75° gives p ≈ 0.66 > p_c = 0.5 on the
  3-regular dual) is a model, not a measurement. Settled by the **ε-sweep
  experiment** (PR 3 pre-work): CC size histogram at ε ∈ {5,8,10,13,20,30,45,60}°.
- **A2.** The board's two faces sit 21σ_form apart along the datum normal and
  bow < ~1.2 mm. Settled by the station KDE itself on the first cross-cut run.
- **A3.** Shipment 1 (branch `feat/scan-sigma-closure`, in flight) moves the
  small-region refusal population; its measured re-run is the decisive
  experiment. Both outcomes are planned for (§5).
- **A4.** Scanner arc coverage on the cans is 180–300°, clearing the 60° span
  gate. Settled by the first post-cross-cut fit record.

---

## 2. Scoring

Criteria (declared): **O** = predicted Dig-Next-2 outcome (board one region per
face; cans and holes fittable) · **σR** = robustness to σ mis-estimation (it will
be wrong again) · **P** = percolation immunity (B's no-overlap proof is the bar)
· **RT** = runtime/memory at 500k–2M · **SZ** = implementation size and reuse ·
**EC** = evidence-chain compatibility · **G** = failure modes our gates catch vs
slip through. Scale 0–5; †marks a contested cell argued in §2.1.

| candidate | O | σR | P | RT | SZ | EC | G | verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **B cross-cut** (dihedral CC × datum cells, then peel) | 5† | **5** | **5** | 5 (~5 s/pass, no derived mesh) | 5 (~250–350 loc, reuses datum + event machinery) | **5** (labels only, zero derived meshes) | 4† | **winning first splitter** |
| **C region tree** (containing architecture) | n/a — not a segmenter | n/a | n/a | 5 (d_max whole-mesh-pass bound; permutation storage 9× RSS cut) | 3 (~1,000 loc for the segmentation-relevant core) | **5** (partition invariant is what keeps coverage honest) | **5** (per-node failure isolation; T1–T5 named) | **adopted as the frame, unconditionally** |
| A1 (filtered normals labels-only → proxy growing → HFP) | 4 (45–65% predicted) | 2† (ε, α, filter σ_r all σ-derived) | 4† (immune *conditional on ε correct*) | 4 (1.5–4 min) | 2 (~600 loc + filter) | 3† (in-memory derived label mesh; params must be recorded) | 3† (filter can *fabricate* a crease — the only candidate with a fabrication mode) | refinement-only, inside cells; filter dropped (§3.2) |
| A1+A3 (Efficient RANSAC on residual) | +5–12% coverage | 3 (fixed ε = 3σ_form) | 4 (bitmap bridging bounded at β = 0.35 mm, not eliminated) | 3 (30–90 s on 100k residual) | 1 (600–800 loc, restores deleted code) | 4 | 4 (explicitly a gate-stress test) | conditional last escalation (PR 6), FTO-gated |
| A2 (vectorized hybrid VSA) | 3† (no convergence guarantee; 85% clutter is the bad case) | 2 (energy is σ-normalized) | 4 | 3 (60–120 s + A1 stages) | 1 (A1 + 300–400 loc) | 3 | 3 (argmin tie non-determinism risk) | rejected; shelf note only |
| B multi-scale GFG on sub-mesh | 0 (B predicts one group again; mechanism-free) | n/a | 0 (same criterion, same field) | 5 | 5 (~20 loc) | 5 | n/a | **run as 20-min falsification with prediction on record; never plan on it** |
| decimate-for-segmentation | 1 (kills confetti; the blob is form waviness, which resampling does not touch) | 3 | 2 | 4 | 2 (+ permanent derived-mesh audit obligation) | 1† (no `derived_from` schema exists — C found the hole) | 2 | rejected for Dig-Next-2; `derived_from` schema ships anyway (§4.6) |

### 2.1 Contested cells, argued

**Cross-cut O = 5, with one judge's correction to B.** Board top/bottom as two
regions: high confidence (21σ slab margin, F3). Holes and cans: B's "radial
normal family (distinct cell)" is **wrong as written** — the argmax over six
signed datum directions *fragments* a cylinder wall into up to four azimuthal
quadrant cells plus ambiguous wedges at the quadrant boundaries, because wall
normals sweep all azimuths. A 90° quadrant arc clears `min_angular_span_deg = 60`
only marginally and wastes evidence. **Fix (one line): all four
lateral families plus the ambiguous family collapse into a single `lateral`
super-cell before CC, and that super-cell carries no station** — the three
holes and three cans are spatially disconnected, so CC isolates each wall
whole. The station must drop out too, not just the azimuth: a through-hole or
can wall spans several datum stations, so keeping `slab-station` in a lateral
triangle's `label_cell` would have the final `np.unique` cut every connected
wall into axial bands — the same fragmentation one axis over, and it would
break the whole-wall measurement PR 3 claims (§6, PR 3). Stations still
separate the axial/planar families, which is what they were introduced for. With that fix B's 3/3 holes
(~490 triangles each, full 360°) and 3/3 can predictions stand; C's caution is
retained for *emission*: on an open mesh `material_side` is unavailable, so
hole/bore classification downstream still refuses even when the cylinder *fit*
is accepted (see follow-up §11.3 on A's winding observation).

**Cross-cut σR = 5 — the decisive column.** The judge's brief said σ will be
wrong again, and it will. The cross-cut's parameters are: ε from an **empirical
quantile of measured in-plane dihedrals** (not from σ at all), family assignment
by **threshold-free argmax** (the ambiguity band is a σ, not a choice), and
station KDE bandwidth = σ_form, where a 2–3× σ error against a 21σ margin merely
widens peaks. A1 puts σ into ε, α, and the filter's range kernel; a repeat of
the 6–14× σ failure re-breaks A1 and leaves the cross-cut standing. This single
column decides first place.

**Cross-cut G = 4, not 5.** Failure modes: warped board widens stations
(degrades gracefully, KDE still finds two peaks below ~1.2 mm bow — A2 in §1.2);
cell explosion (support floors catch it; measure, don't pre-solve); first-pass ε
circularity (the 443 planes are gate-accepted noise samples regardless of how
they were found; pass 2 re-derives — self-correcting). The docked point: a
mis-assigned ambiguous wedge becomes unclaimed area, which is honest but shows
up as coverage left on the table, and no gate distinguishes "wedge was genuinely
ambiguous" from "family margin was mis-derived". Recorded, not blocking.

**A1 percolation is conditional, not constructive.** A's own load-bearing
sentence — a proxy comparison cannot percolate — is right, but the guarantee is
"cannot leak onto anything standing more than ε proud", and ε is 3σ_form. If σ
is next wrong *high* by 2×, ε = 0.3 mm absorbs 0402 components by A's own
absorption rule; wrong *low*, the board top under-claims and shatters. B's slab
cut has no such conditionality: no workable ε changes which slab a triangle's
centroid projects into. B's bar is met by B and only conditionally by A.

**A2's O = 3.** A's own author ranks it below A1 (Lloyd local-minimum risk on
85% clutter, no convergence guarantee), and B independently rejects VSA for
having no noise parameter. No expert advocates it as first choice. Rejected
with a shelf note: escalation only if the grower proves order-sensitive at
contested boundaries *and* HFP-over-regions doesn't cure it.

---

## 3. Rulings where the experts contradict

### 3.1 A's HFP agglomeration vs B's "datum cells make agglomeration unnecessary"

**Ruling: B, for the first shipment; A's HFP-over-regions is retained as a
named, conditional escalation.** The cross-cut's cells plus the existing support
floors handle first-order merge needs, and the house rule (every threshold
declared or derived) favours shipping no merge machinery until a measurement
shows over-segmentation: specifically, cells that individually fail support
floors but whose union passes a joint fit. If that census (emitted from PR 3's
first run) shows > a declared area fraction in such fragments, HFP over the
~500 regions (O(m²) ≈ free, threshold-free, cut licensed by the existing
parsimony-F gate — A's genuinely good idea) enters as a small follow-on. It is
the *cheapest* good idea in A's survey precisely because it works on regions,
not triangles, so deferring it costs nothing.

### 3.2 A's guided normal filtering vs B's smoothing rejection

**Ruling: B. The filter is out of the winning path entirely.** Three
independent grounds: (1) B's mechanism argument — a feature-preserving filter
preserves creases by *detecting* them with a normal/dihedral criterion, which is
the criterion the percolation proof just killed on this mesh; the smoother needs
the segmentation it is meant to enable. (2) A's own least-confident claim is
exactly this: Zheng/Zhang are validated on iid noise, and under correlated
waviness with kernel ≈ correlation length the range kernel can lock onto a
waviness crest and *sharpen a ripple into a crease* — the only failure mode on
the table that fabricates rather than misses. (3) C's finding that no
`derived_from` schema exists means any derived signal is currently
unrecordable. **What survives is A's discipline, adopted as doctrine
(KTD-5): wherever any filtered or derived signal ever appears, it produces
labels only; every fit, residual, covariance, and gate runs on original
vertices; the deriving operation's parameters are recorded.** The doctrine
binds future work (including HFP joint fits and any later filter revival); the
filter itself waits until a measured boundary-quality deficit licenses it.

### 3.3 A's "cans 3/3" vs C's "cylinders will mostly still refuse"

**Ruling: split the claim.** Cylinder *fits* on can and hole walls: plausible
accepts (A and B, with the §2.1 lateral-super-cell fix; span gate arithmetic
favours 180–300° visible arc over the 60° floor — A4 in §1.2). Hole/bore
*classification and emission*: C is right — open mesh, no `material_side`,
downstream refuses, and `delivered_area_fraction` stays 0.0 until the 2.5D
multi-loop lane lands (F10). The report must lead with that label so the
cross-cut's success is not misread, and this design deliberately does not touch
emission.

### 3.4 A's refusal-tally reading

**Ruling: corrected by measurement (F6).** 609 blocked-no-fit, not ~2,255. The
held-out power floor is still right (conflating disproved with underpowered is a
licence defect) and ships in shipment 1, but its expected yield is modest; the
σ fix carries the 1,598 ratio failures.

### 3.5 Sequencing: "relationships fix in the same cycle" 

**Ruling: stronger than the brief — the relationships rewrite must land
*before* the cross-cut, not merely in the same cycle.** The cross-cut is what
takes accepted fits from 443 toward 600–1,000+ (C projects 2,083 fits →
2.76 GB program.json under the current pair loop). Shipping the splitter first
would make its own decisive experiment emit a multi-GB artifact. PR 2 is
therefore the relationship rewrite, and it is independently measurable at
today's 443 fits (156.6 MB → < 0.5 MB).

---

## 4. The winning design

**C's region tree is the frame; B's cross-cut is the first splitter plugged
into it; A's proxy-distance criterion is the refinement inside cells and the
no-datum fallback; the Moran correlated-noise null and the relationships
equivalence-class rewrite ship in the same cycle.** The judge's incoming read
survives contact with the evidence, with the amendments in §3 (filter dropped,
HFP deferred, relationships promoted ahead of the splitter, lateral super-cell
fix).

### 4.1 Frame (C, adopted whole for the segmentation-relevant core)

Regions become a tree; terminal nodes are a **checked partition** of the mesh;
a node splits when its best fit is **rejected above the split floor** (never on
size); T1–T5 terminal rules; P1 (strict partition, asserted every level), P2
(strict decrease), P3 (floor), P4 (productivity — a split none of whose
children improves the parent's residual by a declared margin is
`split-unproductive`, capping useless work at one level). **[Superseded:
P4's existential form and the bare "rejected above the floor splits" trigger
are replaced by the reason-aware licence and aggregate productivity predicate
of §A.1; T1–T5 are defined there.]** Work bound: ≤ d_max
whole-mesh fitting passes regardless of splitter. Storage: one int32
permutation + node table; a region is `(offset, count)`. New flags join
`REGION_FLAGS` (`split-ineffective`, `split-unproductive`,
`split-depth-exhausted`, `region-fit-failed`); `REFUSAL_REASONS` stays reserved
for aborts. The regime verdict is already measured before segmentation
(`_stage_noise_scale`, F9), so `anchor` reads it rather than re-deriving it,
and the dispatch **degenerates into the containment rule**: GFG always runs (it
is free, 0.02 s measured); if its groups fit they are the partition whatever
the regime label says; a failing over-floor group is split whatever the regime
says. Tessellation corpus behaviour is unchanged (§6's normalized comparison;
the frontier empties at level 0). Coverage sums over terminal nodes only and **names its partition**
(`partition_checked`, `terminal_regions`, `triangles_in_terminal_regions`) —
C's flattering-direction risk is closed by one assert and one definition.

Determinism: every seeded choice inside a node derives from that node's
existing content-addressed `_region_hash`; numpy/BLAS build recorded in the
stage record (a reassociated reduction can flip a marginal accept and silently
miss the resume cache).

### 4.2 First splitter: the cross-cut (B, with the §2.1 fix)

Per node: `label_local` = connected components of the dual graph keeping edges
with |dihedral| < ε; `label_cell` = (normal-family, slab-station) per triangle
for the axial/planar families, and a single station-free `lateral` super-cell
for the four lateral families + ambiguous (§2.1 — a wall spans stations, so a
lateral cell that carried one would band it); region = `np.unique` over the
pair. The two label sources
fail in opposite directions (local leaks / cell merges) and share no failure
mode. Parameters: ε = quantile of the measured in-plane dihedral distribution
(from the 443 gate-accepted planes) at 1 − 1/L_max, L_max = measured perimeter
/ mean edge ≈ 1,230 — deliberately loose, percolation intended and neutralized
by the cell cut; family assignment threshold-free argmax with ambiguity band =
derived facet-noise tilt (1.76°); stations by 1-D KDE at bandwidth σ_form,
peaks separated by the declared `min_feature_size = 1.6`. **The station
detector is new code in PR 3, not a reuse.** The only station machinery in the
repo is `mesh_slabs.collect_event_candidates` / `merge_events` on the unmerged
2.5D lane (`feat/25d-events`), and it is a different question: it collects
stations from *accepted fits'* offsets and sigmas and merges them by complete
linkage, where the cross-cut needs peaks in a 1-D density over raw triangle
coordinates before any fit exists. `mesh_segmentation._structure_stations`
computes coordinates for residual analysis and locates no peaks. So PR 3 scopes
and tests a KDE peak finder of its own (~60 lines, included in its size
estimate below), and takes the sigma-derived merge tolerance from the 2.5D
lane's machinery only if that lane has landed by then. **No derived mesh; no constant
chosen.** Peel: accepted terminal regions leave the frontier; stations
re-estimated on the residual; **the same procedure every pass, no parameter
escalation** — which is also what keeps the loop off US11017535B2's
modified-procedure limitation (F12). Peel removes whole cells, not inlier sets
(B's fringe-confetti mitigation). Termination: monotone, bounded below,
expected 2–3 passes.

### 4.3 Bootstrap order and the no-datum fallback (A's role)

The cross-cut needs a datum. The measured bootstrap on this very part: pass 0 =
GFG confetti + existing fitters yields small accepted planes (443 here) →
datum recovery from their normal families (0.13°) → cross-cut passes 1..n. On
a part where pass 0 yields no accepted fits, the fallback ladder is: (1)
three-axis offset-histogram seeding on trimmed-PCA normals (A's measured-Hough,
~20 lines) to recover families directly; (2) if no orthogonal frame emerges,
named flag `segmentation-datum-unavailable` (renamed per §A.7; scope decision
in §A.5) and **A1's proxy region grower runs as the
standalone splitter** (layered frontier growth against the region's own fitted
proxy, refit on raw vertices every K layers) — order-independent of the
cross-cut because it plugs into the same `split(node)` socket. A's
proxy-distance criterion is also the designated **refinement splitter inside
cells**: a cell whose joint fit is rejected (two nearly-coplanar component tops
sharing a cell, adjacent within ε) re-splits by proxy growing seeded at the
cell's two worst-residual poles — deferred until PR 3's census shows it is
needed (§3.1 logic; same escalation discipline).

### 4.4 Gates in the same cycle: the Moran correlated-noise null (B §6.3)

F7 makes this non-optional: the residual-structure gate already rejects at
83 mm² on this part, and board faces are 66× larger. Fix: **block-bootstrap the
Moran null** at the waviness correlation length, and add an n-aware
practical-significance floor (structure must exceed a declared multiple of
σ_form, not merely be statistically nonzero at n = 10⁵).

**The correlation length is new code, and PR 4 owns it.** The σ_form lane
supplies amplitudes, not lengths: `_local_scale_estimates` returns the scalar
pair `(surface_scale, sigma_quadric)` and `_sigma_form` returns a ladder of
amplitudes against patch radius. Neither is a spatial correlation length, and
the repo has no estimator that is. So PR 4 scopes one explicitly — the
empirical semivariogram range of a region's own plane residuals over its mesh
graph, the length at which the variogram reaches its sill — with its own tests
against a synthetic correlated field of known length, and it declares that
length on the record beside the block size derived from it. **[Superseded:
"a region's own plane residuals" is circular — the candidate would calibrate
its own null. PR 4's estimator is respecified in §A.4: one frozen,
candidate-independent correlation record per scan, consumed by Moran,
held-out, covariance inflation, and relation uncertainty alike.]** Reading the σ_form
ladder as if it were a length is exactly the substitution this design refuses
elsewhere; taking a block size that nothing measured would put an undeclared
constant under the one gate the plan is loosening. Never by raising `moran_z_max`. Bootstrap
block size and replicate count are declared numbers with rationales. Held-out
and parsimony gates still run unchanged — the bootstrap loosens exactly one
null, in exactly the direction the physics says the iid assumption is false.

### 4.5 Relationships: equivalence classes + pruning census (B + C)

`parallel`/`coaxial`/`concentric`/`equal_radius` are equivalence relations on a
parameter: cluster, emit **one proposal per class with a member list**
(hub-and-spoke; 443 fits → ~14 records; `implied_pairs` recorded;
`pairs_unexamined: 0`). Non-transitivity at the 2° window is handled by
enumerating `contested_split`/`contested_join` in full (~30 pairs here, and
that number is measured in advance: 46,695 = C(306,2) + 30). `perpendicular`
becomes class-pairs. `symmetric` becomes clustered-candidate generation with a
joint statistic (plan-007 §8.3's own shape — the design knew; the
implementation enumerated). `tangent`/`distance` get a derived locality reach
(3σ̂ + both positional sigmas) over the existing uniform-grid choice, then
top-k with `worst_dropped_deviation` vs `best_adopted_deviation` recorded.
Dispositions use **C's two classes and they must never blur**: `not-omitted`
(lossless reduction, every pair's verdict reconstructible) vs `not-tested` (we
chose not to look; rule, derived parameter, and counts recorded). Coverage
cites the pruning census so silence cannot read as judgment. Record slimming
(license prose declared once; hash carried once; jsonl streaming for bulk) is
worth 60% independently. The codebase already argues the principle against
itself — `_symmetry_proposal` excludes sphere pairs for exactly this reason;
this applies the existing argument to the missing case.

### 4.6 Preprocessing discipline

`derived_from` schema (source id, parent digest, operation, operation-spec
hash, label-map hash, rationale; `provenance: "derived"`) ships **before any
derived mesh exists** (~15 lines of schema + validation), per C: the closed
`MESH_SOURCE_FIELDS` set means today's tempted path is "register it as a fresh
unlinked source", which is the evidence-chain hole. The decimator itself is
**not built** — decimation attacks the wrong noise scale for this failure
(B §5.3) and the other fixes already pay off its cost.

### 4.7 Prior-art notes (fold-in, per F12)

- **US11017535B2 (granted, live)** recites fit → remove → *modified
  segmentation procedure* on the residual → repeat. The cross-cut peel runs the
  identical procedure each pass with stations re-estimated from the residual —
  no procedure switch, no sensitivity escalation — and does not read on the
  distinguishing limitation. **PR 6 (RANSAC on the residual) is exactly the
  claim's shape** (different procedure on the residual after a first
  segmentation): route to the FTO owner before PR 6 is implemented.
  Mitigations on record: Design X `Preserve Existing Region` and Schnabel 2007
  fit-remove-repeat predate the 2016 priority date.
- **US20070285425A1** (abandoned) is 2D-section segmentation with constraint
  snapping, not 3D mesh auto-segment; `2026-08-19-008` treats it as the Design
  X Auto Segment lineage spec, which is wrong. The closest disclosure is
  **DE102007021711A1** (withdrawn). Doc correction is follow-up §11.1.

---

## 5. Shipment-1 conditioning (both branches, as charged)

Shipment 1 (`feat/scan-sigma-closure`: σ_form through ε and all gates,
held-out power floor, HK dead zone at feature scale, local closure licence,
report tee) re-runs the scan with existing GFG. What its result changes:

**Branch "moves a lot"** (coverage 0.039 → ~0.10–0.17; ceiling anchored by the
diagnostic run's permissive 16.78%): confirms A's §0 diagnosis for the small
regions. It cannot exceed that band, because ~79% of area sits in the
mega-group, which fails as a *two-parallel-planes* blob at any σ (F3) — **no σ
outcome removes the need for the splitter**. PRs 1–3 unchanged. PR 4's scope
depends on the Moran readout within this branch (below).

**Branch "barely moves"**: implicates the gates rather than σ — the held-out
ratio failures were not σ-starvation, and the Moran null is the standing
suspect. PRs 1–3 still unchanged (the splitter is need-driven by F3, not by
σ); PR 4 escalates to co-blocking and should be pulled forward to land with
PR 3, because otherwise the cross-cut's first run reports near-0 coverage and
the cause gets misattributed to segmentation (B's explicitly recorded warning).

**The single shipment-1 result that would most change this design** (as
charged): **the measured Moran z on the largest re-fitted regions — whether the
83.1 mm² / 31.4 mm² diagnostic planes flip to accepted under σ_form + the
AR-style n_eff inflation.** If they flip, the board faces have a fighting
chance under existing gates, PR 4 shrinks to a calibration pass, and coverage
credit lands in PR 3. If they still fail, the iid-null defect is confirmed
structural at exactly board-face scale, PR 4 is a hard prerequisite for any
coverage movement, and it merges with PR 3 into one cycle. Every other
shipment-1 number adjusts predictions; this one reorders the plan.

---

## 6. PR sequence

**[Ordering superseded 2026-08-20: the canonical cross-lane order lives in
`docs/reviews/2026-08-20-oracle-design-review.md` §2 (PR 0a/0b first); PR
contents below stand, amended per §A.1–§A.6.]**

One opus worker, one PR at a time, tree green after each, each PR names the
measured claim it must move and re-runs the Dig-Next-2 artifacts to prove it.
All paths under `plugins/agent-utilities/skills/fusion-parametric-design/`.

### PR 1 — region tree skeleton, partition invariant, record slimming

- **Files:** `src/fusion_design/mesh_segmentation.py` (node table, permutation,
  T1–T5, flags, dispatch record; `anchor` dispatching on the regime verdict
  `_stage_noise_scale` already stores, F9),
  `src/fusion_design/mesh_source.py` + schema (`derived_from`, ~15 lines),
  `reconstruction_coverage` consumer (partition citation), tests (+ the 60-line
  adversarial-splitter property check: k=1, child==parent, dropped triangle,
  double-assigned triangle).
- **Size:** ~550–650 added, ~150 deleted (index-list region records → ranges).
- **Splitter plugged:** trivial L0 = GFG groups (no new splitting yet; the
  mega-group becomes a terminal-unfitted node with its named gate, as today).
- **Measured claim:** tessellation corpus (11 parts, 71%) **semantically
  identical** fit/coverage results; `fit.json` 32.6 MB → ~1.5 MB; coverage
  record carries `partition_checked: true` naming its partition.
- **What the 32.6 MB actually is.** Two things hold it, and replacing only the
  first does not reach 1.5 MB: the per-region triangle-index lists, *and*
  `inlier_vertex_indices`, which every region also serializes and which
  `fit-regions` pretty-prints one integer per indented line — on a
  262k-vertex scan that field alone is megabytes. PR 1 compacts both: ranges
  plus a permutation for the triangles, and `inlier_vertex_indices` either
  dropped (no consumer in the repo — verified in the PR, with the grep
  recorded) or reduced to the same range form. If it turns out to have a
  consumer, the size gate is revised in the PR rather than the field kept and
  the number quietly missed.
- **The permutation lives inside the record, not in a file beside it.**
  `_cmd_fit_regions` emits exactly one JSON payload through one output path
  and supports stdout, where there is no directory to put a companion in. A
  separate file would also be unauthenticated: a stale or swapped one maps
  ranges onto the wrong triangles silently. So the permutation is a top-level
  array *in* `fit.json`, covered by the record's own digest like everything
  else in it, and `cli.py` needs no new output path — which is why it is
  absent from the file list below rather than forgotten from it.
- **The size gate is on the *compact* encoding, and PR 1 changes the encoding.**
  `_cmd_fit_regions` writes `json.dumps(..., indent=2)`, which puts every
  integer on its own indented line: a 524,614-entry permutation serializes to
  about 6.2 MB that way even as the identity, so an indented record cannot
  reach 1.5 MB whatever is in it. PR 1 therefore writes the two bulk arrays —
  the permutation and each region's range pair — on one line each
  (`separators=(",", ":")` for those values, the surrounding record still
  indented so it stays readable and reviewable in a diff), and the 1.5 MB gate
  is measured against that. If the compact encoding still misses it, the PR
  revises the number with the measurement rather than shipping past it.
- **The comparison this PR is gated on, stated exactly.** This PR replaces
  per-region index lists with `(offset, count)` ranges plus one permutation —
  which is where most of the 32.6 MB goes — so a byte comparison of
  `fit.json` must fail even when every verdict is unchanged, and demanding one
  would gate the PR on not doing the thing it exists to do. The gate is
  therefore: (a) `fit.json` and the coverage record compared *after*
  normalization — expand each region's range through the permutation back to a
  sorted index list, then compare the resulting structures — every region's
  triangle set, fitted kind, parameters, accept/reject verdict and reason, and
  every coverage fraction identical; (b) byte comparison retained, unchanged,
  for every artifact whose encoding this PR does not touch (`program.json`,
  `rebuild-*.json`, the dumps and their hashes). The normalizer is a test
  helper committed with the PR, not a hand comparison.
- **Risks:** record-schema churn breaking downstream readers (mitigated: same
  top-level vocabulary, ranges are additive); silent coverage drift (mitigated:
  the normalized corpus comparison above *is* the gate, and it is stricter than
  bytes on the numbers that matter — bytes would also have passed on a
  re-ordering that changed nothing and failed on one that changed nothing).

### PR 2 — relationships equivalence-class rewrite + pruning census

- **Files:** `src/fusion_design/mesh_fitting.py` (delete the pair loop
  `propose_design_intent` interior, ~180 lines; add clustering, class records,
  locality reach, symmetric candidate clustering),
  `src/fusion_design/reconstruction_program.py` (pruning census sibling, jsonl
  streaming, license-base/table record slimming, thresholds through
  `_declared_number`), tests.
- **Size:** ~500–650 added, ~300 deleted.
- **Measured claim:** on the existing 443-fit record, `program.json`
  156.6 MB → < 0.5 MB; proposals 104,014 → ~10³; `pairs_unexamined: 0` for
  every equivalence kind; contested lists enumerated in full (~30 expected);
  plan stage wall clock unchanged or better.
- **Risks:** non-transitive clustering choice hidden (mitigated: contested
  lists are the design's own honesty device); a downstream consumer of
  `relationships.proposals` appearing later (mitigated: verified none exists
  today, F8; jsonl retains full information).

### PR 3 — cross-cut splitter + peel

- **Pre-work, recorded in the PR's evidence with predictions on record:**
  (a) ε-sweep CC histogram (~10 lines over the existing dump; prediction: no ε
  yields a good histogram — falsifies or confirms the percolation proof);
  (b) mega-group sub-mesh GFG re-run (~20 min; prediction: one group again).
  A surprise in either cancels or reshapes this PR — that is the point.
- **Files:** `src/fusion_design/mesh_segmentation.py` (cross-cut
  `split(node)`: dual-graph CC at derived ε, argmax families with lateral
  super-cell, **a new 1-D KDE station peak finder** (§4.2 — the existing event
  helpers merge stations from accepted fits' offsets and answer a different
  question, so nothing here is a reuse), cell×CC intersect, peel driver;
  datum-bootstrap ladder incl. `segmentation-datum-unavailable`), spec block with every
  derivation, tests including the peak finder's own.
- **Size:** ~360–460 added (~60 of it the station detector).
- **Measured claim (gate-independent by design):** the 448,122-triangle group
  splits; board top and bottom emerge as two ~180k-triangle regions, each
  attracting a plane fit whose *offset difference recovers 1.6 ± 0.1 mm*
  (measurable even if acceptance is still gated); holes/cans isolated as whole
  walls (census of lateral regions); refusal census shifts from one blob gate
  to named per-region reasons. Segmentation wall clock ≤ ~10 s/full peel.
- **Risks:** Moran gate rejects the board faces and coverage stays near 0 —
  **expected, not a failure of this PR** (the claim above is region-level, and
  PR 4 exists precisely for this); warped-board station widening (degrades
  gracefully; KDE peak record shows it); cell explosion (measured census, not
  pre-solved).

### PR 4 — Moran correlated-noise null (block bootstrap)

- **Files:** `src/fusion_design/mesh_segmentation.py` — **not**
  `mesh_fitting.py`: `_moran_i`, the `moran_z_max` declaration and every
  residual-structure call site are in `mesh_segmentation.py`, and the bootstrap
  needs that module's topology and stage state (`topo`, `point_indices`,
  `_Topology.point_neighbours`) besides. Adds the semivariogram correlation-length
  estimator (§4.4), the block-bootstrap null over the mesh graph, the n-aware
  practical-significance floor, and declared `bootstrap_block_length` /
  `bootstrap_replicates` with rationales; `tests/test_mesh_segmentation.py`
  with a synthetic correlated-noise fixture of known correlation length.
- **Size:** ~250–350 added (the estimator is ~60 of it).
- **Sequencing switch:** lands after PR 3 by default; **merges into PR 3's
  cycle if shipment 1's readout shows the 83/31 mm² planes still failing**
  (§5). Never resolves by raising `moran_z_max`.
- **Measured claim:** `covered_area_fraction` 0.039 → **≥ 0.25** (C's
  conservative band 0.25–0.35; B's optimistic 60–85% recorded as the upper
  case), with each large-region verdict naming a physical reason; the
  83.1 mm²/31.4 mm² diagnostic planes' verdicts flip or their refusals name
  structure exceeding the physical floor.
- **Risks:** over-permissive null (mitigated: held-out + parsimony unchanged;
  bootstrap parameters declared and recorded); correlation length itself
  mis-estimated (mitigated: it comes from the same measured estimator lane as
  σ_form, and the gate records the length it used).

### PR 5 (conditional) — refinement inside cells: proxy grower, HFP merge

- **Escalation gate (declared, from PR 3/4's census):** run only if
  (a) mixed-cell area — cells whose joint fit fails with multi-surface residual
  signatures — exceeds a declared fraction, or (b) fragment area — adjacent
  cells individually under support floors whose union fits — exceeds one, or
  (c) **any part in the corpus reaches `segmentation-datum-unavailable`**. (a) licenses A's
  proxy grower inside cells; (b) licenses HFP-over-regions (threshold-free, cut
  by the existing parsimony-F gate); (c) licenses the same grower as the
  *standalone* splitter §4.3's fallback ladder requires — without it a
  no-datum scan has no splitter at all even after the whole plan is complete,
  and neither census above would ever fire on such a part, because a part with
  no datum never reaches the cell census.
- **Files:** `mesh_segmentation.py` (layered proxy grower as a second
  registered splitter; HFP merge pass over terminal regions), tests.
- **Size:** ~250–350 (grower) + ~90 (HFP).
- **Measured claim:** the specific census population that licensed it converts
  — +N accepted fits / +X% coverage in component geometry, numbers set by the
  census that triggered the PR.
- **Risks:** order-sensitivity at contested boundaries (recorded; A2 VSA is
  the named shelf escalation if measured); ε-band absorption of sub-0402
  features (declared absorption rule, reported).

### PR 6 (conditional) — Efficient RANSAC on the residual

- **Escalation gate:** post-PR-5 unclaimed area with fittable HK signatures
  (at the corrected h_κ = 1.5 mm dead zone from shipment 1) above a declared
  floor — i.e., evidence that non-axis-aligned or cone/torus surfaces exist
  that no deterministic stage can seed. **Plus FTO clearance on US11017535B2
  first (§4.7) — this PR, not the peel, is the one shaped like the claim.**
- **Files:** restore the deleted detection engine under `mesh_fitting.py` /
  `mesh_segmentation.py` with A3's four corrections (σ = σ_form; σ_θ-law
  neighbourhoods; β = min(2ℓ_med, declared `min_feature_height` = 0.35 mm);
  HK ranking at h_κ), seeded from region hashes.
- **Size:** ~600–800.
- **Measured claim:** +5–12% coverage; and — explicitly a good outcome —
  spurious candidates proposed *and gated*, exercising the disproof gates.
- **Risks:** re-litigates the deleted design (mitigated: falsifiable
  prediction required up front, per A); reproducible-under-seed rather than
  deterministic-by-construction (recorded as the weakest C4 in the pipeline).

Sequence rationale in one line each: PR 1 makes every later split *checkable*;
PR 2 must precede the fit-count explosion PR 3 causes (§3.5); PR 3 is the
splitter the mega-group's own fit record demands; PR 4 is what lets the
splitter's output through the gates honestly; PRs 5–6 spend effort only where a
measured residual licenses it.

---

## 7. Key technical decisions

- **KTD-1 — Region tree as the containing architecture; split on rejection,
  never size.** Rationale: a rejected fit above the floor is evidence of more
  than one surface; the partition invariant is the only thing that keeps
  `covered_area_fraction` meaningful under a hierarchy, and it fails in the
  flattering direction without the assert (C §8). Tessellation path unchanged
  by construction — verdict for verdict, under §6's normalized comparison.
- **KTD-2 — Cross-cut as first splitter.** Rationale: the only candidate whose
  discriminator survives σ being wrong again (empirical-quantile ε,
  threshold-free argmax, 21σ slab margin) and whose two label sources provably
  share no failure mode; ~300 lines, ~5 s, zero derived meshes. Includes the
  lateral super-cell correction (§2.1).
- **KTD-3 — Relationships as equivalence classes with a two-class pruning
  census (`not-omitted` / `not-tested`), landing before the splitter.**
  Rationale: it is a modelling error, not a scaling problem; top-k-first would
  silently drop evidence; the fit-count explosion PR 3 causes would otherwise
  emit multi-GB artifacts (§3.5).
- **KTD-4 — Moran null by block bootstrap at the measured correlation length;
  `moran_z_max` untouched.** Rationale: F7 shows the iid null already rejecting
  at 83 mm²; matching the null to the physics is a fix, raising the threshold
  is a rubber stamp.
- **KTD-5 — Labels-only doctrine for every derived signal; `derived_from`
  schema ships before any derived mesh; no smoothing, no decimation for this
  part.** Rationale: §3.2; C's schema-hole finding; coverage computed in
  parent area so derivation can never inflate it.
- **KTD-6 — Peel is procedure-invariant (same cross-cut every pass); RANSAC
  escalation is FTO-gated.** Rationale: US11017535B2 (F12).
- **KTD-7 — Every new threshold through `_declared_number` with rationale or
  derived from a measurement named in the record** (ε quantile + L_max, KDE
  bandwidth, bootstrap block length, escalation census floors,
  `min_feature_height`). Rationale: house rule; "a bare number is a module
  constant with extra steps."
- **KTD-8 — Determinism by content-addressed seeds** (`_region_hash`-derived
  per node; BLAS/numpy build recorded). Rationale: resume cache correctness
  and the house determinism rule.

## 8. Rejected / deferred register (so nobody re-proposes silently)

| item | status | licence to revisit |
| --- | --- | --- |
| Guided/bilateral normal filtering | rejected from path (§3.2) | measured boundary-quality deficit after PR 5, and only under KTD-5 |
| A2 vectorized VSA | rejected | measured grower order-sensitivity that HFP doesn't cure |
| Decimate-for-segmentation | rejected for Dig-Next-2 | a part whose failure is sampling noise, not form waviness; schema already in place |
| Multi-scale GFG on sub-mesh | run once as falsification (PR 3 pre-work) | a surprise result |
| Watershed on curvature, spectral/n-cut | rejected (κ is noise at this sampling; scale/objective mismatch) | — |
| HFP-over-regions | deferred (§3.1) | PR 5 gate (b) |
| RANSAC-on-residual | deferred | PR 6 gate + FTO clearance |
| Smoothing as mesh prep | rejected outright | — |

## 9. Verification contract

- Every PR re-runs the Dig-Next-2 artifact set host-side (`fit-regions` path —
  no Fusion required for PRs 1–6) and commits the measured numbers it claimed
  into its PR description; a claim without its number does not merge.
- PR 1's adversarial-splitter property check runs in the standard suite
  thereafter; any splitter registered later must pass it unmodified.
- Tessellation-corpus regression (11 parts) green on every PR; PR 1 identical
  under the normalized fit/coverage comparison defined in §6 (and byte-identical
  on every artifact whose encoding it does not change), later PRs
  identical-or-explained.
- The falsification experiments (ε-sweep, sub-mesh GFG) carry written
  predictions *before* they run; outcomes recorded either way.
- Coverage records must cite: their partition (KTD-1), the pruning census
  (KTD-3), and — until the 2.5D lane's PR 3 lands — the
  `delivered_area_fraction = 0.0` label with `reconstruction-refused` /
  `claims_not_made`, so covered-vs-delivered cannot be conflated (F10).
- One live-Fusion writer at a time is unaffected by PRs 1–6 (all host-side over
  the hash-bound dump); any later in-Fusion stage inherits plan-010's nonce
  discipline plus C's `.fusion.lock` when that work is scheduled.

## 10. Definition of done

1. PRs 1–4 merged; PRs 5–6 either merged under their census gates or their
   gates recorded as not met.
2. On Dig-Next-2: mega-group split into named terminal regions; board top and
   bottom fitted as planes with the 1.6 mm offset recovered inside its stated
   uncertainty; `covered_area_fraction ≥ 0.25` with every large-region verdict
   naming a physical reason; holes/cans present as regions with accept/refuse
   reasons from the declared gate set.
   **Whole-wall cylinder *acceptance* is explicitly not required on this
   capture.** The addendum measured why: this scan's bore walls are
   single-sided, so they fail the support floors and the axis-sigma gate
   honestly, and no segmentation or gate change in PRs 1–6 recovers evidence
   the capture does not contain. What is required here is that each such region
   exists as its own region and names that reason — not that it fits. Accepted
   whole-wall bore cylinders on this part need a re-capture, which is
   deliberately not scheduled in this plan (§11.5).
3. `program.json` under 1 MB at the new fit count; `pairs_unexamined = 0` for
   equivalence kinds; contested lists enumerated.
4. Tessellation corpus unchanged (71%, 85/85 bores).
5. Shipment-1 readout incorporated: the §5 branch taken is recorded in the
   PR 4 description, with the Moran-vs-area numbers that decided it.

## 11. Follow-ups (outside this design's PRs)

1. **Correct `docs/plans/2026-08-19-008-research-prior-art-landscape.md`:**
   US20070285425A1 is 2D-section segmentation, not 3D Auto Segment; the closest
   free disclosure is DE102007021711A1 (withdrawn). Small doc PR.
2. **FTO review of US11017535B2** before PR 6 (owner: whoever holds the FTO
   question; mitigating prior art listed in §4.7).
3. **`material_side` precondition audit** (from A §3.5): the mesh is globally
   oriented, manifold, 0.02% boundary edges; inward/outward for a fitted
   cylinder needs consistent winding, not closedness. If the audit agrees,
   loosening the precondition un-discards the three mounting holes at the
   emission step — but that lands in the 2.5D/emission lane, not here.
4. **Emission dependency:** scan `delivered_area_fraction` stays 0.0 until the
   2.5D multi-loop emitter lane's PR 3 lands; this design must not duplicate
   that scope and does not.
5. **Re-capture of Dig-Next-2 for the bores.** Measured in the addendum: the
   bore walls are captured single-sided, so the evidence for a full cylinder is
   not in the scan and no work in this design's PRs can put it there. A
   two-sided re-capture (or a second pass at a different presentation) is what
   unblocks accepted whole-wall bore cylinders on this part. Owner: whoever
   holds the scanner; not scheduled here, and §10.2 is conditioned on it.

---

## Addendum — shipment-1 readout, measured 2026-08-20

*Post-verdict measurement, appended after shipment 1 (PR #54,
`feat/scan-sigma-closure`) landed its numbers. §5 named this readout as the
pivot, so it is recorded here against the predictions it was scored on. The
scoring in §2 and the design in §4 are **not** rewritten: this section says
which branch the measurement selected and what it refuted.*

- **The σ-scale hypothesis is refuted.** σ_form *within* face groups measures
  **0.0032 mm** — below σ_dihedral, not above it. The 0.033–0.076 mm figure the
  panel reasoned from was patches straddling the un-segmented mega-group, i.e.
  a segmentation artifact read as a noise measurement. Expert A's two predicted
  consequences did not reproduce: the margin collapse (29.8 → ~3) did not
  happen and the saddle histogram did not disappear — **both identical to the
  digit**.
- **Coverage moved 3.88% → 11.23%** (accepted fits 443 → 1,718). The movement
  came from the per-region σ ladder and the held-out underpowered-vs-disproved
  skip, **not** from global σ. That is §5's "moves a lot" band by the number
  and its "implicates the gates rather than σ" cause by the mechanism.
- **The mega-group's 79% is invariant under all of it.** No σ treatment touched
  it. **The splitter is the sole binding constraint, exactly as F3 and §5
  predicted** — "no σ outcome removes the need for the splitter" is now
  measured rather than argued. PRs 1–3 stand unchanged.
- **The pivot condition resolved against the optimistic branch.** The z = 54 /
  z = 34 diagnostic planes did not demonstrably flip: residual-structure
  refusals moved 286 → 207, but **large-plane acceptance was not established**.
  By §5's own rule that is the "still fail" branch, so **PR 4 (Moran
  block-bootstrap null) is a hard co-requisite merged into PR 3's cycle**, not
  a calibration pass afterwards. §6's default sequencing switch is hereby
  taken; PR 3 does not ship its coverage claim without PR 4.
- **Bore recovery on this scan is capture-limited, not gate-limited.**
  Single-sided bore walls fail the support floors and the axis-σ gate honestly:
  the evidence for a full cylinder is not in the scan. No segmentation change
  and no gate change addresses that, so the Dig-Next-2 hole predictions in §4
  and §10 should be read as conditional on a re-capture, not as work this
  design's PRs can deliver.
- **σ_form stays shipped and load-bearing where it binds** — it binds on the
  desktop organiser, and the horn now reaches emission. Refuted as *this
  part's* explanation is not refuted as a mechanism.

---

## Amendment A — external-review incorporation (2026-08-20)

*Incorporates the accepted findings of the external design review preserved at
`docs/reviews/2026-08-20-oracle-design-review.md` (GPT-5.6 Sol, Pro tier,
verdict REVISE BEFORE IMPLEMENTATION). Findings 2, 3, 8, 9, 10 and 14 land
here; this amendment supersedes the specific passages it names and nothing
else. House rules apply throughout: verified facts carry sources, assumptions
are labelled, every new threshold is caller-declared through
`_declared_number` with a rationale, and every new token joins a closed set.
The PR ordering in §6 is subordinated to the canonical cross-lane order in the
review file §2 (see §A.8).*

### A.1 The split licence, made reason-aware (finding 2 — accepted)

§4.1's P4 ("a split none of whose children improves the parent's residual …
is `split-unproductive`") was an existential rule, and the review's confetti
scenario against it is not hypothetical: the 443 accepted ≤ 99-triangle planes
on Dig-Next-2 (F4) are the measured face of exactly this failure — locally
flat patches of surfaces no justified primitive explains, each passing plane
gates honestly. A splitter driven by "any child improved" would manufacture
more of them and call it coverage, contradicting 007's foundational rule that
unexplained geometry stays unclaimed rather than being absorbed. P4 is
replaced as follows.

**T1–T5, defined** (previously referenced, never written — missing decision
1, decided here):

- **T1 `terminal-accepted`** — the node's fit passed every gate. Terminal;
  claimed; leaves the frontier.
- **T2 `terminal-below-floor`** — support below the split floor (area or
  triangle count). Terminal, named. Never split: splitting cannot create
  evidence.
- **T3 `terminal-insufficient-evidence`** — the fit was rejected for an
  *information-class* reason (table below). Terminal without splitting; the
  rejection reason is carried on the node.
- **T4 `terminal-split-unproductive`** — a licensed split was attempted and
  failed the aggregate productivity predicate below. The parent remains the
  addressable terminal, with both the split attempt and the predicate's
  numbers recorded.
- **T5 `terminal-depth-exhausted`** — d_max reached. Terminal, named
  (`split-depth-exhausted` flag, unchanged).

**Which rejections license a split** (missing decision 2, decided here).
A rejected fit above the floor no longer licenses a split by itself; the
*reason* does:

| Rejection class | Examples (existing tokens) | Split? |
| --- | --- | --- |
| **mixed-support** — evidence of more than one surface | multimodal residual distribution, disconnected inlier support, incompatible normal families, multiple competing primitive candidates | licenses a split |
| **wrong-kind structure** | `residual-structure` (Moran), directional-bin structure | licenses a split **only when** the proposed children jointly explain ≥ `split_min_children_explained` of the parent's area under the predicate below |
| **insufficient-information** | support floors, `parameter-uncertainty`, span gates, capture boundary, `segmentation-datum-unavailable`, `correlation-model-unidentified` | terminates as T3 — splitting an information-starved region manufactures smaller information-starved regions |

This licence governs **every splitter entry point**, and the two paths that
look like exceptions are not splits of a T3 terminal: the standalone proxy
grower of §4.3/§A.5 is **scan-scoped** — when
`segmentation-datum-unavailable` fires no cross-cut exists, and the grower
*is* the splitter for the whole scan (the token names the scan's missing
datum, not a node's evidence class, so no node is simultaneously terminal
and splittable); and §A.3's mandatory proxy refinement runs on a
**joint-fit rejection over a mixed lateral cell**, which is the
mixed-support class (row 1) by definition. A node terminal as T3 is never
split by any path.

**The aggregate productive-split predicate** (missing decision 3, decided
here) replaces the existential rule. A split stands only when **all** of the
following hold, evaluated on **reserved validation triangles** — a blocked
subset of the node (block scale from the §A.4 correlation record; octree-cell
parity, the §10.3 idiom) reserved **when the node is created, before any fit
on the node runs** — neither the parent model, any child model, **nor
`split(node)` itself** sees the validation blocks: partition discovery
(cross-cut, station finder, proxy refinement) runs on the non-validation
subset only, and the reserved triangles are assigned to the chosen children
after the boundary is fixed, then scored. (1)–(2) therefore compare
held-out losses on both sides of a boundary the held-out data did not help
choose (a parent that was already fit on all triangles is refit on the
non-validation subset before grading), and the tree cannot search
partitions and then grade the winner on the evidence that chose it:

1. area-weighted mean child validation loss ≤ parent validation loss ×
   (1 − `split_min_loss_improvement`);
2. children whose own validation loss improves on the parent's carry ≥
   `split_min_improved_fraction` of the parent's area;
3. the **fractional** improvement in (1) — (parent validation loss −
   area-weighted mean child validation loss) / parent validation loss,
   dimensionless — exceeds `split_boundary_cost` × (new boundary length /
   the parent's boundary scale), where the boundary scale is the parent's
   boundary length or, when that length is zero, **sqrt(parent area)** — a
   closed connected surface has no boundary, sqrt(area) is its natural
   perimeter scale, and the root split of a watertight capture must be
   licensable. Both sides are dimensionless, so mesh units and part scale
   cannot flip the verdict; new boundaries are a model cost, paid for in
   measured improvement, never free;
4. the area-weighted mean in (1) is computed over **all** children — no
   child's loss may be dropped. Toward the improved fraction in (2) and the
   wrong-kind clause's explained fraction count: **T1 `terminal-accepted`**
   children, and children whose rejection falls in a **split-licensing
   class of the table** (mixed-support or wrong-kind) *and* whose own
   validation loss improves on the parent's — the table itself licenses
   those children for the next level, so counting them as zero progress
   would cap every tree at depth 1 and make d_max > 1 dead text.
   Insufficient-information and other terminal children are recorded with
   their class and contribute **zero**. The confetti guard survives because
   this credit is provisional to the tree walk, never to a claim: area is
   *claimed* only by T1 descendants, and a lineage that never reaches T1
   ends as named terminals with its provisional credit expired. (The
   earlier "any named terminal class" form was vacuous; a T1-only form
   over-corrects and breaks multi-level decomposition; this reading is the
   one the licence table itself makes consistent.)

A proposed child that receives **zero reserved validation triangles** —
possible because blocks are reserved before the partition and assigned only
after its boundary is fixed — is **ungradable, by name**: it enters (1) at
the parent's validation loss and counts as not-improved in (2), the
conservative substitution under which an ungradable child can never help
license a split, and the ungradable set is recorded on the split attempt.
A **node** whose own reserved validation set is empty (possible at the
block floor on tiny nodes) makes the ordinary predicate **ungradable as a
whole**: the parent validation loss is undefined, so the split attempt is
non-licensing, named as such on the record, and never graded on training
loss instead. The topology-licensed path below is unaffected — it grades
on topology, not loss.

**Topology-licensed splits.** When the licensing rejection is
*disconnected inlier support*, the split severs nothing on the mesh: the
children are the connected components of the parent's support, no new
surface boundary is created, and coplanar components can show no residual
improvement at all — grading that split on (1)–(3) would make the table's
own licence unreachable (T4 by construction, and an exact fit puts a zero
in condition 3's denominator). For that reason-class only, (1)–(3) are
replaced by: **every** child — terminal children included — corresponds to
an evidenced connected component of the parent's support (terminal status
affects only whether a child is claimed, never whether it must be a
component), the children partition the parent exactly, and each claimed
child passes its own gates — the split's productivity *is* the evidenced
separation, and the record names the reason-class that licensed it. A
fragmentation whose pieces are not the support's connected components is
not this split and takes the ordinary predicate. Because this path grades
on topology rather than held-out loss, it is **discovered on the full
parent** — the holdout restriction exists to protect loss grading and does
not apply here — and the exact-partition check runs on the full parent,
validation triangles included, so lineage stays exact. Triangles outside
every inlier component (outliers) attach deterministically to the
dual-graph-nearest component (quantized distance, ties by the 007 §2.3
idiom) and are enumerated on the record; a set with no adjacency to any
component forms one named residual child — every source triangle lands in
exactly one child.

New declared thresholds, each `{value, rationale}` through
`_declared_number`: `split_min_loss_improvement` (default 0.15 — below that,
the split explains noise re-partitioned, not structure), `split_min_improved_fraction`
(default 0.5 — a split justified by one flattering sliver while half the
parent stays unexplained is the confetti mechanism by construction),
`split_min_children_explained` (default 0.5, same rationale applied to the
wrong-kind class), `split_boundary_cost` (default 0.05 per unit boundary
ratio — small, but nonzero so boundary manufacture is never free),
`split_validation_fraction` (default 0.25 — enough blocked area to grade
against without starving the fit; blocked, not random, per §10.3's argument).
Defaults are declared starting points to be re-derived against the first
post-splitter census, and the record carries whichever value ran.

`REGION_FLAGS` grows the closed set: `terminal-insufficient-evidence`
(carrying the rejection token). `split-unproductive` keeps its name, now
meaning T4 under the aggregate predicate.

### A.2 Partition lineage and invalidation — a first-class contract (finding 3 — accepted; missing decision 8, decided)

This section is **shared infrastructure**: 004's `plan-decomposition`
(interface-split refinement) and 003's H audit consume it by reference —
design -004 §A.2 and the scoreboard cite this section and restate nothing.
The region tree gave partition identity; nothing yet said what happens to
evidence derived from a terminal that is later refined (fits, covariances,
held-out and Moran verdicts, relationships, datum contributions, coverage
claims, cached reconstruction decisions). The review's failure scenario — an
accepted board plane split into base + interface strips whose child inherits
a covariance computed over triangles it no longer contains — is exactly the
kind of silent semantic rot 010's hash chain does *not* prevent: hashes
protect artifact identity, not meaning after a partition mutation.

**The lineage model** (immutable):

```text
source_triangle_id
    -> partition_version
        -> terminal_region_id
            -> owner_id                    {base | thing-k | interface-j | residual}, assemblies only
                -> fit/plan/emission disposition
```

**The rules:**

1. Every partition mutation (split, interface-split, peel removal) creates a
   new `partition_version`, recorded in the stage record.
2. Every child carries its parent's id and its exact source-triangle subset
   (ranges over the permutation, as in PR 1).
3. A parent's fit is **never** inherited as an accepted child fit.
4. Every non-interface child is re-fit and re-gated under its own support.
5. Relationships, datum-frame contributions, and program claims computed
   against a replaced node are invalidated — marked
   `invalidated-by-partition` with the version that did it — and recomputed
   or dropped, never silently retained.
6. Every consumer (coverage, program, scoreboard, assignment record) cites
   the exact `partition_version` it consumed; a version mismatch is a
   refusal, the same shape as `dump-hash-mismatch`.
7. Inferred surfaces (virtual closure caps, inferred base footprints —
   design -004 §4.6) live in a separate **derived-geometry ledger** and never
   enter original-area conservation.

`invalidated-by-partition` joins the closed vocabulary. This contract is the
substrate that makes 003's H rule enforceable (silently-unclaimed = 0, exact,
by triangle identity — 003 §1.5 amended) and the precondition for 004's PR
C-4 (canonical order, review file §2, step 7). Missing decision 7 (where
decomposition sits relative to frame/relationships) is decided in design
-004 §A.2 *on top of* this contract: whatever ran earlier against a replaced
partition version is invalidated by rule 5, so the ordering question loses
its sting — it becomes a cost question, not a correctness one.

The same argument settles **PR 0b's records** (§A.6, which the canonical
order runs before the region tree and the peels): they are **provisional by
construction** — each cites the `partition_version` it ran against, rule 5
invalidates and recomputes them on every subsequent partition mutation, and
rule 6 means the scoreboard and every other consumer accept only records
citing the current version; a stale relationship is a version-mismatch
refusal, never silently consumed. Running the rewrite early therefore costs
recomputation, never correctness.

### A.3 Separation certificates on cross-cut boundaries (finding 8 — accepted)

§4.2's claim that the two label sources "share no failure mode" is true for
the axial/planar families and **false by construction for the lateral
super-cell**: the §2.1 fix deliberately removed station from lateral labels,
so lateral and ambiguous-family surfaces are protected only by the local
dihedral CC — a tangent plane/cylinder transition, adjacent cylinders joined
by a smooth fillet, or two vertical faces bridged by scan waviness can
percolate there with no cell barrier. Flush same-station surfaces and oblique
(45°) faces that fall into the ambiguity family are further shared-failure
cases. The measured PCB top/bottom split stands (station cells genuinely
separate those faces — survived-attack 3), but the design must say *which*
protection each boundary actually had:

- Every produced boundary records a **separation certificate**:
  `separation_basis ∈ {local, cell, both}`.
- `both` is strong; no further check.
- `cell`-only requires a joint-fit comparison across the boundary before the
  two sides may be claimed separately.
- `local`-only inside a lateral super-cell is **not percolation-protected**:
  when the containing cell's joint fit rejects, the proxy-distance refinement
  splitter (§4.3) **must** run there. This moves the proxy refinement for
  mixed lateral cells from PR 5's conditional census gate into the
  correctness path: it ships in the PR 3/4 cycle (canonical order step 5).
  PR 5's remaining scope (HFP merge, gate (b); standalone grower, gate (c))
  keeps its census gates.
- A child boundary with neither an observed crease nor a statistically
  decisive competing-model split cannot license separately *emitted*
  features; the two sides stay one claim with the certificate recorded.

### A.4 The correlation model, made non-circular (finding 9 — accepted; missing decisions 5 and 6, decided)

§4.4/PR 4 as written estimated the correlation length from **each candidate's
own residual semivariogram** — the candidate helping define its own null. The
failure is concrete: a bowed sheet fitted as a plane has a broad systematic
residual trend; the semivariogram reads that trend as a long correlation
length; large bootstrap blocks then normalize away the structure Moran exists
to reject. PR 4 is respecified:

- **One frozen, candidate-independent correlation record per scan (or per
  regime), from a preliminary calibration phase.** The calibration
  population is selected **without any correlation-sensitive gate**: small
  regions passing support floors and a raw residual-magnitude cut only —
  Moran, held-out and every other consumer of the record play no part in
  selecting it, so the record never conditions on the null it defines. (The
  443-plane population on this part is the measured face of what that
  selection yields — locally flat patches whose high-passed residuals are
  noise samples, the §2.1 self-correction argument, now load-bearing here.
  Their small extent bounds the *observable* range; where the sill is not
  reached within it, the record refuses rather than extrapolates — the
  `correlation-model-unidentified` outcome below — so small-patch selection
  can under-observe long-range structure but never silently understate it.)
  Directional empirical variograms; under anisotropy the **conservative
  maximum** range is used. The record `{range(s), sill, source-region ids,
  estimator params, hash}` is **frozen at the end of the calibration phase,
  before any candidate acceptance**, and cited by every consumer — the
  phase ordering is what makes PR 4 implementable on a new scan with no
  prior accepted population.
- **All four correlation-sensitive consumers read the same record** (decision
  6: yes, one length): (1) Moran bootstrap block size; (2) held-out block
  separation — the fixed ≈ 8 ℓ_med scale of 007 §10.3 is replaced by the
  measured range where a record exists (007 flags its own AR(1) inflation as
  approximate; this is the upgrade it anticipated); (3) covariance /
  effective-sample-size inflation (replacing the lag-1 AR(1) ρ̄ of 007 §7.3
  when the record exists); (4) relation and snap uncertainty through the
  inflated covariances. **[Amended 2026-08-21, §B.1: the consumers share the
  *record*, not one transformed statistic — each derives its own.]**
- **Deterministic block construction** (decision 5): blocks are the point
  sets of octree cells at the smallest level whose cell edge ≥ the recorded
  range; block resampling uses the stage RNG under the content-addressed
  seed (KTD-8); **the primitive is refit inside every bootstrap replicate**
  — otherwise the null excludes parameter-estimation effects and is too
  narrow.
- **`correlation-model-unidentified`** (new closed-set token): the variogram
  reaches no stable sill, or the source population is too small. The
  affected candidates terminate in the insufficient-information class (T3,
  §A.1) rather than being judged under a null the data cannot calibrate.

PR 4 remains merged into PR 3's cycle — the addendum's pivot already forced
that; this amendment changes what PR 4 builds, not when.

### A.5 Datum bootstrap: scope decided (finding 10 — accepted with modification; missing decision 4, decided/split)

**Decision: declared initial-domain limitation.** Orthogonal-datum scans are
the supported initial domain of PRs 1–4. A scan on which the bootstrap ladder
(§4.3) recovers no orthogonal frame terminates with the named refusal
**`segmentation-datum-unavailable`** (renamed from `datum-unavailable` — see
§A.7) and flows to the single-body path exactly as a refused segmentation
does today. PR 5 gate (c) stands unchanged as the designed escalation: the
first observed `segmentation-datum-unavailable` part licenses the standalone
proxy grower. Rationale, per review file §4.1: both measured fixtures are
strongly datum-oriented; a no-datum splitter shipped now would be unmeasured
code with no fixture to prove its claim against, violating §9's "a claim
without its number does not merge."

**Datum lifecycle contract** (the decided half of missing decision 4):

- The global datum is **frozen across peel passes**. Stations are
  re-estimated on the residual each pass (unchanged), and each pass's
  station set is versioned in the record beside the `partition_version` it
  produced — region identities must never depend on extraction order
  through an unversioned station drift.
- Datum acceptance floors, declared: ≥ 2 independent normal families
  separated by ≥ `datum_min_family_separation_deg` (default 45°, rationale:
  below that, "independent" families are one family with spread); family
  evidence spatial dispersion ≥ `datum_min_dispersion` (default 0.25 of
  extent, rationale: a datum built from one corner of the part is that
  corner's datum); winner–runner-up confidence margin follows 007 §9's
  z-margin idiom.
- **Open, owner seg PR 3:** contamination/background handling (pedestal or
  table planes dominating the object datum; scan-texture patches read as
  stable families). Registered, not silently missing.

### A.6 Relationships: PR 0b, class semantics, hard budgets (finding 14 — accepted with modification; missing decision 25, decided)

§3.5 already ordered the rewrite ahead of the splitter. The measured 2.13 GB
program artifact (v0.12.0 baseline, review prompt addendum) moves it earlier
still: **the rewrite is PR 0b in the canonical order** — before the
region-tree PR, whose gates re-run the Dig-Next-2 artifact set and would
otherwise re-materialize multi-GB programs on every check.

- **Class formation, named** (the §4.5 gap): equivalence classes form by
  **complete linkage** — every implied pair within the class deviates by
  less than the declared window, and the class record carries a
  maximum-pairwise-deviation certificate — or by a **joint shared-parameter
  fit** in which every member passes its own §8.4-style rollback gate.
  Union-find over pairwise "within tolerance" edges is banned (chaining
  makes implied pairs unreconstructible). Only under one of these two is
  `not-omitted` a valid disposition; anything else is `not-tested` or
  contested, exactly as §4.5's two classes demand.
- **Hard budgets, declared before allocation** (each `{value, rationale}`):
  `max_relationship_records` (default 20,000 — ~20× the expected ~10³
  post-rewrite class count, two orders below the measured 104,014
  pathology); `max_relationship_bytes` (default 50 MB serialized — jsonl
  streaming bounds peak memory but not artifact size, and 156.6 MB → 2.13 GB
  is the measured growth curve being cut); `max_planning_rss_mb` (default
  2,048 — the planning stage must run on the host that runs it today).
  Exceeding any budget refuses **`relationship-budget-exceeded`** (new
  closed-set token) *before* allocation, with the census of what would have
  been proposed. A budget refusal is a modelling-error signal, never a
  licence to fall back to the pair loop.

### A.7 Vocabulary renames applied (review collision table)

Normative from this amendment forward; existing artifacts carry the old keys
until the named PR migrates them, and the migration is recorded, not silent:

| Old (in this doc) | New | Migration |
| --- | --- | --- |
| `datum-unavailable` | `segmentation-datum-unavailable` | seg PR 3 (the token's birth PR) |
| `min_feature_size` as station peak separation (§4.2) | `min_station_separation` (initialized at the declared 1.6 mm, same rationale) | seg PR 3; `fit-spec.json` keeps `min_feature_size` for 007's resolvable-scale sense until 007's own rename lands |
| `unclaimed_components` (diagnostic population) | `unclaimed-surface-component` | first PR that touches the coverage record schema (PR 1) |

007's `min_feature_size` → `min_resolvable_surface_scale` and 004's
thing-support floor → `min_thing_support_extent` are those documents' rows;
see review file §3.

### A.8 Sequencing superseded [see also Amendment B]

§6's internal PR order (1 → 2 → 3+4 → conditional 5/6) is subordinated to the
canonical cross-lane order in `docs/reviews/2026-08-20-oracle-design-review.md`
§2: PR 0a (non-vacuity gate, emission lane) and PR 0b (§A.6) precede
everything here; the amended split licence (§A.1) is design-complete before
the region-tree skeleton lands; the lineage contract (§A.2) ships *inside*
the region-tree PR; cross-cut + correlation model remain one shipment with
§A.3's certificates and the lateral-cell proxy refinement. PR contents in §6
are otherwise unchanged.

---

## Amendment B — deep-research reconciliation incorporation (2026-08-21)

*Source: `docs/reviews/2026-08-21-deep-research-reconciliation.md` (findings
4 and 8; adoption 6; abandonment 7; the "threshold rationales are not yet
calibration" finding). §B.1 amends §A.4's decision 6 in place (marker
above); §B.2 defines the sweep protocol every topology-changing threshold
now cites. The canonical implementation order moves to that review file's
§3, which extends the 2026-08-20 file's §2 (§A.8 unchanged in substance).*

### B.1 One shared substrate, per-consumer derived statistics (finding 8, accepted with modification)

What stays: **one frozen, candidate-independent correlation record per scan
(or per regime)**, calibrated before any candidate acceptance — §A.4's
non-circularity property is load-bearing and untouched. What changes: the
record is a **measured substrate** (residual field over the calibration
population, directional range(s), sill, source-region ids, estimator
params, hash), not one transformed statistic that every consumer reads as
its answer. One correlation length is useful *input* to all of the
consumers; it is not their common *answer*:

- **held-out validation** derives the spatial separation sufficient to
  limit leakage (block scale ≥ the recorded range in the relevant
  direction);
- **the Moran bootstrap** derives its block *design* (octree-cell blocks at
  the recorded range, refit inside every replicate — §A.4's mechanics
  unchanged) and its own weight/null construction;
- **primitive-parameter covariance** derives effective-sample-size
  inflation through its own estimator over blocked variation in fitted
  parameters — not by scaling with a single global n/n_eff ratio (007
  §7.3's AR(1) inflation remains the fallback where no record exists,
  flagged approximate exactly as 007 already flags it);
- **relation and snap uncertainty** consume the inflated covariances of the
  specific parameter combinations they test (the §8.1 delta-method path),
  never a raw length.

Each consumer's derivation is recorded beside the verdict it produced,
citing the record's hash. No consumer's derived statistic is an input to
another consumer; only the frozen record is shared. Spatial effective
sample size is not one universal scalar, and the record refusing to reach a
sill (`correlation-model-unidentified`) still terminates the affected
candidates as T3 — unchanged.

The judgment record (review file §4.1) is explicit about one thing this
amendment does *not* concede: the review's motivating σ example (6–14×
under-estimate) was refuted to the digit by the shipment-1 readout
(addendum above). The consumer-separation argument is accepted on its own
merits, not on that example.

### B.2 Sensitivity sweeps — thresholds relabelled `experimental-default` (finding "rationales are not yet calibration", accepted)

A declared rationale is necessary but not sufficient for a value that
directly changes segmentation or program topology. Every such threshold —
§A.1's `split_min_loss_improvement`, `split_min_improved_fraction`,
`split_min_children_explained`, `split_boundary_cost`,
`split_validation_fraction`; §4.2's ε-quantile parameters and station
bandwidth choices; the selection-gate tolerances of design 2026-08-21-001
§6 — carries the label **`experimental-default`** in its
`_declared_number` record until the sweep protocol below has run, at which
point the label becomes `swept` with the sweep record's hash. The label is
reported wherever the value is; an `experimental-default` never silently
reads as a statistically licensed constant.

**The sweep protocol** (owned by the lane that owns the threshold; first
target: the §A.1 split-licence set, swept against the first post-splitter
census):

1. **Fixtures, three classes:** clean CAD tessellations (the committed
   benchmark four), synthetic noisy scans with known ground-truth regions
   (generated: known primitives + the measured correlation record's noise
   model), and ≥ 2 real scans with manually annotated major
   surfaces/features (Dig-Next-2 plus one more capture; the annotation is
   authored before the sweep, same independence rule as the C denominator).
2. **Sweep:** each threshold over a declared grid spanning at least
   [default/4, default×4] (log-spaced), others held at defaults; declared
   pairwise interactions (e.g. loss-improvement × improved-fraction) swept
   jointly on the reduced grid.
3. **Publish sensitivity curves** for: over-split rate and under-split rate
   against ground truth, feature recall (and precision, 003 Amendment §7),
   geometric coverage, and runtime — per fixture class.
4. **Re-derive or confirm** each default from the curves, with the chosen
   operating point's rationale recorded; flat curves are recorded as
   insensitivity (a finding, not a failure); cliff edges move the default
   away from the cliff by a declared margin.
5. The sweep record (grid, curves, chosen values, fixture hashes) is a
   committed artifact cited by every `swept` label.
