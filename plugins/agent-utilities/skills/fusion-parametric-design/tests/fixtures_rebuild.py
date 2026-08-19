"""Fixtures shared by the U4/U5 tests: a bound dump and a program over it."""

from __future__ import annotations

from typing import Any

from fusion_design.reconstruction_program import program_sha256

from test_mesh_segmentation import box_mesh, cylinder_mesh, make_dump


MANIFEST_HASH_PLACEHOLDER = "c" * 64

IDENTITY = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]


def box_dump(size: float = 20.0, **kwargs: Any):
    vertices, triangles, groups = box_mesh(size=size, **kwargs)
    return make_dump(vertices, triangles, face_groups=groups)


def two_box_dump(size: float = 20.0, gap: float = 40.0):
    """Two disjoint boxes, so any section between their caps closes two loops."""
    vertices, triangles, groups = box_mesh(size=size)
    count = len(vertices)
    shifted = [(x + gap, y, z) for x, y, z in vertices]
    return make_dump(
        list(vertices) + shifted,
        list(triangles) + [tuple(i + count for i in t) for t in triangles],
        # The second box's six faces are six more groups, not the same six.
        face_groups=list(groups) + [g + 6 for g in groups],
    )


def cylinder_dump(radius: float = 8.0, height: float = 30.0, **kwargs: Any):
    vertices, triangles, groups = cylinder_mesh(radius=radius, height=height, **kwargs)
    return make_dump(vertices, triangles, face_groups=groups)


def capped_cylinder_mesh(
    radius: float = 8.0,
    height: float = 30.0,
    sides: int = 64,
    steps: int = 6,
):
    """A closed solid of revolution: the shape a revolve archetype rebuilds.

    ``cylinder_mesh`` is an open tube, so its axial section is two disconnected
    runs rather than a closed loop, and a revolve profile has to come from a
    closed one.  The profile is *sampled*, not just cornered: four points of a
    rectangle are exactly concyclic, so a corner-only section legitimately
    classifies as one arc.  Real mesh data carries intermediate samples and this
    fixture does too, or the test would be measuring the fixture.
    """
    import math

    profile: list[tuple[float, float]] = []
    for k in range(steps):  # bottom cap, r = 0 .. R
        profile.append((radius * k / steps, 0.0))
    for k in range(steps):  # side, z = 0 .. H
        profile.append((radius, height * k / steps))
    for k in range(steps):  # top cap, r = R .. 0
        profile.append((radius * (steps - k) / steps, height))
    profile.append((0.0, height))

    vertices: list[tuple[float, float, float]] = []
    index: dict[tuple[int, int], int] = {}
    for j, (r, z) in enumerate(profile):
        if r == 0.0:
            index[(j, 0)] = len(vertices)
            vertices.append((0.0, 0.0, z))
            for i in range(1, sides):
                index[(j, i)] = index[(j, 0)]
            continue
        for i in range(sides):
            angle = 2.0 * math.pi * i / sides
            index[(j, i)] = len(vertices)
            vertices.append((r * math.cos(angle), r * math.sin(angle), z))

    triangles: list[tuple[int, int, int]] = []
    # Three analytic faces, which is what Fusion's accurate grouping returns for
    # this solid: the bottom disc, the cylindrical side, the top disc.
    groups: list[int] = []
    for j in range(len(profile) - 1):
        face = 0 if j < steps else (1 if j < 2 * steps else 2)
        for i in range(sides):
            nxt = (i + 1) % sides
            a, b = index[(j, i)], index[(j, nxt)]
            c, d = index[(j + 1, nxt)], index[(j + 1, i)]
            if len({a, b, c}) == 3:
                triangles.append((a, b, c))
                groups.append(face)
            if len({a, c, d}) == 3:
                triangles.append((a, c, d))
                groups.append(face)
    return vertices, triangles, groups


def capped_cylinder_dump(
    radius: float = 8.0, height: float = 30.0, sides: int = 64, steps: int = 6
):
    vertices, triangles, groups = capped_cylinder_mesh(radius, height, sides, steps)
    return make_dump(vertices, triangles, face_groups=groups)


def datum(origin=(0.0, 0.0, 0.0)) -> dict[str, Any]:
    return {
        "origin": list(origin),
        "x_axis": [1.0, 0.0, 0.0],
        "y_axis": [0.0, 1.0, 0.0],
        "z_axis": [0.0, 0.0, 1.0],
        "evidence": {"basis": "fixture"},
    }


def threshold(value: float, rationale: str = "fixture threshold") -> dict[str, Any]:
    return {"value": value, "rationale": rationale}


def program(
    dump_sha256: str,
    *,
    archetypes: list[dict[str, Any]] | None = None,
    parameters: list[dict[str, Any]] | None = None,
    order: list[str] | None = None,
    origin=(0.0, 0.0, 0.0),
    **overrides: Any,
) -> dict[str, Any]:
    archetypes = archetypes if archetypes is not None else [extrude_archetype()]
    parameters = parameters if parameters is not None else default_parameters(archetypes)
    # The planner gives every archetype the share of the scan it accounts for, so
    # a fixture without one is a shape the producer never emits -- and the last
    # time a fixture and a producer disagreed like this the whole pipeline was
    # unrunnable. Split the declared coverage evenly unless the caller says.
    covered = float(overrides.get("covered_area_fraction", 1.0))
    for group in archetypes:
        group.setdefault("area_fraction", covered / len(archetypes) if archetypes else 0.0)
    body = {
        "program_version": 1,
        "dump_sha256": dump_sha256,
        "manifest_sha256": MANIFEST_HASH_PLACEHOLDER,
        "units": "mm",
        "thresholds": {"tolerance_basis": "declared-absolute"},
        "datum": datum(origin),
        "user_parameters": parameters,
        "archetypes": archetypes,
        "order": order if order is not None else [g["id"] for g in archetypes],
        "unreconstructed": [],
        "relationships": {"proposals": [], "adopted": []},
        "covered_area_fraction": 1.0,
        "profile_note": "fixture",
    }
    body.update(overrides)
    body["program_sha256"] = program_sha256(body)
    return body


def extrude_archetype(
    identifier: str = "sketch-extrude-aaaaaaaaaaaa",
    *,
    datum_plane: str = "XY",
    offset: float = -10.0,
    depth: float = 20.0,
    operation: str = "new-body",
    dependencies: list[str] | None = None,
    parameter: str = "recon_base_1_depth",
    constraints: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": identifier,
        "kind": "sketch-extrude",
        "operation": operation,
        "regions": ["a" * 64],
        "plane": {"datum_plane": datum_plane, "offset": offset, "rotation": None},
        "cap_regions": ["a" * 64],
        "profile": None,
        "profile_source": "mesh-section",
        "extent": {"kind": "distance", "parameter": parameter, "value": depth},
        "constraints": constraints or [],
        "dependencies": dependencies or [],
        "reason": "fixture",
    }


def revolve_archetype(
    identifier: str = "revolve-bbbbbbbbbbbb",
    *,
    radius: float = 8.0,
    parameter: str = "recon_revolve_1_radius",
    dependencies: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": identifier,
        "kind": "revolve",
        "operation": "new-body",
        "regions": ["b" * 64],
        "plane": {"datum_plane": "XZ", "offset": 0.0, "rotation": None},
        "axis": {"datum_axis": "Z", "angle_deg": 360.0},
        "profile": None,
        "profile_source": "mesh-section",
        "extent": {"kind": "revolve-full", "parameter": None, "value": 30.0},
        "radius": {"parameter": parameter, "value": radius},
        "constraints": [],
        "dependencies": dependencies or [],
        "reason": "fixture",
    }


def hole_archetype(
    identifier: str = "hole-cccccccccccc",
    *,
    datum_plane: str = "XY",
    offset: float = -10.0,
    depth: float = 20.0,
    diameter: float = 6.0,
    position: tuple[float, float] = (2.0, 3.0),
    dependencies: list[str] | None = None,
    stem: str = "recon_hole_1",
) -> dict[str, Any]:
    u_axis, v_axis = {"XY": ("X", "Y"), "XZ": ("X", "Z"), "YZ": ("Y", "Z")}[datum_plane]
    return {
        "id": identifier,
        "kind": "hole",
        "operation": "cut",
        "regions": ["c" * 64],
        "plane": {"datum_plane": datum_plane, "offset": offset, "rotation": None},
        "hole": {
            "diameter": {"parameter": f"{stem}_dia", "value": diameter},
            "position": {
                "u_axis": u_axis,
                "v_axis": v_axis,
                "u": {"parameter": f"{stem}_{u_axis.lower()}", "value": position[0]},
                "v": {"parameter": f"{stem}_{v_axis.lower()}", "value": position[1]},
            },
        },
        "profile": None,
        "profile_source": "fit-primitive",
        "extent": {"kind": "distance", "parameter": f"{stem}_depth", "value": depth},
        "constraints": [],
        "dependencies": dependencies if dependencies is not None else ["sketch-extrude-aaaaaaaaaaaa"],
        "reason": "fixture: an accepted cylinder whose material_side is inside.",
    }


def fillet_archetype(
    identifier: str = "fillet-eeeeeeeeeeee",
    *,
    radius: float = 1.5,
    between: list[str] | None = None,
    parameter: str = "recon_fillet_1_radius",
) -> dict[str, Any]:
    between = between if between is not None else [
        "sketch-extrude-aaaaaaaaaaaa",
        "hole-cccccccccccc",
    ]
    return {
        "id": identifier,
        "kind": "fillet",
        "operation": "finish",
        "regions": ["e" * 64],
        "plane": None,
        "radius": {"parameter": parameter, "value": radius},
        "between": list(between),
        "profile": None,
        "profile_source": None,
        "constraints": [],
        "dependencies": list(between),
        "reason": "fixture: an accepted torus between two rebuilt features.",
    }


def default_parameters(archetypes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group in archetypes:
        wanted: list[tuple[str | None, Any, str, str]] = []
        if group["kind"] in ("revolve", "fillet"):
            wanted.append(
                (group["radius"]["parameter"], group["radius"]["value"], "radius", "volume")
            )
        else:
            wanted.append(
                (group["extent"]["parameter"], group["extent"]["value"], "depth", "volume")
            )
        # `.get` rather than `[...]`: some tests build a deliberately malformed
        # hole to prove the planner refuses it, and the fixture must be able to
        # produce that program rather than failing first.
        if group["kind"] == "hole" and isinstance(group.get("hole"), dict):
            body = group["hole"]
            wanted.append(
                (body["diameter"]["parameter"], body["diameter"]["value"], "diameter", "volume")
            )
            for slot in (body["position"]["u"], body["position"]["v"]):
                wanted.append((slot["parameter"], slot["value"], "position", "centroid"))
        for name, nominal, quantity, observable in wanted:
            if name is None or any(row["name"] == name for row in rows):
                continue
            rows.append(
                {
                    "name": name,
                    "quantity": quantity,
                    "unit": "mm",
                    "nominal": nominal,
                    "expected_observable": observable,
                    "observable_rationale": "fixture",
                    "rationale": "fixture",
                    "driving_archetypes": [group["id"]],
                }
            )
    return rows


def rebuild_spec(dump_path: str, **overrides: Any) -> dict[str, Any]:
    spec = {
        "component_name": "Reconstruction",
        "dump_path": dump_path,
        "rationale": "fixture: thresholds sized for a synthetic 20 mm box at zero noise.",
        "thresholds": {
            "section_tolerance_mm": threshold(1e-9),
            "classify_tolerance_mm": threshold(0.05),
            "profile_chain_tolerance_mm": threshold(0.01),
            "snap_tolerance_deg": threshold(2.0),
            "snap_tolerance_mm": threshold(0.1),
            "constraint_displacement_tolerance_mm": threshold(0.05),
            "constraint_rejection_budget": {"value": 2, "rationale": "fixture budget"},
            "entity_match_tolerance_mm": threshold(0.1),
        },
    }
    thresholds = overrides.pop("thresholds", None)
    if thresholds:
        spec["thresholds"].update(thresholds)
    spec.update(overrides)
    return spec
