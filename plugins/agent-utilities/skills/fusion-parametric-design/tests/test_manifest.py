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

    def test_manifest_without_printable_parts_is_still_valid(self) -> None:
        data = copy.deepcopy(self.data)
        data.pop("printable_parts")
        self.assertEqual([], validate_manifest_data(data))

    def test_example_printable_parts_validate(self) -> None:
        self.assertEqual([], validate_manifest_data(self.data))
        manifest = load_manifest(EXAMPLE)
        self.assertEqual(3, len(manifest.printable_parts))

    def _codes(self, data) -> set[str]:
        return {issue.code for issue in validate_manifest_data(data)}

    def test_printable_part_identity_rules(self) -> None:
        data = copy.deepcopy(self.data)
        data["printable_parts"][1]["id"] = data["printable_parts"][0]["id"]
        self.assertIn("printable-part-duplicate-id", self._codes(data))

        data = copy.deepcopy(self.data)
        data["printable_parts"][0]["id"] = "bad-id!"
        self.assertIn("invalid-printable-part-id", self._codes(data))

        data = copy.deepcopy(self.data)
        data["printable_parts"][0]["path"] = "10_PRODUCT/DOES_NOT_EXIST"
        codes = self._codes(data)
        self.assertIn("printable-part-unknown-path", codes)
        self.assertIn("printable-parts-mismatch-expected", codes)

        data = copy.deepcopy(self.data)
        data["printable_parts"].pop()
        self.assertIn("printable-parts-mismatch-expected", self._codes(data))

        data = copy.deepcopy(self.data)
        data["printable_parts"][1]["path"] = data["printable_parts"][0]["path"]
        self.assertIn("printable-part-duplicate-path", self._codes(data))

    def test_printable_part_orientation_rules(self) -> None:
        data = copy.deepcopy(self.data)
        data["printable_parts"][0]["orientation"]["contact_face"] = "down"
        self.assertIn("printable-part-invalid-orientation", self._codes(data))

        data = copy.deepcopy(self.data)
        data["printable_parts"][0]["orientation"]["allowed_alternatives"] = ["-Z"]
        self.assertIn("printable-part-invalid-orientation", self._codes(data))

        data = copy.deepcopy(self.data)
        data["printable_parts"][0]["orientation"]["rationale"] = "  "
        self.assertIn("printable-part-invalid-orientation", self._codes(data))

        data = copy.deepcopy(self.data)
        data["printable_parts"][1]["orientation"]["allowed_alternatives"] = ["-Z", "-Z"]
        self.assertIn("printable-part-invalid-orientation", self._codes(data))

    def test_printable_part_support_rules(self) -> None:
        data = copy.deepcopy(self.data)
        data["printable_parts"][0]["support_policy"] = "tree"
        self.assertIn("printable-part-invalid-support-policy", self._codes(data))

        data = copy.deepcopy(self.data)
        data["printable_parts"][0]["support_policy"] = "explicit-regions"
        self.assertIn("printable-part-invalid-support-policy", self._codes(data))

        data = copy.deepcopy(self.data)
        data["printable_parts"][0]["support_policy"] = "explicit-regions"
        data["printable_parts"][0]["support_regions"] = [{"kind": "sideways", "description": "x"}]
        self.assertIn("printable-part-invalid-support-policy", self._codes(data))

        data = copy.deepcopy(self.data)
        data["printable_parts"][0]["support_regions"] = [{"kind": "blocker", "description": "keep rim clear"}]
        self.assertIn("printable-part-invalid-support-policy", self._codes(data))

        data = copy.deepcopy(self.data)
        data["printable_parts"][0]["support_policy"] = "explicit-regions"
        data["printable_parts"][0]["support_regions"] = [
            {"kind": "blocker", "description": "Keep the mating rim clear."}
        ]
        self.assertNotIn("printable-part-invalid-support-policy", self._codes(data))

    def test_printable_part_strength_rules(self) -> None:
        for mutate in (
            lambda part: part["strength"].__setitem__("min_perimeters", 0),
            lambda part: part["strength"]["infill_percent"].__setitem__("target", 101),
            lambda part: part["strength"]["infill_percent"].__setitem__("min", 90),
            lambda part: part["strength"]["infill_percent"].__setitem__("max", 1),
            lambda part: part["strength"].pop("infill_percent"),
        ):
            data = copy.deepcopy(self.data)
            mutate(data["printable_parts"][0])
            self.assertIn("printable-part-invalid-strength", self._codes(data))

    def test_printable_part_feature_material_and_misc_rules(self) -> None:
        data = copy.deepcopy(self.data)
        data["printable_parts"][0]["protected_features"][0]["kind"] = "sticker"
        self.assertIn("printable-part-invalid-protected-features", self._codes(data))

        data = copy.deepcopy(self.data)
        data["printable_parts"][0]["material"]["assumption"] = " "
        self.assertIn("printable-part-invalid-material", self._codes(data))

        data = copy.deepcopy(self.data)
        data["printable_parts"][0]["material"]["status"] = "guessed"
        self.assertIn("printable-part-invalid-material", self._codes(data))

        data = copy.deepcopy(self.data)
        data["printable_parts"][0]["material"]["source_id"] = "unknown_source"
        self.assertIn("printable-part-invalid-material", self._codes(data))

        data = copy.deepcopy(self.data)
        data["printable_parts"][0]["material"]["source_id"] = "pd_trigger_board_measurement"
        self.assertNotIn("printable-part-invalid-material", self._codes(data))

        data = copy.deepcopy(self.data)
        data["printable_parts"][0]["quantity"] = 0
        self.assertIn("printable-part-invalid-quantity", self._codes(data))

        data = copy.deepcopy(self.data)
        data["printable_parts"][0]["print_as"] = "together"
        self.assertIn("printable-part-invalid-print-as", self._codes(data))

        data = copy.deepcopy(self.data)
        data["printable_parts"][0]["body_name"] = ""
        self.assertIn("printable-part-invalid-body-name", self._codes(data))

        data = copy.deepcopy(self.data)
        data["printable_parts"][0]["surprise"] = True
        self.assertIn("unknown-manifest-field", self._codes(data))

        data = copy.deepcopy(self.data)
        data["printable_parts"] = {"not": "a list"}
        self.assertIn("printable-parts-must-be-list", self._codes(data))

    def test_schema_json_stays_in_lockstep_with_validator_constants(self) -> None:
        from fusion_design.manifest import (
            CONTACT_FACES,
            MATERIAL_STATUSES,
            PRINT_AS_VALUES,
            PROTECTED_FEATURE_KINDS,
            SUPPORT_POLICIES,
            SUPPORT_REGION_KINDS,
        )

        schema = json.loads((ROOT / "schema" / "fusion-project.schema.json").read_text(encoding="utf-8"))
        part = schema["$defs"]["printable_part"]
        self.assertIn("printable_parts", schema["properties"])
        self.assertEqual(
            {
                "id",
                "path",
                "body_name",
                "quantity",
                "print_as",
                "orientation",
                "support_policy",
                "support_regions",
                "strength",
                "protected_features",
                "material",
            },
            set(part["properties"]),
        )
        self.assertEqual(PRINT_AS_VALUES, set(part["properties"]["print_as"]["enum"]))
        self.assertEqual(CONTACT_FACES, set(schema["$defs"]["contact_face"]["enum"]))
        self.assertEqual(SUPPORT_POLICIES, set(part["properties"]["support_policy"]["enum"]))
        self.assertEqual(
            SUPPORT_REGION_KINDS,
            set(part["properties"]["support_regions"]["items"]["properties"]["kind"]["enum"]),
        )
        self.assertEqual(
            PROTECTED_FEATURE_KINDS,
            set(part["properties"]["protected_features"]["items"]["properties"]["kind"]["enum"]),
        )
        self.assertEqual(
            MATERIAL_STATUSES,
            set(part["properties"]["material"]["properties"]["status"]["enum"]),
        )

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
