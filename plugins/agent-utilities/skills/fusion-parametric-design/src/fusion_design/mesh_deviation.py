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


DEVIATION_SPEC_FIELDS = {"source", "reconstruction", "thresholds_mm", "rationale"}

DEVIATION_THRESHOLD_FIELDS = {"invented_material", "omitted_detail", "percentile_sample_limit"}


def validate_deviation_spec(spec: Any) -> list[ValidationIssue]:
    """Validate the deviation spec: the two bodies, and the declared thresholds."""
    issues: list[ValidationIssue] = []
    if not isinstance(spec, dict):
        return [
            ValidationIssue(
                "deviation-spec-must-be-object",
                "deviation_spec",
                "A deviation spec must be an object.",
            )
        ]
    _reject_unknown_fields(issues, spec, DEVIATION_SPEC_FIELDS, "deviation_spec")
    _validate_body_binding(
        issues, spec.get("source"), "deviation_spec.source", "deviation-spec-invalid-binding"
    )
    _validate_body_binding(
        issues,
        spec.get("reconstruction"),
        "deviation_spec.reconstruction",
        "deviation-spec-invalid-binding",
    )
    thresholds = spec.get("thresholds_mm")
    if not isinstance(thresholds, dict):
        issues.append(
            ValidationIssue(
                "deviation-spec-invalid-thresholds",
                "deviation_spec.thresholds_mm",
                "thresholds_mm must be declared per reconstruction and recorded with the verdict.",
            )
        )
    else:
        _reject_unknown_fields(
            issues, thresholds, DEVIATION_THRESHOLD_FIELDS, "deviation_spec.thresholds_mm"
        )
        for field in ("invented_material", "omitted_detail"):
            _require_positive_number(
                issues,
                thresholds.get(field),
                f"deviation_spec.thresholds_mm.{field}",
                "deviation-spec-invalid-thresholds",
                f"thresholds_mm.{field} must be a positive number of millimetres declared for this "
                "reconstruction; it is never a module constant.",
            )
        limit = thresholds.get("percentile_sample_limit")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            issues.append(
                ValidationIssue(
                    "deviation-spec-invalid-thresholds",
                    "deviation_spec.thresholds_mm.percentile_sample_limit",
                    "percentile_sample_limit must be a positive integer; it bounds only the percentile "
                    "sample, never the exact comparison against a threshold.",
                )
            )
    rationale = spec.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        issues.append(
            ValidationIssue(
                "deviation-spec-invalid-rationale",
                "deviation_spec.rationale",
                "Record why these thresholds are the right ones for this reconstruction.",
            )
        )
    return issues


def emit_mesh_deviation_script(
    manifest: "Manifest",
    classification_record: Any,
    source_record: Any,
    spec: Any,
) -> str:
    """Emit the deviation transaction and its asymmetric, two-directional verdict.

    The two directions answer different questions and are never collapsed into
    one number.  ``PolygonMesh.compareWith`` is preview and API-only; its absence
    is a fail-closed unsupported result naming the API and the Fusion version.
    """
    from .scripts import _json_literal, _script_prelude

    classification = require_classification(
        classification_record,
        "mesh-deviation-verdict",
        {"faceted-brep", "parametric-rebuild"},
        source_record,
    )
    issues = validate_deviation_spec(spec)
    if issues:
        raise ManifestValidationError(issues)

    specs = {
        "classification": classification.to_dict(),
        "mesh_source": _source_evidence(source_record),
        "source": dict(spec["source"]),
        "reconstruction": dict(spec["reconstruction"]),
        "thresholds_mm": dict(spec["thresholds_mm"]),
        "rationale": str(spec["rationale"]).strip(),
    }

    transaction = '''DEVIATION_SPECS = json.loads(__DEVIATION_SPECS__)

RECONSTRUCTION_TO_SOURCE_QUESTION = (
    "How far does the reconstructed surface sit from the nearest scanned surface? This answers whether "
    "the rebuild stayed on the scan. It says nothing about scanned detail the rebuild never modelled."
)
SOURCE_TO_RECONSTRUCTION_QUESTION = (
    "How far does each scanned point sit from the reconstruction, and is it inside the reconstructed "
    "solid? This answers whether the rebuild captured what was scanned. It says nothing about material "
    "the rebuild added where the scan has no points."
)
VERDICT_NOTE = (
    "These two numbers answer different questions and neither certifies the other. A small maximum "
    "deviation from the reconstruction to the scan does not establish that the reconstruction captured "
    "every scanned feature."
)


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


def _named_body(component, body_name):
    for attribute in ("meshBodies", "bRepBodies"):
        bodies = getattr(component, attribute, None)
        if bodies is None:
            continue
        for index in range(bodies.count):
            body = bodies.item(index)
            if getattr(body, "name", None) == body_name:
                return body, attribute
    return None, None


def _polygon_mesh(body, kind, missing):
    """The PolygonMesh for a body, or None with the missing API named."""
    mesh = getattr(body, "mesh", None)
    if mesh is not None:
        return mesh
    manager = getattr(body, "meshManager", None)
    display = getattr(manager, "displayMeshes", None) if manager is not None else None
    best = getattr(display, "bestMesh", None) if display is not None else None
    if best is None:
        missing.append(kind + ": MeshBody.mesh or BRepBody.meshManager.displayMeshes.bestMesh")
        return None
    return best


def _percentiles(values, limit):
    """Percentiles may be sampled; a threshold comparison never is."""
    if not values:
        return {}, False, 1
    stride = 1
    if len(values) > limit:
        stride = (len(values) // limit) + 1
    sample = sorted(values[::stride])
    sampled = stride > 1
    result = {}
    for name, fraction in (("p50", 0.5), ("p95", 0.95), ("p99", 0.99), ("max_of_sample", 1.0)):
        index = int(round(fraction * (len(sample) - 1)))
        result[name] = sample[index]
    return result, sampled, stride


def _node_points_mm(mesh):
    coordinates = getattr(mesh, "nodeCoordinates", None)
    if not coordinates:
        return []
    return [[point.x * 10.0, point.y * 10.0, point.z * 10.0] for point in coordinates]


def _worst(points, distances, threshold, count):
    ranked = sorted(range(len(distances)), key=lambda index: -distances[index])
    worst = []
    for index in ranked[:count]:
        if distances[index] <= threshold:
            break
        entry = {"distance_mm": distances[index]}
        if index < len(points):
            entry["point_mm"] = points[index]
        worst.append(entry)
    return worst


def run(context):
    report_attempted = False
    try:
        app, design = _active_design()
        fusion_version = getattr(app, "version", None)
        target_document = _require_target_document(app)
        _pump_events(app, design, target_document)

        thresholds = DEVIATION_SPECS["thresholds_mm"]
        report = {
            "kind": "mesh-deviation",
            "ok": False,
            "project": PROJECT_NAME,
            "manifest_sha256": MANIFEST_SHA256,
            "fusion_version": fusion_version,
            "classification": DEVIATION_SPECS["classification"],
            "mesh_source": DEVIATION_SPECS["mesh_source"],
            "declared_thresholds_mm": thresholds,
            "threshold_rationale": DEVIATION_SPECS["rationale"],
            "preview_apis": ["PolygonMesh.compareWith"],
            "failures": [],
            "verdict_note": VERDICT_NOTE,
        }

        source_component, source_error = _target_component(design, DEVIATION_SPECS["source"]["component_path"])
        recon_component, recon_error = _target_component(
            design, DEVIATION_SPECS["reconstruction"]["component_path"]
        )
        if source_component is None or recon_component is None:
            report["failures"] = ["body-not-found"]
            report["resolution_errors"] = {"source": source_error, "reconstruction": recon_error}
            report_attempted = True
            _emit(report)
            raise RuntimeError("Deviation verdict failed closed: body-not-found")

        source_body, _ = _named_body(source_component, DEVIATION_SPECS["source"]["body_name"])
        recon_body, recon_kind = _named_body(
            recon_component, DEVIATION_SPECS["reconstruction"]["body_name"]
        )
        if source_body is None or recon_body is None:
            report["failures"] = ["body-not-found"]
            report["resolution_errors"] = {
                "source": None if source_body is not None else "body-name-missing",
                "reconstruction": None if recon_body is not None else "body-name-missing",
            }
            report_attempted = True
            _emit(report)
            raise RuntimeError("Deviation verdict failed closed: body-not-found")

        missing = []
        source_mesh = _polygon_mesh(source_body, "source", missing)
        recon_mesh = _polygon_mesh(recon_body, "reconstruction", missing)
        if source_mesh is None or recon_mesh is None or not hasattr(source_mesh, "compareWith"):
            if source_mesh is not None and not hasattr(source_mesh, "compareWith"):
                missing.append("PolygonMesh.compareWith")
            report["failures"] = ["deviation-capability"]
            report["missing_capabilities"] = missing
            report["unsupported"] = (
                "PolygonMesh.compareWith is the only API-level deviation mechanism in Fusion; Mesh "
                "Section Sketch and Fit Curves are UI-only and cannot be scripted. compareWith is a "
                "preview API (July 2026) and is absent from Fusion version "
                + str(fusion_version)
                + " as connected, so no deviation number is available and none is invented."
            )
            report_attempted = True
            _emit(report)
            raise RuntimeError(
                "Deviation verdict unsupported on this Fusion: missing " + ", ".join(missing)
            )

        try:
            recon_to_source = [value * 10.0 for value in recon_mesh.compareWith(source_mesh, None, None)]
            source_to_recon = [value * 10.0 for value in source_mesh.compareWith(recon_mesh, None, None)]
        except Exception as error:
            report["failures"] = ["deviation-comparison-failed"]
            report["error"] = str(error)
            report["unsupported"] = (
                "compareWith is preview and rejected these two meshes; no deviation number is available."
            )
            report_attempted = True
            _emit(report)
            raise

        if not recon_to_source or not source_to_recon:
            report["failures"] = ["deviation-comparison-empty"]
            report_attempted = True
            _emit(report)
            raise RuntimeError("Deviation verdict failed closed: deviation-comparison-empty")

        signed = any(value < 0.0 for value in recon_to_source)
        recon_points = _node_points_mm(recon_mesh)
        source_points = _node_points_mm(source_mesh)
        invented_threshold = float(thresholds["invented_material"])
        omitted_threshold = float(thresholds["omitted_detail"])

        # Direction 1: reconstruction to source. Exact per-node values decide the
        # threshold comparison; only the percentiles may be sampled.
        outside = [value for value in recon_to_source if value > 0.0] if signed else []
        percentiles_1, sampled_1, stride_1 = _percentiles(
            [abs(value) for value in recon_to_source], int(thresholds["percentile_sample_limit"])
        )
        report["reconstruction_to_source"] = {
            "question": RECONSTRUCTION_TO_SOURCE_QUESTION,
            "node_count": len(recon_to_source),
            "max_abs_mm": max(abs(value) for value in recon_to_source),
            "signed": signed,
            "percentiles_mm": percentiles_1,
            "percentiles_sampled": sampled_1,
            "percentile_stride": stride_1,
        }

        # Direction 2: source to reconstruction, with containment answered by the
        # native B-Rep query when the reconstruction is a solid.
        containment = None
        outside_solid = None
        point_containment = getattr(recon_body, "pointContainment", None)
        if recon_kind == "bRepBodies" and point_containment is not None and source_points:
            outside_enum = getattr(
                getattr(adsk.fusion, "PointContainment", None), "PointOutsidePointContainment", None
            )
            try:
                nodes = getattr(source_mesh, "nodeCoordinates", None) or []
                outside_solid = sum(
                    1 for node in nodes if point_containment(node) == outside_enum
                )
                containment = "BRepBody.pointContainment"
            except Exception:
                outside_solid = None
                containment = None
        percentiles_2, sampled_2, stride_2 = _percentiles(
            [abs(value) for value in source_to_recon], int(thresholds["percentile_sample_limit"])
        )
        omitted_points = _worst(
            source_points, [abs(value) for value in source_to_recon], omitted_threshold, 5
        )
        report["source_to_reconstruction"] = {
            "question": SOURCE_TO_RECONSTRUCTION_QUESTION,
            "node_count": len(source_to_recon),
            "max_abs_mm": max(abs(value) for value in source_to_recon),
            "beyond_omitted_threshold": sum(
                1 for value in source_to_recon if abs(value) > omitted_threshold
            ),
            "percentiles_mm": percentiles_2,
            "percentiles_sampled": sampled_2,
            "percentile_stride": stride_2,
            "containment_query": containment,
            "nodes_outside_reconstruction_solid": outside_solid,
        }

        omitted = {
            "severity": "advisory",
            "threshold_mm": omitted_threshold,
            "count": report["source_to_reconstruction"]["beyond_omitted_threshold"],
            "worst_points": omitted_points,
            "meaning": "Scanned detail the rebuild did not model. Advisory: a rebuild models only the "
                       "geometry the edit requires.",
        }

        if not signed:
            # Unsigned magnitudes cannot separate invented material from omitted
            # detail, and guessing which is which is exactly the dishonest answer.
            report["failures"] = ["deviation-unsigned-comparison"]
            report["verdict"] = {
                "invented_material": {
                    "severity": "not-established",
                    "threshold_mm": invented_threshold,
                    "meaning": "The connected Fusion returned only unsigned distances, so material "
                               "outside the source cannot be distinguished from detail inside it. The "
                               "absence of invented material is NOT established by this run.",
                },
                "omitted_detail": omitted,
            }
            report_attempted = True
            _emit(report)
            raise RuntimeError("Deviation verdict failed closed: deviation-unsigned-comparison")

        beyond = [value for value in outside if value > invented_threshold]
        invented_points = _worst(recon_points, recon_to_source, invented_threshold, 5)
        report["verdict"] = {
            "invented_material": {
                "severity": "failure" if beyond else "pass",
                "threshold_mm": invented_threshold,
                "count": len(beyond),
                "max_mm": max(beyond) if beyond else 0.0,
                "worst_points": invented_points,
                "sign_convention": "PolygonMesh.compareWith returns a signed distance; a positive value "
                                   "is read as lying outside the compared body. Confirm that convention "
                                   "once on this Fusion version before trusting a pass.",
                "meaning": "Rebuilt material outside the source solid is invented geometry, and that is "
                           "categorically worse than omitted detail.",
            },
            "omitted_detail": omitted,
        }
        if beyond:
            report["failures"] = ["invented-material"]
            report_attempted = True
            _emit(report)
            raise RuntimeError(
                "Deviation verdict failed: invented material at "
                + json.dumps(invented_points[:1])
            )

        report["ok"] = True
        report_attempted = True
        _emit(report)
    except Exception as error:
        if not report_attempted:
            report_attempted = True
            _emit({
                "kind": "mesh-deviation",
                "ok": False,
                "project": PROJECT_NAME,
                "manifest_sha256": MANIFEST_SHA256,
                "error": str(error),
                "traceback": traceback.format_exc(),
            })
        raise
'''
    return _script_prelude(manifest) + transaction.replace(
        "__DEVIATION_SPECS__", _json_literal(specs)
    )
