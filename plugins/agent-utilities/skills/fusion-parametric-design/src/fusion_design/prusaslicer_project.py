"""Build a PrusaSlicer project ``.3mf`` from a verified export-handoff index.

The project is constructed as a file. This module never launches the slicer and
deliberately contains no process-launching API at all -- everything here is
filesystem reads plus ``zipfile``/``ElementTree`` writes, and a test enforces
that structurally. Slicing is real and supported, but it lives in
``prusaslicer_slice`` so the no-execution guarantee for project construction
stays a file boundary rather than a promise.

Layout conventions worth knowing before reading the code:

* Mesh vertices are re-emitted from the Fusion-exported 3MF at six-decimal fixed
  precision (see ``_fmt``): the coordinates are not transformed, but they are
  quantized, so ``project_sha256`` attests to this re-serialization rather than to
  the exported bytes. Build orientation and plate placement are expressed as the
  object's build-item transform matrix (standard 3MF placement, honored by every
  reader), so no rotation is baked into the coordinates and the applied rotation
  stays auditable.
* Print settings come from the *manifest*. The index carries a transcript of the
  manifest's manufacturing intent, and every field of it is compared back against
  the manifest before anything is written -- an index that disagrees is refused,
  never applied.
* ``Metadata/Slic3r_PE.config`` carries preset *identifiers only*. The user's
  profile settings are never copied into our artifacts.
* PrusaSlicer has a single bed. "Plates" here are declared grouping, not a
  capacity check: plate members are laid out adjacently, plates are separated
  along Y, and nothing verifies that objects physically fit.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Any
from xml.sax.saxutils import escape
import xml.etree.ElementTree as ET
import zipfile

from .export_handoff import manufacturing_intent_by_path
from .manifest import Manifest
from .printable_parts import CONTACT_FACES, SUPPORT_POLICIES
from .scripts import manifest_sha256


_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")


MODEL_ENTRY = "3D/3dmodel.model"
CONFIG_ENTRY = "Metadata/Slic3r_PE.config"
MODEL_CONFIG_ENTRY = "Metadata/Slic3r_PE_model.config"
CORE_NAMESPACE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"

PRESET_KINDS = ("printer", "filament", "print")
PRESET_SETTINGS_KEYS = {
    "printer": "printer_settings_id",
    "filament": "filament_settings_id",
    "print": "print_settings_id",
}

ALLOWED_OVERRIDE_KEYS = (
    "fill_density",
    "perimeters",
    "support_material",
    "support_material_buildplate_only",
    "support_material_style",
)

# Every override below is traceable to a declared support_policy value; a policy
# outside this table has no justified translation and is rejected. 'explicit-regions'
# is deliberately absent: it declares support_regions this adapter cannot express,
# and honoring it as 'everywhere' would silently print a different policy.
SUPPORT_POLICY_OVERRIDES = {
    "none": {"support_material": "0"},
    "build-plate-only": {"support_material": "1", "support_material_buildplate_only": "1"},
    "everywhere": {"support_material": "1", "support_material_buildplate_only": "0"},
}

# contact_face names the face that must end up on the bed, so the rotation is
# the one that maps that face's outward normal onto -Z. All six are axis-aligned
# quarter turns, kept as exact integers so the emitted matrix has no float noise.
CONTACT_FACE_ROTATIONS = {
    "-Z": (None, 0),
    "+Z": ("X", 180),
    "-Y": ("X", 90),
    "+Y": ("X", -90),
    "-X": ("Y", -90),
    "+X": ("Y", 90),
}

OBJECT_GAP_MM = 10.0
PLATE_GAP_MM = 20.0

# A verified artifact is not hostile input, but an unbounded read still turns a
# corrupt export into an OOM instead of an error message.
MAX_MODEL_BYTES = 256 * 1024 * 1024
MAX_ARTIFACT_BYTES = MAX_MODEL_BYTES

_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

# The 'config' default is deliberately more than PrusaSlicer itself declares: a
# real PrusaSlicer-authored project lists only rels, model, and png, leaving its
# own .config parts without a content type even though OPC requires one for every
# part extension. PrusaSlicer reads those parts by name, so declaring it is
# harmless and standards-correct -- do not "fix" this back after diffing against a
# real project. (A thumbnail part, if ever added, would need a png default too.)
_CONTENT_TYPES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
 <Default Extension="config" ContentType="application/octet-stream"/>
</Types>
"""

_RELS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>
"""


@dataclass(frozen=True, slots=True)
class ResolvedPresets:
    """Preset identifiers resolved against the user's PrusaSlicer configuration."""

    printer: str
    filament: str
    print_settings: str
    config_root: str

    def as_dict(self) -> dict[str, str]:
        return {"printer": self.printer, "filament": self.filament, "print": self.print_settings}


# ---------------------------------------------------------------------------
# preset resolution (R5)
# ---------------------------------------------------------------------------


def default_config_root() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "PrusaSlicer"
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        return (Path(appdata) if appdata else Path.home() / "AppData" / "Roaming") / "PrusaSlicer"
    return Path.home() / ".config" / "PrusaSlicer"


def _selected_presets(config_root: Path) -> tuple[dict[str, set[str]], dict[str, str]]:
    """Preset names PrusaSlicer.ini records as selected, plus the primary of each kind.

    A selected preset may be a *system* preset with no user ``.ini`` on disk, so
    these names count as installed even when the directory scan misses them.

    On a multi-tool printer PrusaSlicer records ``filament`` for extruder 0 and
    ``filament_1``..``filament_N`` for the rest. The bare key is the primary
    selection and is the only one an unrequested kind may fall back to; the union
    exists solely to decide whether a name counts as installed.
    """
    selected: dict[str, set[str]] = {kind: set() for kind in PRESET_KINDS}
    primary: dict[str, str] = {}
    ini = config_root / "PrusaSlicer.ini"
    if not ini.is_file():
        return selected, primary
    section = ""
    for raw_line in ini.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().lower()
            continue
        if section != "presets" or "=" not in line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"')
        if not value:
            continue
        # filament_1, filament_2, ... are the extra extruders on a multi-tool printer.
        base = key.split("_")[0] if key.startswith("filament") else key
        if base in PRESET_KINDS:
            selected[base].add(value)
            if key == base:
                primary[base] = value
    return selected, primary


def _installed_presets(config_root: Path) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, str]]:
    selected, primary = _selected_presets(config_root)
    available: dict[str, set[str]] = {}
    for kind in PRESET_KINDS:
        directory = config_root / kind
        stems = {entry.stem for entry in directory.glob("*.ini")} if directory.is_dir() else set()
        available[kind] = stems | selected[kind]
    return available, selected, primary


def resolve_presets(
    requested: dict[str, str | None] | None = None,
    config_root: str | Path | None = None,
) -> ResolvedPresets:
    """Resolve printer/filament/print presets by identifier, fail-closed.

    Only names are resolved; the user's profile settings are never read or
    copied. An unrequested kind falls back to the preset PrusaSlicer.ini records
    as currently selected.
    """
    root = Path(config_root).expanduser() if config_root is not None else default_config_root()
    if not root.is_dir():
        raise ValueError(
            f"PrusaSlicer configuration root {str(root)!r} does not exist; "
            "presets cannot be resolved by identifier."
        )
    requested = requested or {}
    unknown_kinds = sorted(set(requested) - set(PRESET_KINDS))
    if unknown_kinds:
        raise ValueError(
            f"Unknown preset kinds: {', '.join(unknown_kinds)}; expected {', '.join(PRESET_KINDS)}."
        )
    available, selected, primary = _installed_presets(root)
    chosen: dict[str, str] = {}
    for kind in PRESET_KINDS:
        name = requested.get(kind)
        name = name.strip() if isinstance(name, str) else None
        if not name:
            # The bare key is extruder 0 / the active selection. Only when the ini
            # records no unsuffixed key at all does sorted order decide anything.
            name = primary.get(kind) or (sorted(selected[kind])[0] if selected[kind] else None)
            if not name:
                raise ValueError(
                    f"No {kind} preset was requested and PrusaSlicer.ini in {str(root)!r} "
                    f"records no selected {kind} preset."
                )
        if any(character in name for character in '\r\n"'):
            raise ValueError(
                f"PrusaSlicer {kind} preset name {name!r} contains a newline, carriage return, or "
                "double quote; such a name cannot be written to Metadata/Slic3r_PE.config without "
                "corrupting it."
            )
        if name not in available[kind]:
            options = ", ".join(sorted(available[kind])) or "<none installed>"
            raise ValueError(
                f"PrusaSlicer {kind} preset {name!r} is not installed in {str(root)!r}; "
                f"available {kind} presets: {options}."
            )
        chosen[kind] = name
    return ResolvedPresets(
        printer=chosen["printer"],
        filament=chosen["filament"],
        print_settings=chosen["print"],
        config_root=str(root),
    )


# ---------------------------------------------------------------------------
# intent -> per-object overrides (R6)
# ---------------------------------------------------------------------------


def _fmt(value: float) -> str:
    """Six-decimal fixed-point, with the zero collapse tested on the *result*.

    Testing ``value == 0.0`` instead let any negative magnitude below 5e-7 round to
    zero and still print as ``-0``, so mathematically indistinguishable inputs
    produced different bytes -- and different ``project_sha256`` values.
    """
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0", "0") else text


def overrides_for_intent(intent: Any, part_path: str) -> dict[str, str]:
    """Translate declared manufacturing intent into the allowed override set.

    Every emitted key is justified by a declared field; anything the intent does
    not declare is left to the selected presets rather than invented here.
    """
    if not isinstance(intent, dict):
        raise ValueError(f"Printable part {part_path!r} has no manufacturing_intent object.")
    overrides: dict[str, str] = {}

    policy = intent.get("support_policy")
    if not isinstance(policy, str) or policy not in SUPPORT_POLICIES:
        raise ValueError(
            f"Printable part {part_path!r} declares support_policy {policy!r}; "
            f"expected one of {', '.join(sorted(SUPPORT_POLICIES))}."
        )
    if policy not in SUPPORT_POLICY_OVERRIDES:
        raise ValueError(
            f"Printable part {part_path!r} declares support_policy {policy!r}, which requires "
            "per-region support painting; this adapter cannot express declared support_regions in a "
            "PrusaSlicer project and refuses to substitute support everywhere."
        )
    overrides.update(SUPPORT_POLICY_OVERRIDES[policy])

    strength = intent.get("strength")
    if not isinstance(strength, dict):
        raise ValueError(f"Printable part {part_path!r} declares no strength object.")
    perimeters = strength.get("min_perimeters")
    if isinstance(perimeters, bool) or not isinstance(perimeters, int) or perimeters < 1:
        raise ValueError(
            f"Printable part {part_path!r} declares strength.min_perimeters {perimeters!r}; "
            "expected an integer of at least 1."
        )
    overrides["perimeters"] = str(perimeters)
    infill = strength.get("infill_percent")
    if not isinstance(infill, dict):
        raise ValueError(f"Printable part {part_path!r} declares no strength.infill_percent object.")
    target = infill.get("target")
    if isinstance(target, bool) or not isinstance(target, (int, float)) or not 0 <= float(target) <= 100:
        raise ValueError(
            f"Printable part {part_path!r} declares strength.infill_percent.target {target!r}; "
            "expected a number between 0 and 100."
        )
    overrides["fill_density"] = f"{_fmt(target)}%"

    # support_material_style is intentionally absent: no declared field names a
    # style, so PrusaSlicer's configured value stands.
    return validate_overrides(overrides, part_path)


def validate_overrides(overrides: dict[str, str], part_path: str) -> dict[str, str]:
    """Reject any override key outside the justified set (R6, fail-closed)."""
    unjustified = sorted(set(overrides) - set(ALLOWED_OVERRIDE_KEYS))
    if unjustified:
        raise ValueError(
            f"Printable part {part_path!r} would carry unjustified per-object overrides: "
            f"{', '.join(unjustified)}; allowed keys are {', '.join(ALLOWED_OVERRIDE_KEYS)}."
        )
    return dict(overrides)


# ---------------------------------------------------------------------------
# source 3MF reading (R9)
# ---------------------------------------------------------------------------


def _local(tag: Any) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _children(node: Any, name: str) -> list[Any]:
    return [child for child in node if _local(child.tag) == name]


def _mesh_coordinate(vertex: Any, name: str, label: str) -> float:
    """Read one vertex coordinate, fail-closed on missing, non-numeric, or non-finite.

    ``float()`` happily accepts ``"NaN"`` and ``"inf"``; either would propagate
    through the bounds of every part on the plate and emit bare NaN literals into
    the report, which is not even valid JSON.
    """
    raw = vertex.get(name)
    if raw is None:
        raise ValueError(f"Exported 3MF {label!r} has a vertex with no {name} coordinate.")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"Exported 3MF {label!r} has a vertex with non-numeric {name}={raw!r}.") from None
    if not math.isfinite(value):
        raise ValueError(f"Exported 3MF {label!r} has a vertex with non-finite {name}={raw!r}.")
    return value


def _mesh_index(triangle: Any, name: str, label: str) -> int:
    """Read one triangle vertex index; a missing attribute must not raise TypeError."""
    raw = triangle.get(name)
    if raw is None:
        raise ValueError(f"Exported 3MF {label!r} has a triangle with no {name} vertex index.")
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ValueError(f"Exported 3MF {label!r} has a triangle with non-integer {name}={raw!r}.") from None


def _read_source_mesh(payload: bytes, label: str) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            try:
                info = archive.getinfo(MODEL_ENTRY)
            except KeyError:
                raise ValueError(f"Exported 3MF {label!r} has no {MODEL_ENTRY} entry.") from None
            if info.file_size > MAX_MODEL_BYTES:
                raise ValueError(
                    f"Exported 3MF {label!r} declares a {info.file_size}-byte model, "
                    f"above the {MAX_MODEL_BYTES}-byte limit."
                )
            data = archive.read(MODEL_ENTRY)
    except zipfile.BadZipFile as error:
        raise ValueError(f"Exported 3MF {label!r} is not a readable zip package: {error}") from error

    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise ValueError(f"Exported 3MF {label!r} has unparseable {MODEL_ENTRY}: {error}") from error
    unit = root.get("unit", "millimeter")
    if unit != "millimeter":
        raise ValueError(f"Exported 3MF {label!r} declares unit {unit!r}; only 'millimeter' is supported.")

    for build in _children(root, "build"):
        for item in _children(build, "item"):
            transform = item.get("transform")
            if transform and [float(value) for value in transform.split()] != [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0]:
                raise ValueError(
                    f"Exported 3MF {label!r} places its object with a non-identity build transform; "
                    "the adapter would silently drop it."
                )

    objects = [obj for resources in _children(root, "resources") for obj in _children(resources, "object")]
    meshes = [mesh for obj in objects for mesh in _children(obj, "mesh")]
    if len(meshes) != 1:
        raise ValueError(
            f"Exported 3MF {label!r} contains {len(meshes)} mesh objects; exactly one is required "
            "(one printable part per exported artifact)."
        )
    mesh = meshes[0]

    vertices: list[tuple[float, float, float]] = []
    for holder in _children(mesh, "vertices"):
        for vertex in _children(holder, "vertex"):
            vertices.append(tuple(_mesh_coordinate(vertex, axis, label) for axis in ("x", "y", "z")))  # type: ignore[arg-type]
    triangles: list[tuple[int, int, int]] = []
    for holder in _children(mesh, "triangles"):
        for triangle in _children(holder, "triangle"):
            triangles.append(tuple(_mesh_index(triangle, name, label) for name in ("v1", "v2", "v3")))  # type: ignore[arg-type]
    if not vertices or not triangles:
        raise ValueError(f"Exported 3MF {label!r} carries no mesh geometry ({len(vertices)} vertices, {len(triangles)} triangles).")
    limit = len(vertices)
    for triangle in triangles:
        if any(index < 0 or index >= limit for index in triangle):
            raise ValueError(f"Exported 3MF {label!r} has a triangle referencing a vertex outside its own mesh.")
    return vertices, triangles


# ---------------------------------------------------------------------------
# orientation and placement (R3, R4)
# ---------------------------------------------------------------------------


def rotation_for_contact_face(contact_face: Any) -> tuple[tuple[tuple[int, int, int], ...], dict[str, Any]]:
    """Return the 3x3 rotation putting ``contact_face`` on the bed, plus its audit record."""
    if not isinstance(contact_face, str) or contact_face not in CONTACT_FACES:
        raise ValueError(
            f"orientation.contact_face {contact_face!r} is not one of {', '.join(sorted(CONTACT_FACES))}."
        )
    axis, degrees = CONTACT_FACE_ROTATIONS[contact_face]
    record = {"contact_face": contact_face, "axis": axis, "degrees": degrees}
    if axis is None:
        return ((1, 0, 0), (0, 1, 0), (0, 0, 1)), record
    # Quarter/half turns only, so sin/cos are exact integers.
    sin = {90: 1, -90: -1, 180: 0}[degrees]
    cos = {90: 0, -90: 0, 180: -1}[degrees]
    if axis == "X":
        return ((1, 0, 0), (0, cos, -sin), (0, sin, cos)), record
    return ((cos, 0, sin), (0, 1, 0), (-sin, 0, cos)), record


def _apply(rotation: tuple[tuple[int, int, int], ...], point: tuple[float, float, float]) -> tuple[float, float, float]:
    return tuple(  # type: ignore[return-value]
        sum(rotation[row][column] * point[column] for column in range(3)) for row in range(3)
    )


def _rotated_bounds(
    rotation: tuple[tuple[int, int, int], ...],
    vertices: list[tuple[float, float, float]],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    rotated = [_apply(rotation, vertex) for vertex in vertices]
    minimum = tuple(min(point[axis] for point in rotated) for axis in range(3))
    maximum = tuple(max(point[axis] for point in rotated) for axis in range(3))
    return minimum, maximum  # type: ignore[return-value]


def _item_transform(rotation: tuple[tuple[int, int, int], ...], translation: tuple[float, float, float]) -> str:
    """Flatten to the 3MF item transform layout (row-vector convention, translation last)."""
    values = [
        rotation[0][0], rotation[1][0], rotation[2][0],
        rotation[0][1], rotation[1][1], rotation[2][1],
        rotation[0][2], rotation[1][2], rotation[2][2],
        translation[0], translation[1], translation[2],
    ]
    return " ".join(_fmt(value) for value in values)


def assign_plates(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group parts onto plates from declared intent alone.

    ``assembled`` parts share one plate because intent says they belong together.
    ``separate`` parts each get their own plate: capacity is not modeled, so the
    adapter refuses to co-locate parts it was never told to co-locate.
    """
    assembled = [part for part in parts if part["print_as"] == "assembled"]
    separate = [part for part in parts if part["print_as"] != "assembled"]
    plates: list[dict[str, Any]] = []
    if assembled:
        plates.append({"plate": 1, "parts": assembled})
    for part in separate:
        plates.append({"plate": len(plates) + 1, "parts": [part]})
    return plates


# ---------------------------------------------------------------------------
# index validation (R1)
# ---------------------------------------------------------------------------


def _verified_artifact(artifact: dict[str, Any], artifact_dir: Path) -> bytes:
    """Re-verify one indexed artifact and return its bytes (read exactly once)."""
    filename = artifact.get("filename")
    if not isinstance(filename, str) or not filename.strip():
        raise ValueError("Export index artifact is missing a filename.")
    if Path(filename).name != filename or filename in (".", ".."):
        raise ValueError(f"Export index artifact filename {filename!r} must be a bare filename.")
    path = artifact_dir / filename
    if not path.is_file():
        raise ValueError(f"Export index references {filename!r}, which is not a file in {str(artifact_dir)!r}.")
    expected_size = artifact.get("byte_size")
    actual_size = path.stat().st_size
    if actual_size > MAX_ARTIFACT_BYTES:
        raise ValueError(
            f"Export artifact {filename!r} is {actual_size} bytes, above the {MAX_ARTIFACT_BYTES}-byte limit."
        )
    if not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size != actual_size:
        raise ValueError(
            f"Export artifact {filename!r} is {actual_size} bytes; the index records {expected_size!r}."
        )
    payload = path.read_bytes()
    expected_digest = artifact.get("sha256")
    actual_digest = hashlib.sha256(payload).hexdigest()
    if not isinstance(expected_digest, str) or expected_digest != actual_digest:
        raise ValueError(
            f"Export artifact {filename!r} hashes to {actual_digest}; the index records {expected_digest!r}."
        )
    return payload


def _load_index(index_path: Path, expected_manifest_digest: str) -> tuple[dict[str, Any], str]:
    if not index_path.is_file():
        raise ValueError(f"Export index {str(index_path)!r} is not a file.")
    raw = index_path.read_bytes()
    try:
        index = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Export index {str(index_path)!r} is not readable JSON: {error}") from error
    if not isinstance(index, dict):
        raise ValueError("Export index must be a JSON object.")
    if index.get("kind") != "export-handoff":
        raise ValueError(f"Export index kind is {index.get('kind')!r}, expected 'export-handoff'.")
    if index.get("ok") is not True:
        raise ValueError("Export index is not ok: true; the project requires a passing export handoff.")
    actual_digest = index.get("manifest_sha256")
    if actual_digest != expected_manifest_digest:
        raise ValueError(
            f"Export index manifest_sha256 {actual_digest!r} does not match manifest {expected_manifest_digest!r}."
        )
    # The chain is manifest -> verification -> export -> project. Each hop must
    # carry the previous hop's bindings forward, or the project is a set of
    # disconnected links and nothing downstream can tell whether any verification
    # run justified the geometry it contains.
    report_digest = index.get("verification_report_sha256")
    if not isinstance(report_digest, str) or not _SHA256_RE.fullmatch(report_digest):
        raise ValueError(
            f"Export index verification_report_sha256 is {report_digest!r}; a lowercase hex SHA-256 is "
            "required, because the project must name the verification run that justified its geometry."
        )
    run_id = index.get("export_run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError(
            f"Export index export_run_id is {run_id!r}; the project must name the export run it was built from."
        )
    artifacts = index.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("Export index carries no artifacts.")
    return index, hashlib.sha256(raw).hexdigest()


def _collect_parts(index: dict[str, Any], artifact_dir: Path) -> list[dict[str, Any]]:
    geometry: dict[str, dict[str, Any]] = {}
    provenance: dict[str, list[dict[str, Any]]] = {}
    for artifact in index["artifacts"]:
        if not isinstance(artifact, dict):
            raise ValueError("Export index artifacts must be objects.")
        part_path = artifact.get("part_path")
        if not isinstance(part_path, str) or not part_path.strip():
            raise ValueError("Export index artifact is missing part_path.")
        part_path = part_path.strip()
        export_format = artifact.get("format")
        payload = _verified_artifact(artifact, artifact_dir)
        record = {
            "filename": artifact["filename"],
            "format": export_format,
            "sha256": artifact["sha256"],
            "byte_size": artifact["byte_size"],
        }
        if export_format != "3mf":
            provenance.setdefault(part_path, []).append(record)
            continue
        if part_path in geometry:
            raise ValueError(f"Export index carries more than one 3MF artifact for part {part_path!r}.")
        intent = artifact.get("manufacturing_intent")
        if not isinstance(intent, dict):
            raise ValueError(
                f"Export index artifact for part {part_path!r} carries no manufacturing_intent; "
                "the project cannot be built without declared intent."
            )
        # Parsed here, from the bytes just verified: the artifact is never read twice.
        geometry[part_path] = {
            "mesh": _read_source_mesh(payload, artifact["filename"]),
            "artifact": record,
            "intent": intent,
        }

    if not geometry:
        raise ValueError("Export index carries no 3MF artifacts; the project needs exported meshes.")

    parts: list[dict[str, Any]] = []
    for part_path in sorted(geometry):
        entry = geometry[part_path]
        intent = entry["intent"]
        quantity = intent.get("quantity", 1)
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            raise ValueError(f"Printable part {part_path!r} declares quantity {quantity!r}; expected an integer of at least 1.")
        print_as = intent.get("print_as")
        if print_as not in ("separate", "assembled"):
            raise ValueError(f"Printable part {part_path!r} declares print_as {print_as!r}; expected 'separate' or 'assembled'.")
        orientation = intent.get("orientation")
        if not isinstance(orientation, dict):
            raise ValueError(f"Printable part {part_path!r} declares no orientation object.")
        rotation, rotation_record = rotation_for_contact_face(orientation.get("contact_face"))
        vertices, triangles = entry["mesh"]
        parts.append(
            {
                "part_path": part_path,
                "intent": intent,
                "quantity": quantity,
                "print_as": print_as,
                "rotation": rotation,
                "rotation_record": rotation_record,
                "overrides": overrides_for_intent(intent, part_path),
                "vertices": vertices,
                "triangles": triangles,
                "source_artifact": entry["artifact"],
                "provenance_artifacts": sorted(
                    provenance.get(part_path, []), key=lambda record: str(record["filename"])
                ),
            }
        )
    return parts


def _divergent_fields(declared: dict[str, Any], carried: Any) -> list[str]:
    """Keys where the manifest and the index disagree, *including omissions*.

    The union is load-bearing and is not a stylistic choice. Narrowing it to an
    intersection would compare only keys both sides happen to carry, so an index
    that simply *drops* a key would pass -- and ``_collect_parts`` defaults the
    missing ones (quantity to 1), which is how a manifest declaring ``quantity: 2``
    would yield a project printing one. Omission is a divergence.
    """
    if not isinstance(carried, dict):
        return ["<not an object>"]
    return sorted(key for key in set(declared) | set(carried) if declared.get(key) != carried.get(key))


def _assert_intent_matches_manifest(manifest: Manifest, parts: list[dict[str, Any]]) -> None:
    """Refuse an index whose manufacturing intent disagrees with the manifest.

    The manifest is the authority for what gets printed and how. The index carries
    a transcript of it (``export_handoff.manufacturing_intent_by_path``, embedded
    by the export transaction), and every print-determining value applied here --
    support policy, perimeters, infill, contact face, quantity -- is read out of
    that transcript. Binding the manifest's digest while sourcing the content from
    an unchecked copy would make the digest a decoration, so the copy is compared
    back field by field and any divergence fails closed.
    """
    declared_by_path = manufacturing_intent_by_path(manifest)
    # Both directions. Checking only index-against-manifest lets an index that
    # simply omits artifacts build a project that silently prints a subset of the
    # declared parts, under a matching manifest_sha256 and a clean provenance
    # block. A part whose 3MF is missing is missing whether or not its STEP is
    # still indexed, because only 3MF artifacts carry geometry.
    missing = sorted(set(declared_by_path) - {part["part_path"] for part in parts})
    if missing:
        raise ValueError(
            f"Export index carries no 3MF artifact for printable parts the manifest declares: "
            f"{', '.join(missing)}. The project would silently omit them."
        )
    for part in parts:
        part_path = part["part_path"]
        declared = declared_by_path.get(part_path)
        if declared is None:
            raise ValueError(
                f"Export index carries manufacturing intent for part {part_path!r}, which the manifest "
                "does not declare as printable."
            )
        divergent = _divergent_fields(declared, part["intent"])
        if divergent:
            details = ", ".join(
                f"{key}: manifest {declared.get(key)!r} vs index {part['intent'].get(key)!r}"
                for key in divergent
            )
            raise ValueError(
                f"Export index manufacturing_intent for part {part_path!r} disagrees with the manifest "
                f"it is bound to ({details}). The manifest is the authority for print settings; refusing "
                "to apply intent the manifest does not declare."
            )


# ---------------------------------------------------------------------------
# project writing (R2, R8, R9)
# ---------------------------------------------------------------------------


def _attribute(value: Any) -> str:
    return escape(str(value), {'"': "&quot;", "\t": "&#9;", "\n": "&#10;", "\r": "&#13;"})


def _model_xml(parts: list[dict[str, Any]]) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<model unit="millimeter" xml:lang="en-US" xmlns="{CORE_NAMESPACE}">',
        " <resources>",
    ]
    for part in parts:
        lines.append(f'  <object id="{part["object_id"]}" type="model">')
        lines.append("   <mesh>")
        lines.append("    <vertices>")
        for vertex in part["vertices"]:
            lines.append(
                f'     <vertex x="{_fmt(vertex[0])}" y="{_fmt(vertex[1])}" z="{_fmt(vertex[2])}"/>'
            )
        lines.append("    </vertices>")
        lines.append("    <triangles>")
        for triangle in part["triangles"]:
            lines.append(f'     <triangle v1="{triangle[0]}" v2="{triangle[1]}" v3="{triangle[2]}"/>')
        lines.append("    </triangles>")
        lines.append("   </mesh>")
        lines.append("  </object>")
    lines.append(" </resources>")
    lines.append(" <build>")
    for part in parts:
        for transform in part["item_transforms"]:
            lines.append(f'  <item objectid="{part["object_id"]}" transform="{_attribute(transform)}"/>')
    lines.append(" </build>")
    lines.append("</model>")
    return "\n".join(lines) + "\n"


def _model_config_xml(parts: list[dict[str, Any]]) -> str:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<config>"]
    for part in parts:
        lines.append(f' <object id="{part["object_id"]}" instances_count="{part["quantity"]}">')
        lines.append(f'  <metadata type="object" key="name" value="{_attribute(part["part_path"])}"/>')
        for key in sorted(part["overrides"]):
            lines.append(
                f'  <metadata type="object" key="{key}" value="{_attribute(part["overrides"][key])}"/>'
            )
        lines.append(f'  <volume firstid="0" lastid="{len(part["triangles"]) - 1}">')
        lines.append(f'   <metadata type="volume" key="name" value="{_attribute(part["part_path"])}"/>')
        lines.append('   <metadata type="volume" key="volume_type" value="ModelPart"/>')
        # Identity: build orientation and placement live in the build-item
        # transform, so the volume carries no extra frame of its own.
        lines.append('   <metadata type="volume" key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>')
        lines.append("  </volume>")
        lines.append(" </object>")
    lines.append("</config>")
    return "\n".join(lines) + "\n"


def _config_text(presets: ResolvedPresets) -> str:
    """Preset identifiers only -- never a clone of the user's profile settings."""
    return (
        f"; {PRESET_SETTINGS_KEYS['print']} = {presets.print_settings}\n"
        f"; {PRESET_SETTINGS_KEYS['filament']} = \"{presets.filament}\"\n"
        f"; {PRESET_SETTINGS_KEYS['printer']} = {presets.printer}\n"
    )


def _deterministic_zip(entries: list[tuple[str, str]]) -> bytes:
    # ZIP_STORED, not ZIP_DEFLATED: project_sha256 is published so another host can
    # re-derive it, and deflate output depends on the linked zlib build (zlib-ng and
    # stock zlib compress identical bytes differently). Storing costs archive size
    # and buys a hash that means the same thing everywhere.
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, text in entries:
            info = zipfile.ZipInfo(name, date_time=_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o644 << 16
            archive.writestr(info, text.encode("utf-8"))
    return buffer.getvalue()


def _layout(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plates = assign_plates(parts)
    y_cursor = 0.0
    for plate in plates:
        x_cursor = 0.0
        depth = 0.0
        for part in plate["parts"]:
            minimum, maximum = _rotated_bounds(part["rotation"], part["vertices"])
            width = maximum[0] - minimum[0]
            depth = max(depth, maximum[1] - minimum[1])
            transforms = []
            translations = []
            for _ in range(part["quantity"]):
                translation = (x_cursor - minimum[0], y_cursor - minimum[1], -minimum[2])
                transforms.append(_item_transform(part["rotation"], translation))
                translations.append([float(_fmt(value)) for value in translation])
                x_cursor += width + OBJECT_GAP_MM
            part["plate"] = plate["plate"]
            part["item_transforms"] = transforms
            part["translations_mm"] = translations
        y_cursor += depth + PLATE_GAP_MM
    return plates


def build_project(
    manifest: Manifest,
    index_path: str | Path,
    output_path: str | Path,
    presets: ResolvedPresets,
) -> dict[str, Any]:
    """Write a PrusaSlicer project ``.3mf`` from a verified export-handoff index.

    The index must be the one this manifest produced: its ``manifest_sha256`` has
    to match the manifest's own digest, its 3MF parts have to be declared printable
    parts, and its manufacturing intent has to agree with the manifest field for
    field -- so the reported provenance describes the design actually built. It
    must also name the verification report and export run behind it, both of which
    are carried into the result. Fails closed on any index, binding, hash,
    byte-size, intent, orientation, or override problem, and refuses to overwrite
    an existing output.
    """
    index_file = Path(index_path).expanduser()
    output = Path(output_path).expanduser()
    if not isinstance(manifest, Manifest):
        raise ValueError("manifest must be a Manifest loaded via load_manifest().")
    if not isinstance(presets, ResolvedPresets):
        raise ValueError("presets must be a ResolvedPresets resolved via resolve_presets().")
    if output.exists() or output.is_symlink():
        raise ValueError(f"Refusing to overwrite existing output {str(output)!r}.")

    index, index_digest = _load_index(index_file, manifest_sha256(manifest))
    parts = _collect_parts(index, index_file.parent)
    # Stripped, like _collect_parts and export_handoff: the three modules have to
    # agree on what a part path is, or a padded manifest path over-refuses.
    declared = {str(part.get("path", "")).strip() for part in manifest.printable_parts}
    undeclared = sorted({part["part_path"] for part in parts} - declared)
    if undeclared:
        raise ValueError(
            f"Export index carries 3MF artifacts for parts the manifest does not declare as "
            f"printable: {', '.join(undeclared)}."
        )
    _assert_intent_matches_manifest(manifest, parts)
    for object_id, part in enumerate(parts, start=1):
        part["object_id"] = object_id
    plates = _layout(parts)

    payload = _deterministic_zip(
        [
            ("[Content_Types].xml", _CONTENT_TYPES_XML),
            ("_rels/.rels", _RELS_XML),
            (MODEL_ENTRY, _model_xml(parts)),
            (CONFIG_ENTRY, _config_text(presets)),
            (MODEL_CONFIG_ENTRY, _model_config_xml(parts)),
        ]
    )
    try:
        with output.open("xb") as handle:
            handle.write(payload)
    except FileExistsError as error:
        raise ValueError(f"Refusing to overwrite existing output {str(output)!r}.") from error
    except BaseException:
        # A partial file would be indistinguishable from a finished project and
        # would block the retry, since the writer never overwrites.
        output.unlink(missing_ok=True)
        raise

    return {
        "kind": "prusaslicer-project",
        "ok": True,
        "project_path": str(output),
        "project_sha256": hashlib.sha256(payload).hexdigest(),
        "project_byte_size": len(payload),
        "export_index_path": str(index_file),
        "export_index_sha256": index_digest,
        "manifest_sha256": index.get("manifest_sha256"),
        # Carried forward, not re-derived: a downstream reader can follow this
        # project back to the export run and the verification report behind it.
        "verification_report_sha256": index.get("verification_report_sha256"),
        "export_run_id": index.get("export_run_id"),
        "presets": presets.as_dict(),
        "preset_config_root": presets.config_root,
        "plates": [
            {"plate": plate["plate"], "part_paths": [part["part_path"] for part in plate["parts"]]}
            for plate in plates
        ],
        "objects": [
            {
                "object_id": part["object_id"],
                "part_path": part["part_path"],
                "instances_count": part["quantity"],
                "print_as": part["print_as"],
                "plate": part["plate"],
                "applied_rotation": part["rotation_record"],
                "translations_mm": part["translations_mm"],
                "overrides": part["overrides"],
                "source_artifact": part["source_artifact"],
                "provenance_artifacts": part["provenance_artifacts"],
            }
            for part in parts
        ],
        "notes": [
            "Preset identifiers only; no PrusaSlicer profile settings were copied.",
            "PrusaSlicer has a single bed: plates are declared grouping laid out side by side, "
            "and plate capacity was not validated.",
            "Plates march along +Y without bound, so past roughly seven plates the layout runs off "
            "a 360 mm bed. Bed size is not known here -- printer presets are referenced by name and "
            "never read -- so arrange the plates in the PrusaSlicer GUI before slicing.",
            "Project construction executed no binary; slicing is a separate opt-in step.",
        ],
    }
