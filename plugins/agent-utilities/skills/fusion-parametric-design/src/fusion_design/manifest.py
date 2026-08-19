from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable

# Re-exported so both fusion_design.manifest and fusion_design.printable_parts
# remain valid import paths for the printable-part closed-world constants.
from .printable_parts import (  # noqa: F401
    CONTACT_FACES,
    MATERIAL_STATUSES,
    PRINT_AS_VALUES,
    PRINTABLE_PART_FIELDS,
    PROTECTED_FEATURE_KINDS,
    SUPPORT_POLICIES,
    SUPPORT_REGION_KINDS,
    _validate_printable_parts,
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
            issues = validate_manifest_data(copied)
            if issues:
                raise ManifestValidationError(issues)
        return cls(copied)

    @property
    def project_name(self) -> str:
        return str(self.data.get("project", {}).get("name", ""))

    @property
    def fusion_document(self) -> str:
        return str(self.data.get("project", {}).get("fusion_document", ""))

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
            {"name", "units", "process", "material", "fusion_document"},
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

    sources = _as_list(data.get("sources"))
    source_ids = [str(source.get("id", "")) for source in sources if isinstance(source, dict)]
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
        if not source_id or not valid_name.fullmatch(source_id):
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
        if kind not in SOURCE_KINDS:
            issues.append(
                ValidationIssue(
                    "unknown-source-kind",
                    f"{path}.kind",
                    f"Source kind must be one of {', '.join(sorted(SOURCE_KINDS))}.",
                )
            )
        confidence = raw_source.get("confidence")
        if confidence not in SOURCE_CONFIDENCES:
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

    parameters = _as_list(data.get("parameters"))
    parameter_names = [str(parameter.get("name", "")) for parameter in parameters if isinstance(parameter, dict)]
    for duplicate in sorted(_duplicates(parameter_names)):
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

        if not name or not valid_name.match(name):
            issues.append(
                ValidationIssue(
                    "invalid-parameter-name",
                    f"{path}.name",
                    "Parameter names must begin with a letter and contain only letters, digits, and underscores.",
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
        if critical and role == "source" and not source_id:
            issues.append(
                ValidationIssue(
                    "critical-parameter-missing-source",
                    f"{path}.source_id",
                    f"Critical source parameter {name!r} has no provenance source.",
                )
            )
        if source_id and not valid_name.fullmatch(source_id):
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

        source = source_map.get(source_id)
        if (
            source
            and source.get("kind") == "scan"
            and source.get("confidence") != "coupon_verified"
            and critical
            and not provisional
        ):
            issues.append(
                ValidationIssue(
                    "scan-parameter-not-provisional",
                    f"{path}.provisional",
                    f"Critical parameter {name!r} comes from a scan and must remain provisional until coupon-verified.",
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
    reference_ids = [str(reference.get("id", "")) for reference in references if isinstance(reference, dict)]
    for duplicate in sorted(_duplicates(reference_ids)):
        issues.append(
            ValidationIssue("duplicate-reference-id", "references", f"Reference id {duplicate!r} is duplicated.")
        )

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
        if representation not in REFERENCE_REPRESENTATIONS:
            issues.append(
                ValidationIssue(
                    "unknown-reference-representation",
                    f"{path}.representation",
                    f"Representation must be one of {', '.join(sorted(REFERENCE_REPRESENTATIONS))}.",
                )
            )
        if not reference_id or not valid_name.fullmatch(reference_id):
            issues.append(
                ValidationIssue(
                    "invalid-reference-id",
                    f"{path}.id",
                    "A reference id must begin with a letter and contain only letters, digits, and underscores.",
                )
            )
        if source_id and not valid_name.fullmatch(source_id):
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

    verification = data.get("verification")
    if not isinstance(verification, dict):
        issues.append(
            ValidationIssue("verification-required", "verification", "A verification contract is required.")
        )
    else:
        _reject_unknown_fields(
            issues,
            verification,
            {"required_components", "clearance_checks", "interference_checks", "expected_print_parts"},
            "verification",
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

        for component_path in expected_print_parts:
            if component_path not in component_path_set:
                issues.append(
                    ValidationIssue(
                        "expected-print-part-not-in-tree",
                        "verification.expected_print_parts",
                        f"Expected print part {component_path!r} is not declared in component_tree.",
                    )
                )

        verification_check_ids: list[str] = []
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
                    if (
                        isinstance(minimum, bool)
                        or not isinstance(minimum, (int, float))
                        or not finite_minimum
                        or minimum < 0
                    ):
                        issues.append(
                            ValidationIssue(
                                "invalid-clearance-minimum",
                                f"{path}.minimum_mm",
                                "minimum_mm must be a non-negative number.",
                            )
                        )
                elif not isinstance(raw_check.get("allow_interference"), bool):
                    issues.append(
                        ValidationIssue(
                            "invalid-interference-allowance",
                            f"{path}.allow_interference",
                            "allow_interference must be a boolean.",
                        )
                    )

        for duplicate in sorted(_duplicates(verification_check_ids)):
            issues.append(
                ValidationIssue(
                    "duplicate-verification-check-id",
                    "verification",
                    f"Verification check id {duplicate!r} is duplicated.",
                )
            )

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

    return issues


def load_manifest(path: str | Path) -> Manifest:
    manifest_path = Path(path)
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ManifestValidationError(
            [ValidationIssue("manifest-not-found", str(manifest_path), "Manifest file does not exist.")]
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
