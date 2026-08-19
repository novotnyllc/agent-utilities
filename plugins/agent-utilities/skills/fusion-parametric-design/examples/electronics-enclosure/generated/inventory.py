import json
import traceback
import adsk.core
import adsk.fusion

PROJECT_NAME = 'wearable-controller-pod'
FUSION_DOCUMENT_NAME = 'Wearable Controller Pod'
MANIFEST_SHA256 = 'dea2a647d99f41c6f2829a67e92a66f634eba5f838d056d86464efa3fef3a642'
REPORT_BEGIN = 'FUSION_DESIGN_REPORT_BEGIN'
REPORT_END = 'FUSION_DESIGN_REPORT_END'


class DocumentChangedError(RuntimeError):
    """The active document is no longer ours; the transaction must touch nothing further."""


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
        raise DocumentChangedError("Active Fusion document changed while the transaction was running; stopping before further work.")


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


def _occurrence_state(occurrence):
    """Participation state for a root-context occurrence.

    A suppressed occurrence is still returned by allOccurrences and still owns
    its component's bodies, but contributes no geometry to interference or
    measurement -- so 'no interference' and 'not in the model' look identical
    unless this state is recorded.
    """
    state = {}
    for key, attribute in (
        ("is_suppressed", "isSuppressed"),
        ("is_light_bulb_on", "isLightBulbOn"),
        ("is_visible", "isVisible"),
    ):
        try:
            value = getattr(occurrence, attribute)
        except Exception:
            value = None
        state[key] = None if value is None else bool(value)
    return state


def _timeline_health(design):
    unhealthy = []
    suppressed = []
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
        elif state == suppressed_state:
            # Suppression silently changes the shape away from recorded intent,
            # so it is reported separately instead of buried in informational.
            suppressed.append(row)
        elif state == unknown_state:
            informational.append(row)
        elif state != healthy_state:
            unhealthy.append(row)

    return {
        "count": design.timeline.count,
        "unhealthy": unhealthy,
        "suppressed": suppressed,
        "informational": informational,
    }

EXPECTED_COMPONENT_PATHS = json.loads('["00_REFERENCES","00_REFERENCES/REF__PD_TRIGGER__PARAMETRIC","00_REFERENCES/PACK__PD_TRIGGER__EXACT_OR_CONSERVATIVE","00_REFERENCES/KEEP__USB_C_INSERTION","00_REFERENCES/REF__EKYLIN__PARAMETRIC","00_REFERENCES/PACK__EKYLIN__EXACT_OR_CONSERVATIVE","00_REFERENCES/KEEP__EKYLIN_WIRE_BENDS","10_PRODUCT","10_PRODUCT/PROD__BASE","10_PRODUCT/PROD__LID","20_FIXTURES","90_VALIDATION","90_VALIDATION/VAL__PD_FIT_COUPON"]')


def run(context):
    report_attempted = False
    try:
        app, design = _active_design()
        target_document = _require_target_document(app)
        user_parameters = design.userParameters
        for index in range(user_parameters.count):
            _pump_events_periodically(app, design, target_document, index)
        _pump_events(app, design, target_document)

        # The report snapshot intentionally follows the last event pump.  Do not
        # retain observations made before a yield: same-document UI edits are valid.
        parameters = {}
        for index in range(user_parameters.count):
            parameter = user_parameters.item(index)
            parameters[parameter.name] = {
                "expression": parameter.expression,
                "units": parameter.unit,
                "comment": parameter.comment,
            }
        component_paths, occurrence_map, duplicate_semantic_paths = _root_context_occurrence_map(
            design.rootComponent
        )
        bounding_boxes = {}
        brep_bounding_boxes = {}
        geometry = {}
        for path, occurrence in occurrence_map.items():
            geometry[path] = _body_summary(occurrence)
            try:
                bounding_boxes[path] = _all_geometry_bbox_mm(occurrence)
            except Exception as error:
                bounding_boxes[path] = {"error": str(error)}
            try:
                brep_bounding_boxes[path] = _bbox_mm(occurrence)
            except Exception as error:
                brep_bounding_boxes[path] = {"error": str(error)}

        # Inventory is a survey, not a gate: it deliberately carries no "ok".
        # A descriptive snapshot that always said ok:true read as a verdict.
        report = {
            "kind": "inventory",
            "project": PROJECT_NAME,
            "manifest_sha256": MANIFEST_SHA256,
            "document_name": app.activeDocument.name if app.activeDocument else None,
            "design_type": str(design.designType),
            "is_parametric": design.designType == adsk.fusion.DesignTypes.ParametricDesignType,
            "parameters": parameters,
            "component_paths": component_paths,
            "duplicate_semantic_paths": duplicate_semantic_paths,
            "missing_expected_components": sorted(set(EXPECTED_COMPONENT_PATHS) - set(component_paths)),
            "ambiguous_expected_components": sorted(
                set(EXPECTED_COMPONENT_PATHS).intersection(duplicate_semantic_paths)
            ),
            "bounding_boxes_mm": bounding_boxes,
            "brep_bounding_boxes_mm": brep_bounding_boxes,
            "geometry": geometry,
            "timeline": _timeline_health(design),
        }
        report_attempted = True
        _emit(report)
    except Exception as error:
        if not report_attempted:
            report_attempted = True
            _emit({"kind": "inventory", "ok": False, "error": str(error), "traceback": traceback.format_exc()})
        raise
