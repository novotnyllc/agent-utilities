---
title: "review: external Deep Research reconciliation of the mesh→CAD design corpus (issue #20) — verdict, judgment, incorporation"
date: 2026-08-21
role: preserved external review + incorporation record
reviewer_model: "GPT-5.6 Sol (ChatGPT), Deep Research mode"
reviewer_session: "oracle 0.17.3, session mesh-cad-deep-research-reconcile"
reviewer_runtime: "11m56s; ~113.4k tokens up / ~15.1k down; model selection verified via chatgpt-model-picker at 2026-08-21T07:18:47Z"
review_protocol: "three strictly ordered phases: Phase A independent architecture (external literature/products/patents only), Phase B adversarial review of the corpus, Phase C reconciliation (convergence/divergence tables with picked winners, adoption list of 13, abandonment list of 8, top-5 decide-before-code). The reviewer discloses that Phase A blinding was imperfect (attachment snippets surfaced early); treated accordingly."
reviewed:
  - docs/plans/2026-08-19-007-research-reconstruction-algorithms.md
  - docs/plans/2026-08-19-010-design-fusion-native-architecture.md
  - docs/plans/2026-08-20-001-design-25d-event-decomposition.md
  - docs/plans/2026-08-20-002-design-scan-segmentation.md
  - docs/plans/2026-08-20-003-scoreboard-mesh-to-cad.md
  - docs/plans/2026-08-20-004-design-componentization.md
  - plugins/agent-utilities/skills/fusion-parametric-design/references/mesh-reconstruction.md
verdict: "evidence-backed overall; 3 blockers, 5 high, 1 medium; central recommendation: make verified feature-program synthesis the central abstraction"
status: "incorporated 2026-08-21 — every finding, adoption, and abandonment judged; amendments landed in 001/002/003/004/007/010; new design doc 2026-08-21-001 (feature-program synthesis); mesh-reconstruction.md rewrite registered behind PR #65 (§6)"
---

# Deep Research reconciliation — verdict, judgment, and incorporation record

This file preserves, verbatim, the full answer of the external Deep Research
reconciliation run (§7). §1 is this repository's judgment of every finding,
adoption, and abandonment — rendered against the documents *and* the measured
record, not rubber-stamped. §2 records one user ruling that overrides a class
of findings. §3 is the canonical implementation order every design doc now
defers to (superseding the §2 order of
`docs/reviews/2026-08-20-oracle-design-review.md`, which it extends rather
than contradicts). §4 records the accept-with-modification arguments in full.
§5 lists the incorporation ledger — which document changed how. §6 registers
the one deferred item.

The same check as the previous review applies to every finding before
acceptance: **does it contradict a measured result?** One reviewer premise
does (§1.2 finding 4's motivating example — the "σ was 6–14× too small"
reading was refuted to the digit by the shipment-1 readout, design -002
addendum), and the judgment below says so while accepting the finding's
architectural point on its own merits. Measured results in the corpus outrank
the reviewer's reasoning wherever they conflict.

## 1. Judgment

### 1.1 The three blockers

| # | Finding (short) | Judgment | Incorporated in |
| --- | --- | --- | --- |
| B1 | The architecture still contains a BaseFeature path (010's "surfaced remainder", probe P5) — a violation of the repo's own ban | **accept** — verified: 010's freeform §2 delivers "smooth reference surfaces in a base feature"; plan 005 R9 bans `baseFeatures` for reconstructed geometry, and the hard-constraint statement bans them outright. The "labelled non-parametric, separate bucket" carve-out does not survive: a base feature is history-free geometry wearing a timeline item, which is the over-claim the project exists to avoid, and it buys no design intent | 010 (path deleted in place; Amendment B) |
| B2 | The canonical implementation contract (mesh-reconstruction.md) still describes a different product — no segmentation, GFG-as-input, edit-specific-only reconstruction | **accept** — verified by quote: "the segmentation layer is deleted and the grouping is the input", "refused `face-groups-absent`", "`parametric-rebuild` — … This is not a whole-part auto-converter" all stand in the shipped reference while 010/002 build segmentation as load-bearing and the goal is whole-part reconstruction. Two internally legitimate definitions of success is a governance failure | **deferred behind PR #65** (§6) — the file is being amended by an open PR; the supersession rewrite lands on the merged text |
| B3 | No sufficiently strong program-quality/model-selection layer between recovered geometry and emitted timeline | **accept** — the user has directed incorporation ("taking the two to the next step"). The Feature Hypothesis Graph and bounded program search become a first-class design | new design doc `docs/plans/2026-08-21-001-design-feature-program-synthesis.md`; hooks in 010 (plan stage), 001 (semantic factorization), 003 (P cell) |

### 1.2 The high and medium findings

| # | Sev | Finding (short) | Judgment | Incorporated in |
| --- | --- | --- | --- | --- |
| 4 | High | Statistical licensing framework claims more than its models justify; scan uncertainty needs a consumer-specific model | **accept-with-modification** (§4.1) — the architectural point stands; the motivating σ example is refuted by measurement and is corrected in the record | 002 §B.1; 007 Amendment §§1–2 |
| 5 | High | Slab representation can score well while producing semantically poor CAD; join-only stack encodes the wrong conceptual structure | **accept** — user-directed. Slabs demoted to evidence generator + honest fallback; semantic factorization preferred when licensed | 001 Amendment B; design -001 (2026-08-21) |
| 6 | High | Scoreboard lacks feature precision, local-causal editability, and program compactness | **accept** — all three. Metrics create the optimizer; landing them after emitters are optimized repeats the non-vacuity mistake | 003 Amendment §7 (P cell, precision, causal-E) |
| 7 | High | Preview Fusion APIs treated too casually; convert-timeout is unenforceable on a synchronous call | **split**: timeout critique **accept** (a Python wall-clock timer on a synchronous `add()` observes the overrun only after control returns — the refusal semantics could not be enforced); Preview-status demotion **reject per user override** (§2) | 010 Amendment B (resource policy); §2 (override) |
| 8 | High | The correlation record is over-centralized — one transformed statistic answering five different questions | **accept-with-modification** (§4.2) — the frozen candidate-independent *substrate* stays (its non-circularity argument is untouched); each consumer derives its own statistic from it | 002 §B.1 |
| 9 | Medium | Componentization ontology excellent; product narrative around it too broad in two places | **accept** — C2 "exceeds the documented commercial bar" narrowed to "useful intermediate capability"; the v1 detection lane described as its restricted scope. Plus: the "independent channel" list made machine-checkable | 004 Amendment B |

### 1.3 Embedded findings judged individually

| Finding | Judgment | Where |
| --- | --- | --- |
| Nested-kind F tests (torus→cylinder R→∞, cone→cylinder ω=0) are singular/boundary limits, not regular nests; classical F interpretation unlicensed | **accept** — verified against 007 §10.4's own degeneracy analysis (§12.3 risk 1 already documents the JᵀJ singularity along exactly these directions). Replaced by spatially blocked held-out comparison and/or parametric bootstrap under the simpler kind. 007 §8.4's relation-rollback F test is a *regular* interior-constraint nest and **stands** | 007 Amendment §1 |
| Three fixed constancy sections cannot certify slab constancy | **accept** — a narrow boss, slot, or chamfer termination between stations contributes no event when its bounding plane was never an accepted fit, so the event machinery lowers but does not eliminate the risk. Certification becomes adaptive, terminating on evidence, not station count | 001 Amendment B.2 |
| Universal "~10σ" information-theoretic resolution language over-claims | **accept** — the 6–10σ arithmetic survives as the iid-point-noise regime bound it actually derives; the universal claim is replaced by measured detector power conditional on feature family, support, sampling, form error, and correlation regime | 007 Amendment §2 |
| "Delete the spatial index and use broadcasting" is O(N²) at 10⁶ triangles | **accept** — vectorization is not an indexing algorithm. Replaced by an explicit bounded-memory neighbourhood strategy with a stated memory bound | 010 Amendment B |
| Threshold rationales are necessary but not sufficient for values that change segmentation topology | **accept** — such values are relabelled `experimental-default` pending sensitivity sweeps; the sweep protocol is defined | 002 §B.2 (protocol); 007 Amendment §3 (cross-ref) |
| "Original design intent" language corpus-wide | **accept as terminology alignment** — the corpus already *refuses* recovering original design intent (005 KTD9, 010 not-achievable, 001 §Not-achievable); what was missing is the positive name for what **is** delivered: an **evidence-licensed editable design-intent hypothesis**. Adopted as the canonical term | design -001 (2026-08-21) §1; this file; carried into the mesh-reconstruction.md rewrite (§6) |
| "A worker can faithfully implement mesh-reconstruction.md and still fail the project objective" | **accept** — see B2 | §6 |

### 1.4 The adoption list of 13, judged

| # | Import | Judgment | Where |
| --- | --- | --- | --- |
| 1 | Feature Hypothesis Graph + bounded program search | **accept** (B3) | design 2026-08-21-001 |
| 2 | Semantic factorization of the slab stack | **accept** | 001 Amendment B.1 |
| 3 | Program-quality score P | **accept** | 003 Amendment §7 |
| 4 | Feature precision alongside vocabulary recall | **accept** | 003 Amendment §7 |
| 5 | Parameter→region causal influence map | **accept** | 003 Amendment §7 |
| 6 | Consumer-specific spatial uncertainty | **accept-with-modification** (§4.1, §4.2) | 002 §B.1; 007 Amendment |
| 7 | Replace singular nested-kind F tests | **accept** | 007 Amendment §1 |
| 8 | Adaptive slab certification | **accept** | 001 Amendment B.2 |
| 9 | Preview-API release boundary ("optional candidate providers; absence must not disable the native route") | **reject-as-motivated / already-satisfied-as-behaviour** — the *behaviour* (010 designs `convert-unavailable`/`convert-failed` in advance and routes every failure to the native path; the native path is already the workhorse) predates the review and stands on its own reliability-at-scale rationale. The *motivation* — Preview status itself disqualifies — is rejected per the user override (§2). No document demotes GFG/MeshConvert because they are Preview | §2; 010 unchanged in substance |
| 10 | Replace convert-timeout with enforceable resource policy | **accept** — pre-call triangle/complexity budgets from measured conversion behaviour + post-call elapsed-time telemetry; no claimed preemption of a synchronous call | 010 Amendment B |
| 11 | Explicit bounded-memory spatial indexing | **accept** | 010 Amendment B |
| 12 | Machine-checkable physical-thing evidence predicates | **accept** | 004 Amendment B |
| 13 | Canonical supersession matrix for mesh-reconstruction.md | **accept, deferred** behind PR #65 — the six-question one-answer contract is fixed now; the rewrite lands on the merged text | §6 |

### 1.5 The abandonment list of 8, judged

| # | Abandon | Judgment |
| --- | --- | --- |
| 1 | BaseFeature surfaced remainder | **accept, decisive** — deleted from 010 (B1) |
| 2 | "GFG is the segmentation; no fallback" | **accept for scans** — already contradicted by the measured real-scan failure and design -002; the contract statement dies in the §6 rewrite. GFG remains a candidate partition (P1 discipline, unchanged) |
| 3 | Ordinary F tests over singular primitive degeneracies | **accept** — 007 Amendment §1 |
| 4 | Universal ~10σ resolution language | **accept as universal claim** — survives as the stated iid regime bound; 007 Amendment §2 |
| 5 | Join-only slabs as the preferred final representation | **accept as endpoint, retain as fallback** — 001 Amendment B.1. The review's own formulation ("lose to a smaller base+cut+boss+hole program whenever that program explains the same measured support") is adopted verbatim as the FHG competition rule |
| 6 | Global-observable-only editability proof | **accept as the scored proof** — volume/centroid/bbox stay as cheap smoke tests; local causal influence becomes the scored criterion. 003 Amendment §7 |
| 7 | One correlation-length record as every subsystem's final answer | **accept-with-modification** — the shared measured residual/correlation substrate is kept (its freeze-before-acceptance non-circularity is the load-bearing property); each consumer derives its own statistic. 002 §B.1 |
| 8 | Preview Fusion APIs as indispensable production infrastructure | **moot as stated + motivation rejected** — no document ever made them indispensable (010: "accelerator, not authority"; native path is the workhorse; absence is a designed refusal that costs the accelerator, not the pipeline). The Preview-status motivation is rejected per §2 |

**Tally: 20 accept, 4 accept-with-modification, 2 reject (both on the same
Preview-status ground, per the user override), 2 deferred-behind-#65 (both
accepted in substance).** Counting scheme: 1.1–1.3 findings and 1.4/1.5 items
that name the same change are counted once.

## 2. User override — Preview APIs (recorded ruling)

The review recommends demoting `MeshGenerateFaceGroupsFeatures` (GFG) and
`MeshConvertFeatures` to optional corroborating accelerators *because
Autodesk documents both API surfaces as Preview* ("may change and should not
be relied upon for distributed programs").

**The user's ruling, verbatim: "I'm okay with using preview APIs anytime
it's the right thing."**

Consequences, binding on the corpus:

- **Preview status alone never disqualifies an API.** GFG and MeshConvert
  remain load-bearing wherever they are the right tool. The probe record
  already makes an API-surface change *detectable* (010's probe stage keys
  every record to the Fusion version; a member disappearing is a named
  refusal naming the probe that would re-settle it) — which is the honest
  mitigation for Preview churn, and it is already built.
- What **does** bound MeshConvert's role is its measured reliability at
  scale (010 P2b: quality degrades with triangle count) — a geometry
  argument, not a release-stability argument. That boundary stands
  unchanged: per-region invocation, same gates both sources, provenance with
  a size predictor.
- The review's subsidiary point — declare what "distributed program" means
  for this plugin's delivery model — is accepted as a one-line fact: the
  pipeline runs on the user's own Fusion install against probed API surfaces
  and re-probes per version; it is not a distributed binary whose API
  surface is frozen at build time. That is why Preview churn is a detectable
  refusal here rather than a shipped breakage.

## 3. §order — the canonical implementation order (stated once; every design doc defers here)

This order extends `docs/reviews/2026-08-20-oracle-design-review.md` §2 and
supersedes it as the single reference. Steps 2–3 are unchanged from that
file; the FHG ratification and the scoreboard completion are inserted before
any emitter is optimized, and the previously ordered lanes are re-expressed
as evidence producers feeding the FHG.

1. **Contract/supersession freeze** — rewrite
   `references/mesh-reconstruction.md` on the post-#65 text (§6) so exactly
   one answer exists to each of: whole-part editable reconstruction is the
   goal (yes); custom scan segmentation exists (yes, when Fusion grouping is
   insufficient); GFG is a candidate partition, not authority (yes — and
   usable per §2's override); a Mesh Convert body is a candidate source,
   never a reconstruction result (yes); BaseFeatures are banned (yes,
   totally); the deliverable is a feature program constituting an
   evidence-licensed editable design-intent hypothesis, never the original
   history (yes).
2. **PR 0a — non-vacuous emission gate** (003 §1.1) — unchanged.
3. **PR 0b — relationships rewrite** (002 §A.6: complete-linkage classes,
   hard artifact budgets) — unchanged.
4. **FHG design ratified** — `2026-08-21-001-design-feature-program-synthesis.md`
   reviewed and frozen: closed operation vocabulary, per-operation evidence
   licences, Boolean polarity evidence, the lexicographic program-selection
   objective, determinism. No emitter work that encodes an archetype→feature
   rule proceeds until the rule's place in the FHG competition is stated.
5. **Scoreboard P / precision / causal-E landed** (003 Amendment §7)
   **before emitters are optimized** — metrics create the optimizer; a lane
   optimized against the old five-cell vector and then measured against the
   completed one (RC, V as a precision/recall pair, causal E, P, C, with H
   the guardrail) repeats the non-vacuity failure in slow motion. That
   corpus schema — RC/V/E/P/C/H — is the governing scoreboard for every
   selection record; the reviewer's Phase A vector G/F/E/P/C/H (§7) is its
   own vocabulary, mapped G→RC+deviation, F→V, E→E, P→P, C→C, H→H, and the
   review's own divergence table already awards the corpus vector the win.
6. **The evidence lanes, in their previously ordered sequence, re-expressed
   as evidence-feeding-FHG**: amended split licence → region-tree skeleton
   with lineage → cross-cut + correlation model (one shipment, separation
   certificates, lateral proxy refinement) → 004 schema/probes/synthetic
   emitter (C-1..C-3) → `plan-decomposition` (C-4) → slab tracks + virtual
   closure → per-thing recursion (C-6). Each lane's output is hypothesis-
   graph evidence (region tree → surface hypotheses; sections/slabs →
   profile and occupancy evidence; relationships → regularity hypotheses;
   componentization → program-boundary priors), and each lane's PR states
   which FHG node kinds it feeds.
7. **Component identity decided before C5 semantics** — 004 §A.4's stable
   thing-ID design note (owner: PR C-4) remains the blocking open item; no
   joint, update-in-place, or instance semantics may depend on component
   identity until it lands.

## 4. Accept-with-modification arguments

### 4.1 Consumer-specific uncertainty (finding 4 / adoption 6)

The review's motivating example — "a real board scan exhibited flat-face
form error many times larger than the earlier local σ estimate" — is the one
place it contradicts the measured record: the shipment-1 readout (design
-002 addendum) refuted the σ-scale hypothesis to the digit (σ_form within
face groups measured 0.0032 mm, *below* σ_dihedral; the 0.033–0.076 mm
figure was patches straddling the un-segmented mega-group — a segmentation
artifact read as a noise measurement). The finding is accepted anyway,
because its argument does not depend on the example: point jitter, form
error, spatial correlation structure, held-out independence, and parameter
covariance are related but distinct estimands, and no single scalar should
automatically size a PCA neighbourhood *and* set the tolerance for a 70 mm
plane's low-frequency bow. The modification: the corpus keeps its measured
substrate (002 §A.4's frozen record — the non-circularity property is
load-bearing and the review endorses it) and the per-consumer derivation
lands on top (002 §B.1). The judgment record notes the refuted example so
the corpus never cites this review as evidence for the 6–14× reading.

### 4.2 De-centralizing the correlation record (finding 8 / abandonment 7)

002 §A.4 decision 6 said "yes, one length" — all four consumers read the
same record. The review's correction is accepted: the *record* (residual
field, range(s), sill, provenance) is shared; the *statistic* each consumer
needs is derived per consumer — block separation for held-out, block design
for the bootstrap, ESS/covariance inflation via its own estimator, relation
uncertainty through the inflated covariances of the relevant parameter
combinations, Moran's own weight/null construction. What is *not* accepted
is any weakening of the freeze-before-acceptance rule: every derivation
still starts from the one frozen candidate-independent record, so no
consumer's statistic conditions on the candidates it judges.

### 4.3 The Preview-API split (finding 7 / adoptions 9–10 / abandonment 8)

Two claims travelled together in the review and are separated here. The
enforceability claim (a synchronous `MeshConvertFeatures.add` cannot be
preempted by a Python timer, so `convert-timeout` promises a refusal
semantics the execution model cannot deliver) is verified against the API
shape and accepted: 010 now budgets *before* the call and measures after
it. The release-stability claim (Preview status demands demotion to
optional) is rejected per the user override (§2). The behavioural overlap —
absence or failure of convert never disables the native route — was already
true in 010 for reliability reasons and is unchanged.

## 5. Incorporation ledger

| Document | Change |
| --- | --- |
| `docs/plans/2026-08-21-001-design-feature-program-synthesis.md` | **new** — the Feature Hypothesis Graph and bounded program search (B3/adoption 1), with the closed operation vocabulary, per-operation evidence licences, Boolean polarity evidence, the lexicographic selection objective, determinism, and the composition table binding every existing lane |
| `2026-08-19-010` | BaseFeature/surfaced-remainder path deleted in place (P5, freeform §2, M6); `convert-timeout` → pre-call complexity budget + post-call telemetry; spatial-index row → bounded-memory neighbourhood strategy; `plan` stage becomes FHG construction + program selection; Amendment B records all of it |
| `2026-08-20-001` | Amendment B: slabs demoted to evidence + fallback; semantic factorization stage over slab occupancy differences; adaptive section certification replaces the fixed three-station constancy guard |
| `2026-08-20-002` | §B.1 consumer-specific statistics over the shared frozen substrate; §B.2 sensitivity-sweep protocol; topology-changing thresholds relabelled `experimental-default` |
| `2026-08-20-003` | Amendment §7: P (program quality) as a scored cell; V gains feature precision; E upgraded to local-causal influence maps with global observables demoted to smoke tests |
| `2026-08-19-007` | Amendment: §10.4 singular-nest F test replaced (held-out / parametric bootstrap); §12.1's ~10σ language made regime-conditional; §3's "σ is the foundation" scoped to local jitter; threshold defaults cross-referenced to the sweep protocol |
| `2026-08-20-004` | Amendment B: the two narrative narrowings; machine-checkable physical-evidence predicates; stable thing-ID reaffirmed as the C5 blocker |
| `references/mesh-reconstruction.md` | **not touched in this change** — §6 |

## 6. Deferred: the mesh-reconstruction.md supersession rewrite (registered follow-up)

PR #65 (`fusion-expert-operator`) is amending
`references/mesh-reconstruction.md` and merges ahead of this file's PR. The
B2/adoption-13 rewrite therefore lands **on the merged text**, as its own
follow-up PR, and is registered here rather than raced: the canonical
contract answers the six §3-step-1 questions one way — whole-part editable
reconstruction is the goal; scan segmentation exists; GFG/Convert are
advisory-but-usable (Preview status never disqualifies, per §2); BaseFeatures
are banned; the feature program is the output; the deliverable is an
evidence-licensed editable design-intent hypothesis. The file ships in the
skill, so the rewrite is present-tense with no history narration, exactly as
the rest of the skill's references. Until that PR lands, this section is the
notice that the shipped contract text is known-stale on those six answers and
the design corpus (not the reference) is authoritative.

---

# §7 — the verbatim review

Everything below this line is the reviewer's answer, preserved verbatim
(transport wrapper and CLI metadata removed; content untouched).

---

Independent Expert Review of Mesh-to-Parametric-CAD Reconstruction
Executive verdict and method boundary
Overall judgment: evidence-backed. The program has several unusually strong foundations for trustworthy reverse engineering: immutable source provenance, explicit refusal semantics, measured rather than assumed Fusion behavior, detection-first primitive recovery, global relationship inference, partition lineage, non-vacuity gates, a real perturbation-based editability concept, and, especially, the four-level distinction between geometric regions, geometric subobjects, physical things, and delivery components. Those choices put it on a credible path toward high-integrity automatic reconstruction of restricted mechanical-part classes.
It is not yet on a demonstrated path to commercial-class general mesh-to-editable-CAD reconstruction, because the central unsolved problem is still between “surfaces have been recognized” and “a good editable CAD program has been inferred.” The current designs are much stronger at identifying and validating geometry than at synthesizing the right feature program. That distinction matters: a reconstruction can have excellent geometric coverage, valid parameters, zero silent area, and still be a terrible Fusion model because pockets became slab boundaries, repeated features became independent sketches, a shell became nested profiles, or fifty surfaces became fifty unrelated operations.
The single highest-leverage change is therefore:
Make verified feature-program synthesis, rather than region fitting or slab decomposition, the central abstraction.
Segmentation should produce evidence for competing feature-program hypotheses. A bounded search should choose among extrude/cut/revolve/shell/fillet/chamfer/sweep/loft/pattern/component programs using held-out geometric fit, evidence coverage, semantic consistency, unsupported inferred geometry, and program compactness. The winning program is then emitted, rebuilt, perturbed, and re-graded.
That change connects the strongest existing pieces instead of replacing them.
What “commercial parity” actually means
Current commercial material supports a somewhat narrower claim than “commercial products automatically recover the original CAD history.” Hexagon describes Geomagic Design X as combining scan processing with history-based CAD, guided/automated modeling, geometric-feature extraction, accuracy analysis, and editable feature-based solid models.
QUICKSURFACE advertises editable parametric CAD, primitive extraction, sketches, dimensions, loft/sweep/shell/pattern operations, hybrid modeling, automatic/freeform surfacing, and deviation analysis.
Polyga's Xtract3D documentation is particularly revealing because its documented workflow is explicitly assisted: align the scan, create slices, construct and constrain sketches, revolve/extrude, then analyze deviation. Its slice features remain editable.
Evidence-backed judgment. Commercial-output parity and commercial-automation parity should be treated as different goals. The former means “the result looks like a competent human reverse-engineering model: sketches, dimensions, features, components, and a useful history.” That is plausible for restricted mechanical domains. The latter means “the system autonomously discovers the same decomposition a skilled Design X user would guide.” The commercial documentation does not establish that this second capability is generally one-click or fully automatic.
I interpret the prompt's “Quicksolid” as QUICKSURFACE, because that is the current commercial reverse-engineering product I found matching the stated workflow. If a different product was intended, that specific comparison is not included.
Independence limitation
Evidence disclosure. The intended Phase A/B blinding was not perfectly preserved: attachment snippets were surfaced by the tooling before the independent architecture was completely frozen. I have therefore treated Phase A below as an externally derived architecture and have deliberately excluded corpus-specific mechanisms from its premises. The external literature and product sources are sufficient to derive it independently, but I cannot honestly call it a perfect blind preregistration. In a strict evidence culture, that contamination should be stated rather than hidden.
Judgment labels used below:
Label	Meaning
Fact	Directly supported by the supplied corpus, the accepted hard constraints, or a cited external primary source.
Evidence-backed judgment	Evaluation following from those facts plus a stated technical argument.
Synthesis	My architectural proposal connecting established methods in a way not directly prescribed by a source.
Opinion	A design preference where available evidence does not uniquely determine the choice.
Phase A independent architecture
The core model: reconstruction is program inference, not surface conversion
A triangle mesh is an observation of boundary geometry. An editable Fusion design is a generative program. The mapping is therefore not:
mesh → segmentation → fitted surfaces → B-Rep
but:
mesh → evidence → geometric hypotheses → feature hypotheses → constrained feature program → Fusion history → counterfactual verification
This distinction is already visible across the research literature. Efficient RANSAC addresses detection of analytic surface primitives in noisy point clouds, including planes, spheres, cylinders, cones, and tori.
GlobFit starts from local primitive hypotheses and improves them by enforcing global regularities such as shared orientations, placements, and dimensions.
Classical reverse-engineering work by Benkő, Martin, Várady, and collaborators explicitly connects segmentation, analytic/swept surface fitting, profiles, topology, and blend recovery into a B-Rep reconstruction problem.
“Beautification” work similarly recognizes that noisy local fits must be reconciled with global regularities to recover engineering structure rather than faithfully preserving acquisition error.
Program-synthesis work exposes the next step. InverseCSG searches for compact constructive programs whose evaluation reproduces an observed shape, making program complexity part of the reconstruction objective rather than merely fitting geometry.
Point2Cyl shows why elementary surface labels are not enough: sketch profiles, extrusion axes/ranges, and Boolean composition form a substantially more useful representation of manufactured shapes.
More recent CAD-generation research has moved even closer to executable parametric programs, although those neural implementations are not a practical runtime choice under the stated Fusion/CPython constraints.
Synthesis. I would make the main intermediate representation a Feature Hypothesis Graph:
text
Copy
Source mesh
│
├── immutable triangle evidence
│
├── primitive/surface hypotheses
│      plane / cylinder / cone / sphere / torus
│      extrusion field / revolution field
│      sweep / loft / shell-offset / blend
│
├── boundary/profile hypotheses
│      section loops / axes / sketch planes
│      line / arc / spline entities
│
├── regularity hypotheses
│      parallel / perpendicular / coaxial
│      concentric / equal / symmetric / tangent
│      pattern / nominal-value hypotheses
│
└── feature hypotheses
additive extrusion / cut / revolve
hole / pocket / boss / shell
fillet / chamfer / sweep / loft
pattern / component
│
▼
bounded program search
│
▼
executable Fusion history
Every hypothesis carries its support, uncertainty, counter-evidence, dependencies, and provenance. A fitted cylinder is therefore never equivalent to “hole.” It may support a bore, boss, revolved exterior, swept geometry, fillet fragment, or an incidental cylindrical surface. Feature interpretation happens at the graph level.
Scan segmentation under real form error
Measurement model
Established practice. Robust primitive detectors should be able to work before perfect segmentation. Efficient RANSAC was specifically developed to detect multiple primitive shapes in large noisy point sets with outliers.
Synthesis. I would not represent scan uncertainty by one universal scalar. Keep at least three conceptually distinct quantities:
Sampling-scale noise: local point/facet jitter relevant to normal estimation and minimal-set fitting.
Form error: lower-frequency departure of a scanned nominal plane/cylinder from its ideal CAD generator.
Spatial correlation scale/structure: how far residual errors remain correlated.
Those quantities may coincide on synthetic iid perturbations and diverge badly on a smoothed or structured-light scan. Spatial effective sample size depends on correlation structure, not merely on raw sample count, and block choices in spatial resampling are themselves model/criterion dependent.
Consequently, no single σ should automatically determine normal support radius, RANSAC inlier width, covariance, held-out block size, relation confidence, minimum feature size, and nominal-value snapping.
Candidate generation before hard partitioning
Established practice. Run an overcomplete Efficient-RANSAC-style detector over the original points/normals for planes, cylinders, cones, spheres, and tori.
Use Fusion GFG, where available, only as a second candidate-generation channel. Autodesk currently exposes both Mesh Generate Face Groups and Mesh Convert through API surfaces, but those API surfaces are documented as Preview; Autodesk explicitly warns that Preview APIs may change and should not be relied upon for distributed programs.
For every candidate, refit on raw original geometry rather than filtered or decimated geometry. Derived signals may propose labels, but do not become the measurement substrate.
Segmentation as model competition
Each triangle/point should then choose among:
supported analytic candidates;
generative swept/extruded/revolved hypotheses;
unexplained.
Use adjacency as a regularizer, but never make smoothness strong enough to force unexplained geometry into a primitive.
Synthesis. The split/merge test should ask:
Does one model explain this connected support adequately, or does partitioning it into multiple models yield a materially better prediction on spatially held-out support after charging for the additional boundary and model complexity?
That addresses the two opposite errors:
Over-segmentation / primitive confetti. Merge pieces when a common jointly fitted model predicts all of them well and the boundary does not correspond to a model or topology change. Global equality and orientation relations help here, but disconnected spatial support must remain representable: two disconnected coplanar faces can share a relationship without becoming one feature.
Under-segmentation. Split when residuals show coherent spatial structure, when competing model families explain different support, when section topology changes, or when a change-point/boundary has independent geometric evidence. A “best plane” with large low-frequency residual structure does not become a slightly bad plane merely because one aggregate RMS is acceptable.
A hierarchical region tree is an appropriate implementation structure, but the tree is bookkeeping; predictive model comparison is the license for each split or merge.
Recovering design intent and an editable timeline
The most important conceptual limit is:
Evidence-backed judgment. A single exterior mesh generally does not identify the historical modeling sequence that originally created it. Multiple CAD programs can produce exactly the same boundary. Neither geometry nor an optimizer can recover information that is not encoded in the observation.
Therefore the product should not claim “the original design intent.” It can recover:
a compact, editable design-intent hypothesis that is consistent with the observed geometry and declared priors.
That is still extremely valuable.
Primary feature hypotheses
For mechanical geometry, construct hypotheses roughly in this causal order, but allow alternatives:
primary extrusion or revolution;
additive bosses/ribs;
subtractive holes, pockets, slots, counterbores;
shell;
secondary sweeps/lofts;
fillets/chamfers;
patterns and equality relations.
Classical B-Rep reverse engineering and blend-recovery literature support separating primary surfaces from blends rather than treating every patch independently.
Point2Cyl likewise treats extrusion as a sketch-plus-motion-plus-Boolean construct rather than a collection of barrel faces.
Profile recovery
Because the given constraints rule out API access to Fusion's mesh-section sketch/fitted-curve UI commands, custom mesh/plane intersection is unavoidable for this path.
For each candidate extrusion/revolution/sweep:
choose sketch/support planes from licensed datums or feature-local frames;
intersect the immutable mesh against several stations;
form loops with triangle provenance;
fit line/arc/circle/spline entities;
infer dimensional/equality/tangency constraints;
compare the resulting generated feature to held-out mesh support.
The sections are measurements, not the final model.
Global regularity
Established practice. GlobFit and constrained-fitting work provide strong precedent for using relations between locally fitted surfaces to improve the global reconstruction.
Adopt relations conservatively:
parallel/perpendicular;
coaxial/concentric;
equal radius/diameter;
equal offsets;
symmetry;
tangency;
repeating pitch/pattern.
Synthesis. A relation should survive a counterfactual test: constrain the relevant parameters, refit/rebuild, and require that the held-out geometric loss remain within a declared practical margin. Statistical significance alone is insufficient on a scan with enormous correlated sample counts.
Nominal snapping, such as 5.01 mm → 5 mm, deserves an even higher bar. Repeated dimensions, a caller-provided manufacturing grid, symmetry, or a known standards library can support the inference. Mere closeness does not establish intent.
Program search
I would use bounded beam search or another deterministic best-first search rather than choose one archetype greedily.
A candidate program receives a vector or lexicographic objective containing:
[ L = L_{\text{heldout geometry}}
\lambda_u L_{\text{unexplained}}
\lambda_i L_{\text{unsupported inference}}
\lambda_s L_{\text{semantic contradictions}}
\lambda_c L_{\text{program complexity}} ]
The coefficients cannot be arbitrary hidden knobs. Either declare them as policy choices or replace the scalar with lexicographically ordered gates.
Program-complexity terms include:
feature count;
sketch count;
unconstrained degrees of freedom;
duplicate dimensions;
independently represented values that could legitimately share one parameter;
redundant intermediate planes;
repeated geometry not represented as a pattern;
slabs used where one base+cut program explains the same observations.
InverseCSG provides good precedent for treating compactness as an essential reconstruction criterion rather than celebrating any program that reproduces the boundary.
Componentization: geometry is not thinghood
This is an information-identifiability problem before it is an algorithm problem.
Consider two hypotheses with exactly the same visible exterior:
an injection-molded housing with an integral cylindrical boss;
a housing plus a separately manufactured cylinder bonded perfectly over an interface hidden from the scanner.
No exterior-only algorithm can distinguish those hypotheses if the interface leaves no observable consequence.
Evidence-backed judgment. Therefore geometric separability cannot license physical thinghood.
I would expose three claim levels:
Claim	What the system may assert	Evidence required
Geometric subobject	A stable surface decomposition exists	geometry, boundary, closure and reconstruction evidence
Delivery/editing component	Separate editing is useful	explicit output policy plus geometric subobject evidence
Physical thing	Independent objecthood is evidenced	an independent evidence channel
Independent physical-thing evidence can include observed disconnected topology, a real gap/seam, mutually occluding surfaces, an exposed interface, a second view, a repeated complete instance that uniquely constrains a hidden continuation, explicit user annotation, or a trusted part/template prior.
When several partitions remain equally compatible with the observations, the correct output is not “best guess physical component.” It is either:
one geometric editing component with the ambiguity recorded; or
multiple candidate decompositions with no physical claim.
That non-identifiability is fundamental, not an implementation deficiency.
Where freeform belongs
Expired Geomagic/Raindrop patents provide useful historical blueprints for reconstructing smooth NURBS surfaces from triangulated or noisy point data. Patent metadata currently identifies US6996505B1 and US7023432B2 as expired, although patent-status metadata is not a legal opinion or jurisdiction-specific freedom-to-operate conclusion.
Evidence-backed judgment. Those techniques solve a different problem from the one posed here. A smooth patch quilt may be excellent reverse-engineered geometry and still contain almost no editable design intent.
My hierarchy would be:
recognized extrusion/revolution/sweep/loft → emit that real feature;
identifiable editable sketch-spline/loft representation → emit it;
otherwise preserve the original mesh as reference and mark the region unreconstructed.
Do not turn arbitrary freeform residuals into a NURBS quilt merely to inflate coverage.
Phase A verification and refusal model
Verification must test four different claims
A reconstruction can be geometrically close but semantically terrible; semantically elegant but geometrically wrong; geometrically and semantically good but inert under editing; or componentized beyond the evidence. One score cannot distinguish these.
I would publish a vector.
Dimension	What it proves
G: geometry	The generated model explains the observed source geometry.
F: feature semantics	Recognized feature instances are correct and sufficiently complete.
E: editability	Parameters cause the intended local/model changes and survive recomputation.
P: program quality	The timeline is compact, constrained, reusable, and not feature confetti.
C: componentization	Geometric and physical component claims are supported at the stated claim level.
H: honesty	All observed support is claimed, explicitly refused, or otherwise dispositioned without silent loss.
Geometry
For observed regions measure at least:
area-weighted source→CAD distance distribution;
robust quantiles plus localized maximum/error clusters;
region-by-region residuals;
normal disagreement where meaningful;
signed side/containment disagreement where the source topology licenses it;
CAD→source distance only over support for which the scan provides meaningful observability, otherwise unobserved hidden caps and deliberately simplified regions distort the score.
Do not collapse both directions into one Hausdorff-like headline.
Reconstruction of hidden geometry should carry an evidence class such as inferred-by-contact, inferred-by-continuation, or template-derived, with its area excluded from scan-measured fidelity claims.
Feature semantics
Where CAD ground truth exists, measure both recall and precision:
[ \mathrm{feature\ recall} = \frac{\text{correct recovered feature instances}} {\text{ground-truth feature instances}} ]
[ \mathrm{feature\ precision} = \frac{\text{correct recovered feature instances}} {\text{all emitted feature instances}} ]
A recall-only vocabulary metric can be gamed by emitting too many hypotheses.
Also measure operation family, Boolean polarity, dependency graph, recovered relation accuracy, and important dimension errors.
Where historical CAD is unavailable, use a human-reviewed evident-feature census on controlled acceptance fixtures and otherwise call the semantic score unmeasured.
Editability is causal, not merely mutable
A user parameter is not “proven” merely because something about the model changes.
For each parameter, store an expected influence set:
text
Copy
parameter: hole_diameter_1
expected to move:
hole-03 cylindrical wall
expected not to move:
base exterior
unrelated holes
observable:
local radius + local signed-distance field
Perturb, recompute, and verify:
intended local support moved in the expected direction/magnitude;
unrelated support remained invariant within tolerance;
constraints and feature health remained valid;
restore reproduced the baseline;
important coupled parameter pairs/interactions also recomputed correctly.
A global volume, centroid, or bounding-box change is only a weak smoke test. Many incorrect edits move those quantities, while legitimate symmetric/local edits can leave one or more of them unchanged.
Program quality
This is the metric most reconstruction systems omit.
Measure:
feature count;
sketch count;
parameter count;
fully constrained sketch rate;
redundant/duplicated dimensional variables;
repeated geometry represented independently rather than by equality/pattern;
feature depth;
unnecessary construction geometry;
reference/ground-truth program-size ratio where available;
feature-graph similarity where ground truth exists.
Evidence-backed judgment. Without such a metric, optimizing geometric coverage creates a direct incentive for primitive confetti and slab confetti.
Refusals
Under the stated constraints I would explicitly refuse the following claims.
Refusal	Reason
Original historical feature order	Boundary geometry generally does not uniquely encode construction chronology.
Physical thinghood with an invisible, non-identifiable interface	Multiple physical assemblies can produce the same observed exterior.
Hidden internal geometry without a uniquely constraining family/prior	The scan contains no evidence for it.
Arbitrary organic/freeform design intent from a single noisy mesh	Many editable parameterizations fit the same observations; a patch quilt is not design intent.
Features beneath measured spatial/form-error resolution	They are not reliably distinguishable from acquisition error.
Kinematic joint semantics from one static scan	Geometry does not establish intended motion.
Nominal/manufacturing-grid snaps without an independent prior	Closeness is not evidence of intended nominal value.
General autonomous parity with assisted commercial reverse engineering	Current commercial workflows themselves mix automation with guided modeling, and the runtime/domain constraints materially narrow the feasible algorithm set.
One refusal I would not make is a universal “anything below 10σ is impossible.” Identifiability depends on support area, sampling density, feature geometry, spatial correlation, direction, repeated evidence, and prior structure. A resolution report should come from the actual detector/model-comparison power in the relevant regime.
Phase B adversarial review of the design corpus
The findings below are ranked by how likely they are to let the implementation either violate the stated constraints or terminate “successfully” with an output a competent Fusion user would reject.
Critical findings
Severity	Finding	Judgment
Blocker	The architecture still contains a BaseFeature path, which is forbidden by the stated hard constraints.	Fact / evidence-backed judgment
Blocker	The canonical implementation contract still describes a different product from the one being designed.	Fact / evidence-backed judgment
Blocker	There is no sufficiently strong program-quality/model-selection layer between recovered geometry and emitted timeline.	Evidence-backed judgment
High	Parts of the statistical licensing framework make stronger inferential claims than their models justify.	Evidence-backed judgment
High	The slab representation can score well while producing semantically poor CAD.	Evidence-backed judgment
High	The scoreboard lacks feature precision, local causal editability, and program compactness.	Evidence-backed judgment
High	Preview Fusion APIs and a non-enforceable “timeout” are treated too casually as architectural elements.	Fact / evidence-backed judgment
High	The scan correlation model is being asked to support too many statistically different decisions.	Evidence-backed judgment
Medium	Componentization's ontology is excellent, but its current detection lane remains much narrower than the product narrative around it.	Evidence-backed judgment
BaseFeature is an actual specification violation
The Fusion-native architecture proposes:
“a new, optional … surfaced remainder … delivered as smooth reference surfaces in a base feature, explicitly labelled non-parametric …”
and its probe P5 seeks a route from NurbsSurface to “a body a base feature can hold.”
Fact. The problem statement explicitly bans BaseFeatures.
Evidence-backed judgment. This is not a trade-off to leave open. The entire surfaced-remainder outcome should be deleted from this project. If an irregular region cannot be represented as a real timeline loft/sweep or another allowed parametric feature, keep the immutable mesh as reference and count the region as unreconstructed.
There is no product value in violating the central “no history-free B-Rep masquerading as reconstruction” rule just to make the visual result more complete.
The canonical contract still defines the old product
The implemented contract says:
“So the segmentation layer is deleted and the grouping is the input.”
and:
“A dump that carries no grouping is refused face-groups-absent rather than segmented by a fallback nobody measured.”
The newer Fusion-native architecture says the opposite: segmentation stays and is “load-bearing twice,” while the scan-segmentation design builds an explicit region tree and cross-cut splitter.
Worse, the current contract still says:
“parametric-rebuild — rebuild only the geometry the edit requires … This is not a whole-part auto-converter.”
That is no longer the product described by the request.
Evidence-backed judgment. This is a blocker because it creates two internally legitimate definitions of success. A worker can faithfully implement mesh-reconstruction.md and still fail the actual project objective.
Before additional algorithm work, create a short supersession matrix and rewrite the canonical contract so that there is one answer to:
Is whole-part editable reconstruction a goal? Yes.
Is segmentation required for scans? Yes, when Fusion grouping is insufficient.
Is Fusion GFG authoritative? No.
Is a Mesh Convert body a reconstruction result? No.
Are BaseFeatures allowed? No.
Is historical original design intent promised? No; a licensed editable design-intent hypothesis is.
This documentation fix has higher leverage than another fitter because it closes a governance failure that can invalidate entire implementation branches.
Surface recognition is outrunning feature-program inference
The designs have become quite sophisticated about obtaining surfaces: RANSAC, face groups, cross-cut partitions, residual structure, relation classes, section events, shell pairs, material-side evidence.
The weak transition is still:
accepted geometry → chosen archetype → emitted feature.
The 2.5D design openly says:
“Operations are join-only.”
and argues that:
“joining each slab's measured profile cannot be [wrong] …”
Geometrically, a union of appropriately profiled slabs can indeed reproduce many 2.5D objects. Semantically, that does not imply it is a good CAD program.
Consider a simple block with two shallow pockets at different depths. A competent history might be:
text
Copy
Extrude base
Cut pocket A
Cut pocket B
Fillet pocket edges
The slab grammar can instead encode the same boundary as several changing cross-sections joined in sequence. The latter can pass geometric deviation and every parameter can be live, yet a user opening Fusion sees the wrong conceptual structure.
Point2Cyl's sketch/extrusion/Boolean representation and classical B-Rep reverse engineering both support modeling the generative operation rather than merely reproducing cross-sectional occupancy.
Compact-program work such as InverseCSG gives a direct framework for penalizing unnecessarily complicated constructive explanations.
Evidence-backed judgment. Keep slab decomposition, but demote it to two roles:
an evidence generator for topology changes, loops, depths, and candidate features;
a fallback program for geometry that cannot yet be factored into better semantic features.
Then run feature factorization over the slab representation:
text
Copy
slab occupancy differences
│
├── persistent added loop → boss/additive extrusion candidate
├── persistent removed loop → pocket/cut candidate
├── concentric circular removal → hole/counterbore candidate
├── constant offset cavity → shell candidate
├── repeated congruent changes → pattern candidate
└── unexplained → retain slab fallback
The compact feature program should win whenever it explains the same observations within the same fidelity budget.
The statistical framework is overconfident in places
The algorithms research says:
“σ is the foundation: it sizes neighbourhoods … the RANSAC band … covariance scale … and every statistical test …”
Later it describes approximately 6–10σ feature scales in information-theoretic language.
The scan-segmentation design itself discovered the practical failure: a real board scan exhibited flat-face form error many times larger than the earlier local σ estimate, so later work introduced a separate form-error lane and correlation model.
Evidence-backed judgment. That discovery should trigger a stronger architectural revision than merely adding another estimator. “σ” is not a physical property of the whole scan. The system needs a consumer-specific uncertainty model.
A local point-jitter scale can legitimately size a PCA neighborhood. It does not automatically establish the tolerance for a 70 mm plane's low-frequency bow. Likewise, one spatial correlation range cannot automatically establish the effective sample size for every nonlinear primitive parameter or the correct block size for every model comparison. Spatial effective sample size depends on correlation structure and sampling geometry, while block-selection methods are criterion dependent.
The nested-kind F tests are particularly fragile
The algorithms document treats relationships such as cylinder as a limiting torus and cone→cylinder degeneration as nested models and applies an ordinary nested-model parsimony F test.
Evidence-backed mathematical judgment. Those are not ordinary regular finite-parameter nests. “Torus major radius → infinity” is a singular limiting case, and cone half-angle → zero or another degenerate limit places parameters on a boundary where identifiability changes. The standard finite-sample F-test interpretation is therefore not licensed merely by writing one model as a limiting case of another.
I would replace those tests with:
spatially blocked held-out predictive comparison; and/or
a parametric bootstrap generated under the simpler candidate using the measured scan-error model.
The result should be recorded as model-selection evidence, not as an exact classical p-value whose assumptions are unverified.
Three section samples do not certify slab constancy
The 2.5D design says:
“one section characterises the slab, confirmed by sections at two more declared stations.”
using approximately quarter/mid/three-quarter sections.
Evidence-backed judgment. Three deterministic samples cannot prove no local topological event occurs between them.
A narrow boss, slot, chamfer termination, local rib, or scan defect can live entirely between sample planes. The plane-event machinery lowers the probability of this for strongly 2.5D mechanical parts, but it does not prove completeness because event-defining regions can themselves be rejected or missed.
The solution is not “use five sections.” It is adaptive:
derive predicted invariance from fitted side surfaces and event hypotheses;
verify with initially sparse sections;
compare interval support to the generative model;
insert another section where model residual, triangle provenance, or side-region endpoint evidence suggests unresolved variation;
stop only when every interval is below a declared geometric uncertainty bound or refuse.
In other words, certification should terminate on evidence, not on a fixed station count.
The scoreboard can reward garbage
The recognition scoreboard is conceptually strong in several respects: it explicitly distinguishes scripted, built, and verified coverage; adds non-vacuity; refuses to pretend host-side scripts are delivered geometry; separates physical-thing denominators from detector-produced counts; and moves toward exact triangle-disposition accounting.
But two gaps materially change optimization incentives.
Feature recall without precision
Vocabulary V largely asks how many evident feature instances/kinds were recovered.
Evidence-backed judgment. A system that finds the five real holes and hallucinates another six semantic holes can retain excellent recall. Negative claims are discussed, but they are not structurally part of the ratio.
Add feature precision and report a precision/recall pair. Do not collapse it immediately to one scalar if the evidence culture prefers vectors.
Editability does not prove correct causality
The scoreboard defines editability as:
“Parameters proven to drive ÷ parameters emitted”
using perturb/recompute/restore and observables including volume, centroid, and bounding box; it explicitly says interactions_exercised is false in the first version.
Evidence-backed judgment. This proves liveness, not necessarily semantic editability.
A supposed hole-diameter parameter that accidentally scales the whole body changes volume and bbox beautifully. A symmetric pair-spacing parameter might move two holes in opposite directions and leave the centroid unchanged. A station parameter can drive six unrelated slabs.
Add an expected parameter→region influence map, verify local geometry, verify non-target invariance, and exercise coupled parameters where expressions/constraints create interactions.
No program-quality dimension
This is the larger omission.
An eighty-feature slab-and-primitive timeline and a twelve-feature human-quality timeline can have equal:
RC;
feature-kind recall;
parameter liveness;
component count;
zero silent area.
Evidence-backed judgment. Add a sixth scored objective, P for program quality/compactness, before optimizing the existing scoreboard further. Compact generative programs are not just aesthetic; program-synthesis literature treats compactness as an important discriminator between alternative shape explanations.
Fusion Preview APIs need a harder architectural boundary
The Fusion-native design appropriately says Mesh Convert is “an accelerator, not authority.”
That is directionally correct.
There are two additional problems.
Release stability
Autodesk's current documentation marks MeshConvertFeatures.add and Mesh Generate Face Groups as Preview, with explicit warnings that Preview APIs may change and should not be used in distributed programs.
Autodesk documents prismatic conversion as a mesh-convert operation, not recovery of the source sketch/feature history.
Evidence-backed judgment. A trustworthy architecture may use these as opportunistic candidate sources, but core correctness must not depend on them. There also needs to be an explicit product policy for what “distributed program” means for this plugin's delivery model.
A synchronous call cannot be made safe by declaring a timeout
The design includes convert-timeout and says a per-region timeout prevents one region from stalling the stage.
Autodesk's API form is a synchronous add(input) call returning after the feature operation completes or fails.
Evidence-backed judgment. Unless Fusion exposes a cancellation/preemption mechanism not established in the design, a Python wall-clock timer can notice the overrun only after control returns. It cannot keep the UI thread responsive while the native operation is blocked.
Replace convert-timeout with:
pre-call triangle/complexity budgets based on measured conversion behavior;
explicit user cancellation only if a proven Fusion cancellation API exists;
post-call elapsed-time telemetry.
Do not write a refusal semantics that the execution model cannot actually enforce.
“Delete the spatial index and use broadcasting” is underspecified enough to be dangerous
The architecture says:
“Spatial grid index … numpy broadcasting for neighbourhoods at our mesh sizes … Delete.”
It also targets scans up to roughly millions of triangles.
Evidence-backed judgment. Literal broadcast pairwise distances at (N\sim10^6) is infeasible because the intermediate is (O(N^2)). Vectorization is not an indexing algorithm.
The implementation needs an explicit bounded-memory neighborhood strategy. Under the wheel constraints, plausible approaches include:
uniform hashed voxel/grid indexing implemented with NumPy sorting;
Morton-coded cells;
blockwise distance calculations after spatial binning;
Fusion-provided topology where it corresponds to the required neighborhood.
Delete hand-written general-purpose indexing only after the replacement has a stated asymptotic and memory bound.
The correlation amendment is better, but still over-centralized
The scan-segmentation amendments are a major improvement because they recognize that correlation calibration must not be fitted to the candidate it is being used to judge. They move toward one frozen candidate-independent correlation record.
But the same record is then intended to inform Moran testing, held-out separation, covariance inflation, relation uncertainty, and other consumers.
Evidence-backed judgment. Share the measured residual field and spatial scale, not necessarily one transformed statistic.
For example:
held-out validation needs spatial separation sufficient to limit leakage;
a block bootstrap needs a block design;
primitive-parameter covariance needs variation in fitted parameters across blocks;
relation testing needs the covariance of the relevant parameter combinations;
Moran's statistic needs a spatial weight/null construction.
One correlation length is useful input to all of those. It is not their common answer.
Threshold rationales are not yet calibration
The scan design admirably records rationales for such quantities as split-loss improvements, productive-child fractions, boundary costs, and validation fractions.
Evidence-backed judgment. A rationale is necessary but not sufficient when a threshold directly changes segmentation topology.
Before freezing such values as production defaults, sweep them over:
clean CAD tessellations;
synthetic noisy scans with known ground-truth regions;
multiple real scans with manually annotated major surfaces/features.
Publish sensitivity curves for over-split, under-split, feature recall, geometric coverage, and runtime. Until that exists, label those values experimental defaults rather than statistically licensed constants.
Componentization survives the strongest attack, with two qualifications
The componentization document's four-concept ontology is one of the strongest design decisions in the corpus:
surface-region → geometric model
geometric-subobject → separable exterior partition
physical-thing → independent-object evidence beyond separability
delivery-component → chosen editing unit.
It explicitly acknowledges the molded-boss counterexample and says reconstructed separability is not evidence of physical thinghood.
Evidence-backed judgment. Keep this ontology substantially unchanged. It independently converges on the identifiability boundary from Phase A.
Two claims should change.
First, the document says its product story:
“still exceeds the documented commercial bar”
because an early C2 stage can preserve separately placed reference-mesh components.
Evidence-backed judgment. That comparison is too broad. Preserving placement may exceed one aspect of a scan-separate-and-reassemble workflow, but reference meshes are not the requested editable parametric reconstruction. Do not describe C2 as exceeding the commercial reconstruction bar; call it a useful intermediate capability.
Second, current detection is deliberately strongest for candidates attached to accepted base faces and planar/contact-style interfaces, with multiple honest refusal modes for non-planar, through, or unsupported interfaces.
Evidence-backed judgment. That is a good v1 scope, not a general componentization solution. The external/product narrative should be restricted accordingly.
The document also correctly identifies stable thing-ID migration as unresolved.
Evidence-backed judgment: do not let later joint, update-in-place, or instance semantics depend on component identity until that identity model is decided.
Phase C convergence and divergence
Convergence
Independent agreement is especially valuable here because Phase A and the corpus often arrived at the same structural answer from different starting points.
Decision	Phase A	Attached design	Confidence
Detection need not wait for perfect segmentation.	Overcomplete primitive hypotheses first; segmentation by model competition.	007 explicitly reverses the old segmentation-first premise toward detection-first RANSAC.
High. Established practice. Efficient RANSAC directly supports it.
Raw scan evidence must remain immutable.	Derived signals may propose labels; refit/grade on immutable observations.	Hash binding, original triangle identities, partition lineage, derived-geometry ledgers.	Very high.
Local fits need global regularization.	GlobFit-style orientation/placement/equality relations.	007 has staged relation adoption and constrained refitting.
High. Supported by GlobFit/constrained fitting.
A fitted primitive is evidence, not automatically design intent.	Feature hypotheses interpret surfaces in generative context.	Relationship, archetype, kinematic-router, shell, hole, and fillet stages sit above fits.	High, though attached implementation does not yet take this far enough.
Fusion Convert is not the deliverable.	Convert may propose geometry but cannot restore a useful feature tree.	010 explicitly calls it an accelerator and says emission remains the deliverable.
Very high. Autodesk's API exposes a mesh-convert feature, not reconstructed original sketches/features.
Section/profile evidence is central for extruded geometry.	Custom plane-mesh intersection feeds feature hypotheses.	001 builds event/slab/loop machinery around sections.
High.
Blends should be interpreted through neighboring primary surfaces.	Fillet/chamfer late in feature program.	007 treats torus/partial blends as evidence for fillet features.
High. Classic blend-recovery work agrees.
Physical thinghood is stronger than geometric separability.	Independent evidence required.	004's four-concept ontology says exactly this.
Very high. Logical identifiability result.
Partial reconstruction with named refusal is preferable to invented certainty.	Unidentifiable regions/claims remain unreconstructed.	Closed refusal vocabularies, lose-only accounting, H ledger.	Very high.
Editability must be tested by perturbation, not designType.	Counterfactual edit/recompute verification.	003's E metric and existing perturbation doctrine.
High. Phase A strengthens the locality test.
One scalar “quality” score is dangerous.	G/F/E/P/C/H vector.	003 explicitly rejects one weighted scalar and uses RC/V/E/C/H.
High. Difference is what belongs in the vector.
Divergence
Question	Phase A	Attached design	Winner	Reason
What is the central IR?	Feature Hypothesis Graph + competing executable programs.	Accepted regions → archetypes/slabs → program.	Phase A.	The product goal is an editable feature program. Region coverage is evidence for that program, not the final abstraction.
How should pockets/steps be emitted?	Prefer explicit cuts/adds when licensed; use slab occupancy as evidence/fallback.	Join-only slab stack is deliberate.
Phase A.	Join-only preserves geometry but often destroys conceptual feature structure. Point2Cyl/classical RE favor generative extrusion/Boolean interpretation.
Is three-section agreement sufficient to establish a slab?	Adaptive interval validation.	Fixed quarter/mid/three-quarter confirmation.	Phase A.	Finite fixed samples cannot exclude a localized event between them.
How should scan uncertainty be represented?	Multiple consumer-specific scales/models.	Increasingly sophisticated σ/form-error/correlation record, but substantial shared calibration.	Phase A.	Point noise, form error, spatial dependence, block validation, and parameter covariance are related but not identical estimands.
Nested primitive model selection.	Held-out/bootstrapped comparison.	Ordinary F-style parsimony including singular limiting nests.
Phase A.	Torus→cylinder and cone→cylinder limits change parameter identifiability; ordinary regular nested-test interpretation is not established.
Freeform residual.	Editable sweep/loft if identifiable; otherwise refuse/preserve mesh.	Optional BaseFeature/NURBS surfaced remainder in 010.	Phase A, decisively.	The BaseFeature route violates the given constraints and would not provide design intent anyway.
What proves editability?	Local causal influence + non-target invariance + interaction tests.	Global observable perturb/recompute/restore is first scoreboard standard.	Phase A.	“Something changed” does not prove “the intended thing changed correctly.”
How should timeline quality be scored?	Explicit compactness/semantic score P.	No direct program-quality cell.	Phase A.	Without it, slab/primitive confetti can dominate RC while remaining unusable. InverseCSG supports compactness as a program-selection criterion.
Feature semantics metric.	Precision and recall.	Mainly vocabulary/evident-feature recovery plus negative annotations.	Phase A.	Recall alone does not penalize semantic over-recognition sufficiently.
Fusion GFG/Convert dependency.	Optional, corroborating, correctness independent.	Also “accelerator, not authority,” but more deeply built into 010's stage design.	Phase A's stricter boundary.	Both API surfaces are currently Preview.
Physical thing ontology.	Three claim levels with independent physical evidence.	Four-concept ontology, plus a separate surface-region level.	Attached design.	The corpus version is more precise and should be adopted as the canonical vocabulary.
Partition/honesty bookkeeping.	Immutable source disposition required.	Detailed region-tree lineage plus triangle state machine.	Attached design.	It is more operationally complete than Phase A and should win intact.
Whether to use relations globally.	Yes, but judged by counterfactual predictive effect.	χ²/covariance licensing plus staged constrained refit.	Hybrid: attached mechanism, Phase A acceptance test.	GlobFit supports global fitting; scan correlation makes nominal distributional confidence insufficient by itself.
Componentization v1 scope.	General evidence channels, refuse unseen ambiguous boundaries.	Accepted-base/contact-interface lane first.	Attached design for v1; Phase A for long-term architecture.	The attached scope is implementable and fail-closed, but should be described as restricted rather than general.
A particularly important point of agreement is also a terminology correction:
Evidence-backed judgment. Neither design should claim to recover “the original design intent” in a historical sense. The correct object is a compact, evidence-licensed editable design-intent hypothesis. Geometry can strongly constrain that hypothesis without uniquely identifying the original modeling chronology.
Phase C adoption, abandonment, and decisions
Adoption into the current design
Import	Amend	Evidence and rationale
Feature Hypothesis Graph and bounded program search	2026-08-19-010, after plan; 2026-08-20-001, after slab interpretation	Make regions/slabs evidence for alternative CAD programs. Point2Cyl demonstrates sketch/extrusion/Boolean inference; InverseCSG demonstrates compact-program search.
Semantic factorization of the slab stack	2026-08-20-001, immediately after slab classification	Detect persistent profile differences as boss/cut/pocket/hole/pattern candidates. Keep the join-only stack only when semantic factorization cannot be licensed.
Program-quality score P	2026-08-20-003, beside RC/V/E/C/H	Penalize primitive/slab confetti, duplicate values, unnecessary sketches/features, weakly constrained programs; compare to reference program where available. Compactness has direct precedent in shape-program inference.
Feature precision alongside vocabulary recall	2026-08-20-003, V definition	Prevent semantic over-recognition from being invisible to the headline vector.
Parameter→region causal influence map	2026-08-20-003, E; corresponding emitter/prover contract	Perturb parameters and verify intended local motion plus unrelated-region stability; add pairwise interaction cases for shared station/equality constraints.
Consumer-specific spatial uncertainty	2026-08-19-007 §§ noise/covariance/disproof; 2026-08-20-002 correlation amendment	Preserve measured spatial correlation information but derive held-out separation, parameter uncertainty, and relation confidence through their own estimators/resampling procedures. Spatial ESS is not one universal scalar.
Replace singular nested-kind F tests	2026-08-19-007, nested-kind parsimony	Use spatial held-out prediction and/or parametric bootstrap for cylinder/cone/torus/sphere degeneracies.
Adaptive slab certification	2026-08-20-001, constancy guard	Section adaptively where model/support evidence says uncertainty remains instead of asserting interval constancy from three fixed samples.
Preview-API release boundary	2026-08-19-010, capability policy	GFG and MeshConvert are optional candidate providers; absence/version break must not disable the native reconstruction route. Current Autodesk docs explicitly classify them as Preview.
Replace convert-timeout with enforceable resource policy	2026-08-19-010, prismatic-convert section	Pre-call region-size/complexity limits and post-call timing telemetry; do not claim preemptive timeout on a synchronous call.
Explicit bounded-memory spatial indexing	2026-08-19-010, numpy migration table	A NumPy implementation is appropriate; an (O(N^2)) broadcast neighborhood is not. State data structure, memory bound, and target size.
Operationalize physical-thing evidence predicates	2026-08-20-004 § ontology/licence	Keep the excellent ontology but make “independent channel” machine-checkable: disconnected topology, observed seam/gap, occlusion, uniquely constrained repeated instance, second view, or caller declaration.
Canonical supersession matrix	mesh-reconstruction.md, then cross-reference every design	Remove contradictory old statements about no segmentation, edit-specific-only reconstruction, and BaseFeature/freeform paths.
Abandonment list
BaseFeature surfaced remainder
Abandon: decisive.
It contradicts the supplied hard constraint and does not produce the requested parametric design intent anyway. The expired Geomagic NURBS patents are useful reminders that surface reconstruction is a mature but distinct objective.
“GFG is the segmentation; no fallback”
Abandon: decisive for scans.
The current contract's statement that “the segmentation layer is deleted and the grouping is the input” is already contradicted by the measured real-scan failure and the newer scan design.
GFG can remain a useful candidate partition.
Ordinary F tests over singular primitive degeneracies
Abandon: evidence-backed.
Keep parsimony as a principle, but not an uncalibrated classical F interpretation for models connected only by singular or infinite-parameter limits.
Universal ~10σ information-theoretic feature-resolution language
Abandon as a universal claim.
Replace it with measured detector power/resolution conditional on feature family, support, sampling, form error, and correlation.
Join-only slabs as the preferred final design representation
Abandon as an endpoint, retain as fallback.
Slabs are excellent evidence and can be an honest geometric fallback. They should lose to a smaller base+cut+boss+hole program whenever that program explains the same measured support.
Global-observable-only editability proof
Abandon as the scored proof.
Keep volume/centroid/bbox as cheap smoke tests, but make local causal influence the actual semantic editability criterion.
One correlation-length record as the final uncertainty answer to every subsystem
Abandon, while keeping one shared measured residual/correlation substrate.
Each consumer should derive the statistic it actually needs.
Preview Fusion APIs as indispensable production infrastructure
Abandon that dependency.
Autodesk's own current documentation warns about Preview stability.
They are valuable corroborating accelerators.
Decide before writing more code
The requested top five are not simply the five largest algorithmic unknowns. They are the five decisions whose absence would cause downstream code to encode the wrong abstraction.
First: freeze the canonical reconstruction contract and supersession order.
Evidence-backed judgment. This is the immediate blocker. mesh-reconstruction.md, 010, 001, 002, 003, and 004 currently span at least two product eras. State definitively that the goal is whole-part, editable, parameterized reconstruction with partial fail-closed coverage; custom scan segmentation exists; Mesh Convert is advisory; BaseFeatures are banned; a feature program rather than converted B-Rep is the output.
Second: define the Feature Hypothesis Graph and program-selection objective.
Evidence-backed judgment. This is the highest technical leverage. Decide the closed operation vocabulary, what support licenses each operation, Boolean polarity evidence, how dependencies are represented, how equivalent programs compete, and how complexity is charged. Otherwise every segmentation improvement merely produces more surfaces for increasingly ad hoc emitter rules. Program synthesis and sketch/extrusion inference literature show viable conceptual precedents.
Third: settle the scan-error/statistical contract.
Evidence-backed judgment. Decide which quantities represent local jitter, form error, spatial dependence, held-out independence, and parameter uncertainty; then revalidate every χ²/F/Moran/relationship/snapping gate against that contract. Do this before more relationship and snapping code because erroneous covariance assumptions propagate confidence into “design intent.”
Fourth: freeze the scoreboard including semantic precision, local causal editability, and program quality.
Evidence-backed judgment. Metrics create the optimizer. If P/precision/local causal E are added later, existing code may already have been optimized toward slab/primitive coverage that the new metrics punish. The non-vacuity gate was exactly this kind of late-discovered metric hole; avoid repeating it.
Fifth: decide component identity and the supported physical-evidence envelope before C5 semantics.
Evidence-backed judgment. Freeze stable IDs across partition refinements/rebuilds, evidence classes for hidden interfaces, occurrence-vs-definition semantics, and the exact v1 supported interface families. The four-concept ontology is ready; persistence semantics are not.
Two additional items are not really “decisions” and should simply be done: delete the BaseFeature design path, and make Preview APIs optional.
Overall verdict
What the program is already getting right
Evidence-backed judgment. The project is materially better positioned than a conventional “fit primitive patches and hope” reverse-engineering implementation.
Its strongest properties are mutually reinforcing:
007 moved from brittle segmentation-first thinking to detection and disproof.
010 correctly recognizes that Fusion should execute native CAD operations while the project's differentiating logic judges whether those operations are licensed.
002's region tree, cross-cut idea, partition invariants, reason-aware splitting, and partition lineage address the real scan failure rather than relaxing thresholds until something passes.
003 has unusually strong metric hygiene around non-vacuity, scripted vs built vs verified coverage, independent component denominators, and exact triangle disposition.
004's physical-thing ontology correctly identifies a fundamental observability limit that many automatic “part segmentation” systems would simply hallucinate through.
These principles align well with the strongest external reverse-engineering precedent: robust primitive detection, global relation recovery, constrained fitting, explicit blend interpretation, and compact generative explanations rather than literal surface copying.
What is still missing
The project currently has an asymmetry:
text
Copy
GEOMETRIC EVIDENCE
segmentation / fitting / gates
relations / covariance / lineage
sections / loops / shell pairs
████████████████
│
│
▼
FEATURE PROGRAM
archetype selection
slab emission
█████
│
▼
Fusion timeline
The upper half is receiving sophisticated statistical and systems engineering. The middle is still comparatively heuristic.
That is why I do not think the next order-of-magnitude gain comes from a better cylinder fitter, another segmentation splitter, or more aggressive Fusion conversion. It comes from turning the middle into a first-class inference problem.
Commercial-quality prognosis
Evidence-backed judgment. Under the current constraints, the program can plausibly reach commercially useful automatic output for a bounded domain of predominantly prismatic/revolved mechanical parts, particularly clean CAD exports and reasonably complete scans of parts whose manufacturing logic is well represented by extrudes, cuts, holes, shells, simple blends, and repeated dimensions.
That is a meaningful target. It includes a great deal of real mechanical reverse engineering.
It is not yet justified to claim a path to general commercial reconstruction quality across:
arbitrary scan form error;
arbitrary sweep/loft/freeform components;
hidden/internal features;
assemblies with invisible interfaces;
fully automatic feature semantics;
human-quality timeline compactness;
general component identification.
Current commercial systems advertise a broader toolbox that combines automated fitting with guided modeling, history-based CAD, surfacing, editable sketches/features, and deviation analysis.
The comparison should therefore be made per capability and per corpus, not as one “matches Design X” claim.
The highest-leverage trajectory change
Evidence-backed judgment.
Stop treating emission as the mostly deterministic consequence of accepted regions. Make emission the result of explicit, competing feature-program hypotheses.
Concretely:
text
Copy
region tree
+ primitive fits
+ sections
+ relationships
+ material-side evidence
+ component evidence
│
▼
FEATURE HYPOTHESIS GRAPH
│
├─ candidate A:
│    base extrude
│    pocket cut
│    4-hole pattern
│    shell
│    fillets
│
├─ candidate B:
│    7 joined slabs
│    4 independent holes
│
└─ candidate C:
base extrude
separate bosses
...
│
▼
bounded comparison on
held-out geometry
semantic evidence
unsupported inference
program compactness
editability constraints
│
▼
winning evidence-licensed program
│
▼
Fusion build
│
▼
local causal perturbation proof
│
▼
mesh deviation + feature/coverage ledger
That architecture gives every existing subsystem a clearer purpose.
Segmentation stops asking “what should I emit?” and asks “what geometric evidence exists?”
Relationships stop being decorative metadata and become constraints on competing programs.
Slab decomposition stops being the timeline and becomes a powerful topology/evidence representation.
Shell detection becomes a model hypothesis competing against explicit interior cuts.
Fillets become late generative explanations of blend support.
Componentization becomes a prior on program boundaries without overclaiming physical identity.
The scoreboard finally gets something meaningful to measure as program quality.
And, crucially, ambiguity becomes explicit. When two compact programs fit equally well, the system can say so instead of silently letting whichever emitter rule happened to run first become “design intent.”
That change is the shortest route from the project you have now, which is becoming a strong geometric recognition and evidence system, to the project the problem actually asks for: a strong mesh-to-editable-CAD program reconstruction system.
