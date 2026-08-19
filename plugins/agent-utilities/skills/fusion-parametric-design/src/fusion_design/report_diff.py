from __future__ import annotations

import json
from typing import Any

# This is the same comparison the export staleness gate makes -- two independent
# Fusion measurements of a body that did not move -- so it must use the same
# tolerance. That gate's value lives inside the emitted export transaction
# (export_handoff.EXPORT_STALENESS_TOLERANCE_MM, a literal in the script
# template, not importable from here), so the two are kept equal by
# test_report_diff.test_bounds_tolerance_matches_the_export_staleness_gate.
BOUNDS_TOLERANCE_MM = 1e-3


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _canonical_rows(value: Any) -> dict[str, Any]:
    rows = value if isinstance(value, list) else []
    return {
        json.dumps(row, sort_keys=True, separators=(",", ":"), default=str): row
        for row in rows
    }


def _rows_by_id(value: Any) -> dict[str, Any]:
    """Key check rows by their declared id.

    Rows without one are keyed by their own canonical JSON rather than by list
    position, so deleting one unnamed row does not report its neighbour as
    changed.
    """
    rows = value if isinstance(value, list) else []
    indexed: dict[str, Any] = {}
    for row in rows:
        identifier = row.get("id") if isinstance(row, dict) else None
        if identifier is None:
            indexed[json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)] = row
        else:
            indexed[str(identifier)] = row
    return indexed


def _changed_by_id(before: Any, after: Any) -> dict[str, dict[str, Any]]:
    before_rows = _rows_by_id(before)
    after_rows = _rows_by_id(after)
    return {
        identifier: {"before": before_rows.get(identifier), "after": after_rows.get(identifier)}
        for identifier in sorted(set(before_rows) | set(after_rows))
        if before_rows.get(identifier) != after_rows.get(identifier)
    }


def _corners_mm(value: Any) -> list[float] | None:
    """Flatten a {min, max} bounds record to six numbers, or None if it is not one."""
    if not isinstance(value, dict):
        return None
    flattened: list[float] = []
    for key in ("min", "max"):
        corner = value.get(key)
        if not isinstance(corner, list) or len(corner) != 3:
            return None
        for element in corner:
            if isinstance(element, bool) or not isinstance(element, (int, float)):
                return None
            flattened.append(float(element))
    return flattened


def _bounds_equal(before: Any, after: Any) -> bool:
    before_corners = _corners_mm(before)
    after_corners = _corners_mm(after)
    if before_corners is None or after_corners is None:
        # Error records and malformed entries are compared verbatim.
        return before == after
    return all(
        abs(left - right) <= BOUNDS_TOLERANCE_MM
        for left, right in zip(before_corners, after_corners)
    )


def _token_set(value: Any) -> set[str]:
    return {str(token) for token in value} if isinstance(value, list) else set()


def diff_reports(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_parameters = _as_dict(before.get("parameters", {}))
    after_parameters = _as_dict(after.get("parameters", {}))
    parameter_changes: dict[str, dict[str, Any]] = {}
    for name in sorted(set(before_parameters) | set(after_parameters)):
        before_value = before_parameters.get(name)
        after_value = after_parameters.get(name)
        if before_value != after_value:
            parameter_changes[name] = {"before": before_value, "after": after_value}

    before_components = set(before.get("component_paths", []) or [])
    after_components = set(after.get("component_paths", []) or [])

    before_geometry = _as_dict(before.get("geometry", {}))
    after_geometry = _as_dict(after.get("geometry", {}))
    geometry_changed: dict[str, dict[str, Any]] = {}
    for path in sorted(set(before_geometry).intersection(after_geometry)):
        if before_geometry[path] != after_geometry[path]:
            geometry_changed[path] = {
                "before": before_geometry[path],
                "after": after_geometry[path],
            }

    before_timeline = _as_dict(before.get("timeline", {}))
    after_timeline = _as_dict(after.get("timeline", {}))
    unhealthy_before = _canonical_rows(before_timeline.get("unhealthy", []))
    unhealthy_after = _canonical_rows(after_timeline.get("unhealthy", []))

    # Position is invisible in the geometry summaries (volume and body counts
    # survive a rigid move), so bounds are diffed separately for both kinds.
    before_bounds = _as_dict(before.get("brep_bounding_boxes_mm", {}))
    after_bounds = _as_dict(after.get("brep_bounding_boxes_mm", {}))
    bounds_changed: dict[str, dict[str, Any]] = {}
    for path in sorted(set(before_bounds).intersection(after_bounds)):
        if not _bounds_equal(before_bounds[path], after_bounds[path]):
            bounds_changed[path] = {"before": before_bounds[path], "after": after_bounds[path]}

    before_failures = _token_set(before.get("failures"))
    after_failures = _token_set(after.get("failures"))

    return {
        "parameters_changed": parameter_changes,
        "components_added": sorted(after_components - before_components),
        "components_removed": sorted(before_components - after_components),
        "geometry_added": sorted(set(after_geometry) - set(before_geometry)),
        "geometry_removed": sorted(set(before_geometry) - set(after_geometry)),
        "geometry_changed": geometry_changed,
        "timeline_unhealthy_after": list(after_timeline.get("unhealthy", []) or []),
        "timeline_unhealthy_added": [
            unhealthy_after[key] for key in sorted(set(unhealthy_after) - set(unhealthy_before))
        ],
        "timeline_unhealthy_removed": [
            unhealthy_before[key] for key in sorted(set(unhealthy_before) - set(unhealthy_after))
        ],
        "bounds_changed": bounds_changed,
        # An uncompared pair is reported, not silently omitted: a body that was
        # renamed and moved must not lose its displacement to the rename.
        "bounds_added": sorted(set(after_bounds) - set(before_bounds)),
        "bounds_removed": sorted(set(before_bounds) - set(after_bounds)),
        "ok_before": before.get("ok"),
        "ok_after": after.get("ok"),
        "failures_added": sorted(after_failures - before_failures),
        "failures_removed": sorted(before_failures - after_failures),
        "clearance_changed": _changed_by_id(
            before.get("clearance_results"), after.get("clearance_results")
        ),
        "interference_changed": _changed_by_id(
            before.get("interference_results"), after.get("interference_results")
        ),
    }
