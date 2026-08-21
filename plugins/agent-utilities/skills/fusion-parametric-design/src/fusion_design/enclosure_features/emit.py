"""Public one-feature-at-a-time emitter surface."""

from collections.abc import Mapping, Sequence

from .boss import (
    emit_create_boss_source,
    emit_delete_feature_source,
    emit_edit_feature_source,
    emit_inspect_feature_source,
)
from .contracts import BossRequest
from .identity import validate_feature_id
from .parameters import validate_expression


def emit_create_boss(request: BossRequest) -> str:
    return emit_create_boss_source(request)


def emit_edit_feature(
    feature_id: str,
    updates: Mapping[str, str],
    parameter_names: Sequence[str],
    object_tokens: Sequence[str],
    timeline_group_name: str,
) -> str:
    validate_feature_id(feature_id)
    if not updates:
        raise ValueError("at least one parameter update is required")
    _validate_receipt(parameter_names, object_tokens, timeline_group_name)
    for expression in updates.values():
        validate_expression(expression, "mm")
    return emit_edit_feature_source(
        feature_id, updates, parameter_names, object_tokens, timeline_group_name
    )


def emit_inspect_feature(
    feature_id: str,
    parameter_names: Sequence[str],
    object_tokens: Sequence[str],
    timeline_group_name: str,
) -> str:
    validate_feature_id(feature_id)
    _validate_receipt(parameter_names, object_tokens, timeline_group_name)
    return emit_inspect_feature_source(
        feature_id, parameter_names, object_tokens, timeline_group_name
    )


def emit_delete_feature(
    feature_id: str,
    parameter_names: Sequence[str],
    object_tokens: Sequence[str],
    timeline_group_name: str,
) -> str:
    validate_feature_id(feature_id)
    _validate_receipt(parameter_names, object_tokens, timeline_group_name)
    return emit_delete_feature_source(
        feature_id, parameter_names, object_tokens, timeline_group_name
    )


def _validate_receipt(
    parameter_names: Sequence[str], object_tokens: Sequence[str], timeline_group_name: str
) -> None:
    if not parameter_names or len(set(parameter_names)) != len(parameter_names):
        raise ValueError("receipt requires unique managed parameter names")
    if not object_tokens or len(set(object_tokens)) != len(object_tokens):
        raise ValueError("receipt requires unique managed object tokens")
    if not timeline_group_name.strip():
        raise ValueError("receipt requires the exact managed timeline group name")
    if (len(parameter_names), len(object_tokens)) not in {(6, 8), (8, 14)}:
        raise ValueError("receipt does not match a complete v1 boss shape")
