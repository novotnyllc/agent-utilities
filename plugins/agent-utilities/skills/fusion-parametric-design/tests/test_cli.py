from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from fusion_design.cli import main


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


if __name__ == "__main__":
    unittest.main()
