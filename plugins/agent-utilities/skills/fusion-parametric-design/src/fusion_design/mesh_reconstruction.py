from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable

from .manifest import (
    ManifestValidationError,
    ValidationIssue,
    _in_closed_set,
    _reject_unknown_fields,
    _VALID_NAME_RE,
)
from .mesh_source import _SHA256_RE, MESH_PROVENANCES, validate_mesh_source_record


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
    "source_id",
    "source_sha256",
}

# facet_budget is deliberately absent: it is required exactly when the edit kind
# is boolean-mechanical, which _validate_inputs decides rather than this list.
REQUIRED_CLASSIFICATION_INPUTS = (
    "edit_kind",
    "provenance",
    "watertight",
    "facet_count",
    "brep_source_available",
    "source_id",
    "source_sha256",
)

# The link the manifest cannot make: mesh_sources records a file, not a Fusion
# body, so every geometry entry point takes the binding explicitly.
BODY_BINDING_FIELDS = {"component_path", "body_name"}


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


def _validate_inputs(inputs: dict[str, Any], prefix: str) -> list[ValidationIssue]:
    """Type-check the recorded inputs, so re-deriving the choice means something.

    The record's own error message promises the choice is reproducible from what
    drove it.  That is only true if the values are checked on the way out with
    the same closed sets they were checked with on the way in.
    """
    issues: list[ValidationIssue] = []
    _reject_unknown_fields(issues, inputs, CLASSIFICATION_INPUT_FIELDS, prefix)
    for field in REQUIRED_CLASSIFICATION_INPUTS:
        if field not in inputs:
            issues.append(
                ValidationIssue(
                    "classification-inputs-required",
                    f"{prefix}.{field}",
                    f"inputs.{field} is required; the choice must be reproducible from what drove it.",
                )
            )

    def bad(field: str, message: str) -> None:
        issues.append(ValidationIssue("classification-invalid-inputs", f"{prefix}.{field}", message))

    if "edit_kind" in inputs and not _in_closed_set(inputs["edit_kind"], EDIT_KINDS):
        bad("edit_kind", f"inputs.edit_kind must be one of {', '.join(sorted(EDIT_KINDS))}.")
    if "provenance" in inputs and not _in_closed_set(inputs["provenance"], MESH_PROVENANCES):
        bad(
            "provenance",
            f"inputs.provenance must be one of {', '.join(sorted(MESH_PROVENANCES))}.",
        )
    for field in ("watertight", "brep_source_available"):
        if field in inputs and not isinstance(inputs[field], bool):
            bad(field, f"inputs.{field} must be a boolean.")
    facet_count = inputs.get("facet_count")
    if "facet_count" in inputs and (
        isinstance(facet_count, bool) or not isinstance(facet_count, int) or facet_count < 0
    ):
        bad("facet_count", "inputs.facet_count must be a non-negative integer.")
    facet_budget = inputs.get("facet_budget")
    if inputs.get("edit_kind") == "boolean-mechanical":
        if isinstance(facet_budget, bool) or not isinstance(facet_budget, int) or facet_budget < 1:
            bad(
                "facet_budget",
                "inputs.facet_budget must be a positive integer for a boolean-mechanical edit; "
                "it is the single number that decides faceted-brep against parametric-rebuild.",
            )
    elif "facet_budget" in inputs:
        bad("facet_budget", "inputs.facet_budget is only allowed when edit_kind is 'boolean-mechanical'.")
    source_id = inputs.get("source_id")
    if "source_id" in inputs and (
        not isinstance(source_id, str) or not _VALID_NAME_RE.fullmatch(source_id)
    ):
        bad("source_id", "inputs.source_id must be the id of the mesh source this choice was made for.")
    source_sha256 = inputs.get("source_sha256")
    if "source_sha256" in inputs and (
        not isinstance(source_sha256, str) or not _SHA256_RE.fullmatch(source_sha256)
    ):
        bad(
            "source_sha256",
            "inputs.source_sha256 must be the captured digest of the mesh this choice was made for; "
            "without it a classification transfers to any source.",
        )
    return issues


def _decide(inputs: dict[str, Any]) -> tuple[str, str]:
    """The whole decision, in one place, so a record can be re-derived from it.

    Callers must have validated ``inputs`` first; this function is the only
    authority on which path a set of inputs means.
    """
    edit_kind = inputs["edit_kind"]
    watertight = bool(inputs["watertight"])
    facet_count = int(inputs["facet_count"])
    facet_budget = inputs.get("facet_budget")
    provenance = inputs["provenance"]
    brep_source_available = bool(inputs["brep_source_available"])

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
    return path, rationale


def classify(request: Any, source_record: Any) -> Classification:
    """Choose exactly one reconstruction path and record why, before touching geometry."""
    issues = _validate_request(request)
    issues.extend(validate_mesh_source_record(source_record))
    if issues:
        raise ManifestValidationError(issues)

    # Keyed on exactly the strings the closed-set tests above accepted: normalizing
    # here and not there is how an accepted value turns into an unmatched key.
    facet_budget = request.get("facet_budget")
    inputs: dict[str, Any] = {
        "edit_kind": request["edit_kind"],
        "provenance": source_record["provenance"],
        "watertight": bool(request["watertight"]),
        "facet_count": int(request["facet_count"]),
        "brep_source_available": isinstance(source_record.get("brep_source"), dict),
        # The classification is the artifact that gates geometry, so it carries
        # the identity of the mesh it was decided for; otherwise one stale record
        # authorizes work on any source in the project.
        "source_id": source_record["id"],
        "source_sha256": source_record["sha256"],
    }
    if facet_budget is not None:
        inputs["facet_budget"] = int(facet_budget)

    path, rationale = _decide(inputs)
    return Classification(path=path, rationale=rationale, inputs=inputs)


def classification_from_record(record: Any) -> Classification:
    """Rehydrate a recorded classification, re-deriving the choice from its inputs."""
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
        issues.extend(_validate_inputs(inputs, "classification.inputs"))
    if issues:
        raise ManifestValidationError(issues)

    derived, _ = _decide(inputs)
    if derived != path:
        raise ManifestValidationError(
            [
                ValidationIssue(
                    "classification-path-contradicts-inputs",
                    "classification.path",
                    f"The recorded inputs decide {derived!r} but the record claims {path!r}; "
                    "a faceted conversion is never recorded as a parametric rebuild.",
                )
            ]
        )
    return Classification(path=path, rationale=str(rationale).strip(), inputs=dict(inputs))


def require_classification(
    record: Any,
    operation: str,
    allowed_paths: Iterable[str],
    source_record: Any,
) -> Classification:
    """The gate every geometry entry point calls first.

    ``allowed_paths`` is required, and names the paths this entry point actually
    implements: proving that *a* decision exists is not the same as proving the
    decision permits *this* operation.  ``source_record`` is required for the
    same reason — a classification decided for one mesh must not open the gate
    for another.
    """
    allowed = set(allowed_paths)
    unknown = sorted(allowed - RECONSTRUCTION_PATHS)
    if not allowed or unknown:
        raise ValueError(
            f"Operation {operation!r} must declare a non-empty subset of "
            f"{', '.join(sorted(RECONSTRUCTION_PATHS))}; got {sorted(allowed)}."
        )
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
    classification = classification_from_record(record)

    issues = validate_mesh_source_record(source_record)
    if issues:
        raise ManifestValidationError(issues)
    if classification.path not in allowed:
        issues.append(
            ValidationIssue(
                "classification-path-forbids-operation",
                "classification.path",
                f"Operation {operation!r} implements {', '.join(sorted(allowed))}, but the recorded "
                f"path is {classification.path!r}; classify again rather than running the wrong path.",
            )
        )
    if classification.inputs["source_sha256"] != source_record["sha256"] or (
        classification.inputs["source_id"] != source_record["id"]
    ):
        issues.append(
            ValidationIssue(
                "classification-source-mismatch",
                "classification.inputs.source_sha256",
                f"The classification was decided for mesh source {classification.inputs['source_id']!r} "
                f"({classification.inputs['source_sha256'][:12]}...), not for "
                f"{source_record['id']!r} ({str(source_record['sha256'])[:12]}...); classify the source "
                "actually being operated on.",
            )
        )
    if issues:
        raise ManifestValidationError(issues)
    return classification


def _require_positive_number(issues: list[ValidationIssue], value: Any, path: str, code: str, message: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) <= 0.0
    ):
        issues.append(ValidationIssue(code, path, message))


def _validate_body_binding(issues: list[ValidationIssue], raw: Any, path: str, code: str) -> None:
    """A body binding is the human-established link the capture report cannot make."""
    if not isinstance(raw, dict):
        issues.append(
            ValidationIssue(code, path, "A body binding must be an object with component_path and body_name.")
        )
        return
    _reject_unknown_fields(issues, raw, BODY_BINDING_FIELDS, path)
    if not isinstance(raw.get("component_path"), str):
        issues.append(
            ValidationIssue(
                code,
                f"{path}.component_path",
                "component_path must be a string; use \"\" for the root component.",
            )
        )
    body_name = raw.get("body_name")
    if not isinstance(body_name, str) or not body_name.strip():
        issues.append(
            ValidationIssue(
                code,
                f"{path}.body_name",
                "body_name must name the body; nothing in the manifest binds a mesh_sources record to a body.",
            )
        )


def _source_evidence(source_record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": source_record["id"],
        "sha256": source_record["sha256"],
        "path": str(source_record["path"]).strip(),
        "units": source_record["units"],
        "unit_source": source_record["unit_source"],
        "provenance": source_record["provenance"],
    }
