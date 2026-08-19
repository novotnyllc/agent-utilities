from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .manifest import ManifestValidationError, ValidationIssue, _in_closed_set, _reject_unknown_fields
from .mesh_source import validate_mesh_source_record


RECONSTRUCTION_PATHS = {"mesh-edit", "faceted-brep", "parametric-rebuild"}

EDIT_KINDS = {
    "cosmetic-local",
    "clearance-only",
    "boolean-mechanical",
    "dimensional",
    "structural",
}

CLASSIFICATION_REQUEST_FIELDS = {"edit_kind", "watertight", "facet_count", "facet_budget"}

CLASSIFICATION_RECORD_FIELDS = {"path", "rationale", "inputs"}

CLASSIFICATION_INPUT_FIELDS = {
    "edit_kind",
    "provenance",
    "watertight",
    "facet_count",
    "facet_budget",
    "brep_source_available",
}


@dataclass(frozen=True, slots=True)
class Classification:
    """The recorded choice of reconstruction path, written before any geometry runs."""

    path: str
    rationale: str
    inputs: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "rationale": self.rationale, "inputs": dict(self.inputs)}


def _validate_request(request: Any) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not isinstance(request, dict):
        return [
            ValidationIssue(
                "classification-request-must-be-object",
                "request",
                "A classification request must be an object.",
            )
        ]
    _reject_unknown_fields(issues, request, CLASSIFICATION_REQUEST_FIELDS, "request")

    edit_kind = request.get("edit_kind")
    if not _in_closed_set(edit_kind, EDIT_KINDS):
        issues.append(
            ValidationIssue(
                "classification-invalid-edit-kind",
                "request.edit_kind",
                f"edit_kind must be one of {', '.join(sorted(EDIT_KINDS))}.",
            )
        )
    if not isinstance(request.get("watertight"), bool):
        issues.append(
            ValidationIssue(
                "classification-invalid-watertight",
                "request.watertight",
                "watertight must be a boolean read from the capture report, never assumed.",
            )
        )
    facet_count = request.get("facet_count")
    if isinstance(facet_count, bool) or not isinstance(facet_count, int) or facet_count < 0:
        issues.append(
            ValidationIssue(
                "classification-invalid-facet-count",
                "request.facet_count",
                "facet_count must be a non-negative integer read from the capture report.",
            )
        )
    facet_budget = request.get("facet_budget")
    # The budget is declared per request, never a module constant: Fusion's own
    # ceiling is version-specific and the widely-cited numbers are unverified.
    if edit_kind == "boolean-mechanical":
        if isinstance(facet_budget, bool) or not isinstance(facet_budget, int) or facet_budget < 1:
            issues.append(
                ValidationIssue(
                    "classification-invalid-facet-budget",
                    "request.facet_budget",
                    "A boolean-mechanical edit must declare facet_budget as a positive integer; "
                    "the faceted path is only worth taking below a stated ceiling.",
                )
            )
    elif "facet_budget" in request:
        issues.append(
            ValidationIssue(
                "classification-invalid-facet-budget",
                "request.facet_budget",
                "facet_budget is only allowed when edit_kind is 'boolean-mechanical'.",
            )
        )
    return issues


def classify(request: Any, source_record: Any) -> Classification:
    """Choose exactly one reconstruction path and record why, before touching geometry."""
    issues = _validate_request(request)
    issues.extend(validate_mesh_source_record(source_record))
    if issues:
        raise ManifestValidationError(issues)

    # Keyed on exactly the strings the closed-set tests above accepted: normalizing
    # here and not there is how an accepted value turns into an unmatched key.
    edit_kind = request["edit_kind"]
    watertight = bool(request["watertight"])
    facet_count = int(request["facet_count"])
    facet_budget = request.get("facet_budget")
    provenance = source_record["provenance"]
    brep_source_available = isinstance(source_record.get("brep_source"), dict)

    inputs: dict[str, Any] = {
        "edit_kind": edit_kind,
        "provenance": provenance,
        "watertight": watertight,
        "facet_count": facet_count,
        "brep_source_available": brep_source_available,
    }
    if facet_budget is not None:
        inputs["facet_budget"] = int(facet_budget)

    if edit_kind in ("cosmetic-local", "clearance-only"):
        path = "mesh-edit"
        rationale = (
            f"Edit kind {edit_kind!r} changes no dimension and no structure, so the body stays a mesh; "
            "conversion would add facets without adding design intent."
        )
    elif edit_kind == "boolean-mechanical":
        if not watertight:
            path = "parametric-rebuild"
            rationale = (
                "A boolean needs a solid, and the source mesh is not watertight, so conversion would "
                "yield a surface body; rebuild the geometry the edit requires instead."
            )
        elif facet_count > int(facet_budget):
            path = "parametric-rebuild"
            rationale = (
                f"The source carries {facet_count} facets against a declared budget of {facet_budget}; "
                "conversion at that density yields unselectable faceted geometry, so rebuild instead."
            )
        else:
            path = "faceted-brep"
            rationale = (
                f"A watertight mechanical part of {facet_count} facets, within the declared budget of "
                f"{facet_budget}, converts well enough for a boolean. The result is faceted, never parametric."
            )
    else:
        path = "parametric-rebuild"
        rationale = (
            f"Edit kind {edit_kind!r} changes the geometry itself, and no conversion recovers sketches, "
            "constraints, or feature history; rebuild only the geometry the edit requires."
        )

    if provenance == "capture":
        rationale += " Provenance is a capture, so fitted values stay provisional until a coupon proves them."
    if brep_source_available:
        rationale += (
            " A B-Rep source is recorded and should be preferred, noting that it does not restore design "
            "intent and may not match the mesh that was actually printed."
        )
    return Classification(path=path, rationale=rationale, inputs=inputs)


def classification_from_record(record: Any) -> Classification:
    """Rehydrate a recorded classification, refusing anything that is not one."""
    issues: list[ValidationIssue] = []
    if not isinstance(record, dict):
        raise ManifestValidationError(
            [
                ValidationIssue(
                    "classification-must-be-object",
                    "classification",
                    "A classification record must be an object.",
                )
            ]
        )
    _reject_unknown_fields(issues, record, CLASSIFICATION_RECORD_FIELDS, "classification")

    path = record.get("path")
    if not _in_closed_set(path, RECONSTRUCTION_PATHS):
        issues.append(
            ValidationIssue(
                "classification-unknown-path",
                "classification.path",
                f"path must be exactly one of {', '.join(sorted(RECONSTRUCTION_PATHS))}.",
            )
        )
    rationale = record.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        issues.append(
            ValidationIssue(
                "classification-rationale-required",
                "classification.rationale",
                "A classification without a rationale is not a decision; record why this path was chosen.",
            )
        )
    inputs = record.get("inputs")
    if not isinstance(inputs, dict):
        issues.append(
            ValidationIssue(
                "classification-inputs-required",
                "classification.inputs",
                "inputs must record the values that drove the choice.",
            )
        )
    else:
        _reject_unknown_fields(issues, inputs, CLASSIFICATION_INPUT_FIELDS, "classification.inputs")
        for field in ("edit_kind", "provenance", "watertight", "facet_count", "brep_source_available"):
            if field not in inputs:
                issues.append(
                    ValidationIssue(
                        "classification-inputs-required",
                        f"classification.inputs.{field}",
                        f"inputs.{field} is required; the choice must be reproducible from what drove it.",
                    )
                )
    if issues:
        raise ManifestValidationError(issues)
    return Classification(path=path, rationale=str(rationale).strip(), inputs=dict(inputs))


def require_classification(record: Any, operation: str) -> Classification:
    """The gate every geometry entry point calls first; an unclassified run refuses."""
    if record is None:
        raise ManifestValidationError(
            [
                ValidationIssue(
                    "classification-required",
                    "classification",
                    f"Geometry operation {operation!r} refuses to run without a recorded classification; "
                    "classify the edit and record the choice before any geometry operation.",
                )
            ]
        )
    return classification_from_record(record)
