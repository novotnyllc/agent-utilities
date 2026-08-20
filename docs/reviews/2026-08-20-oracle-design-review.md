---
title: "review: external design review of the mesh→CAD design corpus (issue #20) — verdict, judgment, incorporation"
date: 2026-08-20
role: preserved external review + incorporation record
reviewer_model: "GPT-5.6 Sol (ChatGPT), thinking tier: Pro"
reviewer_session: "oracle 0.17.3, session mesh-cad-design-review-7, run 7"
reviewer_runtime: "28m22s; ~78.8k tokens up / ~9.95k down; model selection verified via chatgpt-model-picker at 2026-08-20T19:29:58Z"
reviewed:
  - docs/plans/2026-08-19-007-research-reconstruction-algorithms.md
  - docs/plans/2026-08-19-010-design-fusion-native-architecture.md
  - docs/plans/2026-08-20-001-design-25d-event-decomposition.md
  - docs/plans/2026-08-20-002-design-scan-segmentation.md
  - docs/plans/2026-08-20-003-scoreboard-mesh-to-cad.md
  - docs/plans/2026-08-20-004-design-componentization.md
review_prompt: "adversarial pre-implementation review of 002/004 (next builds), 003's instrument, and cross-document composition, against the measured v0.12.0 baseline (8 of 16 emit, area-weighted RC 23.3%; scan fit 11.1%, 2.13 GB program artifact; regressions: exit-0/0.0%-area emission, five discontinuous-slab-stack profile-ambiguous refusals, interior-slab gating worsened)"
verdict: "REVISE BEFORE IMPLEMENTATION — 4 P0, 10 P1, 13 survived attacks, 26 missing decisions"
status: incorporated 2026-08-20 — every finding judged (none rejected); amendments landed
  in 001/002/003/004 on the same branch as this file
---

# External design review — verdict, judgment, and incorporation record

This file preserves, verbatim, the full answer of the external adversarial
design review run before implementation of designs -002 (scan segmentation)
and -004 (componentization). The reviewer saw the six documents above plus the
measured v0.12.0 baseline addendum; it did not see source code. §1 below is
this repository's judgment of each finding — rendered against the documents
*and* the measured record, not rubber-stamped; §2 is the canonical corrected
implementation order every design doc now defers to; §3 is the disposition
ledger for the 26 missing decisions; §4 records the accept-with-modification
arguments in full (there are no outright rejections). The verbatim review
follows in §5.

One check applied to every finding before acceptance: **does it contradict a
measured result?** The corpus contains one refuted expert prediction (the
σ-scale hypothesis, refuted to the digit — design -002 addendum, shipment 1 /
PR #54 readout), so "an expert said so" is not evidence here. No Oracle
finding contradicts a measured result: the review's own load-bearing examples
(the 0.0%-area exit-0 emission, the 2.13 GB artifact, the 46 open slab
sections, the five discontinuous-stack refusals, the 443-plane confetti) are
the measured record, cited correctly.

## 1. Judgment: the fourteen findings

| # | Sev | Finding (short) | Judgment | Incorporated in |
| --- | --- | --- | --- | --- |
| 1 | P0 | 004 proves geometric separability, not physical thinghood | **accept** | 004 §0 (ontology), §4.1, amendment A1 |
| 2 | P0 | Region-tree proof establishes termination, not meaningful segmentation | **accept** | 002 amendment §A.1 (reason-aware split licence, T1–T5, aggregate productivity, reserved validation) |
| 3 | P0 | No shared partition-lineage / invalidation contract | **accept** | 002 amendment §A.2 (first-class contract; 004 references it, never restates it) |
| 4 | P0 | Emission success has no non-vacuity condition | **accept** | 003 §1.1 (rewritten), amendment; measured by the exit-0 / 0.0%-area regression |
| 5 | P1 | 001 lacks slab-stack continuity; join-only rule internally inconsistent | **accept** | 001 amendment §A.1 (slab-track graph), §A.2 (event states), §A.3 (tokens) |
| 6 | P1 | C1 reconstruction licence contradicts reference-first C2 ladder | **accept** | 004 §4.1 (licence split C1/C2/C3) |
| 7 | P1 | No usable virtual-closure and winding contract | **accept** | 004 §4.6 (virtual closure surface); 001 amendment §A.4 |
| 8 | P1 | Cross-cut only conditionally percolation-resistant | **accept** | 002 amendment §A.3 (separation certificates; proxy refinement into the correctness path) |
| 9 | P1 | Moran block-bootstrap null is circular; correlation not propagated | **accept** | 002 amendment §A.4 (frozen scan-level correlation model, consumed by Moran + held-out + covariance + relations) |
| 10 | P1 | Datum bootstrap corpus-specific; fallback not in required shipment | **accept-with-modification** (§4.1 below) | 002 amendment §A.5 (declared initial domain; lifecycle contract) |
| 11 | P1 | Scoreboard gameable three ways (RC ladder, H unenforceable, C circular) | **accept** (all three) | 003 §1.1/§1.4/§1.5 + amendment |
| 12 | P1 | Per-DOF placement and instancing need a formal observability model | **accept-with-modification** (§4.2 below) | 004 §4.7 (pose observability + tiered instancing) |
| 13 | P1 | "No fix exists" lateral-contact claim too broad | **accept** | 004 R5 (amended), `inferred-by-continuation`, renamed limit |
| 14 | P1 | Relationship rewrite correctly identified but sequenced too late | **accept-with-modification** (§4.3 below) | 002 amendment §A.6 (PR 0b promotion, complete-linkage semantics, hard budgets) |

Tally: **11 accept, 3 accept-with-modification, 0 reject.** The cross-document
composition table, the vocabulary-collision table, and the corrected
implementation order are accepted whole; the vocabulary renames are applied in
the four amended documents (007/010 were reviewed but carry no PR sequencing
and no colliding *new* vocabulary; the one 007 rename — `min_feature_size` →
`min_resolvable_surface_scale` in its §4.2 sense — is registered in §3 as a
follow-up doc edit rather than silently skipped).

## 2. Canonical implementation order (stated once — every design doc defers here)

This order supersedes the PR ordering statements in 001, 002, 003 §3, and 004
§6. The PR *contents* in those documents stand; their relative order is this:

1. **PR 0a — non-vacuous emission gate** (emission lane): the five positive
   conditions of 003 §1.1 (amended) plus the four refusal tokens; then
   **recompute the "emits" census** — the v0.12.0 "8 of 16 emit" figure is
   flagged pending this recomputation (the measured 0.0%-area exit-0 part
   does not count as emitting).
2. **PR 0b — relationships rewrite** (was 002 PR 2): equivalence classes with
   complete-linkage/joint-fit semantics, pruning census, jsonl streaming,
   **hard artifact budgets** with `relationship-budget-exceeded`. Before any
   PR that re-materializes a scan program (the measured 2.13 GB artifact
   makes "before the splitter" no longer early enough — it must precede the
   region-tree PR's baseline re-runs).
3. **Amended split licence** (002 §A.1): reason-aware splitting, T1–T5
   defined, aggregate productive-split rule, reserved validation data —
   design-complete before the region-tree skeleton lands.
4. **Region-tree storage/partition skeleton** (was 002 PR 1), carrying the
   partition-lineage and invalidation contract (002 §A.2) from birth.
5. **Cross-cut splitter + independently calibrated correlation model in the
   same shipment** (was 002 PR 3 + PR 4; the shipment-1 readout already
   forced the merge — 002 addendum): plus separation certificates (§A.3)
   and the lateral-cell proxy refinement in the correctness path.
6. **004 schema, Fusion probes, synthetic assembly emitter** (PRs C-1..C-3)
   — PR C-1 is itself the step that puts the object ontology (004 §0) into
   the schema; C-2/C-3 require C-1, not some prior schema step.
7. **`plan-decomposition`** (PR C-4) — only after partition lineage and
   invalidation (002 §A.2) are implemented and asserted.
8. **Slab tracks and virtual closure** (001 §A.1–§A.4; 004 §4.6) — before
   C3 per-thing parametric recursion (PR C-6).
9. **Recompute RC as `RC-scripted-nonempty`**; never promote it over
   `RC-built` / `RC-verified` (live verified delivery).

Conditional PRs (002 PR 5/PR 6 escalations, 004 C-7/C-8) keep their census
and probe gates and slot after the step that produces their census.

## 3. The 26 missing decisions — disposition ledger

"Decided" means the decision now appears, with rationale, in the named
document; "open" means it is registered there as an explicit open item with
an owner PR — none remains silently missing.

| # | Decision | Disposition | Where |
| --- | --- | --- | --- |
| 1 | Exact T1–T5 terminal rules | **decided** | 002 §A.1 |
| 2 | Which rejection reasons license splitting | **decided** | 002 §A.1 |
| 3 | Aggregate productive-split formula + validation-data separation | **decided** | 002 §A.1 |
| 4 | Datum confidence, contamination handling, lifecycle across peels | **decided** (confidence floors, lifecycle) / **open** (contamination & background rejection — owner: seg PR 3) | 002 §A.5 |
| 5 | Deterministic graph-block construction and refit for Moran bootstrap | **decided** | 002 §A.4 |
| 6 | Same measured correlation length for held-out and covariance | **decided** (yes — one frozen record, all four consumers) | 002 §A.4 |
| 7 | Order of decomposition vs global frame and relationship inference | **decided** (decompose after segment-fit, before frame-relate; earlier frame/relations invalidated by lineage) | 004 §A.2 |
| 8 | Partition-version and fit/relationship invalidation protocol | **decided** | 002 §A.2 |
| 9 | Semantic boundary: geometric subobject / physical thing / delivery component | **decided** | 004 §0 |
| 10 | Independent source for the C denominator | **decided** (human-reviewed evident-things table on acceptance fixtures; `C = unmeasured` on unlabeled scans; raw counts always) | 003 §1.4; 004 R4 |
| 11 | How contact curves are found before an interface band is defined | **decided** (two-pass bootstrap: plane-band cut → cut loops become contact curves → band re-derived as δ of the curves, second pass authoritative) | 004 §A.3 |
| 12 | Overlapping bands from multiple candidate base faces | **decided** (nearest-contact-curve ownership, quantized tie-break, contested set enumerated) | 004 §A.3 |
| 13 | Geometry representing interface-owned triangles at C2 | **decided** (delivered inside the base component's mesh slice, owner stays `interface-j` in the record; ownership digest and delivery digest are distinct, each audited by its own consumer; revisited at C5) | 004 §A.3 |
| 14 | Virtual-cap representation, uncertainty, orientation, area rules | **decided** | 004 §4.6 |
| 15 | Inferred base surface beneath a removed thing | **decided** (same mechanism, `inferred-by-contact`, derived-geometry ledger, never in original-area conservation) | 004 §4.6 |
| 16 | Slab-track correspondence and temporary-multiple-body policy | **decided** | 001 §A.1 |
| 17 | Loop correspondence across the three slab constancy sections | **decided** (complete-linkage match on centroid+area within the constancy tolerance; unmatched loop names the refusal) | 001 §A.2 |
| 18 | Policy for open capture boundaries unrelated to component interfaces | **decided** (v1: hard `capture-boundary-unclosed` refusal; licensed local closure is a registered follow-up, owner: emission lane) | 001 §A.4 |
| 19 | Local-coordinate and occurrence-transform convention | **decided** | 004 §4.7 |
| 20 | Pose symmetry/nullspace schema | **decided** | 004 §4.7 |
| 21 | Tier-specific instancing metrics and class formation | **decided** | 004 §4.7 |
| 22 | Stable thing-ID migration when segmentation boundaries change | **open** — owner: PR C-4 (design note required before C-5 re-emission relies on stable ids) | 004 §A.4 |
| 23 | Non-vacuous emission success criteria | **decided** | 003 §1.1 |
| 24 | Exact per-stage triangle-disposition state machine for H | **decided** | 003 §1.5 + amendment |
| 25 | Relationship and program artifact hard budgets | **decided** | 002 §A.6 |
| 26 | Whether rigid grouping is evidence or an explicit delivery policy | **decided** (delivery policy; `pose-locked-for-delivery` unless attachment evidence exists) | 004 §4.7 |

Also registered: 007's `min_feature_size` → `min_resolvable_surface_scale`
rename (vocabulary table row 1) is a follow-up doc edit to 007 §4.2/§14,
owner: whoever next touches 007 (the runtime key migration lands with seg
PR 3, which introduces `min_station_separation`).

## 4. Accept-with-modification arguments (the evidence, in full)

### 4.1 Finding 10 — datum bootstrap

The Oracle states the proxy-grower fallback "is not actually in the required
shipment." Half right. 002 PR 5's gate (c) already makes `datum-unavailable`
itself a licence — "without it a no-datum scan has no splitter at all…
because a part with no datum never reaches the cell census" (002 §6 PR 5) —
so the design had already noticed the gap the Oracle re-derives, and the
fallback does fire the run after a no-datum part first appears. What the
design had *not* done is choose between the Oracle's two honest scopes, which
left the first no-datum part's outcome (a refusal, not a segmentation)
implicit. **The decision, now made in 002 §A.5: declared initial-domain
limitation** — orthogonal-datum scans are the supported initial domain;
a no-datum scan terminates `segmentation-datum-unavailable`; PR 5 gate (c)
stays as the designed, licensed escalation. Rationale: every measured fixture
(one PCB scan, eleven enclosures) is strongly datum-oriented; shipping a
minimal no-datum splitter now would ship unmeasured code with no fixture to
prove its measured claim against, violating the house rule that every PR
names the measured number it must move. The modification is that the finding's
"choose one" is answered with the option the design was already one sentence
short of, not with new machinery.

### 4.2 Finding 12 — pose observability and instancing

Accepted in substance: a per-DOF Boolean vector cannot express a cylinder's
continuous stabilizer, a square component's 90° ambiguity, or coupled
translation/rotation uncertainty, and pairwise "within tolerance" instancing
is nontransitive. The modification is scope-honesty about what already
existed: 004 already prescribed canonical representatives with a declared
deterministic rule and `canonical-not-observed` labels (consensus item 4),
and already routed instancing through "the equivalence-class + contested-list
idiom from segmentation PR 2" (PR C-7) — and complete linkage is the house
clustering rule (001's event merge uses it by name). So the amendment
formalizes and extends (information matrix, nullspace, stabilizer group,
discrete alternates, per-mode evidence class, tier table) rather than
replacing a design that had none of it. `pose-locked-for-delivery` for C5 is
adopted verbatim.

### 4.3 Finding 14 — relationship rewrite sequencing

Accepted in substance: promote to PR 0b, add hard budgets, define the cluster
algorithm. Two factual corrections to the finding's framing, for the record:
(a) 002 §3.5 had already promoted the rewrite *ahead of the splitter* ("the
relationships rewrite must land **before** the cross-cut, not merely in the
same cycle") — the Oracle's genuinely new point is that the 2.13 GB measured
artifact means it must also precede the region-tree PR's baseline re-runs,
which is accepted and is what PR 0b now means; (b) 002 §4.5 already handled
non-transitivity by enumerating `contested_split`/`contested_join` in full —
what it did not do, and now does (002 §A.6), is name the cluster-formation
algorithm (complete linkage with a maximum-pairwise-deviation certificate, or
a joint shared-parameter fit with per-member rollback) that makes every
implied pair reconstructible, which is the condition under which `not-omitted`
is a valid disposition.

---

# 5. The review, verbatim

Everything below this line is the reviewer's answer, unedited.

---

# Verdict

**REVISE BEFORE IMPLEMENTATION.**

The core ideas are not uniformly flawed:

* 002’s region tree is a useful containment structure.
* The cross-cut is a credible first splitter for PCB-like, strongly datum-oriented scans.
* 004’s progression from reference components to parametric components is sound as a product architecture.
* 003 correctly distinguishes fit coverage, scripted coverage, and live-delivered coverage.

But the designs currently cross three unjustified boundaries:

1. A rejected fit is treated as evidence that a surface should be partitioned.
2. A geometrically separable partition is treated as evidence of distinct physical things.
3. A successful process exit is treated as evidence that something was emitted.

Those can produce false semantics or flattering metrics while every local invariant still passes.

Two changes should precede the planned implementation sequence:

* **Promote the relationship rewrite to PR 0**, ahead of the region-tree PR. The current 2.13 GB artifact means “before the splitter” is no longer early enough.
* **Add a non-vacuity emission gate in the same PR 0 cycle.** Exit 0 with zero claimed source area must be a named refusal, not an emission.

---

# Ranked findings

## 1. P0 — 004 proves geometric separability, not physical thinghood

**Document:** 004 §2, R3, §4.1

### Failure scenario

Take a single injection-molded enclosure lid with:

* four integral cylindrical bosses,
* two integral ribs,
* a raised connector surround.

Against an accepted base plane, each protrusion can:

* detach when a narrow contact band is removed,
* meet the band along a closed curve,
* reconstruct independently,
* leave a reconstructable base after removal.

That is exactly the proposed `separable-at-interface` and submesh reconstruction license. The design would classify the bosses and ribs as “things,” despite their being integral features of one physical part. The always-on interface census makes this possible even when the monolithic model fits. A held-out fit comparison cannot resolve the error because both representations explain the observed exterior geometry. 

The design currently moves directly from a surface partition to components and occurrences while defining the goal in terms of distinct physical things. Those are not equivalent propositions. 

### Required fix

Define four separate concepts and never collapse them:

| Concept               | Claim supported                                                   |
| --------------------- | ----------------------------------------------------------------- |
| `surface-region`      | These triangles share a geometric model.                          |
| `geometric-subobject` | The exterior surface admits a stable separable partition.         |
| `physical-thing`      | Independent-object evidence exists beyond geometric separability. |
| `delivery-component`  | The output policy chooses a Fusion component as an editing unit.  |

A geometric subobject can become a useful Fusion component, but its status must be something like `componentized-geometric`, not `physical-thing-evidenced`.

Physical-thing evidence needs an independent channel, such as an observed gap or seam, disconnected source topology, a mutually occluding boundary, a uniquely evidenced assembly interface, or an explicit caller policy. “Base and subobject both reconstruct” is not that channel.

The 004 design should be rewritten around **componentization as an editing decomposition**, with physical thinghood as a stronger optional claim.

---

## 2. P0 — The region-tree proof establishes termination, not meaningful segmentation

**Document:** 002 §4.1

On an immutable finite triangle set, termination is salvageable if every successful split produces at least two nonempty proper children and depth is bounded. The problem is that 002 does not define its referenced T1–T5 rules, the exact split floor, or a complete productive-split predicate. It states that a rejected fit above the floor splits, and calls the split unproductive only when **none** of the children improves the parent residual. 

### Failure scenario

Consider one smooth, nonprimitive surface:

* a gently domed casting,
* a warped sheet,
* a freeform grip,
* a shallow saddle.

Its best plane or cylinder fit is correctly rejected. A splitter divides it. One small child happens to be locally flatter and improves its residual. That single child is enough to avoid `split-unproductive`. Repetition yields local patches that pass plane gates. The tree terminates, the partition invariant is perfect, and primitive-fit coverage rises, but the program has converted one unsupported continuous surface into primitive confetti.

That contradicts 007’s foundational rule that geometry explained by no justified primitive stays unclaimed rather than being absorbed. 

### Required fix

Splitting must be **reason-aware**:

* Rejections indicating mixed support can license a split: multimodal residuals, disconnected support, incompatible normal families, multiple competing primitive candidates.
* Rejections indicating insufficient information must terminate without splitting: support floor, unidentifiable parameters, capture boundary, insufficient span, missing datum.
* Wrong-kind residual structure can license a split only when the proposed children jointly explain a meaningful fraction of the parent.

Replace the existential productivity rule with an aggregate comparison over identical held-out support:

* area-weighted child loss versus parent loss,
* complexity penalty,
* minimum fraction of parent area improved,
* explicit cost for new boundaries,
* no child counted unless its own support and gates pass.

Also reserve blocked validation data that was not used to choose the split. Otherwise the tree adaptively searches partitions and then evaluates the winning partition on the same evidence.

---

## 3. P0 — 002 and 004 do not have a shared partition-lineage and invalidation contract

**Documents:** 002 §4.1; 004 R1; 003 §1.5; 010 execution model

004 correctly notices that an interface band can cut through a terminal region, so it refines the region tree using `interface-split`. It then asserts a new assembly partition. 

What it does not specify is what happens to evidence derived from the old terminal:

* the primitive fit and covariance,
* support-span verdict,
* Moran and held-out verdicts,
* relationships involving the parent,
* datum contributions,
* coverage claims keyed to the old region,
* cached reconstruction decisions.

### Failure scenario

A large accepted board plane is split into:

* retained base surface,
* several interface strips.

If the base child inherits the parent plane fit, its covariance and held-out evidence refer to triangles it no longer contains. If the parent remains addressable, coverage can count both parent and children. If relationships were computed before `plan-decomposition`, they refer to a region that is no longer terminal.

The hash-chain discipline in 010 protects artifact identity but does not itself define semantic invalidation after a partition mutation. 

### Required fix

Introduce a single immutable lineage model:

```text
source_triangle_id
    -> partition_version
        -> terminal_region_id
            -> owner_id
                -> fit/plan/emission disposition
```

Rules:

1. Every partition mutation creates a new `partition_version`.
2. Every child carries its parent ID and exact source-triangle subset.
3. A parent fit is never inherited as an accepted child fit.
4. Every non-interface child is re-fit and re-gated.
5. Relationships, frame contributions, and program claims against replaced nodes are invalidated.
6. Consumers must cite the exact partition version they consumed.
7. Inferred surfaces live in a separate derived-geometry ledger and never enter original-area conservation.

This is also the substrate required to make H enforceable. The current scoreboard acknowledges that its area-conservation audit does not yet exist. 

---

## 4. P0 — Emission success has no non-vacuity condition

**Document:** 003 §1.1
**Measured regression:** exit 0, 0.0% source-area coverage

003 correctly makes emission all-or-nothing and gives zero credit until a reduced program has actually emitted. 

But “emitted” is still being derived from transaction success rather than a positive result. The measured empty success proves the gap.

This also interacts badly with 004: an empty successful monolithic run produces no refusal token, so refusal-triggered decomposition may not run.

### Required fix

A successful parametric reconstruction must satisfy all of these:

* at least one parameter-driven feature was created,
* at least one immutable source region is claimed,
* the union of claimed source triangles has positive area,
* at least one resulting body has positive volume or explicitly licensed surface area,
* `created` and `checked` entries were appended only after the corresponding API operations succeeded.

Add closed refusal tokens:

* `no-emittable-claims`
* `emission-empty`
* `emission-zero-source-area`
* `emission-zero-geometry`

An intentionally emptied `replan-without` result is a named “nothing reconstructable” outcome, not an emission.

The current “8 of 16 emit” figure should be recomputed after this gate. The 0.0%-area case does not count as an emitting part.

---

## 5. P1 — 001 lacks a slab-stack continuity model, and its join-only rule is internally inconsistent

**Document:** 001 A/C
**Measured regression:** five `profile-ambiguous` failures caused by discontinuous slab stacks

001 constructs one slab for every consecutive event pair and verifies each slab internally at three stations. It does not establish correspondence between material components across adjacent slabs. 

The contradiction is explicit:

* `relation_to_below` may be `disjoint`.
* Yet slab 0 is `new-body`, every later slab is `join`, and every slab depends on its predecessor because “join needs a body.” 

A disjoint slab cannot necessarily join the predecessor. The current whole-part fallback and resulting multi-loop ambiguity are predictable consequences of this missing model.

### Failure scenario

A connected U-shaped or bridged part can have:

* two disjoint cross-sectional material components at lower stations,
* a later slab where they merge,
* one connected final solid.

A PCB assembly can have numerous protrusions that are born and die at different stations. A global one-profile-set-per-slab chain cannot represent either case without transient multiple bodies or explicit tracks.

### Required fix

Add a **slab-track graph**:

* Nodes: connected material components in each slab.
* Edges: evidence-backed correspondence across adjacent events.
* States: continuation, birth, death, branch, merge, temporary disconnection.
* A track may begin as `new-body`.
* Tracks may later join when contact is evidenced.
* A track that never joins is either a true multi-body result, a componentization candidate, or a named refusal.

Remove the whole-part fallback. Use specific refusals:

* `slab-track-ambiguous`
* `slab-stack-disconnected`
* `slab-track-merge-unlicensed`
* `multi-body-output-unlicensed`

The fresh interior-slab regression also indicates that “plane exists at station” is being allowed to become “topology-changing event.” Event records need separate states:

* candidate geometry station,
* corroborating station,
* topology-changing event.

Only the last one divides slab tracks. Coalescing congruent sections is not enough to establish this.

---

## 6. P1 — C1’s reconstruction license contradicts the reference-first C2 ladder

**Document:** 004 §4.1 and §4.5

004 says a thing can be claimed only when both the base and every claimed thing submesh reconstruct under the existing gates. 

But C2 is explicitly supposed to ship placed **reference-mesh** components before per-thing primitive or parametric reconstruction, with those upgrades deferred to C3. 

### Failure scenario

A connector shell is clearly separable at the board interface but contains complex freeform details that cannot reconstruct parametrically. Under the stated C1 license it cannot become a thing, so C2 cannot place it even as a reference mesh. That defeats the main value of C2.

### Required fix

Separate the gates:

* **C1 partition license:** boundary/separability evidence, stability, exact ownership, and closure accounting.
* **C2 delivery license:** the source triangle slice and placement can be reproduced exactly as a reference mesh.
* **C3 reconstruction license:** primitive or parametric gates pass.

Failure to reconstruct must lower the component’s status to `recognized-reference`; it must not erase an otherwise justified component boundary.

The base should likewise be allowed to remain a reference component at C2.

---

## 7. P1 — Per-thing recursion has no usable virtual-closure and winding contract

**Documents:** 001 B; 004 §4.2/§4.3 and PC-11
**Measured reality:** all 46 PCB slabs are `slab-section-open`

001’s loop-material logic requires a closed, consistently wound mesh and a positive signed volume. Otherwise it refuses orientation and therefore loop classification. 

A thing submesh extracted by cutting it off a base is necessarily open at the contact loop. 004 says closure is “supplied by the interface record” and “never by fabricated triangles,” but downstream sectioning, volume, winding, and manifold algorithms require an actual topological surface representation. 

PC-11 is a probe request, not an algorithmic contract. 

### Required fix

Define a **virtual closure surface**:

* transient and never added to the source mesh,
* generated from the licensed contact plane and cut loop,
* evidence class `inferred-by-contact`,
* used for topology, winding, section closure, event creation, and volume only,
* excluded from scan deviation and original-area RC,
* carrying plane, loop, and placement uncertainty.

The same issue exists on the base side: removing a component leaves an unobserved footprint in the board’s top face. If the base model fills that footprint, it is also inferred-by-contact and must be accounted for separately.

For globally open captures, define one of two explicit outcomes:

1. A locally licensed closure procedure for each relevant boundary loop.
2. A hard `capture-boundary-unclosed` refusal.

002 segmentation and 004 componentization do not, by themselves, solve the scan’s 46 open slab sections. Without this decision, scan fit coverage may rise while RC-emitted remains zero.

---

## 8. P1 — The cross-cut is only conditionally percolation-resistant

**Document:** 002 §4.2

The algebra is valid: intersecting two labels prevents a merge whenever at least one label separates the surfaces. The unsupported claim is that the two label sources “share no failure mode.” 

### Concrete shared failures

1. **Lateral surfaces:** all lateral and ambiguous normal families are collapsed into one station-free super-cell. For those surfaces, only the local dihedral CC remains. A tangent plane/cylinder transition, adjacent cylinders joined by a smooth fillet, or two vertical faces connected through scan waviness can percolate with no cell barrier.

2. **Same-family, same-station surfaces:** a flush component top and board patch at the same height can share both labels.

3. **Oblique mechanical parts:** a 45° plane can land in the ambiguity family, lose its station, and join the lateral super-cell.

4. **Curved/freeform surfaces:** normal-family and station cells fragment a single legitimate surface into many regions.

### Required fix

Record a separation certificate for every produced boundary:

```text
separation_basis = local | cell | both
```

Then enforce:

* A `both` boundary is strong.
* A `cell`-only boundary needs a joint-fit comparison.
* A `local`-only boundary in a lateral super-cell is not percolation-protected and must run the refinement splitter when the joint fit rejects.
* A child boundary with neither an observed crease nor a statistically decisive competing-model split cannot license separate emitted features.

The proxy refinement cannot remain merely a future census-triggered optimization for mixed lateral cells. It is part of the correctness path for the cases where the cross-cut’s second discriminator has been deliberately removed.

The measured PCB top/bottom split remains a strong use case because the station cells actually separate those faces.

---

## 9. P1 — Moran’s proposed block-bootstrap null is circular and does not propagate to the other correlation-sensitive gates

**Documents:** 002 §4.4; 007 §7.3 and §10.3

002 proposes estimating correlation length from each candidate plane’s own residual semivariogram and using that value to calibrate its Moran null. It then leaves held-out and parsimony gates unchanged. 

### Failure scenario

A shallow cylinder or bowed sheet is fitted as a plane. Its residuals contain a broad systematic trend. The semivariogram interprets that trend as a long correlation length. Large bootstrap blocks then preserve or normalize away the structure that Moran was supposed to reject.

The candidate is effectively helping define its own null.

The same measured correlation also affects:

* covariance inflation,
* parameter uncertainty,
* relation licensing,
* blocked held-out leakage.

007 itself says the current AR(1)-style effective-sample correction is approximate.  Its held-out split uses a fixed spatial scale rather than the proposed measured correlation length. 

### Required fix

Establish one scan-level or regime-level correlation model independently of the candidate being tested:

1. Estimate correlation from high-confidence local patches or high-pass local residuals.
2. Prefer directional variograms; use a conservative maximum range when anisotropic.
3. Freeze the resulting correlation record before candidate acceptance.
4. Use it consistently for:

   * Moran bootstrap blocks,
   * held-out block separation,
   * covariance/effective sample size,
   * relation and snap uncertainty.
5. Refit the primitive inside each bootstrap replicate; otherwise the null does not include parameter-estimation effects.
6. Name `correlation-model-unidentified` when the variogram has no stable sill or the region is too small.

PR 4 remains a hard co-requisite for the splitter, as the addendum concludes. The design of PR 4 is not yet implementation-complete.

---

## 10. P1 — The datum bootstrap is corpus-specific, and the documented fallback is not actually in the required shipment

**Document:** 002 §4.3 and PR 5

The measured ladder is:

```text
GFG confetti -> 443 small planes -> orthogonal datum -> cross-cut
```

The fallback is an offset-Hough frame, then a proxy grower when no orthogonal frame exists. 

But the proxy grower is placed in conditional PR 5, triggered only by a corpus census or an observed `datum-unavailable` case. 

### Failure scenarios

* A smooth rotational part produces no reliable orthogonal plane family.
* A curved surface produces planar confetti whose normals form a misleading frame.
* A scan includes a pedestal or table fragment whose planes dominate the object datum.
* Only one major normal family is visible.
* Accepted patches come from scan texture rather than stable geometric families.

### Required fix

Choose one honest scope:

* Include a minimal no-datum splitter in the required PR 3/4 shipment, or
* Declare orthogonal-datum scans as the supported initial domain and terminate with `segmentation-datum-unavailable`.

Also define:

* minimum independent normal families,
* minimum spatial dispersion of datum evidence,
* contamination/background handling,
* confidence and ambiguity margins,
* whether the global datum is frozen across peel passes,
* how per-pass station re-estimation is versioned.

Re-estimating stations on the residual while keeping the datum fixed may be reasonable. Re-estimating both without a lifecycle contract can make region identities depend on extraction order.

---

## 11. P1 — 003’s scoreboard is directionally right but currently gameable in three distinct ways

### 11.1 RC-emitted is an upper bound, not the final headline

003 already acknowledges that RC-emitted is host-side scripted coverage and that live delivered coverage must replace it when available. 

Against the v0.12.0 reality, call the 23.3% figure **RC-scripted**, not simply RC-emitted.

It can be raised by:

* scripting one broad but geometrically poor extrude,
* splitting unsupported surfaces into locally accepted patches,
* planning only easy large-area slabs while dropping feature-rich small areas,
* overlapping source claims between slab, shell, fillet, and hole archetypes,
* empty exit-0 transactions unless finding 4 is fixed.

The headline ladder should be:

```text
RC-scripted-nonempty   host-side upper bound
RC-built               Fusion transaction created geometry
RC-verified            built + deviation accepted + editability proof
```

`delivered_area_fraction` is the natural name for the last one. Report area-weighted corpus RC, macro-average per part, median, and zero-count; one large easy surface must not hide a population of failed parts.

### 11.2 H is not currently enforceable

The intended H rule is sound: every unclaimed unit must be named. But the document explicitly says the area-conservation audit does not exist. 

Run D correctly notices that naive cross-stage sums double-count regions and that the current coverage account drops identities needed for an audit. 

H becomes enforceable only when:

* every original triangle has exactly one primary disposition per stage,
* partition lineage is exact,
* every transition is checked,
* every refusal token cites the executed gate evidence,
* inferred geometry is counted separately,
* generic `residual` cannot be used as reason laundering.

The target should be **silently unclaimed triangle count = 0**, not “approximately zero.” Area tolerance is unnecessary when ownership is checked by immutable triangle IDs.

### 11.3 The component denominator cannot be produced by the detector being scored

003 correctly says C’s denominator is “distinct physical things evident,” and that it is unmeasured for Dig-Next-2. 

004 says the first C1 run will publish the evident-things census and thereby make the denominator measured. 

That is circular. If the detector finds 8 of approximately 40 things and then publishes a census of 8, C becomes 8/8.

Use:

* independently annotated ground truth where available,
* a manually reviewed evident-things table for acceptance fixtures,
* `C = unmeasured` on ordinary unlabeled scans,
* raw counts on those scans: candidates, licensed geometric subobjects, physical things evidenced, component definitions, occurrences.

---

## 12. P1 — Per-DOF placement and instancing need a formal observability model

**Document:** 004 consensus, §4.2, C4

Recording `rotation-unconstrained` and choosing a canonical representative is the right instinct.  But a per-DOF Boolean vector is insufficient for:

* continuous symmetry, such as rotation around a cylinder axis,
* full rotational symmetry of a sphere,
* discrete 90° ambiguity of a square component,
* coupled translation/rotation uncertainty,
* repeated identical things with permutation ambiguity,
* nearly symmetric geometry whose canonical axis flips under small noise.

### Required placement model

Represent the pose estimate as:

* a canonical local frame,
* a world occurrence transform,
* a pose information or covariance matrix,
* its rank and nullspace,
* a continuous stabilizer group,
* discrete alternate transforms,
* evidence class per constrained mode:

  * observed,
  * relation-inferred,
  * contact-inferred,
  * canonical-only,
  * unconstrained.

Define local coordinates explicitly:

```text
local_vertices = inverse(T_occurrence) * source_world_vertices
```

The occurrence transform must reconstruct the source-world placement within a declared tolerance. An occurrence-move test proves Fusion editability; it does not prove that the initial semantic frame was observed.

### Required instancing model

“Fitted parameters agree within joint uncertainty plus aligned mesh deviation” is too weak and pairwise tolerance is nontransitive. 

Use tier-specific licenses:

| Instance level | Required agreement                                                                     |
| -------------- | -------------------------------------------------------------------------------------- |
| Reference mesh | observed mesh congruence on compatible visibility masks; same interface evidence class |
| Primitive      | joint primitive fit, support, span, and placement-equivalence class                    |
| Parametric     | same reconstruction-program topology and licensed parameter vector                     |
| Pattern        | instance license plus a separately gated lattice fit                                   |

Classes should be formed by complete linkage or a joint class fit, with contested members listed. Do not use union-find over pairwise “within tolerance” edges.

C5’s rigid group or as-built joint should be labelled `pose-locked-for-delivery` unless attachment evidence exists. A static scan establishes current relative pose, not zero physical degrees of freedom.

---

## 13. P1 — The “no fix exists” lateral-contact claim is too broad

**Document:** 004 R5

The design is correct for one precise case:

> The observed exterior surface is compatible with multiple internal partitions, and no additional evidence or declared prior distinguishes them.

That is information-theoretically non-identifiable. The merged pseudo-thing is the honest result. 

It is not true for all laterally touching things.

Potentially sufficient evidence includes:

* an observed crease or gap,
* a T-junction or occlusion contour,
* two independently supported primitive continuations that determine a unique hidden contact,
* a matching complete instance elsewhere,
* a second view exposing part of the interface.

The design already permits an unobserved bottom surface as `inferred-by-contact`. It can consistently permit a uniquely determined lateral completion as `inferred-by-continuation`, with:

* the inferred interface area separately enumerated,
* no scan-deviation claim on that area,
* alternative partitions tested,
* refusal when more than one completion survives.

Even a unique geometric split still does not prove two physical things. It licenses a geometric decomposition, not physical identity.

The permanent limit should therefore be renamed:

```text
lateral-interface-unobserved-and-partition-nonunique
```

---

## 14. P1 — The O(n²) relationship rewrite is correctly identified but now sequenced too late

**Document:** 002 §3.5, §4.5, PR 2
**Measured reality:** 2.13 GB program before cross-cut

002 correctly says the relationship rewrite must precede the fit-count explosion caused by the splitter. 

The current artifact means it must also precede the region-tree PR’s full baseline reruns. Promote it ahead of the existing PR 1, or make PR 1 incapable of materializing a program.

Add immediate declared budgets:

* maximum proposed relationship records,
* maximum serialized relationship bytes,
* maximum planning memory,
* named `relationship-budget-exceeded` refusal before allocation.

JSONL streaming reduces peak serialization memory but does not fix O(n²) candidate generation.

There is also a semantic defect in calling tolerance relations equivalence relations. “Within 2°” is not transitive. The design mentions contested joins and splits but does not define a cluster algorithm that makes every implied pair reconstructible. 

Use either:

* complete-linkage classes with a maximum pairwise deviation certificate, or
* a joint shared-parameter fit whose every member passes its own rollback gate.

Only then is `not-omitted` valid. Otherwise the reduced pairs are `not-tested` or contested.

---

# Cross-document composition verdict

| Interface                                    | Verdict                                                                                                                                                                                                                                                                            |
| -------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **002 region tree → 004 assignment**         | Not composable yet. Interface refinement changes the partition after fits, frame evidence, and possibly relationships exist. Findings 2–3 must be resolved.                                                                                                                        |
| **004 per-thing recursion → 001 slabs**      | Not composable yet. Extracted submeshes are open, inferred contact events are unspecified, and slab tracks do not support discontinuity. Findings 5–7 block C3.                                                                                                                    |
| **004 stage placement → 010 pipeline**       | Undecided. 010 orders `segment-fit → frame-relate → plan`; 004 inserts decomposition “between fit and plan” without saying whether it precedes or invalidates `frame-relate`. 004 also describes C1 reconstruction passes as host-side while 010 moves the pipeline into Fusion.   |
| **001 events → 002 raw-coordinate stations** | They answer different questions, correctly noted by 002. They need different names and records; sharing only a merge helper is reasonable.                                                                                                                                         |
| **003 H → 002/004 hierarchy**                | Requires versioned lineage, not area-only arithmetic.                                                                                                                                                                                                                              |
| **003 C → 004 census**                       | Invalid unless the denominator is independently established.                                                                                                                                                                                                                       |

## Threshold and vocabulary collisions

| Current term                           | Collision                                                                                     | Recommended split                                                                               |
| -------------------------------------- | --------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `min_feature_size`                     | Normal-neighbourhood limit in 007; station peak separation in 002; thing-support floor in 004 | `min_resolvable_surface_scale`, `min_station_separation`, `min_thing_support_extent/area`       |
| `datum-unavailable`                    | Segmentation bootstrap, reconstruction frame, and thing-local frame                           | `segmentation-datum-unavailable`, `reconstruction-frame-ambiguous`, `thing-frame-ambiguous`     |
| `component`                            | Unclaimed connected surface component versus Fusion/physical component                        | Rename existing diagnostic to `unclaimed-surface-component`                                     |
| `thing-boundary-ambiguous`             | Both-fit model choice, nonunique geometric partition, and invisible lateral interface         | Separate `decomposition-model-ambiguous`, `partition-nonunique`, `lateral-interface-unobserved` |
| `profile-ambiguous`                    | Multi-body station, discontinuous stack, loop composition, whole-part fallback                | Replace with cause-specific slab and profile tokens                                             |
| `inferred-by-contact` / `derived_from` | Evidence class versus source lineage                                                          | Keep separate schemas: `evidence_class` and `source_derivation`                                 |
| `RC-emitted`                           | Script existence versus actual build/delivery                                                 | `RC-scripted`, `RC-built`, `RC-verified`                                                        |

---

# Attacks the designs survive

These are clean under their stated preconditions.

1. **Dropped or duplicated triangles in a fixed region-tree split:** the strict partition assertion and adversarial splitter property test are the correct defense. 

2. **Literal infinite recursion on a fixed finite mesh:** proper nonempty children plus `d_max` is sufficient. The unresolved problem is semantic oversegmentation, not raw nontermination.

3. **Dihedral percolation between the PCB’s top and bottom faces:** the station-cell intersection is a valid independent separator for those two measured surfaces. The cross-cut is well motivated for that fixture. 

4. **Axial fragmentation of cylindrical walls:** collapsing lateral families and removing station from lateral labels is the correct correction to the first cross-cut proposal.

5. **Solving Moran by merely raising `moran_z_max`:** 002 explicitly rejects that shortcut and instead changes the null and adds a practical-amplitude floor. That design direction is correct. 

6. **Evidence inflation through smoothing or decimation:** the labels-only discipline and `derived_from` schema preserve the original mesh as the judging surface. 

7. **Interface triangles being owned simultaneously by base and thing:** 004 correctly makes the interface a first-class owner and refines terminals rather than assigning fractions of regions. The remaining problem is invalidation, not ownership intent. 

8. **Pretending an unobserved underside was scan-verified:** `observed` versus `inferred-by-contact`, and separate graded versus asserted area, is the right evidence model. 

9. **A genuinely non-identifiable lateral boundary:** merged pseudo-thing is the correct default when multiple partitions remain equally supported.

10. **Using the largest sketch profile when multiple loops exist:** 001’s profile-set resolver and ambiguity refusal are a sound replacement for the largest-area heuristic. 

11. **Fit coverage masquerading as delivered CAD:** 003 explicitly distinguishes fit, plan, scripted emission, and live delivery. The remaining change is naming RC-scripted as an upper bound. 

12. **Naively summing every named list for H:** Run D correctly recognizes that stages have different universes and that identities, not raw area sums, are required. 

13. **Progressive fidelity changing assembly structure:** C2’s fixed reference-component tree with later in-place upgrades is a good architecture once C1’s boundary license is corrected.

---

# Decisions currently missing

Implementation will otherwise be forced to choose these ad hoc:

1. The exact T1–T5 terminal rules referenced by 002.
2. Which rejection reasons license splitting and which mean “insufficient evidence.”
3. The aggregate productive-split formula and validation-data separation.
4. Datum confidence, contamination handling, and lifecycle across peel passes.
5. The deterministic graph-block construction and refit procedure for Moran bootstrap.
6. Whether the same measured correlation length replaces the held-out and covariance assumptions.
7. The exact order of decomposition relative to global frame and relationship inference.
8. The partition-version and fit/relationship invalidation protocol.
9. The semantic boundary between geometric subobject, physical thing, and delivery component.
10. An independent source for the C denominator.
11. How contact curves are found before an interface band is defined.
12. How overlapping bands from multiple candidate base faces are resolved.
13. What geometry represents interface-owned triangles at C2.
14. The virtual-cap representation, uncertainty, orientation, and area rules.
15. How inferred base surface beneath a removed thing is represented.
16. The slab-track correspondence and temporary-multiple-body policy.
17. Loop correspondence across the three slab constancy sections.
18. The policy for open capture boundaries unrelated to component interfaces.
19. The local-coordinate and occurrence-transform convention.
20. The pose symmetry/nullspace schema.
21. Tier-specific instancing metrics and class formation.
22. Stable thing-ID migration when segmentation boundaries change.
23. Non-vacuous emission success criteria.
24. The exact per-stage triangle-disposition state machine for H.
25. The relationship and program artifact hard budgets.
26. Whether rigid grouping is evidence or an explicit delivery policy.

---

# Top 3 decisions before writing code

## 1. Define what a split means at every level

Produce one closed ontology and license table for:

```text
surface split
geometric subobject
physical thing
Fusion component
```

For each transition, state:

* required evidence,
* allowed inferred geometry,
* gates,
* refusal,
* whether it contributes to RC, C, or neither.

Until this exists, 002 can create primitive confetti and 004 can componentize integral bosses.

## 2. Define one source-ownership, lineage, and non-vacuity contract

The contract must cover:

* immutable source triangle IDs,
* partition versions,
* parent/child lineage,
* invalidation after refinement,
* exact stage dispositions,
* inferred-geometry separation,
* positive-source-area emission,
* exact H conservation.

Completion criterion:

> Every original triangle has exactly one checked disposition at every stage, every mutation cites its predecessor, and no successful reconstruction can claim zero source area.

## 3. Define slab continuity and virtual closure before per-thing recursion

Specify:

* slab-track graph,
* birth/continuation/branch/merge/disjoint semantics,
* temporary body creation and later join,
* no whole-part fallback,
* virtual contact caps,
* inherited winding,
* inferred event stations and uncertainty,
* global open-capture policy.

Completion criterion:

> A discontinuous but ultimately connected stack either produces an explicit track program or a cause-specific refusal, and a cut-open thing submesh can run 001 without pretending its inferred cap was observed.

---

# Corrected implementation order

1. **PR 0a:** non-vacuous emission gate and recompute the “emits” census.
2. **PR 0b:** relationship rewrite, complete-linkage/joint-fit semantics, and hard artifact budgets.
3. Amend the region-tree split license and define T1–T5.
4. Land the region-tree storage/partition skeleton.
5. Land cross-cut and the independently calibrated correlation model in the same shipment.
6. Land 004 schema, Fusion probes, and synthetic assembly emitter only after the object ontology is corrected.
7. Land `plan-decomposition` only after partition lineage and invalidation are implemented.
8. Fix slab tracks and virtual closure before C3 per-thing parametric recursion.
9. Recompute RC as `RC-scripted-nonempty`; do not promote it over live verified delivery.

The 002 cross-cut remains worth building. The 004 progressive-component architecture remains worth building. Their current licenses and composition contracts are not safe enough to implement unchanged.


