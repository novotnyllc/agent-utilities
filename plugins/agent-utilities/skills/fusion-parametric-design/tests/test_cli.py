from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import re
import tempfile
import unittest

import fusion_design.cli as cli_module
from fusion_design.reconstruction_program import PROGRAM_VERSION
from fusion_design.cli import main
from fusion_design.export_handoff import example_verification_report, manufacturing_intent_by_path
from fusion_design.manifest import load_manifest
from fusion_design.scripts import manifest_sha256
from fusion_design.variant_matrix import MatrixConfig
from test_prusaslicer_project import _Fixture, _config_root, process_execution_offenses
from test_prusaslicer_slice import _fake_slicer
from test_variant_matrix import _FakeFusion, seed_reports


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "electronics-enclosure" / "fusion-project.json"
# The parts the example manifest declares printable; the index must name these.
EXAMPLE_BASE = "Product/Base"
EXAMPLE_LID = "Product/Lid"
EXAMPLE_COUPON = "Validation/PD Fit Coupon"


class PlanReconstructionCliTests(unittest.TestCase):
    def _run(self, record, spec):
        import fixtures_fit_record as fx  # noqa: F401  (fixture module lives in tests/)

        with tempfile.TemporaryDirectory() as temporary:
            fit_path = Path(temporary) / "fit-record.json"
            spec_path = Path(temporary) / "program-spec.json"
            fit_path.write_text(json.dumps(record), encoding="utf-8")
            spec_path.write_text(json.dumps(spec), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "plan-reconstruction",
                        str(EXAMPLE),
                        "--fit-record",
                        str(fit_path),
                        "--program-spec",
                        str(spec_path),
                    ]
                )
            return code, json.loads(output.getvalue())

    def test_a_plannable_fit_record_produces_a_bound_program(self) -> None:
        import fixtures_fit_record as fx

        code, program = self._run(fx.box_record(), fx.spec())
        self.assertEqual(0, code)
        self.assertEqual(program["manifest_sha256"], manifest_sha256(load_manifest(str(EXAMPLE))))
        self.assertEqual(program["dump_sha256"], fx.DUMP_SHA256)
        self.assertEqual(program["program_version"], PROGRAM_VERSION)

    def test_a_refusal_prints_its_named_reason_and_alternative_and_exits_two(self) -> None:
        import fixtures_fit_record as fx

        # Two cylinders of identical score at right angles, whose axis directions
        # are measured only to a degree against a two-degree quantization grid.
        # The score tie alone is settled canonically now; what still refuses is a
        # tie the *directions* cannot break reproducibly either.
        loose = dict(fx.CYLINDER_SIGMAS, axis_direction_deg=1.0)
        record = fx.record(
            [
                fx.cylinder(
                    "a", (0.0, 0.0, 1.0), (0.0, 0.0, 4.0), 3.0, 150.0, 8.0, uncertainty=loose
                ),
                fx.cylinder(
                    "b", (1.0, 0.0, 0.0), (4.0, 0.0, 0.0), 3.0, 150.0, 8.0, uncertainty=loose
                ),
                fx.plane("cap", (0.0, 0.0, 1.0), (0.0, 0.0, 0.0), 28.0),
            ]
        )
        code, refusal = self._run(record, fx.spec())
        self.assertEqual(2, code)
        self.assertEqual(refusal["refusal"], "frame-ambiguous")
        self.assertTrue(refusal["alternative"].strip())
        self.assertIn("winner", refusal["detail"])


class CliTests(unittest.TestCase):
    def test_validate_prints_json_for_valid_manifest(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["validate", str(EXAMPLE)])
        self.assertEqual(0, code)
        self.assertIn('"ok": true', output.getvalue())

    def test_validate_serializes_validation_issues(self) -> None:
        data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        data["parameters"][0].pop("source_id")
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as scratch:
            broken = Path(scratch) / "cli_broken.json"
            broken.write_text(json.dumps(data), encoding="utf-8")
            with redirect_stdout(output):
                code = main(["validate", str(broken)])
            self.assertEqual(2, code)
            self.assertIn("critical-parameter-missing-source", output.getvalue())

    def test_validate_refuses_a_manifest_whose_bytes_and_object_disagree(self) -> None:
        # `validate` is the command a human runs to sign a manifest off
        # (SKILL.md). It read the file with a bare json.loads, so a duplicate
        # key that silently flips provisional true->false reported ok: true
        # while the object-based loaders refused the same file.
        text = EXAMPLE.read_text(encoding="utf-8").replace(
            '"provisional": false,\n      "description": "Measured PD trigger board length."',
            '"provisional": true,\n      "provisional": false,'
            '\n      "description": "Measured PD trigger board length."',
            1,
        )
        with tempfile.TemporaryDirectory() as scratch:
            broken = Path(scratch) / "duplicate_key.json"
            broken.write_text(text, encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["validate", str(broken)])
            self.assertEqual(2, code)
            payload = json.loads(output.getvalue())
            self.assertFalse(payload["ok"])
            self.assertEqual(
                ["manifest-duplicate-key"], [issue["code"] for issue in payload["issues"]]
            )

    def test_validate_reports_warnings_without_blocking(self) -> None:
        data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        data.pop("printable_parts")
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "no_printable_parts.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["validate", str(path)])
            self.assertEqual(0, code)
            payload = json.loads(output.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(
                ["printable-parts-not-declared"], [issue["code"] for issue in payload["issues"]]
            )

    def test_validate_rejects_non_object_manifest_root(self) -> None:
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as scratch:
            broken = Path(scratch) / "cli_non_object.json"
            broken.write_text("[]", encoding="utf-8")
            with redirect_stdout(output):
                code = main(["validate", str(broken)])
            self.assertEqual(2, code)
            self.assertIn("manifest-root-invalid", output.getvalue())

    def test_emit_creates_missing_output_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "nested" / "inventory.py"
            code = main(["emit-inventory", str(EXAMPLE), "-o", str(output)])
            self.assertEqual(0, code)
            self.assertTrue(output.is_file())
            compile(output.read_text(encoding="utf-8"), str(output), "exec")

    def test_emit_rejects_manifest_output_alias(self) -> None:
        errors = io.StringIO()
        with redirect_stderr(errors):
            code = main(["emit-inventory", str(EXAMPLE), "-o", str(EXAMPLE)])
        self.assertEqual(2, code)
        self.assertIn("manifest and output must name different files", errors.getvalue())


# A stand-in for the nonce emit-verification mints. A fixture can only use it
# because the same test also passes it to --verification-nonce; nothing here
# derives it from the manifest, which is exactly what a forger cannot do.
NONCE = "0123456789abcdef0123456789abcdef"


class EmitExportCliTests(unittest.TestCase):
    def _write_report(self, directory: Path, mutate=None, keep_sample_marker=False) -> Path:
        report = example_verification_report(load_manifest(EXAMPLE))
        if not keep_sample_marker:
            report.pop("sample", None)
            report.update(
                verification_nonce=NONCE,
                compute_invoked=True,
                failures=[],
                timeline={"unhealthy": []},
                # Layered onto the sample's real geometry, not substituted for it:
                # the export's staleness binding reads total_solid_volume_mm3 here.
                geometry={
                    path: {**summary, "solid_body_count": 1, "has_positive_solid": True}
                    for path, summary in report["geometry"].items()
                },
            )
        if mutate:
            mutate(report)
        path = directory / "verification-report.json"
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        output = io.StringIO()
        errors = io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = main(argv)
        return code, output.getvalue(), errors.getvalue()

    def test_emit_export_binds_verification_report(self) -> None:
        import hashlib

        with tempfile.TemporaryDirectory() as temporary:
            report_path = self._write_report(Path(temporary))
            script_path = Path(temporary) / "export.py"
            code, _, errors = self._run(
                [
                    "emit-export",
                    str(EXAMPLE),
                    "--verification-report",
                    str(report_path),
                    "--verification-nonce",
                    NONCE,
                    "--export-dir",
                    "/exports/on/fusion/host",
                    "-o",
                    str(script_path),
                ]
            )
            self.assertEqual(0, code, errors)
            source = script_path.read_text(encoding="utf-8")
            compile(source, str(script_path), "exec")
            self.assertIn(hashlib.sha256(report_path.read_bytes()).hexdigest(), source)
            self.assertIn('"step"', source)
            self.assertIn('"3mf"', source)

    def test_emit_export_rejects_mismatched_manifest_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report_path = self._write_report(
                Path(temporary), mutate=lambda report: report.update(manifest_sha256="0" * 64)
            )
            code, _, errors = self._run(
                ["emit-export", str(EXAMPLE), "--verification-report", str(report_path), "--verification-nonce", NONCE, "--export-dir", "/exports"]
            )
            self.assertEqual(2, code)
            self.assertIn("does not match manifest", errors)

    def test_emit_export_rejects_failed_or_wrong_kind_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            failed = self._write_report(Path(temporary), mutate=lambda report: report.update(ok=False))
            code, _, errors = self._run(
                ["emit-export", str(EXAMPLE), "--verification-report", str(failed), "--verification-nonce", NONCE, "--export-dir", "/exports"]
            )
            self.assertEqual(2, code)
            self.assertIn("ok: true", errors)

            wrong_kind = self._write_report(Path(temporary), mutate=lambda report: report.update(kind="inventory"))
            code, _, errors = self._run(
                ["emit-export", str(EXAMPLE), "--verification-report", str(wrong_kind), "--verification-nonce", NONCE, "--export-dir", "/exports"]
            )
            self.assertEqual(2, code)
            self.assertIn("expected 'verification'", errors)

    def test_emit_export_rejects_report_missing_part_bounds(self) -> None:
        def drop_bounds(report):
            report["brep_bounding_boxes_mm"].pop(next(iter(report["brep_bounding_boxes_mm"])))

        with tempfile.TemporaryDirectory() as temporary:
            report_path = self._write_report(Path(temporary), mutate=drop_bounds)
            code, _, errors = self._run(
                ["emit-export", str(EXAMPLE), "--verification-report", str(report_path), "--verification-nonce", NONCE, "--export-dir", "/exports"]
            )
            self.assertEqual(2, code)
            self.assertIn("no usable B-Rep bounds", errors)

    def test_emit_export_rejects_path_aliasing_and_duplicate_formats(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report_path = self._write_report(Path(temporary))
            code, _, errors = self._run(
                ["emit-export", str(EXAMPLE), "--verification-report", str(EXAMPLE), "--verification-nonce", NONCE, "--export-dir", "/exports"]
            )
            self.assertEqual(2, code)
            self.assertIn("must name different files", errors)

            code, _, errors = self._run(
                [
                    "emit-export",
                    str(EXAMPLE),
                    "--verification-report",
                    str(report_path),
                    "--verification-nonce",
                    NONCE,
                    "--export-dir",
                    "/exports",
                    "--format",
                    "step",
                    "--format",
                    "step",
                ]
            )
            self.assertEqual(2, code)
            self.assertIn("must not repeat", errors)

    def test_emit_export_rejects_sample_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report_path = self._write_report(Path(temporary), keep_sample_marker=True)
            code, _, errors = self._run(
                ["emit-export", str(EXAMPLE), "--verification-report", str(report_path), "--verification-nonce", NONCE, "--export-dir", "/exports"]
            )
            self.assertEqual(2, code)
            self.assertIn("sample verification report", errors)

    def test_emit_export_rejects_a_report_forged_from_this_packages_public_api(self) -> None:
        # The whole bypass, in six lines: example_verification_report synthesizes
        # a report from the manifest alone, and every consistency key is a
        # constant a forger already knows. Only the nonce is not derivable.
        with tempfile.TemporaryDirectory() as temporary:
            forged = example_verification_report(load_manifest(EXAMPLE))
            forged.pop("sample")
            forged.update(
                compute_invoked=True,
                failures=[],
                timeline={"unhealthy": []},
                geometry={EXAMPLE_BASE: {"has_positive_solid": True}},
            )
            path = Path(temporary) / "forged.json"
            path.write_text(json.dumps(forged), encoding="utf-8")
            code, _, errors = self._run(
                [
                    "emit-export",
                    str(EXAMPLE),
                    "--verification-report",
                    str(path),
                    "--verification-nonce",
                    NONCE,
                    "--export-dir",
                    "/exports",
                ]
            )
            self.assertEqual(2, code)
            self.assertIn("nonce does not match", errors)

    def test_emit_export_rejects_a_report_bound_to_a_different_nonce(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report_path = self._write_report(Path(temporary))
            code, _, errors = self._run(
                [
                    "emit-export",
                    str(EXAMPLE),
                    "--verification-report",
                    str(report_path),
                    "--verification-nonce",
                    "f" * 32,
                    "--export-dir",
                    "/exports",
                ]
            )
            self.assertEqual(2, code)
            self.assertIn("nonce does not match", errors)

    def test_emit_verification_mints_a_nonce_the_emitted_script_carries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / "verify.py"
            code, _, errors = self._run(["emit-verification", str(EXAMPLE), "-o", str(script)])
            self.assertEqual(0, code, errors)
            nonce = re.search(r"verification nonce: ([0-9a-f]{32})", errors).group(1)
            self.assertIn(nonce, script.read_text(encoding="utf-8"))

            # Two emissions never share a nonce, so an old one cannot be replayed.
            second = Path(temporary) / "verify2.py"
            _, _, more = self._run(["emit-verification", str(EXAMPLE), "-o", str(second)])
            self.assertNotEqual(nonce, re.search(r"verification nonce: ([0-9a-f]{32})", more).group(1))

    def test_emit_export_rejects_a_sample_report_with_the_marker_stripped(self) -> None:
        # The improvisation the guard actually has to survive: delete "sample"
        # and the fabricated acceptance-box report becomes an export binding.
        with tempfile.TemporaryDirectory() as temporary:
            report = example_verification_report(load_manifest(EXAMPLE))
            report.pop("sample")
            path = Path(temporary) / "verification-report.json"
            path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            code, _, errors = self._run(
                ["emit-export", str(EXAMPLE), "--verification-report", str(path), "--verification-nonce", NONCE, "--export-dir", "/exports"]
            )
            self.assertEqual(2, code)
            # Refused on the nonce, which no manifest-derived report can carry.
            self.assertIn("nonce does not match", errors)

    def test_emit_export_rejects_a_report_whose_failures_are_not_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report_path = self._write_report(
                Path(temporary), mutate=lambda report: report.update(failures=["clearance"])
            )
            code, _, errors = self._run(
                ["emit-export", str(EXAMPLE), "--verification-report", str(report_path), "--verification-nonce", NONCE, "--export-dir", "/exports"]
            )
            self.assertEqual(2, code)
            self.assertIn("not internally consistent", errors)

    def test_emit_export_rejects_unknown_format(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report_path = self._write_report(Path(temporary))
            with self.assertRaises(SystemExit):
                with redirect_stderr(io.StringIO()):
                    main(
                        [
                            "emit-export",
                            str(EXAMPLE),
                            "--verification-report",
                            str(report_path),
                            "--verification-nonce",
                            NONCE,
                            "--export-dir",
                            "/exports",
                            "--format",
                            "obj",
                        ]
                    )


class PrusaSlicerProjectCliTests(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        output = io.StringIO()
        errors = io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = main(argv)
        return code, output.getvalue(), errors.getvalue()

    def _handoff(self, root: Path, manifest=None, mutate_intent=None) -> tuple[Path, Path]:
        """A handoff whose intent is the example manifest's own, as a real export's is.

        ``mutate_intent`` forges the index's copy, so the manifest/index divergence
        gate can be exercised end to end.
        """
        declared = manufacturing_intent_by_path(load_manifest(EXAMPLE))
        fixture = _Fixture(root)
        # Every part the manifest declares printable, not a convenient subset: an
        # index missing one is refused, which is the point of the coverage check.
        for part_path, with_step in (
            (EXAMPLE_BASE, True),
            (EXAMPLE_LID, False),
            (EXAMPLE_COUPON, False),
        ):
            intent = json.loads(json.dumps(declared[part_path]))
            if mutate_intent is not None:
                mutate_intent(part_path, intent)
            fixture.add_part(part_path, intent=intent, with_step=with_step)
        index = fixture.write_index(manifest=manifest if manifest is not None else load_manifest(EXAMPLE))
        return index, _config_root(root)

    def _argv(self, index: Path, output: Path, config: Path, *extra: str) -> list[str]:
        return [
            "prusaslicer-project",
            str(EXAMPLE),
            "--export-index",
            str(index),
            "--output",
            str(output),
            "--config-root",
            str(config),
            *extra,
        ]

    def test_project_is_written_and_hashes_are_reported(self) -> None:
        import hashlib

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index, config = self._handoff(root)
            output = root / "project.3mf"
            code, stdout, errors = self._run(self._argv(index, output, config))
            self.assertEqual(0, code, errors)
            payload = json.loads(stdout)

            self.assertTrue(output.is_file())
            self.assertEqual(str(output), payload["project_path"])
            self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(), payload["project_sha256"])
            self.assertEqual(output.stat().st_size, payload["project_byte_size"])
            self.assertEqual(hashlib.sha256(index.read_bytes()).hexdigest(), payload["export_index_sha256"])
            # Both parts declare print_as "separate", so each gets its own plate.
            self.assertEqual(
                [
                    {"plate": 1, "part_paths": [EXAMPLE_BASE]},
                    {"plate": 2, "part_paths": [EXAMPLE_LID]},
                    {"plate": 3, "part_paths": [EXAMPLE_COUPON]},
                ],
                payload["plates"],
            )
            lid = next(obj for obj in payload["objects"] if obj["part_path"] == EXAMPLE_LID)
            self.assertEqual({"contact_face": "+Z", "axis": "X", "degrees": 180}, lid["applied_rotation"])
            self.assertEqual(1, lid["instances_count"])
            self.assertEqual(2, lid["plate"])
            self.assertEqual("1", lid["overrides"]["support_material_buildplate_only"])
            self.assertEqual(
                {"printer", "filament", "print"}, set(payload["presets"]), payload["presets"]
            )
            # The chain is carried forward, not re-derived at each hop.
            index_data = json.loads(index.read_text(encoding="utf-8"))
            self.assertEqual(
                index_data["verification_report_sha256"], payload["verification_report_sha256"]
            )
            self.assertEqual(index_data["export_run_id"], payload["export_run_id"])

    def test_index_intent_diverging_from_the_manifest_exits_two(self) -> None:
        """The manifest is the authority: a forged index must not print its settings."""
        forgeries = {
            "support_policy": lambda intent: intent.update(support_policy="everywhere"),
            "min_perimeters": lambda intent: intent["strength"].update(min_perimeters=1),
            "infill": lambda intent: intent["strength"]["infill_percent"].update(target=5),
            "contact_face": lambda intent: intent["orientation"].update(contact_face="+Z"),
        }
        for name, forge in forgeries.items():
            with self.subTest(forgery=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                index, config = self._handoff(
                    root,
                    mutate_intent=lambda path, intent: forge(intent) if path == EXAMPLE_BASE else None,
                )
                output = root / "p.3mf"
                code, stdout, errors = self._run(self._argv(index, output, config))
                self.assertEqual(2, code, stdout)
                self.assertIn("disagrees with the manifest", errors)
                self.assertFalse(output.exists())

    def test_index_omitting_a_declared_part_exits_two(self) -> None:
        """A subset index must not silently build a project missing parts.

        The intent check runs index-against-manifest; without the reverse check
        this exits 0 with a matching manifest_sha256 and a clean provenance block.
        """
        for drop_step_too in (True, False):
            with self.subTest(drop_step_too=drop_step_too), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                index, config = self._handoff(root)
                payload = json.loads(index.read_text(encoding="utf-8"))
                payload["artifacts"] = [
                    artifact
                    for artifact in payload["artifacts"]
                    if artifact["part_path"] != EXAMPLE_COUPON
                    # Dropping only the 3MF is the same omission: _collect_parts
                    # counts geometry, so a lingering STEP hides nothing.
                    or (not drop_step_too and artifact["format"] != "3mf")
                ]
                index.write_text(json.dumps(payload), encoding="utf-8")
                output = root / "p.3mf"
                code, stdout, errors = self._run(self._argv(index, output, config))
                self.assertEqual(2, code, stdout)
                self.assertIn("carries no 3MF artifact for printable parts", errors)
                self.assertIn(EXAMPLE_COUPON, errors)
                self.assertFalse(output.exists())

    def test_an_omitted_or_extra_intent_key_is_a_divergence(self) -> None:
        """Omission diverges, not just contradiction -- the union is load-bearing.

        Comparing only the keys both sides carry lets an index *drop* quantity and
        inherit _collect_parts' default of 1, contradicting a manifest that says 2.
        """
        def drop_quantity(intent):
            intent.pop("quantity")

        def add_unknown_key(intent):
            intent["printer"] = "Some Printer"

        for name, forge, expected in (
            ("omitted", drop_quantity, "quantity"),
            ("extra", add_unknown_key, "printer"),
        ):
            with self.subTest(kind=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                index, config = self._handoff(
                    root,
                    mutate_intent=lambda path, intent: forge(intent) if path == EXAMPLE_BASE else None,
                )
                output = root / "p.3mf"
                code, stdout, errors = self._run(self._argv(index, output, config))
                self.assertEqual(2, code, stdout)
                self.assertIn("disagrees with the manifest", errors)
                self.assertIn(expected, errors)
                self.assertFalse(output.exists())

    def test_index_without_the_verification_chain_exits_two(self) -> None:
        for missing, pattern in (
            ("verification_report_sha256", "verification_report_sha256"),
            ("export_run_id", "export_run_id"),
        ):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                index, config = self._handoff(root)
                payload = json.loads(index.read_text(encoding="utf-8"))
                payload.pop(missing)
                index.write_text(json.dumps(payload), encoding="utf-8")
                output = root / "p.3mf"
                code, _, errors = self._run(self._argv(index, output, config))
                self.assertEqual(2, code)
                self.assertIn(pattern, errors)
                self.assertFalse(output.exists())

    def test_default_run_attempts_no_slice_and_carries_no_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index, config = self._handoff(root)
            code, stdout, errors = self._run(self._argv(index, root / "p.3mf", config))
            self.assertEqual(0, code, errors)
            slice_block = json.loads(stdout)["slice"]
            self.assertEqual({"supported", "attempted", "reason", "detail"}, set(slice_block))
            self.assertIs(True, slice_block["supported"])
            self.assertIs(False, slice_block["attempted"])
            self.assertIn("--slice", slice_block["reason"])
            self.assertIn("none may be inferred, estimated, or interpolated", slice_block["detail"])
            for banned in ("print_time", "estimated_time", "filament_used", "gcode_statistics", "grams"):
                self.assertNotIn(banned, stdout, banned)
            self.assertFalse((root / "p.gcode").exists())

    def test_slice_flag_reports_real_statistics_from_the_produced_gcode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index, config = self._handoff(root)
            code, stdout, errors = self._run(
                self._argv(
                    index, root / "p.3mf", config, "--slice", "--slicer-executable", str(_fake_slicer(root))
                )
            )
            self.assertEqual(0, code, errors)
            payload = json.loads(stdout)
            slice_block = payload["slice"]
            self.assertTrue(slice_block["ok"], slice_block)
            self.assertIs(True, slice_block["attempted"])
            self.assertEqual(payload["project_sha256"], slice_block["project_sha256"])
            self.assertEqual("18m 4s", slice_block["statistics"]["estimated_printing_time_normal"])
            self.assertEqual(
                hashlib.sha256((root / "p.gcode").read_bytes()).hexdigest(), slice_block["gcode_sha256"]
            )

    def test_failed_slice_exits_two_and_keeps_its_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index, config = self._handoff(root)
            code, stdout, _ = self._run(
                self._argv(
                    index,
                    root / "p.3mf",
                    config,
                    "--slice",
                    "--slicer-executable",
                    str(_fake_slicer(root, exit_code=139)),
                )
            )
            self.assertEqual(2, code)
            slice_block = json.loads(stdout)["slice"]
            self.assertFalse(slice_block["ok"])
            self.assertEqual(139, slice_block["exit_code"])
            self.assertIn("SIGSEGV", slice_block["failure"])
            self.assertNotIn("statistics", slice_block)

    def test_unknown_preset_exits_two_and_names_what_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index, config = self._handoff(root)
            output = root / "p.3mf"
            code, _, errors = self._run(
                self._argv(index, output, config, "--printer", "Bambu X1C")
            )
            self.assertEqual(2, code)
            self.assertIn("'Bambu X1C' is not installed", errors)
            self.assertIn("Original Prusa XL - 5T", errors)
            self.assertFalse(output.exists())

    def test_missing_or_unreadable_index_exits_two(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, config = self._handoff(root)
            code, _, errors = self._run(self._argv(root / "absent.json", root / "a.3mf", config))
            self.assertEqual(2, code)
            self.assertIn("is not a file", errors)

            unreadable = root / "broken.json"
            unreadable.write_text("{not json", encoding="utf-8")
            code, _, errors = self._run(self._argv(unreadable, root / "b.3mf", config))
            self.assertEqual(2, code)
            self.assertIn("not readable JSON", errors)

    def test_output_aliasing_manifest_or_index_exits_two(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index, config = self._handoff(root)
            code, _, errors = self._run(self._argv(index, EXAMPLE, config))
            self.assertEqual(2, code)
            self.assertIn("manifest and output must name different files", errors)

            code, _, errors = self._run(self._argv(index, index, config))
            self.assertEqual(2, code)
            self.assertIn("export-index and output must name different files", errors)

    def test_existing_output_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index, config = self._handoff(root)
            output = root / "p.3mf"
            output.write_bytes(b"prior")
            code, _, errors = self._run(self._argv(index, output, config))
            self.assertEqual(2, code)
            self.assertIn("Refusing to overwrite", errors)
            self.assertEqual(b"prior", output.read_bytes())

    def test_index_built_for_another_manifest_exits_two(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            other = load_manifest(EXAMPLE)
            other.data["project"]["name"] = "A Different Design"
            index, config = self._handoff(root, manifest=other)
            output = root / "p.3mf"
            code, stdout, errors = self._run(self._argv(index, output, config))
            self.assertEqual(2, code)
            self.assertIn("does not match manifest", errors)
            self.assertEqual("", stdout)
            self.assertFalse(output.exists())

    def test_index_naming_an_undeclared_part_exits_two(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = load_manifest(EXAMPLE)
            fixture = _Fixture(root)
            fixture.add_part("Product/PROD__STOWAWAY")
            index = fixture.write_index(manifest=manifest)
            output = root / "p.3mf"
            code, _, errors = self._run(self._argv(index, output, _config_root(root)))
            self.assertEqual(2, code)
            self.assertIn("does not declare as printable: Product/PROD__STOWAWAY", errors)
            self.assertFalse(output.exists())

    def test_malformed_source_mesh_exits_two_rather_than_crashing(self) -> None:
        from test_prusaslicer_project import _source_3mf_bytes

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            fixture.add_part(EXAMPLE_BASE, payload=_source_3mf_bytes(triangle_xml=['<triangle v1="0" v2="1"/>']))
            index = fixture.write_index(manifest=load_manifest(EXAMPLE))
            code, _, errors = self._run(self._argv(index, root / "p.3mf", _config_root(root)))
            self.assertEqual(2, code)
            self.assertIn("no v3 vertex index", errors)

    def test_cli_module_contains_no_process_execution_api(self) -> None:
        source = Path(cli_module.__file__).read_text(encoding="utf-8")
        self.assertEqual([], process_execution_offenses(source))


class DiffReportsCliTests(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        output = io.StringIO()
        errors = io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = main(argv)
        return code, output.getvalue(), errors.getvalue()

    def _report(self, directory: Path, name: str, **overrides) -> Path:
        report = {
            "kind": "inventory",
            "ok": True,
            "project": "wearable-controller-pod",
            "manifest_sha256": "a" * 64,
            "component_paths": [EXAMPLE_BASE],
        }
        report.update(overrides)
        path = directory / name
        path.write_text(json.dumps(report), encoding="utf-8")
        return path

    def test_diff_reports_refuses_mismatched_kinds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before = self._report(root, "before.json")
            after = self._report(root, "after.json", kind="verification", component_paths=[])
            code, output, errors = self._run(["diff-reports", str(before), str(after)])
            self.assertEqual(2, code)
            self.assertIn("'inventory'", errors)
            self.assertIn("'verification'", errors)
            # The fabricated removal must never be printed.
            self.assertNotIn("components_removed", output)

    def test_diff_reports_refuses_a_different_project_or_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before = self._report(root, "before.json")

            other_project = self._report(root, "other-project.json", project="something-else")
            code, _, errors = self._run(["diff-reports", str(before), str(other_project)])
            self.assertEqual(2, code)
            self.assertIn("different projects", errors)

            other_manifest = self._report(root, "other-manifest.json", manifest_sha256="b" * 64)
            code, _, errors = self._run(["diff-reports", str(before), str(other_manifest)])
            self.assertEqual(2, code)
            self.assertIn("--allow-manifest-change", errors)

            code, output, errors = self._run(
                ["diff-reports", str(before), str(other_manifest), "--allow-manifest-change"]
            )
            self.assertEqual(0, code, errors)
            self.assertIn("components_removed", output)

    def test_diff_reports_refuses_reports_missing_project_or_manifest_hash(self) -> None:
        # Absence must fail like a mismatch: None == None is not agreement.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for field in ("project", "manifest_sha256"):
                before = self._report(root, f"before-{field}.json")
                after = self._report(root, f"after-{field}.json")
                for path in (before, after):
                    data = json.loads(path.read_text(encoding="utf-8"))
                    data.pop(field)
                    path.write_text(json.dumps(data), encoding="utf-8")
                code, output, errors = self._run(["diff-reports", str(before), str(after)])
                self.assertEqual(2, code, field)
                self.assertIn(f"no usable {field!r}", errors)
                self.assertEqual("", output)

    def test_diff_reports_exits_two_when_the_diff_finds_a_regression(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before = self._report(root, "before.json", kind="verification", failures=[])
            after = self._report(
                root, "after.json", kind="verification", ok=False, failures=["clearance"]
            )
            code, output, _ = self._run(["diff-reports", str(before), str(after)])
            self.assertEqual(2, code)
            self.assertIn('"clearance"', output)

            code, _, _ = self._run(["diff-reports", str(before), str(before)])
            self.assertEqual(0, code)

    def test_diff_reports_refuses_an_undiffable_kind(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before = self._report(root, "before.json", kind="export-handoff")
            after = self._report(root, "after.json", kind="export-handoff")
            code, _, errors = self._run(["diff-reports", str(before), str(after)])
            self.assertEqual(2, code)
            self.assertIn("cannot be diffed", errors)


class PlanVariantsCliTests(unittest.TestCase):
    VARIANTS = [
        {"id": "small", "description": "Compact enclosure.", "parameters": {"des_corner_radius": "3 mm"}},
        {"id": "large", "description": "Large enclosure.", "parameters": {"des_corner_radius": "8 mm"}},
    ]

    def _manifest_path(self, directory: Path) -> Path:
        data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        data["variants"] = self.VARIANTS
        path = directory / "fusion-project.json"
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        output = io.StringIO()
        errors = io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = main(argv)
        return code, output.getvalue(), errors.getvalue()

    def test_plan_is_emitted_in_capture_variant_restore_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = self._manifest_path(Path(temporary))
            code, output, errors = self._run(["plan-variants", str(manifest)])
        self.assertEqual(0, code, errors)
        payload = json.loads(output)
        steps = [(step["step_id"], step["variant_id"]) for step in payload["steps"]]
        self.assertEqual(("capture-initial-state", ""), steps[0])
        self.assertEqual(("verify-restore", ""), steps[-1])
        self.assertEqual(
            [("apply", "small"), ("inventory", "small"), ("verify", "small")], steps[1:4]
        )
        for step in payload["steps"]:
            if step["script"]:
                compile(step["script"], step["report_name"], "exec")

    def test_export_gives_each_variant_its_own_directory_and_a_deferred_script(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = self._manifest_path(Path(temporary))
            code, output, errors = self._run(
                ["plan-variants", str(manifest), "--export-dir", "/exports", "--format", "step"]
            )
        self.assertEqual(0, code, errors)
        payload = json.loads(output)
        self.assertTrue(payload["export_requested"])
        exports = [step for step in payload["steps"] if step["step_id"] == "export"]
        self.assertEqual(["small", "large"], [step["variant_id"] for step in exports])
        for step in exports:
            self.assertIsNone(step["script"])
            self.assertIn("verification report", step["deferred_reason"])

    def test_a_manifest_without_variants_exits_two_with_a_clear_message(self) -> None:
        code, _, errors = self._run(["plan-variants", str(EXAMPLE)])
        self.assertEqual(2, code)
        self.assertIn("declares no variants", errors)

    def test_path_aliasing_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = self._manifest_path(Path(temporary))
            code, _, errors = self._run(["plan-variants", str(manifest), "-o", str(manifest)])
        self.assertEqual(2, code)
        self.assertIn("manifest and output must name different files", errors)

    def test_folding_saved_reports_reports_the_next_step_without_failing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = self._manifest_path(Path(temporary))
            reports = Path(temporary) / "reports"
            reports.mkdir()
            code, output, errors = self._run(
                ["plan-variants", str(manifest), "--reports-dir", str(reports)]
            )
        self.assertEqual(0, code, errors)
        record = json.loads(output)
        self.assertFalse(record["complete"])
        self.assertEqual([], record["failures"])
        self.assertEqual("capture-initial-state", record["next_step"]["step_id"])

    def test_an_output_inside_the_reports_directory_is_refused(self) -> None:
        # Writing the record over a saved report either destroys that evidence
        # or feeds the record back to the next fold as evidence.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self._manifest_path(root)
            reports = root / "reports"
            reports.mkdir()
            digest = manifest_sha256(load_manifest(manifest))
            for output in (
                reports / f"capture-initial-state__{digest[:8]}.json",
                reports / "nested" / "record.json",
                # Containment has to be tested after resolution, not before.
                root / "elsewhere" / ".." / "reports" / "record.json",
            ):
                with self.subTest(output=str(output)):
                    code, _, errors = self._run(
                        ["plan-variants", str(manifest), "--reports-dir", str(reports), "-o", str(output)]
                    )
                    self.assertEqual(2, code)
                    self.assertIn("must not be written inside reports-dir", errors)
                    self.assertFalse(output.exists())

            outside = root / "record.json"
            code, _, errors = self._run(
                ["plan-variants", str(manifest), "--reports-dir", str(reports), "-o", str(outside)]
            )
            self.assertEqual(0, code, errors)
            self.assertTrue(outside.exists())

    def test_a_complete_successful_fold_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = self._manifest_path(Path(temporary))
            reports = Path(temporary) / "reports"
            reports.mkdir()
            seed_reports(load_manifest(manifest), reports)
            code, output, errors = self._run(
                ["plan-variants", str(manifest), "--reports-dir", str(reports)]
            )
        self.assertEqual(0, code, errors)
        record = json.loads(output)
        self.assertTrue(record["complete"])
        self.assertTrue(record["ok"], record["failures"])
        self.assertTrue(record["restore"]["verified"])

    def test_a_failed_variant_still_waiting_on_the_rest_exits_two(self) -> None:
        # The normal shape of every intermediate fold in the acceptance loop: a
        # variant has already failed and later steps have no report yet.
        with tempfile.TemporaryDirectory() as temporary:
            manifest = self._manifest_path(Path(temporary))
            reports = Path(temporary) / "reports"
            reports.mkdir()
            loaded = load_manifest(manifest)
            config = MatrixConfig(on_failure="continue")
            seed_reports(
                loaded, reports, _FakeFusion(loaded, fail_steps={("small", "verify")}), config
            )
            for pending in reports.glob("large__*"):
                pending.unlink()
            code, output, errors = self._run(
                [
                    "plan-variants",
                    str(manifest),
                    "--reports-dir",
                    str(reports),
                    "--on-failure",
                    "continue",
                ]
            )
        self.assertEqual(2, code, errors)
        record = json.loads(output)
        self.assertFalse(record["complete"])
        self.assertIn("variant-failed", record["failures"])

    def test_an_export_format_the_emitter_rejects_exits_two_at_plan_time(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = self._manifest_path(Path(temporary))
            code, _, errors = self._run(
                ["plan-variants", str(manifest), "--export-dir", "/exports", "--format", "3mf"]
            )
        self.assertEqual(2, code)
        self.assertIn("STEP export is required", errors)

    def test_a_failed_step_report_exits_two(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = self._manifest_path(Path(temporary))
            reports = Path(temporary) / "reports"
            reports.mkdir()
            digest = manifest_sha256(load_manifest(manifest))
            (reports / f"capture-initial-state__{digest[:8]}.json").write_text(
                json.dumps({"kind": "inventory", "manifest_sha256": digest, "ok": False}), encoding="utf-8"
            )
            code, output, _ = self._run(["plan-variants", str(manifest), "--reports-dir", str(reports)])
        self.assertEqual(2, code)
        record = json.loads(output)
        self.assertIn("initial-state-capture", record["failures"])
        self.assertFalse(record["ok"])


class MeshCliTests(unittest.TestCase):
    """The mesh commands anchor on the recorded digest and the recorded path."""

    def setUp(self) -> None:
        from fusion_design.mesh_source import file_sha256

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "sources").mkdir()
        self.stl = self.root / "sources" / "bracket.stl"
        self.stl.write_bytes(b"solid bracket\nendsolid bracket\n")
        data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        data["mesh_sources"] = [
            {
                "id": "scan_bracket",
                "path": "sources/bracket.stl",
                "sha256": file_sha256(self.stl),
                "units": "mm",
                "unit_source": "declared",
                "provenance": "designed_export",
                "alignment_transform": [
                    1.0, 0.0, 0.0, 0.0,
                    0.0, 1.0, 0.0, 0.0,
                    0.0, 0.0, 1.0, 0.0,
                    0.0, 0.0, 0.0, 1.0,
                ],
            }
        ]
        self.manifest = self.root / "fusion-project.json"
        self.manifest.write_text(json.dumps(data), encoding="utf-8")

    def _classification(self, name: str, **request) -> Path:
        from fusion_design.mesh_reconstruction import classify

        payload = {"edit_kind": "dimensional", "watertight": True, "facet_count": 800}
        payload.update(request)
        source = load_manifest(self.manifest).mesh_sources[0]
        path = self.root / name
        path.write_text(json.dumps(classify(payload, source).to_dict()), encoding="utf-8")
        return path

    def _run(self, argv):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = main(argv)
        return code, output.getvalue(), errors.getvalue()

    def test_emit_mesh_capture_refuses_a_source_that_changed_since_capture(self) -> None:
        script = self.root / "capture.py"
        code, _, errors = self._run(["emit-mesh-capture", str(self.manifest), "-o", str(script)])
        self.assertEqual(0, code, errors)
        self.assertIn("mesh-capture", script.read_text(encoding="utf-8"))

        self.stl.write_bytes(b"solid bracket\nfacet\nendsolid bracket\n")
        code, _, errors = self._run(["emit-mesh-capture", str(self.manifest), "-o", str(self.root / "b.py")])
        self.assertEqual(2, code)
        self.assertIn("mesh-source-hash-mismatch", errors)

    def _extract_spec(self, **overrides) -> Path:
        payload = {
            "component_path": "",
            "body_name": "bracket_scan",
            "dump_dir": str(self.root / "dumps"),
            "max_triangles": 200000,
            "max_triangles_rationale": (
                "Beyond this density the extra triangles are noise samples rather than recoverable "
                "design, and fit-driven splitting is superlinear in the base count."
            ),
            "fallback_max_bytes": 4000000,
            "fallback_max_bytes_rationale": (
                "The stdout report is the transport of last resort; beyond this the report becomes "
                "the failure, so refuse rather than truncate."
            ),
        }
        payload.update(overrides)
        path = self.root / "extract.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_emit_capability_probe_runs_with_and_without_a_bound_body(self) -> None:
        script = self.root / "probe.py"
        code, _, errors = self._run(["emit-capability-probe", str(self.manifest), "-o", str(script)])
        self.assertEqual(0, code, errors)
        source = script.read_text(encoding="utf-8")
        self.assertIn("capability-probe", source)
        self.assertIn('"probe_spec":null', source)

        spec = self.root / "probe.json"
        spec.write_text(
            json.dumps(
                {
                    "component_path": "",
                    "body_name": "bracket_scan",
                    "dump_dir": str(self.root / "dumps"),
                }
            ),
            encoding="utf-8",
        )
        bound = self.root / "probe-bound.py"
        code, _, errors = self._run(
            ["emit-capability-probe", str(self.manifest), "--probe-spec", str(spec), "-o", str(bound)]
        )
        self.assertEqual(0, code, errors)
        self.assertIn("bracket_scan", bound.read_text(encoding="utf-8"))

    def test_emit_capability_probe_rejects_a_spec_without_a_dump_directory(self) -> None:
        spec = self.root / "probe.json"
        spec.write_text(
            json.dumps({"component_path": "", "body_name": "bracket_scan", "dump_dir": ""}),
            encoding="utf-8",
        )
        code, _, errors = self._run(
            ["emit-capability-probe", str(self.manifest), "--probe-spec", str(spec)]
        )
        self.assertEqual(2, code)
        self.assertIn("probe-spec-invalid-dump-dir", errors)

    def test_emit_mesh_extract_requires_a_parametric_rebuild_classification(self) -> None:
        spec = self._extract_spec()
        faceted = self._classification(
            "faceted.json", edit_kind="boolean-mechanical", facet_budget=10000
        )
        code, _, errors = self._run(
            [
                "emit-mesh-extract",
                str(self.manifest),
                "--mesh-source-id",
                "scan_bracket",
                "--classification",
                str(faceted),
                "--extract-spec",
                str(spec),
                "-o",
                str(self.root / "extract.py"),
            ]
        )
        self.assertEqual(2, code)
        self.assertIn("classification-path-forbids-operation", errors)

        script = self.root / "extract.py"
        code, _, errors = self._run(
            [
                "emit-mesh-extract",
                str(self.manifest),
                "--mesh-source-id",
                "scan_bracket",
                "--classification",
                str(self._classification("rebuild.json")),
                "--extract-spec",
                str(spec),
                "-o",
                str(script),
            ]
        )
        self.assertEqual(0, code, errors)
        source = script.read_text(encoding="utf-8")
        self.assertIn("mesh-extract", source)
        self.assertIn("def pack_mesh_dump(", source)

    def test_emit_mesh_extract_rejects_a_budget_without_a_rationale(self) -> None:
        code, _, errors = self._run(
            [
                "emit-mesh-extract",
                str(self.manifest),
                "--mesh-source-id",
                "scan_bracket",
                "--classification",
                str(self._classification("rebuild.json")),
                "--extract-spec",
                str(self._extract_spec(max_triangles_rationale="   ")),
            ]
        )
        self.assertEqual(2, code)
        self.assertIn("extract-spec-invalid-budget-rationale", errors)

    def test_emit_mesh_convert_requires_a_faceted_brep_classification(self) -> None:
        spec = self.root / "convert.json"
        spec.write_text(
            json.dumps(
                {
                    "component_path": "",
                    "body_name": "bracket_scan",
                    "max_faces_per_face_group": 4.0,
                    "rationale": "Three face groups; more than four faces each leaves nothing selectable.",
                }
            ),
            encoding="utf-8",
        )
        rebuild = self._classification("rebuild.json")
        code, _, errors = self._run(
            [
                "emit-mesh-convert",
                str(self.manifest),
                "--mesh-source-id",
                "scan_bracket",
                "--classification",
                str(rebuild),
                "--convert-spec",
                str(spec),
                "-o",
                str(self.root / "convert.py"),
            ]
        )
        self.assertEqual(2, code)
        self.assertIn("classification-path-forbids-operation", errors)

        faceted = self._classification(
            "faceted.json", edit_kind="boolean-mechanical", facet_budget=10000
        )
        script = self.root / "convert.py"
        code, _, errors = self._run(
            [
                "emit-mesh-convert",
                str(self.manifest),
                "--mesh-source-id",
                "scan_bracket",
                "--classification",
                str(faceted),
                "--convert-spec",
                str(spec),
                "-o",
                str(script),
            ]
        )
        self.assertEqual(0, code, errors)
        self.assertIn("mesh-convert", script.read_text(encoding="utf-8"))

    def test_emit_mesh_deviation_binds_to_the_declared_source(self) -> None:
        spec = self.root / "deviation.json"
        spec.write_text(
            json.dumps(
                {
                    "source": {"component_path": "", "body_name": "bracket_scan"},
                    "reconstruction": {"component_path": "", "body_name": "bracket_rebuild"},
                    "thresholds_mm": {
                        "invented_material": 0.05,
                        "omitted_detail": 0.25,
                        "percentile_sample_limit": 20000,
                    },
                    "rationale": "Printed fit is held to 0.05 mm.",
                }
            ),
            encoding="utf-8",
        )
        script = self.root / "deviation.py"
        code, _, errors = self._run(
            [
                "emit-mesh-deviation",
                str(self.manifest),
                "--mesh-source-id",
                "scan_bracket",
                "--classification",
                str(self._classification("rebuild.json")),
                "--deviation-spec",
                str(spec),
                "-o",
                str(script),
            ]
        )
        self.assertEqual(0, code, errors)
        source = script.read_text(encoding="utf-8")
        self.assertIn("BRepBody.pointContainment", source)
        self.assertIn("MeshManager.createMeshCalculator", source)
        # compareWith survives as corroboration and as the reason it cannot be
        # the mechanism, never as the measurement.
        self.assertIn("PolygonMesh.compareWith", source)
        self.assertIn("neither certifies the other", source)

    def test_an_undeclared_source_id_exits_two(self) -> None:
        spec = self.root / "deviation.json"
        spec.write_text(json.dumps({"source": {}, "reconstruction": {}}), encoding="utf-8")
        code, _, errors = self._run(
            [
                "emit-mesh-deviation",
                str(self.manifest),
                "--mesh-source-id",
                "scan_absent",
                "--classification",
                str(self._classification("rebuild.json")),
                "--deviation-spec",
                str(spec),
            ]
        )
        self.assertEqual(2, code)
        self.assertIn("mesh-source-unknown-id", errors)

    def test_a_classification_decided_for_another_source_exits_two(self) -> None:
        # The id is supplied independently of the record, so this comparison is
        # between two values from different places and can actually fail.
        from fusion_design.mesh_reconstruction import classify

        other = dict(load_manifest(self.manifest).mesh_sources[0], id="scan_lid", sha256="b" * 64)
        record = classify(
            {"edit_kind": "dimensional", "watertight": True, "facet_count": 8}, other
        ).to_dict()
        path = self.root / "stray.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        spec = self.root / "deviation.json"
        spec.write_text(json.dumps({"source": {}, "reconstruction": {}}), encoding="utf-8")
        code, _, errors = self._run(
            [
                "emit-mesh-deviation",
                str(self.manifest),
                "--mesh-source-id",
                "scan_bracket",
                "--classification",
                str(path),
                "--deviation-spec",
                str(spec),
            ]
        )
        self.assertEqual(2, code)
        self.assertIn("classification-source-mismatch", errors)


if __name__ == "__main__":
    unittest.main()
