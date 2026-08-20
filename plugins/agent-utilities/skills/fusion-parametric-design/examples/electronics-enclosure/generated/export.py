import json
import os
import time
import traceback
import adsk.core
import adsk.fusion

PROJECT_NAME = 'wearable-controller-pod'
FUSION_DOCUMENT_NAME = 'Wearable Controller Pod'
MANIFEST_SHA256 = 'dea2a647d99f41c6f2829a67e92a66f634eba5f838d056d86464efa3fef3a642'
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

import hashlib
import os
import uuid

EXPORT_SPECS = json.loads('{"export_dir":"FUSION_EXPORT_DIR","formats":["step","3mf"],"index_filename":"export-index__dea2a647.json","material_decision":{"confidence":"provisional","coupon_component":"90_VALIDATION/VAL__PD_FIT_COUPON","family":"PETG","formulation":null,"rationale":"The lid snap rim deflects at every opening and must recover; PETG has the toughness and strain recovery for a repeatedly deflected snap, where PLA would be brittle at the snap root and crack after a few cycles. Nothing here needs heat, UV, or sustained-load resistance beyond PETG, so the tougher families are not warranted. Family only: the specific product is not chosen, so every material-dependent number stays provisional.","source_id":"enclosure_material_requirements","unresolved_risks":["No formulation is named, so no data-sheet number backs any material-dependent value.","fab_fit_clearance is a hypothesis until VAL__PD_FIT_COUPON is printed and measured on the machine that will make the parts.","Snap-rim strain and cycle life are unverified; the coupon proves the pocket fit, not the snap."]},"parts":[{"expected_bounds_mm":{"max":[100.0,110.0,2.0],"min":[0.0,50.0,0.0]},"expected_total_solid_volume_mm3":12000.0,"expected_transform":[1.0,0.0,0.0,0.0,0.0,1.0,0.0,0.0,0.0,0.0,1.0,0.0,0.0,0.0,0.0,1.0],"filenames":{"3mf":"wearable-controller-pod__10_product-prod__base__dea2a647.3mf","step":"wearable-controller-pod__10_product-prod__base__dea2a647.step"},"manufacturing_intent":{"id":"prod_base","material":{"assumption":"PETG","status":"provisional"},"orientation":{"allowed_alternatives":[],"contact_face":"-Z","rationale":"The flat floor sits on the plate, which is why support_policy is \'none\' here, and keeps the seam off the mating rim. Whether the part actually needs supports is a slicer result, not a manifest claim."},"print_as":"separate","protected_features":[{"description":"Top rim mates with the lid; keep it support-free and unscarred.","kind":"mating-face"},{"description":"USB-C insertion opening must stay dimensionally clean.","kind":"hole"}],"quantity":1,"strength":{"infill_percent":{"max":40,"min":20,"target":25},"min_perimeters":3},"support_policy":"none"},"path":"10_PRODUCT/PROD__BASE"},{"expected_bounds_mm":{"max":[35.0,13.0,12.0],"min":[0.0,0.0,10.0]},"expected_total_solid_volume_mm3":910.0,"expected_transform":[1.0,0.0,0.0,0.0,0.0,1.0,0.0,0.0,0.0,0.0,1.0,0.0,0.0,0.0,0.0,1.0],"filenames":{"3mf":"wearable-controller-pod__10_product-prod__lid__dea2a647.3mf","step":"wearable-controller-pod__10_product-prod__lid__dea2a647.step"},"manufacturing_intent":{"id":"prod_lid","material":{"assumption":"PETG","status":"provisional"},"orientation":{"allowed_alternatives":["-Z"],"contact_face":"+Z","rationale":"Printing the lid top-down keeps the visible outer face against the plate and the snap rim accessible."},"print_as":"separate","protected_features":[{"description":"Snap rim engages the base; supports must not touch it.","kind":"mating-face"}],"quantity":1,"strength":{"infill_percent":{"target":20},"min_perimeters":3},"support_policy":"build-plate-only"},"path":"10_PRODUCT/PROD__LID"},{"expected_bounds_mm":{"max":[10.0,110.0,2.0],"min":[0.0,100.0,0.0]},"expected_total_solid_volume_mm3":200.0,"expected_transform":[1.0,0.0,0.0,0.0,0.0,1.0,0.0,0.0,0.0,0.0,1.0,0.0,0.0,0.0,0.0,1.0],"filenames":{"3mf":"wearable-controller-pod__90_validation-val__pd_fit_coupon__dea2a647.3mf","step":"wearable-controller-pod__90_validation-val__pd_fit_coupon__dea2a647.step"},"manufacturing_intent":{"id":"val_pd_fit_coupon","material":{"assumption":"PETG","status":"provisional"},"orientation":{"allowed_alternatives":[],"contact_face":"-Z","rationale":"Coupon prints flat in the same orientation as the base pocket it validates."},"print_as":"separate","protected_features":[{"description":"Pocket walls are the measured fit surfaces.","kind":"critical-surface"}],"quantity":1,"strength":{"infill_percent":{"target":15},"min_perimeters":2},"support_policy":"none"},"path":"90_VALIDATION/VAL__PD_FIT_COUPON"}],"verification_report_sha256":"7bbbf80e49641add512a277e8d51684622288898a44842cba944c2ca97f972ba"}')
EXPORT_STALENESS_TOLERANCE_MM = 1e-3
# Volume is compared relatively: it scales as the cube of a length, so an absolute
# millimetre tolerance would be meaningless across part sizes. 1e-4 is chosen to
# sit alongside the bounds gate rather than far below it -- 1e-3 mm on a 100 mm
# part is ~1e-5 relative, and volume goes as the cube, so a tighter volume figure
# would make this the strictest gate of the three. The producer and the
# re-measurement are the same summation, so there is no systematic offset to
# absorb; the headroom is for Fusion's recompute jitter, which cannot be measured
# offline. It is still orders of magnitude below any real edit: deleting an
# internal boss or thinning a wall moves volume by percent, not by 0.01%.
# A false alarm on the most safety-critical gate is how a gate gets disabled.
EXPORT_STALENESS_VOLUME_RELATIVE_TOLERANCE = 1e-4
# transform2 is a 4x4 in Fusion's internal centimetres; the rotation entries are
# dimensionless, so one absolute tolerance covers both halves.
EXPORT_STALENESS_TRANSFORM_TOLERANCE = 1e-9
# Residual, stated in the emitted script because it is the script that gates:
# The staleness gate re-measures bounds, total solid volume, and the occurrence transform. An edit that preserves all three -- relocating a hole, swapping a fillet for an equal-volume chamfer -- is not detected, and the report's clearance and interference results are not re-run. The gate detects drift in the properties it names; it does not prove the exported geometry is the verified geometry.
FORMAT_OPTION_ATTRIBUTES = {
    "step": "createSTEPExportOptions",
    "3mf": "createC3MFExportOptions",
    "stl": "createSTLExportOptions",
}


def _file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1048576)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _missing_export_capabilities(design):
    missing = []
    export_manager = getattr(design, "exportManager", None)
    if not export_manager:
        return ["Design.exportManager"], None
    if not hasattr(export_manager, "execute"):
        missing.append("ExportManager.execute")
    for export_format in EXPORT_SPECS["formats"]:
        attribute = FORMAT_OPTION_ATTRIBUTES[export_format]
        if not hasattr(export_manager, attribute):
            missing.append("ExportManager." + attribute)
    return missing, export_manager


def _document_identity(target_document):
    saved = bool(getattr(target_document, "isSaved", False))
    version = "unsaved"
    if saved:
        try:
            data_file = target_document.dataFile
            if data_file:
                version = {
                    "id": str(data_file.id),
                    "version_number": int(data_file.versionNumber),
                }
        except Exception:
            version = "unsaved"
    return saved, version


def _occurrence_transform(occurrence):
    transform = getattr(occurrence, "transform2", None)
    if not transform:
        return None
    return [float(value) for value in transform.asArray()]


def _resolve_single_solid_body(occurrence, path, failures, resolution_errors):
    bodies = occurrence.bRepBodies
    name_counts = {}
    solids = []
    for index in range(bodies.count):
        body = bodies.item(index)
        name_counts[body.name] = name_counts.get(body.name, 0) + 1
        if bool(body.isSolid) and float(body.volume) * 1000.0 > 1e-9:
            solids.append(body)
    duplicate_names = sorted(name for name, count in name_counts.items() if count > 1)
    if duplicate_names:
        failures.add("ambiguous-body")
        resolution_errors.append({
            "path": path,
            "reason": "duplicate-body-names",
            "detail": duplicate_names,
        })
        return None
    if not solids:
        failures.add("missing-solid")
        resolution_errors.append({"path": path, "reason": "no-positive-solid-body"})
        return None
    if len(solids) > 1:
        failures.add("ambiguous-body")
        resolution_errors.append({
            "path": path,
            "reason": "multiple-solid-bodies",
            "detail": sorted(body.name for body in solids),
        })
        return None
    return solids[0]


def _bounds_are_stale(actual, expected):
    for key in ("min", "max"):
        for index in range(3):
            if abs(float(actual[key][index]) - float(expected[key][index])) > EXPORT_STALENESS_TOLERANCE_MM:
                return True
    return False


def _solid_volume_mm3(occurrence):
    """Total volume of the positive solid bodies, matching the verification report."""
    total = 0.0
    bodies = occurrence.bRepBodies
    for index in range(bodies.count):
        body = bodies.item(index)
        volume_mm3 = float(body.volume) * 1000.0
        if bool(body.isSolid) and volume_mm3 > 1e-9:
            total += volume_mm3
    return total


def _volume_is_stale(actual, expected):
    expected = float(expected)
    return abs(float(actual) - expected) > abs(expected) * EXPORT_STALENESS_VOLUME_RELATIVE_TOLERANCE


def _transform_is_stale(actual, expected):
    if not isinstance(actual, list) or len(actual) != len(expected):
        return True
    for index in range(len(expected)):
        if abs(float(actual[index]) - float(expected[index])) > EXPORT_STALENESS_TRANSFORM_TOLERANCE:
            return True
    return False


def _remove_created(paths):
    errors = []
    for path in reversed(paths):
        try:
            os.remove(path)
        except FileNotFoundError:
            continue
        except Exception as error:
            errors.append(path + ": " + str(error))
    return errors


def run(context):
    report_attempted = False
    created_paths = []
    try:
        app, design = _active_design()
        missing_capabilities, export_manager = _missing_export_capabilities(design)
        if missing_capabilities:
            report_attempted = True
            _emit({
                "kind": "export-handoff",
                "project": PROJECT_NAME,
                "manifest_sha256": MANIFEST_SHA256,
                "ok": False,
                "failures": ["export-capability"],
                "missing_export_capabilities": missing_capabilities,
            })
            raise RuntimeError(
                "The live Fusion export capability is unavailable; missing "
                + ", ".join(missing_capabilities)
                + ". A missing constructor name is an adapter/API mismatch, not proof Fusion cannot export."
            )
        target_document = _require_target_document(app)
        _pump_events(app, design, target_document)

        document_saved, document_version = _document_identity(target_document)
        try:
            units = design.unitsManager.defaultLengthUnits
        except Exception:
            units = None

        _, occurrence_map, duplicate_semantic_paths = _root_context_occurrence_map(design.rootComponent)
        failures = set()
        resolution_errors = []
        stale_parts = []
        resolved = {}
        for part in EXPORT_SPECS["parts"]:
            path = part["path"]
            if path in duplicate_semantic_paths:
                failures.add("ambiguous-components")
                resolution_errors.append({
                    "path": path,
                    "reason": "duplicate-semantic-path",
                    "detail": duplicate_semantic_paths[path],
                })
                continue
            occurrence = occurrence_map.get(path)
            if not occurrence:
                failures.add("missing-component")
                resolution_errors.append({"path": path, "reason": "component-path-missing"})
                continue
            body = _resolve_single_solid_body(occurrence, path, failures, resolution_errors)
            if body is None:
                continue
            expected_body_name = part.get("expected_body_name")
            if expected_body_name and body.name != expected_body_name:
                failures.add("body-name-mismatch")
                resolution_errors.append({
                    "path": path,
                    "reason": "declared-body-name-mismatch",
                    "expected": expected_body_name,
                    "actual": body.name,
                })
                continue
            try:
                actual_bounds = _bbox_mm(occurrence)
            except Exception as error:
                failures.add("stale-verification")
                stale_parts.append({"path": path, "reason": "bounds-unavailable", "detail": str(error)})
                continue
            if _bounds_are_stale(actual_bounds, part["expected_bounds_mm"]):
                failures.add("stale-verification")
                stale_parts.append({
                    "path": path,
                    "reason": "bounds-drifted",
                    "expected_bounds_mm": part["expected_bounds_mm"],
                    "actual_bounds_mm": actual_bounds,
                })
                continue
            # Bounds alone are six numbers: an edit that preserves the extent
            # passes them. Volume and placement are the other two properties the
            # verification report already measured, so they are re-measured here.
            try:
                actual_volume = _solid_volume_mm3(occurrence)
            except Exception as error:
                failures.add("stale-verification")
                stale_parts.append({"path": path, "reason": "volume-unavailable", "detail": str(error)})
                continue
            if _volume_is_stale(actual_volume, part["expected_total_solid_volume_mm3"]):
                failures.add("stale-verification")
                stale_parts.append({
                    "path": path,
                    "reason": "volume-drifted",
                    "expected_total_solid_volume_mm3": part["expected_total_solid_volume_mm3"],
                    "actual_total_solid_volume_mm3": actual_volume,
                })
                continue
            actual_transform = _occurrence_transform(occurrence)
            if _transform_is_stale(actual_transform, part["expected_transform"]):
                failures.add("stale-verification")
                stale_parts.append({
                    "path": path,
                    "reason": "transform-drifted",
                    "expected_transform": part["expected_transform"],
                    "actual_transform": actual_transform,
                })
                continue
            resolved[path] = {
                "occurrence": occurrence,
                "body": body,
                "actual_bounds_mm": actual_bounds,
                "actual_total_solid_volume_mm3": actual_volume,
                "transform": actual_transform,
            }

        export_dir = EXPORT_SPECS["export_dir"]
        existing_outputs = []
        if not os.path.isdir(export_dir) or not os.access(export_dir, os.W_OK):
            failures.add("missing-output-dir")
        else:
            target_names = [EXPORT_SPECS["index_filename"]]
            for part in EXPORT_SPECS["parts"]:
                for export_format in EXPORT_SPECS["formats"]:
                    target_names.append(part["filenames"][export_format])
            for name in target_names:
                if os.path.lexists(os.path.join(export_dir, name)):
                    existing_outputs.append(name)
            if existing_outputs:
                failures.add("output-exists")

        if failures:
            report_attempted = True
            _emit({
                "kind": "export-handoff",
                "project": PROJECT_NAME,
                "manifest_sha256": MANIFEST_SHA256,
                "verification_report_sha256": EXPORT_SPECS["verification_report_sha256"],
                "ok": False,
                "failures": sorted(failures),
                "resolution_errors": resolution_errors,
                "stale_parts": stale_parts,
                "existing_outputs": sorted(existing_outputs),
                "export_dir": export_dir,
            })
            raise RuntimeError("Fusion export failed closed: " + ", ".join(sorted(failures)))

        export_run_id = uuid.uuid4().hex
        artifacts = []
        try:
            for part in EXPORT_SPECS["parts"]:
                path = part["path"]
                resolution = resolved[path]
                occurrence = resolution["occurrence"]
                body = resolution["body"]
                for export_format in EXPORT_SPECS["formats"]:
                    filename = part["filenames"][export_format]
                    target = os.path.join(export_dir, filename)
                    constructor = FORMAT_OPTION_ATTRIBUTES[export_format]
                    if export_format == "step":
                        # STEP options take a Component (live-verified: the root-context
                        # occurrence proxy is rejected); the occurrence transform is
                        # recorded per artifact so the assembly frame stays recoverable.
                        options = export_manager.createSTEPExportOptions(target, occurrence.component)
                        export_scope = "component"
                    else:
                        options = getattr(export_manager, constructor)(body, target)
                        export_scope = "body"
                    if not options:
                        raise RuntimeError("Fusion failed to create export options for " + filename)
                    if os.path.lexists(target):
                        raise RuntimeError("Output appeared after preflight; refusing to overwrite " + target)
                    created_paths.append(target)
                    executed = export_manager.execute(options)
                    if not executed or not os.path.isfile(target) or os.path.getsize(target) <= 0:
                        raise RuntimeError("Fusion export did not produce " + target)
                    artifact_entry = {
                        "part_path": path,
                        "body_name": body.name,
                        "format": export_format,
                        "filename": filename,
                        "export_scope": export_scope,
                        "export_options": {"constructor": constructor, "defaults": True},
                        "byte_size": os.path.getsize(target),
                        "sha256": _file_sha256(target),
                        "transform": resolution["transform"],
                        "bounds_mm": resolution["actual_bounds_mm"],
                        "total_solid_volume_mm3": resolution["actual_total_solid_volume_mm3"],
                    }
                    if "manufacturing_intent" in part:
                        artifact_entry["manufacturing_intent"] = part["manufacturing_intent"]
                    artifacts.append(artifact_entry)

            index = {
                "kind": "export-handoff",
                "project": PROJECT_NAME,
                "manifest_sha256": MANIFEST_SHA256,
                "verification_report_sha256": EXPORT_SPECS["verification_report_sha256"],
                "export_run_id": export_run_id,
                "document_name": target_document.name,
                "document_saved": document_saved,
                "document_modified": bool(getattr(target_document, "isModified", False)),
                "document_version": document_version,
                "units": units,
                "export_dir": export_dir,
                "formats": EXPORT_SPECS["formats"],
                "artifacts": artifacts,
                "verification_binding_residual": "The staleness gate re-measures bounds, total solid volume, and the occurrence transform. An edit that preserves all three -- relocating a hole, swapping a fillet for an equal-volume chamfer -- is not detected, and the report's clearance and interference results are not re-run. The gate detects drift in the properties it names; it does not prove the exported geometry is the verified geometry.",
            }
            if "material_decision" in EXPORT_SPECS:
                index["material_decision"] = EXPORT_SPECS["material_decision"]
            design_state_rows = []
            for artifact in artifacts:
                design_state_rows.append(
                    "| " + artifact["filename"]
                    + " | " + json.dumps(document_version)
                    + " | " + artifact["part_path"]
                    + " | " + (units if units else "unknown")
                    + " | " + artifact["export_options"]["constructor"] + " (defaults)"
                    + " | " + str(artifact["byte_size"])
                    + " | " + artifact["sha256"]
                    + " | " + export_run_id[:8]
                    + " | " + EXPORT_SPECS["verification_report_sha256"][:12]
                    + " | \u2014 | |"
                )
            index_path = os.path.join(export_dir, EXPORT_SPECS["index_filename"])
            with open(index_path, "x", encoding="utf-8") as handle:
                created_paths.append(index_path)
                handle.write(json.dumps(index, indent=2, sort_keys=True))
                handle.write("\n")
        except Exception as error:
            created_and_removed = list(created_paths)
            cleanup_errors = _remove_created(created_paths)
            report_attempted = True
            failure_tokens = ["export-incomplete"]
            if cleanup_errors:
                failure_tokens.append("cleanup-incomplete")
            _emit({
                "kind": "export-handoff",
                "project": PROJECT_NAME,
                "manifest_sha256": MANIFEST_SHA256,
                "verification_report_sha256": EXPORT_SPECS["verification_report_sha256"],
                "ok": False,
                "failures": failure_tokens,
                "error": str(error),
                "created_and_removed": created_and_removed,
                "cleanup_errors": cleanup_errors,
                "traceback": traceback.format_exc(),
            })
            if cleanup_errors:
                raise RuntimeError(
                    "Fusion export failed and cleanup left partial artifacts: " + "; ".join(cleanup_errors)
                ) from error
            raise

        report = dict(index)
        report["ok"] = True
        report["design_state_rows"] = design_state_rows
        report_attempted = True
        _emit(report)
    except Exception as error:
        if not report_attempted:
            report_attempted = True
            _emit({
                "kind": "export-handoff",
                "project": PROJECT_NAME,
                "manifest_sha256": MANIFEST_SHA256,
                "ok": False,
                "error": str(error),
                "traceback": traceback.format_exc(),
            })
        raise
