from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from fusion_design.manifest import Manifest, load_manifest
from fusion_design.scripts import (
    emit_inventory_script,
    emit_parameter_sync_script,
    emit_scaffold_script,
    emit_verification_script,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "electronics-enclosure" / "fusion-project.json"


def load_generated_script(source: str) -> dict:
    adsk = ModuleType("adsk")
    core = ModuleType("adsk.core")
    fusion = ModuleType("adsk.fusion")
    adsk.core = core
    adsk.fusion = fusion
    adsk.doEvents = lambda: None
    fusion.DesignTypes = SimpleNamespace(ParametricDesignType="parametric")
    fusion.FeatureHealthStates = SimpleNamespace(
        HealthyFeatureHealthState="healthy",
        WarningFeatureHealthState="warning",
        ErrorFeatureHealthState="error",
        RolledBackFeatureHealthState="rolled-back",
        SuppressedFeatureHealthState="suppressed",
        UnknownFeatureHealthState="unknown",
    )
    core.ValueInput = SimpleNamespace(createByString=lambda expression: expression)
    core.Matrix3D = SimpleNamespace(create=lambda: SimpleNamespace())
    modules = {"adsk": adsk, "adsk.core": core, "adsk.fusion": fusion}
    previous = {name: sys.modules.get(name) for name in modules}
    sys.modules.update(modules)
    try:
        namespace: dict = {}
        exec(source, namespace)
        return namespace
    finally:
        for name, value in previous.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


class ScriptEmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = load_manifest(EXAMPLE)

    def assert_compiles(self, source: str) -> None:
        compile(source, "<generated-fusion-script>", "exec")

    def assert_compiles_when_wrapped(self, source: str) -> None:
        wrapped = "WRAPPER_CONTEXT = None\n" + source + "\nrun(WRAPPER_CONTEXT)\n"
        compile(wrapped, "<wrapped-fusion-script>", "exec")

    def test_all_emitters_compile_under_reference_wrapper(self) -> None:
        for emitter in (
            emit_inventory_script,
            emit_parameter_sync_script,
            emit_scaffold_script,
            emit_verification_script,
        ):
            with self.subTest(emitter=emitter.__name__):
                source = emitter(self.manifest)
                self.assert_compiles_when_wrapped(source)
                self.assertNotIn("from __future__ import", source)

    def test_report_path_and_run_id_must_be_paired(self) -> None:
        with self.assertRaisesRegex(ValueError, "supplied together"):
            emit_inventory_script(self.manifest, "/private/tmp/inventory.json")
        with self.assertRaisesRegex(ValueError, "supplied together"):
            emit_inventory_script(self.manifest, report_run_id="test-run")

    def test_report_path_is_absolute_and_emitted_atomically(self) -> None:
        with self.assertRaisesRegex(ValueError, "absolute"):
            emit_inventory_script(self.manifest, "reports/inventory.json")

        with tempfile.TemporaryDirectory() as temporary:
            report_path = Path(temporary) / "inventory.json"
            source = emit_inventory_script(self.manifest, report_path, "test-run")
            self.assert_compiles(source)
            self.assertIn(f"REPORT_PATH = {str(report_path)!r}", source)

            namespace = load_generated_script(source)
            output = StringIO()
            with redirect_stdout(output):
                namespace["_emit"]({"kind": "test", "ok": True}, "test-run")

            self.assertEqual(
                {"kind": "test", "ok": True, "report_run_id": "test-run"},
                json.loads(report_path.read_text()),
            )
            self.assertIn("FUSION_DESIGN_REPORT_BEGIN", output.getvalue())
            self.assertLess(
                source.index("os.link(temporary_path, REPORT_PATH)"), source.index("print(REPORT_BEGIN)")
            )
            self.assertEqual([], list(Path(temporary).glob(".fusion-design-report-*")))

    def test_report_write_failure_is_visible_and_cleans_up(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report_directory = Path(temporary) / "missing"
            report_path = report_directory / "inventory.json"
            namespace = load_generated_script(emit_inventory_script(self.manifest, report_path, "test-run"))
            output = StringIO()
            errors = StringIO()
            with redirect_stdout(output), redirect_stderr(errors), self.assertRaisesRegex(
                RuntimeError, "Failed to deliver Fusion JSON report"
            ):
                namespace["_emit"]({"kind": "test"}, "test-run")
            self.assertIn("Failed to deliver Fusion JSON report", errors.getvalue())
            self.assertEqual("", output.getvalue())

    def test_report_path_never_clobbers_existing_or_symlink_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            report_path = directory / "inventory.json"
            report_path.write_text("original")
            namespace = load_generated_script(emit_inventory_script(self.manifest, report_path, "test-run"))
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()), self.assertRaisesRegex(
                RuntimeError, "already exists"
            ):
                namespace["_emit"]({"kind": "test"}, "test-run")
            self.assertEqual("original", report_path.read_text())
            self.assertEqual([], list(directory.glob(".fusion-design-report-*")))

            report_path.unlink()
            report_path.symlink_to(directory / "missing-target")
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()), self.assertRaisesRegex(
                RuntimeError, "already exists"
            ):
                namespace["_emit"]({"kind": "test"}, "test-run")
            self.assertTrue(report_path.is_symlink())
            self.assertFalse(os.path.exists(report_path))
            self.assertEqual([], list(directory.glob(".fusion-design-report-*")))

    def test_report_delivery_failure_after_temp_creation_cleans_up(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            report_path = directory / "inventory.json"
            namespace = load_generated_script(emit_inventory_script(self.manifest, report_path, "test-run"))
            with patch.object(namespace["os"], "link", side_effect=OSError("link denied")):
                with redirect_stdout(StringIO()), redirect_stderr(StringIO()), self.assertRaisesRegex(
                    RuntimeError, "link denied"
                ):
                    namespace["_emit"]({"kind": "test"}, "test-run")
            self.assertFalse(report_path.exists())
            self.assertEqual([], list(directory.glob(".fusion-design-report-*")))

    def test_report_delivery_failure_does_not_replace_domain_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report_path = Path(temporary) / "inventory.json"
            report_path.write_text("original")
            namespace = load_generated_script(emit_inventory_script(self.manifest, report_path, "test-run"))
            wrong_app = SimpleNamespace(activeDocument=SimpleNamespace(name="Different design"))
            namespace["_active_design"] = lambda: (wrong_app, SimpleNamespace())
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()), self.assertRaisesRegex(
                RuntimeError, "does not match manifest target"
            ):
                namespace["run"](None)
            self.assertEqual("original", report_path.read_text())
            self.assertEqual([], list(Path(temporary).glob(".fusion-design-report-*")))

    def test_inventory_script_is_read_only_and_compiles(self) -> None:
        source = emit_inventory_script(self.manifest)
        self.assert_compiles(source)
        self.assert_compiles_when_wrapped(source)
        self.assertNotIn("from __future__ import", source)
        self.assertIn("FUSION_DESIGN_REPORT_BEGIN", source)
        self.assertIn("root_component.allOccurrences", source)
        self.assertIn("fullPathName", source)
        self.assertIn("duplicate_semantic_paths", source)
        self.assertIn("AllEntitiesBoundingBoxEntityType", source)
        self.assertIn("adsk.doEvents()", source)
        self.assertNotIn("addNewComponent", source)
        self.assertNotIn("userParameters.add", source)

    def test_parameter_sync_is_idempotent_and_never_rebuilds_timeline(self) -> None:
        source = emit_parameter_sync_script(self.manifest)
        self.assert_compiles(source)
        self.assertIn("itemByName", source)
        self.assertIn('existing.expression = spec["expression"]', source)
        self.assertIn("user_parameters.add", source)
        self.assertIn("HealthyFeatureHealthState", source)
        self.assertIn("report_attempted = False", source)
        self.assertIn("existing.unit != spec[\"units\"]", source)
        self.assertIn("Existing parameter unit mismatch", source)
        self.assertIn('"ok": bool(compute_invoked)', source)
        self.assertIn("adsk.doEvents()", source)
        self.assertNotIn("deleteAllAfterMarker", source)
        self.assertNotIn("design.designType =", source)

        class Attributes:
            def __init__(self):
                self.values = {}
                self.fail_writes = False

            def itemByName(self, group, name):
                value = self.values.get((group, name))
                return SimpleNamespace(value=value) if value is not None else None

            def add(self, group, name, value):
                if self.fail_writes:
                    return None
                self.values[(group, name)] = value
                return (group, name, value)

        class Parameter:
            def __init__(self, name, expression, unit, comment):
                self.name = name
                self.expression = expression
                self.unit = unit
                self.comment = comment
                self.attributes = Attributes()

        class UserParameters:
            def __init__(self):
                self.values = {}
                self.add_count = 0
                self.initial_expressions = []

            def itemByName(self, name):
                return self.values.get(name)

            def add(self, name, expression, unit, comment):
                self.add_count += 1
                self.initial_expressions.append(expression)
                parameter = Parameter(name, expression, unit, comment)
                self.values[name] = parameter
                return parameter

        user_parameters = UserParameters()
        design = SimpleNamespace(
            designType="parametric",
            userParameters=user_parameters,
            timeline=SimpleNamespace(count=0),
            computeAll=lambda: True,
        )
        namespace = load_generated_script(source)
        app = SimpleNamespace(activeDocument=SimpleNamespace(name=self.manifest.fusion_document))
        namespace["_active_design"] = lambda: (app, design)
        output = StringIO()
        with redirect_stdout(output):
            namespace["run"](None)
            first_add_count = user_parameters.add_count
            namespace["run"](None)

        reports = [
            json.loads(line)
            for line in output.getvalue().splitlines()
            if line.startswith("{")
        ]
        self.assertGreater(first_add_count, 0)
        self.assertEqual({"0"}, set(user_parameters.initial_expressions))
        self.assertEqual(first_add_count, user_parameters.add_count)
        self.assertTrue(reports[0]["ok"])
        self.assertTrue(all(change["operation"] == "unchanged" for change in reports[1]["changes"]))

        first_parameter = user_parameters.values[namespace["PARAMETER_SPECS"][0]["name"]]
        first_parameter.attributes.values[("fusion_parametric_design", "role")] = "stale"
        attribute_output = StringIO()
        with redirect_stdout(attribute_output):
            namespace["run"](None)
        attribute_report = next(
            json.loads(line) for line in attribute_output.getvalue().splitlines() if line.startswith("{")
        )
        first_change = next(
            change for change in attribute_report["changes"] if change["name"] == first_parameter.name
        )
        self.assertEqual("updated", first_change["operation"])
        self.assertIn("attribute:role", first_change["fields"])

        namespace["adsk"].doEvents = lambda: setattr(first_parameter, "expression", "tampered")
        design.computeAll = lambda: True
        tampered_output = StringIO()
        with redirect_stdout(tampered_output), self.assertRaisesRegex(RuntimeError, "changed while Fusion processed events"):
            namespace["run"](None)
        tampered_report = next(
            json.loads(line) for line in tampered_output.getvalue().splitlines() if line.startswith("{")
        )
        self.assertFalse(tampered_report["ok"])
        self.assertIn(first_parameter.name + ":expression", tampered_report["verification_failures"])
        namespace["adsk"].doEvents = lambda: None

        first_parameter.attributes.values[("fusion_parametric_design", "role")] = "stale-again"
        first_parameter.attributes.fail_writes = True
        with redirect_stdout(StringIO()), self.assertRaisesRegex(RuntimeError, "failed to write parameter attribute"):
            namespace["run"](None)
        first_parameter.attributes.fail_writes = False

        design.computeAll = lambda: False
        with redirect_stdout(StringIO()), self.assertRaisesRegex(RuntimeError, "Compute All did not complete"):
            namespace["run"](None)

        first_spec = namespace["PARAMETER_SPECS"][0]
        last_spec = namespace["PARAMETER_SPECS"][-1]
        conflict_parameters = UserParameters()
        early = Parameter(first_spec["name"], "unchanged-on-error", first_spec["units"], first_spec["comment"])
        late = Parameter(last_spec["name"], last_spec["expression"], "wrong-unit", last_spec["comment"])
        conflict_parameters.values = {first_spec["name"]: early, last_spec["name"]: late}
        conflict_design = SimpleNamespace(
            designType="parametric",
            userParameters=conflict_parameters,
            timeline=SimpleNamespace(count=0),
            computeAll=lambda: True,
        )
        conflict_namespace = load_generated_script(source)
        conflict_namespace["_active_design"] = lambda: (app, conflict_design)
        with redirect_stdout(StringIO()), self.assertRaisesRegex(RuntimeError, "unit mismatch"):
            conflict_namespace["run"](None)
        self.assertEqual("unchanged-on-error", early.expression)

        unitless_manifest_data = self.manifest.to_dict()
        unitless_manifest_data["parameters"][0]["units"] = ""
        unitless_source = emit_parameter_sync_script(Manifest.from_data(unitless_manifest_data))
        unitless_namespace = load_generated_script(unitless_source)
        unitless_spec = unitless_namespace["PARAMETER_SPECS"][0]
        dimensional = Parameter(
            unitless_spec["name"], "unchanged-on-error", "mm", unitless_spec["comment"]
        )
        unitless_parameters = UserParameters()
        unitless_parameters.values[unitless_spec["name"]] = dimensional
        unitless_design = SimpleNamespace(
            designType="parametric",
            userParameters=unitless_parameters,
            timeline=SimpleNamespace(count=0),
            computeAll=lambda: True,
        )
        unitless_namespace["_active_design"] = lambda: (app, unitless_design)
        with redirect_stdout(StringIO()), self.assertRaisesRegex(RuntimeError, "unit mismatch"):
            unitless_namespace["run"](None)
        self.assertEqual("unchanged-on-error", dimensional.expression)
        self.assertEqual(0, unitless_parameters.add_count)

        text_manifest_data = self.manifest.to_dict()
        text_manifest_data["parameters"].append(
            {
                "name": "des_label",
                "expression": "'hello'",
                "units": "Text",
                "role": "design",
                "critical": False,
                "provisional": False,
                "description": "User-visible label.",
            }
        )
        text_source = emit_parameter_sync_script(Manifest.from_data(text_manifest_data))
        text_parameters = UserParameters()
        text_design = SimpleNamespace(
            designType="parametric",
            userParameters=text_parameters,
            timeline=SimpleNamespace(count=0),
            computeAll=lambda: True,
        )
        text_namespace = load_generated_script(text_source)
        text_namespace["_active_design"] = lambda: (app, text_design)
        with redirect_stdout(StringIO()):
            text_namespace["run"](None)
        self.assertIn("''", text_parameters.initial_expressions)

        wrong_document = SimpleNamespace(activeDocument=SimpleNamespace(name="Different design"))
        namespace["_active_design"] = lambda: (wrong_document, design)
        with redirect_stdout(StringIO()), self.assertRaisesRegex(RuntimeError, "does not match manifest target"):
            namespace["run"](None)

    def test_scaffold_ensures_component_paths_without_deleting_existing_geometry(self) -> None:
        source = emit_scaffold_script(self.manifest)
        self.assert_compiles(source)
        self.assertIn("adsk.doEvents()", source)
        self.assertIn("addNewComponent", source)
        self.assertIn("_ensure_component_path", source)
        self.assertIn("preexisting_duplicate_semantic_paths", source)
        self.assertIn("missing_component_paths", source)
        self.assertIn("not duplicate_semantic_paths and not missing_component_paths", source)
        self.assertIn("compute_invoked = design.computeAll()", source)
        self.assertIn('timeline["unhealthy"]', source)
        self.assertLess(source.index("preexisting_duplicate_semantic_paths"), source.index("created = []", source.index("def run(context):")))
        self.assertNotIn("deleteMe", source)

        namespace = load_generated_script(source)
        real_ensure_component_path = namespace["_ensure_component_path"]
        design = SimpleNamespace(
            designType="parametric",
            rootComponent=SimpleNamespace(),
            timeline=SimpleNamespace(count=0),
            computeAll=lambda: True,
        )
        observations = iter([([], {}, {}), ([], {}, {})])
        app = SimpleNamespace(activeDocument=SimpleNamespace(name=self.manifest.fusion_document))
        namespace["_active_design"] = lambda: (app, design)
        namespace["_root_context_occurrence_map"] = lambda root: next(observations)
        namespace["_ensure_component_path"] = lambda root, path: ([], [])
        output = StringIO()
        with redirect_stdout(output), self.assertRaisesRegex(RuntimeError, "component paths are still missing"):
            namespace["run"](None)
        report = next(json.loads(line) for line in output.getvalue().splitlines() if line.startswith("{"))
        self.assertFalse(report["ok"])
        self.assertEqual(sorted(namespace["COMPONENT_PATHS"]), report["missing_component_paths"])

        all_paths = sorted(namespace["COMPONENT_PATHS"])
        design.computeAll = lambda: False
        observations = iter([([], {}, {}), (all_paths, {}, {})])
        namespace["_root_context_occurrence_map"] = lambda root: next(observations)
        compute_output = StringIO()
        with redirect_stdout(compute_output), self.assertRaisesRegex(RuntimeError, "Compute All did not complete"):
            namespace["run"](None)
        compute_report = next(
            json.loads(line) for line in compute_output.getvalue().splitlines() if line.startswith("{")
        )
        self.assertFalse(compute_report["ok"])

        design.computeAll = lambda: True
        observations = iter([([], {}, {}), (all_paths, {}, {})])
        namespace["_root_context_occurrence_map"] = lambda root: next(observations)
        namespace["_timeline_health"] = lambda current: {
            "count": 1,
            "unhealthy": [{"index": 0, "health_state": "error"}],
            "informational": [],
        }
        timeline_output = StringIO()
        with redirect_stdout(timeline_output), self.assertRaisesRegex(RuntimeError, "unhealthy timeline"):
            namespace["run"](None)
        timeline_report = next(
            json.loads(line) for line in timeline_output.getvalue().splitlines() if line.startswith("{")
        )
        self.assertFalse(timeline_report["ok"])

        class RetryAttributes:
            def __init__(self):
                self.values = {}
                self.fail_writes = True

            def itemByName(self, group, name):
                value = self.values.get((group, name))
                return SimpleNamespace(value=value) if value is not None else None

            def add(self, group, name, value):
                if self.fail_writes:
                    return None
                self.values[(group, name)] = value
                return SimpleNamespace(value=value)

        retry_attributes = RetryAttributes()
        child = SimpleNamespace(component=SimpleNamespace(name="", attributes=retry_attributes))

        class Occurrences:
            def __init__(self):
                self.values = []

            @property
            def count(self):
                return len(self.values)

            def item(self, index):
                return self.values[index]

            def addNewComponent(self, matrix):
                self.values.append(child)
                return child

        occurrences = Occurrences()
        parent = SimpleNamespace(occurrences=occurrences)
        with self.assertRaisesRegex(RuntimeError, "failed to write component attribute managed"):
            real_ensure_component_path(parent, "NEW_COMPONENT")
        retry_attributes.fail_writes = False
        created, attribute_updates = real_ensure_component_path(parent, "NEW_COMPONENT")
        self.assertEqual([], created)
        self.assertEqual(
            [{"component_path": "NEW_COMPONENT", "attributes": ["managed", "manifest_sha256"]}],
            attribute_updates,
        )
        self.assertEqual("true", retry_attributes.values[("fusion_parametric_design", "managed")])
        self.assertIn(("fusion_parametric_design", "manifest_sha256"), retry_attributes.values)

        target_document = SimpleNamespace(name=self.manifest.fusion_document)
        app = SimpleNamespace(activeDocument=target_document)
        namespace["_active_design"] = lambda: (app, design)
        observations = iter([([], {}, {})])
        namespace["_root_context_occurrence_map"] = lambda root: next(observations)
        namespace["_ensure_component_path"] = lambda root, path: ([], [])
        event_pumps = []

        def switch_document():
            event_pumps.append(True)
            app.activeDocument = SimpleNamespace(name="Different design")

        namespace["adsk"].doEvents = switch_document
        with redirect_stdout(StringIO()), self.assertRaisesRegex(RuntimeError, "document changed"):
            namespace["run"](None)
        self.assertEqual([True], event_pumps)
        namespace["adsk"].doEvents = lambda: None

        wrong_document = SimpleNamespace(activeDocument=SimpleNamespace(name="Different design"))
        namespace["_active_design"] = lambda: (wrong_document, design)
        with redirect_stdout(StringIO()), self.assertRaisesRegex(RuntimeError, "does not match manifest target"):
            namespace["run"](None)

    def test_scaffold_reports_attribute_updates_and_idempotent_second_pass(self) -> None:
        namespace = load_generated_script(emit_scaffold_script(self.manifest))

        class Attributes:
            def __init__(self):
                self.values = {
                    ("fusion_parametric_design", "managed"): "false",
                }

            def itemByName(self, group, name):
                value = self.values.get((group, name))
                return SimpleNamespace(value=value) if value is not None else None

            def add(self, group, name, value):
                self.values[(group, name)] = value
                return SimpleNamespace(value=value)

        component = SimpleNamespace(name="EXISTING", attributes=Attributes())
        occurrence = SimpleNamespace(component=component)
        component.occurrences = SimpleNamespace(count=0, item=lambda index: None)
        root = SimpleNamespace(
            occurrences=SimpleNamespace(count=1, item=lambda index: occurrence),
        )
        design = SimpleNamespace(
            designType="parametric",
            rootComponent=root,
            timeline=SimpleNamespace(count=0),
            computeAll=lambda: True,
        )
        app = SimpleNamespace(activeDocument=SimpleNamespace(name=self.manifest.fusion_document))
        namespace["COMPONENT_PATHS"] = ["EXISTING"]
        namespace["_active_design"] = lambda: (app, design)
        namespace["_root_context_occurrence_map"] = lambda current: (["EXISTING"], {}, {})

        first_output = StringIO()
        with redirect_stdout(first_output):
            namespace["run"](None)
        first_report = next(
            json.loads(line) for line in first_output.getvalue().splitlines() if line.startswith("{")
        )
        self.assertEqual([], first_report["created"])
        self.assertEqual(
            [{"component_path": "EXISTING", "attributes": ["managed", "manifest_sha256"]}],
            first_report["attribute_updates"],
        )

        second_output = StringIO()
        with redirect_stdout(second_output):
            namespace["run"](None)
        second_report = next(
            json.loads(line) for line in second_output.getvalue().splitlines() if line.startswith("{")
        )
        self.assertEqual([], second_report["created"])
        self.assertEqual([], second_report["attribute_updates"])

    def test_scaffold_success_uses_same_document_snapshot_after_event_pump(self) -> None:
        namespace = load_generated_script(emit_scaffold_script(self.manifest))
        all_paths = sorted(namespace["COMPONENT_PATHS"])
        design = SimpleNamespace(
            designType="parametric",
            rootComponent=SimpleNamespace(),
            timeline=SimpleNamespace(count=0),
            computeAll=lambda: True,
        )
        app = SimpleNamespace(activeDocument=SimpleNamespace(name=self.manifest.fusion_document))
        state = {"edited": False}
        namespace["_active_design"] = lambda: (app, design)
        namespace["_ensure_component_path"] = lambda root, path: ([], [])
        namespace["_root_context_occurrence_map"] = lambda root: (
            (all_paths, {}, {}) if state["edited"] else ([], {}, {})
        )
        namespace["adsk"].doEvents = lambda: state.update(edited=True)
        output = StringIO()
        with redirect_stdout(output):
            namespace["run"](None)
        report = next(json.loads(line) for line in output.getvalue().splitlines() if line.startswith("{"))
        self.assertTrue(report["ok"])
        self.assertEqual(all_paths, report["component_paths"])
        self.assertEqual([], report["missing_component_paths"])
        self.assertTrue(report["report_run_id"])

    def test_verification_script_checks_distance_interference_and_timeline_health(self) -> None:
        source = emit_verification_script(self.manifest)
        self.assert_compiles(source)
        self.assertIn("adsk.doEvents()", source)
        self.assertIn("root_component.allOccurrences", source)
        self.assertIn("fullPathName", source)
        self.assertIn("measureMinimumDistance", source)
        self.assertIn("createInterferenceInput", source)
        self.assertIn("healthState", source)
        self.assertIn("preciseBoundingBox", source)
        self.assertIn("occurrence.bRepBodies", source)
        self.assertIn("solid_body_count", source)
        self.assertIn("expected_print_parts_without_positive_solid", source)
        self.assertIn("def _has_positive_solid_brep", source)
        self.assertIn("positive-volume root-context B-Rep", source)
        self.assertNotIn("def _has_brep", source)
        self.assertIn("ambiguous_component_paths", source)
        self.assertIn("report_attempted = False", source)
        self.assertIn('failures.append("compute-all")', source)
        self.assertIn('failures.append("parameters")', source)

        namespace = load_generated_script(source)
        first_spec = namespace["PARAMETER_SPECS"][0]
        matching = SimpleNamespace(expression=first_spec["expression"], unit=first_spec["units"])
        user_parameters = SimpleNamespace(
            itemByName=lambda name: matching if name == first_spec["name"] else None
        )
        mismatches = namespace["_parameter_mismatches"](user_parameters)
        self.assertTrue(any(row["reason"] == "missing" for row in mismatches))

        unitless_manifest_data = self.manifest.to_dict()
        unitless_manifest_data["parameters"][0]["units"] = ""
        unitless_namespace = load_generated_script(
            emit_verification_script(Manifest.from_data(unitless_manifest_data))
        )
        unitless_spec = unitless_namespace["PARAMETER_SPECS"][0]
        dimensional = SimpleNamespace(expression=unitless_spec["expression"], unit="mm")
        unitless_parameters = SimpleNamespace(
            itemByName=lambda name: dimensional if name == unitless_spec["name"] else None
        )
        unitless_mismatches = unitless_namespace["_parameter_mismatches"](unitless_parameters)
        self.assertIn(
            {
                "name": unitless_spec["name"],
                "reason": "units",
                "expected": "",
                "actual": "mm",
            },
            unitless_mismatches,
        )


if __name__ == "__main__":
    unittest.main()
