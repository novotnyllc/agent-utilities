# Downloaded-part reconstruction benchmark

Four models somebody actually downloaded and printed, kept byte for byte, plus
what this skill's reconstruction pipeline measured on each. Two of them carry an
answer key that did not come from this pipeline, which is the whole point:

| pair | mesh input | ground truth |
| --- | --- | --- |
| honeycomb organiser | `parts/honeycomb-tool-organizer.stl` | `parts/honeycomb-tool-organizer.step` — the vendor's own B-Rep |
| unicorn horn | `parts/unicorn-horn-4examples-v3.3mf` | `parts/unicorn-horn-parametric-multi-v3.f3d` — the native Fusion archive, **and** `parts/unicorn-horn-4examples-v3.step` |
| tropical leaves | `parts/tropical-leaves.stl` | none; it is here to be refused |
| desktop organiser | `parts/desktop-organiser-bambulab-v0.3mf` | none; it is here to prove 3MF intake |

Every file kept its bytes and lost its awkward name. The original names are in
`benchmark-manifest.json` next to each file's sha256 and size, and
`.gitattributes` marks `parts/` and `dumps/` as binary so a checkout cannot
normalise a line ending and break the digest the whole benchmark hangs from.

## What ran, and where the Fusion boundary is

Inside live Fusion, once, at version 2705.0.108:

* the two STEP files were imported and every face read out with its surface kind
  and parameters, into `ground-truth/*.brep.json`;
* the F3D archive was imported and its timeline and user parameters read out,
  into `ground-truth/*.timeline.json`;
* each mesh was imported as a mesh body and the skill's own
  `emit-mesh-capture`, `emit-mesh-face-groups` and `emit-mesh-extract` scripts
  were run against it, producing the hash-bound dumps in `dumps/`.

Everything downstream of the dump — `fit-regions`, `plan-reconstruction`,
`reconstruction-coverage`, and the emission of the rebuild script — is host-side
with no Fusion at all. That is why the whole benchmark replays from this
repository alone, and why `tests/test_reconstruction_benchmark.py` can assert it.

## The result

**No part in this corpus reaches a built reconstruction, and each stops at a
named gate.** That is the finding, not a preamble to one. Two of the four stop
at the same one — a section that closes more than one loop — which is what the
corpus looks like once the datum frame stops being the first thing in the way.
The horn is the one part where it still is, and it now says which measurement
stops it: two axis candidates a third of a degree apart, one of them carrying a
direction sigma three times the grid that would separate them.

| part | triangles | face groups | regime | accepted fits | fit coverage | stops at | gate |
| --- | ---: | ---: | --- | --- | ---: | --- | --- |
| honeycomb organiser (STL) | 556 | 121 | tessellation | 39 — 39 planes | 41.6% | emit-rebuild | `profile-ambiguous` |
| unicorn horn (3MF) | 88,334 | 620 | scan | 23 — 20 planes, 3 cylinders | 4.8% | plan | `frame-ambiguous` |
| tropical leaves (STL) | 86,394 | 2,299 | scan | 49 — 48 planes, 1 sphere | 19.0% | emit-rebuild | `profile-ambiguous` |
| desktop organiser (3MF) | 6,502 | 790 | scan | 36 — 21 planes, 15 spheres | 27.9% | — | emitted; 1 `sketch-extrude`, 22.5% planned |

### The honeycomb, which is the one the STEP can grade

The vendor STEP is **145 planar faces in exactly four directions** — three
vertical walls 120° apart and one horizontal — and not one cylinder, cone,
sphere or torus anywhere. The STL is the same solid: its summed facet area
agrees with the STEP's analytic area to 3.2e-08 relative, its volume to 7.7e-07,
and its bounding box to 2.3e-06 mm. Those three are all invariant under moving
the part, and this mesh *is* moved — it arrives with its bounding-box corner on
the origin — so position is checked through the single rigid translation between
the two, `(76.25, 86.946886, 2.0)` mm, measured from the two bounding boxes and
recorded in the manifest.

It now fits: **45 regions, 39 accepted, every one a plane, 41.6% of the area,
every one parallel to one of the STEP's own face normals to 0.0° with all four
families hit, and every one landing on that face's plane to 1.1e-05 mm** once
that translation is applied. Not one cylinder, cone, sphere or torus is claimed —
which is the strongest check this pair affords, because the STEP says the part
contains none.

(The 0.38° this used to report was never the agreement: the family table's
normals are rounded to three decimals, and 0.38° is how far an exact
`0.866025404` sits from a stored `0.866`. It is still recorded, under a name that
says what it measures.)

Getting there took two fixes, and this part is what found both.

**The noise estimator was measuring the part.** `_sigma_dihedral` states its own
assumption:

> "Real creases are a small minority of interior edges on a mechanical part, so
> the median sees only the noise."

On a honeycomb that is false. 61.5% of the interior edges are genuine 60° cell
creases, so the median interior dihedral is 59.99993° and estimator B reported
13.108 mm of noise — on a mesh whose quadric estimator reports **exactly zero**
and whose regime is correctly detected as an exact tessellation. Ten sigma is the
recoverable feature size, so the whole 168.9 mm part refused
`feature-scale-below-noise` claiming 131.08 mm was unrecoverable. `sigma` was
`max(quadric, dihedral)` computed *before* the regime was known, so the regime
check that already suppressed the `noise-model-inconsistent` *flag* never saw the
*value*. The regime is detected first now: on a tessellation `sigma` is the
quadric estimator alone, and the dihedral reading becomes `surface_scale`, which
is where a facet turn angle belongs and which is what it already reached through
`sigma` — so every power floor sized by it is untouched. Both estimators stay in
the record, with `noise.sigma_estimator` naming the one chosen.

**Six flat walls fitted as their own circumscribed cylinder.** With the estimator
fixed, the fitter claimed **6 cylinders of radius 12.990381 mm that the STEP
proves do not exist**. A regular hexagon's six corners lie *exactly* on that
circle, so each pocket's six walls — delivered as one face group — fitted a
cylinder at float-noise residual, and every gate that reads vertices passed it.
The same corners lie on a sphere just as exactly. The facet normals are the only
evidence that separates them: they sit within 0° of perpendicular to one axis but
occupy five discrete directions across 240° of arc, 7.5 per full turn against a
declared minimum of 8. Those groups are now refused `cylinder-normals-discrete`,
the sphere falls with the cylinder, and the pockets' area is honestly unclaimed —
which is why coverage is 41.6% rather than the 47.6% the wrong answer scored.

The same defect was then found on parts nobody had suspected: **21 M3 nut pockets
across five of the eleven production STLs** (5.700 mm across flats, 12 facets
each) were being planned as 6.58 mm round holes.

The planner used to refuse here, with `frame-ambiguous`: the three wall
directions carry 21,714 mm² and 19,572 mm², a margin of 0.0986 against a declared
`frame_margin` of 0.1. That one is structural rather than a threshold — a
hexagonal part has no distinguishable secondary datum, and a smaller margin would
pick a winner the geometry does not prefer.

It is no longer refused, because a reconstruction does not need the designer's
preferred frame; it needs a *deterministic* one, and every archetype in the
program is expressed against the datum. When the scores tie, the axis is settled
on the tied candidates' **canonical directions quantized to the declared
`angle_tolerance_deg` grid**, smallest cell first — the directions being what a
re-tessellation does not move, unlike the two near-equal areas. The program says
which happened: `datum.evidence.frame_choice` is `arbitrary-canonical` here
against `evidence` on a part whose frame was measured, and the tied candidates,
their scores, the margin, the grid and the cell each quantized to are all
recorded beside it. The refusal survives for the case it still protects — a tie
whose candidates carry direction uncertainty reaching that grid, where the choice
really could flip on a re-tessellation. The honeycomb's three walls carry
1.2e-06° and less, against a 2° grid.

The part then plans **one `sketch-extrude`, 33.5% of the area, 23 regions
unreconstructed** (17 planes no archetype covers, 6 hex pockets refused
`cylinder-normals-discrete`) and refuses at *emission* instead:
`profile-ambiguous`, because the section at station 51 mm closes eleven loops and
a single-loop profile cannot describe a honeycomb.

### The unicorn horn, which the F3D grades

The archive is a real parametric design: 25 timeline entries and 8 user
parameters (`height = 140 mm`, `diameter = 40 mm`, `multiplicity = 3`, …). Its
twelve solid features are **1 coil, 2 sweeps, 2 lofts, 3 extrudes, 1 fillet,
1 shell, 1 split body and 1 move**.

The archetype vocabulary is closed at `sketch-extrude`, `revolve`, `hole` and
`fillet`. So of what the designer actually did, **four features are expressible
in kind and eight are not** — and the one archetype the shape might have earned,
a revolve, never appears in the original at all. 22 of the graded body's 51 STEP
faces are NURBS, which no member of the vocabulary describes. This part is out of
scope by construction, not by tuning, and the F3D is the evidence for saying so.

It does not get far enough for that to be what stops it. The fit stage accepts
**23 regions — 20 planes and 3 cylinders, 4.8% of the area** — and the planner
refuses `frame-ambiguous`: two primary-axis candidates sit within the declared
`frame_margin` of each other in score and 0.3666° apart in direction, and the
lower-scoring one carries a 6.487° direction sigma against the 2° grid that
decides whether it is the winner re-measured or a rival. The canonical tie rule
settles a tie it can quantize reproducibly; this one it cannot, so it says so
rather than picking.

### The tropical leaves, which are here to be refused

The assertion that matters on an organic part is not how much it recovers but
what it declines to claim. It claims **no cylinder, no cone and no torus** — 48
planes and one sphere out of 958 regions, 19.0% of the area — and the plan
reduces that to a single `sketch-extrude` at 6.3%. Emission then refuses with
`profile-ambiguous`: the section closes two loops, and because the mesh's winding
is inconsistent (`isOriented` false, signed volume 0.0) `material_side` is null,
so the inner loop cannot be held out as a hole. That refusal chain runs straight
back to the capture evidence rather than to a threshold.

### The Bambu 3MF, which is here to test intake

3MF **is** supported: Fusion's mesh import reads it, and the same face-group and
extract scripts write the same dump format. It is also the only part here whose
rebuild script emits. Its `min_feature_size` is declared at 2 mm with the reason
in `results/desktop_organiser_3mf/fit-spec.json` — the part is 250 mm across at
6,502 facets, so one facet spans several millimetres; at 1 mm it refuses
`feature-scale-below-noise` at a recoverable size of 1.3627 mm, which is the
estimator working rather than failing. 15 of its 36 accepted fits are spheres,
which no ground truth here can confirm or deny.

## Layout

```
benchmark-manifest.json   fixtures with hashes and roles, every measured number, and the known gaps
fusion-project.json       the project manifest, with all four mesh_sources and their brep_source pairs
program-spec.json         the planner's declared thresholds, shared by every part
rebuild-spec.json         the emitter's declared thresholds; dump_path is a placeholder the runner substitutes
parts/                    the seven downloaded files, byte for byte
dumps/                    one hash-bound mesh dump per mesh input, written by Fusion
ground-truth/             the two STEP B-Rep readings and the F3D timeline, hash-bound like the rest
results/<source-id>/      the recorded classification and the declared fit spec for that part
```

One spec serves four parts, so its `dump_path` is
`dumps/REPLACED_WITH_THE_PARTS_OWN_DUMP` and the runner substitutes the selected
part's dump before emitting. Run `emit-mesh-rebuild` against the spec as
committed and the placeholder is refused by name — `dump-unreadable`, naming the
path — rather than escaping as an errno nobody can branch on.

### What this costs, and what earns it

29.6 MB of binary fixtures, in git history forever: 24.4 MB in `parts/` and
5.1 MB in `dumps/`. 14.1 MB of that is the pair nothing in this repository can
open — the 10.7 MB F3D archive and the 3.1 MB unicorn STEP — kept because the
originals are the point: the answer key is then the vendor's own file rather than
somebody's transcription of it.

What earns the bytes is that everything asserted *about* them is asserted against
the derived JSONs in `ground-truth/`, and those are hash-bound in the same
fixture table as the parts and the dumps. The F3D's timeline JSON is re-read for
the horn's own feature census — 3 extrudes, 2 sweeps, 2 lofts, a coil, a fillet,
a shell, a split and a move — and "eight of the twelve are inexpressible" is
*derived* from `ARCHETYPE_KINDS` rather than restated, so growing the vocabulary
fails the test instead of quietly making this README wrong. The unicorn STEP's
B-Rep JSON is checked the same way, face kind by face kind. Nothing here cites a
file it never reads.

## Running it

The fast half is a gate and runs with the suite: fixture digests, the project
manifest still agreeing with its files, and the whole honeycomb replay including
its comparison against the STEP. The honeycomb is 556 triangles, so it costs
under a tenth of a second.

The three larger parts are a measurement, not a gate, and cost about a minute:

```bash
FUSION_DESIGN_RECONSTRUCTION_BENCHMARK=1 ./scripts/test.sh
```

Every tolerance the comparison uses is declared with the measurement it came
from at the top of `tests/test_reconstruction_benchmark.py`.

## When one of these gates is fixed

The test asserts the gates, so a fix makes it fail. That is deliberate: re-measure
the corpus, update `benchmark-manifest.json`, and the improvement lands in the
record instead of passing unnoticed.

It has happened twice already, both on the honeycomb. `known_gaps` keeps a
`fixed` entry for each with the evidence that diagnosed it, because the evidence
is still true of the mesh — 61.5% of its interior edges really are 60° creases —
and the tests re-read it, so a diagnosis cannot rot into folklore while the mesh
underneath it changes.
