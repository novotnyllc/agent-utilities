from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .manifest import ValidationIssue


PRINT_AS_VALUES = {"separate", "assembled"}

CONTACT_FACES = {"+X", "-X", "+Y", "-Y", "+Z", "-Z"}

SUPPORT_POLICIES = {"none", "build-plate-only", "everywhere", "explicit-regions"}

SUPPORT_REGION_KINDS = {"enforcer", "blocker"}

PROTECTED_FEATURE_KINDS = {
    "critical-surface",
    "hole",
    "bridge",
    "overhang",
    "mating-face",
    "cosmetic-face",
}

MATERIAL_STATUSES = {"provisional", "coupon_verified"}

PRINTABLE_PART_FIELDS = {
    "id",
    "path",
    "body_name",
    "minimum_volume_mm3",
    "quantity",
    "print_as",
    "orientation",
    "support_policy",
    "support_regions",
    "strength",
    "protected_features",
    "material",
}


def _in_closed_set(value: Any, allowed: set[str]) -> bool:
    """Closed-world membership test that survives unhashable JSON values.

    A bare ``value in allowed`` raises TypeError when the manifest supplies a
    dict or list where an enum string belongs, and that escapes the validator
    as a crash instead of a validation issue.
    """
    try:
        return value in allowed
    except TypeError:
        return False


def _validate_printable_parts(
    issues: list[ValidationIssue],
    printable_parts: Any,
    component_path_set: set[str],
    expected_print_part_paths: list[str] | None,
    source_map: dict[str, dict[str, Any]],
) -> None:
    # Imported here, not at module scope: manifest.py imports this module to
    # re-export the enums, so a top-level import would be circular.
    from .manifest import ValidationIssue, _duplicates, _reject_unknown_fields, _VALID_NAME_RE

    if printable_parts is None:
        return
    if not isinstance(printable_parts, list):
        issues.append(
            ValidationIssue(
                "printable-parts-must-be-list",
                "printable_parts",
                "printable_parts must be a list of printable-part objects.",
            )
        )
        return

    valid_name = _VALID_NAME_RE
    part_ids: list[str] = []
    part_paths: list[str] = []

    def require_string(raw_part: dict[str, Any], field: str, path: str) -> str:
        value = raw_part.get(field)
        if not isinstance(value, str) or not value.strip():
            issues.append(
                ValidationIssue(
                    "printable-part-field-required",
                    f"{path}.{field}",
                    f"Printable-part field {field!r} must be a non-empty string.",
                )
            )
            return ""
        return value.strip()

    for index, raw_part in enumerate(printable_parts):
        path = f"printable_parts[{index}]"
        if not isinstance(raw_part, dict):
            issues.append(
                ValidationIssue(
                    "printable-part-must-be-object",
                    path,
                    "Printable-part entries must be objects.",
                )
            )
            continue
        _reject_unknown_fields(issues, raw_part, PRINTABLE_PART_FIELDS, path)

        part_id = require_string(raw_part, "id", path)
        if part_id and not valid_name.fullmatch(part_id):
            issues.append(
                ValidationIssue(
                    "invalid-printable-part-id",
                    f"{path}.id",
                    "A printable-part id must begin with a letter and contain only letters, digits, and underscores.",
                )
            )
        if part_id:
            part_ids.append(part_id)

        part_path = require_string(raw_part, "path", path)
        if part_path:
            part_paths.append(part_path)
            if part_path not in component_path_set:
                issues.append(
                    ValidationIssue(
                        "printable-part-unknown-path",
                        f"{path}.path",
                        f"Printable part {part_id or index!r} names component path {part_path!r} that is not declared in component_tree.",
                    )
                )

        body_name = raw_part.get("body_name")
        if body_name is not None and (not isinstance(body_name, str) or not body_name.strip()):
            issues.append(
                ValidationIssue(
                    "printable-part-invalid-body-name",
                    f"{path}.body_name",
                    "body_name, when present, must be a non-empty string.",
                )
            )

        # The verification print-part gate is measured against this: without a
        # declared floor, "has a positive-volume solid" passes for a sliver.
        minimum_volume = raw_part.get("minimum_volume_mm3")
        try:
            finite_volume = math.isfinite(float(minimum_volume))
        except (OverflowError, TypeError, ValueError):
            finite_volume = False
        if (
            isinstance(minimum_volume, bool)
            or not isinstance(minimum_volume, (int, float))
            or not finite_volume
            or minimum_volume <= 0
        ):
            issues.append(
                ValidationIssue(
                    "printable-part-invalid-minimum-volume",
                    f"{path}.minimum_volume_mm3",
                    "minimum_volume_mm3 must be a positive number; it is the declared floor the "
                    "verification print-part gate measures the resolved solid against.",
                )
            )

        quantity = raw_part.get("quantity", 1)
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            issues.append(
                ValidationIssue(
                    "printable-part-invalid-quantity",
                    f"{path}.quantity",
                    "quantity must be an integer greater than or equal to 1.",
                )
            )

        print_as = require_string(raw_part, "print_as", path)
        if print_as and not _in_closed_set(print_as, PRINT_AS_VALUES):
            issues.append(
                ValidationIssue(
                    "printable-part-invalid-print-as",
                    f"{path}.print_as",
                    f"print_as must be one of {', '.join(sorted(PRINT_AS_VALUES))}.",
                )
            )

        orientation = raw_part.get("orientation")
        if not isinstance(orientation, dict):
            issues.append(
                ValidationIssue(
                    "printable-part-invalid-orientation",
                    f"{path}.orientation",
                    "orientation must be an object with contact_face, rationale, and allowed_alternatives.",
                )
            )
        else:
            _reject_unknown_fields(
                issues,
                orientation,
                {"contact_face", "rationale", "allowed_alternatives"},
                f"{path}.orientation",
            )
            contact_face = orientation.get("contact_face")
            if not _in_closed_set(contact_face, CONTACT_FACES):
                issues.append(
                    ValidationIssue(
                        "printable-part-invalid-orientation",
                        f"{path}.orientation.contact_face",
                        f"contact_face must be one of {', '.join(sorted(CONTACT_FACES))}.",
                    )
                )
            rationale = orientation.get("rationale")
            if not isinstance(rationale, str) or not rationale.strip():
                issues.append(
                    ValidationIssue(
                        "printable-part-invalid-orientation",
                        f"{path}.orientation.rationale",
                        "orientation.rationale must be a non-empty string.",
                    )
                )
            alternatives = orientation.get("allowed_alternatives")
            if not isinstance(alternatives, list):
                issues.append(
                    ValidationIssue(
                        "printable-part-invalid-orientation",
                        f"{path}.orientation.allowed_alternatives",
                        "allowed_alternatives must be a list of contact faces.",
                    )
                )
            else:
                for alt_index, alternative in enumerate(alternatives):
                    if not _in_closed_set(alternative, CONTACT_FACES):
                        issues.append(
                            ValidationIssue(
                                "printable-part-invalid-orientation",
                                f"{path}.orientation.allowed_alternatives[{alt_index}]",
                                f"Allowed alternative must be one of {', '.join(sorted(CONTACT_FACES))}.",
                            )
                        )
                    elif alternative == contact_face:
                        issues.append(
                            ValidationIssue(
                                "printable-part-invalid-orientation",
                                f"{path}.orientation.allowed_alternatives[{alt_index}]",
                                "allowed_alternatives must not repeat the primary contact_face.",
                            )
                        )
                for duplicate in sorted(_duplicates(str(value) for value in alternatives)):
                    issues.append(
                        ValidationIssue(
                            "printable-part-invalid-orientation",
                            f"{path}.orientation.allowed_alternatives",
                            f"Allowed alternative {duplicate!r} is duplicated.",
                        )
                    )

        support_policy = require_string(raw_part, "support_policy", path)
        if support_policy and not _in_closed_set(support_policy, SUPPORT_POLICIES):
            issues.append(
                ValidationIssue(
                    "printable-part-invalid-support-policy",
                    f"{path}.support_policy",
                    f"support_policy must be one of {', '.join(sorted(SUPPORT_POLICIES))}.",
                )
            )
        support_regions = raw_part.get("support_regions")
        if support_policy == "explicit-regions":
            regions = support_regions if isinstance(support_regions, list) else []
            if not regions:
                issues.append(
                    ValidationIssue(
                        "printable-part-invalid-support-policy",
                        f"{path}.support_regions",
                        "support_policy 'explicit-regions' requires a non-empty support_regions list.",
                    )
                )
            for region_index, raw_region in enumerate(regions):
                region_path = f"{path}.support_regions[{region_index}]"
                if not isinstance(raw_region, dict):
                    issues.append(
                        ValidationIssue(
                            "printable-part-invalid-support-policy",
                            region_path,
                            "support_regions entries must be objects.",
                        )
                    )
                    continue
                _reject_unknown_fields(issues, raw_region, {"kind", "description"}, region_path)
                if not _in_closed_set(raw_region.get("kind"), SUPPORT_REGION_KINDS):
                    issues.append(
                        ValidationIssue(
                            "printable-part-invalid-support-policy",
                            f"{region_path}.kind",
                            f"Support-region kind must be one of {', '.join(sorted(SUPPORT_REGION_KINDS))}.",
                        )
                    )
                description = raw_region.get("description")
                if not isinstance(description, str) or not description.strip():
                    issues.append(
                        ValidationIssue(
                            "printable-part-invalid-support-policy",
                            f"{region_path}.description",
                            "Support regions need a plain-language description.",
                        )
                    )
        elif "support_regions" in raw_part:
            issues.append(
                ValidationIssue(
                    "printable-part-invalid-support-policy",
                    f"{path}.support_regions",
                    "support_regions is only allowed when support_policy is 'explicit-regions'.",
                )
            )

        strength = raw_part.get("strength")
        if not isinstance(strength, dict):
            issues.append(
                ValidationIssue(
                    "printable-part-invalid-strength",
                    f"{path}.strength",
                    "strength must be an object with min_perimeters and infill_percent.",
                )
            )
        else:
            _reject_unknown_fields(issues, strength, {"min_perimeters", "infill_percent"}, f"{path}.strength")
            min_perimeters = strength.get("min_perimeters")
            if isinstance(min_perimeters, bool) or not isinstance(min_perimeters, int) or min_perimeters < 1:
                issues.append(
                    ValidationIssue(
                        "printable-part-invalid-strength",
                        f"{path}.strength.min_perimeters",
                        "min_perimeters must be an integer greater than or equal to 1.",
                    )
                )
            infill = strength.get("infill_percent")
            if not isinstance(infill, dict):
                issues.append(
                    ValidationIssue(
                        "printable-part-invalid-strength",
                        f"{path}.strength.infill_percent",
                        "infill_percent must be an object with a target and optional min/max.",
                    )
                )
            else:
                _reject_unknown_fields(issues, infill, {"target", "min", "max"}, f"{path}.strength.infill_percent")

                def infill_number(field: str, required: bool) -> float | None:
                    value = infill.get(field)
                    if value is None:
                        if required:
                            issues.append(
                                ValidationIssue(
                                    "printable-part-invalid-strength",
                                    f"{path}.strength.infill_percent.{field}",
                                    f"infill_percent.{field} is required.",
                                )
                            )
                        return None
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or not 0 <= float(value) <= 100:
                        issues.append(
                            ValidationIssue(
                                "printable-part-invalid-strength",
                                f"{path}.strength.infill_percent.{field}",
                                f"infill_percent.{field} must be a number between 0 and 100.",
                            )
                        )
                        return None
                    return float(value)

                target = infill_number("target", required=True)
                minimum = infill_number("min", required=False)
                maximum = infill_number("max", required=False)
                if target is not None and minimum is not None and minimum > target:
                    issues.append(
                        ValidationIssue(
                            "printable-part-invalid-strength",
                            f"{path}.strength.infill_percent.min",
                            "infill_percent.min must not exceed the target.",
                        )
                    )
                if target is not None and maximum is not None and maximum < target:
                    issues.append(
                        ValidationIssue(
                            "printable-part-invalid-strength",
                            f"{path}.strength.infill_percent.max",
                            "infill_percent.max must not be below the target.",
                        )
                    )

        protected_features = raw_part.get("protected_features")
        if not isinstance(protected_features, list):
            issues.append(
                ValidationIssue(
                    "printable-part-invalid-protected-features",
                    f"{path}.protected_features",
                    "protected_features must be a list (it may be empty).",
                )
            )
        else:
            for feature_index, raw_feature in enumerate(protected_features):
                feature_path = f"{path}.protected_features[{feature_index}]"
                if not isinstance(raw_feature, dict):
                    issues.append(
                        ValidationIssue(
                            "printable-part-invalid-protected-features",
                            feature_path,
                            "protected_features entries must be objects.",
                        )
                    )
                    continue
                _reject_unknown_fields(issues, raw_feature, {"kind", "description"}, feature_path)
                if not _in_closed_set(raw_feature.get("kind"), PROTECTED_FEATURE_KINDS):
                    issues.append(
                        ValidationIssue(
                            "printable-part-invalid-protected-features",
                            f"{feature_path}.kind",
                            f"Protected-feature kind must be one of {', '.join(sorted(PROTECTED_FEATURE_KINDS))}.",
                        )
                    )
                description = raw_feature.get("description")
                if not isinstance(description, str) or not description.strip():
                    issues.append(
                        ValidationIssue(
                            "printable-part-invalid-protected-features",
                            f"{feature_path}.description",
                            "Protected features need a plain-language description.",
                        )
                    )

        material = raw_part.get("material")
        if not isinstance(material, dict):
            issues.append(
                ValidationIssue(
                    "printable-part-invalid-material",
                    f"{path}.material",
                    "material must be an object with an assumption and status.",
                )
            )
        else:
            _reject_unknown_fields(issues, material, {"assumption", "source_id", "status"}, f"{path}.material")
            assumption = material.get("assumption")
            if not isinstance(assumption, str) or not assumption.strip():
                issues.append(
                    ValidationIssue(
                        "printable-part-invalid-material",
                        f"{path}.material.assumption",
                        "material.assumption must be a non-empty string.",
                    )
                )
            if not _in_closed_set(material.get("status"), MATERIAL_STATUSES):
                issues.append(
                    ValidationIssue(
                        "printable-part-invalid-material",
                        f"{path}.material.status",
                        f"material.status must be one of {', '.join(sorted(MATERIAL_STATUSES))}.",
                    )
                )
            material_source = material.get("source_id")
            if material_source is not None:
                if not isinstance(material_source, str) or not valid_name.fullmatch(material_source):
                    issues.append(
                        ValidationIssue(
                            "printable-part-invalid-material",
                            f"{path}.material.source_id",
                            "material.source_id must begin with a letter and contain only letters, digits, and underscores.",
                        )
                    )
                elif material_source not in source_map:
                    issues.append(
                        ValidationIssue(
                            "printable-part-invalid-material",
                            f"{path}.material.source_id",
                            f"material.source_id references unknown source {material_source!r}.",
                        )
                    )

    for duplicate in sorted(_duplicates(part_ids)):
        issues.append(
            ValidationIssue(
                "printable-part-duplicate-id",
                "printable_parts",
                f"Printable-part id {duplicate!r} is duplicated.",
            )
        )
    for duplicate in sorted(_duplicates(part_paths)):
        issues.append(
            ValidationIssue(
                "printable-part-duplicate-path",
                "printable_parts",
                f"Printable-part path {duplicate!r} is duplicated.",
            )
        )
    if expected_print_part_paths is not None and set(part_paths) != set(expected_print_part_paths):
        missing = sorted(set(expected_print_part_paths) - set(part_paths))
        extra = sorted(set(part_paths) - set(expected_print_part_paths))
        issues.append(
            ValidationIssue(
                "printable-parts-mismatch-expected",
                "printable_parts",
                "printable_parts paths must exactly match verification.expected_print_parts"
                + (f"; missing {', '.join(missing)}" if missing else "")
                + (f"; unexpected {', '.join(extra)}" if extra else "")
                + ".",
            )
        )

