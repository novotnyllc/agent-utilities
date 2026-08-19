from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Any

from .manifest import Manifest


ALLOWED_FORMATS = ("step", "3mf", "stl")
EXAMPLE_EXPORT_DIR = "FUSION_EXPORT_DIR"
_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class ExportConfig:
    """Host-side binding embedded into the generated export transaction.

    ``verification_binding`` maps each expected print part to the properties the
    passing verification report measured for it -- bounds, solid volume, and the
    root-context occurrence transform. Every one of them is re-measured in Fusion
    before the export runs. See ``EXPORT_BINDING_RESIDUAL`` for what that does and
    does not prove.
    """

    export_dir: str
    formats: tuple[str, ...]
    verification_report_sha256: str
    verification_binding: dict[str, dict[str, Any]]


# Stated wherever the gate is described, because the gate is a sampling of
# properties and not a proof of identity.
EXPORT_BINDING_RESIDUAL = (
    "The staleness gate re-measures bounds, total solid volume, and the occurrence transform. "
    "An edit that preserves all three -- relocating a hole, swapping a fillet for an equal-volume "
    "chamfer -- is not detected, and the report's clearance and interference results are not "
    "re-run. The gate detects drift in the properties it names; it does not prove the exported "
    "geometry is the verified geometry."
)


def _slug(value: str) -> str:
    collapsed = re.sub(r"[^A-Za-z0-9_]+", "-", value).strip("-")
    if not collapsed:
        raise ValueError(f"Cannot derive a deterministic filename slug from {value!r}.")
    return collapsed.lower()


def _artifact_filename(project_name: str, part_path: str, digest: str, export_format: str) -> str:
    return f"{_slug(project_name)}__{_slug(part_path)}__{digest[:8]}.{export_format}"


def _validate_bounds(path: str, bounds: Any) -> dict[str, list[float]]:
    if not isinstance(bounds, dict) or set(bounds) != {"min", "max"}:
        raise ValueError(f"Verification bounds for {path!r} must contain exactly 'min' and 'max'.")
    validated: dict[str, list[float]] = {}
    for key in ("min", "max"):
        corner = bounds[key]
        if not isinstance(corner, list) or len(corner) != 3:
            raise ValueError(f"Verification bounds for {path!r} must be three-axis boxes.")
        values = [float(value) for value in corner]
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"Verification bounds for {path!r} must be finite; NaN/Infinity would vacuously pass the staleness gate.")
        validated[key] = values
    return validated


def _validate_volume(path: str, geometry: Any) -> float:
    if not isinstance(geometry, dict):
        raise ValueError(f"Verification report has no geometry summary for print part {path!r}.")
    volume = geometry.get("total_solid_volume_mm3")
    if isinstance(volume, bool) or not isinstance(volume, (int, float)):
        raise ValueError(f"Verification report records total_solid_volume_mm3 {volume!r} for {path!r}.")
    volume = float(volume)
    if not math.isfinite(volume) or volume <= 0.0:
        raise ValueError(
            f"Verification report records a non-positive or non-finite solid volume for {path!r}; "
            "such a value would vacuously pass the staleness gate."
        )
    return volume


def _validate_transform(path: str, transform: Any) -> list[float]:
    if not isinstance(transform, list) or len(transform) != 16:
        raise ValueError(
            f"Verification report has no 16-element occurrence transform for print part {path!r}; "
            "the export cannot confirm the part is still placed where it was verified."
        )
    values = [float(value) for value in transform]
    if not all(math.isfinite(value) for value in values):
        raise ValueError(f"Occurrence transform for {path!r} must be finite.")
    return values


def verification_binding_from_report(manifest: Manifest, report_data: Any) -> dict[str, dict[str, Any]]:
    """Validate a verification report against the manifest and extract the print-part binding.

    Binds every property the report already measured that the export can cheaply
    re-measure: B-Rep bounds, total solid volume, and the root-context occurrence
    transform. ``EXPORT_BINDING_RESIDUAL`` states what that still does not cover.
    """
    from .scripts import manifest_sha256

    if not isinstance(report_data, dict):
        raise ValueError("Verification report must be a JSON object.")
    if report_data.get("kind") != "verification":
        raise ValueError(f"Verification report kind is {report_data.get('kind')!r}, expected 'verification'.")
    if report_data.get("ok") is not True:
        raise ValueError("Verification report is not ok: true; export requires passing verification.")
    expected_digest = manifest_sha256(manifest)
    actual_digest = report_data.get("manifest_sha256")
    if actual_digest != expected_digest:
        raise ValueError(
            f"Verification report manifest_sha256 {actual_digest!r} does not match manifest {expected_digest!r}."
        )
    boxes = report_data.get("brep_bounding_boxes_mm")
    if not isinstance(boxes, dict):
        raise ValueError("Verification report is missing brep_bounding_boxes_mm.")
    geometry = report_data.get("geometry")
    if not isinstance(geometry, dict):
        raise ValueError("Verification report is missing geometry.")
    transforms = report_data.get("occurrence_transforms")
    if not isinstance(transforms, dict):
        raise ValueError("Verification report is missing occurrence_transforms.")
    binding: dict[str, dict[str, Any]] = {}
    for path in manifest.verification.get("expected_print_parts", []):
        part_bounds = boxes.get(path)
        if part_bounds is None or (isinstance(part_bounds, dict) and "error" in part_bounds):
            raise ValueError(f"Verification report has no usable B-Rep bounds for print part {path!r}.")
        binding[path] = {
            "bounds_mm": _validate_bounds(path, part_bounds),
            "total_solid_volume_mm3": _validate_volume(path, geometry.get(path)),
            "transform": _validate_transform(path, transforms.get(path)),
        }
    return binding


def _validate_config(manifest: Manifest, config: ExportConfig) -> list[str]:
    expected_parts = list(manifest.verification.get("expected_print_parts", []))
    if not expected_parts:
        raise ValueError("Manifest declares no verification.expected_print_parts; nothing to export.")
    if not config.export_dir or not str(config.export_dir).strip():
        raise ValueError("Export directory must be a non-empty Fusion-host path.")
    formats = tuple(config.formats)
    if not formats:
        raise ValueError("At least one export format is required.")
    unknown = sorted(set(formats) - set(ALLOWED_FORMATS))
    if unknown:
        raise ValueError(f"Unsupported export formats: {', '.join(unknown)}.")
    if len(set(formats)) != len(formats):
        raise ValueError("Export formats must not repeat.")
    if "step" not in formats:
        raise ValueError("STEP export is required; add 'step' to the requested formats.")
    if not _SHA256_RE.fullmatch(config.verification_report_sha256):
        raise ValueError("verification_report_sha256 must be a lowercase hex SHA-256.")
    missing = sorted(set(expected_parts) - set(config.verification_binding))
    if missing:
        raise ValueError(f"Verification bounds are missing for print parts: {', '.join(missing)}.")
    return expected_parts


def manufacturing_intent_by_path(manifest: Manifest) -> dict[str, dict[str, Any]]:
    """The manifest's declared manufacturing intent, keyed by normalized part path.

    This is the *only* projection of intent in the package. The export transaction
    embeds it into the handoff index verbatim, and ``prusaslicer_project`` compares
    the index's copy back against it -- so the index is a transcript of the manifest
    rather than an independent, unbound source of print settings.

    Keys are stripped to match the validator, which normalizes printable-part paths
    before comparing them against ``verification.expected_print_parts``.
    """
    return {
        str(part.get("path", "")).strip(): {
            "id": part.get("id"),
            "quantity": part.get("quantity", 1),
            "print_as": part.get("print_as"),
            "orientation": part.get("orientation"),
            "support_policy": part.get("support_policy"),
            **({"support_regions": part["support_regions"]} if "support_regions" in part else {}),
            "strength": part.get("strength"),
            "protected_features": part.get("protected_features"),
            "material": part.get("material"),
        }
        for part in manifest.printable_parts
    }


def emit_export_script(manifest: Manifest, config: ExportConfig) -> str:
    from .scripts import _json_literal, _script_prelude, manifest_sha256

    expected_parts = _validate_config(manifest, config)
    digest = manifest_sha256(manifest)
    intent_by_path = manufacturing_intent_by_path(manifest)
    body_name_by_path = {
        str(part.get("path", "")).strip(): str(part["body_name"]).strip()
        for part in manifest.printable_parts
        if part.get("body_name")
    }
    parts = []
    for path in expected_parts:
        binding = config.verification_binding[path]
        part_spec = {
            "path": path,
            "expected_bounds_mm": _validate_bounds(path, binding.get("bounds_mm")),
            "expected_total_solid_volume_mm3": _validate_volume(path, binding),
            "expected_transform": _validate_transform(path, binding.get("transform")),
            "filenames": {
                export_format: _artifact_filename(manifest.project_name, path, digest, export_format)
                for export_format in config.formats
            },
        }
        if path in intent_by_path:
            part_spec["manufacturing_intent"] = intent_by_path[path]
        if path in body_name_by_path:
            part_spec["expected_body_name"] = body_name_by_path[path]
        parts.append(part_spec)
    if manifest.printable_parts:
        uncovered = sorted(path for path in expected_parts if path not in intent_by_path)
        if uncovered:
            raise ValueError(
                f"Manufacturing intent is missing for print parts: {', '.join(uncovered)}."
            )
    filename_owners: dict[str, str] = {f"export-index__{digest[:8]}.json": "<index>"}
    for part in parts:
        for filename in part["filenames"].values():
            if filename in filename_owners:
                raise ValueError(
                    f"Deterministic filenames collide: {part['path']!r} and {filename_owners[filename]!r} "
                    f"both produce {filename!r}; rename one component path."
                )
            filename_owners[filename] = part["path"]
    specs = {
        "export_dir": str(config.export_dir),
        "formats": list(config.formats),
        "verification_report_sha256": config.verification_report_sha256,
        "index_filename": f"export-index__{digest[:8]}.json",
        "parts": parts,
    }
    # The material decision is a project-level fact, so it rides the index once
    # rather than being copied onto every artifact.
    if manifest.material_decision:
        specs["material_decision"] = manifest.material_decision

    transaction = '''import hashlib
import os
import uuid

EXPORT_SPECS = json.loads(__EXPORT_SPECS__)
EXPORT_STALENESS_TOLERANCE_MM = 1e-3
# Volume is compared relatively: it scales as the cube of a length, so an absolute
# millimetre tolerance would be meaningless across part sizes. 1e-4 is chosen to
# sit alongside the bounds gate rather than far below it -- 1e-3 mm on a 100 mm
# part is ~1e-5 relative, and volume goes as the cube, so a tighter volume figure
# would make this the strictest gate of the three. The producer and the
# re-measurement are the same summation, so there is no systematic offset to
# absorb; the headroom is for Fusion's recompute jitter, which cannot be measured
# offline. It is still orders of magnitude below any real edit: deleting an
# internal boss or thinning a wall moves volume by percent, not by 0.01%.
# A false alarm on the most safety-critical gate is how a gate gets disabled.
EXPORT_STALENESS_VOLUME_RELATIVE_TOLERANCE = 1e-4
# transform2 is a 4x4 in Fusion's internal centimetres; the rotation entries are
# dimensionless, so one absolute tolerance covers both halves.
EXPORT_STALENESS_TRANSFORM_TOLERANCE = 1e-9
# Residual, stated in the emitted script because it is the script that gates:
# __BINDING_RESIDUAL__
FORMAT_OPTION_ATTRIBUTES = {
    "step": "createSTEPExportOptions",
    "3mf": "createC3MFExportOptions",
    "stl": "createSTLExportOptions",
}


def _file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1048576)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _missing_export_capabilities(design):
    missing = []
    export_manager = getattr(design, "exportManager", None)
    if not export_manager:
        return ["Design.exportManager"], None
    if not hasattr(export_manager, "execute"):
        missing.append("ExportManager.execute")
    for export_format in EXPORT_SPECS["formats"]:
        attribute = FORMAT_OPTION_ATTRIBUTES[export_format]
        if not hasattr(export_manager, attribute):
            missing.append("ExportManager." + attribute)
    return missing, export_manager


def _document_identity(target_document):
    saved = bool(getattr(target_document, "isSaved", False))
    version = "unsaved"
    if saved:
        try:
            data_file = target_document.dataFile
            if data_file:
                version = {
                    "id": str(data_file.id),
                    "version_number": int(data_file.versionNumber),
                }
        except Exception:
            version = "unsaved"
    return saved, version


def _occurrence_transform(occurrence):
    transform = getattr(occurrence, "transform2", None)
    if not transform:
        return None
    return [float(value) for value in transform.asArray()]


def _resolve_single_solid_body(occurrence, path, failures, resolution_errors):
    bodies = occurrence.bRepBodies
    name_counts = {}
    solids = []
    for index in range(bodies.count):
        body = bodies.item(index)
        name_counts[body.name] = name_counts.get(body.name, 0) + 1
        if bool(body.isSolid) and float(body.volume) * 1000.0 > 1e-9:
            solids.append(body)
    duplicate_names = sorted(name for name, count in name_counts.items() if count > 1)
    if duplicate_names:
        failures.add("ambiguous-body")
        resolution_errors.append({
            "path": path,
            "reason": "duplicate-body-names",
            "detail": duplicate_names,
        })
        return None
    if not solids:
        failures.add("missing-solid")
        resolution_errors.append({"path": path, "reason": "no-positive-solid-body"})
        return None
    if len(solids) > 1:
        failures.add("ambiguous-body")
        resolution_errors.append({
            "path": path,
            "reason": "multiple-solid-bodies",
            "detail": sorted(body.name for body in solids),
        })
        return None
    return solids[0]


def _bounds_are_stale(actual, expected):
    for key in ("min", "max"):
        for index in range(3):
            if abs(float(actual[key][index]) - float(expected[key][index])) > EXPORT_STALENESS_TOLERANCE_MM:
                return True
    return False


def _solid_volume_mm3(occurrence):
    """Total volume of the positive solid bodies, matching the verification report."""
    total = 0.0
    bodies = occurrence.bRepBodies
    for index in range(bodies.count):
        body = bodies.item(index)
        volume_mm3 = float(body.volume) * 1000.0
        if bool(body.isSolid) and volume_mm3 > 1e-9:
            total += volume_mm3
    return total


def _volume_is_stale(actual, expected):
    expected = float(expected)
    return abs(float(actual) - expected) > abs(expected) * EXPORT_STALENESS_VOLUME_RELATIVE_TOLERANCE


def _transform_is_stale(actual, expected):
    if not isinstance(actual, list) or len(actual) != len(expected):
        return True
    for index in range(len(expected)):
        if abs(float(actual[index]) - float(expected[index])) > EXPORT_STALENESS_TRANSFORM_TOLERANCE:
            return True
    return False


def _remove_created(paths):
    errors = []
    for path in reversed(paths):
        try:
            os.remove(path)
        except FileNotFoundError:
            continue
        except Exception as error:
            errors.append(path + ": " + str(error))
    return errors


def run(context):
    report_attempted = False
    created_paths = []
    try:
        app, design = _active_design()
        missing_capabilities, export_manager = _missing_export_capabilities(design)
        if missing_capabilities:
            report_attempted = True
            _emit({
                "kind": "export-handoff",
                "project": PROJECT_NAME,
                "manifest_sha256": MANIFEST_SHA256,
                "ok": False,
                "failures": ["export-capability"],
                "missing_export_capabilities": missing_capabilities,
            })
            raise RuntimeError(
                "The live Fusion export capability is unavailable; missing "
                + ", ".join(missing_capabilities)
                + ". A missing constructor name is an adapter/API mismatch, not proof Fusion cannot export."
            )
        target_document = _require_target_document(app)
        _pump_events(app, design, target_document)

        document_saved, document_version = _document_identity(target_document)
        try:
            units = design.unitsManager.defaultLengthUnits
        except Exception:
            units = None

        _, occurrence_map, duplicate_semantic_paths = _root_context_occurrence_map(design.rootComponent)
        failures = set()
        resolution_errors = []
        stale_parts = []
        resolved = {}
        for part in EXPORT_SPECS["parts"]:
            path = part["path"]
            if path in duplicate_semantic_paths:
                failures.add("ambiguous-components")
                resolution_errors.append({
                    "path": path,
                    "reason": "duplicate-semantic-path",
                    "detail": duplicate_semantic_paths[path],
                })
                continue
            occurrence = occurrence_map.get(path)
            if not occurrence:
                failures.add("missing-component")
                resolution_errors.append({"path": path, "reason": "component-path-missing"})
                continue
            body = _resolve_single_solid_body(occurrence, path, failures, resolution_errors)
            if body is None:
                continue
            expected_body_name = part.get("expected_body_name")
            if expected_body_name and body.name != expected_body_name:
                failures.add("body-name-mismatch")
                resolution_errors.append({
                    "path": path,
                    "reason": "declared-body-name-mismatch",
                    "expected": expected_body_name,
                    "actual": body.name,
                })
                continue
            try:
                actual_bounds = _bbox_mm(occurrence)
            except Exception as error:
                failures.add("stale-verification")
                stale_parts.append({"path": path, "reason": "bounds-unavailable", "detail": str(error)})
                continue
            if _bounds_are_stale(actual_bounds, part["expected_bounds_mm"]):
                failures.add("stale-verification")
                stale_parts.append({
                    "path": path,
                    "reason": "bounds-drifted",
                    "expected_bounds_mm": part["expected_bounds_mm"],
                    "actual_bounds_mm": actual_bounds,
                })
                continue
            # Bounds alone are six numbers: an edit that preserves the extent
            # passes them. Volume and placement are the other two properties the
            # verification report already measured, so they are re-measured here.
            try:
                actual_volume = _solid_volume_mm3(occurrence)
            except Exception as error:
                failures.add("stale-verification")
                stale_parts.append({"path": path, "reason": "volume-unavailable", "detail": str(error)})
                continue
            if _volume_is_stale(actual_volume, part["expected_total_solid_volume_mm3"]):
                failures.add("stale-verification")
                stale_parts.append({
                    "path": path,
                    "reason": "volume-drifted",
                    "expected_total_solid_volume_mm3": part["expected_total_solid_volume_mm3"],
                    "actual_total_solid_volume_mm3": actual_volume,
                })
                continue
            actual_transform = _occurrence_transform(occurrence)
            if _transform_is_stale(actual_transform, part["expected_transform"]):
                failures.add("stale-verification")
                stale_parts.append({
                    "path": path,
                    "reason": "transform-drifted",
                    "expected_transform": part["expected_transform"],
                    "actual_transform": actual_transform,
                })
                continue
            resolved[path] = {
                "occurrence": occurrence,
                "body": body,
                "actual_bounds_mm": actual_bounds,
                "actual_total_solid_volume_mm3": actual_volume,
                "transform": actual_transform,
            }

        export_dir = EXPORT_SPECS["export_dir"]
        existing_outputs = []
        if not os.path.isdir(export_dir) or not os.access(export_dir, os.W_OK):
            failures.add("missing-output-dir")
        else:
            target_names = [EXPORT_SPECS["index_filename"]]
            for part in EXPORT_SPECS["parts"]:
                for export_format in EXPORT_SPECS["formats"]:
                    target_names.append(part["filenames"][export_format])
            for name in target_names:
                if os.path.lexists(os.path.join(export_dir, name)):
                    existing_outputs.append(name)
            if existing_outputs:
                failures.add("output-exists")

        if failures:
            report_attempted = True
            _emit({
                "kind": "export-handoff",
                "project": PROJECT_NAME,
                "manifest_sha256": MANIFEST_SHA256,
                "verification_report_sha256": EXPORT_SPECS["verification_report_sha256"],
                "ok": False,
                "failures": sorted(failures),
                "resolution_errors": resolution_errors,
                "stale_parts": stale_parts,
                "existing_outputs": sorted(existing_outputs),
                "export_dir": export_dir,
            })
            raise RuntimeError("Fusion export failed closed: " + ", ".join(sorted(failures)))

        export_run_id = uuid.uuid4().hex
        artifacts = []
        try:
            for part in EXPORT_SPECS["parts"]:
                path = part["path"]
                resolution = resolved[path]
                occurrence = resolution["occurrence"]
                body = resolution["body"]
                for export_format in EXPORT_SPECS["formats"]:
                    filename = part["filenames"][export_format]
                    target = os.path.join(export_dir, filename)
                    constructor = FORMAT_OPTION_ATTRIBUTES[export_format]
                    if export_format == "step":
                        # STEP options take a Component (live-verified: the root-context
                        # occurrence proxy is rejected); the occurrence transform is
                        # recorded per artifact so the assembly frame stays recoverable.
                        options = export_manager.createSTEPExportOptions(target, occurrence.component)
                        export_scope = "component"
                    else:
                        options = getattr(export_manager, constructor)(body, target)
                        export_scope = "body"
                    if not options:
                        raise RuntimeError("Fusion failed to create export options for " + filename)
                    if os.path.lexists(target):
                        raise RuntimeError("Output appeared after preflight; refusing to overwrite " + target)
                    created_paths.append(target)
                    executed = export_manager.execute(options)
                    if not executed or not os.path.isfile(target) or os.path.getsize(target) <= 0:
                        raise RuntimeError("Fusion export did not produce " + target)
                    artifact_entry = {
                        "part_path": path,
                        "body_name": body.name,
                        "format": export_format,
                        "filename": filename,
                        "export_scope": export_scope,
                        "export_options": {"constructor": constructor, "defaults": True},
                        "byte_size": os.path.getsize(target),
                        "sha256": _file_sha256(target),
                        "transform": resolution["transform"],
                        "bounds_mm": resolution["actual_bounds_mm"],
                        "total_solid_volume_mm3": resolution["actual_total_solid_volume_mm3"],
                    }
                    if "manufacturing_intent" in part:
                        artifact_entry["manufacturing_intent"] = part["manufacturing_intent"]
                    artifacts.append(artifact_entry)

            index = {
                "kind": "export-handoff",
                "project": PROJECT_NAME,
                "manifest_sha256": MANIFEST_SHA256,
                "verification_report_sha256": EXPORT_SPECS["verification_report_sha256"],
                "export_run_id": export_run_id,
                "document_name": target_document.name,
                "document_saved": document_saved,
                "document_modified": bool(getattr(target_document, "isModified", False)),
                "document_version": document_version,
                "units": units,
                "export_dir": export_dir,
                "formats": EXPORT_SPECS["formats"],
                "artifacts": artifacts,
                "verification_binding_residual": "__BINDING_RESIDUAL__",
            }
            if "material_decision" in EXPORT_SPECS:
                index["material_decision"] = EXPORT_SPECS["material_decision"]
            design_state_rows = []
            for artifact in artifacts:
                design_state_rows.append(
                    "| " + artifact["filename"]
                    + " | " + json.dumps(document_version)
                    + " | " + artifact["part_path"]
                    + " | " + (units if units else "unknown")
                    + " | " + artifact["export_options"]["constructor"] + " (defaults)"
                    + " | " + str(artifact["byte_size"])
                    + " | " + artifact["sha256"]
                    + " | " + export_run_id[:8]
                    + " | " + EXPORT_SPECS["verification_report_sha256"][:12]
                    + " | \\u2014 | |"
                )
            index_path = os.path.join(export_dir, EXPORT_SPECS["index_filename"])
            with open(index_path, "x", encoding="utf-8") as handle:
                created_paths.append(index_path)
                handle.write(json.dumps(index, indent=2, sort_keys=True))
                handle.write("\\n")
        except Exception as error:
            created_and_removed = list(created_paths)
            cleanup_errors = _remove_created(created_paths)
            report_attempted = True
            failure_tokens = ["export-incomplete"]
            if cleanup_errors:
                failure_tokens.append("cleanup-incomplete")
            _emit({
                "kind": "export-handoff",
                "project": PROJECT_NAME,
                "manifest_sha256": MANIFEST_SHA256,
                "verification_report_sha256": EXPORT_SPECS["verification_report_sha256"],
                "ok": False,
                "failures": failure_tokens,
                "error": str(error),
                "created_and_removed": created_and_removed,
                "cleanup_errors": cleanup_errors,
                "traceback": traceback.format_exc(),
            })
            if cleanup_errors:
                raise RuntimeError(
                    "Fusion export failed and cleanup left partial artifacts: " + "; ".join(cleanup_errors)
                ) from error
            raise

        report = dict(index)
        report["ok"] = True
        report["design_state_rows"] = design_state_rows
        report_attempted = True
        _emit(report)
    except Exception as error:
        if not report_attempted:
            report_attempted = True
            _emit({
                "kind": "export-handoff",
                "project": PROJECT_NAME,
                "manifest_sha256": MANIFEST_SHA256,
                "ok": False,
                "error": str(error),
                "traceback": traceback.format_exc(),
            })
        raise
'''
    transaction = transaction.replace("__BINDING_RESIDUAL__", EXPORT_BINDING_RESIDUAL)
    return _script_prelude(manifest) + transaction.replace("__EXPORT_SPECS__", _json_literal(specs))


def example_verification_report(manifest: Manifest) -> dict[str, Any]:
    """Deterministic sample verification report for the checked-in export example.

    Bounds come from the positive-control box contract, so the committed sample
    stays consistent with the golden-path geometry. Live acceptance always uses
    a real verification report instead of this sample.
    """
    from .positive_control import _bounds, _box_specs
    from .scripts import manifest_sha256

    bounds_by_path = {}
    volume_by_path = {}
    for spec in _box_specs(manifest):
        minimum, maximum = _bounds(spec)
        bounds_by_path[spec["path"]] = {"min": minimum, "max": maximum}
        volume_by_path[spec["path"]] = float(
            spec["size_mm"][0] * spec["size_mm"][1] * spec["size_mm"][2]
        )
    boxes = {}
    geometry = {}
    transforms = {}
    for path in manifest.verification.get("expected_print_parts", []):
        if path not in bounds_by_path:
            raise ValueError(f"Positive-control geometry does not cover print part {path!r}.")
        boxes[path] = bounds_by_path[path]
        # Solid rectangular boxes placed at the root: volume is the product of the
        # sides and the occurrence carries no transform of its own.
        geometry[path] = {"total_solid_volume_mm3": volume_by_path[path]}
        transforms[path] = [
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ]
    return {
        "kind": "verification",
        "ok": True,
        "sample": True,
        "project": manifest.project_name,
        "manifest_sha256": manifest_sha256(manifest),
        "brep_bounding_boxes_mm": boxes,
        "geometry": geometry,
        "occurrence_transforms": transforms,
        "note": "Sample report for the checked-in export example; live runs bind a real verification report.",
    }


def example_verification_report_bytes(manifest: Manifest) -> bytes:
    report = example_verification_report(manifest)
    return (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")


def example_export_config(manifest: Manifest) -> ExportConfig:
    report_bytes = example_verification_report_bytes(manifest)
    return ExportConfig(
        export_dir=EXAMPLE_EXPORT_DIR,
        formats=("step", "3mf"),
        verification_report_sha256=hashlib.sha256(report_bytes).hexdigest(),
        verification_binding=verification_binding_from_report(manifest, json.loads(report_bytes)),
    )


def emit_export_example_script(manifest: Manifest) -> str:
    """Byte-stable example emitter used by the checked-in generated script."""
    return emit_export_script(manifest, example_export_config(manifest))
