"""Synthetic fit records with known analytic answers, shared by the U3 tests."""

from __future__ import annotations

import hashlib
from typing import Any


def region_hash(label: str) -> str:
    """A stand-in for U2's canonical hash over a region's triangle indices."""
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


DUMP_SHA256 = hashlib.sha256(b"synthetic-dump").hexdigest()

PLANE_SIGMAS = {"normal_deg": 0.05, "offset": 0.01}
CYLINDER_SIGMAS = {"axis_direction_deg": 0.05, "axis_point": 0.01, "radius": 0.005}
CONE_SIGMAS = {"axis_direction_deg": 0.05, "apex": 0.01, "half_angle_deg": 0.05}
SPHERE_SIGMAS = {"center": 0.01, "radius": 0.005}


def plane(label, normal, point, area, *, uncertainty=None, accepted=True, rejection=None):
    offset = sum(n * p for n, p in zip(normal, point))
    lo = tuple(p - 1.0 for p in point)
    hi = tuple(p + 1.0 for p in point)
    return {
        "region_hash": region_hash(label),
        "area": area,
        "bounding_box": [list(lo), list(hi)],
        "fit": {
            "kind": "plane",
            "accepted": accepted,
            "rms_residual": 0.001,
            "relative_residual": 0.0001,
            "extent": 10.0,
            "parameters": {"normal": list(normal), "offset": offset, "point_on_plane": list(point)},
            "uncertainty": dict(PLANE_SIGMAS if uncertainty is None else uncertainty),
            **({"rejection": rejection} if rejection else {}),
        },
    }


def cylinder(label, axis, axis_point, radius, area, span, *, uncertainty=None):
    lo = tuple(p - radius for p in axis_point)
    hi = tuple(p + radius for p in axis_point)
    return {
        "region_hash": region_hash(label),
        "area": area,
        "bounding_box": [list(lo), list(hi)],
        "fit": {
            "kind": "cylinder",
            "accepted": True,
            "rms_residual": 0.001,
            "relative_residual": 0.0001,
            "extent": 10.0,
            "parameters": {
                "axis_direction": list(axis),
                "axis_point": list(axis_point),
                "radius": radius,
            },
            "support": {"axial_span": span},
            "uncertainty": dict(CYLINDER_SIGMAS if uncertainty is None else uncertainty),
        },
    }


def record(regions: list[dict[str, Any]], *, units: str = "mm") -> dict[str, Any]:
    return {
        "record_version": 1,
        "dump_sha256": DUMP_SHA256,
        "units": units,
        "total_area": sum(region["area"] for region in regions),
        "regions": regions,
    }


def box_record() -> dict[str, Any]:
    """A 10 x 20 x 5 box: six planes, no cylinder, every answer known by hand."""
    return record(
        [
            plane("x-lo", (1.0, 0.0, 0.0), (0.0, 10.0, 2.5), 100.0),
            plane("x-hi", (1.0, 0.0, 0.0), (10.0, 10.0, 2.5), 100.0),
            plane("y-lo", (0.0, 1.0, 0.0), (5.0, 0.0, 2.5), 50.0),
            plane("y-hi", (0.0, 1.0, 0.0), (5.0, 20.0, 2.5), 50.0),
            plane("z-lo", (0.0, 0.0, 1.0), (5.0, 10.0, 0.0), 200.0),
            plane("z-hi", (0.0, 0.0, 1.0), (5.0, 10.0, 5.0), 200.0),
        ]
    )


def turned_record() -> dict[str, Any]:
    """A cylinder between two end caps, plus one flat that gives the frame an X."""
    return record(
        [
            cylinder("boss", (0.0, 0.0, 1.0), (0.0, 0.0, 4.0), 3.0, 150.0, 8.0),
            plane("cap-lo", (0.0, 0.0, 1.0), (0.0, 0.0, 0.0), 28.0),
            plane("cap-hi", (0.0, 0.0, 1.0), (0.0, 0.0, 8.0), 28.0),
            plane("flat", (1.0, 0.0, 0.0), (3.0, 0.0, 4.0), 12.0),
        ]
    )


def spec(
    *,
    basis: str = "uncertainty",
    adopted: list[dict[str, Any]] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    thresholds: dict[str, Any] = {
        "frame_margin": {
            "value": 0.1,
            "rationale": "10% of the winning score; below that the two candidates are the same size.",
        },
        "angle_tolerance_deg": {
            "value": 2.0,
            "rationale": "screening window; wider than any fit's angular sigma in this fixture.",
        },
        "offset_tolerance": {
            "value": 0.5,
            "rationale": "screening window in mm for axis offsets on a part of this size.",
        },
        "equal_radius_tolerance": {
            "value": 0.05,
            "rationale": "screening window for radii that might be one parameter on this part.",
        },
        "tangent_tolerance": {
            "value": 0.05,
            "rationale": "screening window for tangency on a part of this size.",
        },
        "tolerance_basis": basis,
        "sigma_multiple": {
            "value": 3.0,
            "rationale": "three sigma: a deviation beyond it is not explained by fit noise.",
        },
    }
    if basis == "declared-absolute":
        thresholds.pop("sigma_multiple")
        thresholds["absolute_angle_tolerance_deg"] = {
            "value": 0.5,
            "rationale": "the shop's angular tolerance for this class of part.",
        }
        thresholds["absolute_length_tolerance"] = {
            "value": 0.05,
            "rationale": "the shop's linear tolerance for this class of part.",
        }
    thresholds.update(overrides)
    return {"thresholds": thresholds, "adopted": list(adopted or [])}
