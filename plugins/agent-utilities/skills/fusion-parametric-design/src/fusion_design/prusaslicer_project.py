"""Build a PrusaSlicer project ``.3mf`` from a verified export-handoff index.

The project is constructed as a file. This module never launches the slicer:
PrusaSlicer 2.9.6 segfaults during headless slicing on the target host, so the
adapter deliberately contains no process-launching API at all. Everything here
is filesystem reads plus ``zipfile``/``ElementTree`` writes.

Layout conventions worth knowing before reading the code:

* Mesh vertices are copied verbatim from the Fusion-exported 3MF. Build
  orientation and plate placement are expressed as the object's build-item
  transform matrix (standard 3MF placement, honored by every reader), so the
  geometry is never rewritten and the applied rotation stays auditable.
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
from pathlib import Path
import sys
from typing import Any
from xml.sax.saxutils import escape
import xml.etree.ElementTree as ET
import zipfile

from .printable_parts import CONTACT_FACES, SUPPORT_POLICIES


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
# outside this table has no justified translation and is rejected.
SUPPORT_POLICY_OVERRIDES = {
    "none": {"support_material": "0"},
    "build-plate-only": {"support_material": "1", "support_material_buildplate_only": "1"},
    "everywhere": {"support_material": "1", "support_material_buildplate_only": "0"},
    "explicit-regions": {"support_material": "1", "support_material_buildplate_only": "0"},
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

_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

_CONTENT_TYPES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
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
    return Path.home() / ".config" / "PrusaSlicer"


def _selected_presets(config_root: Path) -> dict[str, set[str]]:
    """Preset names PrusaSlicer.ini records as selected.

    A selected preset may be a *system* preset with no user ``.ini`` on disk, so
    these names count as installed even when the directory scan misses them.
    """
    selected: dict[str, set[str]] = {kind: set() for kind in PRESET_KINDS}
    ini = config_root / "PrusaSlicer.ini"
    if not ini.is_file():
        return selected
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
    return selected


def _installed_presets(config_root: Path) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    selected = _selected_presets(config_root)
    available: dict[str, set[str]] = {}
    for kind in PRESET_KINDS:
        directory = config_root / kind
        stems = {entry.stem for entry in directory.glob("*.ini")} if directory.is_dir() else set()
        available[kind] = stems | selected[kind]
    return available, selected


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
    available, selected = _installed_presets(root)
    chosen: dict[str, str] = {}
    for kind in PRESET_KINDS:
        name = requested.get(kind)
        name = name.strip() if isinstance(name, str) else None
        if not name:
            fallback = sorted(selected[kind])
            if not fallback:
                raise ValueError(
                    f"No {kind} preset was requested and PrusaSlicer.ini in {str(root)!r} "
                    f"records no selected {kind} preset."
                )
            name = fallback[0]
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
    number = float(value)
    if number == 0.0:
        number = 0.0  # collapse -0.0 so identical inputs give identical bytes
    text = f"{number:.6f}".rstrip("0").rstrip(".")
    return text or "0"


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


def _read_source_mesh(archive_path: Path) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    label = archive_path.name
    try:
        with zipfile.ZipFile(archive_path) as archive:
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
            vertices.append((float(vertex.get("x", 0.0)), float(vertex.get("y", 0.0)), float(vertex.get("z", 0.0))))
    triangles: list[tuple[int, int, int]] = []
    for holder in _children(mesh, "triangles"):
        for triangle in _children(holder, "triangle"):
            triangles.append((int(triangle.get("v1")), int(triangle.get("v2")), int(triangle.get("v3"))))
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


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verified_artifact_path(artifact: dict[str, Any], artifact_dir: Path) -> Path:
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
    if not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size != actual_size:
        raise ValueError(
            f"Export artifact {filename!r} is {actual_size} bytes; the index records {expected_size!r}."
        )
    expected_digest = artifact.get("sha256")
    actual_digest = _file_sha256(path)
    if not isinstance(expected_digest, str) or expected_digest != actual_digest:
        raise ValueError(
            f"Export artifact {filename!r} hashes to {actual_digest}; the index records {expected_digest!r}."
        )
    return path


def _load_index(index_path: Path) -> tuple[dict[str, Any], str]:
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
        path = _verified_artifact_path(artifact, artifact_dir)
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
        geometry[part_path] = {"path": path, "artifact": record, "intent": intent}

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
        vertices, triangles = _read_source_mesh(entry["path"])
        parts.append(
            {
                "part_path": part_path,
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
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, text in entries:
            info = zipfile.ZipInfo(name, date_time=_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
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
    index_path: str | Path,
    output_path: str | Path,
    presets: ResolvedPresets,
) -> dict[str, Any]:
    """Write a PrusaSlicer project ``.3mf`` from a verified export-handoff index.

    Fails closed on any index, hash, byte-size, intent, orientation, or override
    problem, and refuses to overwrite an existing output.
    """
    index_file = Path(index_path).expanduser()
    output = Path(output_path).expanduser()
    if not isinstance(presets, ResolvedPresets):
        raise ValueError("presets must be a ResolvedPresets resolved via resolve_presets().")
    if output.exists() or output.is_symlink():
        raise ValueError(f"Refusing to overwrite existing output {str(output)!r}.")

    index, index_digest = _load_index(index_file)
    parts = _collect_parts(index, index_file.parent)
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

    return {
        "kind": "prusaslicer-project",
        "ok": True,
        "project_path": str(output),
        "project_sha256": hashlib.sha256(payload).hexdigest(),
        "project_byte_size": len(payload),
        "export_index_path": str(index_file),
        "export_index_sha256": index_digest,
        "manifest_sha256": index.get("manifest_sha256"),
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
            "The PrusaSlicer binary was not executed.",
        ],
    }
