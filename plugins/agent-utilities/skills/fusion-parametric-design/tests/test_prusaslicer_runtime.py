from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from fusion_design.prusaslicer_runtime import (
    AUTHORIZED_VERSION,
    PrusaSlicerRuntime,
    profile_snapshot_sha256,
    resolve_executable,
)


class Runner:
    def __init__(self, *, returncode=0, stdout="", stderr="", mutate=None):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.mutate = mutate
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        if self.mutate:
            self.mutate()
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, self.stderr)


class ActionRunner:
    def __init__(self, payload: dict, *, mutate=None):
        self.payload = payload
        self.mutate = mutate
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if "--help" in argv:
            return subprocess.CompletedProcess(argv, 0, "PrusaSlicer 2.9.6\n", "")
        result = subprocess.CompletedProcess(argv, 1, json.dumps(self.payload), "")
        if self.mutate and "--query-printer-models" in argv:
            self.mutate()
        return result


def _binary(root: Path) -> Path:
    path = root / "PrusaSlicer"
    path.write_bytes(b"fake slicer")
    return path


class RuntimeTests(unittest.TestCase):
    def test_requires_absolute_datadir(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                PrusaSlicerRuntime(_binary(Path(temp)), "relative")

    def test_rejects_invalid_timeouts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for timeout in (True, None, "30", 0, -1, 10**1000, float("nan"), float("inf")):
                with self.subTest(timeout=timeout), self.assertRaisesRegex(ValueError, "positive finite"):
                    PrusaSlicerRuntime(_binary(root), root, timeout=timeout)

    def test_fingerprints_are_stable_and_ignore_unrelated_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "printer").mkdir()
            (root / "print").mkdir()
            (root / "filament").mkdir()
            (root / "vendor").mkdir()
            (root / "PrusaSlicer.ini").write_text("[presets]\n", encoding="utf-8")
            (root / "printer" / "P.ini").write_text("printer_model = P\n", encoding="utf-8")
            first = profile_snapshot_sha256(root)
            self.assertEqual(first, profile_snapshot_sha256(root))
            (root / "notes.txt").write_text("ignored", encoding="utf-8")
            self.assertEqual(first, profile_snapshot_sha256(root))
            (root / "print" / "Q.ini").write_text("print_settings_id = Q\n", encoding="utf-8")
            self.assertNotEqual(first, profile_snapshot_sha256(root))

    def test_help_probe_records_hash_and_authoritative_version(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            datadir = root / "config"
            datadir.mkdir()
            binary = _binary(root)
            runner = Runner(stdout="PrusaSlicer 2.9.6\n")
            runtime = PrusaSlicerRuntime(binary, datadir, runner=runner)
            result = runtime.probe_version()
            self.assertEqual(AUTHORIZED_VERSION, result["version"])
            self.assertEqual(hashlib.sha256(binary.read_bytes()).hexdigest(), result["executable_sha256"])
            self.assertEqual(0, result["exit_code"])
            self.assertEqual([str(binary), "--help"], runner.calls[0][0])
            self.assertFalse(runner.calls[0][1]["shell"])

    def test_help_probe_refuses_unvalidated_version(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            datadir = root / "config"
            datadir.mkdir()
            result = PrusaSlicerRuntime(
                _binary(root), datadir, runner=Runner(stdout="PrusaSlicer 2.9.7\n")
            ).probe_version()
            self.assertEqual("unsupported_version", result["outcome"])
            self.assertFalse(result["ok"])

    def test_help_probe_rejects_suffixed_authorized_version(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            datadir = root / "config"
            datadir.mkdir()
            result = PrusaSlicerRuntime(
                _binary(root), datadir, runner=Runner(stdout="PrusaSlicer 2.9.6-alpha\n")
            ).probe_version()
            self.assertEqual("unsupported_version", result["outcome"])
            self.assertFalse(result["ok"])

    def test_query_exit_one_with_expected_json_is_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            datadir = root / "config"
            datadir.mkdir()
            (datadir / "PrusaSlicer.ini").write_text("[presets]\n", encoding="utf-8")
            payload = {"printer_models": []}
            runner = Runner(
                stdout=json.dumps(payload),
                returncode=1,
            )
            result = PrusaSlicerRuntime(_binary(root), datadir, runner=runner).query_printer_models()
            self.assertTrue(result["ok"])
            self.assertEqual("success", result["outcome"])
            self.assertEqual(1, result["exit_code"])
            self.assertEqual(payload, result["payload"])

    def test_query_accepts_numeric_variant_names(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            datadir = root / "config"
            datadir.mkdir()
            payload = {
                "printer_models": [
                    {
                        "id": "XL5IS",
                        "name": "Original Prusa XL",
                        "variants": [
                            {
                                "name": 0.25,
                                "printer_profiles": [
                                    {
                                        "name": "XL 0.25",
                                        "extruders_cnt": 5,
                                        "bed": {"width": 360, "height": 360},
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
            result = PrusaSlicerRuntime(
                _binary(root), datadir, runner=Runner(stdout=json.dumps(payload), returncode=1)
            ).query_printer_models()
            self.assertTrue(result["ok"])

    def test_query_exit_one_without_expected_json_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            datadir = root / "config"
            datadir.mkdir()
            runner = Runner(stdout="not json", returncode=1)
            result = PrusaSlicerRuntime(_binary(root), datadir, runner=runner).query_printer_models()
            self.assertFalse(result["ok"])
            self.assertEqual("nonzero_exit", result["outcome"])

    def test_compatibility_query_requires_matching_printer_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            datadir = root / "config"
            datadir.mkdir()
            payload = {
                "printer_profile": "Other",
                "print_profiles": [{"name": "Q", "filament_profiles": ["M"]}],
            }
            result = PrusaSlicerRuntime(
                _binary(root), datadir, runner=Runner(stdout=json.dumps(payload), returncode=1)
            ).query_print_filament_profiles("Requested")
            self.assertEqual("nonzero_exit", result["outcome"])
            self.assertFalse(result["ok"])

    def test_normal_exit_139_is_not_a_signal_crash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            datadir = root / "config"
            datadir.mkdir()
            result = PrusaSlicerRuntime(
                _binary(root), datadir, runner=Runner(returncode=139, stdout=json.dumps({"printer_models": []}))
            ).query_printer_models()
            self.assertEqual("nonzero_exit", result["outcome"])
            self.assertIsNone(result["signal"])

    def test_cached_authoritative_probe_refuses_executable_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            datadir = root / "config"
            datadir.mkdir()
            binary = _binary(root)
            runner = ActionRunner({"printer_models": []})
            runtime = PrusaSlicerRuntime(binary, datadir, runner=runner)
            self.assertEqual("success", runtime.query_printer_models_authoritative()["outcome"])
            binary.write_bytes(b"replacement")
            result = runtime.query_printer_models_authoritative()
            self.assertEqual("snapshot_changed", result["outcome"])
            self.assertEqual(2, len(runner.calls))

    def test_authoritative_queries_refuse_datadir_drift_between_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            datadir = root / "config"
            datadir.mkdir()
            target = datadir / "PrusaSlicer.ini"
            target.write_text("before", encoding="utf-8")
            payload = json.dumps({"printer_models": []})
            runner = ActionRunner({"printer_models": []})
            runtime = PrusaSlicerRuntime(_binary(root), datadir, runner=runner)
            self.assertEqual("success", runtime.query_printer_models_authoritative()["outcome"])
            target.write_text("after", encoding="utf-8")
            result = runtime.query_printer_models_authoritative()
            self.assertEqual("snapshot_changed", result["outcome"])

    def test_timeout_preserves_diagnostics_and_classifies_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            datadir = root / "config"
            datadir.mkdir()
            target = datadir / "PrusaSlicer.ini"
            target.write_text("before", encoding="utf-8")

            def timeout(*args, **kwargs):
                target.write_text("after", encoding="utf-8")
                raise subprocess.TimeoutExpired(args[0], kwargs["timeout"], output="out", stderr="err")

            result = PrusaSlicerRuntime(_binary(root), datadir, runner=timeout).query_printer_models()
            self.assertEqual("snapshot_changed", result["outcome"])
            self.assertEqual("out", result["stdout_tail"])
            self.assertEqual("err", result["stderr_tail"])

    def test_oversized_query_output_is_refused_without_parsing_a_tail(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            datadir = root / "config"
            datadir.mkdir()
            payload = json.dumps({"printer_models": [{"padding": "x" * 256}]})
            result = PrusaSlicerRuntime(
                _binary(root), datadir, output_limit=128, runner=Runner(stdout=payload)
            ).query_printer_models()
            self.assertEqual("malformed_json", result["outcome"])
            self.assertIn("128-byte limit", result["reason"])

    def test_query_classifies_missing_config_profile_and_signal(self):
        cases = (
            (Runner(returncode=1, stderr="Configuration wasn't found; check your datadir"), "missing_app_config"),
            (Runner(returncode=1, stderr="Printer profile 'P' wasn't found"), "profile_not_resolvable"),
            (Runner(returncode=-11), "signal_crash"),
        )
        for runner, outcome in cases:
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                datadir = root / "config"
                datadir.mkdir()
                result = PrusaSlicerRuntime(_binary(root), datadir, runner=runner).query_printer_models()
                self.assertEqual(outcome, result["outcome"])

    def test_snapshot_drift_is_terminal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            datadir = root / "config"
            datadir.mkdir()
            target = datadir / "PrusaSlicer.ini"
            target.write_text("before", encoding="utf-8")

            def mutate():
                target.write_text("after", encoding="utf-8")

            runner = Runner(stdout=json.dumps({"printer_models": []}), mutate=mutate)
            result = PrusaSlicerRuntime(_binary(root), datadir, runner=runner).query_printer_models()
            self.assertFalse(result["ok"])
            self.assertEqual("snapshot_changed", result["outcome"])

    def test_timeout_is_distinct(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            datadir = root / "config"
            datadir.mkdir()

            def timeout(*args, **kwargs):
                raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

            result = PrusaSlicerRuntime(_binary(root), datadir, runner=timeout).query_printer_models()
            self.assertEqual("timeout", result["outcome"])


if __name__ == "__main__":
    unittest.main()
