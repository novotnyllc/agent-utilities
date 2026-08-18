from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from fusion_design.manifest import ManifestValidationError, load_manifest, validate_manifest_data


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "electronics-enclosure" / "fusion-project.json"


class ManifestValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def test_example_manifest_is_valid(self) -> None:
        issues = validate_manifest_data(self.data)
        self.assertEqual([], issues)
        manifest = load_manifest(EXAMPLE)
        self.assertEqual("wearable-controller-pod", manifest.project_name)

    def test_critical_source_parameter_requires_source(self) -> None:
        data = copy.deepcopy(self.data)
        data["parameters"][0].pop("source_id")
        issues = validate_manifest_data(data)
        self.assertIn("critical-parameter-missing-source", {issue.code for issue in issues})

    def test_parameter_role_requires_prefix(self) -> None:
        data = copy.deepcopy(self.data)
        data["parameters"][0]["name"] = "board_length"
        issues = validate_manifest_data(data)
        self.assertIn("parameter-prefix-mismatch", {issue.code for issue in issues})

    def test_every_parameter_requires_a_nonempty_expression(self) -> None:
        data = copy.deepcopy(self.data)
        data["parameters"][-1]["critical"] = False
        data["parameters"][-1]["expression"] = "   "
        issues = validate_manifest_data(data)
        self.assertIn("parameter-expression-required", {issue.code for issue in issues})

    def test_reference_requires_authoring_and_packing_models(self) -> None:
        data = copy.deepcopy(self.data)
        data["references"][0].pop("packing_component")
        issues = validate_manifest_data(data)
        self.assertIn("reference-missing-packing-component", {issue.code for issue in issues})

    def test_scan_derived_critical_parameter_must_be_provisional(self) -> None:
        data = copy.deepcopy(self.data)
        data["sources"][0]["kind"] = "scan"
        data["parameters"][0]["provisional"] = False
        issues = validate_manifest_data(data)
        self.assertIn("scan-parameter-not-provisional", {issue.code for issue in issues})

    def test_coupon_verified_scan_parameter_can_be_final(self) -> None:
        data = copy.deepcopy(self.data)
        data["sources"][0]["kind"] = "scan"
        data["sources"][0]["confidence"] = "coupon_verified"
        data["parameters"][0]["provisional"] = False
        issues = validate_manifest_data(data)
        self.assertNotIn("scan-parameter-not-provisional", {issue.code for issue in issues})

    def test_cli_enforces_schema_identity_and_unknown_field_rules(self) -> None:
        data = copy.deepcopy(self.data)
        data["sources"][0].pop("notes")
        data["sources"][0]["id"] = "invalid-id"
        data["parameters"][0]["unexpected"] = True
        data["verification"]["clearance_checks"][0]["unexpected"] = True

        codes = {issue.code for issue in validate_manifest_data(data)}

        self.assertIn("source-notes-required", codes)
        self.assertIn("invalid-source-id", codes)
        self.assertIn("unknown-manifest-field", codes)

    def test_cli_rejects_schema_scalar_type_mismatches(self) -> None:
        data = copy.deepcopy(self.data)
        data["project"]["units"] = 1
        data["sources"][0]["locator"] = 1
        data["parameters"][0]["description"] = 1
        data["references"][0]["keepout_components"] = []
        data["references"][0]["no_keepout_rationale"] = 1
        data["component_tree"][0] = 1
        data["verification"]["clearance_checks"][0]["id"] = 1

        codes = {issue.code for issue in validate_manifest_data(data)}

        self.assertIn("project-field-required", codes)
        self.assertIn("source-provenance-incomplete", codes)
        self.assertIn("parameter-description-required", codes)
        self.assertIn("no-keepout-rationale-must-be-string", codes)
        self.assertIn("component-path-must-be-string", codes)
        self.assertIn("verification-check-id-required", codes)

    def test_verification_references_declared_unique_component_paths(self) -> None:
        data = copy.deepcopy(self.data)
        data["verification"]["clearance_checks"].append(
            {
                "id": "pd-to-lid-clearance",
                "one": "00_REFERENCES/DOES_NOT_EXIST",
                "two": "10_PRODUCT/PROD__LID",
                "minimum_mm": -0.1,
            }
        )
        data["verification"]["interference_checks"].append(
            {
                "id": "pd-to-lid-clearance",
                "one": "10_PRODUCT/PROD__BASE",
                "two": "00_REFERENCES/ALSO_MISSING",
                "allow_interference": False,
            }
        )
        data["verification"]["expected_print_parts"].append("10_PRODUCT/PROD__MISSING")

        issues = validate_manifest_data(data)
        codes = {issue.code for issue in issues}
        self.assertIn("duplicate-verification-check-id", codes)
        self.assertIn("verification-component-not-in-tree", codes)
        self.assertIn("invalid-clearance-minimum", codes)
        self.assertIn("expected-print-part-not-in-tree", codes)

    def test_clearance_minimum_must_be_finite(self) -> None:
        for minimum in (float("nan"), 10**400):
            with self.subTest(minimum=minimum):
                data = copy.deepcopy(self.data)
                data["verification"]["clearance_checks"][0]["minimum_mm"] = minimum
                self.assertIn("invalid-clearance-minimum", {issue.code for issue in validate_manifest_data(data)})

    def test_component_paths_must_have_declared_parents_and_unambiguous_names(self) -> None:
        data = copy.deepcopy(self.data)
        data["component_tree"].extend(
            [
                "MISSING_PARENT/CHILD",
                "10_PRODUCT/BAD+NAME",
                "10_PRODUCT/BAD:12",
            ]
        )

        issues = validate_manifest_data(data)
        codes = {issue.code for issue in issues}
        self.assertIn("component-parent-not-in-tree", codes)
        self.assertIn("ambiguous-component-path-segment", codes)

    def test_manifest_structure_and_enumerations_are_enforced_by_cli_validator(self) -> None:
        data = copy.deepcopy(self.data)
        data["project"].pop("units")
        data.pop("sources")
        data["parameters"][0]["critical"] = "true"
        data["references"][0]["representation"] = "magic_mesh"

        issues = validate_manifest_data(data)
        codes = {issue.code for issue in issues}
        self.assertIn("project-field-required", codes)
        self.assertIn("manifest-list-field-required", codes)
        self.assertIn("parameter-boolean-required", codes)
        self.assertIn("unknown-reference-representation", codes)

    def test_reference_can_use_an_explicit_no_keepout_rationale(self) -> None:
        data = copy.deepcopy(self.data)
        data["references"][0]["keepout_components"] = []
        data["references"][0]["no_keepout_rationale"] = (
            "This reference is an immutable flat datum plate with no insertion, service, motion, thermal, or tool envelope."
        )
        issues = validate_manifest_data(data)
        self.assertNotIn("reference-keepout-required", {issue.code for issue in issues})

    def test_load_manifest_raises_with_all_issues(self) -> None:
        data = copy.deepcopy(self.data)
        data["parameters"][0].pop("source_id")
        broken = ROOT / "tests" / "_broken_manifest.json"
        broken.write_text(json.dumps(data), encoding="utf-8")
        try:
            with self.assertRaises(ManifestValidationError) as ctx:
                load_manifest(broken)
            self.assertIn("critical-parameter-missing-source", str(ctx.exception))
        finally:
            broken.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
