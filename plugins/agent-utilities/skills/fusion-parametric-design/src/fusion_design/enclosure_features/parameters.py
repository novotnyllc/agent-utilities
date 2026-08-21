"""Fusion-expression and namespaced-parameter validation."""

import re


_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_EXPRESSION = re.compile(r"^[A-Za-z0-9_+*/(). -]+$")
ROLE_PREFIXES = ("des_", "fab_", "clr_", "calc_")


def validate_namespace(value: str) -> str:
    if not _NAME.fullmatch(value):
        raise ValueError("parameter namespace must be a lower-case Fusion-safe identifier")
    return value


def validate_parameter_name(value: str, namespace: str) -> str:
    if not _NAME.fullmatch(value) or not value.startswith(ROLE_PREFIXES):
        raise ValueError("parameter name must use des_/fab_/clr_/calc_ ownership")
    if f"_{namespace}_" not in value:
        raise ValueError("parameter name must contain its namespace")
    return value


def validate_expression(value: str, units: str) -> str:
    if not value.strip() or not _EXPRESSION.fullmatch(value):
        raise ValueError("invalid Fusion expression")
    if units == "mm" and not re.search(r"\b(?:mm|cm|m|in|ft)\b", value):
        raise ValueError("length expressions must carry explicit units")
    return value
