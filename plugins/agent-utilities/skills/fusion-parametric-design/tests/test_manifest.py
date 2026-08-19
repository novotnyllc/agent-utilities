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

        # A stronger claim is allowed only when it is bound by both a coupon and
        # a recorded risk.
        bound = self._with_decision(
            source_id="enclosure_material_requirements",
            confidence="coupon_verified",
            unresolved_risks=["Snap-rim cycle life is still unproven."],
        )
        self.assertNotIn("material-decision-outranks-source", self._codes(bound))

        # A measured source carries a measured decision without complaint.
        self.assertEqual([], validate_manifest_data(self._with_decision()))

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

    def test_schema_json_stays_in_lockstep_with_validator_constants(self) -> None:
        from fusion_design.manifest import (
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
            SOURCE_CONFIDENCES,
            SUPPORT_POLICIES,
            SUPPORT_REGION_KINDS,
        )

        schema = json.loads((ROOT / "schema" / "fusion-project.schema.json").read_text(encoding="utf-8"))
        part = schema["$defs"]["printable_part"]
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
