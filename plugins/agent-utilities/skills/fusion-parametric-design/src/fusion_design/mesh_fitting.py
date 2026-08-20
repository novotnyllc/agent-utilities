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

#: Every token that may appear in ``PrimitiveFit.support["checked"]``, declared
#: in one place so a reader can enumerate the gates and a summary can be derived
#: from the lists rather than asserted beside them.  A free string here is a
#: gate nobody can grep for and a typo nobody can catch: the disproof census in
#: U2 counts these tokens, so a misspelt one reads as "the gate did not run".
#: The gates run in two modules -- the exact fitters here, the statistical ones
#: in ``mesh_segmentation`` -- and both append through ``_passed`` below.
FIT_GATE_TOKENS = frozenset(
    {
        # mesh_fitting: the exact-fit gates and the facet-normal evidence
        "radius-ratio",
        "bounds-margin",
        "relative-residual",
        "simpler-primitive",
        "support-span",
        "residual-structure",
        "heldout-residual",
        "cylinder-normal-tie-break",
        "cylinder-normals-discrete",
        "normal-constrained-axis",
        # mesh_segmentation: the disproof ladder over a whole region
        "support-span-floor",
        "nested-kind-parsimony",
        "kind-promotion",
        "parameter-uncertainty",
        "boundary-circle-corroboration",
    }
)


#: Rejections this module states under a *named* token rather than in prose, so
#: a consumer can branch on the reason instead of matching a sentence.  The
#: prose rejections are deliberately not tokenized: a token is a promise that
#: something downstream reads it, and nothing reads those.
FIT_REJECTION_TOKENS = frozenset({"cylinder-normals-discrete"})


def _passed(checked: list[str], token: str) -> None:
    """Record that ``token``'s gate ran and passed, once, under a declared name."""
    if not _in_closed_set(token, set(FIT_GATE_TOKENS)):
        raise ValueError(f"gate token must be one of {', '.join(sorted(FIT_GATE_TOKENS))}.")
    if token not in checked:
        checked.append(token)


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


def _jacobi_eigen(
    matrix: Sequence[Sequence[float]],
) -> tuple[tuple[float, ...], tuple[tuple[float, ...], ...]]:
    """Cyclic Jacobi on a symmetric n x n; eigenpairs sorted by ascending value.

    The 3x3 case is the one the primitive fits use and the 6x6 case is the
    kinematic router's; they are the same sweep over off-diagonal pairs, so
    there is one implementation rather than two that can drift apart.
    Eigenvectors come back normalized, and a vector that normalizes to nothing
    comes back as the corresponding basis vector rather than as zeros, so a
    caller never has to distinguish "degenerate" from "absent".
    """
    n = len(matrix)
    a = [list(row) for row in matrix]
    v = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    pairs_to_sweep = [(p, q) for p in range(n) for q in range(p + 1, n)]
    for _ in range(64):
        off = sum(abs(a[p][q]) for p, q in pairs_to_sweep)
        if off <= 1e-18:
            break
        for p, q in pairs_to_sweep:
            apq = a[p][q]
            if abs(apq) <= 1e-20:
                continue
            theta = (a[q][q] - a[p][p]) / (2.0 * apq)
            t = math.copysign(1.0, theta) / (abs(theta) + math.sqrt(theta * theta + 1.0))
            c = 1.0 / math.sqrt(t * t + 1.0)
            s = t * c
            for k in range(n):
                akp, akq = a[k][p], a[k][q]
                a[k][p], a[k][q] = c * akp - s * akq, s * akp + c * akq
            for k in range(n):
                apk, aqk = a[p][k], a[q][k]
                a[p][k], a[q][k] = c * apk - s * aqk, s * apk + c * aqk
            for k in range(n):
                vkp, vkq = v[k][p], v[k][q]
                v[k][p], v[k][q] = c * vkp - s * vkq, s * vkp + c * vkq
    pairs = sorted(
        ((a[i][i], tuple(v[row][i] for row in range(n))) for i in range(n)),
        key=lambda kv: kv[0],
    )
    vectors: list[tuple[float, ...]] = []
    for index, (_value, raw) in enumerate(pairs):
        norm = math.sqrt(sum(component * component for component in raw))
        if not math.isfinite(norm) or norm < 1e-15:  # pragma: no cover - Jacobi keeps it unitary
            vectors.append(tuple(1.0 if k == index else 0.0 for k in range(n)))
            continue
        vectors.append(tuple(component / norm for component in raw))
    return tuple(p[0] for p in pairs), tuple(vectors)


def _symmetric_eigen(matrix: Sequence[Sequence[float]]) -> tuple[tuple[float, ...], tuple[Vec3, ...]]:
    """Cyclic Jacobi on a symmetric 3x3; eigenpairs sorted by ascending value."""
    values, vectors = _jacobi_eigen(matrix)
    return values, tuple((v[0], v[1], v[2]) for v in vectors)


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
    """An ordered run of section points, each segment naming the triangles it came from.

    A closed loop does *not* repeat its first point; ``closed`` says it wraps.

    ``segment_triangles`` is one entry per *segment*, in the same order as the
    segments implied by ``points`` — ``len(points)`` of them when ``closed``,
    ``len(points) - 1`` when open — and each entry is the tuple of dump triangle
    indices that produced that segment.  It is a tuple rather than one index
    because a segment lying *on* an edge shared by two triangles genuinely has
    two producers, and recording one of them would be choosing which piece of
    evidence to discard.  A segment whose producers are unknown carries an empty
    tuple, which is a measurement ("nothing attributed this") and not a zero.

    It defaults to empty so every construction site that predates provenance
    still builds, and ``to_dict`` omits the key when it is empty rather than
    writing an empty list a reader could mistake for "measured, found nothing".
    """

    points: tuple[Vec3, ...]
    closed: bool
    segment_triangles: tuple[tuple[int, ...], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"points": [list(p) for p in self.points], "closed": self.closed}
        if self.segment_triangles:
            out["segment_triangles"] = [list(t) for t in self.segment_triangles]
        return out


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

    Every emitted segment records the *index of the triangle that produced it*,
    in the caller's own triangle order, on ``SectionPolyline.segment_triangles``.
    That is the wire nothing downstream could reconstruct afterwards: the
    chained points carry no memory of which facet they were cut from, and the
    material side of a loop is read from those facets' winding.  A segment lying
    on an edge two triangles share records both.

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

    coplanar: list[tuple[int, tuple[int, int, int]]] = []
    segments: dict[frozenset, tuple[tuple, tuple]] = {}
    producers: dict[frozenset, list[int]] = {}
    vertex_touches = 0

    def emit(a: tuple, b: tuple, source: int) -> None:
        if a == b:
            return
        key = frozenset((a, b))
        segments.setdefault(key, (a, b))
        # Append rather than overwrite: two triangles sharing an in-plane edge
        # both produced this segment, and which one is "the" producer is not a
        # question the geometry answers. Deduped because a triangle can reach
        # the same edge twice through the coplanar-boundary pass.
        incident = producers.setdefault(key, [])
        if source not in incident:
            incident.append(source)

    for tri_index, tri in enumerate(faces):
        s = [side[i] for i in tri]
        on = [tri[k] for k in range(3) if s[k] == 0]
        if len(on) == 3:
            coplanar.append((tri_index, tri))
            continue
        if len(on) == 2:
            # An edge lying in the plane: emit it.  If the plane merely grazes the
            # surface here the section is a real, if degenerate, curve; dedup by
            # endpoint pair keeps a shared edge from being emitted twice -- and
            # both triangles that reached it are recorded as its producers.
            emit(vertex_key(on[0]), vertex_key(on[1]), tri_index)
            continue
        if len(on) == 1:
            others = [tri[k] for k in range(3) if s[k] != 0]
            if side[others[0]] == side[others[1]]:
                vertex_touches += 1
                continue
            emit(vertex_key(on[0]), edge_key(others[0], others[1]), tri_index)
            continue
        if s[0] == s[1] == s[2]:
            continue
        crossings = [
            edge_key(tri[k], tri[(k + 1) % 3])
            for k in range(3)
            if side[tri[k]] != side[tri[(k + 1) % 3]]
        ]
        if len(crossings) == 2:
            emit(crossings[0], crossings[1], tri_index)

    if coplanar:
        edge_use: dict[frozenset, list[int]] = {}
        for tri_index, tri in coplanar:
            for k in range(3):
                edge_use.setdefault(
                    frozenset((tri[k], tri[(k + 1) % 3])), []
                ).append(tri_index)
        for edge, incident in edge_use.items():
            if len(incident) == 1:
                a, b = tuple(edge)
                emit(vertex_key(a), vertex_key(b), incident[0])

    polylines, junctions = _chain_segments(segments, producers, coords)
    return MeshSection(
        polylines=tuple(polylines),
        coplanar_triangles=len(coplanar),
        vertex_touches=vertex_touches,
        junctions=tuple(junctions),
    )


def _chain_segments(
    segments: Mapping[frozenset, tuple[tuple, tuple]],
    producers: Mapping[frozenset, Sequence[int]],
    coords: Mapping[tuple, Vec3],
) -> tuple[list[SectionPolyline], list[Vec3]]:
    keys_ordered = sorted(segments, key=lambda k: sorted(map(repr, k)))
    ordered = [segments[key] for key in keys_ordered]
    ordered_producers = [tuple(producers.get(key, ())) for key in keys_ordered]
    adjacency: dict[tuple, list[tuple[tuple, int]]] = {}
    for index, (a, b) in enumerate(ordered):
        adjacency.setdefault(a, []).append((b, index))
        adjacency.setdefault(b, []).append((a, index))

    junction_keys = sorted((k for k, adj in adjacency.items() if len(adj) >= 3), key=repr)
    ends = sorted((k for k, adj in adjacency.items() if len(adj) == 1), key=repr)
    used: set[int] = set()
    runs: list[tuple[list[tuple], list[int]]] = []

    def walk(start: tuple, first: int) -> tuple[list[tuple], list[int]]:
        run = [start]
        walked: list[int] = []
        current = start
        seg = first
        while True:
            used.add(seg)
            walked.append(seg)
            a, b = ordered[seg]
            nxt = b if a == current else a
            run.append(nxt)
            if nxt in junction_keys or nxt == run[0]:
                return run, walked
            options = [s for _, s in adjacency[nxt] if s not in used]
            if len(options) != 1:
                return run, walked
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
    for run, walked in runs:
        closed = len(run) > 2 and run[0] == run[-1]
        keys = run[:-1] if closed else run
        # ``walked`` is one segment per step, so it is already parallel to the
        # point run: len(keys) entries when the run closes, len(keys) - 1 when
        # it does not. The assertion is the invariant, not a guess.
        polylines.append(
            SectionPolyline(
                points=tuple(coords[k] for k in keys),
                closed=closed,
                segment_triangles=tuple(ordered_producers[s] for s in walked),
            )
        )
    return polylines, [coords[k] for k in junction_keys]


# --------------------------------------------------------------------------
# 1b. winding evidence, and what a section loop's own walls say about material
# --------------------------------------------------------------------------

#: What a loop's walls can be measured to say.  ``material-inside`` means the
#: solid fills the loop (an outer boundary); ``material-outside`` means the loop
#: is a hole in material (a bore, a pocket, a nut pocket).  ``contradictory``
#: means the walls disagreed with themselves beyond the declared consensus
#: floor, and ``unavailable`` means nothing licensed the question at all.
LOOP_VERDICTS = {"material-inside", "material-outside", "contradictory", "unavailable"}

#: The gate tokens this measurement can raise.  They are *recorded*, not acted
#: on: this layer diagnoses, and the stage that refuses on them is the slab
#: planner that does not exist yet.  Held as a closed set here for the same
#: reason every other vocabulary in this package is closed -- a token nobody
#: declared is a token nobody can write a handler for.
LOOP_EVIDENCE_GATES = {
    "loop-orientation-unavailable",
    "slab-wall-unattributed",
    "loop-material-contradictory",
    "loop-parity-contradiction",
}


def mesh_winding_evidence(vertices: Any, triangles: Any) -> dict[str, Any]:
    """Is this mesh closed and consistently wound, and which way does it face?

    The licence splits in two, because the two ways a mesh can be dirty are not
    the same fact and lumping them threw away eleven judgeable loops on the
    production corpus:

    * **A boundary edge is global.** An edge with one incident triangle means
      the surface has a hole in it, the enclosed volume is undefined, and the
      sign of the signed volume means nothing anywhere. ``winding`` is ``None``
      and no loop at any station can be classified.
    * **A non-manifold edge is local.** An edge three or more triangles share is
      a surface touching *itself*: it tears nothing, the body still encloses its
      volume, and the sign is as trustworthy as it ever was. So the direction
      stands, and ``non_manifold_triangles`` names exactly the triangles that
      touch the dirt -- a loop cut from any of them is unjudgeable, and a loop
      cut from clean walls elsewhere on the same mesh is not.

    That is the per-edge locality the 2.5D design assumes. Measured on the
    production corpus it is the whole difference between two parts refusing
    outright and both being classified: tropical leaves carries **one**
    non-manifold edge in 86,394 triangles and POD-A2-LID **two** in 10,200, and
    neither has a single boundary edge.

    ``consistently_wound`` (no edge two triangles traverse the same way) is
    measured and reported rather than gating: a winding flip makes its own
    triangles vote wrong, which the loop consensus already catches by name.

    Adjacency is keyed by exact vertex *position*, not by index: a dump exported
    through a triangle-soup format repeats a position under several indices, and
    keying by index would report every edge as a boundary on a perfectly closed
    solid.  The weld is exact -- coordinates that differ in the last bit stay
    distinct, which reads as "not closed", which is the honest answer for a mesh
    whose vertices genuinely do not meet.

    Adjacency is keyed by exact vertex *position*, not by index: a dump exported
    through a triangle-soup format repeats a position under several indices, and
    keying by index would report every edge as a boundary on a perfectly closed
    solid.  The weld is exact -- coordinates that differ in the last bit stay
    distinct, which reads as "not closed", which is the honest answer for a mesh
    whose vertices genuinely do not meet.
    """
    verts = _as_points(vertices, "vertices", 3)
    faces = _as_triangle_indices(triangles, len(verts))

    node = {}
    weld: list[int] = []
    for point in verts:
        target = node.get(point)
        if target is None:
            target = len(node)
            node[point] = target
        weld.append(target)

    directed: dict[tuple[int, int], int] = {}
    incident: dict[tuple[int, int], list[int]] = {}
    degenerate = 0
    volume = 0.0
    for index, (a, b, c) in enumerate(faces):
        pa, pb, pc = verts[a], verts[b], verts[c]
        if _unit(_cross(_sub(pb, pa), _sub(pc, pa))) is None:
            # A zero-area triangle has no normal and no adjacency worth having.
            # Counted, and excluded from both, never given a fabricated one.
            degenerate += 1
            continue
        volume += _dot(pa, _cross(pb, pc)) / 6.0
        wa, wb, wc = weld[a], weld[b], weld[c]
        for i, j in ((wa, wb), (wb, wc), (wc, wa)):
            directed[(i, j)] = directed.get((i, j), 0) + 1
            incident.setdefault((i, j) if i < j else (j, i), []).append(index)

    boundary = non_manifold = reversed_edges = 0
    dirty: set[int] = set()
    seen: set[tuple[int, int]] = set()
    for (i, j), forward in directed.items():
        key = (i, j) if i < j else (j, i)
        if key in seen:
            continue
        seen.add(key)
        backward = directed.get((j, i), 0)
        total = forward + backward
        if total > 2:
            non_manifold += 1
            dirty.update(incident[key])
        elif total == 1:
            boundary += 1
        elif forward == 2 or backward == 2:
            reversed_edges += 1

    closed = boundary == 0 and non_manifold == 0
    # A hole in the surface is what makes the sign meaningless; a self-touch is
    # not. See the docstring -- this is the per-edge locality, and it is the only
    # place the two kinds of dirt are told apart.
    winding = ("outward" if volume > 0.0 else "inward") if boundary == 0 and volume != 0.0 else None
    return {
        "closed": closed,
        "consistently_wound": reversed_edges == 0,
        "signed_volume": volume,
        "winding": winding,
        "boundary_edges": boundary,
        "non_manifold_edges": non_manifold,
        "non_manifold_triangles": tuple(sorted(dirty)),
        "reversed_edges": reversed_edges,
        "degenerate_triangles": degenerate,
        "welded_positions": len(node),
        "node_count": len(verts),
        "unavailable_reason": (
            None
            if winding is not None
            else (
                "the surface has a hole in it, so it encloses no volume and its winding carries no "
                "inside/outside information"
                if boundary > 0
                else "the mesh's signed volume is zero, so its winding carries no inside/outside "
                "information"
            )
        ),
    }


def _as_triangle_indices(triangles: Any, vertex_count: int) -> list[tuple[int, int, int]]:
    if isinstance(triangles, (str, bytes)) or not isinstance(triangles, Sequence):
        raise ValueError("triangles must be a sequence of index triples.")
    faces: list[tuple[int, int, int]] = []
    for index, raw in enumerate(triangles):
        if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence) or len(raw) != 3:
            raise ValueError(f"triangles[{index}] must be a triple of vertex indices.")
        tri: list[int] = []
        for value in raw:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"triangles[{index}] must contain integer vertex indices.")
            if not 0 <= value < vertex_count:
                raise ValueError(
                    f"triangles[{index}] references vertex {value}, which does not exist."
                )
            tri.append(value)
        faces.append((tri[0], tri[1], tri[2]))
    return faces


def _polygon_contains(polygon: Sequence[tuple[float, float]], point: tuple[float, float]) -> bool:
    """Even-odd ray crossing in 2-D. No tolerance, because none would be declared."""
    inside = False
    n = len(polygon)
    for index in range(n):
        ax, ay = polygon[index]
        bx, by = polygon[(index + 1) % n]
        if (ay > point[1]) != (by > point[1]):
            span = by - ay
            if span == 0.0:
                continue
            x = ax + (point[1] - ay) / span * (bx - ax)
            if x > point[0]:
                inside = not inside
    return inside


def loop_material_evidence(
    section: MeshSection,
    vertices: Any,
    triangles: Any,
    plane_normal: Any,
    *,
    consensus_fraction: float,
    attribution_min_fraction: float,
    triangle_regions: Mapping[int, str] | None = None,
) -> dict[str, Any]:
    """Measure, per closed loop of a section, which side of it the material is on.

    The evidence is the mesh's **own winding**, not the fitted regions: every
    triangle of a closed oriented mesh has an outward normal whether or not any
    fitter ever accepted the surface it belongs to, so this measurement does not
    inherit the fitters' coverage ceiling.  Fitted regions are consulted here for
    *identity only* -- which region a wall came from -- and never for the side.

    Per segment: the producing triangle's outward normal is projected into the
    section plane and compared with the loop's own inward direction (read from
    its signed area and traversal order).  An outward normal pointing *out* of
    the loop votes ``material-inside``; one pointing *in* votes
    ``material-outside``.  Votes are weighted by segment length, a segment two
    triangles produced splits its length between them, and a segment whose
    triangle is parallel to the section plane -- a cap facet the plane grazes --
    has no in-plane direction at all and is counted as unattributed rather than
    given a vote it cannot cast.

    Both fractions are the caller's, declared with their rationale upstream:
    ``consensus_fraction`` is the share of attributed length that must agree
    before a verdict is a verdict, and ``attribution_min_fraction`` is how much
    of a loop may go unattributed before the loop's walls are not evidence.

    Nothing here refuses.  The gates a loop trips are named on the loop and
    collected on the record; acting on them belongs to the stage that builds
    slabs, which does not exist yet.
    """
    if not isinstance(consensus_fraction, (int, float)) or isinstance(consensus_fraction, bool):
        raise ValueError("consensus_fraction must be a number the caller declared.")
    if not 0.0 < float(consensus_fraction) <= 1.0:
        raise ValueError("consensus_fraction must lie in (0, 1].")
    if not isinstance(attribution_min_fraction, (int, float)) or isinstance(
        attribution_min_fraction, bool
    ):
        raise ValueError("attribution_min_fraction must be a number the caller declared.")
    if not 0.0 <= float(attribution_min_fraction) <= 1.0:
        raise ValueError("attribution_min_fraction must lie in [0, 1].")

    verts = _as_points(vertices, "vertices", 3)
    faces = _as_triangle_indices(triangles, len(verts))
    normal = _as_direction(plane_normal, "plane_normal")
    u, v = _frame(normal)
    winding = mesh_winding_evidence(verts, faces)
    licensed = winding["winding"] is not None
    flip = -1.0 if winding["winding"] == "inward" else 1.0

    closed_loops = [
        (index, line)
        for index, line in enumerate(section.polylines)
        if line.closed and len(line.points) >= 3
    ]
    # (u, v, normal) is right-handed -- u x v == normal -- so a loop whose
    # shoelace area is positive here runs counter-clockwise seen from +normal.
    projected = [
        [(_dot(p, u), _dot(p, v)) for p in line.points] for _index, line in closed_loops
    ]

    loops: list[dict[str, Any]] = []
    gates: set[str] = set()
    for slot, (index, line) in enumerate(closed_loops):
        flat = projected[slot]
        n = len(flat)
        area2 = sum(
            flat[k][0] * flat[(k + 1) % n][1] - flat[(k + 1) % n][0] * flat[k][1] for k in range(n)
        )
        turn = 1.0 if area2 >= 0.0 else -1.0
        depth = sum(
            1
            for other, points in enumerate(projected)
            if other != slot and _polygon_contains(points, flat[0])
        )

        inside_length = outside_length = unattributed_length = 0.0
        regions: set[str] = set()
        provenance = line.segment_triangles
        # Locality: this loop is judgeable only if none of *its own* walls sits
        # on a non-manifold edge. Dirt elsewhere on the mesh is not this loop's
        # problem, and refusing over it is what threw away eleven good loops.
        dirty_walls = sorted(
            {t for entry in provenance for t in entry} & set(winding["non_manifold_triangles"])
        )
        clean = not dirty_walls
        for k in range(n):
            ax, ay = flat[k]
            bx, by = flat[(k + 1) % n]
            length = math.hypot(bx - ax, by - ay)
            if length <= 0.0:
                continue
            # The loop's interior is to the left of travel for a counter-clockwise
            # loop and to the right for a clockwise one; `turn` carries which.
            inward = (-(by - ay) * turn, (bx - ax) * turn)
            sources = provenance[k] if k < len(provenance) else ()
            votes: list[float] = []
            for tri_index in sources:
                if tri_index >= len(faces):
                    continue
                if triangle_regions is not None and tri_index in triangle_regions:
                    regions.add(triangle_regions[tri_index])
                a, b, c = faces[tri_index]
                outward = _unit(_cross(_sub(verts[b], verts[a]), _sub(verts[c], verts[a])))
                if outward is None or not licensed or not clean:
                    continue
                outward = _scale(outward, flip)
                planar = _sub(outward, _scale(normal, _dot(outward, normal)))
                dot = planar[0] * u[0] + planar[1] * u[1] + planar[2] * u[2]
                dotv = planar[0] * v[0] + planar[1] * v[1] + planar[2] * v[2]
                if dot == 0.0 and dotv == 0.0:
                    # The facet is parallel to the section plane: it bounds
                    # material along the axis, not across the loop, so it has no
                    # opinion about which side of the loop is solid.
                    continue
                votes.append(dot * inward[0] + dotv * inward[1])
            if not votes:
                unattributed_length += length
                continue
            share = length / len(votes)
            for value in votes:
                if value < 0.0:
                    inside_length += share
                elif value > 0.0:
                    outside_length += share
                else:
                    unattributed_length += share

        attributed = inside_length + outside_length
        total = attributed + unattributed_length
        consensus = (max(inside_length, outside_length) / attributed) if attributed > 0.0 else None
        unattributed_fraction = (unattributed_length / total) if total > 0.0 else 1.0
        loop_gates: list[str] = []
        if not licensed or not clean:
            verdict = "unavailable"
            loop_gates.append("loop-orientation-unavailable")
        elif attributed <= 0.0:
            verdict = "unavailable"
            loop_gates.append("slab-wall-unattributed")
        elif consensus is not None and consensus < float(consensus_fraction):
            verdict = "contradictory"
            loop_gates.append("loop-material-contradictory")
        else:
            verdict = "material-inside" if inside_length >= outside_length else "material-outside"
        if licensed and clean and unattributed_fraction > float(attribution_min_fraction):
            if "slab-wall-unattributed" not in loop_gates:
                loop_gates.append("slab-wall-unattributed")
        parity_expected = "material-inside" if depth % 2 == 0 else "material-outside"
        parity_agrees = (
            (verdict == parity_expected) if verdict in {"material-inside", "material-outside"} else None
        )
        if parity_agrees is False:
            loop_gates.append("loop-parity-contradiction")
        gates.update(loop_gates)
        loops.append(
            {
                "polyline_index": index,
                "point_count": n,
                "segment_count": len(provenance),
                "signed_area_mm2": area2 / 2.0,
                "perimeter_mm": total,
                "depth": depth,
                "verdict": verdict,
                "consensus_fraction": consensus,
                "material_inside_length_mm": inside_length,
                "material_outside_length_mm": outside_length,
                "unattributed_length_mm": unattributed_length,
                "unattributed_fraction": unattributed_fraction,
                # Which of this loop's own walls sit on a non-manifold edge. Empty
                # is the normal case and the reason a dirty mesh no longer costs
                # every loop on it; non-empty is exactly why this one refuses.
                "dirty_wall_triangles": dirty_walls,
                "parity_expected": parity_expected,
                "parity_agrees": parity_agrees,
                "wall_regions": sorted(regions),
                "gates": loop_gates,
            }
        )

    unknown = gates - LOOP_EVIDENCE_GATES
    if unknown:  # pragma: no cover - the set and its uses are edited together
        raise ValueError(
            f"{sorted(unknown)} is outside this layer's closed gate vocabulary; a token nobody "
            "declared is a token nobody can write a handler for."
        )
    return {
        "winding": winding,
        "declared": {
            "loop_material_consensus_fraction": float(consensus_fraction),
            "loop_attribution_min_fraction": float(attribution_min_fraction),
        },
        "closed_loop_count": len(loops),
        "open_polyline_count": sum(1 for line in section.polylines if not line.closed),
        "junction_count": len(section.junctions),
        "coplanar_triangles": section.coplanar_triangles,
        "loops": loops,
        "gates": sorted(gates),
        "note": (
            "Verdicts come from the mesh's own winding, never from the fitted regions: fit "
            "coverage is a ceiling this measurement does not inherit. `wall_regions` is identity "
            "only. Nothing here refuses; the gates are recorded for the stage that will."
        ),
    }


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

    ``triangles`` is the sorted set of dump triangle indices that produced the
    segments this entity covers — present only when the caller passed the
    section's own ``segment_triangles`` through, absent otherwise, because an
    empty list would read as "measured, and nothing produced it".
    """

    kind: str
    start: Vec3
    end: Vec3
    residual: float
    point_count: int
    center: Vec3 | None = None
    radius: float | None = None
    mid: Vec3 | None = None
    triangles: tuple[int, ...] = ()

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
        if self.triangles:
            out["triangles"] = list(self.triangles)
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
    segment_triangles: Sequence[Sequence[int]] | None = None,
) -> tuple[SketchEntity, ...]:
    """Split a section polyline into line and arc runs within ``tolerance``.

    Greedy longest-run: at each position take the longest line run, then the
    longest arc run, and keep whichever covers strictly more points (line wins
    ties, so a straight stretch never becomes a very large arc).  ``residual`` is
    the worst deviation of that run from its fitted entity.

    A closed polyline is first rotated to start at its sharpest corner, so a
    square section yields four lines rather than five; a closed loop that fits a
    single circle within tolerance is reported as one ``circle`` entity.

    ``segment_triangles`` is the section's own per-segment provenance — one
    entry per segment, exactly as ``SectionPolyline.segment_triangles`` carries
    it — and when it is given each entity reports the triangles that produced
    the segments it covers.  Passing it is optional and changes nothing else:
    every caller that does not is byte-identical to before.
    """
    pts = list(_as_points(points, "points", 2))
    tol = _as_tolerance(tolerance, "tolerance")
    plane_normal = None if normal is None else _as_direction(normal, "normal")
    segs = _as_segment_triangles(segment_triangles, len(pts), closed)

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
                    triangles=_union_triangles(segs, 0, len(pts)) if segs else (),
                ),
            )
        pivot = _sharpest_corner(pts)
        pts = pts[pivot:] + pts[:pivot] + [pts[pivot]]
        if segs is not None:
            # The points rotated, so the segments rotate with them: new segment
            # i is old segment (pivot + i) % n, which keeps the parallel intact.
            segs = segs[pivot:] + segs[:pivot]

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
                    triangles=_union_triangles(segs, i, arc_end) if segs else (),
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
                triangles=_union_triangles(segs, i, line_end) if segs else (),
            )
        )
        i = line_end
    return tuple(entities)


def _as_segment_triangles(
    raw: Any, point_count: int, closed: bool
) -> list[tuple[int, ...]] | None:
    """Validate per-segment provenance against the point run it must parallel.

    A provenance list that does not have exactly one entry per segment is not a
    slightly-wrong list, it is a list nobody can index safely -- so it raises
    here rather than silently attributing a segment to its neighbour's triangle.
    """
    if raw is None:
        return None
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise ValueError("segment_triangles must be a sequence of index tuples.")
    expected = point_count if closed else max(point_count - 1, 0)
    if len(raw) != expected:
        raise ValueError(
            f"segment_triangles carries {len(raw)} entries for {point_count} "
            f"{'closed' if closed else 'open'} points, which implies {expected} segments."
        )
    out: list[tuple[int, ...]] = []
    for index, entry in enumerate(raw):
        if isinstance(entry, (str, bytes)) or not isinstance(entry, Sequence):
            raise ValueError(f"segment_triangles[{index}] must be a sequence of triangle indices.")
        row: list[int] = []
        for value in entry:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(
                    f"segment_triangles[{index}] must contain non-negative triangle indices."
                )
            row.append(value)
        out.append(tuple(row))
    return out


def _union_triangles(
    segs: Sequence[Sequence[int]] | None, start: int, end: int
) -> tuple[int, ...]:
    """The triangles behind segments ``start`` .. ``end - 1``, sorted and deduped."""
    if segs is None:
        return ()
    found: set[int] = set()
    for index in range(start, min(end, len(segs))):
        found.update(segs[index])
    return tuple(sorted(found))


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
    fixed_axis: Vec3 | None = None,
) -> PrimitiveFit:
    """Least squares only: no gates, so the gates can call it without recursing."""
    if kind == "plane":
        return _fit_plane(points, extent)
    if kind == "sphere":
        return _fit_sphere(points, extent)
    if kind == "cylinder":
        return _fit_cylinder(points, extent, seed_axis, fixed_axis)
    if kind == "torus":
        return _fit_torus(points, extent, min_torus_major_ratio, seed_axis, fixed_axis)
    return _fit_cone(points, extent, min_taper_ratio, seed_axis, fixed_axis)


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
    fixed_axis: Any = None,
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
    pinned = None if fixed_axis is None else _as_direction(fixed_axis, "fixed_axis")
    if pinned is not None and kind in ("plane", "sphere"):
        raise ValueError("fixed_axis applies to cylinder, cone and torus; a plane and a sphere have no axis.")
    fit = _raw_fit(
        pts,
        kind,
        extent,
        float(min_taper_ratio),
        float(min_torus_major_ratio),
        axis_hint,
        pinned,
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
    _passed(checked, "radius-ratio")

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
    _passed(checked, "bounds-margin")

    if fit.relative_residual > max_relative_residual:
        return _rejected(
            fit.kind,
            extent,
            f"relative residual {fit.relative_residual:.6g} exceeds the gate "
            f"{max_relative_residual:g}.",
            support,
        )
    _passed(checked, "relative-residual")

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
        _passed(checked, "simpler-primitive")

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
        _passed(checked, "support-span")

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
        _passed(checked, "residual-structure")

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
        _passed(checked, "heldout-residual")

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
    fixed: Vec3 | None = None,
) -> PrimitiveFit | None:
    """Seed from each principal axis and keep the best-scoring fit ever seen.

    Refinement is only accepted when it scores better than what it replaced.  On
    a shallow patch the per-slab circle fits are badly conditioned and the update
    can walk the axis away from a good seed; keeping the running best means the
    reported fit is never worse than the seed that produced it.

    ``fixed`` pins the axis instead of searching for one, and is how a
    normal-determined axis reaches the fit.  It is deliberately not a seed: the
    search refines against the *vertices*, and on a bore tessellated as two rings
    that is exactly the evidence that does not determine an axis, so refining
    would walk a determined axis back toward an undetermined one.  With the
    direction pinned, what is left is the module's existing exact 2-D circle fit
    in the plane perpendicular to it.
    """
    centroid = _centroid(points)
    if fixed is not None:
        pinned = _unit(fixed)
        return None if pinned is None else evaluate(centroid, pinned)
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
    points: Sequence[Vec3],
    extent: float,
    seed_axis: Vec3 | None = None,
    fixed_axis: Vec3 | None = None,
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

    best = _search_axis(
        points,
        evaluate,
        seeds=None if seed_axis is None else (seed_axis,),
        fixed=fixed_axis,
    )
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
    fixed_axis: Vec3 | None = None,
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

    best = _search_axis(
        points,
        evaluate,
        seeds=None if seed_axis is None else (seed_axis,),
        fixed=fixed_axis,
    )
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
    fixed_axis: Vec3 | None = None,
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

    best = _search_axis(
        points,
        evaluate,
        seeds=None if seed_axis is None else (seed_axis,),
        fixed=fixed_axis,
    )
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
    return _joint_axis_sigma(fit, out)


def _joint_axis_sigma(fit: PrimitiveFit, out: dict[str, float]) -> dict[str, float]:
    """Report the axis sigma from whichever system actually determined the axis.

    When the fit's axis came from the facet normals, the vertex Jacobian's tilt
    columns describe a determination that did not happen -- on a two-ring bore
    they are computed from a matrix that is going singular, and the sigma they
    produce is an artefact of the conditioning rather than a statement about the
    axis.  The joint system's closed-form sigma replaces it, and the vertex
    number is kept beside it under a name that says what it is, so a reader can
    see the size of the difference the normals made.

    Nothing is blended.  Averaging an honest number with a meaningless one gives
    a meaningless one, and the whole point of the joint system is that it knows
    which is which.
    """
    evidence = fit.support.get("axis_evidence")
    if not isinstance(evidence, Mapping) or evidence.get("source") != "facet-normals":
        return out
    joint = evidence.get("axis_tilt_sigma_deg")
    if not isinstance(joint, (int, float)) or isinstance(joint, bool) or not math.isfinite(joint):
        return out
    if "axis_tilt_deg" in out:
        out["axis_tilt_vertices_deg"] = out["axis_tilt_deg"]
    out["axis_tilt_deg"] = float(joint)
    out["axis_direction_deg"] = float(joint)
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


def _perpendicularity_deg(normals: Sequence[Any], axis: Vec3) -> float | None:
    """The worst facet normal's departure from perpendicular to ``axis``, in degrees.

    ``None`` when any normal is unreadable or degenerate: absent evidence refuses
    rather than defaulting to zero, which would read as perfect perpendicularity.
    """
    worst = 0.0
    seen = 0
    for raw in normals:
        vector = _unit(_as_point(raw, "facet_normals"))
        if vector is None:
            return None
        seen += 1
        # The angle between a normal and the plane perpendicular to the axis is
        # asin|n . axis| directly -- no 90-degree subtraction to lose precision in.
        worst = max(worst, math.degrees(math.asin(min(1.0, abs(_dot(vector, axis))))))
    return worst if seen else None


# --------------------------------------------------------------------------
# the facet-normal system: one accumulation, three consumers
# --------------------------------------------------------------------------


def _normal_moments(
    points: Sequence[Vec3],
    normals: Sequence[Any],
    centre: Vec3,
    scale: float,
    weights: Sequence[float] | None = None,
) -> tuple[list[list[float]], int, float]:
    """One pass over the facets, building the whole normal system at once.

    Returns the 6x6 symmetric matrix over rows ``[x x n, n]`` -- Pottmann and
    Randrup's ``n.(c_bar + c x x) = 0`` -- together with the number of usable
    facets and the total weight.  Its lower-right 3x3 block is ``sum w n n^T``,
    the normal second-moment matrix whose smallest eigenvector is a cylinder's
    axis, so the router and the cylinder axis read the same accumulation rather
    than two that can drift apart.  Positions are centred and scaled; the normal
    block is untouched by both, which is why the cylinder path can ignore them.

    Weights are facet areas divided by their own mean, so the normal block's
    trace reads as an *effective facet count* rather than an area.  That is what
    makes ``sigma^2 / lambda`` a variance over a count, and what makes the
    recovered sigma fall as ``1/sqrt(N)`` the way a mean's does.  A facet whose
    normal is unreadable is skipped and not counted -- never given a fabricated
    direction, and never counted as evidence it did not supply.
    """
    if len(points) != len(normals):
        raise ValueError("the normal system needs one normal per point.")
    if weights is not None and len(weights) != len(normals):
        raise ValueError("the normal system needs one weight per normal, or none at all.")
    if not math.isfinite(scale) or scale <= 0.0:
        raise ValueError("the normal system needs a region with a positive extent.")
    scaled_weights: list[float] | None = None
    if weights is not None:
        total = sum(float(w) for w in weights)
        if not math.isfinite(total) or total <= 0.0:
            raise ValueError("facet weights must carry a positive finite total.")
        mean = total / len(weights)
        scaled_weights = [float(w) / mean for w in weights]

    matrix = [[0.0] * 6 for _ in range(6)]
    used = 0
    weight_sum = 0.0
    for index, (point, raw_normal) in enumerate(zip(points, normals)):
        normal = _unit(_as_point(raw_normal, "facet_normals"))
        if normal is None:
            continue
        weight = 1.0 if scaled_weights is None else scaled_weights[index]
        if not math.isfinite(weight) or weight <= 0.0:
            continue
        moment = _cross(_scale(_sub(point, centre), 1.0 / scale), normal)
        row = (moment[0], moment[1], moment[2], normal[0], normal[1], normal[2])
        for i in range(6):
            for j in range(i, 6):
                matrix[i][j] += weight * row[i] * row[j]
        used += 1
        weight_sum += weight
    for i in range(6):
        for j in range(i):
            matrix[i][j] = matrix[j][i]
    return matrix, used, weight_sum


def normal_constrained_axis(
    facet_centroids: Any,
    facet_normals: Sequence[Any],
    *,
    facet_areas: Sequence[float] | None = None,
    sigma_theta_floor_deg: float = 0.0,
) -> dict[str, Any] | None:
    """The axis a region's facet normals determine, with its own uncertainty.

    Every facet normal of a cylinder is exactly perpendicular to its axis, so
    with ``A = sum w n n^T`` the axis is A's smallest eigenvector and ``a^T A a``
    is the weighted sum of squared perpendicularity errors.  In the tangent
    parameterization ``a(u, v) = normalise(a0 + u e1 + v e2)`` the Gauss-Newton
    normal matrix is *exactly* ``diag(lambda1, lambda2)`` -- the two larger
    eigenvalues -- so the covariance is diagonal in closed form:

        sigma_theta^2 = lambda0 / (W - 2),
        sigma_tilt    = sigma_theta * sqrt(1/lambda1 + 1/lambda2)

    with ``W`` the total weight.  No Jacobian, no matrix inverse, and no
    conditioning question: the number that decides whether the axis is
    determined is ``lambda1`` itself, reported here as the eigengap
    ``lambda1 / trace`` -- one half for a full turn of facets, and falling to
    zero for a sliver, which is the honest statement that a sliver's normals do
    not determine an axis either.

    This exists because two rings of vertices do not determine an axis and the
    facets between them do.  ``sigma_theta_floor_deg`` is the caller's
    measurement floor: on an exact tessellation the measured residual is float
    noise, and reporting a sigma of zero would be inventing certainty.

    ``None`` when the normals are unreadable or too few: absent evidence refuses
    rather than defaulting to an axis nobody measured.
    """
    pts = _as_points(facet_centroids, "facet_centroids", 1)
    if (
        isinstance(sigma_theta_floor_deg, bool)
        or not isinstance(sigma_theta_floor_deg, (int, float))
        or not math.isfinite(sigma_theta_floor_deg)
        or sigma_theta_floor_deg < 0.0
    ):
        raise ValueError("sigma_theta_floor_deg must be a non-negative finite number.")
    extent = _extent(pts)
    if extent <= 0.0:
        return None
    matrix, used, weight = _normal_moments(
        pts, facet_normals, _centroid(pts), extent, facet_areas
    )
    # Two tangent parameters, so the residual degrees of freedom need a third
    # facet before a variance means anything.
    if used < 3 or weight <= 2.0:
        return None
    block = [[matrix[3 + i][3 + j] for j in range(3)] for i in range(3)]
    values, vectors = _symmetric_eigen(block)
    lam0, lam1, lam2 = values
    trace = lam0 + lam1 + lam2
    if trace <= 0.0 or lam1 <= 0.0 or lam2 <= 0.0:
        return None
    axis = _unit(vectors[0])
    if axis is None:  # pragma: no cover - Jacobi returns unit vectors
        return None
    floor_rad = math.radians(float(sigma_theta_floor_deg))
    measured = math.sqrt(max(lam0, 0.0) / (weight - 2.0))
    sigma_theta = max(measured, floor_rad)
    tilt = sigma_theta * math.sqrt(1.0 / lam1 + 1.0 / lam2)
    return {
        "axis": _canonical_direction(axis),
        "eigenvalues": [lam0, lam1, lam2],
        "eigengap": lam1 / trace,
        "facet_count": used,
        "effective_facet_count": weight,
        "measured_sigma_theta_deg": math.degrees(measured),
        "sigma_theta_floor_deg": float(sigma_theta_floor_deg),
        "sigma_theta_deg": math.degrees(sigma_theta),
        "axis_tilt_sigma_deg": math.degrees(tilt),
        "method": (
            "smallest eigenvector of the area-weighted facet-normal second moment; sigma from the "
            "closed-form Gauss-Newton covariance diag(1/lambda1, 1/lambda2) in the tangent plane"
        ),
    }


# --------------------------------------------------------------------------
# the kinematic-surface router
# --------------------------------------------------------------------------

#: A signature that is doubly curved with the same sign cannot be swept by a
#: translation: an extrusion is flat in the sweep direction by construction. The
#: signature never vetoes on its own (existing doctrine), so the contradiction is
#: recorded and routed to the *conservative* outcome rather than to either claim.
_TRANSLATION_IMPOSSIBLE_SIGNATURES = {"peak-pit"}


def route_kinematic_surface(
    points: Sequence[Vec3],
    normals: Sequence[Vec3],
    *,
    sigma_theta_rad: float,
    residual_sigma_factor: float,
    eigengap_min: float,
    translation_epsilon: float,
    pitch_epsilon: float,
    signature: str | None = None,
    facet_areas: Sequence[float] | None = None,
) -> dict[str, Any]:
    """Is this region swept by a one-parameter rigid motion, and which one?

    Pottmann & Randrup (*Computing* 60, 1998).  A rigid motion's velocity field
    is ``v(x) = c_bar + c x x``; a surface is swept by that motion exactly when
    every surface normal is orthogonal to the field, ``n . v = 0`` -- which is
    **linear in the six unknowns** ``(c, c_bar)``.  Accumulating
    ``M = sum a a^T`` over rows ``a = [x x n, n]`` is one O(N) pass, and the
    smallest eigenpair of the 6x6 symmetric ``M`` answers extrusion, revolution
    and helix in one test rather than three detectors.

    Points are centred on the region centroid and scaled by its extent before
    the rows are built.  That is mandatory, not tidiness: the two halves of each
    row otherwise carry different units and the recovered pitch comes out in
    garbage ones.  Everything reported is un-scaled afterwards, and both the
    scaled and the unscaled quantities are in the record so a reviewer can see
    how close the call was.

    The verdict is a *proposal*.  Nothing downstream may emit on it without its
    own confirmation -- for an extrusion, that the sections along the direction
    actually agree.
    """
    if len(points) != len(normals):
        raise ValueError("the router needs one normal per point.")
    if len(points) < 6:
        raise ValueError("the router needs at least six samples for a six-parameter fit.")
    centre = _centroid(points)
    scale = _extent(points)
    if not math.isfinite(scale) or scale <= 0.0:
        raise ValueError("the router needs a region with a positive extent.")

    matrix, used, _weight = _normal_moments(points, normals, centre, scale, facet_areas)
    if used < 6:
        raise ValueError("the router needs at least six samples carrying usable normals.")
    return _route_from_moments(
        matrix,
        used,
        centre,
        scale,
        sigma_theta_rad=sigma_theta_rad,
        residual_sigma_factor=residual_sigma_factor,
        eigengap_min=eigengap_min,
        translation_epsilon=translation_epsilon,
        pitch_epsilon=pitch_epsilon,
        signature=signature,
    )


def _route_from_moments(
    matrix: Sequence[Sequence[float]],
    used: int,
    centre: Vec3,
    scale: float,
    *,
    sigma_theta_rad: float,
    residual_sigma_factor: float,
    eigengap_min: float,
    translation_epsilon: float,
    pitch_epsilon: float,
    signature: str | None,
) -> dict[str, Any]:
    """The verdict, from an already-accumulated ``M`` and the frame it was built in.

    Split out of ``route_kinematic_surface`` so that the group router — which
    reaches its ``M`` by summing per-region blocks rather than by walking facets
    — reads the *same* spectrum through the *same* gates.  Two copies of this
    ladder is how a group verdict and a region verdict start disagreeing about
    the same geometry.
    """
    values, vectors = _jacobi_eigen(matrix)
    smallest, second, largest = values[0], values[1], values[5]
    winner = vectors[0]
    omega = (winner[0], winner[1], winner[2])
    u_bar = (winner[3], winner[4], winner[5])
    residual = math.sqrt(max(smallest, 0.0) / used)
    residual_gate = residual_sigma_factor * sigma_theta_rad
    # How far the *second* smallest eigenvalue sits from zero, on the spectrum's
    # own scale. It is the right quantity rather than the difference of the two
    # smallest: what makes an eigenvector meaningless is a null space with more
    # than one direction in it, and that is exactly `second ~ 0`.
    spread = max(abs(largest), _ZERO_RESIDUAL_FLOOR_RATIO)
    eigengap = second / spread

    omega_magnitude = _length(omega)
    pitch_scaled = (
        _dot(omega, u_bar) / (omega_magnitude * omega_magnitude)
        if omega_magnitude > 0.0
        else math.inf
    )
    # Un-scale: with x = centre + scale * x', n.(u_bar + omega x x') = 0 becomes
    # n.(scale * u_bar - omega x centre + omega x x) = 0.
    c_vector = omega
    c_bar = _sub(_scale(u_bar, scale), _cross(omega, centre))

    record: dict[str, Any] = {
        "verdict": "none",
        "refusal": None,
        "sample_count": used,
        "eigenvalues": list(values),
        "residual_rad": residual,
        "residual_gate_rad": residual_gate,
        "sigma_theta_rad": sigma_theta_rad,
        "eigengap": eigengap,
        "eigengap_min": eigengap_min,
        "translation_magnitude": omega_magnitude,
        "translation_epsilon": translation_epsilon,
        "pitch_scaled": None if math.isinf(pitch_scaled) else pitch_scaled,
        "pitch_epsilon": pitch_epsilon,
        "scale": scale,
        "centre": list(centre),
        "c": list(c_vector),
        "c_bar": list(c_bar),
        "direction": None,
        "axis_point": None,
        "pitch": None,
        "signature": signature,
        "note": (
            "n.(c_bar + c x x) = 0 over the region's own normals; the residual is an RMS of that "
            "dot product over unit normals and unit-extent positions, so it reads as an angle in "
            "radians and is gated against the measured normal-noise floor rather than a constant."
        ),
    }
    if residual > residual_gate:
        record["reason"] = (
            f"no rigid motion leaves this region invariant: the best one still misses the normals "
            f"by {residual:.6g} rad against a declared gate of {residual_gate:.6g} rad."
        )
        return record
    if eigengap < eigengap_min:
        # A plane admits a three-parameter family of invariant motions and a
        # sphere any rotation about its centre, so a degenerate spectrum means
        # the primitive stage and the router disagree about this region. Picking
        # an eigenvector out of a degenerate subspace would be a guess.
        record["refusal"] = "router-ambiguous"
        record["reason"] = (
            f"the second-smallest eigenvalue is {eigengap:.6g} of the spectrum against a declared "
            f"minimum of {eigengap_min:.6g}: this region's invariant motions form a family rather "
            "than a single one, so no eigenvector describes it."
        )
        return record

    if omega_magnitude <= translation_epsilon:
        direction = _unit(u_bar)
        if direction is None:  # pragma: no cover - |omega|^2 + |u_bar|^2 == 1
            record["refusal"] = "router-ambiguous"
            record["reason"] = "the recovered motion has neither a rotation nor a translation part."
            return record
        if signature in _TRANSLATION_IMPOSSIBLE_SIGNATURES:
            record["refusal"] = "router-signature-conflict"
            record["reason"] = (
                f"the normals fit a translation, and the region's dominant curvature signature is "
                f"{signature!r} -- doubly curved with one sign, which no extrusion can be. The two "
                "measurements contradict each other, so this falls through rather than picking one."
            )
            return record
        record["verdict"] = "extrusion"
        record["direction"] = list(_canonical_direction(direction))
        record["reason"] = (
            f"the recovered motion is a translation: its rotation part is {omega_magnitude:.6g} "
            f"against a declared {translation_epsilon:.6g}."
        )
        return record

    axis = _unit(c_vector)
    if axis is None:  # pragma: no cover - |omega| > translation_epsilon > 0
        record["refusal"] = "router-ambiguous"
        record["reason"] = "the recovered motion has neither a rotation nor a translation part."
        return record
    magnitude_sq = _dot(c_vector, c_vector)
    axis_point = _scale(_cross(c_vector, c_bar), 1.0 / magnitude_sq)
    pitch = _dot(c_vector, c_bar) / magnitude_sq
    record["direction"] = list(_canonical_direction(axis))
    record["axis_point"] = list(axis_point)
    record["pitch"] = pitch
    if abs(pitch_scaled) <= pitch_epsilon:
        record["verdict"] = "revolution"
        record["reason"] = (
            f"the recovered motion is a rotation: its scaled pitch is {pitch_scaled:.6g} against a "
            f"declared {pitch_epsilon:.6g}."
        )
        return record
    record["verdict"] = "helical"
    record["reason"] = (
        f"the recovered motion is a screw of scaled pitch {pitch_scaled:.6g}, beyond the declared "
        f"{pitch_epsilon:.6g}. Helical geometry is reported and not emitted."
    )
    return record


# --------------------------------------------------------------------------
# carrying the router's evidence across the fit record
#
# The router reads facets; the archetype planner has only the fit record, which
# carries no triangles. What crosses the seam is the *sufficient statistic*:
# ``M_raw = sum over facets of area * b b^T`` with ``b = [x x n, n]`` in the
# mesh's own frame. It is 21 numbers per region, additive across regions, and it
# re-centres and re-scales by a congruence, so a group's 6x6 is recoverable from
# its members' blocks without keeping a single triangle. "Exact" there is a
# statement about the algebra, not about the floats: the two paths sum the same
# terms in different orders, so they agree to *relative* rounding -- measured at
# 2.0e-16 on the seam test's own group, which is about one ulp.
# --------------------------------------------------------------------------

#: Row-major upper triangle of a symmetric 6x6, in the order the record stores it.
_MOMENT_TRIANGLE = tuple((i, j) for i in range(6) for j in range(i, 6))

MOTION_MOMENT_FIELDS = frozenset({"matrix", "facet_count", "area", "centroid_sum"})


def region_motion_moments(
    points: Sequence[Vec3], normals: Sequence[Any], areas: Sequence[float]
) -> dict[str, Any] | None:
    """One region's raw kinematic moments, or ``None`` when it carries no usable facet.

    Raw means *un-centred, un-scaled and weighted by real area*: those are the
    three properties that make the block additive.  A block centred on its own
    region could not be summed with its neighbour's, and one whose weights were
    already normalized to that region's mean facet size would silently re-weight
    the group by how finely each member happened to be tessellated.

    A facet whose normal does not normalize is dropped from all four fields
    together, so ``facet_count``, ``area``, ``centroid_sum`` and ``matrix``
    always describe the same set of facets.
    """
    if not (len(points) == len(normals) == len(areas)):
        raise ValueError("region moments need one normal and one area per facet.")
    kept_points: list[Vec3] = []
    kept_normals: list[Vec3] = []
    kept_areas: list[float] = []
    for point, raw_normal, area in zip(points, normals, areas):
        normal = _unit(_as_point(raw_normal, "facet_normals"))
        value = float(area)
        if normal is None or not math.isfinite(value) or value <= 0.0:
            continue
        kept_points.append(_as_point(point, "facet_centroids"))
        kept_normals.append(normal)
        kept_areas.append(value)
    if not kept_points:
        return None
    total = sum(kept_areas)
    mean = total / len(kept_areas)
    # `_normal_moments` divides the weights by their own mean; multiplying the
    # result back by that mean recovers the raw area-weighted sum exactly, so
    # there is one accumulation loop in this module rather than two.
    matrix, used, _weight = _normal_moments(
        kept_points, kept_normals, (0.0, 0.0, 0.0), 1.0, kept_areas
    )
    return {
        "matrix": [matrix[i][j] * mean for i, j in _MOMENT_TRIANGLE],
        "facet_count": used,
        "area": total,
        "centroid_sum": [
            sum(p[0] for p in kept_points),
            sum(p[1] for p in kept_points),
            sum(p[2] for p in kept_points),
        ],
    }


def route_kinematic_group(
    moments: Sequence[Mapping[str, Any]],
    extent: float,
    *,
    sigma_theta_rad: float,
    residual_sigma_factor: float,
    eigengap_min: float,
    translation_epsilon: float,
    pitch_epsilon: float,
    signature: str | None = None,
) -> dict[str, Any]:
    """Route a *set* of regions from their carried moment blocks.

    The blocks are summed in the mesh frame, then taken to the group's own
    centred, unit-extent frame by the congruence ``M' = T M T^T`` with

        T = [[I/s, -C/s], [0, I]],   C n = centre x n

    which is exactly the change of variables ``x -> (x - centre) / s`` applied
    to the rows.  The area weights are re-normalized to the *group's* mean facet
    area, so a group's verdict does not depend on how finely each member was
    tessellated relative to the others -- only on how much surface each supplies.
    That re-weighting is the whole reason a 4 mm^2 corner round cannot certify a
    2000 mm^2 plate as a solid of revolution.
    """
    blocks = [m for m in moments if m]
    if not blocks:
        raise ValueError("the group router needs at least one region's moments.")
    count = sum(int(m["facet_count"]) for m in blocks)
    area = sum(float(m["area"]) for m in blocks)
    if count < 6:
        raise ValueError("the group router needs at least six facets for a six-parameter fit.")
    if not math.isfinite(area) or area <= 0.0:
        raise ValueError("the group router needs a positive total facet area.")
    if not math.isfinite(extent) or extent <= 0.0:
        raise ValueError("the group router needs a positive extent.")
    centre = (
        sum(float(m["centroid_sum"][0]) for m in blocks) / count,
        sum(float(m["centroid_sum"][1]) for m in blocks) / count,
        sum(float(m["centroid_sum"][2]) for m in blocks) / count,
    )
    # sum(area_i b b^T), then to mean-one weights over the whole group.
    factor = count / area
    raw = [[0.0] * 6 for _ in range(6)]
    for block in blocks:
        entries = block["matrix"]
        for index, (i, j) in enumerate(_MOMENT_TRIANGLE):
            raw[i][j] += float(entries[index]) * factor
    for i in range(6):
        for j in range(i):
            raw[i][j] = raw[j][i]
    # T's rows: the moment half is (x x n)/s - (centre x n)/s, the normal half
    # is untouched. Written as a 6x6 so the congruence is one loop.
    cx, cy, cz = centre
    transform = [
        [1.0 / extent, 0.0, 0.0, 0.0, cz / extent, -cy / extent],
        [0.0, 1.0 / extent, 0.0, -cz / extent, 0.0, cx / extent],
        [0.0, 0.0, 1.0 / extent, cy / extent, -cx / extent, 0.0],
        [0.0, 0.0, 0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
    ]
    intermediate = [
        [sum(transform[i][k] * raw[k][j] for k in range(6)) for j in range(6)] for i in range(6)
    ]
    matrix = [
        [sum(intermediate[i][k] * transform[j][k] for k in range(6)) for j in range(6)]
        for i in range(6)
    ]
    record = _route_from_moments(
        matrix,
        count,
        centre,
        extent,
        sigma_theta_rad=sigma_theta_rad,
        residual_sigma_factor=residual_sigma_factor,
        eigengap_min=eigengap_min,
        translation_epsilon=translation_epsilon,
        pitch_epsilon=pitch_epsilon,
        signature=signature,
    )
    record["region_count"] = len(blocks)
    record["facet_area"] = area
    return record


def _cylinder_over_sphere(
    fits: Sequence[PrimitiveFit], normals: Sequence[Any], max_perpendicular_deg: float
) -> tuple[PrimitiveFit, ...]:
    """Break the sphere/cylinder tie on facet normals, which the vertices cannot.

    A bore or a round tessellated with two rings of vertices and no intermediate
    samples puts every one of its vertices *exactly* on a sphere as well as on
    its cylinder -- a 2 mm corner round 1.6 mm tall fits a sphere of radius
    sqrt(2.0^2 + 0.8^2) = 2.15407 at rms 0.0.  Both fits are then accepted at
    float noise and ranking by residual alone hands the group to the sphere by
    the eighth decimal.  Neither parsimony nor sphere occupancy catches it,
    because to the *vertices* the sphere really is the better fit.

    The facets say otherwise: every facet normal of a cylinder is perpendicular
    to its axis, and no sphere's are.  Measured over 11 production STLs, 367 of
    367 groups that fitted a sphere better than a cylinder were cylinders, and
    every one held its facet normals within 5 degrees of perpendicular.  So the
    cylinder takes the group only when the normals actually say so; the angle is
    the caller's, and unreadable normals leave the ranking alone.
    """
    if not fits or not fits[0].accepted or fits[0].kind != "sphere":
        return tuple(fits)
    cylinder = next((f for f in fits if f.accepted and f.kind == "cylinder"), None)
    if cylinder is None:
        return tuple(fits)
    axis = _unit(_as_direction(cylinder.parameters["axis_direction"], "axis_direction"))
    if axis is None:
        return tuple(fits)
    worst = _perpendicularity_deg(normals, axis)
    if worst is None or worst > max_perpendicular_deg:
        return tuple(fits)
    cylinder.support["normal_tie_break"] = {
        "over": "sphere",
        "max_deviation_from_perpendicular_deg": worst,
        "declared_max_deg": max_perpendicular_deg,
        "sphere_relative_residual": fits[0].relative_residual,
        "cylinder_relative_residual": cylinder.relative_residual,
    }
    _passed(cylinder.support.setdefault("checked", []), "cylinder-normal-tie-break")
    return (cylinder,) + tuple(f for f in fits if f is not cylinder)


def _normal_direction_spread(
    normals: Sequence[Any], axis: Vec3, merge_deg: float
) -> dict[str, Any] | None:
    """How many distinct directions the facet normals occupy around ``axis``.

    A cylinder's facet normals sweep its axis continuously: a tessellation of
    ``n`` facets across an arc puts ``n`` distinct normals along that arc, evenly
    spaced by the exporter's chord tolerance.  A prism's do not -- every facet on
    one planar wall carries the *same* normal, so the distribution is a handful
    of spikes with the wall count as its cardinality however many facets there
    are.  Both fit the same circle through the same vertices, because a regular
    polygon's corners lie exactly on its circumscribed circle; only the normals
    tell them apart.

    Azimuths are merged at ``merge_deg``, the caller's measurement floor on a
    facet normal's direction, by **complete** linkage: a direction joins the
    open cluster only while it stays within ``merge_deg`` of that cluster's
    *first* member, so no cluster is ever wider than the floor it was merged at.
    Single linkage -- comparing against the cluster's last member -- chains
    instead: on a scan the floor is the mesh's own normal noise, which is
    routinely wider than the spacing of a fine tessellation, and every azimuth
    around the turn then falls within the floor of its predecessor and the whole
    sweep collapses to one direction.  A genuine 360-facet cylinder measured
    that way reported one direction, zero per turn, and was refused as a prism.

    So ``merge_deg`` is a *noise* width and not a design angle: on a tessellation
    it is float precision and only exactly parallel facets merge; on a scan it is
    wider, and clusters of that width still leave a genuine sweep with far more
    directions per turn than any prism has walls -- which is correct, since
    discrete normals are a tessellation signature and a scan has none.

    ``angular_coverage_deg`` is 360 minus the largest gap between adjacent
    directions: the arc the directions actually occupy, so a partial round is
    measured over its own arc rather than penalised for the arc it does not
    cover.  ``None`` when a normal is unreadable -- absent evidence refuses
    rather than defaulting to a spread nobody measured.
    """
    u, v = _frame(axis)
    azimuths: list[float] = []
    for raw in normals:
        vector = _unit(_as_point(raw, "facet_normals"))
        if vector is None:
            return None
        x, y = _dot(vector, u), _dot(vector, v)
        if math.hypot(x, y) <= _ZERO_RESIDUAL_FLOOR_RATIO:
            # Parallel to the axis: an end cap swept into the group, carrying no
            # azimuth at all. Not evidence either way, so it is not counted.
            continue
        azimuths.append(math.degrees(math.atan2(y, x)) % 360.0)
    if len(azimuths) < 2:
        return None
    azimuths.sort()
    clusters = [[azimuths[0]]]
    for angle in azimuths[1:]:
        if angle - clusters[-1][0] <= merge_deg:
            clusters[-1].append(angle)
        else:
            clusters.append([angle])
    if len(clusters) > 1 and (clusters[0][-1] + 360.0) - clusters[-1][0] <= merge_deg:
        clusters[0] = clusters.pop() + clusters[0]
    representatives = sorted(cluster[0] for cluster in clusters)
    directions = len(representatives)
    if directions < 2:
        # Every facet normal points the same way: that is one plane, and a plane
        # has no arc to spread over.
        return {
            "facet_count": len(azimuths),
            "directions": directions,
            "angular_coverage_deg": 0.0,
            "directions_per_turn": 0.0,
            "largest_gap_deg": 360.0,
            "merge_tolerance_deg": merge_deg,
        }
    gaps = [representatives[i + 1] - representatives[i] for i in range(directions - 1)]
    gaps.append(representatives[0] + 360.0 - representatives[-1])
    coverage = 360.0 - max(gaps)
    return {
        "facet_count": len(azimuths),
        "directions": directions,
        "angular_coverage_deg": coverage,
        "directions_per_turn": directions * 360.0 / coverage if coverage > 0.0 else math.inf,
        "largest_gap_deg": max(gaps),
        "merge_tolerance_deg": merge_deg,
    }


def _prism_of_planes(
    fits: Sequence[PrimitiveFit],
    normals: Sequence[Any],
    axis: Vec3,
    max_perpendicular_deg: float,
    minimum_per_turn: float,
    merge_deg: float,
) -> tuple[PrimitiveFit, ...]:
    """Refuse a curved fit whose facet normals are a prism's spikes, not a sweep.

    The measured case: a hexagonal pocket's six planar walls arrive as one face
    group, and a regular polygon's corners lie *exactly* on its circumscribed
    circle -- so the vertex fit returns the right radius at float-noise residual
    and every existing gate passes it.  Six 26 mm across-corners hex pockets on
    the honeycomb organiser came back as six 26 mm round bores, and the vendor's
    own STEP -- 145 planar faces, not one curved surface -- says they are not.
    Those same corners lie on a *sphere* as well, so refusing only the cylinder
    hands the group to the sphere; the verdict is therefore about the group and
    every curved primitive over it falls with the same named gate.

    Two conditions, both from evidence this run already carries:

    * the facet normals are perpendicular to a common axis, within the caller's
      already-declared ``cylinder_normal_perpendicular_deg``.  This is what says
      "these facets are arranged around an axis" and it is what excludes a real
      sphere, whose normals are perpendicular to nothing;
    * they occupy fewer distinct directions per turn than the caller declared.

    The threshold is measured against the tessellation, not against a shape: a
    genuine tessellated circle carries one normal direction per facet, and below
    ``min_cylinder_normal_directions_per_turn`` the facets are further apart than
    any exporter's chord tolerance would leave them.
    """
    curved = [f for f in fits if f.accepted and f.kind != "plane"]
    if not curved:
        return tuple(fits)
    perpendicular = _perpendicularity_deg(normals, axis)
    if perpendicular is None or perpendicular > max_perpendicular_deg:
        # The normals are not arranged around this axis at all, so "prism" is not
        # a claim the evidence supports either way.
        return tuple(fits)
    spread = _normal_direction_spread(normals, axis, merge_deg)
    if spread is None:
        return tuple(fits)
    measured = dict(
        spread,
        min_directions_per_turn=minimum_per_turn,
        max_deviation_from_perpendicular_deg=perpendicular,
        declared_max_perpendicular_deg=max_perpendicular_deg,
    )
    out: list[PrimitiveFit] = []
    discrete = spread["directions_per_turn"] < minimum_per_turn
    # One direction has no arc, so saying it occupies "0 degrees of arc" reads as
    # a measurement that refutes its own premise. It is a different sentence.
    if spread["directions"] < 2:
        occupancy = (
            f"all point the same way, within the {spread['merge_tolerance_deg']:.4g} degree "
            "measurement floor on a normal's direction: one wall, with no arc to sweep"
        )
    else:
        occupancy = (
            f"occupy only {spread['directions']} distinct directions across "
            f"{spread['angular_coverage_deg']:.4g} degrees of arc -- "
            f"{spread['directions_per_turn']:.4g} per full turn, below the declared "
            f"{minimum_per_turn:g}"
        )
    for fit in fits:
        if fit not in curved:
            out.append(fit)
            continue
        support = dict(fit.support)
        support["normal_direction_spread"] = dict(measured)
        if not discrete:
            checked = list(support.get("checked", ()))
            _passed(checked, "cylinder-normals-discrete")
            support["checked"] = checked
            out.append(
                PrimitiveFit(
                    kind=fit.kind,
                    accepted=True,
                    rms_residual=fit.rms_residual,
                    relative_residual=fit.relative_residual,
                    extent=fit.extent,
                    parameters=dict(fit.parameters),
                    support=support,
                    uncertainty=dict(fit.uncertainty),
                )
            )
            continue
        out.append(
            _rejected(
                fit.kind,
                fit.extent,
                f"cylinder-normals-discrete: the {spread['facet_count']} facet normals sit within "
                f"{perpendicular:.4g} degrees of perpendicular to one axis but "
                f"{occupancy}. A curved surface's normals sweep; these are the spikes of "
                "a prism of planar walls whose corners happen to lie on the circle -- and on the "
                f"sphere -- this {fit.kind} fits.",
                support,
            )
        )
    return tuple(out)


def _normal_constrained_cylinder(
    fits: Sequence[PrimitiveFit],
    points: Sequence[Vec3],
    evidence: Mapping[str, Any],
    eigengap_min: float,
    gates: Mapping[str, Any],
) -> tuple[PrimitiveFit, ...]:
    """Refit the winning cylinder about the axis its facet normals determined.

    The vertices of a bore tessellated as two rings determine a radius and not an
    axis; the facets between them determine the axis and not much else.  So the
    two halves are taken from the evidence that carries each: the direction from
    the normal second moment, and then -- with the direction pinned -- the radius
    and the axis point from the module's existing exact 2-D circle fit.

    The axis tilt sigma is *replaced*, not blended, by the joint system's.  The
    vertex-side Jacobian for a two-ring group reports a tilt sigma computed from a
    matrix that is going singular, and averaging an honest number with a
    meaningless one produces a meaningless one.  ``uncertainty`` records both,
    under names that say which is which.

    A normal system whose eigengap is below the declared floor changes nothing:
    the normals were consulted, they did not determine an axis either, and the
    record says so rather than silently keeping the vertex answer as though it
    had been confirmed.
    """
    ordered = list(fits)
    cylinder = next((f for f in ordered if f.accepted and f.kind == "cylinder"), None)
    if cylinder is None or ordered[0] is not cylinder:
        return tuple(ordered)
    measured = {
        "eigengap": evidence["eigengap"],
        "eigengap_min": eigengap_min,
        "axis_tilt_sigma_deg": evidence["axis_tilt_sigma_deg"],
        "sigma_theta_deg": evidence["sigma_theta_deg"],
        "measured_sigma_theta_deg": evidence["measured_sigma_theta_deg"],
        "sigma_theta_floor_deg": evidence["sigma_theta_floor_deg"],
        "effective_facet_count": evidence["effective_facet_count"],
        "facet_count": evidence["facet_count"],
        "method": evidence["method"],
    }
    if evidence["eigengap"] < eigengap_min:
        cylinder.support["axis_evidence"] = dict(
            measured,
            source="vertices",
            reason=(
                f"the facet normals span an eigengap of {evidence['eigengap']:.4g}, below the "
                f"declared {eigengap_min:g}; they do not determine an axis either, so the vertex "
                "fit stands unchanged rather than being confirmed by evidence that did not confirm "
                "it."
            ),
        )
        return tuple(ordered)

    refit = fit_primitive(points, "cylinder", fixed_axis=evidence["axis"], **dict(gates))
    if not refit.accepted:
        cylinder.support["axis_evidence"] = dict(
            measured,
            source="vertices",
            reason=(
                "the normal-determined axis was refused by the same gates the vertex fit passed "
                f"({refit.rejection}); the vertex fit stands and this is recorded rather than "
                "silently discarded."
            ),
        )
        return tuple(ordered)

    refit.support["axis_evidence"] = dict(
        measured,
        source="facet-normals",
        vertex_axis_direction=list(cylinder.parameters["axis_direction"]),
        vertex_relative_residual=cylinder.relative_residual,
        reason=(
            "the axis came from the facet normals, which are perpendicular to it by construction, "
            "and the radius and axis point from the exact circle fit in the plane that axis defines."
        ),
    )
    _passed(refit.support.setdefault("checked", []), "normal-constrained-axis")
    return (refit,) + tuple(f for f in ordered if f is not cylinder)


def fit_face_group(
    points: Any,
    *,
    kinds: Iterable[str] = ("plane", "cylinder", "cone", "sphere"),
    facet_normals: Sequence[Any] | None = None,
    cylinder_perpendicular_deg: float | None = None,
    facet_centroids: Sequence[Any] | None = None,
    facet_areas: Sequence[float] | None = None,
    normal_axis_eigengap_min: float | None = None,
    normal_sigma_theta_floor_deg: float | None = None,
    min_cylinder_normal_directions_per_turn: float | None = None,
    **gates: Any,
) -> tuple[PrimitiveFit, ...]:
    """Fit each requested primitive, accepted fits first by relative residual.

    Rejected fits stay in the result with their reason: "we could not fit this"
    is itself evidence, and dropping it would leave the caller unable to tell a
    refusal from a kind that was never tried.

    ``facet_normals`` -- one outward normal per facet of the group -- and the
    caller-declared ``cylinder_perpendicular_deg`` enable the sphere/cylinder
    tie-break above.  Both are needed: a caller that supplies neither gets the
    residual ranking unchanged, which is what every caller got before.

    ``facet_centroids``, ``facet_areas`` and the caller-declared
    ``normal_axis_eigengap_min`` / ``normal_sigma_theta_floor_deg`` /
    ``min_cylinder_normal_directions_per_turn`` additionally turn those normals
    from a tie-break into *fit data*: a winning cylinder is refitted about the
    axis they determine, with the joint uncertainty that determination carries,
    and a cylinder whose normals are a prism's discrete spikes rather than a
    sweep is refused.  All five are declared together or not at all.
    """
    requested = list(kinds)
    for kind in requested:
        if not _in_closed_set(kind, PRIMITIVE_KINDS):
            raise ValueError(f"kind must be one of {', '.join(sorted(PRIMITIVE_KINDS))}.")
    if (facet_normals is None) != (cylinder_perpendicular_deg is None):
        raise ValueError(
            "facet_normals and cylinder_perpendicular_deg are declared together or not at all; "
            "an angle with no normals checks nothing and normals with no declared angle would "
            "need a threshold this module invented."
        )
    if cylinder_perpendicular_deg is not None:
        _as_tolerance(cylinder_perpendicular_deg, "cylinder_perpendicular_deg")
    constrained = (
        facet_centroids,
        facet_areas,
        normal_axis_eigengap_min,
        normal_sigma_theta_floor_deg,
        min_cylinder_normal_directions_per_turn,
    )
    if any(part is not None for part in constrained):
        if any(part is None for part in constrained) or facet_normals is None:
            raise ValueError(
                "normal-constrained fitting needs facet_normals, facet_centroids, facet_areas, "
                "normal_axis_eigengap_min, normal_sigma_theta_floor_deg and "
                "min_cylinder_normal_directions_per_turn together; a partial set would need this "
                "module to invent the rest."
            )
        _as_tolerance(normal_axis_eigengap_min, "normal_axis_eigengap_min")
        _as_tolerance(
            min_cylinder_normal_directions_per_turn, "min_cylinder_normal_directions_per_turn"
        )

    pts = _as_points(points, "points", 4)
    fits = [fit_primitive(pts, kind, **gates) for kind in requested]
    ordered = sorted(fits, key=lambda f: (not f.accepted, f.relative_residual))
    if facet_normals is None:
        return tuple(ordered)
    ordered = list(
        _cylinder_over_sphere(ordered, facet_normals, float(cylinder_perpendicular_deg))
    )
    if facet_centroids is None:
        return tuple(ordered)
    evidence = normal_constrained_axis(
        facet_centroids,
        facet_normals,
        facet_areas=facet_areas,
        sigma_theta_floor_deg=float(normal_sigma_theta_floor_deg),
    )
    if evidence is None:
        return tuple(ordered)
    ordered = list(
        _normal_constrained_cylinder(ordered, pts, evidence, float(normal_axis_eigengap_min), gates)
    )
    # Last, so it reads the axis the refit settled on rather than one it is about
    # to replace. The same accumulation, read a fourth way: its smallest
    # eigenvector is the axis the normals are perpendicular to, and how those
    # normals are spread *around* it says whether there is a curved surface there
    # at all. Stable on acceptance alone: a newly refused fit moves behind the
    # accepted ones and the tie-break's ordering among those survives, which
    # re-sorting by residual would silently undo.
    return tuple(
        sorted(
            _prism_of_planes(
                ordered,
                facet_normals,
                evidence["axis"],
                float(cylinder_perpendicular_deg),
                float(min_cylinder_normal_directions_per_turn),
                float(normal_sigma_theta_floor_deg),
            ),
            key=lambda f: not f.accepted,
        )
    )


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
