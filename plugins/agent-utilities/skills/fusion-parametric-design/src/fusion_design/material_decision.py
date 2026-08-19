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
    "nozzle",
    "drying",
}

# Filled and hygroscopic families are not drop-in filaments: carbon and glass
# fill chew through a brass nozzle, and PA absorbs enough water from the room to
# change what actually prints. Both must be declared, not assumed away.
FILLED_FAMILIES = {family for family in MATERIAL_FAMILIES if family.endswith("_CF")} | {"PA"}

# The machine constraints are closed enums, not prose. A safety gate read out of
# free text is satisfiable by text that denies the constraint ("No hardened
# nozzle here") and by text that is about something else entirely ("PEI steel
# sheet", "dry-fit the lid"), because a string sweep has no negation and no
# scope. printer_requirements survives as human prose and discharges nothing.
NOZZLE_MATERIALS = {"brass", "hardened_steel", "ruby", "tungsten_carbide"}
ABRASION_RESISTANT_NOZZLES = NOZZLE_MATERIALS - {"brass"}
DRYING_STATES = {"required", "done", "not_needed"}

# R4: "TPU" alone is not a decision — the rationale has to say how hard or how
# flexible the part needs to be. The hardness route needs an actual figure next
# to the word; "the offshore supplier stocks it" is not a durometer.
_TPU_HARDNESS_RE = re.compile(
    r"(?<!\w)(?:shore|durometer|hardness)\w*[^.;]{0,24}\d|\d[^.;]{0,24}(?<!\w)(?:shore|durometer|hardness)",
    re.IGNORECASE,
)
_TPU_FLEX_TERMS = ("flex", "flexible", "elastic", "elastomeric")


def _text(value: Any) -> str:
    """Normalized string form; every comparison below runs on this."""
    return value.strip() if isinstance(value, str) else ""


def _normalized(value: str) -> str:
    """Lowercase, with hyphens folded onto the enum's own underscore.

    "PA-CF" and "PA_CF" have to normalize identically, and the joiner has to stay
    a ``\\w`` character: collapsing it to a space would let the word-run match in
    :func:`_names` find the unfilled family ``PA`` inside the filled ``PA_CF``,
    which is exactly the mismatch R6 exists to catch.
    """
    return re.sub(r"[^a-z0-9_]+", " ", value.lower().replace("-", "_")).strip()


def _needle_pattern(normalized_needle: str) -> str:
    """Regex for the needle where each segment may carry a numeric grade suffix.

    ``PA12`` and ``PA6`` are how the industry spells polyamide grades, so family
    ``PA`` names them; ``pa\\d*`` still refuses ``pa_cf``, whose next character is
    a ``\\w``.
    """
    parts = re.split(r"([_ ]+)", normalized_needle)
    return "".join(
        part if index % 2 else re.escape(part) + r"\d*" for index, part in enumerate(parts)
    )


def _names(haystack: str, needle: str) -> bool:
    """True when ``needle`` appears in ``haystack`` as a whole word run.

    Word-run matching, not bare containment: family ``PA`` must not be satisfied
    by an assumption reading "opaque PETG".
    """
    normalized_needle = _normalized(needle)
    if not normalized_needle:
        return False
    pattern = rf"(?<!\w){_needle_pattern(normalized_needle)}(?!\w)"
    return re.search(pattern, _normalized(haystack)) is not None


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

    # Closed-enum and identifier fields are tested raw, never stripped: the value
    # that leaves in Manifest.material_decision and in the export index is the
    # raw one, so validating a stripped copy would bless "  PETG\n" as PETG and
    # ship a family the published schema's enum does not contain.
    raw_family = decision.get("family")
    family = raw_family if isinstance(raw_family, str) else ""
    if not _in_closed_set(raw_family, MATERIAL_FAMILIES):
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

    raw_source_id = decision.get("source_id")
    source_id = raw_source_id if isinstance(raw_source_id, str) else ""
    if not source_id or not _VALID_NAME_RE.fullmatch(source_id):
        source_id = ""
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

    raw_confidence = decision.get("confidence")
    confidence = raw_confidence if isinstance(raw_confidence, str) else ""
    if not _in_closed_set(raw_confidence, SOURCE_CONFIDENCES):
        issues.append(
            ValidationIssue(
                "material-decision-unknown-confidence",
                "material_decision.confidence",
                f"confidence must be one of {', '.join(sorted(SOURCE_CONFIDENCES))}.",
            )
        )
        confidence = ""

    # A coupon that is never printed cannot settle anything, so component_tree
    # membership is not enough: reference geometry, keep-outs and bare container
    # nodes all live there. A manifest that declares no printable_parts at all is
    # the pre-printable-parts shape and falls back to the component tree.
    if isinstance(printable_parts, list):
        coupon_scope = {
            part["path"]
            for part in printable_parts
            if isinstance(part, dict) and isinstance(part.get("path"), str)
        }
        coupon_scope_name = "a declared printable part"
    else:
        coupon_scope = component_path_set
        coupon_scope_name = "declared in component_tree"
    raw_coupon = decision.get("coupon_component")
    coupon = raw_coupon if isinstance(raw_coupon, str) else ""
    if raw_coupon is not None and coupon not in coupon_scope:
        issues.append(
            ValidationIssue(
                "material-decision-unknown-coupon",
                "material_decision.coupon_component",
                f"coupon_component {raw_coupon!r} is not {coupon_scope_name}; "
                "a coupon that is never printed cannot settle a material-dependent fit.",
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
    if raw_requirements is not None and not _text(raw_requirements):
        issues.append(
            ValidationIssue(
                "material-decision-invalid-printer-requirements",
                "material_decision.printer_requirements",
                "printer_requirements, when present, must be a non-empty string.",
            )
        )

    raw_nozzle = decision.get("nozzle")
    nozzle = raw_nozzle if _in_closed_set(raw_nozzle, NOZZLE_MATERIALS) else ""
    if raw_nozzle is not None and not nozzle:
        issues.append(
            ValidationIssue(
                "material-decision-unknown-nozzle",
                "material_decision.nozzle",
                f"nozzle must be one of {', '.join(sorted(NOZZLE_MATERIALS))}, "
                "or null when the machine is unconstrained.",
            )
        )

    raw_drying = decision.get("drying")
    drying = raw_drying if _in_closed_set(raw_drying, DRYING_STATES) else ""
    if raw_drying is not None and not drying:
        issues.append(
            ValidationIssue(
                "material-decision-unknown-drying",
                "material_decision.drying",
                f"drying must be one of {', '.join(sorted(DRYING_STATES))}, "
                "or null when the family does not need it.",
            )
        )

    if family in FILLED_FAMILIES:
        # Only the structured fields discharge this. An unresolved risk is
        # advisory here — "Lid colour not chosen yet." is a risk, and it says
        # nothing about the nozzle that is about to wear open.
        guarded = nozzle in ABRASION_RESISTANT_NOZZLES
        if guarded and family.startswith("PA"):
            guarded = drying in {"required", "done"}
        if not guarded:
            issues.append(
                ValidationIssue(
                    "material-decision-filled-material-unguarded",
                    "material_decision.nozzle",
                    f"Family {family!r} requires nozzle to be one of "
                    f"{', '.join(sorted(ABRASION_RESISTANT_NOZZLES))}"
                    + (" and drying to be 'required' or 'done'" if family.startswith("PA") else "")
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
        states_hardness = _TPU_HARDNESS_RE.search(rationale) is not None
        states_flex = any(_names(rationale, term) for term in _TPU_FLEX_TERMS)
        if not states_hardness and not states_flex:
            issues.append(
                ValidationIssue(
                    "material-decision-tpu-underspecified",
                    "material_decision.rationale",
                    "A TPU rationale must state the needed hardness as a Shore/durometer figure, "
                    "or the flex behavior the part needs.",
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

    # A decision may not claim more than the source it rests on. Mirrors
    # scan-parameter-not-provisional in manifest.py, which refuses the same move
    # for a critical parameter cited to a scan.
    source = source_map.get(source_id)
    if (
        isinstance(source, dict)
        and source.get("confidence") == "provisional"
        and confidence
        and confidence != "provisional"
        and not (coupon and risks)
    ):
        issues.append(
            ValidationIssue(
                "material-decision-outranks-source",
                "material_decision.confidence",
                f"confidence {confidence!r} claims more than source {source_id!r}, which is provisional. "
                "Keep the decision provisional, or bind the stronger claim to both a coupon_component "
                "and an unresolved risk.",
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
    # Families the decision itself names, so a formulation like "Fiberon PET-CF17"
    # under the OTHER sentinel does not read as naming a foreign family. OTHER is
    # never foreign: it is a sentinel, not a chemistry.
    decided_names = {"OTHER"} | {
        member
        for member in MATERIAL_FAMILIES
        if _names(family, member) or (formulation and _names(formulation, member))
    }
    for index, part in enumerate(printable_parts):
        if not isinstance(part, dict):
            continue
        material = part.get("material")
        if not isinstance(material, dict):
            continue
        assumption = _text(material.get("assumption"))
        if not assumption:
            # A missing or non-string assumption is already reported as
            # printable-part-invalid-material; a mismatch on top of it would be
            # noise, not a second finding.
            continue
        # Bidirectional on the formulation: R6 asks that the part not name a
        # *different* material, not that it repeat the decision verbatim, so a
        # shortened product name ("PET-CF17" under "Fiberon PET-CF17") is a match.
        # The family route is skipped for OTHER, which word-matches plain English
        # ("Same as the other lid part."); OTHER always has a formulation to match.
        names_decision = (
            (family != "OTHER" and _names(assumption, family))
            or _names(assumption, formulation)
            or _names(formulation, assumption)
        )
        if not names_decision:
            issues.append(
                ValidationIssue(
                    "material-decision-part-mismatch",
                    f"printable_parts[{index}].material.assumption",
                    f"Part material assumption {assumption!r} names neither the decided family {family!r} "
                    f"nor the formulation {formulation!r}.",
                )
            )
            continue
        # Naming the decision is not enough — it has to be the only material
        # named, or "PETG for now, ABS if it runs hot" survives as intent.
        foreign = sorted(
            member for member in MATERIAL_FAMILIES - decided_names if _names(assumption, member)
        )
        if foreign:
            issues.append(
                ValidationIssue(
                    "material-decision-part-mismatch",
                    f"printable_parts[{index}].material.assumption",
                    f"Part material assumption {assumption!r} also names {', '.join(foreign)}, "
                    "which the project did not decide; a part assumes one material, not a choice.",
                )
            )
