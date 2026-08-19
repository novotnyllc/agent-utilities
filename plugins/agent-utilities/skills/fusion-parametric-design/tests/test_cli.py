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
from fusion_design.cli import main
from fusion_design.export_handoff import example_verification_report
from fusion_design.manifest import load_manifest
from test_prusaslicer_project import _Fixture, _config_root, _intent, process_execution_offenses
from test_prusaslicer_slice import _fake_slicer


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "electronics-enclosure" / "fusion-project.json"
# The parts the example manifest declares printable; the index must name these.
EXAMPLE_BASE = "10_PRODUCT/PROD__BASE"
EXAMPLE_LID = "10_PRODUCT/PROD__LID"


class CliTests(unittest.TestCase):
    def test_validate_prints_json_for_valid_manifest(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["validate", str(EXAMPLE)])
        self.assertEqual(0, code)
        self.assertIn('"ok": true', output.getvalue())

    def test_validate_serializes_validation_issues(self) -> None:
        broken = ROOT / "tests" / "_cli_broken.json"
        data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        data["parameters"][0].pop("source_id")
        broken.write_text(json.dumps(data), encoding="utf-8")
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                code = main(["validate", str(broken)])
            self.assertEqual(2, code)
            self.assertIn("critical-parameter-missing-source", output.getvalue())
        finally:
            broken.unlink(missing_ok=True)

    def test_validate_rejects_non_object_manifest_root(self) -> None:
        broken = ROOT / "tests" / "_cli_non_object.json"
        broken.write_text("[]", encoding="utf-8")
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                code = main(["validate", str(broken)])
            self.assertEqual(2, code)
            self.assertIn("manifest-root-invalid", output.getvalue())
        finally:
            broken.unlink(missing_ok=True)

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
                geometry={EXAMPLE_BASE: {"solid_body_count": 1, "has_positive_solid": True}},
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

    def _handoff(self, root: Path, manifest=None) -> tuple[Path, Path]:
        fixture = _Fixture(root)
        fixture.add_part(EXAMPLE_BASE, intent=_intent(print_as="assembled"), with_step=True)
        fixture.add_part(
            EXAMPLE_LID,
            intent=_intent(
                print_as="assembled",
                quantity=2,
                orientation={"contact_face": "+Z", "rationale": "declared", "allowed_alternatives": []},
                support_policy="build-plate-only",
            ),
        )
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
            self.assertEqual(
                [{"plate": 1, "part_paths": [EXAMPLE_BASE, EXAMPLE_LID]}], payload["plates"]
            )
            lid = next(obj for obj in payload["objects"] if obj["part_path"] == EXAMPLE_LID)
            self.assertEqual({"contact_face": "+Z", "axis": "X", "degrees": 180}, lid["applied_rotation"])
            self.assertEqual(2, lid["instances_count"])
            self.assertEqual(1, lid["plate"])
            self.assertEqual("1", lid["overrides"]["support_material_buildplate_only"])
            self.assertEqual(
                {"printer", "filament", "print"}, set(payload["presets"]), payload["presets"]
            )

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
            fixture.add_part("10_PRODUCT/PROD__STOWAWAY")
            index = fixture.write_index(manifest=manifest)
            output = root / "p.3mf"
            code, _, errors = self._run(self._argv(index, output, _config_root(root)))
            self.assertEqual(2, code)
            self.assertIn("does not declare as printable: 10_PRODUCT/PROD__STOWAWAY", errors)
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


if __name__ == "__main__":
    unittest.main()
