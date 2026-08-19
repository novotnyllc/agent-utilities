from __future__ import annotations

import copy
import json
import random
import unittest

from fusion_design.manifest import ManifestValidationError, ValidationIssue
from fusion_design.mesh_datum import ReconstructionRefused, parse_fit_record
from fusion_design import reconstruction_program as rp

import fixtures_fit_record as fx


MANIFEST_SHA = "b" * 64


def build(record, spec):
    return rp.build_reconstruction_program(
        parse_fit_record(record), spec, manifest_sha256=MANIFEST_SHA
    )


def adoption(kind, subjects, target, rationale="the part was designed that way."):
    return {"kind": kind, "subjects": list(subjects), "target": target, "rationale": rationale}


def two_bores(radius_b: float = 3.0):
    """Two parallel bores in a plate: the equal-radius and coaxial fixture."""
    return fx.record(
        [
            fx.cylinder("bore-a", (0.0, 0.0, 1.0), (0.0, 0.0, 4.0), 3.0, 150.0, 8.0),
            fx.cylinder("bore-b", (0.0, 0.0, 1.0), (9.0, 0.0, 4.0), radius_b, 150.0, 8.0),
            fx.plane("cap-lo", (0.0, 0.0, 1.0), (0.0, 0.0, 0.0), 28.0),
            fx.plane("cap-hi", (0.0, 0.0, 1.0), (0.0, 0.0, 8.0), 28.0),
        ]
    )


class SpecValidationTests(unittest.TestCase):
    def test_a_threshold_without_a_rationale_is_rejected(self) -> None:
        spec = fx.spec()
        spec["thresholds"]["frame_margin"] = {"value": 0.1}
        issues = rp.validate_program_spec(spec)
        self.assertIn("threshold-missing-rationale", [issue.code for issue in issues])

    def test_a_bare_number_is_rejected_as_a_module_constant_with_extra_steps(self) -> None:
        spec = fx.spec()
        spec["thresholds"]["offset_tolerance"] = 0.5
        issues = rp.validate_program_spec(spec)
        self.assertIn("threshold-must-be-declared", [issue.code for issue in issues])

    def test_an_unknown_threshold_is_rejected(self) -> None:
        spec = fx.spec()
        spec["thresholds"]["fudge_factor"] = {"value": 1.0, "rationale": "vibes"}
        issues = rp.validate_program_spec(spec)
        self.assertTrue(any(issue.path.endswith("fudge_factor") for issue in issues))

    def test_an_unknown_tolerance_basis_is_rejected(self) -> None:
        spec = fx.spec()
        spec["thresholds"]["tolerance_basis"] = "whatever-looks-right"
        issues = rp.validate_program_spec(spec)
        self.assertIn("program-spec-invalid-basis", [issue.code for issue in issues])

    def test_declared_absolute_needs_its_absolute_numbers(self) -> None:
        spec = fx.spec(basis="declared-absolute")
        del spec["thresholds"]["absolute_length_tolerance"]
        issues = rp.validate_program_spec(spec)
        self.assertTrue(any("absolute_length_tolerance" in issue.path for issue in issues))

    def test_adoption_without_a_rationale_is_rejected(self) -> None:
        spec = fx.spec(adopted=[adoption("coaxial", ["a", "b"], "constraint", "")])
        issues = rp.validate_program_spec(spec)
        self.assertTrue(any(issue.path.endswith("rationale") for issue in issues))

    def test_build_raises_on_an_invalid_spec(self) -> None:
        with self.assertRaises(ManifestValidationError):
            build(fx.box_record(), {"thresholds": {}, "adopted": []})


class LicensingTests(unittest.TestCase):
    def test_a_deviation_inside_three_sigma_is_licensed(self) -> None:
        program = build(two_bores(radius_b=3.008), fx.spec())
        equal = next(
            entry
            for entry in program["relationships"]["proposals"]
            if entry["kind"] == "equal_radius"
        )
        # sigma_radius 0.005 each -> combined 0.00707 -> 3 sigma = 0.0212
        self.assertEqual(equal["license"]["basis"], "uncertainty")
        self.assertAlmostEqual(equal["license"]["tolerance"], 3.0 * (0.005**2 * 2) ** 0.5)
        self.assertTrue(equal["license"]["licensed"])

    def test_a_deviation_outside_three_sigma_is_measured_and_not_licensed(self) -> None:
        program = build(two_bores(radius_b=3.1), fx.spec())
        equal = next(
            (
                entry
                for entry in program["relationships"]["proposals"]
                if entry["kind"] == "equal_radius"
            ),
            None,
        )
        # 0.1 apart is outside the screening window too, so it is not proposed;
        # what matters is that nothing adopted it.
        self.assertIsNone(equal)

    def test_uncertainty_basis_refuses_a_record_without_uncertainty(self) -> None:
        record = two_bores()
        for region in record["regions"]:
            region["fit"].pop("uncertainty")
        with self.assertRaises(ReconstructionRefused) as caught:
            build(record, fx.spec())
        self.assertEqual(caught.exception.reason, "fit-record-missing-uncertainty")

    def test_declared_absolute_basis_says_so_in_the_record(self) -> None:
        program = build(two_bores(radius_b=3.008), fx.spec(basis="declared-absolute"))
        equal = next(
            entry
            for entry in program["relationships"]["proposals"]
            if entry["kind"] == "equal_radius"
        )
        self.assertEqual(equal["license"]["basis"], "declared-absolute")
        self.assertEqual(equal["license"]["tolerance"], 0.05)

    def test_a_pair_with_no_uncertainty_model_is_unlicensable_not_licensed(self) -> None:
        judgement = rp.license_proposal(
            _fake_proposal("coaxial", ("a", "b"), 0.0, "deg"),
            {},
            basis="uncertainty",
            sigma_multiple=3.0,
            absolute_angle_tolerance_deg=1.0,
            absolute_length_tolerance=1.0,
        )
        self.assertFalse(judgement["licensed"])
        self.assertEqual(judgement["basis"], "unlicensable")


def _fake_proposal(kind, subjects, deviation, unit):
    from fusion_design.mesh_fitting import IntentProposal

    return IntentProposal(
        kind=kind,
        subjects=tuple(subjects),
        statement="synthetic",
        deviation=deviation,
        deviation_unit=unit,
    )


class AdoptionTests(unittest.TestCase):
    def test_an_unmeasured_relationship_cannot_be_adopted(self) -> None:
        spec = fx.spec(
            adopted=[adoption("coaxial", [fx.region_hash("bore-a"), fx.region_hash("cap-lo")], "constraint")]
        )
        with self.assertRaises(ReconstructionRefused) as caught:
            build(two_bores(), spec)
        self.assertEqual(caught.exception.reason, "adoption-unmeasured")

    def test_a_kind_that_cannot_be_re_solved_cannot_be_adopted_as_a_parameter(self) -> None:
        spec = fx.spec(
            adopted=[
                adoption(
                    "symmetric",
                    [fx.region_hash("bore-a"), fx.region_hash("bore-b")],
                    "parameter",
                )
            ]
        )
        with self.assertRaises(ReconstructionRefused) as caught:
            build(two_bores(), spec)
        self.assertEqual(caught.exception.reason, "adoption-unsupported-target")

    def test_an_unadopted_proposal_never_reaches_a_constraint_list(self) -> None:
        program = build(two_bores(radius_b=3.008), fx.spec())
        self.assertTrue(program["relationships"]["proposals"])
        self.assertEqual(program["relationships"]["adopted"], [])
        self.assertEqual(program["relationships"]["constraints"], [])
        for group in program["archetypes"]:
            self.assertEqual(group["constraints"], [])

    def test_an_adopted_constraint_carries_the_deviation_it_will_erase(self) -> None:
        subjects = sorted([fx.region_hash("boss"), fx.region_hash("cap-lo")])
        spec = fx.spec(adopted=[adoption("parallel", subjects, "constraint")])
        program = build(fx.turned_record(), spec)
        adopted = program["relationships"]["adopted"][0]
        self.assertEqual(adopted["target"], "constraint")
        self.assertEqual(adopted["deviation"], 0.0)
        self.assertIn("tolerance", adopted["license"])
        attached = [c for group in program["archetypes"] for c in group["constraints"]]
        self.assertTrue(attached)
        self.assertEqual(attached[0]["snapped_from"], 0.0)
        self.assertEqual(attached[0]["license_basis"], "uncertainty")


class ReconciliationTests(unittest.TestCase):
    def test_adopting_equal_radius_makes_the_radii_actually_equal(self) -> None:
        subjects = sorted([fx.region_hash("bore-a"), fx.region_hash("bore-b")])
        spec = fx.spec(adopted=[adoption("equal_radius", subjects, "parameter")])
        program = build(two_bores(radius_b=3.008), spec)
        shifts = program["relationships"]["reconciliation"]
        radii = {entry["region_hash"]: entry["after"] for entry in shifts}
        self.assertEqual(len(set(radii.values())), 1)
        self.assertAlmostEqual(list(radii.values())[0], 3.004)
        for entry in shifts:
            self.assertAlmostEqual(entry["shift"], 0.004)
            self.assertGreater(entry["tolerance"], entry["shift"])

    def test_a_shift_beyond_the_licence_refuses_rather_than_averaging_it_away(self) -> None:
        # A chain a=b, b=c whose ends are further apart than either link.
        # Each link is inside the 3-sigma licence (0.0212 mm); the ends are not.
        record = fx.record(
            [
                fx.cylinder("bore-a", (0.0, 0.0, 1.0), (0.0, 0.0, 4.0), 3.000, 150.0, 8.0),
                fx.cylinder("bore-b", (0.0, 0.0, 1.0), (9.0, 0.0, 4.0), 3.020, 150.0, 8.0),
                fx.cylinder("bore-c", (0.0, 0.0, 1.0), (18.0, 0.0, 4.0), 3.040, 150.0, 8.0),
                fx.cylinder("bore-d", (0.0, 0.0, 1.0), (27.0, 0.0, 4.0), 3.060, 150.0, 8.0),
                fx.plane("cap-lo", (0.0, 0.0, 1.0), (0.0, 0.0, 0.0), 28.0),
                fx.plane("cap-hi", (0.0, 0.0, 1.0), (0.0, 0.0, 8.0), 28.0),
            ]
        )
        spec = fx.spec(
            adopted=[
                adoption(
                    "equal_radius",
                    sorted([fx.region_hash(f"bore-{a}"), fx.region_hash(f"bore-{b}")]),
                    "parameter",
                )
                for a, b in (("a", "b"), ("b", "c"), ("c", "d"))
            ]
        )
        with self.assertRaises(ReconstructionRefused) as caught:
            build(record, spec)
        self.assertEqual(caught.exception.reason, "adoption-shift-exceeds-license")

    def test_adopting_coaxial_puts_both_axes_on_one_line(self) -> None:
        record = fx.record(
            [
                fx.cylinder("upper", (0.0, 0.0, 1.0), (0.0, 0.0, 6.0), 3.0, 150.0, 8.0),
                fx.cylinder("lower", (0.0, 0.0, 1.0), (0.004, 0.0, 1.0), 2.0, 90.0, 4.0),
                fx.plane("cap-lo", (0.0, 0.0, 1.0), (0.0, 0.0, 0.0), 28.0),
                fx.plane("flat", (1.0, 0.0, 0.0), (3.0, 0.0, 4.0), 12.0),
            ]
        )
        subjects = sorted([fx.region_hash("upper"), fx.region_hash("lower")])
        spec = fx.spec(adopted=[adoption("coaxial", subjects, "parameter")])
        program = build(record, spec)
        moved = [
            entry
            for entry in program["relationships"]["reconciliation"]
            if entry["parameter"] == "axis_point"
        ]
        self.assertEqual(len(moved), 2)
        xs = {round(entry["after"][0], 12) for entry in moved}
        self.assertEqual(len(xs), 1)

    def test_the_reconciliation_scope_states_what_it_did_not_do(self) -> None:
        program = build(two_bores(), fx.spec())
        scope = program["relationships"]["reconciliation_scope"]
        self.assertIn("not a re-solve against the region point sets", scope)


class ArchetypeTests(unittest.TestCase):
    def test_a_box_becomes_one_sketch_extrude_covering_every_region(self) -> None:
        program = build(fx.box_record(), fx.spec())
        self.assertEqual([g["kind"] for g in program["archetypes"]], ["sketch-extrude"])
        group = program["archetypes"][0]
        self.assertEqual(len(group["regions"]), 6)
        self.assertEqual(group["operation"], "new-body")
        # A 10 x 20 x 5 box is a legal prism in all three directions, so which
        # one it plans as is a *rule* rather than a measurement, and the rule is
        # the datum frame: the caps are the pair perpendicular to the primary
        # axis, and the extrude runs along the axis every other archetype in the
        # program is already expressed against. Under the old rule this was the
        # box's longest dimension, which is a fact about its bounding box.
        self.assertEqual(group["plane"]["datum_plane"], "XY")
        self.assertEqual("datum-primary-axis", group["cap_selection"]["rule"])
        self.assertAlmostEqual(group["extent"]["value"], 5.0)
        self.assertEqual(program["covered_area_fraction"], 1.0)
        self.assertEqual(program["unreconstructed"], [])

    def test_a_turned_part_becomes_a_revolve_and_declares_what_it_left_out(self) -> None:
        program = build(fx.turned_record(), fx.spec())
        self.assertEqual([g["kind"] for g in program["archetypes"]], ["revolve"])
        group = program["archetypes"][0]
        self.assertEqual(group["axis"], {"datum_axis": "Z", "angle_deg": 360.0})
        self.assertEqual(group["plane"]["datum_plane"], "XZ")
        self.assertLess(program["covered_area_fraction"], 1.0)
        left_out = program["unreconstructed"]
        self.assertEqual(len(left_out), 1)
        self.assertEqual(left_out[0]["region_id"], fx.region_hash("flat"))
        self.assertIn("bounding_box", left_out[0])
        self.assertTrue(left_out[0]["gate"])
        self.assertAlmostEqual(
            sum(entry["area_fraction"] for entry in left_out) + program["covered_area_fraction"],
            1.0,
        )

    def test_the_revolve_carries_the_motion_evidence_that_licensed_it(self) -> None:
        # A revolve is no longer won on precedence alone. It is won on the
        # group's own facet normals being invariant under one rotation about
        # this very axis, and the program carries the router's record so a
        # reviewer can see the spectrum the decision came off.
        group = build(fx.turned_record(), fx.spec())["archetypes"][0]
        evidence = group["motion_evidence"]
        self.assertTrue(evidence["confirmed"], evidence)
        self.assertEqual("motion-revolution-confirmed", evidence["reason"])
        self.assertEqual("revolution", evidence["router"]["verdict"])
        self.assertGreater(evidence["router"]["eigengap"], 0.005)
        self.assertLessEqual(evidence["axis_tilt_deg"], 2.0)
        self.assertLessEqual(evidence["axis_offset"], 0.5)

    def test_without_a_declared_motion_gate_no_revolve_is_claimed(self) -> None:
        # A revolve asserts that a whole group is swept by one rotation. The
        # caller who declared no gate to judge that against has not licensed the
        # assertion, and the program says so on the archetype that took the
        # regions instead rather than quietly falling back to precedence.
        spec = fx.spec()
        del spec["thresholds"]["motion_evidence"]
        program = build(fx.turned_record(), spec)
        self.assertEqual(["sketch-extrude"], [g["kind"] for g in program["archetypes"]])
        evidence = program["archetypes"][0]["motion_evidence"]
        self.assertFalse(evidence["confirmed"])
        self.assertEqual("motion-evidence-undeclared", evidence["reason"])
        self.assertIsNone(evidence["router"])

    def test_a_record_carrying_no_facet_moments_names_the_absence(self) -> None:
        # An older fit record has no moment block, and a missing measurement is
        # not a failed one: the refusal names what is absent and how to get it.
        record = fx.turned_record()
        for region in record["regions"]:
            region.pop("motion_moments")
        program = build(record, fx.spec())
        self.assertNotIn("revolve", [g["kind"] for g in program["archetypes"]])
        evidence = program["archetypes"][0]["motion_evidence"]
        self.assertEqual("motion-evidence-unavailable", evidence["reason"])
        self.assertIn("re-run `fit-regions`", evidence["detail"])
        self.assertEqual(3, len(evidence["regions_without_moments"]))

    def test_a_partly_declared_motion_gate_is_refused_rather_than_completed(self) -> None:
        spec = fx.spec()
        del spec["thresholds"]["motion_evidence"]["eigengap_min"]
        issues = rp.validate_program_spec(spec)
        self.assertIn(
            "program_spec.thresholds.motion_evidence.eigengap_min",
            [issue.path for issue in issues],
        )

    def test_a_rejected_fit_is_listed_with_the_gate_it_failed(self) -> None:
        record = fx.box_record()
        # The rejected wall is a *y* wall, not an *x* one, and that is not
        # incidental. The box is 10 x 20 x 5, so its two x walls carry 100 each
        # and its two y walls 50 each; the datum's X axis is now chosen by the
        # total area facing a direction rather than by one face's area, and
        # dropping an x wall would leave 100 against 100 -- a real tie, which
        # the frame refuses. Dropping a y wall leaves 200 against 50 and the
        # frame is as determined as it was with all six.
        rejected = next(r for r in record["regions"] if r["region_hash"] == fx.region_hash("y-lo"))
        rejected["fit"]["accepted"] = False
        rejected["fit"]["rejection"] = "relative residual 0.4 exceeds the gate 0.02."
        program = build(record, fx.spec())
        gates = [entry["gate"] for entry in program["unreconstructed"]]
        self.assertIn("relative residual 0.4 exceeds the gate 0.02.", gates)

    def test_an_oblique_cap_plane_is_unmappable_rather_than_emitted(self) -> None:
        # Caps at 30 degrees to every datum axis: setByPlane is direct-edit-only,
        # so this plane cannot be asked for at all.
        #
        # `x-flat` carries more area than the *pair* of oblique faces together,
        # which is what keeps the datum's X axis on +x. The frame now scores a
        # direction by the total area facing it, so two 60 mm2 oblique faces
        # would otherwise outweigh one 100 mm2 flat and the datum would rotate
        # to meet them -- leaving nothing oblique for this gate to catch.
        #
        # The oblique pair is the *only* parallel pair here, and that is what
        # this gate now needs: the caps follow the datum primary axis whenever a
        # pair lies on it, so a body with a z pair would take that and never
        # reach an oblique plane at all. One z face and no second one is a body
        # whose only two parallel faces are the oblique cut, which is exactly the
        # shape this refusal exists for.
        sqrt2 = 2.0**0.5
        oblique = (1.0 / sqrt2, 1.0 / sqrt2, 0.0)
        record = fx.record(
            [
                fx.plane("z-lo", (0.0, 0.0, 1.0), (0.0, 0.0, 0.0), 200.0),
                fx.plane("x-flat", (1.0, 0.0, 0.0), (5.0, 0.0, 2.5), 150.0),
                fx.plane("cut-lo", oblique, (0.0, 0.0, 2.5), 60.0),
                fx.plane("cut-hi", oblique, (7.0, 7.0, 2.5), 60.0),
            ]
        )
        program = build(record, fx.spec())
        gates = " ".join(entry["gate"] for entry in program["unreconstructed"])
        self.assertIn("plane-unmappable", gates)
        self.assertNotIn(
            fx.region_hash("cut-lo"),
            [h for group in program["archetypes"] for h in group["regions"]],
        )


class HoleAndFilletTests(unittest.TestCase):
    """The U6 gap: `hole` and `fillet` were in the vocabulary and never assigned."""

    def test_an_inward_cylinder_becomes_a_hole_that_cuts_the_body_it_lies_in(self) -> None:
        program = build(fx.bored_post_record("inside"), fx.spec())
        kinds = [g["kind"] for g in program["archetypes"]]
        self.assertEqual(["sketch-extrude", "hole"], kinds)
        base, hole = program["archetypes"]
        self.assertEqual("cut", hole["operation"])
        self.assertEqual([base["id"]], hole["dependencies"])
        # Bases before cuts: the hole can only cut a body that exists.
        self.assertEqual([base["id"], hole["id"]], program["order"])
        self.assertAlmostEqual(4.0, hole["hole"]["diameter"]["value"])
        self.assertAlmostEqual(30.0, hole["extent"]["value"])
        self.assertEqual(1.0, program["covered_area_fraction"])
        self.assertIn("material_side", hole["reason"])

    def test_a_hole_is_driven_by_a_diameter_a_depth_and_two_positions(self) -> None:
        program = build(fx.bored_post_record("inside"), fx.spec())
        by_name = {row["name"]: row for row in program["user_parameters"]}
        self.assertLessEqual(
            {"recon_hole_1_dia", "recon_hole_1_depth", "recon_hole_1_x", "recon_hole_1_y"},
            set(by_name),
        )
        # A position parameter can move a hole across a face without changing
        # the volume at all, so the proof must watch the centroid instead.
        self.assertEqual("centroid", by_name["recon_hole_1_x"]["expected_observable"])
        self.assertEqual("volume", by_name["recon_hole_1_dia"]["expected_observable"])

    def test_an_unknown_material_side_is_never_guessed_into_a_hole(self) -> None:
        program = build(fx.bored_post_record(None), fx.spec())
        self.assertNotIn("hole", [g["kind"] for g in program["archetypes"]])

    def test_an_outward_cylinder_is_a_boss_and_never_a_hole(self) -> None:
        program = build(fx.bored_post_record("outside"), fx.spec())
        self.assertNotIn("hole", [g["kind"] for g in program["archetypes"]])

    def test_an_unclaimed_cylinder_of_unknown_side_names_that_as_its_gate(self) -> None:
        # The gate that must never round down to "no archetype fits this". The
        # bore-or-boss question is open, and saying which question is open is
        # what stops the next reader from closing it by eye.
        # Axis along Y: neither coaxial with the primary axis nor perpendicular
        # to the extrude's cap normal, so nothing claims it and the gate is all
        # the reader gets.
        regions = list(fx.bored_post_record(None)["regions"])
        cross = fx.cylinder("cross", (0.0, 1.0, 0.0), (6.0, 4.0, 20.0), 1.5, 90.0, 12.0)
        cross["bounding_box"] = [[4.5, 0.0, 18.5], [7.5, 10.0, 21.5]]
        regions.append(fx.oriented(cross, None))
        program = build(fx.record(regions), fx.spec())
        gates = " ".join(entry["gate"] for entry in program["unreconstructed"])
        self.assertIn("material-side-unavailable", gates)
        self.assertIn("bore", gates)
        self.assertIn("not closed and consistently wound", gates)

    def test_a_bore_whose_axis_is_oblique_to_its_body_is_gated_by_name(self) -> None:
        regions = list(fx.bored_post_record("inside")["regions"])
        cross = fx.cylinder("cross", (1.0, 0.0, 0.0), (6.0, 4.0, 20.0), 1.5, 90.0, 12.0)
        cross["bounding_box"] = [[0.0, 2.5, 18.5], [12.0, 5.5, 21.5]]
        regions.append(fx.oriented(cross, "inside"))
        program = build(fx.record(regions), fx.spec())
        gates = " ".join(entry["gate"] for entry in program["unreconstructed"])
        self.assertIn("hole-axis-oblique", gates)

    def test_a_bore_reaching_outside_the_body_it_would_cut_is_gated(self) -> None:
        record = fx.bored_post_record("inside")
        bore = next(r for r in record["regions"] if r["region_hash"] == fx.region_hash("bore"))
        bore["bounding_box"] = [[2.0, 2.0, -40.0], [6.0, 6.0, 30.0]]
        program = build(record, fx.spec())
        gates = " ".join(entry["gate"] for entry in program["unreconstructed"])
        self.assertIn("hole-not-contained", gates)

    def test_a_body_whose_only_turned_surface_is_a_bore_is_not_a_revolve(self) -> None:
        # Revolving a bore's own profile builds a disc where a plate belongs.
        # Neither side evidence makes this post a revolve, and the two get there
        # by different routes, so the test names both. Known-inside: a bore is
        # not an outward turned surface. Unknown: the side is still not the
        # discriminator -- "unknown" is not "inward", exactly as before -- and
        # what stops the revolve is the post's own shape. Its z faces are 12 x 10
        # rectangles whose box centres sit 2.2 mm off the bore's axis against a
        # declared 0.5: planes perpendicular to the axis, not annuli about it.
        inside = build(fx.bored_post_record("inside"), fx.spec())
        unknown = build(fx.bored_post_record(None), fx.spec())
        self.assertNotIn("revolve", [g["kind"] for g in inside["archetypes"]])
        self.assertNotIn("revolve", [g["kind"] for g in unknown["archetypes"]])
        # The side evidence still decides the hole, which is what it is for: a
        # bore whose side the record states is cut out of the body, and one it
        # does not is left in the extrude's section as an ordinary wall rather
        # than cut on a guess.
        self.assertIn("hole", [g["kind"] for g in inside["archetypes"]])
        self.assertNotIn("hole", [g["kind"] for g in unknown["archetypes"]])
        owner = {h: g for g in unknown["archetypes"] for h in g["regions"]}
        self.assertEqual("sketch-extrude", owner[fx.region_hash("bore")]["kind"])

    def test_a_torus_between_two_rebuilt_features_becomes_a_fillet(self) -> None:
        blend = fx.torus("blend", 5.0, 1.0, 40.0, between=["bore", "z-lo"])
        program = build(fx.bored_post_record("inside", extras=[blend]), fx.spec())
        fillets = [g for g in program["archetypes"] if g["kind"] == "fillet"]
        self.assertEqual(1, len(fillets))
        fillet = fillets[0]
        self.assertEqual("finish", fillet["operation"])
        self.assertAlmostEqual(1.0, fillet["radius"]["value"])
        self.assertEqual(2, len(fillet["between"]))
        self.assertEqual(sorted(fillet["between"]), sorted(fillet["dependencies"]))
        # Fillets are finishing features and are ordered after everything they
        # round, so the edge exists by the time the radius is applied.
        self.assertEqual(fillet["id"], program["order"][-1])
        self.assertEqual(
            "recon_fillet_1_radius", program["archetypes"][-1]["radius"]["parameter"]
        )

    def test_a_partial_arc_cylinder_between_two_features_is_also_a_fillet(self) -> None:
        # The shape a face-grouped mesh actually delivers an edge round as. This
        # gate wanted a torus, so across the 11 benchmark parts all 114 of U2's
        # proposals died here and no fillet was ever emitted.
        blend = fx.oriented(
            fx.blend_cylinder(
                "blend", (1.0, 0.0, 0.0), (6.0, 4.0, 2.0), 1.0, 40.0, between=["bore", "z-lo"]
            ),
            None,
        )
        program = build(fx.bored_post_record("inside", extras=[blend]), fx.spec())
        fillets = [g for g in program["archetypes"] if g["kind"] == "fillet"]
        self.assertEqual(1, len(fillets), program["unreconstructed"])
        self.assertAlmostEqual(1.0, fillets[0]["radius"]["value"])
        self.assertEqual(2, len(set(fillets[0]["between"])))
        self.assertEqual(fillets[0]["id"], program["order"][-1])

    def test_a_blend_another_archetype_already_rebuilds_is_not_filleted_too(self) -> None:
        # A partial-arc cylinder can be claimed where a torus never could -- here
        # as a side of the extrude, whose section profile runs through the round
        # already. Rounding it a second time would put the same area in two
        # archetypes and report more of the scan covered than there is.
        blend = fx.oriented(
            fx.blend_cylinder(
                "blend", (0.0, 0.0, 1.0), (11.0, 9.0, 15.0), 1.0, 40.0, between=["bore", "z-lo"]
            ),
            None,
        )
        program = build(fx.bored_post_record("inside", extras=[blend]), fx.spec())
        claimed = [
            g["id"] for g in program["archetypes"] if fx.region_hash("blend") in g["regions"]
        ]
        self.assertEqual(1, len(claimed), program["archetypes"])
        self.assertNotIn("fillet", [g["kind"] for g in program["archetypes"]])
        self.assertAlmostEqual(
            program["covered_area_fraction"],
            sum(g["area_fraction"] for g in program["archetypes"]),
        )

    def _blend(self, label, between, radius=1.0, area=40.0, y=4.0, axis=(1.0, 0.0, 0.0), chain=None):
        # The axis must not be parallel to the extrude's cap normal or the round
        # is claimed as one of its sides and never reaches the fillet gate at all.
        #
        # `chain` names the edge: fragments of one round share it. Two fragments
        # with no chain in common are two rounds on two edges, which is what a
        # lone fragment gets by default.
        return fx.oriented(
            fx.blend_cylinder(
                label, axis, (6.0, y, 2.0), radius, area, between=between, chain=chain
            ),
            None,
        )

    def test_a_blend_between_two_sides_of_one_extrude_is_a_fillet_on_that_edge(self) -> None:
        # 42 of the benchmark's 114 candidates died on this: a box's own edge
        # runs between two faces of one feature, and Fusion rounds it.
        program = build(
            fx.bored_post_record("inside", extras=[self._blend("blend", ["x-lo", "y-lo"])]),
            fx.spec(),
        )
        fillets = [g for g in program["archetypes"] if g["kind"] == "fillet"]
        self.assertEqual(1, len(fillets), program["unreconstructed"])
        self.assertEqual(1, len(fillets[0]["between"]))
        self.assertEqual("side-side", fillets[0]["edge_faces"])
        self.assertEqual(fillets[0]["between"], fillets[0]["dependencies"])

    def test_a_blend_on_a_cap_names_which_cap_so_the_emitter_can_pick_the_face_set(self) -> None:
        # z-hi is the far cap in station order, which is the feature's endFaces.
        program = build(
            fx.bored_post_record("inside", extras=[self._blend("blend", ["z-hi", "x-lo"])]),
            fx.spec(),
        )
        fillets = [g for g in program["archetypes"] if g["kind"] == "fillet"]
        self.assertEqual(1, len(fillets), program["unreconstructed"])
        self.assertEqual("end-side", fillets[0]["edge_faces"])

    def test_a_blend_between_two_caps_of_one_extrude_has_no_edge_to_round(self) -> None:
        program = build(
            fx.bored_post_record("inside", extras=[self._blend("blend", ["z-lo", "z-hi"])]),
            fx.spec(),
        )
        self.assertNotIn("fillet", [g["kind"] for g in program["archetypes"]])
        gates = " ".join(entry["gate"] for entry in program["unreconstructed"])
        self.assertIn("fillet-neighbour-shared", gates)
        self.assertIn("face away from each other", gates)

    def test_a_blend_inside_a_revolve_still_refuses_and_says_why(self) -> None:
        # A revolve's faces come as one collection with no partition, so an edge
        # inside it cannot be named. The refusal is the honest answer.
        #
        # The body has to be a *real* revolve for the refusal to be about the
        # partition rather than about the archetype: the turned post's caps are
        # discs centred on the boss's own axis and its facets are invariant under
        # one rotation about it, so the revolve is earned. The blend runs between
        # the boss and the top cap, two surfaces of that one feature.
        blend = fx.oriented(
            fx.blend_cylinder(
                "blend", (1.0, 0.0, 0.0), (3.0, 0.0, 8.0), 1.0, 20.0, between=["boss", "cap-hi"]
            ),
            None,
        )
        record = fx.turned_record()
        record["regions"].append(blend)
        record["total_area"] = sum(region["area"] for region in record["regions"])
        program = build(record, fx.spec())
        owner = {h: g for g in program["archetypes"] for h in g["regions"]}
        self.assertEqual("revolve", owner[fx.region_hash("boss")]["kind"])
        self.assertEqual(
            owner[fx.region_hash("boss")]["id"], owner[fx.region_hash("cap-hi")]["id"]
        )
        self.assertNotIn("fillet", [g["kind"] for g in program["archetypes"]])
        gates = " ".join(entry["gate"] for entry in program["unreconstructed"])
        self.assertIn("cannot partition into named sets", gates)

    def test_two_fragments_of_one_round_become_one_fillet_over_both_regions(self) -> None:
        # One edge, cut into two groups by the face grouping: U2 chained them, so
        # they name one chain and pool into one fillet.
        extras = [
            self._blend("left", ["x-lo", "y-lo"], radius=1.0, area=40.0, chain="round"),
            self._blend("right", ["x-lo", "y-lo"], radius=1.02, area=20.0, y=6.0, chain="round"),
        ]
        program = build(fx.bored_post_record("inside", extras=extras), fx.spec())
        fillets = [g for g in program["archetypes"] if g["kind"] == "fillet"]
        self.assertEqual(1, len(fillets), program["unreconstructed"])
        self.assertEqual(
            sorted([fx.region_hash("left"), fx.region_hash("right")]), fillets[0]["regions"]
        )
        # The larger fragment's own measured radius, not a mean of the two: a
        # mean is a number no fit ever produced.
        self.assertAlmostEqual(1.0, fillets[0]["radius"]["value"])

    def test_fragments_whose_radii_disagree_refuse_rather_than_pick_one(self) -> None:
        # Disagreement *within one edge*: both fragments name the same chain and
        # measured different rounds, which is the case this gate is for. Two
        # radii on two different edges are two fillets, not a disagreement.
        extras = [
            self._blend("left", ["x-lo", "y-lo"], radius=1.0, area=40.0, chain="round"),
            self._blend("right", ["x-lo", "y-lo"], radius=3.0, area=20.0, y=6.0, chain="round"),
        ]
        program = build(fx.bored_post_record("inside", extras=extras), fx.spec())
        self.assertNotIn("fillet", [g["kind"] for g in program["archetypes"]])
        gates = " ".join(entry["gate"] for entry in program["unreconstructed"])
        self.assertIn("fillet-radius-disagrees", gates)

    def test_pooling_fragments_needs_a_declared_equal_radius_tolerance(self) -> None:
        # No tolerance declared is *not judged*, never "judged with a default".
        spec = fx.spec()
        spec["thresholds"].pop("equal_radius_tolerance")
        extras = [
            self._blend("left", ["x-lo", "y-lo"], radius=1.0, area=40.0, chain="round"),
            self._blend("right", ["x-lo", "y-lo"], radius=1.02, area=20.0, y=6.0, chain="round"),
        ]
        program = build(fx.bored_post_record("inside", extras=extras), spec)
        self.assertNotIn("fillet", [g["kind"] for g in program["archetypes"]])
        gates = " ".join(entry["gate"] for entry in program["unreconstructed"])
        self.assertIn("fillet-radius-undeclared", gates)

    def test_a_blend_whose_neighbours_were_not_both_rebuilt_is_not_a_fillet(self) -> None:
        # A fillet rounds the edge between two features. Nothing here rebuilt
        # the second neighbour, so there is no edge to round.
        blend = fx.torus("blend", 5.0, 1.0, 40.0, between=["bore", "nowhere"])
        program = build(fx.bored_post_record("inside", extras=[blend]), fx.spec())
        self.assertNotIn("fillet", [g["kind"] for g in program["archetypes"]])
        gates = " ".join(entry["gate"] for entry in program["unreconstructed"])
        self.assertIn("fillet-neighbour-unreconstructed", gates)

    def test_a_blend_inside_one_feature_is_not_an_edge_between_two(self) -> None:
        blend = fx.torus("blend", 5.0, 1.0, 40.0, between=["z-lo", "z-hi"])
        program = build(fx.bored_post_record("inside", extras=[blend]), fx.spec())
        self.assertNotIn("fillet", [g["kind"] for g in program["archetypes"]])
        gates = " ".join(entry["gate"] for entry in program["unreconstructed"])
        self.assertIn("fillet-neighbour-shared", gates)

    def test_every_archetype_carries_the_share_of_the_scan_it_accounts_for(self) -> None:
        program = build(fx.bored_post_record("inside"), fx.spec())
        total = sum(g["area_fraction"] for g in program["archetypes"])
        self.assertAlmostEqual(program["covered_area_fraction"], total)


class UserParameterTests(unittest.TestCase):
    def test_every_parameter_declares_the_observable_that_should_move(self) -> None:
        program = build(fx.box_record(), fx.spec())
        self.assertTrue(program["user_parameters"])
        for parameter in program["user_parameters"]:
            self.assertIn(parameter["expected_observable"], rp.OBSERVABLES)
            self.assertTrue(parameter["observable_rationale"].strip())
            self.assertTrue(parameter["rationale"].strip())
            self.assertEqual(parameter["unit"], "mm")
        group = program["archetypes"][0]
        self.assertEqual(group["extent"]["parameter"], program["user_parameters"][0]["name"])

    def test_an_adopted_equal_radius_produces_one_shared_parameter(self) -> None:
        subjects = sorted([fx.region_hash("bore-a"), fx.region_hash("bore-b")])
        spec = fx.spec(adopted=[adoption("equal_radius", subjects, "parameter")])
        program = build(two_bores(radius_b=3.008), spec)
        shared = [p for p in program["user_parameters"] if p["name"].startswith("recon_shared")]
        self.assertEqual(len(shared), 1)
        self.assertEqual(shared[0]["quantity"], "radius")


class ProgramShapeTests(unittest.TestCase):
    def test_the_program_is_deterministic_and_hash_bound(self) -> None:
        record = fx.turned_record()
        first = build(record, fx.spec())
        rng = random.Random(7)
        shuffled = copy.deepcopy(record)
        rng.shuffle(shuffled["regions"])
        second = build(shuffled, fx.spec())
        self.assertEqual(first, second)
        self.assertEqual(first["dump_sha256"], fx.DUMP_SHA256)
        self.assertEqual(first["manifest_sha256"], MANIFEST_SHA)
        self.assertEqual(first["program_sha256"], rp.program_sha256(first))
        self.assertEqual(first["units"], "mm")

    def test_the_program_is_json_serialisable_data_only(self) -> None:
        program = build(fx.turned_record(), fx.spec())
        self.assertEqual(json.loads(json.dumps(program)), program)

    def test_the_order_is_a_total_order_over_the_archetype_ids(self) -> None:
        program = build(fx.box_record(), fx.spec())
        self.assertEqual(program["order"], [group["id"] for group in program["archetypes"]])

    def test_a_null_profile_is_explained_rather_than_left_absent(self) -> None:
        program = build(fx.box_record(), fx.spec())
        self.assertIsNone(program["archetypes"][0]["profile"])
        self.assertIn("cannot produce one", program["profile_note"])


class ProgramValidatorTests(unittest.TestCase):
    def _valid(self):
        return build(fx.box_record(), fx.spec())

    def _check(self, program):
        return rp.check_reconstruction_program(
            program, dump_sha256=fx.DUMP_SHA256, manifest_sha256=MANIFEST_SHA
        )

    def test_a_well_formed_program_passes_every_check(self) -> None:
        result = self._check(self._valid())
        self.assertEqual(result["issues"], ())
        self.assertEqual(
            result["checked"], ("program-version", "closed-vocabulary", "hash-binding", "coverage")
        )

    def test_an_unknown_program_version_is_refused(self) -> None:
        program = self._valid()
        program["program_version"] = 2
        codes = [issue.code for issue in self._check(program)["issues"]]
        self.assertIn("program-version-unsupported", codes)

    def test_an_unknown_key_is_refused_by_path(self) -> None:
        program = self._valid()
        program["extra_instructions"] = "run this"
        issues = self._check(program)["issues"]
        self.assertTrue(any(issue.path == "program.extra_instructions" for issue in issues))

    def test_an_out_of_set_archetype_is_refused(self) -> None:
        program = self._valid()
        program["archetypes"][0]["kind"] = "loft"
        codes = [issue.code for issue in self._check(program)["issues"]]
        self.assertIn("program-value-out-of-set", codes)

    def test_an_out_of_set_observable_is_refused(self) -> None:
        program = self._valid()
        program["user_parameters"][0]["expected_observable"] = "vibes"
        codes = [issue.code for issue in self._check(program)["issues"]]
        self.assertIn("program-value-out-of-set", codes)

    def test_a_program_edited_after_it_was_built_fails_its_own_hash(self) -> None:
        program = self._valid()
        program["covered_area_fraction"] = 0.5
        codes = [issue.code for issue in self._check(program)["issues"]]
        self.assertIn("program-hash-mismatch", codes)

    def test_a_mesh_that_moved_under_the_plan_is_refused(self) -> None:
        result = rp.check_reconstruction_program(
            self._valid(), dump_sha256="c" * 64, manifest_sha256=MANIFEST_SHA
        )
        paths = [issue.path for issue in result["issues"]]
        self.assertIn("program.dump_sha256", paths)

    def test_the_checked_list_omits_a_check_that_raised(self) -> None:
        """R12's enforcing test: `checked` is built by the code that ran the checks.

        Not by review discipline — this stubs a raising check and asserts its
        name is absent, so an entry appended before its check could never pass.
        """

        def explode(program, dump, manifest):
            raise RuntimeError("the check itself failed")

        original = rp.PROGRAM_CHECKS
        rp.PROGRAM_CHECKS = (
            ("program-version", rp._check_version),
            ("closed-vocabulary", explode),
            ("hash-binding", rp._check_hash_binding),
        )
        try:
            with self.assertRaises(RuntimeError):
                self._check(self._valid())
        finally:
            rp.PROGRAM_CHECKS = original

        # And the ordinary path still reports the checks that did run.
        recorded: list[str] = []

        def observing(program, dump, manifest):
            recorded.append("ran")
            return [ValidationIssue("noted", "program", "observed")]

        rp.PROGRAM_CHECKS = (("closed-vocabulary", observing),)
        try:
            result = self._check(self._valid())
        finally:
            rp.PROGRAM_CHECKS = original
        self.assertEqual(recorded, ["ran"])
        self.assertEqual(result["checked"], ("closed-vocabulary",))


if __name__ == "__main__":
    unittest.main()
