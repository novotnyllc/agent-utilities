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
INVENTED_MEANING = (
    "Rebuilt material outside the source solid is invented geometry, and that is categorically worse "
    "than omitted detail."
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


def _probe_sign_convention(containment_values, distances, floor, outside_enum, inside_enum):
    """Read compareWith's sign convention off the native containment query.

    Nothing documents which sign means outside, and assuming it is how an
    inverted convention turns invented material into a pass.  Every source node
    whose distance clears the floor has an independent inside/outside answer
    from ``BRepBody.pointContainment``, so the convention is measured, not
    guessed.  Disagreement -- which is also what unsigned magnitudes look like
    -- yields ``None`` and no verdict.
    """
    tally = {"outside_positive": 0, "outside_negative": 0, "inside_positive": 0, "inside_negative": 0}
    for index, containment in enumerate(containment_values):
        if index >= len(distances):
            break
        distance = distances[index]
        if abs(distance) <= floor:
            continue
        if containment == outside_enum:
            side = "outside"
        elif containment == inside_enum:
            side = "inside"
        else:
            continue
        tally[side + ("_positive" if distance > 0.0 else "_negative")] += 1
    positive_outside = tally["outside_positive"] + tally["inside_negative"]
    negative_outside = tally["outside_negative"] + tally["inside_positive"]
    tally["samples"] = positive_outside + negative_outside
    tally["floor_mm"] = floor
    if positive_outside and not negative_outside:
        return "positive-is-outside", tally
    if negative_outside and not positive_outside:
        return "negative-is-outside", tally
    return None, tally


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
        for label, mesh in (("source", source_mesh), ("reconstruction", recon_mesh)):
            if mesh is not None and not hasattr(mesh, "compareWith"):
                missing.append("PolygonMesh.compareWith (" + label + ")")
        # Containment is the only evidence here that does not rest on compareWith's
        # sign, and it is what establishes that sign. It is a hard capability, never
        # a conditional: a missing enum must not read as "nothing was outside".
        if recon_kind != "bRepBodies":
            missing.append("reconstruction must be a BRepBody for BRepBody.pointContainment")
        elif getattr(recon_body, "pointContainment", None) is None:
            missing.append("BRepBody.pointContainment")
        if not (getattr(source_mesh, "nodeCoordinates", None) or []):
            missing.append("PolygonMesh.nodeCoordinates (source)")
        if not fusion_version:
            missing.append("Application.version")
        containment_enum = getattr(adsk.fusion, "PointContainment", None)
        for name in ("PointOutsidePointContainment", "PointInsidePointContainment"):
            if getattr(containment_enum, name, None) is None:
                missing.append("adsk.fusion.PointContainment." + name)
        if missing:
            report["failures"] = ["deviation-capability"]
            report["missing_capabilities"] = missing
            report["unsupported"] = (
                "PolygonMesh.compareWith is the only API-level deviation mechanism in Fusion; Mesh "
                "Section Sketch and Fit Curves are UI-only and cannot be scripted. compareWith is a "
                "preview API (July 2026), and BRepBody.pointContainment is what establishes its sign "
                "convention. Fusion version "
                + str(fusion_version)
                + " as connected does not expose all of them, so no deviation verdict is available "
                "and none is invented."
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

        signed = any(value < 0.0 for value in recon_to_source) or any(
            value < 0.0 for value in source_to_recon
        )
        recon_points = _node_points_mm(recon_mesh)
        source_points = _node_points_mm(source_mesh)
        invented_threshold = float(thresholds["invented_material"])
        omitted_threshold = float(thresholds["omitted_detail"])

        # Direction 1: reconstruction to source. Exact per-node values decide the
        # threshold comparison; only the percentiles may be sampled.
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
        # native B-Rep query. The capability check above guarantees it is present,
        # so a failure here is a failure, never a zero.
        outside_enum = adsk.fusion.PointContainment.PointOutsidePointContainment
        inside_enum = adsk.fusion.PointContainment.PointInsidePointContainment
        try:
            containment_values = [
                recon_body.pointContainment(node)
                for node in (getattr(source_mesh, "nodeCoordinates", None) or [])
            ]
        except Exception as error:
            report["failures"] = ["containment-query-failed"]
            report["error"] = str(error)
            report_attempted = True
            _emit(report)
            raise
        outside_solid = sum(1 for value in containment_values if value == outside_enum)
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
            "containment_query": "BRepBody.pointContainment",
            "nodes_outside_reconstruction_solid": outside_solid,
        }

        omitted_count = report["source_to_reconstruction"]["beyond_omitted_threshold"]
        omitted = {
            "severity": "advisory" if omitted_count else "pass",
            "threshold_mm": omitted_threshold,
            "count": omitted_count,
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

        # No reconstructed node lies further than the threshold from the source in
        # *either* direction, so the verdict holds whichever way the sign runs and
        # the convention does not need establishing.
        candidates = [value for value in recon_to_source if abs(value) > invented_threshold]
        if not candidates:
            report["verdict"] = {
                "invented_material": {
                    "severity": "pass",
                    "threshold_mm": invented_threshold,
                    "count": 0,
                    "max_mm": 0.0,
                    "worst_points": [],
                    "sign_convention": "not required: no reconstructed node lies further than the "
                                       "threshold from the source in either direction, so no sign "
                                       "reading could change this verdict.",
                    "meaning": INVENTED_MEANING,
                },
                "omitted_detail": omitted,
            }
            report["ok"] = True
            report_attempted = True
            _emit(report)
            return

        convention, evidence = _probe_sign_convention(
            containment_values, source_to_recon, invented_threshold, outside_enum, inside_enum
        )
        if convention is None:
            # The sign is what separates invented material from omitted detail, and
            # an unverified premise must never produce a passing severity.
            report["failures"] = ["sign-convention-unestablished"]
            report["verdict"] = {
                "invented_material": {
                    "severity": "not-established",
                    "threshold_mm": invented_threshold,
                    "sign_convention": "unestablished",
                    "sign_probe": evidence,
                    "meaning": "Reconstructed nodes lie beyond the threshold, but probing "
                               "BRepBody.pointContainment against compareWith's own signs did not "
                               "agree on which sign means outside. Whether that material is invented "
                               "is NOT established by this run.",
                },
                "omitted_detail": omitted,
            }
            report_attempted = True
            _emit(report)
            raise RuntimeError("Deviation verdict failed closed: sign-convention-unestablished")

        outward = 1.0 if convention == "positive-is-outside" else -1.0
        outside_mm = [value * outward for value in recon_to_source]
        beyond = [value for value in outside_mm if value > invented_threshold]
        invented_points = _worst(recon_points, outside_mm, invented_threshold, 5)
        report["verdict"] = {
            "invented_material": {
                "severity": "failure" if beyond else "pass",
                "threshold_mm": invented_threshold,
                "count": len(beyond),
                "max_mm": max(beyond) if beyond else 0.0,
                "worst_points": invented_points,
                "sign_convention": convention,
                "sign_probe": evidence,
                "meaning": INVENTED_MEANING,
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
