from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest

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

    def test_inventory_script_is_read_only_and_compiles(self) -> None:
        source = emit_inventory_script(self.manifest)
        self.assert_compiles(source)
        self.assertIn("FUSION_DESIGN_REPORT_BEGIN", source)
        self.assertIn("root_component.allOccurrences", source)
        self.assertIn("fullPathName", source)
        self.assertIn("duplicate_semantic_paths", source)
        self.assertIn("AllEntitiesBoundingBoxEntityType", source)
        self.assertNotIn("addNewComponent", source)
        self.assertNotIn("userParameters.add", source)

    def test_parameter_sync_is_idempotent_and_never_rebuilds_timeline(self) -> None:
        source = emit_parameter_sync_script(self.manifest)
        self.assert_compiles(source)
        self.assertIn("itemByName", source)
        self.assertIn('existing.expression = spec["expression"]', source)
        self.assertIn("user_parameters.add", source)
        self.assertIn("HealthyFeatureHealthState", source)
        self.assertIn("reported = False", source)
        self.assertIn("existing.unit != spec[\"units\"]", source)
        self.assertIn("Existing parameter unit mismatch", source)
        self.assertIn('"ok": bool(compute_invoked)', source)
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
        namespace["_active_design"] = lambda: (SimpleNamespace(), design)
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
        conflict_namespace["_active_design"] = lambda: (SimpleNamespace(), conflict_design)
        with redirect_stdout(StringIO()), self.assertRaisesRegex(RuntimeError, "unit mismatch"):
            conflict_namespace["run"](None)
        self.assertEqual("unchanged-on-error", early.expression)

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
        text_namespace["_active_design"] = lambda: (SimpleNamespace(), text_design)
        with redirect_stdout(StringIO()):
            text_namespace["run"](None)
        self.assertIn("''", text_parameters.initial_expressions)

    def test_scaffold_ensures_component_paths_without_deleting_existing_geometry(self) -> None:
        source = emit_scaffold_script(self.manifest)
        self.assert_compiles(source)
        self.assertIn("addNewComponent", source)
        self.assertIn("_ensure_component_path", source)
        self.assertIn("preexisting_duplicate_semantic_paths", source)
        self.assertIn("missing_component_paths", source)
        self.assertIn("not duplicate_semantic_paths and not missing_component_paths", source)
        self.assertLess(source.index("preexisting_duplicate_semantic_paths"), source.index("created = []", source.index("def run(context):")))
        self.assertNotIn("deleteMe", source)

        namespace = load_generated_script(source)
        design = SimpleNamespace(designType="parametric", rootComponent=SimpleNamespace())
        observations = iter([([], {}, {}), ([], {}, {})])
        namespace["_active_design"] = lambda: (SimpleNamespace(), design)
        namespace["_root_context_occurrence_map"] = lambda root: next(observations)
        namespace["_ensure_component_path"] = lambda root, path: []
        output = StringIO()
        with redirect_stdout(output), self.assertRaisesRegex(RuntimeError, "component paths are still missing"):
            namespace["run"](None)
        report = next(json.loads(line) for line in output.getvalue().splitlines() if line.startswith("{"))
        self.assertFalse(report["ok"])
        self.assertEqual(sorted(namespace["COMPONENT_PATHS"]), report["missing_component_paths"])

    def test_verification_script_checks_distance_interference_and_timeline_health(self) -> None:
        source = emit_verification_script(self.manifest)
        self.assert_compiles(source)
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
        self.assertIn("reported = False", source)
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


if __name__ == "__main__":
    unittest.main()
