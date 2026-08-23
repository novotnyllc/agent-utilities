from __future__ import annotations

import unittest

from fusion_design.printable_parts import (
    PRINT_INTENT_OVERRIDE_KEYS,
    SEAM_POSITION_VALUES,
    SUPPORT_STYLE_OVERRIDE_KEY,
    SUPPORT_MATERIAL_STYLES,
    SUPPORT_MATERIAL_STYLE_TRANSLATIONS,
    validate_extended_override_value,
)


def _intent(**overrides):
    intent = {
        "support_policy": "everywhere",
        "print_intent": "fast-structural",
    }
    intent.update(overrides)
    return intent


class PrintIntentOverrideTests(unittest.TestCase):
    def test_every_extended_key_names_a_declared_field(self) -> None:
        self.assertEqual(
            {"speed", "layer_height", "seam_position", "brim_width"},
            set(PRINT_INTENT_OVERRIDE_KEYS),
        )
        for key, field in PRINT_INTENT_OVERRIDE_KEYS.items():
            with self.subTest(key=key):
                self.assertEqual("print_intent", field)

    def test_speed_requires_print_intent(self) -> None:
        validate_extended_override_value("speed", 120, "Widget/Part", _intent())

    def test_absent_intent_fails_closed_with_justifying_field(self) -> None:
        with self.assertRaisesRegex(ValueError, "print_intent"):
            validate_extended_override_value("layer_height", 0.2, "Widget/Part", {})

    def test_invalid_intent_value_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "print_intent"):
            validate_extended_override_value(
                "brim_width", 5, "Widget/Part", _intent(print_intent="tough")
            )

    def test_support_style_requires_support_bearing_policy(self) -> None:
        for policy in ("build-plate-only", "everywhere"):
            with self.subTest(policy=policy):
                validate_extended_override_value(
                    SUPPORT_STYLE_OVERRIDE_KEY,
                    "organic",
                    "Widget/Part",
                    _intent(support_policy=policy),
                )

    def test_support_style_without_supports_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "support_policy"):
            validate_extended_override_value(
                SUPPORT_STYLE_OVERRIDE_KEY, "grid", "Widget/Part", _intent(support_policy="none")
            )

    def test_style_values_map_to_prusaslicer_values(self) -> None:
        # organic/grid/snug are already PrusaSlicer's own values; the table
        # exists so a rename on either side is a visible edit.
        self.assertEqual(
            {"organic": "organic", "grid": "grid", "snug": "snug"},
            SUPPORT_MATERIAL_STYLE_TRANSLATIONS,
        )

    def test_seam_position_enum_enforced(self) -> None:
        validate_extended_override_value("seam_position", "rear", "Widget/Part", _intent())
        with self.assertRaisesRegex(ValueError, "seam_position"):
            validate_extended_override_value("seam_position", "random", "Widget/Part", _intent())
        self.assertEqual({"aligned", "nearest", "hidden", "rear"}, set(SEAM_POSITION_VALUES))

    def test_numeric_bounds_enforced(self) -> None:
        validate_extended_override_value("speed", 150, "Widget/Part", _intent())
        validate_extended_override_value("brim_width", 0, "Widget/Part", _intent())
        cases = (
            ("speed", 0),
            ("speed", -1),
            ("speed", float("nan")),
            ("layer_height", "0.2"),
        )
        for key, bad in cases:
            with self.subTest(key=key, bad=bad):
                with self.assertRaisesRegex(ValueError, key):
                    validate_extended_override_value(key, bad, "Widget/Part", _intent())

    def test_unknown_key_fails_named(self) -> None:
        with self.assertRaisesRegex(ValueError, "not part of the extended"):
            validate_extended_override_value("nozzle_diameter", 0.4, "Widget/Part", _intent())


if __name__ == "__main__":
    unittest.main()
