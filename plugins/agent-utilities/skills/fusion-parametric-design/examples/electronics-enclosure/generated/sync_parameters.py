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

PARAMETER_SPECS = json.loads('[{"comment":"Measured PD trigger board length. [source=pd_trigger_board_measurement; provisional=false]","critical":true,"expression":"35 mm","name":"src_pd_board_length","provisional":false,"role":"source","source_id":"pd_trigger_board_measurement","units":"mm"},{"comment":"Measured PD trigger board width. [source=pd_trigger_board_measurement; provisional=false]","critical":true,"expression":"13 mm","name":"src_pd_board_width","provisional":false,"role":"source","source_id":"pd_trigger_board_measurement","units":"mm"},{"comment":"Measured rigid board-and-component height. [source=pd_trigger_board_measurement; provisional=false]","critical":true,"expression":"5 mm","name":"src_pd_board_height","provisional":false,"role":"source","source_id":"pd_trigger_board_measurement","units":"mm"},{"comment":"Measured converter body length, excluding flexible leads. [source=ekylin_converter_measurement; provisional=false]","critical":true,"expression":"62 mm","name":"src_ekylin_length","provisional":false,"role":"source","source_id":"ekylin_converter_measurement","units":"mm"},{"comment":"Measured converter body width. [source=ekylin_converter_measurement; provisional=false]","critical":true,"expression":"31 mm","name":"src_ekylin_width","provisional":false,"role":"source","source_id":"ekylin_converter_measurement","units":"mm"},{"comment":"Measured converter body height. [source=ekylin_converter_measurement; provisional=false]","critical":true,"expression":"27 mm","name":"src_ekylin_height","provisional":false,"role":"source","source_id":"ekylin_converter_measurement","units":"mm"},{"comment":"Per-side clearance around rigid electronic bodies. [source=none; provisional=false]","critical":true,"expression":"0.5 mm","name":"clr_rigid_xy","provisional":false,"role":"clearance","source_id":"","units":"mm"},{"comment":"Vertical clearance above rigid electronic bodies. [source=none; provisional=false]","critical":true,"expression":"1 mm","name":"clr_rigid_z","provisional":false,"role":"clearance","source_id":"","units":"mm"},{"comment":"Nominal PETG enclosure wall thickness. [source=none; provisional=false]","critical":true,"expression":"2 mm","name":"fab_wall_thickness","provisional":false,"role":"fabrication","source_id":"","units":"mm"},{"comment":"Per-side printed sliding-fit clearance. [source=none; provisional=false]","critical":true,"expression":"0.35 mm","name":"fab_fit_clearance","provisional":false,"role":"fabrication","source_id":"","units":"mm"},{"comment":"Exterior corner radius; adjustable without changing fit evidence. [source=none; provisional=false]","critical":false,"expression":"5 mm","name":"des_corner_radius","provisional":false,"role":"design","source_id":"","units":"mm"},{"comment":"Conservative initial straight cable-departure keep-out; confirm with the actual cable. [source=none; provisional=true]","critical":true,"expression":"20 mm","name":"pack_usb_c_straight_departure","provisional":true,"role":"packing","source_id":"","units":"mm"}]')
ATTRIBUTE_GROUP = "fusion_parametric_design"


def _set_attribute(entity, name, value):
    entity.attributes.add(ATTRIBUTE_GROUP, name, str(value))


def run(context):
    reported = False
    try:
        app, design = _active_design()
        if design.designType != adsk.fusion.DesignTypes.ParametricDesignType:
            raise RuntimeError(
                "This workflow requires a parametric Fusion design. Refusing to switch design type because doing so can remove history."
            )

        user_parameters = design.userParameters
        existing_parameters = {}
        for spec in PARAMETER_SPECS:
            existing = user_parameters.itemByName(spec["name"])
            if existing and spec["units"] and existing.unit != spec["units"]:
                raise RuntimeError(
                    "Existing parameter unit mismatch for "
                    + spec["name"]
                    + ": Fusion has "
                    + repr(existing.unit)
                    + ", manifest requires "
                    + repr(spec["units"])
                )
            existing_parameters[spec["name"]] = existing

        created_names = set()
        for spec in PARAMETER_SPECS:
            if not existing_parameters[spec["name"]]:
                neutral_expression = "''" if spec["units"].lower() == "text" else "0"
                value = adsk.core.ValueInput.createByString(neutral_expression)
                existing = user_parameters.add(spec["name"], value, spec["units"], spec["comment"])
                if not existing:
                    raise RuntimeError("Fusion failed to create user parameter " + spec["name"])
                existing_parameters[spec["name"]] = existing
                created_names.add(spec["name"])

        changes = []
        for spec in PARAMETER_SPECS:
            existing = existing_parameters[spec["name"]]
            changed_fields = ["created"] if spec["name"] in created_names else []
            if existing.expression != spec["expression"]:
                existing.expression = spec["expression"]
                changed_fields.append("expression")
            if existing.comment != spec["comment"]:
                existing.comment = spec["comment"]
                changed_fields.append("comment")
            if spec["name"] in created_names:
                operation = "created"
            else:
                operation = "updated" if changed_fields else "unchanged"

            _set_attribute(existing, "role", spec["role"])
            _set_attribute(existing, "source_id", spec["source_id"])
            _set_attribute(existing, "provisional", str(spec["provisional"]).lower())
            _set_attribute(existing, "critical", str(spec["critical"]).lower())
            _set_attribute(existing, "manifest_sha256", MANIFEST_SHA256)
            changes.append({"name": spec["name"], "operation": operation, "fields": changed_fields})

        compute_invoked = design.computeAll()
        timeline = _timeline_health(design)
        report = {
            "kind": "parameter-sync",
            "project": PROJECT_NAME,
            "manifest_sha256": MANIFEST_SHA256,
            "compute_invoked": compute_invoked,
            "changes": changes,
            "timeline": timeline,
            "ok": bool(compute_invoked) and len(timeline["unhealthy"]) == 0,
        }
        _emit(report)
        reported = True
        if not compute_invoked:
            raise RuntimeError("Fusion Compute All did not complete; see the emitted report.")
        if timeline["unhealthy"]:
            raise RuntimeError("Compute completed with unhealthy timeline objects; see the emitted report.")
    except Exception as error:
        if not reported:
            _emit({"kind": "parameter-sync", "ok": False, "error": str(error), "traceback": traceback.format_exc()})
        raise
