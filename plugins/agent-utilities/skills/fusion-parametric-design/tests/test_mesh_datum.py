from __future__ import annotations

import copy
import math
import random
import unittest

from fusion_design.mesh_datum import (
    DATUM_REFUSALS,
    FRAME_CHOICES,
    REFUSAL_ALTERNATIVES,
    ReconstructionRefused,
    derive_datum_frame,
    parse_fit_record,
    require_uncertainty,
)

import fixtures_fit_record as fx


FRAME_ARGS = dict(frame_margin=0.1, angle_tolerance_deg=2.0, offset_tolerance=0.5)


def _walled_lid(x_walls, y_walls):
    """A lid: one boss on +z, plus wall planes facing +x and +y.

    Shaped after POD-A1-LID, whose primary axis was never in doubt and whose X
    axis was decided between two walls of 95.40 mm2 and 94.80 mm2 -- a margin of
    0.0063 -- while the stacks those two walls belong to measured 1008.4 mm2
    against 189.6 mm2.
    """
    regions = [
        fx.cylinder("boss", (0.0, 0.0, 1.0), (0.0, 0.0, 4.0), 3.0, 150.0, 8.0),
        fx.plane("cap", (0.0, 0.0, 1.0), (0.0, 0.0, 0.0), 900.0),
    ]
    for index, area in enumerate(x_walls):
        regions.append(fx.plane(f"x{index}", (1.0, 0.0, 0.0), (float(index), 0.0, 4.0), area))
    for index, area in enumerate(y_walls):
        regions.append(fx.plane(f"y{index}", (0.0, 1.0, 0.0), (0.0, float(index), 4.0), area))
    return fx.record(regions)


def _tied_lid():
    """The square lid: two wall stacks of identical area, a dead tie on X."""
    return _walled_lid([95.4, 95.4], [95.4, 95.4])


def _regions(record):
    return list(parse_fit_record(record).regions)


class ParseFitRecordTests(unittest.TestCase):
    def test_reads_the_fields_this_stage_needs(self) -> None:
        record = parse_fit_record(fx.turned_record())
        self.assertEqual(record.dump_sha256, fx.DUMP_SHA256)
        self.assertEqual(record.units, "mm")
        self.assertEqual(len(record.regions), 4)
        boss = next(r for r in record.regions if r.region_hash == fx.region_hash("boss"))
        self.assertEqual(boss.axial_span, 8.0)
        self.assertEqual(boss.sigma("radius"), 0.005)

    def test_reads_the_material_side_that_tells_a_bore_from_a_boss(self) -> None:
        record = fx.turned_record()
        fx.oriented(record["regions"][0], "inside")
        boss = next(
            r
            for r in parse_fit_record(record).regions
            if r.region_hash == fx.region_hash("boss")
        )
        self.assertEqual(boss.material_side, "inside")
        self.assertIsNone(boss.orientation_gate)

    def test_an_absent_orientation_block_fails_closed_with_a_named_reason(self) -> None:
        # An older fit record simply has no orientation block. That is not
        # malformed -- but it must never read as "outside" or as any answer at
        # all, because the consumer decides bore-versus-boss on this field.
        boss = next(
            r
            for r in parse_fit_record(fx.turned_record()).regions
            if r.region_hash == fx.region_hash("boss")
        )
        self.assertIsNone(boss.material_side)
        self.assertIn("no orientation block", boss.orientation_gate)

    def test_an_open_mesh_carries_u2s_own_reason_for_the_absence(self) -> None:
        record = fx.turned_record()
        fx.oriented(record["regions"][0], None)
        boss = next(
            r
            for r in parse_fit_record(record).regions
            if r.region_hash == fx.region_hash("boss")
        )
        self.assertIsNone(boss.material_side)
        self.assertIn("not closed and consistently wound", boss.orientation_gate)

    def test_a_material_side_outside_the_vocabulary_refuses(self) -> None:
        record = fx.turned_record()
        record["regions"][0]["orientation"] = {"material_side": "left"}
        with self.assertRaises(ReconstructionRefused) as caught:
            parse_fit_record(record)
        self.assertEqual(caught.exception.reason, "fit-record-malformed")
        self.assertIn("material_side", caught.exception.message)

    def test_a_fillet_flag_with_no_evidence_refuses_rather_than_reading_as_a_fillet(self) -> None:
        record = fx.turned_record()
        record["regions"][0]["fillet_candidate"] = True
        with self.assertRaises(ReconstructionRefused) as caught:
            parse_fit_record(record)
        self.assertIn("fillet", caught.exception.message)

    def test_a_fillet_between_other_than_two_regions_refuses(self) -> None:
        record = fx.record(
            [
                fx.plane("z-lo", (0.0, 0.0, 1.0), (0.0, 0.0, 0.0), 200.0),
                fx.torus("blend", 5.0, 1.0, 30.0, between=["z-lo"]),
            ]
        )
        record["regions"][1]["fillet"]["between"] = [fx.region_hash("z-lo")]
        with self.assertRaises(ReconstructionRefused) as caught:
            parse_fit_record(record)
        self.assertIn("exactly two region hashes", caught.exception.message)

    def test_extra_upstream_keys_are_ignored_not_refused(self) -> None:
        record = fx.box_record()
        record["segmentation"] = {"source": "crease-growing"}
        # Not `triangle_count` any more: the moment block is bound to it, so it
        # is read rather than ignored.
        record["regions"][0]["point_count"] = 812
        self.assertEqual(len(parse_fit_record(record).regions), 6)

    def test_missing_units_refuses_rather_than_assuming_millimetres(self) -> None:
        record = fx.box_record()
        del record["units"]
        with self.assertRaises(ReconstructionRefused) as caught:
            parse_fit_record(record)
        self.assertEqual(caught.exception.reason, "fit-record-malformed")
        self.assertIn("units", caught.exception.message)

    def test_a_tampered_dump_hash_is_refused(self) -> None:
        record = fx.box_record()
        record["dump_sha256"] = "not-a-hash"
        with self.assertRaises(ReconstructionRefused):
            parse_fit_record(record)

    def test_duplicate_region_hashes_are_refused(self) -> None:
        record = fx.box_record()
        record["regions"][1]["region_hash"] = record["regions"][0]["region_hash"]
        with self.assertRaises(ReconstructionRefused):
            parse_fit_record(record)

    def test_a_rejected_fit_may_carry_infinite_residuals(self) -> None:
        record = fx.box_record()
        record["regions"][0]["fit"]["accepted"] = False
        record["regions"][0]["fit"]["rms_residual"] = float("inf")
        record["regions"][0]["fit"]["relative_residual"] = float("inf")
        record["regions"][0]["fit"]["rejection"] = "relative residual exceeds the gate."
        regions = _regions(record)
        self.assertFalse(regions[0].accepted)

    def test_an_accepted_fit_may_not(self) -> None:
        record = fx.box_record()
        record["regions"][0]["fit"]["rms_residual"] = float("inf")
        with self.assertRaises(ReconstructionRefused):
            parse_fit_record(record)

    def test_a_moment_block_that_does_not_describe_its_region_is_refused(self) -> None:
        """Shape validation alone accepted every one of these.

        The block is *summed* into a group's motion evidence and nothing
        downstream re-derives it, so a block whose numbers came from somewhere
        else silently changes which archetypes get emitted. Two numbers the
        region already carries catch all of it.
        """
        fabrications = {
            "matrix scaled by 1e6": lambda b, o: b.update(
                matrix=[value * 1e06 for value in b["matrix"]]
            ),
            "a zero block": lambda b, o: b.update(matrix=[0.0] * 21),
            "a centroid a kilometre away": lambda b, o: b.update(
                centroid_sum=[value + 1e06 for value in b["centroid_sum"]]
            ),
            "another region's block copied over": lambda b, o: b.update(o),
            "another region's facet count": lambda b, o: b.update(facet_count=b["facet_count"] + 1),
            "another region's area": lambda b, o: b.update(area=b["area"] * 2.0),
        }
        for name, fabricate in fabrications.items():
            with self.subTest(fabrication=name):
                record = fx.box_record()
                # regions[0] is a 100 mm^2 x face, regions[4] a 200 mm^2 z face.
                fabricate(record["regions"][0]["motion_moments"], record["regions"][4]["motion_moments"])
                with self.assertRaises(ReconstructionRefused) as caught:
                    parse_fit_record(record)
                self.assertEqual(caught.exception.reason, "fit-record-moments-unbound")

    def test_a_block_whose_region_states_no_triangle_count_cannot_be_bound(self) -> None:
        record = fx.box_record()
        del record["regions"][0]["triangle_count"]
        with self.assertRaises(ReconstructionRefused) as caught:
            parse_fit_record(record)
        self.assertEqual(caught.exception.reason, "fit-record-malformed")
        self.assertIn("triangle_count", caught.exception.message)

    def test_a_record_with_no_moment_block_at_all_still_parses(self) -> None:
        """Absent stays absent: an older record carries none and says so."""
        record = fx.box_record()
        for region in record["regions"]:
            region.pop("motion_moments")
            region.pop("triangle_count")
        self.assertTrue(all(r.motion_moments is None for r in parse_fit_record(record).regions))


class UncertaintyTests(unittest.TestCase):
    def test_a_missing_sigma_refuses_instead_of_reading_as_zero(self) -> None:
        record = fx.box_record()
        del record["regions"][2]["fit"]["uncertainty"]["offset"]
        with self.assertRaises(ReconstructionRefused) as caught:
            require_uncertainty(_regions(record))
        self.assertEqual(caught.exception.reason, "fit-record-missing-uncertainty")
        self.assertIn("offset", caught.exception.message)

    def test_every_refusal_names_an_alternative(self) -> None:
        for reason in DATUM_REFUSALS:
            self.assertTrue(REFUSAL_ALTERNATIVES.get(reason, "").strip(), reason)

    def test_every_frame_choice_a_frame_can_carry_is_in_the_closed_set(self) -> None:
        # `frame_choice` is read to decide whether the datum is a measurement or
        # a convention, so a token outside the vocabulary would be read as
        # neither. Both paths are exercised here rather than the set restated.
        seen = set()
        for record in (fx.box_record(), _tied_lid()):
            evidence = derive_datum_frame(_regions(record), **FRAME_ARGS).evidence
            seen.add(evidence["frame_choice"])
            for axis in ("primary", "secondary"):
                seen.add(evidence[f"{axis}_choice"]["basis"])
        self.assertEqual(FRAME_CHOICES, seen)


class DatumFrameTests(unittest.TestCase):
    def test_a_cylinder_beats_planes_and_sets_the_primary_axis(self) -> None:
        frame = derive_datum_frame(_regions(fx.turned_record()), **FRAME_ARGS)
        self.assertEqual(frame.z_axis, (0.0, 0.0, 1.0))
        self.assertEqual(frame.evidence["primary_source"], "cylinder")
        self.assertEqual(frame.evidence["primary"]["score"], 24.0)
        # radius 3 x span 8

    def test_the_origin_sits_where_the_axis_meets_the_lowest_perpendicular_plane(self) -> None:
        frame = derive_datum_frame(_regions(fx.turned_record()), **FRAME_ARGS)
        self.assertEqual(frame.origin, (0.0, 0.0, 0.0))
        self.assertIn(fx.region_hash("cap-lo")[:12], frame.evidence["origin_source"])

    def test_the_frame_is_right_handed(self) -> None:
        frame = derive_datum_frame(_regions(fx.turned_record()), **FRAME_ARGS)
        cross = (
            frame.x_axis[1] * frame.y_axis[2] - frame.x_axis[2] * frame.y_axis[1],
            frame.x_axis[2] * frame.y_axis[0] - frame.x_axis[0] * frame.y_axis[2],
            frame.x_axis[0] * frame.y_axis[1] - frame.x_axis[1] * frame.y_axis[0],
        )
        for a, b in zip(cross, frame.z_axis):
            self.assertAlmostEqual(a, b, places=12)

    def test_planes_rank_by_area_when_no_cylinder_is_accepted(self) -> None:
        frame = derive_datum_frame(_regions(fx.box_record()), **FRAME_ARGS)
        self.assertEqual(frame.evidence["primary_source"], "plane")
        self.assertEqual(frame.z_axis, (0.0, 0.0, 1.0))
        self.assertEqual(frame.x_axis, (1.0, 0.0, 0.0))
        self.assertEqual(frame.origin, (5.0, 10.0, 0.0))

    def test_the_frame_is_identical_under_shuffled_region_order(self) -> None:
        record = fx.turned_record()
        reference = derive_datum_frame(_regions(record), **FRAME_ARGS).to_dict()
        rng = random.Random(20260819)
        for _ in range(12):
            shuffled = copy.deepcopy(record)
            rng.shuffle(shuffled["regions"])
            self.assertEqual(derive_datum_frame(_regions(shuffled), **FRAME_ARGS).to_dict(), reference)

    def _crossed_cylinders(self, uncertainty=None):
        """Two cylinders of identical score at right angles: a dead score tie."""
        return fx.record(
            [
                fx.cylinder(
                    "a", (0.0, 0.0, 1.0), (0.0, 0.0, 4.0), 3.0, 150.0, 8.0, uncertainty=uncertainty
                ),
                fx.cylinder(
                    "b", (1.0, 0.0, 0.0), (4.0, 0.0, 0.0), 3.0, 150.0, 8.0, uncertainty=uncertainty
                ),
                fx.plane("cap", (0.0, 0.0, 1.0), (0.0, 0.0, 0.0), 28.0),
            ]
        )

    def test_two_equally_good_perpendicular_cylinders_pick_canonically(self) -> None:
        # The scores are equal to the last bit, so no evidence separates them.
        # A reconstruction does not need the designer's axis, only a
        # reproducible one -- so the tie is settled on the quantized canonical
        # directions and *labelled* as the convention it is.
        frame = derive_datum_frame(_regions(self._crossed_cylinders()), **FRAME_ARGS)
        choice = frame.evidence["primary_choice"]
        self.assertEqual(frame.evidence["frame_choice"], "arbitrary-canonical")
        self.assertEqual(choice["basis"], "arbitrary-canonical")
        self.assertEqual(frame.evidence["primary_margin"], 0.0)
        self.assertEqual(choice["quantization_grid_deg"], 2.0)
        self.assertEqual(2, len(choice["tied"]))
        self.assertEqual({24.0}, {entry["score"] for entry in choice["tied"]})  # radius 3 x span 8
        # (0,0,1) and (1,0,0) quantize to (0,0,29) and (29,0,0); the smaller
        # cell is the first, so Z is the +z cylinder's axis.
        self.assertEqual(frame.z_axis, (0.0, 0.0, 1.0))
        self.assertEqual([0, 0, 29], choice["canonical_cell"])

    def test_a_tie_the_uncertainties_cannot_resolve_still_refuses(self) -> None:
        # The boundary the refusal still protects: directions known only to a
        # sigma that reaches the quantization grid could quantize either way on
        # a re-tessellation, so no canonical rule over them is reproducible.
        record = self._crossed_cylinders(
            uncertainty=dict(fx.CYLINDER_SIGMAS, axis_direction_deg=1.0)
        )
        with self.assertRaises(ReconstructionRefused) as caught:
            derive_datum_frame(_regions(record), **FRAME_ARGS)
        self.assertEqual(caught.exception.reason, "frame-ambiguous")
        self.assertEqual(caught.exception.detail["margin"], 0.0)
        self.assertEqual(caught.exception.detail["quantization_grid_deg"], 2.0)
        self.assertIn("winner", caught.exception.detail)
        self.assertIn("runner_up", caught.exception.detail)
        self.assertEqual(2, len(caught.exception.detail["tied"]))

    def test_two_tied_candidates_in_one_cell_refuse_rather_than_falling_back_to_score(self) -> None:
        # A cell spans the tolerance angle's *chord* in each component, so two
        # directions further apart than the tolerance can still share one. The
        # sort would then decide on `sort_key`, whose first element is the score
        # -- the number a re-tessellation moves, and the whole reason this rule
        # replaced the score comparison. Same answer as an unstable cell.
        # 2.0097 deg apart on a 2 deg grid, and both in cell (0, 0, 29).
        tilt = 0.0124
        norm = math.sqrt(1.0 + 2.0 * tilt * tilt)
        record = fx.record(
            [
                fx.cylinder(
                    "a", (tilt / norm, tilt / norm, 1.0 / norm), (0.0, 0.0, 4.0), 3.0, 150.0, 8.0
                ),
                fx.cylinder(
                    "b", (-tilt / norm, -tilt / norm, 1.0 / norm), (4.0, 0.0, 0.0), 3.0, 150.0, 8.0
                ),
                fx.plane("cap", (0.0, 0.0, 1.0), (0.0, 0.0, 0.0), 28.0),
            ]
        )
        with self.assertRaises(ReconstructionRefused) as caught:
            derive_datum_frame(_regions(record), **FRAME_ARGS)
        self.assertEqual(caught.exception.reason, "frame-ambiguous")
        self.assertIn("same 2 deg cell", caught.exception.message)
        cells = [entry["canonical_cell"] for entry in caught.exception.detail["tied"]]
        self.assertEqual([[0, 0, 29], [0, 0, 29]], cells)

    def test_the_secondary_sigma_carries_the_primary_axis_uncertainty_too(self) -> None:
        # A secondary direction is a plane normal orthogonalised against the
        # measured primary axis, so the plane's own sigma is a lower bound on
        # it. `_canonical_cell` reads whatever it is handed as the whole bound,
        # so the two measured sigmas are combined before it sees them -- and
        # when the record states no sigma for the primary axis there is no
        # combined bound to hand it, which is the refusal's own case.
        record = _tied_lid()
        frame = derive_datum_frame(_regions(record), **FRAME_ARGS)
        tied = frame.evidence["secondary_choice"]["tied"]
        self.assertEqual({"propagated"}, {entry["direction_sigma_basis"] for entry in tied})
        # hypot(0.05 plane normal, 0.05 cylinder axis).
        for entry in tied:
            self.assertAlmostEqual(math.hypot(0.05, 0.05), entry["direction_sigma_deg"], places=12)

        blind = _tied_lid()
        for region in blind["regions"]:
            if region["fit"]["kind"] == "cylinder":
                del region["fit"]["uncertainty"]["axis_direction_deg"]
        with self.assertRaises(ReconstructionRefused) as caught:
            derive_datum_frame(_regions(blind), **FRAME_ARGS)
        self.assertEqual(caught.exception.reason, "frame-ambiguous")
        self.assertEqual(caught.exception.detail["axis"], "secondary")

    def test_the_canonical_choice_is_identical_under_shuffled_region_order(self) -> None:
        record = self._crossed_cylinders()
        reference = derive_datum_frame(_regions(record), **FRAME_ARGS).to_dict()
        self.assertEqual(reference["evidence"]["frame_choice"], "arbitrary-canonical")
        rng = random.Random(20260819)
        for _ in range(12):
            shuffled = copy.deepcopy(record)
            rng.shuffle(shuffled["regions"])
            self.assertEqual(
                derive_datum_frame(_regions(shuffled), **FRAME_ARGS).to_dict(), reference
            )

    def test_parallel_walls_pool_their_area_so_the_bigger_stack_sets_x(self) -> None:
        # Face for face the contest is a coin toss: 95.4 against 94.8. Stack for
        # stack it is not close, and the stack is the quantity that survives a
        # re-tessellation, which is what the margin is protecting.
        record = _walled_lid([94.8, 47.4, 47.4], [95.4, 95.4, 95.4, 95.4])
        frame = derive_datum_frame(_regions(record), **FRAME_ARGS)
        self.assertEqual(frame.z_axis, (0.0, 0.0, 1.0))
        self.assertEqual(frame.x_axis, (0.0, 1.0, 0.0))
        self.assertAlmostEqual(381.6, frame.evidence["secondary"]["score"], places=6)
        self.assertIn("summed over 4 parallel fits", frame.evidence["secondary"]["basis"])
        # (381.6 - 189.6) / 381.6, against a face-for-face margin of 0.0063.
        self.assertAlmostEqual(0.50314465, frame.evidence["secondary_margin"], places=6)

    def test_a_lid_whose_wall_stacks_really_do_tie_is_settled_canonically(self) -> None:
        # Pooling parallel evidence must not turn a square box into a *decided*
        # one -- and it does not: the tie is recorded as a tie, and what changes
        # is that the frame is still built, from a stated convention.
        record = _tied_lid()
        frame = derive_datum_frame(_regions(record), **FRAME_ARGS)
        choice = frame.evidence["secondary_choice"]
        self.assertEqual(frame.evidence["frame_choice"], "arbitrary-canonical")
        self.assertEqual(choice["axis"], "secondary")
        self.assertEqual(choice["basis"], "arbitrary-canonical")
        self.assertEqual(frame.evidence["secondary_margin"], 0.0)
        self.assertEqual(frame.evidence["primary_choice"]["basis"], "evidence")
        self.assertEqual(2, len(choice["tied"]))
        # The primary axis is measured; only the rotation about it is convention.
        self.assertEqual(frame.z_axis, (0.0, 0.0, 1.0))
        # (0,1,0) quantizes to (0,29,0) against the +x stack's (29,0,0).
        self.assertEqual(frame.x_axis, (0.0, 1.0, 0.0))

    def test_a_pooled_stack_carries_its_members_spread_not_just_the_biggest_one(self) -> None:
        """Which member represents a merged stack rests on areas, and areas move.

        `_merge_parallel` keeps the largest single member as the group's
        direction, so a re-tessellation that swaps which member is largest moves
        the merged direction -- by up to the group's own angular spread, even
        though every member sits safely inside its own cell. The merged
        candidate's stated sigma has to cover that, or the tie-break certifies a
        cell the next run can leave.
        """
        record = _walled_lid([95.4, 95.4], [95.4, 95.4])
        # Tilt one wall of the +x stack inside the tolerance: still the same
        # direction by the module's own rule, and still a real spread. Kept
        # small enough that the merged cell is stable -- what is under test is
        # that the spread reaches the sigma, not that it refuses.
        tilt = 0.2
        radians = math.radians(tilt)
        for region in record["regions"]:
            if region["region_hash"] == fx.region_hash("x1"):
                region["fit"]["parameters"]["normal"] = [math.cos(radians), math.sin(radians), 0.0]
        frame = derive_datum_frame(_regions(record), **FRAME_ARGS)
        pooled = [
            entry
            for entry in frame.evidence["secondary_choice"]["tied"]
            if "summed over" in entry["basis"]
        ]
        self.assertTrue(pooled, frame.evidence["secondary_choice"]["tied"])
        for entry in pooled:
            self.assertEqual("propagated", entry["direction_sigma_basis"])
        # Each member already carries hypot(0.05 plane, 0.05 primary axis); the
        # tilted stack's 0.2 deg spread dominates that and has to be in the
        # number, or the representative could change and the cell with it. The
        # untilted stack keeps the member sigma, which is the control.
        member = math.hypot(0.05, 0.05)
        sigmas = sorted(entry["direction_sigma_deg"] for entry in pooled)
        self.assertAlmostEqual(member, sigmas[0], places=9)
        self.assertAlmostEqual(math.hypot(member, tilt), sigmas[-1], places=9)

    def test_a_pooled_member_with_no_sigma_leaves_the_stack_with_none(self) -> None:
        # One member nobody measured makes the whole merged direction
        # unmeasured: the representative could become that member.
        record = _tied_lid()
        for region in record["regions"]:
            if region["region_hash"] == fx.region_hash("x1"):
                del region["fit"]["uncertainty"]["normal_deg"]
        with self.assertRaises(ReconstructionRefused) as caught:
            derive_datum_frame(_regions(record), **FRAME_ARGS)
        self.assertEqual(caught.exception.reason, "frame-ambiguous")
        self.assertEqual(caught.exception.detail["axis"], "secondary")

    def test_a_tied_lid_whose_walls_are_too_uncertain_still_refuses(self) -> None:
        record = _tied_lid()
        for region in record["regions"]:
            if region["fit"]["kind"] == "plane":
                region["fit"]["uncertainty"]["normal_deg"] = 1.5
        with self.assertRaises(ReconstructionRefused) as caught:
            derive_datum_frame(_regions(record), **FRAME_ARGS)
        self.assertEqual(caught.exception.reason, "frame-ambiguous")
        self.assertEqual(caught.exception.detail["axis"], "secondary")
        self.assertEqual(caught.exception.detail["margin"], 0.0)

    def test_pooling_leaves_the_frame_identical_under_shuffled_region_order(self) -> None:
        record = _walled_lid([94.8, 47.4, 47.4], [95.4, 95.4, 95.4, 95.4])
        reference = derive_datum_frame(_regions(record), **FRAME_ARGS).to_dict()
        rng = random.Random(20260819)
        for _ in range(12):
            shuffled = copy.deepcopy(record)
            rng.shuffle(shuffled["regions"])
            self.assertEqual(
                derive_datum_frame(_regions(shuffled), **FRAME_ARGS).to_dict(), reference
            )

    def test_a_second_axis_carries_its_own_anchor_key_and_the_primary_s_lever_arm(self) -> None:
        # Two propagations, both first-order, both from numbers the record
        # states. A cone's positional sigma lives under `apex`, not
        # `axis_point`, so reading one key for both kinds gave every cone no
        # sigma at all -- which reads as "carries none" and refuses a tie the
        # record could settle. And the direction *to* an axis is produced by
        # projecting out the primary axis, so tilting that axis by delta turns
        # this direction by about `axial / radial * delta`: an anchor 4 mm up
        # the axis and 9 mm out from it levers 0.05 deg into 0.0222.
        def as_cone(region):
            fit = region["fit"]
            fit["kind"] = "cone"
            parameters = fit["parameters"]
            parameters["apex"] = parameters.pop("axis_point")
            parameters["half_angle_deg"] = 12.0
            parameters.pop("radius")
            fit["uncertainty"] = dict(fx.CONE_SIGMAS)
            fit.pop("support", None)
            region.pop("motion_moments", None)
            region.pop("triangle_count", None)
            return region

        record = fx.record(
            [
                fx.cylinder("boss", (0.0, 0.0, 1.0), (0.0, 0.0, 4.0), 3.0, 150.0, 8.0),
                as_cone(fx.cylinder("pin", (0.0, 0.0, 1.0), (9.0, 0.0, 4.0), 1.0, 40.0, 6.0)),
                fx.plane("cap", (0.0, 0.0, 1.0), (0.0, 0.0, 0.0), 28.0),
            ]
        )
        frame = derive_datum_frame(_regions(record), **FRAME_ARGS)
        secondary = frame.evidence["secondary"]
        self.assertEqual("cone", secondary["kind"])
        self.assertEqual("propagated", secondary["direction_sigma_basis"])
        # Three measured terms: the cone apex's own sigma over the 9 mm lever,
        # the origin's over the same lever -- the cap plane's offset sigma and
        # the primary cylinder's axis-point sigma, which place the two ends of
        # that origin -- and the primary axis's 0.05 deg tilt levered by the
        # anchor's 4 mm of axial offset over the same 9 mm.
        origin_sigma = math.hypot(0.01, 0.01)
        self.assertAlmostEqual(
            math.hypot(
                math.hypot(
                    math.degrees(math.atan2(0.01, 9.0)),
                    math.degrees(math.atan2(origin_sigma, 9.0)),
                ),
                0.05 * 4.0 / 9.0,
            ),
            secondary["direction_sigma_deg"],
            places=12,
        )

    def test_an_origin_that_is_only_a_plane_centroid_states_no_bound(self) -> None:
        """A plane's `offset` sigma is along its normal; the centroid slides.

        With no plane perpendicular to the primary axis the origin falls back
        to the largest plane's vertex centroid. Nothing in the record bounds
        where on that plane the centroid sits -- a re-tessellation moves it
        tangentially, and can swap which of two near-equal-area planes is
        picked at all -- so the origin states no uncertainty and the canonical
        tie over directions measured from it refuses rather than certifying a
        cell the origin can walk out of.
        """
        record = fx.record(
            [
                # The primary axis is a cylinder along +z; the only planes are
                # *parallel* to it, so no cap places the origin.
                fx.cylinder("boss", (0.0, 0.0, 1.0), (0.0, 0.0, 4.0), 3.0, 150.0, 8.0),
                fx.plane("wall", (1.0, 0.0, 0.0), (0.0, 0.0, 4.0), 900.0),
                fx.cylinder("pin-a", (0.0, 0.0, 1.0), (9.0, 0.0, 4.0), 1.0, 40.0, 6.0),
                fx.cylinder("pin-b", (0.0, 0.0, 1.0), (0.0, 9.0, 4.0), 1.0, 40.0, 6.0),
            ]
        )
        frame = derive_datum_frame(_regions(record), **FRAME_ARGS)
        self.assertIn("no plane is perpendicular", frame.evidence["origin_source"])
        # The secondary came from the wall, which carries its own bound; what
        # is under test is that a *second-axis* candidate measured from this
        # origin would carry none.
        self.assertEqual("plane parallel to the primary axis", frame.evidence["secondary_source"])

    def test_a_parallel_second_cylinder_is_not_a_rival(self) -> None:
        record = fx.record(
            [
                fx.cylinder("a", (0.0, 0.0, 1.0), (0.0, 0.0, 4.0), 3.0, 150.0, 8.0),
                fx.cylinder("b", (0.0, 0.0, 1.0), (9.0, 0.0, 4.0), 3.0, 150.0, 8.0),
                fx.plane("cap", (0.0, 0.0, 1.0), (0.0, 0.0, 0.0), 28.0),
            ]
        )
        frame = derive_datum_frame(_regions(record), **FRAME_ARGS)
        self.assertIsNone(frame.evidence["primary_runner_up"])
        # A bolt pattern gives X: the direction from the origin to the second axis.
        self.assertEqual(frame.x_axis, (1.0, 0.0, 0.0))
        self.assertEqual(frame.evidence["secondary_source"], "second axis off the primary axis")

    def test_rotation_about_the_axis_that_nothing_observes_refuses(self) -> None:
        record = fx.record(
            [
                fx.cylinder("boss", (0.0, 0.0, 1.0), (0.0, 0.0, 4.0), 3.0, 150.0, 8.0),
                fx.plane("cap", (0.0, 0.0, 1.0), (0.0, 0.0, 0.0), 28.0),
            ]
        )
        with self.assertRaises(ReconstructionRefused) as caught:
            derive_datum_frame(_regions(record), **FRAME_ARGS)
        self.assertEqual(caught.exception.reason, "frame-x-underdetermined")
        self.assertIn("not a substitute", caught.exception.message)

    def test_no_accepted_fit_refuses(self) -> None:
        record = fx.box_record()
        for region in record["regions"]:
            region["fit"]["accepted"] = False
            region["fit"]["rejection"] = "relative residual exceeds the gate."
        with self.assertRaises(ReconstructionRefused) as caught:
            derive_datum_frame(_regions(record), **FRAME_ARGS)
        self.assertEqual(caught.exception.reason, "frame-no-accepted-fits")

    def test_a_cylinder_without_its_axial_span_refuses_rather_than_scoring_zero(self) -> None:
        record = fx.turned_record()
        del record["regions"][0]["fit"]["support"]
        with self.assertRaises(ReconstructionRefused) as caught:
            derive_datum_frame(_regions(record), **FRAME_ARGS)
        self.assertEqual(caught.exception.reason, "fit-record-missing-axial-span")

    def test_thresholds_must_be_declared_positively(self) -> None:
        regions = _regions(fx.turned_record())
        for bad in ({"frame_margin": 0.0}, {"angle_tolerance_deg": -1.0}, {"offset_tolerance": None}):
            args = dict(FRAME_ARGS)
            args.update(bad)
            with self.assertRaises(ValueError):
                derive_datum_frame(regions, **args)


if __name__ == "__main__":
    unittest.main()
