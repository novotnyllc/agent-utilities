"""The segmentation transaction: the method is set, read back, and never inherited.

The failure this stage exists to prevent is not an exception. It is Fusion
grouping by its default Fast method, producing a solid it calls healthy that is
7.6% wrong on volume. So the tests here are about what the run *states*: which
method it applied, what it read back, and what it refuses to do when either
answer is not the one it asked for.
"""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import copy
import json
from types import SimpleNamespace
import unittest

from fusion_design.manifest import ManifestValidationError
from fusion_design.mesh_face_groups import (
    FACE_GROUP_METHOD,
    emit_mesh_face_groups_script,
    validate_face_group_spec,
)
from fusion_design.mesh_reconstruction import classify

from test_mesh_reconstruction import _manifest, request
from test_mesh_source import mesh_source
from test_scripts import load_generated_script


SPEC = {"component_path": "", "body_name": "bracket_scan"}

ACCURATE = "accurate"


def spec(**overrides) -> dict:
    value = copy.deepcopy(SPEC)
    value.update(overrides)
    return value


class _Mesh:
    """PolygonMesh: the grouping only appears once the feature has been added."""

    def __init__(self, triangle_count=8, groups_after=(0, 0, 0, 1, 1, 1, 2, 2)):
        self.triangleCount = triangle_count
        self._groups_after = None if groups_after is None else list(groups_after)
        self.triangleFaceGroupTempIds = None

    def apply(self):
        self.triangleFaceGroupTempIds = self._groups_after


class _Input:
    """MeshGenerateFaceGroupsFeatureInput. Keeps what it is given, like the real one."""

    def __init__(self, keeps=True, raises=False):
        object.__setattr__(self, "_keeps", keeps)
        object.__setattr__(self, "_raises", False)
        self.meshGenerateFaceGroupsMethodType = "fast"
        object.__setattr__(self, "_raises", raises)

    def __setattr__(self, name, value):
        if name == "meshGenerateFaceGroupsMethodType" and getattr(self, "_raises", False):
            raise RuntimeError("2 : InternalValidationError")
        if (
            name == "meshGenerateFaceGroupsMethodType"
            and not getattr(self, "_keeps", True)
        ):
            object.__setattr__(self, name, "fast")
            return
        object.__setattr__(self, name, value)


class _Features:
    def __init__(self, mesh, input_factory=_Input, add_raises=False):
        self._mesh = mesh
        self._input_factory = input_factory
        self._add_raises = add_raises
        self.added_with = None

    def createInput(self, mesh_body):
        # The real API takes the MeshBody itself; an ObjectCollection raises.
        assert getattr(mesh_body, "mesh", None) is not None, "createInput takes a MeshBody"
        self.bound_body = mesh_body
        return self._input_factory()

    def add(self, group_input):
        if self._add_raises:
            raise RuntimeError("Fusion refused the operation")
        self.added_with = group_input.meshGenerateFaceGroupsMethodType
        self._mesh.apply()
        # Documented: null for a non-parametric operation, even on success.
        return None


class _Bodies:
    def __init__(self, items=()):
        self._items = list(items)

    @property
    def count(self):
        return len(self._items)

    def item(self, index):
        return self._items[index]


class _FaceGroup:
    def __init__(self, temp_id, area_cm2, planar):
        self.tempId = temp_id
        self.area = area_cm2
        self.centroid = SimpleNamespace(x=1.0, y=2.0, z=3.0)
        self.boundingBox = SimpleNamespace(
            minPoint=SimpleNamespace(x=0.0, y=0.0, z=0.0),
            maxPoint=SimpleNamespace(x=1.0, y=1.0, z=1.0),
        )
        self.isPlanar = planar


class _Harness(unittest.TestCase):
    def setUp(self) -> None:
        self.source = mesh_source(provenance="designed_export")
        self.manifest = _manifest(self.source)
        self.record = classify(request(edit_kind="dimensional"), self.source).to_dict()

    def script(self, **overrides) -> str:
        return emit_mesh_face_groups_script(
            self.manifest, self.record, self.source, spec(**overrides)
        )

    def namespace(self, body, *, version="2.0.20000", methods=True):
        source = self.script()
        namespace = load_generated_script(source)
        if not methods:
            namespace["adsk"].fusion.MeshGenerateFaceGroupsMethodTypes = None
        component = SimpleNamespace(
            meshBodies=_Bodies([body] if body is not None else []),
            features=SimpleNamespace(
                meshGenerateFaceGroupsFeatures=getattr(body, "_features", None)
            ),
        )
        design = SimpleNamespace(rootComponent=component)
        app = SimpleNamespace(activeDocument=SimpleNamespace(name=self.manifest.fusion_document))
        if version is not None:
            app.version = version
        namespace["_active_design"] = lambda: (app, design)
        namespace["_root_context_occurrence_map"] = lambda root: ([], {}, {})
        return namespace

    def run_it(self, namespace, failure=None):
        output = StringIO()
        if failure is None:
            with redirect_stdout(output):
                namespace["run"](None)
        else:
            with redirect_stdout(output), self.assertRaisesRegex(RuntimeError, failure):
                namespace["run"](None)
        return [json.loads(line) for line in output.getvalue().splitlines() if line.startswith("{")]

    def body(self, *, mesh=None, groups=(), **feature_kwargs):
        mesh = mesh if mesh is not None else _Mesh()
        body = SimpleNamespace(
            name="bracket_scan",
            mesh=mesh,
            isValid=True,
            faceGroups=_Bodies(list(groups)),
        )
        body._features = _Features(mesh, **feature_kwargs)
        return body


class SpecValidationTests(_Harness):
    def test_a_spec_must_be_an_object_with_a_known_vocabulary(self) -> None:
        self.assertEqual(
            {"face-group-spec-must-be-object"},
            {issue.code for issue in validate_face_group_spec("bracket")},
        )
        self.assertIn(
            "unknown-manifest-field",
            {issue.code for issue in validate_face_group_spec(spec(method="fast"))},
        )

    def test_the_body_binding_is_required(self) -> None:
        self.assertIn(
            "face-group-spec-invalid-binding",
            {issue.code for issue in validate_face_group_spec({"component_path": ""})},
        )

    def test_a_classification_that_forbids_the_operation_refuses(self) -> None:
        faceted = classify(request(edit_kind="cosmetic-local"), self.source).to_dict()
        with self.assertRaises(ManifestValidationError) as caught:
            emit_mesh_face_groups_script(self.manifest, faceted, self.source, spec())
        self.assertIn(
            "classification-path-forbids-operation",
            {issue.code for issue in caught.exception.issues},
        )

    def test_the_classification_is_required_at_all(self) -> None:
        with self.assertRaises(ManifestValidationError) as caught:
            emit_mesh_face_groups_script(self.manifest, None, self.source, spec())
        self.assertIn("classification-required", {i.code for i in caught.exception.issues})


class EmissionTests(_Harness):
    def test_the_script_compiles_and_keeps_the_report_protocol(self) -> None:
        source = self.script()
        compile("WRAPPER_CONTEXT = None\n" + source + "\nrun(WRAPPER_CONTEXT)\n", "<w>", "exec")
        self.assertIn("FUSION_DESIGN_REPORT_BEGIN", source)
        self.assertIn("FUSION_DESIGN_REPORT_END", source)

    def test_the_accurate_method_is_named_in_the_emitted_source(self) -> None:
        source = self.script()
        self.assertIn("AccurateGenerateFaceGroupsType", source)
        self.assertNotIn("FastGenerateFaceGroupsType", source)
        self.assertEqual("AccurateGenerateFaceGroupsType", FACE_GROUP_METHOD)

    def test_the_transaction_starts_no_process(self) -> None:
        source = self.script()
        for forbidden in ("subprocess", "sys.executable", "os.system", "popen"):
            self.assertNotIn(forbidden, source, forbidden)

    def test_the_dead_numeric_knobs_are_never_touched(self) -> None:
        source = self.script()
        for knob in ("angleThreshold", "minimumFaceGroupSize", "boundaryTolerance"):
            self.assertNotIn(knob, source, knob)


class TransactionTests(_Harness):
    def test_a_clean_run_applies_the_accurate_method_and_reports_the_grouping(self) -> None:
        body = self.body(
            groups=[_FaceGroup(4, 2.5, True), _FaceGroup(5, 1.0, False), _FaceGroup(6, 0.5, True)]
        )
        report = self.run_it(self.namespace(body))[0]
        self.assertTrue(report["ok"], report)
        self.assertEqual(FACE_GROUP_METHOD, report["requested_method"])
        self.assertEqual(FACE_GROUP_METHOD, report["applied_method"])
        self.assertEqual(ACCURATE, body._features.added_with)
        self.assertEqual(3, report["group_count"])
        self.assertEqual({"0": 3, "1": 3, "2": 2}, report["triangles_per_group"])
        self.assertTrue(report["source_mesh_body_present"])

    def test_per_group_metadata_arrives_in_millimetres(self) -> None:
        body = self.body(groups=[_FaceGroup(4, 2.5, True), _FaceGroup(5, 1.0, False)])
        report = self.run_it(self.namespace(body))[0]
        first = report["face_groups"][0]
        self.assertEqual(4, first["temp_id"])
        # Fusion works in centimetres; an area scales by the square of the length.
        self.assertAlmostEqual(250.0, first["area_mm2"])
        self.assertEqual([10.0, 20.0, 30.0], first["centroid_mm"])
        self.assertEqual([[0.0, 0.0, 0.0], [10.0, 10.0, 10.0]], first["bounding_box_mm"])
        self.assertTrue(first["is_planar"])
        self.assertIsNone(report["face_groups_unavailable_reason"])

    def test_absent_group_metadata_is_named_never_counted_as_no_groups(self) -> None:
        body = self.body()
        del body.faceGroups
        report = self.run_it(self.namespace(body))[0]
        self.assertTrue(report["ok"])
        self.assertIsNone(report["face_groups"])
        self.assertIn("faceGroups", report["face_groups_unavailable_reason"])
        # The per-triangle grouping is what the pipeline needs, and it is there.
        self.assertEqual(3, report["group_count"])

    def test_an_input_that_does_not_keep_the_method_refuses(self) -> None:
        body = self.body(input_factory=lambda: _Input(keeps=False))
        report = self.run_it(self.namespace(body), failure="face-group-method-not-applied")[0]
        self.assertFalse(report["ok"])
        self.assertEqual("fast", report["applied_method"])
        self.assertIsNone(report["group_count"])
        self.assertIsNone(body._features.added_with)

    def test_an_unsettable_method_refuses_rather_than_running_the_default(self) -> None:
        body = self.body(input_factory=lambda: _Input(raises=True))
        report = self.run_it(self.namespace(body), failure="face-group-method-unsettable")[0]
        self.assertFalse(report["ok"])
        self.assertIsNone(body._features.added_with)

    def test_a_missing_capability_is_named_not_assumed_away(self) -> None:
        body = self.body()
        report = self.run_it(
            self.namespace(body, methods=False), failure="face-group-capability"
        )[0]
        self.assertIn(
            "adsk.fusion.MeshGenerateFaceGroupsMethodTypes.AccurateGenerateFaceGroupsType",
            report["missing_capabilities"],
        )

    def test_a_null_return_from_add_is_not_read_as_failure(self) -> None:
        """add() returns None for a non-parametric operation while still applying."""
        body = self.body()
        report = self.run_it(self.namespace(body))[0]
        self.assertTrue(report["ok"])
        self.assertEqual(3, report["group_count"])

    def test_a_grouping_that_does_not_cover_every_triangle_refuses(self) -> None:
        body = self.body(mesh=_Mesh(triangle_count=8, groups_after=(0, 0, 1)))
        report = self.run_it(self.namespace(body), failure="face-groups-partial")[0]
        self.assertFalse(report["ok"])

    def test_one_group_over_the_whole_body_refuses_here(self) -> None:
        body = self.body(mesh=_Mesh(groups_after=(0,) * 8))
        report = self.run_it(self.namespace(body), failure="face-groups-degenerate")[0]
        self.assertEqual(1, report["group_count"])

    def test_an_unreadable_grouping_after_the_feature_refuses(self) -> None:
        body = self.body(mesh=_Mesh(groups_after=None))
        report = self.run_it(self.namespace(body), failure="face-groups-unreadable")[0]
        self.assertFalse(report["ok"])

    def test_a_missing_body_is_a_binding_error(self) -> None:
        namespace = self.namespace(None)
        namespace["_active_design"]  # bound above
        component = SimpleNamespace(
            meshBodies=_Bodies([]),
            features=SimpleNamespace(meshGenerateFaceGroupsFeatures=_Features(_Mesh())),
        )
        design = SimpleNamespace(rootComponent=component)
        app = SimpleNamespace(
            version="2.0.20000",
            activeDocument=SimpleNamespace(name=self.manifest.fusion_document),
        )
        namespace["_active_design"] = lambda: (app, design)
        report = self.run_it(namespace, failure="source-not-found")[0]
        self.assertFalse(report["ok"])

    def test_a_consumed_source_mesh_is_a_failure(self) -> None:
        body = self.body()
        body.isValid = False
        report = self.run_it(self.namespace(body), failure="source-mesh-consumed")[0]
        self.assertFalse(report["source_mesh_body_present"])


if __name__ == "__main__":
    unittest.main()
