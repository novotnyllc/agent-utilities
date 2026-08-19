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
different named gate.** That is the finding, not a preamble to one.

| part | triangles | face groups | regime | accepted fits | fit coverage | stops at | gate |
| --- | ---: | ---: | --- | --- | ---: | --- | --- |
| honeycomb organiser (STL) | 556 | 121 | tessellation | 0 | 0.0% | fit | `feature-scale-below-noise` |
| unicorn horn (3MF) | 88,334 | 620 | scan | 9 — 6 planes, 3 cylinders | 4.7% | plan | `frame-x-underdetermined` |
| tropical leaves (STL) | 86,394 | 2,299 | scan | 31 — 30 planes, 1 sphere | 18.3% | emit-rebuild | `profile-ambiguous` |
| desktop organiser (3MF) | 6,502 | 790 | scan | 38 — 21 planes, 17 spheres | 27.9% | — | emitted; 1 `sketch-extrude`, 27.6% planned |

### The honeycomb, which is the one the STEP can grade

The vendor STEP is **145 planar faces in exactly four directions** — three
vertical walls 120° apart and one horizontal — and not one cylinder, cone,
sphere or torus anywhere. The STL is the same solid: its summed facet area
agrees with the STEP's analytic area to 3.2e-08 relative, its volume to 7.7e-07,
and its bounding box to 2.3e-06 mm.

The pipeline nevertheless refuses it before fitting anything, with
`feature-scale-below-noise` at a recoverable feature size of **131.08 mm on a
168.9 mm part**. The cause is one estimator and it states its own assumption:

> `_sigma_dihedral` — "Real creases are a small minority of interior edges on a
> mechanical part, so the median sees only the noise."

On a honeycomb that is false. 61.5% of the interior edges are genuine 60° cell
creases, so the median interior dihedral is 59.99993° and estimator B reports
13.108 mm of noise — on a mesh whose quadric estimator reports **exactly zero**
and whose regime is correctly detected as an exact tessellation. `sigma` is taken
as `max(quadric, dihedral)` before the regime is known, so the regime check that
already suppresses the `noise-model-inconsistent` *flag* does not suppress the
*value* that refuses the part.

Sized, as a diagnostic only, by forcing `_sigma_dihedral` to zero and changing
nothing that ships: the fitter then accepts **45 of 45 regions covering 47.6% of
the area — 39 planes, every one within 0.38° of one of the STEP's four families,
and all four families hit**. It also claims **6 cylinders of radius 12.990381 mm
that the STEP proves do not exist**: that number is 15 × cos 30°, the apothem of
the hexagonal cell, so each hex pocket's six walls are grouped together and
fitted as the inscribed cylinder. Right size, wrong kind — a 25.98 mm
across-flats hex pocket reported as a 25.98 mm round bore.

The planner then refuses anyway, with `frame-ambiguous`: the three wall
directions carry 21,714 mm² and 19,572 mm², a margin of 0.0986 against a declared
`frame_margin` of 0.1. That one is structural rather than a threshold — a
hexagonal part has no distinguishable secondary datum, and a smaller margin would
pick a winner the geometry does not prefer.

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

### The tropical leaves, which are here to be refused

The assertion that matters on an organic part is not how much it recovers but
what it declines to claim. It claims **no cylinder, no cone and no torus** — 30
planes and one sphere out of 958 regions, 18.3% of the area — and the plan
reduces that to a single `sketch-extrude` at 5.7%. Emission then refuses with
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
estimator working rather than failing. 17 of its 38 accepted fits are spheres,
which no ground truth here can confirm or deny.

## Layout

```
benchmark-manifest.json   fixtures with hashes and roles, every measured number, and the known gaps
fusion-project.json       the project manifest, with all four mesh_sources and their brep_source pairs
program-spec.json         the planner's declared thresholds, shared by every part
rebuild-spec.json         the emitter's declared thresholds; dump_path is relative and the runner resolves it
parts/                    the seven downloaded files, byte for byte
dumps/                    one hash-bound mesh dump per mesh input, written by Fusion
ground-truth/             the two STEP B-Rep readings and the F3D timeline
results/<source-id>/      the recorded classification and the declared fit spec for that part
```

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
