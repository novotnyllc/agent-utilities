from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

from fusion_design import prusaslicer_project
from fusion_design.printable_parts import CONTACT_FACES, SUPPORT_POLICIES
from fusion_design.prusaslicer_project import (
    ResolvedPresets,
    build_project,
    overrides_for_intent,
    resolve_presets,
    rotation_for_contact_face,
    validate_overrides,
)


VERTICES = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (0.0, 20.0, 0.0), (0.0, 0.0, 30.0)]
TRIANGLES = [(0, 1, 2), (0, 1, 3), (1, 2, 3), (0, 2, 3)]

FACE_NORMALS = {
    "+X": (1.0, 0.0, 0.0),
    "-X": (-1.0, 0.0, 0.0),
    "+Y": (0.0, 1.0, 0.0),
    "-Y": (0.0, -1.0, 0.0),
    "+Z": (0.0, 0.0, 1.0),
    "-Z": (0.0, 0.0, -1.0),
}


def _source_3mf_bytes(vertices=VERTICES, triangles=TRIANGLES, unit: str = "millimeter", transform: str | None = None) -> bytes:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<model unit="{unit}" xmlns="{prusaslicer_project.CORE_NAMESPACE}">',
        " <resources>",
        '  <object id="1" type="model">',
        "   <mesh>",
        "    <vertices>",
    ]
    for vertex in vertices:
        lines.append(f'     <vertex x="{vertex[0]}" y="{vertex[1]}" z="{vertex[2]}"/>')
    lines.append("    </vertices>")
    lines.append("    <triangles>")
    for triangle in triangles:
        lines.append(f'     <triangle v1="{triangle[0]}" v2="{triangle[1]}" v3="{triangle[2]}"/>')
    lines.extend(["    </triangles>", "   </mesh>", "  </object>", " </resources>", " <build>"])
    attribute = f' transform="{transform}"' if transform else ""
    lines.append(f'  <item objectid="1"{attribute}/>')
    lines.extend([" </build>", "</model>"])
    model = "\n".join(lines).encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(prusaslicer_project.MODEL_ENTRY, model)
    return buffer.getvalue()


def _intent(**overrides):
    intent = {
        "id": "part_a",
        "quantity": 1,
        "print_as": "separate",
        "orientation": {"contact_face": "-Z", "rationale": "largest flat face", "allowed_alternatives": []},
        "support_policy": "none",
        "strength": {"min_perimeters": 3, "infill_percent": {"target": 20}},
        "protected_features": [],
        "material": {"assumption": "PETG", "status": "provisional"},
    }
    intent.update(overrides)
    return intent


class _Fixture:
    """Synthesized export handoff: 3MF artifacts plus an index, all on disk."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.export_dir = root / "exports"
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts: list[dict] = []

    def add_part(self, part_path: str, intent=None, payload: bytes | None = None, with_step: bool = False) -> dict:
        data = payload if payload is not None else _source_3mf_bytes()
        filename = f"{part_path.replace('/', '-')}.3mf"
        (self.export_dir / filename).write_bytes(data)
        artifact = {
            "part_path": part_path,
            "format": "3mf",
            "filename": filename,
            "sha256": hashlib.sha256(data).hexdigest(),
            "byte_size": len(data),
            "manufacturing_intent": intent if intent is not None else _intent(),
        }
        self.artifacts.append(artifact)
        if with_step:
            step = b"ISO-10303-21;\nENDSEC;\nEND-ISO-10303-21;\n"
            step_name = f"{part_path.replace('/', '-')}.step"
            (self.export_dir / step_name).write_bytes(step)
            self.artifacts.append(
                {
                    "part_path": part_path,
                    "format": "step",
                    "filename": step_name,
                    "sha256": hashlib.sha256(step).hexdigest(),
                    "byte_size": len(step),
                }
            )
        return artifact

    def write_index(self, name: str = "export-index.json", **overrides) -> Path:
        index = {
            "kind": "export-handoff",
            "ok": True,
            "project": "Widget",
            "manifest_sha256": "0" * 64,
            "artifacts": self.artifacts,
        }
        index.update(overrides)
        path = self.export_dir / name
        path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path


def _config_root(root: Path, selected: dict[str, str] | None = None, user_presets: dict[str, list[str]] | None = None) -> Path:
    config = root / "PrusaSlicer"
    user_presets = user_presets if user_presets is not None else {
        "printer": ["Original Prusa XL - 5T"],
        "filament": ["Overture PETG @XL HF0.4 - Black"],
        "print": ["0.40 SPEED @XLIS HF0.6 mixed"],
    }
    for kind, names in user_presets.items():
        directory = config / kind
        directory.mkdir(parents=True, exist_ok=True)
        for preset_name in names:
            (directory / f"{preset_name}.ini").write_text("layer_height = 0.2\n", encoding="utf-8")
    config.mkdir(parents=True, exist_ok=True)
    selected = selected if selected is not None else {
        "printer": "Original Prusa XL - 5T",
        "filament": "Overture PETG @XL HF0.4 - Black",
        "print": "0.40 SPEED @XLIS HF0.6 mixed",
    }
    lines = ["[presets]"] + [f"{kind} = {name}" for kind, name in sorted(selected.items())]
    (config / "PrusaSlicer.ini").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return config


def _presets(config: Path) -> ResolvedPresets:
    return resolve_presets({}, config)


def _entries(project: Path) -> dict[str, str]:
    with zipfile.ZipFile(project) as archive:
        return {name: archive.read(name).decode("utf-8") for name in archive.namelist()}


class RotationTests(unittest.TestCase):
    def test_every_contact_face_maps_its_normal_onto_the_bed(self) -> None:
        for face in sorted(CONTACT_FACES):
            with self.subTest(face=face):
                rotation, record = rotation_for_contact_face(face)
                rotated = prusaslicer_project._apply(rotation, FACE_NORMALS[face])
                self.assertEqual((0.0, 0.0, -1.0), tuple(float(value) for value in rotated))
                self.assertEqual(face, record["contact_face"])

    def test_contact_face_minus_z_is_identity(self) -> None:
        rotation, record = rotation_for_contact_face("-Z")
        self.assertEqual(((1, 0, 0), (0, 1, 0), (0, 0, 1)), rotation)
        self.assertEqual({"contact_face": "-Z", "axis": None, "degrees": 0}, record)

    def test_unknown_contact_face_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "contact_face"):
            rotation_for_contact_face("sideways")


class OverrideTests(unittest.TestCase):
    def test_every_support_policy_maps_to_justified_keys(self) -> None:
        expected = {
            "none": {"support_material": "0"},
            "build-plate-only": {"support_material": "1", "support_material_buildplate_only": "1"},
            "everywhere": {"support_material": "1", "support_material_buildplate_only": "0"},
            "explicit-regions": {"support_material": "1", "support_material_buildplate_only": "0"},
        }
        self.assertEqual(SUPPORT_POLICIES, set(expected))
        for policy, support_keys in expected.items():
            with self.subTest(policy=policy):
                overrides = overrides_for_intent(_intent(support_policy=policy), "Widget/Part")
                for key, value in support_keys.items():
                    self.assertEqual(value, overrides[key])
                self.assertNotIn("support_material_style", overrides)

    def test_strength_drives_infill_and_perimeters(self) -> None:
        intent = _intent(strength={"min_perimeters": 5, "infill_percent": {"target": 42.5}})
        overrides = overrides_for_intent(intent, "Widget/Part")
        self.assertEqual("5", overrides["perimeters"])
        self.assertEqual("42.5%", overrides["fill_density"])

    def test_unjustified_override_key_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unjustified per-object overrides: layer_height"):
            validate_overrides({"layer_height": "0.2"}, "Widget/Part")

    def test_missing_declaration_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "support_policy"):
            overrides_for_intent(_intent(support_policy="whenever"), "Widget/Part")
        with self.assertRaisesRegex(ValueError, "min_perimeters"):
            overrides_for_intent(_intent(strength={"min_perimeters": 0, "infill_percent": {"target": 20}}), "Widget/Part")
        with self.assertRaisesRegex(ValueError, "infill_percent"):
            overrides_for_intent(_intent(strength={"min_perimeters": 2}), "Widget/Part")


class PresetResolutionTests(unittest.TestCase):
    def test_selected_system_preset_without_a_user_ini_resolves(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = _config_root(
                Path(temporary),
                selected={
                    "printer": "Original Prusa XL - 5T",
                    "filament": "Prusament PETG @XL HF0.4",
                    "print": "0.20mm SPEED @XLIS HF0.4",
                },
            )
            self.assertFalse((config / "filament" / "Prusament PETG @XL HF0.4.ini").exists())
            presets = resolve_presets({"filament": "Prusament PETG @XL HF0.4"}, config)
            self.assertEqual("Prusament PETG @XL HF0.4", presets.filament)
            self.assertEqual("0.20mm SPEED @XLIS HF0.4", presets.print_settings)

    def test_user_ini_preset_resolves_even_when_not_selected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = _config_root(Path(temporary))
            presets = resolve_presets({"print": "0.40 SPEED @XLIS HF0.6 mixed"}, config)
            self.assertEqual("0.40 SPEED @XLIS HF0.6 mixed", presets.print_settings)

    def test_unknown_preset_lists_what_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = _config_root(Path(temporary))
            with self.assertRaises(ValueError) as caught:
                resolve_presets({"printer": "Bambu X1C"}, config)
            message = str(caught.exception)
            self.assertIn("'Bambu X1C' is not installed", message)
            self.assertIn("Original Prusa XL - 5T", message)

    def test_missing_config_root_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "does not exist"):
                resolve_presets({}, Path(temporary) / "absent")

    def test_no_selection_and_no_request_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = _config_root(Path(temporary), selected={})
            with self.assertRaisesRegex(ValueError, "records no selected"):
                resolve_presets({}, config)

    def test_unknown_preset_kind_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = _config_root(Path(temporary))
            with self.assertRaisesRegex(ValueError, "Unknown preset kinds: nozzle"):
                resolve_presets({"nozzle": "0.4"}, config)


class ProjectWriterTests(unittest.TestCase):
    def test_index_round_trip_produces_one_object_per_part(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            fixture.add_part("Widget/Bracket", with_step=True)
            fixture.add_part("Widget/Cover")
            index = fixture.write_index()
            config = _config_root(root)
            output = root / "project.3mf"

            result = build_project(index, output, _presets(config))

            self.assertTrue(result["ok"])
            self.assertEqual(["Widget/Bracket", "Widget/Cover"], [obj["part_path"] for obj in result["objects"]])
            entries = _entries(output)
            self.assertEqual(
                {
                    "[Content_Types].xml",
                    "_rels/.rels",
                    prusaslicer_project.MODEL_ENTRY,
                    prusaslicer_project.CONFIG_ENTRY,
                    prusaslicer_project.MODEL_CONFIG_ENTRY,
                },
                set(entries),
            )
            model = ET.fromstring(entries[prusaslicer_project.MODEL_ENTRY])
            objects = [node for node in model.iter() if prusaslicer_project._local(node.tag) == "object"]
            self.assertEqual(2, len(objects))
            config_xml = ET.fromstring(entries[prusaslicer_project.MODEL_CONFIG_ENTRY])
            names = [
                node.get("value")
                for node in config_xml.iter("metadata")
                if node.get("type") == "object" and node.get("key") == "name"
            ]
            self.assertEqual(["Widget/Bracket", "Widget/Cover"], names)

    def test_step_artifacts_are_provenance_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            fixture.add_part("Widget/Bracket", with_step=True)
            result = build_project(fixture.write_index(), root / "p.3mf", _presets(_config_root(root)))
            provenance = result["objects"][0]["provenance_artifacts"]
            self.assertEqual(["step"], [record["format"] for record in provenance])
            self.assertEqual("3mf", result["objects"][0]["source_artifact"]["format"])

    def test_hash_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            artifact = fixture.add_part("Widget/Bracket")
            artifact["sha256"] = "f" * 64
            with self.assertRaisesRegex(ValueError, "hashes to"):
                build_project(fixture.write_index(), root / "p.3mf", _presets(_config_root(root)))

    def test_byte_size_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            artifact = fixture.add_part("Widget/Bracket")
            artifact["byte_size"] = artifact["byte_size"] + 1
            with self.assertRaisesRegex(ValueError, "the index records"):
                build_project(fixture.write_index(), root / "p.3mf", _presets(_config_root(root)))

    def test_missing_artifact_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            artifact = fixture.add_part("Widget/Bracket")
            (fixture.export_dir / artifact["filename"]).unlink()
            with self.assertRaisesRegex(ValueError, "which is not a file"):
                build_project(fixture.write_index(), root / "p.3mf", _presets(_config_root(root)))

    def test_index_without_manufacturing_intent_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            artifact = fixture.add_part("Widget/Bracket")
            del artifact["manufacturing_intent"]
            with self.assertRaisesRegex(ValueError, "carries no manufacturing_intent"):
                build_project(fixture.write_index(), root / "p.3mf", _presets(_config_root(root)))

    def test_non_ok_or_wrong_kind_index_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            fixture.add_part("Widget/Bracket")
            presets = _presets(_config_root(root))
            with self.assertRaisesRegex(ValueError, "not ok: true"):
                build_project(fixture.write_index("a.json", ok=False), root / "a.3mf", presets)
            with self.assertRaisesRegex(ValueError, "expected 'export-handoff'"):
                build_project(fixture.write_index("b.json", kind="verification"), root / "b.3mf", presets)
            with self.assertRaisesRegex(ValueError, "is not a file"):
                build_project(root / "absent.json", root / "c.3mf", presets)

    def test_traversal_filename_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            artifact = fixture.add_part("Widget/Bracket")
            artifact["filename"] = f"../{artifact['filename']}"
            with self.assertRaisesRegex(ValueError, "must be a bare filename"):
                build_project(fixture.write_index(), root / "p.3mf", _presets(_config_root(root)))

    def test_contact_face_reaches_the_build_transform(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for face in sorted(CONTACT_FACES):
                with self.subTest(face=face):
                    case = root / face.replace("+", "plus").replace("-", "minus")
                    fixture = _Fixture(case)
                    fixture.add_part(
                        "Widget/Bracket",
                        intent=_intent(
                            orientation={"contact_face": face, "rationale": "declared", "allowed_alternatives": []}
                        ),
                    )
                    result = build_project(
                        fixture.write_index(), case / "p.3mf", _presets(_config_root(root))
                    )
                    record = result["objects"][0]["applied_rotation"]
                    self.assertEqual(prusaslicer_project.CONTACT_FACE_ROTATIONS[face], (record["axis"], record["degrees"]))
                    model = ET.fromstring(_entries(case / "p.3mf")[prusaslicer_project.MODEL_ENTRY])
                    items = [node for node in model.iter() if prusaslicer_project._local(node.tag) == "item"]
                    self.assertEqual(1, len(items))
                    rotation, _ = rotation_for_contact_face(face)
                    values = [float(value) for value in items[0].get("transform").split()]
                    self.assertEqual(12, len(values))
                    # 3MF stores the row-vector matrix, so the leading nine are R transposed.
                    self.assertEqual(
                        [float(rotation[row][column]) for column in range(3) for row in range(3)],
                        values[:9],
                    )
                    # The rotated mesh sits on the bed, never below it.
                    self.assertAlmostEqual(0.0, min(
                        prusaslicer_project._apply(rotation, vertex)[2] + values[11] for vertex in VERTICES
                    ))

    def test_quantity_maps_to_instances_count_and_build_items(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            fixture.add_part("Widget/Bracket", intent=_intent(quantity=3))
            output = root / "p.3mf"
            result = build_project(fixture.write_index(), output, _presets(_config_root(root)))
            self.assertEqual(3, result["objects"][0]["instances_count"])
            entries = _entries(output)
            config_xml = ET.fromstring(entries[prusaslicer_project.MODEL_CONFIG_ENTRY])
            self.assertEqual(["3"], [node.get("instances_count") for node in config_xml.iter("object")])
            model = ET.fromstring(entries[prusaslicer_project.MODEL_ENTRY])
            items = [node for node in model.iter() if prusaslicer_project._local(node.tag) == "item"]
            self.assertEqual(3, len(items))
            offsets = [float(node.get("transform").split()[9]) for node in items]
            self.assertEqual(sorted(set(offsets)), offsets)

    def test_assembled_parts_share_a_plate_and_separate_parts_do_not(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            fixture.add_part("Widget/Base", intent=_intent(print_as="assembled"))
            fixture.add_part("Widget/Lid", intent=_intent(print_as="assembled"))
            fixture.add_part("Widget/Spacer", intent=_intent(print_as="separate"))
            fixture.add_part("Widget/Washer", intent=_intent(print_as="separate"))
            result = build_project(fixture.write_index(), root / "p.3mf", _presets(_config_root(root)))
            self.assertEqual(
                [
                    {"plate": 1, "part_paths": ["Widget/Base", "Widget/Lid"]},
                    {"plate": 2, "part_paths": ["Widget/Spacer"]},
                    {"plate": 3, "part_paths": ["Widget/Washer"]},
                ],
                result["plates"],
            )
            plate_by_path = {obj["part_path"]: obj["plate"] for obj in result["objects"]}
            self.assertEqual(plate_by_path["Widget/Base"], plate_by_path["Widget/Lid"])
            self.assertNotEqual(plate_by_path["Widget/Spacer"], plate_by_path["Widget/Washer"])

    def test_identical_inputs_produce_byte_identical_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            fixture.add_part("Widget/Bracket", intent=_intent(quantity=2))
            fixture.add_part("Widget/Cover", intent=_intent(print_as="assembled"))
            index = fixture.write_index()
            presets = _presets(_config_root(root))
            first = build_project(index, root / "first.3mf", presets)
            second = build_project(index, root / "second.3mf", presets)
            self.assertEqual((root / "first.3mf").read_bytes(), (root / "second.3mf").read_bytes())
            self.assertEqual(first["project_sha256"], second["project_sha256"])
            self.assertEqual(
                hashlib.sha256((root / "first.3mf").read_bytes()).hexdigest(), first["project_sha256"]
            )
            self.assertEqual((root / "first.3mf").stat().st_size, first["project_byte_size"])
            self.assertEqual(hashlib.sha256(index.read_bytes()).hexdigest(), first["export_index_sha256"])

    def test_existing_output_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            fixture.add_part("Widget/Bracket")
            output = root / "p.3mf"
            output.write_bytes(b"prior")
            with self.assertRaisesRegex(ValueError, "Refusing to overwrite"):
                build_project(fixture.write_index(), output, _presets(_config_root(root)))
            self.assertEqual(b"prior", output.read_bytes())

    def test_only_preset_identifiers_reach_the_project_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            fixture.add_part("Widget/Bracket")
            output = root / "p.3mf"
            build_project(fixture.write_index(), output, _presets(_config_root(root)))
            entries = _entries(output)
            config_text = entries[prusaslicer_project.CONFIG_ENTRY]
            self.assertIn("; printer_settings_id = Original Prusa XL - 5T", config_text)
            self.assertIn('; filament_settings_id = "Overture PETG @XL HF0.4 - Black"', config_text)
            self.assertIn("; print_settings_id = 0.40 SPEED @XLIS HF0.6 mixed", config_text)
            # Nothing from the user's actual profiles is copied anywhere.
            for name, text in entries.items():
                for leaked in ("layer_height", "nozzle_diameter", "bed_shape", "filament_diameter", "temperature"):
                    self.assertNotIn(leaked, text, f"{leaked} leaked into {name}")

    def test_declared_overrides_land_as_object_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            fixture.add_part(
                "Widget/Bracket",
                intent=_intent(
                    support_policy="build-plate-only",
                    strength={"min_perimeters": 4, "infill_percent": {"target": 35}},
                ),
            )
            output = root / "p.3mf"
            result = build_project(fixture.write_index(), output, _presets(_config_root(root)))
            self.assertEqual(
                {
                    "support_material": "1",
                    "support_material_buildplate_only": "1",
                    "perimeters": "4",
                    "fill_density": "35%",
                },
                result["objects"][0]["overrides"],
            )
            config_xml = ET.fromstring(_entries(output)[prusaslicer_project.MODEL_CONFIG_ENTRY])
            metadata = {
                node.get("key"): node.get("value")
                for node in config_xml.iter("metadata")
                if node.get("type") == "object"
            }
            self.assertEqual("35%", metadata["fill_density"])
            self.assertEqual("4", metadata["perimeters"])
            self.assertEqual("1", metadata["support_material_buildplate_only"])

    def test_volume_spans_the_object_triangles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            fixture.add_part("Widget/Bracket")
            output = root / "p.3mf"
            build_project(fixture.write_index(), output, _presets(_config_root(root)))
            config_xml = ET.fromstring(_entries(output)[prusaslicer_project.MODEL_CONFIG_ENTRY])
            volume = next(config_xml.iter("volume"))
            self.assertEqual("0", volume.get("firstid"))
            self.assertEqual(str(len(TRIANGLES) - 1), volume.get("lastid"))

    def test_unusable_source_3mf_fails_closed(self) -> None:
        cases = {
            "not a readable zip package": b"definitely not a zip",
            "only 'millimeter' is supported": _source_3mf_bytes(unit="inch"),
            "non-identity build transform": _source_3mf_bytes(transform="0 1 0 -1 0 0 0 0 1 5 5 0"),
            "carries no mesh geometry": _source_3mf_bytes(vertices=VERTICES, triangles=[]),
            "outside its own mesh": _source_3mf_bytes(triangles=[(0, 1, 99)]),
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = _config_root(root)
            for index_name, (message, payload) in enumerate(cases.items()):
                with self.subTest(message=message):
                    case = root / f"case{index_name}"
                    fixture = _Fixture(case)
                    fixture.add_part("Widget/Bracket", payload=payload)
                    with self.assertRaisesRegex(ValueError, message):
                        build_project(fixture.write_index(), case / "p.3mf", _presets(config))


class NoSlicerExecutionTests(unittest.TestCase):
    def test_module_contains_no_process_execution_api(self) -> None:
        source = Path(prusaslicer_project.__file__).read_text(encoding="utf-8")
        for token in ("subprocess", "os.system", "Popen", "os.exec", "os.spawn", "pty.spawn", "commands.getoutput"):
            self.assertNotIn(token, source, f"{token} must never appear in the PrusaSlicer project adapter")


if __name__ == "__main__":
    unittest.main()
