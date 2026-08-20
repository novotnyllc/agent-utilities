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

DOCUMENT_ID = json.loads('null')
DOCUMENT_FOLDER = json.loads('""')
SAVE_DESCRIPTION = "fusion-parametric-design checkpoint (" + MANIFEST_SHA256[:12] + ")"


class DocumentSaveRefused(RuntimeError):
    """A named refusal: the transaction cannot save safely, and says why."""

    def __init__(self, refusal, detail):
        self.refusal = refusal
        self.detail = detail
        super().__init__(refusal + ": " + json.dumps(detail, sort_keys=True, default=str))


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


def _probe(owner, attribute):
    """Read a data-API property that may not exist or may itself raise.

    Fusion's data properties raise RuntimeError (not AttributeError) when the
    backing state is absent -- `Data.activeProject` was measured raising
    `InternalValidationError` on a live session with three healthy projects --
    so a bare getattr default is not a probe. Returns (value, error_text).
    """
    try:
        return getattr(owner, attribute), None
    except Exception as error:
        return None, str(error)


def _resolve_target_folder(app):
    """The folder a first save writes into.

    The active project's root folder; when Fusion cannot report an active
    project, the data panel's current folder (`Data.activeFolder`) -- the same
    default Fusion's own save dialog uses. The manifest's optional
    ``project.document_folder`` is a "/"-separated path under the project root.
    Every hop fails closed with a named refusal -- an offline or projectless
    Fusion must refuse, never silently keep the document Untitled.
    """
    data, data_error = _probe(app, "data")
    if not data:
        raise DocumentSaveRefused(
            "data-api-unavailable",
            {"detail": "app.data is not available; Fusion may be offline.", "error": data_error},
        )
    project, project_error = _probe(data, "activeProject")
    root = None
    root_error = None
    if project:
        root, root_error = _probe(project, "rootFolder")
    if not root:
        active_folder, active_folder_error = _probe(data, "activeFolder")
        if active_folder and not DOCUMENT_FOLDER:
            return active_folder
        if active_folder:
            # A declared folder path is anchored at a project root, so recover
            # the root through the panel folder's own project.
            parent_project, parent_error = _probe(active_folder, "parentProject")
            if parent_project:
                root, root_error = _probe(parent_project, "rootFolder")
            else:
                root_error = parent_error
        else:
            root_error = root_error or active_folder_error
    if not root:
        raise DocumentSaveRefused(
            "no-active-project",
            {
                "detail": "Fusion reports no active project and no data-panel folder to save into; select a project in the Data panel.",
                "active_project_error": project_error,
                "resolution_error": root_error,
            },
        )
    folder = root
    for segment in [part for part in DOCUMENT_FOLDER.split("/") if part]:
        try:
            child = folder.dataFolders.itemByName(segment)
        except Exception as error:
            raise DocumentSaveRefused(
                "folder-not-found",
                {"segment": segment, "declared_path": DOCUMENT_FOLDER, "error": str(error)},
            )
        if not child:
            raise DocumentSaveRefused(
                "folder-not-found",
                {
                    "segment": segment,
                    "declared_path": DOCUMENT_FOLDER,
                    "detail": "Declared project.document_folder segment does not exist; create it in Fusion or correct the manifest.",
                },
            )
        folder = child
    return folder


def _adopt_recorded_document(app):
    """Reconnect to the recorded document by dataFile id: open wins, then the data API."""
    document = _open_document_by_data_file_id(app, DOCUMENT_ID)
    if document is not None:
        adoption = "adopted-open-document"
    else:
        data, _data_error = _probe(app, "data")
        find_file = getattr(data, "findFileById", None) if data else None
        if not find_file:
            raise DocumentSaveRefused(
                "data-api-unavailable",
                {
                    "recorded_data_file_id": DOCUMENT_ID,
                    "detail": "The recorded document is not open and app.data.findFileById is not available; Fusion may be offline.",
                },
            )
        # Measured live: findFileById raises for a missing id ("3 : file not
        # found") rather than returning None, and raises the same way when the
        # data service is unreachable -- so the raw error text is carried in
        # the refusal, where a deleted document and an offline service read
        # differently even though the token is one.
        find_error = None
        try:
            data_file = find_file(DOCUMENT_ID)
        except Exception as error:
            find_error = str(error)
            data_file = None
        if not data_file:
            raise DocumentSaveRefused(
                "recorded-document-not-found",
                {
                    "recorded_data_file_id": DOCUMENT_ID,
                    "name_match_hints": _name_match_hints(app),
                    "error": find_error,
                    "detail": "No open document and no data item carries the recorded id; read `error` to tell a deleted or moved document from an unreachable data service. Refusing to adopt by name: names are user-mutable.",
                },
            )
        try:
            document = app.documents.open(data_file, True)
        except Exception as error:
            raise DocumentSaveRefused(
                "open-failed", {"recorded_data_file_id": DOCUMENT_ID, "error": str(error)}
            )
        if not document:
            raise DocumentSaveRefused("open-failed", {"recorded_data_file_id": DOCUMENT_ID})
        adoption = "opened-recorded-document"
    if app.activeDocument != document:
        activate = getattr(document, "activate", None)
        if not activate:
            raise DocumentSaveRefused(
                "activate-unavailable", {"recorded_data_file_id": DOCUMENT_ID}
            )
        activate()
    adsk.doEvents()
    if app.activeDocument != document:
        raise DocumentSaveRefused("activate-failed", {"recorded_data_file_id": DOCUMENT_ID})
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
                raise DocumentSaveRefused("no-active-document", {})
            adoption = "adopted-active-document"

        before = _document_saved_state(document)
        if not DOCUMENT_ID and before.get("is_saved") and not _is_target_name(before.get("name")):
            raise DocumentSaveRefused(
                "active-document-not-target",
                {
                    "active_document": before.get("name"),
                    "manifest_target": FUSION_DOCUMENT_NAME,
                    "detail": "The active document is a different saved document; refusing to adopt or save it. Activate the target document, or pass the recorded document id.",
                },
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
                    {"name": FUSION_DOCUMENT_NAME, "folder": getattr(folder, "name", None)},
                )
            save_action = "saved-as"
        else:
            # An unreadable isModified counts as modified: saving a clean
            # document costs a version, skipping a dirty one costs the work.
            if getattr(document, "isModified", True):
                if not document.save(SAVE_DESCRIPTION):
                    raise DocumentSaveRefused("save-failed", {"name": before.get("name")})
                save_action = "saved-version"
            else:
                save_action = "already-saved"
        adsk.doEvents()

        # The durable identity is assigned asynchronously: measured live, the
        # dataFile id immediately after a first save was a local staging path
        # and became the stable dm.lineage urn only after cloud sync. Wait
        # briefly for the stable id; a transient one is recorded and flagged,
        # never silently treated as durable.
        after = _document_saved_state(document)
        deadline = time.time() + 10.0
        while time.time() < deadline:
            candidate = after.get("data_file") if isinstance(after.get("data_file"), dict) else None
            if candidate and str(candidate.get("id") or "").startswith("urn:"):
                break
            adsk.doEvents()
            time.sleep(0.25)
            after = _document_saved_state(document)

        identity = after.get("data_file") if isinstance(after.get("data_file"), dict) else None
        failures = []
        if after.get("is_saved") is not True:
            failures.append("still-unsaved")
        if not identity or not identity.get("id"):
            failures.append("data-file-identity-unreadable")
        report = {
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
            # False means the id is still Fusion's local staging identity (the
            # save is durable on disk, the *cloud* id is not assigned yet).
            # Record it provisionally and refresh it from the next checkpoint
            # save's report; reconnection by a transient id can fail.
            "data_file_id_stable": bool(
                identity and str(identity.get("id") or "").startswith("urn:")
            ),
            "failures": failures,
            "ok": not failures,
        }
        report_attempted = True
        _emit(report)
        if failures:
            raise RuntimeError("Document save did not verify: " + ", ".join(failures))
    except DocumentSaveRefused as refused:
        if not report_attempted:
            report_attempted = True
            _emit({
                "kind": "document-save",
                "project": PROJECT_NAME,
                "manifest_sha256": MANIFEST_SHA256,
                "recorded_data_file_id": DOCUMENT_ID,
                "manifest_target_name": FUSION_DOCUMENT_NAME,
                "ok": False,
                "refusal": refused.refusal,
                "detail": refused.detail,
            })
        raise
    except Exception as error:
        if not report_attempted:
            report_attempted = True
            _emit({"kind": "document-save", "ok": False, "error": str(error), "traceback": traceback.format_exc()})
        raise
