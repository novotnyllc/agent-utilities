"""Region fitting, noise estimation and disproof gates, against known analytic answers.

Every fixture here is a synthetic mesh whose true primitives are known exactly,
so a fit can be checked against the answer rather than against itself. Noisy
variants use a seeded RNG, so a failure is reproducible.

Each generator returns ``(vertices, triangles, face_groups)`` -- the third being
one group id per triangle, exactly as Fusion's ``triangleFaceGroupTempIds``
delivers them, because the regions are no longer this module's to invent. The
ids follow the fixture's own analytic faces: six for a box, one for an open
tube. ``make_dump(*box_mesh())`` therefore builds the dump the real pipeline
would see, and a call that deliberately withholds the grouping passes
``face_groups=None`` to test the refusal.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import time
import unittest

from fusion_design.mesh_dump import pack_mesh_dump, parse_mesh_dump
from fusion_design import mesh_segmentation as seg
from fusion_design.mesh_fitting import fit_primitive, parameter_uncertainty


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


def _metadata(**overrides):
    base = {
        "vertex_units": "mm",
        "internal_to_vertex_unit_scale": 10.0,
        "source_units": "mm",
        "source_unit_source": "declared",
        "mesh_source_id": "MESH__fixture",
        "mesh_source_sha256": "b" * 64,
        "manifest_sha256": "c" * 64,
        "fusion_version": "2.0.0",
        "component_path": "root",
        "body_name": "Body1",
        "transform": [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0],
        "transform_source": "MeshBody.transform",
        "face_groups_source": "absent",
    }
    base.update(overrides)
    return base


def make_dump(vertices, triangles, face_groups=None, **metadata):
    flat_v = [c for p in vertices for c in p]
    flat_t = [i for t in triangles for i in t]
    meta = _metadata(**metadata)
    if face_groups is not None:
        meta["face_groups_source"] = "triangleFaceGroupTempIds"
    data = pack_mesh_dump(meta, flat_v, flat_t, list(face_groups) if face_groups else None)
    return parse_mesh_dump(data, hashlib.sha256(data).hexdigest())


def _grid_quad(points, triangles, a, b, c, d):
    triangles.append((a, b, c))
    triangles.append((a, c, d))


def box_mesh(size=20.0, divisions=6, noise=0.0, seed=1):
    """A closed, welded, outward-wound box. Six planes, exactly known."""
    rng = random.Random(seed)
    vertices: list[tuple[float, float, float]] = []
    index: dict[tuple[int, int, int], int] = {}

    def node(i, j, k):
        key = (i, j, k)
        if key not in index:
            index[key] = len(vertices)
            step = size / divisions
            vertices.append((i * step, j * step, k * step))
        return index[key]

    triangles: list[tuple[int, int, int]] = []
    groups: list[int] = []
    n = divisions
    for i in range(n):
        for j in range(n):
            # z = 0 (normal -z) and z = size (normal +z)
            _grid_quad(vertices, triangles, node(i, j, 0), node(i, j + 1, 0), node(i + 1, j + 1, 0), node(i + 1, j, 0))
            _grid_quad(vertices, triangles, node(i, j, n), node(i + 1, j, n), node(i + 1, j + 1, n), node(i, j + 1, n))
            # y = 0 and y = size
            _grid_quad(vertices, triangles, node(i, 0, j), node(i + 1, 0, j), node(i + 1, 0, j + 1), node(i, 0, j + 1))
            _grid_quad(vertices, triangles, node(i, n, j), node(i, n, j + 1), node(i + 1, n, j + 1), node(i + 1, n, j))
            # x = 0 and x = size
            _grid_quad(vertices, triangles, node(0, i, j), node(0, i, j + 1), node(0, i + 1, j + 1), node(0, i + 1, j))
            _grid_quad(vertices, triangles, node(n, i, j), node(n, i + 1, j), node(n, i + 1, j + 1), node(n, i, j + 1))
            # One group per planar face, in the order the quads were appended,
            # two triangles each. This is what Fusion's accurate grouping returns
            # for a box: six analytic faces, six groups.
            groups.extend([0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5])
    if noise > 0.0:
        vertices = [tuple(c + rng.gauss(0.0, noise) for c in p) for p in vertices]
    return vertices, triangles, groups


def cylinder_mesh(radius=8.0, height=30.0, sides=48, stacks=12, noise=0.0, seed=2):
    """An open cylindrical tube: one cylinder, exactly known."""
    rng = random.Random(seed)
    vertices = []
    for k in range(stacks + 1):
        z = height * k / stacks
        for i in range(sides):
            a = 2.0 * math.pi * i / sides
            vertices.append((radius * math.cos(a), radius * math.sin(a), z))
    triangles = []
    for k in range(stacks):
        for i in range(sides):
            a = k * sides + i
            b = k * sides + (i + 1) % sides
            c = (k + 1) * sides + (i + 1) % sides
            d = (k + 1) * sides + i
            triangles.append((a, b, c))
            triangles.append((a, c, d))
    if noise > 0.0:
        vertices = [tuple(c + rng.gauss(0.0, noise) for c in p) for p in vertices]
    return vertices, triangles, [0] * len(triangles)


def arc_patch_mesh(radius=8.0, height=30.0, sweep_deg=20.0, sides=12, stacks=10):
    """A narrow arc of cylindrical surface: a real cylinder, but no evidence of one."""
    vertices = []
    for k in range(stacks + 1):
        z = height * k / stacks
        for i in range(sides + 1):
            a = math.radians(sweep_deg) * i / sides
            vertices.append((radius * math.cos(a), radius * math.sin(a), z))
    triangles = []
    row = sides + 1
    for k in range(stacks):
        for i in range(sides):
            a = k * row + i
            b = k * row + i + 1
            c = (k + 1) * row + i + 1
            d = (k + 1) * row + i
            triangles.append((a, b, c))
            triangles.append((a, c, d))
    return vertices, triangles, [0] * len(triangles)


def shallow_cone_mesh(radius=8.0, height=30.0, taper=0.12, sides=48, stacks=12):
    """A cone shallow enough that fitting it as a cylinder gives a flattering RMS."""
    vertices = []
    for k in range(stacks + 1):
        z = height * k / stacks
        r = radius + taper * z
        for i in range(sides):
            a = 2.0 * math.pi * i / sides
            vertices.append((r * math.cos(a), r * math.sin(a), z))
    triangles = []
    for k in range(stacks):
        for i in range(sides):
            a = k * sides + i
            b = k * sides + (i + 1) % sides
            c = (k + 1) * sides + (i + 1) % sides
            d = (k + 1) * sides + i
            triangles.append((a, b, c))
            triangles.append((a, c, d))
    return vertices, triangles, [0] * len(triangles)


def torus_mesh(major=12.0, minor=3.0, major_steps=48, minor_steps=16, noise=0.0, seed=3):
    rng = random.Random(seed)
    vertices = []
    for i in range(major_steps):
        a = 2.0 * math.pi * i / major_steps
        for j in range(minor_steps):
            b = 2.0 * math.pi * j / minor_steps
            rho = major + minor * math.cos(b)
            vertices.append((rho * math.cos(a), rho * math.sin(a), minor * math.sin(b)))
    triangles = []
    for i in range(major_steps):
        for j in range(minor_steps):
            a = i * minor_steps + j
            b = i * minor_steps + (j + 1) % minor_steps
            c = ((i + 1) % major_steps) * minor_steps + (j + 1) % minor_steps
            d = ((i + 1) % major_steps) * minor_steps + j
            triangles.append((a, b, c))
            triangles.append((a, c, d))
    if noise > 0.0:
        vertices = [tuple(c + rng.gauss(0.0, noise) for c in p) for p in vertices]
    return vertices, triangles, [0] * len(triangles)


def rounded_plinth_mesh(
    width=20.0, depth=30.0, height=12.0, radius=4.0, nx=12, ny=8, nz=6, arc=10,
    post_radius=5.0, post_height=9.0, post_sides=36, post_stacks=6, post_inward=False,
    post_centre=None, back_radius=0.0,
):
    """A closed plinth whose top-front edge is rounded, under a coaxial post.

    Built for the fillet seam, and every part of it earns its place:

    * the **round** is a partial-arc cylinder -- the shape a face-grouped mesh
      actually delivers an edge round as -- and it is cut into *three* groups
      along its length, the way Fusion's grouping cuts a real one. Only the
      middle fragment touches exactly two faces; the outer two also touch a side
      plane, so they are chains against three primaries and the producer refuses
      them. That discipline is reproduced here rather than asserted.
    * the round's axis runs along **x** while the plinth is deeper than it is
      wide, so the extrude's caps are the front and back faces and the round is
      not one of the extrude's sides. A round claimed as a side is already
      rebuilt by the section profile and must not also be filleted.
    * the **post** is what licenses a revolve, which is what puts the top face in
      a *different* archetype from the front face -- and a fillet needs an edge
      between two archetypes.

    ``post_inward`` sinks the post into the body as a blind bore instead. Nothing
    else about the shape changes and the round is still the same round, but the
    part stops being a revolve: a bore is not an outward turned surface, so the
    top face joins the *extrude* that already owns the front face, and the round
    then sits between two faces of one feature -- a side and a cap. That is the
    same-feature edge, on a real mesh rather than a fixture of one.

    ``back_radius`` rounds the *back*-top edge as well, to a different radius.
    Both rounds then lie between the same two face sets of the same extrude --
    the top cap and a side wall -- which is the shape a lid arrives as: POD-A1-LID
    carries twenty-four rounds on that one pair of face sets at four radii, and
    what has to come out is one fillet per edge carrying that edge's own radius.

    Closed and outward-wound, because the rebuild sections the dump for its
    profiles and an open surface has no section to give.
    """
    post_sign = -1.0 if post_inward else 1.0
    # The post sits on the top face's centre unless the caller moves it. Moving
    # it is what turns this plinth into the acceptance run's plate: the top face
    # stops being an annulus about the post's axis and becomes a rectangle that
    # merely happens to be perpendicular to it.
    post_x, post_y = post_centre or (width / 2.0, (radius + depth) / 2.0)
    vertices: list[tuple[float, float, float]] = []
    index: dict[tuple, int] = {}

    def node(key, point):
        if key not in index:
            index[key] = len(vertices)
            vertices.append(point)
        return index[key]

    triangles: list[tuple[int, int, int]] = []
    groups: list[int] = []

    def quad(a, b, c, d, group):
        triangles.append((a, b, c))
        groups.append(group)
        triangles.append((a, c, d))
        groups.append(group)

    def span(lo, hi, steps, i):
        return lo + (hi - lo) * i / steps

    def round_point(a, r=None):
        # The endpoints are written exactly rather than evaluated: cos(pi/2) is
        # 6e-17 and not 0, and the 4e-16 gap that follows is enough to cost the
        # round its adjacency to the top face, which is the whole point here.
        r = radius if r is None else r
        if a == 0:
            return 0.0, height - r
        if a == arc:
            return r, height
        angle = math.pi / 2 * a / arc
        return r * (1.0 - math.cos(angle)), height - r * (1.0 - math.sin(angle))

    def bottom(i, j):
        return node(("b", i, j), (span(0.0, width, nx, i), span(0.0, depth, ny, j), 0.0))

    def top(i, j):
        return node(
            ("t", i, j),
            (span(0.0, width, nx, i), span(radius, depth - back_radius, ny, j), height),
        )

    def front(i, k):
        return node(("f", i, k), (span(0.0, width, nx, i), 0.0, span(0.0, height - radius, nz, k)))

    def back(i, k):
        return node(
            ("k", i, k),
            (span(0.0, width, nx, i), depth, span(0.0, height - back_radius, nz, k)),
        )

    def blend(i, a):
        y, z = round_point(a)
        return node(("r", i, a), (span(0.0, width, nx, i), y, z))

    def back_blend(i, a):
        y, z = round_point(a, back_radius)
        return node(("q", i, a), (span(0.0, width, nx, i), depth - y, z))

    def rim(level, s):
        angle = 2.0 * math.pi * (s % post_sides) / post_sides
        return node(
            ("p", level, s % post_sides),
            (
                post_x + post_radius * math.cos(angle),
                post_y + post_radius * math.sin(angle),
                height + post_sign * post_height * level / post_stacks,
            ),
        )

    for i in range(nx):
        for j in range(ny):
            quad(bottom(i, j), bottom(i, j + 1), bottom(i + 1, j + 1), bottom(i + 1, j), 0)
    for i in range(nx):
        for k in range(nz):
            quad(front(i, k), front(i + 1, k), front(i + 1, k + 1), front(i, k + 1), 2)
            quad(back(i, k), back(i, k + 1), back(i + 1, k + 1), back(i + 1, k), 3)
        for a in range(arc):
            band = min(2, i // (nx // 3))
            quad(blend(i, a), blend(i + 1, a), blend(i + 1, a + 1), blend(i, a + 1), 6 + band)
            if back_radius > 0.0:
                quad(
                    back_blend(i, a),
                    back_blend(i, a + 1),
                    back_blend(i + 1, a + 1),
                    back_blend(i + 1, a),
                    11 + band,
                )

    # The two side faces, fanned from an interior hub over a boundary ring that
    # reuses its neighbours' own nodes -- so every edge of the ring is an edge
    # some other face already owns, and the adjacency the fillet is read from is
    # real rather than nearly real.
    for column, group in ((0, 4), (nx, 5)):
        ring = (
            [bottom(column, j) for j in range(ny)]
            + [back(column, k) for k in range(nz)]
            + ([back_blend(column, a) for a in range(arc)] if back_radius > 0.0 else [])
            + [top(column, ny - j) for j in range(ny)]
            + [blend(column, arc - a) for a in range(arc)]
            + [front(column, nz - k) for k in range(nz)]
        )
        hub = node(("c", column), (span(0.0, width, nx, column), depth / 2.0, height / 2.0))
        for m, first in enumerate(ring):
            second = ring[(m + 1) % len(ring)]
            triangles.append((hub, second, first) if column else (hub, first, second))
            groups.append(group)

    # The top face is a rectangle with the post's footprint cut out of it: two
    # closed loops, stitched by walking both in step.
    outer = (
        [top(i, 0) for i in range(nx)]
        + [top(nx, j) for j in range(ny)]
        + [top(nx - i, ny) for i in range(nx)]
        + [top(0, ny - j) for j in range(ny)]
    )
    # Both loops run counter-clockwise seen from +z, and the inner one starts at
    # the rim point nearest the outer one's start. Without that alignment the
    # walk below is monotone in each loop's own parameter but not in angle, and
    # it stitches triangles straight across the hole.
    start = math.atan2(radius - post_y, -post_x)
    offset = round(start / (2.0 * math.pi) * post_sides)
    inner = [rim(0, offset + s) for s in range(post_sides)]
    i = j = 0
    while i < len(outer) or j < len(inner):
        if j >= len(inner) or (
            i < len(outer) and (i + 1) / len(outer) <= (j + 1) / len(inner)
        ):
            triangles.append((outer[i], outer[(i + 1) % len(outer)], inner[j % len(inner)]))
            i += 1
        else:
            triangles.append((outer[i % len(outer)], inner[(j + 1) % len(inner)], inner[j % len(inner)]))
            j += 1
        groups.append(1)

    # One winding serves both cases, and that is not an oversight: sinking the
    # post mirrors it in z, and mirroring a surface reverses the normal its
    # unchanged winding implies. A boss's wall faces away from its axis and a
    # bore's faces toward it, so the same triangles describe both -- which is
    # what lets the fit read the sunk one's material_side as `inside`.
    for k in range(post_stacks):
        for s in range(post_sides):
            quad(rim(k, s), rim(k, s + 1), rim(k + 1, s + 1), rim(k + 1, s), 9)
    cap = node(("pc",), (post_x, post_y, height + post_sign * post_height))
    for s in range(post_sides):
        triangles.append((cap, rim(post_stacks, s), rim(post_stacks, s + 1)))
        groups.append(10)
    return vertices, triangles, groups


def unweld(vertices, triangles, groups=None, jitter=1e-7, seed=9):
    """Explode a welded mesh: every triangle gets its own three nodes.

    The jitter is what makes this a *scanner's* unwelded mesh rather than an
    exporter's: exact duplicates weld at tolerance zero, near-duplicates do not,
    and it is the near-duplicate case that silently destroys adjacency.
    """
    rng = random.Random(seed)
    out_v = []
    out_t = []
    for a, b, c in triangles:
        base = len(out_v)
        for source in (a, b, c):
            out_v.append(tuple(k + rng.uniform(-jitter, jitter) for k in vertices[source]))
        out_t.append((base, base + 1, base + 2))
    return out_v, out_t, list(groups) if groups is not None else [0] * len(out_t)


# --------------------------------------------------------------------------
# the reference spec
# --------------------------------------------------------------------------

_SHA256 = re.compile(r"[0-9a-f]{64}")

REFERENCE = {
    "max_triangles": (200000, "the density above which extra triangles are noise samples, not information"),
    "weld_tolerance": (0.0, "this fixture is exported from a solid modeller, so exact duplicates are the only duplicates"),
    "min_feature_size": (1.0, "the smallest fillet and bore this part family carries is one millimetre"),
    "normal_alpha_deg": (25.0, "loose on purpose: the normal check separates surfaces, it does not re-segment"),
    "curvature_dead_zone_sigmas": (2.0, "two estimator sigmas of curvature is indistinguishable from flat"),
    "cylinder_normal_perpendicular_deg": (5.0, "every one of the 367 measured two-ring bores held its facet normals inside five degrees of perpendicular, and no sphere's do"),
    "regime": ("auto", "let the mesh's own dihedral distribution and measured sigma decide, and report which"),
    "vertex_precision_rel": (1.2e-07, "a binary STL stores float32, so a vertex is quantized to about a ten-millionth of its own magnitude"),
    "tessellation_sigma_over_extent": (1e-9, "an exporter's vertices sit on the analytic surface to float precision; a scan's never do"),
    "min_normal_axis_eigengap": (0.05, "a twentieth of the normal spectrum away from the axis is a full ring of facets, not a sliver"),
    "normal_sigma_theta_floor_deg": (1e-06, "double precision over a millimetre-scale part leaves about a microdegree of normal direction"),
    "min_cylinder_normal_directions_per_turn": (8.0, "a tessellated circle carries one normal direction per facet; at eight per turn a facet already spans 45 degrees, coarser than any exporter's chord tolerance, so below it the group is a prism of walls -- measured, the 230 genuine cylinders in the 11-part corpus carry 29.6 per turn or more and the hexagonal pockets carry 7.2"),
    "max_fillet_radius_rel_spread": (0.02, "a constant-radius round is constant; two percent is the tessellation's own radius wobble"),
    "boundary_circle_sigmas": (3.0, "three joint sigmas before an independent boundary circle counts as disagreeing"),
    "max_fillet_arc_deg": (180.0, "a bore or a boss closes on itself; an edge round never sweeps past a half turn"),
    "max_relative_residual": (0.02, "two percent of the sampled extent is the residual gate this skill already uses"),
    "max_radius_ratio": (5.0, "a radius beyond five extents is the near-flat-strip pathology"),
    "bounds_margin_ratio": (1.0, "an anchor one extent outside the part is not describing the part"),
    "min_taper_ratio": (0.01, "below one percent taper a cone is a cylinder and should be reported as one"),
    "min_torus_major_ratio": (1.2, "a major radius under 1.2 tubes is a spindle, not a fillet"),
    "min_angular_span_deg": (60.0, "below sixty degrees of arc the radius is not determined by the data"),
    "min_axial_span_ratio": (0.5, "half a radius of length before an axis direction means anything"),
    "min_sphere_occupancy": (0.5, "half a sphere's diameter of extent before it is a sphere"),
    "min_plane_aspect": (0.05, "a footprint narrower than one in twenty does not fix a normal about its long axis"),
    "max_radius_rel_sigma": (0.02, "a radius uncertain by more than two percent cannot drive a dimension"),
    "max_axis_sigma_deg": (2.0, "an axis uncertain by more than two degrees makes coaxiality unlicensable"),
    "moran_z_max": (6.0, "scanner noise is itself mildly correlated, so the iid null is conservative-false"),
    "moran_baseline_slack": (4.0, "how far above the part's own best plane another feature may sit"),
    "directional_bin_sigmas": (4.0, "four standard errors over two adjacent bins is structure, not luck"),
    "heldout_ratio_max": (1.5, "far outside the concentration of a correct model, immediate for an overfit one"),
    "parsimony_alpha": (0.01, "a richer primitive must clear one percent to earn its extra parameters"),
    "min_covered_area_fraction": (0.0, "this fixture measures detection, so coverage is reported not gated"),
}


def spec(**overrides):
    raw = {name: {"value": value, "rationale": why} for name, (value, why) in REFERENCE.items()}
    for name, value in overrides.items():
        raw[name] = {"value": value, "rationale": REFERENCE[name][1]}
    return seg.load_spec(raw)


def kinds_of(record):
    return sorted(r["fit"]["kind"] for r in record["regions"] if r["accepted"])


# --------------------------------------------------------------------------
# spec validation
# --------------------------------------------------------------------------


class SpecTests(unittest.TestCase):
    def test_every_threshold_needs_a_rationale(self) -> None:
        raw = {name: {"value": value, "rationale": why} for name, (value, why) in REFERENCE.items()}
        raw["moran_z_max"] = {"value": 6.0, "rationale": "   "}
        with self.assertRaises(seg.SegmentationSpecError) as caught:
            seg.load_spec(raw)
        codes = {issue.code for issue in caught.exception.issues}
        self.assertIn("detection-threshold-rationale-required", codes)

    def test_a_bare_number_is_not_a_declared_threshold(self) -> None:
        raw = {name: {"value": value, "rationale": why} for name, (value, why) in REFERENCE.items()}
        raw["normal_alpha_deg"] = 25.0
        with self.assertRaises(seg.SegmentationSpecError) as caught:
            seg.load_spec(raw)
        self.assertIn(
            "detection-threshold-must-be-object", {i.code for i in caught.exception.issues}
        )

    def test_a_missing_threshold_is_named_not_defaulted(self) -> None:
        raw = {name: {"value": value, "rationale": why} for name, (value, why) in REFERENCE.items()}
        del raw["min_feature_size"]
        with self.assertRaises(seg.SegmentationSpecError) as caught:
            seg.load_spec(raw)
        self.assertIn("spec.min_feature_size", {i.path for i in caught.exception.issues})

    def test_unknown_thresholds_are_rejected(self) -> None:
        raw = {name: {"value": value, "rationale": why} for name, (value, why) in REFERENCE.items()}
        raw["crease_threshold_deg"] = {"value": 15.0, "rationale": "the old design's threshold"}
        with self.assertRaises(seg.SegmentationSpecError) as caught:
            seg.load_spec(raw)
        self.assertIn("unknown-manifest-field", {i.code for i in caught.exception.issues})

    def test_out_of_range_values_are_rejected_per_threshold(self) -> None:
        for name, bad in (
            ("normal_alpha_deg", 120.0),
            ("cylinder_normal_perpendicular_deg", 90.0),
            ("min_torus_major_ratio", 1.0),
            ("heldout_ratio_max", 0.5),
        ):
            raw = {n: {"value": v, "rationale": w} for n, (v, w) in REFERENCE.items()}
            raw[name] = {"value": bad, "rationale": REFERENCE[name][1]}
            with self.assertRaises(seg.SegmentationSpecError, msg=name):
                seg.load_spec(raw)

    def test_the_thresholds_and_their_rationales_round_trip_into_the_record(self) -> None:
        declared = spec()
        payload = declared.to_dict()
        self.assertEqual(set(payload), set(seg.THRESHOLDS))
        for name, entry in payload.items():
            self.assertTrue(entry["rationale"].strip(), name)


# --------------------------------------------------------------------------
# welding
# --------------------------------------------------------------------------


class WeldTests(unittest.TestCase):
    def test_an_unwelded_mesh_refuses_rather_than_estimating_from_no_adjacency(self) -> None:
        vertices, triangles, groups = box_mesh()
        dump = make_dump(*unweld(vertices, triangles))
        record = seg.fit_regions(dump, spec())
        self.assertEqual("mesh-not-welded", record["refusal"]["reason"])
        self.assertEqual([], record["regions"])
        self.assertIn("weld_tolerance", record["refusal"]["alternative"])
        # And the stages after welding never claim to have run.
        self.assertEqual(["triangle-budget"], record["checked"])

    def test_welding_with_a_declared_tolerance_recovers_the_unwelded_mesh(self) -> None:
        vertices, triangles, groups = box_mesh()
        dump = make_dump(*unweld(vertices, triangles))
        record = seg.fit_regions(dump, spec(weld_tolerance=1e-5))
        self.assertIsNone(record["refusal"])
        self.assertGreater(record["weld"]["nodes_merged"], 0)
        self.assertEqual(len(vertices), record["weld"]["node_count_after"])

    def test_weld_reports_how_many_nodes_merged_and_how_many_triangles_collapsed(self) -> None:
        vertices, triangles, groups = box_mesh(divisions=2)
        dump = make_dump(*unweld(vertices, triangles))
        welded = seg.weld_dump(dump, 1e-5)
        self.assertEqual(dump.vertex_count, welded.weld["node_count_before"])
        self.assertEqual(len(vertices), welded.weld["node_count_after"])
        self.assertEqual(0, welded.weld["triangles_collapsed"])

    def test_a_tolerance_that_swallows_the_part_collapses_it_and_refuses(self) -> None:
        vertices, triangles, groups = box_mesh(divisions=2)
        dump = make_dump(vertices, triangles, face_groups=groups)
        record = seg.fit_regions(dump, spec(weld_tolerance=1000.0))
        self.assertEqual("mesh-degenerate", record["refusal"]["reason"])


# --------------------------------------------------------------------------
# noise estimation and the feature-scale refusal
# --------------------------------------------------------------------------


class NoiseTests(unittest.TestCase):
    def test_a_clean_mesh_measures_noise_down_to_its_own_storage_precision(self) -> None:
        """Both estimators read zero, and sigma still stops at the declared floor.

        No estimator can see below the precision the coordinates are *stored* at,
        and a sigma of zero would divide every downstream standard error by
        nothing -- which is how a float32 STL's quantization comes to read as
        systematic residual structure. The record says which of the two it is
        reporting.
        """
        dump = make_dump(*box_mesh())
        record = seg.fit_regions(dump, spec())
        noise = record["noise"]
        self.assertEqual(0.0, noise["sigma_quadric"])
        self.assertEqual(0.0, noise["sigma_dihedral"])
        self.assertTrue(noise["precision_floor_binds"])
        self.assertEqual(noise["vertex_precision_floor"], noise["sigma"])
        self.assertAlmostEqual(1.2e-07, noise["sigma_over_extent"])

    def test_a_declared_precision_floor_of_zero_is_still_honoured_as_declared(self) -> None:
        record = seg.fit_regions(make_dump(*box_mesh()), spec(vertex_precision_rel=1e-15))
        self.assertLess(record["noise"]["sigma"], 1e-9)

    def test_the_declared_precision_is_bounded_above_because_it_floors_sigma(self) -> None:
        """A declaration only bounded below can silence every gate above it.

        At 1e-04 a 100 mm part carries a 0.01 mm noise floor -- a printed
        feature's layer height -- and the residual-structure gates spend their
        power on the declaration instead of the mesh.
        """
        self.assertEqual(1e-04, spec(vertex_precision_rel=1e-04).value("vertex_precision_rel"))
        with self.assertRaises(seg.SegmentationSpecError):
            spec(vertex_precision_rel=1.1e-04)

    def test_the_storage_precision_is_measured_and_not_only_declared(self) -> None:
        """`vertex_precision_rel` is a claim about the file, and the file can answer it.

        A coordinate that arrived through float32 survives a float32 round trip
        exactly. These fixtures are float64 by construction, so the honest answer
        is that they carry more precision than the declaration assumes -- which
        is reported, not enforced: a conservative floor is not a malformed record.
        """
        measured = seg.fit_regions(make_dump(*box_mesh()), spec())["noise"]["vertex_precision"]
        self.assertFalse(measured["reads_as_float32"])
        self.assertGreater(measured["max_float32_round_trip"], 0.0)
        self.assertEqual(1.2e-07, measured["declared_precision_rel"])
        # And a mesh whose coordinates really did come through float32 says so,
        # and reports the format's own relative precision rather than a residual.
        import struct

        vertices, triangles, groups = box_mesh()
        quantized = [
            tuple(struct.unpack("<f", struct.pack("<f", value))[0] for value in vertex)
            for vertex in vertices
        ]
        f32 = seg.fit_regions(make_dump(quantized, triangles, face_groups=groups), spec())
        self.assertTrue(f32["noise"]["vertex_precision"]["reads_as_float32"])
        self.assertEqual(0.0, f32["noise"]["vertex_precision"]["max_float32_round_trip"])
        self.assertAlmostEqual(
            1.1920929e-07, f32["noise"]["vertex_precision"]["measured_precision_rel"], places=12
        )

    def test_surface_scale_says_what_it_is_a_scale_of(self) -> None:
        """On a tessellation it is the facet turn angle, which is the part's geometry.

        The honeycomb's cell walls meet at 60 degrees, and the dihedral estimator
        read 13.108 mm of "discretization" on a 249 mm part from exactly that.
        The number is the right power floor either way -- nothing to test below
        the scale at which the surface turns -- so what changed is that the
        record says which it is instead of leaving it to be read as noise.
        """
        exact = seg.fit_regions(make_dump(*box_mesh()), spec())["noise"]
        self.assertEqual("tessellation", exact["regime"])
        self.assertEqual("facet-turn-angle", exact["surface_scale_basis"])
        scanned = seg.fit_regions(
            make_dump(*box_mesh(size=20.0, divisions=14, noise=0.05)), spec(min_feature_size=5.0)
        )["noise"]
        self.assertEqual("scan", scanned["regime"])
        self.assertEqual("measurement-noise", scanned["surface_scale_basis"])

    def test_noise_estimators_recover_the_injected_sigma_on_flat_surface(self) -> None:
        """Calibration, checked where curvature cannot contaminate it.

        Both estimators carry a *geometric* bias on a curved surface: a plane
        fitted across a coarse cylinder picks up the chordal sagitta, and the
        median dihedral picks up the facet turn angle. Neither is a defect --
        that bias is exactly the allowance a consensus band needs on a coarse
        mesh -- but it means the calibration has to be checked on a flat fixture,
        where the true answer is the injected noise and nothing else.
        """
        for injected in (0.02, 0.05, 0.1):
            dump = make_dump(*box_mesh(size=20.0, divisions=14, noise=injected))
            record = seg.fit_regions(dump, spec(min_feature_size=5.0))
            measured = record["noise"]["sigma"]
            self.assertGreater(measured, injected / 2.0, injected)
            self.assertLess(measured, injected * 2.0, injected)

    def test_the_measured_scale_on_a_coarse_curved_mesh_is_reported_as_such(self) -> None:
        """A coarse cylinder measures its own chordal error, and that is correct.

        The band has to cover discretization as well as noise, or no facet of a
        coarsely tessellated cylinder is ever an inlier of the cylinder it came
        from. The record therefore reports sigma against the median edge length,
        so a reader can see which of the two they are looking at.
        """
        dump = make_dump(*cylinder_mesh(radius=8.0, sides=32, stacks=10, noise=0.0))
        record = seg.fit_regions(dump, spec(min_feature_size=5.0))
        self.assertGreater(record["noise"]["sigma"], 0.0)
        self.assertIn("sigma_over_median_edge", record["noise"])

    def test_the_dihedral_median_is_reported_but_never_gated_on(self) -> None:
        dump = make_dump(*cylinder_mesh(noise=0.05))
        record = seg.fit_regions(dump, spec(min_feature_size=5.0))
        self.assertIsNotNone(record["noise"]["median_abs_dihedral_deg"])
        self.assertNotIn("crease", json.dumps(record["thresholds"]))

    def test_disagreeing_estimators_flag_rather_than_refuse(self) -> None:
        # A mesh smoothed in one direction only: the local-plane estimator and
        # the dihedral estimator see different things.
        vertices, triangles, groups = cylinder_mesh(noise=0.0, sides=64, stacks=20)
        rng = random.Random(11)
        vertices = [(x, y, z + rng.gauss(0.0, 0.05)) for (x, y, z) in vertices]
        dump = make_dump(vertices, triangles, face_groups=groups)
        record = seg.fit_regions(dump, spec(min_feature_size=5.0))
        self.assertIsNone(record["refusal"])
        self.assertIsInstance(record["noise"]["estimators_consistent"], bool)

    def test_refusal_is_about_feature_scale_not_about_the_estimator(self) -> None:
        dump = make_dump(*cylinder_mesh(noise=0.5, sides=48, stacks=16))
        record = seg.fit_regions(dump, spec(min_feature_size=0.5))
        self.assertEqual("feature-scale-below-noise", record["refusal"]["reason"])
        detail = record["refusal"]["detail"]
        self.assertGreater(detail["recoverable_feature_size"], detail["min_feature_size"])
        # The same mesh with an honestly declared feature size proceeds.
        allowed = seg.fit_regions(dump, spec(min_feature_size=50.0))
        self.assertIsNone(allowed["refusal"])

    def test_the_feature_budget_is_reported_whether_or_not_it_refuses(self) -> None:
        dump = make_dump(*cylinder_mesh(noise=0.05))
        record = seg.fit_regions(dump, spec(min_feature_size=5.0))
        self.assertIn("recoverable_feature_size", record["feature_scale"])
        self.assertGreater(record["feature_scale"]["margin"], 1.0)


class NormalTests(unittest.TestCase):
    def test_neighbourhood_normals_beat_per_triangle_jitter_by_an_order_of_magnitude(self) -> None:
        """The whole argument against the old refusal, measured.

        Per-triangle jitter is ~2.3 sigma/l radians; trimmed PCA over a radius h
        drops it to ~2 sigma/(h sqrt(k)). This asserts the achieved number is a
        large factor better than the per-triangle one on the contested case.
        """
        dump = make_dump(*cylinder_mesh(radius=8.0, height=30.0, sides=100, stacks=60, noise=0.05))
        record = seg.fit_regions(dump, spec(min_feature_size=5.0))
        edge = record["topology"]["median_edge_length"]
        per_triangle = math.degrees(2.3 * record["noise"]["sigma"] / edge)
        achieved = record["normals"]["sigma_theta_deg"]
        self.assertLess(achieved * 4.0, per_triangle)

    def test_the_neighbourhood_radius_is_clamped_by_the_declared_feature_size(self) -> None:
        dump = make_dump(*cylinder_mesh(noise=0.05, sides=64, stacks=24))
        record = seg.fit_regions(dump, spec(min_feature_size=2.0))
        normals = record["normals"]
        self.assertLessEqual(normals["neighbourhood_radius"], 1.0 + 1e-9)
        self.assertTrue(normals["clamped_by_feature_size"])
        self.assertIn("angular-resolution-degraded", record["flags"])
        # Degradation is stated in numbers and paid for by widening the check,
        # not by refusing the run.
        self.assertGreaterEqual(normals["normal_alpha_deg_used"], 25.0)
        self.assertGreater(normals["sigma_theta_deg"], 0.0)


# --------------------------------------------------------------------------
# detection
# --------------------------------------------------------------------------


class DetectionTests(unittest.TestCase):
    def test_a_box_yields_planes_and_nothing_curved(self) -> None:
        dump = make_dump(*box_mesh())
        record = seg.fit_regions(dump, spec())
        self.assertIsNone(record["refusal"])
        self.assertTrue(record["regions"])
        self.assertEqual({"plane"}, set(kinds_of(record)))

    def test_a_box_recovers_axis_aligned_normals_exactly(self) -> None:
        dump = make_dump(*box_mesh())
        record = seg.fit_regions(dump, spec())
        for region in record["regions"]:
            if not region["accepted"]:
                continue
            normal = region["fit"]["parameters"]["normal"]
            self.assertAlmostEqual(1.0, max(abs(c) for c in normal), places=12)
            self.assertAlmostEqual(0.0, sorted(abs(c) for c in normal)[1], places=12)

    def test_a_cylinder_is_detected_with_its_analytic_radius_and_axis(self) -> None:
        dump = make_dump(*cylinder_mesh(radius=8.0, height=30.0, sides=64, stacks=20))
        record = seg.fit_regions(dump, spec())
        cylinders = [r for r in record["regions"] if r["accepted"] and r["fit"]["kind"] == "cylinder"]
        self.assertTrue(cylinders, kinds_of(record))
        parameters = cylinders[0]["fit"]["parameters"]
        # The mesh inscribes the true cylinder, so the fitted radius sits between
        # the inscribed and circumscribed radii of a 64-gon.
        self.assertGreater(parameters["radius"], 8.0 * math.cos(math.pi / 64) - 1e-6)
        self.assertLess(parameters["radius"], 8.0 + 1e-6)
        self.assertAlmostEqual(1.0, abs(parameters["axis_direction"][2]), places=9)

    def test_a_noisy_cylinder_is_still_detected_at_the_contested_noise_level(self) -> None:
        dump = make_dump(*cylinder_mesh(radius=8.0, height=30.0, sides=64, stacks=24, noise=0.05))
        record = seg.fit_regions(dump, spec(min_feature_size=5.0))
        cylinders = [r for r in record["regions"] if r["accepted"] and r["fit"]["kind"] == "cylinder"]
        self.assertTrue(cylinders, record["refusal"] or kinds_of(record))
        self.assertAlmostEqual(8.0, cylinders[0]["fit"]["parameters"]["radius"], delta=0.1)

    def test_the_same_dump_gives_a_bit_identical_record(self) -> None:
        dump = make_dump(*cylinder_mesh(noise=0.05, sides=48, stacks=16))
        first = seg.fit_regions(dump, spec(min_feature_size=5.0))
        second = seg.fit_regions(dump, spec(min_feature_size=5.0))
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))

    def test_region_identity_is_geometric_and_ignores_face_group_ids(self) -> None:
        """Region identity comes from the triangles, never from a Fusion temp id.

        The grouping decides the *partition*; the temp ids that expressed it are
        not stable across sessions and must not reach the record. Re-numbering
        every group without moving a triangle therefore has to leave the same
        partition -- and no temp id anywhere in the JSON.
        """
        vertices, triangles, groups = box_mesh()
        low = make_dump(vertices, triangles, face_groups=groups)
        high = make_dump(vertices, triangles, face_groups=[901 + 7 * g for g in groups])
        first = seg.fit_regions(low, spec())
        second = seg.fit_regions(high, spec())
        self.assertEqual(
            [r["triangle_indices"] for r in first["regions"]],
            [r["triangle_indices"] for r in second["regions"]],
        )
        # Scanned with the measured floats and the content hashes replaced
        # first: both are digit strings, so a raw substring search over the whole
        # record collides with arithmetic and passes or fails by luck. What is
        # left is every name, key and integer the record actually carries, and no
        # temp id may appear among them.
        def scrubbed(value):
            if isinstance(value, float):
                return "<measured>"
            if isinstance(value, str):
                return "<digest>" if _SHA256.fullmatch(value) else value
            if isinstance(value, dict):
                return {key: scrubbed(item) for key, item in value.items()}
            if isinstance(value, list):
                return [scrubbed(item) for item in value]
            return value

        payload = json.dumps(scrubbed(second))
        for temp_id in sorted({901 + 7 * g for g in groups}):
            self.assertNotIn(str(temp_id), payload, temp_id)
        self.assertNotEqual(low.sha256, high.sha256)

    def test_region_hashes_are_stable_across_runs_over_the_same_dump(self) -> None:
        dump = make_dump(*box_mesh())
        first = seg.fit_regions(dump, spec())
        second = seg.fit_regions(dump, spec())
        self.assertEqual(
            [r["region_hash"] for r in first["regions"]],
            [r["region_hash"] for r in second["regions"]],
        )
        self.assertTrue(first["regions"])

    def test_one_group_over_a_whole_body_is_one_region_and_is_said_so(self) -> None:
        """Not a refusal here. The transaction refuses it, where re-running fixes it."""
        vertices, triangles, groups = box_mesh()
        dump = make_dump(vertices, triangles, face_groups=[0] * len(triangles))
        record = seg.fit_regions(dump, spec())
        self.assertTrue(record["face_groups"]["single_group"])
        self.assertEqual(1, record["face_groups"]["group_count"])
        self.assertEqual(1, len(record["regions"]))

    def test_a_dump_with_no_grouping_refuses_rather_than_segmenting_by_itself(self) -> None:
        dump = make_dump(*box_mesh()[:2])
        record = seg.fit_regions(dump, spec())
        self.assertEqual("face-groups-absent", record["refusal"]["reason"])
        self.assertIn("emit-mesh-face-groups", record["refusal"]["alternative"])
        self.assertFalse(record["face_groups"]["present"])
        self.assertEqual([], record["regions"])
        # It refused before disproof, so it may not claim disproof ran.
        self.assertNotIn("disproof", record["checked"])

    def test_the_grouping_is_the_partition_triangle_for_triangle(self) -> None:
        """Fusion decides which triangles belong together; nothing here re-decides it."""
        vertices, triangles, groups = box_mesh(divisions=8)
        dump = make_dump(vertices, triangles, face_groups=groups)
        record = seg.fit_regions(dump, spec())
        self.assertTrue(record["face_groups"]["present"])
        self.assertEqual(6, record["face_groups"]["group_count"])
        expected = {}
        for index, group in enumerate(groups):
            expected.setdefault(group, []).append(index)
        self.assertEqual(
            sorted(sorted(v) for v in expected.values()),
            sorted(sorted(r["triangle_indices"]) for r in record["regions"]),
        )


# --------------------------------------------------------------------------
# torus and fillets
# --------------------------------------------------------------------------


class TorusTests(unittest.TestCase):
    def test_a_torus_fits_to_its_analytic_radii(self) -> None:
        vertices, _triangles, _groups = torus_mesh(major=12.0, minor=3.0)
        fit = fit_primitive(vertices, "torus")
        self.assertTrue(fit.accepted, fit.rejection)
        self.assertAlmostEqual(12.0, fit.parameters["radius"], places=9)
        self.assertAlmostEqual(3.0, fit.parameters["minor_radius"], places=9)
        self.assertAlmostEqual(1.0, abs(fit.parameters["axis_direction"][2]), places=12)

    def test_a_cylinder_does_not_sprout_a_torus(self) -> None:
        vertices, _triangles, _groups = cylinder_mesh(sides=64, stacks=20)
        fit = fit_primitive(vertices, "torus")
        self.assertFalse(fit.accepted)
        self.assertTrue(fit.rejection)

    def test_the_discriminating_test_names_the_simpler_kind(self) -> None:
        """A torus through points a cylinder already explains is refused by name."""
        vertices, _triangles, _groups = cylinder_mesh(sides=64, stacks=20)
        # Loose enough that a plane does not pre-empt the comparison, tight
        # enough that the torus itself is not simply refused on residual.
        fit = fit_primitive(vertices, "torus", max_relative_residual=0.1)
        self.assertFalse(fit.accepted)
        self.assertIn("cylinder", fit.rejection)

    def test_a_sphere_does_not_sprout_a_torus(self) -> None:
        points = []
        for i in range(40):
            theta = math.pi * (i + 0.5) / 40
            for j in range(40):
                phi = 2.0 * math.pi * j / 40
                points.append(
                    (
                        6.0 * math.sin(theta) * math.cos(phi),
                        6.0 * math.sin(theta) * math.sin(phi),
                        6.0 * math.cos(theta),
                    )
                )
        fit = fit_primitive(points, "torus")
        self.assertFalse(fit.accepted)

    def test_a_torus_is_detected_end_to_end_with_its_analytic_radii(self) -> None:
        """The whole pipeline, on the kind that exists so fillets are not lost area."""
        dump = make_dump(*torus_mesh(major=12.0, minor=3.0))
        record = seg.fit_regions(dump, spec(min_feature_size=3.0))
        tori = [r for r in record["regions"] if r["accepted"] and r["fit"]["kind"] == "torus"]
        self.assertTrue(tori, record["refusal"] or kinds_of(record))
        parameters = tori[0]["fit"]["parameters"]
        self.assertAlmostEqual(12.0, parameters["radius"], places=6)
        self.assertAlmostEqual(3.0, parameters["minor_radius"], places=6)
        self.assertAlmostEqual(1.0, abs(parameters["axis_direction"][2]), places=9)
        self.assertAlmostEqual(1.0, record["covered_area_fraction"], places=6)

    def _region(self, name, index, kind, parameters, span=None):
        fit = {"kind": kind, "parameters": parameters}
        if span is not None:
            fit["support"] = {"angular_span_deg": span}
        return {
            "region_hash": name,
            "triangle_indices": [index],
            "welded_triangle_indices": [index],
            "area": 1.0,
            "fit": fit,
        }

    def test_a_torus_region_adjacent_to_two_primaries_is_flagged_as_a_fillet(self) -> None:
        accepted = [
            self._region("a", 0, "plane", {}),
            self._region("b", 1, "cylinder", {"radius": 9.0}, span=360.0),
            self._region("t", 2, "torus", {"minor_radius": 2.0}),
        ]

        class _Topo:
            tri_neighbours = [[2], [2], [0, 1]]

        seg._mark_fillet_candidates(accepted, _Topo(), 180.0, 0.02)
        blend = accepted[2]
        self.assertTrue(blend["fillet_candidate"])
        self.assertEqual(2.0, blend["fillet"]["radius"])
        self.assertEqual(["a", "b"], blend["fillet"]["between"])
        self.assertFalse(accepted[0]["fillet_candidate"])
        # The full-circle cylinder is a bore, not a blend, so it is a primary.
        self.assertFalse(accepted[1]["fillet_candidate"])

    def test_a_partial_arc_cylinder_between_two_faces_is_a_fillet(self) -> None:
        """The bucket Fusion's grouping actually delivers edge rounds in."""
        accepted = [
            self._region("a", 0, "plane", {}),
            self._region("b", 1, "plane", {}),
            self._region("r", 2, "cylinder", {"radius": 2.0}, span=90.0),
        ]

        class _Topo:
            tri_neighbours = [[2], [2], [0, 1]]

        seg._mark_fillet_candidates(accepted, _Topo(), 180.0, 0.02)
        blend = accepted[2]
        self.assertTrue(blend["fillet_candidate"])
        self.assertEqual(2.0, blend["fillet"]["radius"])
        self.assertEqual(["a", "b"], blend["fillet"]["between"])
        self.assertIn("partial arc", blend["fillet"]["emission"])

    def test_a_full_circle_cylinder_is_a_bore_not_a_fillet(self) -> None:
        accepted = [
            self._region("a", 0, "plane", {}),
            self._region("b", 1, "plane", {}),
            self._region("bore", 2, "cylinder", {"radius": 2.0}, span=355.0),
        ]

        class _Topo:
            tri_neighbours = [[2], [2], [0, 1]]

        seg._mark_fillet_candidates(accepted, _Topo(), 180.0, 0.02)
        self.assertFalse(accepted[2]["fillet_candidate"])
        self.assertNotIn("fillet", accepted[2])

    def test_a_cylinder_whose_arc_was_never_measured_is_not_a_fillet(self) -> None:
        """An absent span is not a small one."""
        accepted = [
            self._region("a", 0, "plane", {}),
            self._region("b", 1, "plane", {}),
            self._region("c", 2, "cylinder", {"radius": 2.0}),
        ]

        class _Topo:
            tri_neighbours = [[2], [2], [0, 1]]

        seg._mark_fillet_candidates(accepted, _Topo(), 180.0, 0.02)
        self.assertFalse(accepted[2]["fillet_candidate"])

    def test_a_blend_needs_two_non_blend_neighbours(self) -> None:
        """Two rounds against each other are not a fillet between two features."""
        accepted = [
            self._region("a", 0, "plane", {}),
            self._region("r1", 1, "cylinder", {"radius": 2.0}, span=90.0),
            self._region("r2", 2, "cylinder", {"radius": 2.0}, span=90.0),
        ]

        class _Topo:
            tri_neighbours = [[1, 2], [0, 2], [0, 1]]

        seg._mark_fillet_candidates(accepted, _Topo(), 180.0, 0.02)
        self.assertFalse(accepted[1]["fillet_candidate"])
        self.assertFalse(accepted[2]["fillet_candidate"])


# --------------------------------------------------------------------------
# the disproof gates
# --------------------------------------------------------------------------


class DisproofTests(unittest.TestCase):
    def test_a_twenty_degree_arc_is_refused_for_support_span(self) -> None:
        vertices, triangles, groups = arc_patch_mesh(sweep_deg=20.0)
        dump = make_dump(vertices, triangles, face_groups=groups)
        record = seg.fit_regions(dump, spec())
        # A 20-degree arc of an r=8 cylinder is a plane to within 0.12 mm, so the
        # residual gate does not catch it and the *structure* gate has to. The
        # region is refused either way; what matters is that nothing is accepted.
        self.assertEqual([], [r for r in record["regions"] if r["accepted"]])
        for region in record["regions"]:
            if region["fit"]["kind"] == "cylinder":
                self.assertFalse(region["accepted"], region["fit"].get("rejection"))

    def test_the_power_floor_is_bound_before_any_branch_that_can_clear_accepted(self) -> None:
        """The support-floors-fail-first path reaches a read of `power_floor`.

        It is safe today only because `and` short-circuits on `accepted` before
        the read, which is an operand order and not an invariant: reorder that
        one condition, or set `accepted` back to true anywhere between, and the
        result is an UnboundLocalError that `fit_regions` turns into
        `fit-record-stage-failed` for the whole mesh. Asserted on the source
        because the failure is latent -- no input reaches it while the ordering
        happens to hold, which is exactly why it needs pinning.
        """
        import inspect

        source = inspect.getsource(seg._stage_disproof)
        bound = source.index("power_floor = max(")
        refuses = source.index("accepted, rejection = False, (")
        reads = source.index("fit.rms_residual <= power_floor")
        self.assertLess(bound, refuses, "power_floor is bound after a branch that can skip it")
        self.assertLess(bound, reads)
        # And the arc patch is the input that walks it: support floors refuse it
        # first, and the stage still completes with a named region refusal.
        record = seg.fit_regions(
            make_dump(*arc_patch_mesh(sweep_deg=20.0)), spec()
        )
        self.assertIsNone(record["refusal"])
        self.assertEqual([], [r for r in record["regions"] if r["accepted"]])

    def test_the_span_gate_measures_the_arc_it_rejects(self) -> None:
        vertices, _triangles, _groups = arc_patch_mesh(sweep_deg=20.0)
        fit = fit_primitive(vertices, "cylinder")
        if fit.accepted:
            passed, measured = seg._support_floors(fit, vertices, spec(), 1.0)
            self.assertFalse(passed)
            self.assertLess(measured["angular_span_deg"], 60.0)

    def test_a_shallow_cone_fitted_as_a_cylinder_is_caught_by_residual_structure(self) -> None:
        vertices, triangles, groups = shallow_cone_mesh()
        dump = make_dump(vertices, triangles, face_groups=groups)
        # Force the cylinder hypothesis onto cone data and check the structure
        # test sees it even though the RMS is flattering.
        fit = fit_primitive(vertices, "cylinder", max_relative_residual=0.05)
        self.assertTrue(fit.accepted, fit.rejection)
        residuals = list(seg._residuals(fit.kind, fit.parameters, vertices))
        structured, coordinate, magnitude = seg._directional_bins(
            fit, vertices, residuals, 1e-6, 4.0
        )
        self.assertTrue(structured)
        self.assertEqual("axial", coordinate)
        self.assertGreater(magnitude, 4.0)

    def test_morans_i_separates_structured_residuals_from_white_noise(self) -> None:
        dump = make_dump(*box_mesh(noise=0.01))
        welded = seg.weld_dump(dump, 1e-9)
        topo = seg._build_topology(welded)
        indices = sorted(range(len(welded.vertices)))
        rng = random.Random(5)
        white = [rng.gauss(0.0, 1.0) for _ in indices]
        smooth = [welded.vertices[i][0] + welded.vertices[i][1] for i in indices]
        noise_stat = seg._moran_i(white, indices, topo)
        structure_stat = seg._moran_i(smooth, indices, topo)
        self.assertIsNotNone(noise_stat)
        self.assertIsNotNone(structure_stat)
        self.assertLess(abs(noise_stat["z"]), 6.0)
        self.assertGreater(structure_stat["z"], 20.0)

    def test_held_out_residual_is_spatially_blocked_not_randomly_split(self) -> None:
        dump = make_dump(*cylinder_mesh(noise=0.03, sides=64, stacks=20))
        record = seg.fit_regions(dump, spec(min_feature_size=5.0))
        for region in record["regions"]:
            support = region["fit"].get("support", {})
            if "heldout_rms" in support:
                self.assertGreater(support["in_sample_rms"], 0.0)
                self.assertLess(support["ratio"], 1.5)
                return
        self.skipTest("no region reached the held-out gate on this fixture")

    def test_a_region_below_the_power_floor_says_so_and_does_not_claim_the_gate(self) -> None:
        """The held-out floor, pinned by name rather than by a fillet test's side effect.

        An exact tessellation fits its planes at float noise, and a held-out
        refit of residuals orders inside the measurement noise compares two
        quantization patterns. The block reports that and deliberately does not
        append `heldout-residual`, so a reader can tell "passed" from "had
        nothing to test".
        """
        record = seg.fit_regions(make_dump(*box_mesh()), spec())
        accepted = [r for r in record["regions"] if r["accepted"]]
        self.assertEqual(6, len(accepted))
        for region in accepted:
            support = region["fit"]["support"]
            self.assertIn("no power here", support["heldout_unavailable_reason"])
            self.assertNotIn("heldout-residual", support["checked"])
            self.assertNotIn("residual-structure", support["checked"])

    def test_the_disproof_note_is_derived_from_the_checked_lists_not_asserted(self) -> None:
        """The note claimed all four gates ran on every accepted fit; two ran on none."""
        record = seg.fit_regions(make_dump(*box_mesh()), spec())
        disproof = record["disproof"]
        self.assertEqual(6, disproof["accepted_fits"])
        gates = disproof["gates"]
        for token in ("support-span-floor", "nested-kind-parsimony"):
            self.assertEqual(6, gates[token]["ran"])
            self.assertEqual({}, gates[token]["skip_reasons"])
        for token in ("residual-structure", "heldout-residual"):
            self.assertEqual(0, gates[token]["ran"])
            self.assertEqual(6, gates[token]["skipped"])
            self.assertEqual([6], list(gates[token]["skip_reasons"].values()))
            self.assertIn("no power here", next(iter(gates[token]["skip_reasons"])))
        # And the counts are the lists', not a second opinion about them.
        for token, gate in gates.items():
            ran = sum(
                1
                for region in record["regions"]
                if region["accepted"] and token in region["fit"]["support"]["checked"]
            )
            self.assertEqual(ran, gate["ran"], token)

    def test_the_parsimony_test_refuses_a_richer_kind_that_did_not_earn_it(self) -> None:
        vertices, _triangles, _groups = cylinder_mesh(sides=64, stacks=20, noise=0.02)
        fit = fit_primitive(vertices, "cone", max_relative_residual=0.5, min_taper_ratio=1e-9)
        if not fit.accepted:
            self.skipTest("the cone fitter refused this cylinder outright, which is also correct")
        earned, detail = seg._parsimony(fit, vertices, spec(), float(len(vertices)))
        self.assertFalse(earned)
        self.assertEqual("cylinder", detail["parsimony_loser"])

    def test_the_f_distribution_tail_matches_known_values(self) -> None:
        # F(1, 10) upper 5% point is 4.9646; upper 1% is 10.044.
        self.assertAlmostEqual(0.05, seg._f_survival(4.9646, 1, 10), places=4)
        self.assertAlmostEqual(0.01, seg._f_survival(10.044, 1, 10), places=4)
        # F(3, 20) upper 5% point is 3.0984.
        self.assertAlmostEqual(0.05, seg._f_survival(3.0984, 3, 20), places=4)

    def test_uncertainty_matches_the_analytic_standard_error(self) -> None:
        rng = random.Random(17)
        points = [(x, y, rng.gauss(0.0, 0.05)) for x in range(-10, 11) for y in range(-10, 11)]
        fit = fit_primitive(points, "plane")
        sigmas = parameter_uncertainty(fit, points)
        # sigma_offset = sigma / sqrt(n) for a plane fitted to n points.
        self.assertAlmostEqual(0.05 / math.sqrt(len(points)), sigmas["offset"], delta=0.0004)

    def test_an_undetermined_fit_reports_no_uncertainty_and_is_refused(self) -> None:
        # A sliver of plane: the normal is not determined about the long axis.
        points = [(x * 1.0, 0.0, 0.0) for x in range(20)] + [(x * 1.0, 0.001, 0.0) for x in range(20)]
        fit = fit_primitive(points, "plane")
        self.assertTrue(fit.accepted)
        passed, _measured = seg._support_floors(fit, points, spec(), 1.0)
        self.assertFalse(passed)

    def test_an_empty_uncertainty_is_a_rejection_never_a_pass(self) -> None:
        vertices, _triangles, _groups = cylinder_mesh(sides=64, stacks=20)
        fit = fit_primitive(vertices, "cylinder")
        self.assertIsNotNone(seg._uncertainty_gate({}, fit, spec()))
        self.assertIn("not determined", seg._uncertainty_gate({}, fit, spec()))


# --------------------------------------------------------------------------
# the record contract U3 consumes
# --------------------------------------------------------------------------


class RecordContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dump = make_dump(*cylinder_mesh(radius=8.0, height=30.0, sides=64, stacks=20))
        self.record = seg.fit_regions(self.dump, spec())
        self.accepted = [r for r in self.record["regions"] if r["accepted"]]

    def test_the_record_carries_its_bindings_and_units(self) -> None:
        self.assertEqual(seg.RECORD_VERSION, self.record["record_version"])
        self.assertEqual(self.dump.sha256, self.record["dump_sha256"])
        self.assertEqual("mm", self.record["units"])
        self.assertEqual("c" * 64, self.record["manifest_sha256"])

    def test_regions_carry_the_dump_indices_downstream_needs(self) -> None:
        self.assertTrue(self.accepted)
        for region in self.accepted:
            self.assertTrue(region["inlier_vertex_indices"])
            self.assertEqual(
                sorted(region["inlier_vertex_indices"]), region["inlier_vertex_indices"]
            )
            self.assertLess(max(region["inlier_vertex_indices"]), self.dump.vertex_count)
            self.assertLess(max(region["triangle_indices"]), self.dump.triangle_count)

    def test_regions_carry_area_and_bounding_box_under_those_names(self) -> None:
        for region in self.accepted:
            self.assertGreater(region["area"], 0.0)
            lo, hi = region["bounding_box"]
            self.assertEqual(3, len(lo))
            self.assertTrue(all(h >= l for l, h in zip(lo, hi)))

    def test_axis_bearing_fits_carry_axial_span_under_exactly_that_key(self) -> None:
        for region in self.accepted:
            if region["fit"]["kind"] in ("cylinder", "cone", "torus"):
                self.assertIn("axial_span", region["fit"]["support"])
                self.assertGreater(region["fit"]["support"]["axial_span"], 0.0)

    def test_accepted_fits_carry_a_one_sigma_per_parameter(self) -> None:
        for region in self.accepted:
            self.assertTrue(region["fit"]["uncertainty"], region["fit"]["kind"])
            for value in region["fit"]["uncertainty"].values():
                self.assertGreaterEqual(value, 0.0)

    def test_orientation_evidence_is_present_and_refuses_to_guess_on_an_open_mesh(self) -> None:
        for region in self.accepted:
            orientation = region["orientation"]
            self.assertIn("material_side", orientation)
            # The tube fixture is open, so no inside/outside claim is licensed.
            self.assertIsNone(orientation["material_side"])
            self.assertIsNotNone(orientation["unavailable_reason"])

    def test_a_plane_reports_its_outward_direction_instead_of_a_side(self) -> None:
        """A plane encloses nothing, so "inside" is not a claim it can support."""
        dump = make_dump(*box_mesh())
        record = seg.fit_regions(dump, spec())
        accepted = [r for r in record["regions"] if r["accepted"]]
        self.assertEqual(6, len(accepted))
        outward = []
        for region in accepted:
            orientation = region["orientation"]
            self.assertIsNone(orientation["material_side"])
            self.assertTrue(orientation["mesh_closed"])
            self.assertEqual("outward", orientation["mesh_winding"])
            outward.append(tuple(round(c, 9) for c in orientation["outward_normal"]))
        # Six faces of a box: six distinct outward directions, the axis pairs.
        self.assertEqual(6, len(set(outward)))

    def test_a_bore_and_a_boss_are_distinguishable_on_a_closed_mesh(self) -> None:
        """The winding evidence a hole archetype needs, and its refusal to guess."""
        vertices, triangles, groups = cylinder_mesh(radius=8.0, height=30.0, sides=64, stacks=20)
        outward = seg.fit_regions(make_dump(vertices, triangles, face_groups=groups), spec())
        cylinders = [
            r for r in outward["regions"] if r["accepted"] and r["fit"]["kind"] == "cylinder"
        ]
        # Asserted, not skipped past: a test that quietly stops testing when the
        # fixture changes shape is the failure mode this suite exists to catch.
        self.assertTrue(cylinders, [r["fit"]["kind"] for r in outward["regions"]])
        for region in cylinders:
            # The tube fixture is open, so no side may be claimed.
            self.assertIsNone(region["orientation"]["material_side"])
            self.assertFalse(region["orientation"]["mesh_closed"])
            self.assertIsNotNone(region["orientation"]["unavailable_reason"])

    def test_unclaimed_area_is_reported_with_its_curvature_signature(self) -> None:
        unclaimed = self.record["unclaimed"]
        self.assertIn("components", unclaimed)
        for component in unclaimed["components"]:
            self.assertIn(component["dominant_curvature"], seg.CURVATURE_CLASSES)
            self.assertEqual(2, len(component["bounding_box"]))

    def test_a_rejected_fit_is_kept_with_the_gate_that_killed_it(self) -> None:
        vertices, triangles, groups = arc_patch_mesh(sweep_deg=20.0)
        record = seg.fit_regions(make_dump(vertices, triangles, face_groups=groups), spec())
        rejected = record["unfitted_regions"]
        self.assertTrue(rejected)
        if rejected:
            for entry in rejected:
                self.assertTrue(entry["failed_gate"])
                self.assertIn("area_fraction", entry)

    def test_the_record_is_json_serializable(self) -> None:
        json.dumps(self.record, sort_keys=True)


# --------------------------------------------------------------------------
# the checked-list construction rule (R12)
# --------------------------------------------------------------------------


class CheckedListTests(unittest.TestCase):
    def test_a_stage_that_raises_leaves_no_entry_in_checked(self) -> None:
        """R12, enforced rather than reviewed.

        The rule is that `checked` is appended by the block that ran the check,
        after it succeeded. The only way to prove that is to make a check raise
        and assert its name is absent -- which is what this does.
        """
        dump = make_dump(*box_mesh(divisions=8))

        def explode(_state):
            raise RuntimeError("this check did not complete")

        original = seg._stage_noise_scale
        seg._stage_noise_scale = explode
        try:
            record = seg.fit_regions(dump, spec())
        finally:
            seg._stage_noise_scale = original

        self.assertNotIn("noise-scale", record["checked"])
        self.assertEqual(["triangle-budget", "weld", "topology"], record["checked"])
        self.assertEqual("fit-record-stage-failed", record["refusal"]["reason"])
        self.assertEqual("noise-scale", record["refusal"]["detail"]["stage"])
        self.assertIn("RuntimeError", record["refusal"]["detail"]["error"])
        self.assertEqual([], record["regions"])

    def test_a_stage_that_refuses_also_leaves_no_entry(self) -> None:
        dump = make_dump(*box_mesh(divisions=8))
        record = seg.fit_regions(dump, spec(max_triangles=4))
        self.assertEqual([], record["checked"])
        self.assertEqual("triangle-budget-exceeded", record["refusal"]["reason"])

    def test_a_complete_run_checks_every_stage(self) -> None:
        record = seg.fit_regions(make_dump(*box_mesh()), spec())
        self.assertIsNone(record["refusal"])
        self.assertEqual(list(seg.STAGES), record["checked"])

    def test_gate_level_checked_lists_follow_the_same_rule(self) -> None:
        vertices, _triangles, _groups = cylinder_mesh(sides=64, stacks=20)
        accepted = fit_primitive(vertices, "cylinder")
        self.assertIn("relative-residual", accepted.support["checked"])
        # A near-flat strip fits an enormous circle: rejected by the very first
        # gate, so no later gate may appear in the list.
        strip = [(x * 1.0, 0.0, 0.001 * x * x) for x in range(-15, 16)]
        strip += [(x * 1.0, 1.0, 0.001 * x * x) for x in range(-15, 16)]
        rejected = fit_primitive(strip, "cylinder")
        self.assertFalse(rejected.accepted)
        self.assertEqual([], rejected.support["checked"])


# --------------------------------------------------------------------------
# refusal vocabulary
# --------------------------------------------------------------------------


class RefusalTests(unittest.TestCase):
    def test_the_refusal_vocabulary_is_closed(self) -> None:
        with self.assertRaises(ValueError):
            seg._refusal("segmentation-noise-limited", {}, "the old vocabulary is gone")

    def test_every_refusal_carries_a_named_alternative(self) -> None:
        dump = make_dump(*box_mesh(divisions=8))
        for declared in (spec(max_triangles=4), spec(min_covered_area_fraction=1.0)):
            record = seg.fit_regions(dump, declared)
            if record["refusal"] is not None:
                self.assertIn(record["refusal"]["reason"], seg.REFUSAL_REASONS)
                self.assertTrue(record["refusal"]["alternative"].strip())

    def test_coverage_below_the_declared_floor_refuses_and_names_the_signatures(self) -> None:
        # A twenty-degree arc patch: a real cylinder, but no evidence of one, so
        # every fit is refused and the coverage floor is what turns that into a
        # named outcome instead of an empty record.
        dump = make_dump(*arc_patch_mesh(sweep_deg=20.0))
        record = seg.fit_regions(dump, spec(min_covered_area_fraction=0.5))
        self.assertEqual("segmentation-coverage-insufficient", record["refusal"]["reason"])
        self.assertIn("unclaimed_signatures", record["refusal"]["detail"])
        self.assertLess(record["refusal"]["detail"]["covered_area_fraction"], 0.5)

    def test_this_module_never_imports_adsk(self) -> None:
        """Offline testability is the architecture's load-bearing property."""
        import pathlib

        source = pathlib.Path(seg.__file__).read_text(encoding="utf-8")
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                self.assertNotIn("adsk", stripped)

    def test_the_sigma_estimator_calibration_is_re_derived_not_trusted(self) -> None:
        """The quartile calibration constant, checked against its own Monte Carlo."""
        from fusion_design.mesh_fitting import _centroid, _covariance, _symmetric_eigen

        rng = random.Random(1)
        k = seg._SIGMA_A_NEIGHBOURS
        sigma = 0.05
        estimates = []
        for _ in range(1500):
            patch = []
            for _i in range(k):
                angle = 2.0 * math.pi * rng.random()
                radius = math.sqrt(rng.random())
                patch.append(
                    (radius * math.cos(angle), radius * math.sin(angle), rng.gauss(0.0, sigma))
                )
            values, _vectors = _symmetric_eigen(_covariance(patch, _centroid(patch)))
            estimates.append(math.sqrt(max(0.0, values[0]) * k / (k - 3)) / sigma)
        measured = seg._quantile(estimates, seg._SIGMA_A_QUANTILE)
        self.assertAlmostEqual(seg._SIGMA_A_QUANTILE_CALIBRATION, measured, delta=0.02)


# --------------------------------------------------------------------------
# the measured noise ceiling, and the runtime budget
# --------------------------------------------------------------------------


class NoiseCeilingTests(unittest.TestCase):
    """Where the estimator actually breaks, measured against ground truth.

    The spec predicts correct gated fits at point noise up to roughly the median
    triangle edge length. This sweeps a known cylinder across noise levels and
    records the highest one at which the radius is still recovered. It asserts
    only the contested case, and reports the rest, because asserting the exact
    breaking point would make a flaky test out of a measurement.
    """

    def test_the_contested_noise_level_is_handled_with_margin(self) -> None:
        dump = make_dump(*cylinder_mesh(radius=8.0, height=30.0, sides=64, stacks=24, noise=0.05))
        record = seg.fit_regions(dump, spec(min_feature_size=5.0))
        cylinders = [
            r for r in record["regions"] if r["accepted"] and r["fit"]["kind"] == "cylinder"
        ]
        self.assertTrue(cylinders, record["refusal"])
        self.assertAlmostEqual(8.0, cylinders[0]["fit"]["parameters"]["radius"], delta=0.1)

    @unittest.skipUnless(
        os.environ.get("FUSION_DESIGN_NOISE_SWEEP"),
        "noise sweep is a measurement, not a gate; set FUSION_DESIGN_NOISE_SWEEP=1",
    )
    def test_noise_sweep_reports_the_ceiling(self) -> None:  # pragma: no cover - measurement
        edge = 2.0 * math.pi * 8.0 / 64
        for ratio in (0.0, 0.05, 0.1, 0.2, 0.4, 0.8, 1.2):
            sigma = ratio * edge
            dump = make_dump(
                *cylinder_mesh(radius=8.0, height=30.0, sides=64, stacks=24, noise=sigma)
            )
            record = seg.fit_regions(dump, spec(min_feature_size=50.0))
            found = [
                r for r in record["regions"] if r["accepted"] and r["fit"]["kind"] == "cylinder"
            ]
            radius = found[0]["fit"]["parameters"]["radius"] if found else None
            print(
                f"sigma/edge={ratio:>4}  sigma={sigma:.4f}  measured={record['noise']['sigma']:.4f}  "
                f"sigma_theta={record['normals']['sigma_theta_deg']:.2f}deg  "
                f"radius={radius}  refusal={(record['refusal'] or {}).get('reason')}"
            )

    @unittest.skipUnless(
        os.environ.get("FUSION_DESIGN_BENCHMARK"),
        "benchmark is a measurement, not a gate; set FUSION_DESIGN_BENCHMARK=1",
    )
    def test_benchmark_reports_runtime(self) -> None:  # pragma: no cover - measurement
        for sides, stacks in ((64, 40), (140, 90), (260, 190)):
            vertices, triangles, groups = cylinder_mesh(sides=sides, stacks=stacks, noise=0.02)
            dump = make_dump(vertices, triangles, face_groups=groups)
            started = time.monotonic()
            record = seg.fit_regions(dump, spec(min_feature_size=5.0))
            print(
                f"triangles={len(triangles):>7}  seconds={time.monotonic() - started:7.2f}  "
                f"regions={len(record['regions'])}  refusal={(record['refusal'] or {}).get('reason')}"
            )


class CliTests(unittest.TestCase):
    def _write(self, directory, dump, declared):
        import json as _json

        dump_path = directory / "mesh.bin"
        spec_path = directory / "spec.json"
        spec_path.write_text(_json.dumps(declared), encoding="utf-8")
        return dump_path, spec_path

    def test_fit_regions_reads_a_hash_bound_dump_and_prints_a_record(self) -> None:
        import contextlib
        import io
        import json as _json
        import pathlib
        import tempfile

        from fusion_design.cli import main
        from fusion_design.mesh_dump import pack_mesh_dump

        vertices, triangles, groups = box_mesh()
        meta = _metadata()
        meta["face_groups_source"] = "triangleFaceGroupTempIds"
        data = pack_mesh_dump(
            meta, [c for p in vertices for c in p], [i for t in triangles for i in t], groups
        )
        digest = hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as raw:
            directory = pathlib.Path(raw)
            (directory / "mesh.bin").write_bytes(data)
            (directory / "spec.json").write_text(
                _json.dumps(
                    {n: {"value": v, "rationale": w} for n, (v, w) in REFERENCE.items()}
                ),
                encoding="utf-8",
            )
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(
                    [
                        "fit-regions",
                        str(directory / "mesh.bin"),
                        "--dump-sha256",
                        digest,
                        "--spec",
                        str(directory / "spec.json"),
                    ]
                )
            self.assertEqual(0, code)
            record = _json.loads(out.getvalue())
            self.assertEqual(digest, record["dump_sha256"])
            self.assertEqual(6, len([r for r in record["regions"] if r["accepted"]]))

            # A digest that does not match the bytes refuses before parsing.
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                code = main(
                    [
                        "fit-regions",
                        str(directory / "mesh.bin"),
                        "--dump-sha256",
                        "0" * 64,
                        "--spec",
                        str(directory / "spec.json"),
                    ]
                )
            self.assertEqual(2, code)
            self.assertIn("dump-hash-mismatch", errors.getvalue())

    def test_a_refusal_exits_non_zero_so_nothing_downstream_consumes_it(self) -> None:
        import contextlib
        import io
        import json as _json
        import pathlib
        import tempfile

        from fusion_design.cli import main
        from fusion_design.mesh_dump import pack_mesh_dump

        vertices, triangles, groups = box_mesh(divisions=8)
        data = pack_mesh_dump(
            _metadata(),
            [c for p in vertices for c in p],
            [i for t in triangles for i in t],
            None,
        )
        digest = hashlib.sha256(data).hexdigest()
        declared = {n: {"value": v, "rationale": w} for n, (v, w) in REFERENCE.items()}
        declared["max_triangles"] = {"value": 4, "rationale": REFERENCE["max_triangles"][1]}
        with tempfile.TemporaryDirectory() as raw:
            directory = pathlib.Path(raw)
            (directory / "mesh.bin").write_bytes(data)
            (directory / "spec.json").write_text(_json.dumps(declared), encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(
                    [
                        "fit-regions",
                        str(directory / "mesh.bin"),
                        "--dump-sha256",
                        digest,
                        "--spec",
                        str(directory / "spec.json"),
                    ]
                )
            self.assertEqual(2, code)
            self.assertEqual(
                "triangle-budget-exceeded", _json.loads(out.getvalue())["refusal"]["reason"]
            )


# --------------------------------------------------------------------------
# normals as fit data, the measurement regime, and the evidence they unlock
#
# The measured failure these exist for: across 11 production STLs, 85 full-turn
# bores were refused because two rings of vertices carry no axial baseline. The
# facets between the rings carry the axis exactly, and none of the declared
# thresholds moves.
# --------------------------------------------------------------------------


class NormalConstrainedRegionTests(unittest.TestCase):
    def _shallow_bore(self):
        # One stack: two rings of vertices and nothing between them, which is how
        # a solid modeller tessellates a shallow bore.
        return make_dump(*cylinder_mesh(radius=5.0, height=2.0, sides=48, stacks=1))

    def test_a_shallow_two_ring_bore_is_accepted_on_its_facet_normals(self) -> None:
        record = seg.fit_regions(self._shallow_bore(), spec())
        cylinders = [r for r in record["regions"] if r["accepted"] and r["fit"]["kind"] == "cylinder"]
        self.assertTrue(cylinders, record["refusal"] or record["unfitted_regions"])
        support = cylinders[0]["fit"]["support"]
        self.assertEqual("facet-normals", support["axis_evidence"]["source"])
        self.assertEqual("facet-normals", support["axis_determined_by"])
        self.assertFalse(support["axial_span_floor_applied"])
        # The floor was still *measured*, and the bore is still short of it. What
        # changed is which evidence the fit rests on, not the number.
        self.assertLess(support["axial_span"], support["axial_span_floor"])
        self.assertAlmostEqual(5.0, cylinders[0]["fit"]["parameters"]["radius"], places=6)

    def test_the_same_bore_is_refused_when_the_normals_do_not_determine_it_either(self) -> None:
        """The floor is not loosened; it is applied to whatever determined the axis.

        Declaring an eigengap floor no facet ring can reach takes the normals out
        of the determination, and the vertex evidence then faces exactly the
        floor it always faced -- at exactly the same value.
        """
        dump = self._shallow_bore()
        passed = seg.fit_regions(dump, spec())
        refused = seg.fit_regions(dump, spec(min_normal_axis_eigengap=0.9))
        cylinder = [r for r in refused["regions"] if r["fit"]["kind"] == "cylinder"][0]
        self.assertFalse(cylinder["accepted"])
        self.assertIn("support floors", cylinder["fit"]["rejection"])
        self.assertEqual("vertices", cylinder["fit"]["support"]["axis_determined_by"])
        self.assertTrue(cylinder["fit"]["support"]["axial_span_floor_applied"])
        # Same declared floor, same measured span, opposite verdict -- and the
        # only difference between the two runs is which evidence was allowed to
        # determine the axis.
        accepted = [r for r in passed["regions"] if r["accepted"] and r["fit"]["kind"] == "cylinder"][0]
        for key in ("axial_span", "axial_span_floor"):
            self.assertAlmostEqual(
                accepted["fit"]["support"][key], cylinder["fit"]["support"][key], places=9
            )
        self.assertEqual(
            passed["thresholds"]["min_axial_span_ratio"],
            refused["thresholds"]["min_axial_span_ratio"],
        )

    def test_a_bore_is_corroborated_by_the_circle_its_own_boundary_traces(self) -> None:
        record = seg.fit_regions(self._shallow_bore(), spec())
        cylinder = [r for r in record["regions"] if r["accepted"] and r["fit"]["kind"] == "cylinder"][0]
        boundary = cylinder["fit"]["support"]["boundary_circle"]
        self.assertAlmostEqual(5.0, boundary["loop_radius"], places=6)
        self.assertIsNone(boundary["flag"])
        self.assertTrue(boundary["agrees_on_radius"])
        self.assertLess(boundary["loop_normal_to_axis_deg"], 1e-06)
        self.assertIn("boundary-circle-corroboration", cylinder["fit"]["support"]["checked"])
        # Corroboration is reported beside the fit, never folded into it: the
        # parameters still carry the surface fit's own radius and the loop's is a
        # second, separately named number.
        self.assertEqual(cylinder["fit"]["parameters"]["radius"], boundary["fitted_radius"])
        self.assertIn("loop_radius", boundary)

    def test_a_boundary_circle_that_disagrees_is_flagged_and_moves_nothing(self) -> None:
        """The other half of the corroboration, which had no test naming it.

        The same bore, judged against a fit whose radius is half a millimetre
        out. The loop still measures 5.0, the disagreement is far beyond the
        joint uncertainty, and the flag says so -- while the fit's own radius is
        left exactly where it was, because corroboration that quietly moved the
        answer would stop being corroboration.
        """
        dump = self._shallow_bore()
        welded = seg.weld_dump(dump, 1e-09)
        topo = seg._build_topology(welded)
        record = seg.fit_regions(dump, spec())
        cylinder = [
            r for r in record["regions"] if r["accepted"] and r["fit"]["kind"] == "cylinder"
        ][0]
        parameters = dict(cylinder["fit"]["parameters"])
        parameters["radius"] = parameters["radius"] + 0.5
        wrong = seg.PrimitiveFit(
            kind="cylinder",
            accepted=True,
            rms_residual=cylinder["fit"]["rms_residual"],
            relative_residual=cylinder["fit"]["relative_residual"],
            extent=cylinder["fit"]["extent"],
            parameters={
                key: tuple(value) if isinstance(value, list) else value
                for key, value in parameters.items()
            },
        )
        measured = seg._boundary_corroboration(
            wrong,
            cylinder["fit"]["uncertainty"],
            cylinder["welded_triangle_indices"],
            welded,
            topo,
            3.0,
            record["noise"]["surface_scale"],
        )
        self.assertEqual("boundary-circle-disagrees", measured["flag"])
        self.assertFalse(measured["agrees_on_radius"])
        self.assertAlmostEqual(5.0, measured["loop_radius"], places=6)
        self.assertAlmostEqual(-0.5, measured["radius_delta"], places=6)
        self.assertEqual(wrong.parameters["radius"], measured["fitted_radius"])

    def test_a_cone_is_corroborated_at_the_station_its_own_loop_sits_at(self) -> None:
        """`_AXIS_KINDS` names cone, and a cone never reached this check.

        The guard read a dead `anchor` local matching `axis_point` or `center`;
        a cone's anchor key is `apex`, so `anchor` was always None and the
        function returned before looking at a single loop. A cone's radius also
        varies along its axis, so the number a loop is comparable to is the
        cone's radius *at that loop's station* -- apex to loop centre along the
        axis, times the taper -- and not one constant it does not have.
        """
        record = seg.fit_regions(
            make_dump(*shallow_cone_mesh(taper=0.5)), spec(min_feature_size=3.0)
        )
        cone = [r for r in record["regions"] if r["accepted"] and r["fit"]["kind"] == "cone"][0]
        boundary = cone["fit"]["support"]["boundary_circle"]
        self.assertIn("boundary-circle-corroboration", cone["fit"]["support"]["checked"])
        # The fixture's base ring: radius 8.0 at z = 0, and the cone's own radius
        # there to a tenth of a percent.
        self.assertAlmostEqual(8.0, boundary["loop_radius"], places=9)
        self.assertAlmostEqual(8.0, boundary["fitted_radius"], delta=0.05)
        self.assertLess(abs(boundary["radius_delta"]), 0.05)
        self.assertTrue(boundary["agrees_on_axis"])
        self.assertIsNone(boundary["flag"])
        # A cone carries no radius sigma, so the radius reading is reported and
        # explicitly unsized rather than counted as agreement.
        self.assertIsNone(boundary["radius_sigma"])
        self.assertIsNone(boundary["agrees_on_radius"])

    def test_a_closed_surface_has_no_boundary_to_be_corroborated_by(self) -> None:
        """Absent evidence is absent, not agreement."""
        record = seg.fit_regions(make_dump(*torus_mesh(major=12.0, minor=3.0)), spec(min_feature_size=3.0))
        tori = [r for r in record["regions"] if r["accepted"] and r["fit"]["kind"] == "torus"]
        self.assertTrue(tori, record["refusal"])
        support = tori[0]["fit"]["support"]
        self.assertNotIn("boundary_circle", support)
        self.assertNotIn("boundary-circle-corroboration", support["checked"])


def plate_with_pockets(*, sides, radius=6.0, depth=12.0, stacks=3, plate=60.0):
    """A tessellated plate with one prismatic/cylindrical pocket standing beside it.

    The plate is what makes this a *tessellation*: its faces put the tenth
    percentile of the quadric residual at exactly zero and its coplanar interior
    edges make the dihedral distribution bimodal, which is the honeycomb's
    situation and not a bare tube's.  ``sides`` is the pocket's wall count, and
    the whole point is that the vertices cannot tell six walls from six facets:
    a regular polygon's corners lie exactly on its circumscribed circle.
    """
    vertices, triangles, groups = box_mesh(size=plate, divisions=6)
    vertices, triangles, groups = list(vertices), list(triangles), list(groups)
    offset = len(vertices)
    for k in range(stacks + 1):
        z = 10.0 + depth * k / stacks
        for i in range(sides):
            angle = 2.0 * math.pi * i / sides
            vertices.append((30.0 + radius * math.cos(angle), 90.0 + radius * math.sin(angle), z))
    for k in range(stacks):
        for i in range(sides):
            a = offset + k * sides + i
            b = offset + k * sides + (i + 1) % sides
            c = offset + (k + 1) * sides + (i + 1) % sides
            d = offset + (k + 1) * sides + i
            triangles.append((a, b, c))
            triangles.append((a, c, d))
            # The box's six analytic faces are groups 0..5; the pocket is the
            # seventh, exactly as Fusion delivers a pocket's walls: one group.
            groups.extend([6, 6])
    return vertices, triangles, groups


class DiscreteNormalTests(unittest.TestCase):
    """The hex pocket that fits its own circumscribed cylinder, and the coarse bore that does not.

    Measured on the honeycomb organiser: six hexagonal pockets came back as six
    round bores of radius 15*cos(30) at float-noise residual, because a regular
    hexagon's six corners lie *exactly* on that circle.  Every gate that reads
    vertices passed them.  The facet normals are the only evidence that separates
    the two, and the two sides of this test are the two sides of the declared
    threshold.
    """

    def _pocket(self, sides, **declared):
        """The record, and the one region that is the pocket's walls."""
        record = seg.fit_regions(
            make_dump(*plate_with_pockets(sides=sides)),
            spec(min_feature_size=1.0, **declared),
        )
        self.assertIsNone(record["refusal"], record["refusal"])
        walls = [r for r in record["regions"] if r["triangle_count"] == 6 * sides]
        self.assertEqual(1, len(walls), [r["triangle_count"] for r in record["regions"]])
        return record, walls[0]

    def test_a_hexagonal_pocket_is_refused_as_a_cylinder_by_its_own_facet_normals(self) -> None:
        _record, region = self._pocket(6)
        self.assertFalse(region["accepted"])
        self.assertIn("cylinder-normals-discrete", region["fit"]["rejection"])

    def test_the_refusal_records_the_cluster_count_and_the_arc_they_cover(self) -> None:
        """A named refusal that does not say what it measured is folklore."""
        _record, region = self._pocket(6)
        spread = region["fit"]["support"]["normal_direction_spread"]
        self.assertEqual(6, spread["directions"])
        self.assertEqual(36, spread["facet_count"])
        self.assertAlmostEqual(300.0, spread["angular_coverage_deg"], places=6)
        self.assertAlmostEqual(7.2, spread["directions_per_turn"], places=6)
        self.assertEqual(8.0, spread["min_directions_per_turn"])
        # The other half of the claim: these normals really are arranged around
        # an axis. Without that the group could be a sphere, and refusing it as a
        # prism would be an assertion about evidence nobody produced.
        self.assertLess(spread["max_deviation_from_perpendicular_deg"], 1e-09)

    def test_a_coarse_eight_facet_bore_still_passes_the_same_gate(self) -> None:
        """The boundary, from the other side: the threshold is where the caller put it."""
        _record, region = self._pocket(8)
        self.assertTrue(region["accepted"], region["fit"].get("rejection"))
        self.assertEqual("cylinder", region["fit"]["kind"])
        spread = region["fit"]["support"]["normal_direction_spread"]
        self.assertEqual(8, spread["directions"])
        self.assertGreater(spread["directions_per_turn"], 8.0)
        self.assertIn("cylinder-normals-discrete", region["fit"]["support"]["checked"])

    def test_a_finely_tessellated_bore_is_nowhere_near_the_gate(self) -> None:
        _record, region = self._pocket(48)
        self.assertTrue(region["accepted"], region["fit"].get("rejection"))
        spread = region["fit"]["support"]["normal_direction_spread"]
        self.assertEqual(48, spread["directions"])
        self.assertGreater(spread["directions_per_turn"], 40.0)

    def test_the_declared_minimum_is_what_decides_and_nothing_else_moves(self) -> None:
        """Raise the caller's threshold past the coarse bore and it goes too."""
        _record, region = self._pocket(8, min_cylinder_normal_directions_per_turn=16.0)
        self.assertFalse(region["accepted"])
        self.assertIn("cylinder-normals-discrete", region["fit"]["rejection"])


class SigmaSelectionTests(unittest.TestCase):
    """Which estimator sigma comes from is the regime's decision, not the maximum's.

    The honeycomb is the case: 61.5% of its interior edges are genuine 60-degree
    cell walls, so the dihedral estimator -- whose stated assumption is that real
    creases are a small minority -- reported 13.108 mm of noise on a mesh whose
    quadric estimator reported exactly 0.0.  `sigma = max(...)` ran before the
    regime was known, so the regime check that already suppressed the
    *noise-model-inconsistent flag* never saw the *value*, and a 169 mm part
    refused `feature-scale-below-noise` claiming 131 mm was unrecoverable.
    """

    def test_a_tessellation_takes_sigma_from_the_quadric_estimator(self) -> None:
        """The torus is the lever: a tessellated tube's dihedral is 2.2x its quadric.

        The disagreement is the same one the honeycomb has and the same one the
        record already flags -- only larger there, because a honeycomb's creases
        are 60 degrees and a fine torus's facet turns are five. Declaring the
        regime is what isolates the *selection* from the detection.
        """
        auto = seg.fit_regions(make_dump(*torus_mesh(major=12.0, minor=3.0)), spec(min_feature_size=1.0))
        declared = seg.fit_regions(
            make_dump(*torus_mesh(major=12.0, minor=3.0)),
            spec(min_feature_size=1.0, regime="tessellation"),
        )
        self.assertEqual("scan", auto["noise"]["regime"])
        self.assertEqual("dihedral", auto["noise"]["sigma_estimator"])
        self.assertEqual("tessellation", declared["noise"]["regime"])
        self.assertEqual("quadric", declared["noise"]["sigma_estimator"])
        # Both estimators are recorded in both runs -- the cross-check stays
        # honest, and it is only the selection that respects the regime.
        for record in (auto, declared):
            self.assertEqual(auto["noise"]["sigma_quadric"], record["noise"]["sigma_quadric"])
            self.assertEqual(auto["noise"]["sigma_dihedral"], record["noise"]["sigma_dihedral"])
        self.assertEqual(declared["noise"]["sigma_quadric"], declared["noise"]["sigma"])
        self.assertLess(declared["noise"]["sigma"], auto["noise"]["sigma"])

    def test_the_dihedral_reading_becomes_the_discretization_scale(self) -> None:
        """It is not discarded: on a tessellation a dihedral is a facet turn angle.

        `surface_scale` is what sizes the power floor under the residual-structure
        and held-out tests, and the dihedral reading was already reaching it
        through `sigma` in both regimes. Moving it here is what leaves every one
        of those gates exactly where it was -- measured over the 11-part corpus,
        every accepted region, archetype and coverage figure is unchanged.
        """
        auto = seg.fit_regions(make_dump(*torus_mesh(major=12.0, minor=3.0)), spec(min_feature_size=1.0))
        declared = seg.fit_regions(
            make_dump(*torus_mesh(major=12.0, minor=3.0)),
            spec(min_feature_size=1.0, regime="tessellation"),
        )
        self.assertEqual(auto["noise"]["surface_scale"], declared["noise"]["surface_scale"])
        self.assertGreaterEqual(declared["noise"]["surface_scale"], declared["noise"]["sigma_dihedral"])
        self.assertGreater(
            declared["noise"]["discretization_scale"], auto["noise"]["discretization_scale"]
        )

    def test_a_quiet_tessellation_falls_to_the_vertex_precision_floor(self) -> None:
        """With both estimators at zero the floor is the only thing left, and it binds."""
        noise = seg.fit_regions(make_dump(*box_mesh()), spec())["noise"]
        self.assertEqual("tessellation", noise["regime"])
        self.assertEqual("quadric", noise["sigma_estimator"])
        self.assertEqual(noise["vertex_precision_floor"], noise["sigma"])
        self.assertTrue(noise["precision_floor_binds"])

    def test_a_scan_still_takes_the_conservative_larger_of_the_two(self) -> None:
        noise = seg.fit_regions(
            make_dump(*box_mesh(size=20.0, divisions=14, noise=0.05)), spec(min_feature_size=5.0)
        )["noise"]
        self.assertEqual("scan", noise["regime"])
        self.assertAlmostEqual(
            max(noise["sigma_quadric"], noise["sigma_dihedral"]), noise["sigma"], places=12
        )
        self.assertEqual(
            "quadric" if noise["sigma_quadric"] >= noise["sigma_dihedral"] else "dihedral",
            noise["sigma_estimator"],
        )

    def test_the_feature_scale_budget_is_the_thing_the_selection_moves(self) -> None:
        """`feature-scale-below-noise` is the refusal the honeycomb hit, and it reads sigma.

        Ten sigma is the recoverable feature size, so an estimator measuring the
        part's own creases prices the whole part out: 13.108 mm of "noise" on the
        honeycomb put the recoverable feature at 131 mm of a 169 mm part. Here is
        the same arithmetic, on one mesh, under the two regimes.
        """
        auto = seg.fit_regions(make_dump(*torus_mesh(major=12.0, minor=3.0)), spec(min_feature_size=1.0))
        declared = seg.fit_regions(
            make_dump(*torus_mesh(major=12.0, minor=3.0)),
            spec(min_feature_size=1.0, regime="tessellation"),
        )
        for record in (auto, declared):
            self.assertAlmostEqual(
                10.0 * record["noise"]["sigma"],
                record["feature_scale"]["recoverable_feature_size"],
                places=12,
            )
        self.assertLess(
            declared["feature_scale"]["recoverable_feature_size"],
            auto["feature_scale"]["recoverable_feature_size"],
        )


class RegimeTests(unittest.TestCase):
    def test_an_exact_tessellation_is_detected_and_stops_the_noise_flag(self) -> None:
        record = seg.fit_regions(make_dump(*box_mesh()), spec())
        regime = record["regime"]
        self.assertEqual("tessellation", regime["regime"])
        self.assertEqual("tessellation", regime["detected"])
        self.assertTrue(regime["evidence"]["vertices_read_as_exact"])
        self.assertTrue(regime["evidence"]["dihedral_reads_as_bimodal"])
        self.assertNotIn("noise-model-inconsistent", record["flags"])

    def test_a_noisy_mesh_reads_as_a_scan(self) -> None:
        record = seg.fit_regions(
            make_dump(*box_mesh(size=20.0, divisions=14, noise=0.05)), spec(min_feature_size=5.0)
        )
        self.assertEqual("scan", record["regime"]["regime"])
        self.assertFalse(record["regime"]["evidence"]["vertices_read_as_exact"])

    def test_a_declared_regime_overrides_the_detection_and_records_both(self) -> None:
        record = seg.fit_regions(make_dump(*box_mesh()), spec(regime="scan"))
        self.assertEqual("scan", record["regime"]["regime"])
        self.assertEqual("tessellation", record["regime"]["detected"])
        self.assertTrue(record["regime"]["overridden"])

    def test_a_regime_outside_the_vocabulary_is_refused_at_spec_load(self) -> None:
        with self.assertRaises(seg.SegmentationSpecError):
            spec(regime="exact")

    def test_coplanar_facets_from_different_vertex_triples_still_read_as_exact(self) -> None:
        """The coplanarity test is `acos` at 1e-09 degrees, below what acos resolves.

        One ulp off a unit dot product already reads 1.2e-06 degrees, so this
        comparison is really "did the dot product round to exactly 1.0" -- and
        the question is whether facets generated from one analytic face, whose
        normals come from *different vertex triples*, do. Measured here: they do,
        every one of them, so the band between 0 and the threshold is empty and
        the regime does not turn on where inside it the line sits. A mesh that
        ever populated that band would read `scan`, which is the conservative
        side and needs every coplanar pair on the whole mesh to miss, because
        `dihedral_reads_as_bimodal` needs a single exact pair.
        """
        welded = seg.weld_dump(make_dump(*box_mesh(size=20.0, divisions=6)), 1e-09)
        dihedral = seg._dihedral_degrees(seg._build_topology(welded))
        exact = [angle for angle in dihedral if abs(angle) < seg._EXACT_COPLANAR_DEG]
        near_miss = [angle for angle in dihedral if 0.0 < angle < 1e-03]
        self.assertGreater(len(exact), 0)
        self.assertEqual([0.0], sorted(set(exact)))
        self.assertEqual([], near_miss, "coplanar facets landed inside acos's own resolution")


class FilletChainTests(unittest.TestCase):
    def _blend(self, name, index, radius, span=90.0):
        return {
            "region_hash": name,
            "triangle_indices": [index],
            "welded_triangle_indices": [index],
            "area": 1.0,
            "fit": {
                "kind": "cylinder",
                "parameters": {"radius": radius},
                "support": {"angular_span_deg": span},
            },
        }

    def _face(self, name, index):
        return {
            "region_hash": name,
            "triangle_indices": [index],
            "welded_triangle_indices": [index],
            "area": 1.0,
            "fit": {"kind": "plane", "parameters": {}},
        }

    def test_a_run_of_blends_along_one_edge_is_one_fillet_not_three(self) -> None:
        """The 298-group bucket: a round cut into fragments is still one round."""
        accepted = [
            self._face("a", 0),
            self._face("b", 1),
            self._blend("r1", 2, 2.0),
            self._blend("r2", 3, 2.01),
            self._blend("r3", 4, 1.99),
        ]

        class _Topo:
            tri_neighbours = [[2, 3, 4], [2, 3, 4], [0, 1, 3], [0, 1, 2, 4], [0, 1, 3]]

        seg._mark_fillet_candidates(accepted, _Topo(), 180.0, 0.02)
        blends = accepted[2:]
        self.assertTrue(all(r["fillet_candidate"] for r in blends))
        self.assertEqual(1, len({r["fillet"]["chain_id"] for r in blends}))
        self.assertEqual([3], sorted({r["fillet"]["chain_member_count"] for r in blends}))
        self.assertEqual(["a", "b"], blends[0]["fillet"]["between"])
        self.assertAlmostEqual(2.0, blends[0]["fillet"]["radius"], places=9)

    def test_a_chain_whose_radius_drifts_is_not_one_constant_radius_round(self) -> None:
        accepted = [
            self._face("a", 0),
            self._face("b", 1),
            self._blend("r1", 2, 2.0),
            self._blend("r2", 3, 3.0),
        ]

        class _Topo:
            tri_neighbours = [[2, 3], [2, 3], [0, 1, 3], [0, 1, 2]]

        seg._mark_fillet_candidates(accepted, _Topo(), 180.0, 0.02)
        for region in accepted[2:]:
            self.assertFalse(region["fillet_candidate"])
            self.assertFalse(region["fillet_chain"]["accepted"])
            self.assertIn("spread", region["fillet_chain"]["reason"])

    def test_a_chain_is_still_refused_without_two_accepted_primaries(self) -> None:
        accepted = [
            self._face("a", 0),
            self._blend("r1", 1, 2.0),
            self._blend("r2", 2, 2.0),
        ]

        class _Topo:
            tri_neighbours = [[1, 2], [0, 2], [0, 1]]

        seg._mark_fillet_candidates(accepted, _Topo(), 180.0, 0.02)
        for region in accepted[1:]:
            self.assertFalse(region["fillet_candidate"])
            self.assertIn("exactly two", region["fillet_chain"]["reason"])



if __name__ == "__main__":
    unittest.main()


# --------------------------------------------------------------------------
# estimator C: form error, and the two licences that read it
# --------------------------------------------------------------------------


def wavy_plate_mesh(size=12.0, divisions=96, wavelength=4.0, amplitude=0.05, noise=0.0005, seed=7):
    """Four flat-ish plates that are smooth at facet scale and wavy at feature scale.

    This is the shape the facet estimators are blind to by construction, and it
    is what a structured-light scanner actually delivers: every neighbouring pair
    of facets agrees to within the sampling noise, and the surface still departs
    from its own best-fit plane by far more than that over a feature.
    """
    rng = random.Random(seed)
    step = size / divisions
    vertices = []
    for i in range(divisions + 1):
        for j in range(divisions + 1):
            x, y = i * step, j * step
            z = amplitude * math.sin(2.0 * math.pi * x / wavelength)
            vertices.append((x + rng.gauss(0.0, noise), y + rng.gauss(0.0, noise), z + rng.gauss(0.0, noise)))
    triangles, groups = [], []
    half = divisions // 2
    for i in range(divisions):
        for j in range(divisions):
            a = i * (divisions + 1) + j
            b = a + 1
            c = (i + 1) * (divisions + 1) + j + 1
            d = (i + 1) * (divisions + 1) + j
            triangles.append((a, b, c))
            triangles.append((a, c, d))
            # Four quadrants, four face groups: a rung is only measured on
            # surfaces that span it, so the fixture has to carry more than one.
            label = (0 if i < half else 2) + (0 if j < half else 1)
            groups.extend([label, label])
    return vertices, triangles, groups


def punch(vertices, triangles, groups, drop):
    """Drop triangles by index: the mesh's own dirt, a boundary loop where they were."""
    kept = [(t, g) for i, (t, g) in enumerate(zip(triangles, groups)) if i not in drop]
    return vertices, [t for t, _ in kept], [g for _, g in kept]


class FormErrorEstimatorTests(unittest.TestCase):
    """Estimator C measures what A and B cannot, and never speaks on a tessellation."""

    def _noise_block(self, vertices, triangles, groups, **overrides):
        dump = make_dump(vertices, triangles, face_groups=groups)
        mesh = seg.weld_dump(dump, 0.0)
        topo = seg._build_topology(mesh)
        return seg._sigma_form(mesh, topo, spec(**overrides)), mesh, topo

    def test_a_wavy_surface_is_invisible_to_the_facet_estimators_and_not_to_this_one(self) -> None:
        vertices, triangles, groups = wavy_plate_mesh()
        form, mesh, topo = self._noise_block(vertices, triangles, groups, min_feature_size=1.6)
        quadric_surface, quadric = seg._local_scale_estimates(
            mesh, topo, sorted({v for i in topo.valid for v in mesh.triangles[i]})
        )
        dihedral = seg._sigma_dihedral(topo)
        # Both facet estimators sit at the sampling noise; the wave is a
        # millimetre-scale shape and neither of them works at that scale.
        self.assertLess(quadric, 0.005, quadric)
        self.assertLess(dihedral, 0.005, dihedral)
        # Estimator C sees it, and reports the scale it saw it at.
        self.assertGreater(form["sigma"], 5.0 * max(quadric, dihedral), form)
        self.assertTrue(form["scale_table"])
        self.assertEqual(0.8, form["scale_table"][0]["radius"])
        self.assertIsNone(form["unavailable_reason"])

    def test_the_ladder_grows_with_scale_and_says_how_many_surfaces_measured_each_rung(self) -> None:
        vertices, triangles, groups = wavy_plate_mesh()
        form, _mesh, _topo = self._noise_block(vertices, triangles, groups, min_feature_size=1.6)
        table = form["scale_table"]
        self.assertGreaterEqual(len(table), 2)
        for rung in table:
            # A rung nobody could measure is not reported at all.
            self.assertGreaterEqual(rung["surfaces"], seg._SIGMA_FORM_MIN_SURFACES)
        radii = [rung["radius"] for rung in table]
        self.assertEqual(sorted(radii), radii)
        self.assertLessEqual(table[0]["form_error"], table[-1]["form_error"])

    def test_the_ladder_is_read_at_a_region_s_own_extent_and_clamped_at_both_ends(self) -> None:
        table = [
            {"radius": 1.0, "form_error": 0.01, "surfaces": 9},
            {"radius": 4.0, "form_error": 0.04, "surfaces": 5},
        ]
        # Below the smallest rung: that rung, never an extrapolation into the
        # scale the facet estimators already own.
        self.assertAlmostEqual(0.01, seg._form_error_at(table, 0.5))
        # Half the extent is the patch radius the region spans.
        self.assertAlmostEqual(0.01, seg._form_error_at(table, 2.0))
        self.assertAlmostEqual(0.04, seg._form_error_at(table, 8.0))
        self.assertAlmostEqual(0.02, seg._form_error_at(table, 4.0), places=6)
        # Above the largest rung the part said nothing, so the last stands.
        self.assertAlmostEqual(0.04, seg._form_error_at(table, 400.0))
        self.assertEqual(0.0, seg._form_error_at([], 4.0))

    def test_an_exact_tessellation_reports_the_estimator_and_never_takes_it(self) -> None:
        record = seg.fit_regions(make_dump(*box_mesh()), spec())
        noise = record["noise"]
        self.assertEqual("tessellation", noise["regime"])
        # Recorded in every regime -- an absent key would read as "not measured".
        self.assertIn("sigma_form", noise)
        self.assertEqual("quadric", noise["sigma_estimator"])
        # `sigma` is the quadric estimate or the vertex-precision floor under it,
        # never the form estimator.
        self.assertEqual(max(noise["sigma_quadric"], noise["vertex_precision_floor"]), noise["sigma"])
        # And nothing downstream may read a form error on a mesh whose vertices
        # sit on the analytic surface: what a plane residual measures there is
        # the surface's own curvature, which is geometry and not error.
        self.assertNotEqual("form", noise["sigma_estimator"])
        self.assertIn("scale_table", noise["form_error"])
        # The structure gates keep the facet scale: on a tessellation what a
        # plane residual over a patch measures is the surface's own curvature.
        self.assertEqual(noise["surface_scale"], noise["structure_scale"])
        self.assertIn("no form error", noise["structure_scale_reason"])

    def test_a_dump_with_no_grouping_says_it_cannot_measure_form_rather_than_zero(self) -> None:
        vertices, triangles, _groups = wavy_plate_mesh(divisions=8)
        dump = make_dump(vertices, triangles)
        mesh = seg.weld_dump(dump, 0.0)
        form = seg._sigma_form(mesh, seg._build_topology(mesh), spec())
        self.assertEqual(0.0, form["sigma"])
        self.assertIn("face grouping", form["unavailable_reason"])

    def test_a_curved_surface_s_own_sagitta_is_geometry_and_never_a_form_error(self) -> None:
        """A plane residual over a curved patch measures the surface, not its error.

        This module already says so for a tessellated part -- and the same
        holds per surface on a scan. Four cylinders of radius 8, sampled at
        half a micron of noise: over a 3 mm patch the sagitta is 0.13 mm and
        over a 12 mm one it is 2.35 mm, so the estimator used to report a form
        error 264x and 4,700x the noise actually on the part. Pooled into the
        floor, that is licence for a wrong primitive to skip the Moran check
        and clear the held-out ratio on a part whose eligible surfaces happen
        to be curved.

        The admission test is the declared `normal_alpha_deg` -- the angle at
        which this package calls two normals the same normal -- over the
        surface's own fitted patch normals, per rung, because a surface can be
        flat at one scale and curved at the next.
        """
        vertices, triangles, groups = [], [], []
        for label, offset in enumerate((0.0, 40.0, 80.0, 120.0)):
            block, faces, _ = cylinder_mesh(
                radius=8.0, height=30.0, sides=96, stacks=40, noise=0.0005, seed=3 + label
            )
            base = len(vertices)
            vertices += [(x + offset, y, z) for x, y, z in block]
            triangles += [tuple(index + base for index in face) for face in faces]
            groups += [label] * len(faces)
        form, _mesh, _topo = self._noise_block(
            vertices, triangles, groups, min_feature_size=6.0
        )
        self.assertEqual(0.0, form["sigma"])
        self.assertEqual([], form["scale_table"])
        self.assertIn("normal_alpha_deg", form["unavailable_reason"])
        self.assertIn("about its curvature", form["unavailable_reason"])

    def test_a_flat_surface_is_still_admitted_next_to_curved_ones(self) -> None:
        # The gate must reject curvature, not the estimator: the wavy plate's
        # four groups are flat at the rung and every one of them still counts,
        # with nothing excluded.
        vertices, triangles, groups = wavy_plate_mesh()
        form, _mesh, _topo = self._noise_block(vertices, triangles, groups, min_feature_size=1.6)
        self.assertTrue(form["scale_table"])
        for rung in form["scale_table"]:
            self.assertEqual(0, rung["curved_surfaces_excluded"])
            self.assertGreaterEqual(rung["surfaces"], seg._SIGMA_FORM_MIN_SURFACES)


class LocalWindingLicenceTests(unittest.TestCase):
    """A closed mesh is not the only mesh whose winding says which side is material."""

    def test_a_closed_mesh_is_licensed_by_closure_exactly_as_it_always_was(self) -> None:
        record = seg.fit_regions(make_dump(*torus_mesh()), spec())
        orientation = record["mesh_orientation"]
        self.assertTrue(orientation["closed"])
        self.assertEqual("closed", orientation["licence"])
        self.assertEqual(0, orientation["boundary_loop_count"])
        sides = [r["orientation"]["material_side"] for r in record["regions"] if r["accepted"]]
        self.assertTrue(sides)
        self.assertTrue(all(side is not None for side in sides), sides)

    def test_dirt_costs_the_regions_that_touch_it_and_not_the_rest(self) -> None:
        vertices, triangles, groups = torus_mesh(major_steps=64, minor_steps=24)
        # Two adjacent quads removed: a small boundary loop on an otherwise
        # closed, consistently wound part -- the shape a real scan arrives in.
        punched = punch(vertices, triangles, groups, drop={0, 1, 2, 3})
        record = seg.fit_regions(
            make_dump(punched[0], punched[1], face_groups=punched[2]), spec()
        )
        orientation = record["mesh_orientation"]
        self.assertFalse(orientation["closed"])
        self.assertTrue(orientation["consistently_oriented"])
        # The new licence: not closed, and the winding is still usable.
        self.assertEqual("oriented-and-bounded", orientation["licence"])
        self.assertIn(orientation["winding"], ("outward", "inward"))
        self.assertGreater(orientation["open_cap_area"], 0.0)
        self.assertLess(orientation["cap_volume_bound"], abs(orientation["signed_volume"]))
        # And it says what it rests on. `cap_volume_bound` bounds a fan-sized
        # filling, not every surface that spans the loop -- a tube out and back
        # through the hole has arbitrary area and is bounded by nothing computed
        # from the loop. The licence assumes these boundaries are capture dirt,
        # and a reader must be able to see that assumption rather than read
        # "bounded" as "proved against any filling".
        assumption = orientation["licence_assumption"]
        self.assertIsNotNone(assumption)
        self.assertIn("arbitrarily greater area", assumption)
        self.assertIn("capture dirt", assumption)

    def test_a_closed_mesh_asserts_no_such_assumption(self) -> None:
        # Closure needs no filling at all, so there is nothing to assume and the
        # field must be absent rather than repeat an assumption that is not made.
        record = seg.fit_regions(make_dump(*torus_mesh()), spec())
        orientation = record["mesh_orientation"]
        self.assertEqual("closed", orientation["licence"])
        self.assertIsNone(orientation["licence_assumption"])

    def test_a_region_on_the_dirt_stays_null_and_names_its_distance(self) -> None:
        vertices, triangles, groups = torus_mesh(major_steps=64, minor_steps=24)
        # One group per major step, so the region that owns the hole is separable
        # from the ones that do not.
        groups = [i // (2 * 24) for i in range(len(triangles))]
        punched_v, punched_t, punched_g = punch(vertices, triangles, groups, drop={0, 1, 2, 3})
        record = seg.fit_regions(
            make_dump(punched_v, punched_t, face_groups=punched_g), spec(min_feature_size=1.0)
        )
        curved = [
            r for r in record["regions"] if r["accepted"] and r["fit"]["kind"] != "plane"
        ]
        self.assertTrue(curved, [r["fit"]["kind"] for r in record["regions"]])
        near = [r for r in curved if r["orientation"]["material_side"] is None]
        clean = [r for r in curved if r["orientation"]["material_side"] is not None]
        # Both halves must be non-empty, or this fixture is testing one branch.
        self.assertTrue(near, "no region was refused for being on the dirt")
        self.assertTrue(clean, "every region was refused; the licence is not local")
        for region in near:
            local = region["orientation"]["local_winding"]
            self.assertFalse(local["clean"])
            self.assertIsNotNone(local["nearest_dirty_distance"])
            self.assertLessEqual(local["nearest_dirty_distance"], local["margin"])
            self.assertIn("boundary or non-manifold edge", region["orientation"]["unavailable_reason"])
        for region in clean:
            self.assertTrue(region["orientation"]["local_winding"]["clean"])
            self.assertIsNone(region["orientation"]["unavailable_reason"])


class HeldOutPowerTests(unittest.TestCase):
    """Underpowered is not disproved, and the census has to be able to tell them apart."""

    def test_a_half_that_cannot_fit_is_a_skip_with_a_reason_not_a_refusal(self) -> None:
        record = seg.fit_regions(make_dump(*box_mesh(divisions=6)), spec())
        skipped = [
            r for r in record["regions"]
            if r["accepted"] and "heldout_unavailable_reason" in r["fit"]["support"]
        ]
        for region in skipped:
            # A skip never claims the gate.
            self.assertNotIn("heldout-residual", region["fit"]["support"]["checked"])
        refusals = [
            r["fit"]["rejection"] for r in record["regions"]
            if not r["accepted"] and str(r["fit"]["rejection"]).startswith("held-out")
        ]
        # The old "produced no fit, so it does not survive being asked for half
        # the evidence" refusal is gone: that sentence was a verdict about the
        # split, and it is now a skip.
        for rejection in refusals:
            self.assertNotIn("produced no fit", rejection)

    def test_the_underpowered_reason_says_it_is_about_the_split(self) -> None:
        """The gate itself, on a region whose halves cannot each carry a fit."""
        vertices, triangles, groups = cylinder_mesh(radius=8.0, height=30.0, sides=64, stacks=20)
        dump = make_dump(vertices, triangles, face_groups=groups)
        record = seg.fit_regions(dump, spec())
        region = next(r for r in record["regions"] if r["accepted"])
        mesh = seg.weld_dump(dump, 0.0)
        topo = seg._build_topology(mesh)
        fit = seg.PrimitiveFit(**{
            **{k: v for k, v in region["fit"].items() if k != "support"},
            "support": region["fit"]["support"],
        })
        # A grid whose cells are the whole part puts every point on one side of
        # the checkerboard, so there is no half to refit -- the underpowered case.
        indices = sorted({v for t in region["welded_triangle_indices"] for v in mesh.triangles[t]})
        one_cell = seg._Grid(mesh.vertices, indices, 1e6)
        one_cell.keys = {index: (0, 0, 0) for index in indices}
        held = seg._blocked_heldout(fit, indices, mesh, one_cell, spec())
        self.assertIn("underpowered", held)
        self.assertIn("points", held["underpowered"])
        self.assertNotIn("ratio", held)
