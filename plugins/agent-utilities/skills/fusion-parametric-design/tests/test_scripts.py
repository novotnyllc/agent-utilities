from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest

from fusion_design.export_handoff import emit_export_example_script
from fusion_design.manifest import Manifest, load_manifest
from fusion_design.positive_control import emit_positive_control_script
from fusion_design.scripts import (
    REPORT_BEGIN,
    REPORT_END,
    _script_prelude,
    emit_document_save_script,
    emit_inventory_script,
    emit_parameter_sync_script,
    emit_scaffold_script,
    emit_verification_script,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "electronics-enclosure" / "fusion-project.json"


class _ObjectCollection(list):
    """Stand-in for adsk.core.ObjectCollection (list plus an add method)."""

    def add(self, item) -> None:
        self.append(item)


def _temporary_box(box):
    """Stand-in for TemporaryBRepManager.createBox; Fusion works in centimetres."""
    length, width, height = box.size
    center = box.center
    half = (length / 2.0, width / 2.0, height / 2.0)
    origin = (center.x, center.y, center.z)
    return SimpleNamespace(
        volume_cm3=length * width * height,
        min_cm=[origin[index] - half[index] for index in range(3)],
        max_cm=[origin[index] + half[index] for index in range(3)],
    )


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
    fusion.MeshGenerateFaceGroupsMethodTypes = SimpleNamespace(
        FastGenerateFaceGroupsType="fast",
        AccurateGenerateFaceGroupsType="accurate",
    )
    fusion.BoundingBoxEntityTypes = SimpleNamespace(
        AllEntitiesBoundingBoxEntityType="all-entities",
    )
    core.ValueInput = SimpleNamespace(createByString=lambda expression: expression)
    core.Matrix3D = SimpleNamespace(
        create=lambda: SimpleNamespace(asArray=lambda: [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0])
    )
    core.Point3D = SimpleNamespace(create=lambda x, y, z: SimpleNamespace(x=x, y=y, z=z))
    core.Point2D = SimpleNamespace(create=lambda x, y: SimpleNamespace(x=x, y=y))
    core.Vector3D = SimpleNamespace(create=lambda x, y, z: SimpleNamespace(x=x, y=y, z=z))
    core.OrientedBoundingBox3D = SimpleNamespace(
        create=lambda center, x_axis, y_axis, length, width, height: SimpleNamespace(
            center=center, size=(length, width, height)
        )
    )
    core.ObjectCollection = SimpleNamespace(create=_ObjectCollection)
    fusion.TemporaryBRepManager = SimpleNamespace(
        get=lambda: SimpleNamespace(createBox=_temporary_box)
    )
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
            emit_document_save_script,
        ):
            with self.subTest(emitter=emitter.__name__):
                source = emitter(self.manifest)
                self.assert_compiles_when_wrapped(source)
                self.assertNotIn("from __future__ import", source)

    def test_checked_in_example_scripts_match_canonical_emitters(self) -> None:
        generated = ROOT / "examples" / "electronics-enclosure" / "generated"
        emitted = {
            "inventory.py": emit_inventory_script,
            "sync_parameters.py": emit_parameter_sync_script,
            "scaffold.py": emit_scaffold_script,
            "verify.py": emit_verification_script,
            "export.py": emit_export_example_script,
            "save_document.py": emit_document_save_script,
        }
        for filename, emitter in emitted.items():
            with self.subTest(filename=filename):
                self.assertEqual(
                    emitter(self.manifest),
                    (generated / filename).read_text(encoding="utf-8"),
                )

    def test_positive_control_cleanup_detects_remaining_entities(self) -> None:
        namespace = load_generated_script(emit_positive_control_script(self.manifest))

        class Entity:
            def __init__(self, deletes: bool):
                self.deletes = deletes
                self.isValid = True

            def deleteMe(self):
                if self.deletes:
                    self.isValid = False
                return self.deletes

        self.assertEqual([], namespace["_cleanup_pair"](Entity(True), None))
        self.assertRegex(namespace["_cleanup_pair"](Entity(False), None)[0], "body")

    def test_inventory_script_is_read_only_and_compiles(self) -> None:
        source = emit_inventory_script(self.manifest)
        self.assert_compiles(source)
        self.assert_compiles_when_wrapped(source)
        self.assertNotIn("from __future__ import", source)
        self.assertIn("FUSION_DESIGN_REPORT_BEGIN", source)
        self.assertNotIn('"ok": True', source)
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
        # The ambiguity refusal must still precede the first component creation.
        self.assertLess(
            source.index("preexisting_duplicate_semantic_paths"),
            source.index("_ensure_component_path(design.rootComponent"),
        )
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
        self.assertEqual("component-scaffold", report["kind"])
        self.assertEqual(all_paths, report["component_paths"])
        self.assertEqual([], report["missing_component_paths"])

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
        self.assertIn("print_part_failures", source)
        self.assertIn("def _has_positive_solid_brep", source)
        self.assertIn("positive-volume root-context B-Rep", source)
        self.assertNotIn("def _has_brep", source)
        self.assertIn("ambiguous_component_paths", source)
        self.assertIn("report_attempted = False", source)
        self.assertIn('failures.append("compute-all")', source)
        self.assertIn('failures.append("parameters")', source)
        self.assertIn("occurrence_transforms", source)
        self.assertIn("transform2", source)

        namespace = load_generated_script(source)
        with_transform = SimpleNamespace(
            transform2=SimpleNamespace(asArray=lambda: [1.0] + [0.0] * 15)
        )
        without_transform = SimpleNamespace(transform2=None)
        self.assertEqual([1.0] + [0.0] * 15, namespace["_occurrence_transform"](with_transform))
        self.assertIsNone(namespace["_occurrence_transform"](without_transform))

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

    # Behavioural coverage of run(), the occurrence map, and the body summary
    # against realistic geometry doubles lives in test_generated_transactions.py.

    def test_setup_and_verification_reports_carry_the_document_saved_state(self) -> None:
        for emitter in (emit_inventory_script, emit_verification_script):
            with self.subTest(emitter=emitter.__name__):
                self.assertIn('"document_saved_state": _document_saved_state', emitter(self.manifest))

    def test_document_saved_state_fails_closed_on_every_unreadable_probe(self) -> None:
        state = load_generated_script(_script_prelude(self.manifest))["_document_saved_state"]

        self.assertEqual({"available": False, "reason": "no-active-document"}, state(None))

        no_is_saved = state(SimpleNamespace(name="Untitled"))
        self.assertFalse(no_is_saved["available"])
        self.assertEqual("isSaved-unavailable", no_is_saved["reason"])
        self.assertEqual("Untitled", no_is_saved["name"])

        unsaved = state(SimpleNamespace(name="Untitled", isSaved=False))
        self.assertTrue(unsaved["available"])
        self.assertFalse(unsaved["is_saved"])
        self.assertIsNone(unsaved["data_file"])

        class RaisingDataFile:
            name = "Broken"
            isSaved = True

            @property
            def dataFile(self):
                raise RuntimeError("no cloud item")

        unreadable = state(RaisingDataFile())
        self.assertFalse(unreadable["available"])
        self.assertIn("dataFile-unreadable", unreadable["reason"])

        class RaisingIsSaved:
            name = "Flaky"

            @property
            def isSaved(self):
                raise RuntimeError("2 : InternalValidationError")

        flaky = state(RaisingIsSaved())
        self.assertFalse(flaky["available"])
        self.assertIn("isSaved-unreadable", flaky["reason"])

        saved = state(
            SimpleNamespace(
                name="Wearable Controller Pod v3",
                isSaved=True,
                dataFile=SimpleNamespace(
                    id="urn:test:df-1",
                    versionNumber=3,
                    parentProject=SimpleNamespace(id="proj-1"),
                    parentFolder=SimpleNamespace(id="folder-1"),
                ),
            )
        )
        self.assertTrue(saved["available"])
        self.assertEqual(
            {"id": "urn:test:df-1", "version_number": 3, "project_id": "proj-1", "folder_id": "folder-1"},
            saved["data_file"],
        )

    def test_name_bound_guards_accept_fusions_version_suffix(self) -> None:
        namespace = load_generated_script(_script_prelude(self.manifest))
        target = self.manifest.fusion_document
        is_target = namespace["_is_target_name"]
        self.assertTrue(is_target(target))
        self.assertTrue(is_target(target + " v12"))
        self.assertFalse(is_target(target + " v12b"))
        self.assertFalse(is_target("Another Design"))

        app = SimpleNamespace(activeDocument=SimpleNamespace(name=target + " v3"))
        self.assertIs(app.activeDocument, namespace["_require_target_document"](app))
        wrong = SimpleNamespace(activeDocument=SimpleNamespace(name="Another Design"))
        with self.assertRaisesRegex(RuntimeError, "does not match manifest target"):
            namespace["_require_target_document"](wrong)


class _FakeDataFile:
    def __init__(self, identifier, version=1, project_id="proj-1", folder_id="folder-1"):
        self.id = identifier
        self.versionNumber = version
        self.parentProject = SimpleNamespace(id=project_id)
        self.parentFolder = SimpleNamespace(id=folder_id)


class _FakeDocument:
    def __init__(self, name="Untitled", saved=False, data_file=None, modified=True):
        self.name = name
        self.isSaved = saved
        self.isModified = modified
        self._data_file = data_file
        self.save_calls: list = []
        self.save_as_calls: list = []
        self.app = None

    @property
    def dataFile(self):
        if self._data_file is None:
            raise RuntimeError("this document has never been saved")
        return self._data_file

    def saveAs(self, name, folder, description, tag):
        self.save_as_calls.append((name, getattr(folder, "name", None), description, tag))
        self.name = name + " v1"
        self.isSaved = True
        self.isModified = False
        self._data_file = _FakeDataFile("urn:test:df-new", 1, "proj-1", getattr(folder, "folder_id", "folder-1"))
        return True

    def save(self, description):
        self.save_calls.append(description)
        self.isModified = False
        self._data_file = _FakeDataFile(
            self._data_file.id, self._data_file.versionNumber + 1
        )
        return True

    def activate(self):
        self.app.activeDocument = self


class _FakeDocuments:
    def __init__(self, app, documents):
        self._app = app
        self._documents = list(documents)
        self.opened: list = []

    @property
    def count(self):
        return len(self._documents)

    def item(self, index):
        return self._documents[index]

    def open(self, data_file, visible):
        document = _FakeDocument(
            name="Wearable Controller Pod v" + str(data_file.versionNumber),
            saved=True,
            data_file=data_file,
            modified=False,
        )
        document.app = self._app
        self._documents.append(document)
        self._app.activeDocument = document
        self.opened.append(data_file.id)
        return document


class _FakeApp:
    def __init__(self, documents=(), active=None, data=None):
        self.activeDocument = active
        self.documents = _FakeDocuments(self, documents)
        for document in self.documents._documents:
            document.app = self
        self.data = data


def _root_folder(children=None, name="RootFolder"):
    lookup = dict(children or {})
    return SimpleNamespace(
        name=name,
        folder_id="folder-" + name,
        dataFolders=SimpleNamespace(itemByName=lambda segment: lookup.get(segment)),
    )


class DocumentSaveScriptTests(unittest.TestCase):
    """The save/adopt transaction: never leave a design Untitled, never adopt by name."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = load_manifest(EXAMPLE)
        cls.target = cls.manifest.fusion_document

    def _run(self, source: str, app, expect_error: str | None = None):
        namespace = load_generated_script(source)
        namespace["adsk"].core.Application = SimpleNamespace(get=lambda: app)
        output = StringIO()
        if expect_error is None:
            with redirect_stdout(output):
                namespace["run"](None)
        else:
            with redirect_stdout(output), self.assertRaisesRegex(RuntimeError, expect_error):
                namespace["run"](None)
        reports = [
            json.loads(line) for line in output.getvalue().splitlines() if line.startswith("{")
        ]
        self.assertTrue(reports, "the transaction emitted no report")
        return reports[-1]

    def test_first_save_names_the_untitled_document_from_the_manifest(self) -> None:
        source = emit_document_save_script(self.manifest)
        document = _FakeDocument()
        app = _FakeApp(
            documents=[document],
            active=document,
            data=SimpleNamespace(activeProject=SimpleNamespace(rootFolder=_root_folder())),
        )
        report = self._run(source, app)
        self.assertTrue(report["ok"])
        self.assertEqual("saved-as", report["save_action"])
        self.assertEqual("adopted-active-document", report["adoption"])
        self.assertEqual([(self.target, "RootFolder", document.save_as_calls[0][2], "")], document.save_as_calls)
        self.assertEqual("urn:test:df-new", report["data_file"]["id"])
        self.assertTrue(report["data_file_id_stable"])
        self.assertTrue(report["name_matches_manifest"])
        self.assertTrue(document.isSaved)

    def test_manifest_document_folder_resolves_under_the_project_root(self) -> None:
        data = self.manifest.to_dict()
        data["project"]["document_folder"] = "Designs/Pods"
        manifest = Manifest.from_data(data)
        source = emit_document_save_script(manifest)

        pods = _root_folder(name="Pods")
        designs = _root_folder({"Pods": pods}, name="Designs")
        document = _FakeDocument()
        app = _FakeApp(
            documents=[document],
            active=document,
            data=SimpleNamespace(
                activeProject=SimpleNamespace(rootFolder=_root_folder({"Designs": designs}))
            ),
        )
        report = self._run(source, app)
        self.assertTrue(report["ok"])
        self.assertEqual([(self.target, "Pods", document.save_as_calls[0][2], "")], document.save_as_calls)

        missing = _FakeDocument()
        missing_app = _FakeApp(
            documents=[missing],
            active=missing,
            data=SimpleNamespace(activeProject=SimpleNamespace(rootFolder=_root_folder())),
        )
        refusal = self._run(source, missing_app, expect_error="folder-not-found")
        self.assertFalse(refusal["ok"])
        self.assertEqual("folder-not-found", refusal["refusal"])
        self.assertEqual("Designs", refusal["detail"]["segment"])
        self.assertEqual([], missing.save_as_calls)
        self.assertFalse(missing.isSaved)

    def test_a_raising_active_project_falls_back_to_the_data_panel_folder(self) -> None:
        """Measured live: Data.activeProject raises InternalValidationError on a
        healthy session, so the probe must catch, and Data.activeFolder -- the
        save dialog's own default -- is the fallback."""
        panel = _root_folder(name="PanelFolder")

        class RaisingData:
            activeFolder = panel

            @property
            def activeProject(self):
                raise RuntimeError("2 : InternalValidationError : id.size()")

        source = emit_document_save_script(self.manifest)
        document = _FakeDocument()
        app = _FakeApp(documents=[document], active=document, data=RaisingData())
        report = self._run(source, app)
        self.assertTrue(report["ok"])
        self.assertEqual("PanelFolder", document.save_as_calls[0][1])

        # With a declared document_folder the path is re-anchored at the panel
        # folder's own project root.
        data = self.manifest.to_dict()
        data["project"]["document_folder"] = "Designs"
        anchored_source = emit_document_save_script(Manifest.from_data(data))
        designs = _root_folder(name="Designs")
        panel.parentProject = SimpleNamespace(rootFolder=_root_folder({"Designs": designs}))
        anchored_document = _FakeDocument()
        anchored_app = _FakeApp(
            documents=[anchored_document], active=anchored_document, data=RaisingData()
        )
        anchored = self._run(anchored_source, anchored_app)
        self.assertTrue(anchored["ok"])
        self.assertEqual("Designs", anchored_document.save_as_calls[0][1])

    def test_no_resolvable_folder_is_a_named_refusal_not_a_silent_untitled(self) -> None:
        source = emit_document_save_script(self.manifest)
        for app, refusal in (
            (_FakeApp(documents=[_FakeDocument()], active=None), "no-active-document"),
            (
                _FakeApp(documents=[(document := _FakeDocument())], active=document, data=None),
                "data-api-unavailable",
            ),
            (
                _FakeApp(
                    documents=[(document := _FakeDocument())],
                    active=document,
                    data=SimpleNamespace(activeProject=None),
                ),
                "no-active-project",
            ),
        ):
            with self.subTest(refusal=refusal):
                report = self._run(source, app, expect_error=refusal)
                self.assertFalse(report["ok"])
                self.assertEqual(refusal, report["refusal"])

    def test_checkpoint_saves_a_version_only_when_the_document_is_modified(self) -> None:
        source = emit_document_save_script(self.manifest)
        document = _FakeDocument(
            name=self.target + " v3", saved=True, data_file=_FakeDataFile("urn:test:df-1", 3), modified=True
        )
        app = _FakeApp(documents=[document], active=document)
        report = self._run(source, app)
        self.assertTrue(report["ok"])
        self.assertEqual("saved-version", report["save_action"])
        self.assertEqual(1, len(document.save_calls))
        self.assertEqual(4, report["data_file"]["version_number"])

        clean = self._run(source, app)
        self.assertTrue(clean["ok"])
        self.assertEqual("already-saved", clean["save_action"])
        self.assertEqual(1, len(document.save_calls))

    def test_a_different_saved_document_is_refused_never_adopted(self) -> None:
        source = emit_document_save_script(self.manifest)
        document = _FakeDocument(
            name="Someone Elses Design v9", saved=True, data_file=_FakeDataFile("urn:test:df-other"), modified=True
        )
        app = _FakeApp(documents=[document], active=document)
        report = self._run(source, app, expect_error="active-document-not-target")
        self.assertEqual("active-document-not-target", report["refusal"])
        self.assertEqual([], document.save_calls)
        self.assertEqual([], document.save_as_calls)

    def test_reconnect_adopts_the_open_document_by_data_file_id(self) -> None:
        source = emit_document_save_script(self.manifest, "urn:test:df-1")
        self.assertIn('DOCUMENT_ID = json.loads(\'"urn:test:df-1"\')', source)
        other = _FakeDocument(name="Untitled", saved=False)
        # Renamed by the user: identity is the id, the name is only reported.
        target = _FakeDocument(
            name="Renamed By The User v7", saved=True, data_file=_FakeDataFile("urn:test:df-1", 7), modified=False
        )
        app = _FakeApp(documents=[other, target], active=other)
        report = self._run(source, app)
        self.assertTrue(report["ok"])
        self.assertEqual("adopted-open-document", report["adoption"])
        self.assertEqual("already-saved", report["save_action"])
        self.assertIs(app.activeDocument, target)
        self.assertFalse(report["name_matches_manifest"])
        self.assertEqual("Renamed By The User v7", report["document_name"])
        # The user's other open document was never saved or renamed.
        self.assertEqual([], other.save_calls)
        self.assertEqual([], other.save_as_calls)

    def test_reconnect_opens_a_closed_document_through_the_data_api(self) -> None:
        source = emit_document_save_script(self.manifest, "urn:test:df-9")
        recorded = _FakeDataFile("urn:test:df-9", 5)
        app = _FakeApp(
            documents=[],
            active=None,
            data=SimpleNamespace(findFileById=lambda identifier: recorded if identifier == "urn:test:df-9" else None),
        )
        report = self._run(source, app)
        self.assertTrue(report["ok"])
        self.assertEqual("opened-recorded-document", report["adoption"])
        self.assertEqual(["urn:test:df-9"], app.documents.opened)
        self.assertEqual("urn:test:df-9", report["data_file"]["id"])

    def test_reconnect_refuses_a_missing_id_and_reports_name_matches_only_as_hints(self) -> None:
        source = emit_document_save_script(self.manifest, "urn:test:df-gone")
        lookalike = _FakeDocument(
            name=self.target + " v2", saved=True, data_file=_FakeDataFile("urn:test:df-different"), modified=True
        )
        app = _FakeApp(
            documents=[lookalike],
            active=lookalike,
            data=SimpleNamespace(findFileById=lambda identifier: None),
        )
        report = self._run(source, app, expect_error="recorded-document-not-found")
        self.assertFalse(report["ok"])
        self.assertEqual("recorded-document-not-found", report["refusal"])
        self.assertEqual("urn:test:df-gone", report["detail"]["recorded_data_file_id"])
        self.assertEqual([self.target + " v2"], report["detail"]["name_match_hints"])
        # A name match is a hint, never an identity: nothing was saved.
        self.assertEqual([], lookalike.save_calls)

        offline = _FakeApp(documents=[], active=None, data=None)
        offline_report = self._run(source, offline, expect_error="data-api-unavailable")
        self.assertEqual("data-api-unavailable", offline_report["refusal"])

        # Measured live: findFileById raises for a missing id, so the refusal
        # carries the raw error text rather than swallowing it.
        def raising_lookup(identifier):
            raise RuntimeError("3 : file not found")

        raising = _FakeApp(
            documents=[], active=None, data=SimpleNamespace(findFileById=raising_lookup)
        )
        raised_report = self._run(source, raising, expect_error="recorded-document-not-found")
        self.assertEqual("3 : file not found", raised_report["detail"]["error"])


if __name__ == "__main__":
    unittest.main()


class ReportTeeTests(unittest.TestCase):
    """A transport timeout must not be able to lose a report the transaction produced.

    GFG-Accurate on a 524k-triangle scan ran 330 seconds against an MCP transport
    that gives up at 180. The grouping was applied, the report was discarded, and
    the pipeline was stuck on an operation that had already succeeded. stdout is
    not a durable channel, so `_emit` also writes the report beside the
    transaction's own inputs and says on stdout where it put it.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = load_manifest(
            Path(__file__).resolve().parents[1]
            / "examples"
            / "electronics-enclosure"
            / "fusion-project.json"
        )

    def _emitter(self, source: str):
        namespace = load_generated_script(source)
        return namespace["_emit"], namespace

    def test_a_declared_directory_gets_the_same_bytes_stdout_carries(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            emit, _namespace = self._emitter(_script_prelude(self.manifest, report_dir=directory))
            captured = StringIO()
            with redirect_stdout(captured):
                emit({"kind": "mesh-generate-face-groups", "ok": True})
            printed = json.loads(
                captured.getvalue().split(REPORT_BEGIN)[1].split(REPORT_END)[0].strip()
            )
            path = Path(printed["report_tee_path"])
            self.assertTrue(path.is_file(), printed)
            self.assertEqual(directory, str(path.parent))
            self.assertEqual(printed, json.loads(path.read_text(encoding="utf-8")))
            self.assertNotIn("report_tee_error", printed)

    def test_two_transaction_kinds_in_one_directory_do_not_clobber_each_other(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            emit, _namespace = self._emitter(_script_prelude(self.manifest, report_dir=directory))
            with redirect_stdout(StringIO()):
                emit({"kind": "mesh-extract", "ok": True})
                emit({"kind": "mesh-generate-face-groups", "ok": True})
                emit({"kind": "mesh-extract", "ok": False})
            written = sorted(p.name for p in Path(directory).iterdir())
            self.assertEqual(2, len(written), written)
            # Re-running one transaction overwrites only its own report.
            extract = next(p for p in Path(directory).iterdir() if "mesh-extract" in p.name)
            self.assertIs(False, json.loads(extract.read_text(encoding="utf-8"))["ok"])

    def test_two_runs_of_one_transaction_kind_do_not_race_for_one_file(self) -> None:
        """Concurrent agents are a supported hazard, so they get separate files.

        Same kind, same manifest, same directory: without a per-run identity in
        the name both runs resolved to one path, their writes interleaved, and
        a recovery read after a transport timeout could hand back the other
        run's report as if it were this one's.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            source = _script_prelude(self.manifest, report_dir=directory)
            paths = []
            for ok in (True, False):
                # A second load is a second run of the same emitted bytes,
                # which is exactly what two agents driving one transaction are.
                emit, namespace = self._emitter(source)
                namespace["RUN_ID"] = "run-%s" % ok
                captured = StringIO()
                with redirect_stdout(captured):
                    emit({"kind": "mesh-extract", "ok": ok})
                printed = json.loads(
                    captured.getvalue().split(REPORT_BEGIN)[1].split(REPORT_END)[0].strip()
                )
                paths.append(Path(printed["report_tee_path"]))
            self.assertNotEqual(paths[0], paths[1])
            for path, ok in zip(paths, (True, False)):
                self.assertTrue(path.is_file(), path)
                self.assertIs(ok, json.loads(path.read_text(encoding="utf-8"))["ok"])
            # And nothing is left half-written beside them.
            self.assertEqual(
                [], [p.name for p in Path(directory).iterdir() if p.name.endswith(".partial")]
            )

    def test_the_run_id_is_bound_at_run_time_not_at_emission(self) -> None:
        # Emission stays byte-identical -- several tests here and the checked-in
        # example scripts rest on that -- so the identity is computed when the
        # transaction runs.
        source = _script_prelude(self.manifest, report_dir="/tmp")
        self.assertEqual(source, _script_prelude(self.manifest, report_dir="/tmp"))
        self.assertIn("RUN_ID = ", source)
        first = load_generated_script(source)["RUN_ID"]
        self.assertTrue(first)

    def test_a_transaction_with_no_output_directory_says_so_rather_than_going_quiet(self) -> None:
        emit, _namespace = self._emitter(_script_prelude(self.manifest))
        captured = StringIO()
        with redirect_stdout(captured):
            emit({"kind": "inventory"})
        printed = json.loads(
            captured.getvalue().split(REPORT_BEGIN)[1].split(REPORT_END)[0].strip()
        )
        self.assertIsNone(printed["report_tee_path"])
        self.assertIn("only on stdout", printed["report_tee_unavailable_reason"])

    def test_an_unwritable_directory_reports_the_failure_and_still_emits(self) -> None:
        emit, _namespace = self._emitter(
            _script_prelude(self.manifest, report_dir="/nonexistent-directory-for-this-test")
        )
        captured = StringIO()
        with redirect_stdout(captured):
            emit({"kind": "mesh-extract", "ok": True})
        printed = json.loads(
            captured.getvalue().split(REPORT_BEGIN)[1].split(REPORT_END)[0].strip()
        )
        # Losing the tee must never lose the transaction.
        self.assertIs(True, printed["ok"])
        self.assertIn("report_tee_error", printed)
