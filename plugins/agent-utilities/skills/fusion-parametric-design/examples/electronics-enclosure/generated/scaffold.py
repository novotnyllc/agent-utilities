import json
import os
import time
import traceback
import adsk.core
import adsk.fusion

PROJECT_NAME = 'wearable-controller-pod'
FUSION_DOCUMENT_NAME = 'Wearable Controller Pod'
MANIFEST_SHA256 = '40a7264c16975c5bfd37627450fd8a156c2f483becd936c0dae268ce6e45f4d1'
REPORT_BEGIN = 'FUSION_DESIGN_REPORT_BEGIN'
REPORT_END = 'FUSION_DESIGN_REPORT_END'
# Where _emit tees its report so a transport timeout loses nothing. None when
# this transaction declares no output directory of its own.
REPORT_TEE_DIR = None
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


def _is_target_name(name):
    """The manifest name, or the manifest name plus Fusion's own " vN" suffix.

    Fusion builds differ on whether Document.name carries the version suffix,
    and a saved-as document may report either form -- so every name-bound
    check accepts both, and nothing else.
    """
    text = str(name or "")
    if text == FUSION_DOCUMENT_NAME or not text.startswith(FUSION_DOCUMENT_NAME + " v"):
        return text == FUSION_DOCUMENT_NAME
    return text[len(FUSION_DOCUMENT_NAME) + 2:].isdigit()


def _require_target_document(app):
    active_document = app.activeDocument
    active_name = active_document.name if active_document else None
    if not _is_target_name(active_name):
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
        or not _is_target_name(target_document.name)
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


def _document_saved_state(document):
    """The document's saved identity, fail closed.

    "Unsaved" and "could not read" must never look alike: an unreadable probe is
    reported as available:false with a named reason, never defaulted to a value
    that reads as an answer. A saved document's identity is its dataFile id --
    names are user-mutable and are reported, not trusted.
    """
    if document is None:
        return {"available": False, "reason": "no-active-document"}
    state = {"available": True, "name": None, "is_saved": None, "data_file": None}
    try:
        state["name"] = str(document.name)
    except Exception:
        pass
    try:
        is_saved = getattr(document, "isSaved", None)
    except Exception as error:
        # Fusion properties raise rather than return None when their backing
        # state is unavailable; that is "could not read", not "unsaved".
        state["available"] = False
        state["reason"] = "isSaved-unreadable: " + str(error)
        return state
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
    identity = {}
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

COMPONENT_PATHS = json.loads('["References","References/PD Trigger Reference","References/PD Trigger Envelope","References/USB-C Insertion Keep-Out","References/EKYLIN Converter Reference","References/EKYLIN Converter Envelope","References/EKYLIN Wire Bend Keep-Out","Product","Product/Base","Product/Lid","Fixtures","Validation","Validation/PD Fit Coupon"]')
COMPONENT_ROLES = json.loads('{"Product/Base":"product","Product/Lid":"product","References/EKYLIN Converter Envelope":"packing","References/EKYLIN Converter Reference":"reference","References/EKYLIN Wire Bend Keep-Out":"keepout","References/PD Trigger Envelope":"packing","References/PD Trigger Reference":"reference","References/USB-C Insertion Keep-Out":"keepout","Validation/PD Fit Coupon":"validation"}')
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
        role = COMPONENT_ROLES.get("/".join(current_parts))
        if role:
            if _ensure_component_attribute(occurrence.component, "role", role):
                changed_attributes.append("role")
        else:
            # A manifest revision that drops a path's classification must also
            # retract the previously written role: inventory is attribute-first,
            # so a stale attribute would keep reporting the obsolete role.
            stale = occurrence.component.attributes.itemByName(ATTRIBUTE_GROUP, "role")
            if stale:
                if not stale.deleteMe():
                    raise RuntimeError(
                        "Fusion failed to remove the stale role attribute on " + "/".join(current_parts)
                    )
                changed_attributes.append("role-removed")
        if changed_attributes:
            attribute_updates.append({
                "component_path": "/".join(current_parts),
                "attributes": changed_attributes,
            })
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
            _emit({
                "kind": "component-scaffold",
                "project": PROJECT_NAME,
                "manifest_sha256": MANIFEST_SHA256,
                "created": [],
                "attribute_updates": [],
                "duplicate_semantic_paths": preexisting_duplicate_semantic_paths,
                "ok": False,
            })
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
            _emit({
                "kind": "component-scaffold",
                "project": PROJECT_NAME,
                "manifest_sha256": MANIFEST_SHA256,
                "ok": False,
                "error": str(error),
                "created": sorted(set(created)),
                "attribute_updates": attribute_updates,
                "left_behind": sorted(set(created)),
                "traceback": traceback.format_exc(),
            })
        raise
