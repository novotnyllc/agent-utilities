"""Plane-mesh sectioning, segment classification and primitive fitting.

Pure geometry over plain vertex/triangle data: no Fusion, no live API, stdlib
only.  Everything here is what U4's parametric-rebuild path needs *before* it
touches the Sketch API, and it is exactly the part that is worth proving
against synthetic meshes with known analytic answers.

Three deliberate positions, because each is a place a naive implementation is
confidently wrong:

* **Degenerate sections are named, not swallowed.**  A triangle lying in the
  plane, an edge touching it at one vertex, and a junction where three or more
  segments meet each get an explicit rule and an explicit count in the result.
* **Fits are gated on a *relative* residual and on part bounds.**  A near-flat
  strip fits an enormous circle centred far outside the part; a fit whose
  radius dwarfs the sampled extent, or whose centre/apex escapes the bounding
  box by more than a stated margin, is rejected rather than reported.
* **Design intent is proposed, never applied.**  Coaxiality, perpendicularity,
  parallelism, symmetry and nominal values come back as proposals carrying the
  measured deviation.  Snapping silently is how a scan-shaped model masquerades
  as a designed one.

Lengths are in whatever unit the caller's coordinates use; the module never
assumes millimetres.  Angles are reported in degrees and labelled ``deg``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import random
from typing import Any, Iterable, Mapping, Sequence

from .manifest import _in_closed_set


Vec3 = tuple[float, float, float]

PRIMITIVE_KINDS = {"plane", "cylinder", "cone", "sphere", "torus"}

#: Which *simpler* primitives must fail before a kind is believed.  A cylinder
#: through near-coplanar points is an artefact of the fit; so is a torus through
#: points a cylinder or a sphere already explains.  This is the discriminating
#: test that keeps a torus from being the answer to everything, since a torus
#: degenerates to a cylinder as its major radius grows and to a sphere as it
#: shrinks.
_SIMPLER_KINDS = {
    "plane": (),
    "sphere": ("plane",),
    "cylinder": ("plane",),
    "cone": ("plane",),
    "torus": ("plane", "cylinder", "sphere"),
}

ENTITY_KINDS = {"line", "arc", "circle"}

INTENT_KINDS = {
    "coaxial",
    "parallel",
    "perpendicular",
    "symmetric",
    "tangent",
    "equal_radius",
    "nominal",
}

# Default gates.  They are module defaults, not laws: every entry point takes
# them as keyword arguments so a caller can state its own.
DEFAULT_MAX_RELATIVE_RESIDUAL = 0.02
DEFAULT_MAX_RADIUS_RATIO = 5.0
DEFAULT_BOUNDS_MARGIN_RATIO = 1.0
DEFAULT_MIN_TAPER_RATIO = 0.01
#: A torus whose major radius is not comfortably larger than its minor radius is
#: a spindle or a sphere wearing a torus's parameters, so it is refused by name.
DEFAULT_MIN_TORUS_MAJOR_RATIO = 1.2

# The three disproof gates default to *not applied* rather than to a permissive
# number.  A number would be a threshold nobody declared, and "absent" would
# then be indistinguishable from "measured and passed"; ``None`` says plainly
# that the gate did not run, and ``support["checked"]`` says which ones did.
# Callers that predate the gates keep their previous behaviour, and U2 -- the
# only production caller -- declares all three.
DEFAULT_MIN_SUPPORT_SPAN: float | None = None
DEFAULT_RESIDUAL_STRUCTURE_TOLERANCE: float | None = None
DEFAULT_HELDOUT_RESIDUAL_RATIO: float | None = None

# A residual is only ever compared against a *relative* gate, so ratios need a
# floor to stay finite on an exact synthetic fit.  This is float noise, not a
# decision threshold: no verdict turns on its value, it only stops 0/0.
_ZERO_RESIDUAL_FLOOR_RATIO = 1e-9


# --------------------------------------------------------------------------
# vector and linear-algebra kernel
# --------------------------------------------------------------------------


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(a: Vec3, k: float) -> Vec3:
    return (a[0] * k, a[1] * k, a[2] * k)


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _length(a: Vec3) -> float:
    return math.sqrt(_dot(a, a))


def _unit(a: Vec3) -> Vec3 | None:
    n = _length(a)
    if not math.isfinite(n) or n < 1e-15:
        return None
    return (a[0] / n, a[1] / n, a[2] / n)


def _canonical_direction(a: Vec3) -> Vec3:
    """Fix the arbitrary sign of an unoriented direction, identically everywhere.

    Vertices carry no orientation, so a fitted normal or axis is only defined up
    to sign.  Flipping so the dominant component is positive makes the value
    stable across runs, which matters because these directions are later keyed
    and compared.
    """
    dominant = max(range(3), key=lambda i: (abs(a[i]), -i))
    return _scale(a, -1.0) if a[dominant] < 0.0 else a


def _frame(direction: Vec3) -> tuple[Vec3, Vec3]:
    """Two unit vectors spanning the plane perpendicular to ``direction``."""
    least = min(range(3), key=lambda i: (abs(direction[i]), i))
    seed: Vec3 = (1.0 if least == 0 else 0.0, 1.0 if least == 1 else 0.0, 1.0 if least == 2 else 0.0)
    u = _unit(_cross(direction, seed))
    if u is None:  # pragma: no cover - direction is always a unit vector here
        raise ValueError("cannot build a frame from a degenerate direction")
    return u, _cross(direction, u)


def _solve(matrix: Sequence[Sequence[float]], rhs: Sequence[float]) -> tuple[float, ...] | None:
    """Gauss-Jordan with partial pivoting; ``None`` when the system is singular.

    Callers centre and scale their data first, so the pivot floor below is a
    meaningful conditioning test rather than an absolute magnitude guess.
    """
    n = len(rhs)
    rows = [list(matrix[i]) + [rhs[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(rows[r][col]))
        if abs(rows[pivot][col]) < 1e-12:
            return None
        rows[col], rows[pivot] = rows[pivot], rows[col]
        pv = rows[col][col]
        for r in range(n):
            if r == col:
                continue
            factor = rows[r][col] / pv
            if factor == 0.0:
                continue
            for c in range(col, n + 1):
                rows[r][c] -= factor * rows[col][c]
    out = tuple(rows[i][n] / rows[i][i] for i in range(n))
    return out if all(math.isfinite(v) for v in out) else None


def _symmetric_eigen(matrix: Sequence[Sequence[float]]) -> tuple[tuple[float, ...], tuple[Vec3, ...]]:
    """Cyclic Jacobi on a symmetric 3x3; eigenpairs sorted by ascending value."""
    a = [list(row) for row in matrix]
    v = [[1.0 if i == j else 0.0 for j in range(3)] for i in range(3)]
    for _ in range(64):
        off = abs(a[0][1]) + abs(a[0][2]) + abs(a[1][2])
        if off <= 1e-18:
            break
        for p, q in ((0, 1), (0, 2), (1, 2)):
            apq = a[p][q]
            if abs(apq) <= 1e-20:
                continue
            theta = (a[q][q] - a[p][p]) / (2.0 * apq)
            t = math.copysign(1.0, theta) / (abs(theta) + math.sqrt(theta * theta + 1.0))
            c = 1.0 / math.sqrt(t * t + 1.0)
            s = t * c
            for k in range(3):
                akp, akq = a[k][p], a[k][q]
                a[k][p], a[k][q] = c * akp - s * akq, s * akp + c * akq
            for k in range(3):
                apk, aqk = a[p][k], a[q][k]
                a[p][k], a[q][k] = c * apk - s * aqk, s * apk + c * aqk
            for k in range(3):
                vkp, vkq = v[k][p], v[k][q]
                v[k][p], v[k][q] = c * vkp - s * vkq, s * vkp + c * vkq
    pairs = sorted(
        ((a[i][i], (v[0][i], v[1][i], v[2][i])) for i in range(3)),
        key=lambda kv: kv[0],
    )
    vectors: list[Vec3] = []
    for _, raw in pairs:
        unit = _unit(raw)
        vectors.append(unit if unit is not None else (0.0, 0.0, 1.0))
    return tuple(p[0] for p in pairs), tuple(vectors)


def _centroid(points: Sequence[Vec3]) -> Vec3:
    n = float(len(points))
    return (
        sum(p[0] for p in points) / n,
        sum(p[1] for p in points) / n,
        sum(p[2] for p in points) / n,
    )


def _covariance(points: Sequence[Vec3], centre: Vec3) -> list[list[float]]:
    m = [[0.0] * 3 for _ in range(3)]
    for p in points:
        w = _sub(p, centre)
        for i in range(3):
            for j in range(3):
                m[i][j] += w[i] * w[j]
    n = float(len(points))
    return [[m[i][j] / n for j in range(3)] for i in range(3)]


def _bbox(points: Sequence[Vec3]) -> tuple[Vec3, Vec3]:
    lo = (min(p[0] for p in points), min(p[1] for p in points), min(p[2] for p in points))
    hi = (max(p[0] for p in points), max(p[1] for p in points), max(p[2] for p in points))
    return lo, hi


def _extent(points: Sequence[Vec3]) -> float:
    lo, hi = _bbox(points)
    return _length(_sub(hi, lo))


def _within_bounds(point: Vec3, box: tuple[Vec3, Vec3], margin: float) -> bool:
    lo, hi = box
    return all(lo[i] - margin <= point[i] <= hi[i] + margin for i in range(3))


def _rms(values: Iterable[float]) -> float:
    seq = list(values)
    if not seq:
        return math.inf
    return math.sqrt(sum(v * v for v in seq) / len(seq))


def _fit_circle_2d(xs: Sequence[float], ys: Sequence[float]) -> tuple[float, float, float] | None:
    """Least-squares circle through planar points; ``None`` when degenerate.

    A perfectly straight run makes this system singular, which is the honest
    answer: there is no circle to report, so none is reported.
    """
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    scale = max(max(abs(x - mx) for x in xs), max(abs(y - my) for y in ys), 1e-12)
    px = [(x - mx) / scale for x in xs]
    py = [(y - my) / scale for y in ys]
    z = [x * x + y * y for x, y in zip(px, py)]
    sxx = sum(x * x for x in px)
    syy = sum(y * y for y in py)
    sxy = sum(x * y for x, y in zip(px, py))
    sx = sum(px)
    sy = sum(py)
    sol = _solve(
        [[sxx, sxy, sx], [sxy, syy, sy], [sx, sy, float(n)]],
        [sum(x * zz for x, zz in zip(px, z)), sum(y * zz for y, zz in zip(py, z)), sum(z)],
    )
    if sol is None:
        return None
    cx, cy = sol[0] / 2.0, sol[1] / 2.0
    r_sq = sol[2] + cx * cx + cy * cy
    if not math.isfinite(r_sq) or r_sq <= 0.0:
        return None
    return cx * scale + mx, cy * scale + my, math.sqrt(r_sq) * scale


def _linfit(ts: Sequence[float], ys: Sequence[float]) -> tuple[float, float] | None:
    """Least-squares ``y = intercept + slope * t``; ``None`` when t is constant."""
    n = len(ts)
    if n < 2:
        return None
    tbar = sum(ts) / n
    ybar = sum(ys) / n
    stt = sum((t - tbar) ** 2 for t in ts)
    if stt <= 1e-18:
        return None
    slope = sum((t - tbar) * (y - ybar) for t, y in zip(ts, ys)) / stt
    intercept = ybar - slope * tbar
    if not (math.isfinite(slope) and math.isfinite(intercept)):
        return None
    return intercept, slope


# --------------------------------------------------------------------------
# input validation
# --------------------------------------------------------------------------


def _as_point(raw: Any, label: str) -> Vec3:
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence) or len(raw) != 3:
        raise ValueError(f"{label} must be a sequence of three coordinates.")
    out = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{label} coordinates must be finite numbers.")
        out.append(float(value))
    return (out[0], out[1], out[2])


def _as_points(raw: Any, label: str, minimum: int) -> tuple[Vec3, ...]:
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise ValueError(f"{label} must be a sequence of points.")
    points = tuple(_as_point(p, f"{label}[{i}]") for i, p in enumerate(raw))
    if len(points) < minimum:
        raise ValueError(f"{label} needs at least {minimum} points; got {len(points)}.")
    return points


def _as_direction(raw: Any, label: str) -> Vec3:
    direction = _unit(_as_point(raw, label))
    if direction is None:
        raise ValueError(f"{label} must be a non-zero direction.")
    return direction


def _as_tolerance(raw: Any, label: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw) or raw <= 0.0:
        raise ValueError(f"{label} must be a positive finite number.")
    return float(raw)


# --------------------------------------------------------------------------
# 1. plane-mesh section extraction
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SectionPolyline:
    """An ordered run of section points.

    A closed loop does *not* repeat its first point; ``closed`` says it wraps.
    """

    points: tuple[Vec3, ...]
    closed: bool

    def to_dict(self) -> dict[str, Any]:
        return {"points": [list(p) for p in self.points], "closed": self.closed}


@dataclass(frozen=True, slots=True)
class MeshSection:
    """The full result of one plane-mesh intersection, degeneracies included."""

    polylines: tuple[SectionPolyline, ...]
    coplanar_triangles: int
    vertex_touches: int
    junctions: tuple[Vec3, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "polylines": [p.to_dict() for p in self.polylines],
            "coplanar_triangles": self.coplanar_triangles,
            "vertex_touches": self.vertex_touches,
            "junctions": [list(p) for p in self.junctions],
        }


def section_mesh(
    vertices: Any,
    triangles: Any,
    plane_point: Any,
    plane_normal: Any,
    *,
    tolerance: float = 1e-9,
) -> MeshSection:
    """Intersect a triangle mesh with a plane and chain the result into polylines.

    The awkward cases are handled explicitly rather than silently:

    * **Coplanar triangle** (all three vertices within ``tolerance`` of the
      plane): its interior edges — those shared with another coplanar triangle —
      contribute nothing, and only its boundary edges become section segments.
      That reproduces the face outline instead of a scribble of interior edges.
    * **Single-vertex touch** (one vertex on the plane, the other two on the same
      side): produces no segment, because the intersection is a point and a
      zero-length segment is not geometry.  It is counted in ``vertex_touches``.
    * **Junction** (a node where three or more segments meet, e.g. a plane
      containing an interior edge of a T-shaped body): chaining *stops* there.
      Guessing which branch continues the curve is exactly the kind of invention
      this workflow refuses, so each incident branch becomes its own polyline
      and the junction point is reported.
    * **Open vs closed**: a run whose two ends coincide is returned with
      ``closed=True`` and no repeated point; everything else is open.

    Segment endpoints are keyed by *topology* — a vertex index, or a sorted
    edge-index pair — never by rounded coordinates.  Two triangles sharing an
    edge therefore agree on the crossing point exactly, and the same key that
    identifies an endpoint is the one used to look it up when chaining.
    """
    verts = _as_points(vertices, "vertices", 3)
    tol = _as_tolerance(tolerance, "tolerance")
    origin = _as_point(plane_point, "plane_point")
    normal = _as_direction(plane_normal, "plane_normal")

    if isinstance(triangles, (str, bytes)) or not isinstance(triangles, Sequence):
        raise ValueError("triangles must be a sequence of index triples.")
    faces: list[tuple[int, int, int]] = []
    for index, raw in enumerate(triangles):
        if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence) or len(raw) != 3:
            raise ValueError(f"triangles[{index}] must be a triple of vertex indices.")
        tri = []
        for value in raw:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"triangles[{index}] must contain integer vertex indices.")
            if not 0 <= value < len(verts):
                raise ValueError(f"triangles[{index}] references vertex {value}, which does not exist.")
            tri.append(value)
        if len(set(tri)) != 3:
            raise ValueError(f"triangles[{index}] repeats a vertex index; it is not a triangle.")
        faces.append((tri[0], tri[1], tri[2]))

    offset = _dot(normal, origin)
    signed = [_dot(normal, v) - offset for v in verts]
    side = [0 if abs(d) <= tol else (1 if d > 0.0 else -1) for d in signed]

    coords: dict[tuple, Vec3] = {}

    def vertex_key(i: int) -> tuple:
        key = ("v", i)
        coords.setdefault(key, verts[i])
        return key

    def edge_key(i: int, j: int) -> tuple:
        lo, hi = (i, j) if i < j else (j, i)
        key = ("e", lo, hi)
        if key not in coords:
            # Computed once from the canonical (lo, hi) order, so every triangle
            # sharing this edge sees bit-identical coordinates.
            span = signed[hi] - signed[lo]
            t = 0.5 if span == 0.0 else -signed[lo] / span
            coords[key] = _add(verts[lo], _scale(_sub(verts[hi], verts[lo]), t))
        return key

    coplanar: list[tuple[int, int, int]] = []
    segments: dict[frozenset, tuple[tuple, tuple]] = {}
    vertex_touches = 0

    def emit(a: tuple, b: tuple) -> None:
        if a != b:
            segments.setdefault(frozenset((a, b)), (a, b))

    for tri in faces:
        s = [side[i] for i in tri]
        on = [tri[k] for k in range(3) if s[k] == 0]
        if len(on) == 3:
            coplanar.append(tri)
            continue
        if len(on) == 2:
            # An edge lying in the plane: emit it.  If the plane merely grazes the
            # surface here the section is a real, if degenerate, curve; dedup by
            # endpoint pair keeps a shared edge from being emitted twice.
            emit(vertex_key(on[0]), vertex_key(on[1]))
            continue
        if len(on) == 1:
            others = [tri[k] for k in range(3) if s[k] != 0]
            if side[others[0]] == side[others[1]]:
                vertex_touches += 1
                continue
            emit(vertex_key(on[0]), edge_key(others[0], others[1]))
            continue
        if s[0] == s[1] == s[2]:
            continue
        crossings = [
            edge_key(tri[k], tri[(k + 1) % 3])
            for k in range(3)
            if side[tri[k]] != side[tri[(k + 1) % 3]]
        ]
        if len(crossings) == 2:
            emit(crossings[0], crossings[1])

    if coplanar:
        edge_use: dict[frozenset, int] = {}
        for tri in coplanar:
            for k in range(3):
                edge_use[frozenset((tri[k], tri[(k + 1) % 3]))] = (
                    edge_use.get(frozenset((tri[k], tri[(k + 1) % 3])), 0) + 1
                )
        for edge, count in edge_use.items():
            if count == 1:
                a, b = tuple(edge)
                emit(vertex_key(a), vertex_key(b))

    polylines, junctions = _chain_segments(segments, coords)
    return MeshSection(
        polylines=tuple(polylines),
        coplanar_triangles=len(coplanar),
        vertex_touches=vertex_touches,
        junctions=tuple(junctions),
    )


def _chain_segments(
    segments: Mapping[frozenset, tuple[tuple, tuple]], coords: Mapping[tuple, Vec3]
) -> tuple[list[SectionPolyline], list[Vec3]]:
    ordered = [segments[key] for key in sorted(segments, key=lambda k: sorted(map(repr, k)))]
    adjacency: dict[tuple, list[tuple[tuple, int]]] = {}
    for index, (a, b) in enumerate(ordered):
        adjacency.setdefault(a, []).append((b, index))
        adjacency.setdefault(b, []).append((a, index))

    junction_keys = sorted((k for k, adj in adjacency.items() if len(adj) >= 3), key=repr)
    ends = sorted((k for k, adj in adjacency.items() if len(adj) == 1), key=repr)
    used: set[int] = set()
    runs: list[list[tuple]] = []

    def walk(start: tuple, first: int) -> list[tuple]:
        run = [start]
        current = start
        seg = first
        while True:
            used.add(seg)
            a, b = ordered[seg]
            nxt = b if a == current else a
            run.append(nxt)
            if nxt in junction_keys or nxt == run[0]:
                return run
            options = [s for _, s in adjacency[nxt] if s not in used]
            if len(options) != 1:
                return run
            current = nxt
            seg = options[0]

    for start in ends + junction_keys:
        for _, seg in adjacency[start]:
            if seg not in used:
                runs.append(walk(start, seg))
    for index, (a, _b) in enumerate(ordered):
        if index not in used:
            runs.append(walk(a, index))

    polylines: list[SectionPolyline] = []
    for run in runs:
        closed = len(run) > 2 and run[0] == run[-1]
        keys = run[:-1] if closed else run
        polylines.append(
            SectionPolyline(points=tuple(coords[k] for k in keys), closed=closed)
        )
    return polylines, [coords[k] for k in junction_keys]


# --------------------------------------------------------------------------
# 2. segment classification
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SketchEntity:
    """One fitted run of a section polyline, carrying enough to build a sketch.

    ``start``/``end`` are the polyline's own points, so consecutive entities
    share endpoints exactly and a coincident constraint is trivially satisfiable.
    ``center``/``radius``/``mid`` are present only for arcs and circles — a line
    reports them absent rather than carrying a fabricated centre.
    """

    kind: str
    start: Vec3
    end: Vec3
    residual: float
    point_count: int
    center: Vec3 | None = None
    radius: float | None = None
    mid: Vec3 | None = None

    def __post_init__(self) -> None:
        if not _in_closed_set(self.kind, ENTITY_KINDS):
            raise ValueError(f"kind must be one of {', '.join(sorted(ENTITY_KINDS))}.")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "kind": self.kind,
            "start": list(self.start),
            "end": list(self.end),
            "residual": self.residual,
            "point_count": self.point_count,
        }
        if self.center is not None:
            out["center"] = list(self.center)
        if self.radius is not None:
            out["radius"] = self.radius
        if self.mid is not None:
            out["mid"] = list(self.mid)
        return out


def _line_residual(points: Sequence[Vec3]) -> float:
    if len(points) < 2:
        return math.inf
    centre = _centroid(points)
    _values, vectors = _symmetric_eigen(_covariance(points, centre))
    direction = vectors[2]
    worst = 0.0
    for p in points:
        w = _sub(p, centre)
        worst = max(worst, _length(_sub(w, _scale(direction, _dot(w, direction)))))
    return worst


def _plane_basis(points: Sequence[Vec3], normal: Vec3 | None) -> tuple[Vec3, Vec3, Vec3]:
    if normal is None:
        centre = _centroid(points)
        _values, vectors = _symmetric_eigen(_covariance(points, centre))
        normal = vectors[0]
    u, v = _frame(normal)
    return normal, u, v


def _arc_fit(points: Sequence[Vec3], u: Vec3, v: Vec3) -> tuple[Vec3, float, float] | None:
    if len(points) < 4:
        return None
    origin = points[0]
    xs = [_dot(_sub(p, origin), u) for p in points]
    ys = [_dot(_sub(p, origin), v) for p in points]
    circle = _fit_circle_2d(xs, ys)
    if circle is None:
        return None
    cx, cy, r = circle
    centre = _add(origin, _add(_scale(u, cx), _scale(v, cy)))
    worst = max(abs(math.hypot(x - cx, y - cy) - r) for x, y in zip(xs, ys))
    if not math.isfinite(worst):
        return None
    return centre, r, worst


def classify_polyline(
    points: Any,
    *,
    tolerance: float,
    closed: bool = False,
    normal: Any = None,
) -> tuple[SketchEntity, ...]:
    """Split a section polyline into line and arc runs within ``tolerance``.

    Greedy longest-run: at each position take the longest line run, then the
    longest arc run, and keep whichever covers strictly more points (line wins
    ties, so a straight stretch never becomes a very large arc).  ``residual`` is
    the worst deviation of that run from its fitted entity.

    A closed polyline is first rotated to start at its sharpest corner, so a
    square section yields four lines rather than five; a closed loop that fits a
    single circle within tolerance is reported as one ``circle`` entity.
    """
    pts = list(_as_points(points, "points", 2))
    tol = _as_tolerance(tolerance, "tolerance")
    plane_normal = None if normal is None else _as_direction(normal, "normal")

    if closed:
        if len(pts) < 3:
            raise ValueError("a closed polyline needs at least three points.")
        _n, u, v = _plane_basis(pts, plane_normal)
        whole = _arc_fit(pts, u, v)
        if whole is not None and whole[2] <= tol:
            centre, radius, residual = whole
            return (
                SketchEntity(
                    kind="circle",
                    start=pts[0],
                    end=pts[0],
                    residual=residual,
                    point_count=len(pts),
                    center=centre,
                    radius=radius,
                    mid=pts[len(pts) // 2],
                ),
            )
        pivot = _sharpest_corner(pts)
        pts = pts[pivot:] + pts[:pivot] + [pts[pivot]]

    _n, u, v = _plane_basis(pts, plane_normal)
    entities: list[SketchEntity] = []
    i = 0
    n = len(pts)
    # ponytail: O(n^2) greedy re-fits every extension; a incremental-moment fit
    # if section polylines ever get long enough for it to matter.
    while i < n - 1:
        line_end = i + 1
        while line_end + 1 < n and _line_residual(pts[i : line_end + 2]) <= tol:
            line_end += 1
        arc_end = i
        arc_best: tuple[Vec3, float, float] | None = None
        probe = i + 3
        while probe < n:
            candidate = _arc_fit(pts[i : probe + 1], u, v)
            if candidate is None or candidate[2] > tol:
                break
            arc_end, arc_best = probe, candidate
            probe += 1
        if arc_best is not None and arc_end > line_end:
            centre, radius, residual = arc_best
            entities.append(
                SketchEntity(
                    kind="arc",
                    start=pts[i],
                    end=pts[arc_end],
                    residual=residual,
                    point_count=arc_end - i + 1,
                    center=centre,
                    radius=radius,
                    mid=pts[(i + arc_end) // 2],
                )
            )
            i = arc_end
            continue
        entities.append(
            SketchEntity(
                kind="line",
                start=pts[i],
                end=pts[line_end],
                residual=_line_residual(pts[i : line_end + 1]),
                point_count=line_end - i + 1,
            )
        )
        i = line_end
    return tuple(entities)


def _sharpest_corner(points: Sequence[Vec3]) -> int:
    n = len(points)
    best_index, best_turn = 0, -1.0
    for k in range(n):
        a = _unit(_sub(points[k], points[(k - 1) % n]))
        b = _unit(_sub(points[(k + 1) % n], points[k]))
        if a is None or b is None:
            continue
        turn = 1.0 - _dot(a, b)
        if turn > best_turn + 1e-12:
            best_index, best_turn = k, turn
    return best_index


# --------------------------------------------------------------------------
# 3. primitive fitting per face group
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PrimitiveFit:
    """A least-squares fit and its verdict.

    ``relative_residual`` divides the RMS deviation by the sampled *extent* — the
    bounding-box diagonal of the face group — deliberately, not by the fitted
    radius.  Dividing by the radius is what lets a near-flat strip score a
    beautiful relative residual on a metre-wide circle.
    """

    kind: str
    accepted: bool
    rms_residual: float
    relative_residual: float
    extent: float
    parameters: dict[str, Any] = field(default_factory=dict)
    rejection: str | None = None
    #: Everything the gates *measured*, so a reader can see why a fit was
    #: accepted rather than only that it was.  ``checked`` lists the gates that
    #: ran and passed, appended by the block that ran each one -- a gate that
    #: raised or was never requested leaves no entry.
    support: dict[str, Any] = field(default_factory=dict)
    #: One-sigma uncertainty per reported parameter, in the caller's own length
    #: unit (angles in degrees).  Empty when it was not computed -- and an empty
    #: mapping must be read as *unknown*, never as zero: a consumer that treats a
    #: missing sigma as certainty is inventing precision.
    uncertainty: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _in_closed_set(self.kind, PRIMITIVE_KINDS):
            raise ValueError(f"kind must be one of {', '.join(sorted(PRIMITIVE_KINDS))}.")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "kind": self.kind,
            "accepted": self.accepted,
            "rms_residual": self.rms_residual,
            "relative_residual": self.relative_residual,
            "extent": self.extent,
            "parameters": {
                k: (list(v) if isinstance(v, tuple) else v) for k, v in self.parameters.items()
            },
        }
        if self.rejection is not None:
            out["rejection"] = self.rejection
        if self.support:
            out["support"] = {
                k: (list(v) if isinstance(v, tuple) else v) for k, v in self.support.items()
            }
        if self.uncertainty:
            out["uncertainty"] = dict(self.uncertainty)
        return out


def _rejected(
    kind: str, extent: float, reason: str, support: Mapping[str, Any] | None = None
) -> PrimitiveFit:
    return PrimitiveFit(
        kind=kind,
        accepted=False,
        rms_residual=math.inf,
        relative_residual=math.inf,
        extent=extent,
        parameters={},
        rejection=reason,
        support=dict(support or {}),
    )


def _residuals(kind: str, parameters: Mapping[str, Any], points: Sequence[Vec3]) -> list[float]:
    """Signed distance from each point to the primitive's surface.

    Parameters are read by subscript, never by ``.get``: a fit missing the
    parameter its own kind requires is a bug, and it must raise rather than
    quietly become "this point is not on the surface".
    """
    if kind == "plane":
        normal, offset = parameters["normal"], parameters["offset"]
        return [_dot(normal, p) - offset for p in points]
    if kind == "sphere":
        centre, radius = parameters["center"], parameters["radius"]
        return [_length(_sub(p, centre)) - radius for p in points]
    if kind == "cylinder":
        anchor = parameters["axis_point"]
        axis = parameters["axis_direction"]
        radius = parameters["radius"]
        out = []
        for p in points:
            w = _sub(p, anchor)
            out.append(_length(_sub(w, _scale(axis, _dot(w, axis)))) - radius)
        return out
    if kind == "torus":
        centre = parameters["center"]
        axis = parameters["axis_direction"]
        major, minor = parameters["radius"], parameters["minor_radius"]
        out = []
        for p in points:
            w = _sub(p, centre)
            t = _dot(w, axis)
            rho = _length(_sub(w, _scale(axis, t)))
            out.append(math.hypot(rho - major, t) - minor)
        return out
    apex = parameters["apex"]
    axis = parameters["axis_direction"]
    half_angle = math.radians(parameters["half_angle_deg"])
    cos_a, sin_a = math.cos(half_angle), math.sin(half_angle)
    out = []
    for p in points:
        w = _sub(p, apex)
        t = _dot(w, axis)
        rho = _length(_sub(w, _scale(axis, t)))
        out.append(rho * cos_a - t * sin_a)
    return out


def _surface_normal(kind: str, parameters: Mapping[str, Any], point: Vec3) -> Vec3 | None:
    """Unit surface normal of the primitive nearest ``point``; ``None`` on the axis.

    Unoriented: the sign is whatever the parameters give.  Callers compare with
    ``abs(dot(...))`` because a mesh triangle's winding is not evidence here.
    """
    if kind == "plane":
        return parameters["normal"]
    if kind == "sphere":
        return _unit(_sub(point, parameters["center"]))
    if kind == "cylinder":
        anchor = parameters["axis_point"]
        axis = parameters["axis_direction"]
        w = _sub(point, anchor)
        return _unit(_sub(w, _scale(axis, _dot(w, axis))))
    if kind == "torus":
        # The normal points away from the nearest point on the core circle.
        centre = parameters["center"]
        axis = parameters["axis_direction"]
        major = parameters["radius"]
        w = _sub(point, centre)
        radial = _unit(_sub(w, _scale(axis, _dot(w, axis))))
        if radial is None:
            return None
        return _unit(_sub(w, _scale(radial, major)))
    apex = parameters["apex"]
    axis = parameters["axis_direction"]
    half_angle = math.radians(parameters["half_angle_deg"])
    w = _sub(point, apex)
    radial = _unit(_sub(w, _scale(axis, _dot(w, axis))))
    if radial is None:
        return None
    return _unit(
        _sub(_scale(radial, math.cos(half_angle)), _scale(axis, math.sin(half_angle)))
    )


def primitive_residuals(fit: PrimitiveFit, points: Any) -> tuple[float, ...]:
    """Public signed residuals of ``points`` against an accepted fit."""
    if not fit.accepted:
        raise ValueError("a rejected fit has no surface to measure residuals against.")
    return tuple(_residuals(fit.kind, fit.parameters, _as_points(points, "points", 1)))


def primitive_normal(fit: PrimitiveFit, point: Any) -> Vec3 | None:
    """Public unit surface normal of an accepted fit at ``point``."""
    if not fit.accepted:
        raise ValueError("a rejected fit has no surface to take a normal from.")
    return _surface_normal(fit.kind, fit.parameters, _as_point(point, "point"))


def _raw_fit(
    points: Sequence[Vec3],
    kind: str,
    extent: float,
    min_taper_ratio: float,
    min_torus_major_ratio: float = DEFAULT_MIN_TORUS_MAJOR_RATIO,
    seed_axis: Vec3 | None = None,
) -> PrimitiveFit:
    """Least squares only: no gates, so the gates can call it without recursing."""
    if kind == "plane":
        return _fit_plane(points, extent)
    if kind == "sphere":
        return _fit_sphere(points, extent)
    if kind == "cylinder":
        return _fit_cylinder(points, extent, seed_axis)
    if kind == "torus":
        return _fit_torus(points, extent, min_torus_major_ratio, seed_axis)
    return _fit_cone(points, extent, min_taper_ratio, seed_axis)


def fit_primitive(
    points: Any,
    kind: str,
    *,
    max_relative_residual: float = DEFAULT_MAX_RELATIVE_RESIDUAL,
    max_radius_ratio: float = DEFAULT_MAX_RADIUS_RATIO,
    bounds_margin_ratio: float = DEFAULT_BOUNDS_MARGIN_RATIO,
    min_taper_ratio: float = DEFAULT_MIN_TAPER_RATIO,
    min_torus_major_ratio: float = DEFAULT_MIN_TORUS_MAJOR_RATIO,
    seed_axis: Any = None,
    min_support_span: float | None = DEFAULT_MIN_SUPPORT_SPAN,
    residual_structure_tolerance: float | None = DEFAULT_RESIDUAL_STRUCTURE_TOLERANCE,
    heldout_residual_ratio: float | None = DEFAULT_HELDOUT_RESIDUAL_RATIO,
    heldout_seed: int = 0,
) -> PrimitiveFit:
    """Fit one analytic primitive to a face group's vertices, with sanity gates.

    Returns a ``PrimitiveFit`` either way: a fit that fails a gate comes back
    with ``accepted=False`` and a stated ``rejection``, never as a silent
    success and never as a fabricated value.
    """
    if not _in_closed_set(kind, PRIMITIVE_KINDS):
        raise ValueError(f"kind must be one of {', '.join(sorted(PRIMITIVE_KINDS))}.")
    pts = _as_points(points, "points", 4)
    for label, value in (
        ("max_relative_residual", max_relative_residual),
        ("max_radius_ratio", max_radius_ratio),
        ("min_taper_ratio", min_taper_ratio),
        ("min_torus_major_ratio", min_torus_major_ratio),
    ):
        _as_tolerance(value, label)
    if (
        isinstance(bounds_margin_ratio, bool)
        or not isinstance(bounds_margin_ratio, (int, float))
        or not math.isfinite(bounds_margin_ratio)
        or bounds_margin_ratio < 0.0
    ):
        raise ValueError("bounds_margin_ratio must be a non-negative finite number.")

    extent = _extent(pts)
    if extent <= 0.0:
        return _rejected(kind, extent, "the face group has zero extent; there is nothing to fit.")

    for label, value in (
        ("min_support_span", min_support_span),
        ("residual_structure_tolerance", residual_structure_tolerance),
        ("heldout_residual_ratio", heldout_residual_ratio),
    ):
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0.0:
            raise ValueError(f"{label} must be a non-negative finite number when declared.")
    if isinstance(heldout_seed, bool) or not isinstance(heldout_seed, int):
        raise ValueError("heldout_seed must be an integer.")

    axis_hint = None if seed_axis is None else _as_direction(seed_axis, "seed_axis")
    fit = _raw_fit(
        pts, kind, extent, float(min_taper_ratio), float(min_torus_major_ratio), axis_hint
    )
    if not fit.accepted:
        return fit

    return _apply_gates(
        fit,
        pts,
        max_relative_residual=float(max_relative_residual),
        max_radius_ratio=float(max_radius_ratio),
        bounds_margin_ratio=float(bounds_margin_ratio),
        min_taper_ratio=float(min_taper_ratio),
        min_torus_major_ratio=float(min_torus_major_ratio),
        min_support_span=None if min_support_span is None else float(min_support_span),
        residual_structure_tolerance=(
            None if residual_structure_tolerance is None else float(residual_structure_tolerance)
        ),
        heldout_residual_ratio=(
            None if heldout_residual_ratio is None else float(heldout_residual_ratio)
        ),
        heldout_seed=int(heldout_seed),
    )


def _apply_gates(
    fit: PrimitiveFit,
    points: Sequence[Vec3],
    *,
    max_relative_residual: float,
    max_radius_ratio: float,
    bounds_margin_ratio: float,
    min_taper_ratio: float = DEFAULT_MIN_TAPER_RATIO,
    min_torus_major_ratio: float = DEFAULT_MIN_TORUS_MAJOR_RATIO,
    min_support_span: float | None = None,
    residual_structure_tolerance: float | None = None,
    heldout_residual_ratio: float | None = None,
    heldout_seed: int = 0,
) -> PrimitiveFit:
    extent = fit.extent
    # Appended by the block that ran each gate, after it passed.  A gate that
    # raises, or that no caller declared, leaves no entry -- so the list can
    # never claim a check that did not happen.
    checked: list[str] = []
    support: dict[str, Any] = {"checked": checked}

    radius = fit.parameters.get("radius")
    if isinstance(radius, float) and radius > max_radius_ratio * extent:
        return _rejected(
            fit.kind,
            extent,
            f"fitted radius {radius:.6g} exceeds {max_radius_ratio:g}x the sampled extent "
            f"{extent:.6g}; a near-flat face group fits an enormous circle, so this is rejected "
            "rather than reported.",
            support,
        )
    checked.append("radius-ratio")

    box = _bbox(points)
    margin = bounds_margin_ratio * extent
    for label in ("center", "apex", "axis_point"):
        anchor = fit.parameters.get(label)
        if isinstance(anchor, tuple) and not _within_bounds(anchor, box, margin):
            return _rejected(
                fit.kind,
                extent,
                f"fitted {label} lies outside the part bounds by more than "
                f"{bounds_margin_ratio:g}x the sampled extent {extent:.6g}.",
                support,
            )
    checked.append("bounds-margin")

    if fit.relative_residual > max_relative_residual:
        return _rejected(
            fit.kind,
            extent,
            f"relative residual {fit.relative_residual:.6g} exceeds the gate "
            f"{max_relative_residual:g}.",
            support,
        )
    checked.append("relative-residual")

    simpler = _SIMPLER_KINDS[fit.kind]
    for other in simpler:
        rival = _raw_fit(points, other, extent, min_taper_ratio, min_torus_major_ratio)
        if rival.accepted and rival.relative_residual <= max_relative_residual:
            return _rejected(
                fit.kind,
                extent,
                f"a {other} already explains this face group to within the gate "
                f"{max_relative_residual:g} (relative residual "
                f"{rival.relative_residual:.6g}); a richer primitive through points a simpler one "
                "already fits is an artefact of the fit, not a feature of the part.",
                support,
            )
    if simpler:
        checked.append("simpler-primitive")

    # --- the three disproof gates (KTD6) ------------------------------------
    # A passing residual is not evidence.  Each of these tries to *falsify* the
    # fit, and each runs only when the caller declared its threshold.

    if min_support_span is not None:
        span = _support_span(fit, points)
        support["span"] = span
        support["span_measure"] = _SPAN_MEASURE[fit.kind]
        if span < min_support_span:
            return _rejected(
                fit.kind,
                extent,
                f"supporting points span only {span:.4g} of this {fit.kind}'s "
                f"{_SPAN_MEASURE[fit.kind]}, below the declared minimum {min_support_span:g}; a "
                "primitive fitted through a narrow sliver of surface is not evidence of that "
                "primitive however small its residual.",
                support,
            )
        checked.append("support-span")

    if residual_structure_tolerance is not None:
        structure = _residual_structure(fit, points)
        support["residual_structure"] = structure
        if structure > residual_structure_tolerance:
            return _rejected(
                fit.kind,
                extent,
                f"residuals binned along this {fit.kind}'s own parameterization have a per-bin "
                f"mean reaching {structure:.6g} of the sampled extent, above the declared "
                f"{residual_structure_tolerance:g}; a systematically signed residual pattern is "
                "the wrong primitive with a flattering RMS.",
                support,
            )
        checked.append("residual-structure")

    if heldout_residual_ratio is not None:
        held = _heldout_residual(fit, points, min_taper_ratio, heldout_seed)
        if held is None:
            return _rejected(
                fit.kind,
                extent,
                f"refitting this {fit.kind} on a random half of its points produced no fit at "
                "all, so the fit does not survive being asked for half the evidence.",
                support,
            )
        heldout_rms, in_sample_rms = held
        floor = _ZERO_RESIDUAL_FLOOR_RATIO * extent
        ratio = heldout_rms / max(in_sample_rms, floor)
        support["heldout_rms"] = heldout_rms
        support["heldout_in_sample_rms"] = in_sample_rms
        support["heldout_ratio"] = ratio
        if ratio > heldout_residual_ratio:
            return _rejected(
                fit.kind,
                extent,
                f"held-out residual {heldout_rms:.6g} is {ratio:.4g}x the in-sample residual "
                f"{in_sample_rms:.6g}, above the declared {heldout_residual_ratio:g}; the fit is "
                "over-parameterized for the evidence.",
                support,
            )
        checked.append("heldout-residual")

    return PrimitiveFit(
        kind=fit.kind,
        accepted=True,
        rms_residual=fit.rms_residual,
        relative_residual=fit.relative_residual,
        extent=fit.extent,
        parameters=dict(fit.parameters),
        support=support,
    )


# What ``support["span"]`` is a fraction *of*, per kind.  A single number would
# be meaningless without it, and the three measures are genuinely different.
_SPAN_MEASURE = {
    "plane": "footprint aspect ratio (narrow side over wide side)",
    "sphere": "sampled extent over the fitted diameter",
    "cylinder": "angular sweep about the fitted axis",
    "cone": "angular sweep about the fitted axis",
    "torus": "angular sweep about the fitted axis",
}

#: The parameter naming each kind's axis anchor.  Absent for plane and sphere,
#: which have no axis.
_AXIS_ANCHOR = {"cylinder": "axis_point", "cone": "apex", "torus": "center"}


def _support_span(fit: PrimitiveFit, points: Sequence[Vec3]) -> float:
    """How much of the primitive the supporting points actually cover, in [0, 1]."""
    if fit.kind == "plane":
        # A sliver constrains the normal about its own long axis not at all, so
        # aspect ratio -- not area -- is what says whether a plane is supported.
        u, v = _frame(fit.parameters["normal"])
        us = [_dot(p, u) for p in points]
        vs = [_dot(p, v) for p in points]
        du, dv = max(us) - min(us), max(vs) - min(vs)
        wide = max(du, dv)
        return 0.0 if wide <= 0.0 else min(du, dv) / wide
    if fit.kind == "sphere":
        diameter = 2.0 * fit.parameters["radius"]
        return 0.0 if diameter <= 0.0 else min(1.0, _extent(points) / diameter)
    anchor = fit.parameters[_AXIS_ANCHOR[fit.kind]]
    axis = fit.parameters["axis_direction"]
    u, v = _frame(axis)
    angles = sorted(
        math.atan2(_dot(_sub(p, anchor), v), _dot(_sub(p, anchor), u)) for p in points
    )
    if len(angles) < 2:
        return 0.0
    gaps = [angles[i + 1] - angles[i] for i in range(len(angles) - 1)]
    gaps.append(angles[0] + 2.0 * math.pi - angles[-1])
    return max(0.0, 1.0 - max(gaps) / (2.0 * math.pi))


def _structure_stations(fit: PrimitiveFit, points: Sequence[Vec3]) -> list[list[float]]:
    """Scalar coordinates along the primitive's *own* parameterization.

    Binning residuals along a global axis would mostly measure how the part is
    oriented.  Binning along the primitive's own coordinates is what makes a
    systematic pattern -- the signature of the wrong primitive -- visible.
    """
    if fit.kind == "plane":
        u, v = _frame(fit.parameters["normal"])
        return [[_dot(p, u) for p in points], [_dot(p, v) for p in points]]
    if fit.kind == "sphere":
        centre = fit.parameters["center"]
        offsets = [_sub(p, centre) for p in points]
        polar = _unit(_centroid(points)) or (0.0, 0.0, 1.0)
        u, v = _frame(polar)
        return [
            [_dot(w, polar) for w in offsets],
            [math.atan2(_dot(w, v), _dot(w, u)) for w in offsets],
        ]
    anchor = fit.parameters[_AXIS_ANCHOR[fit.kind]]
    axis = fit.parameters["axis_direction"]
    u, v = _frame(axis)
    offsets = [_sub(p, anchor) for p in points]
    stations = [
        [_dot(w, axis) for w in offsets],
        [math.atan2(_dot(w, v), _dot(w, u)) for w in offsets],
    ]
    if fit.kind == "torus":
        # A torus also has a tube angle, and that is exactly where a cylinder
        # masquerading as a torus shows its structure.
        major = fit.parameters["radius"]
        stations.append(
            [
                math.atan2(
                    _dot(w, axis), _length(_sub(w, _scale(axis, _dot(w, axis)))) - major
                )
                for w in offsets
            ]
        )
    return stations


def _residual_structure(fit: PrimitiveFit, points: Sequence[Vec3]) -> float:
    """Largest per-bin mean residual, relative to the sampled extent.

    Bins hold equal *counts* rather than equal spans, so an unevenly sampled
    surface cannot produce an empty or single-point bin whose "mean" is one
    sample's noise.
    """
    residuals = _residuals(fit.kind, fit.parameters, points)
    n = len(residuals)
    worst = 0.0
    for station in _structure_stations(fit, points):
        order = sorted(range(n), key=lambda i: station[i])
        count = _slab_count(n)
        size = n / count
        for b in range(count):
            lo = int(b * size)
            hi = n if b == count - 1 else int((b + 1) * size)
            if hi - lo < 2:
                continue
            worst = max(worst, abs(sum(residuals[i] for i in order[lo:hi]) / (hi - lo)))
    return worst / fit.extent


def _heldout_residual(
    fit: PrimitiveFit, points: Sequence[Vec3], min_taper_ratio: float, seed: int
) -> tuple[float, float] | None:
    """Refit on a random half, measure on the other; ``None`` when the refit failed.

    The shuffle is seeded by the caller -- U2 seeds it from the region hash --
    so the same region gives the same verdict on every run.
    """
    order = list(range(len(points)))
    random.Random(seed).shuffle(order)
    half = len(order) // 2
    if half < 4:
        return None
    train = [points[i] for i in order[:half]]
    test = [points[i] for i in order[half:]]
    extent = _extent(train)
    if extent <= 0.0:
        return None
    # Deliberately *not* seeded from the full-data fit: an axis handed over from
    # the answer is leakage, and a held-out test that starts from the answer
    # tests nothing.  The refit gets the same data-independent start any first
    # fit would.
    trial = _raw_fit(train, fit.kind, extent, min_taper_ratio)
    if not trial.accepted:
        return None
    return _rms(_residuals(trial.kind, trial.parameters, test)), trial.rms_residual


def _fit_plane(points: Sequence[Vec3], extent: float) -> PrimitiveFit:
    centre = _centroid(points)
    _values, vectors = _symmetric_eigen(_covariance(points, centre))
    normal = _canonical_direction(vectors[0])
    offset = _dot(normal, centre)
    rms = _rms(_dot(normal, p) - offset for p in points)
    return PrimitiveFit(
        kind="plane",
        accepted=True,
        rms_residual=rms,
        relative_residual=rms / extent,
        extent=extent,
        parameters={"normal": normal, "offset": offset, "point_on_plane": centre},
    )


def _fit_sphere(points: Sequence[Vec3], extent: float) -> PrimitiveFit:
    centre0 = _centroid(points)
    scale = extent
    rows = [[0.0] * 4 for _ in range(4)]
    rhs = [0.0] * 4
    for p in points:
        w = _scale(_sub(p, centre0), 1.0 / scale)
        basis = (w[0], w[1], w[2], 1.0)
        z = _dot(w, w)
        for i in range(4):
            rhs[i] += basis[i] * z
            for j in range(4):
                rows[i][j] += basis[i] * basis[j]
    sol = _solve(rows, rhs)
    if sol is None:
        return _rejected("sphere", extent, "the sphere normal equations are singular for this face group.")
    cx, cy, cz = sol[0] / 2.0, sol[1] / 2.0, sol[2] / 2.0
    r_sq = sol[3] + cx * cx + cy * cy + cz * cz
    if not math.isfinite(r_sq) or r_sq <= 0.0:
        return _rejected("sphere", extent, "the fitted sphere has no real radius.")
    centre = _add(centre0, _scale((cx, cy, cz), scale))
    radius = math.sqrt(r_sq) * scale
    rms = _rms(_length(_sub(p, centre)) - radius for p in points)
    return PrimitiveFit(
        kind="sphere",
        accepted=True,
        rms_residual=rms,
        relative_residual=rms / extent,
        extent=extent,
        parameters={"center": centre, "radius": radius},
    )


def _candidate_axes(points: Sequence[Vec3]) -> tuple[Vec3, ...]:
    centre = _centroid(points)
    _values, vectors = _symmetric_eigen(_covariance(points, centre))
    return vectors


def _bin_by_t(
    rows: Sequence[tuple[float, float, float]], count: int
) -> list[list[tuple[float, float, float]]]:
    """Split rows into slabs along the axis, never cutting through a shared t.

    A tessellated body puts many points at exactly the same axial station.
    Splitting such a ring across two slabs makes each slab a fit through two
    different radii, which is what turns an exact taper into a slightly wrong
    one; extending each boundary past its tied value keeps rings intact.
    """
    ordered = sorted(rows, key=lambda r: r[0])
    n = len(ordered)
    size = n // count
    if size < 3:
        return []
    # A ring is "one station" up to the float noise a slightly-tilted trial axis
    # injects, so ties are compared against the span rather than exactly.
    tie = 1e-9 * (ordered[-1][0] - ordered[0][0])
    slabs: list[list[tuple[float, float, float]]] = []
    start = 0
    for k in range(count):
        stop = n if k == count - 1 else (k + 1) * size
        while 0 < stop < n and ordered[stop][0] - ordered[stop - 1][0] <= tie:
            stop += 1
        if stop - start >= 3:
            slabs.append(ordered[start:stop])
        start = max(start, stop)
    return slabs


def _slab_count(n: int) -> int:
    return max(2, min(12, n // 8))


def _refine_axis_step(
    points: Sequence[Vec3], axis_point: Vec3, axis_dir: Vec3
) -> tuple[Vec3, Vec3] | None:
    """One circle-per-slab pass: re-centre the axis and tilt it toward the drift."""
    u, v = _frame(axis_dir)
    rows = []
    for p in points:
        w = _sub(p, axis_point)
        rows.append((_dot(w, axis_dir), _dot(w, u), _dot(w, v)))
    fits = []
    for group in _bin_by_t(rows, _slab_count(len(points))):
        circle = _fit_circle_2d([g[1] for g in group], [g[2] for g in group])
        if circle is None:
            continue
        fits.append((sum(g[0] for g in group) / len(group), circle[0], circle[1]))
    if len(fits) < 2:
        return None
    ts = [f[0] for f in fits]
    cx = _linfit(ts, [f[1] for f in fits])
    cy = _linfit(ts, [f[2] for f in fits])
    if cx is None or cy is None:
        return None
    moved = _add(axis_point, _add(_scale(u, cx[0]), _scale(v, cy[0])))
    tilted = _unit(_add(axis_dir, _add(_scale(u, cx[1]), _scale(v, cy[1]))))
    if tilted is None or not all(math.isfinite(c) for c in moved):
        return None
    return moved, tilted


def _search_axis(
    points: Sequence[Vec3],
    evaluate,
    iterations: int = 8,
    seeds: Sequence[Vec3] | None = None,
) -> PrimitiveFit | None:
    """Seed from each principal axis and keep the best-scoring fit ever seen.

    Refinement is only accepted when it scores better than what it replaced.  On
    a shallow patch the per-slab circle fits are badly conditioned and the update
    can walk the axis away from a good seed; keeping the running best means the
    reported fit is never worse than the seed that produced it.
    """
    centroid = _centroid(points)
    best: PrimitiveFit | None = None
    # A caller that already has an axis estimate -- RANSAC's minimal-set
    # candidate, say -- hands it in as an extra seed rather than throwing it
    # away.  On a narrow band of surface the principal axes are a poor guess and
    # this is the difference between finding the primitive and not.
    starts = list(_candidate_axes(points))
    for extra in seeds or ():
        unit = _unit(extra)
        if unit is not None:
            starts.insert(0, unit)
    for seed in starts:
        axis_point, axis_dir = centroid, seed
        for _ in range(iterations):
            candidate = evaluate(axis_point, axis_dir)
            if candidate is not None and (best is None or candidate.rms_residual < best.rms_residual):
                best = candidate
            stepped = _refine_axis_step(points, axis_point, axis_dir)
            if stepped is None:
                break
            if (
                _length(_sub(stepped[0], axis_point)) < 1e-13
                and _length(_sub(stepped[1], axis_dir)) < 1e-13
            ):
                break
            axis_point, axis_dir = stepped
        final = evaluate(axis_point, axis_dir)
        if final is not None and (best is None or final.rms_residual < best.rms_residual):
            best = final
    return best


def _fit_cylinder(
    points: Sequence[Vec3], extent: float, seed_axis: Vec3 | None = None
) -> PrimitiveFit:
    centroid = _centroid(points)

    def evaluate(axis_point: Vec3, axis_dir: Vec3) -> PrimitiveFit | None:
        u, v = _frame(axis_dir)
        xs = [_dot(_sub(p, axis_point), u) for p in points]
        ys = [_dot(_sub(p, axis_point), v) for p in points]
        circle = _fit_circle_2d(xs, ys)
        if circle is None:
            return None
        cx, cy, radius = circle
        if not all(math.isfinite(value) for value in (cx, cy, radius)) or radius <= 0.0:
            return None
        rms = _rms(math.hypot(x - cx, y - cy) - radius for x, y in zip(xs, ys))
        if not math.isfinite(rms):
            return None
        on_axis = _add(axis_point, _add(_scale(u, cx), _scale(v, cy)))
        return PrimitiveFit(
            kind="cylinder",
            accepted=True,
            rms_residual=rms,
            relative_residual=rms / extent,
            extent=extent,
            parameters={
                "axis_point": _closest_point_on_axis(centroid, on_axis, axis_dir),
                "axis_direction": _canonical_direction(axis_dir),
                "radius": radius,
            },
        )

    best = _search_axis(points, evaluate, seeds=None if seed_axis is None else (seed_axis,))
    if best is None:
        return _rejected("cylinder", extent, "no candidate axis produced a solvable circle fit.")
    return best


def _closest_point_on_axis(target: Vec3, axis_point: Vec3, axis_dir: Vec3) -> Vec3:
    w = _sub(target, axis_point)
    return _add(axis_point, _scale(axis_dir, _dot(w, axis_dir)))


def _fit_cone(
    points: Sequence[Vec3],
    extent: float,
    min_taper_ratio: float,
    seed_axis: Vec3 | None = None,
) -> PrimitiveFit:
    saw_flat_profile = False

    def evaluate(axis_point: Vec3, axis_dir: Vec3) -> PrimitiveFit | None:
        nonlocal saw_flat_profile
        profile = _taper_profile(points, axis_point, axis_dir)
        if profile is None:
            return None
        _r0, slope, span = profile
        if abs(slope) * span <= min_taper_ratio * extent:
            saw_flat_profile = True
            return None
        if slope < 0.0:
            # Orient the axis so the radius grows along it; the apex is then behind t = 0.
            axis_dir = _scale(axis_dir, -1.0)
            profile = _taper_profile(points, axis_point, axis_dir)
            if profile is None:
                return None
        r0, slope, _span = profile
        if slope <= 0.0 or not math.isfinite(slope) or not math.isfinite(r0):
            return None
        apex = _add(axis_point, _scale(axis_dir, -r0 / slope))
        if not all(math.isfinite(c) for c in apex):
            return None
        half_angle = math.atan(slope)
        cos_a, sin_a = math.cos(half_angle), math.sin(half_angle)
        deviations = []
        for p in points:
            w = _sub(p, apex)
            t = _dot(w, axis_dir)
            rho = _length(_sub(w, _scale(axis_dir, t)))
            deviations.append(rho * cos_a - t * sin_a)
        rms = _rms(deviations)
        if not math.isfinite(rms):
            return None
        return PrimitiveFit(
            kind="cone",
            accepted=True,
            rms_residual=rms,
            relative_residual=rms / extent,
            extent=extent,
            parameters={
                # Deliberately *not* canonicalised: a cone's taper orients its
                # own axis (radius grows along it, so the apex is behind it).
                # Flipping the sign for tidiness would leave the reported apex
                # and half-angle describing the opposite nappe.
                "apex": apex,
                "axis_direction": axis_dir,
                "half_angle_deg": math.degrees(half_angle),
                "reference_radius": r0,
            },
        )

    best = _search_axis(points, evaluate, seeds=None if seed_axis is None else (seed_axis,))
    if best is not None:
        return best
    if saw_flat_profile:
        return _rejected(
            "cone",
            extent,
            "the radius change across the sampled band is below "
            f"{min_taper_ratio:g}x the extent; this face group is a cylinder, not a cone.",
        )
    return _rejected("cone", extent, "no candidate axis produced a solvable taper profile.")


def _taper_profile(
    points: Sequence[Vec3], axis_point: Vec3, axis_dir: Vec3
) -> tuple[float, float, float] | None:
    u, v = _frame(axis_dir)
    rows = []
    for p in points:
        w = _sub(p, axis_point)
        rows.append((_dot(w, axis_dir), _dot(w, u), _dot(w, v)))
    slabs = _bin_by_t(rows, _slab_count(len(points)))
    samples = []
    for group in slabs:
        circle = _fit_circle_2d([g[1] for g in group], [g[2] for g in group])
        if circle is None:
            continue
        samples.append((sum(g[0] for g in group) / len(group), circle[2]))
    if len(samples) < 2:
        return None
    line = _linfit([s[0] for s in samples], [s[1] for s in samples])
    if line is None:
        return None
    span = max(r[0] for r in rows) - min(r[0] for r in rows)
    return line[0], line[1], span


def _fit_torus(
    points: Sequence[Vec3],
    extent: float,
    min_torus_major_ratio: float,
    seed_axis: Vec3 | None = None,
) -> PrimitiveFit:
    """Lukacs, Martin and Marshall (ECCV 1998): in the axial half-plane a torus is a circle.

    Project each point to ``(rho, t)`` about a trial axis -- distance from the
    axis and station along it -- and the tube becomes a plain 2-D circle of
    radius ``minor`` centred at ``(major, t0)``.  So the whole fit is this
    module's existing axis search plus its existing least-squares circle: no new
    numerics, no new failure modes, and the same analytic precision.

    Why a torus at all: without one, every fillet on a real part becomes
    unreconstructed area, and real parts are covered in fillets.  The record
    flags an accepted torus as a fillet candidate so the downstream emitter can
    put a *fillet feature on the shared edge* -- parametric and editable --
    rather than a surface patch.
    """
    saw_degenerate = False

    def evaluate(axis_point: Vec3, axis_dir: Vec3) -> PrimitiveFit | None:
        nonlocal saw_degenerate
        rhos: list[float] = []
        ts: list[float] = []
        for p in points:
            w = _sub(p, axis_point)
            t = _dot(w, axis_dir)
            rhos.append(_length(_sub(w, _scale(axis_dir, t))))
            ts.append(t)
        circle = _fit_circle_2d(rhos, ts)
        if circle is None:
            return None
        major, t0, minor = circle
        if not all(math.isfinite(value) for value in (major, t0, minor)) or minor <= 0.0:
            return None
        if major <= min_torus_major_ratio * minor:
            # Major radius no larger than the tube: a spindle or self-intersecting
            # torus, which is a sphere or a blob wearing a torus's parameters.
            saw_degenerate = True
            return None
        rms = _rms(math.hypot(r - major, t - t0) - minor for r, t in zip(rhos, ts))
        if not math.isfinite(rms):
            return None
        return PrimitiveFit(
            kind="torus",
            accepted=True,
            rms_residual=rms,
            relative_residual=rms / extent,
            extent=extent,
            parameters={
                # The centre lies on the axis, so it is invariant under the
                # canonicalising sign flip below, and so is the residual, which
                # measures t from the centre rather than from the trial origin.
                "center": _add(axis_point, _scale(axis_dir, t0)),
                "axis_direction": _canonical_direction(axis_dir),
                "radius": major,
                "minor_radius": minor,
            },
        )

    best = _search_axis(points, evaluate, seeds=None if seed_axis is None else (seed_axis,))
    if best is not None:
        return best
    if saw_degenerate:
        return _rejected(
            "torus",
            extent,
            f"the fitted major radius never exceeded {min_torus_major_ratio:g}x the minor radius; "
            "this face group is a sphere or a spindle, not a torus.",
        )
    return _rejected("torus", extent, "no candidate axis produced a solvable tube-section circle.")


# --------------------------------------------------------------------------
# 3b. parameter uncertainty
# --------------------------------------------------------------------------

#: Free parameters per kind, in a *degeneracy-finite* local parameterization:
#: tilts rather than a normal's three coupled components, and a cone's
#: half-angle rather than an apex that flies to infinity as the taper vanishes.
#: The order is the order of the perturbation vector below.
_PARAMETER_NAMES: dict[str, tuple[str, ...]] = {
    "plane": ("offset", "tilt_u", "tilt_v"),
    "sphere": ("center_x", "center_y", "center_z", "radius"),
    "cylinder": ("axis_point_u", "axis_point_v", "tilt_u", "tilt_v", "radius"),
    "cone": ("apex_u", "apex_v", "apex_axial", "tilt_u", "tilt_v", "half_angle"),
    "torus": (
        "center_u",
        "center_v",
        "center_axial",
        "tilt_u",
        "tilt_v",
        "radius",
        "minor_radius",
    ),
}

#: How each local parameter maps to something a downstream consumer can use.
#: ``length`` sigmas come back in the caller's own unit; ``angle`` sigmas in
#: degrees.
_PARAMETER_UNITS: dict[str, str] = {
    "offset": "length",
    "tilt_u": "angle",
    "tilt_v": "angle",
    "center_x": "length",
    "center_y": "length",
    "center_z": "length",
    "radius": "length",
    "minor_radius": "length",
    "axis_point_u": "length",
    "axis_point_v": "length",
    "apex_u": "length",
    "apex_v": "length",
    "apex_axial": "length",
    "center_u": "length",
    "center_v": "length",
    "center_axial": "length",
    "half_angle": "angle",
}


def _perturb(kind: str, parameters: Mapping[str, Any], index: int, delta: float) -> dict[str, Any]:
    """Move one local parameter by ``delta`` and return the shifted parameter set.

    Angular parameters take ``delta`` in radians; length parameters in the
    caller's own unit.  The local frame is rebuilt from the primitive's own axis
    or normal each time, so the perturbation directions are the ones the
    parameter names claim.
    """
    out = dict(parameters)
    if kind == "plane":
        normal = parameters["normal"]
        u, v = _frame(normal)
        if index == 0:
            out["offset"] = parameters["offset"] + delta
            return out
        tilted = _unit(_add(normal, _scale(u if index == 1 else v, delta)))
        if tilted is None:
            return out
        anchor = _scale(normal, parameters["offset"])
        out["normal"] = tilted
        out["offset"] = _dot(tilted, anchor)
        return out
    if kind == "sphere":
        if index == 3:
            out["radius"] = parameters["radius"] + delta
            return out
        centre = list(parameters["center"])
        centre[index] += delta
        out["center"] = (centre[0], centre[1], centre[2])
        return out

    axis = parameters["axis_direction"]
    u, v = _frame(axis)
    anchor_key = _AXIS_ANCHOR[kind]
    anchor = parameters[anchor_key]
    if kind == "cylinder":
        if index in (0, 1):
            out[anchor_key] = _add(anchor, _scale(u if index == 0 else v, delta))
        elif index in (2, 3):
            tilted = _unit(_add(axis, _scale(u if index == 2 else v, delta)))
            if tilted is not None:
                out["axis_direction"] = tilted
        else:
            out["radius"] = parameters["radius"] + delta
        return out
    if kind == "cone":
        if index in (0, 1, 2):
            direction = (u, v, axis)[index]
            out[anchor_key] = _add(anchor, _scale(direction, delta))
        elif index in (3, 4):
            tilted = _unit(_add(axis, _scale(u if index == 3 else v, delta)))
            if tilted is not None:
                out["axis_direction"] = tilted
        else:
            out["half_angle_deg"] = parameters["half_angle_deg"] + math.degrees(delta)
        return out
    if index in (0, 1, 2):
        direction = (u, v, axis)[index]
        out[anchor_key] = _add(anchor, _scale(direction, delta))
    elif index in (3, 4):
        tilted = _unit(_add(axis, _scale(u if index == 3 else v, delta)))
        if tilted is not None:
            out["axis_direction"] = tilted
    elif index == 5:
        out["radius"] = parameters["radius"] + delta
    else:
        out["minor_radius"] = parameters["minor_radius"] + delta
    return out


def _invert(matrix: Sequence[Sequence[float]]) -> list[list[float]] | None:
    n = len(matrix)
    columns: list[tuple[float, ...]] = []
    for k in range(n):
        column = _solve(matrix, [1.0 if i == k else 0.0 for i in range(n)])
        if column is None:
            return None
        columns.append(column)
    return [[columns[j][i] for j in range(n)] for i in range(n)]


def parameter_uncertainty(
    fit: PrimitiveFit, points: Any, *, n_eff: float | None = None
) -> dict[str, float]:
    """One-sigma uncertainty per reported parameter, from ``sigma^2 (J^T J)^-1``.

    The Jacobian is taken by central differences over the degeneracy-finite local
    parameterization above rather than by hand-derived analytic rows.  That is a
    deliberate trade: the analytic Jacobians for five kinds are several hundred
    lines with five chances to be subtly wrong, the central difference is exact
    to the step's second order on residual functions this smooth, and the real
    numerical risk here -- named in the spec -- is conditioning of ``J^T J``, not
    the accuracy of its entries.  A singular ``J^T J`` returns ``{}``: the
    parameters are not determined by this data, and saying nothing is the honest
    answer.  **Empty means unknown, never zero.**

    ``n_eff`` lets the caller substitute an effective sample size for correlated
    residuals; the default of ``len(points)`` is optimistic exactly when the
    residuals are spatially correlated, which is why the caller computes it.
    """
    if not fit.accepted:
        return {}
    pts = _as_points(points, "points", 1)
    names = _PARAMETER_NAMES[fit.kind]
    count = len(names)
    effective = float(len(pts)) if n_eff is None else float(n_eff)
    if effective <= count:
        return {}
    base = list(_residuals(fit.kind, fit.parameters, pts))
    ssr = sum(r * r for r in base)
    length_step = 1e-6 * max(fit.extent, 1e-12)
    columns: list[list[float]] = []
    for index, name in enumerate(names):
        step = length_step if _PARAMETER_UNITS[name] == "length" else 1e-6
        plus = _residuals(fit.kind, _perturb(fit.kind, fit.parameters, index, step), pts)
        minus = _residuals(fit.kind, _perturb(fit.kind, fit.parameters, index, -step), pts)
        columns.append([(a - b) / (2.0 * step) for a, b in zip(plus, minus)])
    normal_matrix = [
        [sum(columns[i][k] * columns[j][k] for k in range(len(pts))) for j in range(count)]
        for i in range(count)
    ]
    inverse = _invert(normal_matrix)
    if inverse is None:
        return {}
    variance = ssr / (effective - count)
    out: dict[str, float] = {}
    for index, name in enumerate(names):
        value = variance * inverse[index][index]
        if not math.isfinite(value) or value < 0.0:
            return {}
        sigma = math.sqrt(value)
        out[name] = math.degrees(sigma) if _PARAMETER_UNITS[name] == "angle" else sigma
    # One combined axis-tilt number, because that is what a downstream tolerance
    # actually needs and combining two tilts by quadrature is what it would do.
    if "tilt_u" in out and "tilt_v" in out:
        out["axis_tilt_deg"] = math.hypot(out["tilt_u"], out["tilt_v"])
    out.update(_downstream_sigmas(fit.kind, out))
    return out


#: The local parameterization above is chosen for conditioning, not for the
#: consumer.  U3 licenses relationships against *scalar magnitudes* per fit kind
#: -- ``FIT_UNCERTAINTY_KEYS`` in ``mesh_datum`` and ``LICENSE_SIGMAS`` in
#: ``reconstruction_program`` -- and those names are the contract.  Each entry
#: maps one contract name to the local components it combines in quadrature.
#: Emitted alongside the local names, never instead of them.
#:
#: Without this the two vocabularies overlapped on exactly one name per kind and
#: every real fit record was refused with `fit-record-missing-uncertainty`; only
#: a torus, whose single sigma happens to be named the same on both sides, ever
#: crossed the seam.
_DOWNSTREAM_SIGMAS: dict[str, dict[str, tuple[str, ...]]] = {
    "plane": {"normal_deg": ("tilt_u", "tilt_v"), "offset": ("offset",)},
    "cylinder": {
        "axis_direction_deg": ("tilt_u", "tilt_v"),
        "axis_point": ("axis_point_u", "axis_point_v"),
        "radius": ("radius",),
    },
    "cone": {
        "axis_direction_deg": ("tilt_u", "tilt_v"),
        "apex": ("apex_u", "apex_v", "apex_axial"),
        "half_angle_deg": ("half_angle",),
    },
    "sphere": {"center": ("center_x", "center_y", "center_z"), "radius": ("radius",)},
    "torus": {"minor_radius": ("minor_radius",)},
}


def _downstream_sigmas(kind: str, local: Mapping[str, float]) -> dict[str, float]:
    """The contract-named sigmas, in quadrature over their local components.

    A name whose components are not all present is omitted rather than computed
    from the ones that are: a partial quadrature would understate the very
    uncertainty a tolerance is sized from. Empty means unknown, never zero, and
    the consumer refuses on absence.
    """
    out: dict[str, float] = {}
    for name, components in _DOWNSTREAM_SIGMAS.get(kind, {}).items():
        if any(component not in local for component in components):
            continue
        out[name] = math.sqrt(sum(local[component] ** 2 for component in components))
    return out


def fit_face_group(
    points: Any,
    *,
    kinds: Iterable[str] = ("plane", "cylinder", "cone", "sphere"),
    **gates: Any,
) -> tuple[PrimitiveFit, ...]:
    """Fit each requested primitive, accepted fits first by relative residual.

    Rejected fits stay in the result with their reason: "we could not fit this"
    is itself evidence, and dropping it would leave the caller unable to tell a
    refusal from a kind that was never tried.
    """
    requested = list(kinds)
    for kind in requested:
        if not _in_closed_set(kind, PRIMITIVE_KINDS):
            raise ValueError(f"kind must be one of {', '.join(sorted(PRIMITIVE_KINDS))}.")
    fits = [fit_primitive(points, kind, **gates) for kind in requested]
    return tuple(sorted(fits, key=lambda f: (not f.accepted, f.relative_residual)))


def best_fit(points: Any, **kwargs: Any) -> PrimitiveFit | None:
    """The best accepted fit, or ``None`` when nothing passed the gates.

    ``None`` means *unfitted*, explicitly.  Never a "closest guess".
    """
    for fit in fit_face_group(points, **kwargs):
        if fit.accepted:
            return fit
    return None


# --------------------------------------------------------------------------
# 4. design-intent proposals
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IntentProposal:
    """A measured near-relationship, offered for confirmation.

    Nothing here mutates a fit.  ``deviation`` is the headline measurement in
    ``deviation_unit`` ("deg", or "length" in the caller's own unit); ``detail``
    carries every other number that went into the judgement.
    """

    kind: str
    subjects: tuple[str, ...]
    statement: str
    deviation: float
    deviation_unit: str
    proposed_value: Any | None = None
    detail: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _in_closed_set(self.kind, INTENT_KINDS):
            raise ValueError(f"kind must be one of {', '.join(sorted(INTENT_KINDS))}.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "subjects": list(self.subjects),
            "statement": self.statement,
            "deviation": self.deviation,
            "deviation_unit": self.deviation_unit,
            "proposed_value": (
                list(self.proposed_value)
                if isinstance(self.proposed_value, tuple)
                else self.proposed_value
            ),
            "detail": dict(self.detail),
        }


def _fit_direction(fit: PrimitiveFit) -> Vec3 | None:
    if fit.kind == "plane":
        return fit.parameters.get("normal")
    if fit.kind in ("cylinder", "cone", "torus"):
        return fit.parameters.get("axis_direction")
    return None


def _fit_axis_line(fit: PrimitiveFit) -> tuple[Vec3, Vec3] | None:
    direction = _fit_direction(fit)
    if direction is None or fit.kind == "plane":
        return None
    anchor = fit.parameters.get(_AXIS_ANCHOR.get(fit.kind, ""))
    if anchor is None:
        return None
    return anchor, direction


def _angle_deg(a: Vec3, b: Vec3) -> float:
    return math.degrees(math.acos(max(-1.0, min(1.0, abs(_dot(a, b))))))


def _axis_offset(a: tuple[Vec3, Vec3], b: tuple[Vec3, Vec3]) -> Vec3:
    """Component of the anchor separation perpendicular to the first axis."""
    w = _sub(b[0], a[0])
    return _sub(w, _scale(a[1], _dot(w, a[1])))


def propose_nominal(
    subject: str,
    value: float,
    *,
    tolerance: float,
    steps: Sequence[float] = (1.0, 0.5, 0.25, 0.1),
) -> IntentProposal | None:
    """Is 10.03 meant to be 10?  Proposed, with the deviation, never applied.

    Returns the coarsest step whose rounded value lands within ``tolerance``, or
    ``None`` when nothing does — and ``None`` too when the value already sits on
    that step, because there is then nothing to propose.
    """
    if not isinstance(subject, str) or not subject.strip():
        raise ValueError("subject must be a non-empty string.")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("value must be a finite number.")
    tol = _as_tolerance(tolerance, "tolerance")
    for step in sorted((_as_tolerance(s, "steps") for s in steps), reverse=True):
        candidate = round(float(value) / step) * step
        deviation = abs(float(value) - candidate)
        if deviation <= tol and deviation > 0.0:
            return IntentProposal(
                kind="nominal",
                subjects=(subject.strip(),),
                statement=(
                    f"{subject.strip()} measures {float(value):.6g}; a nominal {candidate:.6g} "
                    f"(step {step:g}) is {deviation:.6g} away. Confirm before adopting it."
                ),
                deviation=deviation,
                deviation_unit="length",
                proposed_value=candidate,
                detail={"measured": float(value), "step": step},
            )
    return None


def propose_design_intent(
    features: Mapping[str, PrimitiveFit],
    *,
    angle_tolerance_deg: float = 2.0,
    offset_tolerance: float | None = None,
    nominal_tolerance: float | None = None,
    tangent_tolerance: float | None = None,
    equal_radius_tolerance: float | None = None,
) -> tuple[IntentProposal, ...]:
    """Surface near-relationships between fitted primitives as proposals.

    Covers near-coaxial, near-perpendicular, near-parallel and near-symmetric
    pairs, plus near-nominal diameters when ``nominal_tolerance`` is given,
    near-tangency when ``tangent_tolerance`` is given, and near-equal radii when
    ``equal_radius_tolerance`` is given.  Each carries its measured deviation;
    none is applied, and no fit is modified.

    The three optional tolerances default to ``None`` meaning *not judged*, not
    "judged with a default": a tangency nobody declared a tolerance for is left
    unproposed rather than proposed against a number this module invented.

    ``offset_tolerance`` defaults to 2% of the largest fitted extent, because a
    coaxiality judgement needs a length scale and inventing an absolute
    millimetre figure would be a guess about the caller's units.
    """
    if not isinstance(features, Mapping):
        raise ValueError("features must be a mapping of name to PrimitiveFit.")
    for name, fit in features.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("feature names must be non-empty strings.")
        if not isinstance(fit, PrimitiveFit):
            raise ValueError(f"feature {name!r} must be a PrimitiveFit.")
        if not fit.accepted:
            raise ValueError(
                f"feature {name!r} was not accepted; a rejected fit is not a basis for design intent."
            )
    angle_tol = _as_tolerance(angle_tolerance_deg, "angle_tolerance_deg")
    if offset_tolerance is None:
        offset_tol = 0.02 * max((fit.extent for fit in features.values()), default=0.0)
        if offset_tol <= 0.0:
            raise ValueError("offset_tolerance could not be derived; state it explicitly.")
    else:
        offset_tol = _as_tolerance(offset_tolerance, "offset_tolerance")
    tangent_tol = (
        None if tangent_tolerance is None else _as_tolerance(tangent_tolerance, "tangent_tolerance")
    )
    equal_radius_tol = (
        None
        if equal_radius_tolerance is None
        else _as_tolerance(equal_radius_tolerance, "equal_radius_tolerance")
    )

    names = sorted(features)
    proposals: list[IntentProposal] = []

    for index, first in enumerate(names):
        for second in names[index + 1 :]:
            a, b = features[first], features[second]
            subjects = (first, second)
            if equal_radius_tol is not None:
                equal_radius = _equal_radius_proposal(subjects, a, b, equal_radius_tol)
                if equal_radius is not None:
                    proposals.append(equal_radius)
            if tangent_tol is not None:
                tangent = _tangent_proposal(
                    subjects, a, b, angle_tol=angle_tol, tangent_tol=tangent_tol
                )
                if tangent is not None:
                    proposals.append(tangent)
            da, db = _fit_direction(a), _fit_direction(b)
            if da is None or db is None:
                continue
            angle = _angle_deg(da, db)
            axes = (_fit_axis_line(a), _fit_axis_line(b))
            coaxial = False
            if angle <= angle_tol and axes[0] is not None and axes[1] is not None:
                offset = _length(_axis_offset(axes[0], axes[1]))
                if offset <= offset_tol:
                    coaxial = True
                    proposals.append(
                        IntentProposal(
                            kind="coaxial",
                            subjects=subjects,
                            statement=(
                                f"{first} and {second} are within {angle:.4g} deg and {offset:.4g} "
                                "of coaxial. Propose a coaxial constraint; values are unchanged."
                            ),
                            deviation=offset,
                            deviation_unit="length",
                            detail={"axis_angle_deg": angle, "axis_offset": offset},
                        )
                    )
            if angle <= angle_tol and not coaxial:
                proposals.append(
                    IntentProposal(
                        kind="parallel",
                        subjects=subjects,
                        statement=(
                            f"{first} and {second} are within {angle:.4g} deg of parallel. "
                            "Propose a parallel constraint; values are unchanged."
                        ),
                        deviation=angle,
                        deviation_unit="deg",
                        detail={"axis_angle_deg": angle},
                    )
                )
            if abs(angle - 90.0) <= angle_tol:
                proposals.append(
                    IntentProposal(
                        kind="perpendicular",
                        subjects=subjects,
                        statement=(
                            f"{first} and {second} are within {abs(angle - 90.0):.4g} deg of "
                            "perpendicular. Propose a perpendicular constraint; values are unchanged."
                        ),
                        deviation=abs(angle - 90.0),
                        deviation_unit="deg",
                        detail={"axis_angle_deg": angle},
                    )
                )
            if angle <= angle_tol and not coaxial:
                symmetry = _symmetry_proposal(subjects, a, b, angle)
                if symmetry is not None:
                    proposals.append(symmetry)

    if nominal_tolerance is not None:
        for name in names:
            radius = features[name].parameters.get("radius")
            if isinstance(radius, float):
                proposal = propose_nominal(
                    f"{name} diameter", 2.0 * radius, tolerance=nominal_tolerance
                )
                if proposal is not None:
                    proposals.append(proposal)
    return tuple(proposals)


def _equal_radius_proposal(
    subjects: tuple[str, str], a: PrimitiveFit, b: PrimitiveFit, tolerance: float
) -> IntentProposal | None:
    """Two radii close enough to be one driven parameter — measured, not assumed.

    Only fits that carry an actual ``radius`` qualify, which is cylinders and
    spheres.  A cone's ``reference_radius`` is its radius *at the axis point the
    search happened to land on*, not a diameter of the part, so equating two of
    them would compare two arbitrary stations and call it a design decision.
    """
    first, second = subjects
    ra, rb = a.parameters.get("radius"), b.parameters.get("radius")
    if not isinstance(ra, float) or not isinstance(rb, float):
        return None
    delta = abs(ra - rb)
    if delta > tolerance:
        return None
    mean = (ra + rb) / 2.0
    return IntentProposal(
        kind="equal_radius",
        subjects=subjects,
        statement=(
            f"{first} and {second} have radii {ra:.6g} and {rb:.6g}, differing by {delta:.4g}. "
            "Propose one shared radius parameter; values are unchanged until adopted."
        ),
        deviation=delta,
        deviation_unit="length",
        proposed_value=mean,
        detail={"radius_a": ra, "radius_b": rb, "radius_delta": delta, "mean_radius": mean},
    )


def _tangent_proposal(
    subjects: tuple[str, str],
    a: PrimitiveFit,
    b: PrimitiveFit,
    *,
    angle_tol: float,
    tangent_tol: float,
) -> IntentProposal | None:
    """Plane-to-cylinder and cylinder-to-cylinder tangency, from the measurement.

    A cylinder whose axis is not parallel to the plane *crosses* it; the distance
    from axis to plane is then not a clearance at all, so that pair is left
    unproposed rather than measured with a formula that does not apply to it.
    """
    first, second = subjects
    for plane, cylinder, plane_first in ((a, b, True), (b, a, False)):
        if plane.kind != "plane" or cylinder.kind != "cylinder":
            continue
        axis = _fit_axis_line(cylinder)
        radius = cylinder.parameters.get("radius")
        if axis is None or not isinstance(radius, float):
            return None
        if abs(_angle_deg(plane.parameters["normal"], axis[1]) - 90.0) > angle_tol:
            return None
        distance = abs(_dot(plane.parameters["normal"], axis[0]) - plane.parameters["offset"])
        deviation = abs(distance - radius)
        if deviation > tangent_tol:
            return None
        plane_name, cylinder_name = (first, second) if plane_first else (second, first)
        return IntentProposal(
            kind="tangent",
            subjects=subjects,
            statement=(
                f"{cylinder_name} has its axis {distance:.6g} from plane {plane_name} and radius "
                f"{radius:.6g}, which is {deviation:.4g} from tangent. Propose a tangent constraint."
            ),
            deviation=deviation,
            deviation_unit="length",
            detail={
                "axis_to_plane_distance": distance,
                "radius": radius,
                "tangent_deviation": deviation,
            },
        )

    if a.kind == "cylinder" and b.kind == "cylinder":
        axis_a, axis_b = _fit_axis_line(a), _fit_axis_line(b)
        ra, rb = a.parameters.get("radius"), b.parameters.get("radius")
        if axis_a is None or axis_b is None:
            return None
        if not isinstance(ra, float) or not isinstance(rb, float):
            return None
        if _angle_deg(axis_a[1], axis_b[1]) > angle_tol:
            return None
        separation = _length(_axis_offset(axis_a, axis_b))
        if separation <= 0.0:
            # Coincident axes are coaxial, and the internal-tangency formula
            # would report equal radii as a tangency. That is coaxial's case.
            return None
        external = abs(separation - (ra + rb))
        internal = abs(separation - abs(ra - rb))
        contact, deviation = (
            ("external", external) if external <= internal else ("internal", internal)
        )
        if deviation > tangent_tol:
            return None
        return IntentProposal(
            kind="tangent",
            subjects=subjects,
            statement=(
                f"{first} and {second} have parallel axes {separation:.6g} apart with radii "
                f"{ra:.6g} and {rb:.6g}, which is {deviation:.4g} from {contact} tangency. "
                "Propose a tangent constraint."
            ),
            deviation=deviation,
            deviation_unit="length",
            proposed_value=contact,
            detail={
                "axis_separation": separation,
                "radius_a": ra,
                "radius_b": rb,
                "tangent_deviation": deviation,
            },
        )
    return None


def _symmetry_proposal(
    subjects: tuple[str, str], a: PrimitiveFit, b: PrimitiveFit, angle: float
) -> IntentProposal | None:
    """Mirror-plane proposals for the same-kind pairs the evidence supports.

    Two parallel planes (a part's outer faces), two parallel-axis cylinders (a
    pair of mounting holes), and two parallel-axis cones (a pair of countersinks
    or chamfers).  Mixed kinds are left unproposed: a cylinder and a cone with
    parallel axes are not each other's mirror image, and saying so would be an
    invention.  Two spheres are deliberately excluded too — *any* two spheres are
    mirror-symmetric about the bisector of their centres, so the proposal would
    carry no evidence and would fire on every sphere pair in the part.
    """
    first, second = subjects
    if a.kind != b.kind:
        return None
    if a.kind == "plane":
        normal = a.parameters["normal"]
        # Both normals are canonicalised, but canonicalisation keys on the
        # dominant component, which two near-parallel normals can disagree
        # about; express the second offset in the first's frame before mixing.
        sign = 1.0 if _dot(normal, b.parameters["normal"]) >= 0.0 else -1.0
        offset_b = sign * b.parameters["offset"]
        separation = abs(a.parameters["offset"] - offset_b)
        if separation <= 0.0:
            return None
        mid = (a.parameters["offset"] + offset_b) / 2.0
        return IntentProposal(
            kind="symmetric",
            subjects=subjects,
            statement=(
                f"{first} and {second} are parallel planes {separation:.4g} apart, within "
                f"{angle:.4g} deg of exactly parallel. Propose a mirror plane between them."
            ),
            deviation=angle,
            deviation_unit="deg",
            proposed_value={"normal": list(normal), "offset": mid},
            detail={"separation": separation, "normal_angle_deg": angle},
        )
    if a.kind in ("cylinder", "cone"):
        axis_a, axis_b = _fit_axis_line(a), _fit_axis_line(b)
        if axis_a is None or axis_b is None:
            return None
        offset_vector = _axis_offset(axis_a, axis_b)
        separation = _length(offset_vector)
        normal = _unit(offset_vector)
        if normal is None or separation <= 0.0:
            return None
        midpoint = _add(axis_a[0], _scale(offset_vector, 0.5))
        # A pair of bores is judged on radius; a pair of countersinks on taper,
        # because a cone carries no single radius to compare (see
        # _equal_radius_proposal for the same reason stated the other way).
        measured = "radius" if a.kind == "cylinder" else "half_angle_deg"
        unit = "length" if a.kind == "cylinder" else "deg"
        delta = abs(a.parameters[measured] - b.parameters[measured])
        return IntentProposal(
            kind="symmetric",
            subjects=subjects,
            statement=(
                f"{first} and {second} are {a.kind}s with parallel axes {separation:.4g} apart, "
                f"differing in {measured} by {delta:.4g}. Propose a mirror plane midway between them."
            ),
            deviation=delta,
            deviation_unit=unit,
            proposed_value={"normal": list(normal), "offset": _dot(normal, midpoint)},
            detail={
                "axis_separation": separation,
                f"{measured}_delta": delta,
                "axis_angle_deg": angle,
            },
        )
    return None
