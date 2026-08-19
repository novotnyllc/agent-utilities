from __future__ import annotations

from contextlib import redirect_stdout
import copy
from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from fusion_design.manifest import Manifest, ManifestValidationError
from fusion_design.mesh_convert import emit_mesh_convert_script, validate_convert_spec
from fusion_design.mesh_deviation import emit_mesh_deviation_script, validate_deviation_spec
from fusion_design.mesh_reconstruction import (
    Classification,
    classification_from_record,
    classify,
    require_classification,
)

from test_mesh_source import BREP_SOURCE, mesh_source
from test_scripts import load_generated_script


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "electronics-enclosure" / "fusion-project.json"


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
                "source_id": "scan_bracket",
                "source_sha256": "a" * 64,
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


    def test_a_record_whose_path_contradicts_its_inputs_is_refused(self) -> None:
        # The inputs describe a watertight, in-budget boolean-mechanical edit,
        # which is faceted-brep. A record claiming parametric-rebuild for those
        # same inputs is a faceted result reported as a parametric one.
        faceted = classify(
            request(edit_kind="boolean-mechanical", facet_count=100, facet_budget=5000),
            mesh_source(provenance="designed_export"),
        )
        self.assertEqual("faceted-brep", faceted.path)
        forged = dict(faceted.to_dict(), path="parametric-rebuild", rationale="rebuilt parametrically")
        self.assertIn(
            "classification-path-contradicts-inputs",
            codes(lambda: classification_from_record(forged)),
        )

    def test_recorded_input_values_are_checked_on_the_way_out(self) -> None:
        for field, value in (
            ("edit_kind", "vibes"),
            ("provenance", "unicorn"),
            ("watertight", "yes"),
            ("facet_count", -5),
            ("brep_source_available", "maybe"),
            ("source_id", "2bad"),
            ("source_sha256", "nope"),
        ):
            with self.subTest(field=field):
                record = copy.deepcopy(self.record)
                record["inputs"][field] = value
                self.assertIn(
                    "classification-invalid-inputs",
                    codes(lambda record=record: classification_from_record(record)),
                )

    def test_the_number_that_decides_the_faceted_path_cannot_be_omitted(self) -> None:
        record = classify(
            request(edit_kind="boolean-mechanical", facet_count=100, facet_budget=5000),
            mesh_source(),
        ).to_dict()
        record["inputs"].pop("facet_budget")
        self.assertIn(
            "classification-invalid-inputs",
            codes(lambda: classification_from_record(record)),
        )


class ClassificationGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = mesh_source()
        self.record = classify(request(), self.source).to_dict()

    def test_an_unclassified_geometry_operation_refuses_to_run(self) -> None:
        self.assertIn(
            "classification-required",
            codes(
                lambda: require_classification(
                    None, "mesh-convert", {"faceted-brep"}, self.source
                )
            ),
        )

    def test_a_recorded_classification_opens_the_gate(self) -> None:
        gated = require_classification(
            self.record, "mesh-rebuild", {"parametric-rebuild"}, self.source
        )
        self.assertIsInstance(gated, Classification)
        self.assertEqual("parametric-rebuild", gated.path)

    def test_a_path_that_does_not_permit_the_operation_is_refused(self) -> None:
        # Proving a decision exists is not proving it permits this operation.
        mesh_edit = classify(request(edit_kind="cosmetic-local"), self.source).to_dict()
        self.assertIn(
            "classification-path-forbids-operation",
            codes(
                lambda: require_classification(
                    mesh_edit, "mesh-convert-to-brep", {"faceted-brep"}, self.source
                )
            ),
        )
        self.assertIn(
            "classification-path-forbids-operation",
            codes(
                lambda: require_classification(
                    self.record, "mesh-convert-to-brep", {"faceted-brep"}, self.source
                )
            ),
        )

    def test_a_classification_decided_for_another_source_does_not_transfer(self) -> None:
        other = mesh_source(id="scan_lid", sha256="b" * 64)
        self.assertIn(
            "classification-source-mismatch",
            codes(
                lambda: require_classification(
                    self.record, "mesh-rebuild", {"parametric-rebuild"}, other
                )
            ),
        )

    def test_an_entry_point_must_declare_the_paths_it_implements(self) -> None:
        for allowed in (set(), {"auto-surface"}):
            with self.subTest(allowed=allowed):
                with self.assertRaises(ValueError):
                    require_classification(self.record, "mesh-rebuild", allowed, self.source)


def _manifest(source: dict) -> Manifest:
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data["mesh_sources"] = [source]
    return Manifest.from_data(data)


class _Bodies:
    def __init__(self, items=()):
        self._items = list(items)

    @property
    def count(self):
        return len(self._items)

    def item(self, index):
        return self._items[index]

    def append(self, body):
        self._items.append(body)

    def discard(self, body):
        if body in self._items:
            self._items.remove(body)


class _ObjectCollection:
    def __init__(self):
        self.items = []

    def add(self, item):
        self.items.append(item)


class _Feature:
    def __init__(self, bodies, created, complaint, health):
        self._bodies = bodies
        self._created = created
        self.errorOrWarningMessage = complaint
        self.healthState = health

    def deleteMe(self):
        for body in self._created:
            self._bodies.discard(body)
        return True


class _MeshConvertFeatures:
    """The live half of the ladder: what Fusion says, and what it produced."""

    def __init__(self, bodies, *, faces=8, complaint=None, health="healthy", returns_feature=True, creates=True):
        self.bodies = bodies
        self.faces = faces
        self.complaint = complaint
        self.health = health
        self.returns_feature = returns_feature
        self.creates = creates

    def createInput(self, collection, method):
        return SimpleNamespace(collection=collection, method=method)

    def add(self, convert_input):
        created = []
        if self.creates:
            body = SimpleNamespace(name="bracket_scan (Converted)", faces=SimpleNamespace(count=self.faces))
            self.bodies.append(body)
            created.append(body)
        if not self.returns_feature:
            # Documented: add() returns null for a non-parametric operation.
            return None
        return _Feature(self.bodies, created, self.complaint, self.health)


def _source_mesh_body(**overrides):
    body = {
        "name": "bracket_scan",
        "isClosed": True,
        "volume": 2.5,
        "isValid": True,
        "mesh": SimpleNamespace(triangleCount=800, triangleFaceGroupTempIds=[1, 1, 2, 2, 3, 3]),
    }
    body.update(overrides)
    return SimpleNamespace(**body)


CONVERT_SPEC = {
    "component_path": "",
    "body_name": "bracket_scan",
    "max_faces_per_face_group": 4.0,
    "rationale": "Three fitted face groups; more than four faces each means nothing selectable.",
}


def _faceted_record(source: dict) -> dict:
    return classify(
        request(edit_kind="boolean-mechanical", facet_count=800, facet_budget=10000), source
    ).to_dict()


class FacetedConversionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = mesh_source(provenance="designed_export")
        self.manifest = _manifest(self.source)
        self.record = _faceted_record(self.source)

    def _namespace(self, mesh_body, *, spec=None, version="2.0.20000", **feature_kwargs):
        script = emit_mesh_convert_script(
            self.manifest, self.record, self.source, spec or CONVERT_SPEC
        )
        compile(script, "<generated-fusion-script>", "exec")
        namespace = load_generated_script(script)
        brep = _Bodies()
        component = SimpleNamespace(
            meshBodies=_Bodies([mesh_body] if mesh_body is not None else []),
            bRepBodies=brep,
            features=SimpleNamespace(meshConvertFeatures=_MeshConvertFeatures(brep, **feature_kwargs)),
        )
        design = SimpleNamespace(rootComponent=component)
        app = SimpleNamespace(activeDocument=SimpleNamespace(name=self.manifest.fusion_document))
        if version is not None:
            app.version = version
        namespace["_active_design"] = lambda: (app, design)
        namespace["_root_context_occurrence_map"] = lambda root: ([], {}, {})
        namespace["adsk"].core.ObjectCollection = SimpleNamespace(create=_ObjectCollection)
        namespace["adsk"].fusion.MeshConvertMethodTypes = SimpleNamespace(
            FacetedMeshConvertMethodType="faceted"
        )
        namespace["_component"] = component
        return namespace

    def _run(self, namespace, failure=None):
        output = StringIO()
        if failure is None:
            with redirect_stdout(output):
                namespace["run"](None)
        else:
            with redirect_stdout(output), self.assertRaisesRegex(RuntimeError, failure):
                namespace["run"](None)
        return [json.loads(line) for line in output.getvalue().splitlines() if line.startswith("{")]

    def test_a_low_facet_prismatic_mesh_converts_and_is_labeled_faceted(self) -> None:
        namespace = self._namespace(_source_mesh_body(), faces=8)
        report = self._run(namespace)[0]
        self.assertTrue(report["ok"])
        self.assertEqual("faceted", report["label"])
        self.assertFalse(report["parametric"])
        self.assertNotIn("parametric-rebuild", report["classification"]["path"])
        self.assertEqual(3, report["editability"]["face_groups"])
        self.assertEqual(8, report["editability"]["faces"])
        self.assertIn("faceted, never parametric", report["note"])
        self.assertEqual(1, namespace["_component"].bRepBodies.count)

    def test_each_refusal_names_its_reason_and_creates_no_geometry(self) -> None:
        cases = (
            (None, "not-convertible-source"),
            (_source_mesh_body(isClosed=False), "not-watertight"),
            (_source_mesh_body(volume=0.0), "non-positive-volume"),
            (_source_mesh_body(mesh=None), "mesh-evidence-unavailable"),
        )
        for mesh_body, expected in cases:
            with self.subTest(reason=expected):
                namespace = self._namespace(mesh_body)
                report = self._run(namespace, failure=expected)[0]
                self.assertFalse(report["ok"])
                self.assertIn(expected, report["failures"])
                self.assertIsNone(report["label"])
                self.assertEqual(0, report["bodies_created"])
                self.assertEqual(0, namespace["_component"].bRepBodies.count)
                reasons = {refusal["reason"] for refusal in report["refusals"]}
                self.assertIn(expected, reasons)
                for refusal in report["refusals"]:
                    self.assertTrue(refusal["alternative"].strip())

    def test_fusions_own_complaint_is_quoted_rather_than_a_hardcoded_ceiling(self) -> None:
        namespace = self._namespace(
            _source_mesh_body(mesh=SimpleNamespace(triangleCount=480000, triangleFaceGroupTempIds=[1] * 6)),
            complaint="The mesh body is too dense to convert.",
        )
        report = self._run(namespace, failure="fusion-refused-conversion")[0]
        refusal = next(r for r in report["refusals"] if r["reason"] == "fusion-refused-conversion")
        self.assertEqual("The mesh body is too dense to convert.", refusal["detail"]["errorOrWarningMessage"])
        self.assertEqual(0, namespace["_component"].bRepBodies.count)
        self.assertIn("no facet ceiling is hardcoded", refusal["alternative"])

    def test_an_unhealthy_convert_feature_is_refused_and_rolled_back(self) -> None:
        namespace = self._namespace(_source_mesh_body(), health="error")
        report = self._run(namespace, failure="fusion-refused-conversion")[0]
        self.assertEqual("error", next(
            r for r in report["refusals"] if r["reason"] == "fusion-refused-conversion"
        )["detail"]["healthState"])
        self.assertEqual(0, namespace["_component"].bRepBodies.count)

    def test_unselectable_facets_are_a_poor_outcome_not_a_success(self) -> None:
        namespace = self._namespace(_source_mesh_body(), faces=9000)
        report = self._run(namespace, failure="not-editable")[0]
        self.assertFalse(report["ok"])
        self.assertIsNone(report["label"])
        self.assertEqual(3000.0, report["editability"]["faces_per_face_group"])
        self.assertEqual(4.0, report["editability"]["declared_max_faces_per_face_group"])
        self.assertEqual(0, namespace["_component"].bRepBodies.count)

    def test_a_null_feature_return_is_handled_rather_than_assumed(self) -> None:
        report = self._run(self._namespace(_source_mesh_body(), returns_feature=False))[0]
        self.assertTrue(report["ok"])
        self.assertFalse(report["feature_object_returned"])

    def test_a_conversion_that_produced_nothing_is_not_a_success(self) -> None:
        report = self._run(
            self._namespace(_source_mesh_body(), returns_feature=False, creates=False),
            failure="conversion-produced-nothing",
        )[0]
        self.assertIn("conversion-produced-nothing", report["failures"])

    def test_an_unhealthy_feature_with_no_message_is_never_reported_successful(self) -> None:
        # The named failure mode of this whole feature: a faceted result reported
        # as a successful conversion because the health rung quietly disabled.
        namespace = self._namespace(_source_mesh_body(), health="error", complaint=None)
        report = self._run(namespace, failure="fusion-refused-conversion")[0]
        self.assertFalse(report["ok"])
        self.assertIsNone(report["label"])
        self.assertEqual(0, namespace["_component"].bRepBodies.count)

    def test_a_missing_health_enum_fails_closed_rather_than_disabling_the_rung(self) -> None:
        namespace = self._namespace(_source_mesh_body(), health="error")
        namespace["adsk"].fusion.FeatureHealthStates = SimpleNamespace()
        report = self._run(namespace, failure="mesh-convert capability is unavailable")[0]
        self.assertEqual(["mesh-convert-capability"], report["failures"])
        self.assertIn(
            "adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState",
            report["missing_capabilities"],
        )

    def test_a_body_surviving_rollback_is_re_enumerated_not_assumed_gone(self) -> None:
        # add() returned null, so there is no feature to delete, and a body whose
        # own deleteMe silently does nothing must be reported rather than inferred
        # away from the absence of an exception.
        namespace = self._namespace(_source_mesh_body(), faces=9000, returns_feature=False)
        features = namespace["_component"].features.meshConvertFeatures
        original_add = features.add

        def add_undeletable(convert_input):
            result = original_add(convert_input)
            body = namespace["_component"].bRepBodies.item(0)
            body.deleteMe = lambda: True
            return result

        features.add = add_undeletable
        report = self._run(namespace, failure="not-editable")[0]
        self.assertIn("cleanup-incomplete", report["failures"])
        self.assertEqual(1, report["bodies_created"])
        self.assertEqual(["bracket_scan (Converted)"], report["surviving_bodies"])

    def test_a_missing_preview_feature_class_fails_closed(self) -> None:
        namespace = self._namespace(_source_mesh_body())
        namespace["adsk"].fusion.MeshConvertMethodTypes = None
        report = self._run(namespace, failure="mesh-convert capability is unavailable")[0]
        self.assertEqual(["mesh-convert-capability"], report["failures"])
        self.assertIn(
            "adsk.fusion.MeshConvertMethodTypes.FacetedMeshConvertMethodType",
            report["missing_capabilities"],
        )

    def test_a_source_mesh_that_did_not_survive_is_a_failure(self) -> None:
        # False and unreadable both fail: absent is not proof the source survived.
        for value in (False, None):
            with self.subTest(is_valid=value):
                body = _source_mesh_body()
                if value is None:
                    del body.isValid
                else:
                    body.isValid = value
                report = self._run(self._namespace(body), failure="consumed the source mesh")[0]
                self.assertEqual(["source-mesh-consumed"], report["failures"])

    def test_a_conversion_that_cannot_record_the_fusion_version_fails_closed(self) -> None:
        namespace = self._namespace(_source_mesh_body(), version=None)
        report = self._run(namespace, failure="mesh-convert capability is unavailable")[0]
        self.assertIn("Application.version", report["missing_capabilities"])

    def test_the_gate_refuses_a_conversion_the_classification_did_not_choose(self) -> None:
        rebuild = classify(request(edit_kind="dimensional"), self.source).to_dict()
        self.assertIn(
            "classification-path-forbids-operation",
            codes(lambda: emit_mesh_convert_script(self.manifest, rebuild, self.source, CONVERT_SPEC)),
        )
        self.assertIn(
            "classification-required",
            codes(lambda: emit_mesh_convert_script(self.manifest, None, self.source, CONVERT_SPEC)),
        )

    def test_the_editability_ceiling_is_declared_never_defaulted(self) -> None:
        for value in (None, 0, -1.0, "four", float("inf")):
            with self.subTest(value=value):
                spec = dict(CONVERT_SPEC, max_faces_per_face_group=value)
                self.assertIn(
                    "convert-spec-invalid-editability",
                    {issue.code for issue in validate_convert_spec(spec)},
                )
        self.assertIn(
            "convert-spec-invalid-binding",
            {issue.code for issue in validate_convert_spec(dict(CONVERT_SPEC, body_name="  "))},
        )
        self.assertIn(
            "unknown-manifest-field",
            {issue.code for issue in validate_convert_spec(dict(CONVERT_SPEC, hopes=1))},
        )


def _point(x, y, z, index):
    # Tagged so the fake pointContainment can answer per node, the way a real
    # B-Rep query answers per point.
    return SimpleNamespace(x=x, y=y, z=z, index=index)


def _containment(kinds):
    def query(node):
        return kinds[node.index] if node.index < len(kinds) else "on-boundary"

    return query


class _PolygonMesh:
    """A PolygonMesh whose compareWith answers for one direction only.

    ``comparable=False`` omits the attribute entirely, which is what a Fusion
    without the preview API looks like.
    """

    def __init__(self, nodes_mm, distances_mm=None, *, comparable=True):
        self.nodeCoordinates = [
            _point(x / 10.0, y / 10.0, z / 10.0, index) for index, (x, y, z) in enumerate(nodes_mm)
        ]
        if comparable:
            self.compareWith = _compare_with(distances_mm)


def _compare_with(distances_mm):
    def compare(other, transform, transform_other):
        if distances_mm is None:
            raise RuntimeError("compareWith rejected these meshes")
        return [value / 10.0 for value in distances_mm]

    return compare


DEVIATION_SPEC = {
    "source": {"component_path": "", "body_name": "bracket_scan"},
    "reconstruction": {"component_path": "", "body_name": "bracket_rebuild"},
    "thresholds_mm": {
        "invented_material": 0.05,
        "omitted_detail": 0.25,
        "percentile_sample_limit": 20000,
    },
    "rationale": "Printed fit is held to 0.05 mm; scanned fillets below 0.25 mm are not modelled.",
}


class DeviationVerdictTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = mesh_source()
        self.manifest = _manifest(self.source)
        self.record = classify(request(edit_kind="dimensional"), self.source).to_dict()

    def _namespace(
        self,
        *,
        recon_distances,
        source_distances,
        compare=True,
        containment=("inside", "inside", "inside"),
        point_containment=True,
        containment_enum=True,
    ):
        script = emit_mesh_deviation_script(
            self.manifest, self.record, self.source, DEVIATION_SPEC
        )
        compile(script, "<generated-fusion-script>", "exec")
        namespace = load_generated_script(script)
        source_mesh = _PolygonMesh(
            [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0)], source_distances, comparable=compare
        )
        recon_mesh = _PolygonMesh(
            [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (5.0, 5.0, 9.0)], recon_distances, comparable=compare
        )
        source_body = SimpleNamespace(name="bracket_scan", mesh=source_mesh)
        recon_body = SimpleNamespace(
            name="bracket_rebuild",
            meshManager=SimpleNamespace(displayMeshes=SimpleNamespace(bestMesh=recon_mesh)),
        )
        if point_containment:
            recon_body.pointContainment = _containment(containment)
        component = SimpleNamespace(
            meshBodies=_Bodies([source_body]), bRepBodies=_Bodies([recon_body])
        )
        design = SimpleNamespace(rootComponent=component)
        app = SimpleNamespace(
            version="2.0.20000",
            activeDocument=SimpleNamespace(name=self.manifest.fusion_document),
        )
        namespace["_active_design"] = lambda: (app, design)
        namespace["_root_context_occurrence_map"] = lambda root: ([], {}, {})
        if containment_enum:
            namespace["adsk"].fusion.PointContainment = SimpleNamespace(
                PointOutsidePointContainment="outside",
                PointInsidePointContainment="inside",
            )
        return namespace

    def _run(self, namespace, failure=None):
        output = StringIO()
        if failure is None:
            with redirect_stdout(output):
                namespace["run"](None)
        else:
            with redirect_stdout(output), self.assertRaisesRegex(RuntimeError, failure):
                namespace["run"](None)
        return [json.loads(line) for line in output.getvalue().splitlines() if line.startswith("{")]

    def test_material_outside_the_source_fails_and_names_the_location(self) -> None:
        report = self._run(
            self._namespace(
                recon_distances=[0.0, -0.01, 0.9],
                source_distances=[0.0, -0.01, -0.9],
            ),
            failure="invented material",
        )[0]
        self.assertFalse(report["ok"])
        self.assertEqual(["invented-material"], report["failures"])
        verdict = report["verdict"]["invented_material"]
        self.assertEqual("failure", verdict["severity"])
        self.assertEqual(1, verdict["count"])
        self.assertAlmostEqual(0.9, verdict["max_mm"])
        self.assertEqual([5.0, 5.0, 9.0], verdict["worst_points"][0]["point_mm"])

    def test_a_rebuild_missing_a_boss_is_advisory_not_a_failure(self) -> None:
        # The scan carries a boss the rebuild did not model: source points sit
        # far from the reconstruction, while every rebuilt point sits on the
        # scan, so the wall beneath the dropped boss is not invented material.
        report = self._run(
            self._namespace(
                recon_distances=[0.0, -0.004, -0.002],
                source_distances=[0.0, -0.002, -3.4],
                containment=("inside", "inside", "outside"),
            )
        )[0]
        self.assertTrue(report["ok"])
        self.assertEqual([], report["failures"])
        self.assertEqual("pass", report["verdict"]["invented_material"]["severity"])
        omitted = report["verdict"]["omitted_detail"]
        self.assertEqual("advisory", omitted["severity"])
        self.assertEqual(1, omitted["count"])
        self.assertEqual([10.0, 10.0, 0.0], omitted["worst_points"][0]["point_mm"])

    def test_the_two_directions_are_reported_distinctly_and_never_collapsed(self) -> None:
        report = self._run(
            self._namespace(
                recon_distances=[0.0, -0.004, -0.002],
                source_distances=[0.0, -0.002, -3.4],
                containment=("inside", "inside", "outside"),
            )
        )[0]
        forward = report["reconstruction_to_source"]
        backward = report["source_to_reconstruction"]
        self.assertNotEqual(forward["question"], backward["question"])
        self.assertNotEqual(forward["max_abs_mm"], backward["max_abs_mm"])
        self.assertIn("stayed on the scan", forward["question"])
        self.assertIn("captured what was scanned", backward["question"])
        self.assertIn("neither certifies the other", report["verdict_note"])
        self.assertNotIn("deviation_mm", report)

    def test_the_declared_thresholds_and_their_rationale_are_recorded(self) -> None:
        report = self._run(
            self._namespace(
                recon_distances=[0.0, -0.004, -0.002], source_distances=[0.0, 0.0, -0.9]
            )
        )[0]
        self.assertEqual(DEVIATION_SPEC["thresholds_mm"], report["declared_thresholds_mm"])
        self.assertEqual(DEVIATION_SPEC["rationale"], report["threshold_rationale"])
        self.assertEqual(0.05, report["verdict"]["invented_material"]["threshold_mm"])
        self.assertEqual(0.25, report["verdict"]["omitted_detail"]["threshold_mm"])

    def test_native_containment_answers_the_omitted_direction_when_available(self) -> None:
        report = self._run(
            self._namespace(
                recon_distances=[0.0, -0.004, -0.002],
                source_distances=[0.0, -0.002, -3.4],
                containment=("inside", "inside", "outside"),
            )
        )[0]
        backward = report["source_to_reconstruction"]
        self.assertEqual("BRepBody.pointContainment", backward["containment_query"])
        self.assertEqual(1, backward["nodes_outside_reconstruction_solid"])

    def test_an_inverted_sign_convention_reaches_the_same_verdict(self) -> None:
        # Identical geometry to the invented-material case with every distance
        # negated: the same blob is still invented. Reading the sign off the
        # native containment query is what makes both runs agree; assuming
        # positive-is-outside turns this one into a pass.
        report = self._run(
            self._namespace(
                recon_distances=[0.0, 0.01, -0.9],
                source_distances=[0.0, 0.01, 0.9],
            ),
            failure="invented material",
        )[0]
        verdict = report["verdict"]["invented_material"]
        self.assertEqual("negative-is-outside", verdict["sign_convention"])
        self.assertEqual("failure", verdict["severity"])
        self.assertAlmostEqual(0.9, verdict["max_mm"])
        self.assertEqual([5.0, 5.0, 9.0], verdict["worst_points"][0]["point_mm"])

    def test_an_unreadable_sign_convention_yields_no_passing_severity(self) -> None:
        # The containment query and the signs disagree, so which sign means
        # outside is unknown. A premise this run cannot verify must never produce
        # a green severity.
        report = self._run(
            self._namespace(
                recon_distances=[0.0, -0.01, 0.9],
                source_distances=[-0.9, 0.9, -0.9],
                containment=("inside", "inside", "outside"),
            ),
            failure="sign-convention-unestablished",
        )[0]
        self.assertFalse(report["ok"])
        self.assertEqual(["sign-convention-unestablished"], report["failures"])
        verdict = report["verdict"]["invented_material"]
        self.assertEqual("not-established", verdict["severity"])
        self.assertEqual("unestablished", verdict["sign_convention"])
        # No zero anyone could misread as "nothing was invented".
        self.assertNotIn("count", verdict)
        self.assertNotIn("max_mm", verdict)

    def test_a_verdict_within_tolerance_needs_no_sign_convention(self) -> None:
        # Nothing clears the threshold in either direction, so no sign reading
        # could change the answer and none is demanded.
        report = self._run(
            self._namespace(
                recon_distances=[0.0, -0.004, 0.002], source_distances=[0.0, 0.0, 0.0]
            )
        )[0]
        self.assertTrue(report["ok"])
        self.assertEqual("pass", report["verdict"]["invented_material"]["severity"])
        self.assertIn("not required", report["verdict"]["invented_material"]["sign_convention"])

    def test_a_missing_containment_enum_is_a_capability_failure_not_a_clean_result(self) -> None:
        # Nothing equals a None enum, so the sum would be 0 and the report would
        # assert the native query ran and found nothing outside.
        report = self._run(
            self._namespace(
                recon_distances=[0.0, -0.004, -0.002],
                source_distances=[0.0, -0.002, -3.4],
                containment=("inside", "inside", "outside"),
                containment_enum=False,
            ),
            failure="Deviation verdict unsupported",
        )[0]
        self.assertFalse(report["ok"])
        self.assertEqual(["deviation-capability"], report["failures"])
        self.assertIn(
            "adsk.fusion.PointContainment.PointOutsidePointContainment",
            report["missing_capabilities"],
        )
        self.assertNotIn("source_to_reconstruction", report)
        self.assertNotIn("verdict", report)

    def test_a_reconstruction_without_the_containment_query_fails_closed(self) -> None:
        report = self._run(
            self._namespace(
                recon_distances=[0.0, -0.004, -0.002],
                source_distances=[0.0, -0.002, -3.4],
                point_containment=False,
            ),
            failure="Deviation verdict unsupported",
        )[0]
        self.assertEqual(["deviation-capability"], report["failures"])
        self.assertIn("BRepBody.pointContainment", report["missing_capabilities"])

    def test_a_missing_compare_with_fails_closed_naming_the_api_and_version(self) -> None:
        report = self._run(
            self._namespace(recon_distances=[0.0], source_distances=[0.0], compare=False),
            failure="Deviation verdict unsupported",
        )[0]
        self.assertFalse(report["ok"])
        self.assertEqual(["deviation-capability"], report["failures"])
        self.assertIn("PolygonMesh.compareWith", report["unsupported"])
        self.assertIn("2.0.20000", report["unsupported"])
        self.assertIn("UI-only", report["unsupported"])
        self.assertNotIn("verdict", report)

    def test_an_unsigned_comparison_cannot_establish_invented_material(self) -> None:
        report = self._run(
            self._namespace(recon_distances=[0.0, 0.004, 0.002], source_distances=[0.0, 0.0, 3.4]),
            failure="deviation-unsigned-comparison",
        )[0]
        self.assertFalse(report["ok"])
        self.assertEqual(["deviation-unsigned-comparison"], report["failures"])
        self.assertEqual("not-established", report["verdict"]["invented_material"]["severity"])
        self.assertIn("NOT established", report["verdict"]["invented_material"]["meaning"])
        # The other direction is still measured and still reported.
        self.assertEqual("advisory", report["verdict"]["omitted_detail"]["severity"])

    def test_percentiles_may_be_sampled_but_the_threshold_comparison_is_not(self) -> None:
        spec = copy.deepcopy(DEVIATION_SPEC)
        spec["thresholds_mm"]["percentile_sample_limit"] = 2
        script = emit_mesh_deviation_script(self.manifest, self.record, self.source, spec)
        namespace = load_generated_script(script)
        distances = [-0.001] * 40 + [0.9]
        source_mesh = _PolygonMesh([(0.0, 0.0, 0.0)] * 41, [-0.001] * 40 + [-0.9])
        recon_mesh = _PolygonMesh([(float(index), 0.0, 0.0) for index in range(41)], distances)
        component = SimpleNamespace(
            meshBodies=_Bodies([SimpleNamespace(name="bracket_scan", mesh=source_mesh)]),
            bRepBodies=_Bodies(
                [
                    SimpleNamespace(
                        name="bracket_rebuild",
                        meshManager=SimpleNamespace(displayMeshes=SimpleNamespace(bestMesh=recon_mesh)),
                        pointContainment=_containment(("inside",) * 41),
                    )
                ]
            ),
        )
        app = SimpleNamespace(
            version="2.0.20000", activeDocument=SimpleNamespace(name=self.manifest.fusion_document)
        )
        namespace["_active_design"] = lambda: (app, SimpleNamespace(rootComponent=component))
        namespace["_root_context_occurrence_map"] = lambda root: ([], {}, {})
        namespace["adsk"].fusion.PointContainment = SimpleNamespace(
            PointOutsidePointContainment="outside", PointInsidePointContainment="inside"
        )
        report = self._run(namespace, failure="invented material")[0]
        self.assertTrue(report["reconstruction_to_source"]["percentiles_sampled"])
        # The single point beyond the threshold is caught by the exact scan even
        # though the sampled percentiles never see it.
        self.assertEqual(1, report["verdict"]["invented_material"]["count"])

    def test_the_gate_refuses_a_verdict_for_a_mesh_edit(self) -> None:
        mesh_edit = classify(request(edit_kind="clearance-only"), self.source).to_dict()
        self.assertIn(
            "classification-path-forbids-operation",
            codes(lambda: emit_mesh_deviation_script(self.manifest, mesh_edit, self.source, DEVIATION_SPEC)),
        )

    def test_thresholds_are_declared_per_reconstruction_never_defaulted(self) -> None:
        codes_for = lambda spec: {issue.code for issue in validate_deviation_spec(spec)}
        missing = copy.deepcopy(DEVIATION_SPEC)
        missing["thresholds_mm"].pop("invented_material")
        self.assertIn("deviation-spec-invalid-thresholds", codes_for(missing))
        blank = copy.deepcopy(DEVIATION_SPEC)
        blank["rationale"] = "  "
        self.assertIn("deviation-spec-invalid-rationale", codes_for(blank))
        bad_limit = copy.deepcopy(DEVIATION_SPEC)
        bad_limit["thresholds_mm"]["percentile_sample_limit"] = 0
        self.assertIn("deviation-spec-invalid-thresholds", codes_for(bad_limit))
        no_binding = copy.deepcopy(DEVIATION_SPEC)
        no_binding.pop("reconstruction")
        self.assertIn("deviation-spec-invalid-binding", codes_for(no_binding))
        self.assertIn("unknown-manifest-field", codes_for(dict(DEVIATION_SPEC, hopes=1)))


if __name__ == "__main__":
    unittest.main()
