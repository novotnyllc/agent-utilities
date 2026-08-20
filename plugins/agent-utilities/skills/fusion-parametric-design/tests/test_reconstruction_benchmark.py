"""The downloaded-part benchmark: four real parts, two of them with ground truth.

`examples/reconstruction-benchmark/` holds four models somebody actually
downloaded and printed, byte for byte, together with what the reconstruction
pipeline measured on each. Two of them carry an answer key that did not come
from this pipeline:

* the honeycomb organiser ships the vendor's own **STEP**, read as a B-Rep in
  Fusion and recorded in `ground-truth/`. It is 145 planar faces in exactly four
  directions and not one curved surface, so "did the STL come back matching the
  STEP" is a checkable question rather than an opinion.
* the unicorn horn ships the **F3D archive** it was exported from, so the real
  timeline and the real user parameters are recorded too -- what parametric
  looked like *before* anybody exported a mesh.

What the tests here assert, and what they deliberately do not:

* The fixtures are byte-exact and the benchmark's own project manifest still
  agrees with them. That is a gate: a fixture that silently changed makes every
  number below a fiction.
* The honeycomb replays from its committed dump to the outcome recorded in
  `benchmark-manifest.json`, and the numbers that *can* be checked against the
  STEP -- area, volume, bounding box, and now every fitted plane's direction --
  are checked against it. The honeycomb is 556 triangles, so this runs in under
  a tenth of a second and stays a gate.
* The three larger parts are a **measurement**, not a gate, and are env-gated
  like the two sweeps in `test_mesh_segmentation.py`. Together they take about a
  minute.

The recorded outcome today is that **no part in this corpus reaches a built
reconstruction**, and each stops at a different named gate. Asserting the gates
is the point: when one of them is fixed, this test fails and the manifest has to
be re-measured rather than the improvement going unrecorded. That is exactly
what happened to the honeycomb -- it used to refuse `feature-scale-below-noise`
before fitting anything and it now fits 39 planes matching all four of the
STEP's families, so what this file asserts about it changed with the build. It
still stops at the planner, on `frame-ambiguous`, which is hexagonal symmetry
rather than a threshold.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "examples" / "reconstruction-benchmark"
MANIFEST = json.loads((BENCH / "benchmark-manifest.json").read_text(encoding="utf-8"))

#: The closed role vocabulary the fixture table is allowed to use. A role
#: outside it means the manifest is describing something this benchmark does not
#: know how to treat, which is a defect and not a new capability.
FIXTURE_ROLES = {
    "stl-input",
    "step-ground-truth",
    "f3d-ground-truth",
    "3mf-input",
    "mesh-dump",
    # The two derived answer keys. They are what the STEP and F3D are *read as*
    # -- nothing in this repository can open a STEP or an F3D -- so they are the
    # files the assertions actually run against and they are hash-bound in the
    # same table as the parts and the dumps. Left unbound, the answer key could
    # be edited into agreement with whatever the pipeline happened to produce.
    "brep-ground-truth",
    "timeline-ground-truth",
}

# --- tolerances, each with the measurement it was set from -----------------
#
# The honeycomb STL and the honeycomb STEP describe the same solid, and that
# solid is bounded entirely by planes. A tessellation of a planar face has
# *exactly* the face's area and encloses exactly its volume, so these are not
# approximation tolerances -- they are the width of the float32 the STL stores
# its vertices in, and the agreement measured through them.

#: Measured agreement between the mesh dump's summed facet area and the STEP
#: body's analytic area is 3.2e-08. A binary STL holds float32, so a vertex
#: carries about 1.2e-07 of relative quantization; 1e-06 is an order above that
#: and thirty times the measured disagreement. Anything larger than this means
#: the STL is not a tessellation of this STEP.
STEP_AREA_REL_TOLERANCE = 1.0e-06

#: Measured agreement between the mesh body's volume and the STEP body's is
#: 7.7e-07. Volume is cubic in the coordinates, so it carries three times the
#: relative vertex error; 1e-05 is an order above the measurement and still far
#: below any difference a real modelling change would make.
STEP_VOLUME_REL_TOLERANCE = 1.0e-05

#: The two bounding boxes agree to 2.3e-06 mm. A thousandth of a millimetre is
#: below the resolution of any process that would make this organiser, so a
#: disagreement above it is a transform or a unit error rather than rounding.
STEP_BBOX_ABS_TOLERANCE_MM = 1.0e-03

#: The refusal this benchmark records carries computed floats. They are
#: deterministic, but asserting them bit-for-bit would make a platform's
#: last-place rounding into a test failure, so they are compared relatively at a
#: width no real change to the estimator could hide inside.
RECORDED_FLOAT_REL_TOLERANCE = 1.0e-09

#: A fitted plane's normal against the STEP face normal it matches. The STEP
#: states its normals to nine decimals and a plane fitted through the
#: tessellation of one of its faces agrees with it to 0.0 degrees -- every dot
#: product in the set is 1.0 in double precision -- so this is the width of the
#: agreement's own float noise, not a modelling allowance.
PLANE_NORMAL_ABS_TOLERANCE_DEG = 1.0e-06

#: And its *position*: the distance from the fitted plane to the STEP face's own
#: plane, once the single rigid translation between the two is applied. Measured
#: worst is 1.1e-05 mm over 39 planes; 1e-03 mm is the same thousandth of a
#: millimetre the bounding boxes are held to, below the resolution of any process
#: that would make this organiser and ninety times the measurement.
PLANE_OFFSET_ABS_TOLERANCE_MM = 1.0e-03


def _families(body):
    """The set of unsigned plane normals in a B-Rep body, rounded to a milliunit.

    A face and the face opposite it carry the same direction with opposite signs
    and are one family; the sign is taken off the first non-zero component so the
    two collapse onto each other rather than counting twice.
    """
    out = set()
    for face in body["faces"]:
        normal = face["normal"]
        sign = 1.0
        for value in normal:
            if abs(value) > 1e-9:
                sign = 1.0 if value > 0.0 else -1.0
                break
        out.add(tuple(round(value / sign, 3) + 0.0 for value in normal))
    return out


def _angle_deg(a, b) -> float:
    """The unsigned angle between two directions, in degrees."""
    dot = sum(x * y for x, y in zip(a, b))
    return math.degrees(math.acos(max(-1.0, min(1.0, abs(dot)))))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _fit(source_id: str):
    """Replay one part's fit stage from its committed, hash-bound dump."""
    from fusion_design import mesh_segmentation as seg
    from fusion_design.mesh_dump import read_mesh_dump

    row = MANIFEST["results"][source_id]
    spec = seg.load_spec(
        json.loads((BENCH / "results" / source_id / "fit-spec.json").read_text(encoding="utf-8"))
    )
    dump = read_mesh_dump(BENCH / "dumps" / row["dump"], row["dump_sha256"])
    return row, seg.fit_regions(dump, spec)


def _plan(record):
    """Run the planner, returning either the program or the refusal it raised."""
    from fusion_design.manifest import load_manifest
    from fusion_design.mesh_datum import ReconstructionRefused, parse_fit_record
    from fusion_design.reconstruction_program import build_reconstruction_program
    from fusion_design.scripts import manifest_sha256

    spec = json.loads((BENCH / "program-spec.json").read_text(encoding="utf-8"))
    digest = manifest_sha256(load_manifest(BENCH / "fusion-project.json"))
    try:
        return build_reconstruction_program(
            parse_fit_record(record), spec, manifest_sha256=digest
        ), None
    except ReconstructionRefused as refused:
        return None, refused


class BenchmarkFixtureTests(unittest.TestCase):
    """The corpus itself: byte-exact, self-describing, and still bound to the manifest."""

    def test_every_recorded_fixture_is_present_and_byte_exact(self) -> None:
        # These files are the benchmark. A fixture that drifted -- re-exported,
        # line-ending normalised, re-saved by a viewer -- would leave every
        # measured number below describing a model nobody has any more.
        self.assertTrue(MANIFEST["fixtures"], "the fixture table is empty")
        for fixture in MANIFEST["fixtures"]:
            path = BENCH / fixture["file"]
            with self.subTest(fixture=fixture["file"]):
                self.assertTrue(path.is_file(), f"{fixture['file']} is missing")
                self.assertEqual(fixture["bytes"], path.stat().st_size)
                self.assertEqual(fixture["sha256"], _sha256(path))
                self.assertIn(fixture["role"], FIXTURE_ROLES)

    def test_every_ground_truth_file_exists_and_is_bound_by_digest(self) -> None:
        # The answer key gets the same treatment as the questions. Without a
        # digest, `ground-truth/*.json` could be rewritten wholesale -- into
        # agreement with whatever the pipeline produced -- and every assertion
        # below would still pass, greenly.
        bound = {fixture["file"]: fixture for fixture in MANIFEST["fixtures"]}
        for name in MANIFEST["ground_truth"]:
            with self.subTest(ground_truth=name):
                path = BENCH / "ground-truth" / name
                self.assertTrue(path.is_file())
                fixture = bound.get(f"ground-truth/{name}")
                self.assertIsNotNone(fixture, f"{name} is not in the hash-bound fixture table")
                self.assertEqual(fixture["sha256"], _sha256(path))
                self.assertEqual(fixture["bytes"], path.stat().st_size)

    def test_the_benchmark_project_manifest_validates_and_still_matches_its_files(self) -> None:
        # mesh_sources records a file by digest, so this is the check that the
        # project manifest and the fixtures have not drifted apart.
        from fusion_design.manifest import load_manifest, validate_manifest_data
        from fusion_design.mesh_source import verify_manifest_mesh_sources

        path = BENCH / "fusion-project.json"
        self.assertEqual([], validate_manifest_data(json.loads(path.read_text(encoding="utf-8"))))
        manifest = load_manifest(path)
        # It raises on a swapped or edited file and otherwise returns the digest
        # it re-hashed for each source, so the mapping is the evidence.
        self.assertEqual(
            {str(record["id"]): str(record["sha256"]) for record in manifest.mesh_sources},
            verify_manifest_mesh_sources(manifest, path),
        )

    def test_every_recorded_part_carries_a_classification_and_a_declared_fit_spec(self) -> None:
        # The comment here used to claim the gate re-derived the path, while the
        # only code that calls it ran on the env-gated path for two of the four
        # parts. So it is called here, for all four: `classification_from_record`
        # re-derives the decision from the recorded inputs and refuses a record
        # whose stated path is not the one those inputs produce, and
        # `require_classification` additionally binds it to the mesh source it
        # was decided for.
        from fusion_design.manifest import load_manifest
        from fusion_design.mesh_reconstruction import (
            classification_from_record,
            require_classification,
        )
        from fusion_design.mesh_source import mesh_source_record

        manifest = load_manifest(BENCH / "fusion-project.json")
        for source_id in MANIFEST["results"]:
            with self.subTest(part=source_id):
                classification = json.loads(
                    (BENCH / "results" / source_id / "classification.json").read_text(encoding="utf-8")
                )
                self.assertEqual("parametric-rebuild", classification["path"])
                self.assertEqual(source_id, classification["inputs"]["source_id"])
                rederived = classification_from_record(classification)
                self.assertEqual(classification["path"], rederived.path)
                bound = require_classification(
                    classification,
                    "reconstruction-benchmark",
                    ("parametric-rebuild",),
                    mesh_source_record(manifest, source_id),
                )
                self.assertEqual("parametric-rebuild", bound.path)
                spec = json.loads(
                    (BENCH / "results" / source_id / "fit-spec.json").read_text(encoding="utf-8")
                )
                for name, declared in spec.items():
                    self.assertIn("value", declared, name)
                    self.assertTrue(str(declared.get("rationale", "")).strip(), name)

    def test_each_parts_recorded_stage_is_the_one_its_own_refusals_imply(self) -> None:
        """A hand-set outcome label contradicted its own row, so there is none.

        The desktop organiser carried `coverage_label: reconstruction-refused`
        beside one `sketch-extrude`, no refusal anywhere, and
        `stage_reached: emitted`: the one part in the corpus that gets all the
        way through, labelled as the failure. Two of the four carried no label at
        all. `coverage_label` is the *build* stage's verdict -- `compose_coverage`
        calls anything Fusion has not built `reconstruction-refused`, and this
        benchmark runs no Fusion, so it is not a number this corpus can report.
        The outcome is the stage reached, and it is derived here from the row's
        own refusal fields rather than trusted, so it cannot contradict them
        again.
        """
        self.assertTrue(MANIFEST["results"], "the results table is empty")
        for source_id, row in MANIFEST["results"].items():
            with self.subTest(part=source_id):
                self.assertNotIn("coverage_label", row)
                if row["fit"]["refusal"]:
                    implied = "fit"
                elif (row.get("plan") or {}).get("refusal"):
                    implied = "plan"
                elif (row.get("rebuild_emission") or {}).get("refusal"):
                    implied = "emit-rebuild"
                else:
                    implied = "emitted"
                self.assertEqual(implied, row["stage_reached"])
                # And the one part that reaches `emitted` says what it emitted.
                if implied == "emitted":
                    self.assertTrue(row["plan"]["archetypes"])


class HoneycombAgainstItsStepTests(unittest.TestCase):
    """"Does the STL come back matching what the STEP says?", as an executable check.

    556 triangles, so this is fast enough to be a gate rather than a measurement.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.brep = json.loads(
            (BENCH / "ground-truth" / "honeycomb-tool-organizer.step.brep.json").read_text(
                encoding="utf-8"
            )
        )
        cls.comparison = MANIFEST["step_comparison"]["honeycomb_organizer_stl"]
        cls.row, cls.record = _fit("honeycomb_organizer_stl")

    def test_the_step_ground_truth_is_planes_only_in_four_directions(self) -> None:
        # Everything else in this class rests on this: if the vendor STEP ever
        # stopped being an all-planar part, the comparison would be measuring
        # something other than what it claims to.
        body, = self.brep["bodies"]
        kinds = {}
        for face in body["faces"]:
            kinds[face["kind"]] = kinds.get(face["kind"], 0) + 1
        self.assertEqual({"PlaneSurfaceType": 145}, kinds)
        families = _families(body)
        self.assertEqual(4, len(families), sorted(families))

    def test_the_stl_is_the_same_solid_the_step_describes(self) -> None:
        body, = self.brep["bodies"]
        self.assertAlmostEqual(
            body["area_mm2"],
            self.record["total_area"],
            delta=STEP_AREA_REL_TOLERANCE * body["area_mm2"],
        )
        self.assertAlmostEqual(
            body["volume_mm3"],
            self.comparison["mesh_volume_mm3"],
            delta=STEP_VOLUME_REL_TOLERANCE * body["volume_mm3"],
        )
        # strict: a bbox of the wrong length would truncate and skip an axis
        # silently, which is a comparison that passed by not being made.
        step_extent = [
            high - low
            for low, high in zip(body["bbox_min_mm"], body["bbox_max_mm"], strict=True)
        ]
        for axis, (expected, measured) in enumerate(
            zip(step_extent, self.comparison["mesh_bbox_extent_mm"], strict=True)
        ):
            with self.subTest(axis="xyz"[axis]):
                self.assertAlmostEqual(expected, measured, delta=STEP_BBOX_ABS_TOLERANCE_MM)

    def test_the_pipeline_fits_this_part_and_the_manifest_records_what_it_fitted(self) -> None:
        # The honeycomb used to refuse `feature-scale-below-noise` before a
        # single primitive was fitted, because the dihedral noise estimator read
        # the part's own 60-degree cell walls as noise. It fits now, and the
        # numbers are asserted against the manifest so an improvement cannot
        # arrive unrecorded any more than a regression can.
        self.assertIsNone(
            self.record["refusal"],
            "the honeycomb is expected to fit; re-measure the manifest",
        )
        self.assertIsNone(self.row["fit"]["refusal"])
        self.assertEqual(self.row["fit"]["regions"], len(self.record["regions"]))
        accepted = [r for r in self.record["regions"] if r["accepted"]]
        self.assertEqual(self.row["fit"]["accepted"], len(accepted))
        kinds = {}
        for region in accepted:
            kinds[region["fit"]["kind"]] = kinds.get(region["fit"]["kind"], 0) + 1
        self.assertEqual(self.row["fit"]["accepted_kinds"], kinds)
        self.assertAlmostEqual(
            self.row["fit"]["covered_area_fraction"],
            self.record["covered_area_fraction"],
            places=9,
        )

    def test_not_one_curved_primitive_is_claimed_on_an_all_planar_part(self) -> None:
        """The strongest check the STEP affords, and it is free.

        The vendor B-Rep is 145 planar faces and not one cylinder, cone, sphere
        or torus. So "how many curved surfaces did the pipeline claim" has an
        answer that is knowable rather than arguable, and the answer is zero.
        Before the discrete-normal gate it was six: each hexagonal pocket's six
        walls arrive as one face group, and a regular hexagon's corners lie
        *exactly* on its circumscribed circle, so the vertex fit returned a
        cylinder of radius 15*cos(30) at float-noise residual and every gate that
        reads vertices passed it.
        """
        body, = self.brep["bodies"]
        self.assertEqual(
            set(), {face["kind"] for face in body["faces"]} - {"PlaneSurfaceType"}
        )
        claimed = {
            region["fit"]["kind"] for region in self.record["regions"] if region["accepted"]
        }
        self.assertEqual(set(), claimed & {"cylinder", "cone", "sphere", "torus"})
        self.assertEqual({"plane"}, claimed)

    def test_the_hex_pockets_are_refused_by_name_and_say_what_they_measured(self) -> None:
        refused = [r for r in self.record["regions"] if not r["accepted"]]
        gates = {}
        for region in refused:
            gate = (region["fit"].get("rejection") or "").split(":")[0]
            gates[gate] = gates.get(gate, 0) + 1
        self.assertEqual(self.row["fit"]["top_gates"], gates)
        self.assertEqual({"cylinder-normals-discrete": 6}, gates)
        for region in refused:
            with self.subTest(region=region["region_hash"][:12]):
                spread = region["fit"]["support"]["normal_direction_spread"]
                # Five of the cell's six walls in this group, at 60 degrees each,
                # against the eight directions per turn the fit-spec declares.
                self.assertEqual(5, spread["directions"])
                self.assertLess(
                    spread["directions_per_turn"], spread["min_directions_per_turn"]
                )
                # And nothing is claimed while refusing: no radius, no axis.
                self.assertEqual({}, region["fit"]["parameters"])

    def test_every_fitted_plane_matches_one_of_the_steps_four_families(self) -> None:
        body, = self.brep["bodies"]
        families = sorted(_families(body))
        self.assertEqual(4, len(families))
        recorded = MANIFEST["step_comparison"]["honeycomb_organizer_stl"]["plane_match"]
        hit, worst = set(), 0.0
        for region in self.record["regions"]:
            if not region["accepted"]:
                continue
            normal = region["fit"]["parameters"]["normal"]
            nearest = min(families, key=lambda f: _angle_deg(normal, f))
            hit.add(nearest)
            worst = max(worst, _angle_deg(normal, nearest))
        self.assertEqual(recorded["planes_matched"], self.row["fit"]["accepted_kinds"]["plane"])
        self.assertEqual(recorded["step_families_hit"], len(hit))
        self.assertEqual(len(families), len(hit))
        # The family table's normals are rounded to three decimals, so `worst`
        # above is how far a fitted normal sits from the *rounded* value and not
        # from the STEP. It was recorded, and asserted one-sidedly, as though it
        # were the agreement. Both are re-measured exactly here: the rounding is
        # a property of the table and the agreement is a property of the fit.
        self.assertAlmostEqual(
            recorded["family_table_rounding_deviation_deg"],
            worst,
            delta=RECORDED_FLOAT_REL_TOLERANCE * recorded["family_table_rounding_deviation_deg"],
        )
        against_step = max(
            min(_angle_deg(region["fit"]["parameters"]["normal"], face["normal"])
                for face in body["faces"])
            for region in self.record["regions"]
            if region["accepted"]
        )
        self.assertAlmostEqual(
            recorded["worst_plane_normal_deviation_deg"],
            against_step,
            delta=PLANE_NORMAL_ABS_TOLERANCE_DEG,
        )

    def test_every_fitted_plane_sits_where_the_step_says_that_face_sits(self) -> None:
        """Direction was checked and *position* never was.

        "The STL is the same solid" was area, volume and bounding-box extent --
        all three of which a solid keeps when it is translated, and this mesh is
        translated: it arrives with its bounding-box corner on the origin while
        the STEP body straddles it. So the check is against the one rigid
        translation between them, measured from the two bounding boxes and
        recorded: with it applied, every fitted plane has to land on the plane of
        the STEP face it is parallel to. Without this, a plane fitted at the
        wrong station -- the wrong shelf, the wrong wall -- still passed.
        """
        body, = self.brep["bodies"]
        recorded = MANIFEST["step_comparison"]["honeycomb_organizer_stl"]["plane_match"]
        low = [min(point[axis] for point in self._mesh_points()) for axis in range(3)]
        translation = [
            measured - stated for measured, stated in zip(low, body["bbox_min_mm"])
        ]
        for axis in range(3):
            with self.subTest(axis="xyz"[axis]):
                self.assertAlmostEqual(
                    recorded["mesh_to_step_translation_mm"][axis],
                    translation[axis],
                    delta=STEP_BBOX_ABS_TOLERANCE_MM,
                )
        worst, matched = 0.0, 0
        for region in self.record["regions"]:
            if not region["accepted"]:
                continue
            normal = region["fit"]["parameters"]["normal"]
            offset = region["fit"]["parameters"]["offset"]
            distances = [
                abs(sum(n * (o + t) for n, o, t in zip(normal, face["origin_mm"], translation))
                    - offset)
                for face in body["faces"]
                if _angle_deg(normal, face["normal"]) <= PLANE_NORMAL_ABS_TOLERANCE_DEG
            ]
            self.assertTrue(distances, "a fitted plane parallel to no STEP face")
            matched += 1
            worst = max(worst, min(distances))
        self.assertEqual(recorded["planes_matched"], matched)
        self.assertLessEqual(worst, PLANE_OFFSET_ABS_TOLERANCE_MM)
        self.assertAlmostEqual(
            recorded["worst_plane_offset_mm"], worst, delta=PLANE_OFFSET_ABS_TOLERANCE_MM
        )

    def _mesh_points(self):
        """The dump's own vertices, in millimetres."""
        from fusion_design.mesh_dump import read_mesh_dump

        dump = read_mesh_dump(BENCH / "dumps" / self.row["dump"], self.row["dump_sha256"])
        flat = dump.vertices_mm
        return [tuple(flat[i : i + 3]) for i in range(0, len(flat), 3)]

    def test_the_noise_record_says_which_estimator_sigma_came_from_and_keeps_both(self) -> None:
        # The defect was that `sigma = max(quadric, dihedral)` ran before the
        # regime was known, so the check that already suppressed the
        # `noise-model-inconsistent` *flag* never saw the *value*. The cross-check
        # is still here -- both estimators recorded, still disagreeing -- and the
        # dihedral reading still reaches `surface_scale`, which is what sizes the
        # power floor under the residual-structure and held-out tests.
        gap, = [g for g in MANIFEST["known_gaps"] if g["id"] == "estimator-b-counts-real-creases-as-noise"]
        evidence = gap["evidence"]
        noise = self.record["noise"]
        self.assertEqual("tessellation", self.record["regime"]["regime"])
        self.assertEqual(0.0, noise["sigma_quadric"])
        self.assertEqual("quadric", noise["sigma_estimator"])
        self.assertTrue(noise["estimators_disagree"])
        self.assertTrue(noise["precision_floor_binds"])
        self.assertEqual(noise["vertex_precision_floor"], noise["sigma"])
        for recorded, measured in (
            (evidence["sigma_dihedral"], noise["sigma_dihedral"]),
            (evidence["sigma_dihedral"], noise["surface_scale"]),
            (evidence["median_abs_dihedral_deg"], noise["median_abs_dihedral_deg"]),
        ):
            self.assertAlmostEqual(
                recorded, measured, delta=RECORDED_FLOAT_REL_TOLERANCE * abs(recorded)
            )
        self.assertEqual(evidence["interior_edge_count"], noise["interior_edge_count"])

    def test_the_planner_still_refuses_a_part_with_no_secondary_datum(self) -> None:
        """Fitting the part did not invent a frame for it, and must not.

        Three wall directions 120 degrees apart carry 21,714 and 19,572 square
        millimetres: the margin is 0.0986 against a declared 0.1, and that is
        hexagonal symmetry rather than a threshold set too tight.
        """
        program, refused = _plan(self.record)
        self.assertIsNone(program, "the honeycomb is expected to refuse at the planner")
        recorded = MANIFEST["results"]["honeycomb_organizer_stl"]["plan"]
        self.assertEqual(recorded["refusal"], refused.reason)
        self.assertEqual("frame-ambiguous", refused.reason)
        self.assertAlmostEqual(
            recorded["margin"],
            refused.detail["margin"],
            delta=RECORDED_FLOAT_REL_TOLERANCE * recorded["margin"],
        )


class UnicornHornGroundTruthTests(unittest.TestCase):
    """What the F3D and the STEP say, read from the JSON they were read into.

    The two binary fixtures -- 13.8 MB of F3D and STEP -- are kept because the
    user asked for them, and nothing in this repository can open either one. The
    files that *are* readable are the derived JSONs in `ground-truth/`, so those
    are hash-bound in the same fixture table and asserted against here. Without
    this the binaries would be inert: kept, cited, and never checked.

    The gap statement is the assertion. `unicorn-horn-is-not-in-the-vocabulary`
    says the horn's real features are outside the closed archetype vocabulary,
    and that stops being a claim about this build the moment the vocabulary
    grows: the expressible set is derived from `ARCHETYPE_KINDS` here rather than
    restated, so adding `loft` or `sweep` fails this test and demands the gap be
    re-written.
    """

    #: Which archetype each Fusion timeline feature would have to become. Only
    #: the four the vocabulary contains are mapped; a feature absent from this
    #: table is inexpressible by construction, which is the point.
    FEATURE_TO_ARCHETYPE = {
        "ExtrudeFeature": "sketch-extrude",
        "RevolveFeature": "revolve",
        "HoleFeature": "hole",
        "FilletFeature": "fillet",
    }

    #: Timeline entries that are not solid features: the sketches and planes a
    #: feature is built on. They are not "inexpressible", they are scaffolding.
    NON_FEATURE_ENTITIES = {"Sketch", "ConstructionPlane"}

    @classmethod
    def setUpClass(cls) -> None:
        cls.timeline = json.loads(
            (BENCH / "ground-truth" / "unicorn-horn-parametric-multi-v3.f3d.timeline.json")
            .read_text(encoding="utf-8")
        )
        cls.brep = json.loads(
            (BENCH / "ground-truth" / "unicorn-horn-4examples-v3.step.brep.json").read_text(
                encoding="utf-8"
            )
        )

    def _kinds(self):
        kinds = {}
        for entry in self.timeline["timeline"]:
            name = entry["entity_type"].rsplit("::", 1)[-1]
            kinds[name] = kinds.get(name, 0) + 1
        return kinds

    def test_the_manifest_summary_is_the_timelines_own_feature_census(self) -> None:
        summary = MANIFEST["f3d_ground_truth"]
        self.assertEqual(self._kinds(), summary["feature_kinds"])
        self.assertEqual(len(self.timeline["timeline"]), summary["timeline_count"])
        self.assertEqual(
            [{"name": p["name"], "expression": p["expression"]}
             for p in self.timeline["user_parameters"]],
            [{"name": p["name"], "expression": p["expression"]}
             for p in summary["user_parameters"]],
        )
        self.assertEqual(self.timeline["design_type"], summary["design_type"])

    def test_the_horns_real_features_are_still_outside_the_vocabulary(self) -> None:
        from fusion_design.reconstruction_program import ARCHETYPE_KINDS

        self.assertEqual({"sketch-extrude", "revolve", "hole", "fillet"}, ARCHETYPE_KINDS)
        self.assertLessEqual(set(self.FEATURE_TO_ARCHETYPE.values()), ARCHETYPE_KINDS)
        kinds = self._kinds()
        features = {
            name: count
            for name, count in kinds.items()
            if name not in self.NON_FEATURE_ENTITIES
        }
        # The designer's own list, feature for feature: three extrudes, two
        # sweeps, two lofts, a coil, a fillet, a shell, a split and a move.
        self.assertEqual(
            {
                "ExtrudeFeature": 3,
                "SweepFeature": 2,
                "LoftFeature": 2,
                "CoilFeature": 1,
                "FilletFeature": 1,
                "ShellFeature": 1,
                "SplitBodyFeature": 1,
                "MoveFeature": 1,
            },
            features,
        )
        inexpressible = sorted(
            name for name in features if self.FEATURE_TO_ARCHETYPE.get(name) not in ARCHETYPE_KINDS
        )
        self.assertEqual(sorted(MANIFEST["f3d_ground_truth"]["inexpressible"]), inexpressible)
        # Eight of the twelve solid features, and no revolve anywhere in the
        # original, so the one archetype this part might have earned is not what
        # the designer used.
        self.assertEqual(8, sum(features[name] for name in inexpressible))
        self.assertNotIn("RevolveFeature", features)
        gap, = [g for g in MANIFEST["known_gaps"] if g["id"] == "unicorn-horn-is-not-in-the-vocabulary"]
        self.assertEqual("open", gap["status"])

    def test_the_graded_body_is_the_one_the_manifest_names_and_is_mostly_nurbs(self) -> None:
        recorded = MANIFEST["step_comparison"]["unicorn_horn_3mf"]
        body, = [
            b for b in self.brep["bodies"]
            if f"{b['component_path']} {b['name']}".strip() == recorded["step_body"]
        ]
        kinds = {}
        for face in body["faces"]:
            kinds[face["kind"]] = kinds.get(face["kind"], 0) + 1
        self.assertEqual(recorded["step_face_kinds"], kinds)
        self.assertEqual(body["face_count"], sum(kinds.values()))
        # "43 percent of the graded body's faces are NURBS", as an arithmetic
        # statement rather than a sentence: 22 of 51. The archetype vocabulary
        # has no NURBS member, so that area is unreachable by construction.
        self.assertAlmostEqual(
            0.43, kinds["NurbsSurfaceType"] / body["face_count"], places=2
        )
        self.assertIn("NURBS", recorded["note"])


@unittest.skipUnless(
    os.environ.get("FUSION_DESIGN_RECONSTRUCTION_BENCHMARK"),
    "the three large downloaded parts are a measurement, not a gate; "
    "set FUSION_DESIGN_RECONSTRUCTION_BENCHMARK=1 (about a minute)",
)
class LargePartBenchmarkTests(unittest.TestCase):  # pragma: no cover - measurement
    """The other three parts, replayed against what the manifest recorded.

    86k and 88k triangles each, so about a minute in total. Every assertion is
    against a number this repository already carries; the point is that the
    recorded corpus stays true, and that a fix anywhere upstream shows up here
    as a failure demanding a re-measurement instead of passing unnoticed.
    """

    def _replay(self, source_id):
        row, record = _fit(source_id)
        self.assertEqual(row["fit"]["refusal"],
                         None if record["refusal"] is None else record["refusal"]["reason"])
        accepted = [r for r in record["regions"] if r["accepted"]]
        self.assertEqual(row["fit"]["accepted"], len(accepted))
        self.assertEqual(row["fit"]["regions"], len(record["regions"]))
        kinds = {}
        for region in accepted:
            kinds[region["fit"]["kind"]] = kinds.get(region["fit"]["kind"], 0) + 1
        self.assertEqual(row["fit"]["accepted_kinds"], kinds)
        self.assertAlmostEqual(
            row["fit"]["covered_area_fraction"], record["covered_area_fraction"], places=9
        )
        return row, record

    def test_the_unicorn_horn_fits_a_little_and_then_cannot_find_a_datum(self) -> None:
        # The horn is a coil swept along a lofted profile: the archetype
        # vocabulary has no member for any of that, and the F3D timeline in
        # ground-truth/ says so in the designer's own features.
        row, record = self._replay("unicorn_horn_3mf")
        program, refused = _plan(record)
        self.assertIsNone(program, "the horn is expected to refuse at the planner")
        self.assertEqual(row["plan"]["refusal"], refused.reason)
        self.assertEqual("frame-x-underdetermined", refused.reason)

    def test_the_tropical_leaves_refuse_honestly_rather_than_inventing_a_primitive(self) -> None:
        # The assertion that matters on an organic part is not how much it
        # recovers but what it declines to claim: no cylinder, no cone, no
        # torus anywhere in the accepted set.
        row, record = self._replay("tropical_leaves_stl")
        claimed = set(row["fit"]["accepted_kinds"])
        self.assertEqual(set(), claimed & {"cylinder", "cone", "torus"})
        program, refused = _plan(record)
        self.assertIsNone(refused, "the leaves are expected to plan, then refuse at emission")
        self.assertEqual(row["plan"]["archetypes"],
                         {kind: sum(1 for g in program["archetypes"] if g["kind"] == kind)
                          for kind in row["plan"]["archetypes"]})
        self.assertAlmostEqual(
            row["plan"]["covered_area_fraction"], program["covered_area_fraction"], places=9
        )
        self.assertEqual(row["rebuild_emission"]["refusal"], self._emit(program, "tropical_leaves_stl"))

    def test_the_bambu_3mf_is_a_supported_intake_and_reaches_an_emitted_rebuild(self) -> None:
        # 3MF is handled: Fusion's mesh import reads it, the same face-group and
        # extract scripts write the same dump format, and this is the one part
        # in the corpus whose rebuild script emits. Its declared
        # min_feature_size is 2 mm and the fit-spec says why -- at 1 mm this
        # part refuses feature-scale-below-noise, which is the estimator working
        # rather than failing.
        row, record = self._replay("desktop_organiser_3mf")
        self.assertEqual(2.0, json.loads(
            (BENCH / "results" / "desktop_organiser_3mf" / "fit-spec.json").read_text(
                encoding="utf-8")
        )["min_feature_size"]["value"])
        program, refused = _plan(record)
        self.assertIsNone(refused)
        self.assertIsNone(self._emit(program, "desktop_organiser_3mf"))

    def _emit(self, program, source_id):
        """Emit the rebuild script; return the refusal reason, or None on success."""
        from fusion_design.manifest import load_manifest
        from fusion_design.mesh_datum import ReconstructionRefused
        from fusion_design.mesh_rebuild import emit_mesh_rebuild_script
        from fusion_design.mesh_source import mesh_source_record

        manifest = load_manifest(BENCH / "fusion-project.json")
        spec = json.loads((BENCH / "rebuild-spec.json").read_text(encoding="utf-8"))
        # dump_path is committed relative to the benchmark directory; the
        # emitter needs the bytes, so the runner resolves it here.
        spec["dump_path"] = str(BENCH / "dumps" / MANIFEST["results"][source_id]["dump"])
        classification = json.loads(
            (BENCH / "results" / source_id / "classification.json").read_text(encoding="utf-8")
        )
        try:
            emit_mesh_rebuild_script(
                manifest,
                classification,
                mesh_source_record(manifest, source_id),
                program,
                spec,
                "0" * 32,
            )
        except ReconstructionRefused as refused:
            return refused.reason
        return None


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
