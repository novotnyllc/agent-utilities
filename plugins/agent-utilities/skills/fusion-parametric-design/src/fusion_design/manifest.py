from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable

# Re-exported so both fusion_design.manifest and fusion_design.mesh_source remain
# valid import paths for the mesh-source closed-world constants.
from .mesh_source import (  # noqa: F401
    BREP_SOURCE_FIELDS,
    MESH_PROVENANCES,
    MESH_SOURCE_FIELDS,
    MESH_UNITS,
    UNIT_GUESS_FIELDS,
    UNIT_SOURCES,
    _validate_mesh_sources,
)

# Re-exported so both fusion_design.manifest and fusion_design.printable_parts
# remain valid import paths for the printable-part closed-world constants.
from .printable_parts import (  # noqa: F401
    CONTACT_FACES,
    MATERIAL_STATUSES,
    PRINT_AS_VALUES,
    PRINTABLE_PART_FIELDS,
    PRINTABLE_PART_REQUIRED_FIELDS,
    PROTECTED_FEATURE_KINDS,
    SUPPORT_POLICIES,
    SUPPORT_REGION_KINDS,
    _in_closed_set,
    _validate_printable_parts,
)

# Same re-export contract for the project-level material decision.
from .material_decision import (  # noqa: F401
    ABRASION_RESISTANT_NOZZLES,
    DRYING_STATES,
    FILLED_FAMILIES,
    MATERIAL_DECISION_FIELDS,
    MATERIAL_FAMILIES,
    NOZZLE_MATERIALS,
    _validate_material_decision,
)

# Re-exported for the same reason: fusion_design.manifest stays the one import
# path callers need for the closed-world constants.
from .variants import (  # noqa: F401
    MAXIMUM_VARIANTS,
    VARIANT_FIELDS,
    VARIANT_SOURCES,
    _validate_variants,
)


SOURCE_KINDS = {
    "manufacturer_cad",
    "manufacturer_drawing",
    "standard",
    "authorized_distributor",
    "third_party_cad",
    "user_measurement",
    "scan",
    "conservative_proxy",
}

SOURCE_CONFIDENCES = {"published", "verified_cad", "measured", "provisional", "coupon_verified"}

# How much weight each source confidence can carry. Published, verified CAD, and
# measured are peers: each settles a dimension. Provisional settles nothing, and
# coupon_verified is the only confidence that records a physical test.
CLAIM_CONFIDENCE_RANK = {
    "provisional": 0,
    "published": 1,
    "verified_cad": 1,
    "measured": 1,
    "coupon_verified": 2,
}

REFERENCE_REPRESENTATIONS = {
    "native_parametric_plus_exact_brep",
    "parametric_proxy_plus_conservative_pack",
    "parametric_proxy_plus_mesh_reference",
    "linked_native_component",
}

ROLE_PREFIXES: dict[str, str] = {
    "source": "src_",
    "clearance": "clr_",
    "fabrication": "fab_",
    "design": "des_",
    "packing": "pack_",
    "derived": "calc_",
}

# Which roles must cite something when the parameter is critical. The split is
# whether the value is a claim about the world or a choice the author made:
#
#   source      a measured or published dimension of a real object;
#   clearance   functional spacing -- a fit claim against something real;
#   fabrication process capability, where "2 mm wall" is folklore until a nozzle
#               and a load say otherwise (references/design-doctrine.md);
#   packing     dynamic/service space -- a physical envelope.
#
# design owns preference: a corner radius is measured against nothing, and
# demanding a source_id for it is the false positive that gets the whole rule
# switched off. derived computes from other parameters, so its provenance is its
# inputs, and citing a source there would duplicate rather than record it.
PROVENANCE_REQUIRED_ROLES = {"source", "clearance", "fabrication", "packing"}

_VALID_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    path: str
    message: str
    severity: str = "error"

    def __str__(self) -> str:
        return f"{self.code} at {self.path}: {self.message}"


class ManifestValidationError(ValueError):
    def __init__(self, issues: Iterable[ValidationIssue]) -> None:
        self.issues = tuple(issues)
        super().__init__("\n".join(str(issue) for issue in self.issues))


@dataclass(frozen=True, slots=True)
class Manifest:
    data: dict[str, Any]

    @classmethod
    def from_data(cls, data: dict[str, Any], *, validate: bool = True) -> "Manifest":
        copied = json.loads(json.dumps(data))
        if validate:
            blocking = [issue for issue in validate_manifest_data(copied) if issue.severity == "error"]
            if blocking:
                raise ManifestValidationError(blocking)
        return cls(copied)

    @property
    def project_name(self) -> str:
        return str(self.data.get("project", {}).get("name", ""))

    @property
    def fusion_document(self) -> str:
        return str(self.data.get("project", {}).get("fusion_document", ""))

    @property
    def document_folder(self) -> str:
        """Optional "/"-separated folder path under the active project's root
        that the document-save transaction saves a new document into. Empty
        means the project root folder itself."""
        return str(self.data.get("project", {}).get("document_folder", ""))

    @property
    def parameters(self) -> list[dict[str, Any]]:
        return list(self.data.get("parameters", []))

    @property
    def component_tree(self) -> list[str]:
        return list(self.data.get("component_tree", []))

    @property
    def verification(self) -> dict[str, Any]:
        return dict(self.data.get("verification", {}))

    @property
    def printable_parts(self) -> list[dict[str, Any]]:
        return list(self.data.get("printable_parts", []))

    @property
    def material_decision(self) -> dict[str, Any]:
        decision = self.data.get("material_decision")
        return dict(decision) if isinstance(decision, dict) else {}

    @property
    def variants(self) -> list[dict[str, Any]]:
        return list(self.data.get("variants", []))

    @property
    def mesh_sources(self) -> list[dict[str, Any]]:
        return list(self.data.get("mesh_sources", []))

    def component_roles(self) -> dict[str, str]:
        """Component path -> semantic role, derived from the manifest blocks
        that already own the classification: references (reference, packing,
        keepout), material_decision (validation), printable_parts (product).

        Browser names stay human; this derivation is what the scaffold writes
        into the `fusion_parametric_design` `role` attribute. A path claimed by
        two different specific roles is a manifest contradiction: fail closed.
        A printable part may additionally be a validation coupon; the specific
        role (validation) wins and printable "product" fills only unclaimed
        paths.
        """
        roles: dict[str, str] = {}

        def claim(raw_path: Any, role: str) -> None:
            path = str(raw_path or "").strip()
            if not path:
                return
            existing = roles.get(path)
            if existing is not None and existing != role:
                raise ValueError(
                    f"Component {path!r} is classified as both {existing!r} and {role!r}; "
                    "one component owns one role."
                )
            roles[path] = role

        for reference in _as_list(self.data.get("references")):
            if not isinstance(reference, dict):
                continue
            claim(reference.get("authoring_component"), "reference")
            claim(reference.get("packing_component"), "packing")
            for keepout in _as_list(reference.get("keepout_components")):
                claim(keepout, "keepout")
        claim(self.material_decision.get("coupon_component"), "validation")
        for part in self.printable_parts:
            if isinstance(part, dict):
                path = str(part.get("path") or "").strip()
                if path and path not in roles:
                    roles[path] = "product"
        return roles

    def to_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.data))


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _duplicates(values: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


# Some source kinds cannot carry what they declare. A scan is evidence of shape,
# not of a dimension; a conservative_proxy's entire semantic content is "this is
# a guess". Both stay provisional until a coupon settles them -- which is the one
# thing that can, so coupon_verified is never capped.
KIND_MAX_CONFIDENCE = {
    "scan": "provisional",
    "conservative_proxy": "provisional",
}


def source_confidence(source: Any) -> str:
    """The confidence a source actually carries, not the one it claims.

    Anything that is not a well-formed source carries nothing.
    """
    if not isinstance(source, dict):
        return "provisional"
    confidence = source.get("confidence")
    if not isinstance(confidence, str) or confidence not in CLAIM_CONFIDENCE_RANK:
        return "provisional"
    kind = source.get("kind")
    cap = KIND_MAX_CONFIDENCE.get(kind) if isinstance(kind, str) else None
    if cap is not None and confidence != "coupon_verified":
        return min(confidence, cap, key=lambda value: CLAIM_CONFIDENCE_RANK[value])
    return confidence


def source_backs_claim(source: Any, minimum_confidence: str) -> bool:
    """A claim's confidence may never exceed the confidence of the source it cites.

    ``minimum_confidence`` is the weakest source confidence that can carry the
    claim: ``"published"`` for any settled (non-provisional) claim, and
    ``"coupon_verified"`` for a claim that a coupon was printed and measured.
    """
    return CLAIM_CONFIDENCE_RANK[source_confidence(source)] >= CLAIM_CONFIDENCE_RANK[minimum_confidence]


# A lint over manifest free text, not a gate. SKILL.md: "Fusion export is not
# the slicer. Print time, filament mass, supports, and machine-specific behavior
# require a configured slicer ... rather than inventing them." These values ship
# verbatim into the export index as manufacturing_intent, so an invented claim
# written here is re-served downstream as if it were evidence.
#
# Honest about what it is: a handful of regexes over English prose. The
# false-negative surface is unbounded -- "prints support-free", past tense,
# passive voice, a claim split across two sentences, or any other language all
# walk straight through -- so this can only ever raise suspicion, never settle
# it. That is exactly why every hit is a *warning*: a hard error that refuses
# honest authoring gets worked around, and then it protects nothing. Do not add
# patterns to make it look complete; each one widens the false-positive surface
# without closing a surface that cannot be closed this way.
_FORBIDDEN_CLAIM_PATTERNS = (
    (re.compile(r"\bprints?\s+(?:without|with\s+no)\s+support", re.I), "reads as a support-free print outcome"),
    (re.compile(r"\bno\s+supports?\s+(?:are\s+)?(?:needed|required)", re.I), "reads as a support-free print outcome"),
    (re.compile(r"\bfilament\s+(?:mass|used|usage|length)\b", re.I), "reads as a filament-consumption figure"),
    (re.compile(r"\b\d+(?:\.\d+)?\s*(?:g|grams?)\s+of\s+filament\b", re.I), "reads as a filament-consumption figure"),
)


def claim_text_issue(text: Any) -> str | None:
    """Return why ``text`` reads as an unbacked slicer claim, or None.

    Only a real slice or a real physical test can settle these. Advisory: see
    the note on _FORBIDDEN_CLAIM_PATTERNS for why this cannot be complete.
    """
    if not isinstance(text, str):
        return None
    for pattern, reason in _FORBIDDEN_CLAIM_PATTERNS:
        match = pattern.search(text)
        if match:
            return f"{reason} ({match.group(0).strip()!r})"
    return None


def _reject_claim_text(issues: list[ValidationIssue], text: Any, path: str) -> None:
    reason = claim_text_issue(text)
    if reason:
        issues.append(
            ValidationIssue(
                "forbidden-claim-text",
                path,
                f"Free text {reason}; that outcome comes only from a configured slicer or a physical test, "
                "not from the manifest. Prefer describing the design choice over asserting the result. "
                "Advisory: this check matches a few English phrasings and cannot be relied on to catch all "
                "of them, nor to be right about every hit.",
                severity="warning",
            )
        )


def _reject_unknown_fields(
    issues: list[ValidationIssue], value: dict[str, Any], allowed: set[str], path: str
) -> None:
    for field in sorted(set(value) - allowed):
        issues.append(
            ValidationIssue(
                "unknown-manifest-field",
                f"{path}.{field}" if path else field,
                f"Field {field!r} is not allowed by the manifest schema.",
            )
        )


def validate_manifest_data(data: Any) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    if not isinstance(data, dict):
        return [ValidationIssue("manifest-root-invalid", "$", "Manifest root must be an object.")]

    _reject_unknown_fields(
        issues,
        data,
        {
            "schema_version",
            "project",
            "sources",
            "parameters",
            "component_tree",
            "references",
            "verification",
            "printable_parts",
            "material_decision",
            "variants",
            "mesh_sources",
        },
        "",
    )

    if data.get("schema_version") != 1:
        issues.append(
            ValidationIssue(
                "unsupported-schema-version",
                "schema_version",
                "schema_version must be 1.",
            )
        )

    for field in ("sources", "parameters", "component_tree", "references"):
        if field not in data or not isinstance(data.get(field), list):
            issues.append(
                ValidationIssue(
                    "manifest-list-field-required",
                    field,
                    f"Manifest field {field!r} must be a list.",
                )
            )

    project = data.get("project")
    if not isinstance(project, dict):
        issues.append(ValidationIssue("project-required", "project", "Project must be an object."))
        project = {}
    else:
        _reject_unknown_fields(
            issues,
            project,
            {"name", "units", "process", "material", "fusion_document", "document_folder"},
            "project",
        )
    for field in ("name", "units", "process", "material", "fusion_document"):
        value = project.get(field)
        if not isinstance(value, str) or not value.strip():
            issues.append(
                ValidationIssue(
                    "project-field-required",
                    f"project.{field}",
                    f"Project field {field!r} must be a non-empty string.",
                )
            )
    if "document_folder" in project:
        document_folder = project.get("document_folder")
        # Segments are validated here rather than silently dropped later: the
        # emitter walks exactly what the manifest declares, so "/Designs/" or
        # "Designs//Pods" would save somewhere other than what was written.
        if (
            not isinstance(document_folder, str)
            or not document_folder.strip()
            or any(not segment.strip() for segment in document_folder.split("/"))
        ):
            issues.append(
                ValidationIssue(
                    "project-field-invalid",
                    "project.document_folder",
                    "Project field 'document_folder' must be a '/'-separated folder path with non-empty segments.",
                )
            )

    sources = _as_list(data.get("sources"))
    # Dedupe on the same value that is validated and keyed on below. Deduping the
    # raw string while validating the stripped one lets 'a' and 'a ' pass both
    # gates and then collide in source_map.
    source_ids = [str(source.get("id", "")).strip() for source in sources if isinstance(source, dict)]
    for duplicate in sorted(_duplicates(source_ids)):
        issues.append(ValidationIssue("duplicate-source-id", "sources", f"Source id {duplicate!r} is duplicated."))

    source_map: dict[str, dict[str, Any]] = {}
    valid_name = _VALID_NAME_RE
    for index, raw_source in enumerate(sources):
        path = f"sources[{index}]"
        if not isinstance(raw_source, dict):
            issues.append(ValidationIssue("source-must-be-object", path, "Source entries must be objects."))
            continue
        _reject_unknown_fields(
            issues,
            raw_source,
            {"id", "kind", "locator", "revision", "confidence", "notes"},
            path,
        )
        source_id = str(raw_source.get("id", "")).strip()
        if not source_id or not valid_name.fullmatch(source_id) or source_id != raw_source.get("id"):
            issues.append(
                ValidationIssue(
                    "invalid-source-id",
                    f"{path}.id",
                    "A source id must begin with a letter and contain only letters, digits, and underscores.",
                )
            )
        source_map[source_id] = raw_source
        for field in ("kind", "locator", "revision", "confidence"):
            value = raw_source.get(field)
            if not isinstance(value, str) or not value.strip():
                issues.append(
                    ValidationIssue(
                        "source-provenance-incomplete",
                        f"{path}.{field}",
                        f"Source {source_id!r} must record {field} as a non-empty string.",
                    )
                )
        kind = raw_source.get("kind")
        if not _in_closed_set(kind, SOURCE_KINDS):
            issues.append(
                ValidationIssue(
                    "unknown-source-kind",
                    f"{path}.kind",
                    f"Source kind must be one of {', '.join(sorted(SOURCE_KINDS))}.",
                )
            )
        confidence = raw_source.get("confidence")
        if not _in_closed_set(confidence, SOURCE_CONFIDENCES):
            issues.append(
                ValidationIssue(
                    "unknown-source-confidence",
                    f"{path}.confidence",
                    f"Source confidence must be one of {', '.join(sorted(SOURCE_CONFIDENCES))}.",
                )
            )
        if not isinstance(raw_source.get("notes"), str):
            issues.append(
                ValidationIssue(
                    "source-notes-required",
                    f"{path}.notes",
                    "Source notes must be a string.",
                )
            )
        _reject_claim_text(issues, raw_source.get("notes"), f"{path}.notes")

    parameters = _as_list(data.get("parameters"))
    parameter_names = [str(parameter.get("name", "")) for parameter in parameters if isinstance(parameter, dict)]
    # Stripped exactly as the per-parameter loop below strips, so a variant and
    # its base parameter agree on what the declared name is — and deduplicated
    # on that same stripped form: two entries a variant cannot tell apart are
    # one parameter, and one override would otherwise be written to both.
    normalized_parameter_names = [name.strip() for name in parameter_names]
    declared_parameter_names = {name for name in normalized_parameter_names if name}
    for duplicate in sorted(_duplicates(normalized_parameter_names)):
        issues.append(
            ValidationIssue("duplicate-parameter-name", "parameters", f"Parameter {duplicate!r} is duplicated.")
        )

    for index, raw_parameter in enumerate(parameters):
        path = f"parameters[{index}]"
        if not isinstance(raw_parameter, dict):
            issues.append(ValidationIssue("parameter-must-be-object", path, "Parameter entries must be objects."))
            continue
        _reject_unknown_fields(
            issues,
            raw_parameter,
            {"name", "expression", "units", "role", "source_id", "critical", "provisional", "description"},
            path,
        )

        name = str(raw_parameter.get("name", "")).strip()
        role = str(raw_parameter.get("role", "")).strip()
        expression = str(raw_parameter.get("expression", "")).strip()
        source_id = str(raw_parameter.get("source_id", "")).strip()
        raw_critical = raw_parameter.get("critical")
        raw_provisional = raw_parameter.get("provisional")
        critical = raw_critical if isinstance(raw_critical, bool) else False
        provisional = raw_provisional if isinstance(raw_provisional, bool) else False

        for field_name, raw_value in (("critical", raw_critical), ("provisional", raw_provisional)):
            if not isinstance(raw_value, bool):
                issues.append(
                    ValidationIssue(
                        "parameter-boolean-required",
                        f"{path}.{field_name}",
                        f"Parameter field {field_name!r} must be a boolean.",
                    )
                )

        if not isinstance(raw_parameter.get("expression"), str):
            issues.append(
                ValidationIssue(
                    "parameter-expression-must-be-string",
                    f"{path}.expression",
                    "Parameter expression must be a string accepted by Fusion.",
                )
            )
        if not isinstance(raw_parameter.get("units"), str):
            issues.append(
                ValidationIssue(
                    "parameter-units-must-be-string",
                    f"{path}.units",
                    "Parameter units must be a string.",
                )
            )

        # scripts.py writes the *raw* name into Fusion, so a name that only
        # becomes well-formed after stripping is not the name Fusion will see.
        if not name or not valid_name.fullmatch(name) or name != raw_parameter.get("name"):
            issues.append(
                ValidationIssue(
                    "invalid-parameter-name",
                    f"{path}.name",
                    "Parameter names must begin with a letter, contain only letters, digits, and underscores, "
                    "and carry no surrounding whitespace.",
                )
            )
        expected_prefix = ROLE_PREFIXES.get(role)
        if expected_prefix is None:
            issues.append(
                ValidationIssue(
                    "unknown-parameter-role",
                    f"{path}.role",
                    f"Role must be one of {', '.join(sorted(ROLE_PREFIXES))}.",
                )
            )
        elif name and not name.startswith(expected_prefix):
            issues.append(
                ValidationIssue(
                    "parameter-prefix-mismatch",
                    f"{path}.name",
                    f"Role {role!r} requires the {expected_prefix!r} prefix.",
                )
            )

        if not expression:
            issues.append(
                ValidationIssue(
                    "parameter-expression-required",
                    f"{path}.expression",
                    f"Parameter {name!r} must have a non-empty Fusion expression.",
                )
            )
        # Not gated on `provisional`: provisional means "not settled yet", not
        # "unsourced". A provisional critical dimension still has to say what
        # the starting assumption rests on.
        if critical and role in PROVENANCE_REQUIRED_ROLES and not source_id:
            issues.append(
                ValidationIssue(
                    "critical-parameter-missing-source",
                    f"{path}.source_id",
                    f"Critical {role} parameter {name!r} has no provenance source; a {role} value is a claim "
                    "about the physical world and must cite one.",
                )
            )
        if source_id and (not valid_name.fullmatch(source_id) or source_id != raw_parameter.get("source_id")):
            issues.append(
                ValidationIssue(
                    "invalid-parameter-source-id",
                    f"{path}.source_id",
                    "A parameter source id must begin with a letter and contain only letters, digits, and underscores.",
                )
            )
        if source_id and source_id not in source_map:
            issues.append(
                ValidationIssue(
                    "unknown-parameter-source",
                    f"{path}.source_id",
                    f"Parameter {name!r} references unknown source {source_id!r}.",
                )
            )
        description = raw_parameter.get("description")
        if not isinstance(description, str) or not description.strip():
            issues.append(
                ValidationIssue(
                    "parameter-description-required",
                    f"{path}.description",
                    f"Parameter {name!r} needs a plain-language description.",
                )
            )
        _reject_claim_text(issues, description, f"{path}.description")

        source = source_map.get(source_id)
        if source is not None and critical and not provisional and not source_backs_claim(source, "published"):
            issues.append(
                ValidationIssue(
                    "parameter-confidence-exceeds-source",
                    f"{path}.provisional",
                    f"Critical parameter {name!r} is not provisional but cites source {source_id!r} "
                    f"(kind {source.get('kind')!r}, confidence {source.get('confidence')!r}), which carries only "
                    f"{source_confidence(source)!r} evidence; a claim may not be more confident than its source.",
                )
            )

    component_tree = _as_list(data.get("component_tree"))
    component_paths: list[str] = []
    for index, value in enumerate(component_tree):
        if not isinstance(value, str):
            issues.append(
                ValidationIssue(
                    "component-path-must-be-string",
                    f"component_tree[{index}]",
                    "Component paths must be strings.",
                )
            )
            continue
        component_paths.append(value)
    component_path_set = set(component_paths)
    for duplicate in sorted(_duplicates(component_paths)):
        issues.append(
            ValidationIssue("duplicate-component-path", "component_tree", f"Component path {duplicate!r} is duplicated.")
        )
    for index, component_path in enumerate(component_paths):
        path = f"component_tree[{index}]"
        if not component_path or component_path.startswith("/") or component_path.endswith("/") or "//" in component_path:
            issues.append(
                ValidationIssue(
                    "invalid-component-path",
                    path,
                    "Component paths must be non-empty slash-separated names with no leading, trailing, or repeated slash.",
                )
            )
            continue
        # Fusion trims and normalizes component names on assignment, so a segment
        # that is whitespace-only -- or that differs from a sibling only by
        # surrounding whitespace -- becomes a component the scaffold can never
        # find again by exact match.
        if any(segment != segment.strip() or not segment for segment in component_path.split("/")):
            issues.append(
                ValidationIssue(
                    "invalid-component-path",
                    path,
                    "Component path segments must be non-empty and carry no surrounding whitespace.",
                )
            )
            continue
        for segment in component_path.split("/"):
            if "+" in segment or re.search(r":\d+$", segment):
                issues.append(
                    ValidationIssue(
                        "ambiguous-component-path-segment",
                        path,
                        f"Component segment {segment!r} conflicts with Fusion occurrence-path syntax; avoid '+' and trailing ':<instance>'.",
                    )
                )
        if "/" in component_path:
            parent_path = component_path.rsplit("/", 1)[0]
            if parent_path not in component_path_set:
                issues.append(
                    ValidationIssue(
                        "component-parent-not-in-tree",
                        path,
                        f"Parent component path {parent_path!r} must also be declared in component_tree.",
                    )
                )

    references = _as_list(data.get("references"))
    reference_ids = [
        str(reference.get("id", "")).strip() for reference in references if isinstance(reference, dict)
    ]
    for duplicate in sorted(_duplicates(reference_ids)):
        issues.append(
            ValidationIssue("duplicate-reference-id", "references", f"Reference id {duplicate!r} is duplicated.")
        )

    # Components owned by the references section: somebody else's hardware plus
    # the volumes it needs. None of them is printable output, and the keep-out
    # set is what the interference checks below are protecting.
    reference_components: set[str] = set()
    declared_keepouts: set[str] = set()
    packing_components: list[str] = []

    for index, raw_reference in enumerate(references):
        path = f"references[{index}]"
        if not isinstance(raw_reference, dict):
            issues.append(ValidationIssue("reference-must-be-object", path, "Reference entries must be objects."))
            continue
        _reject_unknown_fields(
            issues,
            raw_reference,
            {
                "id",
                "source_id",
                "authoring_component",
                "packing_component",
                "representation",
                "keepout_components",
                "no_keepout_rationale",
            },
            path,
        )
        def reference_string(field: str) -> str:
            value = raw_reference.get(field)
            if not isinstance(value, str):
                issues.append(
                    ValidationIssue(
                        "reference-field-must-be-string",
                        f"{path}.{field}",
                        f"Reference field {field!r} must be a string.",
                    )
                )
                return ""
            return value.strip()

        reference_id = reference_string("id")
        source_id = reference_string("source_id")
        authoring = reference_string("authoring_component")
        packing = reference_string("packing_component")
        representation = reference_string("representation")
        if not _in_closed_set(representation, REFERENCE_REPRESENTATIONS):
            issues.append(
                ValidationIssue(
                    "unknown-reference-representation",
                    f"{path}.representation",
                    f"Representation must be one of {', '.join(sorted(REFERENCE_REPRESENTATIONS))}.",
                )
            )
        if not reference_id or not valid_name.fullmatch(reference_id) or reference_id != raw_reference.get("id"):
            issues.append(
                ValidationIssue(
                    "invalid-reference-id",
                    f"{path}.id",
                    "A reference id must begin with a letter and contain only letters, digits, and underscores.",
                )
            )
        if source_id and (not valid_name.fullmatch(source_id) or source_id != raw_reference.get("source_id")):
            issues.append(
                ValidationIssue(
                    "invalid-reference-source-id",
                    f"{path}.source_id",
                    "A reference source id must begin with a letter and contain only letters, digits, and underscores.",
                )
            )
        if not authoring:
            issues.append(
                ValidationIssue(
                    "reference-missing-authoring-component",
                    f"{path}.authoring_component",
                    f"Reference {reference_id!r} needs an editable authoring model.",
                )
            )
        if not packing:
            issues.append(
                ValidationIssue(
                    "reference-missing-packing-component",
                    f"{path}.packing_component",
                    f"Reference {reference_id!r} needs an exact or conservative packing model.",
                )
            )
        if source_id not in source_map:
            issues.append(
                ValidationIssue(
                    "unknown-reference-source",
                    f"{path}.source_id",
                    f"Reference {reference_id!r} references unknown source {source_id!r}.",
                )
            )
        for field_name, component_path in (
            ("authoring_component", authoring),
            ("packing_component", packing),
        ):
            if component_path and component_path not in component_paths:
                issues.append(
                    ValidationIssue(
                        "reference-component-not-in-tree",
                        f"{path}.{field_name}",
                        f"Component path {component_path!r} is not declared in component_tree.",
                    )
                )
            if component_path:
                reference_components.add(component_path)
        if packing:
            packing_components.append(packing)
        # The editable proxy and the exact-or-conservative packing solid answer
        # different questions; one component cannot be both.
        if authoring and packing and authoring == packing:
            issues.append(
                ValidationIssue(
                    "reference-authoring-equals-packing",
                    f"{path}.packing_component",
                    f"Reference {reference_id!r} names {packing!r} as both its authoring and packing model; "
                    "the editable reference and the packing solid must be different components.",
                )
            )
        raw_keepouts = raw_reference.get("keepout_components")
        keepouts = _as_list(raw_keepouts)
        raw_no_keepout_rationale = raw_reference.get("no_keepout_rationale")
        if raw_no_keepout_rationale is not None and not isinstance(raw_no_keepout_rationale, str):
            issues.append(
                ValidationIssue(
                    "no-keepout-rationale-must-be-string",
                    f"{path}.no_keepout_rationale",
                    "no_keepout_rationale must be a string.",
                )
            )
        no_keepout_rationale = (
            raw_no_keepout_rationale.strip() if isinstance(raw_no_keepout_rationale, str) else ""
        )
        _reject_claim_text(issues, raw_no_keepout_rationale, f"{path}.no_keepout_rationale")
        if not isinstance(raw_keepouts, list):
            issues.append(
                ValidationIssue(
                    "reference-keepouts-must-be-list",
                    f"{path}.keepout_components",
                    "keepout_components must be a list.",
                )
            )
        if not keepouts and not no_keepout_rationale:
            issues.append(
                ValidationIssue(
                    "reference-keepout-required",
                    f"{path}.keepout_components",
                    f"Reference {reference_id!r} needs at least one functional keep-out or an explicit no-keepout rationale.",
                )
            )
        for duplicate in sorted(_duplicates(str(value) for value in keepouts)):
            issues.append(
                ValidationIssue(
                    "duplicate-keepout-component",
                    f"{path}.keepout_components",
                    f"Keep-out component {duplicate!r} is duplicated.",
                )
            )
        for keepout in keepouts:
            if not isinstance(keepout, str):
                issues.append(
                    ValidationIssue(
                        "keepout-component-must-be-string",
                        f"{path}.keepout_components",
                        "Keep-out component paths must be strings.",
                    )
                )
                continue
            if keepout not in component_paths:
                issues.append(
                    ValidationIssue(
                        "keepout-component-not-in-tree",
                        f"{path}.keepout_components",
                        f"Keep-out component {keepout!r} is not declared in component_tree.",
                    )
                )
            # A keep-out is the volume the object needs *beyond* its own body.
            # Naming its own model satisfies reference-keepout-required while
            # declaring nothing.
            if keepout in (authoring, packing):
                issues.append(
                    ValidationIssue(
                        "keepout-is-own-model",
                        f"{path}.keepout_components",
                        f"Reference {reference_id!r} names its own model {keepout!r} as a functional keep-out; "
                        "a keep-out must be space the object needs beyond the volume it occupies.",
                    )
                )
            declared_keepouts.add(keepout)
            reference_components.add(keepout)

    # Two physical objects cannot occupy one solid: sharing a packing model makes
    # every packing check for one silently stand in for the other.
    for duplicate in sorted(_duplicates(packing_components)):
        issues.append(
            ValidationIssue(
                "duplicate-packing-component",
                "references",
                f"Packing component {duplicate!r} is claimed by more than one reference.",
            )
        )

    verification = data.get("verification")
    if not isinstance(verification, dict):
        issues.append(
            ValidationIssue("verification-required", "verification", "A verification contract is required.")
        )
    else:
        _reject_unknown_fields(
            issues,
            verification,
            {
                "required_components",
                "clearance_checks",
                "interference_checks",
                "expected_print_parts",
                "allowed_suppressed_paths",
                "allow_suppressed_timeline_features",
            },
            "verification",
        )
        # Suppression is how Fusion models configurations and open/closed/service
        # states; declaring it keeps undeclared suppression a hard failure.
        raw_allowed_suppressed = verification.get("allowed_suppressed_paths")
        if raw_allowed_suppressed is not None and not isinstance(raw_allowed_suppressed, list):
            issues.append(
                ValidationIssue(
                    "invalid-allowed-suppressed-paths",
                    "verification.allowed_suppressed_paths",
                    "allowed_suppressed_paths must be a list of declared component paths.",
                )
            )
        else:
            for index, value in enumerate(_as_list(raw_allowed_suppressed)):
                if not isinstance(value, str) or value not in component_paths:
                    issues.append(
                        ValidationIssue(
                            "invalid-allowed-suppressed-paths",
                            f"verification.allowed_suppressed_paths[{index}]",
                            f"Allowed suppressed path {value!r} is not declared in component_tree.",
                        )
                    )
        if "allow_suppressed_timeline_features" in verification and not isinstance(
            verification["allow_suppressed_timeline_features"], bool
        ):
            issues.append(
                ValidationIssue(
                    "invalid-suppressed-timeline-allowance",
                    "verification.allow_suppressed_timeline_features",
                    "allow_suppressed_timeline_features must be a boolean.",
                )
            )
        for field in ("required_components", "clearance_checks", "interference_checks", "expected_print_parts"):
            if field not in verification or not isinstance(verification.get(field), list):
                issues.append(
                    ValidationIssue(
                        "verification-field-required",
                        f"verification.{field}",
                        f"Verification field {field!r} must be a list.",
                    )
                )
        required_components: list[str] = []
        expected_print_parts: list[str] = []
        for field, destination in (
            ("required_components", required_components),
            ("expected_print_parts", expected_print_parts),
        ):
            for index, value in enumerate(_as_list(verification.get(field))):
                if isinstance(value, str):
                    destination.append(value)
                else:
                    issues.append(
                        ValidationIssue(
                            "verification-component-must-be-string",
                            f"verification.{field}[{index}]",
                            "Verification component paths must be strings.",
                        )
                    )
        for duplicate in sorted(_duplicates(required_components)):
            issues.append(
                ValidationIssue(
                    "duplicate-required-component",
                    "verification.required_components",
                    f"Required component {duplicate!r} is duplicated.",
                )
            )
        for duplicate in sorted(_duplicates(expected_print_parts)):
            issues.append(
                ValidationIssue(
                    "duplicate-expected-print-part",
                    "verification.expected_print_parts",
                    f"Expected print part {duplicate!r} is duplicated.",
                )
            )

        for component_path in required_components:
            if str(component_path) not in component_paths:
                issues.append(
                    ValidationIssue(
                        "required-component-not-in-tree",
                        "verification.required_components",
                        f"Required component {component_path!r} is not declared in component_tree.",
                    )
                )

        required_component_set = set(required_components)
        for component_path in expected_print_parts:
            if component_path not in component_path_set:
                issues.append(
                    ValidationIssue(
                        "expected-print-part-not-in-tree",
                        "verification.expected_print_parts",
                        f"Expected print part {component_path!r} is not declared in component_tree.",
                    )
                )
            # Anything the project intends to print must also be something
            # verification asserts exists; otherwise the print pipeline is told
            # to produce a part that may never have been modelled.
            if component_path not in required_component_set:
                issues.append(
                    ValidationIssue(
                        "expected-print-part-not-required",
                        "verification.expected_print_parts",
                        f"Expected print part {component_path!r} is not listed in "
                        "verification.required_components, so verification would pass without it existing.",
                    )
                )
            # A reference model is somebody else's hardware, or validation
            # geometry for it. It is never printable output (SKILL.md section 5).
            if component_path in reference_components:
                issues.append(
                    ValidationIssue(
                        "expected-print-part-is-reference-model",
                        "verification.expected_print_parts",
                        f"Expected print part {component_path!r} is a reference authoring, packing, or keep-out "
                        "model; reference geometry is validation geometry, not printable output.",
                    )
                )

        verification_check_ids: list[str] = []
        # Keyed on the unordered pair: reversing 'one' and 'two' describes the
        # same physical relationship and must not hide a contradiction.
        clearance_minima: dict[frozenset[str], set[float]] = {}
        allowed_interference_pairs: dict[frozenset[str], str] = {}
        for check_kind, raw_checks in (
            ("clearance", _as_list(verification.get("clearance_checks"))),
            ("interference", _as_list(verification.get("interference_checks"))),
        ):
            for index, raw_check in enumerate(raw_checks):
                path = f"verification.{check_kind}_checks[{index}]"
                if not isinstance(raw_check, dict):
                    issues.append(
                        ValidationIssue(
                            "verification-check-must-be-object",
                            path,
                            "Verification checks must be objects.",
                        )
                    )
                    continue
                allowed_fields = {"id", "one", "two", "minimum_mm"}
                if check_kind == "interference":
                    allowed_fields = {"id", "one", "two", "allow_interference"}
                _reject_unknown_fields(issues, raw_check, allowed_fields, path)
                raw_check_id = raw_check.get("id")
                check_id = raw_check_id.strip() if isinstance(raw_check_id, str) else ""
                if not check_id:
                    issues.append(
                        ValidationIssue(
                            "verification-check-id-required",
                            f"{path}.id",
                            "A verification check id is required.",
                        )
                    )
                else:
                    verification_check_ids.append(check_id)

                raw_one = raw_check.get("one")
                raw_two = raw_check.get("two")
                one = raw_one.strip() if isinstance(raw_one, str) else ""
                two = raw_two.strip() if isinstance(raw_two, str) else ""
                for field_name, component_path in (("one", one), ("two", two)):
                    if component_path not in component_path_set:
                        issues.append(
                            ValidationIssue(
                                "verification-component-not-in-tree",
                                f"{path}.{field_name}",
                                f"Verification component {component_path!r} is not declared in component_tree.",
                            )
                        )
                if one and two and one == two:
                    issues.append(
                        ValidationIssue(
                            "verification-self-check",
                            path,
                            "A verification check must compare two different component paths.",
                        )
                    )

                if check_kind == "clearance":
                    minimum = raw_check.get("minimum_mm")
                    try:
                        finite_minimum = math.isfinite(float(minimum))
                    except (OverflowError, TypeError, ValueError):
                        finite_minimum = False
                    # Zero is not a weak constraint, it is no constraint.
                    # measureMinimumDistance returns 0 both for touching and for
                    # interpenetrating solids, and positive_control.py clamps the
                    # gap with max(..., 0.0), so `distance >= 0` is a tautology --
                    # a 0 mm check reports green while two components fully
                    # interpenetrate. Forbidding contact is what an interference
                    # check is for.
                    if (
                        isinstance(minimum, bool)
                        or not isinstance(minimum, (int, float))
                        or not finite_minimum
                        or minimum <= 0
                    ):
                        issues.append(
                            ValidationIssue(
                                "invalid-clearance-minimum",
                                f"{path}.minimum_mm",
                                "minimum_mm must be a positive number; a zero minimum can never fail "
                                "(measureMinimumDistance returns 0 for touching and for interpenetrating "
                                "solids alike). Express 'must not collide' as an interference check.",
                            )
                        )
                    elif one and two and one != two:
                        clearance_minima.setdefault(frozenset((one, two)), set()).add(float(minimum))
                elif not isinstance(raw_check.get("allow_interference"), bool):
                    issues.append(
                        ValidationIssue(
                            "invalid-interference-allowance",
                            f"{path}.allow_interference",
                            "allow_interference must be a boolean.",
                        )
                    )
                elif raw_check.get("allow_interference") and one and two and one != two:
                    allowed_interference_pairs[frozenset((one, two))] = path

        for duplicate in sorted(_duplicates(verification_check_ids)):
            issues.append(
                ValidationIssue(
                    "duplicate-verification-check-id",
                    "verification",
                    f"Verification check id {duplicate!r} is duplicated.",
                )
            )

        # Each check list validates in isolation, so the contract can demand
        # mutually impossible outcomes for one pair of components and still
        # report every check green.
        for pair, minima in sorted(clearance_minima.items(), key=lambda item: sorted(item[0])):
            names = " and ".join(sorted(pair))
            if len(minima) > 1:
                issues.append(
                    ValidationIssue(
                        "contradictory-verification-checks",
                        "verification.clearance_checks",
                        f"{names} carry clearance checks demanding different minima "
                        f"({', '.join(format(value, 'g') for value in sorted(minima))} mm).",
                    )
                )
            if pair in allowed_interference_pairs:
                issues.append(
                    ValidationIssue(
                        "contradictory-verification-checks",
                        allowed_interference_pairs[pair],
                        f"{names} are required to keep a gap by a clearance check and permitted to overlap by "
                        "an interference check with allow_interference true.",
                    )
                )
        for pair, check_path in sorted(allowed_interference_pairs.items(), key=lambda item: item[1]):
            keepouts = sorted(pair & declared_keepouts)
            if keepouts:
                issues.append(
                    ValidationIssue(
                        "keepout-interference-allowed",
                        f"{check_path}.allow_interference",
                        f"{' and '.join(keepouts)} is a functional keep-out declared by a reference; "
                        "intrusion into it may not be permitted.",
                    )
                )

    required_component_names: list[str] = []
    if isinstance(verification, dict):
        required_component_names = [
            value for value in _as_list(verification.get("required_components")) if isinstance(value, str)
        ]

    expected_print_part_paths: list[str] | None = None
    if isinstance(verification, dict):
        raw_expected = verification.get("expected_print_parts")
        if isinstance(raw_expected, list) and all(isinstance(value, str) for value in raw_expected):
            expected_print_part_paths = list(raw_expected)
    _validate_printable_parts(
        issues,
        data.get("printable_parts"),
        component_path_set,
        expected_print_part_paths,
        source_map,
    )
    # Every rule here is conditional on something being declared, so the cheapest
    # way to satisfy the whole evidence contract is to declare nothing. Emptying
    # the lists also suppresses printable-parts-not-declared, since that keys on
    # expected_print_parts being non-empty. Record the floor.
    if not component_paths and not parameters and not required_component_names:
        issues.append(
            ValidationIssue(
                "manifest-asserts-nothing",
                "$",
                "This manifest declares no components, no parameters and no required components, so every "
                "evidence rule is vacuously satisfied. It asserts nothing about the design.",
                severity="warning",
            )
        )

    _validate_material_decision(
        issues,
        data.get("material_decision"),
        component_path_set,
        source_map,
        data.get("printable_parts"),
    )
    _validate_variants(issues, data.get("variants"), declared_parameter_names)
    _validate_mesh_sources(issues, data.get("mesh_sources"))

    return issues


class _DuplicateManifestKey(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """json.loads takes last-wins on a duplicate key, so the bytes a reviewer
    reads and signs off on can say one thing while the object that drives
    geometry -- and the manifest_sha256 that records provenance -- say another."""
    mapping = dict(pairs)
    if len(mapping) != len(pairs):
        duplicates = sorted(_duplicates(key for key, _ in pairs))
        raise _DuplicateManifestKey(f"Duplicate object key(s): {', '.join(repr(key) for key in duplicates)}.")
    return mapping


def load_manifest(path: str | Path) -> Manifest:
    manifest_path = Path(path)
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except FileNotFoundError as exc:
        raise ManifestValidationError(
            [ValidationIssue("manifest-not-found", str(manifest_path), "Manifest file does not exist.")]
        ) from exc
    except _DuplicateManifestKey as exc:
        raise ManifestValidationError(
            [ValidationIssue("manifest-duplicate-key", str(manifest_path), str(exc))]
        ) from exc
    except json.JSONDecodeError as exc:
        raise ManifestValidationError(
            [
                ValidationIssue(
                    "manifest-json-invalid",
                    f"{manifest_path}:{exc.lineno}:{exc.colno}",
                    exc.msg,
                )
            ]
        ) from exc
    if not isinstance(data, dict):
        raise ManifestValidationError(
            [ValidationIssue("manifest-root-invalid", str(manifest_path), "Manifest root must be an object.")]
        )
    return Manifest.from_data(data)
