---
title: "design: the feature hypothesis graph and bounded program search — emission as inference (issue #20)"
date: 2026-08-21
artifact_contract: ce-unified-plan/v1
artifact_readiness: design
execution: code
origin: https://github.com/novotnyllc/agent-utilities/issues/20
builds_on: docs/plans/2026-08-19-007-research-reconstruction-algorithms.md,
  docs/plans/2026-08-19-010-design-fusion-native-architecture.md,
  docs/plans/2026-08-20-001-design-25d-event-decomposition.md,
  docs/plans/2026-08-20-002-design-scan-segmentation.md,
  docs/plans/2026-08-20-003-scoreboard-mesh-to-cad.md,
  docs/plans/2026-08-20-004-design-componentization.md
source_review: docs/reviews/2026-08-21-deep-research-reconciliation.md
supersedes: "the deterministic archetype-selection premise of 005/006's planner
  and 001's join-only slab stack *as the preferred final representation*; every
  gate, refusal, and evidence rule of those designs stays in force as licences
  inside the search this document defines"
---

# Summary

The corpus's asymmetry, named by the external reconciliation and accepted
(review §1.1 B3): the upper half of the pipeline — segmentation, fitting,
gates, relationships, sections, lineage — receives sophisticated statistical
and systems engineering, while the transition *accepted geometry → chosen
archetype → emitted feature* is comparatively heuristic. A region tree with
excellent coverage can still emit a timeline a competent Fusion user rejects:
pockets encoded as slab boundaries, repeated features as independent
sketches, a shell as nested profiles, fifty surfaces as fifty unrelated
operations. Geometric fidelity does not imply program quality, and nothing in
the current planner makes the two compete.

This design makes emission the result of **explicit, competing
feature-program hypotheses** rather than the deterministic consequence of
accepted regions:

1. Every existing evidence lane feeds a **Feature Hypothesis Graph** (FHG) —
   a typed, append-only graph of hypotheses, each carrying its support, its
   uncertainty, its counter-evidence, its dependencies, and its provenance
   (§2).
2. A **closed operation vocabulary** (§3) defines what a program may say, and
   a **licence table** (§4) defines what evidence permits each operation —
   including the Boolean polarity evidence (§5) that separates a cut from a
   coincidentally concave join.
3. A **bounded, deterministic best-first search** (§7) proposes candidate
   programs over the graph and selects among them by a **lexicographic
   objective** (§6): semantic contradictions first (absolute — so no
   invalid candidate ever sets a relative gate's benchmark), then held-out
   geometric fidelity, unexplained support, unsupported inference, and
   compactness — gates, not hidden scalar weights, per house rules.
4. The winning program is emitted, rebuilt, perturbed, and re-graded by the
   machinery that already exists (006 D7, 003 §1.3-as-amended); the losing
   candidates are recorded, and a tie between materially different programs
   is a **named ambiguity**, never a silent first-rule-wins.

What the product delivers is thereby named precisely: not "the original
design intent" (unrecoverable — 005 KTD9, unchanged), but a compact,
**evidence-licensed editable design-intent hypothesis** — the canonical term
the whole corpus now uses (review §1.3).

# 1. The product object, stated once

A triangle mesh is an observation of boundary geometry. An editable Fusion
design is a generative program. The mapping is therefore not
`mesh → segmentation → fitted surfaces → B-Rep` but

```text
mesh → evidence → geometric hypotheses → feature hypotheses
     → constrained feature program → Fusion history → counterfactual proof
```

A single exterior mesh generally does not identify the historical modeling
sequence that created it; multiple programs produce the same boundary. The
deliverable is a program that (a) reproduces the observed geometry within
measured tolerance, (b) claims no operation its evidence does not license,
(c) is compact — repeated geometry shared, values not duplicated, no slab
confetti where one base+cut explains the same support — and (d) proves its
parameters causally drive the geometry they name. When several such programs
remain, the ambiguity is reported, not resolved by accident of rule order.

# 2. The Feature Hypothesis Graph

## 2.1 Node kinds (closed set)

| Layer | Node kind | Produced by | Example |
| --- | --- | --- | --- |
| surface | `surface-hypothesis` | region tree terminals + fits (002), per-region convert candidates (010), router verdicts (extrusion/revolution/helix fields) | "these 4,112 triangles are one cylinder, r = 3.001 ± 0.004 mm" |
| profile | `profile-hypothesis` | section loops with triangle provenance (001 §B), converted-body edges/silhouettes (010) | "station 3.30 mm closes this hex loop, walls from regions {…}" |
| regularity | `regularity-hypothesis` | relationship classes (002 §A.6 / 007 §8): parallel, perpendicular, coaxial, concentric, equal, tangent, symmetric, pattern, nominal-value | "these 4 bores share one diameter (class certificate attached)" |
| feature | `feature-hypothesis` | factorization over the layers above (§4; 001 Amendment B's slab factorization) | "pocket: cut, depth = station₃ − station₂, floor region r₁₇" |
| boundary | `component-boundary-hypothesis` | componentization lane (004): licensed geometric subobjects, physical-thing evidence | "thing-04's program is a separate component subtree" |

The set is closed; a new node kind is a version bump with a vocabulary
review, exactly as `ARCHETYPE_KINDS` grows today (001 V6 precedent).

## 2.2 What every node carries (mandatory fields)

- **support** — the immutable source-triangle IDs (ranges over the partition
  permutation, 002 PR 1's encoding) and/or the upstream node IDs it rests
  on. A hypothesis with no support is invalid at construction, not at
  scoring.
- **uncertainty** — the fitted sigmas / covariance of its parameters (007
  §7, inflated per the correlation record's consumer-specific derivation,
  002 §B.1), or the residuals of its profile entities.
- **counter-evidence** — every recorded gate failure, source conflict
  (`fit-source-conflict`), dissenting winding arc, or competing hypothesis
  over the same support. Counter-evidence is carried, never erased: a
  hypothesis that loses still explains why its competitor had to win.
- **dependencies** — the upstream nodes whose invalidation invalidates this
  one; partition-lineage rule 5 (002 §A.2) applies to FHG nodes verbatim:
  a node citing a replaced `partition_version` is
  `invalidated-by-partition`, recomputed or dropped, never silently kept.
- **provenance** — which lane produced it (`native-fit`, `fusion-convert`,
  `section-loop`, `relationship-class`, `slab-occupancy`,
  `decomposition-census`), with the run/record hash. Two lanes proposing the
  same hypothesis is recorded corroboration on one node, not two nodes.

The graph is append-only within a partition version: hypotheses accumulate
and carry verdicts; they are never edited in place, so the search's inputs
are stable and its record replayable.

## 2.3 The interpretation rule

**A fitted surface is evidence, never automatically a feature.** A cylinder
hypothesis may support a bore, a boss wall, a revolved exterior, a swept
profile, a fillet fragment, or an incidental cylindrical surface; which of
those it *is* — if any — is decided at the feature layer by licence (§4) and
competition (§6), not at the surface layer by kind. This is the corpus's
existing doctrine (007's detection-and-disproof; 010's "prefer Fusion for
computing geometry, never for judging it") extended one level up: the
archetype decision itself is now judged, not assumed.

# 3. The closed operation vocabulary

Program v3 (v2 = 001's slab blocks; the version discipline of 001 §Schema
deltas applies — v2 programs refuse loudly under v3 validators, replanning is
one command). **Version coordination, explicit:** v3 is a superset schema —
001's v2 slab blocks ride inside it unchanged — and 001's `PROGRAM_VERSION →
2` declaration stands for its lane until the FHG implementation PR performs
the 2→3 bump, the same cross-lane coordination 001 §Deviations item 4
already records for 009's additions; no validator ever accepts two current
versions at once. The operation set the search may compose:

| Operation | Emission surface (exists today unless noted) | Polarity |
| --- | --- | --- |
| `base-extrude` | `sketch-extrude`, `new-body` | additive |
| `boss-extrude` | `sketch-extrude`, `join` | additive |
| `cut-extrude` (pocket, slot, step, counterbore by profile) | `sketch-extrude`, **`cut`** (exercised for holes; generalized here) | subtractive |
| `revolve` (add or cut) | `revolve` archetype | either, declared |
| `hole` (bore, counterbore, countersink) | `hole` archetype | subtractive |
| `shell` | archetype kind `shell`, operation token `hollow` — 001 §D's exact vocabulary, reused unchanged (no second token is minted) | subtractive |
| `fillet` / `chamfer` | `fillet` (`finish`); chamfer is a vocabulary addition with its own licence | dressing |
| `sweep` / `loft` | 009's reserved rungs (design exists; emitters pending) | either, declared |
| `equal` (shared-parameter binding) | expression/parameter sharing on existing archetypes | inherits member polarity |
| `pattern` (rectangular/circular) | new emission surface | inherits member polarity |
| `component` | 004's assembly program | structural |
| `slab-join` | 001's slab stack — **the fallback operation**: always admissible where the slab's own 001 licences hold; the selection gates, never admission, decide whether a factored alternative beats it (001 Amendment B) | additive |

Closed set; `_reject_unknown_fields` discipline unchanged. Everything else —
coil, split, move, freeform patches — stays out of vocabulary and lands in
`unreconstructed` with its gate, exactly as today.

# 4. The licence table — what evidence permits each operation

An operation may enter a candidate program only when its licence holds. The
licences are the corpus's existing gates, relocated from "the planner's
implicit rule" to "a named admission condition the record cites":

| Operation | Licence (all conditions; each is an existing measured gate unless noted) |
| --- | --- |
| `base-extrude` | router extrusion verdict or slab-track evidence for the base body (001 §A.1); cap events at both ends; profile loops close with consistent winding |
| `boss-extrude` | persistent **added** loop across stations (occupancy difference, 001 Amendment B), material-inside verdict (§5), footprint continuity (`continuation`/`birth` track edge) |
| `cut-extrude` | persistent **removed** loop, material-outside verdict, and a licensed pre-cut base: the enclosing program element whose profile the cut subtracts from must itself be licensed over the union of both supports — a cut may never presuppose material no hypothesis claims |
| `hole` | inward cylinder (`material_side == "inside"`) matching centre/diameter within `entity_match_tolerance_mm`; full-turn or licensed-arc span; containment against the spans it crosses (001 §B composition) |
| `shell` | 001 §D's three measurements verbatim: opposing pairs, ray-cast inner/outer discrimination, one t everywhere; competes in the search against the equivalent explicit interior cuts (§6 decides; 001 §D's fallback semantics unchanged) |
| `fillet` / `chamfer` | torus/blend-cylinder adjacency to exactly two accepted primary regions with tangency (007 §6 blend rule); chamfer: planar strip at a licensed angle between two primaries, same adjacency shape |
| `revolve` | router revolution verdict; axis licensed by the datum or a coaxial class; **polarity declared and evidenced per §5** — a subtractive revolve additionally requires material-outside / occupancy-removal evidence, the same polarity bar as `cut-extrude` |
| `sweep` / `loft` | 009's rung licences, unchanged |
| `equal` | the regularity class certificate alone (complete linkage or joint fit — 002 §A.6 semantics; union-find banned): an adopted equality class licenses one shared parameter across its members, which is how equal-radius bores reach their compact representation without any lattice requirement |
| `pattern` | an `equal`-licensed class **plus** a lattice/circle fit passing its declared gate (004 consensus item 6); a class whose members are equal but not lattice-arranged stays at `equal`, and members of no adopted class stay independent — the compactness census then simply pays for it |
| `component` | 004 §0/§4.1's licences at the claimed level, unchanged — the FHG never upgrades a claim level |
| `slab-join` | the slab's own 001 licences (loop ladder, track edges). Always admissible where those hold — which is what makes it the honest floor every factored program must beat |

A candidate program containing one unlicensed operation is not scored low —
it is **not constructed**. The search space is licence-bounded by
construction, which is both the fail-closed rule and the tractability
argument.

# 5. Boolean polarity evidence

Polarity (add vs cut) is a claim about material, and it has exactly three
admissible evidence sources, in precedence order:

1. **Winding / material-side** — the loop-level consensus verdict of 001 §B
   (outward normals vs loop interior, length-weighted, consensus fraction
   declared) and the region-level `material_side`. This is the primary
   source; it needs no fit and does not inherit the fitters' coverage
   ceiling.
2. **Ray parity** — `calculateCollisionsWithRay` on closed meshes (010 V4),
   the arbiter where winding is locally degenerate.
3. **Occupancy differencing** — slab cross-section differences across
   stations (001 Amendment B): a persistent removed loop is subtractive
   evidence; a persistent added loop is additive evidence.

Contradiction between sources is a named refusal on the hypothesis
(`polarity-contradictory`, joining 001's loop-ladder family), never a vote
between unequal evidence kinds. A feature hypothesis with no polarity
evidence cannot enter any polar operation's licence — it can still be
explained by `slab-join`, whose polarity is established by the track
evidence itself.

# 6. The program-selection objective — lexicographic gates, not a scalar

House rule (003 §1.6: a single weighted scalar lets one term paper over
another; every threshold caller-declared with rationale). The reviewer
offered both forms — a weighted vector or lexicographically ordered gates —
and this corpus takes the gates. Candidate programs are compared in strict
order; a candidate failing a gate is eliminated before the next gate is
consulted; ties within a gate's declared tolerance proceed together:

1. **G1 — semantic contradictions.** Zero tolerance, no slack, and **first
   in order because every later gate is relative to the surviving set**: a
   candidate asserting a polarity against its evidence (§5), an operation
   against its licence (§4 — unconstructible anyway), a relationship its
   class certificate contradicts, or a claim level above its 004 licence is
   eliminated here — before it can serve as any relative gate's benchmark.
   A semantically invalid candidate that explains more support must never
   set the bar the valid candidates are measured against.
2. **G2 — held-out geometric fidelity.** Area-weighted residual of the
   candidate's predicted geometry against **program-level reserved
   validation triangles**: one blocked reservation per part, drawn **before
   any hypothesis evidence is extracted** — not merely before fitting.
   Block-scale ordering, stated because the correlation record itself comes
   from measurement (002 §A.4) and its residual field feeds
   construction-facing derivations (covariance inflation → relation and
   snap licences — 002 §B.1), so calibration touching reserved triangles
   would leak reserved geometry into candidate construction through the
   record, not merely through a scalar. The order is therefore
   **reservation first**: (0) the G2 reservation is drawn over the raw
   mesh at a scale needing no measurement of this scan — the declared
   default ≈ 8 ℓ_med (007 §10.3; ℓ_med is a mesh property, not a candidate
   statistic), or a *pre-existing regime record's* range where one is on
   file, whichever is larger — recorded as `blocking-basis: default-8lmed`
   or `blocking-basis: regime-record`; (1) the 002 §A.4 correlation
   calibration runs **on the non-reserved subset only**, so the frozen
   record, the fit covariances, and every licence derived through them
   contain no reserved-triangle information; (2) all FHG evidence
   extraction, under the same restriction. The reservation is **sparse and
   buffered, not a parity checkerboard**: under 007 §10.3's checkerboard
   every construction cell touches a reserved cell, so buffering it would
   consume the entire opposite parity and leave nothing to construct
   from. Instead, validation cells are a **sparse non-adjacent set** —
   octree cells selected deterministically (content-addressed order) such
   that no two chosen cells are within one cell of each other, totalling
   the declared `program_validation_fraction` of area — and around each a
   one-cell buffer shell is excluded from *both* construction and
   validation support (dispositioned `holdout-buffer`, counted in neither
   side's evidence, still owned in the H accounting). Validation plus
   buffer area is bounded by construction (sparse selection caps the
   buffer at the shell of each isolated cell) and both fractions are
   recorded on the reservation. The measured
   range then *audits* the reservation instead of sizing it: if the
   frozen record's range exceeds the buffer width, construction
   triangles can sit within one correlation length of reserved ones and
   separation is not established — G2 grading is unlicensed for this
   scan, recorded `holdout-separation-insufficient` (new closed-set
   token), and the competition falls to the licence-floor outcome exactly
   as under `program-competition-unlicensed`. Undersized separation fails
   closed; it is never patched by re-drawing blocks with data calibration
   has already seen.
   **Where calibration ran and refused** (`correlation-model-unidentified`),
   the 002 fail-closed rule governs — held-out grading is unlicensed for
   this scan, so the program *competition* is unlicensed: no factored
   candidate may be selected on ungradable fidelity, the search emits only
   the licence-floor program (the `slab-join` fallback / today's degenerate
   planner output, whose own admission does not depend on G2), and the
   selection record carries `program-competition-unlicensed` (new
   closed-set token) naming the refused calibration. No default block
   scale is ever substituted for a calibration that measurably could not
   identify one. The reservation contract is total: **candidate
   construction conditions on no reserved geometry at all** — not
   parameters, not residuals, and not topology. Sections and slabs traverse
   raw dump triangles (001 §B), so their extractors run **on the
   non-reserved subset only**: no reserved triangle contributes a section
   segment, a fitted parameter, a station estimate, a profile-entity fit, a
   classification vote, or an occupancy count. A loop chain interrupted
   *only* at reserved-triangle spans is bridged by a straight chord between
   the flanking non-reserved segments' endpoints, labelled
   `reservation-gap` — no reserved-triangle geometry is consulted to place
   it — recorded per loop, and excluded from entity fitting and material
   consensus (the 001 §A.4 closure-segment mechanics, reused). When the
   bridged fraction of a loop's length exceeds
   `reservation_gap_max_fraction` (declared), the loop is **ungradable for
   construction** and hypotheses needing it are not constructed — the
   conservative substitution, same shape as 002 §A.1's ungradable child:
   reservation may cost candidates, never inform them. (Vertex sharing at
   reserved-block boundaries is accepted for the same reason 002's blocked
   holdout accepts it: block scale ≥ the recorded correlation range.) G2
   then grades predicted surfaces against the reserved triangles alone.
   Gate: residual ≤ `program_heldout_tolerance` (declared; rationale tied
   to the emission deviation thresholds — a program that cannot meet the
   grade the emitter will apply is dead on arrival).
3. **G3 — unexplained support.** The area the candidate leaves unclaimed may
   not exceed the baseline by more than `program_unexplained_slack`
   (declared), where the baseline is a **set-level aggregate computed after
   the search completes**: the minimum unclaimed area over *all* G1–G2
   survivors of the full constructed candidate set — never a running best
   that depends on expansion order or beam contents. Unclaimed stays a first-class
   outcome (007 §6); this gate only forbids *choosing* a program that
   explains less for no compensating reason.
4. **G4 — unsupported inference.** Inferred geometry (virtual closures,
   continuation completions, hidden caps — the derived-geometry ledger, 002
   §A.2 rule 7) is charged by area and count; a candidate may not carry more
   unsupported inference than the set-level baseline (minimum charge over
   all G1–G3 survivors, aggregated after search completes, as in G3) plus
   `program_inference_slack` (declared). Nominal snaps count here too: a
   snap without its 007 §8.5 identifiability licence is unsupported
   inference by definition and is never emitted anyway.
5. **G5 — compactness.** Among survivors, minimize the **shared
   program-complexity census** — the same list, item for item and in the
   same order, as the P cell's shared census (003 Amendment §7.1); P's
   ground-truth-only and reporting-only fields are diagnostics outside this
   gate. Compared lexicographically within itself in declared order:
   unlicensed-duplicate parameter values (two independently fitted values a
   regularity class says should be one); repeated geometry not expressed as
   a pattern/equality where its licence holds; feature count; sketch count;
   redundant construction planes/geometry; unconstrained sketch degrees of
   freedom.
   This is the gate at which a base+pocket+pattern program beats the
   equivalent slab stack — *only* having tied or won G1–G4 first, which is
   the review's rule adopted verbatim: the compact program wins whenever it
   explains the same observations within the same fidelity budget.
6. **Tie at the end** — materially different programs surviving all five
   gates within tolerances (after G5 they are, by construction, tied on the
   compactness census too): refuse `program-selection-ambiguous`, enumerate
   the candidates with their full gate vectors, and emit nothing for the
   contested scope. The declared spec escape is
   `program_selection: resolve-by-order`: among the fully tied candidates,
   the deterministic KTD-8 candidate ordering (content-addressed serial)
   picks one, the choice is recorded on the program header as
   `ambiguity-resolved-by-declared-policy` with the full tied set beside
   it, and the report never presents the pick as evidence-preferred — the
   escape resolves *which* to emit, never *whether* the ambiguity existed.
   "Materially different" is itself defined: differing in operation
   multiset, polarity, or dependency topology — not in parameter values
   within combined uncertainty.

Every gate's number is a declared threshold through `_declared_number` with
a rationale, labelled `experimental-default` until the 002 §B.2 sweep
protocol has run against the benchmark corpus — program selection changes
output topology, so these values are exactly the class the sweep rule
governs.

The scoreboard connection is direct: G2 feeds RC/deviation, G3–G4 feed H's
disposition accounting, G1 feeds V's precision (a hallucinated feature is a
G1 kill before it can pollute precision), and G5 *is* the P cell's
optimizer-facing form (003 Amendment §7) — the metric and the objective are
the same census, so the system cannot be optimized against one and measured
against the other.

# 7. Bounded search, determinism, and cost

- **Shape:** best-first beam over program prefixes ordered by the causal
  scaffold (primary body → additive bosses/ribs → subtractive
  holes/pockets/slots → shell → secondary sweeps/lofts → dressings →
  patterns/equalities → components), which is a proposal order, not a truth
  claim about history. Beam width `program_beam_width` (declared; default
  rationale: the licence table already prunes the space to near-linear on
  mechanical parts — the beam exists to cap the adversarial case, not to do
  the selection's job). Candidate count and expansion count are recorded.
  **Hitting the beam cap refuses** — `program-search-budget-exceeded` for
  the affected scope, naming the cap and the census of discarded prefixes —
  unless a recorded dominance bound proves the discarded prefixes cannot
  win any gate (in which case the bound is the census line). A truncated
  search that still crowned a winner would break both the selection
  guarantee and the `program-selection-ambiguous` guarantee, which is
  exactly the silent first-rule-wins this design exists to end.
- **Determinism:** KTD-8 discipline verbatim — every ordering derives from
  content-addressed hashes; gate comparisons use quantized values (007
  §2.3); ties break by the candidate's **content hash over its canonical
  serialized program** (input collections canonically ordered first), then
  by node content hash — never by an incidental construction serial, which
  would leak expansion order into selection; numpy/BLAS build
  recorded. Two runs on one dump produce byte-identical selection records.
- **Bounded memory:** the graph stores support as ranges over the partition
  permutation (002 PR 1), and candidates share structure (a program is a
  list of node references, not copied geometry). Budgets: `max_fhg_nodes`,
  `max_program_candidates` (declared, with the 002 §A.6 budget semantics —
  exceeding one refuses `program-search-budget-exceeded` *before*
  allocation, with the census of what would have been proposed; a budget
  refusal is a modelling-error signal, never a licence to fall back to an
  unsearched first-rule emission).
- **Where it runs:** the `plan` stage of 010's execution model — after
  `frame-relate` (and after `plan-decomposition` where the 004 lane is in
  play), before the review pause. The pause now shows the winning program
  *and* the losing candidates' gate vectors, which is what makes the
  human review a review of a decision rather than of an output.

# 8. Composition table — how this binds the existing designs

| Existing design | Role under the FHG | What changes there |
| --- | --- | --- |
| 002 region tree / cross-cut / gates | produces `surface-hypothesis` nodes; the split licence and lineage contract govern node validity | nothing — the tree stops asking "what should I emit?" and its terminals become evidence, which is what its partition invariant was always for |
| 001 slabs / events / loops | produces `profile-hypothesis` nodes, occupancy-difference evidence (§5.3), and the `slab-join` fallback program | slab stack demoted from preferred representation to evidence + floor candidate (001 Amendment B); adaptive certification feeds interval-support evidence |
| 007 relationships / snapping | produces `regularity-hypothesis` nodes; class certificates license `pattern`/equality bindings and shared parameters | relationships stop being decorative metadata: an adopted class is a constraint every candidate program must satisfy or contest, and its counterfactual cost shows up in G2 when it is wrong |
| 010 execution model / convert | convert-derived faces are `surface-hypothesis` nodes with `fusion-convert` provenance under the same gates; the `plan` stage hosts the search | `plan` re-specified (010 Amendment B); everything else unchanged |
| 004 componentization | `component-boundary-hypothesis` nodes are priors on program boundaries: a licensed geometric subobject proposes a program subtree per component; claim levels never upgraded by the search | R3's both-fit held-out comparison becomes one instance of the general G1–G5 competition (same holdout discipline, same record shape) |
| 003 scoreboard | G1–G5 map onto RC/H/V-precision/P as stated in §6; the selection record is a scoreboard input artifact | P cell (Amendment §7) measures the same census G5 optimizes |
| 006 emission / D7 proof | unchanged as the executor of the winning program; the causal-E influence maps (003 Amendment §7) are authored from the FHG's own dependency edges — the graph knows which support each parameter should move | emitters lose their implicit archetype-selection authority; they build what the selection record says |

# 9. Refusals (closed-set additions)

`polarity-contradictory`, `program-selection-ambiguous`,
`program-search-budget-exceeded`, `program-competition-unlicensed`,
`holdout-separation-insufficient`, plus
per-licence refusals already owned by
the source designs (nothing re-tokenized). All join the closed vocabulary
with the existing validator discipline.

# 10. Verified facts vs assumptions

- **Verified:** every licence input named in §4 exists as a measured gate or
  record in the cited design (checked against 001/002/004/007/010 during
  drafting); the emission surfaces marked "exists today" are exercised on
  `feat/25d-emitter` (001 baseline tables); `cut` is exercised for holes.
- **Assumptions, labelled:** (A1) the licence-bounded candidate space stays
  near-linear on the production corpus — settled by the first selection
  record's candidate census; (A2) generalized `cut-extrude` emission (cut
  with an arbitrary matched profile set, not only hole archetypes) behaves
  like the exercised hole path — settled by the first live cut emission,
  probe-first per house rules; (A3) chamfer's licence shape is adequate —
  settled on the benchmark parts carrying chamfers. Each failure mode has a
  designed outcome: A1 → budgets refuse with census; A2 → the affected
  candidate is unconstructible and the slab fallback survives; A3 → chamfer
  stays out of vocabulary one more version.

# 11. Implementation entry

Per the canonical order (review file §3): this design is **step 4 —
ratified before any emitter is optimized**; the scoreboard completion is
step 5; the evidence lanes then land in their existing sequence, each PR
stating which FHG node kinds it feeds. The first implementation PR of this
design is the selection record schema + the licence-table validator + the
search over *existing* evidence (regions, sections, relationships) with
`slab-join` and the exercised archetypes as the only constructible
operations — which must reproduce today's planner output on the one-slab
degenerate case (the same nothing-regresses discipline as 001 §C).
