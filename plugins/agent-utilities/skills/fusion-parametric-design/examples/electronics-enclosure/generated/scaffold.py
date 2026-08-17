import json
import os
import secrets
import sys
import tempfile
import traceback
import adsk.core
import adsk.fusion

PROJECT_NAME = 'wearable-controller-pod'
FUSION_DOCUMENT_NAME = 'Wearable Controller Pod'
MANIFEST_SHA256 = '7f3e64dbc70edafb0cc28c8082f85fd9209f178e5509aaf2afbc8e89f6884e5e'
REPORT_BEGIN = 'FUSION_DESIGN_REPORT_BEGIN'
REPORT_END = 'FUSION_DESIGN_REPORT_END'
REPORT_PATH = None
REPORT_RUN_ID = None


class ReportDeliveryError(RuntimeError):
    pass


def _new_report_run_id():
    return REPORT_RUN_ID or secrets.token_hex(32)


def _emit(report, report_run_id=None):
    report_run_id = report_run_id or _new_report_run_id()
    envelope = dict(report)
    envelope["report_run_id"] = report_run_id
    payload = json.dumps(envelope, sort_keys=True, separators=(",", ":"), default=str)

    temporary_path = None
    temporary_fd = None
    try:
        if REPORT_PATH:
            if os.path.lexists(REPORT_PATH):
                raise FileExistsError("report path already exists")
            temporary_fd, temporary_path = tempfile.mkstemp(
                prefix=".fusion-design-report-", dir=os.path.dirname(REPORT_PATH)
            )
            with os.fdopen(temporary_fd, "w", encoding="utf-8") as report_file:
                temporary_fd = None
                report_file.write(payload)
                report_file.write("\n")
                report_file.flush()
                os.fsync(report_file.fileno())
            os.link(temporary_path, REPORT_PATH)
            os.unlink(temporary_path)
            temporary_path = None
        print(REPORT_BEGIN)
        print(payload)
        print(REPORT_END)
    except Exception as error:
        if temporary_fd is not None:
            try:
                os.close(temporary_fd)
            except OSError:
                pass
        if temporary_path:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass
        destination = REPORT_PATH or "stdout"
        message = "Failed to deliver Fusion JSON report to " + destination + ": " + str(error)
        print(message, file=sys.stderr)
        raise ReportDeliveryError(message) from error


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

COMPONENT_PATHS = json.loads('["00_REFERENCES","00_REFERENCES/REF__PD_TRIGGER__PARAMETRIC","00_REFERENCES/PACK__PD_TRIGGER__EXACT_OR_CONSERVATIVE","00_REFERENCES/KEEP__USB_C_INSERTION","00_REFERENCES/REF__EKYLIN__PARAMETRIC","00_REFERENCES/PACK__EKYLIN__EXACT_OR_CONSERVATIVE","00_REFERENCES/KEEP__EKYLIN_WIRE_BENDS","10_PRODUCT","10_PRODUCT/PROD__BASE","10_PRODUCT/PROD__LID","20_FIXTURES","90_VALIDATION","90_VALIDATION/VAL__PD_FIT_COUPON"]')
ATTRIBUTE_GROUP = "fusion_parametric_design"


def _find_child(parent_component, name):
    occurrences = parent_component.occurrences
    for index in range(occurrences.count):
        occurrence = occurrences.item(index)
        if occurrence.component.name == name:
            return occurrence
    return None


def _ensure_component_attribute(component, name, value):
    existing = component.attributes.itemByName(ATTRIBUTE_GROUP, name)
    if existing and existing.value == value:
        return False
    if not component.attributes.add(ATTRIBUTE_GROUP, name, value):
        raise RuntimeError("Fusion failed to write component attribute " + name)
    return True


def _ensure_component_path(root_component, path):
    parent = root_component
    created = []
    attribute_updates = []
    current_parts = []
    for name in [part for part in path.split("/") if part]:
        current_parts.append(name)
        occurrence = _find_child(parent, name)
        if not occurrence:
            occurrence = parent.occurrences.addNewComponent(adsk.core.Matrix3D.create())
            if not occurrence:
                raise RuntimeError("Fusion failed to create component path " + "/".join(current_parts))
            occurrence.component.name = name
            created.append("/".join(current_parts))
        changed_attributes = []
        if _ensure_component_attribute(occurrence.component, "managed", "true"):
            changed_attributes.append("managed")
        if _ensure_component_attribute(occurrence.component, "manifest_sha256", MANIFEST_SHA256):
            changed_attributes.append("manifest_sha256")
        if changed_attributes:
            attribute_updates.append({
                "component_path": "/".join(current_parts),
                "attributes": changed_attributes,
            })
        parent = occurrence.component
    return created, attribute_updates


def run(context):
    report_run_id = _new_report_run_id()
    report_attempted = False
    try:
        app, design = _active_design()
        target_document = _require_target_document(app)
        if design.designType != adsk.fusion.DesignTypes.ParametricDesignType:
            raise RuntimeError("Component scaffolding requires a parametric design; refusing a destructive design-type change.")
        _, _, preexisting_duplicate_semantic_paths = _root_context_occurrence_map(design.rootComponent)
        if preexisting_duplicate_semantic_paths:
            report_attempted = True
            _emit({
                "kind": "component-scaffold",
                "project": PROJECT_NAME,
                "manifest_sha256": MANIFEST_SHA256,
                "created": [],
                "attribute_updates": [],
                "duplicate_semantic_paths": preexisting_duplicate_semantic_paths,
                "ok": False,
            }, report_run_id)
            raise RuntimeError("Semantic component paths are already ambiguous; refusing to scaffold into an ambiguous tree.")
        created = []
        attribute_updates = []
        for index, path in enumerate(sorted(COMPONENT_PATHS, key=lambda item: (item.count("/"), item))):
            path_created, path_attribute_updates = _ensure_component_path(design.rootComponent, path)
            created.extend(path_created)
            attribute_updates.extend(path_attribute_updates)
            _pump_events_periodically(app, design, target_document, index)
        _pump_events(app, design, target_document)
        compute_invoked = design.computeAll()
        _pump_events(app, design, target_document)
        # Read the post-yield state once; pre-compute observations can be stale
        # when a user edit changes this same document during event processing.
        component_paths, _, duplicate_semantic_paths = _root_context_occurrence_map(design.rootComponent)
        missing_component_paths = sorted(set(COMPONENT_PATHS) - set(component_paths))
        timeline = _timeline_health(design)
        report = {
            "kind": "component-scaffold",
            "project": PROJECT_NAME,
            "manifest_sha256": MANIFEST_SHA256,
            "created": sorted(set(created)),
            "attribute_updates": attribute_updates,
            "component_paths": component_paths,
            "missing_component_paths": missing_component_paths,
            "duplicate_semantic_paths": duplicate_semantic_paths,
            "compute_invoked": compute_invoked,
            "timeline": timeline,
            "ok": bool(compute_invoked) and not timeline["unhealthy"] and not duplicate_semantic_paths and not missing_component_paths,
        }
        report_attempted = True
        _emit(report, report_run_id)
        if not compute_invoked:
            raise RuntimeError("Fusion Compute All did not complete; see the emitted report.")
        if timeline["unhealthy"]:
            raise RuntimeError("Compute completed with unhealthy timeline objects; see the emitted report.")
        if missing_component_paths:
            raise RuntimeError("Declared component paths are still missing; see the emitted report.")
        if duplicate_semantic_paths:
            raise RuntimeError("Semantic component paths are ambiguous; rename duplicate managed occurrences.")
    except Exception as error:
        if not report_attempted:
            report_attempted = True
            try:
                _emit({"kind": "component-scaffold", "ok": False, "error": str(error), "traceback": traceback.format_exc()}, report_run_id)
            except ReportDeliveryError:
                pass
        raise
