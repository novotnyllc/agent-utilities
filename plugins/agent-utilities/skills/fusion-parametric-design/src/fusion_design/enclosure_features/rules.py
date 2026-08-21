"""Small v1 rule catalog; values remain in the request and Fusion."""

from .evidence import EvidenceClass


INSERT_DIMENSION_EVIDENCE = frozenset(
    {EvidenceClass.MANUFACTURER_SPECIFIED, EvidenceClass.COUPON_VERIFIED}
)
INSERT_DIMENSION_INVALIDATED_BY = frozenset(
    {"insert_model", "material_formulation", "process", "print_orientation"}
)
PHYSICAL_CLAIMS_NOT_MADE = frozenset(
    {"pull_out_strength", "torque_capacity", "fatigue_life", "cycle_life"}
)
