"""Segmentation: run Fusion's own face grouping, on purpose, at the accurate method.

This is the segmentation stage of the reconstruction pipeline. It is a separate
transaction from extraction because it *mutates* the mesh body's grouping, and
``emit-mesh-extract`` promises to create and change nothing: extraction reads
whatever grouping the body already carries. Run this first, then extract.

**The method is set explicitly and never inherited.** The default is
``FastGenerateFaceGroupsType``, angle-threshold clustering, and on the 11-part
production STL set it silently produced a solid Fusion reported healthy whose
volume was 7.6% wrong. ``AccurateGenerateFaceGroupsType`` matches mesh faces to
analytic primitives and returned 1,908 groups across the same parts, every one
of which our exact fitters then accepted a fit for. A run that cannot set the
method, or that reads back a method other than the one it set, refuses --
inheriting the default here is the silent-wrong-answer class this package exists
to refuse. ``references/unsupported.md`` records the measurement.

The three numeric knobs -- ``angleThreshold``, ``minimumFaceGroupSize`` and
``boundaryTolerance`` -- are deliberately never touched: all three raise
``InternalValidationError`` on get and reject every value on set. The method enum
is the only knob that works, so it is the only knob this offers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .manifest import ManifestValidationError, ValidationIssue, _reject_unknown_fields
from .mesh_extract import INTERNAL_TO_MM
from .mesh_reconstruction import (
    _source_evidence,
    _validate_body_binding,
    require_classification,
)

if TYPE_CHECKING:
    from .manifest import Manifest


FACE_GROUP_SPEC_FIELDS = {"component_path", "body_name"}

#: The one method this package will run, and the reason it is not a spec field.
#: Fast is measurably wrong on real parts and Accurate is measurably right; a
#: caller-selectable method here would only offer a way to reproduce the defect.
FACE_GROUP_METHOD = "AccurateGenerateFaceGroupsType"


def validate_face_group_spec(spec: Any) -> list[ValidationIssue]:
    """Validate the face-group spec: which body. Nothing else is settable."""
    issues: list[ValidationIssue] = []
    if not isinstance(spec, dict):
        return [
            ValidationIssue(
                "face-group-spec-must-be-object",
                "face_group_spec",
                "A face-group spec must be an object.",
            )
        ]
    _reject_unknown_fields(issues, spec, FACE_GROUP_SPEC_FIELDS, "face_group_spec")
    _validate_body_binding(
        issues,
        {key: spec[key] for key in ("component_path", "body_name") if key in spec},
        "face_group_spec",
        "face-group-spec-invalid-binding",
    )
    return issues


def emit_mesh_face_groups_script(
    manifest: "Manifest",
    classification_record: Any,
    source_record: Any,
    spec: Any,
) -> str:
    """Emit the segmentation transaction: set the method, group, read the result back."""
    from .scripts import _json_literal, _script_prelude, manifest_sha256

    classification = require_classification(
        classification_record, "mesh-generate-face-groups", {"parametric-rebuild"}, source_record
    )
    issues = validate_face_group_spec(spec)
    if issues:
        raise ManifestValidationError(issues)

    specs = {
        "classification": classification.to_dict(),
        "mesh_source": _source_evidence(source_record),
        "component_path": spec["component_path"],
        "body_name": spec["body_name"],
        "method": FACE_GROUP_METHOD,
        "internal_to_mm": INTERNAL_TO_MM,
        "manifest_sha256": manifest_sha256(manifest),
    }

    transaction = '''FACE_GROUP_SPECS = json.loads(__FACE_GROUP_SPECS__)

METHOD_NOTE = (
    "The grouping method is set explicitly on the input and read back before the feature is added. "
    "The default, Fast, produced a solid Fusion reported healthy and 7.6% wrong on volume across the "
    "measured part set; inheriting it silently is the failure this transaction exists to prevent."
)


def _refuse(reason, detail, alternative):
    return {"reason": reason, "detail": detail, "alternative": alternative}


def _read(source, name, unavailable):
    try:
        value = getattr(source, name, None)
    except Exception:
        value = None
    if value is None:
        unavailable.append(name)
    return value


def _target_component(design, component_path):
    if not component_path:
        return design.rootComponent, None
    _, occurrence_map, duplicate_semantic_paths = _root_context_occurrence_map(design.rootComponent)
    if component_path in duplicate_semantic_paths:
        return None, "duplicate-semantic-path"
    occurrence = occurrence_map.get(component_path)
    if occurrence is None:
        return None, "component-path-missing"
    return occurrence.component, None


def _mesh_body(component, body_name):
    mesh_bodies = getattr(component, "meshBodies", None)
    if mesh_bodies is None:
        return None
    for index in range(mesh_bodies.count):
        body = mesh_bodies.item(index)
        if getattr(body, "name", None) == body_name:
            return body
    return None


def _missing_capabilities(component):
    """Every name this transaction needs, probed and named. Absent is never assumed away."""
    missing = []
    features = getattr(getattr(component, "features", None), "meshGenerateFaceGroupsFeatures", None)
    if features is None:
        missing.append("Features.meshGenerateFaceGroupsFeatures")
    elif not hasattr(features, "createInput") or not hasattr(features, "add"):
        missing.append("MeshGenerateFaceGroupsFeatures.createInput/add")
    methods = getattr(adsk.fusion, "MeshGenerateFaceGroupsMethodTypes", None)
    if methods is None or getattr(methods, FACE_GROUP_SPECS["method"], None) is None:
        missing.append("adsk.fusion.MeshGenerateFaceGroupsMethodTypes." + FACE_GROUP_SPECS["method"])
    return missing, features


def _point(value, scale):
    if value is None:
        return None
    try:
        return [float(value.x) * scale, float(value.y) * scale, float(value.z) * scale]
    except Exception:
        return None


def _box(value, scale):
    if value is None:
        return None
    low = _point(getattr(value, "minPoint", None), scale)
    high = _point(getattr(value, "maxPoint", None), scale)
    if low is None or high is None:
        return None
    return [low, high]


def _group_metadata(mesh_body, scale):
    """Per-group area, centroid, bounding box and planarity, in millimetres.

    Reported as evidence about the segmentation, not as input to it: the host
    re-derives every one of these from the triangles it was handed, so a value
    Fusion declines to report costs the report a null and costs the pipeline
    nothing. An unreadable collection is said so, never counted as zero groups.
    """
    groups = getattr(mesh_body, "faceGroups", None)
    if groups is None:
        return None, "MeshBody.faceGroups is absent on this Fusion"
    try:
        count = int(groups.count)
    except Exception as error:
        return None, "MeshBody.faceGroups.count unreadable: " + str(error)
    out = []
    for index in range(count):
        try:
            group = groups.item(index)
        except Exception as error:
            return None, "MeshBody.faceGroups.item(" + str(index) + ") raised: " + str(error)
        area = getattr(group, "area", None)
        out.append({
            "temp_id": getattr(group, "tempId", None),
            # Fusion works in centimetres, so an area scales by the square.
            "area_mm2": (float(area) * scale * scale) if area is not None else None,
            "centroid_mm": _point(getattr(group, "centroid", None), scale),
            "bounding_box_mm": _box(getattr(group, "boundingBox", None), scale),
            "is_planar": getattr(group, "isPlanar", None),
        })
    return out, None


def run(context):
    report_attempted = False
    try:
        app, design = _active_design()
        fusion_version = getattr(app, "version", None)
        target_document = _require_target_document(app)
        _pump_events(app, design, target_document)

        scale = FACE_GROUP_SPECS["internal_to_mm"]
        report = {
            "kind": "mesh-face-groups",
            "ok": False,
            "project": PROJECT_NAME,
            "manifest_sha256": MANIFEST_SHA256,
            "fusion_version": fusion_version,
            "classification": FACE_GROUP_SPECS["classification"],
            "mesh_source": FACE_GROUP_SPECS["mesh_source"],
            "component_path": FACE_GROUP_SPECS["component_path"],
            "body_name": FACE_GROUP_SPECS["body_name"],
            "requested_method": FACE_GROUP_SPECS["method"],
            "applied_method": None,
            "group_count": None,
            "refusals": [],
            "failures": [],
            "preview_apis": ["MeshGenerateFaceGroupsFeature", "MeshBody.mesh", "MeshBody.faceGroups"],
            "method_note": METHOD_NOTE,
        }

        def fail(reasons):
            report["failures"] = list(reasons)
            _emit(report)
            raise RuntimeError("Face-group generation refused: " + ", ".join(reasons))

        component, resolution_error = _target_component(design, FACE_GROUP_SPECS["component_path"])
        if component is None:
            report["refusals"].append(_refuse(
                "source-not-found",
                {"component_path": FACE_GROUP_SPECS["component_path"], "reason": resolution_error},
                "Re-read the capture report and bind the body by its reported component path and name.",
            ))
            report_attempted = True
            fail(["source-not-found"])

        missing, features = _missing_capabilities(component)
        if not fusion_version:
            missing.append("Application.version")
        if missing:
            report["missing_capabilities"] = missing
            report_attempted = True
            fail(["face-group-capability"])

        mesh_body = _mesh_body(component, FACE_GROUP_SPECS["body_name"])
        if mesh_body is None:
            report["refusals"].append(_refuse(
                "source-not-found",
                {"body_name": FACE_GROUP_SPECS["body_name"], "detail": "no mesh body of that name"},
                "Grouping reads a mesh body; a missing body is a binding error, not an empty mesh.",
            ))
            report_attempted = True
            fail(["source-not-found"])

        unavailable = []
        mesh = _read(mesh_body, "mesh", unavailable)
        triangle_count = None if mesh is None else _read(mesh, "triangleCount", unavailable)
        if triangle_count is None:
            report["refusals"].append(_refuse(
                "mesh-evidence-unavailable",
                {"unavailable": sorted(set(unavailable))},
                "A missing triangle count is not a count of zero, so nothing is grouped.",
            ))
            report_attempted = True
            fail(["mesh-evidence-unavailable"])
        report["triangle_count"] = int(triangle_count)

        method = getattr(
            adsk.fusion.MeshGenerateFaceGroupsMethodTypes, FACE_GROUP_SPECS["method"]
        )
        try:
            # createInput takes the MeshBody itself, not an ObjectCollection --
            # a collection raises "InternalValidationError : meshBody", measured
            # against a live Fusion rather than assumed from the sibling APIs.
            group_input = features.createInput(mesh_body)
        except Exception as error:
            report["error"] = str(error)
            report_attempted = True
            fail(["face-group-input-failed"])

        # Set, then read back. The three numeric knobs on this input raise
        # InternalValidationError on get and reject every value on set; the method
        # enum does not, and a release where it silently does not stick must be a
        # refusal rather than an unannounced Fast run.
        try:
            group_input.meshGenerateFaceGroupsMethodType = method
            applied = group_input.meshGenerateFaceGroupsMethodType
        except Exception as error:
            report["error"] = str(error)
            report_attempted = True
            fail(["face-group-method-unsettable"])
        report["applied_method"] = (
            FACE_GROUP_SPECS["method"] if applied == method else str(applied)
        )
        if applied != method:
            report["refusals"].append(_refuse(
                "face-group-method-not-applied",
                {"requested": FACE_GROUP_SPECS["method"], "read_back": str(applied)},
                "The input did not keep the method it was given, so this run would have grouped by "
                "whatever method it kept. Nothing is grouped rather than grouping by an unknown one.",
            ))
            report_attempted = True
            fail(["face-group-method-not-applied"])

        try:
            # Documented, and confirmed in a direct-modeling design: add() returns
            # None for a non-parametric operation while still applying it. The
            # return value is never read, and never checked for truthiness.
            features.add(group_input)
        except Exception as error:
            report["error"] = str(error)
            report_attempted = True
            fail(["face-group-generation-failed"])

        _pump_events(app, design, target_document)

        mesh = _read(mesh_body, "mesh", unavailable)
        ids = None if mesh is None else _read(mesh, "triangleFaceGroupTempIds", unavailable)
        if ids is None:
            report["refusals"].append(_refuse(
                "face-groups-unreadable",
                {"unavailable": sorted(set(unavailable))},
                "The feature applied but the per-triangle grouping did not read back, so this run "
                "cannot state what it produced.",
            ))
            report_attempted = True
            fail(["face-groups-unreadable"])
        try:
            values = [int(value) for value in ids]
        except Exception as error:
            report["error"] = str(error)
            report_attempted = True
            fail(["face-groups-unreadable"])
        if len(values) != int(triangle_count):
            report["refusals"].append(_refuse(
                "face-groups-partial",
                {"id_count": len(values), "triangle_count": int(triangle_count)},
                "A grouping that does not cover every triangle is not a grouping; neither padded nor "
                "truncated.",
            ))
            report_attempted = True
            fail(["face-groups-partial"])

        histogram = {}
        for value in values:
            key = str(value)
            histogram[key] = histogram.get(key, 0) + 1
        report["group_count"] = len(histogram)
        report["triangles_per_group"] = histogram
        if len(histogram) < 2:
            report["refusals"].append(_refuse(
                "face-groups-degenerate",
                {"group_count": len(histogram)},
                "One group over the whole body is not a segmentation. Nothing downstream may treat it "
                "as one.",
            ))
            report_attempted = True
            fail(["face-groups-degenerate"])

        metadata, metadata_error = _group_metadata(mesh_body, scale)
        report["face_groups"] = metadata
        report["face_groups_unavailable_reason"] = metadata_error

        try:
            source_present = getattr(mesh_body, "isValid", None)
        except Exception:
            source_present = None
        # Unreadable is not proof the source survived; only True is.
        report["source_mesh_body_present"] = source_present
        if source_present is not True:
            report_attempted = True
            fail(["source-mesh-consumed"])

        report["ok"] = True
        report["failures"] = []
        report["next_step"] = (
            "Run emit-mesh-extract against this same body. Extraction reads the grouping this "
            "transaction just applied and writes it into the dump, one id per triangle."
        )
        report_attempted = True
        _emit(report)
    except Exception as error:
        if not report_attempted:
            report_attempted = True
            _emit({
                "kind": "mesh-face-groups",
                "ok": False,
                "project": PROJECT_NAME,
                "manifest_sha256": MANIFEST_SHA256,
                "applied_method": None,
                "group_count": None,
                "error": str(error),
                "traceback": traceback.format_exc(),
            })
        raise
'''
    return _script_prelude(manifest) + transaction.replace(
        "__FACE_GROUP_SPECS__", _json_literal(specs)
    )
