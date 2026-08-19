from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from fusion_design.cli import main
from fusion_design.export_handoff import example_verification_report
from fusion_design.manifest import load_manifest


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "electronics-enclosure" / "fusion-project.json"


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


class EmitExportCliTests(unittest.TestCase):
    def _write_report(self, directory: Path, mutate=None, keep_sample_marker=False) -> Path:
        report = example_verification_report(load_manifest(EXAMPLE))
        if not keep_sample_marker:
            report.pop("sample", None)
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
                ["emit-export", str(EXAMPLE), "--verification-report", str(report_path), "--export-dir", "/exports"]
            )
            self.assertEqual(2, code)
            self.assertIn("does not match manifest", errors)

    def test_emit_export_rejects_failed_or_wrong_kind_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            failed = self._write_report(Path(temporary), mutate=lambda report: report.update(ok=False))
            code, _, errors = self._run(
                ["emit-export", str(EXAMPLE), "--verification-report", str(failed), "--export-dir", "/exports"]
            )
            self.assertEqual(2, code)
            self.assertIn("ok: true", errors)

            wrong_kind = self._write_report(Path(temporary), mutate=lambda report: report.update(kind="inventory"))
            code, _, errors = self._run(
                ["emit-export", str(EXAMPLE), "--verification-report", str(wrong_kind), "--export-dir", "/exports"]
            )
            self.assertEqual(2, code)
            self.assertIn("expected 'verification'", errors)

    def test_emit_export_rejects_report_missing_part_bounds(self) -> None:
        def drop_bounds(report):
            report["brep_bounding_boxes_mm"].pop(next(iter(report["brep_bounding_boxes_mm"])))

        with tempfile.TemporaryDirectory() as temporary:
            report_path = self._write_report(Path(temporary), mutate=drop_bounds)
            code, _, errors = self._run(
                ["emit-export", str(EXAMPLE), "--verification-report", str(report_path), "--export-dir", "/exports"]
            )
            self.assertEqual(2, code)
            self.assertIn("no usable B-Rep bounds", errors)

    def test_emit_export_rejects_path_aliasing_and_duplicate_formats(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report_path = self._write_report(Path(temporary))
            code, _, errors = self._run(
                ["emit-export", str(EXAMPLE), "--verification-report", str(EXAMPLE), "--export-dir", "/exports"]
            )
            self.assertEqual(2, code)
            self.assertIn("must name different files", errors)

            code, _, errors = self._run(
                [
                    "emit-export",
                    str(EXAMPLE),
                    "--verification-report",
                    str(report_path),
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
                ["emit-export", str(EXAMPLE), "--verification-report", str(report_path), "--export-dir", "/exports"]
            )
            self.assertEqual(2, code)
            self.assertIn("sample verification report", errors)

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
                            "--export-dir",
                            "/exports",
                            "--format",
                            "obj",
                        ]
                    )


if __name__ == "__main__":
    unittest.main()
