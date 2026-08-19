import json
import traceback
import adsk.core
import adsk.fusion

PROJECT_NAME = 'wearable-controller-pod'
FUSION_DOCUMENT_NAME = 'Wearable Controller Pod'
MANIFEST_SHA256 = '8cec5b3c46476208d13e741828e906dc3c8b15513e746a8783da8dbe17180756'
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

BOX_SPECS = json.loads('[{"body_name":"POSITIVE_CONTROL__PACK_PD_TRIGGER","origin_mm":[0.0,0.0,0.0],"path":"00_REFERENCES/PACK__PD_TRIGGER__EXACT_OR_CONSERVATIVE","size_mm":[35.0,13.0,5.0]},{"body_name":"POSITIVE_CONTROL__PACK_EKYLIN","origin_mm":[120.0,0.0,0.0],"path":"00_REFERENCES/PACK__EKYLIN__EXACT_OR_CONSERVATIVE","size_mm":[62.0,31.0,27.0]},{"body_name":"POSITIVE_CONTROL__KEEP_USB_C_INSERTION","origin_mm":[0.0,0.0,0.0],"path":"00_REFERENCES/KEEP__USB_C_INSERTION","size_mm":[20.0,20.0,5.0]},{"body_name":"POSITIVE_CONTROL__KEEP_EKYLIN_WIRE_BENDS","origin_mm":[120.0,0.0,0.0],"path":"00_REFERENCES/KEEP__EKYLIN_WIRE_BENDS","size_mm":[20.0,20.0,5.0]},{"body_name":"POSITIVE_CONTROL__PROD_BASE","origin_mm":[0.0,50.0,0.0],"path":"10_PRODUCT/PROD__BASE","size_mm":[100.0,60.0,2.0]},{"body_name":"POSITIVE_CONTROL__PROD_LID","origin_mm":[0.0,0.0,10.0],"path":"10_PRODUCT/PROD__LID","size_mm":[35.0,13.0,2.0]},{"body_name":"POSITIVE_CONTROL__VAL_PD_FIT_COUPON","origin_mm":[0.0,100.0,0.0],"path":"90_VALIDATION/VAL__PD_FIT_COUPON","size_mm":[10.0,10.0,2.0]}]')
ATTRIBUTE_GROUP = "fusion_parametric_design"
GEOMETRY_TOLERANCE_MM = 1e-6
IDENTITY_MATRIX = tuple(adsk.core.Matrix3D.create().asArray())


def _attribute_value(component, name):
    attribute = component.attributes.itemByName(ATTRIBUTE_GROUP, name)
    return attribute.value if attribute else None


def _require_scaffold_identity(occurrence, path):
    component = occurrence.component
    if _attribute_value(component, "managed") != "true":
        raise RuntimeError("Positive control requires scaffold identity for " + path + ".")
    if _attribute_value(component, "manifest_sha256") != MANIFEST_SHA256:
        raise RuntimeError("Positive control scaffold manifest identity mismatch for " + path + ".")


def _require_identity_transform(occurrence, path):
    transform = getattr(occurrence, "transform2", None)
    if not transform:
        raise RuntimeError("Positive control requires Occurrence.transform2 for " + path + ".")
    values = tuple(float(value) for value in transform.asArray())
    if len(values) != len(IDENTITY_MATRIX) or any(
        abs(actual - expected) > GEOMETRY_TOLERANCE_MM / 1000.0
        for actual, expected in zip(values, IDENTITY_MATRIX)
    ):
        raise RuntimeError(
            "Positive control requires identity occurrence transforms; "
            + path
            + " is not identity."
        )


def _expected_bounds(spec):
    origin = spec["origin_mm"]
    size = spec["size_mm"]
    return {
        "min": list(origin),
        "max": [origin[index] + size[index] for index in range(3)],
    }


def _validate_geometry(occurrence, spec):
    path = spec["path"]
    _require_identity_transform(occurrence, path)
    bodies = occurrence.component.bRepBodies
    if bodies.count != 1:
        raise RuntimeError(
            "Positive control requires exactly one B-Rep body for "
            + path
            + "; found "
            + str(bodies.count)
            + "."
        )
    body = bodies.item(0)
    if body.name != spec["body_name"]:
        raise RuntimeError(
            "Positive control body name mismatch for "
            + path
            + ": expected "
            + repr(spec["body_name"])
            + ", found "
            + repr(body.name)
            + "."
        )
    volume_mm3 = float(body.volume) * 1000.0
    if not body.isSolid or volume_mm3 <= 1e-9:
        raise RuntimeError("Positive control body is not a positive-volume solid: " + path + ".")
    actual_bounds = _bbox_mm(occurrence)
    expected_bounds = _expected_bounds(spec)
    for bound in ("min", "max"):
        for index, (actual, expected) in enumerate(
            zip(actual_bounds[bound], expected_bounds[bound])
        ):
            if abs(float(actual) - float(expected)) > GEOMETRY_TOLERANCE_MM:
                raise RuntimeError(
                    "Positive control geometry mismatch for "
                    + path
                    + ": expected complete bounds "
                    + repr(expected_bounds)
                    + ", found "
                    + repr(actual_bounds)
                    + "."
                )
    return {
        "path": path,
        "body_name": body.name,
        "expected_bounds_mm": expected_bounds,
        "actual_bounds_mm": actual_bounds,
        "volume_mm3": volume_mm3,
        "is_solid": bool(body.isSolid),
        "ok": True,
    }, body


def _is_valid(entity):
    if not entity:
        return False
    try:
        return bool(entity.isValid)
    except Exception:
        return True


def _cleanup_pair(body, base_feature, editing=False):
    attempts = []
    if editing and base_feature:
        try:
            if not base_feature.finishEdit():
                attempts.append("finishEdit returned false")
        except Exception as error:
            attempts.append("finishEdit failed: " + str(error))
    for label, entity in (("body", body), ("base feature", base_feature)):
        if not entity:
            continue
        try:
            entity.deleteMe()
        except Exception as error:
            attempts.append(label + " delete failed: " + str(error))
    remaining = [label for label, entity in (("body", body), ("base feature", base_feature)) if _is_valid(entity)]
    if not remaining:
        return []
    detail = "; ".join(attempts) if attempts else "delete left valid entities"
    return [", ".join(remaining) + ": " + detail]


def _create_body(occurrence, spec):
    length_mm, width_mm, height_mm = spec["size_mm"]
    x_mm, y_mm, z_mm = spec["origin_mm"]
    center = adsk.core.Point3D.create(
        (x_mm + length_mm / 2.0) / 10.0,
        (y_mm + width_mm / 2.0) / 10.0,
        (z_mm + height_mm / 2.0) / 10.0,
    )
    box = adsk.core.OrientedBoundingBox3D.create(
        center,
        adsk.core.Vector3D.create(1.0, 0.0, 0.0),
        adsk.core.Vector3D.create(0.0, 1.0, 0.0),
        length_mm / 10.0,
        width_mm / 10.0,
        height_mm / 10.0,
    )
    temporary_body = adsk.fusion.TemporaryBRepManager.get().createBox(box)
    if not temporary_body:
        raise RuntimeError("Fusion failed to create temporary box: " + spec["path"])

    component = occurrence.component
    base_feature = component.features.baseFeatures.add()
    if not base_feature:
        raise RuntimeError("Fusion failed to create a parametric base feature: " + spec["path"])
    body = None
    editing = False
    try:
        if not base_feature.startEdit():
            raise RuntimeError("Fusion failed to enter base-feature edit mode: " + spec["path"])
        editing = True
        body = component.bRepBodies.add(temporary_body, base_feature)
        if not body:
            raise RuntimeError("Fusion failed to persist positive-control body: " + spec["path"])
        body.name = spec["body_name"]
        if not base_feature.finishEdit():
            raise RuntimeError("Fusion failed to finish base-feature edit mode: " + spec["path"])
        editing = False
        return body, base_feature
    except Exception as error:
        cleanup_errors = _cleanup_pair(body, base_feature, editing)
        if cleanup_errors:
            raise RuntimeError(
                "Positive-control creation failed and cleanup left partial artifacts for "
                + spec["path"]
                + ": "
                + "; ".join(cleanup_errors)
            ) from error
        raise


def _cleanup_created(resources):
    errors = []
    for body, base_feature in reversed(resources):
        errors.extend(_cleanup_pair(body, base_feature))
    return errors


def run(context):
    report_attempted = False
    created_resources = []
    try:
        app, design = _active_design()
        target_document = _require_target_document(app)
        if bool(getattr(target_document, "isSaved", True)):
            raise RuntimeError("Positive control requires an unsaved target document.")
        if design.designType != adsk.fusion.DesignTypes.ParametricDesignType:
            raise RuntimeError(
                "Positive-control geometry requires a parametric design; "
                "refusing a destructive design-type change."
            )
        _pump_events(app, design, target_document)
        _, occurrence_map, duplicate_semantic_paths = _root_context_occurrence_map(design.rootComponent)
        if duplicate_semantic_paths:
            raise RuntimeError(
                "Positive control refuses duplicate semantic component paths: "
                + repr(duplicate_semantic_paths)
                + "."
            )
        missing_paths = sorted(spec["path"] for spec in BOX_SPECS if spec["path"] not in occurrence_map)
        if missing_paths:
            raise RuntimeError("Positive-control scaffold components are missing: " + ", ".join(missing_paths))
        for spec in BOX_SPECS:
            occurrence = occurrence_map[spec["path"]]
            _require_scaffold_identity(occurrence, spec["path"])
            _require_identity_transform(occurrence, spec["path"])

        created = []
        reused = []
        for index, spec in enumerate(BOX_SPECS):
            occurrence = occurrence_map[spec["path"]]
            if occurrence.component.bRepBodies.count:
                _, body = _validate_geometry(occurrence, spec)
                reused.append(spec["path"])
            else:
                body, base_feature = _create_body(occurrence, spec)
                created_resources.append((body, base_feature))
                _validate_geometry(occurrence, spec)
                created.append(spec["path"])
            _pump_events_periodically(app, design, target_document, index)

        _pump_events(app, design, target_document)
        compute_invoked = design.computeAll()
        _pump_events(app, design, target_document)
        body_reports = []
        for spec in BOX_SPECS:
            body_report, _ = _validate_geometry(occurrence_map[spec["path"]], spec)
            body_reports.append(body_report)
        timeline = _timeline_health(design)
        report = {
            "kind": "positive-control",
            "project": PROJECT_NAME,
            "manifest_sha256": MANIFEST_SHA256,
            "document_name": target_document.name,
            "created": sorted(created),
            "reused": sorted(reused),
            "bodies": body_reports,
            "compute_invoked": bool(compute_invoked),
            "timeline": timeline,
            "ok": bool(compute_invoked) and not timeline["unhealthy"],
        }
        report_attempted = True
        _emit(report)
        if not report["ok"]:
            raise RuntimeError("Positive-control geometry did not satisfy its report contract.")
    except Exception as error:
        cleanup_errors = _cleanup_created(created_resources)
        if cleanup_errors:
            cleanup_failure = RuntimeError(
                "Positive-control transaction failed and cleanup left partial artifacts: "
                + "; ".join(cleanup_errors)
            )
        else:
            cleanup_failure = None
        if not report_attempted:
            report_attempted = True
            _emit({
                "kind": "positive-control",
                "project": PROJECT_NAME,
                "manifest_sha256": MANIFEST_SHA256,
                "ok": False,
                "error": str(cleanup_failure or error),
                "traceback": traceback.format_exc(),
            })
        if cleanup_failure:
            raise cleanup_failure from error
        raise
