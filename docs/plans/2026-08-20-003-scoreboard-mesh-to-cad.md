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

Six cells per part — RC, V, E, P (added 2026-08-21, §7.1), C, H — all
computable from pipeline artifacts alone (fit record, program, selection
record, emission report, rebuild report, editability report, coverage
account). The vector is reported whole; no scalar is invented (§1.6).

### 1.1 Recognition coverage (RC) — the headline

**The fraction of the mesh's surface area claimed by an archetype that the
emitter accepted and scripted as a parameter-driven feature.**

Derivation, exactly: take the coverage account's `plan` stage
(`covered_area_fraction` over planned archetypes — each archetype carries its
claimed regions and their areas), then subtract every archetype the emission
stage refused or dropped (`profile-ambiguous`, `sketch-loop-budget-exceeded`,
skipped fillets, …). What remains is area standing behind an emitted feature
script. Call it **RC-scripted** (renamed 2026-08-20 from RC-emitted, per the
external review — "emitted" over-claimed: this number attests to a script's
existence, not to built geometry). The headline is a ladder, each rung an
upper bound on the next:

```text
RC-scripted     host-side upper bound: script exists AND the host-checkable
                non-vacuity conditions (2 and 3 below) hold.
                RC-scripted-nonempty is an explicit alias of this rung.
RC-built        a live Fusion transaction created the geometry; non-vacuity
                conditions 1, 4 and 5 below are checkable only here
RC-verified     built + deviation accepted + editability proof
```

`delivered` is bound to **one rung: RC-verified** — the goal metric's own
words ("standing as editable Fusion features") already require the
editability proof, so `delivered_area_fraction` is RC-verified's artifact
name and is published only when all three gates (built geometry, accepted
deviation, editability proof) are on the record. RC-built's coverage-only
artifact is named **`built_area_fraction`** — a build census with no
deviation or editability verdict, never published under the `delivered`
name. `delivered` stays `unmeasured` until §4 Run A's live rebuild — no
host-side lane can produce either live rung. Corpus
reporting carries the area-weighted aggregate **and** the macro-average per
part, the median, and the zero-count — one large easy surface must not hide
a population of failed parts.

**Subtraction alone is not the measurement, and crediting it is how this number
gets overstated.** Emission is all-or-nothing: when host-side `plan_emission`
refuses any archetype, `emit_mesh_rebuild_script` raises before it returns a
transaction, so *nothing* was scripted — and in Fusion a failure rolls the whole
transaction back the same way. A part with one refused archetype and nine good
ones therefore has RC-scripted **0**, not nine archetypes' worth. The remaining
area is credited only after `replan_without` produces a reduced program **and
that program emits successfully**; until then the part's RC-scripted is zero with
the refusal named. Every run below (B, C, E-prod) records the re-emission it
ran, or records zero.

**Non-vacuity (added 2026-08-20; review finding 4 — P0, measured).** Success
was being derived from transaction exit status rather than from a positive
result, and the measured regression proves the gap: one v0.12.0 part EMITS
exit-0 a program covering **0.0% of source area** — an empty success no gate
caught. It also composes badly with componentization: an empty successful
monolithic run raises no refusal token, so refusal-licensed decomposition
never triggers. A successful parametric reconstruction must now satisfy
**all** of:

1. at least one parameter-driven feature was created;
2. at least one immutable source region is claimed;
3. the union of claimed source triangles has positive area;
4. at least one resulting body has positive volume, or explicitly licensed
   surface area;
5. `created`/`checked` entries were appended only after the corresponding
   API operations succeeded (the existing discipline, now a scored condition).

Failing any of these is a named refusal, not an emission — new closed-set
tokens: `no-emittable-claims`, `emission-empty`,
`emission-zero-source-area`, `emission-zero-geometry`. An intentionally
emptied `replan-without` result is a named "nothing reconstructable"
outcome, never a success. **Evidence boundary:** conditions 2 and 3 are
checkable host-side from the program/script record and gate `RC-scripted` —
Run B measures exactly this; conditions 1, 4 and 5 reference live API
operations and gate `RC-built`. A run that never opened a Fusion session
reports `RC-scripted`, never a higher rung, and the pre-gate "8 of 16"
census is *script-existence only* — weaker even than `RC-scripted`, and
flagged as such below. Identical score values are never reported across
different gates. This gate is **PR 0a** in the canonical
implementation order (`docs/reviews/2026-08-21-deep-research-reconciliation.md` §3, which extends and supersedes the 2026-08-20 review's §2),
ahead of everything else, and the v0.12.0 **"8 of 16 emit" census and its
23.3% area-weighted figure are flagged pending recomputation under it** —
the 0.0%-area part does not count as emitting.

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
  cannot rank changes. RC-scripted is the strictest number computable host-side
  today; `delivered` is RC's live-verified counterpart and replaces it in the
  headline the day the §4 Run A exists — Run A's live rebuild is its only
  source; no host-side lane (the 2.5D lane included) can produce it. The lose-only arithmetic
  (each stage may lose area, never gain — mesh-reconstruction.md,
  "Partial reconstruction") guarantees RC-scripted ≥ delivered, so RC-scripted is
  an upper bound on the goal metric, and is reported with that label.

### 1.2 Vocabulary score (V)

**Features recognized by kind ÷ features evident, per part.** **[Amended
2026-08-21, §7.2: V is a precision/recall pair — the ratio above is the
recall half; feature precision (correct recovered ÷ all emitted) is reported
beside it and never collapsed into one number.]**

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

**[Amended 2026-08-21, §7.3: proving a parameter drives *something* is a
liveness smoke test, not the scored proof — E's proof standard is now the
local-causal influence map; volume/centroid/bbox observables are demoted to
smoke tests.]**

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
things evident in the input.**

**Denominator rule (added 2026-08-20; review finding 11.3).** The denominator
can never be produced by the detector being scored — a detector that finds 8
and publishes a census of 8 makes C read 8/8, circular by construction. The
denominator comes from: independently annotated ground truth where it exists;
a **human-reviewed evident-things table** for acceptance fixtures (authored
before the detection run it scores — design -004 R4 as amended);
`C = unmeasured` on ordinary unlabeled scans. Raw counts are always reported
regardless: candidates, licensed geometric subobjects, physical things
evidenced, component definitions, occurrences — and under design -004 §0 the
numerator's claim level is named (`componentized-geometric` vs
`physical-thing-evidenced`), never blended. **Populations must match:** the
headline C divides `physical-thing-evidenced` components by the
evident-things (physical) denominator; `componentized-geometric` counts are
reported beside it as raw counts and — only where a reviewed table of
evident *geometric subobjects* exists — as a separately labelled
`C-geometric` ratio. A geometric numerator over a physical-thing
denominator is never computed. Achieved over target, the same direction as
every other cell — the first draft had it inverted, which made the stated
`C = 0` baseline a division by zero and scored ten things collapsed into one
component as 10 rather than 0.1. Two cases are named rather than computed:
**no components emitted → `C = 0`** (the state below, and the reason the cell
reads 0 rather than undefined), and **an unmeasured denominator →
`C = unmeasured`**, never 0 and never 1 — a part with no evident-things census
has no cell, which is exactly Dig-Next-2's position today. **Precedence:**
`unmeasured` wins — `C = 0` requires a measured, matching denominator and a
claim-level-bearing record; a missing denominator or claim level reads
`unmeasured` even when zero components were emitted. Over-emission
(a ratio above 1: more components than things) is a failure of this cell and
is reported by name — `things-over-partitioned` — not as a score above 1.
Today the emitter builds **one** component per part and places it: the rebuild
transaction sets a transform from `PLAN["datum_transform"]["matrix"]` and calls
`root.occurrences.addNewComponent(transform)` (`mesh_rebuild.py`). So for a
single-object part the cell shows **a raw scripted-occurrence count of 1** —
one placed component; headline C is `unmeasured` (a pre-`claim_level`
record, no measured matching denominator — §1.4 precedence) — and
`unmeasured` live, no rebuild having been built. What is 0 everywhere is *decomposition*: a second component, an
occurrence of a recognized sub-thing, anything that makes the denominator
larger than one. **One body per part is the current ceiling** (design 006
§model). The earlier draft of this section said no component or occurrence
emission existed in any emitter path; that was wrong — the placement call above
is in the shipped transaction, and it is what makes the single-object cell
satisfied rather than merely satisfiable. The cell bites on scans of
assemblies — Dig-Next-2 is a PCB assembly (board + soldered components; exact
census `unmeasured`, no evident-things table exists yet). No lane currently in
flight moves this cell *on an assembly*, which is the only place it is not
already satisfied (§3.7).

### 1.5 Honesty margin (H)

**Refused-by-name area vs silently-unclaimed area.** The second must stay
**exactly 0** (revised 2026-08-20 from "~0"; review finding 11.2: area
tolerance is unnecessary when ownership is checked by immutable triangle
IDs — an approximate target is a place for silence to hide). Original rule:
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

**The enforceable-H spec (added 2026-08-20; review finding 11.2 and missing
decision 24, decided).** H becomes enforceable only on top of the partition
lineage contract (design -002 §A.2) — area-only arithmetic cannot survive a
partition mutation, which Run D's double-counting analysis below already
sensed. The formal object is a **triangle-disposition state machine**: every
original triangle carries exactly one primary disposition per stage —

```text
stage:        fit | decompose | plan | emit | build | verify
disposition:  claimed(owner, claim-id) | refused(token, gate-evidence)
              | invalidated-by-partition(version)
```

— with every stage transition checked (a triangle cannot appear at `plan`
without a `fit`-stage disposition, and every `invalidated-by-partition` must
be re-dispositioned under the new version before the stage record closes).
Every refusal token cites the executed gate's evidence; the generic
`residual` bucket is **not** a permitted disposition — reason-laundering
through an unnamed residual is exactly the silence H exists to catch.
Inferred geometry (virtual caps, inferred base footprints) has no immutable
source-triangle IDs and is therefore **not a disposition of any original
triangle**: it lives only in the derived-geometry ledger with its own
identities (002 §A.2 rule 7) and never enters original-area conservation —
every original triangle is claimed, refused, or invalidated pending
re-disposition, with no third escape. Target: **silently-unclaimed triangle count = 0**,
exact, by immutable triangle ID. Run D remains the audit script; this is the
substrate that makes its identities checkable rather than approximate.

Stage-by-stage enforceability is explicit, because the audit can only read
records that exist: `fit` and `plan` are auditable today from
`fit.json`/`program.json` (Run D's identities); `decompose` becomes
auditable when 002 §A.2's lineage-bearing assignment records land; `emit`
when PR 0a's emission record lands; `build` and `verify` when Run A's
rebuild and editability reports exist. Each stage record carries triangle
IDs, its `partition_version`, predecessor linkage, and refusal evidence.
Until a stage's record exists its dispositions are `unmeasured` — reported
as unmeasured, never assumed zero — and the exact-zero target binds per
stage as each record arrives.

### 1.6 No scalar; a headline ordering

**[Amended 2026-08-21, §7.1: the vector gains a sixth scored cell, P
(program quality); the ranking order becomes RC, V (precision/recall pair),
E (causal), P, C, with H the guardrail.]**

A single weighted scalar would let a vocabulary win paper over a silent-area
regression. The scoreboard is the vector. For ranking work, cells are ordered:

**RC first** (it is the goal sentence made measurable: area standing as
editable features), then **V** (the "as many recognized things" clause — RC can
rise while everything is one extrude; V, a precision/recall pair per §7.2, is
what says the *things* were recognized and not hallucinated; within V the
comparison is **set-level Pareto layering** — the compared lanes are
partitioned into Pareto fronts on (precision, recall), and a lane's V rank
is its front index (front 1 = non-dominated), which is transitive by
construction; lanes in one front are tied at V, the trade recorded, rank
passing to the next cell rather than being resolved by an implementer's
arbitrary weighting (pairwise incomparability treated as an ordinary tie
would make the composed ordering cyclic), then **E**
(editable is the adjective; an inert parameter fails the sentence — the
causal standard of §7.3), then **P** (program quality, §7.1 — RC, V, and E
can all hold while the timeline is slab/primitive confetti; P is what says
the program is one a competent user would keep, compared by G5's
lexicographic census), then **C** (componentized is the other adjective; the
single-object cell is already covered by the raw scripted count, so what
ranks here is assembly decomposition, uniformly zero until a lane can move
it), with **H** as a guardrail rather than a rank: any change that grows
silent area is rejected regardless of its other deltas. *(Paragraph revised
2026-08-21 with Amendment §7 — the marker above records the change.)*

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
| RC-scripted | **unmeasured** (bounded above by 71.2% fit-level) | all 11 emit (PR #53), but per-part *area fractions* at the emission stage were never published, and the dumps are not committed, so the number cannot be recomputed from the repository. §4 Run E-prod. |
| delivered (live) | **unmeasured** | no slab build has ever run live |
| V | holes 74 planned of 85 evident bores (87%); prisms: 21/21 hex nut pockets correctly refused as cylinders; fillets **2 planned of 114 candidates** (3 → 2 on the slab path, PR #51 finding 4); extrudes: slab stacks per table; revolve/shell/chamfer/pattern: 0 (shell and revolve unassigned; chamfer/pattern not in vocabulary) | mesh-reconstruction.md; PR #51/#53 |
| E | **0 proven / parameters emitted per part `unmeasured`** (counts live in the emitted scripts, not in any published table); `interactions_exercised: false` | no U5 report exists for any part |
| C | **raw scripted occurrence count 1 / headline `unmeasured`** — the transaction places one component per part (`addNewComponent` with the datum transform); pre-`claim_level` records, so §1.4's precedence reads the headline `unmeasured`; `unmeasured` live. Decomposition beyond one component is 0 everywhere | §1.4 |
| H | all refusals named (tropical-leaves-style silent loss not observed; every gate token closed-set); area-conservation audit `unmeasured` | §1.5 |

### 2.2 The four benchmark parts (committed, replayable; manifest on the 2.5D head = post-#48 v1 path)

| part | fit accepted / coverage | plan coverage | emission (v1, committed) | emission (slab path, PR #53) | V vs ground truth |
| --- | --- | ---: | --- | --- | --- |
| honeycomb organiser | 39 planes / 41.6% | 33.5% | refused `profile-ambiguous` (11 loops) | **emits**: 5 slabs, 4 multi-loop sketches, 0 holes (hex pockets correctly cavities, not bores) | STEP = 145 planes, 4 normal families, **0 curved faces**: 39 planes matched to all 4 families at ≤1.1e-05 mm; **0 false curved primitives claimed** (was 6 pre-#48) |
| desktop organiser | 38 / 27.9% | 27.6% | **emitted** (1 sketch-extrude) — RC-scripted **27.6%**, the only committed nonzero RC in the program | emits, 1 slab | no ground truth; evident-features table `unmeasured` |
| tropical leaves | 31 / 18.3% | 5.7% | refused `profile-ambiguous` | still refuses — all 8 slabs `slab-section-inconstant`, 0.70–4.71 mm measured | organic; correct refusal → scores in H, not V |
| unicorn horn | 9 / 4.7% | — (plan refuses `frame-x-underdetermined`) | never reaches emission | same | F3D truth: 12 solid features — 3 extrude + 1 fillet expressible, **8 inexpressible by the closed vocabulary** (1 coil, 2 sweeps, 2 lofts, 1 shell, 1 split, 1 move); V = **0/12 recognized** |

On PR #54's branch (scan lane only, no slabs): leaves 31 → **49** accepted,
horn 9 → **23** and now plans a `hole` and reaches emission, desktop 38 → 45,
honeycomb byte-identical (manifest `re_measured` notes, PR #54 body). These
gains are fit-level; RC-scripted moves on no benchmark part from #54 alone.

Scoreboard cells common to all four: delivered `unmeasured` (never built
live); E = 0 proven; C: raw scripted occurrence count 1 (one placed
component each — a pre-`claim_level` record, so headline C is `unmeasured`
under amended §1.4, which requires an emitted component carrying
`physical-thing-evidenced`; the count is reported as a raw number, never as
a C value) and `unmeasured` live; H clean — every stop carries a named gate, and the
two "refuse" parts are the honesty exemplar (the leaves' 8 slabs refuse with
the measured disagreement, not silently).

### 2.3 Dig-Next-2 (Revopoint scan of a PCB assembly, 524,614 triangles, sha256 72aeeb2a…, not committed; artifacts in the scratchpad run + PR #54 body)

| cell | baseline (main, run artifacts) | PR #54 branch | source |
| --- | --- | --- | --- |
| fit coverage (diagnostic ceiling) | 0.0388, 443 accepted (all planes, all ≤ 99 triangles) | **0.1123, 1,718 accepted** | coverage.json; PR #54 |
| RC-scripted | **0.0** — plan claims 0.21% (one sketch-extrude), emission refuses `profile-ambiguous` (15 loops, 0 matched to holes) | still 0.0 — emission still refused; the blocker moved from `material_side` to cylinder support-floor (32×) and axis-uncertainty (14×) refusals: capture geometry, not σ | rebuild-refusal.json; PR #54 body |
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
   acceptance *checklist*. 4. C: the raw scripted occurrence count is 1 on
   every single-object part (one placed component each; headline C
   `unmeasured` under amended §1.4 — pre-`claim_level` records) and
   `unmeasured` live; assembly decomposition is 0 everywhere and no
   lane moves it. 5. Scan
   recognition is fit-level ~11% with RC-scripted still 0.

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
- **Cannot move:** RC-scripted on its own — emission on this part is the 2.5D
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
  Some RC-scripted (fillet area is small; holes already emit).
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
  scoreboard's only fully-replayable RC-scripted numbers).
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

No lane in flight moves C *where it is still open*. The single-object cell is
satisfied already — the rebuild transaction places one component per part — so
what is missing is decomposition: more than one component, and an occurrence
per recognized thing. Nothing can be ranked against evidence because no design
exists: what is a "distinct thing" in
a scan (the cross-cut's datum cells? connected components after board
subtraction?), what transform evidence licenses an occurrence, what U5 means
for a placement. **Action:** a design doc with an evident-things census for
Dig-Next-2 is the entry ticket; until then the assembly half of C stays an
honest 0 on the board rather than a pretended lane.

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
→ `plan-reconstruction <manifest> --fit-record <fit.json> --program-spec <spec.json>
--dump <mesh.bin>` with declared `slab_evidence` (all three options are
required; `--dump` is what the slab decomposition reads and arrives with the
2.5D lane — PR #51/#53 — which these runs are scheduled after in any case);
`emit-mesh-rebuild`
into a clean document; author per-part editability specs (observable +
perturbation + rationale per parameter, design 006 D7 arithmetic rules);
`emit-mesh-editability`; **`check-editability --rebuild-record
--editability-report --editability-nonce`**, which is the gate that turns a
saved report into a verdict and is the only thing that makes the phrase
"validated editability report" below mean anything — `emit-mesh-editability`
emits a script and mints a nonce and validates nothing; `emit-mesh-deviation`
against the immutable source; `reconstruction-coverage` last, with
`--editability-verdict` pointing at what `check-editability` produced. **Three artifacts, three cells — not one
command.** `reconstruction-coverage` yields `delivered_area_fraction` and
nothing else on this list: it takes no deviation verdict, and its editability
stage carries `checked`/`not_exercised` without an emitted-parameter
denominator or a ratio. So the **deviation verdict is read from
`emit-mesh-deviation`'s own report**, and **E is computed** — parameters the
validated editability report proves drive, over the `user_parameters` the
rebuild report emitted, less any the program declared `expected_observable:
none` (which are named, not counted against). Record all three per part, each
against the artifact it came from. Cost: one exclusive Fusion
session; planning is ~6 min for the corpus (PR #51), drawing ~1.5 s per dense
sketch (PR #53), deviation ~0.2 s per synthetic run but unmeasured at corpus
size; the human cost is authoring ~15 editability specs. Estimate half a day of
wall-clock, dominated by spec authorship and the first-failure loop.

**Run B — benchmark slab-path re-measure (host-side, no Fusion).** The four
dumps are committed; run `fit-regions` → `plan-reconstruction <manifest>
--fit-record --program-spec --dump` →
emission per part on the 2.5D head and record RC-scripted per part into the
manifest with `re_measured` notes. This is 2.5D PR 6's declared job; as a
measurement it is runnable today. Cost: minutes of compute, an hour of
recording. This is the **cheapest unmeasured RC number in the program**.

**Run C — Dig-Next-2 re-run on the merged head (post-#54 + post-#53, and again
post-splitter).** Same host-side chain against the retained dump
(`dig_next_2_stl-72aeeb2aed8f.meshdump`, scratchpad run/dumps). Record: fit
coverage, RC-scripted, the mega-group's fate, hole emission given 158 boundary
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
= total mesh area (this is the only stage that can close against the whole
mesh, because it is the only one that sees the unclaimed surface); **plan stage** — Σ(area claimed by **planned** archetypes) +
Σ(`unreconstructed`) = **the total area of the regions the fit stage offered**.
*Planned*, not emitted: `_plan_stage` exposes every archetype the program
carries whether or not emission later refused it, while `unreconstructed` holds
only what the *planner* declined — so subtracting an emission refusal from the
claimed side without adding it to any named list invents missing area. Emission
loss is a stage of its own and is accounted there (§1.1's all-or-nothing rule),
never inside this identity. The offered total is
*not* total mesh area: `plan_archetypes` partitions `fit_record.regions` and
nothing else, so the `unclaimed_components` — surface that never became a
region at all, 1,041 of them on Dig-Next-2 — exist only in `_fit_stage` and
would read as a conservation failure here. The two stages close against each
other instead: offered-region area + Σ(`unclaimed_components`) = total mesh
area is the fit stage's identity, and the plan stage's is against the offered
area it was actually handed. Both sums are taken over a set keyed by
`region_id`, so a region named by two lists is counted once and a region named
by none is the finding — **which is why this script reads the program and the
fit record, not the coverage account**: `_plan_stage` reduces each archetype to
`id`, `kind` and an aggregate `area_fraction` and drops the `regions` list, so
nothing keyed by region identity can be recomputed from the account alone. Run
D takes the raw `program.json` (each archetype's `regions`) and the raw
`fit.json` (each region's area) and reports *against* the account rather than
from it. Retaining region ids in the account would work too and is the larger
change; the audit does not need it. Cross-stage roll-ups state which stage each
term came from. First targets: Dig-Next-2 and the honeycomb; explicitly audit
the <4-point face groups (§1.5). Cost: an hour. Turns H from "by construction"
into a measured row.

**Run E-prod — publish per-part RC-scripted for the eleven.** Fold into Run A
(same session produces the numbers); listed separately because it is the
missing *artifact* — the corpus tables publish counts, never emission-stage
area fractions, which is why §2.1's RC cell is unmeasured today.

---

## 5. Referee's note: the single number to buy first

**Run B** (benchmark slab-path RC-scripted, host-side, free) is the cheapest
unmeasured number, and it is the one most likely to move the *ranking*: if the
honeycomb's slab-path RC-scripted comes back far below its 33.5% plan coverage
(profile-set resolution or loop closure eating area on the only part with a
byte-perfect ground truth), the fix loop behind §3.1 grows and the 2.5D lane's
PR 4–6 ordering reshuffles ahead of scan-seg; if it comes back ≈ plan
coverage, §3.1's risk shrinks and scan-seg's claim to second firms up. Buy it
before scheduling the live session.

---

## 6. Amendment — external-review incorporation (2026-08-20)

Source: `docs/reviews/2026-08-20-oracle-design-review.md` (findings 4, 11.1,
11.2, 11.3 land in this document; §1.1, §1.4 and §1.5 were revised in place).

- **Sequencing.** §3's ranking is subordinated to the canonical
  implementation order in the review file §2: **PR 0a (the §1.1 non-vacuity
  gate + "emits" census recomputation) and PR 0b (the relationships rewrite,
  design -002 §A.6) precede every ranked lane**, including §3.1's Run A.
  The rankings themselves are otherwise unchanged.
- **Baseline flag.** The v0.12.0 addendum figures the review was rendered
  against — 8 of 16 parts emitting, area-weighted RC 23.3% (production 11:
  6 emit, mean 45.5%) — are **RC-scripted, pre-non-vacuity** numbers. They
  are flagged pending recomputation under PR 0a; the measured 0.0%-area
  exit-0 part is known to be inside the "8", so the recomputed census is
  expected to be at most 7 of 16. The recomputed numbers replace them in the
  next baseline revision; until then any citation of "8 of 16" carries this
  flag.
- **New closed-set tokens registered by this amendment:**
  `no-emittable-claims`, `emission-empty`, `emission-zero-source-area`,
  `emission-zero-geometry` (§1.1). Tokens inherited by reference:
  `invalidated-by-partition` (design -002 §A.2),
  `relationship-budget-exceeded` (design -002 §A.6),
  `segmentation-datum-unavailable`, `correlation-model-unidentified`
  (design -002 §A.4/§A.5), `capture-boundary-unclosed`,
  `pose-locked-for-delivery` (design -004 §4.6/§4.7), and design -001 §A.3's
  slab-track tokens.
- **Vocabulary.** `RC-emitted` → `RC-scripted` applied throughout (§1.1
  records the rename); the H ladder reports `RC-scripted-nonempty` /
  `RC-built` / `RC-verified` and never promotes a lower rung over a higher
  one. The `unclaimed_components` population is renamed
  `unclaimed-surface-component` at its next schema touch (design -002 §A.7)
  to end the collision with Fusion/physical components.

---

## 7. Amendment — deep-research reconciliation incorporation (2026-08-21)

Source: `docs/reviews/2026-08-21-deep-research-reconciliation.md` (finding 6;
adoptions 3, 4, 5; abandonment 6). §1.2, §1.3 and §1.6 carry in-place
markers pointing here. Per the canonical order (review file §3, step 5),
**these cells land before any emitter is optimized** — metrics create the
optimizer, and adding P/precision/causal-E after code has been tuned against
the five-cell vector repeats the non-vacuity failure in slow motion.

### 7.1 P — program quality (new scored cell)

An eighty-feature slab-and-primitive timeline and a twelve-feature
human-quality timeline can tie on RC, kind recall, parameter liveness,
component count, and zero silent area. P is what separates them. Measured
per part, from the program and selection records alone, in two labelled
halves:

**The shared census** — identical, item for item and in the same declared
order, to the FHG compactness gate G5 (design 2026-08-21-001 §6), so the
system cannot be optimized against one definition and measured against
another:

1. unlicensed-duplicate parameter values (independently represented values
   whose regularity class licenses one shared parameter);
2. repeated geometry represented independently rather than by
   equality/pattern where the pattern licence held;
3. unnecessary-fallback count — the same bounded, tied-candidate
   definition as G5: `slab-join` operations whose support the selection
   record shows some G1–G4-tied candidate factoring within the declared
   `semantic_factorization_max_expansion` budget; a fallback with no
   within-budget factored alternative costs nothing, and on a program with
   no selection record the item reads `unmeasured` (ahead of feature count
   so a slab encoding never wins on timeline length against the
   factorization it stands in for). **Cross-lane comparisons evaluate
   necessity against the union of the compared lanes' recorded candidate
   sets** — selection records are committed artifacts, so a slab-join is
   unnecessary if *any* compared lane's record factors its support within
   budget; otherwise a lane that fails to generate semantic alternatives
   records zero unnecessary fallbacks and beats the lane that found the
   factorization, ranking the weaker hypothesis generator first;
4. feature count;
5. sketch count;
6. redundant construction planes/geometry;
7. unconstrained sketch degrees of freedom.

**Diagnostics** — reported under P, explicitly *outside* the P≡G5 identity
(G5 cannot optimize them — either ground-truth-only or reporting-only):
parameter count; fully constrained sketch rate; feature dependency depth;
and, where CAD ground truth exists, program-size ratio against the
reference timeline and feature-graph similarity.

P is reported as this census-plus-diagnostics, never collapsed to a scalar
(§1.6's rule); the identity claim binds the shared census only. Where P
must *rank* two candidates or two lanes (the §1.6 ordering), the comparator
is exactly G5's: lexicographic over the shared census in its declared
order, lower is better on every item; diagnostics never rank anything.
Ranking position: after E, before C (§1.6 marker). H remains the guardrail
over all.

### 7.2 V grows feature precision

```text
feature recall    = correct recovered feature instances ÷ ground-truth (or evident-table) instances
feature precision = correct recovered feature instances ÷ all emitted feature instances
```

Zero emitted instances makes precision's denominator zero: the part reads
`precision: unmeasured-no-emissions` — never 1 (nothing was hallucinated)
and never 0 (nothing was wrong) — and aggregates skip such parts with the
skipped count reported beside the aggregate; a zero-denominator recall
(empty evident table) already reads `unmeasured` under the §1.2 rule.

A lane whose *every* evaluated part reads `unmeasured-no-emissions`
therefore has no numeric precision coordinate at all, and §1.6's Pareto
layering needs a defined answer rather than an implementation-dependent
one. The rule is closed: **fronts are formed over the lanes carrying a
numeric (precision, recall) pair only**; every lane without a numeric
precision coordinate is placed together in one trailing front whose index
is (last measured front + 1), recorded `v-rank-basis: no-emissions` — tied
with the other silent lanes, ranked behind every measured lane, and never
assigned a fabricated precision of 1 or 0. Rationale: against any
non-empty evident table a zero-emission lane's recall is a measured 0 —
it recognized nothing — so no measured lane may be dominated by it; but
its silence is a fact about emission volume, not correctness, so it takes
a deterministic trailing rank instead of a synthesized coordinate. Where
the evident table itself is empty the whole cell is already `unmeasured`
(§1.2) and no front is formed.

Recall alone is gameable by over-emission: a system that finds the five
real holes and hallucinates six more keeps perfect recall. V is the pair,
reported as a pair. "Correct" is judged against ground truth where it
exists and the human-reviewed evident-features table otherwise (the §1.2
denominator discipline, unchanged — including `unmeasured` where no table
exists); the §1.4 circularity rule applies to precision's numerator
verbatim: the detector never authors the table it is scored against. Also
carried per part where ground truth allows: operation-family accuracy,
Boolean-polarity accuracy, and dependency-graph agreement — the review's
list, adopted as reported diagnostics under V.

### 7.3 E upgraded to local-causal influence maps

A parameter is not proven because *something* changed: a hole-diameter
parameter that scales the whole body moves volume and bbox beautifully; a
symmetric pair-spacing edit leaves the centroid fixed; a shared station
parameter can drive six unrelated slabs. The scored standard becomes, per
parameter:

1. **Expected influence set**, authored from the program's dependency
   edges **and validated against the evidence that licensed them** — the
   map is never taken on the candidate's own word, or causal E would
   certify exactly the over-coupling it exists to detect (a program that
   wrongly shares one parameter across unrelated regions lists them all as
   expected targets and passes trivially). Every multi-region coupling in
   the expected set must cite the licence that coupled it: the regularity
   class certificate (equality/pattern — measured, candidate-independent
   evidence) or the geometric construction that makes the coupling
   necessary (a station bounding the features on its plane). A coupling
   with no licence is `influence-map-unlicensed` — a program defect
   surfaced by the proof, not a passing map. The set then lists: the
   regions expected to move, with direction and magnitude class; the
   regions expected NOT to move; the local observable (local radius, local
   signed-distance field over the target region's triangles).
2. **Perturb, recompute, and verify**: the intended support moved in the
   expected direction/magnitude; **non-target support stayed invariant
   within declared tolerance**; constraints and feature health stayed
   valid; restore reproduced the baseline (the existing D7 loop,
   unchanged as mechanics).
3. **Interaction cases**: coupled parameters (shared stations, equality
   classes, expressions over two parameters) get declared pairwise
   perturbation cases; `interactions_exercised` stops being a permanent
   `false` — it reports the exercised fraction of declared interaction
   cases.

Global observables (volume/centroid/bbox) are retained as cheap smoke
tests and may still gate early (`parameter-inert` keeps its meaning), but
they are never the scored proof: E's numerator counts parameters passing
the influence-map standard. Until influence-map reports exist, E rows read
`unmeasured (causal)` beside any legacy global-observable count — the two
standards are never conflated in one number (the §1.1 "identical values
never reported across different gates" rule, applied to E).

### 7.4 Tokens and artifacts

New closed-set additions: `parameter-nontarget-moved` (the non-target
invariance failure, distinct from `parameter-inert`), `influence-map-absent`
(a parameter emitted without an expected influence set — a program defect,
not a proof gap), `influence-map-unlicensed` (a multi-region coupling in
the expected set citing no class certificate or necessary construction —
§7.3's anti-circularity rule). The editability spec schema gains the influence-set
fields; the selection record (design 2026-08-21-001) is a scoreboard input
artifact. §4 Run A's procedure gains: author influence maps from the
selection record rather than hand-written observables where the program
carries FHG provenance.
