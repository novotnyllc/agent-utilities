---
title: "The recognition scoreboard: mesh → parametric CAD, measured"
date: 2026-08-20
issue: 20
role: standing referee
status: baseline v1
sources:
  - "origin/main @ 0ee1c02"
  - "PR #48 feat/canonical-frame"
  - "PR #49/#51/#53 stack, head feat/25d-emitter (the current emission capability)"
  - "PR #54 feat/scan-sigma-closure (shipment 1, scan lane)"
  - "PR #52 / docs/plans/2026-08-20-002-design-scan-segmentation.md"
  - "docs/plans/2026-08-19-005, -006; 2026-08-20-001 (on feat/25d-emitter)"
  - "examples/reconstruction-benchmark/benchmark-manifest.json (25d head)"
  - "references/mesh-reconstruction.md (25d head and scan-sigma head)"
  - "Dig-Next-2 run artifacts (scratchpad run/build: coverage.json, fit-spec.json, classification.json, rebuild-refusal.json, fg-histogram.json, mesh-extract-report.json)"
---

# The recognition scoreboard

The owner's goal, verbatim: *"transforms into fully editable componentized
objects for as many recognized surfaces/shapes/things as possible."* This
document turns that sentence into a measured instrument. Every future change to
the program is scored against the vector defined in §1; §2 is today's baseline;
§3 ranks the backlog by the cells each lane moves; §4 names the measurement runs
the scoreboard still lacks.

House rules, applied throughout: **verified facts carry their source artifact;
assumptions are labelled; a number that would require a run that has not
happened is `unmeasured`, never estimated.** Two branch facts matter for every
number below and are stated once here:

- The **2.5D stack** (PRs #49 → #51 → #53, head `feat/25d-emitter`) contains
  PR #48 but **not** PR #54. PR #54 stands alone off main. No branch contains
  both the slab emitter and the scan-sigma fixes; **no combined measurement
  exists** (verified: `git branch --contains` / PR base chain).
- The committed benchmark manifest records the **no-dump v1 path**; the slab
  path on the benchmark is measured only in PR #53's corpus table. Re-recording
  the manifest on the slab path is 2.5D PR 6's declared job (PR #53 body).

---

## 1. The scoreboard, defined

Five cells per part, all computable from pipeline artifacts alone (fit record,
program, emission report, rebuild report, editability report, coverage
account). The vector is reported whole; no scalar is invented (§1.6).

### 1.1 Recognition coverage (RC) — the headline

**The fraction of the mesh's surface area claimed by an archetype that the
emitter accepted and scripted as a parameter-driven feature.**

Derivation, exactly: take the coverage account's `plan` stage
(`covered_area_fraction` over planned archetypes — each archetype carries its
claimed regions and their areas), then subtract every archetype the emission
stage refused or dropped (`profile-ambiguous`, `sketch-loop-budget-exceeded`,
skipped fillets, …). What remains is area standing behind an emitted feature
script. Call it **RC-emitted**.

Why this is the honest number and the two existing numbers are not:

- `covered_area_fraction` at the **fit** stage counts *accepted fits*. A fit is
  a measurement, not a feature: on Dig-Next-2 the fit stage claims 3.9–11.2%
  while the emitted feature set claims **zero** (coverage.json: fit 0.0388,
  plan 0.0021, emission refused). Fit-level coverage overstates recognition by
  construction and is kept on the scoreboard only as a diagnostic ceiling.
- `delivered_area_fraction` is the **goal** metric — plan coverage minus every
  archetype the *live build* did not deliver (coverage.json note, verbatim:
  "the fraction of the scan's surface area now standing as editable Fusion
  features"). But it requires a rebuild report from live Fusion, and **no slab
  build has ever run live** — so today it reads 0.0/`unmeasured` everywhere and
  cannot rank changes. RC-emitted is the strictest number computable host-side
  today; `delivered` is RC's live-verified counterpart and replaces it in the
  headline the day the §4 Run A exists. The lose-only arithmetic
  (each stage may lose area, never gain — mesh-reconstruction.md,
  "Partial reconstruction") guarantees RC-emitted ≥ delivered, so RC-emitted is
  an upper bound on the goal metric, and is reported with that label.

### 1.2 Vocabulary score (V)

**Features recognized by kind ÷ features evident, per part.**

- Where STEP/F3D ground truth exists (honeycomb, unicorn horn): the denominator
  is the ground-truth census (the manifest's `feature_kinds` for the F3D; the
  face-kind table for the STEP). Both numerator and denominator are counted by
  *kind instance* (e.g. horn: 3 ExtrudeFeature + 1 FilletFeature expressible of
  12 solid features — manifest `f3d_ground_truth`).
- For scan/production parts with no CAD ground truth: the denominator is the
  documented evident-features table (production corpus: **85 full-turn bores,
  21 hex nut pockets, 114 fillet candidates, per-part extrude stacks** —
  references/mesh-reconstruction.md; Dig-Next-2: board slab, 3 mounting holes,
  can cylinders — design 2026-08-20-002 §1/§3.3 and PR #54 body). Where no such
  table exists for a part, V is `unmeasured`, and writing the table is the
  measurement.
- Correct *refusal* of a kind outside the vocabulary (leaves' organic surfaces,
  the horn's NURBS) does not score in V; it scores in H (§1.5). Claiming a kind
  the ground truth contradicts (the six honeycomb "cylinders", pre-#48) is a
  **negative** entry, listed by name.

### 1.3 Editability (E)

**Parameters proven to drive ÷ parameters emitted**, under the U5 perturbation
standard exactly as declared (plan 005 R11; design 006 E10/D7): per parameter —
baseline, perturb by the declared amount, recompute, declared observable
(volume/centroid/bbox) moves ≥ `min_observable_change`, restore, observable
returns within `observable_restore_epsilon`; `parameter-inert` is a failure,
`designType` is never evidence. Report `interactions_exercised` beside the
ratio — it is `false` by construction in U5 v1 (design 006 D7), and stays on
the scoreboard so the coupled-parameter lane has a cell to move.

A probe is not a proof: PR #53's S2 probe (a two-station `createByString`
extent recomputing live under a parameter edit) licenses the design, but E
counts only parameters exercised by an `emit-mesh-editability` report.

### 1.4 Componentization (C)

**Fusion components emitted with placement transforms ÷ distinct physical
things evident in the input.** Achieved over target, the same direction as
every other cell — the first draft had it inverted, which made the stated
`C = 0` baseline a division by zero and scored ten things collapsed into one
component as 10 rather than 0.1. Two cases are named rather than computed:
**no components emitted → `C = 0`** (the state below, and the reason the cell
reads 0 rather than undefined), and **an unmeasured denominator →
`C = unmeasured`**, never 0 and never 1 — a part with no evident-things census
has no cell, which is exactly Dig-Next-2's position today. Over-emission
(a ratio above 1: more components than things) is a failure of this cell and
is reported by name — `things-over-partitioned` — not as a score above 1.
Today the emitter builds one dedicated component holding one body per part,
with no occurrence transforms — **C = 0 emitted everywhere; one body per part
is the current ceiling** (design 006 §model;
verified: no component/occurrence emission exists in any emitter path). For a
single-object STL the denominator is 1 and the cell is trivially satisfiable by
the current ceiling *once the emitter declares it*; the cell bites on scans of
assemblies — Dig-Next-2 is a PCB assembly (board + soldered components; exact
census `unmeasured`, no evident-things table exists yet). No lane currently in
flight moves this cell (§3.7).

### 1.5 Honesty margin (H)

**Refused-by-name area vs silently-unclaimed area.** The second must stay ~0:
every unit of area not claimed by an emitted feature must appear in a named
list with a gate token (`unreconstructed` + gate, `unfitted_regions`,
`unclaimed_components`, refusal detail). Structurally this holds by
construction (closed refusal vocabularies, lose-only coverage arithmetic), and
Dig-Next-2 spot-checks clean (2,605 unfitted regions + 1,041 unclaimed
components, all enumerated — coverage.json). The formal check is an area-
conservation audit — Σ(claimed) + Σ(named-unclaimed) = total mesh area per
part — which **does not exist as a script today** (§4 Run D). One known
candidate for silence: the 839 of 1,908 corpus face groups carrying fewer than
four points, stated in prose (mesh-reconstruction.md) but not audited into the
per-part accounts.

### 1.6 No scalar; a headline ordering

A single weighted scalar would let a vocabulary win paper over a silent-area
regression. The scoreboard is the vector. For ranking work, cells are ordered:

**RC first** (it is the goal sentence made measurable: area standing as
editable features), then **V** (the "as many recognized things" clause — RC can
rise while everything is one extrude; V is what says the *things* were
recognized), then **E** (editable is the adjective; an inert parameter fails
the sentence), then **C** (componentized is the other adjective; today's
uniform zero makes it a poor ranker until any lane can move it), with **H** as
a guardrail rather than a rank: any change that grows silent area is rejected
regardless of its other deltas.

---

## 2. Baseline, 2026-08-20

Sources per row are the branch stated; `unmeasured` means the artifact that
would carry the number does not exist. **Delivered (live) column is the goal
metric and is 0.0-or-unmeasured on every row** — no reconstruction of any
corpus part has ever been built in live Fusion (benchmark README: "No part in
this corpus reaches a built reconstruction"; no `emit-mesh-editability` or
slab rebuild report exists in any branch or the run artifacts).

### 2.1 The eleven production STLs (dumps not committed; numbers from PR #48/#51/#53 bodies and references/mesh-reconstruction.md on the 2.5D head)

Aggregate, fit level (post-#48, pre-slab measurement basis): 1,069 regions
offered, **650 accepted, 282 cylinders, 74 planned holes, 85/85 full-turn bores
accepted, 71.2% area-weighted fit coverage, 11/11 parts reach a plan.**

Emission, slab path (PR #53 corpus table — the current capability head):

| part | slabs | multi-loop sketches | holes | emitted? |
| --- | ---: | ---: | ---: | --- |
| FIT-COUPON-01 | 8 | 4 | 4 | yes |
| POD-A1-BASE | 7 | 6 | 6 | yes |
| POD-A1-LID | 5 | 5 | 12 | yes |
| POD-A1-TERMINAL-SHIELD | 1 | 0 | 0 | yes |
| POD-A2-BASE | 7 | 6 | 4 | yes |
| POD-A2-LID | 3 | 3 | 0 | yes |
| POD-B-BASE | 7 | 6 | 6 | yes |
| POD-B-LID | 4 | 2 | 12 | yes |
| POD-C-BASE | 8 | 7 | 6 | yes |
| POD-C-DIGUNO-TRAY | 1 | 0 | 4 | yes |
| POD-C-LID | 3 | 3 | 20 | yes |

Scoreboard row (aggregate):

| cell | value | source / why |
| --- | --- | --- |
| RC-emitted | **unmeasured** (bounded above by 71.2% fit-level) | all 11 emit (PR #53), but per-part *area fractions* at the emission stage were never published, and the dumps are not committed, so the number cannot be recomputed from the repository. §4 Run E-prod. |
| delivered (live) | **unmeasured** | no slab build has ever run live |
| V | holes 74 planned of 85 evident bores (87%); prisms: 21/21 hex nut pockets correctly refused as cylinders; fillets **2 planned of 114 candidates** (3 → 2 on the slab path, PR #51 finding 4); extrudes: slab stacks per table; revolve/shell/chamfer/pattern: 0 (shell and revolve unassigned; chamfer/pattern not in vocabulary) | mesh-reconstruction.md; PR #51/#53 |
| E | **0 proven / parameters emitted per part `unmeasured`** (counts live in the emitted scripts, not in any published table); `interactions_exercised: false` | no U5 report exists for any part |
| C | **0** — 0 components emitted (1 body/part ceiling) over a denominator of 1 each, these being single objects: a measured 0, unlike the assembly row below | §1.4 |
| H | all refusals named (tropical-leaves-style silent loss not observed; every gate token closed-set); area-conservation audit `unmeasured` | §1.5 |

### 2.2 The four benchmark parts (committed, replayable; manifest on the 2.5D head = post-#48 v1 path)

| part | fit accepted / coverage | plan coverage | emission (v1, committed) | emission (slab path, PR #53) | V vs ground truth |
| --- | --- | ---: | --- | --- | --- |
| honeycomb organiser | 39 planes / 41.6% | 33.5% | refused `profile-ambiguous` (11 loops) | **emits**: 5 slabs, 4 multi-loop sketches, 0 holes (hex pockets correctly cavities, not bores) | STEP = 145 planes, 4 normal families, **0 curved faces**: 39 planes matched to all 4 families at ≤1.1e-05 mm; **0 false curved primitives claimed** (was 6 pre-#48) |
| desktop organiser | 38 / 27.9% | 27.6% | **emitted** (1 sketch-extrude) — RC-emitted **27.6%**, the only committed nonzero RC in the program | emits, 1 slab | no ground truth; evident-features table `unmeasured` |
| tropical leaves | 31 / 18.3% | 5.7% | refused `profile-ambiguous` | still refuses — all 8 slabs `slab-section-inconstant`, 0.70–4.71 mm measured | organic; correct refusal → scores in H, not V |
| unicorn horn | 9 / 4.7% | — (plan refuses `frame-x-underdetermined`) | never reaches emission | same | F3D truth: 12 solid features — 3 extrude + 1 fillet expressible, **8 inexpressible by the closed vocabulary** (1 coil, 2 sweeps, 2 lofts, 1 shell, 1 split, 1 move); V = **0/12 recognized** |

On PR #54's branch (scan lane only, no slabs): leaves 31 → **49** accepted,
horn 9 → **23** and now plans a `hole` and reaches emission, desktop 38 → 45,
honeycomb byte-identical (manifest `re_measured` notes, PR #54 body). These
gains are fit-level; RC-emitted moves on no benchmark part from #54 alone.

Scoreboard cells common to all four: delivered `unmeasured` (never built
live); E = 0 proven; C = 0; H clean — every stop carries a named gate, and the
two "refuse" parts are the honesty exemplar (the leaves' 8 slabs refuse with
the measured disagreement, not silently).

### 2.3 Dig-Next-2 (Revopoint scan of a PCB assembly, 524,614 triangles, sha256 72aeeb2a…, not committed; artifacts in the scratchpad run + PR #54 body)

| cell | baseline (main, run artifacts) | PR #54 branch | source |
| --- | --- | --- | --- |
| fit coverage (diagnostic ceiling) | 0.0388, 443 accepted (all planes, all ≤ 99 triangles) | **0.1123, 1,718 accepted** | coverage.json; PR #54 |
| RC-emitted | **0.0** — plan claims 0.21% (one sketch-extrude), emission refuses `profile-ambiguous` (15 loops, 0 matched to holes) | still 0.0 — emission still refused; the blocker moved from `material_side` to cylinder support-floor (32×) and axis-uncertainty (14×) refusals: capture geometry, not σ | rebuild-refusal.json; PR #54 body |
| delivered | 0.0 (`reconstruction-refused`: "Nothing was built") | 0.0 | coverage.json |
| V | 0 of the evident set (board slab, 3 mounting holes, can cylinders): **0 cylinders accepted either side of #54** | same; 94/98 curved regions now carry a `material_side` | design -002 §3.3; PR #54 |
| E | 0 / 0 (nothing emitted) | same | — |
| C | **`unmeasured`** — 0 components emitted, and the input is an assembly whose distinct-things census does not exist, so the denominator is unmeasured and the cell is too (§1.4's named case; not 0, which would claim a measured denominator) | same | §1.4 |
| H | clean: 2,605 unfitted + 1,041 unclaimed components + 3,023 unreconstructed, all enumerated with gates; refusal census re-tallied in design -002 F6 | 609 blocked-no-fit refusals became **518 named skips** — an H improvement (underpowered ≠ disproved) | coverage.json; PR #54 |

The 78.97%-of-area mega-group (448,122 triangles: the board's two faces plus
edge band, plane rejected at relative residual 0.0484 vs 0.02 — design -002
F2/F3) is untouched by #54 and is the single largest unclaimed named region in
the program. PR #54's measured 0.1123 lands inside design -002 §5's "moves a
lot" branch (predicted 0.10–0.17), whose stated consequence is: **neither
outcome removes the need for the splitter; scan-seg PRs 1–3 unchanged.**

### 2.4 The headline gaps, restated as scoreboard facts

1. Slab-built parts have **never been live-rebuilt**; `delivered` is
   unmeasured on all 16 parts. 2. Deviation has **never been graded on a slab
   build** (PR #50's live acceptance is a synthetic 20×20×10 block). 3. E is
   0-proven everywhere; the only committed editability artifact is the
   acceptance *checklist*. 4. C is 0 everywhere and no lane moves it. 5. Scan
   recognition is fit-level ~11% with RC-emitted still 0.

---

## 3. The backlog, ranked by scoreboard delta

Ranking key: which cells move, how far, on what evidence, and what the lane
*cannot* move. Deltas are labelled estimates only where a measured predictor
exists; otherwise the lane's value is stated as the cell it unlocks.

### 3.1 Live rebuild + grade of the eleven (measurement run, then fix loop) — **first**

- **Moves:** `delivered` from unmeasured → real on 11 parts (the goal metric
  gets its first non-benchmark value); E from 0 → per-part proven counts; the
  deviation verdict onto real slab builds.
- **Evidence:** all 11 emit host-side (PR #53); S2/S3 live probes passed;
  loop-budget probe shows the densest sketch (51 loops) draws in ~1.5 s. The
  risk this run retires is exactly the program's biggest unknown: whether the
  slab emitter's output *builds, recomputes under perturbation, and matches the
  scan*. Every later ranking assumes an answer to this.
- **Cannot move:** V (no new kinds), C, scan RC.
- This is §4 Run A; it is a measurement first, but history says the first live
  run finds defects (the plate-as-revolve, S3's enumeration model), so budget a
  fix loop behind it.

### 3.2 Scan-seg PRs 1–4 (region tree, relationships rewrite, cross-cut splitter, Moran block-bootstrap null) — **second**

- **Moves:** Dig-Next-2 fit coverage from 0.1123 toward the board's own area —
  the mega-group alone is ~79% of surface area, board faces ≈ 11,054 of
  16,102 mm² (F2/F3); with the splitter separating the two board faces and the
  correlated-noise null letting a board-scale plane through a gate that
  currently bites two orders of magnitude below board-face area (F7: accept
  boundary z ≈ 16–20, board face extrapolates z ≈ 440 under the iid null),
  fit coverage plausibly moves by tens of points — labelled **estimate**,
  anchored on F2/F3/F7, settled by §4 Run C. V moves for cans/holes only if
  the span-gate arithmetic holds (A4, unverified). PR 2 also removes the
  156.6 MB relationships artifact (F8) that currently makes every scan re-run
  operationally hostile.
- **Cannot move:** RC-emitted on its own — emission on this part is the 2.5D
  lane's scope (F10, ruled explicitly in design -002 §3.3): `delivered stays
  0.0 until the 2.5D multi-loop lane lands` *and* the mesh's 158 boundary
  edges are handled (open mesh → no hole emission, ever — the doctrine's own
  rule). Ranked second on the size of the fit-level unlock and because RC on
  scans is composite: it needs this lane *and* 3.4.
- Sub-ordering within the lane is the design's own (PR 1 → 2 → 3 → 4; 5–6
  conditional on the census, FTO gate before PR 6).

### 3.3 2.5D PR 4 — hole/fillet composition across the stack — **third**

- **Moves:** V's fillet row from **2/114** toward the fit record's candidates
  (the measured regression 3 → 2 on the slab path is the lane's own baseline,
  PR #51 finding 4/PR #53); hole containment across union spans protects the 74.
  Some RC-emitted (fillet area is small; holes already emit).
- **Evidence:** 114 candidates already carry accepted-neighbour evidence;
  the blocker is named (`cap_regions` resolves against one slab).
- **Cannot move:** scan cells, C, E-proven (that is Run A's).

### 3.4 Merge the two measurement bases + Dig-Next-2 re-run (integration, cheap) — **fourth, and a precondition the branches hide**

- No branch holds #53's emitter and #54's scan fixes together (§0). Until they
  merge, "current capability" is a superposition and every scan-side RC claim
  is untestable. **Moves:** nothing by itself; unlocks the composite RC path on
  scans (#54's material_side + slab multi-loop emission + local winding
  licence is exactly the chain rebuild-refusal.json names). Then §4 Run C
  re-measures Dig-Next-2 on the merged head. Cheap: both PRs are open and
  stacked on the same issue.

### 3.5 2.5D PR 5 (shell) and PR 6 (station/thickness editability + benchmark re-measure) — **fifth**

- **Moves:** V (shell is the first new kind since hole; POD lids/bases are
  enclosure parts and the horn's ground truth carries a ShellFeature); E's
  denominator quality (station + thickness parameters are the design-intent
  parameters, and PR 6's perturbation specs are what Run A's editability spec
  will exercise); the committed benchmark manifest onto the slab path (the
  scoreboard's only fully-replayable RC-emitted numbers).
- **Evidence:** design 2026-08-20-001 §D; S1 (shellFeatures) is still an
  unprobed assumption — probe first, as the design orders.
- **Cannot move:** scan fit coverage; C.

### 3.6 Sweep / loft / coil emitters — **sixth**

- **Moves:** V and RC on exactly the parts the vocabulary excludes *by
  construction*: horn 8/12 features inexpressible, 43% of graded faces NURBS
  ("unreachable by construction rather than by a threshold" — manifest);
  leaves' taper is `slab-section-inconstant` until lofts exist (the refusal
  message is the feature request). Largest V ceiling-raiser in the program.
- **Ranked below the others** because every earlier lane moves cells on parts
  users are actually feeding the pipeline (production enclosures, scans), the
  cost is a new archetype family end-to-end (fit → plan → emit → U5 → refusal
  vocabulary), and no design doc exists yet — it enters as a design lane, not
  an implementation one.
- **Cannot move:** scan cells (the horn is a tessellation; Dig-Next-2's
  blockers are segmentation and capture geometry).

### 3.7 Componentization — **unranked as implementation; ranked as design work**

No lane in flight moves C, the goal sentence's second adjective. Nothing can be
ranked against evidence because no design exists: what is a "distinct thing" in
a scan (the cross-cut's datum cells? connected components after board
subtraction?), what transform evidence licenses an occurrence, what U5 means
for a placement. **Action:** a design doc with an evident-things census for
Dig-Next-2 is the entry ticket; until then C stays a uniform, honest 0 on the
board rather than a pretended lane.

### 3.8 Coupled-parameter editability (interactions_exercised) — **last**

Moves one flag on E from `false` → measured, at n² recomputes per part. The
design already scopes it as a straightforward v2 of the U5 loop (design 006
follow-ups). Worthless until Run A gives E a nonzero numerator; cheap
afterwards.

---

## 4. Measurement runs the scoreboard needs and does not have

**Run A — live rebuild + U5 + deviation on the eleven (and the benchmark
four).** Procedure: live Fusion session, version recorded; per part:
`emit-mesh-capture` → `emit-mesh-face-groups` → `emit-mesh-extract` (fresh
hash-bound dumps — the PR-era dumps are not committed); host-side `fit-regions`
→ `plan-reconstruction --dump` with declared `slab_evidence`; `emit-mesh-rebuild`
into a clean document; author per-part editability specs (observable +
perturbation + rationale per parameter, design 006 D7 arithmetic rules);
`emit-mesh-editability`; `emit-mesh-deviation` against the immutable source;
`reconstruction-coverage` last — its `delivered_area_fraction`, E ratio, and
deviation verdict are the scoreboard entries. Cost: one exclusive Fusion
session; planning is ~6 min for the corpus (PR #51), drawing ~1.5 s per dense
sketch (PR #53), deviation ~0.2 s per synthetic run but unmeasured at corpus
size; the human cost is authoring ~15 editability specs. Estimate half a day of
wall-clock, dominated by spec authorship and the first-failure loop.

**Run B — benchmark slab-path re-measure (host-side, no Fusion).** The four
dumps are committed; run `fit-regions` → `plan-reconstruction --dump` →
emission per part on the 2.5D head and record RC-emitted per part into the
manifest with `re_measured` notes. This is 2.5D PR 6's declared job; as a
measurement it is runnable today. Cost: minutes of compute, an hour of
recording. This is the **cheapest unmeasured RC number in the program**.

**Run C — Dig-Next-2 re-run on the merged head (post-#54 + post-#53, and again
post-splitter).** Same host-side chain against the retained dump
(`dig_next_2_stl-72aeeb2aed8f.meshdump`, scratchpad run/dumps). Record: fit
coverage, RC-emitted, the mega-group's fate, hole emission given 158 boundary
edges (expect: still refused — open mesh — unless the local-winding licence
covers the hole regions; the run decides). Cost: minutes host-side; no Fusion
needed until something emits. Re-run after scan-seg PR 3 lands (the design's
own decisive experiment, §6).

**Run D — area-conservation audit (honesty).** A ~50-line host-side script
over any coverage account. **Per stage, and partitioned by region identity
before summing** — the lists are not disjoint across stages and a naive
Σ(claimed) + Σ(every named list) over-counts and reports a false honesty
failure: a region whose fit was rejected is named twice, once by
`reconstruction_coverage._fit_stage` in `unfitted_regions` and again by
`plan_archetypes`, which walks every region and puts the same one in
`unreconstructed` under its rejection text. So: **fit stage** — Σ(area of
regions with an accepted fit) + Σ(`unfitted_regions`) + Σ(`unclaimed_components`)
= total mesh area; **plan stage** — Σ(area claimed by emitted archetypes) +
Σ(`unreconstructed`) = total mesh area, with both sums taken over a set keyed
by `region_id` so a region named by two lists is counted once and a region
named by none is the finding. Cross-stage roll-ups state which stage each
term came from. First targets: Dig-Next-2 and the honeycomb; explicitly audit
the <4-point face groups (§1.5). Cost: an hour. Turns H from "by construction"
into a measured row.

**Run E-prod — publish per-part RC-emitted for the eleven.** Fold into Run A
(same session produces the numbers); listed separately because it is the
missing *artifact* — the corpus tables publish counts, never emission-stage
area fractions, which is why §2.1's RC cell is unmeasured today.

---

## 5. Referee's note: the single number to buy first

**Run B** (benchmark slab-path RC-emitted, host-side, free) is the cheapest
unmeasured number, and it is the one most likely to move the *ranking*: if the
honeycomb's slab-path RC-emitted comes back far below its 33.5% plan coverage
(profile-set resolution or loop closure eating area on the only part with a
byte-perfect ground truth), the fix loop behind §3.1 grows and the 2.5D lane's
PR 4–6 ordering reshuffles ahead of scan-seg; if it comes back ≈ plan
coverage, §3.1's risk shrinks and scan-seg's claim to second firms up. Buy it
before scheduling the live session.
