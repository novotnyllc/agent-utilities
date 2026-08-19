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


def blend_cylinder(label, axis, axis_point, radius, area, *, between):
    """An accepted *partial-arc cylinder* carrying U2's fillet proposal.

    The other shape a blend arrives as, and the only one a face-grouped mesh
    actually produces.  The arc that separates an edge round from a bore is
    measured upstream against U2's own declared ceiling; the fit record carries
    the proposal, not the span, so nothing downstream re-measures it.
    """
    region = cylinder(label, axis, axis_point, radius, area, 8.0)
    region["fillet_candidate"] = True
    region["fillet"] = {
        "radius": radius,
        "between": [region_hash(name) for name in between],
        "emission": "filletFeatures on the shared edge, radius = the cylinder radius over a partial arc",
    }
    return region


def oriented(region, side, *, reason=None):
    """Attach U2's orientation block, the bore-versus-boss evidence.

    ``side=None`` is the open-mesh case: the winding carries no inside/outside
    information and the block says so rather than omitting the question.
    """
    region["orientation"] = {
        "surface_normal_agreement": 0.02 if side else None,
        "outward_normal": [0.0, 0.0, 1.0],
        "mesh_winding": "outward" if side else None,
        "mesh_closed": side is not None,
        "material_side": side,
        "unavailable_reason": None
        if side
        else (
            reason
            or "the mesh is not closed and consistently wound, so its winding carries no "
            "inside/outside information"
        ),
    }
    return region


def torus(label, radius, minor_radius, area, *, between, candidate=True):
    """An accepted torus, optionally carrying U2's two-neighbour fillet proposal."""
    region = {
        "region_hash": region_hash(label),
        "area": area,
        "bounding_box": [[-radius, -radius, -minor_radius], [radius, radius, minor_radius]],
        "fit": {
            "kind": "torus",
            "accepted": True,
            "rms_residual": 0.001,
            "relative_residual": 0.0001,
            "extent": 10.0,
            "parameters": {
                "center": [0.0, 0.0, 0.0],
                "axis_direction": [0.0, 0.0, 1.0],
                "radius": radius,
                "minor_radius": minor_radius,
            },
            "uncertainty": {"center": 0.01, "radius": 0.005, "minor_radius": 0.005},
        },
    }
    if candidate:
        region["fillet_candidate"] = True
        region["fillet"] = {
            "radius": minor_radius,
            "between": [region_hash(name) for name in between],
            "emission": "filletFeatures on the shared edge, radius = the torus minor radius",
        }
    return region


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


def bored_post_record(side="inside", *, bore_axis=(0.0, 0.0, 1.0), extras=()):
    """A 12 x 10 x 30 post with a bore down it, and no cylinder outside it.

    The x faces are deliberately larger than the y faces so the secondary datum
    axis has a clear winner; equal areas make the frame ambiguous and the run
    refuses before archetypes are ever planned.
    """
    bore = cylinder("bore", bore_axis, (4.0, 4.0, 15.0), 2.0, 380.0, 30.0)
    bore["bounding_box"] = [[2.0, 2.0, 0.0], [6.0, 6.0, 30.0]]
    return record(
        [
            plane("x-lo", (1.0, 0.0, 0.0), (0.0, 5.0, 15.0), 360.0),
            plane("x-hi", (1.0, 0.0, 0.0), (12.0, 5.0, 15.0), 360.0),
            plane("y-lo", (0.0, 1.0, 0.0), (6.0, 0.0, 15.0), 300.0),
            plane("y-hi", (0.0, 1.0, 0.0), (6.0, 10.0, 15.0), 300.0),
            plane("z-lo", (0.0, 0.0, 1.0), (6.0, 5.0, 0.0), 120.0),
            plane("z-hi", (0.0, 0.0, 1.0), (6.0, 5.0, 30.0), 120.0),
            oriented(bore, side),
            *extras,
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
