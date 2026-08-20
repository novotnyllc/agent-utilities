---
title: "design: 2.5D event decomposition and shell detection — past profile-ambiguous (issue #20)"
date: 2026-08-20
artifact_contract: ce-unified-plan/v1
artifact_readiness: design
execution: code
origin: https://github.com/novotnyllc/agent-utilities/issues/20
builds_on: docs/plans/2026-08-19-005-feat-mesh-parametric-reconstruction-plan.md, docs/plans/2026-08-19-006-design-u4-u5-feature-emission.md, docs/plans/2026-08-19-009-design-irregular-freeform-geometry.md, docs/plans/2026-08-19-010-design-fusion-native-architecture.md
---

# Summary

`profile-ambiguous` stops nine of the ten production parts at emission. The
cause is structural, not a bug: the planner builds **one** extrude between
**one** cap pair and sections it at **one** mid-station, and on a real part
that section closes 2–22 loops — pocket walls, bosses, ribs, nut pockets,
steps — of which only the loops matching planned holes are identified
(`_loops_cut_by_holes`, `mesh_rebuild.py:473`). Everything else refuses by
name, which is honest and useless: the tool plans well and builds nothing.

This design replaces the single-section premise with the standard 2.5D
decomposition, done in this codebase's own evidence discipline:

1. **Events** (A): the stations along the datum axis where the cross-section's
   topology can change are extracted from the accepted fits — every
   axis-normal plane contributes a measured station with its own fitted sigma —
   and merged by complete linkage at a tolerance *derived from those sigmas*.
   Between consecutive events the topology is constant, so one section
   characterises the slab, confirmed by sections at two more declared stations.
2. **Loops** (B): `section_mesh` gains per-segment triangle provenance, so
   every loop in a slab's section knows which mesh triangles — and therefore
   which fitted regions — its walls came from. Material side per loop is read
   from the mesh's own winding (the same evidence `material_side` already
   rests on), cross-checked against even-odd nesting parity, and a loop whose
   evidence is contradictory or unavailable refuses by name. Never guessed.
3. **Slabs** (C): each slab is one extrude — outer loops plus cavity loops as
   holes-in-profile plus islands — joined onto the stack, sketched on a
   construction plane per *event* (offset from the datum origin plane, so E3
   still binds), with station parameters as the edit surface. A one-slab part
   plans exactly what the current planner plans, so nothing regresses.
4. **Shells** (D): opposing region pairs at a constant offset t — anti-parallel
   plane pairs, coaxial cylinder pairs — with t consistent within combined
   fit uncertainty across the whole interior surface set become one
   `shellFeatures` step after the solid stack, thickness parameter-bound, and
   the interior regions leave the unclaimed set. Inconsistent t or partial
   interior coverage → no shell, by name, and the slab path still builds the
   cavity as profile holes, so the shell is an upgrade, never a dependency.
5. **Verification** (E): the editability proof gains station and thickness
   parameters with declared observables; coverage gains slab-claimed and
   shell-claimed buckets under the same lose-only arithmetic; the benchmark
   predictions below are stated to be falsified by the re-measure, and the
   parts this design still cannot build are named.

The one deliberate simplification, argued in C: slabs are **join-only**.
Deriving cut-vs-join from neighbour relations is a decision that can be wrong;
joining each slab's *measured* profile cannot be, because the profile is the
material at that station. Cuts remain what they are today — holes — because a
hole carries design intent (shared diameters, dimensioned placement) that
absence-in-a-profile does not.

# Verified facts (this repository, 2026-08-20, main @ 0ee1c02)

All paths below are under
`plugins/agent-utilities/skills/fusion-parametric-design/`.

- **V1.** `_single_closed` (`src/fusion_design/mesh_rebuild.py:422`) refuses
  `profile-ambiguous` whenever the mid-station section closes more than one
  loop not identified as a planned hole. `_loops_cut_by_holes` (`:473`)
  identifies a loop only by matching a hole archetype's declared centre and
  radius within `entity_match_tolerance_mm`. There is no other loop identity.
- **V2.** `section_mesh` (`src/fusion_design/mesh_fitting.py:450`) keys
  segment endpoints by topology (vertex index or edge pair) and knows, at
  `emit()` time, exactly which triangle produced each segment — but discards
  it. `SectionPolyline` carries only points and `closed`.
- **V3.** The fit record's regions carry `triangle_indices` in dump index
  space (`mesh_segmentation.py:2322`), `bounding_box`, `area`,
  `material_side` (null on every plane and on any unclosed/unoriented mesh),
  `orientation_gate`, per-parameter `uncertainty`
  (`FIT_UNCERTAINTY_KEYS`, `mesh_datum.py:97` — planes carry `normal_deg` and
  `offset` sigmas; cylinders `axis_direction_deg`, `axis_point`, `radius`),
  and `motion_moments`. `_station_range` (`reconstruction_program.py:1036`)
  already projects a region's box onto a datum axis.
- **V4.** The planner claims exactly one extrude (one cap pair,
  `_extrude_caps`, `reconstruction_program.py:935`) or one revolve;
  `_plan_holes` (`:1054`) requires exactly one base and containment within
  its single span; `_plan_fillets` (`:1206`) resolves same-feature edges only
  against that one extrude's `cap_regions` via `_same_feature_edge` (`:1168`)
  and the executor's `EDGE_FACE_SETS`/`_internal_edges`
  (`mesh_rebuild.py:101`, `:1970`).
- **V5.** The emitter already creates parameter-driven offset construction
  planes via `setByOffset(originPlane, ValueInput.createByString(parameter))`
  (`mesh_rebuild.py:2415`) and binds extents and radii by `createByString`.
  The executor's `_profile` (`:1887`) selects the **largest-area** profile of
  a sketch — correct for one loop, wrong for a multi-loop profile set.
- **V6.** `_ARCHETYPE_FIELDS` and `OPERATIONS` are closed sets
  (`reconstruction_program.py:2386`, `:2425`); `finish` was added for fillet
  precisely because overloading `cut` would assert an unestablished half.
  The precedent for growing both vocabularies with a version bump exists
  (plan 009 does it for `loft`/`sweep`).
- **V7.** Coverage is lose-only with a closed label set
  (`reconstruction_coverage.py:32`); the benchmark test asserts the current
  gates and **fails when a gate is fixed**, forcing a re-measure
  (`examples/reconstruction-benchmark/README.md`). The unicorn horn's
  "eight of twelve features inexpressible" is *derived* from
  `ARCHETYPE_KINDS`, so growing the vocabulary deliberately breaks that test.
- **V8.** The dump is millimetres with optional per-triangle face-group ids;
  region identity is a hash of dump triangle indices, stable across sessions.
  Host-side sectioning runs over raw dump vertices/triangles
  (`mesh_rebuild.py:604`), the same index space as V3's `triangle_indices`.

# Assumptions — labelled, each with its probe

- **S1. `Features.shellFeatures` exists and `ShellFeatureInput` accepts an
  `ObjectCollection` of faces to remove plus `insideThickness` as a
  `ValueInput`.** The API is documented and shipped in core Fusion (no
  extension entitlement is known to gate it), but this codebase has never
  called it — `grep -rn shellFeatures src/` is empty. Probe (first step of
  PR E): create a box, shell it with a `createByString` thickness bound to a
  user parameter, read back the feature's faces, perturb the parameter,
  recompute. Settles: existence, parameter binding, recompute behaviour, and
  which face collections the created feature exposes. Refusal designed in
  advance: `shell-capability`, naming the missing member.
- **S2. A `createByString` expression referencing *two* user parameters
  (`recon_station_2 - recon_station_1`) drives an extrude extent and stays
  live under parameter edits.** Single-parameter expressions are exercised
  (V5); compound arithmetic is Fusion-documented but unexercised here. Probe:
  same session as S1. Fallback (designed): per-slab depth parameters with the
  station chain expressed one way only — weaker sharing, recorded, no
  architecture change.
- **S3. One extrude accepts an `ObjectCollection` of several profiles from
  one sketch (outer loop + islands), and `sketch.profiles` enumerates a
  multi-loop sketch as: one profile per island, one profile for the
  outer-minus-holes region.** Documented Fusion behaviour; unexercised here.
  Probe: PR C's first live run. Ambiguity between candidate profiles refuses
  `profile-set-mismatch` (new token), never "take the largest" — `_profile`'s
  largest-area rule is retired for slab steps.
- **S4. Fusion's shell of the emitted solid reproduces the measured interior
  within the declared deviation thresholds.** Not assumed: `emit-mesh-deviation`
  grades it, and a shell whose result deviates refuses and replans without the
  shell (falling back to the profile-hole cavity the slab path already builds).

# A. Event stations from region spans

## What is an event

The cross-section's topology along the datum primary axis can change only
where a surface *bounds material along that axis* — and every such boundary on
a 2.5D part lies on an axis-normal plane: a cap, a pocket floor, a step face,
a boss top, a counterbore shoulder. Side surfaces (axis-parallel planes,
cylinders, cones) *end* at those same stations. So:

- **Event-defining evidence:** every accepted plane whose normal is within
  `angle_tolerance_deg` of the datum primary axis contributes one event at its
  fitted station (the plane's anchor projected onto the axis), carrying
  `sigma = region.uncertainty["offset"]`. Under the `uncertainty` tolerance
  basis a plane with no offset sigma refuses
  `fit-record-missing-uncertainty`, exactly as licensing already does.
- **Corroborating evidence:** each side region's axial interval
  `[lo, hi] = _station_range(frame, axis, region.bounding_box)` (exact for
  the datum-parallel surfaces admitted here, V3). Each endpoint should
  coincide with some plane event within the merge tolerance; an endpoint that
  matches none becomes its own event carrying the fit record's own measured
  noise sigma (`noise.sigma`, regime-selected, floored at
  `vertex_precision_rel` — the record's numbers, not a new constant). This is
  the honest fallback for a side wall that ends on a face the fitter never
  accepted: the boundary exists in the mesh even when its plane has no fit.

## Merge rule

Sort all events by station. Cluster by **complete linkage**: a station joins
the open cluster only while it lies within `event_merge_sigmas ×
sqrt(sigma_i² + sigma_first²)` of the cluster's *first* member — the same
anti-chaining argument already made for normal-direction merging in
`references/mesh-reconstruction.md`. The merged event's station is the
inverse-variance weighted mean of its members (fitted plane stations, with
their small sigmas, dominate bbox-derived corroborations); the record carries
every member, its source region, its sigma, and the weight.

`event_merge_sigmas` is the one caller-declared number here, a sigma multiple
with a rationale in the existing `sigma_multiple` style ("two stations closer
than their combined measurement uncertainty are one station; a slab thinner
than what the fits can resolve is not evidence of a slab"). The tolerance
itself is derived per pair from the fits' own sigmas — no millimetre constant
anywhere.

Fewer than two events (no axis-normal planes at all) refuses
`event-stations-absent`: a part with no caps along its own datum axis has no
2.5D structure to decompose, and the existing paths (revolve, or the
max-separation cap fallback) still apply upstream.

## Slabs and section stations

Consecutive events `e_k, e_{k+1}` bound slab `k`, height
`h_k = e_{k+1} - e_k` (> the merge resolution by construction). Each slab is
sectioned at its **midpoint** — maximally far from both boundary planes, the
same coplanar-triangle argument `_extrude_profile` already records — and, per
the constancy guard below, at two more declared fractions.

**Constancy guard.** One section is a sample, not a proof of the slab premise.
Each slab is additionally sectioned at declared fractions (doctrine default
0.25 and 0.75 of `h_k`, each recorded), and the three sections must agree:
same loop count, same per-loop classification, per-loop point-to-polyline
Hausdorff within `slab_constancy_tolerance_mm` (declared, rationale tied to
the classify tolerance). Disagreement refuses `slab-section-inconstant`
naming the slab and the measured disagreement — which is where a tapered wall
honestly lands until plan 009's rung 2a exists. This is the same shape as
009's extrusion confirmation, applied per slab.

**Coalescing.** An event both of whose adjacent slabs section to congruent
loop sets (entity lists agreeing within the same constancy tolerance) is
demoted to corroboration and the slabs merge. This absorbs a plane fit that
is real geometry but not a topology change (a flush boss top), and it is
recorded on the event rather than silently dropped.

## Complexity

R accepted regions → ≤ 2R+P endpoints; sort and merge O(R log R). Realistic
counts: the production parts carry ≤ ~600 accepted regions but only 3–10
distinct axis-normal plane stations, so 2–9 slabs. Sectioning is
3 × S × O(T): at ≤ 16,562 triangles and ≤ 10 slabs, well under a second in
stdlib host-side Python; if this stage later moves in-Fusion per plan 010,
the same arithmetic vectorises under numpy. No new complexity class anywhere.

# B. Loop classification by wall evidence

## Provenance: the wire that makes evidence possible

`section_mesh` is extended to record, per emitted segment, the dump triangle
index that produced it (the `emit()` calls already sit inside the per-triangle
loop, V2; a section segment lying *on* a shared edge records both incident
triangles; coplanar-boundary edges record their coplanar triangle).
`SectionPolyline` gains `triangles: tuple[int, ...]`, one entry per segment,
parallel to the point runs. This is additive: every current caller ignores it.

Two lookups then attach meaning:

- **triangle → region:** built from the fit record
  (`region["triangle_indices"]`, dump index space, V3/V8). Triangles in no
  region (the sub-four-point groups) map to nothing, and that absence is
  itself recorded per loop.
- **triangle → outward normal:** computed host-side from the dump's own
  vertices and winding. Licensed only when the dump is closed and
  consistently wound — established host-side by the manifold check (every
  edge shared by exactly two triangles) and a positive signed volume, the
  identical evidence `material_side` already rests on. On a mesh that fails
  it, every loop refuses `loop-orientation-unavailable` carrying the capture
  facts — the tropical-leaves stop, under a name that says what is missing.

## The evidence hierarchy — winding first, fits second

The key decision, made explicit because it moves the biggest risk in this
design: **a loop's material verdict comes from its own triangles' winding,
not from its wall regions' fits.** Fit coverage is 62–71% of area; a slab
section routinely crosses triangles of groups the fitters refused (nut-pocket
prisms, sub-four-point slivers). Winding needs no fit — every triangle of a
closed oriented mesh has an outward normal — so the classification does not
inherit the fitters' coverage ceiling. Fitted regions are consulted for
*identity* (is this cavity a planned hole? is this wall shell-paired?), never
for the material side.

Per segment: project the triangle's outward normal into the section plane;
compare with the loop's local inward direction (from the loop's signed area
and traversal order). The segment votes `material-inside-loop` when the
outward normal points out of the loop, `material-outside-loop` when it points
in. Votes are weighted by segment length. The loop's verdict requires at
least `loop_material_consensus_fraction` (declared; rationale: a couple of
sliver triangles at a blend crossing must not flip a verdict, and beyond a
small dissent the winding is telling us the section crossed a junction or a
degenerate feature) of its length agreeing; anything less refuses
`loop-material-contradictory` naming the loop, the dissenting arc length,
and the regions on each side of the disagreement.

## Nesting, parity, and the classification table

Loops at one station form a containment forest by 2D even-odd nesting
(point-in-polygon of one vertex of each loop against every other loop;
O(L²·n) at L ≤ 22, negligible). Depth 0 is outermost. Winding and parity must
agree — depth-even loops must measure material inside, depth-odd outside —
and disagreement refuses `loop-parity-contradiction` (the signature of a
section through a junction or a self-intersecting chain).

| Loop verdict | Evidence | Becomes |
| --- | --- | --- |
| **outer boundary** | depth even, material inside | a profile outer loop of this slab's extrude |
| **bore** | depth odd, material outside, wall triangles lie in one accepted inward cylinder (`material_side == "inside"`) matching a planned hole's declared centre and diameter within `entity_match_tolerance_mm` | excluded from the profile; the hole archetype cuts it (the existing `_loops_cut_by_holes` wire, now applied per slab) |
| **cavity** (pocket / slot / nut pocket / enclosure void cross-section) | depth odd, material outside, not hole-matched; **or** hole-matched but the walls are shell-claimed (D) | a hole-in-profile loop of this slab's extrude — unless shell-claimed, in which case dropped (the shell creates it) |
| **island / boss** | depth ≥ 2 even, material inside, nested in a cavity | an additional profile loop in the same sketch, part of the same extrude's profile set |
| **unattributed** | more than `loop_attribution_min_fraction` of the loop's length lies on triangles with *no consistent winding evidence* (degenerate/duplicated triangles) | the slab refuses `slab-wall-unattributed` |

Note what is *not* in the last row: triangles outside any fitted region do
not refuse — winding still classifies them, and the classify-polyline
residuals recorded on the profile entities are the measurement of their
geometry. This is how the 21 hexagonal M3 nut pockets — whose wall groups are
correctly *refused* as cylinders by `cylinder-normals-discrete` — finally
build: their loops classify as cavities and enter the profile as six line
entities each, with residuals on the record.

## The refusal ladder, in order

1. `loop-orientation-unavailable` — mesh not closed/oriented; nothing at this
   station can be classified. Carries the capture evidence.
2. `slab-wall-unattributed` — winding evidence itself is degenerate over more
   than the declared fraction of a loop.
3. `loop-material-contradictory` — winding disagrees with itself beyond the
   consensus fraction.
4. `loop-parity-contradiction` — winding disagrees with nesting parity.
5. `profile-ambiguous` — retained as the terminal token for a station whose
   loops classified but do not compose into one buildable profile set (e.g.
   two disjoint depth-0 outer loops: two solids at one station is real
   geometry this emitter still builds one body for — see C, multi-body is out
   of scope). Expected firings drop from nine parts of ten to the rare
   genuinely-2.5D-incompatible case, and the refusal detail now carries the
   full per-loop evidence table, so the next reader sees *why* instead of a
   loop count. **[Superseded 2026-08-20 for slab-stack programs: the
   overloaded token is replaced by the cause-specific set of Amendment §A.3
   (`slab-track-ambiguous`, `slab-stack-disconnected`,
   `slab-track-merge-unlicensed`, `multi-body-output-unlicensed`); a
   two-outer-loop station is a two-track station under §A.1, not an
   ambiguity.]**

Every refusal above stops the slab, the slab's regions go to unreconstructed
with the gate named, and `replan-without` composes as today.

## Composition with holes and fillets

- **Holes** (`_plan_holes`): the single-base requirement relaxes. A bore's
  containment is now judged against the union of slabs its axial interval
  crosses (same `offset_tolerance` arithmetic per slab boundary); its
  dependency set is every slab extrude it intersects, ordered after the last;
  its entry plane is unchanged (the station where the bore starts). The
  bore-matched loops at every crossed slab's station are excluded from those
  profiles — the existing wire, per slab. `hole-base-ambiguous` retires for
  the slab stack (the stack is one body built by named features);
  `hole-not-contained` keeps its meaning against the union span.
- **Fillets**: the two-owner path (`_shared_edges`) already works across slab
  extrudes — a pocket-floor-to-wall blend's neighbours now belong to two
  different slabs, which is the ordinary case, not the shared-owner case.
  The same-feature path (`_same_feature_edge`) generalises: each slab extrude
  carries its own `cap_regions` — the event-member plane regions bounding it —
  and the start/end/side role assignment reads the slab's own two events.
  `EDGE_FACE_SETS` and `_internal_edges` in the executor are unchanged.

# C. Slab → feature emission

## Planes, stations, parameters

One construction plane per **event**, not per slab, each an offset of the one
datum origin plane perpendicular to the primary axis — E3 binds exactly as
today, through the exercised `setByOffset`/`createByString` path (V5). The
edit surface is one user parameter per event: `recon_station_<k>` (mm,
comment naming the event's member regions and weights). Slab `k`'s extrude
extent is the expression `recon_station_<k+1> - recon_station_<k>` (S2;
fallback recorded). Editing one station moves that boundary and everything
that references it — a step height edit behaves like a step height edit —
and no depth is stored twice.

Deviation from 006 E4, argued: E4 requires every extent bound to *a named
user parameter*; a two-parameter expression is not one. The station model is
adopted anyway because the alternative — independent per-slab depths plus
per-slab plane offsets — stores each boundary twice and lets an edit tear
adjacent slabs apart, which is the un-parametric behaviour E4 exists to
prevent. The rule becomes: every extent is bound to a recorded expression
over named user parameters, and every number in the timeline still traces to
a parameter. U5 perturbs stations, not extents.

## Profiles and operations

Each slab is one sketch (on its lower event's plane) holding every classified
loop — outer, cavities-as-holes, islands — chained, constrained and
dimensioned per loop by the existing D3 ladder; inner loops anchor to the
sketch origin with the hole-placement dimension pattern. The executor gains a
**profile-set resolver** replacing `_profile`'s largest-area rule for slab
steps: enumerate `sketch.profiles`, match each planned loop by centroid and
area within `entity_match_tolerance_mm`, refuse `profile-set-mismatch` on any
zero-or-multiple match (S3), and hand the matched collection to one extrude.

**Operations are join-only.** Slab 0 is `new-body`; every subsequent slab is
`join`. The brief's cut-derivation rule (a slab whose section is a subset of
its neighbour's is a step; a material-outside loop present only here is a
pocket → cut) is adopted as *reporting*, not as emission: each slab records
`relation_to_below ∈ {first, same-outline, step-in, step-out, disjoint}` and
each cavity records the events that bound it (so the user knows which station
parameter is "this pocket's depth"), but no cut is emitted for them. Argued:
a cut presupposes a pre-cut solid nobody measured, and choosing which
neighbour is "the base" is a decision that can be wrong; joining each slab's
measured profile has no decision in it, and it composes with the deviation
verdict, which grades the union against the mesh regardless of how it was
assembled. The cost is real and stated: a pocket is not one named "pocket
feature" in the timeline. Its depth is still one parameter edit (its floor's
station), which is the editability that matters, and the report says which.

## Ordering, DAG, and the one-slab case

Total order: slabs ascending by station; then holes (each after the last slab
it cuts); then the shell (D); then fillets. All existing tie-breaks and the
`program-order-invalid`/`-cyclic` cross-checks apply unchanged; each slab
depends on its predecessor (join needs a body). **[Superseded 2026-08-20:
"each slab depends on its predecessor" was internally inconsistent with
`relation_to_below: disjoint` and is replaced by track-edge dependencies —
a slab joins its *track* predecessor, tracks may begin `new-body` at any
station, and temporary multiple bodies are the designed state; see
Amendment §A.1.]**

**Exactly two events → exactly one slab**, and the plan degenerates to
today's single extrude: same profile machinery, same cap semantics
(`cap_regions` = the two events' member planes), same hole containment
(single span), same fillet paths. The slab machinery is the generalisation
the current planner is the base case of, so the existing offline suite keeps
its meaning; byte-pinned examples are regenerated once for the schema
additions (below) and re-pinned, with the diff reviewed as part of PR B.

## Schema deltas

`PROGRAM_VERSION` → 2 (v1 refuses loudly; programs are derived artifacts and
replanning is one command). `sketch-extrude` archetypes gain an optional
`slab` block: `{index, lower_event, upper_event, relation_to_below,
constancy}` plus a `profile_loops` list (per-loop verdict, wall evidence
summary, classification residuals). The program header gains `events[]`
(station, sigma, members, weights) and `cavities[]` (bounding events, loops).
`_ARCHETYPE_FIELDS`, `_check_vocabulary`, and the emitter's validator extend
under the same `_reject_unknown_fields` discipline.

# D. Shell detection

## What is being claimed

An enclosure wall is two surfaces at a constant offset t. The claim "this
part is a shelled solid of thickness t" is earned by three measurements, all
from evidence the record already carries, and it fails closed at each:

1. **Opposing pairs.** For every accepted plane region, candidate partners
   are accepted planes with anti-parallel normals (angle within the licensing
   tolerance derived from the two fits' `normal_deg` sigmas ×
   `sigma_multiple` — the existing licensing arithmetic, reused), lateral
   footprint overlap of at least `shell_footprint_overlap_min` (declared;
   rationale: a left wall and a right wall are also anti-parallel and must
   not pair), and material *between* them (both outward normals point away
   from each other — winding evidence, same license as B). Each face pairs
   with its **nearest** qualified partner; `t = |station_a - station_b|`
   along the shared normal with
   `sigma_t = sqrt(sigma_offset_a² + sigma_offset_b²)`. For coaxial cylinder
   pairs (licensed coaxial by the existing machinery): outer material-side
   `"outside"`, inner `"inside"`, `t = r_outer - r_inner`,
   `sigma_t = sqrt(sigma_r_a² + sigma_r_b²)`.
2. **Inner/outer discrimination.** The pair is geometrically symmetric, so
   "inner" is measured, not inferred: from a point just off each face along
   its outward normal, cast a ray onward through the mesh (host-side, O(T)
   per ray, closed mesh required). The inner face's ray re-enters the mesh —
   its air is enclosed; the outer face's ray escapes. The hit distance also
   independently measures the cavity extent and is recorded.
3. **One t, everywhere.** Cluster the per-pair t values by complete linkage
   at `shell_thickness_sigmas × sigma_t(pair)` (declared multiple; per-pair
   tolerance derived from the fits). The shell hypothesis holds only when a
   single cluster covers **every** inner face found in step 2, plus interior
   blend regions explained by the offset relation (an interior round adjacent
   to two claimed inner faces whose radius equals its outer counterpart's
   radius minus t̂ within combined uncertainty). Any interior face outside
   the cluster refuses `shell-thickness-inconsistent` (naming the outliers
   and both t values); any interior region no pair or offset relation
   explains refuses `shell-interior-unexplained` (naming it). In both cases
   **no shell is emitted, the regions stay unclaimed**, and the slab path
   still builds the cavity as profile holes — the fail-closed outcome is the
   status quo, not a loss.

t̂ is the cluster's inverse-variance weighted mean, and becomes the one new
parameter `recon_shell_thickness`.

## Openings and emission order

Shell detection runs on the fit record **before** slab profiling; when a
shell is claimed, its interior regions are marked shell-claimed, and every
slab-station loop whose wall triangles lie in shell-claimed regions is
dropped from that slab's profile — the slabs plan the *outer solid*, exactly
as the part's designer did. The shell step then runs **after the full solid
stack** (Fusion's own modelling order) and before holes and fillets in the
DAG.

Openings: a cavity that reaches an event station with no interior floor or
ceiling covering its footprint there is open through that face. The shell
step's removed-face set is resolved in the executor from the adjacent slab's
own `endFaces`/`startFaces` (the exercised D5 pattern), matched geometrically
against the opening's station and footprint; zero or multiple matches refuse
`entity-resolution-ambiguous` as everywhere else. A cavity whose opening
cannot be identified refuses `shell-opening-unidentified` — a fully enclosed
void is *also* this refusal in v1, stated plainly: `shellFeatures` with no
removed face hollows a closed body, but verifying that outcome against the
mesh needs the deviation pass on internal surfaces nothing can see from
outside; deferring it is recorded in `unsupported.md` rather than attempted.

Holes through shell walls (connector ports): unchanged hole archetypes,
ordered after the shell; their containment is judged against the slab spans
as in B, and cutting through wall-plus-air is well-defined.

The archetype: `{id, kind: "shell", operation: "hollow", regions:
[shell-claimed hashes], thickness: {parameter, value: t̂, sigma}, pairs:
[...], open_faces: [{event, footprint}], dependencies: [every slab id]}`.
`ARCHETYPE_KINDS` += `shell`; `OPERATIONS` += `hollow` (the `finish`
precedent, V6: a shell removes material from a body this program built, and
calling it `cut` would overload a word with settled meaning).

API surface is assumption S1 with its probe; executor refusals
`shell-capability` / `shell-failed` quote Fusion verbatim per house style,
and S4's deviation grading is the final arbiter.

# E. Verification

## Editability

New perturbable parameters, each with declared observable, perturbation, and
rationale under the existing spec validator:

- `recon_station_<k>`: observable `volume` (adjacent slabs differ in
  cross-section by construction of the events — coalescing removed the equal
  case — so moving the boundary between them moves volume; the interior-vs-
  outermost distinction is recorded, outermost stations may declare `bbox`
  with direction). The CLI validator gains an arithmetic check the program
  makes possible: a station's declared perturbation must be smaller than half
  the smaller adjacent slab height, because inverting a slab is
  `parameter-broke-rebuild` by construction, not a finding.
- `recon_shell_thickness`: observable `volume`, declared direction (thicker
  wall → smaller cavity → larger solid volume).
- Hole and radius parameters: unchanged.

The proof loop, restore assertions, `checked` discipline, and report
bindings are untouched (006 D7).

## Coverage

`compose_coverage` gains two claim provenances under the same lose-only
arithmetic:

- **slab-claimed:** a region (fitted *or not*) whose axial interval is
  covered by built slabs and whose triangles appear in the loop attributions
  of every covering slab's section, carrying the constancy evidence. This is
  the mechanism by which honest coverage can exceed the fitters' 70.5% area
  ceiling: the section polylines are direct measurements, and their classify
  residuals are on the record.
- **shell-claimed:** the interior set a claimed shell explains.

A slab that refuses at emission subtracts every region it claimed, exactly as
a skipped fillet does today. Labels stay `parametric-full` /
`parametric-partial` / `reconstruction-refused`.

## Predicted benchmark outcomes — stated to be falsified

The benchmark test asserts gates, so these predictions are what the
re-measure will confirm or embarrass; per-part slab sectioning has not run,
and the loop-evidence pass rates below are the honest unknown.

Committed corpus (`examples/reconstruction-benchmark/`):

| part | today | predicted after this design |
| --- | --- | --- |
| honeycomb organiser | `frame-ambiguous` at plan | **unchanged** — structural (no distinguishable secondary datum); slabs are never reached. This design does not touch frame derivation. |
| unicorn horn | `frame-x-underdetermined`; 8 of 12 timeline features inexpressible | **unchanged as a build**; the derived census *changes*: the horn's timeline contains one shell, so `ARCHETYPE_KINDS` growth makes it 7 of 12 inexpressible, the known-gap test fails as designed, and the manifest is re-measured. Coil, sweeps, lofts, split, move stay out of vocabulary. |
| tropical leaves | `profile-ambiguous` at emission | refuses `loop-orientation-unavailable` — the same honest stop (winding inconsistent, `isOriented` false, signed volume 0.0), now naming the capture evidence that causes it instead of a loop count. |
| desktop organiser | emitted; 1 extrude, 27.6% planned | multi-slab plan; modest planned-area gain expected, small confidence — 17 of its 38 accepted fits are spheres this vocabulary still does not touch. |

The ten production parts (nine stopped `profile-ambiguous` today):

- **Predict 6–8 of 10 emit end-to-end as `parametric-partial`.** The blocking
  loops are pockets, bosses, ribs, steps and nut pockets — precisely the loop
  classes B classifies and C builds; the nut pockets on five parts build as
  hex profile holes despite their wall groups being (correctly) unaccepted.
- **Predict 2–4 of the enclosure bases/lids additionally claim a shell**,
  with wall thickness parameter-bound; where t is inconsistent (ribbed
  interiors, local bosses inside the cavity), the named shell refusals leave
  the cavity built as profile holes — still an emission, not a stop.
- **The two lids' internal revolve geometry still does not build**: turned
  features coaxial with an axis *other than* the frame's primary axis are
  neither slab-expressible nor claimable by the single-revolve path; their
  regions stay unreconstructed with `revolve-motion-unproven` or the
  neither-coaxial-nor-cap gate, and the lids emit as partials around them.
- **The coupon**: if its distinguishing geometry is embossed text or
  chamfered engagement features, those regions refuse (no archetype); the
  body around them should emit as one or two slabs. Prediction held loosely —
  this is the part the re-measure teaches us about.
- Parts whose sections cross genuinely non-2.5D geometry stop at
  `slab-section-inconstant` or the loop ladder — by name, with the evidence.

The horn's known-gap tests stay true; the one that derives from
`ARCHETYPE_KINDS` fails deliberately and is re-measured (V7), which is the
mechanism working, not breaking.

# Vocabulary, thresholds, and schema deltas (consolidated)

- `ENTITY_KINDS`: unchanged. `ARCHETYPE_KINDS` += `shell`; `OPERATIONS` +=
  `hollow`; `PROGRAM_VERSION` → 2.
- New planner refusals (closed set): `event-stations-absent`,
  `slab-section-inconstant`, `loop-orientation-unavailable`,
  `slab-wall-unattributed`, `loop-material-contradictory`,
  `loop-parity-contradiction`, `shell-thickness-inconsistent`,
  `shell-interior-unexplained`, `shell-opening-unidentified`. New transaction
  refusals: `shell-capability`, `shell-failed`, `profile-set-mismatch`.
  `profile-ambiguous` is retained as the terminal composition refusal;
  `hole-base-ambiguous` retires for slab-stack programs.
- New declared thresholds, each `{value, rationale}` under the existing
  validator: `event_merge_sigmas`, `slab_constancy_tolerance_mm` (+ the two
  extra station fractions), `loop_material_consensus_fraction`,
  `loop_attribution_min_fraction`, `shell_thickness_sigmas`,
  `shell_footprint_overlap_min`. Everything per-pair is derived from the
  fits' own sigmas; no new millimetre constants.
- House rules held: numpy in-Fusion only (this design's host-side additions
  are stdlib arithmetic over ≤17k-triangle dumps); `setByPlane` never
  appears (every plane is an offset of origin geometry, A/C); no process is
  started anywhere; every report asserts only what ran, with `checked` built
  append-after-success.

# Where this design deviates from plans 006 / 009 / 010

1. **006 D4/E1 (operation selection):** 006 derives join/cut from containment
   edges; this design emits join-only slabs and keeps cut for holes. Argued
   in C: joining measured profiles removes a decision rather than making one,
   and the deviation verdict grades the result identically. The neighbour
   relation the brief asks for is kept as recorded reporting.
2. **006 E4 (every extent bound to a named parameter):** slab extents bind to
   recorded expressions over station parameters instead. Argued in C: the
   station model stores each boundary once, which is the editability E4 is
   for; the doctrine text is amended, not weakened.
3. **006 D5/executor:** `_profile`'s largest-area selection is replaced for
   slab steps by plan-matched profile sets with an ambiguity refusal — the
   largest-area rule was itself a positional choice the rest of D5 bans.
4. **009 (program v2):** 009 reserved v2 for `spline`/`loft`/`sweep`. This
   design takes v2 first with `shell` + slab blocks; 009's additions become
   v3 or land together — coordination noted for whichever PR train runs
   first. No conflict of substance: the profile vocabulary is untouched here.
5. **010 (execution model):** nothing here moves the host/Fusion boundary.
   The additions are stage logic that runs wherever the stage runs today, and
   the two live-probe surfaces (S1–S3) are exactly the kind 010's M0 probe
   stage absorbs if the migration lands first. The shell ray-casts run
   host-side over the dump in stdlib; under 010's runtime they become
   `calculateCollisionsWithRay` or stay as-is — either satisfies the design.

# PR sequence — each lands green, each improves something measurable

**[Ordering note 2026-08-20: cross-lane sequencing defers to
`docs/reviews/2026-08-20-oracle-design-review.md` §2 — the slab-track graph
and virtual-closure contract (Amendment §A.1–§A.4) must land before design
-004's C3 per-thing parametric recursion; PR 0a's non-vacuity gate precedes
this lane's re-measures.]**

| PR | Content | Size | Measurable improvement |
| --- | --- | --- | --- |
| **1** | `section_mesh` per-segment triangle provenance; loop→region attribution and host-side winding/material helpers (manifold check, signed volume, per-loop verdicts); `profile-ambiguous` refusal detail upgraded to carry the per-loop evidence table. Synthetic-mesh tests for every verdict and every refusal in B's ladder. | M | The nine production-part refusals now *name* every loop's walls and material side — diagnosis without behaviour change. |
| **2** | Event extraction, merge, coalescing, slab planning, constancy guard; program v2 schema (events, slab blocks, station parameters); one-slab degeneracy asserted against the current planner's output; validator + `check_reconstruction_program` extensions; byte-pinned examples regenerated. Emitter still builds one-slab programs only, refusing multi-slab by version gate. | L | `plan-reconstruction` on the corpus shows slab decompositions and loop verdicts in the reviewable artifact; zero behaviour change at emission. |
| **3** | Emitter: shared event planes, station parameters, chained extents (S2 probe first), multi-loop sketches, profile-set resolver (S3), per-slab bore exclusion, DAG/order updates; live acceptance on one real part. | L | The headline: `profile-ambiguous` count on the ten production parts drops; first multi-slab part builds and survives U5. |
| **4** | Hole and fillet composition: union-span containment, per-slab loop exclusion, multi-slab dependencies, slab `cap_regions` for the same-feature fillet path. | M | Planned holes recover toward the fit record's 45; fillets on pocket edges emit. |
| **5** | Shell: S1 probe recorded first; pairing/clustering/inner-outer detection; shell archetype, `hollow`, executor step, deviation-gated fallback to profile-hole cavities; coverage `shell-claimed`. | M | Enclosure parts emit `shellFeatures` with parameter-bound thickness; interior regions leave unclaimed. |
| **6** | Editability (station + thickness perturbations, spec arithmetic checks), coverage `slab-claimed`, doctrine (`mesh-reconstruction.md`, `unsupported.md`), benchmark re-measure incl. the horn census change. | S–M | The re-measured corpus table with the new gates on record — the predictions in E confirmed or corrected in the manifest. |

PRs 1–2 are pure host-side and fully offline-tested; 3 and 5 each begin with
their live probe and carry the acceptance run; 4 and 6 are offline plus
re-measure.

# The three hardest risks, with mitigations

1. **Winding evidence quality on real dumps.** The whole loop ladder rests on
   closed, consistently wound meshes; a duplicated triangle, a T-junction, or
   a self-touching wall makes segments vote incoherently, and if that fires
   broadly the ladder refuses as many parts as `profile-ambiguous` does
   today. *Mitigation:* the evidence hierarchy already minimises exposure
   (no dependence on fit coverage); PR 1 lands the measurement **before**
   any behaviour change, so the per-part per-loop verdict rates on all ten
   production dumps are known numbers before PR 3 bets on them; the manifold
   check is per-edge, so a locally dirty mesh refuses locally (one slab)
   rather than globally where the dirt is confined to one station.
2. **Fusion's solver and profile enumeration on multi-loop sketches** (S2,
   S3). Chained-extent expressions, islands, and 20-loop sketches are
   unexercised; if profile enumeration is unstable or the solver fights
   multi-loop constraint schedules, `profile-set-mismatch` and the rejection
   budget become the common path. *Mitigation:* probe-first in PR 3 with a
   synthetic two-slab, three-loop part before any production dump; the
   fallback for S2 (per-slab depth parameters) is designed and recorded, not
   improvised; per-loop constraint budgets keep one bad loop from sinking a
   slab's whole schedule; and the replan loop degrades one slab at a time
   because each slab is its own archetype.
3. **Shell behaviour and the offset-geometry mismatch** (S1, S4). Fusion's
   shell may treat interior corners differently from the scanned part
   (sharp-vs-round mismatches at exactly the blends the offset relation
   tries to explain), making a correct t̂ produce a failing deviation grade.
   *Mitigation:* the shell is an upgrade with a designed fallback — refusal
   or deviation failure replans to the profile-hole cavity emission that PR 3
   already proved, so no part's outcome regresses below the pre-shell state;
   the S1 probe and one real enclosure's deviation grade are the first two
   commits of PR 5, so the reliability boundary is measured before the
   feature is claimed.

# Not achievable within this design, named

- **Multi-body stations** (two disjoint outer loops at one station):
  *represented* as slab tracks (Amendment §A.1) with temporary bodies;
  multi-body *delivery* remains a scope decision, refused
  `multi-body-output-unlicensed` (was `profile-ambiguous`; §A.3).
- **Fully enclosed voids** via shell: `shell-opening-unidentified` until the
  internal-surface deviation question is answered (D).
- **Tapered and lofted slabs**: `slab-section-inconstant` by measurement;
  plan 009's rungs 2a/2b are the designed home, and the constancy record is
  exactly the signal 009's loft detection consumes.
- **Side-entry pockets** (cavities whose axis is perpendicular to the datum
  primary axis): their walls are not slab-expressible on this axis; regions
  refuse with the existing neither-coaxial-nor-cap gate. A second
  decomposition axis is future work and is not smuggled in here.
- **Recovering the original feature list**: unchanged from 005 KTD9 — this
  recovers *a* parameterization consistent with the measured surface, and the
  join-only slab stack makes that explicit rather than pretending to know
  which pocket was a cut.

---

# Amendment A — external-review incorporation (2026-08-20)

*Incorporates review finding 5 (P1) and parts of finding 7 from
`docs/reviews/2026-08-20-oracle-design-review.md`, plus missing decisions 16,
17 and 18 (decided here). The measured trigger: five production parts refuse
`profile-ambiguous` with perfect loop-winding verdicts — not an orientation
failure, but discontinuous slab stacks forced into a whole-part fallback whose
section is multi-loop by construction, exactly the internal inconsistency the
review named: `relation_to_below` may be `disjoint`, yet every slab after the
first was `join` and depended on its predecessor because "join needs a body."
A disjoint slab cannot necessarily join its predecessor. Sections A.1–A.4
below supersede the passages they name; everything else in this design
stands.*

## A.1 The slab-track graph (finding 5; missing decision 16, decided)

The missing model is correspondence of material components **across** slabs;
per-slab verification at three stations never established it. Added:

- **Nodes:** connected material components within each slab's section (a
  slab may hold several).
- **Edges:** evidence-backed correspondence across adjacent events, licensed
  per edge kind. `continuation` edges require **footprint overlap across the
  event** — the persisting component's post-event footprint overlaps its
  pre-event footprint. Congruence is *not* required: an ordinary
  step-in/step-out changes the footprint of one persisting component and
  remains a continuation. Congruence stays what it always was — the
  within-slab constancy and coalescing test, where a fully congruent
  section is evidence the event is not topology-changing at all (§A.2).
  `branch` and `merge` edges are
  topology-changing by definition, so congruence with the pre-transition
  footprints cannot be required of them; they are licensed by
  **containment/overlap plus evidenced connectivity** instead: each
  pre-transition component's footprint overlaps the post-transition section,
  and that section shows the overlapped components connected (`merge`) or
  one component's footprint continuing as disjoint successors (`branch`).
  The U-shaped part's bridge slab is the motivating instance: its single
  connected component is congruent with neither track below it, but contains
  both footprints and connects them — a licensed `merge`, not a
  death-plus-birth.
- **Track states**, closed set: `birth`, `continuation`, `branch`, `merge`,
  `death`, `temporary-disconnection`.
- **A track may begin as `new-body` at any station**, not only slab 0. A
  U-shaped or bridged part legitimately runs two disjoint tracks at lower
  stations that merge later into one connected solid; a PCB's protrusions
  are born and die at different stations. Temporary multiple bodies are the
  designed representation of that interval.
- **Tracks join only when contact is evidenced** (the merging slab's section
  shows the components connected). An unevidenced join refuses
  `slab-track-merge-unlicensed`.
- **A track that never joins** is one of exactly three named outcomes: a
  true multi-body result (refused `multi-body-output-unlicensed` until a
  scope decision licenses multi-body delivery), a componentization candidate
  (handed to design -004's lane with its track evidence), or a
  cause-specific refusal from §A.3.
- **The whole-part fallback is removed.** No code path may substitute a
  whole-part section for a discontinuous stack; the five measured refusals
  become named track outcomes instead of a fallback's collateral.

The join-only doctrine survives *within a track*: each slab of a track joins
its **track** predecessor, not "the previous slab" globally. §C's dependency
rule ("each slab depends on its predecessor — join needs a body") is
superseded accordingly: dependencies follow track edges.

The slab record carries the graph into emission: `track_id` and
`track_predecessors` (a list serializing **every** incoming edge — empty at
`birth`, one element for `continuation` and for each `branch` successor,
one per merging track at `merge`) join the schema. §A.1's track states are
**transition facts recorded on the event records at their stations**
(§A.2's `topology-changing-event`), not a single per-slab enum — a
one-slab protrusion is born at its lower event and dies at its upper event
and both facts survive, each on its own event; a `temporary-disconnection`
likewise lives on the event records spanning the gap, where no slab exists
to carry it. §C's "slab 0 is `new-body`, every later slab `join`" is
superseded — the emitted operation derives from the slab's incoming edges:
no predecessor → `new-body`; one predecessor → `join` into the track's
body; several predecessors (a `merge`) → `join` of **all** evidenced-
contact predecessor bodies named in `track_predecessors`, which thereafter
share one track body; a `death` transition ends the track's dependencies at
its event. Across a `temporary-disconnection` the track **suspends**: no
operation is emitted for the gap stations, the track's body identity
persists, and the resuming slab depends on the track's last emitted slab
and joins the track body only when contact is evidenced at the resumption
section (the §A.1 merge rule applied to the track's own body) — otherwise
the resumption is a `birth` plus a later evidenced `merge`, or the
cause-specific refusal, never a silent bridge. Temporary multiple bodies
between `birth` and `merge` are the designed emission state, so the emitter
can encode every valid track graph the planner produces.

## A.2 Event states, separated; loop correspondence defined (finding 5 tail; missing decision 17, decided)

The interior-slab regression (measured, v0.12.0 addendum) shows "a plane
exists at this station" being allowed to become "the topology changes here."
Event records now carry one of three states, and only the third divides slab
tracks:

1. `candidate-geometry-station` — an accepted axis-normal plane exists here;
2. `corroborating-station` — side-region endpoints agree, or a coalesced
   flush-boss plane (the demotion in §A's coalescing rule maps here);
3. `topology-changing-event` — the section's track structure measurably
   differs across the station (loop count, component connectivity, or a
   track state transition from §A.1).

Coalescing congruent sections is evidence *against* topology change, never
sufficient evidence *for* it elsewhere.

**Loop correspondence across the three constancy sections** (0.25 / mid /
0.75): loops match by **complete linkage** on centroid distance and on
**√area difference** (|√A₁ − √A₂|), both within
`slab_constancy_tolerance_mm` — √area is length-dimensioned, so the one
declared length tolerance governs both comparisons and mesh units or part
scale cannot change the verdict (the declared threshold already in the
vocabulary — no new constant); an unmatched loop names itself
in the `slab-section-inconstant` refusal rather than failing the slab on a
bare count mismatch. Matching is a deterministic **one-to-one global
assignment**, not a greedy pair walk: among assignments of maximum
cardinality over the eligible (complete-linkage) pairs, take the one
minimizing total quantized centroid distance, remaining ties broken by loop
serial — so overlapping candidate pairs cannot select different
correspondences on different runs. Unmatched loops on either side drive the
track edges and the `slab-section-inconstant` decision deterministically.

## A.3 Cause-specific tokens replacing `profile-ambiguous`'s overload (review vocabulary table)

`profile-ambiguous` was carrying four meanings (multi-body station,
discontinuous stack, loop composition, whole-part fallback). New closed-set
planner refusals:

- `slab-track-ambiguous` — correspondence evidence supports more than one
  track graph; the candidates are enumerated.
- `slab-stack-disconnected` — a track dies with no evidenced continuation
  and no licensed outcome.
- `slab-track-merge-unlicensed` — §A.1's unevidenced join.
- `multi-body-output-unlicensed` — the track graph terminates in more than
  one body and multi-body delivery is out of scope.

**Scope and propagation:** `slab-track-ambiguous`,
`slab-stack-disconnected` and `slab-track-merge-unlicensed` are
**track-scoped** — they stop the affected track's slabs, whose regions go to
unreconstructed with the token named exactly as the refusal ladder demands,
while other tracks proceed. `multi-body-output-unlicensed` is
**delivery-scoped**: it refuses the *output*, never the evidence — the track
graph, the per-track slab programs and the correspondence evidence stay on
the record and are handed to design -004's componentization lane intact
(§A.1's second outcome); the affected regions still route to unreconstructed
with the token, but nothing §A.1 requires to remain addressable is erased.

`profile-ambiguous` **retires for slab-stack programs** (it survives only as
the terminal composition token on the degenerate one-slab path, where its
original meaning still holds). The B-ladder's item 5 and the "Not
achievable — multi-body stations" entry are superseded by these tokens: a
two-outer-loop station is now a two-track station, represented, and refused
only at delivery scope, with the right name.

## A.4 Open captures and cut-open sub-meshes (finding 7 interop; missing decision 18, decided)

The loop ladder's licence (closed, consistently wound, positive signed
volume) is unchanged — but two inputs now satisfy it by contract rather than
failing globally:

- **A thing sub-mesh cut off a base** (design -004's per-thing recursion)
  runs the ladder with the **virtual closure surface** of design -004 §4.6 in
  place: transient, evidence-class `inferred-by-contact` /
  `inferred-by-continuation`, used for topology/winding/section-closure/
  volume only, excluded from deviation grading and area conservation, its
  cap station entering §A.2 as a `candidate-geometry-station` with the cap's
  recorded uncertainty. The ladder never learns to "tolerate" open meshes;
  it receives closed ones whose closure is honestly labelled. Closure
  segments carry **no dump-triangle provenance** and are **excluded from the
  material-side consensus**; their winding is inherited from the licensed
  contact plane's normal as oriented by the interface record, labelled with
  the cap's evidence class — B's per-segment provenance tables list them
  under the derived-geometry ledger, never as source triangles, so they stay
  out of deviation grading and area conservation on every path.
- **Globally open captures** (boundary edges unrelated to any interface —
  Dig-Next-2's 158 edges, all 46 slabs `slab-section-open`): v1 policy is
  the hard refusal `capture-boundary-unclosed` (token shared with design
  -004 §4.6). A locally licensed closure procedure for capture boundaries is
  a registered follow-up in the emission lane, not attempted here.
  **Precedence:** the global open-capture check runs *before* the ladder's
  closure step — boundary edges unrelated to any licensed interface refuse
  `capture-boundary-unclosed` first, so a globally open capture can no
  longer reach `loop-orientation-unavailable` (which keeps its original
  meaning: orientation/winding failure on a mesh whose boundary is either
  empty or fully licensed). Design -004 and the scoreboard can rely on the
  shared token being the one actually emitted.
