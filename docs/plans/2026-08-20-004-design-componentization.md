---
title: "design: componentization — panel verdict and synthesis (issue #20)"
date: 2026-08-20
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
execution: code
origin: https://github.com/novotnyllc/agent-utilities/issues/20
builds_on: docs/plans/2026-08-20-002-design-scan-segmentation.md,
  docs/plans/2026-08-19-005-feat-mesh-parametric-reconstruction-plan.md,
  docs/plans/2026-08-19-006-design-u4-u5-feature-emission.md
inputs: "panel proposals (geometry lens, product-and-practice lens); the
  recognition scoreboard (2026-08-20-003, referee baseline v1); feat/25d-emitter
  head; run artifacts for Dig-Next-2 (rebuild-refusal.json, coverage.json,
  fit.json, fg-histogram.json) and the loop-evidence dumps (prod-loops.json,
  bench-loops.json)"
status: judged synthesis — rulings, staged design, and PR sequence; no
  production code in this document
---

# Componentization: verdict and synthesis

Judge's charge: reconcile the two panel proposals into one implementable
design for the owner's goal, verbatim: *"fully editable componentized objects
for as many recognized surfaces/shapes/things as possible."* The scoreboard
(2026-08-20-003 §3.7) currently carries componentization as "unranked as
implementation; a design doc with an evident-things census for Dig-Next-2 is
the entry ticket." This document is that entry ticket.

**Prerequisite artifacts, and where they are.** This plan delegates its
segmentation gates, acceptance evidence, and scoreboard definitions to two
documents that are *in the same merge queue as this one*, not yet on `main`:
`docs/plans/2026-08-20-002-design-scan-segmentation.md` on branch
`docs/scan-segmentation` (**PR #52**) and
`docs/plans/2026-08-20-003-scoreboard-mesh-to-cad.md` on branch
`docs/scoreboard` (**PR #55**). Until both merge, this plan is
implementation-ready *conditionally*: `artifact_readiness` above states the
document's own state, not the tree's, and a reader who cannot resolve a cited
PR 1/3/4 behaviour or a scoreboard cell should read those two branches rather
than conclude the citation is dangling. The stage that actually consumes those
gates, PR C-4, is already blocked on the segmentation PRs merging (§6), so no
code in this lane runs against a prerequisite that is not in-tree by the time
it is needed — but the *reading* of this plan does depend on them, which is
what this note is for.

The stakes, from the product expert's research (verified against its cited
sources' summaries, not re-derived): no commercial scan-to-CAD tool promises
automatic decomposition of a fused multi-object scan — the documented industry
answer is "disassemble and scan separately," and service bureaus bill manual
mesh cropping per part. The first shipped stage of this lane (C2, placed
reference-mesh components) therefore exceeds the documented commercial bar,
not merely approaches it.

Module paths below are relative to
`plugins/agent-utilities/skills/fusion-parametric-design/`.

**Review incorporation (2026-08-20).** The external design review preserved at
`docs/reviews/2026-08-20-oracle-design-review.md` returned REVISE BEFORE
IMPLEMENTATION, with this document's ontology as its first P0. The accepted
findings are folded in below: §0 (the four-concept ontology, finding 1), §4.1
(the licence split, finding 6), §4.6 (virtual closure, finding 7), §4.7
(placement observability and instancing, finding 12), R5 (lateral contact,
finding 13), R4/§7 (the C denominator, finding 11.3), and Amendment A at the
end (decided items, renames, sequencing). Passages the amendments supersede
are marked in place.

---

## 0. The object ontology — four concepts, never collapsed

The review's central attack stands: this design as first written moved
directly from a surface partition to components-and-occurrences while
defining its goal as "distinct physical things," and those are not equivalent
propositions. The measured face of the attack is any injection-molded lid:
integral bosses and ribs detach at a narrow contact band, meet it along
closed curves, and reconstruct independently — satisfying every
`separable-at-interface` condition — while being features of one physical
part. No held-out comparison can resolve it, because both readings explain
the observed exterior geometry. So the design is **rewritten around
componentization as an editing decomposition**, with physical thinghood a
strictly stronger, optional claim. Four concepts, each with the exact claim
it supports:

| Concept | Claim supported | Evidence bar |
| --- | --- | --- |
| **`surface-region`** | these triangles share a geometric model | a gated fit (the segmentation lane's product) |
| **`geometric-subobject`** | the exterior surface admits a stable separable partition here | boundary/separability evidence + partition stability + exact ownership + closure accounting (the C1 partition licence, §4.1) |
| **`physical-thing`** | independent-object evidence exists **beyond** geometric separability | an independent channel: an observed gap or seam, disconnected source topology, a mutually occluding boundary, a uniquely evidenced assembly interface, or an explicit caller declaration |
| **`delivery-component`** | the output policy chooses a Fusion component as an editing unit | the C2 delivery licence (§4.1) |

Rules that follow, binding on every stage and record below:

1. A geometric subobject may become a Fusion component; its status is
   **`componentized-geometric`**, never `physical-thing-evidenced`, unless an
   independent-channel item above is on the record. "Base and subobject both
   reconstruct" is **not** that channel — it is the definition of geometric
   separability, restated.
2. Both statuses join the closed component-status vocabulary (§2 item 9);
   the browser-tree note and the census report them distinctly, and the
   scoreboard's C cell counts them distinctly (003 §1.4 amended: the
   numerator's claim level is named).
3. The product story survives intact — an editing decomposition of a fused
   scan into placed, statused components is the deliverable and still
   exceeds the documented commercial bar — it just stops asserting
   physics it has not measured. A user who wants the bosses as components
   gets them, labelled as what the evidence supports.
4. Every refusal and licence in this document is re-read under this table:
   "thing" below means *candidate geometric subobject* at detection time,
   and its post-licence status names which rung it actually reached.

---

## 1. Verified facts vs assumptions

### 1.1 Verified (re-checked against artifacts and source during judging, not taken from the proposals)

- **F1.** `rebuild-refusal.json`: the section at z = 5.17321 mm closed 15
  loops for `sketch-extrude-05d1a37c6938`, 0 matched to holes, refusal
  `profile-ambiguous`. The monolithic reading of Dig-Next-2 is refused today.
- **F2.** `prod-loops.json` (11 production parts, feat/25d-emitter loop
  evidence): pod_a1_lid — 21 loops at station 3.3 mm, all at full winding
  consensus, mixed depths with material-inside islands; pod_b_lid — 22 loops,
  same shape. Monolithic parts routinely carry many islands; any "island ⇒
  thing" detector destroys the production corpus. The null case is the common
  case.
- **F3.** `fit.json` / `coverage.json` (Dig-Next-2, main): 443 accepted fits,
  all planes, all ≤ 99 triangles; `covered_area_fraction` 0.0388; the
  448,122-triangle mega-group (78.97% of area — the board's two faces plus
  edge band) is unfitted. On the PR #54 branch: 0.1123, 1,718 accepted, still
  zero cylinders (scoreboard §2.3). **There is no accepted board face on any
  branch today.**
- **F4.** The machinery both proposals lean on exists at the cited names on
  `feat/25d-emitter`: `mesh_slabs.py` — `classify_loops` (line 521),
  `congruence` (451), `containment_parents` (357), `polygon_centroid` (331);
  `mesh_segmentation.py` — `REFUSAL_REASONS` (104), `REGION_FLAGS` (129).
- **F5.** The 2.5D emitter lane's PRs 1–3 have landed (stack #49 → #51 → #53,
  head `feat/25d-emitter`; all 11 production parts emit host-side); its PRs
  4–6 (hole/fillet composition, shell, editability + re-measure) are pending.
  No branch contains both #53 (emitter) and #54 (scan sigma); the merge is
  scoreboard §3.4's named precondition for any composite scan claim.
- **F6.** The segmentation design (2026-08-20-002) is judged and sequenced:
  PR 1 region tree + partition invariant (KTD-1/P1) + `derived_from` schema;
  PR 2 relationships equivalence-class rewrite; PR 3 cross-cut splitter
  (board faces emerge as regions); PR 4 Moran block-bootstrap null (board
  faces can be *accepted* — F7 there shows the iid null rejects two orders of
  magnitude below board-face area). None of those PRs has landed.
- **F7.** Scoreboard baseline: C (componentization) = 0 everywhere; the
  emitter's ceiling is one dedicated component holding one body per part, no
  occurrence transforms; Dig-Next-2's distinct-things census is `unmeasured` —
  no evident-things table exists.
- **F8.** Today's loop evidence on Dig-Next-2 is 2D: 15 closed section curves
  at one station (F1). It cannot assign the mesh's 524,614 triangles to
  things — triangle ownership requires a surface partition plus a base-face
  band census, neither of which exists before segmentation PRs 1/3 (F3, F6).
- **F9.** `min_feature_size = 1.6 mm` is the declared floor in `fit-spec.json`;
  measured flat-face form error is 0.033–0.076 mm rms (design -002 F5/F11).
  These are the numbers the thing-support floor derives from.

### 1.2 Assumptions (labelled, each with what settles it)

- **A1.** The Fusion API rows in §2 of the product proposal
  (`Occurrences.addNewComponent`, `transform2`, `addExistingComponent`,
  `AsBuiltJoints`, `RigidGroups`, `MeshBodies`-in-component, attributes) are
  documentation, not verified behavior. Settled by probe tickets PC-1..PC-10
  (§8), per plan-010's probe discipline.
- **A2.** Scanner arc coverage and support on the cans/headers clears the
  detection floors (8–20 things at C1). Settled by the first
  `plan-decomposition` run after segmentation PR 3/4 land — and the same run
  *produces* the evident-things census the scoreboard lacks.
- **A3.** Winding (`material_side`) survives thing-split sub-mesh extraction
  well enough for the emitter's loop ladder to run per thing. Settled by
  PC-11 (§8) — host-side, runnable as soon as the extractor exists.
- **A4.** The interface band width δ = max(pooled station sigma, one median
  edge length) neither swallows short components nor leaks solder fillets.
  Settled by the band-area census the interface record carries on every run.

---

## 2. The adopted consensus

The two proposals agree on the load-bearing structure, and the judge adopts
all of it — no defect found in any item:

1. **Monolithic-first; decomposition licensed by refusal.** The single-solid
   reading is the null hypothesis; decomposition is attempted only when the
   monolithic reading is refused by the existing gates (Dig-Next-2's
   `profile-ambiguous`, F1) and claimed only when the decomposed reading fits.
   The production-part null (F2) is safe **by construction**: pod_a1_lid's
   islands never trigger the attempt. See ruling R3 for the one strengthening.
2. **The interface as a first-class record.** The solder-fillet band belongs
   to neither solid: `interface(id) = {plane fit, cut loops, band triangles,
   joined thing ids, δ + derivation}`. Deviation over band triangles grades
   against the joint. The partition invariant stays exact with owner classes
   {base, thing-k, interface-j, residual}.
3. **Per-face evidence class `observed` vs `inferred-by-contact`.** A thing's
   bottom cap has no scan points by construction; deviation partitions into
   `graded-against-scan` and `asserted-by-contact` (area enumerated,
   ungraded, basis recorded); derived dimensions carry
   `derived-with-inferred-endpoint`. A single blanket "deviation: X mm" per
   thing remains impossible.
4. **Per-DOF placement evidence, with `rotation-unconstrained` recorded** and
   a canonical representative chosen by a declared deterministic rule,
   labelled `canonical-not-observed` (Fusion needs a full rigid transform;
   the ambiguity lives in the record and the component note). *[Formalized
   and extended in §4.7: information matrix, nullspace, stabilizer group,
   discrete alternates, per-mode evidence class — the Boolean vector alone
   is superseded.]*
5. **Components + occurrences, never bodies.** The occurrence transform is
   the placement record — the one datum a fused scan uniquely provides over
   separately-scanned parts, and the datum the commercial workflow throws
   away. Grounded base; multi-body-part delivery explicitly rejected.
6. **Instancing licensed by fitted-parameter agreement within joint
   uncertainty plus aligned mesh deviation**, with `instance-breakout`
   revocable per occurrence; patterns are claims, emitted only when a lattice
   fit passes a declared gate (`pattern-not-claimed` otherwise). *[Superseded
   in form by §4.7: pairwise tolerance is nontransitive; classes form by
   complete linkage or joint class fit, per tier.]*
7. **The five-stage ladder C1→C5** (partition record → placed reference-mesh
   components → per-thing reconstruction → instancing/patterns → attachment
   semantics), with **C2 as the first shipped headline**. Kinematic joints
   are never inferred from a static scan (`motion-not-evidenced`).
8. **The production corpus binding:** byte-identical records through C1;
   schema-additive after; single-body path unchanged whenever no thing is
   claimed; refusal vocabulary only grows; existing coverage semantics
   untouched (componentization adds sibling metrics, never redefines).
9. **Component states as UX** (product §5's closed vocabulary): everything
   the scanner saw appears in the browser tree exactly once with a status;
   roll-up `componentized-full` / `componentized-partial` /
   `componentization-refused`, partial never abbreviated.
10. **Geometry's Design 1 over Design 2**, with Design 2's island-chain
    evidence as the primary detection signal inside Design 1 — the chain
    detector is the right first component of the interface-partition stage,
    not an alternative to it.

---

## 3. Rulings

### R1 — Pipeline position: one stage, two artifacts; the stage owns the invariant

**Ruling: both experts described the same thing at different altitudes, and
the synthesis keeps both names with one owner.** A new stage
`plan-decomposition` sits between fit and plan (geometry's position — it
consumes accepted base faces, loop evidence, and region adjacency, and must
run before program planning). Its output artifact is the **assignment
record** (product's C1): a total map from the region tree's terminal
partition onto owner classes {base, thing-k, interface-j, residual}, where
`residual` includes the below-support and unclaimed populations, itemized.

- **The band is δ of the *contact curve*, not δ of the face.** A base face's
  own triangles are at distance zero from it, so a band defined as "within δ of
  an accepted base face" swallows the whole base region — taking the accepted
  datum out of the `base` owner and leaving the base with nothing to
  reconstruct from. The band is therefore defined over the **non-base**
  triangles within δ of the *contact curve* where a candidate thing meets that
  face: the face contributes its own boundary strip only where the curve runs,
  and the rest of the face stays `base`. δ is derived as before; what changed
  is what it is measured from.
- **The interface band is a cut of the region tree, not a filter over it.**
  The band is distance-defined, so it runs through terminal regions rather than
  along their boundaries, and a map from the *existing* terminals onto owner classes
  cannot express it: the region would owe its band triangles to `interface-j`
  and the rest to a thing or the base, which no single owner satisfies. So
  `plan-decomposition` **refines the tree first**: a terminal the band crosses
  is split at the band boundary into two terminals (`interface-split`, under
  the same `derived_from` schema the thing sub-meshes use, both parts carrying
  their parent's identity and their own triangle lists), and the partition is
  taken over the refined terminals. Areas conserve across the split by
  construction, which is what makes the audit below satisfiable; nothing owns
  a fraction of a region, and nothing is owned at two granularities.
- **The partition invariant at assembly level is owned by the
  `plan-decomposition` stage record**, which asserts it exactly once (every
  terminal region — hence every triangle — has exactly one owner), the same
  one-assert discipline as KTD-1/P1. `reconstruction_coverage` *cites* the
  assignment (`assignment_checked: true`, owner-class area fractions) but
  never re-derives it — one owner, one assert, many consumers.
- **Things re-enter the pipeline as region-tree subtrees under their own
  datums** (geometry §4): the assignment record is the flat product view of
  the same tree the recursion mechanism uses. No second data structure; the
  assignment is a projection of the tree, generated and checked in the same
  stage.
- **Where segmentation refused** (no accepted base face: `datum-unavailable`,
  or the mega-group still terminal-unfitted), decomposition cannot evaluate
  either its trigger or its license. Verdict:
  `componentization-refused: no-accepted-base`, assignment degenerates to
  nothing (no assembly layer emitted), and the part flows down the
  single-body path exactly as today. A refused segmentation never produces a
  half-assembly.

### R2 — Sequencing: detection is blocked; the lane is not

**Ruling: the geometry expert is right about the hard dependency and the
product expert is right about the schedule; both were arguing past the
distinction between the *first thing-claim on Dig-Next-2* and the *lane's
PRs*.**

The dependency graph, explicit:

- **C1 detection on Dig-Next-2 is strictly behind segmentation PRs 1, 3,
  and 4** (F6). PR 1 supplies the terminal partition the assignment is
  defined over; PR 3 makes board faces exist as regions; PR 4 (or PR 3+4
  merged, per design -002 §5) makes them *accepted* fits — and the license
  clause ("the base reconstructs with the thing sub-meshes removed") is
  unevaluable without accepted base faces, as is the interface census
  ("triangles within band δ of accepted face F"). The branch merge of #53
  and #54 (F5) is a further precondition for measuring any of it on one head.
- **C2 cannot ship against today's loop/island evidence, and the reason is
  F8, not caution:** the 15 loops at one station are 2D curves; they cannot
  assign 524,614 triangles to things. There is no honest mesh slice to place.
  The refusal that exists today is the *trigger*; the trigger without the
  partition licenses nothing.
- **But only two of the lane's six PRs are behind that wall.** The schema PR
  (evidence classes, `thing-split` derivation, status vocabulary), the probe
  battery (live Fusion, independent of segmentation entirely), and the
  assembly emitter itself (developed and acceptance-tested against a
  hand-authored assignment record on a synthetic two-thing fixture — a block
  with two placed pegs, ground truth known) all proceed now, in parallel with
  the segmentation lane. C2-as-capability lands green on the synthetic
  fixture; C2-on-Dig-Next-2 lights up the day `plan-decomposition` lands.
- **The 2.5D emitter lane (its PRs 4–6) gates nothing before C3.** C1/C2
  place mesh bodies, not features. Only C3's `parametric` upgrades of
  prismatic things wait on the emitter lane's remaining scope; `primitive`
  upgrades (a can becoming a cylinder solid) do not.

Consequence for the PR sequence (§6): three PRs are schedulable immediately;
the detection PR is sequenced behind segmentation PRs 1/3/4 and consumes
their artifacts on the merged head.

### R3 — The trigger: refusal stays the trigger; the census gets its stronger consumer

**Ruling: refusal-licensing is correct as the trigger but insufficient as a
permanent guarantee, exactly as the geometry expert feared. Adopt the
model-selection comparison as the declared consumer of the both-fit census —
the codebase's existing parsimony-F idiom lifted one level.**

The failure mode is real: a future emitter improvement that makes a
grotesque monolithic model of an assembly *fit* (a 15-loop extrude stack
that passes every gate) silences the trigger, and componentization silently
regresses to zero on the very parts it exists for. The defense, in three
layers, cheapest first:

1. **The complexity witness (always on, report-only, ~free).** Whenever the
   monolithic reading fits, the census records what `classify_loops` already
   computes: the count and aggregate area of island chains at depth ≥ 2 with
   station persistence, plus the thickness-anomaly count (chains taller than
   the parent slab). One census line; no geometry changes; the production
   parts gain `things: 0, decomposition-not-triggered` plus the witness
   numbers, schema-additive per the corpus binding.
2. **The declared escalation floor.** When the witness exceeds a declared
   floor (area fraction in persistent chains, with rationale, through
   `_declared_number`), the decomposed reading is *attempted and compared*
   even though the monolithic reading fit. **Not the existing F-test.** That
   statistic (`mesh_segmentation`'s parsimony test) is nested-only: it
   compares primitive kinds where one model's parameter space contains the
   other's, evaluated on the *same* points. These two candidates are neither —
   different topology, and different triangle populations once the interface
   band is removed and inferred closure is added — so its p-value would have
   no interpretation and could select or suppress componentization on
   arithmetic rather than on evidence. The comparison is instead a **held-out
   score over identical observed support**: both readings are scored on the
   same triangle set (the observed triangles, band and inferred-closure
   triangles excluded from both), on held-out samples not used to fit either,
   as declared RMS deviation per triangle plus a declared parameter-count
   penalty and a declared margin — no distributional claim, and both terms
   caller-declared through `_declared_number` with rationale. The verdict —
   `monolithic-preferred` or `decomposition-preferred-on-held-out` — is
   recorded either way, with the support size and both scores beside it.
3. **The claim rule.** Decomposition is *claimed* over a fitting monolithic
   reading only when the comparison is decisive by its declared margin, or
   the spec declares `decomposition: prefer-things` (geometry's policy
   escape, kept). When both fit and neither is decisive:
   `decomposition-model-ambiguous` at the top level (renamed per §A.5) — the monolithic model ships,
   with the candidate partition enumerated beside it, never silently chosen.

The floor must be set (and regression-tested) so the 11 production parts do
not cross it — or, if a pod lid's bosses ever do, the comparison verdict on
a correct monolithic part is `monolithic-preferred` and the output geometry
is unchanged; the corpus byte-identity check through C1 and
identical-or-explained rule after are the gates that keep this honest.
Layers 2–3 land with the C3-era PR (§6, PR C-6), before any emitter
improvement plausibly makes the assembly fit; layer 1 lands with detection.

### R4 — Thing-count honesty: two numbers, not one; floors are acceptance, bands are predictions

**Ruling: the experts' predictions (geometry 15–25 detected / 10–20
componentized; product 8–20 things of ~40) are measuring different stages,
and the reconciliation is to name the stages.** "Componentized" under this
design means *has a component with a placement* — that is C2's occurrence
count, and both experts' bands overlap there. Geometry's "10–20
componentized" conflated recognition with reconstruction; under the ladder,
the parametric number is C3's and is smaller.

Reconciled, with the measured evidence behind each floor:

- **Recognition (C1/C2): predicted 8–20 of ~40; acceptance floor 8.** The
  floor is the population both experts independently name as clearing
  support: 3 electrolytic cans + ≥ 2 headers/connectors + the inductor +
  ≥ 2 larger ICs. Most passives (0402/0603) sit at or below
  `min_feature_size = 1.6 mm` (F9) and land in `residual` with
  `below-support-floor`, itemized — the ~40 denominator is *reported
  against*, never claimed.
- **Parametric componentization (C3): predicted 3–10; acceptance floor 3** —
  the cans reaching `recognized-primitive` (full-arc cylinder walls clear
  the span gate per design -002 A4, still an assumption until the
  post-cross-cut fit record exists). Through-hole parts refuse
  `interface-pierced`; complex shells refuse per-thing; each named.
- **The ~40 denominator itself is `unmeasured` (F7) — and the detector being
  scored can never produce it** (review finding 11.3: if the detector finds
  8 and publishes a census of 8, C reads 8/8 — circular by construction).
  The first C1 run still publishes its census, but as the *numerator-side*
  count of what was found. The denominator comes independently: for
  acceptance fixtures (Dig-Next-2 first) a **human-reviewed evident-things
  table** authored from inspection of the scan/photos *before* PR C-4's
  acceptance run, committed with provenance; on ordinary unlabeled scans
  `C = unmeasured`, with the raw counts always reported — candidates,
  licensed geometric subobjects, physical things evidenced, component
  definitions, occurrences (per §0's distinction). Until the reviewed table
  exists every prediction above is [I]-labelled and falsifiable by that run.

Per-stage acceptance numbers for the Dig-Next-2 fixture are consolidated in
§7.

### R5 — Laterally-touching things: the merged pseudo-thing, named, is the honest disposition

**Ruling (amended 2026-08-20, review finding 13): the merged pseudo-thing
stays the honest default, but the original "no fix exists" claim was too
broad and is narrowed to the case that is actually information-theoretically
non-identifiable.** The permanent limit is precisely:

> the observed exterior surface is compatible with multiple internal
> partitions, and no additional evidence or declared prior distinguishes
> them

— renamed **`lateral-interface-unobserved-and-partition-nonunique`** (the old
blanket name over-claimed). It is *not* true for all laterally touching
things. Evidence that can distinguish partitions, each already inside the
evidence rules: an observed crease or gap; a T-junction or occlusion contour;
two independently supported primitive continuations that determine a
**unique** hidden contact; a matching complete instance elsewhere on the
part; a second view exposing part of the interface. The design already
permits an unobserved bottom as `inferred-by-contact`; it now consistently
permits a **uniquely determined lateral completion** as
**`inferred-by-continuation`** (new evidence class, closed set), under the
same discipline: the inferred interface area separately enumerated in the
derived-geometry ledger (002 §A.2 rule 7), no scan-deviation claim on that
area, alternative partitions tested, and refusal the moment more than one
completion survives. And per §0: even a unique geometric split licenses a
*geometric decomposition* (`componentized-geometric`), never physical
identity by itself.

When the limit genuinely applies — no distinguishing evidence at all:

- One separable sub-surface with no internal-split evidence ships as **one
  merged pseudo-thing per contact cluster**, a real component, placed and
  measurable, named as what it is: `thing-cluster-03 [merged:
  boundary-unobserved]`, status `recognized-reference` (or higher if the
  merged surface reconstructs), with the contact-cluster membership question
  carried as `lateral-interface-unobserved` in its record (renamed per §A.5).
- Congruence against instances elsewhere on the board may *nominate* a split
  (two footprints of a known class); nominations are recorded as proposals
  with their evidence, never asserted. A prior can nominate; only a fit can
  license; when multiple partitions fit, none is claimed.
- This is **not** residual: the cluster is recognized (there is a thing
  there), counted in the occurrence census as one, with
  `cluster_candidate_count` recorded so the honesty margin names how many
  things it might be.
- Entered in the permanent-limits register (§9) with the only known exits:
  better capture (a second scan after partial disassembly — the industry's
  own answer, offered as guidance in the component note), or a future
  multi-view/texture evidence channel, both outside this design's scope.

The through-hole variant (`interface-pierced`) is different in kind: it has
a designed future (multi-patch interfaces) and stays a named refusal, first
follow-up, not a permanent limit.

### R6 — Probe queue: product's ten adopted; two added; ordered by what gates which stage

**Ruling: adopt PC-1..PC-10 verbatim as the empiricist's queue, add PC-11
and PC-12, and order by stage gating (§8).** The geometry design does need
one probe the product list missed — the brief's suspicion is confirmed:
winding inheritance through `thing-split` (PC-11) is load-bearing for C3
(the loop ladder per thing runs on `material_side`, and a sub-mesh open at
its cut loop is exactly the case the ladder has never seen), and mesh-body
scale (PC-12) is the C2 stability question PC-5 only brushes (rigid-group
cost ≠ twenty ~25k-triangle mesh bodies in one document).

---

## 4. The synthesized design

One paragraph, then the pieces. **The segmentation lane's region tree is the
substrate; `plan-decomposition` is a new stage between fit and plan that
produces the assignment record (owner classes {base, thing-k, interface-j,
residual}) under monolithic-first refusal-licensing with the R3 complexity
witness; things re-enter the existing pipeline whole, as subtrees under
their own datums, their sub-meshes derived under the `derived_from` schema
with winding inherited; closure of unobserved bottoms is supplied by the
interface record per cut loop with evidence class `inferred-by-contact`,
never by fabricated triangles; a final `plan-assembly` stage emits the
Fusion component tree — grounded base, one component per thing (mesh body at
minimum), occurrence transforms as the placement record with per-DOF
evidence — and the ladder C2→C5 upgrades fidelity inside that fixed
structure without ever changing it.**

### 4.1 Detection (inside `plan-decomposition`)

- **Trigger — and it must be computable where the stage runs, and it must not
  need nesting.** The stage
  sits between fit and plan, so it cannot observe `emit-mesh-rebuild`'s
  verdict: F1's `profile-ambiguous` is raised two stages later, and a trigger
  that waits for it would leave C-4 producing no assignment on the very part
  it is measured against. So the trigger is **fit-stage computable**, in this
  order: (a) the R3 escalation floor crossed (the island-chain witness §4.1
  computes from `classify_loops` output alone); (b) `decomposition:
  prefer-things` declared; or (c) a **recorded prior refusal** — a monolithic
  verdict from an earlier run of the same dump, cited by dump hash and
  refusal token, which is how F1 enters without inverting the pipeline. A
  live refusal is not a trigger; it is evidence that gets recorded and read
  by the *next* run, which keeps the stage order intact and keeps the trigger
  honest about what it can see. Dig-Next-2 reaches C-4 through (a) and (c)
  both, and the run records which fired.
  **And (d), always on: the separability signal itself.** The island-chain
  witness counts persistent depth-≥2 chains and thickness anomalies, which an
  assembly of side-by-side protrusions does not produce — its things are
  separate depth-0 exterior loops, its monolithic reading fits, and with no
  prior refusal for that dump nothing above ever fires, which is the silent
  regression this section exists to prevent. So the interface census runs on
  every part rather than only after another signal has fired: when it finds
  two or more components that detach at a planar interface and meet the band
  along closed curves (`separable-at-interface`), that is itself a trigger.
  It is the more expensive of the two signals, which is why it was second;
  running it always is the cost of not missing a whole input class, and the
  census line it produces (`things: 0, decomposition-not-triggered` plus its
  own component count) is what the production corpus records when it finds
  nothing. **Per §0: `separable-at-interface` nominates a *geometric
  subobject* candidate and nothing stronger — an integral boss satisfies
  this signal too, which is exactly why the resulting component's status is
  `componentized-geometric` unless an independent physical-thing channel is
  on the record.**
- **Candidates,** from evidence the pipeline already computes (F4):
  island-chain detection over `classify_loops` output (footprint recurrence
  under `congruence`, concentric within pooled sigma, across contiguous
  stations) as the primary signal; the interface census (band-δ deletion
  from the dual graph against each accepted base face; connected components
  that detach and meet the band along closed curves →
  `separable-at-interface`) as the second, independent signal; the
  cross-check between them recorded as disagreement, never silently
  reconciled — the same two-source no-shared-failure-mode principle as the
  cross-cut splitter.
- **Licences — three, split by what each stage actually claims** (review
  finding 6: the single licence as first written contradicted the
  reference-first ladder — a clearly separable connector shell with
  unreconstructable freeform detail could never become a thing, so C2 could
  never place it even as a reference mesh, defeating C2's main value):
  - **C1 partition licence** (claims a *geometric subobject*, §0):
    boundary/separability evidence (the two detection signals), partition
    stability under the declared perturbations, exact triangle ownership
    under the assignment invariant, and closure accounting per §4.6. Fitting
    partitions beyond one → `partition-nonunique` (renamed per §A.5), all
    candidates recorded. **Reconstruction is not part of this licence.**
  - **C2 delivery licence** (claims a *delivery-component*): the source
    triangle slice re-hashes to its recorded digest and the placement is
    reproduced exactly as a reference mesh. Failure to reconstruct lowers a
    component's status to `recognized-reference`; it never erases an
    otherwise-licensed component boundary. The base itself may remain a
    reference component at C2.
  - **C3 reconstruction licence** (upgrades status): the existing primitive
    or parametric gates pass on the sub-mesh, with §4.6's virtual closure in
    force. This is where "the base reconstructs with thing sub-meshes
    removed AND each claimed thing's sub-mesh reconstructs" now lives — as
    the *upgrade* gate, per thing, not as the admission ticket.
  Sub-mesh extraction stays in the stage that needs it first: C1's stability
  and closure accounting are statements about sub-meshes, so the stage that
  evaluates the partition licence is the stage that extracts them. The first draft put
  extraction in PR C-5 while C1 shipped in C-4, which left C-4 unable to
  evaluate its own license, unable to claim a single thing, and unable to
  reach its ≥ 8 acceptance floor. Extraction moves into C-4 (§6): it is
  host-side, writes no Fusion geometry, and the reconstruction it feeds is
  the existing fit/plan pipeline run on a sub-mesh — the same thing C-4
  already does at the pause, before any Fusion write. C-5 keeps what needs
  a document open: thing-local datum seeding, placement records, and
  assembly emission.
- **Floors and refusals:** `thing-below-support` (area enumerated),
  `interface-pierced` (through-hole; face pair + connecting regions named),
  `interface-not-planar` (nearest fits + band census), R5's merged clusters.
  Scale/aspect priors are candidate-ordering tie-breakers only; the fit
  outcome decides every verdict.

### 4.2 Evidence and closure

Per §2 items 2–4, unchanged from the consensus: interface records own band
geometry; caps are `inferred-by-contact` with the basis separating the
measured plane from the asserted flushness; deviation partitions
`graded-against-scan` / `asserted-by-contact`; placement carries the per-DOF
vector with `rotation-unconstrained` and canonical representatives. All new
schema fields, never prose.

### 4.3 Recursion and budget

The existing single-part pipeline is the recursion body. Depth default 2
(base + things), declared; deeper only when that level's own interface
evidence licenses it, same rule recursively. Work bound: triangle counts
partition across units, so total work stays linear in mesh size × d_max.
Determinism: sub-mesh seeds derive from `_region_hash` content addresses
(KTD-8 extended to derived sources — the resume-cache contract is part of
the extraction PR, not an afterthought). Refusals stay per-thing: one
unreconstructable connector never poisons the board or the cans.

### 4.4 Assembly emission (`plan-assembly`)

Host-side planner emits an **assembly program** (versioned, closed-vocabulary,
hash-bound — R16's discipline lifted to the assembly level: component list
with stable thing ids, mesh-slice digests, transforms, status tags,
attribute payloads); the Fusion-side executor is deliberately dumb, per the
006 doctrine. Naming is geometric, not taxonomic (`thing-04 (cyl-ish
d10×h12) [reference]`); the product never claims "capacitor" without
classification evidence. Editability for a placement is the occurrence-move
check: perturb `transform2`, assert recompute, restore, assert the hash
chain — the componentization analogue of R11, and it works on a
reference-mesh component, which is why editability does not wait for
parametric fidelity. Re-emission is update-in-place by stable thing id
(preserving user renames and user-added joints) as far as PC-10 permits;
what it does not permit is recorded, not worked around silently.

### 4.5 The ladder, mapped

| Stage | Ships | Fusion surface | Gated by |
| --- | --- | --- | --- |
| C1 | assignment record, evident-things census, complexity witness, **thing sub-mesh extraction** (the license is evaluated on the sub-meshes, §4.1) | none (extraction and the license's reconstruction passes are host-side; record reviewed at the existing pause, before any Fusion write) | seg PRs 1/3/4 + branch merge |
| C2 | grounded base + N placed reference-mesh components + ≤1 residual component | components, occurrences, `transform2`, mesh bodies | C1 + PC-1/2/7 (PC-9/10 for its report) |
| C3 | per-thing status upgrades reference → primitive → parametric; two-level coverage; R3 layers 2–3 | geometry inside existing components; structure untouched | C2 + PC-11; parametric prisms also on 2.5D lane PRs 4–6 |
| C4 | instancing verdicts + occurrences; lattice-gated patterns | `addExistingComponent`, pattern features | C3 + PC-3/8 |
| C5 | rigid as-built joints / rigid group; grounded-base semantics | `AsBuiltJoints`, `RigidGroups`, `isGrounded` | C4 + PC-4/5/6 |

### 4.6 The virtual closure surface — the contract PC-11 probes, stated as an algorithm's input (review finding 7; missing decisions 14, 15 and 18, decided)

"Closure is supplied by the interface record, never by fabricated triangles"
was a principle without a representation. Downstream, 001's loop ladder
*requires* a closed, consistently wound mesh and a positive signed volume —
its manifold check refuses anything less — and a thing sub-mesh cut off a
base is open at its contact loop **by construction**. The measured reality:
all 46 slabs on Dig-Next-2 are `slab-section-open`. Without this contract,
scan fit coverage can rise while RC stays zero. The contract:

- **A virtual closure surface is transient** — generated on demand from the
  licensed contact plane and the recorded cut loop; **never added to the
  source mesh**, never serialized as triangles into any dump.
- Evidence class **`inferred-by-contact`** (bottom caps against an observed
  base face) or **`inferred-by-continuation`** (R5's uniquely determined
  lateral completions); the class rides every derived quantity.
- **Used for**: topology (manifold check passes with the cap in place),
  winding inheritance, section closure, event creation at the cap's station,
  and volume. **Excluded from**: scan-deviation grading and original-area
  conservation — it lives in the derived-geometry ledger (002 §A.2 rule 7).
- **Carries uncertainty**: the interface plane's fitted sigmas, the cut
  loop's polyline residuals, and the placement uncertainty of the thing it
  closes; derived events cite them.
- **The base side is symmetric** (decision 15): removing a thing leaves an
  unobserved footprint in the base's face. If the base model fills it, that
  fill is `inferred-by-contact`, enumerated separately, never graded against
  scan.
- **Globally open captures** (decision 18 — boundaries unrelated to any
  component interface, e.g. the scan's 158 boundary edges): v1 policy is the
  hard refusal **`capture-boundary-unclosed`** (new closed-set token). A
  locally licensed closure procedure for capture boundaries is a registered
  follow-up (owner: emission lane), not smuggled in here. 002's segmentation
  and this design's componentization do not, by themselves, close a capture
  — this token is what says so by name. **Scope:** the token is
  stage-scoped to closure-dependent operations. C1 partition and C2
  reference-mesh delivery proceed — neither needs a closed mesh — while C3
  per-thing reconstruction and every slab/loop-ladder operation refuse with
  it. The partial record is the ordinary one: affected components stay
  `recognized-reference` with the token recorded, and stage gates and
  acceptance claims count them exactly there, never as reconstruction
  failures of some other name.

### 4.7 Placement observability and instancing, formalized (review finding 12; missing decisions 19, 20, 21 and 26, decided)

The per-DOF Boolean vector of §2 item 4 was the right instinct and an
insufficient representation: it cannot express a cylinder's continuous
rotational stabilizer, a sphere's full one, a square component's discrete 90°
ambiguity, coupled translation/rotation uncertainty, permutation ambiguity
among identical things, or a near-symmetric canonical axis that flips under
noise. The pose record becomes:

- a canonical local frame (from the thing's own datum, deterministic rule
  declared);
- the world occurrence transform, with the convention (decision 19) fixed as
  `local_vertices = inverse(T_occurrence) · source_world_vertices`, and a
  round-trip requirement: the occurrence transform must reconstruct the
  source-world placement within declared `placement_roundtrip_tol` (default
  1e-6 · extent, rationale: numerically meaningful against float64 transform
  composition, far below any measured placement uncertainty);
- a **pose information matrix** with its **rank and nullspace** — the
  information matrix is the one serialized form (decision 20 sharpened): its
  nullspace *is* the set of unconstrained directions, which is the
  observability claim the record makes. A covariance may be carried as a
  derived convenience, never as the source of the rank/nullspace fields — a
  covariance nullspace means the opposite (zero variance), and unbounded
  modes have no finite covariance representation at all;
- a **continuous stabilizer group** (none / axis-rotation / full-rotation);
- **discrete alternate transforms** (the 90° class and its kin), enumerated;
- an **evidence class per constrained mode**, closed set: `observed`,
  `relation-inferred`, `contact-inferred`, `canonical-only`,
  `unconstrained`.

The occurrence-move editability check proves Fusion editability; it does
**not** prove the initial semantic frame was observed — the record's
per-mode evidence classes are what carry that claim, and `canonical-only`
modes stay visibly canonical in the component note (consensus item 4's
labelling, kept).

**Instancing** (decision 21): "fitted parameters agree within joint
uncertainty" is pairwise and nontransitive; union-find over such edges is
banned (the same rule as 002 §A.6). Instance classes form by **complete
linkage or a joint class fit**, contested members enumerated, with
tier-specific licences:

| Instance tier | Required agreement |
| --- | --- |
| reference mesh | observed mesh congruence on compatible visibility masks; same interface evidence class |
| primitive | joint primitive fit; support, span, and a placement-equivalence class |
| parametric | same reconstruction-program topology and licensed parameter vector |
| pattern | instance licence **plus** a separately gated lattice fit (unchanged) |

**Rigid grouping is a delivery policy, not evidence** (decision 26): C5's
rigid group / as-built joints are labelled **`pose-locked-for-delivery`**
unless attachment evidence exists — a static scan establishes current
relative pose, not zero physical degrees of freedom. `motion-not-evidenced`
stands beside it, unchanged.

---

## 5. Key technical decisions

- **KTD-C1 — One stage owns the assembly partition invariant.**
  `plan-decomposition` asserts {base, thing, interface, residual} totality
  exactly once; coverage cites it. (R1.)
- **KTD-C2 — Refusal is the trigger; the parsimony comparison is the
  both-fit resolver; the complexity witness is always on.** No magic number
  decides "is this a component"; the census makes sure silence never hides a
  choice. (R3.)
- **KTD-C3 — Componentize-first.** C2 ships placed reference meshes before
  any thing is reconstructed; upgrading fidelity happens inside a fixed
  assembly structure. Recognition is decoupled from reconstruction because
  the evidence bars differ by an order of magnitude. (Product §3, adopted.)
- **KTD-C4 — The interface is a first-class owner; caps are
  `inferred-by-contact`; deviation never blends its classes.** (Consensus.)
- **KTD-C5 — Placement is the occurrence transform with per-DOF evidence;
  symmetry recorded, canonical representative declared; joints are semantics
  added last with the weakest honest claim; kinematics never inferred.**
  (Consensus + product doctrine.)
- **KTD-C6 — Merged pseudo-things for lateral contact clusters, named,
  permanent-limit registered.** (R5.)
- **KTD-C7 — Every new threshold through `_declared_number`** (δ derivation,
  support floor, instancing k, lattice residual, escalation floor, recursion
  depth, canonical-azimuth rule). (House rule.)
- **KTD-C8 — Probes before trust: no Fusion API behavior in §2's table is
  load-bearing until its PC ticket has a recorded report.** (Plan-010
  discipline.)

---

## 6. PR sequence

**[Ordering superseded 2026-08-20: the canonical cross-lane order lives in
`docs/reviews/2026-08-20-oracle-design-review.md` §2 — PR C-1 is itself the
step that lands the §0 ontology in the schema (the bootstrap that satisfies
the prerequisite; nothing precedes it on this lane), and C-2/C-3 require
C-1; C-4 only after 002 §A.2's lineage contract is implemented; slab tracks
+ virtual closure (001 §A, §4.6) before C-6. PR contents below stand,
amended per §0/§4.1/§4.6/§4.7.]**

One worker, one PR at a time, tree green after each, each PR names the
measured claim it must move **in scoreboard terms** (RC recognition
coverage / C componentization count / E editability / H honesty margin) and
commits the numbers into its description. Schedulable-now PRs are marked ▶;
blocked PRs name their gate.

### PR C-1 ▶ — schema: evidence classes, assignment record, status vocabulary

- **Files:** `src/fusion_design/reconstruction_program.py` +
  `mesh_source.py` (evidence class `observed`/`inferred-by-contact` with
  basis records; `thing-split` operation under the `derived_from` schema;
  assignment-record schema + validator; component-status vocabulary and
  roll-up tri-state; deviation partition fields), tests (malformed-record
  refusals for every new field).
- **Size:** ~250–350 added.
- **Measured claim:** 11-part corpus byte-identical (schema is additive and
  nothing populates it); validators reject each malformed case by name.
  Scoreboard: H unchanged-clean (the new vocabulary is closed-set from
  birth).
- **Risk:** schema churn breaking readers — mitigated exactly as
  segmentation PR 1: additive fields, corpus byte-identity is the gate.

### PR C-2 ▶ — probe battery (live Fusion, recorded)

- **Files:** probe scripts + recorded probe reports for PC-1..PC-10, PC-12
  (§8), Fusion version stamped, one live writer at a time per the standing
  rule.
- **Size:** ~200–300 of probe code; the deliverable is the reports.
- **Measured claim:** every §2-table API behavior moves from [I] to a
  recorded verdict; C2's design either stands or is revised *before* its
  emitter is written. Scoreboard: none directly — this PR exists to keep
  later claims honest.
- **Risk:** a probe failing (e.g. PC-2 mesh-into-component) — that is the
  point; see §10 on PC-2 as the design's biggest single unknown.

### PR C-3 ▶ — assembly emitter on a synthetic fixture (C2 capability)

- **Files:** `src/fusion_design/` new `plan_assembly.py` (assembly program
  planner) + executor extension (components, occurrences, grounded base,
  mesh bodies, attributes, update-in-place per PC-10's verdict), synthetic
  two-thing fixture (block + two placed pegs, hand-authored assignment
  record, ground-truth transforms), occurrence-move editability check,
  tests.
- **Size:** ~300–400 added.
- **Measured claim:** on the fixture — browser tree matches the assignment
  record exactly; transforms round-trip within declared epsilon;
  occurrence-move check passes; re-emission preserves a user rename.
  Scoreboard: E gains the occurrence-move check as a scored move; C stays 0
  on real parts (honestly — the fixture is not a corpus part).
- **Gate:** PC-1/2/7 recorded (PR C-2).
- **Risk:** building the emitter before real detection exists — accepted
  deliberately: the fixture decouples emitter correctness from detection
  availability, and R2 shows detection is the long pole.

### PR C-4 — `plan-decomposition`: detection + assignment (C1 ships)

- **Blocked by:** segmentation PRs 1, 3, 4 merged, and the #53+#54 base
  merge (F5, F6).
- **Files:** `src/fusion_design/` new `mesh_decomposition.py` (island-chain
  detector over `classify_loops`/`congruence`; interface census with derived
  δ; cross-check; trigger + license evaluation; assignment production +
  one-assert invariant; complexity witness), **the sub-mesh extractor**
  (`thing-split` under `derived_from`, winding inheritance,
  resume-cache/determinism contract per KTD-8) — moved here from C-5 because
  the C1 license is evaluated on extracted sub-meshes and cannot be evaluated
  without them (§4.1) — stage wiring between fit and plan,
  `reconstruction_coverage` citation, tests incl. an adversarial-assignment
  property check (dropped region, double-assigned region, cluster with no
  chain, chain with no component).
- **Size:** ~600–700 added (the extractor is ~150–200 of it).
- **Fusion surface:** still none. Extraction and the license's reconstruction
  passes are host-side; the stage ends at the existing pause with a record.
- **Measured claim (Dig-Next-2, merged head):** assignment record with
  ≥ 8 things (§7 C1 row); assignment coverage ≥ 0.80; every residual island
  itemized; **the detection census published** (numerator side; the C
  denominator comes from the independent human-reviewed evident-things
  table, per R4 as amended — the acceptance run is scored against that
  table, not against its own census). 11-part corpus: geometry
  byte-identical; census lines additive (`things: 0,
  decomposition-not-triggered` + witness numbers).
- **Risk:** δ mis-estimation (A4 — visible as band-area growth, a census
  number); detection under-count (the floor-8 acceptance fails → the run's
  census says which candidates fell where, and the floor argument is
  re-examined against evidence, not tuned silently).

### PR C-5 — thing sub-mesh extraction + placement + C2 on Dig-Next-2

- **Blocked by:** PR C-4; PC-11 runnable within this PR (host-side).
- **Files:** thing-local datum seeding + `local-datum-disagrees`, per-DOF
  placement records, assembly emission wired to real assignments. (The
  sub-mesh extractor is C-4's, per §4.1; this stage consumes the sub-meshes
  and their recorded digests rather than producing them.)
- **Size:** ~150–250 added.
- **Measured claim (Dig-Next-2):** C cell moves 0 → 1 base + ≥ 8 placed
  occurrences (§7 C2 row); every component's mesh slice re-hashes to its
  recorded digest; occurrence-move check passes on ≥ 1 real thing; H: every
  non-thing square millimetre named (residual + below-support + interface
  band areas sum with the claimed areas to total mesh area — the
  area-conservation audit extended to assignment level).
- **Risk:** PC-12 scale problems at ~20 mesh bodies — probed before this PR
  lands (PR C-2).

### PR C-6 — per-thing reconstruction + the both-fit comparison (C3)

- **Blocked by:** PR C-5; parametric prism upgrades additionally on the 2.5D
  lane's PRs 4–6 (primitive upgrades are not).
- **Files:** recursion driver (things re-enter the pipeline as subtrees),
  status upgrade machinery, two-level coverage roll-up (no blending), R3
  layers 2–3 (escalation floor + parsimony comparison + claim rule), tests.
- **Size:** ~350–450 added.
- **Measured claim (Dig-Next-2):** ≥ 3 things at `recognized-primitive` (§7
  C3 row); 100% of things report per-thing coverage including 0-with-reason;
  base-lane numbers unregressed. Corpus: identical-or-explained, with the
  R3 floor demonstrably uncrossed (or crossed with `monolithic-preferred`
  and unchanged geometry).
- **Risk:** span-gate arithmetic on can arcs (A2) — if the cans refuse, the
  stage still ships (C3's contract is per-thing honesty, not a can count)
  and the acceptance floor's failure is the finding.

### PR C-7 — instancing + patterns (C4)

- **Blocked by:** PR C-6; PC-3/PC-8 recorded; reuses the equivalence-class +
  contested-list idiom from segmentation PR 2.
- **Size:** ~250–350 added.
- **Measured claim (Dig-Next-2):** the can trio resolves to a recorded
  verdict with measured deviations (§7 C4 row); occurrence count ≥
  component-definition count with the difference explained by
  `instance-licensed` records only; scoreboard reports definitions and
  occurrences separately so the count *dropping* reads as the success it is.

### PR C-8 — attachment semantics (C5)

- **Blocked by:** PR C-7; PC-4/5/6 recorded.
- **Size:** ~150–250 added.
- **Measured claim (Dig-Next-2):** 100% of thing occurrences jointed or
  rigid-grouped to the grounded base; whole-assembly move test passes
  (translate base, two thing-to-base distances unchanged); the
  base-parameter-edit claim asserted exactly as far as PC-6 verified and no
  further.

Sequence rationale in one line each: C-1 makes every later claim
recordable; C-2 makes every Fusion claim honest before code bets on it; C-3
decouples the emitter from the long-pole detection; C-4 is the stage the
whole lane exists for and correctly waits for its evidence; C-5 turns the
record into the headline product; C-6 adds fidelity inside a fixed
structure and closes the R3 backstop; C-7/C-8 add the multiplicative edit
and the semantics, last because each is a claim on top of claims.

---

## 7. Dig-Next-2 acceptance numbers per stage

Floors are acceptance (a run below the floor fails the stage's gate and the
census must say why); bands are [I] predictions on record to be falsified.
Denominator: ~40 distinct things assumed from visual inspection —
`unmeasured` until the **independent human-reviewed evident-things table**
exists (R4 as amended; authored before PR C-4's acceptance run, never by the
detector being scored).

| Stage | Acceptance floor | Prediction [I] | Also required |
| --- | --- | --- | --- |
| C1 | ≥ 8 things assigned; assignment coverage ≥ 0.80; partition assert green | 8–20 things; coverage 0.85–0.95 | evident-things census published; every residual island itemized with reason; corpus geometry byte-identical |
| C2 | ≥ 8 placed occurrences matching C1 exactly; occurrence-move check on ≥ 1 thing | tree = 1 base + 8–20 things + ≤ 1 residual | mesh slices re-hash; no assembly wrapper on any corpus part |
| C3 | ≥ 3 things `recognized-primitive`; 100% of things report coverage-with-reason | cans 3/3 primitive; most SMD stay `reference`, named | base-lane numbers unregressed; recognition count unchanged from C2 |
| C4 | can-trio verdict recorded with measured deviations | `instance-licensed`: 1 definition × 3 occurrences | definitions and occurrences reported separately |
| C5 | 100% things attached; whole-assembly move test passes | rigid group over ~10–20 members within PC-5's measured cost | base-parameter claim limited to PC-6's verdict |

Populations expected outside the count, each named: 0402-class passives →
`below-support-floor` in residual (area enumerated); through-hole parts →
`interface-pierced`; touching clusters → merged pseudo-things counted as one
with `cluster_candidate_count`; anything else → per-thing refusals. The
honest headline at C2 is "board + O(10–20) placed things, every non-thing
square millimetre named" — not "40 components."

---

## 8. Probe queue (the empiricist's, ordered by what gates which stage)

Gate C2 (run first, in PR C-2): **PC-2** mesh body into a specific component
+ transform inheritance + units (load-bearing, see §10) · **PC-1** occurrence
lifecycle, `transform2` round-trip, position-capture/timeline behavior ·
**PC-7** attributes + naming limits/persistence · **PC-12** *(added)* scale:
~20 mesh bodies of ~25k triangles in one document — create, save, reopen,
interaction cost · **PC-10** idempotent re-emission (update-in-place vs
recreate) · **PC-9** export honesty (mesh bodies through STEP/F3D; the
export report names drops as `export-omits-mesh-bodies`).

Gate C3 (host-side, in PR C-5/C-6): **PC-11** *(added)* winding inheritance
through `thing-split` — extract a thing sub-mesh from a production dump,
verify `material_side` verdicts on its walls match the parent's, and that
the loop ladder runs on a sub-mesh open at its cut loop with closure
supplied by the interface record.

Gate C4: **PC-3** master-edit propagation across occurrences (measure, don't
assume) · **PC-8** component patterns from occurrence collections in
parametric mode.

Gate C5: **PC-4** as-built joints on mesh-only components · **PC-5** rigid
group incl. mesh-only members, cost at ~20 · **PC-6** joint semantics under
base recompute (do jointed occurrences follow a moved face or hold absolute
position — C5's honest claim is whatever this shows).

---

## 9. Permanent limits and deferred register (so nobody re-proposes silently)

| item | status | licence to revisit |
| --- | --- | --- |
| Lateral contact, `lateral-interface-unobserved-and-partition-nonunique` (R5 as amended) | **permanent limit only when no distinguishing evidence exists**: merged pseudo-thing per cluster, named | distinguishing evidence per amended R5 (crease/gap, occlusion contour, unique `inferred-by-continuation` completion, matched instance, second view), improved capture, or a new evidence channel |
| Through-hole parts (`interface-pierced`) | deferred, first follow-up | multi-patch interface design |
| Kinematic joint inference | rejected (`motion-not-evidenced`) | motion evidence (multiple captures) |
| Taxonomic naming ("capacitor") | deferred | a classification lane with its own evidence and refusals |
| Depth ≥ 3 recursion | deferred by default (depth 2 declared) | that level's own interface evidence, same rule recursively |
| Multi-body-part delivery (Design X shape) | rejected | — |
| Slab-native decomposition as owner (geometry Design 2) | rejected as owner; its chain detector adopted inside Design 1 | — |

---

## 10. The single probe whose answer most changes the design

**PC-2 — creating a mesh body inside a specific component from host-side
triangle data, inheriting the occurrence transform.** Every stage from C2 up
stands on it: if no API route places our sub-mesh *into a component* (or the
mesh body ignores the occurrence transform, or units mangle), then
"component whose only geometry is its slice of the scan" — the entire
componentize-first spine, the headline stage, and the progressive-fidelity
story — needs a different vehicle (baked-vertex meshes would destroy
placement-as-editable-value; external-reference inserts would change the
document model). Nothing else in the queue invalidates the design's spine;
PC-2 could. It runs first, in PR C-2, before any emitter code is written.

---

## 11. Verification contract

- Every PR re-runs its measured claim against the Dig-Next-2 artifacts
  (host-side until C2; one live Fusion writer at a time thereafter, version
  recorded) and commits the numbers in its description; a claim without its
  number does not merge.
- 11-part corpus regression on every PR: byte-identical through PR C-4 **on
  the record with the additive census fields removed** — adding `things: 0`
  and the complexity witness changes the serialized bytes by construction, so
  "byte-identical" and "census lines additive" cannot both be true of the raw
  file and the contract as first written was unsatisfiable. The comparison is
  therefore against a normalized record: every key this lane introduces is
  dropped from both sides, and what remains must match byte for byte. The new
  keys are checked separately, by name and value, against what the run
  predicts. Identical-or-explained after C-4; no assembly wrapper ever appears
  on a single-thing part.
- The assignment invariant's adversarial property check (PR C-4) enters the
  standard suite; any later detector must pass it unmodified.
- Area conservation at assembly level: Σ(base) + Σ(things) + Σ(interfaces) +
  Σ(residual, itemized) = total mesh area, asserted per run from PR C-5 on —
  the scoreboard's H cell moves from "by construction" to measured for
  assemblies.
- Scoreboard reporting per PR: which of RC / C / E / H moved, by how much,
  with C reported as definitions and occurrences separately from C4 on.
- Probe reports carry Fusion version and date; a probe's verdict is quoted,
  not paraphrased, wherever a PR relies on it.
- The review pause stays where it is: the assignment record is reviewed
  before any Fusion write, exactly as the reconstruction program is today.

## 12. Definition of done

1. PRs C-1..C-5 merged (C1 + C2 shipped: the assignment record and the
   placed-reference-mesh assembly on Dig-Next-2, floors per §7); C-6..C-8
   merged or their gates recorded as not met, with the census that decided.
2. On Dig-Next-2 (merged head): the browser tree shows a grounded base +
   ≥ 8 placed, named, statused things + ≤ 1 residual component; every
   non-thing area named; the evident-things census exists and the scoreboard
   C row cites it.
3. The 11 production parts: unchanged single-body outputs, `things: 0,
   decomposition-not-triggered` + complexity witness on record.
4. The R3 backstop (escalation floor + parsimony comparison) merged before
   or with C3, so no future emitter improvement can silently silence the
   trigger.
5. The permanent-limits register (§9) reflected in `references/` doctrine so
   the merged-pseudo-thing disposition is user-visible documentation, not
   tribal knowledge.

## 13. Follow-ups (outside this design's PRs)

1. Multi-patch interface design for through-hole parts (`interface-pierced`
   population from the first C1 census sizes the prize).
2. Classification lane (taxonomic naming with evidence) — entirely optional
   polish; geometric naming is the contract.
3. FTO note: the prior-art doc (2026-08-19-008) does not survey
   assembly-decomposition patents (product proposal §8's flag). Route to the
   FTO owner alongside the segmentation design's US11017535B2 item before
   PR C-4 ships a fit-remove-recurse loop; the mitigating shape argument
   (same procedure, evidence-licensed, no sensitivity escalation) mirrors
   design -002 §4.7 and should be recorded with it.

---

## Amendment A — external-review incorporation (2026-08-20)

*Companion to the in-place revisions (§0, §4.1, §4.6, §4.7, R4, R5). Source:
`docs/reviews/2026-08-20-oracle-design-review.md`. This section records the
decisions that had no natural in-place home, the vocabulary renames, and the
one open item this lane owns.*

### A.1 Vocabulary additions (closed sets, field-scoped)

The closed sets are **per field**, and PR C-1's malformed-record validators
check each field against its own set — a token that is valid in another
field's set is rejected in this one:

- `component_status`: + `componentized-geometric`,
  `physical-thing-evidenced` (§0); `recognized-reference` keeps its meaning
  as the C2 floor status.
- `evidence_class`: + `inferred-by-continuation` (R5).
- `refusal`: + `capture-boundary-unclosed` (§4.6).
- `delivery_semantics`: + `pose-locked-for-delivery` (§4.7).
- `lineage_state`: + `invalidated-by-partition` (inherited from 002 §A.2).

### A.2 Pipeline position vs frame and relationships (missing decision 7, decided; composition-table row 3 resolved)

`plan-decomposition` runs **after `segment-fit` and before `frame-relate`**
in 010's stage order. The global frame and every relationship proposal are
computed against the **post-decomposition partition version**; anything
computed against an earlier version is invalidated by 002 §A.2 rule 5, so an
implementation that runs frame-relate early pays a recompute, never a
correctness bug. C1's host-side reconstruction passes are an accepted
transitional state under 010's migration (010 M2–M3 move them in-Fusion;
same records either way) — the review's "undecided" row is decided as:
order fixed here, host/Fusion placement follows 010's migration schedule.

### A.3 Interface mechanics (missing decisions 11, 12, 13 — decided)

- **Contact-curve bootstrap (11).** Two passes. Pass 1: cut the dual graph
  by the *plane-distance* band (non-base triangles within δ of the accepted
  base face's plane); the boundary loops of the components that detach are
  the **contact curves**. Pass 2 (authoritative): the interface band is
  re-derived as the non-base triangles within δ of those curves (R1's
  definition, now with its input defined); the pass-1 band is discarded.
  Both passes and their δ derivations are recorded.
- **Overlapping bands from multiple base faces (12).** A triangle within δ
  of contact curves from two or more candidate base faces is owned by the
  interface of the **nearest curve**, distance ties broken on quantized
  values (007 §2.3 idiom); the contested set is enumerated in the interface
  record, never silently resolved.
- **Interface triangles at C2 (13).** Delivered inside the **base
  component's mesh body slice** (the joint is physically continuous with the
  base), while ownership in the assignment record stays `interface-j` — the
  browser shows every triangle exactly once, the evidence never blends the
  owner classes, and the deviation over band triangles still grades against
  the joint (consensus item 2, unchanged). Ownership and delivery are
  therefore **distinct identities with distinct digests**: the assignment
  record's *ownership digest* hashes each owner's triangle set
  (`interface-j` separate from `base`), while C2's *delivery digest* hashes
  the delivered mesh slice per component (the base slice including its
  interface bands). H audits ownership digests; C2's re-hash check audits
  delivery digests; a change in either forces re-emission of the affected
  component, and neither digest is ever derived from the other. Revisited
  at C5 when joints give the band a semantic home; the revisit is
  registered here so it cannot happen silently.

### A.4 Open item (registered, not decided): stable thing-ID migration

Missing decision 22. Region identity is content-addressed over triangle
index sets, so any segmentation-boundary change changes the hash — but PC-10
re-emission and user-rename preservation need ids stable across runs. A
design note (candidate: stable ids assigned at first licence, carried
through 002 §A.2 lineage links, with a declared match threshold for
re-identification across partition versions) is **required in PR C-4 before
PR C-5 relies on stable ids**. Owner: PR C-4.

### A.5 Vocabulary renames applied (review collision table)

| Old (this doc) | New | Notes |
| --- | --- | --- |
| `thing-boundary-ambiguous` (three senses) | `decomposition-model-ambiguous` (R3's both-fit, neither decisive), `partition-nonunique` (multiple fitting partitions, §4.1/R5), `lateral-interface-unobserved` (the evidence condition inside R5's renamed limit) | each use-site now names one sense; the R3 claim-rule's token is `decomposition-model-ambiguous` |
| thing-support floor derived from `min_feature_size` (F9) | `min_thing_support_extent` (initialized from the same declared 1.6 mm, own rationale) | lands with PR C-1's schema |
| `inferred-by-contact` doing double duty as lineage | evidence classes (`evidence_class`) and source lineage (`source_derivation` / `derived_from`) stay separate schemas | already the design's intent; now stated |

### A.6 R3's comparison, tightened by finding 1

R3's held-out comparison decides **model preference between two readings of
the same surface**; under §0 it can promote a decomposition to
*geometric-subobject* status only. It is never evidence of physical
thinghood — the injection-molded-lid case defeats it by construction, since
both readings explain the observed exterior. `decomposition-preferred-on-held-out`
therefore licenses `componentized-geometric` delivery, and the physical-thing
channels of §0 remain the only path to `physical-thing-evidenced`.
