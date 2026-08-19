import json
import traceback
import adsk.core
import adsk.fusion

PROJECT_NAME = 'wearable-controller-pod'
FUSION_DOCUMENT_NAME = 'Wearable Controller Pod'
MANIFEST_SHA256 = '8e28010a7d270c9d49e9218c571de1c5fa3c8fa9ab28e885567e3b12b4cc5c5b'
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

VERIFICATION = json.loads('{"clearance_checks":[{"id":"pd-to-lid-clearance","minimum_mm":1.0,"one":"00_REFERENCES/PACK__PD_TRIGGER__EXACT_OR_CONSERVATIVE","two":"10_PRODUCT/PROD__LID"}],"expected_print_parts":["10_PRODUCT/PROD__BASE","10_PRODUCT/PROD__LID","90_VALIDATION/VAL__PD_FIT_COUPON"],"interference_checks":[{"allow_interference":false,"id":"usb-c-insertion-zone","one":"00_REFERENCES/KEEP__USB_C_INSERTION","two":"10_PRODUCT/PROD__BASE"},{"allow_interference":false,"id":"ekylin-wire-bend-zone","one":"00_REFERENCES/KEEP__EKYLIN_WIRE_BENDS","two":"10_PRODUCT/PROD__LID"}],"required_components":["10_PRODUCT/PROD__BASE","10_PRODUCT/PROD__LID","00_REFERENCES/PACK__PD_TRIGGER__EXACT_OR_CONSERVATIVE","00_REFERENCES/PACK__EKYLIN__EXACT_OR_CONSERVATIVE"]}')
PARAMETER_SPECS = json.loads('[{"expression":"35 mm","name":"src_pd_board_length","units":"mm"},{"expression":"13 mm","name":"src_pd_board_width","units":"mm"},{"expression":"5 mm","name":"src_pd_board_height","units":"mm"},{"expression":"62 mm","name":"src_ekylin_length","units":"mm"},{"expression":"31 mm","name":"src_ekylin_width","units":"mm"},{"expression":"27 mm","name":"src_ekylin_height","units":"mm"},{"expression":"0.5 mm","name":"clr_rigid_xy","units":"mm"},{"expression":"1 mm","name":"clr_rigid_z","units":"mm"},{"expression":"2 mm","name":"fab_wall_thickness","units":"mm"},{"expression":"0.35 mm","name":"fab_fit_clearance","units":"mm"},{"expression":"5 mm","name":"des_corner_radius","units":"mm"},{"expression":"20 mm","name":"pack_usb_c_straight_departure","units":"mm"}]')


def _entity_label(entity):
    if not entity:
        return None
    try:
        if hasattr(entity, "fullPathName"):
            return entity.fullPathName
    except Exception:
        pass
    try:
        if hasattr(entity, "component") and entity.component:
            return entity.component.name
    except Exception:
        pass
    return getattr(entity, "name", str(entity))


def _has_positive_solid_brep(occurrence):
    if not occurrence:
        return False
    bodies = occurrence.bRepBodies
    for index in range(bodies.count):
        body = bodies.item(index)
        if bool(body.isSolid) and float(body.volume) * 1000.0 > 1e-9:
            return True
    return False


def _occurrence_transform(occurrence):
    transform = getattr(occurrence, "transform2", None)
    if not transform:
        return None
    return [float(value) for value in transform.asArray()]


def _parameter_mismatches(user_parameters):
    mismatches = []
    for spec in PARAMETER_SPECS:
        existing = user_parameters.itemByName(spec["name"])
        if not existing:
            mismatches.append({"name": spec["name"], "reason": "missing"})
            continue
        if existing.expression != spec["expression"]:
            mismatches.append({
                "name": spec["name"],
                "reason": "expression",
                "expected": spec["expression"],
                "actual": existing.expression,
            })
        if existing.unit != spec["units"]:
            mismatches.append({
                "name": spec["name"],
                "reason": "units",
                "expected": spec["units"],
                "actual": existing.unit,
            })
    return mismatches


def run(context):
    report_attempted = False
    try:
        app, design = _active_design()
        target_document = _require_target_document(app)
        _pump_events(app, design, target_document)
        compute_invoked = design.computeAll()
        _pump_events(app, design, target_document)
        # All following reads form one report snapshot.  Yielding after a read
        # would make a same-document edit appear as an authoritative result.
        root_component = design.rootComponent
        component_paths, occurrence_map, duplicate_semantic_paths = _root_context_occurrence_map(
            root_component
        )
        component_set = set(component_paths)

        required_paths = set(VERIFICATION.get("required_components", []))
        expected_print_paths = set(VERIFICATION.get("expected_print_parts", []))
        checked_paths = set()
        for check in VERIFICATION.get("clearance_checks", []):
            checked_paths.update((check["one"], check["two"]))
        for check in VERIFICATION.get("interference_checks", []):
            checked_paths.update((check["one"], check["two"]))
        relevant_paths = required_paths | expected_print_paths | checked_paths

        ambiguous_component_paths = sorted(set(duplicate_semantic_paths).intersection(relevant_paths))
        required_missing = sorted(path for path in required_paths if path not in component_set)
        timeline = _timeline_health(design)
        parameter_mismatches = _parameter_mismatches(design.userParameters)

        bounding_boxes = {}
        brep_bounding_boxes = {}
        geometry = {}
        occurrence_transforms = {}
        for path in sorted(relevant_paths):
            occurrence = occurrence_map.get(path)
            if not occurrence:
                continue
            geometry[path] = _body_summary(occurrence)
            occurrence_transforms[path] = _occurrence_transform(occurrence)
            try:
                bounding_boxes[path] = _all_geometry_bbox_mm(occurrence)
            except Exception as error:
                bounding_boxes[path] = {"error": str(error)}
            try:
                brep_bounding_boxes[path] = _bbox_mm(occurrence)
            except Exception as error:
                brep_bounding_boxes[path] = {"error": str(error)}

        clearance_results = []
        for check in VERIFICATION.get("clearance_checks", []):
            one = occurrence_map.get(check["one"])
            two = occurrence_map.get(check["two"])
            result = {
                "id": check["id"],
                "one": check["one"],
                "two": check["two"],
                "minimum_mm": check["minimum_mm"],
            }
            if not one or not two:
                result.update({"ok": False, "error": "one or both component paths are missing"})
            elif not _has_positive_solid_brep(one) or not _has_positive_solid_brep(two):
                result.update({
                    "ok": False,
                    "error": "Automated clearance checks require a positive-volume root-context B-Rep envelope for each component; mesh-only or surface-only geometry remains reference evidence.",
                })
            else:
                try:
                    measured = app.measureManager.measureMinimumDistance(one, two)
                    distance_mm = measured.value * 10.0
                    result.update({
                        "distance_mm": distance_mm,
                        "ok": distance_mm + 1e-9 >= float(check["minimum_mm"]),
                    })
                except Exception as error:
                    result.update({"ok": False, "error": str(error)})
            clearance_results.append(result)

        interference_results = []
        for check in VERIFICATION.get("interference_checks", []):
            one = occurrence_map.get(check["one"])
            two = occurrence_map.get(check["two"])
            result = {
                "id": check["id"],
                "one": check["one"],
                "two": check["two"],
                "allow_interference": bool(check.get("allow_interference", False)),
            }
            if not one or not two:
                result.update({"ok": False, "error": "one or both component paths are missing"})
            elif not _has_positive_solid_brep(one) or not _has_positive_solid_brep(two):
                result.update({
                    "ok": False,
                    "error": "Automated interference checks require a positive-volume root-context B-Rep envelope for each component; mesh-only or surface-only geometry remains reference evidence.",
                })
            else:
                try:
                    entities = adsk.core.ObjectCollection.create()
                    entities.add(one)
                    entities.add(two)
                    analysis_input = design.createInterferenceInput(entities)
                    analyses = design.analyzeInterference(analysis_input)
                    count = analyses.count
                    pairs = []
                    total_interference_volume_mm3 = 0.0
                    for index in range(count):
                        interference = analyses.item(index)
                        volume_mm3 = float(interference.interferenceBody.volume) * 1000.0
                        total_interference_volume_mm3 += volume_mm3
                        pairs.append({
                            "entity_one": _entity_label(interference.entityOne),
                            "entity_two": _entity_label(interference.entityTwo),
                            "volume_mm3": volume_mm3,
                        })
                    allowed = bool(check.get("allow_interference", False))
                    result.update({
                        "count": count,
                        "total_interference_volume_mm3": total_interference_volume_mm3,
                        "pairs": pairs,
                        "ok": allowed or count == 0,
                    })
                except Exception as error:
                    result.update({"ok": False, "error": str(error)})
            interference_results.append(result)

        expected_print_parts_missing = sorted(path for path in expected_print_paths if path not in component_set)
        expected_print_parts_without_positive_solid = sorted(
            path
            for path in expected_print_paths
            if path in component_set and not geometry.get(path, {}).get("has_positive_solid", False)
        )

        failures = []
        if not compute_invoked:
            failures.append("compute-all")
        if design.designType != adsk.fusion.DesignTypes.ParametricDesignType:
            failures.append("design-type")
        if parameter_mismatches:
            failures.append("parameters")
        if ambiguous_component_paths:
            failures.append("ambiguous-components")
        if required_missing:
            failures.append("required-components")
        if timeline["unhealthy"]:
            failures.append("timeline-health")
        if any(not result.get("ok", False) for result in clearance_results):
            failures.append("clearance")
        if any(not result.get("ok", False) for result in interference_results):
            failures.append("interference")
        if expected_print_parts_missing or expected_print_parts_without_positive_solid:
            failures.append("print-parts")

        report = {
            "kind": "verification",
            "project": PROJECT_NAME,
            "manifest_sha256": MANIFEST_SHA256,
            "compute_invoked": compute_invoked,
            "is_parametric": design.designType == adsk.fusion.DesignTypes.ParametricDesignType,
            "ok": not failures,
            "failures": failures,
            "duplicate_semantic_paths": duplicate_semantic_paths,
            "ambiguous_component_paths": ambiguous_component_paths,
            "required_components_missing": required_missing,
            "parameter_mismatches": parameter_mismatches,
            "expected_print_parts_missing": expected_print_parts_missing,
            "expected_print_parts_without_positive_solid": expected_print_parts_without_positive_solid,
            "timeline": timeline,
            "bounding_boxes_mm": bounding_boxes,
            "brep_bounding_boxes_mm": brep_bounding_boxes,
            "occurrence_transforms": occurrence_transforms,
            "geometry": geometry,
            "clearance_results": clearance_results,
            "interference_results": interference_results,
        }
        report_attempted = True
        _emit(report)
        if failures:
            raise RuntimeError("Fusion design verification failed: " + ", ".join(failures))
    except Exception as error:
        if not report_attempted:
            report_attempted = True
            _emit({"kind": "verification", "ok": False, "error": str(error), "traceback": traceback.format_exc()})
        raise
