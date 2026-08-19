from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from fusion_design.export_handoff import example_verification_report
from fusion_design.manifest import Manifest, ManifestValidationError
from fusion_design.scripts import emit_inventory_script, manifest_sha256
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
    restore_manifest,
    run_variant_matrix,
    saved_report_executor,
    variant_manifest,
)
# Private, deliberately: these two are the seams the guard tests need.
from fusion_design.variant_matrix import _MatrixRun, _canonical_report_bytes
from fusion_design.variants import MAXIMUM_VARIANTS, variant_id


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "electronics-enclosure" / "fusion-project.json"

# The document starts on values the manifest does not declare, so "restored"
# means restored to what was found, not to what the manifest wishes were true.
# src_pd_board_length is the case no variant overrides and the sync still
# rewrites: the manifest declares 35 mm and the document is sitting at 99 mm.
INITIAL_DRIFT = {
    "des_corner_radius": "4.5 mm",
    "fab_wall_thickness": "2.4 mm",
    "src_pd_board_length": "99 mm",
}
INITIAL_CONFIGURATION = "Base"


def _document_parameters(manifest: Manifest, **overrides: str) -> dict[str, str]:
    """What a real inventory reports: every parameter in the document."""
    state = {parameter["name"]: parameter["expression"] for parameter in manifest.parameters}
    state.update(INITIAL_DRIFT)
    state.update(overrides)
    return state


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
    """Answers each planned step the way a live Fusion session would.

    Deliberately able to lie the way a hand-saved report directory lies: the
    declared ``ok`` is separable from the failure tokens (``declared_ok``), the
    configuration a report claims is separable from the variant that asked for
    it (``reported_configuration``), and the read-back state is separable from
    the captured one.  A fixture that derives everything from one flag cannot
    express the stale, cross-variant evidence the fold-forward executor reads.
    """

    def __init__(
        self,
        manifest: Manifest,
        *,
        fail_steps: set[tuple[str, str]] | None = None,
        raise_steps: set[tuple[str, str]] | None = None,
        slow_steps: set[tuple[str, str]] | None = None,
        readback: dict[str, str] | None = None,
        restored_configuration: str = INITIAL_CONFIGURATION,
        declared_ok: dict[tuple[str, str], bool] | None = None,
        reported_configuration: dict[str, str] | None = None,
    ) -> None:
        self.manifest = manifest
        self.fail_steps = fail_steps or set()
        self.raise_steps = raise_steps or set()
        self.slow_steps = slow_steps or set()
        self.initial = _document_parameters(manifest)
        self.readback = self.initial if readback is None else readback
        self.restored_configuration = restored_configuration
        self.declared_ok = declared_ok or {}
        self.reported_configuration = reported_configuration or {}
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
            source = self.readback if step.step_id == VERIFY_RESTORE_STEP else self.initial
            report["parameters"] = {
                name: {"expression": expression, "units": "mm", "comment": ""}
                for name, expression in source.items()
            }
        elif step.report_kind == "verification":
            sample = example_verification_report(self.derived[step.variant_id])
            # All three measured properties the export's staleness binding reads,
            # not bounds alone.
            for measured in ("brep_bounding_boxes_mm", "geometry", "occurrence_transforms"):
                report[measured] = sample[measured]
            report["compute_invoked"] = ok
            report["timeline"] = {"count": 4, "unhealthy": [] if ok else [{"index": 2}], "informational": []}
            report["failures"] = [] if ok else ["clearance", "timeline-health"]
            report["clearance_results"] = [
                {"id": "pd-to-lid", "ok": True, "distance_mm": 1.0},
                {"id": "mesh-only", "ok": False, "error": "Automated clearance checks require a B-Rep envelope"},
            ]
        elif step.report_kind == "configuration-activation":
            if step.step_id == CAPTURE_CONFIGURATION_STEP:
                requested, active = None, INITIAL_CONFIGURATION
            elif step.step_id == RESTORE_CONFIGURATION_STEP:
                requested = active = self.restored_configuration
            else:
                requested = active = self.reported_configuration.get(
                    step.variant_id,
                    str(
                        next(
                            variant.get("configuration", "")
                            for variant in self.manifest.variants
                            if variant_id(variant) == step.variant_id
                        )
                    ),
                )
            report["requested_configuration"] = requested
            report["active_configuration"] = active
            report["available_configurations"] = ["Base", "Config A", "Config B"]
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
        if key in self.declared_ok:
            report["ok"] = self.declared_ok[key]
        return report


def _run(manifest, fake, config=None):
    return run_variant_matrix(
        manifest, config or MatrixConfig(), fake, clock=fake.clock
    )


def seed_reports(manifest, directory, fake=None, config=None):
    """Save a whole run's reports the way an agent folding forward would.

    Driven through a real run so every deferred step's report carries the hash
    the runner computes at run time, not one the test guessed.
    """
    fake = fake or _FakeFusion(manifest)

    def executor(step):
        report = fake(step)
        (Path(directory) / step.report_name).write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return report

    run_variant_matrix(manifest, config or MatrixConfig(), executor, clock=fake.clock)
    return fake


def _halting(fake, at):
    """The fake, but the given (variant_id, step_id) has no report yet."""

    def executor(step):
        if (step.variant_id, step.step_id) == at:
            raise StepReportUnavailable("not yet")
        return fake(step)

    return executor


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
        self.assertEqual(_document_parameters(manifest), record["initial_state"]["parameters"])
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
        drifted = dict(_document_parameters(manifest), des_corner_radius="8 mm")
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
        record = _run(manifest, fake, MatrixConfig(slow_step_seconds=60.0))

        self.assertFalse(record["ok"])
        rows = record["variants"]
        self.assertTrue(rows[0]["ok"])
        self.assertFalse(rows[1]["ok"])
        overran = [step for step in rows[1]["steps"] if step.get("overran")]
        self.assertEqual(["apply"], [step["step_id"] for step in overran])
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


class HaltedRunTests(unittest.TestCase):
    """A halt means "not done yet"; it must never launder "already failed"."""

    def test_a_variant_already_proved_bad_fails_the_run_even_while_it_halts(self) -> None:
        manifest = _manifest()
        fake = _FakeFusion(manifest, fail_steps={("small", "verify")})
        record = run_variant_matrix(
            manifest,
            MatrixConfig(on_failure="continue"),
            _halting(fake, ("large", "apply")),
            clock=fake.clock,
        )

        self.assertFalse(record["complete"])
        self.assertFalse(record["ok"])
        # This is the exit code the acceptance loop gates on.
        self.assertIn("variant-failed", record["failures"])
        self.assertEqual("large", record["next_step"]["variant_id"])
        self.assertEqual(
            [("small", False), ("medium", True), ("large", False)],
            [(row["variant_id"], row["ok"]) for row in record["variants"]],
        )

    def test_the_row_being_waited_on_is_pending_not_failed(self) -> None:
        manifest = _manifest()
        fake = _FakeFusion(manifest)
        record = run_variant_matrix(
            manifest, MatrixConfig(), _halting(fake, ("medium", "verify")), clock=fake.clock
        )

        self.assertEqual([], record["failures"])
        self.assertFalse(record["complete"])
        self.assertFalse(record["variants"][-1]["ok"])

    def test_a_halt_after_an_apply_says_the_document_is_still_on_that_variant(self) -> None:
        manifest = _manifest()
        fake = _FakeFusion(manifest)
        record = run_variant_matrix(
            manifest, MatrixConfig(), _halting(fake, ("small", "inventory")), clock=fake.clock
        )

        restore = record["restore"]
        self.assertTrue(restore["required"])
        self.assertFalse(restore["ok"])
        self.assertFalse(restore["verified"])
        self.assertIn("not been verifiably restored", restore["reason"])

    def test_a_halt_before_any_apply_says_the_document_never_moved(self) -> None:
        manifest = _manifest()
        fake = _FakeFusion(manifest)
        record = run_variant_matrix(
            manifest, MatrixConfig(), _halting(fake, ("", CAPTURE_STATE_STEP)), clock=fake.clock
        )

        restore = record["restore"]
        self.assertFalse(restore["required"])
        self.assertTrue(restore["ok"])
        self.assertIn("never moved", restore["reason"])


class RestoreCoverageTests(unittest.TestCase):
    """The sync writes every declared parameter, so the snapshot must too."""

    def test_a_parameter_no_variant_overrides_must_still_come_back(self) -> None:
        manifest = _manifest()
        # The sync drove this one from the document's 99 mm to the manifest's
        # 35 mm; a restore that leaves it there is not a restore.
        drifted = _document_parameters(manifest, src_pd_board_length="35 mm")
        record = _run(manifest, _FakeFusion(manifest, readback=drifted))

        self.assertFalse(record["ok"])
        self.assertIn("restore", record["failures"])
        self.assertFalse(record["restore"]["verified"])
        self.assertEqual(
            [{"name": "src_pd_board_length", "expected": "99 mm", "actual": "35 mm"}],
            record["restore"]["mismatches"],
        )

    def test_a_configuration_only_matrix_compares_real_parameters(self) -> None:
        manifest = _manifest([{"id": "config_a", "description": "A.", "configuration": "Config A"}])
        drifted = _document_parameters(manifest, des_corner_radius="999 mm")
        record = _run(manifest, _FakeFusion(manifest, readback=drifted))

        self.assertFalse(record["ok"])
        self.assertIn("restore", record["failures"])
        self.assertEqual(
            ["des_corner_radius"], [entry["name"] for entry in record["restore"]["mismatches"]]
        )

    def test_a_declared_parameter_absent_from_the_document_is_named_not_hidden(self) -> None:
        manifest = _manifest()
        fake = _FakeFusion(manifest)
        fake.initial = {
            name: expression
            for name, expression in fake.initial.items()
            if name != "pack_usb_c_straight_departure"
        }
        fake.readback = fake.initial
        record = _run(manifest, fake)

        self.assertTrue(record["ok"], record["failures"])
        self.assertEqual(
            ["pack_usb_c_straight_departure"], record["initial_state"]["parameters_absent"]
        )

    def test_restore_manifest_refuses_a_parameter_the_manifest_does_not_declare(self) -> None:
        with self.assertRaises(ValueError) as context:
            restore_manifest(_manifest(), {"not_declared": "1 mm"})
        self.assertIn("does not declare", str(context.exception))

    def test_an_unverifiable_restore_is_a_loud_failure_not_a_crash(self) -> None:
        manifest = _manifest()
        fake = _FakeFusion(manifest)
        run = _MatrixRun(manifest, MatrixConfig(), fake, fake.clock)

        def boom() -> None:
            raise ValueError("the snapshot cannot be turned into a manifest")

        run._restore = boom
        record = run.run()

        self.assertFalse(record["ok"])
        self.assertIn("restore", record["failures"])
        self.assertIn("cannot be turned into a manifest", record["restore"]["reason"])


class RestoreRecordShapeTests(unittest.TestCase):
    """docs/live-fusion-acceptance.md tells the operator to read these keys."""

    KEYS = {"required", "attempted", "ok", "verified", "mismatches", "reason", "steps"}

    def _restores(self):
        manifest = _manifest([VARIANTS[0]])
        fake = _FakeFusion(manifest)
        yield "clean run", _run(manifest, _FakeFusion(manifest))["restore"]
        yield "no capture", _run(
            manifest, _FakeFusion(manifest, fail_steps={("", CAPTURE_STATE_STEP)})
        )["restore"]
        yield "failed restore step", _run(
            manifest, _FakeFusion(manifest, fail_steps={("", RESTORE_PARAMETERS_STEP)})
        )["restore"]
        yield "failed read-back", _run(
            manifest, _FakeFusion(manifest, fail_steps={("", VERIFY_RESTORE_STEP)})
        )["restore"]
        yield "halted", run_variant_matrix(
            manifest, MatrixConfig(), _halting(fake, ("small", "inventory")), clock=fake.clock
        )["restore"]

    def test_every_exit_path_reports_the_whole_restore_block(self) -> None:
        for label, restore in self._restores():
            with self.subTest(path=label):
                self.assertEqual(self.KEYS, set(restore))
                self.assertIsInstance(restore["mismatches"], list)
                self.assertTrue(restore["reason"].strip())
                # Never "ok" without the read-back that earns it.
                self.assertEqual(restore["ok"] and restore["required"], restore["verified"])


class ExportConstructionTests(unittest.TestCase):
    def test_an_unusable_verification_report_fails_only_that_variants_export(self) -> None:
        manifest = _manifest()
        fake = _FakeFusion(manifest)

        def executor(step):
            report = fake(step)
            if (step.variant_id, step.step_id) == ("small", "verify"):
                # Passes _report_rejection, but the export emitter cannot bind
                # to it.
                report.pop("brep_bounding_boxes_mm")
            return report

        record = run_variant_matrix(
            manifest,
            MatrixConfig(export_dir="/exports", on_failure="continue"),
            executor,
            clock=fake.clock,
        )
        rows = record["variants"]
        self.assertEqual([False, True, True], [row["ok"] for row in rows])
        self.assertEqual(["export"], rows[0]["failures"])
        self.assertIn("brep_bounding_boxes_mm", rows[0]["steps"][-1]["error"])
        self.assertNotIn("runner-error", record["failures"])

    def test_any_emitter_fault_stays_this_variants_failure(self) -> None:
        manifest = _manifest()
        fake = _FakeFusion(manifest)
        run = _MatrixRun(manifest, MatrixConfig(export_dir="/exports", on_failure="continue"), fake, fake.clock)
        calls: list[str] = []

        def boom(derived, identity, report, raw):
            calls.append(identity)
            if identity == "small":
                raise RuntimeError("the export emitter blew up in a new way")
            return _MatrixRun._export_script(run, derived, identity, report, raw)

        run._export_script = boom
        record = run.run()

        self.assertEqual(["small", "medium", "large"], calls)
        self.assertEqual(["export"], record["variants"][0]["failures"])
        self.assertNotIn("runner-error", record["failures"])
        self.assertEqual([False, True, True], [row["ok"] for row in record["variants"]])


class ReportTrustTests(unittest.TestCase):
    """The report directory is hand-maintained across many invocations."""

    def test_a_report_declaring_ok_with_failure_tokens_is_rejected(self) -> None:
        manifest = _manifest([VARIANTS[0]])
        fake = _FakeFusion(
            manifest,
            fail_steps={("small", "verify")},
            declared_ok={("small", "verify"): True},
        )
        record = run_variant_matrix(
            manifest, MatrixConfig(export_dir="/exports"), fake, clock=fake.clock
        )

        self.assertFalse(record["ok"])
        row = record["variants"][0]
        self.assertEqual(["verify"], row["failures"])
        failure = [step for step in row["steps"] if step["step_id"] == "verify"][0]
        self.assertIn("contradicts itself", failure["error"])
        # A contradictory report must not go on to drive an export.
        self.assertNotIn(("small", "export"), fake.calls)

    def test_a_report_declaring_ok_over_an_unhealthy_timeline_is_rejected(self) -> None:
        manifest = _manifest([VARIANTS[0]])
        fake = _FakeFusion(manifest)

        def executor(step):
            report = fake(step)
            if step.step_id == "verify":
                report["timeline"] = {"count": 4, "unhealthy": [{"index": 2}], "informational": []}
            return report

        record = run_variant_matrix(manifest, MatrixConfig(), executor, clock=fake.clock)
        self.assertFalse(record["ok"])
        failure = [step for step in record["variants"][0]["steps"] if step["step_id"] == "verify"][0]
        self.assertIn("unhealthy timeline", failure["error"])

    def test_a_configuration_report_naming_another_row_is_rejected(self) -> None:
        manifest = _manifest(
            [
                {"id": "config_a", "description": "A.", "configuration": "Config A"},
                {"id": "config_b", "description": "B.", "configuration": "Config B"},
            ]
        )
        # Every configuration variant derives the base manifest unchanged, so
        # the hash cannot catch this one; the activated row has to.
        fake = _FakeFusion(manifest, reported_configuration={"config_b": "Config A"})
        record = _run(manifest, fake)

        self.assertFalse(record["ok"])
        rows = record["variants"]
        self.assertEqual([True, False], [row["ok"] for row in rows])
        self.assertIn("does not belong to this variant", rows[1]["steps"][0]["error"])

    def test_a_verification_report_for_another_document_does_not_summarise_this_row(self) -> None:
        manifest = _manifest([VARIANTS[0]])
        fake = _FakeFusion(manifest)

        def executor(step):
            report = fake(step)
            if step.step_id == "verify":
                report["manifest_sha256"] = "f" * 64
                report["failures"] = ["clearance"]
            return report

        record = run_variant_matrix(manifest, MatrixConfig(), executor, clock=fake.clock)
        row = record["variants"][0]
        self.assertEqual(["verify"], row["failures"])
        self.assertNotIn("verification_failures", row)

    def test_a_malformed_executor_result_fails_that_step(self) -> None:
        manifest = _manifest([VARIANTS[0]])
        fake = _FakeFusion(manifest)
        record = run_variant_matrix(
            manifest, MatrixConfig(), lambda step: (fake(step),), clock=fake.clock
        )

        self.assertFalse(record["ok"])
        self.assertIn(
            "(report, raw_report_bytes)", record["initial_state"]["steps"][0]["error"]
        )

    def test_the_fallback_digest_uses_the_bytes_fusion_actually_prints(self) -> None:
        # An executor with no raw bytes makes the runner reconstruct them; a
        # different spelling would bind the export to a file that never existed.
        manifest = _manifest([VARIANTS[0]])
        emitted = 'json.dumps(report, sort_keys=True, separators=(",", ":"), default=str)'
        self.assertIn(emitted, emit_inventory_script(manifest))

        report = {"kind": "verification", "ok": True, "values": [1, "two"], "nested": {"b": 1, "a": 2}}
        self.assertEqual(
            (eval(emitted, {"json": json, "report": report}) + "\n").encode("utf-8"),
            _canonical_report_bytes(report),
        )

    def test_the_export_binds_to_the_saved_bytes_not_a_reserialisation(self) -> None:
        manifest = _manifest([VARIANTS[0]])
        fake = _FakeFusion(manifest)
        captured: dict[str, str] = {}
        saved: dict[str, bytes] = {}

        def executor(step):
            report = fake(step)
            if step.step_id == "export":
                captured["script"] = step.script or ""
            # The file on disk, whitespace and all — not a re-serialisation.
            raw = (json.dumps(report, indent=4, sort_keys=True) + "\n\n").encode("utf-8")
            if step.step_id == "verify":
                saved["bytes"] = raw
            return report, raw

        record = run_variant_matrix(
            manifest, MatrixConfig(export_dir="/exports"), executor, clock=fake.clock
        )
        self.assertTrue(record["ok"], record["failures"])
        self.assertIn(hashlib.sha256(saved["bytes"]).hexdigest(), captured["script"])


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
            if parameter["name"] in ("des_corner_radius", "fab_wall_thickness")
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

    def test_a_mixed_matrix_restores_the_configuration_before_the_parameters(self) -> None:
        # Activating a row can drive parameter values, so the parameter sync has
        # to be the last write before the read-back.
        manifest = _manifest(
            [
                VARIANTS[0],
                {"id": "config_a", "description": "A.", "configuration": "Config A"},
            ]
        )
        order = [step.step_id for step in build_matrix_plan(manifest, MatrixConfig())]
        self.assertLess(
            order.index(RESTORE_CONFIGURATION_STEP), order.index(RESTORE_PARAMETERS_STEP)
        )

        fake = _FakeFusion(manifest)
        record = _run(manifest, fake)
        self.assertTrue(record["ok"], record["failures"])
        self.assertEqual(
            [RESTORE_CONFIGURATION_STEP, RESTORE_PARAMETERS_STEP, VERIFY_RESTORE_STEP],
            [step["step_id"] for step in record["restore"]["steps"]],
        )

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

    def test_an_export_format_the_emitter_rejects_is_refused_at_plan_time(self) -> None:
        # Not mid-run, with the document already on variant 1's expressions.
        with self.assertRaises(ValueError) as context:
            MatrixConfig(export_dir="/exports", formats=("3mf",))
        self.assertIn("STEP export is required", str(context.exception))
        for formats in (("3mf", "3mf"), ("obj",), ()):
            with self.subTest(formats=formats):
                with self.assertRaises(ValueError):
                    MatrixConfig(export_dir="/exports", formats=formats)
        # Without an export there is nothing to constrain.
        MatrixConfig(formats=("3mf",))

    def test_the_variant_cap_holds_even_when_validation_was_skipped(self) -> None:
        # Manifest.from_data(validate=False) reaches the planner without ever
        # having seen the cap, and the planner is what talks to a live session.
        data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        data["variants"] = [
            {"id": f"v{index}", "description": "One.", "parameters": {"des_corner_radius": f"{index + 1} mm"}}
            for index in range(MAXIMUM_VARIANTS + 1)
        ]
        unvalidated = Manifest.from_data(data, validate=False)
        with self.assertRaises(ValueError) as context:
            build_matrix_plan(unvalidated, MatrixConfig())
        self.assertIn(f"at most {MAXIMUM_VARIANTS} variants", str(context.exception))
        # The planner's own precondition, refused up front. Without it the cap
        # still held — but only later, as a validation failure of a *derived*
        # manifest, reported against a manifest the author never wrote.
        self.assertNotIsInstance(context.exception, ManifestValidationError)

        data["variants"] = data["variants"][:-1]
        build_matrix_plan(Manifest.from_data(data, validate=False), MatrixConfig())

    def test_a_padded_export_dir_does_not_leak_into_the_variant_paths(self) -> None:
        manifest = _manifest([VARIANTS[0]])
        config = MatrixConfig(export_dir="  /exports  ")
        self.assertEqual("/exports", config.export_dir)

        fake = _FakeFusion(manifest)
        captured: dict[str, str] = {}

        def executor(step):
            if step.step_id == "export":
                captured["script"] = step.script or ""
            return fake(step)

        record = run_variant_matrix(manifest, config, executor, clock=fake.clock)
        self.assertTrue(record["ok"], record["failures"])
        self.assertIn('"/exports/small"', captured["script"])
        self.assertNotIn("/exports /small", captured["script"])

    def test_variant_ids_differing_only_in_case_are_refused(self) -> None:
        # The report directory and export root live on a case-insensitive
        # filesystem, where these two read each other's evidence.
        manifest = _manifest(
            [
                {"id": "small", "description": "One.", "parameters": {"des_corner_radius": "3 mm"}},
                {"id": "Small", "description": "Two.", "parameters": {"des_corner_radius": "3 mm"}},
            ]
        )
        with self.assertRaises(ValueError) as context:
            build_matrix_plan(manifest, MatrixConfig(export_dir="/exports"))
        self.assertIn("collide", str(context.exception))

    def test_planning_a_manifest_without_variants_is_refused(self) -> None:
        data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        with self.assertRaises(ValueError) as context:
            build_matrix_plan(Manifest.from_data(data), MatrixConfig())
        self.assertIn("declares no variants", str(context.exception))

    def test_matrix_config_rejects_an_unknown_policy_and_a_useless_threshold(self) -> None:
        for kwargs in (
            {"on_failure": "carry-on"},
            {"on_failure": {"stop": True}},
            {"slow_step_seconds": 0},
            {"slow_step_seconds": float("nan")},
            {"slow_step_seconds": True},
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
