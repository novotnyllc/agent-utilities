from __future__ import annotations

import hashlib
import json
from typing import Any

from .manifest import Manifest


REPORT_BEGIN = "FUSION_DESIGN_REPORT_BEGIN"
REPORT_END = "FUSION_DESIGN_REPORT_END"


def _json_literal(value: Any) -> str:
    return repr(json.dumps(value, sort_keys=True, separators=(",", ":")))


def manifest_sha256(manifest: Manifest) -> str:
    """Return the canonical hash embedded in every generated transaction."""
    encoded = json.dumps(manifest.data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _script_prelude(manifest: Manifest, report_dir: str | None = None) -> str:
    """The header every generated transaction carries.

    ``report_dir`` is where ``_emit`` tees its report to a file, and it is a
    recovery path rather than a convenience. The MCP transport this skill is
    driven through has a 180-second ceiling: GFG-Accurate on a 524k-triangle scan
    ran 330 seconds, the transport discarded the *successful* report, and the
    pipeline was stuck on an operation that had already done its work. stdout is
    not a durable channel, so the report is also written where the transaction's
    own inputs live, and the stdout report says where.

    Emitters pass their own declared output directory or the directory of the
    file they write. One that has neither passes nothing and the tee is reported
    as unavailable, which is a statement rather than a silence.
    """
    tee_dir = str(report_dir).strip() if report_dir is not None and str(report_dir).strip() else None
    return f'''import json
import os
import time
import traceback
import adsk.core
import adsk.fusion

PROJECT_NAME = {manifest.project_name!r}
FUSION_DOCUMENT_NAME = {manifest.fusion_document!r}
MANIFEST_SHA256 = {manifest_sha256(manifest)!r}
REPORT_BEGIN = {REPORT_BEGIN!r}
REPORT_END = {REPORT_END!r}
# Where _emit tees its report so a transport timeout loses nothing. None when
# this transaction declares no output directory of its own.
REPORT_TEE_DIR = {tee_dir!r}
# This run's own identity, so two agents running the same transaction against
# the same manifest into the same directory write two files rather than racing
# for one. Bound at run time and not at emission, so the emitted script stays
# byte-identical across emissions.
RUN_ID = "%d-%d" % (os.getpid(), int(time.time() * 1000))


class DocumentChangedError(RuntimeError):
    """The active document is no longer ours; the transaction must touch nothing further."""


def _report_tee_path(report):
    """Where this report is teed: one file per *run*, beside the run's inputs.

    Named for the report's own `kind`, the manifest it was emitted against, and
    this run's own identity. The run identity is what makes it safe under the
    hazard `references/mcp-adapter.md` already treats as supported: two agents
    driving the same transaction kind against the same manifest into the same
    directory used to resolve to one path, so their writes interleaved and the
    recovery read could hand back the other run's report as if it were yours.
    Recovery is by newest match on the `<kind>-<manifest12>-` prefix rather than
    by an exact name, which cannot silently return somebody else's answer.
    """
    if not REPORT_TEE_DIR:
        return None
    kind = report.get("kind") if isinstance(report, dict) else None
    name = "".join(c if (c.isalnum() or c in "-_") else "-" for c in str(kind or "report"))
    return os.path.join(
        REPORT_TEE_DIR,
        "fusion-design-report-" + name + "-" + MANIFEST_SHA256[:12] + "-" + RUN_ID + ".json",
    )


def _emit(report):
    # The tee happens before the print and its own path goes into the report, so
    # the file and the stdout block are the same bytes wherever both survive.
    path = _report_tee_path(report)
    if path is not None and isinstance(report, dict):
        report["report_tee_path"] = path
        # On the report as well as in the name, so a caller holding two
        # candidate files can see that they came from two runs rather than
        # inferring it from the filenames.
        report["run_id"] = RUN_ID
        try:
            # Written whole and then moved into place: a reader that arrives
            # mid-write must never see half a report and take it for the run's
            # answer. `os.replace` is atomic within a directory.
            staging = path + ".partial"
            handle = open(staging, "w")
            try:
                handle.write(json.dumps(report, sort_keys=True, separators=(",", ":"), default=str))
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                handle.close()
            os.replace(staging, path)
        except Exception as error:
            # Never fatal: losing the tee must not lose the transaction.
            report["report_tee_error"] = str(error)
    elif isinstance(report, dict):
        report["report_tee_path"] = None
        report["report_tee_unavailable_reason"] = (
            "this transaction declares no output directory, so its report is only on stdout"
        )
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


def _occurrence_state(occurrence):
    """Participation state for a root-context occurrence.

    A suppressed occurrence is still returned by allOccurrences and still owns
    its component's bodies, but contributes no geometry to interference or
    measurement -- so 'no interference' and 'not in the model' look identical
    unless this state is recorded.
    """
    state = {{}}
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


def _document_saved_state(document):
    """The document's saved identity, fail closed.

    "Unsaved" and "could not read" must never look alike: an unreadable probe is
    reported as available:false with a named reason, never defaulted to a value
    that reads as an answer. A saved document's identity is its dataFile id --
    names are user-mutable and are reported, not trusted.
    """
    if document is None:
        return {{"available": False, "reason": "no-active-document"}}
    state = {{"available": True, "name": None, "is_saved": None, "data_file": None}}
    try:
        state["name"] = str(document.name)
    except Exception:
        pass
    is_saved = getattr(document, "isSaved", None)
    if is_saved is None:
        state["available"] = False
        state["reason"] = "isSaved-unavailable"
        return state
    state["is_saved"] = bool(is_saved)
    if not state["is_saved"]:
        return state
    try:
        data_file = document.dataFile
    except Exception as error:
        state["available"] = False
        state["reason"] = "dataFile-unreadable: " + str(error)
        return state
    if not data_file:
        state["available"] = False
        state["reason"] = "dataFile-missing-on-saved-document"
        return state
    identity = {{}}
    try:
        identity["id"] = str(data_file.id)
    except Exception:
        identity["id"] = None
    try:
        identity["version_number"] = int(data_file.versionNumber)
    except Exception:
        identity["version_number"] = None
    for key, attribute in (("project_id", "parentProject"), ("folder_id", "parentFolder")):
        try:
            parent = getattr(data_file, attribute)
            identity[key] = str(parent.id) if parent else None
        except Exception:
            identity[key] = None
    state["data_file"] = identity
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
        elif state == suppressed_state:
            # Suppression silently changes the shape away from recorded intent,
            # so it is reported separately instead of buried in informational.
            suppressed.append(row)
        elif state == unknown_state:
            informational.append(row)
        elif state != healthy_state:
            unhealthy.append(row)

    return {{
        "count": design.timeline.count,
        "unhealthy": unhealthy,
        "suppressed": suppressed,
        "informational": informational,
    }}

'''


def emit_inventory_script(manifest: Manifest) -> str:
    expected = manifest.component_tree
    return _script_prelude(manifest) + f'''EXPECTED_COMPONENT_PATHS = json.loads({_json_literal(expected)})


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
        parameters = {{}}
        for index in range(user_parameters.count):
            parameter = user_parameters.item(index)
            parameters[parameter.name] = {{
                "expression": parameter.expression,
                "units": parameter.unit,
                "comment": parameter.comment,
            }}
        component_paths, occurrence_map, duplicate_semantic_paths = _root_context_occurrence_map(
            design.rootComponent
        )
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

        # Inventory is a survey, not a gate: it deliberately carries no "ok".
        # A descriptive snapshot that always said ok:true read as a verdict.
        report = {{
            "kind": "inventory",
            "project": PROJECT_NAME,
            "manifest_sha256": MANIFEST_SHA256,
            "document_name": app.activeDocument.name if app.activeDocument else None,
            "document_saved_state": _document_saved_state(app.activeDocument),
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
        report_attempted = True
        _emit(report)
    except Exception as error:
        if not report_attempted:
            report_attempted = True
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
        existing_parameters = {{}}
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
            changes.append({{"name": spec["name"], "operation": operation, "fields": changed_fields}})
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
        report = {{
            "kind": "parameter-sync",
            "project": PROJECT_NAME,
            "manifest_sha256": MANIFEST_SHA256,
            "compute_invoked": compute_invoked,
            "changes": changes,
            "verification_failures": verification_failures,
            "timeline": timeline,
            "ok": bool(compute_invoked) and not verification_failures and len(timeline["unhealthy"]) == 0,
        }}
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
            attribute_updates.append({{
                "component_path": "/".join(current_parts),
                "attributes": changed_attributes,
            }})
        parent = occurrence.component
    return created, attribute_updates


def run(context):
    report_attempted = False
    # Scaffolding creates persistent components and has no rollback by design,
    # so the failure report must still name what this run created.
    created = []
    attribute_updates = []
    try:
        app, design = _active_design()
        target_document = _require_target_document(app)
        if design.designType != adsk.fusion.DesignTypes.ParametricDesignType:
            raise RuntimeError("Component scaffolding requires a parametric design; refusing a destructive design-type change.")
        _, _, preexisting_duplicate_semantic_paths = _root_context_occurrence_map(design.rootComponent)
        if preexisting_duplicate_semantic_paths:
            report_attempted = True
            _emit({{
                "kind": "component-scaffold",
                "project": PROJECT_NAME,
                "manifest_sha256": MANIFEST_SHA256,
                "created": [],
                "attribute_updates": [],
                "duplicate_semantic_paths": preexisting_duplicate_semantic_paths,
                "ok": False,
            }})
            raise RuntimeError("Semantic component paths are already ambiguous; refusing to scaffold into an ambiguous tree.")
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
        report = {{
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
        }}
        report_attempted = True
        _emit(report)
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
            _emit({{
                "kind": "component-scaffold",
                "project": PROJECT_NAME,
                "manifest_sha256": MANIFEST_SHA256,
                "ok": False,
                "error": str(error),
                "created": sorted(set(created)),
                "attribute_updates": attribute_updates,
                "left_behind": sorted(set(created)),
                "traceback": traceback.format_exc(),
            }})
        raise
'''


def emit_document_save_script(manifest: Manifest, document_id: str | None = None) -> str:
    """Emit the document save/adopt transaction.

    Establishes the working document as named and saved: an unsaved Fusion
    document is one crash away from gone, so naming and saving are part of
    establishing the document, not an afterthought. Without ``document_id`` the
    transaction adopts the active document -- saving an unsaved one under the
    manifest's ``project.fusion_document`` name into the resolved folder, or
    version-checkpointing one already saved under that name. With
    ``document_id`` (the dataFile id a previous save report recorded) it
    reconnects by identity instead: an open document with that id is adopted,
    a closed one is located through the data API and opened, and anything else
    is a named refusal. Names are user-mutable and are never used to adopt.
    """
    identity = str(document_id).strip() if document_id is not None and str(document_id).strip() else None
    return _script_prelude(manifest) + f'''DOCUMENT_ID = json.loads({_json_literal(identity)})
DOCUMENT_FOLDER = json.loads({_json_literal(manifest.document_folder)})
SAVE_DESCRIPTION = "fusion-parametric-design checkpoint (" + MANIFEST_SHA256[:12] + ")"


class DocumentSaveRefused(RuntimeError):
    """A named refusal: the transaction cannot save safely, and says why."""

    def __init__(self, refusal, detail):
        self.refusal = refusal
        self.detail = detail
        super().__init__(refusal + ": " + json.dumps(detail, sort_keys=True, default=str))


def _is_target_name(name):
    """The manifest name, or the manifest name plus Fusion's own " vN" suffix."""
    text = str(name or "")
    if text == FUSION_DOCUMENT_NAME or not text.startswith(FUSION_DOCUMENT_NAME + " v"):
        return text == FUSION_DOCUMENT_NAME
    return text[len(FUSION_DOCUMENT_NAME) + 2:].isdigit()


def _open_document_by_data_file_id(app, document_id):
    documents = app.documents
    for index in range(documents.count):
        document = documents.item(index)
        try:
            data_file = document.dataFile
        except Exception:
            # An unsaved open document has no dataFile and cannot be the
            # recorded one; other people's documents are never touched.
            continue
        if data_file and str(getattr(data_file, "id", "")) == document_id:
            return document
    return None


def _name_match_hints(app):
    """Open documents whose name matches the manifest target.

    Reported inside a refusal as a hint only, never adopted: names are
    user-mutable, so a name match is not an identity.
    """
    hints = []
    documents = app.documents
    for index in range(documents.count):
        try:
            name = str(documents.item(index).name)
        except Exception:
            continue
        if _is_target_name(name):
            hints.append(name)
    return sorted(hints)


def _resolve_target_folder(app):
    """The folder a first save writes into.

    The manifest's optional ``project.document_folder`` is a "/"-separated path
    under the active project's root folder; without it the root folder itself
    is the target. Every hop fails closed with a named refusal -- an offline or
    projectless Fusion must refuse, never silently keep the document Untitled.
    """
    data = getattr(app, "data", None)
    if not data:
        raise DocumentSaveRefused(
            "data-api-unavailable",
            {{"detail": "app.data is not available; Fusion may be offline."}},
        )
    project = getattr(data, "activeProject", None)
    if not project:
        raise DocumentSaveRefused(
            "no-active-project",
            {{"detail": "Fusion has no active project to save into; open or select one."}},
        )
    folder = getattr(project, "rootFolder", None)
    if not folder:
        raise DocumentSaveRefused(
            "project-root-unavailable", {{"project": getattr(project, "name", None)}}
        )
    for segment in [part for part in DOCUMENT_FOLDER.split("/") if part]:
        try:
            child = folder.dataFolders.itemByName(segment)
        except Exception as error:
            raise DocumentSaveRefused(
                "folder-not-found",
                {{"segment": segment, "declared_path": DOCUMENT_FOLDER, "error": str(error)}},
            )
        if not child:
            raise DocumentSaveRefused(
                "folder-not-found",
                {{
                    "segment": segment,
                    "declared_path": DOCUMENT_FOLDER,
                    "detail": "Declared project.document_folder segment does not exist; create it in Fusion or correct the manifest.",
                }},
            )
        folder = child
    return folder


def _adopt_recorded_document(app):
    """Reconnect to the recorded document by dataFile id: open wins, then the data API."""
    document = _open_document_by_data_file_id(app, DOCUMENT_ID)
    if document is not None:
        adoption = "adopted-open-document"
    else:
        data = getattr(app, "data", None)
        find_file = getattr(data, "findFileById", None) if data else None
        if not find_file:
            raise DocumentSaveRefused(
                "data-api-unavailable",
                {{
                    "recorded_data_file_id": DOCUMENT_ID,
                    "detail": "The recorded document is not open and app.data.findFileById is not available; Fusion may be offline.",
                }},
            )
        try:
            data_file = find_file(DOCUMENT_ID)
        except Exception:
            data_file = None
        if not data_file:
            raise DocumentSaveRefused(
                "recorded-document-not-found",
                {{
                    "recorded_data_file_id": DOCUMENT_ID,
                    "name_match_hints": _name_match_hints(app),
                    "detail": "No open document and no data item carries the recorded id; it may have been deleted or moved. Refusing to adopt by name: names are user-mutable.",
                }},
            )
        try:
            document = app.documents.open(data_file, True)
        except Exception as error:
            raise DocumentSaveRefused(
                "open-failed", {{"recorded_data_file_id": DOCUMENT_ID, "error": str(error)}}
            )
        if not document:
            raise DocumentSaveRefused("open-failed", {{"recorded_data_file_id": DOCUMENT_ID}})
        adoption = "opened-recorded-document"
    if app.activeDocument != document:
        activate = getattr(document, "activate", None)
        if not activate:
            raise DocumentSaveRefused(
                "activate-unavailable", {{"recorded_data_file_id": DOCUMENT_ID}}
            )
        activate()
    adsk.doEvents()
    if app.activeDocument != document:
        raise DocumentSaveRefused("activate-failed", {{"recorded_data_file_id": DOCUMENT_ID}})
    return document, adoption


def run(context):
    report_attempted = False
    try:
        app = adsk.core.Application.get()
        if DOCUMENT_ID:
            document, adoption = _adopt_recorded_document(app)
        else:
            document = app.activeDocument
            if not document:
                raise DocumentSaveRefused("no-active-document", {{}})
            adoption = "adopted-active-document"

        before = _document_saved_state(document)
        if not DOCUMENT_ID and before.get("is_saved") and not _is_target_name(before.get("name")):
            raise DocumentSaveRefused(
                "active-document-not-target",
                {{
                    "active_document": before.get("name"),
                    "manifest_target": FUSION_DOCUMENT_NAME,
                    "detail": "The active document is a different saved document; refusing to adopt or save it. Activate the target document, or pass the recorded document id.",
                }},
            )
        if before.get("is_saved") is None:
            # Fail closed: with isSaved unreadable there is no way to know
            # whether save or saveAs is the safe operation.
            raise DocumentSaveRefused("saved-state-unreadable", before)
        if not before.get("is_saved"):
            folder = _resolve_target_folder(app)
            if not document.saveAs(FUSION_DOCUMENT_NAME, folder, SAVE_DESCRIPTION, ""):
                raise DocumentSaveRefused(
                    "save-as-failed",
                    {{"name": FUSION_DOCUMENT_NAME, "folder": getattr(folder, "name", None)}},
                )
            save_action = "saved-as"
        else:
            # An unreadable isModified counts as modified: saving a clean
            # document costs a version, skipping a dirty one costs the work.
            if getattr(document, "isModified", True):
                if not document.save(SAVE_DESCRIPTION):
                    raise DocumentSaveRefused("save-failed", {{"name": before.get("name")}})
                save_action = "saved-version"
            else:
                save_action = "already-saved"
        adsk.doEvents()

        after = _document_saved_state(document)
        identity = after.get("data_file") if isinstance(after.get("data_file"), dict) else None
        failures = []
        if after.get("is_saved") is not True:
            failures.append("still-unsaved")
        if not identity or not identity.get("id"):
            failures.append("data-file-identity-unreadable")
        report = {{
            "kind": "document-save",
            "project": PROJECT_NAME,
            "manifest_sha256": MANIFEST_SHA256,
            "recorded_data_file_id": DOCUMENT_ID,
            "adoption": adoption,
            "save_action": save_action,
            "document_name": after.get("name"),
            "manifest_target_name": FUSION_DOCUMENT_NAME,
            # A rename is not a failure: the document's identity is its dataFile
            # id. The mismatch is surfaced so project.fusion_document can be
            # reconciled before name-bound transactions run.
            "name_matches_manifest": _is_target_name(after.get("name")),
            "document_saved_state": after,
            "data_file": identity,
            "failures": failures,
            "ok": not failures,
        }}
        report_attempted = True
        _emit(report)
        if failures:
            raise RuntimeError("Document save did not verify: " + ", ".join(failures))
    except DocumentSaveRefused as refused:
        if not report_attempted:
            report_attempted = True
            _emit({{
                "kind": "document-save",
                "project": PROJECT_NAME,
                "manifest_sha256": MANIFEST_SHA256,
                "recorded_data_file_id": DOCUMENT_ID,
                "manifest_target_name": FUSION_DOCUMENT_NAME,
                "ok": False,
                "refusal": refused.refusal,
                "detail": refused.detail,
            }})
        raise
    except Exception as error:
        if not report_attempted:
            report_attempted = True
            _emit({{"kind": "document-save", "ok": False, "error": str(error), "traceback": traceback.format_exc()}})
        raise
'''


# Skill-wide print-part rules: not manifest-declared, and reported separately
# from PRINT_PART_EXPECTATIONS so a reader can tell the two apart.  One solid is
# what the export transaction already resolves; the bounding-box fraction is a
# plausibility floor on the author's own declared minimum volume.
# ponytail: one global fraction, per-part override when a real part legitimately
# occupies under 0.1% of its bounding box.
PRINT_PART_RULES: dict[str, Any] = {
    "solid_body_count": 1,
    "minimum_volume_bounding_box_fraction": 1e-3,
}


def _print_part_expectations(manifest: Manifest) -> dict[str, dict[str, Any]]:
    """Per-print-part expectations declared by the manifest.

    Only manifest-declared values live here -- the declared minimum volume and
    the declared ``body_name`` when the author gave one.  Without a declaration
    there is nothing falsifiable to check, so a print part with no
    ``printable_parts`` entry fails the gate rather than passing a threshold
    that only proves some body exists.
    """
    expectations: dict[str, dict[str, Any]] = {}
    for part in manifest.printable_parts:
        path = str(part.get("path", "")).strip()
        minimum_volume = part.get("minimum_volume_mm3")
        # Fail closed rather than emit an expectation the gate cannot measure:
        # an undeclared path is reported as `no-declared-expectation`.
        if not path or not isinstance(minimum_volume, (int, float)) or isinstance(minimum_volume, bool):
            continue
        expectation: dict[str, Any] = {"minimum_volume_mm3": float(minimum_volume)}
        if part.get("body_name"):
            expectation["body_name"] = str(part["body_name"]).strip()
        expectations[path] = expectation
    return expectations


def emit_verification_script(manifest: Manifest, nonce: str = "") -> str:
    """Emit the verification transaction.

    `nonce` is echoed into the report and is what binds an export to a report
    this CLI emitted: `emit-export` refuses a report whose nonce does not match
    the one printed when the script was emitted. The default empty nonce keeps
    the checked-in example byte-stable and can never satisfy that gate.
    """
    verification = manifest.verification
    parameter_specs = [
        {"name": spec["name"], "expression": spec["expression"], "units": spec["units"]}
        for spec in _parameter_specs(manifest)
    ]
    return _script_prelude(manifest) + f'''VERIFICATION = json.loads({_json_literal(verification)})
PARAMETER_SPECS = json.loads({_json_literal(parameter_specs)})
VERIFICATION_NONCE = json.loads({_json_literal(str(nonce))})
PRINT_PART_EXPECTATIONS = json.loads({_json_literal(_print_part_expectations(manifest))})
PRINT_PART_RULES = json.loads({_json_literal(PRINT_PART_RULES)})


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
            mismatches.append({{"name": spec["name"], "reason": "missing"}})
            continue
        if existing.expression != spec["expression"]:
            mismatches.append({{
                "name": spec["name"],
                "reason": "expression",
                "expected": spec["expression"],
                "actual": existing.expression,
            }})
        if existing.unit != spec["units"]:
            mismatches.append({{
                "name": spec["name"],
                "reason": "units",
                "expected": spec["units"],
                "actual": existing.unit,
            }})
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

        bounding_boxes = {{}}
        brep_bounding_boxes = {{}}
        geometry = {{}}
        occurrence_transforms = {{}}
        occurrence_states = {{}}
        for path in sorted(relevant_paths):
            occurrence = occurrence_map.get(path)
            if not occurrence:
                continue
            geometry[path] = _body_summary(occurrence)
            occurrence_transforms[path] = _occurrence_transform(occurrence)
            occurrence_states[path] = _occurrence_state(occurrence)
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
        # The print-part gate is measured against declared expectations, never
        # against a bare "some body has more than 1e-9 mm3" threshold: that
        # threshold passed a sliver and then became its own export baseline.
        print_part_failures = []
        for path in sorted(expected_print_paths):
            if path not in component_set:
                continue
            expectation = PRINT_PART_EXPECTATIONS.get(path)
            if not expectation:
                print_part_failures.append({{
                    "path": path,
                    "reason": "no-declared-expectation",
                    "detail": "Declare this path in printable_parts; verification will not assert a print part it has no expectation for.",
                }})
                continue
            solid_rows = [
                row
                for row in geometry.get(path, {{}}).get("bodies", [])
                if row["is_solid"] and row["volume_mm3"] > 1e-9
            ]
            if len(solid_rows) != PRINT_PART_RULES["solid_body_count"]:
                print_part_failures.append({{
                    "path": path,
                    "reason": "solid-body-count",
                    "expected": PRINT_PART_RULES["solid_body_count"],
                    "actual": len(solid_rows),
                    "detail": sorted(row["name"] for row in solid_rows),
                }})
                continue
            body_row = solid_rows[0]
            expected_body_name = expectation.get("body_name")
            if expected_body_name and body_row["name"] != expected_body_name:
                print_part_failures.append({{
                    "path": path,
                    "reason": "body-name-mismatch",
                    "expected": expected_body_name,
                    "actual": body_row["name"],
                }})
                continue
            minimum_volume_mm3 = float(expectation["minimum_volume_mm3"])
            if not body_row["volume_mm3"] >= minimum_volume_mm3:
                print_part_failures.append({{
                    "path": path,
                    "reason": "below-declared-minimum-volume",
                    "expected_minimum_mm3": minimum_volume_mm3,
                    "actual_volume_mm3": body_row["volume_mm3"],
                }})
                continue
            # The floor is author-chosen, so cross-check it against something the
            # author did not choose: a solid cannot be a vanishing fraction of its
            # own bounding box and still be the part.  Without this, a forged
            # 1e-12 floor reopens the sliver hole through the supported path.
            box = brep_bounding_boxes.get(path)
            if isinstance(box, dict) and "min" in box and "max" in box:
                box_volume_mm3 = 1.0
                for index in range(3):
                    box_volume_mm3 *= abs(float(box["max"][index]) - float(box["min"][index]))
                if not minimum_volume_mm3 >= box_volume_mm3 * PRINT_PART_RULES["minimum_volume_bounding_box_fraction"]:
                    print_part_failures.append({{
                        "path": path,
                        "reason": "implausible-declared-minimum",
                        "declared_minimum_mm3": minimum_volume_mm3,
                        "bounding_box_volume_mm3": box_volume_mm3,
                        "required_fraction": PRINT_PART_RULES["minimum_volume_bounding_box_fraction"],
                    }})

        # An unreadable participation state is exactly as indistinguishable from
        # "not in the model" as a suppressed one, so it fails closed too.
        suppressed_occurrences = sorted(
            path for path, state in occurrence_states.items() if state["is_suppressed"] is True
        )
        unreadable_occurrence_states = sorted(
            path for path, state in occurrence_states.items() if state["is_suppressed"] is None
        )
        # Suppression is how Fusion models configurations and open/closed/service
        # states, so it is declarable: undeclared suppression fails, declared
        # suppression is recorded and passes.
        undeclared_suppressed_occurrences = sorted(
            set(suppressed_occurrences) - set(VERIFICATION.get("allowed_suppressed_paths", []))
        )
        suppressed_timeline_allowed = bool(VERIFICATION.get("allow_suppressed_timeline_features", False))

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
        if timeline["suppressed"] and not suppressed_timeline_allowed:
            failures.append("timeline-suppressed")
        if undeclared_suppressed_occurrences:
            failures.append("suppressed-occurrence")
        if unreadable_occurrence_states:
            failures.append("unreadable-occurrence-state")
        if any(not result.get("ok", False) for result in clearance_results):
            failures.append("clearance")
        if any(not result.get("ok", False) for result in interference_results):
            failures.append("interference")
        if expected_print_parts_missing or print_part_failures:
            failures.append("print-parts")

        # `checked` names only the gates this run actually performed, so `ok`
        # can never assert a gate the manifest never declared.  A declared-but-
        # unrunnable gate produces a failing result above, not an omission here.
        checked = ["compute-all", "design-type", "timeline-health", "timeline-suppressed"]
        not_declared = []
        for token, ran in (
            ("parameters", bool(PARAMETER_SPECS)),
            ("ambiguous-components", bool(relevant_paths)),
            ("suppressed-occurrence", bool(occurrence_states)),
            ("unreadable-occurrence-state", bool(occurrence_states)),
            ("required-components", bool(required_paths)),
            ("clearance", bool(clearance_results)),
            ("interference", bool(interference_results)),
            ("print-parts", bool(expected_print_paths)),
        ):
            (checked if ran else not_declared).append(token)

        report = {{
            "kind": "verification",
            "project": PROJECT_NAME,
            "manifest_sha256": MANIFEST_SHA256,
            "verification_nonce": VERIFICATION_NONCE,
            "document_saved_state": _document_saved_state(app.activeDocument),
            "compute_invoked": compute_invoked,
            "is_parametric": design.designType == adsk.fusion.DesignTypes.ParametricDesignType,
            "ok": not failures,
            # `ok` covers the gates in `checked` only.  `not_declared` gates were
            # never defined for this manifest and `unchecked` ones need external
            # analysis or a printed part; neither is evidence of anything.
            "checked": sorted(checked),
            "not_declared": sorted(not_declared),
            "unchecked": ["printability", "structural", "thermal", "physical"],
            "failures": failures,
            "duplicate_semantic_paths": duplicate_semantic_paths,
            "ambiguous_component_paths": ambiguous_component_paths,
            "required_components_missing": required_missing,
            "parameter_mismatches": parameter_mismatches,
            "expected_print_parts_missing": expected_print_parts_missing,
            "print_part_expectations": PRINT_PART_EXPECTATIONS,
            "print_part_rules": PRINT_PART_RULES,
            "print_part_failures": print_part_failures,
            "suppressed_occurrences": suppressed_occurrences,
            "undeclared_suppressed_occurrences": undeclared_suppressed_occurrences,
            "unreadable_occurrence_states": unreadable_occurrence_states,
            "timeline": timeline,
            "bounding_boxes_mm": bounding_boxes,
            "brep_bounding_boxes_mm": brep_bounding_boxes,
            "occurrence_transforms": occurrence_transforms,
            "occurrence_states": occurrence_states,
            "geometry": geometry,
            "clearance_results": clearance_results,
            "interference_results": interference_results,
        }}
        report_attempted = True
        _emit(report)
        if failures:
            raise RuntimeError("Fusion design verification failed: " + ", ".join(failures))
    except Exception as error:
        if not report_attempted:
            report_attempted = True
            _emit({{"kind": "verification", "ok": False, "error": str(error), "traceback": traceback.format_exc()}})
        raise
'''
