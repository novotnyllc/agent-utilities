from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
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
        self.assertIn("parameter-confidence-exceeds-source", {issue.code for issue in issues})

    def test_coupon_verified_scan_parameter_can_be_final(self) -> None:
        data = copy.deepcopy(self.data)
        data["sources"][0]["kind"] = "scan"
        data["sources"][0]["confidence"] = "coupon_verified"
        data["parameters"][0]["provisional"] = False
        issues = validate_manifest_data(data)
        self.assertNotIn("parameter-confidence-exceeds-source", {issue.code for issue in issues})

    def test_critical_parameter_may_not_outrank_a_provisional_source_of_any_kind(self) -> None:
        # The scan rule was only ever one instance of the general contract: a
        # claim's confidence may never exceed the confidence of its source.
        for kind in ("user_measurement", "conservative_proxy", "third_party_cad", "manufacturer_drawing"):
            with self.subTest(kind=kind):
                data = copy.deepcopy(self.data)
                data["sources"][0]["kind"] = kind
                data["sources"][0]["confidence"] = "provisional"
                self.assertEqual(False, data["parameters"][0]["provisional"])
                self.assertEqual(True, data["parameters"][0]["critical"])
                self.assertIn("parameter-confidence-exceeds-source", self._codes(data))

    def test_provisional_source_backs_a_parameter_that_admits_it_is_provisional(self) -> None:
        data = copy.deepcopy(self.data)
        data["sources"][0]["confidence"] = "provisional"
        for parameter in data["parameters"]:
            if parameter.get("source_id") == "pd_trigger_board_measurement":
                parameter["provisional"] = True
        self.assertNotIn("parameter-confidence-exceeds-source", self._codes(data))

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

    def test_zero_clearance_minimum_is_rejected(self) -> None:
        # measureMinimumDistance returns 0 for touching and for interpenetrating
        # solids alike, so a zero minimum is a check that can never fail.
        data = copy.deepcopy(self.data)
        data["verification"]["clearance_checks"][0]["minimum_mm"] = 0
        issues = validate_manifest_data(data)
        self.assertIn("invalid-clearance-minimum", {issue.code for issue in issues})
        self.assertIn(
            "interference check",
            next(issue.message for issue in issues if issue.code == "invalid-clearance-minimum"),
        )

    def test_printable_part_requires_a_positive_minimum_volume(self) -> None:
        for minimum_volume in (None, 0, -1, "big", float("nan")):
            with self.subTest(minimum_volume=minimum_volume):
                data = copy.deepcopy(self.data)
                if minimum_volume is None:
                    data["printable_parts"][0].pop("minimum_volume_mm3")
                else:
                    data["printable_parts"][0]["minimum_volume_mm3"] = minimum_volume
                self.assertIn(
                    "printable-part-invalid-minimum-volume",
                    {issue.code for issue in validate_manifest_data(data)},
                )

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

    def test_absent_printable_parts_is_recorded_rather_than_silently_satisfied(self) -> None:
        data = copy.deepcopy(self.data)
        data.pop("printable_parts")
        issues = validate_manifest_data(data)
        # Omitting the section stays legal (back-compat) ...
        self.assertEqual([], [issue for issue in issues if issue.severity == "error"])
        # ... but the absence is recorded, so no consumer can read "no print
        # intent declared" as "print intent satisfied".
        absence = [issue for issue in issues if issue.code == "printable-parts-not-declared"]
        self.assertEqual(1, len(absence), issues)
        self.assertEqual("warning", absence[0].severity)
        for expected in data["verification"]["expected_print_parts"]:
            self.assertIn(expected, absence[0].message)

    def test_absent_printable_parts_is_silent_when_nothing_is_expected(self) -> None:
        data = copy.deepcopy(self.data)
        data.pop("printable_parts")
        data["verification"]["expected_print_parts"] = []
        self.assertEqual([], validate_manifest_data(data))

    def test_absent_printable_parts_does_not_block_loading(self) -> None:
        data = copy.deepcopy(self.data)
        data.pop("printable_parts")
        with tempfile.TemporaryDirectory() as scratch:
            broken = Path(scratch) / "no_printable_parts.json"
            broken.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual([], load_manifest(broken).printable_parts)

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

    def _without_decision(self):
        """The example now declares a decision; back-compat cases strip it."""
        data = copy.deepcopy(self.data)
        data.pop("material_decision", None)
        return data

    def test_valid_material_decision_passes_and_absence_stays_valid(self) -> None:
        from fusion_design.manifest import Manifest

        self.assertEqual([], validate_manifest_data(self._with_decision()))
        stripped = self._without_decision()
        self.assertNotIn("material_decision", stripped)
        self.assertEqual([], validate_manifest_data(stripped))
        self.assertEqual({}, Manifest.from_data(stripped).material_decision)

    def test_example_manifest_declares_a_bound_petg_decision(self) -> None:
        decision = load_manifest(EXAMPLE).material_decision
        self.assertEqual("PETG", decision["family"])
        # Family only: the example deliberately names no formulation, so it
        # claims no data-sheet numbers.
        self.assertIsNone(decision["formulation"])
        self.assertEqual("provisional", decision["confidence"])
        # R5: a provisional decision must be bound to a coupon or a risk.
        self.assertEqual("90_VALIDATION/VAL__PD_FIT_COUPON", decision["coupon_component"])
        self.assertTrue(decision["unresolved_risks"])
        self.assertIn(decision["source_id"], {source["id"] for source in self.data["sources"]})

    def test_example_part_assumption_inconsistent_with_its_decision_fails(self) -> None:
        data = copy.deepcopy(self.data)
        data["printable_parts"][1]["material"]["assumption"] = "ASA"
        self.assertIn("material-decision-part-mismatch", self._codes(data))

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

        # Prose discharges nothing, however emphatic — including prose that
        # denies the constraint or that names the abrasion word on other hardware.
        for label, requirements in (
            ("denies the requirement", "No hardened nozzle here; stock brass nozzle, skip drying."),
            ("build plate, not nozzle", "Print on the smooth PEI steel sheet with the stock nozzle."),
            ("affirms it in prose only", "Hardened steel nozzle required; dry the spool before printing."),
        ):
            with self.subTest(case=label):
                prose = self._with_decision(
                    family="PA_CF",
                    formulation="Some PA-CF",
                    unresolved_risks=[],
                    printer_requirements=requirements,
                )
                self.assertIn("material-decision-filled-material-unguarded", self._codes(prose))

        # An unrelated open risk is advisory, not a discharge.
        by_risk = self._with_decision(
            family="PA_CF",
            formulation="Some PA-CF",
            unresolved_risks=["Lid colour not chosen yet."],
        )
        self.assertIn("material-decision-filled-material-unguarded", self._codes(by_risk))

        # Only the structured fields discharge it.
        by_nozzle = self._with_decision(
            family="PET_CF", formulation="Some PET-CF", nozzle="hardened_steel"
        )
        self.assertNotIn("material-decision-filled-material-unguarded", self._codes(by_nozzle))

        brass = self._with_decision(family="PET_CF", formulation="Some PET-CF", nozzle="brass")
        self.assertIn("material-decision-filled-material-unguarded", self._codes(brass))

        # PA* additionally needs the drying state declared, and 'not_needed' is
        # a declaration that the gate rejects rather than one it accepts.
        for label, overrides, expected in (
            ("nozzle only", {"nozzle": "ruby"}, True),
            ("nozzle and drying required", {"nozzle": "ruby", "drying": "required"}, False),
            ("nozzle and drying done", {"nozzle": "ruby", "drying": "done"}, False),
            ("nozzle but drying not needed", {"nozzle": "ruby", "drying": "not_needed"}, True),
            ("drying only", {"drying": "done"}, True),
        ):
            for family in ("PA", "PA_CF"):
                with self.subTest(case=label, family=family):
                    data = self._with_decision(
                        family=family, formulation=f"Some {family}", unresolved_risks=[], **overrides
                    )
                    codes = self._codes(data)
                    if expected:
                        self.assertIn("material-decision-filled-material-unguarded", codes)
                    else:
                        self.assertNotIn("material-decision-filled-material-unguarded", codes)

        # Unfilled families are not asked for either guard.
        self.assertEqual([], validate_manifest_data(self._with_decision()))

    def test_machine_constraint_fields_are_closed_enums(self) -> None:
        for field, bad in (("nozzle", "hardened steel"), ("drying", "maybe")):
            with self.subTest(field=field):
                self.assertIn(
                    f"material-decision-unknown-{field}", self._codes(self._with_decision(**{field: bad}))
                )
        # Both are optional on an unfilled decision.
        self.assertEqual([], validate_manifest_data(self._with_decision(nozzle=None, drying=None)))

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

        # Substrings are not statements of hardness, and the hardness word on its
        # own is not a figure.
        for rationale in (
            "Chosen because the offshore supplier stocks it and lead time is short.",
            "Matches the reflex housing used on the prior revision.",
            "The hardness will be decided once the grommet is prototyped.",
        ):
            with self.subTest(rationale=rationale):
                vague = self._with_decision(
                    family="TPU", formulation="Some TPU", rationale=rationale
                )
                self.assertIn("material-decision-tpu-underspecified", self._codes(vague))

        # The flex route stays open to a genuine statement about flex behavior.
        by_flex = self._with_decision(
            family="TPU",
            formulation="Some TPU",
            rationale="The strain relief must flex through the full cable bend without taking a set.",
        )
        self.assertNotIn("material-decision-tpu-underspecified", self._codes(by_flex))

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
        without = self._without_decision()
        without["printable_parts"][0]["material"]["assumption"] = "ASA"
        self.assertNotIn("material-decision-part-mismatch", self._codes(without))

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

    def test_part_assumption_may_not_name_a_filled_sibling_of_the_decided_family(self) -> None:
        """A compound family is not its own prefix: PA_CF under PA is a mismatch."""
        for family, assumption in (
            ("PA", "PA-CF filament, dry storage"),
            ("PA", "PA_CF filament"),
            ("PLA", "PLA-SILK, gloss finish"),
            ("PC", "PC-CF spool"),
        ):
            with self.subTest(family=family, assumption=assumption):
                data = self._with_decision(
                    family=family,
                    formulation=None,
                    unresolved_risks=["Drying unverified."],
                )
                for part in data["printable_parts"]:
                    part["material"]["assumption"] = assumption
                self.assertIn("material-decision-part-mismatch", self._codes(data))

    def test_part_assumption_may_carry_a_grade_suffix_or_shorten_the_formulation(self) -> None:
        """R6 rejects a *different* material, not a differently spelled same one."""
        for label, overrides, assumption in (
            ("digit-suffixed grade", {"family": "PA", "formulation": None}, "PA6, dried"),
            (
                "digit-suffixed filled grade",
                {"family": "PA_CF", "formulation": None},
                "PA12-CF",
            ),
            (
                "shortened formulation under OTHER",
                {"family": "OTHER", "formulation": "Fiberon PET-CF17"},
                "PET-CF17",
            ),
            (
                "formulation longer than the assumption",
                {"family": "PETG", "formulation": "Prusament PETG"},
                "Prusament",
            ),
        ):
            with self.subTest(case=label):
                data = self._with_decision(
                    unresolved_risks=["Drying and abrasion unverified."], **overrides
                )
                for part in data["printable_parts"]:
                    part["material"]["assumption"] = assumption
                self.assertNotIn("material-decision-part-mismatch", self._codes(data))

    def test_printer_requirements_may_be_null(self) -> None:
        self.assertEqual([], validate_manifest_data(self._with_decision(printer_requirements=None)))

    def test_family_other_does_not_match_the_english_word(self) -> None:
        data = self._with_decision(family="OTHER", formulation="Weird Co ExoPoly")
        for part in data["printable_parts"]:
            part["material"]["assumption"] = "Same as the other lid part."
        self.assertIn("material-decision-part-mismatch", self._codes(data))

    def test_part_assumption_may_not_hedge_between_two_materials(self) -> None:
        data = self._with_decision(family="PETG", formulation=None)
        for part in data["printable_parts"]:
            part["material"]["assumption"] = "PETG for now, ABS if it runs hot"
        self.assertIn("material-decision-part-mismatch", self._codes(data))

    def test_decision_may_not_claim_more_confidence_than_its_source(self) -> None:
        # enclosure_material_requirements is a conservative_proxy at provisional.
        for confidence in ("published", "measured", "coupon_verified"):
            with self.subTest(confidence=confidence):
                data = self._with_decision(
                    source_id="enclosure_material_requirements",
                    confidence=confidence,
                    coupon_component=None,
                    unresolved_risks=[],
                )
                self.assertIn("material-decision-outranks-source", self._codes(data))

        # A stronger claim is allowed when it is bound by both a coupon and a
        # recorded risk -- a declared plan to close the gap.
        bound = self._with_decision(
            source_id="enclosure_material_requirements",
            confidence="measured",
            unresolved_risks=["VAL__PD_FIT_COUPON is not printed yet, so the fit is unproven."],
        )
        self.assertNotIn("material-decision-outranks-source", self._codes(bound))

        # ... and the risk must name the coupon. Any coupon path plus any
        # non-empty string made the bridge free.
        unbound = self._with_decision(
            source_id="enclosure_material_requirements",
            confidence="measured",
            unresolved_risks=["Snap-rim cycle life is still unproven."],
        )
        self.assertIn("material-decision-outranks-source", self._codes(unbound))

        # ... but coupon_verified is not bridgeable. It asserts a coupon was
        # already printed and measured, and a plan to measure cannot stand in
        # for a measurement that happened. This is the shipped shape: the
        # example decision already carries a coupon and three risks, so a
        # bridgeable coupon_verified would leave the claim unbacked.
        unbridgeable = self._with_decision(
            source_id="enclosure_material_requirements",
            confidence="coupon_verified",
            unresolved_risks=["VAL__PD_FIT_COUPON is not printed yet, so the fit is unproven."],
        )
        self.assertIn("material-decision-outranks-source", self._codes(unbridgeable))

        # A measured source carries a measured decision without complaint.
        self.assertEqual([], validate_manifest_data(self._with_decision()))

    def test_decision_confidence_is_ranked_not_string_compared(self) -> None:
        # The inline predicate only ever tested `source.confidence ==
        # "provisional"`, so every shortfall between two non-provisional
        # confidences validated clean.
        self.assertIn(
            "material-decision-outranks-source",
            self._codes(
                self._with_decision(
                    source_id="pd_trigger_board_measurement",  # confidence: measured
                    confidence="coupon_verified",
                    coupon_component=None,
                    unresolved_risks=[],
                )
            ),
        )

    def test_decision_may_not_rest_on_an_unverified_scan(self) -> None:
        # source_backs_claim demotes a scan to provisional whatever it declares,
        # so the scan rule reaches material decisions without being restated.
        data = self._with_decision(source_id="scan_source", confidence="measured", unresolved_risks=[])
        data["sources"].append(
            {
                "id": "scan_source",
                "kind": "scan",
                "locator": "scan://pd-trigger",
                "revision": "2026-08-18",
                "confidence": "measured",
                "notes": "Structured-light scan of the sample.",
            }
        )
        self.assertIn("material-decision-outranks-source", self._codes(data))

        # Coupon-verifying the scan settles it, exactly as for a parameter.
        data["sources"][-1]["confidence"] = "coupon_verified"
        self.assertNotIn("material-decision-outranks-source", self._codes(data))

    def test_filled_material_guard_still_fires_alongside_the_confidence_rule(self) -> None:
        # Regression guard for the adversarially-found chain: PA_CF plus
        # coupon_verified against a provisional source must not go quiet.
        data = self._with_decision(
            family="PA_CF",
            formulation="Prusament PA11CF",
            source_id="enclosure_material_requirements",
            confidence="coupon_verified",
            unresolved_risks=["Nozzle wear is unquantified until VAL__PD_FIT_COUPON is printed."],
        )
        codes = self._codes(data)
        self.assertIn("material-decision-filled-material-unguarded", codes)
        self.assertIn("material-decision-outranks-source", codes)

    def test_coupon_component_must_be_a_printable_part(self) -> None:
        for path in ("00_REFERENCES/REF__PD_TRIGGER__PARAMETRIC", "20_FIXTURES", "10_PRODUCT"):
            with self.subTest(path=path):
                data = self._with_decision(
                    confidence="provisional", coupon_component=path, unresolved_risks=[]
                )
                codes = self._codes(data)
                self.assertIn("material-decision-unknown-coupon", codes)
                self.assertIn("material-decision-provisional-unbound", codes)

    def test_enum_fields_are_validated_raw_so_the_index_ships_what_was_checked(self) -> None:
        """Padded values are rejected, not silently accepted and then exported raw."""
        for field, padded, expected in (
            ("family", "  PETG\n", "material-decision-unknown-family"),
            ("confidence", " measured ", "material-decision-unknown-confidence"),
            ("source_id", " pd_trigger_board_measurement ", "material-decision-unknown-source"),
            (
                "coupon_component",
                " 90_VALIDATION/VAL__PD_FIT_COUPON ",
                "material-decision-unknown-coupon",
            ),
        ):
            with self.subTest(field=field):
                self.assertIn(expected, self._codes(self._with_decision(**{field: padded})))
    def test_coupon_verified_material_needs_coupon_evidence(self) -> None:
        data = copy.deepcopy(self.data)
        data["printable_parts"][0]["material"]["status"] = "coupon_verified"
        data["printable_parts"][0]["material"].pop("source_id", None)
        self.assertIn("printable-part-invalid-material", self._codes(data))

        # A source may not back a claim stronger than its own confidence.
        data = copy.deepcopy(self.data)
        data["printable_parts"][0]["material"]["status"] = "coupon_verified"
        data["printable_parts"][0]["material"]["source_id"] = "pd_trigger_board_measurement"
        self.assertEqual("measured", data["sources"][0]["confidence"])
        self.assertIn("printable-part-invalid-material", self._codes(data))

        data = copy.deepcopy(self.data)
        data["sources"][0]["confidence"] = "coupon_verified"
        data["printable_parts"][0]["material"]["status"] = "coupon_verified"
        data["printable_parts"][0]["material"]["source_id"] = "pd_trigger_board_measurement"
        self.assertNotIn("printable-part-invalid-material", self._codes(data))

    def test_contradictory_clearance_and_interference_checks_are_reconciled(self) -> None:
        pair = ("10_PRODUCT/PROD__BASE", "10_PRODUCT/PROD__LID")

        data = copy.deepcopy(self.data)
        data["verification"]["clearance_checks"].append(
            {"id": "base-lid-gap", "one": pair[0], "two": pair[1], "minimum_mm": 2.0}
        )
        data["verification"]["interference_checks"].append(
            {"id": "base-lid-overlap", "one": pair[0], "two": pair[1], "allow_interference": True}
        )
        self.assertIn("contradictory-verification-checks", self._codes(data))

        # Reversing 'one' and 'two' describes the same pair and must not hide it.
        data = copy.deepcopy(self.data)
        data["verification"]["clearance_checks"].extend(
            [
                {"id": "base-lid-gap", "one": pair[0], "two": pair[1], "minimum_mm": 2.0},
                {"id": "lid-base-gap", "one": pair[1], "two": pair[0], "minimum_mm": 0.5},
            ]
        )
        self.assertIn("contradictory-verification-checks", self._codes(data))

        data = copy.deepcopy(self.data)
        data["verification"]["interference_checks"][0]["allow_interference"] = True
        codes = self._codes(data)
        self.assertIn("keepout-interference-allowed", codes)

    def test_agreeing_checks_on_one_pair_are_not_a_contradiction(self) -> None:
        data = copy.deepcopy(self.data)
        data["verification"]["clearance_checks"].extend(
            [
                {
                    "id": "base-lid-gap",
                    "one": "10_PRODUCT/PROD__BASE",
                    "two": "10_PRODUCT/PROD__LID",
                    "minimum_mm": 2.0,
                },
                {
                    "id": "lid-base-gap",
                    "one": "10_PRODUCT/PROD__LID",
                    "two": "10_PRODUCT/PROD__BASE",
                    "minimum_mm": 2.0,
                },
            ]
        )
        self.assertNotIn("contradictory-verification-checks", self._codes(data))

    def test_a_reference_may_not_stand_in_for_its_own_keepout_or_packing_model(self) -> None:
        data = copy.deepcopy(self.data)
        data["references"][0]["keepout_components"] = [
            "00_REFERENCES/PACK__PD_TRIGGER__EXACT_OR_CONSERVATIVE"
        ]
        codes = self._codes(data)
        self.assertIn("keepout-is-own-model", codes)
        self.assertNotIn("reference-keepout-required", codes)

        data = copy.deepcopy(self.data)
        data["references"][0]["packing_component"] = "00_REFERENCES/REF__PD_TRIGGER__PARAMETRIC"
        self.assertIn("reference-authoring-equals-packing", self._codes(data))

        data = copy.deepcopy(self.data)
        data["references"][1]["packing_component"] = "00_REFERENCES/PACK__PD_TRIGGER__EXACT_OR_CONSERVATIVE"
        self.assertIn("duplicate-packing-component", self._codes(data))

    def test_expected_print_parts_are_reconciled_with_required_components(self) -> None:
        data = copy.deepcopy(self.data)
        data["verification"]["required_components"] = ["10_PRODUCT/PROD__BASE"]
        self.assertIn("expected-print-part-not-required", self._codes(data))

        # A packing proxy is somebody else's hardware, never printable output.
        pack = "00_REFERENCES/PACK__PD_TRIGGER__EXACT_OR_CONSERVATIVE"
        data = copy.deepcopy(self.data)
        data["verification"]["expected_print_parts"].append(pack)
        data["printable_parts"].append(copy.deepcopy(data["printable_parts"][0]))
        data["printable_parts"][-1].update(id="pack_pd_trigger", path=pack)
        self.assertIn("expected-print-part-is-reference-model", self._codes(data))

    def test_parameter_names_are_deduped_on_the_value_that_is_validated(self) -> None:
        data = copy.deepcopy(self.data)
        duplicate = copy.deepcopy(data["parameters"][0])
        duplicate["name"] = data["parameters"][0]["name"] + " "
        duplicate["expression"] = "36 mm"
        data["parameters"].append(duplicate)
        codes = self._codes(data)
        self.assertIn("duplicate-parameter-name", codes)
        self.assertIn("invalid-parameter-name", codes)

    def test_component_path_segments_reject_whitespace(self) -> None:
        for bad in ("   ", "10_PRODUCT/PROD__LID ", "10_PRODUCT/ PROD__X"):
            with self.subTest(path=bad):
                data = copy.deepcopy(self.data)
                data["component_tree"].append(bad)
                self.assertIn("invalid-component-path", self._codes(data))

    def test_duplicate_json_keys_are_rejected_at_load(self) -> None:
        text = EXAMPLE.read_text(encoding="utf-8").replace(
            '"provisional": false,\n      "description": "Measured PD trigger board length."',
            '"provisional": true,\n      "provisional": false,\n      "description": "Measured PD trigger board length."',
            1,
        )
        with tempfile.TemporaryDirectory() as scratch:
            broken = Path(scratch) / "duplicate_key.json"
            broken.write_text(text, encoding="utf-8")
            with self.assertRaises(ManifestValidationError) as ctx:
                load_manifest(broken)
            self.assertIn("manifest-duplicate-key", str(ctx.exception))

    def test_free_text_claims_are_warned_about_on_every_prose_route(self) -> None:
        # These values are copied verbatim into the export index as
        # manufacturing_intent, so an invented claim here is re-served
        # downstream as if it were evidence. Advisory, never blocking.
        routes = (
            lambda d, text: d["printable_parts"][0]["orientation"].__setitem__("rationale", text),
            lambda d, text: d["printable_parts"][0]["protected_features"][0].__setitem__("description", text),
            lambda d, text: d["printable_parts"][0]["material"].__setitem__("assumption", text),
            lambda d, text: d["parameters"][0].__setitem__("description", text),
            lambda d, text: d["sources"][0].__setitem__("notes", text),
            lambda d, text: d["references"][0].__setitem__("no_keepout_rationale", text),
            lambda d, text: d["material_decision"].__setitem__("rationale", text),
            lambda d, text: d["material_decision"].__setitem__("printer_requirements", text),
            lambda d, text: d["material_decision"].__setitem__("unresolved_risks", [text]),
        )
        for index, mutate in enumerate(routes):
            with self.subTest(route=index):
                data = copy.deepcopy(self.data)
                mutate(data, "The flat floor sits on the plate and prints without supports.")
                hits = [i for i in validate_manifest_data(data) if i.code == "forbidden-claim-text"]
                self.assertTrue(hits, "route did not reach the claim lint")
                self.assertEqual(["warning"], sorted({i.severity for i in hits}))

        # Advisory only: on a pure-prose route it must not block loading.
        data = copy.deepcopy(self.data)
        data["printable_parts"][0]["orientation"]["rationale"] = "It prints without supports."
        self.assertEqual([], [i for i in validate_manifest_data(data) if i.severity == "error"])

    def test_claim_lint_does_not_fire_on_legitimate_authoring(self) -> None:
        # Deliberately NOT drawn from the example manifest and not written
        # against the patterns: text an author would plausibly write, including
        # the doctrine the code comment itself states.
        for text in (
            "This face requires no support scarring, so keep the seam elsewhere.",
            "Do not record print time in this manifest; it belongs to the slicer.",
            "Support placement is the slicer's decision, not ours.",
            "Choose an orientation that keeps the bridge under 5 mm.",
            "The rim is a mating face; scarring it changes the fit.",
            "Wall thickness follows the nozzle, not a folklore 2 mm rule.",
        ):
            with self.subTest(text=text):
                data = copy.deepcopy(self.data)
                data["printable_parts"][0]["orientation"]["rationale"] = text
                self.assertNotIn("forbidden-claim-text", self._codes(data))

    def _with_variants(self, *variants):
        data = copy.deepcopy(self.data)
        data["variants"] = list(variants)
        return data

    def test_two_whitespace_equivalent_base_parameters_are_one_duplicate(self) -> None:
        # A variant strips the names it overrides, so it cannot tell these two
        # apart: one override would be substituted into both parameter entries
        # and restoration would write one captured expression to both.
        data = self._with_variants(
            {"id": "small", "description": "Compact.", "parameters": {"des_corner_radius": "3 mm"}}
        )
        twin = copy.deepcopy(
            next(entry for entry in data["parameters"] if entry["name"] == "des_corner_radius")
        )
        twin["name"] = " des_corner_radius "
        data["parameters"].append(twin)

        issues = validate_manifest_data(data)
        self.assertIn("duplicate-parameter-name", [issue.code for issue in issues])
        self.assertIn(
            "'des_corner_radius' is duplicated",
            " ".join(issue.message for issue in issues),
        )

    def test_manifest_without_variants_is_still_valid(self) -> None:
        self.assertNotIn("variants", self.data)
        self.assertEqual([], validate_manifest_data(self.data))

    def test_parameter_set_and_configuration_variants_both_validate(self) -> None:
        data = self._with_variants(
            {"id": "small", "description": "Compact enclosure.", "parameters": {"des_corner_radius": "3 mm"}},
            {"id": "family_a", "description": "Named Fusion configuration.", "configuration": "Family A"},
        )
        self.assertEqual([], validate_manifest_data(data))

    def test_a_variant_declares_exactly_one_source(self) -> None:
        both = self._with_variants(
            {
                "id": "small",
                "description": "Both sources.",
                "parameters": {"des_corner_radius": "3 mm"},
                "configuration": "Family A",
            }
        )
        self.assertIn("variant-source-ambiguous", self._codes(both))

        neither = self._with_variants({"id": "small", "description": "No source."})
        self.assertIn("variant-source-missing", self._codes(neither))

        empty = self._with_variants({"id": "small", "description": "Empty override.", "parameters": {}})
        self.assertIn("variant-source-missing", self._codes(empty))

    def test_variant_identity_rules(self) -> None:
        duplicate = self._with_variants(
            {"id": "small", "description": "One.", "parameters": {"des_corner_radius": "3 mm"}},
            {"id": "small", "description": "Two.", "parameters": {"des_corner_radius": "8 mm"}},
        )
        self.assertIn("variant-duplicate-id", self._codes(duplicate))

        bad_id = self._with_variants(
            {"id": "not-a-name", "description": "One.", "parameters": {"des_corner_radius": "3 mm"}}
        )
        self.assertIn("invalid-variant-id", self._codes(bad_id))

        for field in ("id", "description"):
            missing = self._with_variants(
                {"id": "small", "description": "One.", "parameters": {"des_corner_radius": "3 mm"}}
            )
            missing["variants"][0][field] = "  "
            self.assertIn("variant-field-required", self._codes(missing), field)

    def test_a_variant_may_not_introduce_or_break_a_parameter(self) -> None:
        unknown = self._with_variants(
            {"id": "small", "description": "One.", "parameters": {"des_invented": "3 mm"}}
        )
        self.assertIn("variant-unknown-parameter", self._codes(unknown))

        for expression in ("   ", 3, None, {"value": "3 mm"}):
            blank = self._with_variants(
                {"id": "small", "description": "One.", "parameters": {"des_corner_radius": expression}}
            )
            self.assertIn("variant-invalid-expression", self._codes(blank), repr(expression))

    def test_variant_structure_is_a_closed_world(self) -> None:
        unknown_field = self._with_variants(
            {
                "id": "small",
                "description": "One.",
                "parameters": {"des_corner_radius": "3 mm"},
                "surprise": True,
            }
        )
        self.assertIn("unknown-manifest-field", self._codes(unknown_field))

        data = copy.deepcopy(self.data)
        data["variants"] = {"not": "a list"}
        self.assertIn("variants-must-be-list", self._codes(data))

        self.assertIn("variant-must-be-object", self._codes(self._with_variants("small")))

        not_an_object = self._with_variants({"id": "small", "description": "One.", "parameters": ["a"]})
        self.assertIn("variant-parameters-must-be-object", self._codes(not_an_object))

        blank_configuration = self._with_variants(
            {"id": "small", "description": "One.", "configuration": "  "}
        )
        self.assertIn("variant-invalid-configuration", self._codes(blank_configuration))

    def test_variant_parameter_names_are_normalized_the_same_on_both_sides(self) -> None:
        from fusion_design.variants import variant_parameter_overrides

        variant = {
            "id": "small",
            "description": "Padded name.",
            "parameters": {" des_corner_radius ": "3 mm"},
        }
        self.assertNotIn("variant-unknown-parameter", self._codes(self._with_variants(variant)))
        self.assertEqual({"des_corner_radius": "3 mm"}, variant_parameter_overrides(variant))

        collapsing = self._with_variants(
            {
                "id": "small",
                "description": "Two names, one parameter.",
                "parameters": {"des_corner_radius": "3 mm", "des_corner_radius ": "8 mm"},
            }
        )
        self.assertIn("variant-duplicate-parameter", self._codes(collapsing))

    def test_variant_enum_fields_reject_unhashable_values_without_crashing(self) -> None:
        # A dict where a parameter name belongs must be a validation issue, not
        # a TypeError escaping the CLI's ok/issues contract.
        data = self._with_variants(
            {"id": "small", "description": "One.", "parameters": {"des_corner_radius": {"a": 1}}}
        )
        self.assertIn("variant-invalid-expression", self._codes(data))

    def test_a_matrix_larger_than_the_declared_maximum_is_rejected(self) -> None:
        from fusion_design.manifest import MAXIMUM_VARIANTS

        variants = [
            {"id": f"v{index}", "description": "One.", "parameters": {"des_corner_radius": f"{index + 1} mm"}}
            for index in range(MAXIMUM_VARIANTS + 1)
        ]
        self.assertIn("variants-exceed-maximum", self._codes(self._with_variants(*variants)))
        self.assertNotIn("variants-exceed-maximum", self._codes(self._with_variants(*variants[:-1])))
    def test_claim_lint_is_advisory_and_its_gaps_are_documented(self) -> None:
        # Pinning the incompleteness rather than pretending it away. Every one
        # of these asserts a print outcome and every one walks through: the
        # false-negative surface is unbounded, which is precisely why the check
        # is a warning and why patterns must not be piled on to hide it.
        for evasion in (
            "The flat floor prints support-free.",
            "Supports are unnecessary in this orientation.",
            "The part is printed without supports.",
            "No support material is needed here.",
            "Supports will not be required for this face.",
            "Se imprime sin soportes.",
        ):
            with self.subTest(evasion=evasion):
                data = copy.deepcopy(self.data)
                data["printable_parts"][0]["orientation"]["rationale"] = evasion
                self.assertNotIn("forbidden-claim-text", self._codes(data))

    def test_manifest_that_asserts_nothing_is_recorded(self) -> None:
        empty = {
            "schema_version": 1,
            "project": copy.deepcopy(self.data["project"]),
            "sources": [],
            "parameters": [],
            "component_tree": [],
            "references": [],
            "verification": {
                "required_components": [],
                "clearance_checks": [],
                "interference_checks": [],
                "expected_print_parts": [],
            },
        }
        issues = validate_manifest_data(empty)
        self.assertEqual([], [i for i in issues if i.severity == "error"])
        floor = [i for i in issues if i.code == "manifest-asserts-nothing"]
        self.assertEqual(1, len(floor), issues)
        self.assertEqual("warning", floor[0].severity)
        # The example asserts plenty; the floor must not fire on it.
        self.assertNotIn("manifest-asserts-nothing", self._codes(self.data))

    def test_zero_clearance_minimum_is_no_constraint_at_all(self) -> None:
        for minimum in (0, 0.0, -0.0):
            with self.subTest(minimum=minimum):
                data = copy.deepcopy(self.data)
                data["verification"]["clearance_checks"][0]["minimum_mm"] = minimum
                self.assertIn("invalid-clearance-minimum", self._codes(data))

    def test_ids_must_be_written_the_way_they_are_validated(self) -> None:
        # scripts.py writes source_id raw into the Fusion provenance comment,
        # the same argument that already applied to parameter names.
        for mutate, expected in (
            (lambda d: d["parameters"][0].__setitem__("source_id", "pd_trigger_board_measurement "),
             "invalid-parameter-source-id"),
            (lambda d: d["sources"][0].__setitem__("id", "pd_trigger_board_measurement "),
             "invalid-source-id"),
            (lambda d: d["references"][0].__setitem__("id", "pd_trigger "), "invalid-reference-id"),
            (lambda d: d["references"][0].__setitem__("source_id", "pd_trigger_board_measurement "),
             "invalid-reference-source-id"),
        ):
            with self.subTest(expected=expected):
                data = copy.deepcopy(self.data)
                mutate(data)
                self.assertIn(expected, self._codes(data))

    def test_a_guess_may_not_self_declare_strong_confidence(self) -> None:
        # conservative_proxy's entire semantic content is "this is a guess"; the
        # per-kind cap generalizes the scan carve-out instead of special-casing.
        data = copy.deepcopy(self.data)
        data["sources"][0].update(kind="conservative_proxy", confidence="verified_cad")
        self.assertIn("parameter-confidence-exceeds-source", self._codes(data))

        data["sources"][0]["confidence"] = "coupon_verified"
        self.assertNotIn("parameter-confidence-exceeds-source", self._codes(data))

    def test_part_may_not_claim_coupon_verified_past_the_project_decision(self) -> None:
        # The part-level rule ranks status against the source the *part* cites
        # and never against the decision governing the same material.
        data = copy.deepcopy(self.data)
        self.assertEqual("provisional", data["material_decision"]["confidence"])
        data["printable_parts"][0]["material"]["status"] = "coupon_verified"
        data["printable_parts"][0]["material"]["source_id"] = "enclosure_material_requirements"
        self.assertIn("material-decision-part-outranks-decision", self._codes(data))

    def test_provisional_starting_assumptions_compose_with_the_confidence_rule(self) -> None:
        """The example's five sourced provisionals against the provenance rule.

        Those parameters previously carried no source_id at all, which made the
        confidence rule short-circuit on them. Now that they cite a
        conservative_proxy source, the rule is live -- so pin both directions.
        """
        sourced = (
            "clr_rigid_xy",
            "clr_rigid_z",
            "fab_wall_thickness",
            "fab_fit_clearance",
            "pack_usb_c_straight_departure",
        )
        for name in sourced:
            parameter = next(p for p in self.data["parameters"] if p["name"] == name)
            self.assertEqual("provisional_starting_assumptions", parameter["source_id"])
            self.assertTrue(parameter["provisional"], name)

        # Declared provisional against a provisional source: satisfied.
        self.assertNotIn("parameter-confidence-exceeds-source", self._codes(self.data))

        # Settling one without settling its source is refused.
        data = copy.deepcopy(self.data)
        next(p for p in data["parameters"] if p["name"] == "fab_wall_thickness")["provisional"] = False
        self.assertIn("parameter-confidence-exceeds-source", self._codes(data))

        # And the source cannot be talked up to launder them: the kind cap holds
        # a conservative_proxy at provisional however it labels itself.
        data = copy.deepcopy(self.data)
        next(s for s in data["sources"] if s["id"] == "provisional_starting_assumptions")[
            "confidence"
        ] = "measured"
        for name in sourced:
            next(p for p in data["parameters"] if p["name"] == name)["provisional"] = False
        self.assertIn("parameter-confidence-exceeds-source", self._codes(data))

        # A printed and measured coupon is what settles them.
        next(s for s in data["sources"] if s["id"] == "provisional_starting_assumptions")[
            "confidence"
        ] = "coupon_verified"
        self.assertNotIn("parameter-confidence-exceeds-source", self._codes(data))

    def test_which_roles_must_cite_provenance_when_critical(self) -> None:
        """The per-role table. A critical value is either a claim about the
        world (cite something) or a choice the author made (nothing to cite).

        This is the documentation for the decision: change the table here and
        in PROVENANCE_REQUIRED_ROLES together, or not at all.
        """
        from fusion_design.manifest import PROVENANCE_REQUIRED_ROLES, ROLE_PREFIXES

        requires_provenance = {
            "source": True,  # a measured or published dimension
            "clearance": True,  # functional spacing: a fit claim against something real
            "fabrication": True,  # process capability; "2 mm wall" is folklore alone
            "packing": True,  # dynamic/service space: a physical envelope
            "design": False,  # preference; a corner radius is measured against nothing
            "derived": False,  # computed, so its provenance is its inputs
        }
        # Every role is covered, and the table is the constant.
        self.assertEqual(set(ROLE_PREFIXES), set(requires_provenance))
        self.assertEqual(
            {role for role, required in requires_provenance.items() if required},
            PROVENANCE_REQUIRED_ROLES,
        )

        for role, required in requires_provenance.items():
            for provisional in (False, True):
                with self.subTest(role=role, provisional=provisional):
                    data = copy.deepcopy(self.data)
                    data["parameters"] = [
                        {
                            "name": f"{ROLE_PREFIXES[role]}probe",
                            "expression": "1 mm",
                            "units": "mm",
                            "role": role,
                            "critical": True,
                            "provisional": provisional,
                            "description": "Probe parameter carrying no source_id.",
                        }
                    ]
                    codes = self._codes(data)
                    # provisional must not buy an exemption: "not settled yet"
                    # is not the same claim as "rests on nothing".
                    self.assertEqual(
                        required,
                        "critical-parameter-missing-source" in codes,
                        f"role={role} provisional={provisional} -> {sorted(codes)}",
                    )

        # Not critical: nothing is required of any role.
        for role in requires_provenance:
            with self.subTest(role=role, critical=False):
                data = copy.deepcopy(self.data)
                data["parameters"] = [
                    {
                        "name": f"{ROLE_PREFIXES[role]}probe",
                        "expression": "1 mm",
                        "units": "mm",
                        "role": role,
                        "critical": False,
                        "provisional": False,
                        "description": "Probe parameter carrying no source_id.",
                    }
                ]
                self.assertNotIn("critical-parameter-missing-source", self._codes(data))

    def test_empty_string_source_id_is_not_provenance(self) -> None:
        # The shape the #36 reviewer proved loads, validates and plans clean.
        data = copy.deepcopy(self.data)
        data["parameters"] = [
            {
                "name": "clr_probe",
                "expression": "1 mm",
                "units": "mm",
                "role": "clearance",
                "source_id": "",
                "critical": True,
                "provisional": False,
                "description": "Critical clearance citing an empty source id.",
            }
        ]
        self.assertIn("critical-parameter-missing-source", self._codes(data))

    def test_schema_json_stays_in_lockstep_with_validator_constants(self) -> None:
        from fusion_design.manifest import (
            CLAIM_CONFIDENCE_RANK,
            CONTACT_FACES,
            DRYING_STATES,
            MATERIAL_DECISION_FIELDS,
            MATERIAL_FAMILIES,
            MATERIAL_STATUSES,
            NOZZLE_MATERIALS,
            PRINT_AS_VALUES,
            PRINTABLE_PART_FIELDS,
            PRINTABLE_PART_REQUIRED_FIELDS,
            PROTECTED_FEATURE_KINDS,
            PROVENANCE_REQUIRED_ROLES,
            REFERENCE_REPRESENTATIONS,
            ROLE_PREFIXES,
            SOURCE_CONFIDENCES,
            SOURCE_KINDS,
            SUPPORT_POLICIES,
            SUPPORT_REGION_KINDS,
        )

        schema = json.loads((ROOT / "schema" / "fusion-project.schema.json").read_text(encoding="utf-8"))
        part = schema["$defs"]["printable_part"]

        self.assertEqual(SOURCE_KINDS, set(schema["$defs"]["source"]["properties"]["kind"]["enum"]))
        self.assertEqual(
            SOURCE_CONFIDENCES, set(schema["$defs"]["source"]["properties"]["confidence"]["enum"])
        )
        # Every confidence must be rankable, or a new enum value silently ranks
        # as provisional and quietly blocks every claim that cites it.
        self.assertEqual(SOURCE_CONFIDENCES, set(CLAIM_CONFIDENCE_RANK))
        self.assertEqual(
            REFERENCE_REPRESENTATIONS,
            set(schema["$defs"]["reference"]["properties"]["representation"]["enum"]),
        )
        self.assertEqual(set(ROLE_PREFIXES), set(schema["$defs"]["parameter"]["properties"]["role"]["enum"]))
        self.assertEqual(
            PROVENANCE_REQUIRED_ROLES,
            set(schema["$defs"]["parameter"]["allOf"][0]["if"]["properties"]["role"]["enum"]),
        )
        # A zero minimum cannot fail, so the schema must exclude it too.
        self.assertEqual(
            {"type": "number", "exclusiveMinimum": 0},
            schema["$defs"]["clearance_check"]["properties"]["minimum_mm"],
        )
        # coupon_verified carries a provenance obligation in both artifacts.
        self.assertIn(
            {
                "if": {
                    "properties": {"material": {"properties": {"status": {"const": "coupon_verified"}}, "required": ["status"]}},
                    "required": ["material"],
                },
                "then": {"properties": {"material": {"required": ["source_id"]}}},
            },
            part["allOf"],
        )
        self.assertIn("printable_parts", schema["properties"])
        self.assertEqual(PRINTABLE_PART_FIELDS, set(part["properties"]))
        self.assertEqual(PRINTABLE_PART_REQUIRED_FIELDS, set(part["required"]))
        self.assertEqual(PRINT_AS_VALUES, set(part["properties"]["print_as"]["enum"]))
        verification = schema["$defs"]["verification"]
        self.assertIn("allowed_suppressed_paths", verification["properties"])
        self.assertIn("allow_suppressed_timeline_features", verification["properties"])
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
        self.assertEqual(
            NOZZLE_MATERIALS | {None}, set(decision["properties"]["nozzle"]["enum"])
        )
        self.assertEqual(DRYING_STATES | {None}, set(decision["properties"]["drying"]["enum"]))
        # Property names and enums are not enough: the coupon-verified /
        # coupon_verified drift got through a check that pinned only those. Pin
        # requiredness against what the validator actually rejects when absent.
        required_by_validator = {
            field
            for field in MATERIAL_DECISION_FIELDS
            if any(
                issue.path.startswith("material_decision")
                for issue in validate_manifest_data(self._with_decision(**{field: _OMIT}))
            )
        }
        self.assertEqual(set(decision["required"]), required_by_validator)

        from fusion_design.manifest import MAXIMUM_VARIANTS, VARIANT_FIELDS, VARIANT_SOURCES

        variant = schema["$defs"]["variant"]
        self.assertIn("variants", schema["properties"])
        self.assertEqual(MAXIMUM_VARIANTS, schema["properties"]["variants"]["maxItems"])
        self.assertEqual(VARIANT_FIELDS, set(variant["properties"]))
        self.assertEqual(
            VARIANT_SOURCES,
            {required for branch in variant["oneOf"] for required in branch["required"]},
        )

    def test_load_manifest_raises_with_all_issues(self) -> None:
        data = copy.deepcopy(self.data)
        data["parameters"][0].pop("source_id")
        with tempfile.TemporaryDirectory() as scratch:
            broken = Path(scratch) / "broken_manifest.json"
            broken.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ManifestValidationError) as ctx:
                load_manifest(broken)
            self.assertIn("critical-parameter-missing-source", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
