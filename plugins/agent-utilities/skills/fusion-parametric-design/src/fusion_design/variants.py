from __future__ import annotations

from typing import TYPE_CHECKING, Any

# The shared closed-world membership test lives with the printable-part
# validator; importing it keeps one implementation rather than a second copy
# that could stop surviving unhashable JSON values.
from .printable_parts import _in_closed_set

if TYPE_CHECKING:
    from .manifest import ValidationIssue


VARIANT_FIELDS = {"id", "description", "parameters", "configuration"}

VARIANT_SOURCES = {"parameters", "configuration"}

# A matrix runs one transaction per step against a live Fusion session, so the
# family size is bounded by declaration rather than by patience.
MAXIMUM_VARIANTS = 16


def variant_id(raw_variant: Any) -> str:
    """The variant's identity, normalized once for validator and runner alike."""
    value = raw_variant.get("id") if isinstance(raw_variant, dict) else None
    return value.strip() if isinstance(value, str) else ""


def variant_configuration(raw_variant: Any) -> str:
    """The named Fusion configuration a variant activates, normalized."""
    value = raw_variant.get("configuration") if isinstance(raw_variant, dict) else None
    return value.strip() if isinstance(value, str) else ""


def variant_parameter_overrides(raw_variant: Any) -> dict[str, str]:
    """Declared parameter overrides, keyed exactly as the validator checks them.

    Both sides strip: a validator that normalized while the runner keyed on the
    raw text would silently drop a declared override.
    """
    raw = raw_variant.get("parameters") if isinstance(raw_variant, dict) else None
    if not isinstance(raw, dict):
        return {}
    overrides: dict[str, str] = {}
    for name, expression in raw.items():
        if isinstance(name, str) and isinstance(expression, str):
            overrides[name.strip()] = expression.strip()
    return overrides


def _validate_variant_parameters(
    issues: list[ValidationIssue],
    raw_variant: dict[str, Any],
    path: str,
    label: str,
    declared_parameter_names: set[str],
) -> None:
    from .manifest import ValidationIssue, _duplicates

    raw_parameters = raw_variant.get("parameters")
    if not isinstance(raw_parameters, dict):
        issues.append(
            ValidationIssue(
                "variant-parameters-must-be-object",
                f"{path}.parameters",
                "variant parameters must be an object mapping declared parameter names to Fusion expressions.",
            )
        )
        return
    if not raw_parameters:
        issues.append(
            ValidationIssue(
                "variant-source-missing",
                f"{path}.parameters",
                f"Variant {label!r} overrides no parameter; a parameter-set variant must change at least one declared parameter.",
            )
        )
        return

    normalized_names: list[str] = []
    for name, expression in sorted(raw_parameters.items(), key=lambda item: str(item[0])):
        field_path = f"{path}.parameters.{name}"
        if not isinstance(name, str) or not name.strip():
            issues.append(
                ValidationIssue(
                    "variant-unknown-parameter",
                    field_path,
                    "Variant parameter names must be non-empty strings.",
                )
            )
            continue
        normalized_name = name.strip()
        normalized_names.append(normalized_name)
        if not _in_closed_set(normalized_name, declared_parameter_names):
            issues.append(
                ValidationIssue(
                    "variant-unknown-parameter",
                    field_path,
                    f"Variant {label!r} names parameter {normalized_name!r} that the manifest never declares.",
                )
            )
        if not isinstance(expression, str) or not expression.strip():
            issues.append(
                ValidationIssue(
                    "variant-invalid-expression",
                    field_path,
                    f"Variant {label!r} must give parameter {normalized_name!r} a non-empty Fusion expression.",
                )
            )

    for duplicate in sorted(_duplicates(normalized_names)):
        issues.append(
            ValidationIssue(
                "variant-duplicate-parameter",
                f"{path}.parameters",
                f"Variant {label!r} names parameter {duplicate!r} more than once; only one override would survive.",
            )
        )


def _validate_variants(
    issues: list[ValidationIssue],
    variants: Any,
    declared_parameter_names: set[str],
) -> None:
    # Imported here, not at module scope: manifest.py imports this module to
    # re-export the variant constants, so a top-level import would be circular.
    from .manifest import ValidationIssue, _duplicates, _reject_unknown_fields, _VALID_NAME_RE

    if variants is None:
        return
    if not isinstance(variants, list):
        issues.append(
            ValidationIssue(
                "variants-must-be-list",
                "variants",
                "variants must be a list of variant objects.",
            )
        )
        return
    if len(variants) > MAXIMUM_VARIANTS:
        issues.append(
            ValidationIssue(
                "variants-exceed-maximum",
                "variants",
                f"A variant matrix runs against a live Fusion session; at most {MAXIMUM_VARIANTS} variants may be declared, found {len(variants)}.",
            )
        )

    identities: list[str] = []
    for index, raw_variant in enumerate(variants):
        path = f"variants[{index}]"
        if not isinstance(raw_variant, dict):
            issues.append(ValidationIssue("variant-must-be-object", path, "Variant entries must be objects."))
            continue
        _reject_unknown_fields(issues, raw_variant, VARIANT_FIELDS, path)

        identity = variant_id(raw_variant)
        if not identity:
            issues.append(
                ValidationIssue(
                    "variant-field-required",
                    f"{path}.id",
                    "Variant field 'id' must be a non-empty string.",
                )
            )
        elif not _VALID_NAME_RE.fullmatch(identity):
            issues.append(
                ValidationIssue(
                    "invalid-variant-id",
                    f"{path}.id",
                    "A variant id must begin with a letter and contain only letters, digits, and underscores.",
                )
            )
        else:
            identities.append(identity)
        label = identity or f"variants[{index}]"

        description = raw_variant.get("description")
        if not isinstance(description, str) or not description.strip():
            issues.append(
                ValidationIssue(
                    "variant-field-required",
                    f"{path}.description",
                    "Variant field 'description' must be a non-empty string.",
                )
            )

        declared_sources = sorted(field for field in VARIANT_SOURCES if field in raw_variant)
        if len(declared_sources) > 1:
            issues.append(
                ValidationIssue(
                    "variant-source-ambiguous",
                    path,
                    f"Variant {label!r} declares both {' and '.join(declared_sources)}; a variant has exactly one explicit source.",
                )
            )
        elif not declared_sources:
            issues.append(
                ValidationIssue(
                    "variant-source-missing",
                    path,
                    f"Variant {label!r} declares neither 'parameters' nor 'configuration'; inventing a variant is an explicit non-goal.",
                )
            )

        if "parameters" in raw_variant:
            _validate_variant_parameters(issues, raw_variant, path, label, declared_parameter_names)
        if "configuration" in raw_variant and not variant_configuration(raw_variant):
            issues.append(
                ValidationIssue(
                    "variant-invalid-configuration",
                    f"{path}.configuration",
                    f"Variant {label!r} must name a non-empty Fusion configuration.",
                )
            )

    for duplicate in sorted(_duplicates(identities)):
        issues.append(
            ValidationIssue(
                "variant-duplicate-id",
                "variants",
                f"Variant id {duplicate!r} is duplicated.",
            )
        )
