"""Evidence labels for enclosure-feature dimensions; no material database."""

from enum import Enum


class EvidenceClass(str, Enum):
    GEOMETRIC_INVARIANT = "geometric-invariant"
    FUSION_API_CONSTRAINT = "fusion-api-constraint"
    MANUFACTURER_SPECIFIED = "manufacturer-specified"
    STANDARD_SPECIFIED = "standard-specified"
    MATERIAL_DATASHEET = "material-datasheet"
    FDM_PROCESS_HEURISTIC = "fdm-process-heuristic"
    USER_PREFERENCE = "user-preference"
    PROVISIONAL_DEFAULT = "provisional-default"
    COUPON_VERIFIED = "coupon-verified"
    PHYSICAL_TEST_REQUIRED = "physical-test-required"


SOURCE_REQUIRED = {
    EvidenceClass.MANUFACTURER_SPECIFIED,
    EvidenceClass.STANDARD_SPECIFIED,
    EvidenceClass.MATERIAL_DATASHEET,
    EvidenceClass.COUPON_VERIFIED,
}


def validate_evidence(evidence_class: EvidenceClass, source_ref: str | None) -> None:
    if not isinstance(evidence_class, EvidenceClass):
        raise ValueError("evidence_class must be a supported EvidenceClass")
    if evidence_class in SOURCE_REQUIRED and not (source_ref and source_ref.strip()):
        raise ValueError(f"{evidence_class.value} requires source_ref")
