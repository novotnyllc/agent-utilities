"""Human naming and Fusion-owned managed identity."""

import re
import uuid


def validate_feature_id(value: str) -> str:
    parsed = uuid.UUID(value)
    if str(parsed) != value.lower():
        raise ValueError("feature_id must be a canonical UUID")
    return value.lower()


def validate_instance_name(value: str) -> str:
    if not value.strip() or len(value) > 80 or re.search(r"[\r\n]", value):
        raise ValueError("instance_name must be one readable browser line")
    return value.strip()
