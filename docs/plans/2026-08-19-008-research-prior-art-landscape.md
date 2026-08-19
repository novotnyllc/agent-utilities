---
title: "research: prior-art landscape — automated mesh-to-parametric CAD reconstruction"
date: 2026-08-19
artifact_contract: research-report/v1
execution: research-only
origin: https://github.com/novotnyllc/agent-utilities/issues/20
relates_to: docs/plans/2026-08-19-005-feat-mesh-parametric-reconstruction-plan.md
---

# Prior-Art Landscape: Mesh → Parametric CAD Reconstruction

Research report for issue #20. Maps the state of the art in automated mesh→parametric
reconstruction — segmentation, primitive detection, constraint inference, feature-tree
emission — and establishes what is freely implementable and why. Written against the
pipeline plan 005 is specifying (crease-based region growing, disproof-gated exact
fitting via `mesh_fitting.py`, pairwise intent proposals, Sketch-API feature emission).

**One legal caveat, stated once:** claim interpretation and infringement analysis are
legal questions. The plain-language claim summaries below are an engineer's reading, not
a legal opinion; anything commercially significant should be reviewed by a patent
attorney. Reading patents for technical understanding is ordinary engineering practice —
public disclosure is the purpose of the system — and everything below proceeds on that
basis.

---

## 1. Executive summary

1. **Every stage of the pipeline we are building is covered by freely implementable
   disclosure** — academic papers from 1988–2011 plus expired or abandoned patents. The
   commercial tools (Geomagic Design X, QuickSurface/Revo Design) are packaging and
   UX on top of this same literature, not a different algorithm class.

2. **The single most striking finding:** the core Design X-lineage method — section a
   mesh on a work plane, split the projected polyline into lines/arcs/curves by
   curvature distribution, link segments with constraints and dimensions, then extrude/
   revolve to match the mesh — was disclosed in US patent application
   **US20070285425A1 (INUS Technology, filed 2006-11-10)**, which was **abandoned and
   never granted in the US**. An abandoned published application is public disclosure
   with no US patent protection: it is an implementation-grade, free specification of
   exactly the workflow plan 005 describes. (Its granted Korean counterpart
   KR100753537B1 is territorial to Korea and, filed June 2006, is at or past its 20-year
   term as of 2026.)

3. **The strongest technique we are *not* currently planning to use is GlobFit's
   staged constrained re-fit** (Li et al., SIGGRAPH 2011): discover relations in a
   priority order (orientation → placement → equality), and after each stage **re-fit
   all primitives simultaneously under the accepted constraints** rather than merely
   annotating relations. `propose_design_intent` proposes; it never refits. The refit is
   what turns "axes 0.4° apart" into *exactly coaxial* features that survive a
   parametric recompute — directly on point for the constrained-refitting problem.

4. **Two live patent families are worth knowing; neither blocks the design.**
   USRE48498E1 (Hexagon Metrology Korea, expires 2029-04-28) claims interactive display
   of accuracy loss per user-selected modeling operation during reverse engineering —
   our batch, hash-bound deviation verdict is a different mechanism, and pre-2007
   deviation-colormap tools are prior context. US11921491B2 (Autodesk, expires 2039)
   claims a specific T-NURCC/quad-parameterization watertight B-Rep conversion pipeline
   — orthogonal to an analytic-primitive feature-emission approach.

5. **Learning-based methods (SPFN, ParSeNet, ComplexGen, Point2CAD, CADFit) are the
   current research frontier but need training data and dependencies we do not have.**
   Their most portable idea — CADFit's IoU-driven "fit an operation, validate against
   geometry, keep or discard" loop — is already the shape of plan 005's disproof gates
   and perturbation-based editability proof. We are architecturally aligned with the
   2026 frontier on validation; our gap is in constraint refinement and blend handling.

6. **Correction worth recording: `nurb` (github.com/Shpigford/nurb) is not a
   mesh→parametric reconstructor.** It is AI-authored build123d code generation plus
   printability validation. Its licence is FSL-1.1-MIT (source-available, non-compete;
   each release converts to plain MIT after two years) — not OSI open source; its code
   cannot be copied today. Its dependency licences are recorded in §6.

---

## 2. Technique-by-technique map

Each pipeline stage, the best-known published method, and where it is published. All
entries in this section are academic literature — freely implementable regardless of
patents (and mostly *predating* the relevant patent filings, which is the strong form of
freedom).

### 2.1 Noise assessment / preprocessing

- **Survey ground truth:** Kaiser, Ybanez Zepeda, Boubekeur, *A Survey of Simple
  Geometric Primitives Detection Methods for Captured 3D Data*, Computer Graphics Forum
  38(1):167–196, **2019**. The best single map of this whole space; use it as the index
  for anything not covered here.
- Plan 005's median-absolute-dihedral noise floor is a reasonable, honest instrument; no
  published method does materially better without normals estimation machinery we don't
  want. No change recommended.

### 2.2 Segmentation

- **Curvature-sign classification (oldest, cheapest, underused):** Besl & Jain,
  *Segmentation through variable-order surface fitting*, IEEE PAMI 10(2):167–192,
  **1988**. Classifies each vertex/region by the signs of mean (H) and Gaussian (K)
  curvature into eight surface types before any fitting: plane (H=0,K=0), ridge/cylinder
  (H≠0,K=0), sphere/peak (K>0), saddle (K<0). This is how Design X's Auto Segment
  decides a region "looks like" a cylinder vs. a torus vs. freeform before fitting.
- **Crease/region growing:** standard practice since the early 1990s; surveyed in
  Várady, Martin, Cox, *Reverse engineering of geometric models — an introduction*,
  Computer-Aided Design 29(4):255–268, **1997** (the canonical RE survey: phases,
  segmentation taxonomy — edge-based vs. face-based, region growing — and the
  fit-and-verify loop).
- **Hierarchical fitting-primitives clustering:** Attene, Falcidieno, Spagnuolo,
  *Hierarchical mesh segmentation based on fitting primitives*, The Visual Computer
  22(3):181–193, **2006**. Bottom-up: start from single triangles, greedily merge the
  adjacent pair whose union is best approximated by any primitive in the set
  (plane/sphere/cylinder), producing a binary tree of clusters; 100k faces in ~8s in
  2006. Reference implementation: EfPiSoft (efpisoft.sourceforge.net).
- **Variational partitioning:** Cohen-Steiner, Alliez, Desbrun, *Variational Shape
  Approximation*, SIGGRAPH **2004**. Lloyd-style alternation: fit k proxies, re-assign
  faces to the best proxy by distortion metric, iterate. The principled answer to
  "region boundaries should be where the *fit* says they are, not where the crease
  threshold says" — exactly the tangent-continuity problem plan 005's KTD4 names.
- **Direct/algebraic segmentation:** Benkő & Várady, *Direct segmentation of smooth,
  multiple point regions* (GMP **2002**); *Segmentation methods for smooth point regions
  of conventional engineering objects* (CAD 36(6):511–523, 2004). Segments by fitting
  translational/rotational algebraic surfaces directly, handling smoothly-joined
  regions that defeat crease detection.
- **Point-cloud primitive detection:** Schnabel, Wahl, Klein, *Efficient RANSAC for
  Point-Cloud Shape Detection*, Computer Graphics Forum 26(2):214–226, **2007**. The
  method the sibling agents are specifying. The parts that make it "efficient" and
  robust are not optional: localized sampling from an octree; candidate scoring by the
  **largest connected component of inliers** (via a bitmap in the shape's parameter
  domain, so a plane spanning two distant faces scores as two components, not one);
  probabilistic termination (stop when the probability of having missed a shape of the
  minimum size drops below a threshold); lazy score evaluation on subsets. Detects
  plane, sphere, cylinder, cone, **torus**.

### 2.3 Primitive fitting

- **Faithful distance-based fitting:** Lukács, Martin, Marshall, *Faithful least-squares
  fitting of spheres, cylinders, cones and tori for reliable segmentation*, ECCV
  **1998** (LNCS 1406). Parametrizes each primitive so the minimized quantity is a
  first-order approximation of true geometric distance and — critically — so the
  representation **degenerates gracefully** (a cylinder is a torus with infinite major
  radius; a plane is a sphere with infinite radius). This kills the bias and the
  near-degenerate blowups that plain algebraic least squares suffers.
- **Robust variant with degeneracy handling:** Marshall, Lukács, Martin, *Robust
  segmentation of primitives from range data in the presence of geometric degeneracy*,
  IEEE PAMI 23(3):304–314, **2001**.
- **Reference algorithms with public pedigree:** NIST's orthogonal-distance fitting
  algorithms for metrology (Shakarji, *Least-squares fitting algorithms of the NIST
  algorithm testing system*, J. Res. NIST 103:633, **1998**) — US government work,
  public domain, and the de-facto correctness oracle for plane/sphere/cylinder/cone
  fits (it is what CMM software is tested against).
- Our `mesh_fitting.py` already fits plane/cylinder/sphere/cone to analytic precision
  with residual gates. The gap against this literature: **no torus**, and no
  distance-faithful parametrization for near-degenerate cones (see §7).

### 2.4 Constraint inference and constrained (re)fitting

- **GlobFit:** Li, Wu, Chrysanthou, Sharf, Cohen-Or, Mitra, *GlobFit: Consistently
  Fitting Primitives by Discovering Global Relations*, ACM TOG 30(4) (SIGGRAPH)
  **2011**. Code: github.com/yangyanli/globfit. The method: fit primitives locally
  (via Efficient RANSAC); enumerate candidate pairwise relations whose deviation is
  below threshold; **validate and enforce them in a strict stage order** — orientation
  (parallel/orthogonal/equal-angle) first, then placement (coaxial, coplanar), then
  equality (equal radius/length) — accepting a relation only if a **simultaneous
  constrained re-fit of all primitives** under the accepted set keeps every fit within
  its noise bound, and rolling back the relation otherwise. This is the published,
  pre-packaged answer to our constrained-refitting problem, and it is 15 years old.
- **Constrained fitting (the numerical machinery):** Benkő, Kós, Várady, Andor, Martin,
  *Constrained fitting in reverse engineering*, Computer Aided Geometric Design
  19(3):173–205, **2002**. Simultaneous fitting of multiple surfaces under tangency,
  perpendicularity, parallelism, concentricity constraints — including the
  sequential/priority formulation that is stdlib-implementable (solve the constrained
  system by parameter elimination + one linearized least-squares pass, iterate) without
  a general nonlinear solver.
- **B-Rep assembly:** Benkő, Martin, Várady, *Algorithms for reverse engineering
  boundary representation models*, Computer-Aided Design 33(11):839–851, **2001**.
  From segmented, fitted, constraint-snapped surfaces to a topologically consistent
  B-Rep: intersection curves, vertex computation, stitching order.

### 2.5 Sectioning → sketch → feature emission

- **The free commercial-grade spec:** US20070285425A1 (abandoned; see §4.2) teaches the
  full loop: reference-frame derivation from curvature analysis or user input → work
  plane → project mesh section → split projected polyline into line/arc/curve segments
  by curvature distribution → attach constraints and dimensions parametrically →
  extrude/revolve/loft → boolean merge → deviation check. This is a superset of our
  `section_mesh` + `classify_polyline` + planned Sketch-API emission, in patent-level
  detail, with no US protection.
- **Extrusion decomposition as a formal problem:** Uy et al., *Point2Cyl: Reverse
  Engineering 3D Objects from Point Clouds to Extrusion Cylinders*, CVPR **2022**
  (arXiv 2112.09329). Defines the "extrusion cylinder" (sketch + axis + extent)
  decomposition our extrude-emission path implicitly targets; learning-based, but the
  problem formalization and metrics are reusable.
- **Program-fitting frontier:** *CADFit: Precise Mesh-to-CAD Program Generation with
  Hybrid Optimization* (arXiv 2605.01171, **2026**; code on GitHub, licence unverified).
  Watertight mesh in → ordered program of extrusions, revolutions, fillets, chamfers
  out, found by IoU-driven optimization that incrementally fits and validates parametric
  operations with geometric feedback. Independent confirmation that
  "emit-validate-refuse" per feature — plan 005's architecture — is where the 2026
  state of the art landed.
- Other current learning-based work, noted for completeness and all requiring training
  corpora (ABC dataset or similar) plus torch-class dependencies we do not have:
  SPFN (Li et al., CVPR 2019, arXiv 1811.08988 — supervised primitive fitting);
  CPFN (ICCV 2021 — cascaded, high-res); ParSeNet (Sharma et al., ECCV 2020, arXiv
  2003.12181 — adds B-spline patches); HPNet (2021); ComplexGen (Guo et al., SIGGRAPH
  2022 — joint corner/curve/patch B-Rep chain complex; outputs frequently
  geometry/topology-inconsistent); Point2CAD (Dupont et al., CVPR 2024, arXiv
  2312.04962 — segmentation network + analytic/spline fitting + topology
  reconstruction, outperforms ComplexGen); Point2Primitive (2025, arXiv 2505.02043).

### 2.6 Validation / deviation analysis

- Fit-and-verify loops with deviation maps are in the literature from Várady 1997
  onward, and in shipping tools (Geomagic Qualify 2003-era, PolyWorks Inspector) well
  before 2007. Plan 005's asymmetric deviation verdict plus perturbation-based
  editability proof goes *beyond* published practice (nothing in the academic
  literature recomputes the feature tree under parameter perturbation to prove
  editability) — that part is ours.
- The one live patent in this area (USRE48498E1) claims a specific interactive
  mechanism; see §5.1.

---

## 3. The freely implementable set (with dates)

Everything in this table is implementable today in the US without permission. The
"why free" column is the load-bearing part.

| Technique | Source | Date | Why free |
|---|---|---|---|
| HK curvature-sign region typing | Besl & Jain, PAMI | 1988 | Academic publication; any related patents long expired |
| RE pipeline architecture (segment→fit→verify) | Várady/Martin/Cox, CAD 29(4) | 1997 | Academic survey |
| Faithful LS fitting of sphere/cyl/cone/**torus** | Lukács/Martin/Marshall, ECCV | 1998 | Academic publication |
| NIST orthogonal-distance reference fits | Shakarji, J. Res. NIST | 1998 | US government work, public domain |
| Robust fitting under degeneracy | Marshall/Lukács/Martin, PAMI | 2001 | Academic publication |
| B-Rep assembly from fitted surfaces | Benkő/Martin/Várady, CAD 33(11) | 2001 | Academic publication |
| Constrained multi-surface fitting | Benkő/Kós/Várady/Andor/Martin, CAGD 19(3) | 2002 | Academic publication |
| Direct segmentation of smooth regions | Benkő/Várady, GMP | 2002 | Academic publication |
| Variational shape approximation | Cohen-Steiner/Alliez/Desbrun, SIGGRAPH | 2004 | Academic publication |
| Hierarchical fitting-primitives segmentation | Attene/Falcidieno/Spagnuolo, Vis. Comput. 22(3) | 2006 | Academic publication |
| Efficient RANSAC (all five primitives, CC scoring, octree sampling, probabilistic stop) | Schnabel/Wahl/Klein, CGF 26(2) | 2007 | Academic publication (the *paper*; the original *code* is research-use only — see §6) |
| Staged relation discovery + constrained global re-fit | Li et al. (GlobFit), SIGGRAPH | 2011 | Academic publication |
| Section→constrained-sketch→feature workflow | US20070285425A1 (INUS) | filed 2006, published 2007 | **Abandoned US application** — published disclosure, never granted, no US protection |
| Alpha-shape/Delaunay point wrap | US6377865 (Raindrop Geomagic) | filed 1999 | **Expired** (~2019) |
| Auto NURBS quilting of triangulated surfaces (decimation hierarchy + homeomorphisms + quad patching) | US6996505 (Raindrop Geomagic) | filed 2000-06-29 | **Expired 2023-06-29** (status confirmed on Google Patents) |
| Independent parameterization/fitting of patch networks | US6256038, US6253164 (Paraform) | filed 1998–99 | **Expired** |
| Parametric master-model RE process | US7219043 (General Electric) | filed 2002-02-05 | **Expired** (fee-related, 2024) |

Rule of thumb the table instantiates: US utility patents run 20 years from filing, so
**anything filed before ~2006 is expired and its full disclosure is public domain**.
The foundational Raindrop Geomagic / Paraform / Imageware-era reverse-engineering
filings all fall in that window. An expired patent is a free, implementation-grade
description of a working method — that is the bargain the patent system strikes.

### What the significant expired/abandoned families actually teach

- **US6996505** (Geomagic, expired 2023): a complete automatic mesh→NURBS pipeline —
  quadric-error-metric decimation building a hierarchy of simpler meshes linked by
  simplicial homeomorphisms; character-line (hard edge / high curvature) detection and
  preservation; triangle-pair matching into quad patches; grid fitting; watertight
  NURBS output; hole-fill by refine-then-decimate. Not our current stage (we emit
  analytic features, not spline quilts), but it is the free blueprint if issue #20 ever
  grows a freeform fallback for the "unreconstructed 30%".
- **US6377865** (Geomagic, expired): Delaunay tetrahedrization + wrap (alpha-shape
  lineage, Edelsbrunner) for point cloud → manifold mesh. Upstream of our pipeline
  (Fusion gives us a mesh) but relevant if raw scans ever arrive.
- **US20070285425A1** (INUS, abandoned): described in §2.5 — the single most
  on-point document in this entire report, and free.
- **US7219043** (GE, expired 2024): reverse/re-engineering via a knowledge-driven
  parametric master model plus per-manufacturing-step context models. Teaches the
  "capture intent as parameters + rules, not geometry" doctrine at industrial scale.

---

## 4. Live-patent landscape (filed ~2006 onward)

Searched: Autodesk, Dassault, Siemens, Ansys/SpaceClaim, 3D Systems/Geomagic/INUS
lineage (now partly Hexagon), via Google Patents and USPTO full-text. The search was
targeted, not exhaustive; findings below are the families that came back plausibly
relevant. Notably, **no live US patent was found covering the general
"segment mesh → fit primitives → emit constrained parametric features" pipeline** —
the on-point INUS application was abandoned, and the general method is anticipated by
the pre-2006 literature in §3 anyway.

### 4.1 USRE48498E1 — "Analyzing modeling accuracy while performing reverse engineering"

- **Holder:** Hexagon Metrology Korea (reissue of US7,821,513, INUS/3D Systems; original
  filed 2007-04-09). **Status: active, expires 2029-04-28.**
- **Independent claims in plain language:** a CAD system that receives 3D scan data,
  lets the user select an editing/modeling operation, **computes the accuracy loss that
  operation introduces relative to the scan**, and **displays that loss to the user**
  (as error maps) so they can proceed, adjust, or abandon. Claimed as medium, method,
  and system.
- **Relevance to us:** superficial. Our deviation verdict is a batch, non-interactive,
  hash-bound comparison of the *finished* reconstruction against the mesh with an
  asymmetric threshold — not a per-operation, user-facing accuracy-loss display inside
  a modeling session. The claim elements (user selects operation → system shows loss
  for that operation) are absent from our design.
- **Prior-art posture:** scan-vs-CAD deviation colormaps shipped in Geomagic Qualify
  and PolyWorks Inspector years before the 2007 filing, and the fit-and-verify loop is
  in Várady 1997; the reissue's survival suggests the *per-operation interactive*
  framing is the novel element. If a future feature ever adds "show accuracy impact of
  each proposed edit live in the UI", that is the one to re-read (with counsel).

### 4.2 US20070285425A1 — the abandoned INUS application

Listed here for completeness because a reader will find it in any search: **abandoned,
never granted in the US, no protection**. Its Korean counterpart KR100753537B1 was
granted; Korean patents are territorial and its 20-year term from the June 2006 filing
is at or past its end as of mid-2026. Treat the document as free teaching material.

### 4.3 US11921491B2 — Autodesk, "Conversion of mesh geometry to watertight boundary representation"

- **Status:** active; priority 2018-11-09; expires ~2039.
- **Independent claims in plain language:** convert a mesh to a watertight B-Rep by
  extracting a quad parameterization (Integer-Grid-Map lineage), blending with smooth
  boundary curves via transfinite interpolation, building **locally refinable T-NURCC
  spline surfaces** whose boundaries are frozen to CAD-kernel tolerance while the
  interior is approximated at a much looser tolerance, then stitching into existing
  solids.
- **Relevance to us: none in the current design.** We emit analytic primitives through
  Fusion's feature API; we build no spline surfaces, no quad parameterization, no
  stitching. If a freeform fallback is ever added, the expired US6996505 pipeline
  (§3) is the freely implementable alternative route to the same end — and the academic
  IGM papers the Autodesk patent itself builds on (Bommes et al. 2013, Campen et al.
  2015) predate its 2018 priority.

### 4.4 Other live-era families checked and set aside

- **US9474582B2** (personalized orthopedic implant CAD generation) — domain-specific,
  medical; not relevant.
- Autodesk/ANSYS "mesh to patch" tooling (SpaceClaim skin/patch) — no blocking family
  surfaced for primitive-feature reconstruction; SpaceClaim's shipped capability is
  facet-region fitting consistent with the pre-2006 literature.
- Siemens/Dassault: nothing surfaced on mesh→feature-tree reconstruction specifically;
  their filings in this era cluster around direct modeling and synchronous technology,
  which is a different problem.

**Honest limitation:** patent searching is recall-limited; a clearance search is a
different product than this report. What this report *can* say strongly: for every
stage of our pipeline there exists published academic prior art dated 1988–2011, which
is the strongest possible ground — stronger than designing around any particular live
claim.

---

## 5. What the commercial tools actually do (published workflow as specification)

### 5.1 Geomagic Design X (Rapidform XOR lineage, now Hexagon)

Published workflow, from its user guide and reseller documentation:

1. **Mesh prep** — Mesh Build-up Wizard: healing, watertighting, smoothing, decimation.
2. **Auto Segment** — cluster adjacent polygons by similar curvature into **regions**;
   classify each region as plane / cylinder / sphere / **torus** / cone / revolution /
   extrusion / freeform from the cluster's curvature signature (the Besl–Jain idea).
   Regions are first-class objects used to define sketch planes and cutting planes.
3. **Feature extraction wizards** — Extrusion, Revolution, Sweep, Loft, Pipe wizards
   fit a feature to a selected region set; "Quick Modeling" chains these automatically.
4. **Mesh Sketch** — section the mesh with a plane; auto-trace the section polyline
   into a fully **constrained and dimensioned** 2D profile (auto sketch with
   constraint snapping).
5. **Accuracy Analyzer** — always-on deviation colormap between the growing CAD model
   and the scan (the USRE48498 mechanism, §4.1).
6. **LiveTransfer** — replay the native feature tree into SOLIDWORKS/NX/Creo/Inventor
   so the target CAD holds a real history, not an import.

The structure is exactly plan 005's structure (regions → per-region fit → sketch with
constraints → features → deviation verdict → editable-tree proof), which is both a
validation of the design and a reminder that the shape of the pipeline is 20+ years
old and free — Design X's moat is polish, blends, and LiveTransfer plumbing, not a
secret algorithm.

### 5.2 QuickSurface / Revo Design (Pro)

Same skeleton, lighter: mesh cleanup and world-frame alignment → region-based primitive
extraction (plane/cylinder/sphere/cone/torus) with **user-applied constraints between
primitives** (coaxial, perpendicular…) → sketch-on-section with snapping → solid
features with history export to SOLIDWORKS via plugin → real-time deviation display →
one-click G2 "autosurface" quilt for organic remainder regions. The notable published
detail: it treats *hybrid* output (prismatic features + freeform quilt for the
remainder) as the normal case — the same "partial reconstruction is a declared
outcome" stance plan 005 takes.

---

## 6. Open-source implementations and licences

| Project | What it has | Licence | Use for us |
|---|---|---|---|
| **CGAL Shape Detection** (`Shape_detection`) | Efficient RANSAC (plane/sphere/cylinder/cone/torus) + Region Growing (point sets: 2D lines/circles, 3D planes/spheres/cylinders; meshes: planes) | **GPL** side of CGAL's split (kernel/support are LGPL; algorithm packages including this one are GPL; commercial licences sold by GeometryFactory) | Correctness oracle only — GPL is incompatible with vendoring, and stdlib-only rules it out anyway. Ideal for generating reference outputs on test meshes. |
| **PCL** `sample_consensus` | RANSAC family (plane, sphere, cylinder, cone, line, …) | **BSD-3-Clause** | Permissive reference; algorithms may be re-derived freely. |
| **Open3D** | `segment_plane` RANSAC, clustering, mesh ops | **MIT** | Permissive reference / test-fixture generator. |
| **GlobFit** (yangyanli/globfit) | The SIGGRAPH 2011 constrained-refit pipeline (C++ + MATLAB) | Repo licence not stated in top-level page — **verify LICENSE file before any reuse**; treat as reference-only until confirmed | The exact reference for §7 recommendation 1. |
| **EfPiSoft** | Attene 2006 hierarchical segmentation | SourceForge listing; licence unverified | Reference-only. |
| **Original Schnabel code** (mirrored at alessandro-gentilini/Efficient-RANSAC-…) | The authors' Efficient RANSAC | **"Research purposes only"** (confirmed from its ReadMe) | Must not be copied. The *paper* is free to implement; CGAL is the maintained reimplementation. |
| **point2cad** (prs-eth), **CADFit** (ghadinehme) | Learning/hybrid mesh→CAD pipelines | Licences unverified | Benchmarks and problem formalization. |
| **nurb** (Shpigford/nurb) | AI-authored build123d part generation + 13 printability checks + slicer integration. **Not a mesh→CAD converter** — confirmed by reading the repo. | **FSL-1.1-MIT** — source-available, non-compete, **not OSI open source**; each release converts to plain MIT two years after that release | Code cannot be copied now. Its dependency stack is informative if the no-dependency decision is ever revisited: **build123d Apache-2.0, OCCT LGPL-2.1-with-exception, trimesh MIT, numpy BSD-3-Clause, three.js MIT, websockets BSD-3-Clause, watchdog Apache-2.0** — i.e. a fully permissive/LGPL geometry stack exists beneath it. |

Note for the stdlib-only rule: nothing in this table needs to enter our tree. The
value is (a) oracles for tests, and (b) proof that a permissive path exists if the
dependency decision is ever reopened — OCCT's LGPL-with-exception plus build123d's
Apache-2.0 impose no copyleft on callers.

---

## 7. Recommendations for our design

Concrete, ordered by expected value. Items 1–3 are things the current
Efficient-RANSAC-plus-exact-fitters plan is **missing relative to the state of the
art**; 4–6 are hardening details; 7–8 are confirmations.

1. **Adopt GlobFit's staged constrained re-fit (the biggest gap).** Today
   `propose_design_intent` *annotates* relations (coaxial/parallel/perpendicular/
   symmetric/nominal) but nothing *re-fits under them*. Implement the 2011 recipe:
   (a) accept orientation relations first, re-fit all primitives with axes constrained
   (a linearized least-squares pass per primitive with the shared direction fixed —
   stdlib-tractable, no general NLP needed per Benkő 2002's sequential formulation);
   (b) then placement (coaxial/coplanar), re-fit; (c) then equality (equal radius —
   also fills plan 005's admitted `equal_radius` gap); accept each relation only if
   every constrained fit stays within its measured noise bound, else roll back. This
   turns near-relations into exact CAD constraints that survive recompute, and it is
   precisely the mechanism that makes emitted features look designed rather than
   scanned.

2. **Add the torus, or every filleted part caps our coverage.** Real mechanical parts
   are planes/cylinders joined by fillets; a pipeline without a torus/blend story
   reports every blend as unreconstructed area. Efficient RANSAC's original primitive
   set includes torus; Lukács–Martin–Marshall 1998 gives the faithful,
   degeneracy-safe torus fit implementable with our existing eigen/least-squares
   toolkit. Emission maps a torus region adjacent to two primary regions to a Fusion
   **fillet feature on the shared edge** (radius = minor radius), not to torus
   geometry — which is also what Design X does.

3. **Pre-classify regions by curvature signs before fitting (Besl–Jain 1988).**
   Estimate per-region mean/Gaussian curvature signatures from the mesh (cheap:
   dihedral-angle-weighted normals we already compute) and use them to *rank* candidate
   primitive types per region. This shrinks the disproof matrix from "try all four
   (five) fits per region" to one or two candidates plus disproof, and it gives the
   refusal ladder a better message ("region reads as doubly-curved freeform; no
   primitive candidate") than four failed fits do.

4. **Complement fit-driven *splitting* with fit-driven *merging*.** Plan 005's KTD4
   splits over-merged crease regions; the mirror failure — one surface shattered into
   many regions by noise — is handled by Attene 2006's hierarchical merge (merge
   adjacent regions while a single primitive still fits within tolerance). One
   bottom-up pass after crease growing, reusing the same fitters and gates. VSA-style
   Lloyd re-assignment is the fancier alternative; the merge pass is the lazy 80%.

5. **If the sibling Efficient-RANSAC spec drops any of these three details, it will
   over-merge or thrash** (worth checking their draft explicitly): (a) score candidates
   by **largest connected component** of inliers, not raw inlier count; (b) sample
   locally (octree cell) rather than globally; (c) probabilistic stopping tied to
   minimum-shape-size, not a fixed iteration count. These are the paper's actual
   contributions over vanilla RANSAC.

6. **Sketch-segment splitting by curvature distribution** (from the abandoned INUS
   application): when classifying section polylines, split at extrema of the discrete
   curvature along the polyline before greedy line/arc fitting. Our current greedy
   classifier can absorb a gentle arc into a line run; curvature-driven split points
   are the published fix, and free.

7. **Keep the disproof gates and perturbation-based editability proof unchanged.**
   Nothing in the 2019 survey, GlobFit, or the 2024–2026 learning literature validates
   harder than plan 005 already does; CADFit's geometric-feedback loop independently
   converged on the same architecture. This is a place we are *at* the frontier, not
   behind it.

8. **No live patent requires a design change.** The two relevant live families
   (USRE48498E1, US11921491B2) claim mechanisms we do not use (interactive
   per-operation accuracy display; T-NURCC watertight conversion). For every mechanism
   we *do* use, published prior art dated 1988–2011 exists and is cited in §3 — which
   is stronger ground than any design-around. Re-engage counsel only if this becomes a
   commercial product or if an interactive accuracy-display UX is ever added.

---

## Sources

Academic:
- Schnabel, Wahl, Klein 2007 — https://onlinelibrary.wiley.com/doi/10.1111/j.1467-8659.2007.01016.x ; https://cg.cs.uni-bonn.de/publication/schnabel-2007-efficient
- Li et al., GlobFit 2011 — https://graphics.stanford.edu/~niloy/research/globFit/globFit_sigg11.html ; code https://github.com/yangyanli/globfit
- Attene, Falcidieno, Spagnuolo 2006 — https://link.springer.com/article/10.1007/s00371-006-0375-x ; https://efpisoft.sourceforge.net/
- Várady, Martin, Cox 1997 — https://www.semanticscholar.org/paper/bacfc96d8da86d7871040dc3e7d328116b7ec961
- Benkő, Kós, Várady, Andor, Martin 2002 — https://orca.cardiff.ac.uk/id/eprint/1812/1/ConstrainedFitting.pdf
- Benkő, Martin, Várady 2001 — https://www.sciencedirect.com/science/article/abs/pii/S0010448501001002
- Lukács, Martin, Marshall 1998 — https://link.springer.com/chapter/10.1007/BFb0055697
- Cohen-Steiner, Alliez, Desbrun 2004 — https://www.geometry.caltech.edu/pubs/CAD04.pdf
- Kaiser, Ybanez Zepeda, Boubekeur 2019 survey — https://onlinelibrary.wiley.com/doi/10.1111/cgf.13451
- SPFN — https://arxiv.org/abs/1811.08988 ; ParSeNet — https://arxiv.org/abs/2003.12181 ; CPFN — https://arxiv.org/abs/2109.00113 ; Point2Cyl — https://arxiv.org/abs/2112.09329 ; ComplexGen — https://arxiv.org/pdf/2205.14573 ; Point2CAD — https://arxiv.org/abs/2312.04962 ; Point2Primitive — https://arxiv.org/abs/2505.02043 ; CADFit — https://arxiv.org/abs/2605.01171

Patents:
- US6996505B1 — https://patents.google.com/patent/US6996505B1/en (expired 2023-06-29)
- US6377865B1 — https://patents.google.com/patent/US6377865 (expired)
- US6256038B1 — https://patents.google.com/patent/US6256038 ; US6253164B1 — https://patents.google.com/patent/US6253164B1/en (expired)
- US7219043B2 — https://patents.google.com/patent/US7219043B2/en (expired 2024, fee-related)
- US20070285425A1 — https://patents.google.com/patent/US20070285425 (abandoned)
- USRE48498E1 — https://patents.google.com/patent/USRE48498E1/en (active, expires 2029-04-28)
- US11921491B2 — https://patents.google.com/patent/US11921491B2 (active, priority 2018)

Commercial workflow documentation:
- Geomagic Design X user guide (2013) — https://www.engineering.pitt.edu/contentassets/52314f399aba40fa86709314a569641c/geomagicdesignx2014userguide.pdf
- Design X regions/workflow — https://www.cati.com/blog/geomagic-design-x-the-impact-of-regions-when-reverse-engineering/ ; https://hexagon.com/products/geomagic-design-x
- QuickSurface / Revo Design — https://www.quicksurface.com/revo-design-powered-by-quicksurface-a-game-changer-for-3d-engineering/ ; https://global.revopoint3d.com/products/quicksurface

Licences:
- CGAL licensing — https://www.cgal.org/license.html ; Shape Detection — https://doc.cgal.org/latest/Shape_detection/index.html
- Schnabel original code terms — https://raw.githubusercontent.com/alessandro-gentilini/Efficient-RANSAC-for-Point-Cloud-Shape-Detection/master/ReadMe.txt
- nurb — https://github.com/Shpigford/nurb (FSL-1.1-MIT)
