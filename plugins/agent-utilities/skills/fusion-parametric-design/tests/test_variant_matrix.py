from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from fusion_design.export_handoff import example_verification_report
from fusion_design.manifest import Manifest
from fusion_design.scripts import manifest_sha256
from fusion_design.variant_matrix import (
    CAPTURE_CONFIGURATION_STEP,
    CAPTURE_STATE_STEP,
    RESTORE_CONFIGURATION_STEP,
    RESTORE_PARAMETERS_STEP,
    VERIFY_RESTORE_STEP,
    MatrixConfig,
    StepReportUnavailable,
    build_matrix_plan,
    emit_configuration_script,
    run_variant_matrix,
    saved_report_executor,
    variant_manifest,
)
from fusion_design.variants import variant_id


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "electronics-enclosure" / "fusion-project.json"

# The document starts on values the manifest does not declare, so "restored"
# means restored to what was found, not to what the manifest wishes were true.
INITIAL_EXPRESSIONS = {"des_corner_radius": "4.5 mm", "fab_wall_thickness": "2.4 mm"}
INITIAL_CONFIGURATION = "Base"

VARIANTS = [
    {"id": "small", "description": "Compact enclosure.", "parameters": {"des_corner_radius": "3 mm"}},
    {
        "id": "medium",
        "description": "Mid enclosure.",
        "parameters": {"des_corner_radius": "6 mm", "fab_wall_thickness": "2.5 mm"},
    },
    {"id": "large", "description": "Large enclosure.", "parameters": {"des_corner_radius": "8 mm"}},
]


def _manifest(variants=None) -> Manifest:
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data["variants"] = copy.deepcopy(VARIANTS if variants is None else variants)
    return Manifest.from_data(data)


class _FakeFusion:
    """Answers each planned step the way a live Fusion session would."""

    def __init__(
        self,
        manifest: Manifest,
        *,
        fail_steps: set[tuple[str, str]] | None = None,
        raise_steps: set[tuple[str, str]] | None = None,
        slow_steps: set[tuple[str, str]] | None = None,
        readback: dict[str, str] | None = None,
        restored_configuration: str = INITIAL_CONFIGURATION,
    ) -> None:
        self.manifest = manifest
        self.fail_steps = fail_steps or set()
        self.raise_steps = raise_steps or set()
        self.slow_steps = slow_steps or set()
        self.readback = INITIAL_EXPRESSIONS if readback is None else readback
        self.restored_configuration = restored_configuration
        self.derived = {
            variant_id(variant): variant_manifest(manifest, variant) for variant in manifest.variants
        }
        self.calls: list[tuple[str, str]] = []
        self.now = 0.0

    def clock(self) -> float:
        return self.now

    def __call__(self, step):
        key = (step.variant_id, step.step_id)
        self.calls.append(key)
        if key in self.raise_steps:
            raise RuntimeError("Fusion transaction failed")
        self.now += 10_000.0 if key in self.slow_steps else 1.0
        ok = key not in self.fail_steps
        report = {
            "kind": step.report_kind,
            "project": self.manifest.project_name,
            "manifest_sha256": step.manifest_sha256,
            "ok": ok,
        }
        if step.report_kind == "inventory":
            source = self.readback if step.step_id == VERIFY_RESTORE_STEP else INITIAL_EXPRESSIONS
            report["parameters"] = {
                name: {"expression": expression, "units": "mm", "comment": ""}
                for name, expression in source.items()
            }
        elif step.report_kind == "verification":
            sample = example_verification_report(self.derived[step.variant_id])
            report["brep_bounding_boxes_mm"] = sample["brep_bounding_boxes_mm"]
            report["compute_invoked"] = ok
            report["timeline"] = {"count": 4, "unhealthy": [] if ok else [{"index": 2}], "informational": []}
            report["failures"] = [] if ok else ["clearance", "timeline-health"]
            report["clearance_results"] = [
                {"id": "pd-to-lid", "ok": True, "distance_mm": 1.0},
                {"id": "mesh-only", "ok": False, "error": "Automated clearance checks require a B-Rep envelope"},
            ]
        elif step.report_kind == "configuration-activation":
            if step.step_id == CAPTURE_CONFIGURATION_STEP:
                report["active_configuration"] = INITIAL_CONFIGURATION
            elif step.step_id == RESTORE_CONFIGURATION_STEP:
                report["active_configuration"] = self.restored_configuration
            else:
                report["active_configuration"] = str(
                    next(
                        variant.get("configuration", "")
                        for variant in self.manifest.variants
                        if variant_id(variant) == step.variant_id
                    )
                )
            report["available_configurations"] = ["Base", "Config A"]
        elif step.report_kind == "export-handoff":
            report["export_dir"] = f"/exports/{step.variant_id}"
            report["artifacts"] = [
                {
                    "part_path": "10_PRODUCT/PROD__BASE",
                    "filename": f"pod__{step.variant_id}.step",
                    "sha256": "0" * 64,
                    "byte_size": 1234,
                }
            ]
        return report


def _run(manifest, fake, config=None):
    return run_variant_matrix(
        manifest, config or MatrixConfig(), fake, clock=fake.clock
    )


class VariantMatrixRunTests(unittest.TestCase):
    def test_every_variant_passing_produces_a_row_each_and_a_verified_restore(self) -> None:
        manifest = _manifest()
        fake = _FakeFusion(manifest)
        record = _run(manifest, fake)

        self.assertTrue(record["ok"], record["failures"])
        self.assertTrue(record["complete"])
        self.assertEqual([], record["failures"])
        self.assertEqual(["small", "medium", "large"], [row["variant_id"] for row in record["variants"]])
        self.assertTrue(all(row["ok"] for row in record["variants"]))
        self.assertEqual(INITIAL_EXPRESSIONS, record["initial_state"]["parameters"])
        self.assertTrue(record["restore"]["ok"])
        self.assertTrue(record["restore"]["verified"])
        self.assertEqual([], record["restore"]["mismatches"])

    def test_each_row_reports_compute_timeline_failure_tokens_and_unsupported_checks(self) -> None:
        manifest = _manifest()
        record = _run(manifest, _FakeFusion(manifest))
        row = record["variants"][0]
        self.assertTrue(row["compute_invoked"])
        self.assertEqual(0, row["timeline_unhealthy_count"])
        self.assertEqual([], row["verification_failures"])
        self.assertEqual(["mesh-only"], [check["id"] for check in row["unsupported_checks"]])

    def test_a_failing_middle_variant_keeps_earlier_evidence_and_fails_the_run(self) -> None:
        manifest = _manifest()
        fake = _FakeFusion(manifest, fail_steps={("medium", "verify")})
        record = _run(manifest, fake)

        self.assertFalse(record["ok"])
        self.assertIn("variant-failed", record["failures"])
        rows = record["variants"]
        self.assertEqual(["small", "medium"], [row["variant_id"] for row in rows])
        self.assertTrue(rows[0]["ok"])
        self.assertFalse(rows[1]["ok"])
        self.assertEqual(["verify"], rows[1]["failures"])
        self.assertEqual(["clearance", "timeline-health"], rows[1]["verification_failures"])
        # Restoration happens after the failure, which is exactly when a
        # best-effort cleanup would be least trustworthy.
        self.assertTrue(record["restore"]["attempted"])
        self.assertTrue(record["restore"]["verified"])

    def test_continue_policy_never_reports_partial_success_as_success(self) -> None:
        manifest = _manifest()
        fake = _FakeFusion(manifest, fail_steps={("medium", "apply")})
        record = _run(manifest, fake, MatrixConfig(on_failure="continue"))

        self.assertEqual(3, len(record["variants"]))
        self.assertEqual([True, False, True], [row["ok"] for row in record["variants"]])
        self.assertFalse(record["ok"])
        self.assertIn("variant-failed", record["failures"])

    def test_restoration_runs_after_an_exception_and_the_record_survives(self) -> None:
        manifest = _manifest()
        fake = _FakeFusion(manifest, raise_steps={("medium", "inventory")})
        record = _run(manifest, fake)

        self.assertFalse(record["ok"])
        self.assertEqual(2, len(record["variants"]))
        self.assertEqual(["inventory"], record["variants"][1]["failures"])
        self.assertTrue(record["restore"]["verified"])
        self.assertIn(("", VERIFY_RESTORE_STEP), fake.calls)

    def test_a_failed_restore_is_itself_a_loud_failure(self) -> None:
        manifest = _manifest()
        fake = _FakeFusion(manifest, fail_steps={("", RESTORE_PARAMETERS_STEP)})
        record = _run(manifest, fake)

        self.assertFalse(record["ok"])
        self.assertIn("restore", record["failures"])
        self.assertFalse(record["restore"]["ok"])
        self.assertIn("Restoring the initial parameter", record["restore"]["reason"])

    def test_a_readback_that_disagrees_with_the_snapshot_fails_the_run(self) -> None:
        manifest = _manifest()
        drifted = dict(INITIAL_EXPRESSIONS, des_corner_radius="8 mm")
        fake = _FakeFusion(manifest, readback=drifted)
        record = _run(manifest, fake)

        self.assertFalse(record["ok"])
        self.assertIn("restore", record["failures"])
        self.assertFalse(record["restore"]["verified"])
        self.assertEqual(
            [{"name": "des_corner_radius", "expected": "4.5 mm", "actual": "8 mm"}],
            record["restore"]["mismatches"],
        )

    def test_a_step_that_outruns_its_budget_fails_that_variant_without_corrupting_the_record(self) -> None:
        manifest = _manifest()
        fake = _FakeFusion(manifest, slow_steps={("medium", "apply")})
        record = _run(manifest, fake, MatrixConfig(timeout_seconds=60.0))

        self.assertFalse(record["ok"])
        rows = record["variants"]
        self.assertTrue(rows[0]["ok"])
        self.assertFalse(rows[1]["ok"])
        timed_out = [step for step in rows[1]["steps"] if step.get("timed_out")]
        self.assertEqual(["apply"], [step["step_id"] for step in timed_out])
        self.assertTrue(record["restore"]["verified"])

    def test_an_unrestorable_initial_capture_stops_before_any_variant_is_applied(self) -> None:
        manifest = _manifest()
        fake = _FakeFusion(manifest)
        fake.readback = {}

        def executor(step):
            report = fake(step)
            if step.step_id == CAPTURE_STATE_STEP:
                report["parameters"] = {}
            return report

        record = run_variant_matrix(manifest, MatrixConfig(), executor, clock=fake.clock)
        self.assertFalse(record["ok"])
        self.assertIn("runner-error", record["failures"])
        self.assertIn("cannot be restored must not start", record["error"])
        self.assertEqual([], record["variants"])
        self.assertFalse(record["restore"]["required"])

    def test_a_failed_initial_capture_fails_the_run_and_requires_no_restore(self) -> None:
        manifest = _manifest()
        fake = _FakeFusion(manifest, fail_steps={("", CAPTURE_STATE_STEP)})
        record = _run(manifest, fake)

        self.assertFalse(record["ok"])
        self.assertEqual(["initial-state-capture"], record["failures"])
        self.assertEqual([], record["variants"])
        self.assertFalse(record["restore"]["required"])


class VariantMatrixEvidenceTests(unittest.TestCase):
    def test_report_identities_and_export_paths_are_unique_and_carry_the_variant_id(self) -> None:
        manifest = _manifest()
        plan = build_matrix_plan(manifest, MatrixConfig(export_dir="/exports"))
        names = [step.report_name for step in plan]
        self.assertEqual(len(names), len(set(names)))
        for step in plan:
            if step.variant_id:
                self.assertTrue(step.report_name.startswith(f"{step.variant_id}__"), step.report_name)

        fake = _FakeFusion(manifest)
        record = run_variant_matrix(
            manifest, MatrixConfig(export_dir="/exports"), fake, clock=fake.clock
        )
        self.assertTrue(record["ok"], record["failures"])
        directories = [row["export"]["export_dir"] for row in record["variants"]]
        self.assertEqual(len(directories), len(set(directories)))
        self.assertEqual(["/exports/small", "/exports/medium", "/exports/large"], directories)
        self.assertEqual("0" * 64, record["variants"][0]["export"]["artifacts"][0]["sha256"])

    def test_two_configuration_variants_still_get_distinct_evidence_paths(self) -> None:
        # Configuration variants leave the manifest hash unchanged, so identity
        # has to come from the variant id or their evidence would collide.
        manifest = _manifest(
            [
                {"id": "config_a", "description": "Config A.", "configuration": "Config A"},
                {"id": "config_b", "description": "Config B.", "configuration": "Config B"},
            ]
        )
        plan = build_matrix_plan(manifest, MatrixConfig(export_dir="/exports"))
        names = [step.report_name for step in plan]
        self.assertEqual(len(names), len(set(names)))

    def test_each_variant_manifest_carries_its_own_expressions_and_hash(self) -> None:
        manifest = _manifest()
        derived = [variant_manifest(manifest, variant) for variant in manifest.variants]
        digests = [manifest_sha256(one) for one in derived]
        self.assertEqual(len(digests), len(set(digests)))
        self.assertNotIn(manifest_sha256(manifest), digests)
        expressions = {
            parameter["name"]: parameter["expression"]
            for parameter in derived[1].parameters
            if parameter["name"] in INITIAL_EXPRESSIONS
        }
        self.assertEqual({"des_corner_radius": "6 mm", "fab_wall_thickness": "2.5 mm"}, expressions)

    def test_the_export_step_binds_to_this_variants_verification_report(self) -> None:
        manifest = _manifest([VARIANTS[0]])
        captured: dict[str, str] = {}
        fake = _FakeFusion(manifest)

        def executor(step):
            if step.step_id == "export":
                captured["script"] = step.script or ""
            return fake(step)

        record = run_variant_matrix(
            manifest, MatrixConfig(export_dir="/exports"), executor, clock=fake.clock
        )
        self.assertTrue(record["ok"], record["failures"])
        script = captured["script"]
        self.assertIn(manifest_sha256(variant_manifest(manifest, manifest.variants[0])), script)
        self.assertIn("/exports/small", script)
        compile(script, "export.py", "exec")


class VariantMatrixPlanTests(unittest.TestCase):
    def test_step_order_is_capture_then_variants_then_restore(self) -> None:
        manifest = _manifest()
        plan = build_matrix_plan(manifest, MatrixConfig())
        order = [(step.step_id, step.variant_id) for step in plan]
        self.assertEqual((CAPTURE_STATE_STEP, ""), order[0])
        self.assertEqual([(RESTORE_PARAMETERS_STEP, ""), (VERIFY_RESTORE_STEP, "")], order[-2:])
        self.assertEqual(
            [("apply", "small"), ("inventory", "small"), ("verify", "small")], order[1:4]
        )
        self.assertNotIn((CAPTURE_CONFIGURATION_STEP, ""), order)

    def test_a_configuration_family_captures_and_restores_the_active_row(self) -> None:
        manifest = _manifest([{"id": "config_a", "description": "Config A.", "configuration": "Config A"}])
        plan = build_matrix_plan(manifest, MatrixConfig())
        order = [step.step_id for step in plan]
        self.assertIn(CAPTURE_CONFIGURATION_STEP, order)
        self.assertIn(RESTORE_CONFIGURATION_STEP, order)
        self.assertNotIn(RESTORE_PARAMETERS_STEP, order)

        fake = _FakeFusion(manifest)
        record = _run(manifest, fake)
        self.assertTrue(record["ok"], record["failures"])
        self.assertEqual(INITIAL_CONFIGURATION, record["initial_state"]["configuration"])
        self.assertEqual(INITIAL_CONFIGURATION, record["restore"]["active_configuration"])

    def test_a_configuration_restored_to_the_wrong_row_fails_the_run(self) -> None:
        manifest = _manifest([{"id": "config_a", "description": "Config A.", "configuration": "Config A"}])
        fake = _FakeFusion(manifest, restored_configuration="Config A")
        record = _run(manifest, fake)
        self.assertFalse(record["ok"])
        self.assertIn("restore", record["failures"])
        self.assertIn("is not the captured", record["restore"]["reason"])

    def test_configuration_activation_fails_closed_when_the_api_is_absent(self) -> None:
        manifest = _manifest()
        script = emit_configuration_script(manifest, "Config A")
        compile(script, "configuration.py", "exec")
        self.assertIn("no Design.configurationTable", script)
        self.assertIn("Refusing to continue", script)
        self.assertIn("configuration-not-active", script)
        self.assertIn('"kind": "configuration-activation"', script)

    def test_planning_a_manifest_without_variants_is_refused(self) -> None:
        data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        with self.assertRaises(ValueError) as context:
            build_matrix_plan(Manifest.from_data(data), MatrixConfig())
        self.assertIn("declares no variants", str(context.exception))

    def test_matrix_config_rejects_an_unknown_policy_and_a_useless_timeout(self) -> None:
        for kwargs in (
            {"on_failure": "carry-on"},
            {"on_failure": {"stop": True}},
            {"timeout_seconds": 0},
            {"timeout_seconds": float("nan")},
            {"timeout_seconds": True},
            {"export_dir": "   "},
        ):
            with self.subTest(**{key: str(value) for key, value in kwargs.items()}):
                with self.assertRaises(ValueError):
                    MatrixConfig(**kwargs)


class SavedReportExecutorTests(unittest.TestCase):
    def test_a_missing_report_halts_the_run_and_names_the_next_step(self) -> None:
        manifest = _manifest()
        with tempfile.TemporaryDirectory() as temporary:
            record = run_variant_matrix(
                manifest, MatrixConfig(), saved_report_executor(temporary)
            )
        self.assertFalse(record["complete"])
        self.assertFalse(record["ok"])
        self.assertEqual([], record["failures"])
        self.assertEqual(CAPTURE_STATE_STEP, record["next_step"]["step_id"])
        self.assertIn("import adsk.core", record["next_step"]["script"])

    def test_saved_reports_are_folded_and_the_run_resumes_at_the_first_gap(self) -> None:
        manifest = _manifest([VARIANTS[0]])
        fake = _FakeFusion(manifest)
        plan = build_matrix_plan(manifest, MatrixConfig())
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for step in plan[:2]:
                report = fake(step)
                (directory / step.report_name).write_text(
                    json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
            record = run_variant_matrix(manifest, MatrixConfig(), saved_report_executor(directory))

        self.assertFalse(record["complete"])
        self.assertEqual([], record["failures"])
        self.assertTrue(record["initial_state"]["captured"])
        self.assertEqual(1, len(record["variants"]))
        self.assertEqual("inventory", record["next_step"]["step_id"])
        self.assertEqual("small", record["next_step"]["variant_id"])

    def test_a_report_bound_to_another_manifest_is_rejected(self) -> None:
        manifest = _manifest([VARIANTS[0]])
        fake = _FakeFusion(manifest)

        def executor(step):
            report = fake(step)
            if step.step_id == "verify":
                report["manifest_sha256"] = "f" * 64
            return report

        record = run_variant_matrix(manifest, MatrixConfig(), executor, clock=fake.clock)
        self.assertFalse(record["ok"])
        failure = [step for step in record["variants"][0]["steps"] if step["step_id"] == "verify"][0]
        self.assertIn("does not belong to this variant", failure["error"])

    def test_unavailable_is_not_confused_with_failure(self) -> None:
        manifest = _manifest([VARIANTS[0]])

        def executor(step):
            raise StepReportUnavailable("not yet")

        record = run_variant_matrix(manifest, MatrixConfig(), executor)
        self.assertEqual([], record["failures"])
        self.assertFalse(record["complete"])


if __name__ == "__main__":
    unittest.main()
