from __future__ import annotations

import json
import traceback
import adsk.core
import adsk.fusion

PROJECT_NAME = 'wearable-controller-pod'
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


def _ensure_component_path(root_component, path):
    parent = root_component
    created = []
    current_parts = []
    for name in [part for part in path.split("/") if part]:
        current_parts.append(name)
        occurrence = _find_child(parent, name)
        if not occurrence:
            occurrence = parent.occurrences.addNewComponent(adsk.core.Matrix3D.create())
            if not occurrence:
                raise RuntimeError("Fusion failed to create component path " + "/".join(current_parts))
            occurrence.component.name = name
            occurrence.component.attributes.add(ATTRIBUTE_GROUP, "managed", "true")
            occurrence.component.attributes.add(ATTRIBUTE_GROUP, "manifest_sha256", MANIFEST_SHA256)
            created.append("/".join(current_parts))
        parent = occurrence.component
    return created


def run(context):
    reported = False
    try:
        app, design = _active_design()
        if design.designType != adsk.fusion.DesignTypes.ParametricDesignType:
            raise RuntimeError("Component scaffolding requires a parametric design; refusing a destructive design-type change.")
        _, _, preexisting_duplicate_semantic_paths = _root_context_occurrence_map(design.rootComponent)
        if preexisting_duplicate_semantic_paths:
            _emit({
                "kind": "component-scaffold",
                "project": PROJECT_NAME,
                "manifest_sha256": MANIFEST_SHA256,
                "created": [],
                "duplicate_semantic_paths": preexisting_duplicate_semantic_paths,
                "ok": False,
            })
            reported = True
            raise RuntimeError("Semantic component paths are already ambiguous; refusing to scaffold into an ambiguous tree.")
        created = []
        for path in sorted(COMPONENT_PATHS, key=lambda item: (item.count("/"), item)):
            created.extend(_ensure_component_path(design.rootComponent, path))
        component_paths, _, duplicate_semantic_paths = _root_context_occurrence_map(design.rootComponent)
        report = {
            "kind": "component-scaffold",
            "project": PROJECT_NAME,
            "manifest_sha256": MANIFEST_SHA256,
            "created": sorted(set(created)),
            "component_paths": component_paths,
            "duplicate_semantic_paths": duplicate_semantic_paths,
            "ok": not duplicate_semantic_paths,
        }
        _emit(report)
        reported = True
        if duplicate_semantic_paths:
            raise RuntimeError("Semantic component paths are ambiguous; rename duplicate managed occurrences.")
    except Exception as error:
        if not reported:
            _emit({"kind": "component-scaffold", "ok": False, "error": str(error), "traceback": traceback.format_exc()})
        raise
