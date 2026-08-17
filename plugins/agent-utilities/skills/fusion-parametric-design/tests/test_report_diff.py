from __future__ import annotations

import unittest

from fusion_design.report_diff import diff_reports


class ReportDiffTests(unittest.TestCase):
    def test_diff_reports_surfaces_parameter_and_component_changes(self) -> None:
        before = {
            "parameters": {"fab_wall_thickness": {"expression": "2 mm"}},
            "component_paths": ["10_PRODUCT/PROD__BASE"],
            "geometry": {
                "10_PRODUCT/PROD__BASE": {
                    "solid_body_count": 1,
                    "total_solid_volume_mm3": 100.0,
                    "has_positive_solid": True,
                }
            },
            "timeline": {"unhealthy": [{"index": 2, "health_state": "warning"}]},
        }
        after = {
            "parameters": {"fab_wall_thickness": {"expression": "2.4 mm"}},
            "component_paths": ["10_PRODUCT/PROD__BASE", "10_PRODUCT/PROD__LID"],
            "geometry": {
                "10_PRODUCT/PROD__BASE": {
                    "solid_body_count": 1,
                    "total_solid_volume_mm3": 102.5,
                    "has_positive_solid": True,
                },
                "10_PRODUCT/PROD__LID": {
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
        self.assertEqual(["10_PRODUCT/PROD__LID"], result["components_added"])
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
            result["geometry_changed"]["10_PRODUCT/PROD__BASE"],
        )
        self.assertEqual(["10_PRODUCT/PROD__LID"], result["geometry_added"])
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


if __name__ == "__main__":
    unittest.main()
