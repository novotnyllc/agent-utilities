from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import copy
import json
from pathlib import Path
import sys
import sysconfig
import tempfile
from types import SimpleNamespace
import unittest

from fusion_design.manifest import ManifestValidationError
from fusion_design.mesh_probe import (
    PROBED_APIS,
    emit_capability_probe_script,
    validate_probe_spec,
)

from test_mesh_reconstruction import _manifest
from test_mesh_source import mesh_source
from test_scripts import load_generated_script


PROBE_SPEC = {"component_path": "", "body_name": "bracket_scan", "dump_dir": "/replaced/per/test"}

# Anything that would launch the running interpreter's executable. Inside Fusion
# that executable is the Fusion application binary, so each of these starts a
# second copy of Fusion on the user's machine. This has actually happened.
PROCESS_STARTERS = (
    "subprocess",
    "multiprocessing",
    "sys.executable",
    "os.system",
    "os.popen",
    "os.spawn",
    "os.exec",
    "ProcessPool",
    "Popen",
    "bootstrap",
    "runpy",
    "pty.spawn",
)

FUSION_MUTATIONS = (
    "deleteMe",
    "createInput",
    "baseFeatures",
    "computeAll",
    "TemporaryBRepManager",
    "meshConvertFeatures",
    "sketches.add",
)


class _Bodies:
    def __init__(self, items=()):
        self._items = list(items)

    @property
    def count(self):
        return len(self._items)

    def item(self, index):
        return self._items[index]


def spec(**overrides) -> dict:
    value = copy.deepcopy(PROBE_SPEC)
    value.update(overrides)
    return value


class ProbeSpecValidationTests(unittest.TestCase):
    def test_the_spec_is_optional_and_absent_is_valid(self) -> None:
        self.assertEqual([], validate_probe_spec(None))

    def test_a_present_spec_must_bind_a_body_and_a_directory(self) -> None:
        self.assertEqual(
            {"probe-spec-must-be-object"}, {issue.code for issue in validate_probe_spec(7)}
        )
        self.assertIn(
            "probe-spec-invalid-dump-dir", {issue.code for issue in validate_probe_spec(spec(dump_dir=""))}
        )
        broken = spec()
        del broken["body_name"]
        self.assertIn(
            "probe-spec-invalid-binding", {issue.code for issue in validate_probe_spec(broken)}
        )
        self.assertIn(
            "unknown-manifest-field", {issue.code for issue in validate_probe_spec(spec(hopes=1))}
        )

    def test_emission_refuses_a_malformed_spec(self) -> None:
        manifest = _manifest(mesh_source())
        with self.assertRaises(ManifestValidationError):
            emit_capability_probe_script(manifest, spec(dump_dir=" "))


class _Harness(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = _manifest(mesh_source(provenance="designed_export"))
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.dump_dir = Path(self.directory.name) / "dumps"

    def _namespace(self, probe_spec=None, *, mesh_body=None, apis=True):
        script = emit_capability_probe_script(self.manifest, probe_spec)
        compile("WRAPPER_CONTEXT = None\n" + script + "\nrun(WRAPPER_CONTEXT)\n", "<wrapped>", "exec")
        namespace = load_generated_script(script)
        component = SimpleNamespace(meshBodies=_Bodies([mesh_body] if mesh_body else []))
        design = SimpleNamespace(rootComponent=component)
        app = SimpleNamespace(
            version="2.0.20000", activeDocument=SimpleNamespace(name=self.manifest.fusion_document)
        )
        namespace["_active_design"] = lambda: (app, design)
        namespace["_root_context_occurrence_map"] = lambda root: ([], {}, {})
        if apis:
            for _, class_name, attribute in PROBED_APIS:
                module = namespace["adsk"].fusion if _ == "fusion" else namespace["adsk"].core
                owner = getattr(module, class_name, None)
                if owner is None:
                    owner = type(class_name, (), {})
                    setattr(module, class_name, owner)
                setattr(owner, attribute, None)
        return namespace

    def _run(self, namespace) -> dict:
        output = StringIO()
        with redirect_stdout(output):
            namespace["run"](None)
        lines = [json.loads(line) for line in output.getvalue().splitlines() if line.startswith("{")]
        return lines[0]


class ProbeSafetyTests(_Harness):
    def test_the_probe_starts_no_process(self) -> None:
        script = emit_capability_probe_script(self.manifest, spec())
        for construct in PROCESS_STARTERS:
            self.assertNotIn(construct, script, construct)

    def test_the_probe_creates_no_geometry(self) -> None:
        script = emit_capability_probe_script(self.manifest, spec())
        for verb in FUSION_MUTATIONS:
            self.assertNotIn(verb, script, verb)
        self.assertFalse(self._run(self._namespace())["creates_geometry"])

    def test_no_interpreter_tag_is_hardcoded_anywhere_in_the_emitted_source(self) -> None:
        script = emit_capability_probe_script(self.manifest, spec())
        for tag in ("cp314", "cp313", "cp312", "macosx_11_0_arm64", "macosx-10.15-universal2"):
            self.assertNotIn(tag, script, tag)


class ProbeRuntimeFactsTests(_Harness):
    def test_the_tag_triple_is_read_from_the_interpreter_that_ran(self) -> None:
        report = self._run(self._namespace())
        self.assertTrue(report["ok"])
        interpreter = report["interpreter"]
        self.assertEqual(
            [sys.version_info[0], sys.version_info[1], sys.version_info[2]],
            interpreter["version_info"],
        )
        self.assertEqual(sysconfig.get_config_var("EXT_SUFFIX"), interpreter["ext_suffix"])
        self.assertEqual(sysconfig.get_platform(), interpreter["sysconfig_platform"])
        # Recorded as evidence of the hazard: in Fusion this path is Fusion.app.
        self.assertEqual(getattr(sys, "executable", None), interpreter["interpreter_executable_path"])

        tags = report["pip_tags"]
        self.assertEqual(
            f"{sys.version_info[0]}.{sys.version_info[1]}", tags["python_version"]
        )
        self.assertEqual("cp", tags["implementation"])
        self.assertEqual(f"cp{sys.version_info[0]}{sys.version_info[1]}", tags["abi"])
        self.assertEqual("EXT_SUFFIX", tags["abi_source"])
        self.assertIn("interpreter-tags", report["checked"])

    def test_the_wheel_platform_is_never_derived_from_the_sysconfig_platform(self) -> None:
        report = self._run(self._namespace())
        tags = report["pip_tags"]
        self.assertIn(tags["platform_source"], ("packaging.tags.sys_tags", "unavailable"))
        if tags["platform_source"] == "unavailable":
            self.assertIsNone(tags["platform"])
        self.assertEqual(sysconfig.get_platform(), tags["sysconfig_platform_is_not_a_wheel_tag"])
        self.assertIn("NOT derivable", report["platform_note"])

    def test_an_underivable_abi_is_reported_unavailable_rather_than_guessed(self) -> None:
        derive = self._namespace()["_abi_from_ext_suffix"]
        self.assertEqual(("cp314", "EXT_SUFFIX"), derive(".cpython-314-darwin.so"))
        for suffix in (None, "", ".so", ".pypy310-pp73-darwin.so", ".cpython-abc-darwin.so"):
            with self.subTest(suffix=suffix):
                self.assertEqual((None, "unavailable"), derive(suffix))

    def test_a_raising_import_is_reported_with_its_message_not_omitted(self) -> None:
        namespace = self._namespace()
        namespace["PROBE_SPECS"]["modules"] = ["json", "fusion_design_no_such_module"]
        modules = self._run(namespace)["modules"]
        self.assertEqual({"json", "fusion_design_no_such_module"}, set(modules))
        self.assertTrue(modules["json"]["available"])
        absent = modules["fusion_design_no_such_module"]
        self.assertFalse(absent["available"])
        self.assertEqual("ModuleNotFoundError", absent["error_type"])
        self.assertIn("fusion_design_no_such_module", absent["error"])

    def test_writable_sys_path_entries_are_recorded_with_their_ownership(self) -> None:
        report = self._run(self._namespace())
        self.assertEqual([entry["path"] for entry in report["sys_path"]], list(sys.path))
        directories = [entry for entry in report["sys_path"] if entry.get("is_dir")]
        self.assertTrue(directories)
        for entry in directories:
            self.assertIn("owner_uid", entry)
            self.assertIn("mode", entry)
        self.assertTrue(set(report["writable_sys_path"]) <= set(sys.path))


class ProbeApiSurfaceTests(_Harness):
    def test_every_needed_api_is_reported_by_its_own_name(self) -> None:
        report = self._run(self._namespace())
        for module, class_name, attribute in PROBED_APIS:
            name = f"adsk.{module}.{class_name}.{attribute}"
            self.assertTrue(report["apis"][name], name)
        self.assertEqual([], report["missing_apis"])
        self.assertIn("api-presence", report["checked"])

    def test_a_missing_attribute_is_named_individually(self) -> None:
        namespace = self._namespace()
        delattr(namespace["adsk"].fusion.Sketch, "geometricConstraints")
        report = self._run(namespace)
        self.assertFalse(report["apis"]["adsk.fusion.Sketch.geometricConstraints"])
        self.assertIn("adsk.fusion.Sketch.geometricConstraints", report["missing_apis"])
        # And not collapsed: its siblings are still reported present.
        self.assertTrue(report["apis"]["adsk.fusion.Sketch.sketchCurves"])

    def test_a_missing_owner_class_names_the_class_and_nulls_its_attributes(self) -> None:
        namespace = self._namespace()
        delattr(namespace["adsk"].fusion, "PolygonMesh")
        report = self._run(namespace)
        self.assertIn("adsk.fusion.PolygonMesh", report["missing_apis"])
        self.assertIsNone(report["apis"]["adsk.fusion.PolygonMesh.nodeCoordinates"])
        self.assertIsNone(report["apis"]["adsk.fusion.PolygonMesh.compareWith"])
        self.assertTrue(report["apis"]["adsk.fusion.MeshBody.mesh"])


class ProbeBoundBodyTests(_Harness):
    def _mesh_body(self, groups=(1, 1, 2, 3), triangle_count=4):
        return SimpleNamespace(
            name="bracket_scan",
            mesh=SimpleNamespace(
                triangleCount=triangle_count,
                triangleFaceGroupTempIds=list(groups) if groups is not None else None,
            ),
        )

    def test_without_a_spec_the_body_probes_are_not_requested_rather_than_passing(self) -> None:
        report = self._run(self._namespace())
        for field in ("face_groups", "dump_write_roundtrip"):
            self.assertEqual("not-requested", report[field]["status"], field)
            self.assertIn("Not attempted is not a pass", report[field]["reason"])
        self.assertNotIn("face-groups", report["checked"])
        self.assertNotIn("dump-write-roundtrip", report["checked"])

    def test_a_bound_body_yields_the_face_group_histogram(self) -> None:
        report = self._run(
            self._namespace(spec(dump_dir=str(self.dump_dir)), mesh_body=self._mesh_body())
        )
        groups = report["face_groups"]
        self.assertEqual("present", groups["status"])
        self.assertEqual({"1": 2, "2": 1, "3": 1}, groups["histogram"])
        self.assertEqual(3, groups["group_count"])
        self.assertFalse(groups["single_group"])
        self.assertTrue(groups["covers_every_triangle"])
        self.assertIn("face-groups", report["checked"])

    def test_a_single_group_is_reported_as_such_rather_than_as_segmentation(self) -> None:
        report = self._run(
            self._namespace(
                spec(dump_dir=str(self.dump_dir)), mesh_body=self._mesh_body(groups=(9, 9, 9, 9))
            )
        )
        self.assertTrue(report["face_groups"]["single_group"])

    def test_absent_face_groups_are_reported_absent(self) -> None:
        report = self._run(
            self._namespace(spec(dump_dir=str(self.dump_dir)), mesh_body=self._mesh_body(groups=None))
        )
        self.assertEqual("absent", report["face_groups"]["status"])
        self.assertIn("no triangleFaceGroupTempIds", report["face_groups"]["reason"])

    def test_a_body_that_is_not_there_is_unavailable_not_empty(self) -> None:
        report = self._run(self._namespace(spec(dump_dir=str(self.dump_dir))))
        self.assertEqual("unavailable", report["face_groups"]["status"])
        self.assertIn("bracket_scan", report["face_groups"]["reason"])

    def test_the_write_round_trip_writes_reads_and_removes_its_own_file(self) -> None:
        report = self._run(
            self._namespace(spec(dump_dir=str(self.dump_dir)), mesh_body=self._mesh_body())
        )
        roundtrip = report["dump_write_roundtrip"]
        self.assertEqual("ok", roundtrip["status"])
        self.assertTrue(roundtrip["removed"])
        self.assertFalse(Path(roundtrip["path"]).exists())
        self.assertIn("dump-write-roundtrip", report["checked"])

    def test_a_failed_write_round_trip_names_its_consequence(self) -> None:
        blocker = Path(self.directory.name) / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        report = self._run(
            self._namespace(
                spec(dump_dir=str(blocker / "dumps")), mesh_body=self._mesh_body()
            )
        )
        roundtrip = report["dump_write_roundtrip"]
        self.assertEqual("failed", roundtrip["status"])
        self.assertIn("chunked-stdout fallback", roundtrip["consequence"])
        # The probe itself still completed and said so.
        self.assertTrue(report["ok"])
        self.assertIn("does not mean every capability is present", report["ok_means"])


if __name__ == "__main__":
    unittest.main()
