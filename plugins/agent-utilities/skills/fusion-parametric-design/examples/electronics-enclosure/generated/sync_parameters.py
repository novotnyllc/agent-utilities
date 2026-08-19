import json
import traceback
import adsk.core
import adsk.fusion

PROJECT_NAME = 'wearable-controller-pod'
FUSION_DOCUMENT_NAME = 'Wearable Controller Pod'
MANIFEST_SHA256 = '9bff3afba88bdf1ade933f1c1a8ba0ba8a4ba54fdae7292d6cc27adb85316beb'
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

PARAMETER_SPECS = json.loads('[{"comment":"Measured PD trigger board length. [source=pd_trigger_board_measurement; provisional=false]","critical":true,"expression":"35 mm","name":"src_pd_board_length","provisional":false,"role":"source","source_id":"pd_trigger_board_measurement","units":"mm"},{"comment":"Measured PD trigger board width. [source=pd_trigger_board_measurement; provisional=false]","critical":true,"expression":"13 mm","name":"src_pd_board_width","provisional":false,"role":"source","source_id":"pd_trigger_board_measurement","units":"mm"},{"comment":"Measured rigid board-and-component height. [source=pd_trigger_board_measurement; provisional=false]","critical":true,"expression":"5 mm","name":"src_pd_board_height","provisional":false,"role":"source","source_id":"pd_trigger_board_measurement","units":"mm"},{"comment":"Measured converter body length, excluding flexible leads. [source=ekylin_converter_measurement; provisional=false]","critical":true,"expression":"62 mm","name":"src_ekylin_length","provisional":false,"role":"source","source_id":"ekylin_converter_measurement","units":"mm"},{"comment":"Measured converter body width. [source=ekylin_converter_measurement; provisional=false]","critical":true,"expression":"31 mm","name":"src_ekylin_width","provisional":false,"role":"source","source_id":"ekylin_converter_measurement","units":"mm"},{"comment":"Measured converter body height. [source=ekylin_converter_measurement; provisional=false]","critical":true,"expression":"27 mm","name":"src_ekylin_height","provisional":false,"role":"source","source_id":"ekylin_converter_measurement","units":"mm"},{"comment":"Per-side clearance around rigid electronic bodies; a starting value, not yet confirmed against a printed part. [source=provisional_starting_assumptions; provisional=true]","critical":true,"expression":"0.5 mm","name":"clr_rigid_xy","provisional":true,"role":"clearance","source_id":"provisional_starting_assumptions","units":"mm"},{"comment":"Vertical clearance above rigid electronic bodies; a starting value, not yet confirmed against a printed part. [source=provisional_starting_assumptions; provisional=true]","critical":true,"expression":"1 mm","name":"clr_rigid_z","provisional":true,"role":"clearance","source_id":"provisional_starting_assumptions","units":"mm"},{"comment":"Nominal PETG enclosure wall thickness. A bare \'2 mm wall\' is folklore until it is reconciled with the nozzle width and the actual load; confirm both before settling it. [source=provisional_starting_assumptions; provisional=true]","critical":true,"expression":"2 mm","name":"fab_wall_thickness","provisional":true,"role":"fabrication","source_id":"provisional_starting_assumptions","units":"mm"},{"comment":"Per-side printed sliding-fit clearance. Printer- and material-specific; settle it by printing and measuring VAL__PD_FIT_COUPON, never by reusing this number. [source=provisional_starting_assumptions; provisional=true]","critical":true,"expression":"0.35 mm","name":"fab_fit_clearance","provisional":true,"role":"fabrication","source_id":"provisional_starting_assumptions","units":"mm"},{"comment":"Exterior corner radius; adjustable without changing fit evidence. [source=none; provisional=false]","critical":false,"expression":"5 mm","name":"des_corner_radius","provisional":false,"role":"design","source_id":"","units":"mm"},{"comment":"Conservative initial straight cable-departure keep-out; confirm with the actual cable. [source=provisional_starting_assumptions; provisional=true]","critical":true,"expression":"20 mm","name":"pack_usb_c_straight_departure","provisional":true,"role":"packing","source_id":"provisional_starting_assumptions","units":"mm"}]')
ATTRIBUTE_GROUP = "fusion_parametric_design"


def _set_attribute(entity, name, value):
    desired = str(value)
    existing = entity.attributes.itemByName(ATTRIBUTE_GROUP, name)
    if existing and existing.value == desired:
        return False
    updated = entity.attributes.add(ATTRIBUTE_GROUP, name, desired)
    if not updated:
        raise RuntimeError("Fusion failed to write parameter attribute " + name)
    return True


def _attribute_value(entity, name):
    attribute = entity.attributes.itemByName(ATTRIBUTE_GROUP, name)
    return attribute.value if attribute else None


def run(context):
    report_attempted = False
    try:
        app, design = _active_design()
        target_document = _require_target_document(app)
        if design.designType != adsk.fusion.DesignTypes.ParametricDesignType:
            raise RuntimeError(
                "This workflow requires a parametric Fusion design. Refusing to switch design type because doing so can remove history."
            )

        user_parameters = design.userParameters
        existing_parameters = {}
        for spec in PARAMETER_SPECS:
            existing = user_parameters.itemByName(spec["name"])
            if existing and existing.unit != spec["units"]:
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
        for index, spec in enumerate(PARAMETER_SPECS):
            if not existing_parameters[spec["name"]]:
                neutral_expression = "''" if spec["units"].lower() == "text" else "0"
                value = adsk.core.ValueInput.createByString(neutral_expression)
                existing = user_parameters.add(spec["name"], value, spec["units"], spec["comment"])
                if not existing:
                    raise RuntimeError("Fusion failed to create user parameter " + spec["name"])
                existing_parameters[spec["name"]] = existing
                created_names.add(spec["name"])
            _pump_events_periodically(app, design, target_document, index)
        _pump_events(app, design, target_document)

        changes = []
        for index, spec in enumerate(PARAMETER_SPECS):
            existing = existing_parameters[spec["name"]]
            changed_fields = ["created"] if spec["name"] in created_names else []
            if existing.expression != spec["expression"]:
                existing.expression = spec["expression"]
                changed_fields.append("expression")
            if existing.comment != spec["comment"]:
                existing.comment = spec["comment"]
                changed_fields.append("comment")
            for attribute_name, attribute_value in (
                ("role", spec["role"]),
                ("source_id", spec["source_id"]),
                ("provisional", str(spec["provisional"]).lower()),
                ("critical", str(spec["critical"]).lower()),
                ("manifest_sha256", MANIFEST_SHA256),
            ):
                if _set_attribute(existing, attribute_name, attribute_value):
                    changed_fields.append("attribute:" + attribute_name)

            if spec["name"] in created_names:
                operation = "created"
            else:
                operation = "updated" if changed_fields else "unchanged"
            changes.append({"name": spec["name"], "operation": operation, "fields": changed_fields})
            _pump_events_periodically(app, design, target_document, index)
        _pump_events(app, design, target_document)

        compute_invoked = design.computeAll()
        _pump_events(app, design, target_document)
        verification_failures = []
        verified_user_parameters = design.userParameters
        for spec in PARAMETER_SPECS:
            verified = verified_user_parameters.itemByName(spec["name"])
            if not verified:
                verification_failures.append(spec["name"] + ":missing")
                continue
            expected_attributes = (
                ("role", str(spec["role"])),
                ("source_id", str(spec["source_id"])),
                ("provisional", str(spec["provisional"]).lower()),
                ("critical", str(spec["critical"]).lower()),
                ("manifest_sha256", MANIFEST_SHA256),
            )
            if verified.expression != spec["expression"]:
                verification_failures.append(spec["name"] + ":expression")
            if verified.unit != spec["units"]:
                verification_failures.append(spec["name"] + ":unit")
            if verified.comment != spec["comment"]:
                verification_failures.append(spec["name"] + ":comment")
            for attribute_name, expected_value in expected_attributes:
                if _attribute_value(verified, attribute_name) != expected_value:
                    verification_failures.append(spec["name"] + ":attribute:" + attribute_name)
        timeline = _timeline_health(design)
        report = {
            "kind": "parameter-sync",
            "project": PROJECT_NAME,
            "manifest_sha256": MANIFEST_SHA256,
            "compute_invoked": compute_invoked,
            "changes": changes,
            "verification_failures": verification_failures,
            "timeline": timeline,
            "ok": bool(compute_invoked) and not verification_failures and len(timeline["unhealthy"]) == 0,
        }
        report_attempted = True
        _emit(report)
        if not compute_invoked:
            raise RuntimeError("Fusion Compute All did not complete; see the emitted report.")
        if timeline["unhealthy"]:
            raise RuntimeError("Compute completed with unhealthy timeline objects; see the emitted report.")
        if verification_failures:
            raise RuntimeError("Managed parameters changed while Fusion processed events; see the emitted report.")
    except Exception as error:
        if not report_attempted:
            report_attempted = True
            _emit({"kind": "parameter-sync", "ok": False, "error": str(error), "traceback": traceback.format_exc()})
        raise
