from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

# printable_parts does not import manifest at module scope, so importing the
# shared closed-set helper from it here stays free of the import cycle.
from .printable_parts import _in_closed_set

if TYPE_CHECKING:
    from .manifest import ValidationIssue


MATERIAL_FAMILIES = {
    "PLA",
    "PLA_SILK",
    "PETG",
    "TPU",
    "ASA",
    "ABS",
    "PC",
    "PC_CF",
    "PA",
    "PA_CF",
    "PET_CF",
    "OTHER",
}

MATERIAL_DECISION_FIELDS = {
    "family",
    "formulation",
    "source_id",
    "confidence",
    "coupon_component",
    "rationale",
    "unresolved_risks",
    "printer_requirements",
}

# Filled and hygroscopic families are not drop-in filaments: carbon and glass
# fill chew through a brass nozzle, and PA absorbs enough water from the room to
# change what actually prints. Both must be declared, not assumed away.
FILLED_FAMILIES = {family for family in MATERIAL_FAMILIES if family.endswith("_CF")} | {"PA"}

_ABRASION_TERMS = ("harden", "abrasion", "ruby", "steel", "tungsten", "carbide")
_DRYING_TERMS = ("dry", "desiccant")
# R4: "TPU" alone is not a decision — the rationale has to say how hard or how
# flexible the part needs to be.
_TPU_RATIONALE_TERMS = ("shore", "durometer", "hardness", "flex", "elastic")


def _text(value: Any) -> str:
    """Normalized string form; every comparison below runs on this."""
    return value.strip() if isinstance(value, str) else ""


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _names(haystack: str, needle: str) -> bool:
    """True when ``needle`` appears in ``haystack`` as a whole word run.

    Word-run matching, not bare containment: family ``PA`` must not be satisfied
    by an assumption reading "opaque PETG".
    """
    normalized_needle = _normalized(needle)
    if not normalized_needle:
        return False
    pattern = rf"(?<!\w){re.escape(normalized_needle)}(?!\w)"
    return re.search(pattern, _normalized(haystack)) is not None


def _mentions(value: str, terms: tuple[str, ...]) -> bool:
    lowered = value.lower()
    return any(term in lowered for term in terms)


def _validate_material_decision(
    issues: list[ValidationIssue],
    decision: Any,
    component_path_set: set[str],
    source_map: dict[str, dict[str, Any]],
    printable_parts: Any,
) -> None:
    # Imported here, not at module scope: manifest.py imports this module to
    # re-export the enums, so a top-level import would be circular.
    from .manifest import SOURCE_CONFIDENCES, ValidationIssue, _reject_unknown_fields, _VALID_NAME_RE

    if decision is None:
        return
    if not isinstance(decision, dict):
        issues.append(
            ValidationIssue(
                "material-decision-must-be-object",
                "material_decision",
                "material_decision must be an object describing the chosen material.",
            )
        )
        return
    _reject_unknown_fields(issues, decision, MATERIAL_DECISION_FIELDS, "material_decision")

    raw_family = decision.get("family")
    family = _text(raw_family)
    if not _in_closed_set(family, MATERIAL_FAMILIES):
        issues.append(
            ValidationIssue(
                "material-decision-unknown-family",
                "material_decision.family",
                f"family must be one of {', '.join(sorted(MATERIAL_FAMILIES))}.",
            )
        )
        family = ""

    raw_formulation = decision.get("formulation")
    formulation = _text(raw_formulation)
    if raw_formulation is not None and not formulation:
        issues.append(
            ValidationIssue(
                "material-decision-invalid-formulation",
                "material_decision.formulation",
                "formulation must be a non-empty string naming the specific product, or null when only the family is settled.",
            )
        )
    if family == "OTHER" and not formulation:
        issues.append(
            ValidationIssue(
                "material-decision-invalid-formulation",
                "material_decision.formulation",
                "family 'OTHER' requires a formulation; an unnamed material has no properties to reason from.",
            )
        )

    source_id = _text(decision.get("source_id"))
    if not source_id or not _VALID_NAME_RE.fullmatch(source_id):
        issues.append(
            ValidationIssue(
                "material-decision-unknown-source",
                "material_decision.source_id",
                "source_id must begin with a letter and contain only letters, digits, and underscores.",
            )
        )
    elif source_id not in source_map:
        issues.append(
            ValidationIssue(
                "material-decision-unknown-source",
                "material_decision.source_id",
                f"material_decision references unknown source {source_id!r}.",
            )
        )

    confidence = _text(decision.get("confidence"))
    if not _in_closed_set(confidence, SOURCE_CONFIDENCES):
        issues.append(
            ValidationIssue(
                "material-decision-unknown-confidence",
                "material_decision.confidence",
                f"confidence must be one of {', '.join(sorted(SOURCE_CONFIDENCES))}.",
            )
        )
        confidence = ""

    raw_coupon = decision.get("coupon_component")
    coupon = _text(raw_coupon)
    if raw_coupon is not None and (not coupon or coupon not in component_path_set):
        issues.append(
            ValidationIssue(
                "material-decision-unknown-coupon",
                "material_decision.coupon_component",
                f"coupon_component {raw_coupon!r} is not declared in component_tree.",
            )
        )
        coupon = ""

    rationale = _text(decision.get("rationale"))
    if not rationale:
        issues.append(
            ValidationIssue(
                "material-decision-missing-rationale",
                "material_decision.rationale",
                "rationale must be a non-empty string saying why this material was chosen.",
            )
        )

    raw_risks = decision.get("unresolved_risks")
    risks: list[str] = []
    if not isinstance(raw_risks, list):
        issues.append(
            ValidationIssue(
                "material-decision-invalid-risks",
                "material_decision.unresolved_risks",
                "unresolved_risks must be a list of strings (it may be empty).",
            )
        )
    else:
        for index, raw_risk in enumerate(raw_risks):
            risk = _text(raw_risk)
            if not risk:
                issues.append(
                    ValidationIssue(
                        "material-decision-invalid-risks",
                        f"material_decision.unresolved_risks[{index}]",
                        "Each unresolved risk must be a non-empty string.",
                    )
                )
                continue
            risks.append(risk)

    raw_requirements = decision.get("printer_requirements")
    requirements = _text(raw_requirements)
    if raw_requirements is not None and not requirements:
        issues.append(
            ValidationIssue(
                "material-decision-invalid-printer-requirements",
                "material_decision.printer_requirements",
                "printer_requirements, when present, must be a non-empty string.",
            )
        )

    if family in FILLED_FAMILIES:
        # Either route is acceptable: an open risk keeps the decision honest, and
        # a printer_requirements string discharges it only when it actually names
        # the abrasion-resistant nozzle (plus drying, for the PA families).
        guarded_by_requirements = _mentions(requirements, ("nozzle",)) and _mentions(
            requirements, _ABRASION_TERMS
        )
        if guarded_by_requirements and family.startswith("PA"):
            guarded_by_requirements = _mentions(requirements, _DRYING_TERMS)
        if not risks and not guarded_by_requirements:
            issues.append(
                ValidationIssue(
                    "material-decision-filled-material-unguarded",
                    "material_decision.printer_requirements",
                    f"Family {family!r} needs at least one unresolved risk or printer_requirements naming an "
                    "abrasion-resistant nozzle"
                    + (" and drying" if family.startswith("PA") else "")
                    + "; filled and hygroscopic filaments are not drop-in.",
                )
            )

    if family == "TPU":
        if not formulation:
            issues.append(
                ValidationIssue(
                    "material-decision-tpu-underspecified",
                    "material_decision.formulation",
                    "family 'TPU' requires a formulation; 'TPU' alone is not a material decision.",
                )
            )
        if not _mentions(rationale, _TPU_RATIONALE_TERMS):
            issues.append(
                ValidationIssue(
                    "material-decision-tpu-underspecified",
                    "material_decision.rationale",
                    "A TPU rationale must state the needed hardness (Shore/durometer) or flex behavior.",
                )
            )

    if confidence == "provisional" and not coupon and not risks:
        issues.append(
            ValidationIssue(
                "material-decision-provisional-unbound",
                "material_decision",
                "A provisional material decision must name a coupon_component or record at least one unresolved risk.",
            )
        )

    _validate_part_material_consistency(issues, printable_parts, family, formulation)


def _validate_part_material_consistency(
    issues: list[ValidationIssue],
    printable_parts: Any,
    family: str,
    formulation: str,
) -> None:
    """R6: a part may not silently assume a different material than the project decided."""
    from .manifest import ValidationIssue

    if not isinstance(printable_parts, list) or (not family and not formulation):
        return
    for index, part in enumerate(printable_parts):
        if not isinstance(part, dict):
            continue
        material = part.get("material")
        if not isinstance(material, dict):
            continue
        assumption = _text(material.get("assumption"))
        if not assumption:
            continue
        if _names(assumption, family) or _names(assumption, formulation):
            continue
        issues.append(
            ValidationIssue(
                "material-decision-part-mismatch",
                f"printable_parts[{index}].material.assumption",
                f"Part material assumption {assumption!r} names neither the decided family {family!r} "
                f"nor the formulation {formulation!r}.",
            )
        )
