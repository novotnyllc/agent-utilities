import json
import traceback
import adsk.core
import adsk.fusion

PROJECT_NAME = 'wearable-controller-pod'
FUSION_DOCUMENT_NAME = 'Wearable Controller Pod'
MANIFEST_SHA256 = '7f3e64dbc70edafb0cc28c8082f85fd9209f178e5509aaf2afbc8e89f6884e5e'
REPORT_BEGIN = 'FUSION_DESIGN_REPORT_BEGIN'
REPORT_END = 'FUSION_DESIGN_REPORT_END'

def _emit(report):
    print(REPORT_BEGIN)
    print(json.dumps(report, sort_keys=True, separators=(",", ":"), default=str))
    print(REPORT_END)


def _active_design():
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if not design:
        raise RuntimeError("The active Fusion product is not a Design.")
    return app, design


def _require_target_document(app):
    active_document = app.activeDocument
    active_name = active_document.name if active_document else None
    if active_name != FUSION_DOCUMENT_NAME:
        raise RuntimeError(
            "Active Fusion document " + repr(active_name)
            + " does not match manifest target " + repr(FUSION_DOCUMENT_NAME) + "."
        )
    return active_document


def _pump_events(app, design, target_document):
    adsk.doEvents()
    active_app, active_design = _active_design()
    if (
        active_app != app
        or app.activeDocument != target_document
        or target_document.name != FUSION_DOCUMENT_NAME
        or active_design != design
    ):
        raise RuntimeError("Active Fusion document changed while the transaction was running; stopping before further work.")


def _pump_events_periodically(app, design, target_document, index):
    if (index + 1) % 10 == 0:
        _pump_events(app, design, target_document)


def _walk_component(component, prefix=""):
    """Walk native component definitions; use only for authoring/scaffolding."""
    paths = []
    mapping = {}
    occurrences = component.occurrences
    for index in range(occurrences.count):
        occurrence = occurrences.item(index)
        name = occurrence.component.name
        path = name if not prefix else prefix + "/" + name
        paths.append(path)
        mapping[path] = occurrence
        child_paths, child_mapping = _walk_component(occurrence.component, path)
        paths.extend(child_paths)
        mapping.update(child_mapping)
    return paths, mapping


def _semantic_path_from_full_path(full_path_name, root_component_name):
    """Convert Fusion's `A:1+B:1` occurrence path to the manifest's `A/B` path."""
    parts = []
    for occurrence_name in [part for part in str(full_path_name).split("+") if part]:
        head, separator, suffix = occurrence_name.rpartition(":")
        component_name = head if separator and suffix.isdigit() else occurrence_name
        parts.append(component_name)
    if parts and parts[0] == root_component_name:
        parts = parts[1:]
    return "/".join(parts)


def _root_context_occurrence_map(root_component):
    """Return root-context occurrence proxies keyed by semantic component path."""
    mapping = {}
    duplicates = {}
    root_occurrences = root_component.allOccurrences
    for index in range(root_occurrences.count):
        occurrence = root_occurrences.item(index)
        semantic_path = _semantic_path_from_full_path(occurrence.fullPathName, root_component.name)
        if not semantic_path:
            continue
        if semantic_path in mapping:
            duplicates.setdefault(semantic_path, [mapping[semantic_path].fullPathName]).append(
                occurrence.fullPathName
            )
            continue
        mapping[semantic_path] = occurrence
    return sorted(mapping), mapping, {key: sorted(value) for key, value in duplicates.items()}


def _box_to_mm(box):
    if not box:
        raise RuntimeError("No bounding box is available for this occurrence.")
    return {
        "min": [box.minPoint.x * 10.0, box.minPoint.y * 10.0, box.minPoint.z * 10.0],
        "max": [box.maxPoint.x * 10.0, box.maxPoint.y * 10.0, box.maxPoint.z * 10.0],
    }


def _bbox_mm(occurrence):
    """Tight B-Rep-only bounds; Fusion ignores meshes for preciseBoundingBox."""
    return _box_to_mm(occurrence.preciseBoundingBox)


def _all_geometry_bbox_mm(occurrence):
    return _box_to_mm(
        occurrence.boundingBox2(adsk.fusion.BoundingBoxEntityTypes.AllEntitiesBoundingBoxEntityType)
    )


def _body_summary(occurrence):
    bodies = occurrence.bRepBodies
    solid_body_count = 0
    surface_body_count = 0
    total_solid_volume_mm3 = 0.0
    body_rows = []
    for index in range(bodies.count):
        body = bodies.item(index)
        volume_mm3 = float(body.volume) * 1000.0
        is_solid = bool(body.isSolid)
        if is_solid and volume_mm3 > 1e-9:
            solid_body_count += 1
            total_solid_volume_mm3 += volume_mm3
        else:
            surface_body_count += 1
        body_rows.append({
            "name": body.name,
            "is_solid": is_solid,
            "volume_mm3": volume_mm3,
        })
    try:
        mesh_body_count = occurrence.component.meshBodies.count
    except Exception:
        mesh_body_count = None
    return {
        "brep_body_count": bodies.count,
        "solid_body_count": solid_body_count,
        "surface_or_zero_volume_body_count": surface_body_count,
        "mesh_body_count": mesh_body_count,
        "total_solid_volume_mm3": total_solid_volume_mm3,
        "has_positive_solid": solid_body_count > 0 and total_solid_volume_mm3 > 1e-9,
        "bodies": body_rows,
    }


def _timeline_health(design):
    unhealthy = []
    informational = []
    healthy_state = adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
    warning_state = adsk.fusion.FeatureHealthStates.WarningFeatureHealthState
    error_state = adsk.fusion.FeatureHealthStates.ErrorFeatureHealthState
    rolled_back_state = adsk.fusion.FeatureHealthStates.RolledBackFeatureHealthState
    suppressed_state = adsk.fusion.FeatureHealthStates.SuppressedFeatureHealthState
    unknown_state = adsk.fusion.FeatureHealthStates.UnknownFeatureHealthState

    for index in range(design.timeline.count):
        item = design.timeline.item(index)
        state = item.healthState
        row = {"index": index, "health_state": str(state)}
        try:
            entity = item.entity
            message = getattr(entity, "errorOrWarningMessage", "") if entity else ""
            if message:
                row["message"] = message
        except Exception:
            pass

        if state in (warning_state, error_state, rolled_back_state):
            unhealthy.append(row)
        elif state in (suppressed_state, unknown_state):
            informational.append(row)
        elif state != healthy_state:
            unhealthy.append(row)

    return {
        "count": design.timeline.count,
        "unhealthy": unhealthy,
        "informational": informational,
    }

import hashlib
import os
import uuid

EXPORT_SPECS = json.loads('{"export_dir":"FUSION_EXPORT_DIR","formats":["step","3mf"],"index_filename":"export-index__7f3e64db.json","parts":[{"expected_bounds_mm":{"max":[100.0,110.0,2.0],"min":[0.0,50.0,0.0]},"filenames":{"3mf":"wearable-controller-pod__10_product-prod__base__7f3e64db.3mf","step":"wearable-controller-pod__10_product-prod__base__7f3e64db.step"},"path":"10_PRODUCT/PROD__BASE"},{"expected_bounds_mm":{"max":[35.0,13.0,12.0],"min":[0.0,0.0,10.0]},"filenames":{"3mf":"wearable-controller-pod__10_product-prod__lid__7f3e64db.3mf","step":"wearable-controller-pod__10_product-prod__lid__7f3e64db.step"},"path":"10_PRODUCT/PROD__LID"},{"expected_bounds_mm":{"max":[10.0,110.0,2.0],"min":[0.0,100.0,0.0]},"filenames":{"3mf":"wearable-controller-pod__90_validation-val__pd_fit_coupon__7f3e64db.3mf","step":"wearable-controller-pod__90_validation-val__pd_fit_coupon__7f3e64db.step"},"path":"90_VALIDATION/VAL__PD_FIT_COUPON"}],"verification_report_sha256":"d0ce59a4a25e1950ea27145cefe1ce33c774a50a63360d92978aaae38da02d0b"}')
EXPORT_STALENESS_TOLERANCE_MM = 1e-3
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
            resolved[path] = {
                "occurrence": occurrence,
                "body": body,
                "actual_bounds_mm": actual_bounds,
                "transform": _occurrence_transform(occurrence),
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
                    artifacts.append({
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
                    })

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
            }
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
                    + " | \u2014 | |"
                )
            index_path = os.path.join(export_dir, EXPORT_SPECS["index_filename"])
            with open(index_path, "x", encoding="utf-8") as handle:
                created_paths.append(index_path)
                handle.write(json.dumps(index, indent=2, sort_keys=True))
                handle.write("\n")
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
