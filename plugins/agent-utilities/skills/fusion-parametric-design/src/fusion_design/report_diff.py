from __future__ import annotations

import json
from typing import Any


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _canonical_rows(value: Any) -> dict[str, Any]:
    rows = value if isinstance(value, list) else []
    return {
        json.dumps(row, sort_keys=True, separators=(",", ":"), default=str): row
        for row in rows
    }


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
    }
