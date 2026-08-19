from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import re
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

MATERIAL_DECISION = {
    "family": "PETG",
    "formulation": "Prusament PETG",
    "source_id": "pd_trigger_board_measurement",
    "confidence": "provisional",
    "coupon_component": "90_VALIDATION/VAL__PD_FIT_COUPON",
    "rationale": "The snap-fit lid needs PETG toughness; PLA would fail brittle at the snap.",
    "unresolved_risks": ["Snap strain is unverified until the coupon prints."],
}

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
    "printer",
    "filament",
    "process_profile",
}


# manufacturing_intent legitimately declares its own support_policy; everything
# else inside it is still subject to the forbidden-claim gate.
INTENT_EXEMPT_KEYS = frozenset({"support_policy"})

# Keys are not the only channel: a whole slicer preset pasted into a prose field
# (printer_requirements, a rationale, a risk) reaches the index as a string value
# and reads to a key-only sweep as nothing at all. Each pattern reports the
# forbidden claim it is evidence of, so the existing key assertions catch it.
# Naming the product on the spool is what `formulation` is for, so a brand name
# is not a claim; a machine model and a process preset are.
FORBIDDEN_CLAIM_VALUE_PATTERNS = (
    ("printer", r"\bmk\d|\bbambu\w*|\bender\b|\bvoron\b|\bx1c\b|\bp1s\b"),
    ("filament", r"\bfilament[ _-](?:profile|preset)"),
    (
        "process_profile",
        r"process profile|print profile|\bpreset\w*|\bperimeters\b|\binfill\b|layer height|\bgyroid\b|prusaslicer",
    ),
)


def _collect_keys(value, keys, exempt=frozenset()):
    """Collect every key — and every string value — that reads as a slicer claim.

    manufacturing_intent is descended into, exempting only its own declared
    support_policy, so a planted printer/filament/slicing key still trips.
    """
    if isinstance(value, dict):
        for key, child in value.items():
            if key not in exempt:
                keys.add(key)
            _collect_keys(child, keys, INTENT_EXEMPT_KEYS if key == "manufacturing_intent" else frozenset())
    elif isinstance(value, list):
        for child in value:
            _collect_keys(child, keys, exempt)
    elif isinstance(value, str):
        for claim, pattern in FORBIDDEN_CLAIM_VALUE_PATTERNS:
            if re.search(pattern, value, re.IGNORECASE):
                keys.add(claim)


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
    """A component whose measured properties agree with the bound verification.

    Takes the whole per-part binding, not just bounds: the staleness gate
    re-measures bounds, solid volume, and placement, so a fake that only carries
    bounds would exercise a third of the gate.
    """

    def __init__(self, bodies, binding):
        bodies = list(bodies)
        self.bRepBodies = FakeBodies(bodies)
        self.bounds = binding["bounds_mm"]
        solids = [body for body in bodies if body.isSolid and body.volume > 0]
        if solids:
            share = float(binding["total_solid_volume_mm3"]) / 1000.0 / len(solids)
            for body in solids:
                body.volume = share
        self.component = SimpleNamespace(name="component")
        transform = list(binding["transform"])
        self.transform2 = SimpleNamespace(asArray=lambda: transform)


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
            verification_binding=verification_binding_from_report(self.manifest, report),
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
            emit_export_script(self.manifest, ExportConfig(good.export_dir, ("3mf",), good.verification_report_sha256, good.verification_binding))
        with self.assertRaisesRegex(ValueError, "Unsupported export formats"):
            emit_export_script(self.manifest, ExportConfig(good.export_dir, ("step", "obj"), good.verification_report_sha256, good.verification_binding))
        with self.assertRaisesRegex(ValueError, "must not repeat"):
            emit_export_script(self.manifest, ExportConfig(good.export_dir, ("step", "step"), good.verification_report_sha256, good.verification_binding))
        with self.assertRaisesRegex(ValueError, "non-empty"):
            emit_export_script(self.manifest, ExportConfig("  ", good.formats, good.verification_report_sha256, good.verification_binding))
        with self.assertRaisesRegex(ValueError, "lowercase hex SHA-256"):
            emit_export_script(self.manifest, ExportConfig(good.export_dir, good.formats, "not-a-digest", good.verification_binding))
        partial_bounds = dict(good.verification_binding)
        partial_bounds.pop(self.print_parts[0])
        with self.assertRaisesRegex(ValueError, "missing for print parts"):
            emit_export_script(self.manifest, ExportConfig(good.export_dir, good.formats, good.verification_report_sha256, partial_bounds))

    def test_padded_manifest_paths_still_carry_manufacturing_intent(self) -> None:
        from fusion_design.manifest import Manifest, validate_manifest_data

        # The validator strips printable-part paths before matching them against
        # verification.expected_print_parts, so the emitter must strip too or the
        # export index silently drops the intent for a padded part.
        data = self.manifest.to_dict()
        part = data["printable_parts"][0]
        part["path"] = "  " + part["path"] + "  "
        part["body_name"] = "  " + (part.get("body_name") or "PADDED_BODY") + "  "
        self.assertEqual([], validate_manifest_data(data))

        padded = Manifest.from_data(data)
        config = self._config("/tmp/example-exports")
        specs = load_generated_script(emit_export_script(padded, config))["EXPORT_SPECS"]
        by_path = {spec["path"]: spec for spec in specs["parts"]}
        self.assertEqual(set(self.print_parts), set(by_path))
        for path in self.print_parts:
            self.assertIn("manufacturing_intent", by_path[path])
        self.assertEqual(
            part["body_name"].strip(),
            by_path[part["path"].strip()]["expected_body_name"],
        )

    def test_incomplete_manufacturing_intent_coverage_fails_closed(self) -> None:
        from fusion_design.manifest import Manifest

        data = self.manifest.to_dict()
        dropped = data["printable_parts"].pop()["path"]
        # validate=False on purpose: the validator rejects this manifest, and the
        # guard exists for exactly the un-validated construction path.
        partial = Manifest.from_data(data, validate=False)
        with self.assertRaises(ValueError) as ctx:
            emit_export_script(partial, self._config("/tmp/example-exports"))
        self.assertIn("Manufacturing intent is missing for print parts", str(ctx.exception))
        self.assertIn(dropped, str(ctx.exception))

    def test_forbidden_claim_gate_inspects_inside_manufacturing_intent(self) -> None:
        planted: set = set()
        _collect_keys(
            {"artifacts": [{"manufacturing_intent": {"printer": "some-printer", "support_policy": "none"}}]},
            planted,
        )
        self.assertEqual({"printer"}, planted & FORBIDDEN_CLAIM_KEYS)

    def test_forbidden_claim_gate_inspects_inside_material_decision(self) -> None:
        planted: set = set()
        _collect_keys(
            {"material_decision": {**MATERIAL_DECISION, "filament": "some-filament", "process_profile": "0.2 fast"}},
            planted,
        )
        self.assertEqual({"filament", "process_profile"}, planted & FORBIDDEN_CLAIM_KEYS)
        legitimate: set = set()
        _collect_keys({"material_decision": {**MATERIAL_DECISION, "printer_requirements": "Any nozzle."}}, legitimate)
        self.assertFalse(legitimate & FORBIDDEN_CLAIM_KEYS)

    def test_forbidden_claim_gate_inspects_string_values_not_only_keys(self) -> None:
        """A slicer preset is a forbidden claim wherever it is written, key or value."""
        preset = (
            "Prusa MK4S with a hardened steel nozzle; Prusament PA11CF Carbon Fiber; "
            "STRUCTURAL process profile, five perimeters, gyroid infill."
        )
        for field in ("printer_requirements", "rationale"):
            with self.subTest(field=field):
                planted: set = set()
                _collect_keys({"material_decision": {**MATERIAL_DECISION, field: preset}}, planted)
                self.assertEqual(
                    {"printer", "process_profile"}, planted & FORBIDDEN_CLAIM_KEYS
                )
        # The brand name alone is legitimate: naming the product on the spool is
        # exactly what `formulation` is for.
        legitimate: set = set()
        _collect_keys({"material_decision": {**MATERIAL_DECISION, "formulation": "Prusament PETG"}}, legitimate)
        self.assertFalse(legitimate & FORBIDDEN_CLAIM_KEYS)
        nested: set = set()
        _collect_keys({"material_decision": {**MATERIAL_DECISION, "unresolved_risks": [preset]}}, nested)
        self.assertTrue(nested & FORBIDDEN_CLAIM_KEYS)

    def test_filename_collisions_fail_at_emit_time(self) -> None:
        good = self._config("/tmp/example-exports")
        colliding = json.loads(json.dumps(self.manifest.to_dict()))
        colliding.pop("printable_parts", None)
        # Two component paths whose slugs collide (lowercase folding).
        colliding["component_tree"].extend(["10_PRODUCT/PROD__CASE", "10_PRODUCT/prod__case"])
        colliding["verification"]["expected_print_parts"] = ["10_PRODUCT/PROD__CASE", "10_PRODUCT/prod__case"]
        from fusion_design.manifest import Manifest

        manifest = Manifest.from_data(colliding)
        one_binding = {
            "bounds_mm": {"min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, 1.0]},
            "total_solid_volume_mm3": 1.0,
            "transform": [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0],
        }
        bounds = {
            "10_PRODUCT/PROD__CASE": one_binding,
            "10_PRODUCT/prod__case": one_binding,
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
            bounds = dict(good.verification_binding)
            bounds[part] = {**good.verification_binding[part], "bounds_mm": bad}
            with self.assertRaises(ValueError):
                emit_export_script(
                    self.manifest,
                    ExportConfig(good.export_dir, good.formats, good.verification_report_sha256, bounds),
                )

    def test_volume_and_transform_binding_reject_unusable_values(self) -> None:
        good = self._config("/tmp/example-exports")
        part = self.print_parts[0]
        for field, bad in (
            ("total_solid_volume_mm3", 0.0),
            ("total_solid_volume_mm3", -1.0),
            ("total_solid_volume_mm3", float("nan")),
            ("total_solid_volume_mm3", "12000"),
            ("transform", None),
            ("transform", [1.0, 0.0, 0.0]),
            ("transform", [float("inf")] * 16),
        ):
            with self.subTest(field=field, bad=bad):
                binding = dict(good.verification_binding)
                binding[part] = {**good.verification_binding[part], field: bad}
                with self.assertRaises(ValueError):
                    emit_export_script(
                        self.manifest,
                        ExportConfig(good.export_dir, good.formats, good.verification_report_sha256, binding),
                    )

    def test_report_without_geometry_or_transforms_is_refused(self) -> None:
        report = example_verification_report(self.manifest)
        for key in ("geometry", "occurrence_transforms"):
            with self.subTest(key=key):
                stripped = {name: value for name, value in report.items() if name != key}
                with self.assertRaisesRegex(ValueError, f"missing {key}"):
                    verification_binding_from_report(self.manifest, stripped)

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
            verification_binding=bounds,
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
        maximum = bounds[self.print_parts[0]]["bounds_mm"]["max"]
        drifted = {
            path: FakeOccurrence(
                [FakeBody("BODY")],
                {
                    **bounds[path],
                    "bounds_mm": {
                        "min": bounds[path]["bounds_mm"]["min"],
                        "max": [
                            bounds[path]["bounds_mm"]["max"][0] + 1.0,
                            bounds[path]["bounds_mm"]["max"][1],
                            bounds[path]["bounds_mm"]["max"][2],
                        ],
                    },
                },
            )
            for path in self.print_parts
        }
        self.assertEqual(3, len(maximum))
        namespace = self._namespace(occurrences=drifted)
        reports = self._run_expect_failure(namespace, "stale-verification")
        self.assertIn("stale-verification", reports[0]["failures"])
        self.assertTrue(all(row["reason"] == "bounds-drifted" for row in reports[0]["stale_parts"]))
        self.assertEqual([], list(self.export_dir.iterdir()))

    def test_equal_extent_edits_are_caught_by_volume_and_placement(self) -> None:
        """Bounds alone are six numbers; an edit that preserves them must not pass.

        This is the whole reason the gate binds more than a bounding box: hollowing
        a part or nudging its occurrence leaves the extent identical.
        """
        bounds = verification_binding_from_report(self.manifest, example_verification_report(self.manifest))
        for reason, mutate in (
            (
                "volume-drifted",
                lambda binding: {**binding, "total_solid_volume_mm3": binding["total_solid_volume_mm3"] * 0.9},
            ),
            (
                "transform-drifted",
                lambda binding: {**binding, "transform": binding["transform"][:12] + [1.0, 0.0, 0.0, 1.0]},
            ),
        ):
            with self.subTest(reason=reason):
                edited = {
                    path: FakeOccurrence([FakeBody("BODY")], mutate(bounds[path]))
                    for path in self.print_parts
                }
                namespace = self._namespace(occurrences=edited)
                reports = self._run_expect_failure(namespace, "stale-verification")
                self.assertTrue(all(row["reason"] == reason for row in reports[0]["stale_parts"]))
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

    def test_index_carries_manufacturing_intent_from_manifest(self) -> None:
        namespace = self._namespace()
        report = self._run(namespace)[0]
        intent_by_path = {part["path"]: part for part in self.manifest.printable_parts}
        for artifact in report["artifacts"]:
            intent = artifact["manufacturing_intent"]
            declared = intent_by_path[artifact["part_path"]]
            # The manifest entry also carries manifest-only keys (path, body_name);
            # every key the intent does carry must match the declaration exactly.
            self.assertEqual({key: declared[key] for key in intent}, intent)
            self.assertEqual(
                {
                    "id",
                    "quantity",
                    "print_as",
                    "orientation",
                    "support_policy",
                    "strength",
                    "protected_features",
                    "material",
                },
                set(intent),
            )
        index = json.loads(next(self.export_dir.glob("export-index__*.json")).read_text(encoding="utf-8"))
        keys: set = set()
        _collect_keys(index, keys)
        self.assertFalse(keys & FORBIDDEN_CLAIM_KEYS, keys & FORBIDDEN_CLAIM_KEYS)

    def test_index_carries_material_decision_once_at_index_level(self) -> None:
        from fusion_design.manifest import Manifest

        declared = self.manifest.to_dict()
        declared["material_decision"] = json.loads(json.dumps(MATERIAL_DECISION))
        self.manifest = Manifest.from_data(declared)

        report = self._run(self._namespace())[0]
        self.assertEqual(MATERIAL_DECISION, report["material_decision"])
        for artifact in report["artifacts"]:
            self.assertNotIn("material_decision", artifact)
        index = json.loads(next(self.export_dir.glob("export-index__*.json")).read_text(encoding="utf-8"))
        self.assertEqual(MATERIAL_DECISION, index["material_decision"])
        keys: set = set()
        _collect_keys(index, keys)
        self.assertFalse(keys & FORBIDDEN_CLAIM_KEYS, keys & FORBIDDEN_CLAIM_KEYS)

    def test_index_carries_the_example_manifests_own_decision(self) -> None:
        declared = self.manifest.material_decision
        self.assertEqual("PETG", declared["family"])
        report = self._run(self._namespace())[0]
        self.assertEqual(declared, report["material_decision"])
        index = json.loads(next(self.export_dir.glob("export-index__*.json")).read_text(encoding="utf-8"))
        self.assertEqual(declared, index["material_decision"])
        keys: set = set()
        _collect_keys(index, keys)
        self.assertFalse(keys & FORBIDDEN_CLAIM_KEYS, keys & FORBIDDEN_CLAIM_KEYS)

    def test_index_omits_material_decision_when_manifest_declares_none(self) -> None:
        from fusion_design.manifest import Manifest

        stripped = self.manifest.to_dict()
        stripped.pop("material_decision")
        self.manifest = Manifest.from_data(stripped)
        self.assertEqual({}, self.manifest.material_decision)
        report = self._run(self._namespace())[0]
        self.assertNotIn("material_decision", report)
        index = json.loads(next(self.export_dir.glob("export-index__*.json")).read_text(encoding="utf-8"))
        self.assertNotIn("material_decision", index)

    def test_index_carries_explicit_support_regions(self) -> None:
        from fusion_design.manifest import Manifest

        declared = self.manifest.to_dict()
        regions = [
            {"kind": "enforcer", "description": "Support the USB-C port ceiling."},
            {"kind": "blocker", "description": "Keep supports out of the sealing groove."},
        ]
        declared["printable_parts"][0]["support_policy"] = "explicit-regions"
        declared["printable_parts"][0]["support_regions"] = regions
        part_path = declared["printable_parts"][0]["path"]
        self.manifest = Manifest.from_data(declared)

        report = self._run(self._namespace())[0]
        matching = [
            artifact for artifact in report["artifacts"] if artifact["part_path"] == part_path
        ]
        self.assertTrue(matching)
        for artifact in matching:
            self.assertEqual("explicit-regions", artifact["manufacturing_intent"]["support_policy"])
            self.assertEqual(regions, artifact["manufacturing_intent"]["support_regions"])
        for artifact in report["artifacts"]:
            if artifact["part_path"] != part_path:
                self.assertNotIn("support_regions", artifact["manufacturing_intent"])

    def test_index_omits_intent_when_manifest_has_none(self) -> None:
        from fusion_design.manifest import Manifest

        stripped = self.manifest.to_dict()
        stripped.pop("printable_parts")
        intentless = Manifest.from_data(stripped)
        report_data = example_verification_report(intentless)
        bounds = verification_binding_from_report(intentless, report_data)
        config = ExportConfig(
            export_dir=str(self.export_dir),
            formats=("step", "3mf"),
            verification_report_sha256=hashlib.sha256(b"x" * 10).hexdigest(),
            verification_binding=bounds,
        )
        source = emit_export_script(intentless, config)
        namespace = load_generated_script(source)
        occurrences = {
            path: FakeOccurrence([FakeBody("BODY")], bounds[path]) for path in self.print_parts
        }
        manager = FakeExportManager()
        design = SimpleNamespace(
            exportManager=manager,
            rootComponent=SimpleNamespace(),
            unitsManager=SimpleNamespace(defaultLengthUnits="mm"),
        )
        app = SimpleNamespace(activeDocument=SimpleNamespace(name=intentless.fusion_document, isSaved=False))
        namespace["_active_design"] = lambda: (app, design)
        namespace["_root_context_occurrence_map"] = lambda root: (sorted(occurrences), dict(occurrences), {})
        namespace["_bbox_mm"] = lambda occurrence: occurrence.bounds
        report = self._run(namespace)[0]
        for artifact in report["artifacts"]:
            self.assertNotIn("manufacturing_intent", artifact)

    def test_declared_body_name_mismatch_fails_closed(self) -> None:
        from fusion_design.manifest import Manifest

        declared = self.manifest.to_dict()
        declared["printable_parts"][0]["body_name"] = "EXPECTED_BODY"
        manifest = Manifest.from_data(declared)
        report_data = example_verification_report(manifest)
        bounds = verification_binding_from_report(manifest, report_data)
        config = ExportConfig(
            export_dir=str(self.export_dir),
            formats=("step", "3mf"),
            verification_report_sha256=hashlib.sha256(b"y" * 10).hexdigest(),
            verification_binding=bounds,
        )
        source = emit_export_script(manifest, config)
        self.assertIn("body-name-mismatch", source)
        namespace = load_generated_script(source)
        occurrences = {
            path: FakeOccurrence([FakeBody("SOME_OTHER_NAME")], bounds[path]) for path in self.print_parts
        }
        design = SimpleNamespace(
            exportManager=FakeExportManager(),
            rootComponent=SimpleNamespace(),
            unitsManager=SimpleNamespace(defaultLengthUnits="mm"),
        )
        app = SimpleNamespace(activeDocument=SimpleNamespace(name=manifest.fusion_document, isSaved=False))
        namespace["_active_design"] = lambda: (app, design)
        namespace["_root_context_occurrence_map"] = lambda root: (sorted(occurrences), dict(occurrences), {})
        namespace["_bbox_mm"] = lambda occurrence: occurrence.bounds
        reports = self._run_expect_failure(namespace, "body-name-mismatch")
        self.assertIn("body-name-mismatch", reports[0]["failures"])
        self.assertEqual([], list(self.export_dir.iterdir()))

        matching = {
            path: FakeOccurrence([FakeBody("EXPECTED_BODY")], bounds[path]) for path in self.print_parts
        }
        namespace["_root_context_occurrence_map"] = lambda root: (sorted(matching), dict(matching), {})
        report = self._run(namespace)[0]
        self.assertTrue(report["ok"])

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
