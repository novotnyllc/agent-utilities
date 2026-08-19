from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from fusion_design.manifest import ManifestValidationError, load_manifest, validate_manifest_data


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "electronics-enclosure" / "fusion-project.json"

# Sentinel for "drop this key entirely" in the material-decision test builder.
_OMIT = object()


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

    def test_printable_part_nested_objects_are_closed_worlds(self) -> None:
        def with_regions(part):
            part["support_policy"] = "explicit-regions"
            part["support_regions"] = [{"kind": "blocker", "description": "Keep the rim clear."}]
            return part["support_regions"][0]

        for label, mutate in (
            ("orientation", lambda part: part["orientation"].__setitem__("surprise", True)),
            ("strength", lambda part: part["strength"].__setitem__("surprise", True)),
            (
                "strength.infill_percent",
                lambda part: part["strength"]["infill_percent"].__setitem__("surprise", True),
            ),
            ("material", lambda part: part["material"].__setitem__("surprise", True)),
            ("support_regions[0]", lambda part: with_regions(part).__setitem__("surprise", True)),
            (
                "protected_features[0]",
                lambda part: part["protected_features"][0].__setitem__("surprise", True),
            ),
        ):
            with self.subTest(nested=label):
                data = copy.deepcopy(self.data)
                mutate(data["printable_parts"][0])
                self.assertIn("unknown-manifest-field", self._codes(data))

    def test_explicit_null_support_regions_is_rejected(self) -> None:
        data = copy.deepcopy(self.data)
        self.assertNotEqual("explicit-regions", data["printable_parts"][0]["support_policy"])
        data["printable_parts"][0]["support_regions"] = None
        self.assertIn("printable-part-invalid-support-policy", self._codes(data))

    def test_closed_world_enums_reject_unhashable_values_without_crashing(self) -> None:
        # A dict where an enum string belongs used to raise TypeError out of the
        # validator, escaping the CLI's ok/issues contract as a traceback.
        cases = (
            ("sources[0].kind", lambda d: d["sources"][0].__setitem__("kind", {"a": 1}), "unknown-source-kind"),
            (
                "sources[0].confidence",
                lambda d: d["sources"][0].__setitem__("confidence", {"a": 1}),
                "unknown-source-confidence",
            ),
            (
                "references[0].representation",
                lambda d: d["references"][0].__setitem__("representation", {"a": 1}),
                "unknown-reference-representation",
            ),
            (
                "printable_parts[0].print_as",
                lambda d: d["printable_parts"][0].__setitem__("print_as", {"a": 1}),
                "printable-part-field-required",
            ),
            (
                "printable_parts[0].orientation.contact_face",
                lambda d: d["printable_parts"][0]["orientation"].__setitem__("contact_face", {"a": 1}),
                "printable-part-invalid-orientation",
            ),
            (
                "printable_parts[0].orientation.allowed_alternatives[0]",
                lambda d: d["printable_parts"][0]["orientation"].__setitem__("allowed_alternatives", [{"a": 1}]),
                "printable-part-invalid-orientation",
            ),
            (
                "printable_parts[0].support_policy",
                lambda d: d["printable_parts"][0].__setitem__("support_policy", {"a": 1}),
                "printable-part-field-required",
            ),
            (
                "printable_parts[0].support_regions[0].kind",
                lambda d: d["printable_parts"][0].update(
                    support_policy="explicit-regions",
                    support_regions=[{"kind": {"a": 1}, "description": "Keep the rim clear."}],
                ),
                "printable-part-invalid-support-policy",
            ),
            (
                "printable_parts[0].protected_features[0].kind",
                lambda d: d["printable_parts"][0]["protected_features"][0].__setitem__("kind", {"a": 1}),
                "printable-part-invalid-protected-features",
            ),
            (
                "printable_parts[0].material.status",
                lambda d: d["printable_parts"][0]["material"].__setitem__("status", {"a": 1}),
                "printable-part-invalid-material",
            ),
        )
        for label, mutate, expected_code in cases:
            with self.subTest(field=label):
                data = copy.deepcopy(self.data)
                mutate(data)
                self.assertIn(expected_code, self._codes(data))

    def _with_decision(self, **overrides):
        data = copy.deepcopy(self.data)
        decision = {
            "family": "PETG",
            "formulation": "Prusament PETG",
            "source_id": "pd_trigger_board_measurement",
            "confidence": "measured",
            "coupon_component": "90_VALIDATION/VAL__PD_FIT_COUPON",
            "rationale": "The snap-fit lid needs PETG toughness; PLA would fail brittle at the snap.",
            "unresolved_risks": [],
        }
        decision.update(overrides)
        for key in [key for key, value in decision.items() if value is _OMIT]:
            decision.pop(key)
        data["material_decision"] = decision
        return data

    def test_valid_material_decision_passes_and_absence_stays_valid(self) -> None:
        self.assertEqual([], validate_manifest_data(self._with_decision()))
        self.assertNotIn("material_decision", self.data)
        self.assertEqual([], validate_manifest_data(self.data))
        manifest = load_manifest(EXAMPLE)
        self.assertEqual({}, manifest.material_decision)

    def test_material_decision_core_rejections(self) -> None:
        for label, overrides, expected in (
            ("unknown family", {"family": "PLAA"}, "material-decision-unknown-family"),
            ("blank formulation", {"formulation": "   "}, "material-decision-invalid-formulation"),
            (
                "other without formulation",
                {"family": "OTHER", "formulation": None},
                "material-decision-invalid-formulation",
            ),
            ("unknown source", {"source_id": "not_a_source"}, "material-decision-unknown-source"),
            ("missing source", {"source_id": _OMIT}, "material-decision-unknown-source"),
            ("unknown confidence", {"confidence": "vibes"}, "material-decision-unknown-confidence"),
            (
                "unknown coupon",
                {"coupon_component": "90_VALIDATION/DOES_NOT_EXIST"},
                "material-decision-unknown-coupon",
            ),
            ("blank rationale", {"rationale": "  "}, "material-decision-missing-rationale"),
            ("missing rationale", {"rationale": _OMIT}, "material-decision-missing-rationale"),
            ("risks not a list", {"unresolved_risks": "moisture"}, "material-decision-invalid-risks"),
            ("blank risk entry", {"unresolved_risks": [" "]}, "material-decision-invalid-risks"),
            (
                "blank printer requirements",
                {"printer_requirements": ""},
                "material-decision-invalid-printer-requirements",
            ),
            ("unknown nested field", {"surprise": True}, "unknown-manifest-field"),
        ):
            with self.subTest(case=label):
                self.assertIn(expected, self._codes(self._with_decision(**overrides)))

    def test_material_decision_must_be_an_object(self) -> None:
        data = copy.deepcopy(self.data)
        data["material_decision"] = ["PETG"]
        self.assertIn("material-decision-must-be-object", self._codes(data))

    def test_filled_material_guard(self) -> None:
        unguarded = self._with_decision(family="PA_CF", formulation="Some PA-CF", unresolved_risks=[])
        self.assertIn("material-decision-filled-material-unguarded", self._codes(unguarded))

        by_risk = self._with_decision(
            family="PA_CF",
            formulation="Some PA-CF",
            unresolved_risks=["Layer adhesion is unproven for this filled filament."],
        )
        self.assertNotIn("material-decision-filled-material-unguarded", self._codes(by_risk))

        by_requirements = self._with_decision(
            family="PET_CF",
            formulation="Some PET-CF",
            printer_requirements="Hardened steel nozzle required for the abrasive fill.",
        )
        self.assertNotIn("material-decision-filled-material-unguarded", self._codes(by_requirements))

        # PA* additionally needs drying declared on the printer_requirements route.
        nozzle_only = self._with_decision(
            family="PA",
            formulation="Some PA",
            printer_requirements="Hardened steel nozzle required for the abrasive fill.",
        )
        self.assertIn("material-decision-filled-material-unguarded", self._codes(nozzle_only))

        with_drying = self._with_decision(
            family="PA",
            formulation="Some PA",
            printer_requirements="Hardened steel nozzle; dry the spool for 8 hours before printing.",
        )
        self.assertNotIn("material-decision-filled-material-unguarded", self._codes(with_drying))

        # Unfilled families are not asked for either guard.
        self.assertEqual([], validate_manifest_data(self._with_decision()))

    def test_tpu_requires_formulation_and_hardness_rationale(self) -> None:
        tpu_rationale = "Shore 95A gives the strain relief the boot needs."
        no_formulation = self._with_decision(family="TPU", formulation=None, rationale=tpu_rationale)
        self.assertIn("material-decision-tpu-underspecified", self._codes(no_formulation))

        vague_rationale = self._with_decision(
            family="TPU",
            formulation="Some TPU",
            rationale="It is the material we happen to have on the shelf.",
        )
        self.assertIn("material-decision-tpu-underspecified", self._codes(vague_rationale))

        specified = self._with_decision(
            family="TPU", formulation="Some TPU 95A", rationale=tpu_rationale
        )
        self.assertNotIn("material-decision-tpu-underspecified", self._codes(specified))

    def test_provisional_decision_must_be_bound(self) -> None:
        unbound = self._with_decision(confidence="provisional", coupon_component=None, unresolved_risks=[])
        self.assertIn("material-decision-provisional-unbound", self._codes(unbound))

        by_coupon = self._with_decision(confidence="provisional", unresolved_risks=[])
        self.assertNotIn("material-decision-provisional-unbound", self._codes(by_coupon))

        by_risk = self._with_decision(
            confidence="provisional",
            coupon_component=None,
            unresolved_risks=["Snap strain is unverified until the coupon prints."],
        )
        self.assertNotIn("material-decision-provisional-unbound", self._codes(by_risk))

    def test_material_decision_fields_reject_unhashable_values_without_crashing(self) -> None:
        for field in sorted(
            {
                "family",
                "formulation",
                "source_id",
                "confidence",
                "coupon_component",
                "rationale",
                "unresolved_risks",
                "printer_requirements",
            }
        ):
            # A list of strings is a legal unresolved_risks value; the unhashable
            # case there is a list holding a dict.
            values = ({"a": 1}, [{"a": 1}]) if field == "unresolved_risks" else ({"a": 1}, ["a"])
            for value in values:
                with self.subTest(field=field, value=type(value).__name__):
                    codes = self._codes(self._with_decision(**{field: value}))
                    self.assertTrue(codes, f"{field} with {value!r} produced no validation issue")

    def test_part_material_assumption_must_match_the_decision(self) -> None:
        # Back-compat: without a project decision the parts are never cross-checked.
        self.assertNotIn("material-decision-part-mismatch", self._codes(self.data))

        consistent = self._with_decision()
        consistent["printable_parts"][0]["material"]["assumption"] = "PETG, generic spool"
        self.assertNotIn("material-decision-part-mismatch", self._codes(consistent))

        by_formulation = self._with_decision(family="PETG", formulation="Prusament PETG")
        by_formulation["printable_parts"][0]["material"]["assumption"] = "prusament petg"
        self.assertNotIn("material-decision-part-mismatch", self._codes(by_formulation))

        mismatched = self._with_decision(family="ASA", formulation=None)
        self.assertIn("material-decision-part-mismatch", self._codes(mismatched))

        # A family that is only a substring of the assumption does not count as a match.
        substring_only = self._with_decision(family="PA", formulation=None, unresolved_risks=["Drying unverified."])
        substring_only["printable_parts"][0]["material"]["assumption"] = "opaque PETG"
        self.assertIn("material-decision-part-mismatch", self._codes(substring_only))

    def test_schema_json_stays_in_lockstep_with_validator_constants(self) -> None:
        from fusion_design.manifest import (
            CONTACT_FACES,
            MATERIAL_DECISION_FIELDS,
            MATERIAL_FAMILIES,
            MATERIAL_STATUSES,
            PRINT_AS_VALUES,
            PRINTABLE_PART_FIELDS,
            PROTECTED_FEATURE_KINDS,
            SOURCE_CONFIDENCES,
            SUPPORT_POLICIES,
            SUPPORT_REGION_KINDS,
        )

        schema = json.loads((ROOT / "schema" / "fusion-project.schema.json").read_text(encoding="utf-8"))
        part = schema["$defs"]["printable_part"]
        self.assertIn("printable_parts", schema["properties"])
        self.assertEqual(PRINTABLE_PART_FIELDS, set(part["properties"]))
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
        decision = schema["$defs"]["material_decision"]
        self.assertIn("material_decision", schema["properties"])
        self.assertEqual(MATERIAL_DECISION_FIELDS, set(decision["properties"]))
        self.assertEqual(MATERIAL_FAMILIES, set(decision["properties"]["family"]["enum"]))
        self.assertEqual(SOURCE_CONFIDENCES, set(decision["properties"]["confidence"]["enum"]))

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
