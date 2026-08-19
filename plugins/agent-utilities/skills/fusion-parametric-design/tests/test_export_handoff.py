from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from fusion_design.export_handoff import (
    ALLOWED_FORMATS,
    EXAMPLE_EXPORT_DIR,
    ExportConfig,
    emit_export_example_script,
    emit_export_script,
    example_verification_report,
    example_verification_report_bytes,
    verification_binding_from_report,
)
from fusion_design.manifest import load_manifest
from fusion_design.scripts import manifest_sha256

from test_scripts import load_generated_script


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "electronics-enclosure" / "fusion-project.json"

FORBIDDEN_CLAIM_KEYS = {
    "slicing",
    "print_time",
    "print_time_s",
    "filament_mass",
    "mass",
    "supports",
    "support_policy",
    "physical_fit",
    "fit",
}


def _collect_keys(value, keys):
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(key)
            _collect_keys(child, keys)
    elif isinstance(value, list):
        for child in value:
            _collect_keys(child, keys)


class FakeBody:
    def __init__(self, name, is_solid=True, volume=0.5):
        self.name = name
        self.isSolid = is_solid
        self.volume = volume


class FakeBodies:
    def __init__(self, bodies):
        self.bodies = list(bodies)

    @property
    def count(self):
        return len(self.bodies)

    def item(self, index):
        return self.bodies[index]


class FakeOccurrence:
    def __init__(self, bodies, bounds):
        self.bRepBodies = FakeBodies(bodies)
        self.bounds = bounds
        self.component = SimpleNamespace(name="component")
        self.transform2 = SimpleNamespace(
            asArray=lambda: [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
        )


class FakeExportManager:
    def __init__(self, fail_after=None):
        self.executed = []
        self.fail_after = fail_after

    def createSTEPExportOptions(self, filename, geometry):
        return SimpleNamespace(filename=filename, geometry=geometry, kind="step")

    def createC3MFExportOptions(self, geometry, filename):
        return SimpleNamespace(filename=filename, geometry=geometry, kind="3mf")

    def createSTLExportOptions(self, geometry, filename):
        return SimpleNamespace(filename=filename, geometry=geometry, kind="stl")

    def execute(self, options):
        if self.fail_after is not None and len(self.executed) >= self.fail_after:
            raise RuntimeError("simulated export failure")
        Path(options.filename).write_bytes(b"fake-" + options.kind.encode("utf-8") + b"-" + os.path.basename(options.filename).encode("utf-8"))
        self.executed.append(options.filename)
        return True


class ExportHandoffEmitterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = load_manifest(EXAMPLE)
        self.digest = manifest_sha256(self.manifest)
        self.print_parts = list(self.manifest.verification["expected_print_parts"])

    def _config(self, export_dir, formats=("step", "3mf")):
        report = example_verification_report(self.manifest)
        return ExportConfig(
            export_dir=str(export_dir),
            formats=tuple(formats),
            verification_report_sha256=hashlib.sha256(example_verification_report_bytes(self.manifest)).hexdigest(),
            expected_bounds_mm=verification_binding_from_report(self.manifest, report),
        )

    def test_emitted_script_compiles_and_embeds_identities(self) -> None:
        config = self._config("/tmp/example-exports")
        source = emit_export_script(self.manifest, config)
        compile(source, "<generated-export-script>", "exec")
        compile("WRAPPER_CONTEXT = None\n" + source + "\nrun(WRAPPER_CONTEXT)\n", "<wrapped>", "exec")
        self.assertNotIn("from __future__ import", source)
        self.assertIn(self.digest, source)
        self.assertIn(config.verification_report_sha256, source)
        for token in (
            "stale-verification",
            "export-capability",
            "missing-output-dir",
            "output-exists",
            "ambiguous-body",
            "missing-solid",
            "cleanup-incomplete",
            "createC3MFExportOptions",
        ):
            self.assertIn(token, source)

    def test_example_script_is_deterministic(self) -> None:
        first = emit_export_example_script(self.manifest)
        second = emit_export_example_script(self.manifest)
        self.assertEqual(first, second)
        self.assertIn(EXAMPLE_EXPORT_DIR, first)
        self.assertEqual(
            example_verification_report_bytes(self.manifest),
            example_verification_report_bytes(self.manifest),
        )

    def test_config_validation_fails_closed(self) -> None:
        good = self._config("/tmp/example-exports")
        with self.assertRaisesRegex(ValueError, "STEP export is required"):
            emit_export_script(self.manifest, ExportConfig(good.export_dir, ("3mf",), good.verification_report_sha256, good.expected_bounds_mm))
        with self.assertRaisesRegex(ValueError, "Unsupported export formats"):
            emit_export_script(self.manifest, ExportConfig(good.export_dir, ("step", "obj"), good.verification_report_sha256, good.expected_bounds_mm))
        with self.assertRaisesRegex(ValueError, "must not repeat"):
            emit_export_script(self.manifest, ExportConfig(good.export_dir, ("step", "step"), good.verification_report_sha256, good.expected_bounds_mm))
        with self.assertRaisesRegex(ValueError, "non-empty"):
            emit_export_script(self.manifest, ExportConfig("  ", good.formats, good.verification_report_sha256, good.expected_bounds_mm))
        with self.assertRaisesRegex(ValueError, "lowercase hex SHA-256"):
            emit_export_script(self.manifest, ExportConfig(good.export_dir, good.formats, "not-a-digest", good.expected_bounds_mm))
        partial_bounds = dict(good.expected_bounds_mm)
        partial_bounds.pop(self.print_parts[0])
        with self.assertRaisesRegex(ValueError, "missing for print parts"):
            emit_export_script(self.manifest, ExportConfig(good.export_dir, good.formats, good.verification_report_sha256, partial_bounds))

    def test_filename_collisions_fail_at_emit_time(self) -> None:
        good = self._config("/tmp/example-exports")
        colliding = json.loads(json.dumps(self.manifest.to_dict()))
        # Two component paths whose slugs collide (lowercase folding).
        colliding["component_tree"].extend(["10_PRODUCT/PROD__CASE", "10_PRODUCT/prod__case"])
        colliding["verification"]["expected_print_parts"] = ["10_PRODUCT/PROD__CASE", "10_PRODUCT/prod__case"]
        from fusion_design.manifest import Manifest

        manifest = Manifest.from_data(colliding)
        bounds = {
            "10_PRODUCT/PROD__CASE": {"min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, 1.0]},
            "10_PRODUCT/prod__case": {"min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, 1.0]},
        }
        with self.assertRaisesRegex(ValueError, "filenames collide"):
            emit_export_script(
                manifest,
                ExportConfig(good.export_dir, good.formats, good.verification_report_sha256, bounds),
            )

    def test_bounds_validation_rejects_malformed_and_non_finite_shapes(self) -> None:
        good = self._config("/tmp/example-exports")
        part = self.print_parts[0]
        for bad in (
            ["not-a-dict"],
            {"min": [0.0, 0.0, 0.0]},
            {"min": [0.0, 0.0], "max": [1.0, 1.0, 1.0]},
            {"min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, float("nan")]},
            {"min": [float("inf"), 0.0, 0.0], "max": [1.0, 1.0, 1.0]},
        ):
            bounds = dict(good.expected_bounds_mm)
            bounds[part] = bad
            with self.assertRaises(ValueError):
                emit_export_script(
                    self.manifest,
                    ExportConfig(good.export_dir, good.formats, good.verification_report_sha256, bounds),
                )

    def test_verification_binding_rejects_mismatched_reports(self) -> None:
        report = example_verification_report(self.manifest)
        with self.assertRaisesRegex(ValueError, "expected 'verification'"):
            verification_binding_from_report(self.manifest, {**report, "kind": "inventory"})
        with self.assertRaisesRegex(ValueError, "ok: true"):
            verification_binding_from_report(self.manifest, {**report, "ok": False})
        with self.assertRaisesRegex(ValueError, "does not match manifest"):
            verification_binding_from_report(self.manifest, {**report, "manifest_sha256": "0" * 64})
        missing_boxes = {**report, "brep_bounding_boxes_mm": {}}
        with self.assertRaisesRegex(ValueError, "no usable B-Rep bounds"):
            verification_binding_from_report(self.manifest, missing_boxes)
        errored = json.loads(json.dumps(report))
        errored["brep_bounding_boxes_mm"][self.print_parts[0]] = {"error": "no bounds"}
        with self.assertRaisesRegex(ValueError, "no usable B-Rep bounds"):
            verification_binding_from_report(self.manifest, errored)


class ExportHandoffRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = load_manifest(EXAMPLE)
        self.print_parts = list(self.manifest.verification["expected_print_parts"])
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.export_dir = Path(self.temp.name)

    def _namespace(self, formats=("step", "3mf"), export_manager=None, occurrences=None, export_dir=None):
        report = example_verification_report(self.manifest)
        bounds = verification_binding_from_report(self.manifest, report)
        config = ExportConfig(
            export_dir=str(export_dir if export_dir is not None else self.export_dir),
            formats=tuple(formats),
            verification_report_sha256=hashlib.sha256(example_verification_report_bytes(self.manifest)).hexdigest(),
            expected_bounds_mm=bounds,
        )
        source = emit_export_script(self.manifest, config)
        namespace = load_generated_script(source)

        if occurrences is None:
            occurrences = {
                path: FakeOccurrence([FakeBody("BODY__" + path.replace("/", "__"))], bounds[path])
                for path in self.print_parts
            }
        self.occurrences = occurrences
        manager = export_manager if export_manager is not None else FakeExportManager()
        self.export_manager = manager
        design = SimpleNamespace(
            exportManager=manager,
            rootComponent=SimpleNamespace(),
            unitsManager=SimpleNamespace(defaultLengthUnits="mm"),
        )
        app = SimpleNamespace(
            activeDocument=SimpleNamespace(name=self.manifest.fusion_document, isSaved=False)
        )
        namespace["_active_design"] = lambda: (app, design)
        namespace["_root_context_occurrence_map"] = lambda root: (
            sorted(occurrences),
            dict(occurrences),
            {},
        )
        namespace["_bbox_mm"] = lambda occurrence: occurrence.bounds
        return namespace

    def _run(self, namespace):
        output = StringIO()
        with redirect_stdout(output):
            namespace["run"](None)
        return [json.loads(line) for line in output.getvalue().splitlines() if line.startswith("{")]

    def _run_expect_failure(self, namespace, pattern):
        output = StringIO()
        with redirect_stdout(output), self.assertRaisesRegex(RuntimeError, pattern):
            namespace["run"](None)
        return [json.loads(line) for line in output.getvalue().splitlines() if line.startswith("{")]

    def test_happy_path_exports_hash_index_and_rows(self) -> None:
        namespace = self._namespace()
        reports = self._run(namespace)
        self.assertEqual(1, len(reports))
        report = reports[0]
        self.assertTrue(report["ok"])
        self.assertEqual("export-handoff", report["kind"])
        self.assertEqual(len(self.print_parts) * 2, len(report["artifacts"]))
        self.assertEqual("unsaved", report["document_version"])
        self.assertFalse(report["document_saved"])
        self.assertEqual("mm", report["units"])
        self.assertEqual(32, len(report["export_run_id"]))
        int(report["export_run_id"], 16)

        index_files = sorted(self.export_dir.glob("export-index__*.json"))
        self.assertEqual(1, len(index_files))
        index = json.loads(index_files[0].read_text(encoding="utf-8"))
        self.assertEqual(report["export_run_id"], index["export_run_id"])
        self.assertEqual(report["verification_report_sha256"], index["verification_report_sha256"])

        for artifact in index["artifacts"]:
            target = self.export_dir / artifact["filename"]
            self.assertTrue(target.is_file())
            self.assertEqual(artifact["byte_size"], target.stat().st_size)
            self.assertEqual(artifact["sha256"], hashlib.sha256(target.read_bytes()).hexdigest())
            expected_scope = "component" if artifact["format"] == "step" else "body"
            self.assertEqual(expected_scope, artifact["export_scope"])
            self.assertEqual(16, len(artifact["transform"]))

        keys: set = set()
        _collect_keys(index, keys)
        self.assertFalse(keys & FORBIDDEN_CLAIM_KEYS, keys & FORBIDDEN_CLAIM_KEYS)
        self.assertEqual(len(index["artifacts"]), len(report["design_state_rows"]))
        for row in report["design_state_rows"]:
            self.assertTrue(row.startswith("| "))
            self.assertIn(report["export_run_id"][:8], row)

    def test_rerun_blocks_without_overwriting(self) -> None:
        namespace = self._namespace()
        self._run(namespace)
        before = {path.name: path.read_bytes() for path in self.export_dir.iterdir()}

        rerun_namespace = self._namespace()
        reports = self._run_expect_failure(rerun_namespace, "output-exists")
        self.assertEqual(["output-exists"], reports[0]["failures"])
        self.assertEqual(sorted(before), sorted(reports[0]["existing_outputs"]))
        after = {path.name: path.read_bytes() for path in self.export_dir.iterdir()}
        self.assertEqual(before, after)

    def test_ambiguous_and_missing_bodies_block_before_any_export(self) -> None:
        report = example_verification_report(self.manifest)
        bounds = verification_binding_from_report(self.manifest, report)
        base, lid, coupon = self.print_parts
        occurrences = {
            base: FakeOccurrence([FakeBody("A"), FakeBody("B")], bounds[base]),
            lid: FakeOccurrence([FakeBody("DUP"), FakeBody("DUP", is_solid=False, volume=0.0)], bounds[lid]),
            coupon: FakeOccurrence([FakeBody("SURFACE", is_solid=False, volume=0.0)], bounds[coupon]),
        }
        namespace = self._namespace(occurrences=occurrences)
        reports = self._run_expect_failure(namespace, "ambiguous-body")
        failures = reports[0]["failures"]
        self.assertIn("ambiguous-body", failures)
        self.assertIn("missing-solid", failures)
        reasons = {row["reason"] for row in reports[0]["resolution_errors"]}
        self.assertEqual({"multiple-solid-bodies", "duplicate-body-names", "no-positive-solid-body"}, reasons)
        self.assertEqual([], list(self.export_dir.iterdir()))

    def test_missing_component_and_duplicate_path_block(self) -> None:
        report = example_verification_report(self.manifest)
        bounds = verification_binding_from_report(self.manifest, report)
        base, lid, coupon = self.print_parts
        occurrences = {
            base: FakeOccurrence([FakeBody("BASE")], bounds[base]),
            lid: FakeOccurrence([FakeBody("LID")], bounds[lid]),
        }
        namespace = self._namespace(occurrences=occurrences)
        duplicates = {coupon: [coupon + ":1", coupon + ":2"]}
        occurrence_map = dict(occurrences)
        namespace["_root_context_occurrence_map"] = lambda root: (
            sorted(occurrence_map),
            occurrence_map,
            duplicates,
        )
        reports = self._run_expect_failure(namespace, "ambiguous-components")
        self.assertIn("ambiguous-components", reports[0]["failures"])
        self.assertEqual([], list(self.export_dir.iterdir()))

        del occurrence_map[lid]
        namespace_missing = self._namespace(occurrences={base: occurrences[base]})
        reports_missing = self._run_expect_failure(namespace_missing, "missing-component")
        self.assertIn("missing-component", reports_missing[0]["failures"])
        self.assertEqual([], list(self.export_dir.iterdir()))

    def test_stale_verification_blocks(self) -> None:
        report = example_verification_report(self.manifest)
        bounds = verification_binding_from_report(self.manifest, report)
        drifted = {
            path: FakeOccurrence(
                [FakeBody("BODY")],
                {
                    "min": bounds[path]["min"],
                    "max": [bounds[path]["max"][0] + 1.0, bounds[path]["max"][1], bounds[path]["max"][2]],
                },
            )
            for path in self.print_parts
        }
        namespace = self._namespace(occurrences=drifted)
        reports = self._run_expect_failure(namespace, "stale-verification")
        self.assertIn("stale-verification", reports[0]["failures"])
        self.assertTrue(all(row["reason"] == "bounds-drifted" for row in reports[0]["stale_parts"]))
        self.assertEqual([], list(self.export_dir.iterdir()))

    def test_missing_export_capability_fails_closed(self) -> None:
        namespace = self._namespace()
        design_without_export = SimpleNamespace(rootComponent=SimpleNamespace())
        app = SimpleNamespace(activeDocument=SimpleNamespace(name=self.manifest.fusion_document))
        namespace["_active_design"] = lambda: (app, design_without_export)
        reports = self._run_expect_failure(namespace, "export capability is unavailable")
        self.assertEqual(["export-capability"], reports[0]["failures"])
        self.assertEqual(["Design.exportManager"], reports[0]["missing_export_capabilities"])
        self.assertEqual([], list(self.export_dir.iterdir()))

    def test_missing_option_constructor_names_the_attribute(self) -> None:
        class StepOnlyManager:
            def createSTEPExportOptions(self, filename, geometry):
                return SimpleNamespace(filename=filename, geometry=geometry, kind="step")

            def execute(self, options):
                return True

        namespace = self._namespace(export_manager=StepOnlyManager())
        reports = self._run_expect_failure(namespace, "createC3MFExportOptions")
        self.assertEqual(["export-capability"], reports[0]["failures"])
        self.assertIn("ExportManager.createC3MFExportOptions", reports[0]["missing_export_capabilities"])

    def test_missing_output_dir_blocks(self) -> None:
        namespace = self._namespace(export_dir=self.export_dir / "does-not-exist")
        reports = self._run_expect_failure(namespace, "missing-output-dir")
        self.assertEqual(["missing-output-dir"], reports[0]["failures"])

    def test_saved_document_records_version_identity(self) -> None:
        namespace = self._namespace()
        data_file = SimpleNamespace(id="doc-id-123", versionNumber=7)
        app = SimpleNamespace(
            activeDocument=SimpleNamespace(name=self.manifest.fusion_document, isSaved=True, dataFile=data_file)
        )
        design = SimpleNamespace(
            exportManager=self.export_manager,
            rootComponent=SimpleNamespace(),
            unitsManager=SimpleNamespace(defaultLengthUnits="mm"),
        )
        namespace["_active_design"] = lambda: (app, design)
        report = self._run(namespace)[0]
        self.assertTrue(report["document_saved"])
        self.assertEqual({"id": "doc-id-123", "version_number": 7}, report["document_version"])

    def test_saved_document_with_failing_datafile_records_unsaved(self) -> None:
        namespace = self._namespace()

        class Document:
            name = self.manifest.fusion_document
            isSaved = True
            isModified = True

            @property
            def dataFile(self):
                raise RuntimeError("dataFile unavailable")

        app = SimpleNamespace(activeDocument=Document())
        design = SimpleNamespace(
            exportManager=self.export_manager,
            rootComponent=SimpleNamespace(),
            unitsManager=SimpleNamespace(defaultLengthUnits="mm"),
        )
        namespace["_active_design"] = lambda: (app, design)
        report = self._run(namespace)[0]
        self.assertTrue(report["document_saved"])
        self.assertTrue(report["document_modified"])
        self.assertEqual("unsaved", report["document_version"])

    def test_target_appearing_after_preflight_fails_closed(self) -> None:
        outer = self

        class RacingManager(FakeExportManager):
            def createC3MFExportOptions(self, geometry, filename):
                Path(filename).write_bytes(b"concurrent-writer")
                return super().createC3MFExportOptions(geometry, filename)

        namespace = self._namespace(export_manager=RacingManager())
        reports = self._run_expect_failure(namespace, "appeared after preflight")
        report = reports[0]
        self.assertIn("export-incomplete", report["failures"])
        survivors = sorted(path.name for path in outer.export_dir.iterdir())
        self.assertEqual(1, len(survivors))
        self.assertTrue(survivors[0].endswith(".3mf"))
        self.assertEqual(b"concurrent-writer", (outer.export_dir / survivors[0]).read_bytes())

    def test_unremovable_file_reports_cleanup_incomplete(self) -> None:
        export_dir = self.export_dir

        class SwappingManager(FakeExportManager):
            def execute(self, options):
                if len(self.executed) == 1:
                    first = Path(self.executed[0])
                    first.unlink()
                    first.mkdir()
                    raise RuntimeError("simulated export failure")
                return super().execute(options)

        namespace = self._namespace(export_manager=SwappingManager())
        reports = self._run_expect_failure(namespace, "cleanup left partial artifacts")
        report = reports[0]
        self.assertIn("export-incomplete", report["failures"])
        self.assertIn("cleanup-incomplete", report["failures"])
        self.assertEqual(1, len(report["cleanup_errors"]))
        leftover = [path for path in export_dir.iterdir()]
        self.assertEqual(1, len(leftover))
        self.assertTrue(leftover[0].is_dir())

    def test_partial_export_failure_cleans_up_and_writes_no_index(self) -> None:
        namespace = self._namespace(export_manager=FakeExportManager(fail_after=1))
        reports = self._run_expect_failure(namespace, "simulated export failure")
        report = reports[0]
        self.assertFalse(report["ok"])
        self.assertIn("export-incomplete", report["failures"])
        self.assertNotIn("cleanup-incomplete", report["failures"])
        self.assertEqual(2, len(report["created_and_removed"]))
        self.assertEqual([], report["cleanup_errors"])
        self.assertEqual([], list(self.export_dir.iterdir()))


if __name__ == "__main__":
    unittest.main()
