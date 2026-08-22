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

PRINT_INTENTS = {"fast-structural", "fine-detail", "enclosure"}

# Override keys added by the PrusaSlicer optimization loop. Each entry maps an
# override key to the declared printable-part field that justifies emitting it;
# an override whose justifying field is absent or invalid fails closed (see
# validate_extended_override_value). These constants are the shared vocabulary:
# prusaslicer_project.ALLOWED_OVERRIDE_KEYS is wired from them so the validator
# and the emitter cannot drift apart.
PRINT_INTENT_OVERRIDE_KEYS = {
    "speed": "print_intent",
    "layer_height": "print_intent",
    "seam_position": "print_intent",
    "brim_width": "print_intent",
}
SUPPORT_STYLE_OVERRIDE_KEY = "support_material_style"
SUPPORT_STYLE_JUSTIFYING_FIELD = "support_policy"
# Styles only mean something when supports are actually emitted; 'none' and
# 'explicit-regions' do not justify a style override.
SUPPORT_STYLE_JUSTIFYING_POLICIES = {"build-plate-only", "everywhere"}

SUPPORT_MATERIAL_STYLES = {"organic", "grid", "snug"}
# organic/grid/snug are already PrusaSlicer's own support_material_style
# values; the table exists so a rename on either side is a visible edit.
SUPPORT_MATERIAL_STYLE_TRANSLATIONS = {style: style for style in sorted(SUPPORT_MATERIAL_STYLES)}

SEAM_POSITION_VALUES = {"aligned", "nearest", "hidden", "rear"}

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
    "print_intent",
}

# The optional fields; everything else in PRINTABLE_PART_FIELDS is required and
# is pinned against the schema's `$defs.printable_part.required` array by
# test_schema_json_stays_in_lockstep_with_validator_constants.
PRINTABLE_PART_OPTIONAL_FIELDS = {
    "body_name",
    "quantity",
    "support_regions",
    "print_intent",
}

PRINTABLE_PART_REQUIRED_FIELDS = PRINTABLE_PART_FIELDS - PRINTABLE_PART_OPTIONAL_FIELDS


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


def validate_extended_override_value(
    key: str, value: Any, part_path: str, intent: dict[str, Any]
) -> None:
    """Fail closed when an extended override lacks justification or is malformed.

    Every key in the extended vocabulary traces to one declared printable-part
    field (the tables above name it). An override whose justifying field is
    absent, invalid, or unable to express the key raises a named error instead
    of being silently applied -- the same doctrine as the original five-key
    path, one level deeper.
    """
    prefix = f"Printable part {part_path!r}"
    justifying_field = PRINT_INTENT_OVERRIDE_KEYS.get(key)
    if justifying_field is None:
        if key != SUPPORT_STYLE_OVERRIDE_KEY:
            raise ValueError(
                f"{prefix} carries override {key!r}, which is not part of the extended "
                f"justified vocabulary ({', '.join(sorted(PRINT_INTENT_OVERRIDE_KEYS))}, "
                f"{SUPPORT_STYLE_OVERRIDE_KEY})."
            )
        declared = intent.get(SUPPORT_STYLE_JUSTIFYING_FIELD)
        if declared not in SUPPORT_STYLE_JUSTIFYING_POLICIES:
            raise ValueError(
                f"{prefix} declares override {SUPPORT_STYLE_OVERRIDE_KEY!r}, which requires "
                f"{SUPPORT_STYLE_JUSTIFYING_FIELD} to be one of "
                f"{', '.join(sorted(SUPPORT_STYLE_JUSTIFYING_POLICIES))}; declared value is "
                f"{declared!r}. Refusing an unjustified override."
            )
        if not _in_closed_set(value, SUPPORT_MATERIAL_STYLES):
            raise ValueError(
                f"{prefix} declares support_material_style {value!r}; expected one of "
                f"{', '.join(sorted(SUPPORT_MATERIAL_STYLES))}."
            )
        return

    declared = intent.get(justifying_field)
    if not _in_closed_set(declared, PRINT_INTENTS):
        raise ValueError(
            f"{prefix} declares override {key!r}, which requires a valid print_intent "
            f"(one of {', '.join(sorted(PRINT_INTENTS))}); declared value is {declared!r}. "
            "Refusing an unjustified override."
        )

    if key == "seam_position":
        if not _in_closed_set(value, SEAM_POSITION_VALUES):
            raise ValueError(
                f"{prefix} declares seam_position {value!r}; expected one of "
                f"{', '.join(sorted(SEAM_POSITION_VALUES))}."
            )
        return

    try:
        number = float(value)
    except (TypeError, ValueError):
        number = math.nan
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(number)
        or (number < 0 if key == "brim_width" else number <= 0)
    ):
        qualifier = "a non-negative" if key == "brim_width" else "a positive"
        raise ValueError(
            f"{prefix} declares {key} {value!r}; expected {qualifier} finite number."
        )


def _validate_printable_parts(
    issues: list[ValidationIssue],
    printable_parts: Any,
    component_path_set: set[str],
    expected_print_part_paths: list[str] | None,
    source_map: dict[str, dict[str, Any]],
) -> None:
    # Imported here, not at module scope: manifest.py imports this module to
    # re-export the enums, so a top-level import would be circular.
    from .manifest import (
        ValidationIssue,
        _duplicates,
        _reject_claim_text,
        _reject_unknown_fields,
        _VALID_NAME_RE,
        source_backs_claim,
        source_confidence,
    )

    if printable_parts is None:
        # The section stays optional for back-compat: a manifest may decline to
        # declare print intent. What it may not do is decline *silently* while
        # verification promises printed parts, because an absent section is
        # otherwise indistinguishable from a satisfied one. Recorded as a
        # warning, so it is surfaced without rejecting manifests that predate
        # the section.
        if expected_print_part_paths:
            issues.append(
                ValidationIssue(
                    "printable-parts-not-declared",
                    "printable_parts",
                    "verification.expected_print_parts promises "
                    f"{', '.join(sorted(expected_print_part_paths))} but the manifest declares no printable_parts, "
                    "so no build orientation, support policy, material status, or strength intent is recorded "
                    "for them. Print-evidence completeness is undeclared, not satisfied.",
                    severity="warning",
                )
            )
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
        for field in sorted(PRINTABLE_PART_REQUIRED_FIELDS - set(raw_part)):
            issues.append(
                ValidationIssue(
                    "printable-part-field-required",
                    f"{path}.{field}",
                    f"Printable-part field {field!r} is required.",
                )
            )

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
            _reject_claim_text(issues, rationale, f"{path}.orientation.rationale")
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
                _reject_claim_text(issues, description, f"{region_path}.description")
        elif "support_regions" in raw_part:
            issues.append(
                ValidationIssue(
                    "printable-part-invalid-support-policy",
                    f"{path}.support_regions",
                    "support_regions is only allowed when support_policy is 'explicit-regions'.",
                )
            )

        print_intent = raw_part.get("print_intent")
        if print_intent is not None:
            if not _in_closed_set(print_intent, PRINT_INTENTS):
                issues.append(
                    ValidationIssue(
                        "printable-part-invalid-print-intent",
                        f"{path}.print_intent",
                        f"print_intent must be one of {', '.join(sorted(PRINT_INTENTS))}.",
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
                _reject_claim_text(issues, description, f"{feature_path}.description")

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
            _reject_claim_text(issues, assumption, f"{path}.material.assumption")
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
            # coupon_verified is a physical claim: a coupon was printed on this
            # material and measured. Same rule as everywhere else -- the claim
            # may not be more confident than the source it cites.
            if material.get("status") == "coupon_verified":
                if material_source is None:
                    issues.append(
                        ValidationIssue(
                            "printable-part-invalid-material",
                            f"{path}.material.source_id",
                            "material.status 'coupon_verified' requires a material.source_id recording the "
                            "coupon evidence.",
                        )
                    )
                elif isinstance(material_source, str) and material_source in source_map:
                    source = source_map[material_source]
                    if not source_backs_claim(source, "coupon_verified"):
                        issues.append(
                            ValidationIssue(
                                "printable-part-invalid-material",
                                f"{path}.material.status",
                                f"material.status 'coupon_verified' cites source {material_source!r} "
                                f"(kind {source.get('kind')!r}, confidence {source.get('confidence')!r}), which "
                                f"carries only {source_confidence(source)!r} evidence.",
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
