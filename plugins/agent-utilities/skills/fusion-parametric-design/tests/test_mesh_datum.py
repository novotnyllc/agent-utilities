from __future__ import annotations

import copy
import random
import unittest

from fusion_design.mesh_datum import (
    DATUM_REFUSALS,
    REFUSAL_ALTERNATIVES,
    ReconstructionRefused,
    derive_datum_frame,
    parse_fit_record,
    require_uncertainty,
)

import fixtures_fit_record as fx


FRAME_ARGS = dict(frame_margin=0.1, angle_tolerance_deg=2.0, offset_tolerance=0.5)


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

    def test_extra_upstream_keys_are_ignored_not_refused(self) -> None:
        record = fx.box_record()
        record["segmentation"] = {"source": "crease-growing"}
        record["regions"][0]["triangle_count"] = 812
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

    def test_two_equally_good_perpendicular_cylinders_refuse_rather_than_pick(self) -> None:
        record = fx.record(
            [
                fx.cylinder("a", (0.0, 0.0, 1.0), (0.0, 0.0, 4.0), 3.0, 150.0, 8.0),
                fx.cylinder("b", (1.0, 0.0, 0.0), (4.0, 0.0, 0.0), 3.0, 150.0, 8.0),
                fx.plane("cap", (0.0, 0.0, 1.0), (0.0, 0.0, 0.0), 28.0),
            ]
        )
        with self.assertRaises(ReconstructionRefused) as caught:
            derive_datum_frame(_regions(record), **FRAME_ARGS)
        self.assertEqual(caught.exception.reason, "frame-ambiguous")
        self.assertEqual(caught.exception.detail["margin"], 0.0)
        self.assertIn("winner", caught.exception.detail)
        self.assertIn("runner_up", caught.exception.detail)

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
