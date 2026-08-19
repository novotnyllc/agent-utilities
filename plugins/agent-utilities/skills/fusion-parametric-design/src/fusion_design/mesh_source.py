from __future__ import annotations

import hashlib
import math
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .manifest import Manifest, ValidationIssue


# STL carries no unit, so the unit is only ever as good as its stated source.
UNIT_SOURCES = {"declared", "file", "guess"}

# No mesh statistic separates a designed export from a scan: a designed model
# scores like a capture on every computable measure.  Provenance is declared.
MESH_PROVENANCES = {"designed_export", "capture"}

MESH_UNITS = {"mm", "cm", "m", "in", "ft"}

MESH_SOURCE_FIELDS = {
    "id",
    "path",
    "sha256",
    "units",
    "unit_source",
    "unit_guess",
    "provenance",
    "brep_source",
    "alignment_transform",
}

# The fields _validate_mesh_source refuses to do without, iterated by the schema
# parity test so the published `required` list cannot drift from the validator.
MESH_SOURCE_REQUIRED_FIELDS = {
    "id",
    "path",
    "sha256",
    "units",
    "unit_source",
    "provenance",
    "alignment_transform",
}

BREP_SOURCE_REQUIRED_FIELDS = {"path", "sha256", "trusted", "rationale"}

UNIT_GUESS_FIELDS = {"heuristic", "threshold"}

BREP_SOURCE_FIELDS = {"path", "sha256", "trusted", "rationale"}

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")


def _validate_sha256(
    issues: list[ValidationIssue], value: Any, path: str, code: str
) -> None:
    from .manifest import ValidationIssue

    # Matched unstripped: the published schema pattern rejects padding, and a
    # validator that accepts what the schema refuses is drift, not tolerance.
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        issues.append(
            ValidationIssue(
                code,
                path,
                "sha256 must be a lowercase 64-character hex digest of the file bytes.",
            )
        )


def _validate_mesh_source(issues: list[ValidationIssue], raw: Any, path: str) -> str:
    from .manifest import ValidationIssue, _reject_unknown_fields, _VALID_NAME_RE, _in_closed_set

    if not isinstance(raw, dict):
        issues.append(
            ValidationIssue("mesh-source-must-be-object", path, "Mesh-source entries must be objects.")
        )
        return ""
    _reject_unknown_fields(issues, raw, MESH_SOURCE_FIELDS, path)

    def require_string(field: str, *, strip: bool = True) -> str:
        value = raw.get(field)
        if not isinstance(value, str) or not value.strip():
            issues.append(
                ValidationIssue(
                    "mesh-source-field-required",
                    f"{path}.{field}",
                    f"Mesh-source field {field!r} must be a non-empty string.",
                )
            )
            return ""
        return value.strip() if strip else value

    # The id is kept unstripped for the same reason as the digest: the schema
    # pattern pins it, so padding must fail here too rather than only there.
    source_id = require_string("id", strip=False)
    if source_id and not _VALID_NAME_RE.fullmatch(source_id):
        issues.append(
            ValidationIssue(
                "invalid-mesh-source-id",
                f"{path}.id",
                "A mesh-source id must begin with a letter and contain only letters, digits, and underscores.",
            )
        )
    require_string("path")
    _validate_sha256(issues, raw.get("sha256"), f"{path}.sha256", "mesh-source-invalid-sha256")

    units = raw.get("units")
    if not _in_closed_set(units, MESH_UNITS):
        issues.append(
            ValidationIssue(
                "mesh-source-invalid-units",
                f"{path}.units",
                f"units must be one of {', '.join(sorted(MESH_UNITS))}.",
            )
        )
    unit_source = raw.get("unit_source")
    if not _in_closed_set(unit_source, UNIT_SOURCES):
        issues.append(
            ValidationIssue(
                "mesh-source-invalid-unit-source",
                f"{path}.unit_source",
                f"unit_source must be one of {', '.join(sorted(UNIT_SOURCES))}; a mesh unit is never assumed.",
            )
        )

    unit_guess = raw.get("unit_guess")
    if unit_source == "guess":
        if not isinstance(unit_guess, dict):
            issues.append(
                ValidationIssue(
                    "mesh-source-invalid-unit-guess",
                    f"{path}.unit_guess",
                    "unit_source 'guess' requires unit_guess with the heuristic and the threshold that produced it.",
                )
            )
        else:
            _reject_unknown_fields(issues, unit_guess, UNIT_GUESS_FIELDS, f"{path}.unit_guess")
            heuristic = unit_guess.get("heuristic")
            if not isinstance(heuristic, str) or not heuristic.strip():
                issues.append(
                    ValidationIssue(
                        "mesh-source-invalid-unit-guess",
                        f"{path}.unit_guess.heuristic",
                        "A guessed unit must name the heuristic that produced it.",
                    )
                )
            threshold = unit_guess.get("threshold")
            if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(float(threshold)):
                issues.append(
                    ValidationIssue(
                        "mesh-source-invalid-unit-guess",
                        f"{path}.unit_guess.threshold",
                        "A guessed unit must record the finite numeric threshold the heuristic compared against.",
                    )
                )
    elif "unit_guess" in raw:
        issues.append(
            ValidationIssue(
                "mesh-source-invalid-unit-guess",
                f"{path}.unit_guess",
                "unit_guess is only allowed when unit_source is 'guess'.",
            )
        )

    if not _in_closed_set(raw.get("provenance"), MESH_PROVENANCES):
        issues.append(
            ValidationIssue(
                "mesh-source-invalid-provenance",
                f"{path}.provenance",
                f"provenance must be one of {', '.join(sorted(MESH_PROVENANCES))}; it is declared, never derived from mesh statistics.",
            )
        )

    brep_source = raw.get("brep_source")
    if brep_source is not None:
        brep_path = f"{path}.brep_source"
        if not isinstance(brep_source, dict):
            issues.append(
                ValidationIssue(
                    "mesh-source-invalid-brep-source",
                    brep_path,
                    "brep_source, when present, must be an object with path, sha256, trusted, and rationale.",
                )
            )
        else:
            _reject_unknown_fields(issues, brep_source, BREP_SOURCE_FIELDS, brep_path)
            for field in ("path", "rationale"):
                value = brep_source.get(field)
                if not isinstance(value, str) or not value.strip():
                    issues.append(
                        ValidationIssue(
                            "mesh-source-invalid-brep-source",
                            f"{brep_path}.{field}",
                            f"brep_source.{field} must be a non-empty string; record which source was trusted and why.",
                        )
                    )
            _validate_sha256(
                issues,
                brep_source.get("sha256"),
                f"{brep_path}.sha256",
                "mesh-source-invalid-brep-source",
            )
            if not isinstance(brep_source.get("trusted"), bool):
                issues.append(
                    ValidationIssue(
                        "mesh-source-invalid-brep-source",
                        f"{brep_path}.trusted",
                        "brep_source.trusted must be a boolean; a bundled B-Rep may not match the mesh people printed.",
                    )
                )

    transform = raw.get("alignment_transform")
    if not isinstance(transform, list) or len(transform) != 16:
        issues.append(
            ValidationIssue(
                "mesh-source-invalid-alignment-transform",
                f"{path}.alignment_transform",
                "alignment_transform must be a 16-value row-major 4x4 matrix; record the identity when nothing was moved.",
            )
        )
    else:
        for index, value in enumerate(transform):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                issues.append(
                    ValidationIssue(
                        "mesh-source-invalid-alignment-transform",
                        f"{path}.alignment_transform[{index}]",
                        "alignment_transform values must be finite numbers.",
                    )
                )
    return source_id


def _validate_mesh_sources(issues: list[ValidationIssue], mesh_sources: Any) -> None:
    from .manifest import ValidationIssue, _duplicates

    if mesh_sources is None:
        return
    if not isinstance(mesh_sources, list):
        issues.append(
            ValidationIssue(
                "mesh-sources-must-be-list",
                "mesh_sources",
                "mesh_sources must be a list of mesh-source objects.",
            )
        )
        return
    source_ids: list[str] = []
    for index, raw in enumerate(mesh_sources):
        source_id = _validate_mesh_source(issues, raw, f"mesh_sources[{index}]")
        if source_id:
            source_ids.append(source_id)
    for duplicate in sorted(_duplicates(source_ids)):
        issues.append(
            ValidationIssue(
                "mesh-source-duplicate-id",
                "mesh_sources",
                f"Mesh-source id {duplicate!r} is duplicated.",
            )
        )


def validate_mesh_source_record(record: Any, path: str = "mesh_source") -> list[ValidationIssue]:
    """Validate one mesh-source record on its own, outside a manifest."""
    issues: list[ValidationIssue] = []
    _validate_mesh_source(issues, record, path)
    return issues


def unit_source_reason(record: dict[str, Any]) -> str:
    """The recorded reason a unit is believed, printed with every capture report."""
    from .manifest import _in_closed_set

    # Read with the same normalization the validator used: exactly none.
    unit_source = record.get("unit_source")
    units = record.get("units")
    if not _in_closed_set(unit_source, UNIT_SOURCES):
        raise ValueError(f"unit_source {unit_source!r} is not one of {', '.join(sorted(UNIT_SOURCES))}.")
    if unit_source == "declared":
        return f"Units {units} were declared by the requester; no file or heuristic evidence backs them."
    if unit_source == "file":
        return f"Units {units} were read from a source file format that carries a unit."
    guess = record.get("unit_guess") or {}
    heuristic = str(guess.get("heuristic", "")).strip()
    threshold = guess.get("threshold")
    # A reason that cannot state its heuristic is not a reason; refuse rather
    # than print "guessed by heuristic '' at threshold None" into the report.
    if not heuristic or isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise ValueError(
            "A guessed unit must record the heuristic and the numeric threshold that produced it."
        )
    return (
        f"Units {units} were guessed by heuristic {heuristic!r} at threshold {guess.get('threshold')}; "
        "a mesh carries no unit, so a 1000x scale error still validates clean."
    )


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1048576)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def verify_mesh_source_file(record: dict[str, Any], file_path: str | Path | None = None) -> str:
    """Fail closed unless the file on disk is byte-identical to the captured source.

    A moved or edited source must stop the workflow, not be silently re-measured.
    """
    from .manifest import ManifestValidationError, ValidationIssue

    issues = validate_mesh_source_record(record)
    if issues:
        raise ManifestValidationError(issues)
    target = Path(str(file_path) if file_path is not None else str(record["path"]).strip())
    if not target.is_file():
        raise ManifestValidationError(
            [
                ValidationIssue(
                    "mesh-source-file-missing",
                    "mesh_source.path",
                    f"Mesh source file {str(target)!r} does not exist; the captured bytes cannot be re-verified.",
                )
            ]
        )
    digest = file_sha256(target)
    recorded = str(record["sha256"]).strip()
    if digest != recorded:
        raise ManifestValidationError(
            [
                ValidationIssue(
                    "mesh-source-hash-mismatch",
                    "mesh_source.sha256",
                    f"Mesh source {str(target)!r} hashes to {digest} but the record captured {recorded}; "
                    "re-capture the source instead of re-measuring a changed file.",
                )
            ]
        )
    return digest


def verify_manifest_mesh_sources(
    manifest: Manifest, manifest_path: str | Path
) -> dict[str, str]:
    """Re-hash every declared mesh source before any mesh transaction is emitted.

    This is what makes the recorded digest load-bearing rather than decorative:
    without it the hash is written once and never checked again, and a swapped
    file produces a confident transaction carrying a stale digest.  Relative
    ``path`` values are anchored to the manifest's own directory.
    """
    root = Path(manifest_path).resolve().parent
    verified: dict[str, str] = {}
    for record in manifest.mesh_sources:
        verified[str(record.get("id", ""))] = verify_mesh_source_file(
            record, root / str(record.get("path", "")).strip()
        )
    return verified


def mesh_source_record(manifest: Manifest, source_id: str) -> dict[str, Any]:
    """Look one declared mesh source up by id, refusing an unknown id."""
    from .manifest import ManifestValidationError, ValidationIssue

    for record in manifest.mesh_sources:
        if record.get("id") == source_id:
            return dict(record)
    raise ManifestValidationError(
        [
            ValidationIssue(
                "mesh-source-unknown-id",
                "mesh_sources",
                f"No mesh source is declared with id {source_id!r}; declared ids are "
                + (", ".join(sorted(str(record.get("id")) for record in manifest.mesh_sources)) or "(none)")
                + ".",
            )
        ]
    )


def mesh_capture_specs(manifest: Manifest) -> list[dict[str, Any]]:
    """Declared side of the capture report: what the manifest claims, with its unit reason."""
    specs: list[dict[str, Any]] = []
    for record in manifest.mesh_sources:
        brep_source = record.get("brep_source")
        specs.append(
            {
                "id": str(record.get("id", "")),
                "path": str(record.get("path", "")).strip(),
                "sha256": str(record.get("sha256", "")),
                # Enum values, the id, and the digest are emitted exactly as the
                # validator accepted them; only path is stripped, because that is
                # the one field whose validation strips.
                "units": record.get("units"),
                "unit_source": record.get("unit_source"),
                "unit_source_reason": unit_source_reason(record),
                "provenance": record.get("provenance"),
                "brep_source_available": isinstance(brep_source, dict),
                "alignment_transform": list(record.get("alignment_transform", [])),
            }
        )
    return specs


def emit_mesh_capture_script(manifest: Manifest) -> str:
    """Emit the read-only capture transaction; it creates and modifies nothing."""
    from .scripts import _json_literal, _script_prelude

    specs = mesh_capture_specs(manifest)
    if not specs:
        raise ValueError("Manifest declares no mesh_sources; there is nothing to capture.")

    transaction = '''MESH_CAPTURE_SPECS = json.loads(__MESH_CAPTURE_SPECS__)


def _read(mesh_body, name, unavailable):
    """Read an optional preview property; absent is reported, never guessed."""
    try:
        value = getattr(mesh_body, name, None)
    except Exception:
        value = None
    if value is None:
        unavailable.append(name)
    return value


def _oriented_box_mm(box, unavailable):
    if box is None:
        return None
    try:
        return {
            "center_mm": [box.centerPoint.x * 10.0, box.centerPoint.y * 10.0, box.centerPoint.z * 10.0],
            "length_mm": float(box.length) * 10.0,
            "width_mm": float(box.width) * 10.0,
            "height_mm": float(box.height) * 10.0,
            "length_direction": [box.lengthDirection.x, box.lengthDirection.y, box.lengthDirection.z],
            "width_direction": [box.widthDirection.x, box.widthDirection.y, box.widthDirection.z],
            "height_direction": [box.heightDirection.x, box.heightDirection.y, box.heightDirection.z],
        }
    except Exception:
        unavailable.append("orientedMinimumBoundingBox.values")
        return None


def _mesh_body_row(mesh_body, component_path):
    unavailable = []
    triangle_count = None
    mesh = _read(mesh_body, "mesh", unavailable)
    if mesh is not None:
        try:
            triangle_count = int(mesh.triangleCount)
        except Exception:
            unavailable.append("mesh.triangleCount")
    volume = _read(mesh_body, "volume", unavailable)
    if triangle_count is None:
        unavailable.append("mesh.triangleCount")
    row = {
        "component_path": component_path,
        # name is half of the binding evidence, so an unnamed body is listed
        # absent rather than reported as a null nobody notices.
        "name": _read(mesh_body, "name", unavailable),
        "triangle_count": triangle_count,
        "is_closed": _read(mesh_body, "isClosed", unavailable),
        "is_oriented": _read(mesh_body, "isOriented", unavailable),
        "volume_mm3": float(volume) * 1000.0 if volume is not None else None,
        "oriented_minimum_bounding_box_mm": _oriented_box_mm(
            _read(mesh_body, "orientedMinimumBoundingBox", unavailable), unavailable
        ),
        "unavailable": sorted(set(unavailable)),
    }
    return row


def _component_mesh_rows(component, component_path, rows):
    mesh_bodies = getattr(component, "meshBodies", None)
    if mesh_bodies is None:
        return False
    for index in range(mesh_bodies.count):
        rows.append(_mesh_body_row(mesh_bodies.item(index), component_path))
    return True


def run(context):
    report_attempted = False
    try:
        app, design = _active_design()
        fusion_version = getattr(app, "version", None)
        root_component = design.rootComponent
        missing_capabilities = []
        if not fusion_version:
            missing_capabilities.append("Application.version")
        if getattr(root_component, "meshBodies", None) is None:
            missing_capabilities.append("Component.meshBodies")
        if missing_capabilities:
            report_attempted = True
            _emit({
                "kind": "mesh-capture",
                "ok": False,
                "project": PROJECT_NAME,
                "manifest_sha256": MANIFEST_SHA256,
                "failures": ["mesh-capture-capability"],
                "missing_capabilities": missing_capabilities,
            })
            raise RuntimeError(
                "The live Fusion mesh capture capability is unavailable; missing "
                + ", ".join(missing_capabilities)
                + ". Every mesh API used here is preview and may move between versions."
            )

        target_document = _require_target_document(app)
        _pump_events(app, design, target_document)

        rows = []
        _component_mesh_rows(root_component, "", rows)
        _, occurrence_map, duplicate_semantic_paths = _root_context_occurrence_map(root_component)
        for index, path in enumerate(sorted(occurrence_map)):
            _component_mesh_rows(occurrence_map[path].component, path, rows)
            _pump_events_periodically(app, design, target_document, index)
        _pump_events(app, design, target_document)

        failures = []
        if not rows:
            failures.append("no-mesh-bodies")
        # The classification gate demands watertightness and facet count be read
        # from this report, never assumed.  A report that says ok while those two
        # are unreadable leaves assuming them as the only way forward, so the
        # capture refuses instead.  isOriented, volume and the bounding box stay
        # optional: they are reported evidence, not gate inputs.
        unreadable = [
            {
                "component_path": row["component_path"],
                "name": row["name"],
                "unavailable": row["unavailable"],
            }
            for row in rows
            if row["triangle_count"] is None or row["is_closed"] is None
        ]
        if unreadable:
            failures.append("mesh-evidence-unavailable")
        if duplicate_semantic_paths:
            # Only the first occurrence per semantic path is enumerated, so the
            # body list is a subset while the binding note tells the reader to
            # bind by name and path.  Refuse, as the scaffold transaction does.
            failures.append("ambiguous-component-paths")

        report = {
            "kind": "mesh-capture",
            "ok": not failures,
            "project": PROJECT_NAME,
            "manifest_sha256": MANIFEST_SHA256,
            "fusion_version": fusion_version,
            "document_name": app.activeDocument.name if app.activeDocument else None,
            "declared_mesh_sources": MESH_CAPTURE_SPECS,
            "unit_source_reasons": [spec["unit_source_reason"] for spec in MESH_CAPTURE_SPECS],
            "mesh_bodies": rows,
            "duplicate_semantic_paths": duplicate_semantic_paths,
            "unreadable_mesh_bodies": unreadable,
            "failures": failures,
            "binding_note": (
                "This capture is read-only and claims no binding between declared mesh_sources and the "
                "mesh bodies it found; bind them from the reported names and paths. That binding is only "
                "usable while duplicate_semantic_paths is empty."
            ),
        }
        report_attempted = True
        _emit(report)
        if failures:
            raise RuntimeError("Fusion mesh capture failed closed: " + ", ".join(failures))
    except Exception as error:
        if not report_attempted:
            report_attempted = True
            _emit({
                "kind": "mesh-capture",
                "ok": False,
                "project": PROJECT_NAME,
                "manifest_sha256": MANIFEST_SHA256,
                "error": str(error),
                "traceback": traceback.format_exc(),
            })
        raise
'''
    return _script_prelude(manifest) + transaction.replace(
        "__MESH_CAPTURE_SPECS__", _json_literal(specs)
    )
