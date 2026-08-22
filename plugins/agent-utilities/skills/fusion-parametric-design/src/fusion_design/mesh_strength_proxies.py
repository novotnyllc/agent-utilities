"""Advisory structural proxies computed from an exported 3MF mesh.

These numbers rank optimization candidates; they are never printed structural
claims. Coupon doctrine is unchanged: every output field carries proxy: true so
a report reader cannot mistake a geometric heuristic for measured strength.

Computed from a parsed 3MF (zipfile plus ElementTree, same reading rules as the
project builder):

* overhang_area_fraction -- share of triangle area whose surface slopes below
  OVERHANG_THRESHOLD_ANGLE_DEGREES from horizontal, i.e. material the slicer
  would consider unsupported overhang.
* max_unsupported_span_mm -- longest horizontal extent of one connected
  cluster of downward-facing triangles, approximated with a bounding box.
* vertical_wall_fraction -- share of triangle area whose normal's z-component
  is near zero.

A degenerate or empty mesh fails closed with a named error rather than
reporting zeros that would look like good news.
"""

from __future__ import annotations

import io
import math
import xml.etree.ElementTree as ET
import zipfile
from typing import Any

from .prusaslicer_project import MAX_MODEL_BYTES, MODEL_ENTRY

# Aligned with PrusaSlicer's default support threshold: surfaces shallower than
# this many degrees from horizontal are counted as overhang area.
OVERHANG_THRESHOLD_ANGLE_DEGREES = 45.0
# A triangle whose |normal z| falls below this is treated as a vertical wall;
# the epsilon keeps axis-aligned walls exact despite float noise.
VERTICAL_WALL_EPSILON = 1e-6

_LOCAL = lambda tag: str(tag).rsplit("}", 1)[-1]  # noqa: E731


class MeshStrengthProxyError(ValueError):
    """Named failure for degenerate or unreadable mesh proxy inputs."""


def _children(node: Any, name: str) -> list[Any]:
    return [child for child in node if _LOCAL(child.tag) == name]


def read_mesh_triangles(payload: bytes, label: str) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    """Read vertices and triangles from a single-mesh 3MF package."""
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            try:
                info = archive.getinfo(MODEL_ENTRY)
            except KeyError:
                raise MeshStrengthProxyError(
                    f"3MF {label!r} has no {MODEL_ENTRY} entry."
                ) from None
            if info.file_size > MAX_MODEL_BYTES:
                raise MeshStrengthProxyError(
                    f"3MF {label!r} declares a {info.file_size}-byte model, above the "
                    f"{MAX_MODEL_BYTES}-byte limit."
                )
            data = archive.read(MODEL_ENTRY)
    except zipfile.BadZipFile as error:
        raise MeshStrengthProxyError(f"3MF {label!r} is not a readable zip package: {error}") from error
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise MeshStrengthProxyError(f"3MF {label!r} has unparseable {MODEL_ENTRY}: {error}") from error

    meshes = [
        mesh
        for resources in _children(root, "resources")
        for obj in _children(resources, "object")
        for mesh in _children(obj, "mesh")
    ]
    if len(meshes) != 1:
        raise MeshStrengthProxyError(
            f"3MF {label!r} contains {len(meshes)} mesh objects; exactly one is required."
        )
    mesh = meshes[0]

    def coordinate(vertex: Any, axis: str) -> float:
        raw = vertex.get(axis)
        if raw is None:
            raise MeshStrengthProxyError(f"3MF {label!r} has a vertex with no {axis} coordinate.")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise MeshStrengthProxyError(f"3MF {label!r} has a non-numeric vertex {axis}={raw!r}.") from None
        if not math.isfinite(value):
            raise MeshStrengthProxyError(f"3MF {label!r} has a non-finite vertex {axis}={raw!r}.")
        return value

    vertices: list[tuple[float, float, float]] = []
    for holder in _children(mesh, "vertices"):
        for vertex in _children(holder, "vertex"):
            vertices.append(tuple(coordinate(vertex, axis) for axis in ("x", "y", "z")))  # type: ignore[arg-type]

    triangles: list[tuple[int, int, int]] = []
    for holder in _children(mesh, "triangles"):
        for triangle in _children(holder, "triangle"):
            indices = []
            for name in ("v1", "v2", "v3"):
                raw = triangle.get(name)
                if raw is None:
                    raise MeshStrengthProxyError(f"3MF {label!r} has a triangle with no {name} index.")
                try:
                    index = int(raw)
                except (TypeError, ValueError):
                    raise MeshStrengthProxyError(f"3MF {label!r} has a non-integer triangle {name}={raw!r}.") from None
                indices.append(index)
            triangles.append((indices[0], indices[1], indices[2]))  # type: ignore[arg-type]

    if not vertices or not triangles:
        raise MeshStrengthProxyError(
            f"3MF {label!r} carries no mesh geometry ({len(vertices)} vertices, "
            f"{len(triangles)} triangles); refusing to report proxies for nothing."
        )
    limit = len(vertices)
    for triangle in triangles:
        if any(index < 0 or index >= limit for index in triangle):
            raise MeshStrengthProxyError(f"3MF {label!r} has a triangle referencing a missing vertex.")
    # Degenerate triangles carry no usable normal and silently distort both
    # area fractions, so zero-area faces fail closed here too.
    for triangle in triangles:
        a, b, c = (vertices[i] for i in triangle)
        cross = (
            (b[1] - a[1]) * (c[2] - a[2]) - (b[2] - a[2]) * (c[1] - a[1]),
            (b[2] - a[2]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[2] - a[2]),
            (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]),
        )
        if math.isclose(math.sqrt(sum(component * component for component in cross)), 0.0, rel_tol=0.0, abs_tol=1e-12):
            raise MeshStrengthProxyError(f"3MF {label!r} has a zero-area (degenerate) triangle.")
    return vertices, triangles


def compute_strength_proxies(payload: bytes, label: str) -> dict[str, Any]:
    """Compute advisory structural proxies from a single-mesh 3MF payload."""
    vertices, triangles = read_mesh_triangles(payload, label)

    total_area = 0.0
    overhang_area = 0.0
    vertical_wall_area = 0.0
    # Downward-facing clusters are unioned with edge-shared adjacency; spans use
    # each cluster's bounding box, which overestimates diagonal layouts but is
    # deterministic and never hides a long bridge. Bed-plane faces are plate-
    # supported, so they join neither the overhang nor the span graph.
    downward_faces: list[int] = []
    overhang_faces: list[int] = []
    face_edges: dict[tuple[int, int], list[int]] = {}
    span_faces: list[int] = []

    min_z = min(vertex[2] for vertex in vertices)
    # Geometry resting on the build plate is supported by definition; only
    # area lying in the bed plane can be true plate-supported overhang. Without
    # this, a flat plate would report its entire bed face as overhang. A tilted
    # face that merely touches the plate at an edge is still mostly unsupported,
    # so only in-plane faces are exempt.
    bed_tolerance_mm = 1e-6
    sin_threshold = math.sin(math.radians(OVERHANG_THRESHOLD_ANGLE_DEGREES))

    for index, triangle in enumerate(triangles):
        ax, ay, az = vertices[triangle[0]]
        bx, by, bz = vertices[triangle[1]]
        cx, cy, cz = vertices[triangle[2]]
        cross = (
            (by - ay) * (cz - az) - (bz - az) * (cy - ay),
            (bz - az) * (cx - ax) - (bx - ax) * (cz - az),
            (bx - ax) * (cy - ay) - (by - ay) * (cx - ax),
        )
        length = math.sqrt(sum(component * component for component in cross))
        area = 0.5 * length
        nz = cross[2] / length
        total_area += area
        if abs(nz) <= VERTICAL_WALL_EPSILON:
            vertical_wall_area += area
        if nz < -VERTICAL_WALL_EPSILON:
            downward_faces.append(index)
            in_bed_plane = all(
                vertices[i][2] <= min_z + bed_tolerance_mm for i in triangle
            )
            if not in_bed_plane:
                overhang_faces.append(index)
                span_faces.append(index)
                for edge in (
                    tuple(sorted((triangle[0], triangle[1]))),
                    tuple(sorted((triangle[1], triangle[2]))),
                    tuple(sorted((triangle[2], triangle[0]))),
                ):
                    face_edges.setdefault(edge, []).append(index)

    for index in overhang_faces:
        triangle = triangles[index]
        ax, ay, az = vertices[triangle[0]]
        bx, by, bz = vertices[triangle[1]]
        cx, cy, cz = vertices[triangle[2]]
        cross = (
            (by - ay) * (cz - az) - (bz - az) * (cy - ay),
            (bz - az) * (cx - ax) - (bx - ax) * (cz - az),
            (bx - ax) * (cy - ay) - (by - ay) * (cx - ax),
        )
        length = math.sqrt(sum(component * component for component in cross))
        # Shallow relative to horizontal: the normal stands closer to vertical
        # than the threshold, i.e. the surface slopes less than the threshold
        # angle away from the build plate.
        if abs(cross[2]) / length >= sin_threshold:
            overhang_area += 0.5 * length

    max_span = 0.0
    remaining = set(span_faces)
    while remaining:
        stack = [remaining.pop()]
        cluster = {stack[0]}
        xs: list[float] = []
        ys: list[float] = []
        while stack:
            face = stack.pop()
            for vertex_index in triangles[face]:
                x, y, _ = vertices[vertex_index]
                xs.append(x)
                ys.append(y)
            for edge in (
                tuple(sorted((triangles[face][0], triangles[face][1]))),
                tuple(sorted((triangles[face][1], triangles[face][2]))),
                tuple(sorted((triangles[face][2], triangles[face][0]))),
            ):
                for neighbor in face_edges.get(edge, ()):
                    if neighbor not in cluster:
                        cluster.add(neighbor)
                        stack.append(neighbor)
                        remaining.discard(neighbor)
        span = max(max(xs) - min(xs), max(ys) - min(ys))
        max_span = max(max_span, span)

    return {
        "proxy": True,
        "overhang_area_fraction": overhang_area / total_area,
        "max_unsupported_span_mm": max_span,
        "vertical_wall_fraction": vertical_wall_area / total_area,
        "overhang_threshold_angle_degrees": OVERHANG_THRESHOLD_ANGLE_DEGREES,
        "triangle_count": len(triangles),
    }
