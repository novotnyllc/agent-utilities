from __future__ import annotations

import ast
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET
import zipfile

from fusion_design import prusaslicer_project
from fusion_design.manifest import Manifest
from fusion_design.printable_parts import CONTACT_FACES, SUPPORT_POLICIES
from fusion_design.prusaslicer_project import (
    ResolvedPresets,
    build_project,
    overrides_for_intent,
    printer_geometry,
    resolve_presets,
    rotation_for_contact_face,
    validate_overrides,
)
from fusion_design.scripts import manifest_sha256


# Modules whose whole point is starting or controlling another process. Import is
# banned outright, so an alias (`import subprocess as sp`) cannot hide the use.
BANNED_MODULES = frozenset({"subprocess", "multiprocessing", "ctypes", "pty", "webbrowser", "commands"})
# Attribute/name references that launch a process regardless of how the module
# they came from was named.
BANNED_CALLS = frozenset(
    {
        "system", "popen", "startfile", "fork", "forkpty", "Popen",
        "execl", "execle", "execlp", "execlpe", "execv", "execve", "execvp", "execvpe",
        "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe",
        "posix_spawn", "posix_spawnp", "getoutput", "getstatusoutput",
    }
)


def process_execution_offenses(source: str) -> list[str]:
    """Names in ``source`` that could start a process, found structurally not textually."""
    offenses: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            offenses += [alias.name for alias in node.names if alias.name.split(".")[0] in BANNED_MODULES]
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in BANNED_MODULES:
                offenses.append(node.module or "")
            offenses += [alias.name for alias in node.names if alias.name in BANNED_CALLS]
        elif isinstance(node, ast.Attribute) and node.attr in BANNED_CALLS:
            offenses.append(node.attr)
        elif isinstance(node, ast.Name) and node.id in BANNED_CALLS:
            offenses.append(node.id)
    return sorted(set(offenses))


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


def _source_3mf_bytes(
    vertices=VERTICES,
    triangles=TRIANGLES,
    unit: str = "millimeter",
    transform: str | None = None,
    vertex_xml: list[str] | None = None,
    triangle_xml: list[str] | None = None,
) -> bytes:
    """Build a source 3MF. ``vertex_xml``/``triangle_xml`` inject raw malformed elements."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<model unit="{unit}" xmlns="{prusaslicer_project.CORE_NAMESPACE}">',
        " <resources>",
        '  <object id="1" type="model">',
        "   <mesh>",
        "    <vertices>",
    ]
    lines.extend(
        vertex_xml
        if vertex_xml is not None
        else [f'     <vertex x="{vertex[0]}" y="{vertex[1]}" z="{vertex[2]}"/>' for vertex in vertices]
    )
    lines.append("    </vertices>")
    lines.append("    <triangles>")
    lines.extend(
        triangle_xml
        if triangle_xml is not None
        else [f'     <triangle v1="{tri[0]}" v2="{tri[1]}" v3="{tri[2]}"/>' for tri in triangles]
    )
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

    def manifest(self) -> Manifest:
        """A manifest declaring exactly the parts this handoff carries, with their intent.

        The index is a transcript of the manifest, so the manifest has to declare
        the same manufacturing intent the index carries -- that agreement is what
        build_project now checks.
        """
        declared = {}
        for artifact in self.artifacts:
            if "manufacturing_intent" in artifact:
                declared[artifact["part_path"]] = artifact["manufacturing_intent"]
            else:
                declared.setdefault(artifact["part_path"], _intent())
        return Manifest(
            {
                "project": {"name": "Widget"},
                "printable_parts": [
                    {"path": path, **declared[path]} for path in sorted(declared)
                ],
            }
        )

    def write_index(self, name: str = "export-index.json", manifest: Manifest | None = None, **overrides) -> Path:
        index = {
            "kind": "export-handoff",
            "ok": True,
            "project": "Widget",
            "manifest_sha256": manifest_sha256(manifest if manifest is not None else self.manifest()),
            "verification_report_sha256": "a" * 64,
            "export_run_id": "0123456789abcdef0123456789abcdef",
            "artifacts": self.artifacts,
        }
        index.update(overrides)
        path = self.export_dir / name
        path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def build(self, index, output, presets, manifest: Manifest | None = None) -> dict:
        return build_project(manifest if manifest is not None else self.manifest(), index, output, presets)


# Synthetic printer profile: a 200 x 180 mm bed, 150 mm tall build volume.
PRINTER_INI = "bed_shape = 0x0,200x0,200x180,0x180\nmax_print_height = 150\n"

# Synthetic vendor bundle in the real PrusaResearch.ini shape: an abstract
# *common* parent carrying model/variant/bed fields, concrete presets
# inheriting from it, and one preset for a model the wizard did not install.
VENDOR_BUNDLE = """\
[printer:*common*]
printer_model = COREONE
printer_variant = HF0.4
bed_shape = 0x0,250x0,250x220,0x220
max_print_height = 270

[printer:Prusa CORE One HF0.4 nozzle]
inherits = *common*

[printer:Prusa CORE One HF0.6 nozzle]
inherits = *common*
printer_variant = HF0.6

[printer:Prusa MINI]
printer_model = MINI
printer_variant = 0.4
bed_shape = 0x0,180x0,180x180,0x180
"""


def _config_root(
    root: Path,
    selected: dict[str, str] | None = None,
    user_presets: dict[str, list[str]] | None = None,
    printer_ini: str = PRINTER_INI,
    vendor_models: str | None = None,
    vendor_bundle: str | None = None,
) -> Path:
    config = root / "PrusaSlicer"
    user_presets = user_presets if user_presets is not None else {
        "printer": ["Original Prusa XL - 5T"],
        "filament": ["Overture PETG @XL HF0.4 - Black"],
        "print": ["0.40 SPEED @XLIS HF0.6 mixed"],
    }
    for kind, names in user_presets.items():
        directory = config / kind
        directory.mkdir(parents=True, exist_ok=True)
        content = printer_ini if kind == "printer" else "layer_height = 0.2\n"
        for preset_name in names:
            (directory / f"{preset_name}.ini").write_text(content, encoding="utf-8")
    config.mkdir(parents=True, exist_ok=True)
    selected = selected if selected is not None else {
        "printer": "Original Prusa XL - 5T",
        "filament": "Overture PETG @XL HF0.4 - Black",
        "print": "0.40 SPEED @XLIS HF0.6 mixed",
    }
    lines = ["[presets]"] + [f"{kind} = {name}" for kind, name in sorted(selected.items())]
    if vendor_models is not None:
        lines += ["[vendor:PrusaResearch]", vendor_models]
    (config / "PrusaSlicer.ini").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if vendor_bundle is not None:
        (config / "vendor").mkdir(exist_ok=True)
        (config / "vendor" / "PrusaResearch.ini").write_text(vendor_bundle, encoding="utf-8")
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


class VertexFormattingTests(unittest.TestCase):
    def test_negative_magnitudes_that_round_to_zero_emit_plain_zero(self) -> None:
        # The zero collapse used to test the input, so any negative below 5e-7
        # printed as "-0" -- different bytes for indistinguishable coordinates.
        for value in (-0.0, -1e-9, -4.9e-7, -0.0000004):
            with self.subTest(value=value):
                self.assertEqual("0", prusaslicer_project._fmt(value))
        self.assertEqual("0", prusaslicer_project._fmt(0.0))
        self.assertEqual("-0.000001", prusaslicer_project._fmt(-1e-6))

    def test_vertices_are_quantized_to_six_decimals_as_documented(self) -> None:
        self.assertEqual("1.234568", prusaslicer_project._fmt(1.23456789))
        self.assertEqual("0.0005", prusaslicer_project._fmt(0.0005000004))
        docstring = prusaslicer_project.__doc__ or ""
        self.assertIn("re-emitted from the Fusion-exported 3MF", docstring)
        self.assertIn("quantized", docstring)
        self.assertNotIn("copied verbatim", docstring)
        self.assertNotIn("geometry is never rewritten", docstring)


class OverrideTests(unittest.TestCase):
    def test_every_support_policy_maps_to_justified_keys(self) -> None:
        expected = {
            "none": {"support_material": "0"},
            "build-plate-only": {"support_material": "1", "support_material_buildplate_only": "1"},
            "everywhere": {"support_material": "1", "support_material_buildplate_only": "0"},
        }
        # explicit-regions is a declared policy with no translation; it is rejected, not mapped.
        self.assertEqual(SUPPORT_POLICIES, set(expected) | {"explicit-regions"})
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

    def test_explicit_regions_is_rejected_rather_than_collapsed_to_everywhere(self) -> None:
        with self.assertRaisesRegex(ValueError, "per-region support painting"):
            overrides_for_intent(_intent(support_policy="explicit-regions"), "Widget/Part")
        self.assertNotIn("explicit-regions", prusaslicer_project.SUPPORT_POLICY_OVERRIDES)

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

    def test_multi_tool_fallback_picks_extruder_zero_not_alphabetical_first(self) -> None:
        # A 5-tool Prusa XL records filament for extruder 0 and filament_N for the rest.
        with tempfile.TemporaryDirectory() as temporary:
            config = _config_root(
                Path(temporary),
                selected={
                    "printer": "Original Prusa XL - 5T",
                    "filament": "Prusament PLA",
                    "filament_1": "Generic ABS",
                    "filament_2": "Overture PETG @XL HF0.4 - Black",
                    "print": "0.40 SPEED @XLIS HF0.6 mixed",
                },
            )
            presets = resolve_presets({}, config)
            self.assertEqual("Prusament PLA", presets.filament)
            # The other extruders still count as installed and may be requested by name.
            self.assertEqual("Generic ABS", resolve_presets({"filament": "Generic ABS"}, config).filament)

    def test_blank_requested_name_falls_back_to_the_selected_preset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = _config_root(Path(temporary))
            presets = resolve_presets({"filament": "   ", "printer": None}, config)
            self.assertEqual("Overture PETG @XL HF0.4 - Black", presets.filament)
            self.assertEqual("Original Prusa XL - 5T", presets.printer)

    def test_preset_name_with_newline_or_quote_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = _config_root(root)
            for injected in ('Evil\nfilament_settings_id = "Other"', "Evil\rPreset", 'Evil"Preset'):
                with self.subTest(injected=injected):
                    with self.assertRaisesRegex(ValueError, "newline, carriage return, or double quote"):
                        resolve_presets({"filament": injected}, config)
            # A quote can also arrive from the ini's own selection, which is the fallback path.
            quoted = _config_root(
                root / "quoted",
                selected={
                    "printer": "Original Prusa XL - 5T",
                    "filament": 'Evil"Preset',
                    "print": "0.40 SPEED @XLIS HF0.6 mixed",
                },
                user_presets={"printer": ["Original Prusa XL - 5T"], "print": ["0.40 SPEED @XLIS HF0.6 mixed"]},
            )
            with self.assertRaisesRegex(ValueError, "newline, carriage return, or double quote"):
                resolve_presets({}, quoted)

    def test_windows_default_config_root_uses_appdata(self) -> None:
        with mock.patch.object(prusaslicer_project.sys, "platform", "win32"):
            with mock.patch.dict(prusaslicer_project.os.environ, {"APPDATA": r"C:\Users\claire\AppData\Roaming"}):
                self.assertEqual(
                    Path(r"C:\Users\claire\AppData\Roaming") / "PrusaSlicer",
                    prusaslicer_project.default_config_root(),
                )
        with mock.patch.object(prusaslicer_project.sys, "platform", "linux"):
            self.assertEqual(Path.home() / ".config" / "PrusaSlicer", prusaslicer_project.default_config_root())


class VendorPresetTests(unittest.TestCase):
    """Printer presets installed via a vendor bundle's wizard selection."""

    def _vendor_config(self, root: Path, models: str = "model:COREONE = HF0.4") -> Path:
        return _config_root(root, vendor_models=models, vendor_bundle=VENDOR_BUNDLE)

    def test_vendor_preset_with_installed_model_resolves_even_when_not_selected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = self._vendor_config(Path(temporary))
            self.assertFalse((config / "printer" / "Prusa CORE One HF0.4 nozzle.ini").exists())
            presets = resolve_presets({"printer": "Prusa CORE One HF0.4 nozzle"}, config)
            self.assertEqual("Prusa CORE One HF0.4 nozzle", presets.printer)

    def test_vendor_preset_whose_model_is_not_installed_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = self._vendor_config(Path(temporary))
            with self.assertRaisesRegex(ValueError, "'Prusa MINI' is not installed"):
                resolve_presets({"printer": "Prusa MINI"}, config)

    def test_vendor_preset_whose_variant_is_not_installed_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = self._vendor_config(Path(temporary))
            with self.assertRaisesRegex(ValueError, "'Prusa CORE One HF0.6 nozzle' is not installed"):
                resolve_presets({"printer": "Prusa CORE One HF0.6 nozzle"}, config)
            both = self._vendor_config(Path(temporary) / "both", models="model:COREONE = HF0.4;HF0.6")
            resolved = resolve_presets({"printer": "Prusa CORE One HF0.6 nozzle"}, both)
            self.assertEqual("Prusa CORE One HF0.6 nozzle", resolved.printer)

    def test_abstract_star_sections_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = self._vendor_config(Path(temporary))
            with self.assertRaisesRegex(ValueError, "is not installed"):
                resolve_presets({"printer": "*common*"}, config)

    def test_malformed_vendor_bundle_degrades_to_the_two_original_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = _config_root(Path(temporary), vendor_models="model:COREONE = HF0.4")
            # The bundle is a directory, so reading it raises OSError.
            (config / "vendor" / "PrusaResearch.ini").mkdir(parents=True)
            presets = resolve_presets({}, config)
            self.assertEqual("Original Prusa XL - 5T", presets.printer)
            with self.assertRaisesRegex(ValueError, "is not installed"):
                resolve_presets({"printer": "Prusa CORE One HF0.4 nozzle"}, config)


class PrinterGeometryTests(unittest.TestCase):
    def test_bed_shape_resolves_from_the_user_printer_ini(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = _config_root(Path(temporary))
            geometry = printer_geometry("Original Prusa XL - 5T", config)
            self.assertEqual(200.0, geometry["bed_width_mm"])
            self.assertEqual(180.0, geometry["bed_depth_mm"])
            self.assertEqual(150.0, geometry["max_print_height_mm"])

    def test_bed_shape_resolves_through_the_vendor_bundle_inherits_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            # The concrete section carries no bed_shape of its own; it comes
            # from the abstract *common* parent via inherits.
            config = _config_root(
                Path(temporary), vendor_models="model:COREONE = HF0.4", vendor_bundle=VENDOR_BUNDLE
            )
            geometry = printer_geometry("Prusa CORE One HF0.4 nozzle", config)
            self.assertEqual("0x0,250x0,250x220,0x220", geometry["bed_shape"])
            self.assertEqual(250.0, geometry["bed_width_mm"])
            self.assertEqual(220.0, geometry["bed_depth_mm"])
            self.assertEqual(270.0, geometry["max_print_height_mm"])

    def test_missing_bed_shape_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = _config_root(Path(temporary), printer_ini="layer_height = 0.2\n")
            with self.assertRaisesRegex(ValueError, "refusing to lay out a project on an assumed bed"):
                printer_geometry("Original Prusa XL - 5T", config)

    def test_unparseable_bed_shape_or_max_print_height_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            garbled = _config_root(root / "a", printer_ini="bed_shape = round-ish\n")
            with self.assertRaisesRegex(ValueError, "is not a\\s+comma-separated list|not a comma-separated"):
                printer_geometry("Original Prusa XL - 5T", garbled)
            bad_height = _config_root(
                root / "b", printer_ini="bed_shape = 0x0,200x0,200x180,0x180\nmax_print_height = tall\n"
            )
            with self.assertRaisesRegex(ValueError, "expected a positive number"):
                printer_geometry("Original Prusa XL - 5T", bad_height)

    def test_absent_max_print_height_skips_the_height_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = _config_root(Path(temporary), printer_ini="bed_shape = 0x0,200x0,200x180,0x180\n")
            self.assertIsNone(printer_geometry("Original Prusa XL - 5T", config)["max_print_height_mm"])

    def test_declared_but_empty_max_print_height_fails_closed(self) -> None:
        # An empty value must not silently disable the height check.
        with tempfile.TemporaryDirectory() as temporary:
            config = _config_root(
                Path(temporary), printer_ini="bed_shape = 0x0,200x0,200x180,0x180\nmax_print_height =\n"
            )
            with self.assertRaisesRegex(ValueError, "expected a positive number"):
                printer_geometry("Original Prusa XL - 5T", config)

    def test_vendor_bundles_resolve_in_separate_namespaces(self) -> None:
        # Two vendors both define *common*; AlphaVendor's printer must never
        # inherit BetaVendor's bed even though "BetaVendor" sorts later and a
        # flattened section map would let it overwrite the abstract parent.
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "PrusaSlicer"
            (config / "vendor").mkdir(parents=True)
            (config / "PrusaSlicer.ini").write_text(
                "[presets]\nprinter = Alpha One\n"
                "[vendor:AlphaVendor]\nmodel:A1 = 0.4\n"
                "[vendor:BetaVendor]\nmodel:B1 = 0.4\n",
                encoding="utf-8",
            )
            (config / "vendor" / "AlphaVendor.ini").write_text(
                "[printer:*common*]\nbed_shape = 0x0,100x0,100x90,0x90\nmax_print_height = 80\n"
                "[printer:Alpha One]\ninherits = *common*\nprinter_model = A1\nprinter_variant = 0.4\n",
                encoding="utf-8",
            )
            (config / "vendor" / "BetaVendor.ini").write_text(
                "[printer:*common*]\nbed_shape = 0x0,999x0,999x999,0x999\nmax_print_height = 999\n"
                "[printer:Beta One]\ninherits = *common*\nprinter_model = B1\nprinter_variant = 0.4\n",
                encoding="utf-8",
            )
            geometry = printer_geometry("Alpha One", config)
            self.assertEqual(100.0, geometry["bed_width_mm"])
            self.assertEqual(90.0, geometry["bed_depth_mm"])
            self.assertEqual(80.0, geometry["max_print_height_mm"])


class BedPlacementTests(unittest.TestCase):
    """Deterministic placement within the resolved bed, fail-closed on overflow."""

    def _build(self, root: Path, fixture: _Fixture, printer_ini: str) -> dict:
        config = _config_root(root, printer_ini=printer_ini)
        return fixture.build(fixture.write_index(), root / "p.3mf", _presets(config))

    def test_placement_stays_within_a_small_synthetic_bed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            # Footprint is 10 x 20 per instance; a 30 mm wide bed forces row wrapping.
            fixture.add_part("Widget/Bracket", intent=_intent(quantity=3, print_as="assembled"))
            result = self._build(root, fixture, "bed_shape = 0x0,30x0,30x100,0x100\n")
            geometry = result["printer_geometry"]
            self.assertEqual(30.0, geometry["bed_width_mm"])
            placements = result["objects"][0]["translations_mm"]
            self.assertEqual(3, len(placements))
            xs = {translation[0] for translation in placements}
            ys = {translation[1] for translation in placements}
            self.assertGreater(len(ys), 1, "expected the third instance to wrap to a new row")
            for x, y, z in placements:
                self.assertGreaterEqual(x, 0.0)
                self.assertLessEqual(x + 10.0, 30.0)
                self.assertGreaterEqual(y, 0.0)
                self.assertLessEqual(y + 20.0, 100.0)
                self.assertEqual(0.0, z)

    def test_oversized_part_fails_closed_naming_part_and_bed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            fixture.add_part("Widget/Bracket")
            with self.assertRaisesRegex(
                ValueError, r"'Widget/Bracket' has a rotated footprint of 10 x 20 mm.*5 x 5 mm bed"
            ):
                self._build(root, fixture, "bed_shape = 0x0,5x0,5x5,0x5\n")

    def test_assembled_group_that_cannot_share_a_plate_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            # Each 10 x 20 part fits a 15 x 25 bed alone, but not both on one plate.
            fixture.add_part("Widget/Base", intent=_intent(print_as="assembled"))
            fixture.add_part("Widget/Lid", intent=_intent(print_as="assembled"))
            with self.assertRaisesRegex(
                ValueError, r"Plate 1 cannot fit all its parts on the 15 x 25 mm bed.*'Widget/Lid'"
            ):
                self._build(root, fixture, "bed_shape = 0x0,15x0,15x25,0x25\n")

    def test_part_taller_than_max_print_height_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            fixture.add_part("Widget/Bracket")  # 30 mm tall as oriented
            with self.assertRaisesRegex(ValueError, r"30 mm tall as oriented.*25 mm maximum print height"):
                self._build(root, fixture, "bed_shape = 0x0,200x0,200x180,0x180\nmax_print_height = 25\n")

    def test_result_records_the_resolved_bed_geometry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            fixture.add_part("Widget/Bracket")
            result = self._build(root, fixture, PRINTER_INI)
            self.assertEqual(
                {
                    "printer": "Original Prusa XL - 5T",
                    "bed_shape": "0x0,200x0,200x180,0x180",
                    "bed_min_x_mm": 0.0,
                    "bed_min_y_mm": 0.0,
                    "bed_width_mm": 200.0,
                    "bed_depth_mm": 180.0,
                    "max_print_height_mm": 150.0,
                },
                result["printer_geometry"],
            )

    def test_process_free_geometry_override_is_the_layout_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            fixture.add_part("Widget/Bracket")
            config = _config_root(root, printer_ini="bed_shape = 0x0,5x0,5x5,0x5\n")
            presets = _presets(config)
            override = {
                "printer": presets.printer,
                "bed_min_x_mm": 2,
                "bed_min_y_mm": 3,
                "bed_width_mm": 20,
                "bed_depth_mm": 30,
                "max_print_height_mm": 40,
            }
            result = build_project(
                fixture.manifest(), fixture.write_index(), root / "p.3mf", presets, geometry_override=override
            )
            self.assertEqual(20.0, result["printer_geometry"]["bed_width_mm"])
            self.assertEqual(30.0, result["printer_geometry"]["bed_depth_mm"])
            self.assertEqual(2.0, result["printer_geometry"]["bed_min_x_mm"])
            self.assertEqual(3.0, result["printer_geometry"]["bed_min_y_mm"])


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

            result = fixture.build(index, output, _presets(config))

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
            result = fixture.build(fixture.write_index(), root / "p.3mf", _presets(_config_root(root)))
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
                fixture.build(fixture.write_index(), root / "p.3mf", _presets(_config_root(root)))

    def test_byte_size_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            artifact = fixture.add_part("Widget/Bracket")
            artifact["byte_size"] = artifact["byte_size"] + 1
            with self.assertRaisesRegex(ValueError, "the index records"):
                fixture.build(fixture.write_index(), root / "p.3mf", _presets(_config_root(root)))

    def test_missing_artifact_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            artifact = fixture.add_part("Widget/Bracket")
            (fixture.export_dir / artifact["filename"]).unlink()
            with self.assertRaisesRegex(ValueError, "which is not a file"):
                fixture.build(fixture.write_index(), root / "p.3mf", _presets(_config_root(root)))

    def test_index_without_manufacturing_intent_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            artifact = fixture.add_part("Widget/Bracket")
            del artifact["manufacturing_intent"]
            with self.assertRaisesRegex(ValueError, "carries no manufacturing_intent"):
                fixture.build(fixture.write_index(), root / "p.3mf", _presets(_config_root(root)))

    def test_non_ok_or_wrong_kind_index_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            fixture.add_part("Widget/Bracket")
            presets = _presets(_config_root(root))
            with self.assertRaisesRegex(ValueError, "not ok: true"):
                fixture.build(fixture.write_index("a.json", ok=False), root / "a.3mf", presets)
            with self.assertRaisesRegex(ValueError, "expected 'export-handoff'"):
                fixture.build(fixture.write_index("b.json", kind="verification"), root / "b.3mf", presets)
            with self.assertRaisesRegex(ValueError, "is not a file"):
                fixture.build(root / "absent.json", root / "c.3mf", presets)

    def test_traversal_filename_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            artifact = fixture.add_part("Widget/Bracket")
            artifact["filename"] = f"../{artifact['filename']}"
            with self.assertRaisesRegex(ValueError, "must be a bare filename"):
                fixture.build(fixture.write_index(), root / "p.3mf", _presets(_config_root(root)))

    def test_literal_dot_filenames_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index_name, filename in enumerate((".", "..")):
                with self.subTest(filename=filename):
                    case = root / f"dot{index_name}"
                    fixture = _Fixture(case)
                    artifact = fixture.add_part("Widget/Bracket")
                    artifact["filename"] = filename
                    with self.assertRaisesRegex(ValueError, "must be a bare filename"):
                        fixture.build(fixture.write_index(), case / "p.3mf", _presets(_config_root(root)))

    def test_two_3mf_artifacts_for_one_part_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            fixture.add_part("Widget/Bracket")
            duplicate = dict(fixture.artifacts[0])
            duplicate["filename"] = "duplicate.3mf"
            (fixture.export_dir / "duplicate.3mf").write_bytes(_source_3mf_bytes())
            fixture.artifacts.append(duplicate)
            with self.assertRaisesRegex(ValueError, "more than one 3MF artifact"):
                fixture.build(fixture.write_index(), root / "p.3mf", _presets(_config_root(root)))

    def test_index_bound_to_a_different_manifest_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            fixture.add_part("Widget/Bracket")
            other = Manifest({"project": {"name": "Other"}, "printable_parts": [{"path": "Widget/Bracket"}]})
            output = root / "p.3mf"
            with self.assertRaisesRegex(ValueError, "does not match manifest"):
                fixture.build(fixture.write_index(), output, _presets(_config_root(root)), manifest=other)
            self.assertFalse(output.exists())

    def test_index_missing_manifest_sha256_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            fixture.add_part("Widget/Bracket")
            index = fixture.write_index()
            payload = json.loads(index.read_text(encoding="utf-8"))
            payload.pop("manifest_sha256")
            index.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not match manifest"):
                fixture.build(index, root / "p.3mf", _presets(_config_root(root)))

    def test_part_not_declared_by_the_manifest_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            fixture.add_part("Widget/Bracket")
            fixture.add_part("Widget/Stowaway")
            declared = Manifest(
                {"project": {"name": "Widget"}, "printable_parts": [{"path": "Widget/Bracket"}]}
            )
            index = fixture.write_index(manifest=declared)
            output = root / "p.3mf"
            with self.assertRaisesRegex(ValueError, "does not declare as printable: Widget/Stowaway"):
                fixture.build(index, output, _presets(_config_root(root)), manifest=declared)
            self.assertFalse(output.exists())

    def test_failed_write_leaves_no_file_behind(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            fixture.add_part("Widget/Bracket")
            index = fixture.write_index()
            presets = _presets(_config_root(root))
            output = root / "p.3mf"
            # Write fails after open("xb") has already created the file.
            with mock.patch.object(prusaslicer_project, "_deterministic_zip", return_value="not bytes"):
                with self.assertRaises(TypeError):
                    fixture.build(index, output, presets)
            self.assertFalse(output.exists())
            # The retry is not blocked by a leftover partial file.
            self.assertTrue(fixture.build(index, output, presets)["ok"])

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
                    result = fixture.build(
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
            result = fixture.build(fixture.write_index(), output, _presets(_config_root(root)))
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
            result = fixture.build(fixture.write_index(), root / "p.3mf", _presets(_config_root(root)))
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
            first = fixture.build(index, root / "first.3mf", presets)
            second = fixture.build(index, root / "second.3mf", presets)
            self.assertEqual((root / "first.3mf").read_bytes(), (root / "second.3mf").read_bytes())
            self.assertEqual(first["project_sha256"], second["project_sha256"])
            self.assertEqual(
                hashlib.sha256((root / "first.3mf").read_bytes()).hexdigest(), first["project_sha256"]
            )
            self.assertEqual((root / "first.3mf").stat().st_size, first["project_byte_size"])
            # Nothing is deflated, so project_sha256 does not depend on the host's zlib build.
            with zipfile.ZipFile(root / "first.3mf") as archive:
                self.assertEqual(
                    {zipfile.ZIP_STORED}, {info.compress_type for info in archive.infolist()}
                )
            self.assertEqual(hashlib.sha256(index.read_bytes()).hexdigest(), first["export_index_sha256"])

    def test_existing_output_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            fixture.add_part("Widget/Bracket")
            output = root / "p.3mf"
            output.write_bytes(b"prior")
            with self.assertRaisesRegex(ValueError, "Refusing to overwrite"):
                fixture.build(fixture.write_index(), output, _presets(_config_root(root)))
            self.assertEqual(b"prior", output.read_bytes())

    def test_only_preset_identifiers_reach_the_project_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = _Fixture(root)
            fixture.add_part("Widget/Bracket")
            output = root / "p.3mf"
            fixture.build(fixture.write_index(), output, _presets(_config_root(root)))
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
            result = fixture.build(fixture.write_index(), output, _presets(_config_root(root)))
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
            fixture.build(fixture.write_index(), output, _presets(_config_root(root)))
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
            "non-finite x='NaN'": _source_3mf_bytes(vertices=[("NaN", 0.0, 0.0)] + VERTICES[1:]),
            "non-finite z='inf'": _source_3mf_bytes(vertices=VERTICES[:3] + [(0.0, 0.0, "inf")]),
            "non-numeric y='left'": _source_3mf_bytes(vertices=[(0.0, "left", 0.0)] + VERTICES[1:]),
            "vertex with no x coordinate": _source_3mf_bytes(
                vertex_xml=['<vertex y="0" z="0"/>'] + [f'<vertex x="{v[0]}" y="{v[1]}" z="{v[2]}"/>' for v in VERTICES[1:]]
            ),
            "triangle with no v3 vertex index": _source_3mf_bytes(triangle_xml=['<triangle v1="0" v2="1"/>']),
            "non-integer v2='two'": _source_3mf_bytes(triangle_xml=['<triangle v1="0" v2="two" v3="1"/>']),
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
                        fixture.build(fixture.write_index(), case / "p.3mf", _presets(config))


class NoSlicerExecutionTests(unittest.TestCase):
    def test_module_contains_no_process_execution_api(self) -> None:
        source = Path(prusaslicer_project.__file__).read_text(encoding="utf-8")
        self.assertEqual([], process_execution_offenses(source))

    def test_guard_catches_aliased_and_indirect_process_execution(self) -> None:
        cases = {
            "import subprocess as sp\nsp.run(['x'])\n": "subprocess",
            "import os\nos.posix_spawn('x', [], {})\n": "posix_spawn",
            "import os\nos.fork()\n": "fork",
            "import ctypes\n": "ctypes",
            "import multiprocessing\n": "multiprocessing",
            "import webbrowser\nwebbrowser.open('x')\n": "webbrowser",
            "from os import system\nsystem('x')\n": "system",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertIn(expected, process_execution_offenses(source))
        # os.environ and other harmless os use must not trip the guard.
        self.assertEqual([], process_execution_offenses("import os\nos.environ.get('APPDATA')\n"))


if __name__ == "__main__":
    unittest.main()
