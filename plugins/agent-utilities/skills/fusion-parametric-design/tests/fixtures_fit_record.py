"""Synthetic fit records with known analytic answers, shared by the U3 tests."""

from __future__ import annotations

import hashlib
import math
from typing import Any

from fusion_design.mesh_fitting import region_motion_moments


def _plane_moments(normal, point, area):
    """Facets of a square patch of the declared area, centred on the fitted point.

    The fixture describes surfaces analytically and U3 now reads a *facet*
    statistic, so the fixture has to produce facets or it would be testing the
    consumer against evidence no producer could write.  These are honest facets
    of the very surface the fit record declares: the normal is the fitted one,
    the positions lie in the fitted plane, and the weights sum to the declared
    area.  `test_pipeline_seams` is what proves the real producer agrees.
    """
    axis = min(range(3), key=lambda i: abs(normal[i]))
    u = _unit_cross(normal, tuple(1.0 if i == axis else 0.0 for i in range(3)))
    v = _unit_cross(normal, u)
    # Kept inside the declared bounding box so the box and the facets describe
    # the same patch; the weights, not the footprint, carry the area.
    half, n = 1.0, 6
    points, normals, areas = [], [], []
    for i in range(n):
        for j in range(n):
            su = -half + 2.0 * half * (i + 0.5) / n
            sv = -half + 2.0 * half * (j + 0.5) / n
            points.append(tuple(point[k] + su * u[k] + sv * v[k] for k in range(3)))
            normals.append(tuple(normal))
            areas.append(area / (n * n))
    return region_motion_moments(points, normals, areas)


def _cylinder_moments(axis, axis_point, radius, area, span):
    u = _unit_cross(axis, (1.0, 0.0, 0.0) if abs(axis[0]) < 0.9 else (0.0, 1.0, 0.0))
    v = _unit_cross(axis, u)
    rings, around = 4, 24
    points, normals, areas = [], [], []
    for i in range(rings):
        t = -0.5 * span + span * (i + 0.5) / rings
        for j in range(around):
            phi = 2.0 * math.pi * j / around
            radial = tuple(math.cos(phi) * u[k] + math.sin(phi) * v[k] for k in range(3))
            points.append(
                tuple(axis_point[k] + t * axis[k] + radius * radial[k] for k in range(3))
            )
            normals.append(radial)
            areas.append(area / (rings * around))
    return region_motion_moments(points, normals, areas)


def _unit_cross(a, b):
    c = (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )
    length = math.sqrt(sum(x * x for x in c))
    return tuple(x / length for x in c)


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
    moments = _plane_moments(normal, point, area)
    return {
        "region_hash": region_hash(label),
        "area": area,
        # The parser binds the moment block to the region it rides on, so the
        # fixture states the same triangle count the block was built from.
        "triangle_count": moments["facet_count"],
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
        "motion_moments": moments,
    }


def cylinder(label, axis, axis_point, radius, area, span, *, uncertainty=None):
    lo = tuple(p - radius for p in axis_point)
    hi = tuple(p + radius for p in axis_point)
    moments = _cylinder_moments(axis, axis_point, radius, area, span)
    return {
        "region_hash": region_hash(label),
        "area": area,
        "triangle_count": moments["facet_count"],
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
        "motion_moments": moments,
    }


def _chain_id(name: str) -> str:
    """A chain id shaped like U2's: a hex digest over the chain's own members."""
    return hashlib.sha256(f"chain:{name}".encode("utf-8")).hexdigest()


def _chain_block(name: str, radius: float) -> dict[str, Any]:
    """U2's chain record for a blend: which edge it is, and that the walk kept it."""
    return {
        "id": _chain_id(name),
        "members": [region_hash(name)],
        "member_count": 1,
        "radius_spread_rel": 0.0,
        "max_radius_rel_spread": 0.02,
        "mean_radius": radius,
        "accepted": True,
        "reason": None,
    }


def blend_cylinder(label, axis, axis_point, radius, area, *, between, chain=None):
    """An accepted *partial-arc cylinder* carrying U2's fillet proposal.

    The other shape a blend arrives as, and the only one a face-grouped mesh
    actually produces.  The arc that separates an edge round from a bore is
    measured upstream against U2's own declared ceiling; the fit record carries
    the proposal, not the span, so nothing downstream re-measures it.

    ``chain`` names the *edge* this fragment lies on, as U2's blend chaining does:
    fragments of one round share a chain, and two rounds between the same pair of
    faces are two chains.  It defaults to the region's own label, which is what a
    lone fragment gets.  A record that named no chain would leave the planner
    unable to tell one rounded edge of a face pair from the next, and it says so
    rather than pooling them.
    """
    region = cylinder(label, axis, axis_point, radius, area, 8.0)
    region["fillet_candidate"] = True
    region["fillet"] = {
        "radius": radius,
        "between": [region_hash(name) for name in between],
        "chain_id": _chain_id(chain or label),
        "emission": "filletFeatures on the shared edge, radius = the cylinder radius over a partial arc",
    }
    region["fillet_chain"] = _chain_block(chain or label, radius)
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
            "chain_id": _chain_id(label),
            "emission": "filletFeatures on the shared edge, radius = the torus minor radius",
        }
        region["fillet_chain"] = _chain_block(label, minor_radius)
    return region


def record(
    regions: list[dict[str, Any]],
    *,
    units: str = "mm",
    detected: str = "tessellation",
    declared: str = "auto",
) -> dict[str, Any]:
    """A fit record shaped like U2's, regime block included.

    ``declared`` is what the caller asked for and ``detected`` what the mesh
    said; the effective regime is the declaration unless it is ``auto``, which
    is exactly the rule `_detect_regime` applies.
    """
    return {
        "record_version": 1,
        "dump_sha256": DUMP_SHA256,
        "units": units,
        "regime": {
            "regime": detected if declared == "auto" else declared,
            "detected": detected,
            "declared": declared,
            "overridden": declared != "auto" and declared != detected,
            "evidence": {},
        },
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


#: The 2.5D decomposition's declared gates, sized for these fixtures' own
#: millimetre-scale synthetic parts. Kept out of `spec()` unless a caller asks
#: for it, so every test that predates slabs stays on the path it was written
#: for -- undeclared means no decomposition is attempted, which is the planner's
#: own rule and not a special case for tests.
SLAB_EVIDENCE = {
    "event_merge_sigmas": {
        "value": 3.0,
        "rationale": "three combined sigmas: two stations closer than that are one station.",
    },
    "slab_constancy_tolerance_mm": {
        "value": 0.05,
        "rationale": "two sections of one slab are the same wall measured twice; this close is agreement.",
    },
    "section_tolerance_mm": {
        "value": 0.01,
        "rationale": "below the smallest feature these fixtures carry, above their float noise.",
    },
    "loop_material_consensus_fraction": {
        "value": 0.95,
        "rationale": "a designed surface's walls should be unanimous; five per cent is sliver room.",
    },
    "loop_attribution_min_fraction": {
        "value": 0.05,
        "rationale": "how much of a loop may cast no vote before its walls stop being evidence.",
    },
    "slab_section_fractions": {
        "value": [0.25, 0.75],
        "rationale": "quarter and three-quarter stations: far from the midpoint, far from both caps.",
    },
}


def spec(
    *,
    basis: str = "uncertainty",
    adopted: list[dict[str, Any]] | None = None,
    slabs: bool = False,
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
        "motion_evidence": {
            "sigma_theta_deg": {
                "value": 0.2865,
                "rationale": (
                    "0.005 rad of facet-normal noise, the floor a tessellated surface leaves once "
                    "the exporter's own vertex quantization is folded in."
                ),
            },
            "residual_sigma_factor": {
                "value": 3.0,
                "rationale": (
                    "three sigma of that noise before 'no rigid motion leaves this surface "
                    "invariant' is a statement about the geometry rather than about the mesh."
                ),
            },
            "eigengap_min": {
                "value": 0.005,
                "rationale": (
                    "half a percent of the spectrum: below it the second-smallest eigenvalue is "
                    "indistinguishable from zero and the invariant motions are a family, not one."
                ),
            },
            "translation_epsilon": {
                "value": 0.05,
                "rationale": (
                    "a rotation part under a twentieth of the unit six-vector is a translation "
                    "with rounding on it."
                ),
            },
            "pitch_epsilon": {
                "value": 0.02,
                "rationale": (
                    "two percent of the region's own extent per radian: below it a screw is a "
                    "rotation and the helix is the tessellation's."
                ),
            },
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
    if slabs:
        thresholds["slab_evidence"] = SLAB_EVIDENCE
    thresholds.update(overrides)
    return {"thresholds": thresholds, "adopted": list(adopted or [])}
