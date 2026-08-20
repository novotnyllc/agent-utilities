"""U4: the emission planner, and every branch of the rebuild transaction.

The planner is pure and is tested directly.  The transaction is tested by
*running the emitted source* against Fusion doubles, so every refusal path is
exercised by the code that will actually run in Fusion rather than asserted
about from the outside.
"""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import re
import tempfile
import unittest

from fusion_design.manifest import ManifestValidationError
from fusion_design.mesh_datum import ReconstructionRefused
from fusion_design.mesh_dump import MeshDumpError
from fusion_design.mesh_rebuild import (
    EMITTED_KINDS,
    _clip_half,
    _require_chained,
    emit_mesh_rebuild_script,
    plan_emission,
    replan_without,
    total_order,
    validate_rebuild_spec,
)
from fusion_design.scripts import _script_prelude

import fakes_fusion_rebuild as fakes
import fixtures_rebuild as fx
from test_mesh_reconstruction import _manifest, request
from test_mesh_source import mesh_source
from fusion_design.mesh_reconstruction import classify
from fusion_design.reconstruction_program import ARCHETYPE_KINDS


NONCE = "0123456789abcdef0123456789abcdef"

SOURCE = mesh_source()


def build_manifest():
    return _manifest(SOURCE)


def classification_record():
    return classify(request(edit_kind="dimensional"), SOURCE).to_dict()


def source_record(_manifest_unused=None):
    return SOURCE


def run_transaction(source, design, document_name):
    """Execute a generated transaction and return (report, raised-error-or-None)."""
    namespace = fakes.load_transaction(source, design, document_name)
    stream = StringIO()
    error = None
    with redirect_stdout(stream):
        try:
            namespace["run"](None)
        except Exception as caught:  # the transaction raises after reporting
            error = caught
    text = stream.getvalue()
    match = re.search(
        r"FUSION_DESIGN_REPORT_BEGIN\n(?P<body>.*?)\nFUSION_DESIGN_REPORT_END", text, re.DOTALL
    )
    return (json.loads(match.group("body")) if match else None), error


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.dump = fx.box_dump()
        self.spec = fx.rebuild_spec("unused")

    def plan(self, program=None, spec=None, **kwargs):
        return plan_emission(
            program or fx.program(self.dump.sha256), self.dump, spec or self.spec, **kwargs
        )

    def test_a_box_program_plans_a_fully_determined_sketch(self):
        plan = self.plan()
        step = plan["steps"][0]
        self.assertEqual(4, len(step["entities"]))
        self.assertTrue(all(entity["kind"] == "line" for entity in step["entities"]))
        kinds = sorted(entry["kind"] for entry in step["constraints"])
        self.assertEqual(
            ["horizontal", "horizontal", "origin-coincident", "origin-coincident", "vertical", "vertical"],
            kinds,
        )
        # Four lines carry eight point degrees of freedom; the chaining removes
        # four, the axis snaps four more, and what is left is exactly the two
        # offsets plus the two origin coincidences.
        self.assertEqual(2, len(step["dimensions"]))
        self.assertEqual("distance", step["extent"]["kind"])
        self.assertEqual("recon_base_1_depth", step["extent"]["parameter"])

    def test_every_dimension_and_extent_binds_a_named_parameter(self):
        plan = self.plan()
        names = {row["name"] for row in plan["user_parameters"]}
        for step in plan["steps"]:
            for dimension in step["dimensions"]:
                self.assertIn(dimension["parameter"], names)
            self.assertIn(step["extent"]["parameter"], names)
        for row in plan["user_parameters"]:
            self.assertIn(row["expected_observable"], {"volume", "centroid", "bbox"})
            self.assertTrue(row["observable_rationale"])

    def test_a_plane_offset_parameter_declares_centroid_not_volume(self):
        # The whole point of D7: a parameter that slides a feature along the
        # datum axis changes no volume, and a volume-only test would call it
        # dead. This is the regression that overturned the parent plan's R11.
        plan = self.plan()
        offsets = [
            row for row in plan["user_parameters"] if row["name"].endswith("_plane_offset")
        ]
        self.assertEqual(1, len(offsets))
        self.assertEqual("centroid", offsets[0]["expected_observable"])

    def test_planning_is_deterministic_and_independent_of_key_order(self):
        first = self.plan()
        second = self.plan()
        self.assertEqual(
            json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True)
        )
        shuffled = json.loads(json.dumps(fx.program(self.dump.sha256)))
        shuffled = dict(reversed(list(shuffled.items())))
        self.assertEqual(
            json.dumps(first, sort_keys=True),
            json.dumps(self.plan(program=shuffled), sort_keys=True),
        )

    def test_a_revolve_binds_the_program_radius_to_the_measured_curve(self):
        dump = fx.capped_cylinder_dump()
        plan = plan_emission(
            fx.program(dump.sha256, archetypes=[fx.revolve_archetype()]),
            dump,
            fx.rebuild_spec("unused"),
        )
        step = plan["steps"][0]
        self.assertEqual("revolve", step["kind"])
        self.assertTrue(step["entities"][-1]["on_axis"])
        bound = [d for d in step["dimensions"] if d.get("bound_from_program")]
        self.assertEqual(["recon_revolve_1_radius"], [d["parameter"] for d in bound])
        # No orphan: the program's own radius parameter drives a real dimension
        # rather than being minted alongside a duplicate.
        names = [row["name"] for row in plan["user_parameters"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("recon_revolve_1_radius", names)

    def test_a_revolve_radius_that_matches_no_section_curve_refuses(self):
        dump = fx.capped_cylinder_dump()
        program = fx.program(
            dump.sha256, archetypes=[fx.revolve_archetype(radius=99.0)]
        )
        with self.assertRaises(ReconstructionRefused) as caught:
            plan_emission(program, dump, fx.rebuild_spec("unused"))
        self.assertEqual("entity-resolution-ambiguous", caught.exception.reason)
        self.assertEqual(99.0, caught.exception.detail["declared_value_mm"])

    def test_a_revolve_axis_that_is_not_the_sketch_plane_axis_refuses(self):
        dump = fx.capped_cylinder_dump()
        archetype = fx.revolve_archetype()
        archetype["axis"]["datum_axis"] = "Y"  # not in the XZ sketch plane at all
        with self.assertRaises(ReconstructionRefused) as caught:
            plan_emission(
                fx.program(dump.sha256, archetypes=[archetype]),
                dump,
                fx.rebuild_spec("unused"),
            )
        self.assertEqual("program-schema-violation", caught.exception.reason)
        self.assertEqual("Z", caught.exception.detail["expected_axis"])

    def test_a_program_in_units_the_dump_is_not_written_in_refuses(self):
        # The dump format writes millimetres, so an inch label would put the
        # sketch geometry and the dimension driving it 25.4x apart.
        program = fx.program(self.dump.sha256, units="in")
        with self.assertRaises(ReconstructionRefused) as caught:
            plan_emission(program, self.dump, self.spec)
        self.assertEqual("units-unsupported", caught.exception.reason)

    def test_an_inverted_cap_order_is_named_rather_than_silently_flipped(self):
        # The extent is an absolute distance, so a cap normal anti-parallel to
        # the datum axis makes the program hand over the far cap. Detected and
        # named; never repaired here, because the extrude direction would still
        # be wrong and repairing a program in the emitter is improvisation.
        archetype = fx.extrude_archetype(offset=30.0, depth=20.0)
        program = fx.program(self.dump.sha256, archetypes=[archetype])
        with self.assertRaises(ReconstructionRefused) as caught:
            plan_emission(program, self.dump, self.spec)
        self.assertEqual("cap-order-inverted", caught.exception.reason)
        self.assertEqual(20.0, caught.exception.detail["mirrored_station_mm"])

    def test_a_plane_nowhere_near_the_body_still_refuses_as_not_found(self):
        program = fx.program(
            self.dump.sha256, archetypes=[fx.extrude_archetype(offset=500.0, depth=20.0)]
        )
        with self.assertRaises(ReconstructionRefused) as caught:
            plan_emission(program, self.dump, self.spec)
        self.assertEqual("profile-not-found", caught.exception.reason)

    def test_a_revolve_whose_section_never_crosses_the_axis_refuses(self):
        # An open tube's axial section is two runs, not one closed loop.
        dump = fx.cylinder_dump()
        with self.assertRaises(ReconstructionRefused) as caught:
            plan_emission(
                fx.program(dump.sha256, archetypes=[fx.revolve_archetype()]),
                dump,
                fx.rebuild_spec("unused"),
            )
        self.assertEqual("profile-not-found", caught.exception.reason)

    def test_a_section_that_closes_two_loops_refuses_rather_than_picking_one(self):
        # Picking the larger loop would silently drop the other solid, and
        # "choose among candidates" is exactly the decision the executor and the
        # planner are both forbidden to make on their own initiative.
        dump = fx.two_box_dump()
        with self.assertRaises(ReconstructionRefused) as caught:
            plan_emission(fx.program(dump.sha256), dump, self.spec)
        self.assertEqual("profile-ambiguous", caught.exception.reason)
        self.assertEqual(2, len(caught.exception.detail["closed_loop_point_counts"]))

    def test_the_ambiguous_refusal_now_names_every_loops_walls_and_material_side(self):
        # The refusal is unchanged -- two loops still stop this emitter -- but a
        # loop count is not a diagnosis. The detail now carries what was measured
        # at that station, which is what makes the next reader able to see two
        # disjoint outer loops rather than guess at an internal void.
        dump = fx.two_box_dump()
        with self.assertRaises(ReconstructionRefused) as caught:
            plan_emission(fx.program(dump.sha256), dump, self.spec)
        evidence = caught.exception.detail["loop_evidence"]
        self.assertEqual("outward", evidence["winding"]["winding"])
        self.assertTrue(evidence["winding"]["closed"])
        self.assertEqual(2, evidence["closed_loop_count"])
        self.assertEqual(
            ["material-inside", "material-inside"], [row["verdict"] for row in evidence["loops"]]
        )
        for row in evidence["loops"]:
            self.assertEqual(1.0, row["consensus_fraction"])
            self.assertEqual(0, row["depth"])
            self.assertTrue(row["parity_agrees"])
            # This emitter never sees the fit record, so it names no regions.
            self.assertEqual([], row["wall_regions"])
        self.assertEqual([], evidence["gates"])
        self.assertEqual(
            {"loop_material_consensus_fraction": 0.95, "loop_attribution_min_fraction": 0.05},
            evidence["declared"],
        )

    def test_a_single_loop_station_pays_nothing_for_the_evidence_it_does_not_need(self):
        # The measurement is a whole winding pass over the dump. It runs only
        # where the station is about to be ambiguous; a one-loop section builds
        # exactly as it did before, with no evidence table anywhere in the plan.
        plan = plan_emission(fx.program(self.dump.sha256), self.dump, self.spec)
        self.assertNotIn("loop_evidence", json.dumps(plan))

    def test_a_deliberately_inverted_wall_reaches_the_contradictory_verdict(self):
        # One triangle of one wall wound the other way: the mesh stays closed and
        # keeps its volume, so the question stays licensed, and the walls of that
        # loop then disagree with themselves past the declared floor.
        dump = fx.two_box_dump()
        station = 0.0  # the fixture program's own mid-station, on the lower cap
        triangles = list(dump.triangles)
        walls = [
            index
            for index in range(0, len(triangles), 3)
            if sorted(dump.vertices_mm[3 * triangles[index + k] + 2] for k in range(3))[:2]
            == [station, station]
            and max(dump.vertices_mm[3 * triangles[index + k] + 2] for k in range(3)) > station
        ]
        # Two of the twenty-four wall facets this loop is cut from, so the
        # dissent is 1/12 of its length -- comfortably past the declared 5%.
        for index in walls[:2]:
            triangles[index], triangles[index + 2] = triangles[index + 2], triangles[index]
        inverted = fx.make_dump(
            [
                tuple(dump.vertices_mm[3 * i + k] for k in range(3))
                for i in range(len(dump.vertices_mm) // 3)
            ],
            [tuple(triangles[i : i + 3]) for i in range(0, len(triangles), 3)],
            face_groups=list(dump.face_group_ids),
        )
        with self.assertRaises(ReconstructionRefused) as caught:
            plan_emission(fx.program(inverted.sha256), inverted, self.spec)
        evidence = caught.exception.detail["loop_evidence"]
        self.assertFalse(evidence["winding"]["consistently_wound"])
        self.assertIn("loop-material-contradictory", evidence["gates"])
        contradictory = [r for r in evidence["loops"] if r["verdict"] == "contradictory"]
        self.assertEqual(1, len(contradictory))
        self.assertLess(contradictory[0]["consensus_fraction"], 0.95)

    def test_a_plane_that_misses_the_mesh_refuses_rather_than_inventing_a_profile(self):
        program = fx.program(
            self.dump.sha256,
            archetypes=[fx.extrude_archetype(offset=500.0, depth=20.0)],
        )
        with self.assertRaises(ReconstructionRefused) as caught:
            plan_emission(program, self.dump, self.spec)
        self.assertEqual("profile-not-found", caught.exception.reason)


    def test_a_hole_archetype_missing_its_hole_block_refuses_by_name(self):
        # This unit builds holes now. What it will not do is read an archetype
        # labelled `hole` that carries no diameter and no position and guess the
        # two numbers that would make it one.
        hole = dict(fx.extrude_archetype(identifier="hole-cccccccccccc"), kind="hole")
        program = fx.program(
            self.dump.sha256,
            archetypes=[hole],
            parameters=[
                {
                    "name": "recon_base_1_depth",
                    "quantity": "depth",
                    "unit": "mm",
                    "nominal": 20.0,
                    "expected_observable": "volume",
                    "observable_rationale": "fixture",
                    "rationale": "fixture",
                    "driving_archetypes": ["hole-cccccccccccc"],
                }
            ],
        )
        with self.assertRaises(ReconstructionRefused) as caught:
            plan_emission(program, self.dump, self.spec)
        self.assertEqual("program-schema-violation", caught.exception.reason)
        self.assertEqual("hole-cccccccccccc", caught.exception.detail["archetype_id"])
        self.assertIn("no hole block", str(caught.exception))

    def test_a_shuffled_declared_order_refuses(self):
        first = fx.extrude_archetype(identifier="sketch-extrude-aaaaaaaaaaaa")
        second = fx.extrude_archetype(
            identifier="sketch-extrude-dddddddddddd",
            operation="join",
            dependencies=["sketch-extrude-aaaaaaaaaaaa"],
            parameter="recon_base_2_depth",
        )
        program = fx.program(
            self.dump.sha256,
            archetypes=[first, second],
            order=[second["id"], first["id"]],
        )
        with self.assertRaises(ReconstructionRefused) as caught:
            plan_emission(program, self.dump, self.spec)
        self.assertEqual("program-order-invalid", caught.exception.reason)

    def test_a_cyclic_dependency_refuses_rather_than_looping(self):
        first = fx.extrude_archetype(identifier="a-1", dependencies=["a-2"])
        second = fx.extrude_archetype(
            identifier="a-2", dependencies=["a-1"], parameter="recon_base_2_depth"
        )
        with self.assertRaises(ReconstructionRefused) as caught:
            total_order([first, second])
        self.assertEqual("program-order-cyclic", caught.exception.reason)

    def test_a_dependency_on_an_absent_archetype_refuses(self):
        with self.assertRaises(ReconstructionRefused) as caught:
            total_order([fx.extrude_archetype(dependencies=["nobody"])])
        self.assertEqual("program-order-invalid", caught.exception.reason)

    def test_a_rotated_sketch_plane_refuses_as_unmappable(self):
        archetype = fx.extrude_archetype()
        archetype["plane"]["rotation"] = {"datum_axis": "X", "angle_deg": 12.0}
        program = fx.program(self.dump.sha256, archetypes=[archetype])
        with self.assertRaises(ReconstructionRefused) as caught:
            plan_emission(program, self.dump, self.spec)
        self.assertEqual("plane-unmappable", caught.exception.reason)

    def test_a_tampered_program_refuses_by_schema_before_anything_else(self):
        program = fx.program(self.dump.sha256)
        program["covered_area_fraction"] = 4.0
        with self.assertRaises(ReconstructionRefused) as caught:
            plan_emission(program, self.dump, self.spec)
        self.assertEqual("program-schema-violation", caught.exception.reason)
        paths = {issue["path"] for issue in caught.exception.detail["issues"]}
        self.assertIn("program.covered_area_fraction", paths)

    def test_a_program_fitted_from_another_dump_refuses(self):
        program = fx.program("f" * 64)
        with self.assertRaises(ReconstructionRefused) as caught:
            plan_emission(program, self.dump, self.spec)
        self.assertEqual("program-schema-violation", caught.exception.reason)

    def test_an_extrude_without_a_parameterised_extent_refuses(self):
        archetype = fx.extrude_archetype()
        archetype["extent"]["parameter"] = None
        program = fx.program(self.dump.sha256, archetypes=[archetype], parameters=[])
        with self.assertRaises(ReconstructionRefused) as caught:
            plan_emission(program, self.dump, self.spec)
        self.assertEqual("program-parameter-unbound", caught.exception.reason)

    def test_a_collision_with_an_existing_manifest_parameter_refuses(self):
        with self.assertRaises(ReconstructionRefused) as caught:
            self.plan(manifest_parameter_names=["recon_base_1_depth"])
        self.assertEqual("parameter-name-collision", caught.exception.reason)

    def test_adopted_constraints_are_carried_but_never_claimed_enforced(self):
        archetype = fx.extrude_archetype(
            constraints=[
                {
                    "kind": "perpendicular",
                    "subjects": ["a" * 64, "b" * 64],
                    "snapped_from": 0.4,
                    "snapped_from_unit": "deg",
                    "license_tolerance": 1.0,
                    "license_basis": "uncertainty",
                    "rationale": "fixture",
                }
            ]
        )
        plan = self.plan(program=fx.program(self.dump.sha256, archetypes=[archetype]))
        carried = plan["steps"][0]["adopted_constraints"]
        self.assertEqual(1, len(carried))
        self.assertIs(False, carried[0]["localized"])
        self.assertIn("region provenance", plan["adopted_constraint_note"])

    def test_the_overlay_transform_maps_datum_space_through_the_body_transform(self):
        # Non-obvious matrix order, pinned numerically: a point stated in the
        # datum frame must land where the mesh actually sits, or the rebuild
        # overlays nothing and the deviation run grades the wrong pair.
        from fusion_design.mesh_rebuild import _datum_transform_cm
        from test_mesh_segmentation import make_dump

        datum = {
            "origin": [10.0, 20.0, 30.0],
            "x_axis": [0.0, 1.0, 0.0],
            "y_axis": [0.0, 0.0, 1.0],
            "z_axis": [1.0, 0.0, 0.0],
            "evidence": {},
        }
        vertices, triangles, groups = fx.box_mesh()
        # The mesh body itself sits 5 cm along world X.
        dump = make_dump(
            vertices,
            triangles,
            transform=[1.0, 0, 0, 5.0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0],
        )
        matrix = _datum_transform_cm(datum, dump)["matrix"]

        def apply(point):
            row = list(point) + [1.0]
            return tuple(
                round(sum(matrix[4 * r + c] * row[c] for c in range(4)), 9) for r in range(3)
            )

        # The datum origin is 10/20/30 mm = 1/2/3 cm in mesh space, plus the
        # body's own 5 cm offset.
        self.assertEqual((6.0, 2.0, 3.0), apply((0.0, 0.0, 0.0)))
        # One centimetre along datum X, which this frame points down world Y.
        self.assertEqual((6.0, 3.0, 3.0), apply((1.0, 0.0, 0.0)))
        # One centimetre along datum Z, which this frame points down world X.
        self.assertEqual((7.0, 2.0, 3.0), apply((0.0, 0.0, 1.0)))

    def test_the_overlay_transform_never_claims_alignment_it_cannot_establish(self):
        vertices, triangles, groups = fx.box_mesh()
        from test_mesh_segmentation import make_dump

        dump = make_dump(vertices, triangles, transform=None, transform_source="unavailable")
        plan = plan_emission(fx.program(dump.sha256), dump, self.spec)
        self.assertEqual("mesh-body space", plan["datum_transform"]["frame"])
        self.assertIn("does not claim more", plan["datum_transform"]["note"])


class ProfileGuardTests(unittest.TestCase):
    """The two guards that stand between a bad section and an invented profile.

    Neither fires on the fixtures, because `classify_polyline` guarantees
    consecutive entities share endpoints exactly and the mesh sections used here
    are clean. They are checked directly rather than left as guards nobody has
    ever seen run: an upstream change that broke the guarantee would otherwise
    reach Fusion as a silently open profile.
    """

    def entity(self, start, end, kind="line"):
        row = {
            "kind": kind,
            "start_mm": list(start),
            "end_mm": list(end),
            "residual_mm": 0.0,
            "point_count": 2,
        }
        return row

    def test_a_chain_with_a_gap_refuses_and_names_the_gap(self):
        entities = [
            self.entity((0.0, 0.0), (10.0, 0.0)),
            self.entity((10.5, 0.0), (10.0, 10.0)),  # starts 0.5 mm from the last end
            self.entity((10.0, 10.0), (0.0, 0.0)),
        ]
        with self.assertRaises(ReconstructionRefused) as caught:
            _require_chained(entities, 0.01, "a-1")
        self.assertEqual("profile-not-closed", caught.exception.reason)
        self.assertAlmostEqual(0.5, caught.exception.detail["gap_mm"], places=9)
        self.assertEqual(0, caught.exception.detail["entity_index"])

    def test_a_single_circle_is_a_closed_profile(self):
        self.assertIsNone(
            _require_chained(
                [self.entity((1.0, 0.0), (1.0, 0.0), kind="circle")], 0.01, "a-1"
            )
        )

    def test_an_empty_section_is_refused_rather_than_treated_as_a_null_profile(self):
        with self.assertRaises(ReconstructionRefused) as caught:
            _require_chained([], 0.01, "a-1")
        self.assertEqual("profile-not-closed", caught.exception.reason)

    def test_a_section_that_never_reaches_the_axis_needs_no_closing_line(self):
        # A ring revolved about a line it does not touch is a torus, and its
        # section is already closed. Appending a closure would be a zero-length
        # line at an arbitrary place and a claim the evidence does not support.
        points = [(2.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 0.0, 3.0), (2.0, 0.0, 3.0)]
        clipped = _clip_half(points, (1.0, 0.0, 0.0), (0.0, 0.0, 0.0), 1e-9)
        self.assertEqual((points, False), clipped)

    def test_a_section_crossing_the_axis_four_times_has_no_single_half_profile(self):
        # An hourglass section: revolving the whole thing sweeps the body twice,
        # and choosing one of the two positive runs would be a guess.
        points = [
            (0.0, 0.0, 0.0),
            (5.0, 0.0, 5.0),
            (-5.0, 0.0, 10.0),
            (5.0, 0.0, 15.0),
            (-5.0, 0.0, 20.0),
        ]
        self.assertIsNone(_clip_half(points, (1.0, 0.0, 0.0), (0.0, 0.0, 0.0), 1e-9))

    def test_a_section_entirely_on_the_far_side_of_the_axis_has_no_half_profile(self):
        points = [(-1.0, 0.0, 0.0), (-5.0, 0.0, 5.0), (-3.0, 0.0, 10.0)]
        self.assertIsNone(_clip_half(points, (1.0, 0.0, 0.0), (0.0, 0.0, 0.0), 1e-9))

    def test_the_axis_crossing_is_interpolated_not_snapped_to_a_sample(self):
        points = [(-2.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 0.0, 4.0), (-2.0, 0.0, 4.0)]
        half, touches_axis = _clip_half(points, (1.0, 0.0, 0.0), (0.0, 0.0, 0.0), 1e-9)
        self.assertTrue(touches_axis)
        self.assertEqual(
            [(0.0, 0.0), (2.0, 0.0), (2.0, 4.0), (0.0, 4.0)],
            [(round(p[0], 9), round(p[2], 9)) for p in half],
        )


class SpecValidationTests(unittest.TestCase):
    def test_every_threshold_must_carry_a_rationale(self):
        spec = fx.rebuild_spec("dump.bin")
        spec["thresholds"]["snap_tolerance_deg"] = {"value": 2.0}
        codes = {issue.code for issue in validate_rebuild_spec(spec)}
        self.assertIn("threshold-missing-rationale", codes)

    def test_a_bare_number_threshold_is_rejected(self):
        spec = fx.rebuild_spec("dump.bin")
        spec["thresholds"]["snap_tolerance_mm"] = 0.1
        codes = {issue.code for issue in validate_rebuild_spec(spec)}
        self.assertIn("threshold-must-be-declared", codes)

    def test_a_zero_rejection_budget_is_a_real_choice(self):
        spec = fx.rebuild_spec("dump.bin")
        spec["thresholds"]["constraint_rejection_budget"] = {
            "value": 0,
            "rationale": "this part's profiles are exact; any rejection means the plan is wrong.",
        }
        self.assertEqual([], validate_rebuild_spec(spec))

    def test_a_negative_budget_is_not(self):
        spec = fx.rebuild_spec("dump.bin")
        spec["thresholds"]["constraint_rejection_budget"] = {"value": -1, "rationale": "x"}
        codes = {issue.code for issue in validate_rebuild_spec(spec)}
        self.assertIn("threshold-invalid-value", codes)

    def test_unknown_threshold_keys_are_rejected(self):
        spec = fx.rebuild_spec("dump.bin")
        spec["thresholds"]["fudge"] = fx.threshold(1.0)
        self.assertTrue(validate_rebuild_spec(spec))


class EmittedSourceTests(unittest.TestCase):
    """Invariants over the generated text itself."""

    @classmethod
    def setUpClass(cls):
        cls.manifest = build_manifest()
        cls.directory = tempfile.TemporaryDirectory()
        cls.dump = fx.box_dump()
        path = Path(cls.directory.name) / "mesh.bin"
        path.write_bytes(_dump_bytes(cls.dump))
        cls.dump_path = str(path)
        cls.program = fx.program(
            cls.dump.sha256, manifest_sha256=_manifest_hash(cls.manifest)
        )
        cls.source = emit_mesh_rebuild_script(
            cls.manifest,
            classification_record(),
            source_record(cls.manifest),
            cls.program,
            fx.rebuild_spec(cls.dump_path),
            NONCE,
        )
        # The prelude is parameterised by where the transaction tees its report,
        # so strip the one this emitter actually produced rather than the default.
        cls.transaction = cls.source[
            len(_script_prelude(cls.manifest, report_dir=str(Path(cls.dump_path).parent))) :
        ]

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_the_emitted_source_compiles(self):
        compile(self.source, "<rebuild>", "exec")

    def test_the_transaction_starts_no_process(self):
        # Inside Fusion sys.executable is the Fusion binary, so shelling out
        # launches a second Fusion.
        for banned in ("subprocess", "os.system", "os.exec", "Popen", "sys.executable"):
            self.assertNotIn(banned, self.source, banned)

    def test_the_transaction_contains_no_direct_edit_or_faceted_shortcut(self):
        for banned in ("baseFeatures", "BaseFeature", "TemporaryBRepManager", "setByPlane"):
            self.assertNotIn(banned, self.transaction, banned)

    def test_the_transaction_never_reads_designtype(self):
        self.assertNotIn("designType", self.source)

    def test_no_positional_index_into_a_body_face_or_edge_list(self):
        # The rule is about *identity*, not about iteration. Selecting a face or
        # an edge by a fixed position is the classic trap -- indices shuffle on
        # rebuild and the parameter silently binds to different geometry.
        # Enumerating a feature-owned collection and matching each member on its
        # own attributes is the sanctioned pattern (D5) and is how the fillet
        # finds the edges its two parents share, so the ban is written against
        # constant subscripts rather than against `item(` as a string.
        import re

        for banned in ("body.faces[", "body.edges["):
            self.assertNotIn(banned, self.transaction, banned)
        constant_index = re.findall(r"\.item\(\s*\d+\s*\)", self.transaction)
        self.assertEqual([], constant_index, constant_index)
        # And every `item(` that survives is driven by a range over the
        # collection's own count, never by a remembered number.
        for line in self.transaction.splitlines():
            if ".item(" in line:
                self.assertNotIn("stored_index", line, line)

    def test_every_capability_probe_refuses_rather_than_defaulting(self):
        # `getattr(x, name, None)` whose result is later compared turns
        # "capability absent" into "condition not met". Every probe here uses
        # the sentinel form and branches on it explicitly.
        for line in self.transaction.splitlines():
            if "getattr(" in line:
                self.assertIn("_MISSING", line, line)

    def test_the_plan_is_embedded_as_data_not_as_generated_control_flow(self):
        self.assertIn("PLAN = json.loads(", self.transaction)
        self.assertNotIn("sketch-extrude-aaaaaaaaaaaa", self.transaction.split("\n", 1)[1])

    def test_the_nonce_and_every_hash_binding_are_embedded(self):
        for value in (NONCE, self.dump.sha256, self.program["program_sha256"]):
            self.assertIn(value, self.source)

    def test_emission_is_byte_identical_across_runs(self):
        again = emit_mesh_rebuild_script(
            self.manifest,
            classification_record(),
            source_record(self.manifest),
            self.program,
            fx.rebuild_spec(self.dump_path),
            NONCE,
        )
        self.assertEqual(self.source, again)

    def test_a_dump_that_does_not_hash_to_the_program_is_never_parsed(self):
        program = dict(self.program)
        program["dump_sha256"] = "e" * 64
        from fusion_design.reconstruction_program import program_sha256

        program.pop("program_sha256")
        program["program_sha256"] = program_sha256(program)
        with self.assertRaises(MeshDumpError) as caught:
            emit_mesh_rebuild_script(
                self.manifest,
                classification_record(),
                source_record(self.manifest),
                program,
                fx.rebuild_spec(self.dump_path),
                NONCE,
            )
        self.assertEqual("dump-hash-mismatch", caught.exception.reason)

    def test_a_faceted_classification_cannot_open_this_gate(self):
        record = classify(
            request(edit_kind="boolean-mechanical", facet_count=3800, facet_budget=10000),
            SOURCE,
        ).to_dict()
        self.assertEqual("faceted-brep", record["path"])
        with self.assertRaises(ManifestValidationError) as caught:
            emit_mesh_rebuild_script(
                self.manifest,
                record,
                source_record(self.manifest),
                self.program,
                fx.rebuild_spec(self.dump_path),
                NONCE,
            )
        self.assertIn(
            "classification-path-forbids-operation",
            {issue.code for issue in caught.exception.issues},
        )

    def test_a_short_nonce_is_refused(self):
        with self.assertRaises(ValueError):
            emit_mesh_rebuild_script(
                self.manifest,
                classification_record(),
                source_record(self.manifest),
                self.program,
                fx.rebuild_spec(self.dump_path),
                "short",
            )


def _manifest_hash(manifest):
    from fusion_design.scripts import manifest_sha256

    return manifest_sha256(manifest)


def _dump_bytes(dump):
    from fusion_design.mesh_dump import pack_mesh_dump

    # Round-trips the grouping too: a dump written without it would not hash to
    # the dump the program was fitted from, and would refuse a stage later for
    # the wrong reason.
    return pack_mesh_dump(
        dump.metadata,
        list(dump.vertices_mm),
        list(dump.triangles),
        None if dump.face_group_ids is None else list(dump.face_group_ids),
    )


class TransactionBehaviourTests(unittest.TestCase):
    """The emitted interpreter, run against Fusion doubles."""

    @classmethod
    def setUpClass(cls):
        cls.manifest = build_manifest()
        cls.document = cls.manifest.fusion_document
        cls.directory = tempfile.TemporaryDirectory()
        cls.dump = fx.box_dump()
        path = Path(cls.directory.name) / "mesh.bin"
        path.write_bytes(_dump_bytes(cls.dump))
        cls.dump_path = str(path)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def emit(self, program=None, **spec_overrides):
        program = program if program is not None else fx.program(
            self.dump.sha256, manifest_sha256=_manifest_hash(self.manifest)
        )
        return emit_mesh_rebuild_script(
            self.manifest,
            classification_record(),
            source_record(self.manifest),
            program,
            fx.rebuild_spec(self.dump_path, **spec_overrides),
            NONCE,
        )

    def plate_with_hole(self, extra=()):
        archetypes = [fx.extrude_archetype(), fx.hole_archetype(), *extra]
        return fx.program(
            self.dump.sha256,
            manifest_sha256=_manifest_hash(self.manifest),
            archetypes=archetypes,
        )

    def test_a_hole_builds_a_cut_from_a_placement_point_dimensioned_to_the_origin(self):
        design = fakes.make_design()
        report, error = run_transaction(self.emit(self.plate_with_hole()), design, self.document)
        self.assertIsNone(error, report)
        self.assertTrue(report["ok"], report)
        kinds = [entry["kind"] for entry in report["created"]]
        self.assertEqual(
            ["component", "construction-plane", "sketch-extrude", "construction-plane", "hole"],
            kinds,
        )
        hole_sketch = report["sketches"][1]
        # No curves: a hole's size is the fitted diameter carried on the
        # feature, and its sketch holds only the point that positions it.
        self.assertEqual(0, hole_sketch["entity_count"])
        self.assertEqual(
            ["recon_hole_1_x", "recon_hole_1_y"],
            sorted(
                entry["parameter"]
                for entry in hole_sketch["applied_dimensions"]
                if entry["kind"] == "hole-position"
            ),
        )
        # Every number the hole is built from is a named parameter.
        names = {row["name"] for row in report["user_parameters"]}
        self.assertLessEqual(
            {"recon_hole_1_dia", "recon_hole_1_depth", "recon_hole_1_x", "recon_hole_1_y"}, names
        )

    def test_a_hole_position_parameter_declares_the_centroid_not_the_volume(self):
        design = fakes.make_design()
        report, _ = run_transaction(self.emit(self.plate_with_hole()), design, self.document)
        by_name = {row["name"]: row for row in report["user_parameters"]}
        # The D7 generalisation, carried end to end: sliding a hole across a
        # face need not change the volume at all, so a volume-only proof would
        # brand this correct parameter inert.
        self.assertEqual("centroid", by_name["recon_hole_1_x"]["expected_observable"])
        self.assertEqual("volume", by_name["recon_hole_1_dia"]["expected_observable"])

    def test_a_fillet_rounds_the_edge_its_two_parents_share(self):
        design = fakes.make_design()
        program = self.plate_with_hole(extra=[fx.fillet_archetype()])
        report, error = run_transaction(self.emit(program), design, self.document)
        self.assertIsNone(error, report)
        self.assertTrue(report["ok"], report)
        fillet = [entry for entry in report["created"] if entry["kind"] == "fillet"]
        self.assertEqual(1, len(fillet))
        self.assertEqual(3, fillet[0]["edge_count"])
        self.assertEqual(
            ["hole-cccccccccccc", "sketch-extrude-aaaaaaaaaaaa"], sorted(fillet[0]["between"])
        )
        self.assertEqual([], report["fillets_skipped"])

    def test_a_fillet_is_ordered_last_and_never_before_what_it_rounds(self):
        program = self.plate_with_hole(extra=[fx.fillet_archetype()])
        self.assertEqual(
            ["sketch-extrude-aaaaaaaaaaaa", "hole-cccccccccccc", "fillet-eeeeeeeeeeee"],
            program["order"],
        )

    def test_a_fillet_whose_parents_share_no_edge_is_skipped_by_name_not_refused(self):
        # Fillets are individually optional because nothing depends on them.
        # Skipping is loud: the archetype, the reason, and the coverage
        # consequence are all recorded.
        design = fakes.make_design(
            behaviour={"feature_edge_ids": {"extrude": [1, 2], "hole": [7, 8]}}
        )
        program = self.plate_with_hole(extra=[fx.fillet_archetype()])
        report, error = run_transaction(self.emit(program), design, self.document)
        self.assertIsNone(error, report)
        self.assertTrue(report["ok"], report)
        self.assertEqual([], [e for e in report["created"] if e["kind"] == "fillet"])
        skipped = report["fillets_skipped"]
        self.assertEqual(1, len(skipped))
        self.assertEqual("fillet-eeeeeeeeeeee", skipped[0]["archetype_id"])
        self.assertEqual("entity-resolution-ambiguous", skipped[0]["reason"])
        self.assertIn("share no edge", skipped[0]["detail"])
        self.assertIn("coverage account subtracts", report["fillets_skipped_note"])

    def test_a_fusion_without_the_fillet_apis_skips_by_name_and_still_builds(self):
        # An absent API member must never read as "these features share no
        # edges": one is a capability answer and the other is a geometry
        # answer, and they call for different fixes.
        design = fakes.make_design(behaviour={"no_feature_faces": True})
        program = self.plate_with_hole(extra=[fx.fillet_archetype()])
        report, error = run_transaction(self.emit(program), design, self.document)
        self.assertIsNone(error, report)
        self.assertTrue(report["ok"], report)
        self.assertEqual("fillet-capability", report["fillets_skipped"][0]["reason"])
        # The extrude and the hole still stand: a fillet carries no dependents.
        self.assertEqual(
            ["sketch-extrude", "hole"],
            [e["kind"] for e in report["created"] if e["kind"] in ("sketch-extrude", "hole")],
        )

    def test_a_hole_that_fails_to_build_rolls_the_whole_run_back(self):
        # A hole is not optional: something may depend on it, so its failure is
        # the ordinary refusal-and-rollback rather than a skip.
        design = fakes.make_design(behaviour={"raise_on_feature": 1})
        report, error = run_transaction(self.emit(self.plate_with_hole()), design, self.document)
        self.assertIsNotNone(error)
        self.assertEqual(["feature-failed"], report["failures"])
        self.assertEqual([], report["created"])
        self.assertEqual("rolled-back", report["document_state"])

    def test_a_clean_run_builds_the_component_and_reports_what_it_created(self):
        design = fakes.make_design()
        report, error = run_transaction(self.emit(), design, self.document)
        self.assertIsNone(error, report)
        self.assertTrue(report["ok"], report)
        self.assertEqual("Reconstruction", report["component_name"])
        kinds = [entry["kind"] for entry in report["created"]]
        self.assertEqual(["component", "construction-plane", "sketch-extrude"], kinds)
        self.assertEqual(NONCE, report["rebuild_nonce"])
        self.assertEqual(4, len(report["user_parameters"]))
        self.assertIs(False, report["interactions_exercised"])
        sketch = report["sketches"][0]
        self.assertEqual([], sketch["rejected_constraints"])
        self.assertIs(True, sketch["fully_constrained"])
        self.assertEqual(6, len(sketch["applied_constraints"]))

    def test_the_report_never_claims_a_parameter_it_did_not_read_back(self):
        design = fakes.make_design()
        report, _ = run_transaction(self.emit(), design, self.document)
        live = {parameter.name for parameter in design.parameters}
        self.assertEqual(live, {row["name"] for row in report["user_parameters"]})

    def test_a_constraint_that_drags_the_profile_is_deleted_and_recorded(self):
        design = fakes.make_design(behaviour={"displace_on_constraint": ("horizontal", 5.0)})
        report, error = run_transaction(self.emit(), design, self.document)
        self.assertIsNone(error, report)
        rejected = report["sketches"][0]["rejected_constraints"]
        # Both horizontal snaps drag the profile, and each is deleted and
        # recorded individually rather than the sketch being abandoned.
        self.assertEqual(2, len(rejected))
        self.assertEqual("displacement", rejected[0]["reason"])
        self.assertAlmostEqual(5.0, rejected[0]["measured_displacement_mm"], places=6)
        self.assertTrue(report["ok"])
        # Deleting the constraint does not necessarily put the geometry back, so
        # the distance from the section is measured and reported rather than
        # assumed to be zero.
        sketch = report["sketches"][0]
        self.assertAlmostEqual(10.0, sketch["profile_displacement_mm"], places=6)
        self.assertIn("cannot establish", sketch["profile_displacement_note"])

    def test_a_clean_sketch_reports_no_displacement_from_the_section(self):
        design = fakes.make_design()
        report, _ = run_transaction(self.emit(), design, self.document)
        self.assertEqual(0.0, report["sketches"][0]["profile_displacement_mm"])

    def test_rejections_beyond_the_declared_budget_refuse_and_roll_everything_back(self):
        design = fakes.make_design(behaviour={"displace_on_constraint": ("horizontal", 5.0)})
        report, error = run_transaction(
            self.emit(
                thresholds={
                    "constraint_rejection_budget": {"value": 0, "rationale": "zero tolerance"}
                }
            ),
            design,
            self.document,
        )
        self.assertIsNotNone(error)
        self.assertEqual(["constraint-rejected-budget-exceeded"], report["failures"])
        self.assertEqual([], report["created"])
        self.assertEqual([], design.parameters)
        self.assertEqual(0, design.root_occurrences.count and 0)
        self.assertFalse(any(o.isValid for o in design.root_occurrences.items))

    def test_a_solver_error_on_a_constraint_is_recorded_like_a_displacement(self):
        design = fakes.make_design(behaviour={"raise_on_constraint": "vertical"})
        report, error = run_transaction(
            self.emit(
                thresholds={
                    "constraint_rejection_budget": {"value": 5, "rationale": "generous"}
                }
            ),
            design,
            self.document,
        )
        self.assertIsNone(error, report)
        reasons = {entry["reason"] for entry in report["sketches"][0]["rejected_constraints"]}
        self.assertEqual({"solver-error"}, reasons)

    def test_a_failed_feature_names_the_archetype_and_deletes_everything_before_it(self):
        design = fakes.make_design(behaviour={"raise_on_feature": 0})
        report, error = run_transaction(self.emit(), design, self.document)
        self.assertIsNotNone(error)
        self.assertEqual(["feature-failed"], report["failures"])
        self.assertEqual("sketch-extrude-aaaaaaaaaaaa", report["refusal_detail"]["archetype_id"])
        self.assertEqual([], report["created"])
        self.assertEqual("rolled-back", report["document_state"])
        self.assertEqual([], design.parameters)

    def test_rollback_deletes_every_kind_in_reverse_creation_order(self):
        # This ordering is not cosmetic: a user parameter a live dimension still
        # references will not delete, so the feature and its sketch have to go
        # first. The whole cross-kind sequence is instrumented, not just one end
        # of it.
        design = fakes.make_design(behaviour={"raise_on_feature": 0})
        order = []
        patches = [
            (fakes.FakeOccurrences, "addNewComponent", "occurrence"),
            (fakes.FakeConstructionPlanes, "add", "plane"),
            (fakes.FakeUserParameters, "add", "parameter"),
        ]
        originals = {}

        def wrap(result, label):
            inner = result.deleteMe

            def deleteMe():
                order.append(label)
                return inner()

            result.deleteMe = deleteMe
            return result

        for owner, method, label in patches:
            originals[(owner, method)] = getattr(owner, method)

        def make(owner, method, label):
            original = originals[(owner, method)]

            def patched(self, *args):
                return wrap(original(self, *args), label)

            return patched

        original_sketches = fakes.FakeComponent.sketches
        original_feature_add = fakes.FakeFeatureCollection.add
        for owner, method, label in patches:
            setattr(owner, method, make(owner, method, label))

        def sketches(self):
            inner = original_sketches.fget(self)

            class Wrapped:
                def add(_self, plane):
                    return wrap(inner.add(plane), "sketch")

            return Wrapped()

        fakes.FakeComponent.sketches = property(sketches)
        try:
            run_transaction(self.emit(), design, self.document)
        finally:
            for owner, method, _label in patches:
                setattr(owner, method, originals[(owner, method)])
            fakes.FakeComponent.sketches = original_sketches
            fakes.FakeFeatureCollection.add = original_feature_add
        # Creation order is occurrence, parameters, plane, sketch; deletion runs
        # the other way, with the occurrence last.
        self.assertEqual("sketch", order[0])
        self.assertEqual("plane", order[1])
        self.assertEqual("occurrence", order[-1])
        self.assertEqual(4, order.count("parameter"))

    def test_an_incomplete_rollback_is_reported_loudly(self):
        design = fakes.make_design(behaviour={"raise_on_feature": 0})
        source = self.emit()
        namespace = fakes.load_transaction(source, design, self.document)
        original = fakes.FakeSketch.deleteMe
        fakes.FakeSketch.deleteMe = lambda self: False
        try:
            stream = StringIO()
            with redirect_stdout(stream):
                with self.assertRaises(Exception):
                    namespace["run"](None)
            report = json.loads(
                re.search(
                    r"REPORT_BEGIN\n(?P<body>.*?)\nFUSION_DESIGN_REPORT_END",
                    stream.getvalue(),
                    re.DOTALL,
                ).group("body")
            )
        finally:
            fakes.FakeSketch.deleteMe = original
        # Both, and the cause first: an incomplete rollback is a second thing
        # that went wrong, not a replacement for the reason it went wrong.
        self.assertEqual(["feature-failed", "rollback-incomplete"], report["failures"])
        self.assertIn("sketch", report["rollback_remaining"])
        self.assertEqual("dirty", report["document_state"])
        self.assertIn("still holds them", report["document_state_note"])
        self.assertEqual([], report["created"])

    def test_a_pre_existing_parameter_name_refuses_before_any_geometry(self):
        design = fakes.make_design(parameters=[("recon_base_1_depth", "5 mm")])
        report, error = run_transaction(self.emit(), design, self.document)
        self.assertIsNotNone(error)
        self.assertEqual(["parameter-name-collision"], report["failures"])
        self.assertEqual([], design.rootComponent.bodies)

    def test_an_unhealthy_timeline_refuses_rather_than_shipping_the_model(self):
        design = fakes.make_design()
        source = self.emit()
        namespace = fakes.load_transaction(source, design, self.document)
        original = fakes.FakeFeatureCollection.add

        def add(self, feature_input):
            feature = original(self, feature_input)
            feature.healthy = False
            feature.errorOrWarningMessage = "the profile is self-intersecting"
            return feature

        fakes.FakeFeatureCollection.add = add
        try:
            stream = StringIO()
            with redirect_stdout(stream):
                with self.assertRaises(Exception):
                    namespace["run"](None)
            report = json.loads(
                re.search(
                    r"REPORT_BEGIN\n(?P<body>.*?)\nFUSION_DESIGN_REPORT_END",
                    stream.getvalue(),
                    re.DOTALL,
                ).group("body")
            )
        finally:
            fakes.FakeFeatureCollection.add = original
        self.assertEqual(["solver-unhealthy"], report["failures"])
        self.assertEqual([], report["created"])

    def test_a_sketch_that_closes_no_profile_refuses(self):
        design = fakes.make_design(behaviour={"profile_count": 0})
        report, error = run_transaction(self.emit(), design, self.document)
        self.assertIsNotNone(error)
        self.assertEqual(["profile-not-found"], report["failures"])

    def test_a_missing_api_member_refuses_by_name_instead_of_defaulting(self):
        design = fakes.make_design()
        del type(design.rootComponent).occurrences
        try:
            report, error = run_transaction(self.emit(), design, self.document)
        finally:
            type(design.rootComponent).occurrences = property(
                lambda self: self.design.root_occurrences
            )
        self.assertIsNotNone(error)
        self.assertEqual(["rebuild-capability"], report["failures"])
        self.assertIn("Component.occurrences", report["refusal_detail"]["missing"])

    def test_a_wrong_document_is_refused_before_anything_is_created(self):
        design = fakes.make_design()
        report, error = run_transaction(self.emit(), design, "SomebodyElse")
        self.assertIsNotNone(error)
        self.assertIn("does not match manifest target", report["error"])
        self.assertEqual([], report["created"])

    def test_a_document_swapped_out_mid_transaction_stops_and_rolls_back(self):
        design = fakes.make_design()
        state = {"pumps": 0}

        def swap(document, app):
            state["pumps"] += 1
            if state["pumps"] >= 2:
                document.name = "SomebodyElseOpenedThis"

        namespace = fakes.load_transaction(self.emit(), design, self.document, on_events=swap)
        stream = StringIO()
        with redirect_stdout(stream):
            with self.assertRaises(Exception):
                namespace["run"](None)
        report = json.loads(
            re.search(
                r"REPORT_BEGIN\n(?P<body>.*?)\nFUSION_DESIGN_REPORT_END",
                stream.getvalue(),
                re.DOTALL,
            ).group("body")
        )
        self.assertEqual(["document-changed"], report["failures"])
        self.assertEqual([], report["created"])
        self.assertEqual([], design.parameters)

    def test_the_profile_is_chained_by_shared_sketch_points(self):
        # Four chained lines share four points, not eight: the closed profile's
        # topology comes from construction, so no coincident constraint has to
        # carry it and none can be rejected out from under it.
        design = fakes.make_design()
        report, error = run_transaction(self.emit(), design, self.document)
        self.assertIsNone(error, report)
        sketch = design.root_occurrences.items[0].component.sketch_list[0]
        self.assertEqual(4, len(sketch.curves))
        self.assertEqual(4, len(sketch.points))
        for index, curve in enumerate(sketch.curves):
            following = sketch.curves[(index + 1) % 4]
            self.assertIs(curve.endSketchPoint, following.startSketchPoint)

    def test_an_absent_isfullyconstrained_is_recorded_absent_never_fabricated(self):
        design = fakes.make_design()
        original = fakes.FakeSketch.__init__

        def init(self, design_, plane, behaviour):
            original(self, design_, plane, behaviour)
            del self.isFullyConstrained

        fakes.FakeSketch.__init__ = init
        try:
            report, error = run_transaction(self.emit(), design, self.document)
        finally:
            fakes.FakeSketch.__init__ = original
        self.assertIsNone(error, report)
        self.assertEqual("unavailable", report["sketches"][0]["fully_constrained"])


class ReplanTests(unittest.TestCase):
    def setUp(self):
        self.dump = fx.box_dump()
        self.first = fx.extrude_archetype(identifier="sketch-extrude-aaaaaaaaaaaa")
        self.second = fx.extrude_archetype(
            identifier="sketch-extrude-dddddddddddd",
            operation="join",
            parameter="recon_base_2_depth",
        )
        self.second["regions"] = ["d" * 64]
        self.program = fx.program(
            self.dump.sha256, archetypes=[self.first, self.second]
        )

    def refusal(self, archetype_id, token="feature-failed"):
        return {"failures": [token], "refusal_detail": {"archetype_id": archetype_id}}

    def test_a_replan_drops_the_named_archetype_and_re_hashes(self):
        replanned = replan_without(self.program, self.refusal(self.second["id"]))
        self.assertEqual([self.first["id"]], [g["id"] for g in replanned["archetypes"]])
        self.assertNotEqual(self.program["program_sha256"], replanned["program_sha256"])
        self.assertEqual(
            self.program["program_sha256"], replanned["replanned_from"]["program_sha256"]
        )
        self.assertLess(
            replanned["covered_area_fraction"], self.program["covered_area_fraction"]
        )

    def test_the_dropped_regions_are_declared_unreconstructed_with_the_refusal_named(self):
        replanned = replan_without(self.program, self.refusal(self.second["id"]))
        gates = [entry["gate"] for entry in replanned["unreconstructed"]]
        self.assertEqual(1, len(gates))
        self.assertIn("feature-failed", gates[0])

    def test_the_replanned_program_still_validates_and_still_plans(self):
        replanned = replan_without(self.program, self.refusal(self.second["id"]))
        plan = plan_emission(replanned, self.dump, fx.rebuild_spec("unused"))
        self.assertEqual([self.first["id"]], plan["order"])

    def test_dropping_something_others_depend_on_is_refused_not_papered_over(self):
        dependent = fx.extrude_archetype(
            identifier="sketch-extrude-eeeeeeeeeeee",
            operation="join",
            dependencies=[self.first["id"]],
            parameter="recon_base_3_depth",
        )
        program = fx.program(self.dump.sha256, archetypes=[self.first, dependent])
        with self.assertRaises(ValueError):
            replan_without(program, self.refusal(self.first["id"]))

    def test_a_replan_against_a_dirty_document_is_refused(self):
        # A refusal whose rollback did not complete leaves the failed emission in
        # the document; emitting a second component beside its wreckage is not a
        # replan, it is a mess.
        report = dict(
            self.refusal(self.second["id"]),
            document_state="dirty",
            rollback_remaining=["sketch"],
        )
        report["failures"] = ["feature-failed", "rollback-incomplete"]
        with self.assertRaises(ValueError) as caught:
            replan_without(self.program, report)
        self.assertIn("dirty document", str(caught.exception))

    def test_the_replan_names_the_cause_not_the_cleanup(self):
        report = dict(self.refusal(self.second["id"]))
        report["failures"] = ["constraint-rejected-budget-exceeded"]
        replanned = replan_without(self.program, report)
        self.assertEqual(
            "constraint-rejected-budget-exceeded", replanned["replanned_from"]["refusal"]
        )

    def test_a_refusal_that_names_no_archetype_cannot_be_replanned(self):
        with self.assertRaises(ValueError):
            replan_without(
                self.program, {"failures": ["rebuild-capability"], "refusal_detail": {}}
            )

    def test_a_token_outside_the_closed_vocabulary_cannot_become_a_gate(self):
        report = dict(self.refusal(self.second["id"]))
        report["failures"] = ["it-just-did-not-work"]
        with self.assertRaises(ValueError) as caught:
            replan_without(self.program, report)
        self.assertIn("closed refusal vocabulary", str(caught.exception))

    def test_a_report_naming_no_failure_cannot_become_a_gate(self):
        report = dict(self.refusal(self.second["id"]))
        report["failures"] = []
        with self.assertRaises(ValueError):
            replan_without(self.program, report)


class CliTests(unittest.TestCase):
    """The three commands this unit adds, driven through `main`."""

    def setUp(self):
        from contextlib import ExitStack

        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.dump = fx.box_dump()
        (self.directory / "mesh.bin").write_bytes(_dump_bytes(self.dump))
        # The CLI re-verifies every declared mesh source hash before emitting,
        # so the fixture writes a real file and declares its real digest.
        import hashlib

        from test_mesh_reconstruction import _manifest
        from test_mesh_source import mesh_source

        payload = b"solid fixture\nendsolid fixture\n"
        (self.directory / "sources").mkdir()
        (self.directory / "sources" / "bracket.stl").write_bytes(payload)
        self.source = mesh_source(sha256=hashlib.sha256(payload).hexdigest())
        manifest = _manifest(self.source)
        self.manifest_path = self.directory / "fusion-project.json"
        self.manifest_path.write_text(json.dumps(manifest.data), encoding="utf-8")
        self.program_path = self.directory / "program.json"
        self.program = fx.program(
            self.dump.sha256, manifest_sha256=_manifest_hash(manifest)
        )
        self.program_path.write_text(json.dumps(self.program), encoding="utf-8")
        self.classification_path = self.directory / "classification.json"
        self.classification_path.write_text(
            json.dumps(classify(request(edit_kind="dimensional"), self.source).to_dict()),
            encoding="utf-8",
        )
        self.spec_path = self.directory / "rebuild-spec.json"
        self.spec_path.write_text(
            json.dumps(fx.rebuild_spec(str(self.directory / "mesh.bin"))), encoding="utf-8"
        )

    def run_cli(self, argv):
        from contextlib import redirect_stderr, redirect_stdout
        from fusion_design.cli import main

        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_emit_mesh_rebuild_mints_its_own_nonce_and_writes_a_transaction(self):
        output = self.directory / "rebuild.py"
        code, _, stderr = self.run_cli(
            [
                "emit-mesh-rebuild",
                str(self.manifest_path),
                "--mesh-source-id",
                self.source["id"],
                "--classification",
                str(self.classification_path),
                "--program",
                str(self.program_path),
                "--rebuild-spec",
                str(self.spec_path),
                "-o",
                str(output),
            ]
        )
        self.assertEqual(0, code)
        nonce = re.search(r"rebuild nonce: (?P<value>[0-9a-f]{32})", stderr).group("value")
        source = output.read_text(encoding="utf-8")
        self.assertIn(nonce, source)
        compile(source, str(output), "exec")

    def test_a_refusal_prints_its_named_reason_and_exits_two(self):
        hole = dict(fx.extrude_archetype(identifier="hole-cccccccccccc"), kind="hole")
        program = fx.program(
            self.dump.sha256,
            archetypes=[hole],
            manifest_sha256=self.program["manifest_sha256"],
        )
        self.program_path.write_text(json.dumps(program), encoding="utf-8")
        code, stdout, _ = self.run_cli(
            [
                "emit-mesh-rebuild",
                str(self.manifest_path),
                "--mesh-source-id",
                self.source["id"],
                "--classification",
                str(self.classification_path),
                "--program",
                str(self.program_path),
                "--rebuild-spec",
                str(self.spec_path),
            ]
        )
        self.assertEqual(2, code)
        self.assertEqual("program-schema-violation", json.loads(stdout)["refusal"])

    def test_replan_without_writes_a_smaller_program_that_still_plans(self):
        second = fx.extrude_archetype(
            identifier="sketch-extrude-dddddddddddd",
            operation="join",
            parameter="recon_base_2_depth",
        )
        second["regions"] = ["d" * 64]
        program = fx.program(
            self.dump.sha256,
            archetypes=[fx.extrude_archetype(), second],
            manifest_sha256=_manifest_hash(build_manifest()),
        )
        self.program_path.write_text(json.dumps(program), encoding="utf-8")
        refusal = self.directory / "refusal.json"
        refusal.write_text(
            json.dumps(
                {
                    "failures": ["feature-failed"],
                    "refusal_detail": {"archetype_id": second["id"]},
                }
            ),
            encoding="utf-8",
        )
        output = self.directory / "program-2.json"
        code, _, _ = self.run_cli(
            ["replan-without", str(self.program_path), "--refusal", str(refusal), "-o", str(output)]
        )
        self.assertEqual(0, code)
        replanned = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(1, len(replanned["archetypes"]))
        self.assertTrue(plan_emission(replanned, self.dump, fx.rebuild_spec("unused"))["steps"])


class VocabularyTests(unittest.TestCase):
    def test_this_unit_emits_every_kind_a_program_can_carry(self):
        # The gap closed in U6: `hole` and `fillet` were unassignable while the
        # planner had no bore-versus-boss evidence to read. It reads
        # `orientation.material_side` now, so every kind in the program's
        # vocabulary has a producer, and this emitter builds all of them. A kind
        # in one set and not the other would be either a dead archetype or an
        # untestable emitter.
        self.assertEqual(ARCHETYPE_KINDS, EMITTED_KINDS)


if __name__ == "__main__":
    unittest.main()
