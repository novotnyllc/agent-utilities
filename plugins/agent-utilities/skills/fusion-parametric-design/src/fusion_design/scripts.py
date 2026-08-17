from __future__ import annotations

import hashlib
import json
from typing import Any

from .manifest import Manifest


REPORT_BEGIN = "FUSION_DESIGN_REPORT_BEGIN"
REPORT_END = "FUSION_DESIGN_REPORT_END"


def _json_literal(value: Any) -> str:
    return repr(json.dumps(value, sort_keys=True, separators=(",", ":")))


def _manifest_hash(manifest: Manifest) -> str:
    encoded = json.dumps(manifest.data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _script_prelude(manifest: Manifest) -> str:
    return f'''from __future__ import annotations

import json
import traceback
import adsk.core
import adsk.fusion

PROJECT_NAME = {manifest.project_name!r}
MANIFEST_SHA256 = {_manifest_hash(manifest)!r}
REPORT_BEGIN = {REPORT_BEGIN!r}
REPORT_END = {REPORT_END!r}


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
    mapping = {{}}
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
    mapping = {{}}
    duplicates = {{}}
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
    return sorted(mapping), mapping, {{key: sorted(value) for key, value in duplicates.items()}}


def _box_to_mm(box):
    if not box:
        raise RuntimeError("No bounding box is available for this occurrence.")
    return {{
        "min": [box.minPoint.x * 10.0, box.minPoint.y * 10.0, box.minPoint.z * 10.0],
        "max": [box.maxPoint.x * 10.0, box.maxPoint.y * 10.0, box.maxPoint.z * 10.0],
    }}


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
        body_rows.append({{
            "name": body.name,
            "is_solid": is_solid,
            "volume_mm3": volume_mm3,
        }})
    try:
        mesh_body_count = occurrence.component.meshBodies.count
    except Exception:
        mesh_body_count = None
    return {{
        "brep_body_count": bodies.count,
        "solid_body_count": solid_body_count,
        "surface_or_zero_volume_body_count": surface_body_count,
        "mesh_body_count": mesh_body_count,
        "total_solid_volume_mm3": total_solid_volume_mm3,
        "has_positive_solid": solid_body_count > 0 and total_solid_volume_mm3 > 1e-9,
        "bodies": body_rows,
    }}


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
        row = {{"index": index, "health_state": str(state)}}
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

    return {{
        "count": design.timeline.count,
        "unhealthy": unhealthy,
        "informational": informational,
    }}

'''


def emit_inventory_script(manifest: Manifest) -> str:
    expected = manifest.component_tree
    return _script_prelude(manifest) + f'''EXPECTED_COMPONENT_PATHS = json.loads({_json_literal(expected)})


def run(context):
    try:
        app, design = _active_design()
        component_paths, occurrence_map, duplicate_semantic_paths = _root_context_occurrence_map(
            design.rootComponent
        )
        parameters = {{}}
        user_parameters = design.userParameters
        for index in range(user_parameters.count):
            parameter = user_parameters.item(index)
            parameters[parameter.name] = {{
                "expression": parameter.expression,
                "units": parameter.unit,
                "comment": parameter.comment,
            }}

        bounding_boxes = {{}}
        brep_bounding_boxes = {{}}
        geometry = {{}}
        for path, occurrence in occurrence_map.items():
            geometry[path] = _body_summary(occurrence)
            try:
                bounding_boxes[path] = _all_geometry_bbox_mm(occurrence)
            except Exception as error:
                bounding_boxes[path] = {{"error": str(error)}}
            try:
                brep_bounding_boxes[path] = _bbox_mm(occurrence)
            except Exception as error:
                brep_bounding_boxes[path] = {{"error": str(error)}}

        report = {{
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
        }}
        _emit(report)
    except Exception as error:
        _emit({{"kind": "inventory", "ok": False, "error": str(error), "traceback": traceback.format_exc()}})
        raise
'''


def _parameter_specs(manifest: Manifest) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for parameter in manifest.parameters:
        source_id = str(parameter.get("source_id", ""))
        provisional = bool(parameter.get("provisional", False))
        description = str(parameter.get("description", ""))
        provenance = f"source={source_id or 'none'}; provisional={str(provisional).lower()}"
        specs.append(
            {
                "name": str(parameter["name"]),
                "expression": str(parameter["expression"]),
                "units": str(parameter.get("units", "")),
                "comment": f"{description} [{provenance}]",
                "role": str(parameter.get("role", "")),
                "source_id": source_id,
                "provisional": provisional,
                "critical": bool(parameter.get("critical", False)),
            }
        )
    return specs


def emit_parameter_sync_script(manifest: Manifest) -> str:
    specs = _parameter_specs(manifest)
    return _script_prelude(manifest) + f'''PARAMETER_SPECS = json.loads({_json_literal(specs)})
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


def run(context):
    reported = False
    try:
        app, design = _active_design()
        if design.designType != adsk.fusion.DesignTypes.ParametricDesignType:
            raise RuntimeError(
                "This workflow requires a parametric Fusion design. Refusing to switch design type because doing so can remove history."
            )

        user_parameters = design.userParameters
        existing_parameters = {{}}
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
            changes.append({{"name": spec["name"], "operation": operation, "fields": changed_fields}})

        compute_invoked = design.computeAll()
        timeline = _timeline_health(design)
        report = {{
            "kind": "parameter-sync",
            "project": PROJECT_NAME,
            "manifest_sha256": MANIFEST_SHA256,
            "compute_invoked": compute_invoked,
            "changes": changes,
            "timeline": timeline,
            "ok": bool(compute_invoked) and len(timeline["unhealthy"]) == 0,
        }}
        _emit(report)
        reported = True
        if not compute_invoked:
            raise RuntimeError("Fusion Compute All did not complete; see the emitted report.")
        if timeline["unhealthy"]:
            raise RuntimeError("Compute completed with unhealthy timeline objects; see the emitted report.")
    except Exception as error:
        if not reported:
            _emit({{"kind": "parameter-sync", "ok": False, "error": str(error), "traceback": traceback.format_exc()}})
        raise
'''


def emit_scaffold_script(manifest: Manifest) -> str:
    paths = manifest.component_tree
    return _script_prelude(manifest) + f'''COMPONENT_PATHS = json.loads({_json_literal(paths)})
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
            _emit({{
                "kind": "component-scaffold",
                "project": PROJECT_NAME,
                "manifest_sha256": MANIFEST_SHA256,
                "created": [],
                "duplicate_semantic_paths": preexisting_duplicate_semantic_paths,
                "ok": False,
            }})
            reported = True
            raise RuntimeError("Semantic component paths are already ambiguous; refusing to scaffold into an ambiguous tree.")
        created = []
        for path in sorted(COMPONENT_PATHS, key=lambda item: (item.count("/"), item)):
            created.extend(_ensure_component_path(design.rootComponent, path))
        component_paths, _, duplicate_semantic_paths = _root_context_occurrence_map(design.rootComponent)
        missing_component_paths = sorted(set(COMPONENT_PATHS) - set(component_paths))
        report = {{
            "kind": "component-scaffold",
            "project": PROJECT_NAME,
            "manifest_sha256": MANIFEST_SHA256,
            "created": sorted(set(created)),
            "component_paths": component_paths,
            "missing_component_paths": missing_component_paths,
            "duplicate_semantic_paths": duplicate_semantic_paths,
            "ok": not duplicate_semantic_paths and not missing_component_paths,
        }}
        _emit(report)
        reported = True
        if missing_component_paths:
            raise RuntimeError("Declared component paths are still missing; see the emitted report.")
        if duplicate_semantic_paths:
            raise RuntimeError("Semantic component paths are ambiguous; rename duplicate managed occurrences.")
    except Exception as error:
        if not reported:
            _emit({{"kind": "component-scaffold", "ok": False, "error": str(error), "traceback": traceback.format_exc()}})
        raise
'''


def emit_verification_script(manifest: Manifest) -> str:
    verification = manifest.verification
    parameter_specs = [
        {"name": spec["name"], "expression": spec["expression"], "units": spec["units"]}
        for spec in _parameter_specs(manifest)
    ]
    return _script_prelude(manifest) + f'''VERIFICATION = json.loads({_json_literal(verification)})
PARAMETER_SPECS = json.loads({_json_literal(parameter_specs)})


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


def _parameter_mismatches(user_parameters):
    mismatches = []
    for spec in PARAMETER_SPECS:
        existing = user_parameters.itemByName(spec["name"])
        if not existing:
            mismatches.append({{"name": spec["name"], "reason": "missing"}})
            continue
        if existing.expression != spec["expression"]:
            mismatches.append({{
                "name": spec["name"],
                "reason": "expression",
                "expected": spec["expression"],
                "actual": existing.expression,
            }})
        if spec["units"] and existing.unit != spec["units"]:
            mismatches.append({{
                "name": spec["name"],
                "reason": "units",
                "expected": spec["units"],
                "actual": existing.unit,
            }})
    return mismatches


def run(context):
    reported = False
    try:
        app, design = _active_design()
        compute_invoked = design.computeAll()
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

        bounding_boxes = {{}}
        brep_bounding_boxes = {{}}
        geometry = {{}}
        for path in sorted(relevant_paths):
            occurrence = occurrence_map.get(path)
            if not occurrence:
                continue
            geometry[path] = _body_summary(occurrence)
            try:
                bounding_boxes[path] = _all_geometry_bbox_mm(occurrence)
            except Exception as error:
                bounding_boxes[path] = {{"error": str(error)}}
            try:
                brep_bounding_boxes[path] = _bbox_mm(occurrence)
            except Exception as error:
                brep_bounding_boxes[path] = {{"error": str(error)}}

        clearance_results = []
        for check in VERIFICATION.get("clearance_checks", []):
            one = occurrence_map.get(check["one"])
            two = occurrence_map.get(check["two"])
            result = {{
                "id": check["id"],
                "one": check["one"],
                "two": check["two"],
                "minimum_mm": check["minimum_mm"],
            }}
            if not one or not two:
                result.update({{"ok": False, "error": "one or both component paths are missing"}})
            elif not _has_positive_solid_brep(one) or not _has_positive_solid_brep(two):
                result.update({{
                    "ok": False,
                    "error": "Automated clearance checks require a positive-volume root-context B-Rep envelope for each component; mesh-only or surface-only geometry remains reference evidence.",
                }})
            else:
                try:
                    measured = app.measureManager.measureMinimumDistance(one, two)
                    distance_mm = measured.value * 10.0
                    result.update({{
                        "distance_mm": distance_mm,
                        "ok": distance_mm + 1e-9 >= float(check["minimum_mm"]),
                    }})
                except Exception as error:
                    result.update({{"ok": False, "error": str(error)}})
            clearance_results.append(result)

        interference_results = []
        for check in VERIFICATION.get("interference_checks", []):
            one = occurrence_map.get(check["one"])
            two = occurrence_map.get(check["two"])
            result = {{
                "id": check["id"],
                "one": check["one"],
                "two": check["two"],
                "allow_interference": bool(check.get("allow_interference", False)),
            }}
            if not one or not two:
                result.update({{"ok": False, "error": "one or both component paths are missing"}})
            elif not _has_positive_solid_brep(one) or not _has_positive_solid_brep(two):
                result.update({{
                    "ok": False,
                    "error": "Automated interference checks require a positive-volume root-context B-Rep envelope for each component; mesh-only or surface-only geometry remains reference evidence.",
                }})
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
                        pairs.append({{
                            "entity_one": _entity_label(interference.entityOne),
                            "entity_two": _entity_label(interference.entityTwo),
                            "volume_mm3": volume_mm3,
                        }})
                    allowed = bool(check.get("allow_interference", False))
                    result.update({{
                        "count": count,
                        "total_interference_volume_mm3": total_interference_volume_mm3,
                        "pairs": pairs,
                        "ok": allowed or count == 0,
                    }})
                except Exception as error:
                    result.update({{"ok": False, "error": str(error)}})
            interference_results.append(result)

        expected_print_parts_missing = sorted(path for path in expected_print_paths if path not in component_set)
        expected_print_parts_without_positive_solid = sorted(
            path
            for path in expected_print_paths
            if path in component_set and not geometry.get(path, {{}}).get("has_positive_solid", False)
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

        report = {{
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
            "geometry": geometry,
            "clearance_results": clearance_results,
            "interference_results": interference_results,
        }}
        _emit(report)
        reported = True
        if failures:
            raise RuntimeError("Fusion design verification failed: " + ", ".join(failures))
    except Exception as error:
        if not reported:
            _emit({{"kind": "verification", "ok": False, "error": str(error), "traceback": traceback.format_exc()}})
        raise
'''
