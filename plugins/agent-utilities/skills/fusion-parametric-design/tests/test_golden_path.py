from __future__ import annotations

import json
from pathlib import Path
import unittest

from fusion_design.export_handoff import emit_export_example_script, example_verification_report_bytes
from fusion_design.manifest import load_manifest
from fusion_design.planner import build_plan
from fusion_design.positive_control import _box_specs, emit_positive_control_script
from fusion_design.scripts import manifest_sha256


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "electronics-enclosure"
MANIFEST_PATH = EXAMPLE / "fusion-project.json"
GENERATED = EXAMPLE / "generated"


class GoldenPathTests(unittest.TestCase):
    def test_every_critical_example_parameter_carries_provenance(self) -> None:
        # The example is what an agent imitates, so it must not model the
        # shortcut the doctrine forbids: a critical value with no source, or an
        # uncouponed fabrication/clearance value declared settled.
        manifest = load_manifest(MANIFEST_PATH)
        source_ids = {str(source["id"]) for source in manifest.data["sources"]}
        settle_by_measurement = {"clearance", "fabrication", "packing"}
        for parameter in manifest.parameters:
            if not parameter.get("critical"):
                continue
            name = parameter["name"]
            source_id = parameter.get("source_id")
            self.assertIn(source_id, source_ids, f"{name} has no known provenance source")
            if parameter.get("role") in settle_by_measurement:
                self.assertTrue(
                    parameter.get("provisional"),
                    f"{name} claims a settled {parameter['role']} value; no coupon supports it",
                )

    def test_enclosure_fixture_is_an_executable_golden_path(self) -> None:
        manifest = load_manifest(MANIFEST_PATH)
        self.assertFalse(build_plan(manifest).blocked)

        digest = manifest_sha256(manifest)
        scripts = sorted(GENERATED.glob("*.py"))
        self.assertEqual(
            {"export.py", "inventory.py", "positive_control.py", "scaffold.py", "sync_parameters.py", "verify.py"},
            {path.name for path in scripts},
        )
        for path in scripts:
            source = path.read_text(encoding="utf-8")
            compile(source, str(path), "exec")
            self.assertIn(digest, source, path.name)

        self.assertEqual(
            emit_positive_control_script(manifest),
            (GENERATED / "positive_control.py").read_text(encoding="utf-8"),
        )

        self.assertEqual(
            example_verification_report_bytes(manifest),
            (EXAMPLE / "sample-verification-report.json").read_bytes(),
        )
        self.assertEqual(
            emit_export_example_script(manifest),
            (GENERATED / "export.py").read_text(encoding="utf-8"),
        )
        export_source = (GENERATED / "export.py").read_text(encoding="utf-8")
        for token in ("stale-verification", "export-capability", "output-exists", "cleanup-incomplete", "FUSION_EXPORT_DIR"):
            self.assertIn(token, export_source)

        data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        verification = data["verification"]
        positive_control = (GENERATED / "positive_control.py").read_text(encoding="utf-8")
        checked_paths = set(verification["required_components"])
        checked_paths.update(verification["expected_print_parts"])
        for check in verification["clearance_checks"] + verification["interference_checks"]:
            checked_paths.update((check["one"], check["two"]))
        for path in checked_paths:
            self.assertIn(json.dumps(path), positive_control, path)
        self.assertIn("isSaved", positive_control)
        self.assertIn("manifest_sha256", positive_control)
        self.assertIn("transform2", positive_control)
        self.assertIn("expected complete bounds", positive_control)
        self.assertIn("exactly one B-Rep body", positive_control)
        self.assertIn("cleanup left partial artifacts", positive_control)

        changed = manifest.to_dict()
        next(parameter for parameter in changed["parameters"] if parameter["name"] == "src_pd_board_length")[
            "expression"
        ] = "36 mm"
        changed_manifest = type(manifest).from_data(changed)
        changed_spec = next(
            spec
            for spec in _box_specs(changed_manifest)
            if spec["path"] == "00_REFERENCES/PACK__PD_TRIGGER__EXACT_OR_CONSERVATIVE"
        )
        self.assertEqual([36.0, 13.0, 5.0], changed_spec["size_mm"])
        self.assertNotEqual(emit_positive_control_script(manifest), emit_positive_control_script(changed_manifest))

        invalid_size = manifest.to_dict()
        next(parameter for parameter in invalid_size["parameters"] if parameter["name"] == "src_pd_board_length")[
            "expression"
        ] = "0 mm"
        with self.assertRaisesRegex(ValueError, "requires a positive value"):
            emit_positive_control_script(type(manifest).from_data(invalid_size))

        infinite_size = manifest.to_dict()
        next(parameter for parameter in infinite_size["parameters"] if parameter["name"] == "src_pd_board_length")[
            "expression"
        ] = "9" * 400 + " mm"
        with self.assertRaisesRegex(ValueError, "requires a positive value"):
            emit_positive_control_script(type(manifest).from_data(infinite_size))

        impossible_clearance = manifest.to_dict()
        impossible_clearance["verification"]["clearance_checks"][0]["minimum_mm"] = 6.0
        with self.assertRaisesRegex(ValueError, "below the manifest minimum"):
            emit_positive_control_script(type(manifest).from_data(impossible_clearance))

        non_finite_clearance = manifest.to_dict()
        non_finite_clearance["verification"]["clearance_checks"][0]["minimum_mm"] = float("nan")
        with self.assertRaisesRegex(ValueError, "has an invalid minimum"):
            emit_positive_control_script(type(manifest).from_data(non_finite_clearance, validate=False))

        oversized_clearance = manifest.to_dict()
        oversized_clearance["verification"]["clearance_checks"][0]["minimum_mm"] = 10**400
        with self.assertRaisesRegex(ValueError, "has an invalid minimum"):
            emit_positive_control_script(type(manifest).from_data(oversized_clearance, validate=False))

        missing_allowed_interference = manifest.to_dict()
        missing_allowed_interference["verification"]["interference_checks"].append(
            {
                "id": "missing-allowed-body",
                "one": "00_REFERENCES/REF__PD_TRIGGER__PARAMETRIC",
                "two": "10_PRODUCT/PROD__BASE",
                "allow_interference": True,
            }
        )
        with self.assertRaisesRegex(ValueError, "missing interference check"):
            emit_positive_control_script(type(manifest).from_data(missing_allowed_interference))

        wrong_fixture = manifest.to_dict()
        wrong_fixture["project"]["name"] = "another-project"
        with self.assertRaisesRegex(ValueError, "only defined for the electronics-enclosure"):
            emit_positive_control_script(type(manifest).from_data(wrong_fixture))


if __name__ == "__main__":
    unittest.main()
