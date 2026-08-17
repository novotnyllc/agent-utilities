from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from fusion_design.cli import main
from fusion_design import report_session


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

    def test_emit_report_path_requires_run_id(self) -> None:
        errors = io.StringIO()
        with redirect_stderr(errors):
            code = main(
                [
                    "emit-inventory",
                    str(EXAMPLE),
                    "--report-path",
                    "/private/tmp/inventory.json",
                ]
            )
        self.assertEqual(2, code)
        self.assertIn("--report-path and --report-run-id must be supplied together", errors.getvalue())

    def test_emit_report_run_id_requires_report_path(self) -> None:
        errors = io.StringIO()
        with redirect_stderr(errors):
            code = main(["emit-inventory", str(EXAMPLE), "--report-run-id", "opaque-run-id"])
        self.assertEqual(2, code)
        self.assertIn("--report-path and --report-run-id must be supplied together", errors.getvalue())

    def test_emit_report_path_requires_absolute_path(self) -> None:
        errors = io.StringIO()
        with redirect_stderr(errors):
            code = main(
                [
                    "emit-inventory",
                    str(EXAMPLE),
                    "--report-path",
                    "reports/inventory.json",
                    "--report-run-id",
                    "opaque-run-id",
                ]
            )
        self.assertEqual(2, code)
        self.assertIn("report path must be absolute", errors.getvalue())

    def test_emit_report_path_is_embedded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "inventory.py"
            report = Path(temporary) / "inventory.json"
            for command in (
                "emit-inventory",
                "emit-parameter-sync",
                "emit-scaffold",
                "emit-verification",
            ):
                with self.subTest(command=command):
                    output.unlink(missing_ok=True)
                    code = main(
                        [
                            command,
                            str(EXAMPLE),
                            "-o",
                            str(output),
                            "--report-path",
                            str(report),
                            "--report-run-id",
                            "opaque-run-id",
                        ]
                    )
                    self.assertEqual(0, code)
                    source = output.read_text(encoding="utf-8")
                    self.assertIn(f"REPORT_PATH = {str(report)!r}", source)
                    self.assertIn("REPORT_RUN_ID = 'opaque-run-id'", source)

    def test_emit_report_path_rejects_existing_target_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report = Path(temporary) / "inventory.json"
            report.write_bytes(b"stale report")
            errors = io.StringIO()
            with redirect_stderr(errors):
                code = main(
                    [
                        "emit-inventory",
                        str(EXAMPLE),
                        "--report-path",
                        str(report),
                        "--report-run-id",
                        "opaque-run-id",
                    ]
                )
            self.assertEqual(2, code)
            self.assertIn("previously nonexistent", errors.getvalue())
            self.assertEqual(b"stale report", report.read_bytes())

    def test_emit_rejects_manifest_output_and_report_aliases(self) -> None:
        errors = io.StringIO()
        with redirect_stderr(errors):
            code = main(["emit-inventory", str(EXAMPLE), "-o", str(EXAMPLE)])
        self.assertEqual(2, code)
        self.assertIn("manifest and output must name different files", errors.getvalue())

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "shared.py"
            errors = io.StringIO()
            with redirect_stderr(errors):
                code = main(
                    [
                        "emit-inventory",
                        str(EXAMPLE),
                        "-o",
                        str(path),
                        "--report-path",
                        str(path),
                        "--report-run-id",
                        "opaque-run-id",
                    ]
                )
            self.assertEqual(2, code)
            self.assertIn("output and report path must name different files", errors.getvalue())

    def _prepare_report_session(self, _temporary: str, kind: str = "inventory") -> dict[str, str]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["prepare-report-session", str(EXAMPLE), kind])
        self.assertEqual(0, code)
        session = json.loads(output.getvalue())
        self.assertEqual(
            {
                "session_file",
                "script",
                "report_path",
                "run_id",
                "kind",
                "manifest_sha256",
            },
            set(session),
        )
        self.assertTrue(Path(session["session_file"]).is_absolute())
        return session

    def test_prepare_report_session_binds_private_artifacts_for_every_kind(self) -> None:
        kinds = ("inventory", "parameter-sync", "scaffold", "verification")
        with tempfile.TemporaryDirectory() as temporary:
            sessions = [self._prepare_report_session(temporary, kind) for kind in kinds]
            for session in sessions:
                with self.subTest(kind=session["kind"]):
                    session_file = Path(session["session_file"])
                    script = Path(session["script"])
                    report = Path(session["report_path"])
                    session_directory = session_file.parent
                    self.assertEqual(session_directory, script.parent)
                    self.assertEqual(session_directory, report.parent)
                    self.assertRegex(session["run_id"], r"\A[0-9a-f]{64}\Z")
                    self.assertRegex(session["manifest_sha256"], r"\A[0-9a-f]{64}\Z")
                    self.assertEqual(0o700, stat.S_IMODE(session_directory.stat().st_mode))
                    self.assertEqual(0o600, stat.S_IMODE(session_file.stat().st_mode))
                    self.assertEqual(0o600, stat.S_IMODE(script.stat().st_mode))
                    self.assertFalse(report.exists())
                    self.assertFalse(report.is_symlink())
                    source = script.read_text(encoding="utf-8")
                    self.assertIn(f"REPORT_PATH = {str(report)!r}", source)
                    self.assertIn(f"REPORT_RUN_ID = {session['run_id']!r}", source)
                    self.assertIn(f"MANIFEST_SHA256 = {session['manifest_sha256']!r}", source)

            for session in sessions:
                output = io.StringIO()
                with redirect_stdout(output):
                    code = main(["cleanup-report-session", session["session_file"]])
                self.assertEqual(0, code)
                self.assertEqual("removed", json.loads(output.getvalue())["status"])

    def test_prepare_report_session_fails_closed_without_posix_primitives(self) -> None:
        errors = io.StringIO()
        with patch.object(report_session.os, "fchmod", None), redirect_stderr(errors):
            code = main(["prepare-report-session", str(EXAMPLE), "inventory"])
        self.assertEqual(2, code)
        self.assertIn("report-file fallback requires POSIX file semantics", errors.getvalue())
        self.assertIn("fchmod", errors.getvalue())

    def test_scaffold_session_uses_canonical_component_scaffold_report_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            session = self._prepare_report_session(temporary, "scaffold")
            self.assertEqual("component-scaffold", session["kind"])
            self.assertEqual("component-scaffold.json", Path(session["report_path"]).name)
            source = Path(session["script"]).read_text(encoding="utf-8")
            self.assertIn('"kind": "component-scaffold"', source)
            self.assertNotIn('"kind": "scaffold"', source)

            report = Path(session["report_path"])
            valid = {
                "kind": "component-scaffold",
                "manifest_sha256": session["manifest_sha256"],
                "report_run_id": session["run_id"],
                "ok": True,
            }
            report.write_text(json.dumps(valid) + "\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["verify-report-session", session["session_file"]])
            self.assertEqual(0, code)
            self.assertEqual(valid, json.loads(output.getvalue()))

            report.write_text(json.dumps(dict(valid, kind="scaffold")) + "\n", encoding="utf-8")
            errors = io.StringIO()
            with redirect_stderr(errors):
                code = main(["verify-report-session", session["session_file"]])
            self.assertEqual(2, code)
            self.assertIn("identity mismatch", errors.getvalue())

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["cleanup-report-session", session["session_file"]])
            self.assertEqual(0, code)

    def test_report_session_verification_is_identity_bound_and_non_destructive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            session = self._prepare_report_session(temporary)
            report = Path(session["report_path"])
            valid = {
                "kind": session["kind"],
                "manifest_sha256": session["manifest_sha256"],
                "report_run_id": session["run_id"],
                "ok": True,
            }
            report.write_text(json.dumps(valid) + "\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["verify-report-session", session["session_file"]])
            self.assertEqual(0, code)
            self.assertEqual(valid, json.loads(output.getvalue()))
            self.assertTrue(Path(session["session_file"]).exists())
            self.assertTrue(Path(session["script"]).exists())
            self.assertTrue(report.exists())

            for field, replacement in (
                ("report_run_id", "0" * 64),
                ("kind", "verification"),
                ("manifest_sha256", "f" * 64),
            ):
                invalid = dict(valid, **{field: replacement})
                report.write_text(json.dumps(invalid) + "\n", encoding="utf-8")
                errors = io.StringIO()
                with redirect_stderr(errors):
                    code = main(["verify-report-session", session["session_file"]])
                self.assertEqual(2, code)
                self.assertIn("identity mismatch", errors.getvalue())
                self.assertTrue(Path(session["session_file"]).exists())
                self.assertTrue(Path(session["script"]).exists())
                self.assertTrue(report.exists())

            report.write_text("{} {}\n", encoding="utf-8")
            errors = io.StringIO()
            with redirect_stderr(errors):
                code = main(["verify-report-session", session["session_file"]])
            self.assertEqual(2, code)
            self.assertIn("one JSON object", errors.getvalue())
            self.assertTrue(report.exists())

            report.unlink()
            external = Path(temporary) / "external.json"
            external.write_text(json.dumps(valid), encoding="utf-8")
            report.symlink_to(external)
            errors = io.StringIO()
            with redirect_stderr(errors):
                code = main(["verify-report-session", session["session_file"]])
            self.assertEqual(2, code)
            self.assertIn("canonical path", errors.getvalue())
            self.assertEqual(json.dumps(valid), external.read_text(encoding="utf-8"))
            report.unlink()

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["cleanup-report-session", session["session_file"]])
            self.assertEqual(0, code)

    def test_report_session_cleanup_rejects_unexpected_entries_and_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            session = self._prepare_report_session(temporary)
            directory = Path(session["session_file"]).parent
            unexpected = directory / "unexpected.txt"
            unexpected.write_text("do not touch", encoding="utf-8")
            errors = io.StringIO()
            with redirect_stderr(errors):
                code = main(["cleanup-report-session", session["session_file"]])
            self.assertEqual(2, code)
            self.assertIn("unexpected entries", errors.getvalue())
            self.assertTrue(Path(session["session_file"]).exists())
            self.assertTrue(Path(session["script"]).exists())
            self.assertTrue(unexpected.exists())
            unexpected.unlink()

            external = Path(temporary) / "outside.txt"
            external.write_text("outside", encoding="utf-8")
            report = Path(session["report_path"])
            report.symlink_to(external)
            errors = io.StringIO()
            with redirect_stderr(errors):
                code = main(["cleanup-report-session", session["session_file"]])
            self.assertEqual(2, code)
            self.assertIn("canonical path", errors.getvalue())
            self.assertTrue(Path(session["session_file"]).exists())
            self.assertTrue(Path(session["script"]).exists())
            self.assertTrue(report.is_symlink())
            self.assertEqual("outside", external.read_text(encoding="utf-8"))
            report.unlink()

            os.link(session["script"], report)
            errors = io.StringIO()
            with redirect_stderr(errors):
                code = main(["cleanup-report-session", session["session_file"]])
            self.assertEqual(2, code)
            self.assertIn("hard-link alias", errors.getvalue())
            self.assertTrue(Path(session["session_file"]).exists())
            self.assertTrue(Path(session["script"]).exists())
            report.unlink()

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["cleanup-report-session", session["session_file"]])
            self.assertEqual(0, code)
            self.assertFalse(directory.exists())

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["cleanup-report-session", session["session_file"]])
            self.assertEqual(0, code)
            self.assertEqual("already-absent", json.loads(output.getvalue())["status"])


if __name__ == "__main__":
    unittest.main()
