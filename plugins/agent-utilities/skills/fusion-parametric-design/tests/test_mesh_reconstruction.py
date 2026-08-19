from __future__ import annotations

import copy
import unittest

from fusion_design.manifest import ManifestValidationError
from fusion_design.mesh_reconstruction import (
    Classification,
    classification_from_record,
    classify,
    require_classification,
)

from test_mesh_source import BREP_SOURCE, mesh_source


def request(**overrides) -> dict:
    payload = {"edit_kind": "dimensional", "watertight": True, "facet_count": 4200}
    payload.update(overrides)
    return payload


def codes(callable_) -> set[str]:
    try:
        callable_()
    except ManifestValidationError as error:
        return {issue.code for issue in error.issues}
    raise AssertionError("expected the classification to be refused")


class ClassificationPathTests(unittest.TestCase):
    def test_each_path_is_selected_for_its_archetype(self) -> None:
        designed = mesh_source(provenance="designed_export")
        cases = (
            (request(edit_kind="cosmetic-local"), "mesh-edit"),
            (request(edit_kind="clearance-only"), "mesh-edit"),
            (request(edit_kind="boolean-mechanical", facet_count=3800, facet_budget=10000), "faceted-brep"),
            (
                request(edit_kind="boolean-mechanical", facet_count=48000, facet_budget=10000),
                "parametric-rebuild",
            ),
            (
                request(edit_kind="boolean-mechanical", watertight=False, facet_count=800, facet_budget=10000),
                "parametric-rebuild",
            ),
            (request(edit_kind="dimensional"), "parametric-rebuild"),
            (request(edit_kind="structural"), "parametric-rebuild"),
        )
        for payload, expected in cases:
            with self.subTest(edit_kind=payload["edit_kind"], facet_count=payload["facet_count"]):
                classification = classify(payload, designed)
                self.assertEqual(expected, classification.path)
                self.assertTrue(classification.rationale.strip())

    def test_the_inputs_that_drove_the_choice_are_recorded(self) -> None:
        classification = classify(
            request(edit_kind="boolean-mechanical", facet_budget=9000),
            mesh_source(brep_source=copy.deepcopy(BREP_SOURCE)),
        )
        self.assertEqual(
            {
                "edit_kind": "boolean-mechanical",
                "provenance": "capture",
                "watertight": True,
                "facet_count": 4200,
                "facet_budget": 9000,
                "brep_source_available": True,
            },
            classification.inputs,
        )

    def test_a_faceted_result_is_never_called_parametric(self) -> None:
        classification = classify(
            request(edit_kind="boolean-mechanical", facet_count=100, facet_budget=5000),
            mesh_source(provenance="designed_export"),
        )
        self.assertEqual("faceted-brep", classification.path)
        self.assertIn("faceted, never parametric", classification.rationale)

    def test_a_capture_keeps_fitted_values_provisional_and_a_brep_source_is_preferred(self) -> None:
        classification = classify(request(), mesh_source(brep_source=copy.deepcopy(BREP_SOURCE)))
        self.assertIn("provisional", classification.rationale)
        self.assertIn("B-Rep source", classification.rationale)
        self.assertNotIn("provisional", classify(request(), mesh_source(provenance="designed_export")).rationale)


class ClassificationRefusalTests(unittest.TestCase):
    def test_a_malformed_request_is_refused_with_named_codes(self) -> None:
        source = mesh_source()
        self.assertIn(
            "classification-invalid-edit-kind",
            codes(lambda: classify(request(edit_kind="polish"), source)),
        )
        self.assertIn(
            "classification-invalid-edit-kind",
            codes(lambda: classify(request(edit_kind={"nested": 1}), source)),
        )
        self.assertIn(
            "classification-invalid-watertight",
            codes(lambda: classify(request(watertight="yes"), source)),
        )
        self.assertIn(
            "classification-invalid-facet-count",
            codes(lambda: classify(request(facet_count=-1), source)),
        )
        self.assertIn(
            "classification-invalid-facet-count",
            codes(lambda: classify(request(facet_count=True), source)),
        )
        self.assertIn("unknown-manifest-field", codes(lambda: classify(request(hopes=1), source)))
        self.assertIn(
            "classification-request-must-be-object",
            codes(lambda: classify("dimensional", source)),
        )

    def test_the_facet_budget_is_declared_only_where_it_decides(self) -> None:
        source = mesh_source()
        self.assertIn(
            "classification-invalid-facet-budget",
            codes(lambda: classify(request(edit_kind="boolean-mechanical"), source)),
        )
        self.assertIn(
            "classification-invalid-facet-budget",
            codes(lambda: classify(request(edit_kind="dimensional", facet_budget=1000), source)),
        )

    def test_an_invalid_source_record_refuses_the_classification(self) -> None:
        self.assertIn(
            "mesh-source-invalid-provenance",
            codes(lambda: classify(request(), mesh_source(provenance="scan"))),
        )


class ClassificationRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.classification = classify(request(), mesh_source())
        self.record = self.classification.to_dict()

    def test_the_record_round_trips(self) -> None:
        self.assertEqual(self.classification, classification_from_record(self.record))
        self.assertEqual(self.record, classification_from_record(self.record).to_dict())

    def test_an_empty_rationale_is_rejected(self) -> None:
        for value in ("", "   ", None, 12):
            with self.subTest(value=value):
                record = dict(self.record, rationale=value)
                self.assertIn(
                    "classification-rationale-required",
                    codes(lambda record=record: classification_from_record(record)),
                )

    def test_an_unknown_or_unhashable_path_is_rejected(self) -> None:
        for value in ("auto-surface", {"nested": 1}, ["mesh-edit"], None):
            with self.subTest(value=value):
                record = dict(self.record, path=value)
                self.assertIn(
                    "classification-unknown-path",
                    codes(lambda record=record: classification_from_record(record)),
                )

    def test_the_recorded_inputs_must_be_complete(self) -> None:
        record = copy.deepcopy(self.record)
        record["inputs"].pop("watertight")
        self.assertIn(
            "classification-inputs-required",
            codes(lambda: classification_from_record(record)),
        )
        self.assertIn(
            "unknown-manifest-field",
            codes(lambda: classification_from_record(dict(self.record, inputs=dict(self.record["inputs"], vibes=1)))),
        )
        self.assertIn(
            "classification-inputs-required",
            codes(lambda: classification_from_record(dict(self.record, inputs="all of them"))),
        )

    def test_unknown_record_fields_and_non_objects_are_rejected(self) -> None:
        self.assertIn(
            "unknown-manifest-field",
            codes(lambda: classification_from_record(dict(self.record, decided_by="vibes"))),
        )
        self.assertIn(
            "classification-must-be-object",
            codes(lambda: classification_from_record("parametric-rebuild")),
        )


class ClassificationGateTests(unittest.TestCase):
    def test_an_unclassified_geometry_operation_refuses_to_run(self) -> None:
        self.assertIn(
            "classification-required",
            codes(lambda: require_classification(None, "mesh-convert")),
        )

    def test_a_recorded_classification_opens_the_gate(self) -> None:
        record = classify(request(), mesh_source()).to_dict()
        gated = require_classification(record, "mesh-convert")
        self.assertIsInstance(gated, Classification)
        self.assertEqual("parametric-rebuild", gated.path)


if __name__ == "__main__":
    unittest.main()
