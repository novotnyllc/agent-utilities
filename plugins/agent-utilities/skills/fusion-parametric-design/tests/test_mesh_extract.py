from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from fusion_design.manifest import ManifestValidationError
from fusion_design.mesh_dump import _SHARED_SOURCE, assemble_inline_dump, parse_mesh_dump, read_mesh_dump
from fusion_design.mesh_extract import (
    dump_file_name,
    emit_mesh_extract_script,
    validate_extract_spec,
)
from fusion_design.mesh_reconstruction import classify

from test_mesh_reconstruction import _manifest, request
from test_mesh_source import mesh_source
from test_scripts import load_generated_script


EXTRACT_SPEC = {
    "component_path": "",
    "body_name": "bracket_scan",
    "dump_dir": "/replaced/per/test",
    "max_triangles": 200000,
    "max_triangles_rationale": (
        "Above this density the extra triangles are noise samples rather than recoverable design, "
        "and fit-driven splitting is superlinear in the base count."
    ),
    "fallback_max_bytes": 4000000,
    "fallback_max_bytes_rationale": (
        "The stdout report protocol is the transport of last resort; beyond this the report itself "
        "becomes the failure, so refuse instead of truncating."
    ),
}

# The welded unit square again, but in Fusion's internal centimetres.
NODES_CM = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0))
TRIANGLES = (0, 1, 2, 0, 2, 3)


class _Mesh:
    """Stands in for PolygonMesh; records whether the coordinate array was touched."""

    def __init__(self, nodes=NODES_CM, indices=TRIANGLES, groups=(4, 4), triangle_count=None):
        self._nodes = nodes
        self._indices = indices
        self.triangleFaceGroupTempIds = list(groups) if groups is not None else None
        self.triangleCount = len(indices) // 3 if triangle_count is None else triangle_count
        self.coordinates_touched = False

    @property
    def nodeCoordinates(self):
        self.coordinates_touched = True
        return [SimpleNamespace(x=node[0], y=node[1], z=node[2]) for node in self._nodes]

    @property
    def triangleNodeIndices(self):
        return list(self._indices)


class _Bodies:
    def __init__(self, items=()):
        self._items = list(items)

    @property
    def count(self):
        return len(self._items)

    def item(self, index):
        return self._items[index]


def _mesh_body(mesh=None, *, name="bracket_scan", transform=True, is_valid=True):
    body = SimpleNamespace(name=name, mesh=mesh if mesh is not None else _Mesh(), isValid=is_valid)
    if transform:
        body.transform = SimpleNamespace(
            asArray=lambda: [
                1.0, 0.0, 0.0, 0.0,
                0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0,
                2.0, 0.0, 0.0, 1.0,
            ]
        )
    return body


def spec(**overrides) -> dict:
    value = copy.deepcopy(EXTRACT_SPEC)
    value.update(overrides)
    return value


def codes(callable_) -> set[str]:
    try:
        callable_()
    except ManifestValidationError as error:
        return {issue.code for issue in error.issues}
    raise AssertionError("expected the extraction to be refused")


class ExtractSpecValidationTests(unittest.TestCase):
    def test_a_spec_must_be_an_object_with_a_known_vocabulary(self) -> None:
        self.assertEqual(
            {"extract-spec-must-be-object"}, {issue.code for issue in validate_extract_spec("bracket")}
        )
        self.assertIn(
            "unknown-manifest-field",
            {issue.code for issue in validate_extract_spec(spec(hopes=1))},
        )

    def test_every_declared_limit_needs_a_value_and_a_rationale(self) -> None:
        cases = {
            "extract-spec-invalid-budget": spec(max_triangles=0),
            "extract-spec-invalid-budget-rationale": spec(max_triangles_rationale="  "),
            "extract-spec-invalid-fallback-ceiling": spec(fallback_max_bytes=True),
            "extract-spec-invalid-fallback-rationale": spec(fallback_max_bytes_rationale=None),
            "extract-spec-invalid-dump-dir": spec(dump_dir=""),
        }
        for code, payload in cases.items():
            with self.subTest(code=code):
                self.assertIn(code, {issue.code for issue in validate_extract_spec(payload)})

    def test_the_body_binding_is_required_because_the_manifest_cannot_supply_it(self) -> None:
        broken = spec()
        del broken["body_name"]
        self.assertIn(
            "extract-spec-invalid-binding", {issue.code for issue in validate_extract_spec(broken)}
        )

    def test_the_dump_name_is_derived_from_the_source_it_came_from(self) -> None:
        self.assertEqual("scan_bracket-aaaaaaaaaaaa.meshdump", dump_file_name(mesh_source()))


class ExtractGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = mesh_source(provenance="designed_export")
        self.manifest = _manifest(self.source)

    def test_a_faceted_classification_does_not_open_the_extraction_gate(self) -> None:
        faceted = classify(
            request(edit_kind="boolean-mechanical", facet_count=800, facet_budget=10000), self.source
        ).to_dict()
        self.assertIn(
            "classification-path-forbids-operation",
            codes(lambda: emit_mesh_extract_script(self.manifest, faceted, self.source, spec())),
        )

    def test_extraction_refuses_without_any_classification_at_all(self) -> None:
        self.assertIn(
            "classification-required",
            codes(lambda: emit_mesh_extract_script(self.manifest, None, self.source, spec())),
        )

    def test_a_classification_decided_for_another_mesh_does_not_transfer(self) -> None:
        other = classify(request(), mesh_source(id="other_scan", sha256="c" * 64)).to_dict()
        self.assertIn(
            "classification-source-mismatch",
            codes(lambda: emit_mesh_extract_script(self.manifest, other, self.source, spec())),
        )


class _Harness(unittest.TestCase):
    """Shared rig: a manifest, a parametric-rebuild classification, and a dump directory."""

    def setUp(self) -> None:
        self.source = mesh_source(provenance="designed_export")
        self.manifest = _manifest(self.source)
        self.record = classify(request(edit_kind="dimensional"), self.source).to_dict()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.dump_dir = Path(self.directory.name) / "dumps"

    def _script(self, **overrides) -> str:
        payload = spec(dump_dir=str(self.dump_dir))
        payload.update(overrides)
        return emit_mesh_extract_script(self.manifest, self.record, self.source, payload)

    def _namespace(self, mesh_body, *, version="2.0.20000", **overrides):
        script = self._script(**overrides)
        compile("WRAPPER_CONTEXT = None\n" + script + "\nrun(WRAPPER_CONTEXT)\n", "<wrapped>", "exec")
        namespace = load_generated_script(script)
        component = SimpleNamespace(
            meshBodies=_Bodies([mesh_body] if mesh_body is not None else [])
        )
        design = SimpleNamespace(rootComponent=component)
        app = SimpleNamespace(activeDocument=SimpleNamespace(name=self.manifest.fusion_document))
        if version is not None:
            app.version = version
        namespace["_active_design"] = lambda: (app, design)
        namespace["_root_context_occurrence_map"] = lambda root: ([], {}, {})
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


class ExtractEmissionTests(_Harness):
    def test_the_generated_transaction_carries_the_shared_packer_verbatim(self) -> None:
        self.assertIn(_SHARED_SOURCE, self._script())

    def test_the_generated_transaction_creates_nothing(self) -> None:
        script = self._script()
        # Named individually so a failure says which mutation appeared.
        for verb in (
            "deleteMe",
            "createInput",
            "baseFeatures",
            "computeAll",
            "TemporaryBRepManager",
            "meshConvertFeatures",
            "sketches.add",
            "extrudeFeatures",
        ):
            self.assertNotIn(verb, script, verb)

    def test_a_mesh_extracts_into_a_dump_the_host_reader_accepts(self) -> None:
        body = _mesh_body()
        report = self._run(self._namespace(body))[0]
        self.assertTrue(report["ok"], report)
        self.assertEqual("file", report["transport"])
        self.assertEqual(2, report["triangle_count"])
        self.assertEqual(4, report["vertex_count"])

        dump = read_mesh_dump(report["dump_path"], report["dump_sha256"])
        # Written in millimetres: Fusion reports centimetres internally.
        self.assertEqual(
            (0.0, 0.0, 0.0, 10.0, 0.0, 0.0, 10.0, 10.0, 0.0, 0.0, 10.0, 0.0), dump.vertices_mm
        )
        self.assertEqual(TRIANGLES, dump.triangles)
        self.assertEqual({4: 2}, dump.face_group_histogram())
        self.assertEqual("mm", dump.metadata["vertex_units"])
        self.assertEqual(self.source["sha256"], dump.metadata["mesh_source_sha256"])
        self.assertEqual("MeshBody.transform", dump.metadata["transform_source"])
        self.assertEqual(2.0, dump.metadata["transform"][12])

        self.assertEqual(1, report["face_groups"]["group_count"])
        self.assertTrue(report["face_groups"]["single_group"])
        self.assertEqual(1, report["dihedral_statistics"]["interior_edge_count"])
        self.assertTrue(report["connectivity_statistics"]["welded"])
        self.assertEqual(
            [
                "mesh-body-bound",
                "triangle-budget",
                "mesh-arrays-read",
                "face-groups-read",
                "dump-written-and-reread",
                "dihedral-statistics",
                "connectivity-statistics",
                "source-mesh-intact",
            ],
            report["checked"],
        )

    def test_the_reported_digest_is_the_digest_of_the_file_on_disk(self) -> None:
        report = self._run(self._namespace(_mesh_body()))[0]
        payload = Path(report["dump_path"]).read_bytes()
        self.assertEqual(report["dump_bytes"], len(payload))
        parse_mesh_dump(payload, report["dump_sha256"])

    def test_the_budget_refuses_before_a_single_coordinate_is_read(self) -> None:
        mesh = _Mesh(triangle_count=900000)
        report = self._run(
            self._namespace(_mesh_body(mesh), max_triangles=1000), "triangle-budget-exceeded"
        )[0]
        self.assertFalse(mesh.coordinates_touched)
        self.assertEqual(["triangle-budget-exceeded"], report["failures"])
        self.assertEqual(["mesh-body-bound"], report["checked"])
        self.assertEqual(900000, report["refusals"][0]["detail"]["triangle_count"])
        self.assertEqual(1000, report["refusals"][0]["detail"]["declared_max_triangles"])
        self.assertFalse(self.dump_dir.exists())

    def test_absent_face_groups_are_reported_absent_and_never_fabricated(self) -> None:
        report = self._run(self._namespace(_mesh_body(_Mesh(groups=None))))[0]
        self.assertEqual("absent", report["face_groups"]["source"])
        self.assertIn("no triangleFaceGroupTempIds", report["face_groups"]["reason"])
        self.assertNotIn("face-groups-read", report["checked"])
        dump = read_mesh_dump(report["dump_path"], report["dump_sha256"])
        self.assertIsNone(dump.face_group_ids)
        self.assertEqual("absent", dump.metadata["face_groups_source"])

    def test_a_partial_grouping_is_not_padded_into_a_grouping(self) -> None:
        report = self._run(self._namespace(_mesh_body(_Mesh(groups=(4,)))))[0]
        self.assertEqual("absent", report["face_groups"]["source"])
        self.assertIn("1 ids for 2 triangles", report["face_groups"]["reason"])
        self.assertIsNone(read_mesh_dump(report["dump_path"], report["dump_sha256"]).face_group_ids)

    def test_an_unreadable_transform_is_recorded_absent_rather_than_as_identity(self) -> None:
        report = self._run(self._namespace(_mesh_body(transform=False)))[0]
        self.assertEqual("unavailable", report["transform_source"])
        dump = read_mesh_dump(report["dump_path"], report["dump_sha256"])
        self.assertIsNone(dump.metadata["transform"])

    def test_each_refusal_names_its_reason_and_writes_nothing(self) -> None:
        cases = (
            (None, "source-not-found"),
            (SimpleNamespace(name="bracket_scan", isValid=True, mesh=None), "mesh-evidence-unavailable"),
            (_mesh_body(_Mesh(indices=(0, 1, 2, 0, 2))), "mesh-arrays-inconsistent"),
            (_mesh_body(_Mesh(indices=(0, 1, 9, 0, 2, 3))), "mesh-arrays-inconsistent"),
        )
        for body, failure in cases:
            with self.subTest(failure=failure):
                report = self._run(self._namespace(body), failure)[0]
                self.assertEqual([failure], report["failures"])
                self.assertIsNone(report["dump_sha256"])
                self.assertFalse(self.dump_dir.exists())

    def test_a_consumed_source_mesh_is_a_failure_even_though_the_dump_was_written(self) -> None:
        report = self._run(
            self._namespace(_mesh_body(is_valid=None)), "source-mesh-consumed"
        )[0]
        self.assertEqual(["source-mesh-consumed"], report["failures"])
        self.assertNotIn("source-mesh-intact", report["checked"])


class ExtractFallbackTests(_Harness):
    def setUp(self) -> None:
        super().setUp()
        # A regular file where the dump directory should be: makedirs will refuse.
        blocker = Path(self.directory.name) / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        self.dump_dir = blocker / "dumps"

    def test_an_unwritable_dump_directory_falls_back_to_hashed_stdout_chunks(self) -> None:
        report = self._run(self._namespace(_mesh_body()))[0]
        self.assertTrue(report["ok"], report)
        self.assertEqual("inline-base64", report["transport"])
        # The write failure is recorded, but it is not a refusal: the dump was
        # still transported, and calling it a refusal would overstate the failure.
        self.assertEqual([], report["refusals"])
        self.assertEqual("dump-write-unavailable", report["dump_write_fallback"]["reason"])
        self.assertIn("dump-inline-chunked", report["checked"])
        self.assertNotIn("dump-written-and-reread", report["checked"])

        payload = assemble_inline_dump(report)
        dump = parse_mesh_dump(payload, report["dump_sha256"])
        self.assertEqual(TRIANGLES, dump.triangles)
        self.assertEqual({4: 2}, dump.face_group_histogram())

    def test_the_fallback_refuses_above_its_declared_ceiling_rather_than_truncating(self) -> None:
        report = self._run(
            self._namespace(_mesh_body(), fallback_max_bytes=1), "dump-too-large-for-fallback"
        )[0]
        self.assertEqual(
            ["dump-too-large-for-fallback", "dump-write-unavailable"], report["failures"]
        )
        self.assertNotIn("dump_chunks", report)
        self.assertIsNone(report["transport"])


if __name__ == "__main__":
    unittest.main()


class ExtractReportTeeTests(unittest.TestCase):
    """The extraction report is written beside the dump, not only to stdout.

    The MCP transport gives up at 180 seconds and a mesh transaction on a real
    capture runs longer than that. A report only on stdout is a report the
    transport can throw away after the work is done.
    """

    def test_the_transaction_tees_its_report_into_its_own_declared_dump_dir(self) -> None:
        source = mesh_source(provenance="designed_export")
        manifest = _manifest(source)
        classification = classify(request(edit_kind="dimensional", facet_count=800), source).to_dict()
        script = emit_mesh_extract_script(manifest, classification, source, spec(dump_dir="/tmp/dumps"))
        self.assertIn("REPORT_TEE_DIR = '/tmp/dumps'", script)
        self.assertIn("def _report_tee_path(report):", script)
