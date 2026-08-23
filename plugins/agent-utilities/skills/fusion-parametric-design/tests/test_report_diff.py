from __future__ import annotations

import json
from pathlib import Path
import re
import unittest

from fusion_design.export_handoff import emit_export_example_script
from fusion_design.manifest import load_manifest
from fusion_design.report_diff import BOUNDS_TOLERANCE_MM, diff_reports


EXAMPLE = (
    Path(__file__).resolve().parents[1] / "examples" / "electronics-enclosure" / "fusion-project.json"
)


class ReportDiffTests(unittest.TestCase):
    def test_diff_reports_surfaces_parameter_and_component_changes(self) -> None:
        before = {
            "parameters": {"fab_wall_thickness": {"expression": "2 mm"}},
            "component_paths": ["Product/Base"],
            "geometry": {
                "Product/Base": {
                    "solid_body_count": 1,
                    "total_solid_volume_mm3": 100.0,
                    "has_positive_solid": True,
                }
            },
            "timeline": {"unhealthy": [{"index": 2, "health_state": "warning"}]},
        }
        after = {
            "parameters": {"fab_wall_thickness": {"expression": "2.4 mm"}},
            "component_paths": ["Product/Base", "Product/Lid"],
            "geometry": {
                "Product/Base": {
                    "solid_body_count": 1,
                    "total_solid_volume_mm3": 102.5,
                    "has_positive_solid": True,
                },
                "Product/Lid": {
                    "solid_body_count": 1,
                    "total_solid_volume_mm3": 45.0,
                    "has_positive_solid": True,
                },
            },
            "timeline": {
                "unhealthy": [
                    {"index": 2, "health_state": "warning"},
                    {"index": 7, "health_state": "error"},
                ]
            },
        }
        result = diff_reports(before, after)
        self.assertEqual(
            {
                "before": {"expression": "2 mm"},
                "after": {"expression": "2.4 mm"},
            },
            result["parameters_changed"]["fab_wall_thickness"],
        )
        self.assertEqual(["Product/Lid"], result["components_added"])
        self.assertEqual(
            {
                "before": {
                    "solid_body_count": 1,
                    "total_solid_volume_mm3": 100.0,
                    "has_positive_solid": True,
                },
                "after": {
                    "solid_body_count": 1,
                    "total_solid_volume_mm3": 102.5,
                    "has_positive_solid": True,
                },
            },
            result["geometry_changed"]["Product/Base"],
        )
        self.assertEqual(["Product/Lid"], result["geometry_added"])
        self.assertEqual(
            [{"index": 7, "health_state": "error"}],
            result["timeline_unhealthy_added"],
        )

    def test_diff_reports_preserves_unit_and_comment_only_parameter_changes(self) -> None:
        before = {"parameters": {"src_width": {"expression": "10 mm", "units": "mm", "comment": "draft"}}}
        after = {"parameters": {"src_width": {"expression": "10 mm", "units": "cm", "comment": "verified"}}}

        result = diff_reports(before, after)

        self.assertEqual(
            {"before": before["parameters"]["src_width"], "after": after["parameters"]["src_width"]},
            result["parameters_changed"]["src_width"],
        )


    def test_diff_reports_surfaces_a_verification_regression(self) -> None:
        before = {
            "kind": "verification",
            "ok": True,
            "failures": [],
            "clearance_results": [
                {"id": "pd-to-lid-clearance", "distance_mm": 2.0, "ok": True},
            ],
            "interference_results": [{"id": "usb-c-insertion-zone", "count": 0, "ok": True}],
            "brep_bounding_boxes_mm": {
                "Product/Base": {"min": [0.0, 0.0, 0.0], "max": [100.0, 60.0, 20.0]}
            },
        }
        after = {
            "kind": "verification",
            "ok": False,
            "failures": ["clearance", "interference"],
            "clearance_results": [
                {"id": "pd-to-lid-clearance", "distance_mm": 0.2, "ok": False},
            ],
            "interference_results": [
                {"id": "usb-c-insertion-zone", "count": 1, "total_interference_volume_mm3": 42.0, "ok": False}
            ],
            "brep_bounding_boxes_mm": {
                "Product/Base": {"min": [50.0, 0.0, 0.0], "max": [150.0, 60.0, 20.0]}
            },
        }

        result = diff_reports(before, after)

        self.assertTrue(result["ok_before"])
        self.assertFalse(result["ok_after"])
        self.assertEqual(["clearance", "interference"], result["failures_added"])
        self.assertEqual([], result["failures_removed"])
        self.assertEqual(0.2, result["clearance_changed"]["pd-to-lid-clearance"]["after"]["distance_mm"])
        self.assertEqual(1, result["interference_changed"]["usb-c-insertion-zone"]["after"]["count"])
        self.assertIn("Product/Base", result["bounds_changed"])

    def test_diff_reports_sees_a_rigid_move_that_preserves_volume(self) -> None:
        geometry = {"solid_body_count": 1, "total_solid_volume_mm3": 100.0, "has_positive_solid": True}
        before = {
            "kind": "inventory",
            "component_paths": ["Product/Base"],
            "geometry": {"Product/Base": geometry},
            "brep_bounding_boxes_mm": {
                "Product/Base": {"min": [0.0, 0.0, 0.0], "max": [10.0, 10.0, 10.0]}
            },
        }
        after = json.loads(json.dumps(before))
        after["brep_bounding_boxes_mm"]["Product/Base"] = {
            "min": [100.0, 0.0, 0.0],
            "max": [110.0, 10.0, 10.0],
        }

        result = diff_reports(before, after)

        self.assertEqual({}, result["geometry_changed"])
        self.assertEqual(
            {"min": [100.0, 0.0, 0.0], "max": [110.0, 10.0, 10.0]},
            result["bounds_changed"]["Product/Base"]["after"],
        )

    def test_diff_reports_ignores_float_noise_below_the_bounds_tolerance(self) -> None:
        before = {
            "brep_bounding_boxes_mm": {"a": {"min": [0.0, 0.0, 0.0], "max": [10.0, 10.0, 10.0]}}
        }
        after = {
            "brep_bounding_boxes_mm": {
                "a": {"min": [0.0, 0.0, 1e-12], "max": [10.0, 10.0, 10.0000000001]}
            }
        }

        self.assertEqual({}, diff_reports(before, after)["bounds_changed"])

    def test_bounds_tolerance_matches_the_export_staleness_gate(self) -> None:
        # Two constants for one question is one too many: both compare
        # independent Fusion measurements of a body that did not move.
        script = emit_export_example_script(load_manifest(EXAMPLE))
        gate = re.search(r"EXPORT_STALENESS_TOLERANCE_MM = (\S+)", script)
        self.assertIsNotNone(gate)
        self.assertEqual(float(gate.group(1)), BOUNDS_TOLERANCE_MM)

    def test_diff_reports_compares_bounds_error_records_verbatim(self) -> None:
        before = {"brep_bounding_boxes_mm": {"a": {"error": "no bounding box"}}}
        after = {"brep_bounding_boxes_mm": {"a": {"min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, 1.0]}}}

        self.assertIn("a", diff_reports(before, after)["bounds_changed"])


if __name__ == "__main__":
    unittest.main()
