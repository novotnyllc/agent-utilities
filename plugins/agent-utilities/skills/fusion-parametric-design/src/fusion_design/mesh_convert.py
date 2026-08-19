from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .manifest import ManifestValidationError, ValidationIssue, _reject_unknown_fields
from .mesh_reconstruction import (
    _require_positive_number,
    _source_evidence,
    _validate_body_binding,
    require_classification,
)

if TYPE_CHECKING:
    from .manifest import Manifest


CONVERT_SPEC_FIELDS = {"component_path", "body_name", "max_faces_per_face_group", "rationale"}


def validate_convert_spec(spec: Any) -> list[ValidationIssue]:
    """Validate the faceted-conversion spec: which body, and the editability ceiling."""
    issues: list[ValidationIssue] = []
    if not isinstance(spec, dict):
        return [
            ValidationIssue(
                "convert-spec-must-be-object",
                "convert_spec",
                "A faceted-conversion spec must be an object.",
            )
        ]
    _reject_unknown_fields(issues, spec, CONVERT_SPEC_FIELDS, "convert_spec")
    _validate_body_binding(
        issues,
        {key: spec[key] for key in ("component_path", "body_name") if key in spec},
        "convert_spec",
        "convert-spec-invalid-binding",
    )
    _require_positive_number(
        issues,
        spec.get("max_faces_per_face_group"),
        "convert_spec.max_faces_per_face_group",
        "convert-spec-invalid-editability",
        "max_faces_per_face_group must be a positive number declared for this conversion; "
        "the editability ceiling is never a module constant.",
    )
    rationale = spec.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        issues.append(
            ValidationIssue(
                "convert-spec-invalid-rationale",
                "convert_spec.rationale",
                "Record why this editability ceiling is the right one for this part; a ceiling nobody "
                "justified can be set high enough that the rung never fires.",
            )
        )
    return issues


def emit_mesh_convert_script(
    manifest: "Manifest",
    classification_record: Any,
    source_record: Any,
    spec: Any,
) -> str:
    """Emit the faceted-conversion transaction: an ordered refusal ladder, then a faceted label.

    The gate runs host-side and refuses anything but ``faceted-brep``; the
    transaction runs the rungs that only live Fusion can answer, and labels what
    it produced ``faceted`` — never parametric.
    """
    from .scripts import _json_literal, _script_prelude

    classification = require_classification(
        classification_record, "mesh-convert-to-brep", {"faceted-brep"}, source_record
    )
    issues = validate_convert_spec(spec)
    if issues:
        raise ManifestValidationError(issues)

    specs = {
        "classification": classification.to_dict(),
        "mesh_source": _source_evidence(source_record),
        "component_path": spec["component_path"],
        "body_name": spec["body_name"],
        "max_faces_per_face_group": float(spec["max_faces_per_face_group"]),
        "editability_rationale": str(spec["rationale"]).strip(),
    }

    transaction = '''CONVERT_SPECS = json.loads(__CONVERT_SPECS__)

FACETED_NOTE = (
    "This body is faceted, never parametric: it carries no sketches, constraints, dimensions, or "
    "feature history, and a converted cylinder has no circular edge to select."
)
HANDOFF_NOTE = (
    "Nothing downstream reads this label: the manifest has no field marking a print part faceted, and "
    "emit-export never reads this report. Carry the label into DESIGN-STATE.md and the handoff by hand, "
    "or the exported body arrives labelled as nothing."
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


def _face_group_count(mesh, unavailable):
    ids = _read(mesh, "triangleFaceGroupTempIds", unavailable)
    if ids is None:
        return None
    try:
        return len({int(value) for value in ids})
    except Exception:
        unavailable.append("triangleFaceGroupTempIds.values")
        return None


def _brep_body_names(component):
    bodies = getattr(component, "bRepBodies", None)
    if bodies is None:
        return None
    return [bodies.item(index) for index in range(bodies.count)]


def _missing_convert_capabilities(component):
    missing = []
    features = getattr(getattr(component, "features", None), "meshConvertFeatures", None)
    if features is None:
        missing.append("Features.meshConvertFeatures")
    elif not hasattr(features, "createInput") or not hasattr(features, "add"):
        missing.append("MeshConvertFeatures.createInput/add")
    if getattr(adsk.core, "ObjectCollection", None) is None:
        missing.append("adsk.core.ObjectCollection")
    if getattr(getattr(adsk.fusion, "MeshConvertMethodTypes", None), "FacetedMeshConvertMethodType", None) is None:
        missing.append("adsk.fusion.MeshConvertMethodTypes.FacetedMeshConvertMethodType")
    # Without this enum the health rung has nothing to compare against. An absent
    # enum must fail closed here, never quietly disable the rung that catches an
    # unhealthy conversion being reported as a successful faceted body.
    if getattr(getattr(adsk.fusion, "FeatureHealthStates", None), "HealthyFeatureHealthState", None) is None:
        missing.append("adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState")
    return missing, features


def _remove(entities):
    errors = []
    for entity in reversed(entities):
        try:
            entity.deleteMe()
        except Exception as error:
            errors.append(str(error))
    return errors


def run(context):
    report_attempted = False
    try:
        app, design = _active_design()
        fusion_version = getattr(app, "version", None)
        target_document = _require_target_document(app)
        _pump_events(app, design, target_document)

        report = {
            "kind": "mesh-convert",
            "ok": False,
            "project": PROJECT_NAME,
            "manifest_sha256": MANIFEST_SHA256,
            "fusion_version": fusion_version,
            "classification": CONVERT_SPECS["classification"],
            "mesh_source": CONVERT_SPECS["mesh_source"],
            "component_path": CONVERT_SPECS["component_path"],
            "body_name": CONVERT_SPECS["body_name"],
            "label": None,
            "parametric": False,
            "refusals": [],
            "failures": [],
            "preview_apis": ["MeshConvertFeature", "MeshBody.mesh"],
            "note": FACETED_NOTE,
            "handoff_note": HANDOFF_NOTE,
            "editability_rationale": CONVERT_SPECS["editability_rationale"],
        }

        component, resolution_error = _target_component(design, CONVERT_SPECS["component_path"])
        if component is None:
            report["refusals"].append(_refuse(
                "source-not-found",
                {"component_path": CONVERT_SPECS["component_path"], "reason": resolution_error},
                "Re-read the capture report and bind the body by its reported component path and name.",
            ))
            report["failures"] = ["source-not-found"]
            report_attempted = True
            _emit(report)
            raise RuntimeError("Faceted conversion refused: source-not-found")

        missing_capabilities, features = _missing_convert_capabilities(component)
        if not fusion_version:
            missing_capabilities.append("Application.version")
        if missing_capabilities:
            report["failures"] = ["mesh-convert-capability"]
            report["missing_capabilities"] = missing_capabilities
            report_attempted = True
            _emit(report)
            raise RuntimeError(
                "The live Fusion mesh-convert capability is unavailable; missing "
                + ", ".join(missing_capabilities)
                + ". Every mesh feature class is preview; a missing name is an adapter/API mismatch, "
                "not proof Fusion cannot convert."
            )

        unavailable = []
        mesh_body = _mesh_body(component, CONVERT_SPECS["body_name"])
        refusals = report["refusals"]
        if mesh_body is None:
            refusals.append(_refuse(
                "not-convertible-source",
                {"body_name": CONVERT_SPECS["body_name"], "detail": "no mesh body of that name"},
                "Convert a mesh body; a B-Rep body is already converted and a missing body is a binding error.",
            ))
        else:
            mesh = _read(mesh_body, "mesh", unavailable)
            is_closed = _read(mesh_body, "isClosed", unavailable)
            volume = _read(mesh_body, "volume", unavailable)
            if mesh is None or is_closed is None or volume is None:
                refusals.append(_refuse(
                    "mesh-evidence-unavailable",
                    {"unavailable": sorted(set(unavailable))},
                    "These preview properties carry the ladder's own inputs; without them the refusal "
                    "ladder cannot run, so nothing is converted.",
                ))
            else:
                if not is_closed:
                    refusals.append(_refuse(
                        "not-watertight",
                        {"is_closed": False},
                        "Conversion yields a surface body, not a solid. Repair the mesh, or take the "
                        "parametric-rebuild path.",
                    ))
                if float(volume) <= 0.0:
                    refusals.append(_refuse(
                        "non-positive-volume",
                        {"volume_mm3": float(volume) * 1000.0},
                        "The signed volume is not positive, so the normals are inverted. Fix the normals "
                        "before converting.",
                    ))

        if refusals:
            report["failures"] = sorted({refusal["reason"] for refusal in refusals})
            report["bodies_created"] = 0
            report_attempted = True
            _emit(report)
            raise RuntimeError("Faceted conversion refused: " + ", ".join(report["failures"]))

        face_group_count = _face_group_count(mesh, unavailable)
        if face_group_count is None or face_group_count < 1:
            report["refusals"].append(_refuse(
                "face-groups-unavailable",
                {"unavailable": sorted(set(unavailable))},
                "Fusion's own face grouping is what the editability check measures against; without it "
                "a successful conversion cannot be told from an unusable one.",
            ))
            report["failures"] = ["face-groups-unavailable"]
            report["bodies_created"] = 0
            report_attempted = True
            _emit(report)
            raise RuntimeError("Faceted conversion refused: face-groups-unavailable")

        before = {id(body) for body in (_brep_body_names(component) or [])}
        created = []
        try:
            collection = adsk.core.ObjectCollection.create()
            collection.add(mesh_body)
            convert_input = features.createInput(
                collection, adsk.fusion.MeshConvertMethodTypes.FacetedMeshConvertMethodType
            )
            # Documented: add() returns null for a non-parametric operation even
            # though the operation succeeded, so the feature object is optional.
            feature = features.add(convert_input)
        except Exception as error:
            report["failures"] = ["mesh-convert-failed"]
            report["error"] = str(error)
            report["bodies_created"] = 0
            report_attempted = True
            _emit(report)
            raise

        after = _brep_body_names(component) or []
        created = [body for body in after if id(body) not in before]

        complaint = None
        health = None
        if feature is not None:
            complaint = getattr(feature, "errorOrWarningMessage", None)
            health = getattr(feature, "healthState", None)
        healthy = adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState

        refusals = report["refusals"]
        if complaint:
            refusals.append(_refuse(
                "fusion-refused-conversion",
                {"errorOrWarningMessage": str(complaint), "healthState": str(health)},
                "This is Fusion's own complaint about this mesh on this version, quoted verbatim; no "
                "facet ceiling is hardcoded here. Take the parametric-rebuild path.",
            ))
        elif health is not None and health != healthy:
            refusals.append(_refuse(
                "fusion-refused-conversion",
                {"errorOrWarningMessage": None, "healthState": str(health)},
                "Fusion reports the convert feature unhealthy. Take the parametric-rebuild path.",
            ))
        elif not created:
            refusals.append(_refuse(
                "conversion-produced-nothing",
                {"feature_object_returned": feature is not None},
                "No B-Rep body appeared. add() returning null is documented for non-parametric "
                "operations, but a missing body is a real failure.",
            ))

        editability = None
        if not refusals:
            body = created[0]
            face_count = None
            try:
                face_count = int(body.faces.count)
            except Exception:
                face_count = None
            if face_count is None:
                refusals.append(_refuse(
                    "not-editable",
                    {"faces": None, "face_groups": face_group_count},
                    "The result exposes no face count, so there is nothing to prove it is selectable.",
                ))
            else:
                ratio = float(face_count) / float(face_group_count)
                editability = {
                    "faces": face_count,
                    "face_groups": face_group_count,
                    "faces_per_face_group": ratio,
                    "declared_max_faces_per_face_group": CONVERT_SPECS["max_faces_per_face_group"],
                }
                if ratio > CONVERT_SPECS["max_faces_per_face_group"]:
                    refusals.append(_refuse(
                        "not-editable",
                        editability,
                        "Converted successfully into faces nobody can select is a poor outcome, not a "
                        "success. Take the parametric-rebuild path.",
                    ))

        if refusals:
            cleanup_errors = _remove(created if feature is None else [feature])
            # Re-enumerate rather than infer emptiness from the absence of an
            # exception: deleting the feature does not always take its bodies.
            survivors = [
                body for body in (_brep_body_names(component) or []) if id(body) not in before
            ]
            report["failures"] = sorted({refusal["reason"] for refusal in refusals})
            if cleanup_errors or survivors:
                report["failures"].append("cleanup-incomplete")
            if cleanup_errors:
                report["cleanup_errors"] = cleanup_errors
            if survivors:
                report["surviving_bodies"] = [getattr(body, "name", None) for body in survivors]
            report["bodies_created"] = len(survivors)
            if editability is not None:
                report["editability"] = editability
            report_attempted = True
            _emit(report)
            raise RuntimeError("Faceted conversion refused: " + ", ".join(report["failures"]))

        try:
            source_present = getattr(mesh_body, "isValid", None)
        except Exception:
            source_present = None
        # Unreadable is not proof the source survived; only True is.
        if source_present is not True:
            report["failures"] = ["source-mesh-consumed"]
            report["source_mesh_body_present"] = source_present
            report["bodies_created"] = len(created)
            report_attempted = True
            _emit(report)
            raise RuntimeError(
                "Faceted conversion consumed the source mesh body; the immutable source must survive "
                "every operation."
            )

        report["ok"] = True
        report["label"] = "faceted"
        report["failures"] = []
        report["bodies_created"] = len(created)
        report["feature_object_returned"] = feature is not None
        report["editability"] = editability
        report["result_body_name"] = getattr(created[0], "name", None)
        report["source_mesh_body_present"] = True
        report_attempted = True
        _emit(report)
    except Exception as error:
        if not report_attempted:
            report_attempted = True
            _emit({
                "kind": "mesh-convert",
                "ok": False,
                "project": PROJECT_NAME,
                "manifest_sha256": MANIFEST_SHA256,
                "label": None,
                "parametric": False,
                "error": str(error),
                "traceback": traceback.format_exc(),
            })
        raise
'''
    return _script_prelude(manifest) + transaction.replace(
        "__CONVERT_SPECS__", _json_literal(specs)
    )
