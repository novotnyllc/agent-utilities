from __future__ import annotations

from contextlib import redirect_stdout
import copy
from io import StringIO
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from fusion_design.manifest import Manifest, ManifestValidationError, validate_manifest_data
from fusion_design.mesh_source import (
    emit_mesh_capture_script,
    file_sha256,
    mesh_capture_specs,
    unit_source_reason,
    validate_mesh_source_record,
    verify_mesh_source_file,
)

from test_scripts import load_generated_script


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "electronics-enclosure" / "fusion-project.json"

IDENTITY = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]

MESH_SOURCE = {
    "id": "scan_bracket",
    "path": "sources/bracket.stl",
    "sha256": "a" * 64,
    "units": "mm",
    "unit_source": "guess",
    "unit_guess": {
        "heuristic": "bounding-box longest edge under the printable envelope",
        "threshold": 300.0,
    },
    "provenance": "capture",
    "alignment_transform": list(IDENTITY),
}

BREP_SOURCE = {
    "path": "sources/bracket.step",
    "sha256": "b" * 64,
    "trusted": False,
    "rationale": "The bundled STEP predates the shipped mesh, so the mesh stays authoritative.",
}


def mesh_source(**overrides) -> dict:
    record = copy.deepcopy(MESH_SOURCE)
    record.update(overrides)
    return record


def codes(record) -> set[str]:
    return {issue.code for issue in validate_mesh_source_record(record)}


class MeshSourceValidationTests(unittest.TestCase):
    def test_complete_record_validates(self) -> None:
        self.assertEqual([], validate_mesh_source_record(mesh_source()))
        self.assertEqual([], validate_mesh_source_record(mesh_source(brep_source=copy.deepcopy(BREP_SOURCE))))

    def test_missing_or_blank_unit_source_is_rejected(self) -> None:
        record = mesh_source()
        record.pop("unit_source")
        record.pop("unit_guess")
        self.assertIn("mesh-source-invalid-unit-source", codes(record))
        self.assertIn("mesh-source-invalid-unit-source", codes(mesh_source(unit_source="   ")))

    def test_guess_without_a_stated_heuristic_or_threshold_is_rejected(self) -> None:
        record = mesh_source()
        record.pop("unit_guess")
        self.assertIn("mesh-source-invalid-unit-guess", codes(record))
        self.assertIn(
            "mesh-source-invalid-unit-guess",
            codes(mesh_source(unit_guess={"heuristic": "  ", "threshold": 300.0})),
        )
        self.assertIn(
            "mesh-source-invalid-unit-guess",
            codes(mesh_source(unit_guess={"heuristic": "longest edge", "threshold": "big"})),
        )
        self.assertIn(
            "unknown-manifest-field",
            codes(mesh_source(unit_guess={"heuristic": "longest edge", "threshold": 1.0, "extra": 1})),
        )

    def test_unit_guess_is_rejected_when_the_unit_was_not_guessed(self) -> None:
        self.assertIn(
            "mesh-source-invalid-unit-guess",
            codes(mesh_source(unit_source="declared")),
        )

    def test_unknown_provenance_is_rejected(self) -> None:
        self.assertIn("mesh-source-invalid-provenance", codes(mesh_source(provenance="scan")))
        record = mesh_source()
        record.pop("provenance")
        self.assertIn("mesh-source-invalid-provenance", codes(record))

    def test_unhashable_values_in_every_enum_yield_issues_not_type_errors(self) -> None:
        cases = (
            ("units", "mesh-source-invalid-units"),
            ("unit_source", "mesh-source-invalid-unit-source"),
            ("provenance", "mesh-source-invalid-provenance"),
        )
        for field, expected in cases:
            for value in ({"nested": 1}, ["listed"]):
                with self.subTest(field=field, value=value):
                    self.assertIn(expected, codes(mesh_source(**{field: value})))

    def test_sha256_must_be_lowercase_hex_of_the_file_bytes(self) -> None:
        for value in ("A" * 64, "a" * 63, "", 12, {"a": 1}):
            with self.subTest(value=value):
                self.assertIn("mesh-source-invalid-sha256", codes(mesh_source(sha256=value)))

    def test_alignment_transform_must_be_sixteen_finite_numbers(self) -> None:
        for value in ([1.0] * 15, "identity", [1.0] * 15 + [float("nan")], [True] * 16):
            with self.subTest(value=value):
                self.assertIn("mesh-source-invalid-alignment-transform", codes(mesh_source(alignment_transform=value)))

    def test_brep_source_records_what_was_trusted_and_why(self) -> None:
        for mutate in (
            lambda brep: brep.pop("rationale"),
            lambda brep: brep.__setitem__("trusted", "no"),
            lambda brep: brep.__setitem__("sha256", "nope"),
            lambda brep: brep.__setitem__("path", "  "),
        ):
            with self.subTest(mutate=mutate):
                brep = copy.deepcopy(BREP_SOURCE)
                mutate(brep)
                self.assertIn("mesh-source-invalid-brep-source", codes(mesh_source(brep_source=brep)))

    def test_unknown_fields_and_bad_shapes_are_rejected(self) -> None:
        self.assertIn("unknown-manifest-field", codes(mesh_source(extra="nope")))
        self.assertIn("mesh-source-must-be-object", codes(["not-an-object"]))
        self.assertIn("invalid-mesh-source-id", codes(mesh_source(id="2bad")))


class MeshSourceManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        self.data["mesh_sources"] = [mesh_source()]

    def manifest_codes(self, data) -> set[str]:
        return {issue.code for issue in validate_manifest_data(data)}

    def test_mesh_sources_section_validates_inside_the_manifest(self) -> None:
        self.assertEqual([], validate_manifest_data(self.data))
        manifest = Manifest.from_data(self.data)
        self.assertEqual(["scan_bracket"], [record["id"] for record in manifest.mesh_sources])

    def test_manifest_rejects_duplicate_and_malformed_mesh_sources(self) -> None:
        duplicated = copy.deepcopy(self.data)
        duplicated["mesh_sources"].append(mesh_source())
        self.assertIn("mesh-source-duplicate-id", self.manifest_codes(duplicated))

        not_a_list = copy.deepcopy(self.data)
        not_a_list["mesh_sources"] = {"id": "scan_bracket"}
        self.assertIn("mesh-sources-must-be-list", self.manifest_codes(not_a_list))

        broken = copy.deepcopy(self.data)
        broken["mesh_sources"][0]["provenance"] = "guessed"
        self.assertIn("mesh-source-invalid-provenance", self.manifest_codes(broken))

    def test_schema_json_stays_in_lockstep_with_mesh_source_constants(self) -> None:
        from fusion_design.manifest import (
            BREP_SOURCE_FIELDS,
            MESH_PROVENANCES,
            MESH_SOURCE_FIELDS,
            MESH_UNITS,
            UNIT_GUESS_FIELDS,
            UNIT_SOURCES,
        )

        schema = json.loads((ROOT / "schema" / "fusion-project.schema.json").read_text(encoding="utf-8"))
        definition = schema["$defs"]["mesh_source"]
        self.assertIn("mesh_sources", schema["properties"])
        self.assertEqual(MESH_SOURCE_FIELDS, set(definition["properties"]))
        self.assertEqual(MESH_UNITS, set(definition["properties"]["units"]["enum"]))
        self.assertEqual(UNIT_SOURCES, set(definition["properties"]["unit_source"]["enum"]))
        self.assertEqual(MESH_PROVENANCES, set(definition["properties"]["provenance"]["enum"]))
        self.assertEqual(UNIT_GUESS_FIELDS, set(definition["properties"]["unit_guess"]["properties"]))
        self.assertEqual(BREP_SOURCE_FIELDS, set(definition["properties"]["brep_source"]["properties"]))


class MeshSourceHashTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "bracket.stl"
        self.path.write_bytes(b"solid bracket\nendsolid bracket\n")
        self.digest = file_sha256(self.path)

    def test_matching_bytes_verify(self) -> None:
        record = mesh_source(path=str(self.path), sha256=self.digest)
        self.assertEqual(self.digest, verify_mesh_source_file(record))

    def test_changed_bytes_fail_closed_instead_of_being_re_measured(self) -> None:
        record = mesh_source(path=str(self.path), sha256=self.digest)
        self.path.write_bytes(b"solid bracket\nfacet\nendsolid bracket\n")
        with self.assertRaises(ManifestValidationError) as ctx:
            verify_mesh_source_file(record)
        self.assertIn("mesh-source-hash-mismatch", str(ctx.exception))

    def test_missing_file_fails_closed(self) -> None:
        record = mesh_source(path=str(self.path) + ".missing", sha256=self.digest)
        with self.assertRaises(ManifestValidationError) as ctx:
            verify_mesh_source_file(record)
        self.assertIn("mesh-source-file-missing", str(ctx.exception))

    def test_an_invalid_record_is_never_verified(self) -> None:
        record = mesh_source(path=str(self.path), sha256=self.digest, provenance="scan")
        with self.assertRaises(ManifestValidationError) as ctx:
            verify_mesh_source_file(record)
        self.assertIn("mesh-source-invalid-provenance", str(ctx.exception))


class UnitSourceReasonTests(unittest.TestCase):
    def test_every_unit_source_states_its_reason(self) -> None:
        guessed = unit_source_reason(mesh_source())
        self.assertIn("bounding-box longest edge under the printable envelope", guessed)
        self.assertIn("300.0", guessed)
        self.assertIn("declared by the requester", unit_source_reason(_declared()))
        self.assertIn("read from a source file", unit_source_reason(_from_file()))

    def test_an_unknown_unit_source_has_no_reason_to_report(self) -> None:
        with self.assertRaises(ValueError):
            unit_source_reason(mesh_source(unit_source={"nested": 1}))


def _declared() -> dict:
    record = mesh_source(unit_source="declared")
    record.pop("unit_guess")
    return record


def _from_file() -> dict:
    record = mesh_source(unit_source="file")
    record.pop("unit_guess")
    return record


def _manifest_with_mesh_sources() -> Manifest:
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data["mesh_sources"] = [mesh_source(brep_source=copy.deepcopy(BREP_SOURCE))]
    return Manifest.from_data(data)


class _Collection:
    def __init__(self, items):
        self._items = list(items)

    @property
    def count(self):
        return len(self._items)

    def item(self, index):
        return self._items[index]


def _oriented_box():
    return SimpleNamespace(
        centerPoint=SimpleNamespace(x=1.0, y=2.0, z=3.0),
        length=4.0,
        width=5.0,
        height=6.0,
        lengthDirection=SimpleNamespace(x=1.0, y=0.0, z=0.0),
        widthDirection=SimpleNamespace(x=0.0, y=1.0, z=0.0),
        heightDirection=SimpleNamespace(x=0.0, y=0.0, z=1.0),
    )


class MeshCaptureScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = _manifest_with_mesh_sources()
        self.source = emit_mesh_capture_script(self.manifest)

    def test_capture_script_compiles_and_carries_the_unit_reason(self) -> None:
        compile(self.source, "<generated-fusion-script>", "exec")
        compile(
            "WRAPPER_CONTEXT = None\n" + self.source + "\nrun(WRAPPER_CONTEXT)\n",
            "<wrapped-fusion-script>",
            "exec",
        )
        self.assertNotIn("from __future__ import", self.source)
        self.assertIn("FUSION_DESIGN_REPORT_BEGIN", self.source)
        self.assertIn("bounding-box longest edge under the printable envelope", self.source)
        self.assertIn("fusion_version", self.source)

    def test_capture_script_contains_no_mutating_api_call(self) -> None:
        for mutation in (
            "addNewComponent",
            "deleteMe",
            "createInput",
            "MeshConvert",
            "MeshGenerateFaceGroups",
            "userParameters.add",
            "meshBodies.add",
            "importManager",
            "deleteAllAfterMarker",
        ):
            self.assertNotIn(mutation, self.source, mutation)

    def test_emitter_refuses_a_manifest_with_nothing_to_capture(self) -> None:
        with self.assertRaises(ValueError):
            emit_mesh_capture_script(Manifest.from_data(json.loads(EXAMPLE.read_text(encoding="utf-8"))))

    def test_capture_specs_carry_the_declared_evidence(self) -> None:
        spec = mesh_capture_specs(self.manifest)[0]
        self.assertEqual("scan_bracket", spec["id"])
        self.assertEqual("capture", spec["provenance"])
        self.assertTrue(spec["brep_source_available"])
        self.assertEqual(IDENTITY, spec["alignment_transform"])


class MeshCaptureRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = _manifest_with_mesh_sources()

    def _namespace(self, mesh_bodies, version="2.0.20000"):
        namespace = load_generated_script(emit_mesh_capture_script(self.manifest))
        root_component = SimpleNamespace(meshBodies=_Collection(mesh_bodies))
        design = SimpleNamespace(rootComponent=root_component)
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

    def test_capture_reports_measured_values_and_names_absent_ones(self) -> None:
        complete = SimpleNamespace(
            name="bracket_scan",
            mesh=SimpleNamespace(triangleCount=1284),
            isClosed=True,
            isOriented=False,
            volume=2.5,
            orientedMinimumBoundingBox=_oriented_box(),
        )
        partial = SimpleNamespace(name="lid_scan", mesh=SimpleNamespace(triangleCount=12))
        report = self._run(self._namespace([complete, partial]))[0]

        self.assertTrue(report["ok"])
        self.assertEqual("mesh-capture", report["kind"])
        self.assertEqual("2.0.20000", report["fusion_version"])
        first, second = report["mesh_bodies"]
        self.assertEqual(1284, first["triangle_count"])
        self.assertTrue(first["is_closed"])
        self.assertFalse(first["is_oriented"])
        self.assertEqual(2500.0, first["volume_mm3"])
        self.assertEqual(40.0, first["oriented_minimum_bounding_box_mm"]["length_mm"])
        self.assertEqual([], first["unavailable"])
        # Nothing readable is guessed: the absent preview properties are named.
        self.assertIsNone(second["volume_mm3"])
        self.assertIsNone(second["oriented_minimum_bounding_box_mm"])
        self.assertEqual(
            ["isClosed", "isOriented", "orientedMinimumBoundingBox", "volume"],
            second["unavailable"],
        )
        self.assertIn(
            "bounding-box longest edge under the printable envelope",
            report["unit_source_reasons"][0],
        )

    def test_a_missing_preview_api_fails_closed(self) -> None:
        reports = self._run(self._namespace([], version=None), failure="mesh capture capability is unavailable")
        self.assertFalse(reports[0]["ok"])
        self.assertEqual(["mesh-capture-capability"], reports[0]["failures"])
        self.assertEqual(["Application.version"], reports[0]["missing_capabilities"])

    def test_a_capture_that_read_no_mesh_body_is_not_a_success(self) -> None:
        reports = self._run(self._namespace([]), failure="no-mesh-bodies")
        self.assertFalse(reports[0]["ok"])
        self.assertEqual(["no-mesh-bodies"], reports[0]["failures"])


if __name__ == "__main__":
    unittest.main()
