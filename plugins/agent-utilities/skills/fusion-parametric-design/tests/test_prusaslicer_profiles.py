from __future__ import annotations

import unittest

from fusion_design.prusaslicer_profiles import (
    normalize_print_filament_profiles,
    normalize_printer_models,
)


class ProfilesTests(unittest.TestCase):
    def test_rejects_whitespace_only_identifiers(self):
        with self.assertRaises(ValueError):
            normalize_printer_models(
                {"printer_models": [{"id": " ", "name": "Printer", "variants": []}]}
            )

    def test_normalizes_system_and_user_printer_profiles_without_changing_names(self):
        result = normalize_printer_models(
            {
                "printer_models": [
                    {
                        "id": "XL5IS",
                        "name": "Original Prusa XL",
                        "vendor_name": "Prusa Research",
                        "vendor_id": "PrusaResearch",
                        "variants": [
                            {
                                "name": "HF0.4",
                                "printer_profiles": [
                                    {
                                        "name": "System XL HF0.4",
                                        "extruders_cnt": 5,
                                        "bed": {"width": 360, "height": 360},
                                    }
                                ],
                                "user_printer_profiles": [
                                    {
                                        "name": "User XL HF0.4",
                                        "extruders_cnt": 5,
                                        "bed": {"width": 360, "height": 360},
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        )
        self.assertEqual({"System XL HF0.4", "User XL HF0.4"}, set(result["printer_profiles"]))
        self.assertEqual("system", result["printer_profiles"]["System XL HF0.4"]["source"])
        self.assertEqual("user", result["printer_profiles"]["User XL HF0.4"]["source"])
        self.assertEqual("XL5IS", result["printer_profiles"]["System XL HF0.4"]["model"])
        self.assertEqual("HF0.4", result["printer_profiles"]["System XL HF0.4"]["variant"])

    def test_normalizes_print_and_filament_compatibility_verbatim(self):
        result = normalize_print_filament_profiles(
            {
                "printer_profile": "User XL HF0.4",
                "print_profiles": [
                    {
                        "name": "0.20mm SPEED @XLIS HF0.4",
                        "filament_profiles": ["Prusament PETG @XL HF0.4"],
                        "user_filament_profiles": ["Custom PETG"],
                    }
                ],
            }
        )
        self.assertEqual("User XL HF0.4", result["printer_profile"])
        self.assertEqual(
            ["Prusament PETG @XL HF0.4", "Custom PETG"],
            result["compatibility"]["0.20mm SPEED @XLIS HF0.4"]["filament_profiles"],
        )
        self.assertEqual(
            ["Custom PETG"],
            result["compatibility"]["0.20mm SPEED @XLIS HF0.4"]["user_filament_profiles"],
        )

    def test_rejects_malformed_shapes(self):
        with self.assertRaises(ValueError):
            normalize_printer_models({})
        with self.assertRaises(ValueError):
            normalize_print_filament_profiles({"printer_profile": "P", "print_profiles": [{}]})

    def test_rejects_non_finite_bed_dimensions(self):
        payload = {
            "printer_models": [
                {
                    "id": "P",
                    "name": "Printer",
                    "variants": [
                        {
                            "name": 0.25,
                            "printer_profiles": [
                                {"name": "P0.25", "extruders_cnt": 1, "bed": {"width": float("nan"), "height": 200}}
                            ],
                        }
                    ],
                }
            ]
        }
        with self.assertRaises(ValueError):
            normalize_printer_models(payload)

    def test_rejects_whitespace_only_filament_ids(self):
        with self.assertRaises(ValueError):
            normalize_print_filament_profiles(
                {
                    "printer_profile": "P",
                    "print_profiles": [{"name": "Q", "filament_profiles": ["   "]}],
                }
            )


if __name__ == "__main__":
    unittest.main()
