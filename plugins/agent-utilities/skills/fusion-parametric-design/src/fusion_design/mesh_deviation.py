from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .manifest import ManifestValidationError, ValidationIssue, _reject_unknown_fields
from .mesh_reconstruction import (
    _require_positive_number,
    _source_evidence,
    _validate_body_binding,
    require_classification,
)

if TYPE_CHECKING:
    from .manifest import Manifest


DEVIATION_SPEC_FIELDS = {"source", "reconstruction", "thresholds_mm", "rationale"}

DEVIATION_THRESHOLD_FIELDS = {"invented_material", "omitted_detail", "percentile_sample_limit"}

# The closed refusal vocabulary for a deviation run.  A run that invents a
# reason is a run nobody can write a handler for, and the verdict this transaction
# produces is the one a person quotes when they say the rebuild is faithful.
DEVIATION_FAILURES = frozenset(
    {
        "body-not-found",
        "deviation-capability",
        "deviation-comparison-empty",
        "containment-query-failed",
        "tessellation-failed",
        "sign-convention-unestablished",
        "invented-material",
        "invented-material-unclassified",
        "deviation-frames-differ",
    }
)


def validate_deviation_spec(spec: Any) -> list[ValidationIssue]:
    """Validate the deviation spec: the two bodies, and the declared thresholds."""
    issues: list[ValidationIssue] = []
    if not isinstance(spec, dict):
        return [
            ValidationIssue(
                "deviation-spec-must-be-object",
                "deviation_spec",
                "A deviation spec must be an object.",
            )
        ]
    _reject_unknown_fields(issues, spec, DEVIATION_SPEC_FIELDS, "deviation_spec")
    _validate_body_binding(
        issues, spec.get("source"), "deviation_spec.source", "deviation-spec-invalid-binding"
    )
    _validate_body_binding(
        issues,
        spec.get("reconstruction"),
        "deviation_spec.reconstruction",
        "deviation-spec-invalid-binding",
    )
    thresholds = spec.get("thresholds_mm")
    if not isinstance(thresholds, dict):
        issues.append(
            ValidationIssue(
                "deviation-spec-invalid-thresholds",
                "deviation_spec.thresholds_mm",
                "thresholds_mm must be declared per reconstruction and recorded with the verdict.",
            )
        )
    else:
        _reject_unknown_fields(
            issues, thresholds, DEVIATION_THRESHOLD_FIELDS, "deviation_spec.thresholds_mm"
        )
        for field in ("invented_material", "omitted_detail"):
            _require_positive_number(
                issues,
                thresholds.get(field),
                f"deviation_spec.thresholds_mm.{field}",
                "deviation-spec-invalid-thresholds",
                f"thresholds_mm.{field} must be a positive number of millimetres declared for this "
                "reconstruction; it is never a module constant.",
            )
        limit = thresholds.get("percentile_sample_limit")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            issues.append(
                ValidationIssue(
                    "deviation-spec-invalid-thresholds",
                    "deviation_spec.thresholds_mm.percentile_sample_limit",
                    "percentile_sample_limit must be a positive integer; it bounds only the percentile "
                    "sample, never the exact comparison against a threshold.",
                )
            )
    rationale = spec.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        issues.append(
            ValidationIssue(
                "deviation-spec-invalid-rationale",
                "deviation_spec.rationale",
                "Record why these thresholds are the right ones for this reconstruction.",
            )
        )
    return issues


def emit_mesh_deviation_script(
    manifest: "Manifest",
    classification_record: Any,
    source_record: Any,
    spec: Any,
) -> str:
    """Emit the deviation transaction and its asymmetric, two-directional verdict.

    The two directions answer different questions and are never collapsed into
    one number.  Both are measured with released, non-preview APIs: the
    reconstruction's own boundary comes from ``MeshManager.createMeshCalculator``
    at a declared surface tolerance, the side comes from
    ``BRepBody.pointContainment``, and the distances are computed here, because
    Fusion has no point-to-mesh distance query and its point-to-*face* query is
    untrimmed.  ``PolygonMesh.compareWith`` -- preview, and unavailable to a
    B-Rep reconstruction because a ``BRepBody``'s mesh is a ``TriangleMesh``,
    which has no ``compareWith`` -- is kept only as a corroboration path and is
    never preferred over the native measurement.
    """
    from .scripts import _json_literal, _script_prelude

    classification = require_classification(
        classification_record,
        "mesh-deviation-verdict",
        {"faceted-brep", "parametric-rebuild"},
        source_record,
    )
    issues = validate_deviation_spec(spec)
    if issues:
        raise ManifestValidationError(issues)

    specs = {
        "classification": classification.to_dict(),
        "mesh_source": _source_evidence(source_record),
        "source": dict(spec["source"]),
        "reconstruction": dict(spec["reconstruction"]),
        "thresholds_mm": dict(spec["thresholds_mm"]),
        "rationale": str(spec["rationale"]).strip(),
    }

    transaction = '''import math

DEVIATION_SPECS = json.loads(__DEVIATION_SPECS__)

RECONSTRUCTION_TO_SOURCE_QUESTION = (
    "How far does the reconstructed surface sit from the nearest scanned surface? This answers whether "
    "the rebuild stayed on the scan. It says nothing about scanned detail the rebuild never modelled."
)
SOURCE_TO_RECONSTRUCTION_QUESTION = (
    "How far does each scanned point sit from the reconstruction's boundary, and is it inside or "
    "outside the reconstructed solid? This answers whether the rebuild captured what was scanned, and "
    "whether it put material where the scan says the part ends. It says nothing about rebuilt surface "
    "standing where the scan has no points at all."
)
# The convention, stated once and verified in the transaction before it is used.
CONTAINMENT_CONVENTION = (
    "A scanned vertex that BRepBody.pointContainment reports INSIDE the reconstruction is a point where "
    "the reconstruction's material extends past the scanned surface: the rebuild put solid where the "
    "scan says the part ends. That is invented material. A scanned vertex reported OUTSIDE is a point "
    "the scan carries and the reconstruction does not reach: omitted detail. PointOnPointContainment is "
    "neither, and measures zero."
)
INVENTED_MEANING = (
    "Rebuilt material outside the source solid is invented geometry, and that is categorically worse "
    "than omitted detail."
)
OMITTED_MEANING = (
    "Scanned detail the rebuild did not model. Advisory: a rebuild models only the geometry the edit "
    "requires."
)
UNSIGNED_DIRECTION_MEANING = (
    "This direction is unsigned. A rebuilt surface sample far from every scanned surface may be "
    "invented material or a region the rebuild deliberately simplified, and this measurement does not "
    "decide which. The invented-material verdict rests on the signed source_to_reconstruction "
    "measurement, whose sign is verified against this body before it is read."
)
UNCLASSIFIED_MEANING = (
    "No scanned vertex lies inside the reconstruction beyond the threshold, but the reconstruction's "
    "own tessellation does reach past it from every scanned surface. A scan carries only the vertices "
    "it captured: material invented *between* two of them leaves each one on the reconstruction's "
    "boundary, so the signed direction measures zero while the unsigned one does not. That direction "
    "cannot say whether this is invented material or deliberate simplification, so it does not fail "
    "the run for invented material -- but it does disprove the absence of it, and the absence is what "
    "a pass would claim. Classify these samples against a closed source mesh to settle it."
)
VERDICT_NOTE = (
    "These two numbers answer different questions and neither certifies the other. A small maximum "
    "deviation from the reconstruction to the scan does not establish that the reconstruction captured "
    "every scanned feature."
)


def _target_component(design, component_path):
    if not component_path:
        return design.rootComponent, None, None
    _, occurrence_map, duplicate_semantic_paths = _root_context_occurrence_map(design.rootComponent)
    if component_path in duplicate_semantic_paths:
        return None, "duplicate-semantic-path", None
    occurrence = occurrence_map.get(component_path)
    if occurrence is None:
        return None, "component-path-missing", None
    return occurrence.component, None, occurrence


_IDENTITY_MATRIX = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)


def _non_identity_transform(holder, attribute):
    """``holder.<attribute>`` as a flat matrix when it is not the identity.

    Both sets of coordinates this verdict compares are read in their own body's
    local frame -- ``PolygonMesh.nodeCoordinates`` and the tessellation of the
    reconstruction -- and ``BRepBody.pointContainment`` takes points in the
    body's own frame too. An occurrence transform or a mesh body's own transform
    puts those frames somewhere else, and nothing here composes them: two
    occurrences with identical local geometry and different assembly positions
    would compare as a perfect match, and two physically aligned bodies in
    different local frames would fail. So a transform that is not the identity
    is *detected* and refused rather than silently ignored.
    """
    matrix = getattr(holder, attribute, None)
    if matrix is None:
        return None
    values = getattr(matrix, "asArray", None)
    if values is None:
        return None
    try:
        flat = [float(value) for value in values()]
    except Exception:
        return None
    if len(flat) != 16:
        return flat
    # A tenth of a micron on the translation terms and 1e-9 on the rest: this
    # is guarding float noise in a matrix Fusion built, not admitting a shift.
    for index, (measured, expected) in enumerate(zip(flat, _IDENTITY_MATRIX)):
        tolerance = 1e-05 if index in (3, 7, 11) else 1e-09
        if abs(measured - expected) > tolerance:
            return flat
    return None


def _named_body(component, body_name):
    for attribute in ("meshBodies", "bRepBodies"):
        bodies = getattr(component, attribute, None)
        if bodies is None:
            continue
        for index in range(bodies.count):
            body = bodies.item(index)
            if getattr(body, "name", None) == body_name:
                return body, attribute
    return None, None


def _polygon_mesh(body):
    """The PolygonMesh for a body, or None.

    Only MeshBody.mesh is a PolygonMesh. Everything a BRepBody offers through its
    meshManager is a TriangleMesh, which carries no compareWith, which is why the
    preview comparison can never be the mechanism for a B-Rep reconstruction.
    """
    return getattr(body, "mesh", None)


def _percentiles(values, limit):
    """Percentiles may be sampled; a threshold comparison never is."""
    if not values:
        return {}, False, 1
    stride = 1
    if len(values) > limit:
        stride = (len(values) // limit) + 1
    sample = sorted(values[::stride])
    sampled = stride > 1
    result = {}
    for name, fraction in (("p50", 0.5), ("p95", 0.95), ("p99", 0.99), ("max_of_sample", 1.0)):
        index = int(round(fraction * (len(sample) - 1)))
        result[name] = sample[index]
    return result, sampled, stride


def _worst(points, distances, threshold, count):
    ranked = sorted(range(len(distances)), key=lambda index: -distances[index])
    worst = []
    for index in ranked[:count]:
        if distances[index] <= threshold:
            break
        entry = {"distance_mm": distances[index]}
        if index < len(points):
            entry["point_mm"] = points[index]
        worst.append(entry)
    return worst


def _mesh_triangles_mm(mesh):
    """The source mesh as flat millimetre vertices and flat triangle indices."""
    coordinates = getattr(mesh, "nodeCoordinates", None) or []
    indices = getattr(mesh, "triangleNodeIndices", None) or []
    vertices = []
    for node in coordinates:
        vertices.append(node.x * 10.0)
        vertices.append(node.y * 10.0)
        vertices.append(node.z * 10.0)
    return vertices, [int(value) for value in indices]


def _median_edge_mm(vertices, triangles):
    """The median triangle edge of the source mesh, in millimetres.

    This is the scan's own resolution: the reconstruction is sampled at this
    spacing so the sampling cannot step over a feature the mesh was able to
    express in the first place.
    """
    lengths = []
    for offset in range(0, len(triangles) - 2, 3):
        a = triangles[offset] * 3
        b = triangles[offset + 1] * 3
        c = triangles[offset + 2] * 3
        for first, second in ((a, b), (b, c), (c, a)):
            dx = vertices[first] - vertices[second]
            dy = vertices[first + 1] - vertices[second + 1]
            dz = vertices[first + 2] - vertices[second + 2]
            lengths.append(math.sqrt(dx * dx + dy * dy + dz * dz))
    if not lengths:
        return None
    lengths.sort()
    return lengths[len(lengths) // 2]


def _point_triangle_distance_sq(px, py, pz, ax, ay, az, bx, by, bz, cx, cy, cz):
    """Squared distance from a point to a triangle, closed form.

    Ericson's region test: the closest point on a triangle is in its interior, on
    one of three edges, or at one of three vertices, and each case is decided by
    the barycentric sign pattern. The degenerate branches are kept because a
    scanned mesh does carry slivers, and a version that only handled the interior
    case would silently return the distance to the plane of a sliver instead of
    to the sliver.
    """
    abx = bx - ax
    aby = by - ay
    abz = bz - az
    acx = cx - ax
    acy = cy - ay
    acz = cz - az
    apx = px - ax
    apy = py - ay
    apz = pz - az
    d1 = abx * apx + aby * apy + abz * apz
    d2 = acx * apx + acy * apy + acz * apz
    if d1 <= 0.0 and d2 <= 0.0:
        return apx * apx + apy * apy + apz * apz
    bpx = px - bx
    bpy = py - by
    bpz = pz - bz
    d3 = abx * bpx + aby * bpy + abz * bpz
    d4 = acx * bpx + acy * bpy + acz * bpz
    if d3 >= 0.0 and d4 <= d3:
        return bpx * bpx + bpy * bpy + bpz * bpz
    cpx = px - cx
    cpy = py - cy
    cpz = pz - cz
    d5 = abx * cpx + aby * cpy + abz * cpz
    d6 = acx * cpx + acy * cpy + acz * cpz
    if d6 >= 0.0 and d5 <= d6:
        return cpx * cpx + cpy * cpy + cpz * cpz
    vc = d1 * d4 - d3 * d2
    if vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:
        denominator = d1 - d3
        v = d1 / denominator if denominator != 0.0 else 0.0
        qx = px - (ax + v * abx)
        qy = py - (ay + v * aby)
        qz = pz - (az + v * abz)
        return qx * qx + qy * qy + qz * qz
    vb = d5 * d2 - d1 * d6
    if vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:
        denominator = d2 - d6
        w = d2 / denominator if denominator != 0.0 else 0.0
        qx = px - (ax + w * acx)
        qy = py - (ay + w * acy)
        qz = pz - (az + w * acz)
        return qx * qx + qy * qy + qz * qz
    va = d3 * d6 - d5 * d4
    if va <= 0.0 and (d4 - d3) >= 0.0 and (d5 - d6) >= 0.0:
        denominator = (d4 - d3) + (d5 - d6)
        w = (d4 - d3) / denominator if denominator != 0.0 else 0.0
        qx = px - (bx + w * (cx - bx))
        qy = py - (by + w * (cy - by))
        qz = pz - (bz + w * (cz - bz))
        return qx * qx + qy * qy + qz * qz
    denominator = va + vb + vc
    if denominator == 0.0:
        return apx * apx + apy * apy + apz * apz
    v = vb / denominator
    w = vc / denominator
    qx = px - (ax + abx * v + acx * w)
    qy = py - (ay + aby * v + acy * w)
    qz = pz - (az + abz * v + acz * w)
    return qx * qx + qy * qy + qz * qz


class _TriangleGrid(object):
    """A uniform grid over the source mesh's triangles, for point-to-mesh distance.

    Fusion has no point-to-mesh distance query at all: measureMinimumDistance
    rejects a MeshBody ("measurement failed") and a PolygonMesh ("invalid
    argument"), on a closed mesh as well as an open one, measured on this Fusion.
    So both directions are computed here, from the same nodeCoordinates and
    triangleNodeIndices the hash-bound dump is written from, with the stdlib
    alone -- numpy inside Fusion is a probed capability, and a verdict must not
    rest on a dependency that can be absent.

    ponytail: uniform grid, not a BVH. Cells are sized off the mesh's own median
    edge, which is what makes the occupancy even; a BVH only pays for itself on a
    mesh whose triangle sizes span orders of magnitude, and then only if the grid
    is measured to be the bottleneck.
    """

    def __init__(self, vertices, triangles, cell_mm):
        self.vertices = vertices
        self.triangles = triangles
        self.cell = cell_mm
        self.buckets = {}
        self.oversized = []
        for offset in range(0, len(triangles) - 2, 3):
            a = triangles[offset] * 3
            b = triangles[offset + 1] * 3
            c = triangles[offset + 2] * 3
            low_x = min(vertices[a], vertices[b], vertices[c])
            low_y = min(vertices[a + 1], vertices[b + 1], vertices[c + 1])
            low_z = min(vertices[a + 2], vertices[b + 2], vertices[c + 2])
            high_x = max(vertices[a], vertices[b], vertices[c])
            high_y = max(vertices[a + 1], vertices[b + 1], vertices[c + 1])
            high_z = max(vertices[a + 2], vertices[b + 2], vertices[c + 2])
            i0 = int(math.floor(low_x / cell_mm))
            j0 = int(math.floor(low_y / cell_mm))
            k0 = int(math.floor(low_z / cell_mm))
            i1 = int(math.floor(high_x / cell_mm))
            j1 = int(math.floor(high_y / cell_mm))
            k1 = int(math.floor(high_z / cell_mm))
            span = (i1 - i0 + 1) * (j1 - j0 + 1) * (k1 - k0 + 1)
            # A triangle far larger than the median edge would be copied into
            # hundreds of cells; those few are checked on every query instead,
            # which costs a constant and keeps the grid from exploding.
            if span > 27:
                self.oversized.append(offset)
                continue
            for i in range(i0, i1 + 1):
                for j in range(j0, j1 + 1):
                    for k in range(k0, k1 + 1):
                        key = (i, j, k)
                        if key in self.buckets:
                            self.buckets[key].append(offset)
                        else:
                            self.buckets[key] = [offset]

    def _triangle_distance_sq(self, offset, x, y, z):
        a = self.triangles[offset] * 3
        b = self.triangles[offset + 1] * 3
        c = self.triangles[offset + 2] * 3
        vertices = self.vertices
        return _point_triangle_distance_sq(
            x,
            y,
            z,
            vertices[a],
            vertices[a + 1],
            vertices[a + 2],
            vertices[b],
            vertices[b + 1],
            vertices[b + 2],
            vertices[c],
            vertices[c + 1],
            vertices[c + 2],
        )

    def nearest_mm(self, x, y, z):
        """Distance from a point to the nearest triangle, or None on an empty mesh."""
        best = None
        for offset in self.oversized:
            value = self._triangle_distance_sq(offset, x, y, z)
            if best is None or value < best:
                best = value
        if not self.buckets:
            return None if best is None else math.sqrt(best)
        cell = self.cell
        ci = int(math.floor(x / cell))
        cj = int(math.floor(y / cell))
        ck = int(math.floor(z / cell))
        low_i, low_j, low_k, high_i, high_j, high_k = self._extent_box()
        # Every occupied cell lies in this box, so a ring below the box's own
        # Chebyshev distance is empty by construction and a ring above it meets
        # the box only where the two overlap. Without both, one query on a
        # displaced reconstruction walks the empty space between the bodies cell
        # by cell: at a 0.1 mm cell and 100 mm of displacement that is a
        # thousand shells of up to 24 million lookups each, inside a transaction
        # Fusion runs this for every node.
        ring = max(
            0, low_i - ci, ci - high_i, low_j - cj, cj - high_j, low_k - ck, ck - high_k
        )
        # Everything in the grid is inside this many rings of the query cell, so
        # the loop terminates even for a point far outside the mesh.
        limit = self._ring_limit(ci, cj, ck)
        while True:
            # A cell in ring r is at least (r - 1) cells away from the query
            # point, which sits somewhere inside ring 0. Stop as soon as that
            # lower bound cannot beat the best triangle already found.
            if ring > 0 and best is not None:
                lower = (ring - 1) * cell
                if lower > 0.0 and best <= lower * lower:
                    break
            if ring > limit:
                break
            for i in range(max(ci - ring, low_i), min(ci + ring, high_i) + 1):
                for j in range(max(cj - ring, low_j), min(cj + ring, high_j) + 1):
                    for k in range(max(ck - ring, low_k), min(ck + ring, high_k) + 1):
                        if ring > 0 and abs(i - ci) != ring and abs(j - cj) != ring and abs(k - ck) != ring:
                            continue
                        bucket = self.buckets.get((i, j, k))
                        if not bucket:
                            continue
                        for offset in bucket:
                            value = self._triangle_distance_sq(offset, x, y, z)
                            if best is None or value < best:
                                best = value
            ring += 1
        return None if best is None else math.sqrt(best)

    def _extent_box(self):
        """The occupied cells' bounding box, measured once."""
        if not hasattr(self, "_extent"):
            keys = list(self.buckets)
            self._extent = (
                min(key[0] for key in keys),
                min(key[1] for key in keys),
                min(key[2] for key in keys),
                max(key[0] for key in keys),
                max(key[1] for key in keys),
                max(key[2] for key in keys),
            )
        return self._extent

    def _ring_limit(self, ci, cj, ck):
        low_i, low_j, low_k, high_i, high_j, high_k = self._extent_box()
        return max(
            abs(ci - low_i), abs(ci - high_i),
            abs(cj - low_j), abs(cj - high_j),
            abs(ck - low_k), abs(ck - high_k),
        ) + 1


def _tessellate(body, max_side_mm, surface_tolerance_mm, record):
    """The reconstruction's own boundary, as triangles, at a declared tolerance.

    Fusion answers no distance question this verdict can use. measureMinimumDistance
    against a *body* returns zero for every interior point -- which is exactly the
    invented-material case -- and against a *face* it measures the underlying
    untrimmed surface: on this Fusion, a point 3 mm inside the hole of an annular
    top face measures 0.0 mm to that face. Both were measured, not assumed. Against
    a MeshBody or a PolygonMesh it refuses outright.

    So the reconstruction is tessellated instead, at a surface tolerance derived
    from the invented-material threshold and recorded, and every distance below is
    computed against those triangles. The tessellation is an approximation of the
    exact B-Rep and is bounded by that tolerance; the achieved tolerance Fusion
    reports back is recorded beside the requested one so the reader knows what the
    numbers stand for.
    """
    manager = body.meshManager
    calculator = manager.createMeshCalculator()
    calculator.surfaceTolerance = surface_tolerance_mm / 10.0
    calculator.maxSideLength = max_side_mm / 10.0
    mesh = calculator.calculate()
    flat = getattr(mesh, "nodeCoordinatesAsDouble", None)
    if flat:
        vertices = [value * 10.0 for value in flat]
    else:
        vertices = []
        for node in mesh.nodeCoordinates:
            vertices.append(node.x * 10.0)
            vertices.append(node.y * 10.0)
            vertices.append(node.z * 10.0)
    triangles = [int(value) for value in mesh.nodeIndices]
    # TriangleMesh.surfaceTolerance raises InternalValidationError on this Fusion
    # rather than answering, so the achieved tolerance is recorded as unreported
    # rather than as the requested value. A cap we asked for is not a cap we saw
    # honoured, and writing the request into the "achieved" slot would say it was.
    achieved = None
    achieved_error = None
    try:
        reported = mesh.surfaceTolerance
    except Exception as error:
        achieved_error = str(error)
    else:
        achieved = None if reported is None else reported * 10.0
    record.update(
        {
            "api": "MeshManager.createMeshCalculator",
            "requested_surface_tolerance_mm": surface_tolerance_mm,
            "surface_tolerance_source": (
                "one tenth of the declared invented_material threshold: the tessellation "
                "must not contribute a tenth of the deviation it is used to measure"
            ),
            "achieved_surface_tolerance_mm": achieved,
            "achieved_surface_tolerance_error": achieved_error,
            "max_side_length_mm": max_side_mm,
            "max_side_length_source": "median triangle edge of the source mesh",
            "triangle_count": len(triangles) // 3,
            "node_count": len(vertices) // 3,
            "meaning": (
                "The reconstruction's boundary is measured through this tessellation, not "
                "through its exact surfaces. Every number in both directions carries the "
                "surface tolerance as its floor -- the achieved one where Fusion reports it, "
                "and otherwise the requested one, which is a cap asked for rather than a cap "
                "seen honoured."
            ),
        }
    )
    return vertices, triangles


def _largest_triangle(vertices, triangles):
    """The biggest non-degenerate tessellation facet, with its inradius.

    The straddle probe steps off this facet's centroid, and the inradius is how
    far it can step before a neighbouring facet becomes the nearer boundary. The
    step is chosen from that inradius by the caller rather than from the
    declared threshold: the probe proves which enum means *inside*, which is a
    question about sign and not about magnitude. Tying it to the threshold made
    verification impossible on exactly the captures this is for -- ``_tessellate``
    caps each side at the source's median edge, a triangle's inradius is at most
    about 0.289 of its longest side, so demanding twice the threshold refused
    every facet as soon as the declared threshold reached about 14.5% of the
    median edge, and every such run failed `sign-convention-unestablished`.
    """
    best = None
    for offset in range(0, len(triangles) - 2, 3):
        a = triangles[offset] * 3
        b = triangles[offset + 1] * 3
        c = triangles[offset + 2] * 3
        ux = vertices[b] - vertices[a]
        uy = vertices[b + 1] - vertices[a + 1]
        uz = vertices[b + 2] - vertices[a + 2]
        vx = vertices[c] - vertices[a]
        vy = vertices[c + 1] - vertices[a + 1]
        vz = vertices[c + 2] - vertices[a + 2]
        nx = uy * vz - uz * vy
        ny = uz * vx - ux * vz
        nz = ux * vy - uy * vx
        length = math.sqrt(nx * nx + ny * ny + nz * nz)
        if length <= 0.0:
            continue
        area = length / 2.0
        perimeter = 0.0
        for first, second in ((a, b), (b, c), (c, a)):
            dx = vertices[first] - vertices[second]
            dy = vertices[first + 1] - vertices[second + 1]
            dz = vertices[first + 2] - vertices[second + 2]
            perimeter += math.sqrt(dx * dx + dy * dy + dz * dz)
        if perimeter <= 0.0:
            continue
        inradius = 2.0 * area / perimeter
        if inradius <= 0.0:
            continue
        if best is None or area > best[0]:
            centroid = [
                (vertices[a] + vertices[b] + vertices[c]) / 3.0,
                (vertices[a + 1] + vertices[b + 1] + vertices[c + 1]) / 3.0,
                (vertices[a + 2] + vertices[b + 2] + vertices[c + 2]) / 3.0,
            ]
            best = (area, centroid, [nx / length, ny / length, nz / length], inradius)
    return best


def _verify_containment_convention(body, grid, vertices, triangles, epsilon_mm, enums):
    """Verify inside/outside end to end on this body before any verdict reads it.

    Nothing in the API documentation ties PointInsidePointContainment to the side
    of the surface a person means by "inside", and the whole asymmetric verdict --
    invented material a failure, omitted detail advisory -- turns on that mapping.
    An inverted convention would report invented material as omitted detail and
    pass. So it is measured, on the actual reconstruction, against two answers
    known by construction:

    * a point pushed a full bounding-box diagonal beyond the body's own bounding
      box is outside any solid, whatever the enum happens to be named;
    * a point stepped epsilon along a tessellation facet's normal and a point
      stepped epsilon against it straddle that facet, so one must read inside and
      the other outside -- and both must measure epsilon from the boundary by the
      same point-to-triangle code the verdict itself uses.

    Only when all of that reproduces does the verdict read a side.
    """
    inside_enum, outside_enum, on_enum = enums
    # One percent of the step, with an absolute floor a thousand times below any
    # geometric meaning: the identity being checked is exact for a planar facet,
    # so the tolerance is only guarding float noise, not admitting a wrong answer.
    evidence = {
        "epsilon_mm": epsilon_mm,
        "convention": CONTAINMENT_CONVENTION,
    }
    box = body.boundingBox
    low = box.minPoint
    high = box.maxPoint
    diagonal = math.sqrt(
        (high.x - low.x) ** 2 + (high.y - low.y) ** 2 + (high.z - low.z) ** 2
    )
    far = adsk.core.Point3D.create(
        high.x + diagonal + 1.0, high.y + diagonal + 1.0, high.z + diagonal + 1.0
    )
    evidence["far_point_mm"] = [far.x * 10.0, far.y * 10.0, far.z * 10.0]
    evidence["far_point_reads_outside"] = body.pointContainment(far) == outside_enum
    evidence["on_boundary_enum_present"] = on_enum is not None
    facet = _largest_triangle(vertices, triangles)
    if facet is None:
        evidence["rejected"] = (
            "The reconstruction's tessellation carries no facet with a positive inradius, so the "
            "probe has nothing to straddle."
        )
        return False, evidence
    _, centroid, normal, inradius = facet
    # Half the inradius, and never more than the declared threshold: far enough
    # inside the facet that no neighbour is the nearer boundary, and no further
    # out than the distance the verdict itself cares about. The probe is a
    # question about *sign*, so this is a facet-derived step rather than a
    # threshold-sized one -- see `_largest_triangle`.
    step_mm = min(epsilon_mm, inradius / 2.0)
    evidence["probe_step_mm"] = step_mm
    evidence["tolerance_mm"] = max(0.01 * step_mm, 1e-6)
    step = step_mm / 10.0
    forward = adsk.core.Point3D.create(
        centroid[0] / 10.0 + normal[0] * step,
        centroid[1] / 10.0 + normal[1] * step,
        centroid[2] / 10.0 + normal[2] * step,
    )
    backward = adsk.core.Point3D.create(
        centroid[0] / 10.0 - normal[0] * step,
        centroid[1] / 10.0 - normal[1] * step,
        centroid[2] / 10.0 - normal[2] * step,
    )
    forward_containment = body.pointContainment(forward)
    backward_containment = body.pointContainment(backward)
    probe = {
        "facet_centroid_mm": centroid,
        "facet_normal": normal,
        "facet_inradius_mm": inradius,
        "forward_reads_inside": forward_containment == inside_enum,
        "backward_reads_inside": backward_containment == inside_enum,
    }
    evidence["straddle_probe"] = probe
    if sorted([forward_containment, backward_containment]) != sorted([inside_enum, outside_enum]):
        probe["rejected"] = "the two offset points did not straddle the facet"
        return False, evidence
    if forward_containment == inside_enum:
        inside_point, outside_point = forward, backward
    else:
        inside_point, outside_point = backward, forward
    inside_distance = grid.nearest_mm(
        inside_point.x * 10.0, inside_point.y * 10.0, inside_point.z * 10.0
    )
    outside_distance = grid.nearest_mm(
        outside_point.x * 10.0, outside_point.y * 10.0, outside_point.z * 10.0
    )
    probe["inside_point_mm"] = [
        inside_point.x * 10.0, inside_point.y * 10.0, inside_point.z * 10.0
    ]
    probe["outside_point_mm"] = [
        outside_point.x * 10.0, outside_point.y * 10.0, outside_point.z * 10.0
    ]
    probe["inside_measured_mm"] = inside_distance
    probe["outside_measured_mm"] = outside_distance
    tolerance = evidence["tolerance_mm"]
    if inside_distance is None or outside_distance is None:
        probe["rejected"] = "the point-to-triangle measurement returned nothing"
        return False, evidence
    if (
        abs(inside_distance - step_mm) > tolerance
        or abs(outside_distance - step_mm) > tolerance
    ):
        probe["rejected"] = "a point stepped off the boundary did not measure that step back to it"
        return False, evidence
    if not evidence["far_point_reads_outside"]:
        probe["rejected"] = "a point far beyond the bounding box did not read outside"
        return False, evidence
    probe["accepted"] = True
    return True, evidence


def run(context):
    report_attempted = False
    try:
        app, design = _active_design()
        fusion_version = getattr(app, "version", None)
        target_document = _require_target_document(app)
        _pump_events(app, design, target_document)

        thresholds = DEVIATION_SPECS["thresholds_mm"]
        report = {
            "kind": "mesh-deviation",
            "ok": False,
            "project": PROJECT_NAME,
            "manifest_sha256": MANIFEST_SHA256,
            "fusion_version": fusion_version,
            "classification": DEVIATION_SPECS["classification"],
            "mesh_source": DEVIATION_SPECS["mesh_source"],
            "declared_thresholds_mm": thresholds,
            "threshold_rationale": DEVIATION_SPECS["rationale"],
            "measurement_apis": [
                "BRepBody.pointContainment",
                "MeshManager.createMeshCalculator (TriangleMeshCalculator)",
                "PolygonMesh.nodeCoordinates / triangleNodeIndices",
            ],
            "preview_apis": [],
            "failures": [],
            "verdict_note": VERDICT_NOTE,
        }

        source_component, source_error, source_occurrence = _target_component(
            design, DEVIATION_SPECS["source"]["component_path"]
        )
        recon_component, recon_error, recon_occurrence = _target_component(
            design, DEVIATION_SPECS["reconstruction"]["component_path"]
        )
        if source_component is None or recon_component is None:
            report["failures"] = ["body-not-found"]
            report["resolution_errors"] = {"source": source_error, "reconstruction": recon_error}
            report_attempted = True
            _emit(report)
            raise RuntimeError("Deviation verdict failed closed: body-not-found")

        source_body, _ = _named_body(source_component, DEVIATION_SPECS["source"]["body_name"])
        recon_body, recon_kind = _named_body(
            recon_component, DEVIATION_SPECS["reconstruction"]["body_name"]
        )
        if source_body is None or recon_body is None:
            report["failures"] = ["body-not-found"]
            report["resolution_errors"] = {
                "source": None if source_body is not None else "body-name-missing",
                "reconstruction": None if recon_body is not None else "body-name-missing",
            }
            report_attempted = True
            _emit(report)
            raise RuntimeError("Deviation verdict failed closed: body-not-found")

        # Both sides are read in their own body's local frame and the
        # containment query takes points in the reconstruction's. Nothing here
        # composes an occurrence transform or a mesh body's own transform, so a
        # non-identity one is named and refused rather than quietly measured
        # across two unrelated coordinate systems.
        frames = {
            "source_occurrence_transform": _non_identity_transform(source_occurrence, "transform2"),
            "source_body_transform": _non_identity_transform(source_body, "transform"),
            "reconstruction_occurrence_transform": _non_identity_transform(
                recon_occurrence, "transform2"
            ),
            "reconstruction_body_transform": _non_identity_transform(recon_body, "transform"),
        }
        if any(value is not None for value in frames.values()):
            report["failures"] = ["deviation-frames-differ"]
            report["frames"] = frames
            report["unsupported"] = (
                "One of the two bindings resolves through a transform this transaction does not "
                "compose: node coordinates, the reconstruction's tessellation and "
                "BRepBody.pointContainment are each read in their own body's local frame, so a "
                "non-identity occurrence or body transform would have them compared across "
                "unrelated coordinate systems -- two identical parts in different assembly "
                "positions reading as a perfect match. The matrices are recorded above. Bind both "
                "bodies in a frame where they are already coincident, or ground the occurrence."
            )
            report_attempted = True
            _emit(report)
            raise RuntimeError("Deviation verdict failed closed: deviation-frames-differ")

        # Every capability below is hard. A missing one that read as a default
        # would turn "we could not look" into "we looked and found nothing", and
        # the verdict this transaction emits is the one a person quotes.
        missing = []
        source_mesh = _polygon_mesh(source_body)
        if source_mesh is None:
            missing.append("MeshBody.mesh (source must be a MeshBody carrying a PolygonMesh)")
        else:
            if not (getattr(source_mesh, "nodeCoordinates", None) or []):
                missing.append("PolygonMesh.nodeCoordinates (source)")
            if not (getattr(source_mesh, "triangleNodeIndices", None) or []):
                missing.append("PolygonMesh.triangleNodeIndices (source)")
        if recon_kind != "bRepBodies":
            missing.append("reconstruction must be a BRepBody for BRepBody.pointContainment")
        elif getattr(recon_body, "pointContainment", None) is None:
            missing.append("BRepBody.pointContainment")
        containment_enum = getattr(adsk.fusion, "PointContainment", None)
        for name in (
            "PointOutsidePointContainment",
            "PointInsidePointContainment",
            "PointOnPointContainment",
        ):
            if getattr(containment_enum, name, None) is None:
                missing.append("adsk.fusion.PointContainment." + name)
        mesh_manager = getattr(recon_body, "meshManager", None)
        if recon_kind == "bRepBodies":
            if mesh_manager is None:
                missing.append("BRepBody.meshManager")
            elif getattr(mesh_manager, "createMeshCalculator", None) is None:
                missing.append("MeshManager.createMeshCalculator")
        if not fusion_version:
            missing.append("Application.version")
        if missing:
            report["failures"] = ["deviation-capability"]
            report["missing_capabilities"] = missing
            report["unsupported"] = (
                "This verdict is measured with released APIs: MeshManager.createMeshCalculator for "
                "the reconstruction's boundary at a declared surface tolerance, and "
                "BRepBody.pointContainment for the side. Mesh Section Sketch and Fit Curves are "
                "UI-only and cannot be scripted, and PolygonMesh.compareWith -- the preview "
                "comparison -- cannot grade a B-Rep reconstruction at all, because a BRepBody's mesh "
                "is a TriangleMesh and TriangleMesh has no compareWith. Fusion version "
                + str(fusion_version)
                + " as connected does not expose all of the required APIs, so no deviation verdict is "
                "available and none is invented."
            )
            report_attempted = True
            _emit(report)
            raise RuntimeError(
                "Deviation verdict unsupported on this Fusion: missing " + ", ".join(missing)
            )

        inside_enum = adsk.fusion.PointContainment.PointInsidePointContainment
        outside_enum = adsk.fusion.PointContainment.PointOutsidePointContainment
        on_enum = adsk.fusion.PointContainment.PointOnPointContainment
        invented_threshold = float(thresholds["invented_material"])
        omitted_threshold = float(thresholds["omitted_detail"])
        percentile_limit = int(thresholds["percentile_sample_limit"])

        source_nodes = list(getattr(source_mesh, "nodeCoordinates", None) or [])
        source_vertices, source_triangles = _mesh_triangles_mm(source_mesh)
        median_edge = _median_edge_mm(source_vertices, source_triangles)
        if not source_nodes or not source_triangles or not median_edge:
            report["failures"] = ["deviation-comparison-empty"]
            report["resolution_errors"] = {
                "source_node_count": len(source_nodes),
                "source_triangle_count": len(source_triangles) // 3,
                "source_median_edge_mm": median_edge,
            }
            report_attempted = True
            _emit(report)
            raise RuntimeError("Deviation verdict failed closed: deviation-comparison-empty")

        # The reconstruction's boundary, at the scan's own resolution: a rebuilt
        # surface sampled coarser than the scan could step over a feature the scan
        # was able to express, and that is the one way this verdict could report a
        # clean number over a bad rebuild.
        tessellation = {"target_step_mm": median_edge}
        try:
            recon_vertices, recon_triangles = _tessellate(
                recon_body, median_edge, invented_threshold / 10.0, tessellation
            )
        except Exception as error:
            report["failures"] = ["tessellation-failed"]
            report["surface_sampling"] = tessellation
            report["error"] = str(error)
            report_attempted = True
            _emit(report)
            raise
        report["surface_sampling"] = tessellation
        if not recon_triangles:
            report["failures"] = ["tessellation-failed"]
            report["error"] = (
                "The reconstruction tessellated to no triangles, so it has no boundary to measure "
                "against and nothing here is a zero."
            )
            report_attempted = True
            _emit(report)
            raise RuntimeError("Deviation verdict failed closed: tessellation-failed")

        recon_grid = _TriangleGrid(recon_vertices, recon_triangles, median_edge * 2.0)
        source_grid = _TriangleGrid(source_vertices, source_triangles, median_edge * 2.0)

        # The premise before the measurement. An unverified convention must never
        # produce a passing severity, so this runs first and gates the verdict.
        try:
            verified, convention_evidence = _verify_containment_convention(
                recon_body,
                recon_grid,
                recon_vertices,
                recon_triangles,
                invented_threshold,
                (inside_enum, outside_enum, on_enum),
            )
        except Exception as error:
            report["failures"] = ["sign-convention-unestablished"]
            report["error"] = str(error)
            report_attempted = True
            _emit(report)
            raise
        convention_evidence["sign_convention_verified"] = verified
        report["containment_convention"] = convention_evidence

        # Direction 1: every scanned vertex against the reconstruction's boundary,
        # signed by the native containment query. Every vertex, not a sample: the
        # comparison against a threshold is never strided.
        try:
            containment_values = [recon_body.pointContainment(node) for node in source_nodes]
        except Exception as error:
            report["failures"] = ["containment-query-failed"]
            report["error"] = str(error)
            report_attempted = True
            _emit(report)
            raise
        source_points = []
        boundary_distances = []
        for node in source_nodes:
            point = [node.x * 10.0, node.y * 10.0, node.z * 10.0]
            source_points.append(point)
            value = recon_grid.nearest_mm(point[0], point[1], point[2])
            boundary_distances.append(0.0 if value is None else value)
        inside_depths = [0.0] * len(source_nodes)
        outside_gaps = [0.0] * len(source_nodes)
        inside_count = 0
        outside_count = 0
        on_count = 0
        neither_count = 0
        for index in range(len(source_nodes)):
            containment = containment_values[index]
            if containment == inside_enum:
                inside_count += 1
                inside_depths[index] = boundary_distances[index]
            elif containment == outside_enum:
                outside_count += 1
                outside_gaps[index] = boundary_distances[index]
            elif containment == on_enum:
                on_count += 1
            else:
                neither_count += 1
        percentiles_1, sampled_1, stride_1 = _percentiles(boundary_distances, percentile_limit)
        report["source_to_reconstruction"] = {
            "question": SOURCE_TO_RECONSTRUCTION_QUESTION,
            "measured_by": (
                "point-to-triangle distance against the reconstruction's own tessellation, signed by "
                "BRepBody.pointContainment"
            ),
            "containment_query": "BRepBody.pointContainment",
            "containment_convention": CONTAINMENT_CONVENTION,
            "node_count": len(source_nodes),
            "max_abs_mm": max(boundary_distances),
            "max_inside_mm": max(inside_depths),
            "max_outside_mm": max(outside_gaps),
            "nodes_inside_reconstruction_solid": inside_count,
            "nodes_outside_reconstruction_solid": outside_count,
            "nodes_on_reconstruction_boundary": on_count,
            "nodes_containment_unknown": neither_count,
            "percentiles_mm": percentiles_1,
            "percentiles_sampled": sampled_1,
            "percentile_stride": stride_1,
        }

        # Direction 2: the rebuilt surface itself against the scanned triangles.
        # Its samples are the tessellation's own nodes, which is why the
        # tessellation was asked for a maximum side of the scan's median edge.
        sample_points = []
        sample_distances = []
        for offset in range(0, len(recon_vertices) - 2, 3):
            point = [recon_vertices[offset], recon_vertices[offset + 1], recon_vertices[offset + 2]]
            sample_points.append(point)
            value = source_grid.nearest_mm(point[0], point[1], point[2])
            sample_distances.append(0.0 if value is None else value)
        percentiles_2, sampled_2, stride_2 = _percentiles(sample_distances, percentile_limit)
        report["reconstruction_to_source"] = {
            "question": RECONSTRUCTION_TO_SOURCE_QUESTION,
            "measured_by": (
                "every node of the reconstruction's tessellation against the source mesh's own "
                "triangles, by point-to-triangle distance"
            ),
            "sample_count": len(sample_distances),
            "max_mm": max(sample_distances) if sample_distances else 0.0,
            "beyond_invented_material_threshold": sum(
                1 for value in sample_distances if value > invented_threshold
            ),
            "worst_points": _worst(sample_points, sample_distances, invented_threshold, 5),
            "percentiles_mm": percentiles_2,
            "percentiles_sampled": sampled_2,
            "percentile_stride": stride_2,
            "attribution": "not-established",
            "meaning": UNSIGNED_DIRECTION_MEANING,
        }

        # compareWith stays available as corroboration and is never preferred. For
        # a B-Rep reconstruction it is structurally unavailable, and the report
        # says so by name rather than leaving a reader to wonder.
        recon_polygon_mesh = _polygon_mesh(recon_body)
        source_can_compare = hasattr(source_mesh, "compareWith")
        if recon_polygon_mesh is None or not source_can_compare:
            report["corroboration"] = {
                "api": "PolygonMesh.compareWith",
                "available": False,
                # Two different causes reach this branch and they are not the
                # same news: one is structural and permanent, the other is this
                # Fusion. Blaming the reconstruction for a member the source
                # mesh does not expose would send a reader to the wrong place.
                "cause": (
                    "reconstruction-is-not-a-polygon-mesh"
                    if recon_polygon_mesh is None
                    else "source-polygon-mesh-has-no-comparewith"
                ),
                "reason": (
                    (
                        "compareWith is defined on PolygonMesh. A BRepBody exposes only "
                        "meshManager.displayMeshes.bestMesh, which is a TriangleMesh and carries "
                        "no compareWith, so the preview comparison cannot grade a B-Rep "
                        "reconstruction."
                    )
                    if recon_polygon_mesh is None
                    else (
                        "The source body's PolygonMesh does not expose compareWith on Fusion "
                        + str(fusion_version)
                        + ". compareWith is a preview API and this connected version does not "
                        "carry it, so the corroboration cannot run."
                    )
                )
                + " The verdict above does not depend on it.",
            }
        else:
            report["preview_apis"] = ["PolygonMesh.compareWith"]
            try:
                corroborating = [
                    abs(value) * 10.0 for value in source_mesh.compareWith(recon_polygon_mesh, None, None)
                ]
            except Exception as error:
                report["corroboration"] = {
                    "api": "PolygonMesh.compareWith",
                    "available": True,
                    "ran": False,
                    "error": str(error),
                }
            else:
                native_max = report["source_to_reconstruction"]["max_abs_mm"]
                preview_max = max(corroborating) if corroborating else None
                disagreement = (
                    preview_max is not None
                    and abs(preview_max - native_max) > max(invented_threshold, 0.01 * native_max)
                )
                report["corroboration"] = {
                    "api": "PolygonMesh.compareWith",
                    "available": True,
                    "ran": True,
                    "node_count": len(corroborating),
                    "max_abs_mm": preview_max,
                    "native_max_abs_mm": native_max,
                    "disagrees_with_native": disagreement,
                    "meaning": (
                        "Corroboration only. compareWith is a preview API with no documented sign "
                        "convention; where it disagrees with the native measurement the native "
                        "measurement stands and the disagreement is flagged, never resolved in "
                        "compareWith's favour."
                    ),
                }

        omitted_count = sum(1 for value in outside_gaps if value > omitted_threshold)
        omitted = {
            "severity": "advisory" if omitted_count else "pass",
            "threshold_mm": omitted_threshold,
            "count": omitted_count,
            "direction": "source_to_reconstruction",
            "worst_points": _worst(source_points, outside_gaps, omitted_threshold, 5),
            "meaning": OMITTED_MEANING,
        }

        if not verified:
            # The sign is what separates invented material from omitted detail,
            # and an unverified premise must never produce a passing severity.
            report["failures"] = ["sign-convention-unestablished"]
            report["verdict"] = {
                "invented_material": {
                    "severity": "not-established",
                    "threshold_mm": invented_threshold,
                    "direction": "source_to_reconstruction",
                    "sign_convention_verified": False,
                    "sign_probe": convention_evidence,
                    "meaning": "Probing BRepBody.pointContainment against points whose side is known "
                               "by construction did not reproduce the expected answers on this body, "
                               "so inside and outside are not established here and neither is whether "
                               "any material was invented. The absence of invented material is NOT "
                               "established by this run.",
                },
                # `outside_gaps` is populated only where pointContainment
                # answered `outside`, so on this path the classification behind
                # every one of these counts is the premise that was just
                # rejected. A green severity derived from a rejected premise is
                # the same defect as a passing invented-material verdict, one
                # field over.
                "omitted_detail": dict(
                    omitted,
                    severity="not-established",
                    meaning=(
                        "Not established: omitted detail is counted from the scanned vertices that "
                        "read OUTSIDE the reconstruction, and this run did not establish which "
                        "enum means outside. The count and the worst points are reported as the "
                        "measurement they are, and neither is a verdict."
                    ),
                ),
            }
            report_attempted = True
            _emit(report)
            raise RuntimeError("Deviation verdict failed closed: sign-convention-unestablished")

        invented_count = sum(1 for value in inside_depths if value > invented_threshold)
        # The signed direction reads scanned *vertices*, and a scan carries only
        # the ones it captured. Material invented between two of them leaves
        # each on the reconstruction's boundary, so `inside_depths` stays at
        # zero while the reconstruction's own nodes sit millimetres from any
        # scanned surface -- and that direction is measured here, recorded, and
        # was then read by nothing. It is unsigned, so it cannot establish
        # invented material; it can and does disprove the absence of it, which
        # is what a pass claims.
        unclassified = report["reconstruction_to_source"]["beyond_invented_material_threshold"]
        established = bool(invented_count) or not unclassified
        report["verdict"] = {
            "invented_material": {
                "severity": (
                    "failure" if invented_count else "pass" if established else "not-established"
                ),
                "threshold_mm": invented_threshold,
                "count": invented_count,
                "max_mm": max(inside_depths),
                "direction": "source_to_reconstruction",
                "worst_points": _worst(source_points, inside_depths, invented_threshold, 5),
                "sign_convention_verified": True,
                "sign_probe": convention_evidence,
                "unclassified_reconstruction_samples": unclassified,
                "meaning": INVENTED_MEANING if established else UNCLASSIFIED_MEANING,
            },
            "omitted_detail": omitted,
        }
        if invented_count:
            report["failures"] = ["invented-material"]
            report_attempted = True
            _emit(report)
            raise RuntimeError(
                "Deviation verdict failed: invented material at "
                + json.dumps(report["verdict"]["invented_material"]["worst_points"][:1])
            )
        if not established:
            report["failures"] = ["invented-material-unclassified"]
            report_attempted = True
            _emit(report)
            raise RuntimeError(
                "Deviation verdict failed closed: invented-material-unclassified, "
                "{0} reconstruction samples beyond {1:g} mm from any scanned surface while no "
                "scanned vertex lies inside the reconstruction".format(
                    unclassified, invented_threshold
                )
            )

        report["ok"] = True
        report_attempted = True
        _emit(report)
    except Exception as error:
        if not report_attempted:
            report_attempted = True
            _emit({
                "kind": "mesh-deviation",
                "ok": False,
                "project": PROJECT_NAME,
                "manifest_sha256": MANIFEST_SHA256,
                "error": str(error),
                "traceback": traceback.format_exc(),
            })
        raise
'''
    return _script_prelude(manifest) + transaction.replace(
        "__DEVIATION_SPECS__", _json_literal(specs)
    )
