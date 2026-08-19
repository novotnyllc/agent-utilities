from __future__ import annotations

import math
import unittest

from fusion_design.mesh_fitting import (
    INTENT_KINDS,
    IntentProposal,
    PrimitiveFit,
    ProfileUnresolvable,
    SketchEntity,
    best_fit,
    classify_polyline,
    fit_face_group,
    fit_primitive,
    propose_design_intent,
    propose_nominal,
    route_kinematic_surface,
    section_mesh,
    select_fit_points,
)


# --------------------------------------------------------------------------
# synthetic meshes with known analytic answers
# --------------------------------------------------------------------------

# index = x*4 + y*2 + z over the unit cube
BOX_VERTS = [(float(x), float(y), float(z)) for x in (0, 1) for y in (0, 1) for z in (0, 1)]


def _quad(a: int, b: int, c: int, d: int) -> list[tuple[int, int, int]]:
    return [(a, b, c), (a, c, d)]


BOX_TRIS = (
    _quad(0, 1, 3, 2)  # x = 0
    + _quad(4, 6, 7, 5)  # x = 1
    + _quad(0, 4, 5, 1)  # y = 0
    + _quad(2, 3, 7, 6)  # y = 1
    + _quad(0, 2, 6, 4)  # z = 0
    + _quad(1, 5, 7, 3)  # z = 1
)

BOX_FACE_GROUPS = {
    "x0": (0, 1, 2, 3),
    "x1": (4, 5, 6, 7),
    "y0": (0, 1, 4, 5),
    "y1": (2, 3, 6, 7),
    "z0": (0, 2, 4, 6),
    "z1": (1, 3, 5, 7),
}

BOX_FACE_PLANES = {
    "x0": ((1.0, 0.0, 0.0), 0.0),
    "x1": ((1.0, 0.0, 0.0), 1.0),
    "y0": ((0.0, 1.0, 0.0), 0.0),
    "y1": ((0.0, 1.0, 0.0), 1.0),
    "z0": ((0.0, 0.0, 1.0), 0.0),
    "z1": ((0.0, 0.0, 1.0), 1.0),
}


def box_face_points(name: str) -> list[tuple[float, float, float]]:
    return [BOX_VERTS[i] for i in BOX_FACE_GROUPS[name]]


def rotation(pitch_deg: float, yaw_deg: float):
    """Rotate by ``pitch`` about x, then ``yaw`` about z."""
    p, y = math.radians(pitch_deg), math.radians(yaw_deg)
    cp, sp, cy, sy = math.cos(p), math.sin(p), math.cos(y), math.sin(y)

    def apply(v):
        x1, y1, z1 = v[0], v[1] * cp - v[2] * sp, v[1] * sp + v[2] * cp
        return (x1 * cy - y1 * sy, x1 * sy + y1 * cy, z1)

    return apply


def cylinder_points(radius, height, segments, rings, transform=None):
    points = []
    for k in range(rings):
        z = height * k / (rings - 1)
        for s in range(segments):
            theta = 2.0 * math.pi * s / segments
            p = (radius * math.cos(theta), radius * math.sin(theta), z)
            points.append(transform(p) if transform else p)
    return points


def cylinder_tube_mesh(radius, height, segments):
    """An uncapped tube: two rings of vertices, each panel split into triangles."""
    verts = []
    for z in (0.0, height):
        for s in range(segments):
            theta = 2.0 * math.pi * s / segments
            verts.append((radius * math.cos(theta), radius * math.sin(theta), z))
    tris = []
    for s in range(segments):
        n = (s + 1) % segments
        a0, a1 = s, n
        b0, b1 = segments + s, segments + n
        tris.append((a0, a1, b1))
        tris.append((a0, b1, b0))
    return verts, tris


def cone_points(radius_low, radius_high, height, segments, rings):
    points = []
    for k in range(rings):
        f = k / (rings - 1)
        z = height * f
        r = radius_low + (radius_high - radius_low) * f
        for s in range(segments):
            theta = 2.0 * math.pi * s / segments
            points.append((r * math.cos(theta), r * math.sin(theta), z))
    return points


def sphere_points(radius, centre, lat_steps=9, lon_steps=16):
    points = []
    for i in range(lat_steps):
        phi = math.radians(-80.0 + 160.0 * i / (lat_steps - 1))
        for j in range(lon_steps):
            theta = 2.0 * math.pi * j / lon_steps
            points.append(
                (
                    centre[0] + radius * math.cos(phi) * math.cos(theta),
                    centre[1] + radius * math.cos(phi) * math.sin(theta),
                    centre[2] + radius * math.sin(phi),
                )
            )
    return points


def near_flat_strip(radius=500.0, half_chord=5.0, length=20.0, across=21, along=11):
    """A shallow cylindrical patch: the classic 'fits an enormous circle' trap."""
    half_angle = math.asin(half_chord / radius)
    points = []
    for i in range(across):
        theta = -half_angle + 2.0 * half_angle * i / (across - 1)
        for k in range(along):
            points.append(
                (radius * math.sin(theta), radius * math.cos(theta) - radius, length * k / (along - 1))
            )
    return points


def flat_plate(size=10.0, steps=11):
    return [
        (size * i / (steps - 1), size * j / (steps - 1), 0.0)
        for i in range(steps)
        for j in range(steps)
    ]


def torus_points(major=10.0, minor=3.0, major_steps=24, minor_steps=16):
    points = []
    for i in range(major_steps):
        u = 2.0 * math.pi * i / major_steps
        for j in range(minor_steps):
            v = 2.0 * math.pi * j / minor_steps
            r = major + minor * math.cos(v)
            points.append((r * math.cos(u), r * math.sin(u), minor * math.sin(v)))
    return points


def cylinder_fit(axis_point, axis_direction, radius, extent=20.0) -> PrimitiveFit:
    return PrimitiveFit(
        kind="cylinder",
        accepted=True,
        rms_residual=0.0,
        relative_residual=0.0,
        extent=extent,
        parameters={
            "axis_point": axis_point,
            "axis_direction": axis_direction,
            "radius": radius,
        },
    )


# --------------------------------------------------------------------------
# 1. section extraction
# --------------------------------------------------------------------------


class SectionExtractionTests(unittest.TestCase):
    def test_box_sectioned_mid_height_is_one_closed_loop(self) -> None:
        section = section_mesh(BOX_VERTS, BOX_TRIS, (0.0, 0.0, 0.5), (0.0, 0.0, 1.0))
        self.assertEqual(len(section.polylines), 1)
        loop = section.polylines[0]
        self.assertTrue(loop.closed)
        # Four vertical-edge crossings plus the four face-diagonal crossings.
        self.assertEqual(len(loop.points), 8)
        for point in loop.points:
            self.assertAlmostEqual(point[2], 0.5, places=12)
        self.assertEqual(section.coplanar_triangles, 0)
        self.assertEqual(section.junctions, ())

    def test_box_section_classifies_into_exactly_four_lines(self) -> None:
        loop = section_mesh(BOX_VERTS, BOX_TRIS, (0.0, 0.0, 0.5), (0.0, 0.0, 1.0)).polylines[0]
        entities = classify_polyline(
            loop.points, tolerance=1e-9, closed=True, normal=(0.0, 0.0, 1.0)
        )
        self.assertEqual([e.kind for e in entities], ["line"] * 4)
        for entity in entities:
            self.assertLess(entity.residual, 1e-12)
            self.assertIsNone(entity.center)
            self.assertIsNone(entity.radius)
        perimeter = sum(
            math.dist(e.start, e.end) for e in entities
        )
        self.assertAlmostEqual(perimeter, 4.0, places=12)

    def test_coplanar_face_yields_its_boundary_and_counts_vertex_touches(self) -> None:
        section = section_mesh(BOX_VERTS, BOX_TRIS, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
        self.assertEqual(section.coplanar_triangles, 2)
        # Four side triangles touch the plane at a single vertex and emit nothing.
        self.assertEqual(section.vertex_touches, 4)
        self.assertEqual(len(section.polylines), 1)
        loop = section.polylines[0]
        self.assertTrue(loop.closed)
        self.assertEqual(len(loop.points), 4)
        self.assertEqual({p[2] for p in loop.points}, {0.0})
        self.assertEqual(
            sorted((p[0], p[1]) for p in loop.points),
            [(0.0, 0.0), (0.0, 1.0), (1.0, 0.0), (1.0, 1.0)],
        )

    def test_single_vertex_touch_produces_no_segment(self) -> None:
        verts = [(0.0, 0.0, 0.0), (1.0, 0.0, 1.0), (0.0, 1.0, 1.0)]
        section = section_mesh(verts, [(0, 1, 2)], (0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
        self.assertEqual(section.polylines, ())
        self.assertEqual(section.vertex_touches, 1)
        self.assertEqual(section.coplanar_triangles, 0)

    def test_open_polyline_from_a_single_crossing_triangle(self) -> None:
        verts = [(0.0, 0.0, -1.0), (2.0, 0.0, -1.0), (1.0, 0.0, 1.0)]
        section = section_mesh(verts, [(0, 1, 2)], (0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
        self.assertEqual(len(section.polylines), 1)
        line = section.polylines[0]
        self.assertFalse(line.closed)
        self.assertEqual(len(line.points), 2)
        self.assertEqual(sorted(p[0] for p in line.points), [0.5, 1.5])

    def test_three_way_junction_stops_chaining_and_is_reported(self) -> None:
        verts = [
            (0.0, 0.0, -1.0),
            (0.0, 0.0, 1.0),
            (1.0, 0.0, 0.0),
            (-0.5, 0.866, 0.0),
            (-0.5, -0.866, 0.0),
        ]
        tris = [(0, 1, 2), (0, 1, 3), (0, 1, 4)]
        section = section_mesh(verts, tris, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
        self.assertEqual(len(section.junctions), 1)
        self.assertEqual(section.junctions[0], (0.0, 0.0, 0.0))
        # Three branches, none of them guessed into a continuation.
        self.assertEqual(len(section.polylines), 3)
        for run in section.polylines:
            self.assertFalse(run.closed)
            self.assertEqual(len(run.points), 2)

    def test_cylinder_section_is_a_polygon_at_tight_tolerance_and_a_circle_at_loose(self) -> None:
        verts, tris = cylinder_tube_mesh(5.0, 20.0, 24)
        section = section_mesh(verts, tris, (0.0, 0.0, 10.0), (0.0, 0.0, 1.0))
        self.assertEqual(len(section.polylines), 1)
        loop = section.polylines[0]
        self.assertTrue(loop.closed)
        self.assertEqual(len(loop.points), 48)

        # 24 facets, not 48 entities: the crossing on each panel's diagonal is
        # exactly the midpoint of the chord between its two neighbours, so it is
        # absorbed into a line rather than starting a new one.
        tight = classify_polyline(loop.points, tolerance=1e-9, closed=True, normal=(0.0, 0.0, 1.0))
        self.assertEqual({e.kind for e in tight}, {"line"})
        self.assertEqual(len(tight), 24)
        self.assertEqual({e.point_count for e in tight}, {3})

        loose = classify_polyline(loop.points, tolerance=0.06, closed=True, normal=(0.0, 0.0, 1.0))
        self.assertEqual([e.kind for e in loose], ["circle"])
        self.assertAlmostEqual(loose[0].radius, 5.0, delta=0.05)
        self.assertGreater(loose[0].residual, 0.0)
        self.assertIsNotNone(loose[0].mid)


class SectionValidationTests(unittest.TestCase):
    def test_degenerate_plane_normal_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            section_mesh(BOX_VERTS, BOX_TRIS, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))

    def test_non_positive_tolerance_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            section_mesh(BOX_VERTS, BOX_TRIS, (0.0, 0.0, 0.5), (0.0, 0.0, 1.0), tolerance=0.0)

    def test_out_of_range_vertex_index_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            section_mesh(BOX_VERTS, [(0, 1, 99)], (0.0, 0.0, 0.5), (0.0, 0.0, 1.0))

    def test_repeated_vertex_index_is_not_a_triangle(self) -> None:
        with self.assertRaises(ValueError):
            section_mesh(BOX_VERTS, [(0, 1, 1)], (0.0, 0.0, 0.5), (0.0, 0.0, 1.0))

    def test_non_finite_coordinate_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            section_mesh(
                [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, float("nan"), 0.0)],
                [(0, 1, 2)],
                (0.0, 0.0, 0.5),
                (0.0, 0.0, 1.0),
            )

    def test_unhashable_triangle_payload_is_a_value_error(self) -> None:
        with self.assertRaises(ValueError):
            section_mesh(BOX_VERTS, [{"a": 1}], (0.0, 0.0, 0.5), (0.0, 0.0, 1.0))


# --------------------------------------------------------------------------
# 2. segment classification
# --------------------------------------------------------------------------


class SegmentClassificationTests(unittest.TestCase):
    def test_open_semicircle_is_one_arc_with_centre_and_radius(self) -> None:
        points = [
            (4.0 * math.cos(math.pi * k / 20.0), 4.0 * math.sin(math.pi * k / 20.0), 0.0)
            for k in range(21)
        ]
        entities = classify_polyline(points, tolerance=1e-9, normal=(0.0, 0.0, 1.0))
        self.assertEqual([e.kind for e in entities], ["arc"])
        arc = entities[0]
        self.assertAlmostEqual(arc.radius, 4.0, places=9)
        for axis in range(3):
            self.assertAlmostEqual(arc.center[axis], 0.0, places=9)
        self.assertEqual(arc.start, points[0])
        self.assertEqual(arc.end, points[-1])
        self.assertIsNotNone(arc.mid)
        self.assertLess(arc.residual, 1e-9)

    def test_a_straight_run_then_an_arc_is_split_into_a_line_and_an_arc(self) -> None:
        straight = [(-10.0 + k, 4.0, 0.0) for k in range(11)]
        arc = [
            (4.0 * math.sin(math.pi * k / 40.0), 4.0 * math.cos(math.pi * k / 40.0), 0.0)
            for k in range(1, 21)
        ]
        entities = classify_polyline(straight + arc, tolerance=1e-9, normal=(0.0, 0.0, 1.0))
        self.assertEqual([e.kind for e in entities], ["line", "arc"])
        self.assertAlmostEqual(entities[1].radius, 4.0, places=9)
        self.assertEqual(entities[0].end, entities[1].start)

    def test_a_straight_polyline_is_never_promoted_to_a_huge_arc(self) -> None:
        points = [(float(k), 0.0, 0.0) for k in range(12)]
        entities = classify_polyline(points, tolerance=1e-6, normal=(0.0, 0.0, 1.0))
        self.assertEqual([e.kind for e in entities], ["line"])
        self.assertIsNone(entities[0].radius)

    def test_classification_refuses_a_non_positive_tolerance(self) -> None:
        with self.assertRaises(ValueError):
            classify_polyline([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], tolerance=-1.0)

    def test_a_closed_polyline_needs_three_points(self) -> None:
        with self.assertRaises(ValueError):
            classify_polyline([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], tolerance=1e-6, closed=True)


# --------------------------------------------------------------------------
# 3. primitive fitting
# --------------------------------------------------------------------------


class PlaneFittingTests(unittest.TestCase):
    def test_unit_box_yields_six_planes_with_exact_normals_and_offsets(self) -> None:
        for name, (normal, offset) in BOX_FACE_PLANES.items():
            with self.subTest(face=name):
                fit = fit_primitive(box_face_points(name), "plane")
                self.assertTrue(fit.accepted, fit.rejection)
                for axis in range(3):
                    self.assertAlmostEqual(fit.parameters["normal"][axis], normal[axis], places=12)
                self.assertAlmostEqual(fit.parameters["offset"], offset, places=12)
                self.assertAlmostEqual(fit.rms_residual, 0.0, places=12)

    def test_a_flat_plate_is_a_plane_and_nothing_curved(self) -> None:
        points = flat_plate()
        chosen = best_fit(points)
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.kind, "plane")
        for kind in ("cylinder", "cone", "sphere"):
            with self.subTest(kind=kind):
                self.assertFalse(fit_primitive(points, kind).accepted)

    def test_a_flat_square_face_is_not_reported_as_a_cylinder(self) -> None:
        fit = fit_primitive(box_face_points("x0"), "cylinder")
        self.assertFalse(fit.accepted)
        self.assertIn("plane already explains", fit.rejection)


class CylinderFittingTests(unittest.TestCase):
    def test_axis_aligned_cylinder_recovers_axis_and_radius(self) -> None:
        fit = fit_primitive(cylinder_points(5.0, 20.0, 32, 9), "cylinder")
        self.assertTrue(fit.accepted, fit.rejection)
        self.assertAlmostEqual(fit.parameters["radius"], 5.0, places=9)
        direction = fit.parameters["axis_direction"]
        self.assertAlmostEqual(abs(direction[2]), 1.0, places=9)
        self.assertAlmostEqual(direction[0], 0.0, places=9)
        self.assertAlmostEqual(direction[1], 0.0, places=9)
        for axis in range(2):
            self.assertAlmostEqual(fit.parameters["axis_point"][axis], 0.0, places=9)
        self.assertLess(fit.relative_residual, 1e-12)

    def test_off_axis_cylinder_is_fitted_correctly_not_silently_wrong(self) -> None:
        rotate = rotation(30.0, 20.0)
        points = cylinder_points(5.0, 20.0, 32, 9, transform=rotate)
        expected = rotate((0.0, 0.0, 1.0))
        fit = fit_primitive(points, "cylinder")
        self.assertTrue(fit.accepted, fit.rejection)
        self.assertAlmostEqual(fit.parameters["radius"], 5.0, places=8)
        direction = fit.parameters["axis_direction"]
        alignment = abs(sum(direction[i] * expected[i] for i in range(3)))
        self.assertAlmostEqual(alignment, 1.0, places=9)
        # The axis line must pass through the true axis, not merely be parallel.
        anchor = fit.parameters["axis_point"]
        along = sum(anchor[i] * expected[i] for i in range(3))
        perpendicular = math.dist(anchor, tuple(along * expected[i] for i in range(3)))
        self.assertLess(perpendicular, 1e-8)

    def test_a_near_flat_strip_is_rejected_rather_than_fitted_as_a_huge_circle(self) -> None:
        # Ungated, this fits a radius-500 cylinder centred 500 away with a
        # relative residual around 1e-15: numerically perfect and useless as
        # design intent. Only the guards below stand between that and a report.
        points = near_flat_strip()
        fit = fit_primitive(points, "cylinder")
        self.assertFalse(fit.accepted)
        self.assertIn("exceeds", fit.rejection)
        self.assertIn("sampled extent", fit.rejection)
        self.assertEqual(fit.parameters, {})
        # The honest answer for a near-flat strip is a plane.
        chosen = best_fit(points)
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.kind, "plane")

    def test_a_wider_radius_ratio_still_refuses_on_the_out_of_bounds_axis(self) -> None:
        fit = fit_primitive(near_flat_strip(), "cylinder", max_radius_ratio=1000.0)
        self.assertFalse(fit.accepted)
        self.assertIn("outside the part bounds", fit.rejection)

    def test_a_wider_radius_and_bounds_margin_still_refuses_on_planarity(self) -> None:
        fit = fit_primitive(
            near_flat_strip(), "cylinder", max_radius_ratio=1000.0, bounds_margin_ratio=1000.0
        )
        self.assertFalse(fit.accepted)
        self.assertIn("plane already explains", fit.rejection)


class SphereFittingTests(unittest.TestCase):
    def test_sphere_recovers_centre_and_radius(self) -> None:
        fit = fit_primitive(sphere_points(7.0, (1.0, 2.0, 3.0)), "sphere")
        self.assertTrue(fit.accepted, fit.rejection)
        self.assertAlmostEqual(fit.parameters["radius"], 7.0, places=9)
        for axis, expected in enumerate((1.0, 2.0, 3.0)):
            self.assertAlmostEqual(fit.parameters["center"][axis], expected, places=9)
        self.assertLess(fit.relative_residual, 1e-12)

    def test_sphere_is_the_best_fit_for_sphere_points(self) -> None:
        chosen = best_fit(sphere_points(7.0, (1.0, 2.0, 3.0)))
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.kind, "sphere")


class ConeFittingTests(unittest.TestCase):
    def test_cone_recovers_apex_and_half_angle(self) -> None:
        points = cone_points(10.0, 2.0, 30.0, 32, 9)
        fit = fit_primitive(points, "cone")
        self.assertTrue(fit.accepted, fit.rejection)
        self.assertAlmostEqual(
            fit.parameters["half_angle_deg"], math.degrees(math.atan(8.0 / 30.0)), places=8
        )
        apex = fit.parameters["apex"]
        self.assertAlmostEqual(apex[0], 0.0, places=8)
        self.assertAlmostEqual(apex[1], 0.0, places=8)
        self.assertAlmostEqual(apex[2], 37.5, places=7)
        self.assertLess(fit.relative_residual, 1e-9)
        # The axis points away from the apex, in the direction the radius grows,
        # so apex + t * axis for t > 0 walks onto the modelled nappe.
        direction = fit.parameters["axis_direction"]
        self.assertAlmostEqual(direction[2], -1.0, places=9)
        walked = tuple(apex[i] + 7.5 * direction[i] for i in range(3))
        self.assertAlmostEqual(walked[2], 30.0, places=7)
        self.assertAlmostEqual(
            7.5 * math.tan(math.radians(fit.parameters["half_angle_deg"])), 2.0, places=7
        )

    def test_a_cylinder_is_refused_as_a_cone_rather_than_given_a_far_apex(self) -> None:
        fit = fit_primitive(cylinder_points(5.0, 20.0, 32, 9), "cone")
        self.assertFalse(fit.accepted)
        self.assertIn("cylinder, not a cone", fit.rejection)
        self.assertEqual(fit.parameters, {})


class FaceGroupSelectionTests(unittest.TestCase):
    def test_fit_face_group_keeps_rejections_with_their_reasons(self) -> None:
        fits = fit_face_group(flat_plate())
        self.assertEqual({f.kind for f in fits}, {"plane", "cylinder", "cone", "sphere"})
        self.assertEqual(fits[0].kind, "plane")
        for fit in fits[1:]:
            self.assertFalse(fit.accepted)
            self.assertTrue(fit.rejection)

    def test_an_unfittable_group_is_reported_absent_not_guessed(self) -> None:
        points = torus_points()
        self.assertIsNone(best_fit(points))
        for fit in fit_face_group(points):
            self.assertFalse(fit.accepted)
            self.assertTrue(fit.rejection)

    def test_a_dict_where_a_kind_belongs_is_a_value_error_not_a_type_error(self) -> None:
        with self.assertRaises(ValueError):
            fit_primitive(flat_plate(), {"kind": "plane"})
        with self.assertRaises(ValueError):
            fit_face_group(flat_plate(), kinds=[{"kind": "plane"}])

    def test_fitting_refuses_bad_gates_and_thin_point_sets(self) -> None:
        with self.assertRaises(ValueError):
            fit_primitive(flat_plate(), "plane", max_relative_residual=0.0)
        with self.assertRaises(ValueError):
            fit_primitive(flat_plate(), "plane", bounds_margin_ratio=-1.0)
        with self.assertRaises(ValueError):
            fit_primitive([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], "plane")

    def test_a_zero_extent_group_is_rejected_with_a_reason(self) -> None:
        fit = fit_primitive([(1.0, 1.0, 1.0)] * 5, "plane")
        self.assertFalse(fit.accepted)
        self.assertIn("zero extent", fit.rejection)

    def test_a_sphere_centre_outside_the_part_bounds_is_rejected(self) -> None:
        # A tiny cap of a large sphere: the fit is fine, the centre is nowhere near the part.
        cap = [
            (
                200.0 * math.cos(0.01 * i) * math.cos(0.01 * j),
                200.0 * math.cos(0.01 * i) * math.sin(0.01 * j),
                200.0 * math.sin(0.01 * i),
            )
            for i in range(-6, 7)
            for j in range(-6, 7)
        ]
        fit = fit_primitive(cap, "sphere", max_radius_ratio=1e9)
        self.assertFalse(fit.accepted)
        self.assertIn("outside the part bounds", fit.rejection)


# --------------------------------------------------------------------------
# 4. design-intent proposals
# --------------------------------------------------------------------------


class DesignIntentTests(unittest.TestCase):
    def test_near_coaxial_pair_proposes_with_its_deviation_and_mutates_nothing(self) -> None:
        tilt = math.radians(0.3)
        lower = cylinder_fit((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 5.0)
        upper = cylinder_fit(
            (0.02, 0.0, 10.0), (math.sin(tilt), 0.0, math.cos(tilt)), 5.0
        )
        proposals = propose_design_intent({"bore_lower": lower, "bore_upper": upper})
        coaxial = [p for p in proposals if p.kind == "coaxial"]
        self.assertEqual(len(coaxial), 1)
        proposal = coaxial[0]
        self.assertEqual(proposal.subjects, ("bore_lower", "bore_upper"))
        self.assertAlmostEqual(proposal.deviation, 0.02, places=12)
        self.assertEqual(proposal.deviation_unit, "length")
        self.assertAlmostEqual(proposal.detail["axis_angle_deg"], 0.3, places=9)
        self.assertIn("Confirm", proposal.statement + " Confirm")
        # Nothing snapped: the fitted values are exactly as measured.
        self.assertEqual(lower.parameters["axis_direction"], (0.0, 0.0, 1.0))
        self.assertEqual(upper.parameters["axis_point"], (0.02, 0.0, 10.0))
        self.assertAlmostEqual(upper.parameters["axis_direction"][0], math.sin(tilt), places=15)
        # A coaxial pair is not also reported as merely parallel.
        self.assertEqual([p for p in proposals if p.kind == "parallel"], [])

    def test_parallel_axes_too_far_apart_are_parallel_and_symmetric_not_coaxial(self) -> None:
        left = cylinder_fit((-15.0, 0.0, 0.0), (0.0, 0.0, 1.0), 2.5)
        right = cylinder_fit((15.0, 0.0, 0.0), (0.0, 0.0, 1.0), 2.4)
        proposals = propose_design_intent({"hole_left": left, "hole_right": right})
        kinds = sorted(p.kind for p in proposals)
        self.assertEqual(kinds, ["parallel", "symmetric"])
        symmetric = next(p for p in proposals if p.kind == "symmetric")
        self.assertAlmostEqual(symmetric.deviation, 0.1, places=12)
        self.assertAlmostEqual(symmetric.detail["axis_separation"], 30.0, places=12)
        self.assertAlmostEqual(symmetric.proposed_value["offset"], 0.0, places=12)

    def test_box_faces_propose_three_parallel_three_symmetric_and_twelve_perpendicular(self) -> None:
        fits = {name: fit_primitive(box_face_points(name), "plane") for name in BOX_FACE_GROUPS}
        proposals = propose_design_intent(fits, angle_tolerance_deg=0.001)
        counts: dict[str, int] = {}
        for proposal in proposals:
            counts[proposal.kind] = counts.get(proposal.kind, 0) + 1
        self.assertEqual(counts, {"parallel": 3, "symmetric": 3, "perpendicular": 12})
        mirror = next(p for p in proposals if p.kind == "symmetric")
        self.assertAlmostEqual(mirror.proposed_value["offset"], 0.5, places=12)
        self.assertAlmostEqual(mirror.detail["separation"], 1.0, places=12)

    def test_a_rejected_fit_is_not_a_basis_for_design_intent(self) -> None:
        rejected = fit_primitive(flat_plate(), "cylinder")
        self.assertFalse(rejected.accepted)
        with self.assertRaises(ValueError):
            propose_design_intent({"strip": rejected})

    def test_intent_refuses_malformed_feature_maps(self) -> None:
        good = cylinder_fit((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 5.0)
        with self.assertRaises(ValueError):
            propose_design_intent([("bore", good)])
        with self.assertRaises(ValueError):
            propose_design_intent({"": good})
        with self.assertRaises(ValueError):
            propose_design_intent({"bore": {"radius": 5.0}})
        with self.assertRaises(ValueError):
            propose_design_intent({"bore": good}, angle_tolerance_deg=0.0)


class NominalProposalTests(unittest.TestCase):
    def test_ten_point_zero_three_proposes_ten_carrying_the_deviation(self) -> None:
        proposal = propose_nominal("bore diameter", 10.03, tolerance=0.05)
        self.assertIsInstance(proposal, IntentProposal)
        self.assertEqual(proposal.kind, "nominal")
        self.assertAlmostEqual(proposal.proposed_value, 10.0, places=12)
        self.assertAlmostEqual(proposal.deviation, 0.03, places=12)
        self.assertAlmostEqual(proposal.detail["measured"], 10.03, places=12)
        self.assertEqual(proposal.detail["step"], 1.0)

    def test_a_value_already_nominal_proposes_nothing(self) -> None:
        self.assertIsNone(propose_nominal("bore diameter", 10.0, tolerance=0.05))

    def test_a_value_beyond_every_step_proposes_nothing(self) -> None:
        self.assertIsNone(propose_nominal("bore diameter", 10.4, tolerance=0.05))

    def test_a_coarse_tolerance_prefers_the_coarsest_step(self) -> None:
        proposal = propose_nominal("bore diameter", 10.4, tolerance=0.5)
        self.assertAlmostEqual(proposal.proposed_value, 10.0, places=12)
        self.assertEqual(proposal.detail["step"], 1.0)

    def test_nominal_diameters_ride_along_with_design_intent(self) -> None:
        bore = cylinder_fit((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 5.015)
        proposals = propose_design_intent({"bore": bore}, nominal_tolerance=0.05)
        self.assertEqual([p.kind for p in proposals], ["nominal"])
        self.assertAlmostEqual(proposals[0].proposed_value, 10.0, places=12)
        self.assertAlmostEqual(proposals[0].deviation, 0.03, places=9)
        # The fit itself is untouched.
        self.assertEqual(bore.parameters["radius"], 5.015)

    def test_nominal_refuses_malformed_arguments(self) -> None:
        with self.assertRaises(ValueError):
            propose_nominal("", 10.03, tolerance=0.05)
        with self.assertRaises(ValueError):
            propose_nominal("bore", float("nan"), tolerance=0.05)
        with self.assertRaises(ValueError):
            propose_nominal("bore", 10.03, tolerance=0.0)
        with self.assertRaises(ValueError):
            propose_nominal("bore", 10.03, tolerance=0.05, steps=(0.0,))


class ClosedVocabularyTests(unittest.TestCase):
    """Every result kind is checked against its closed set, unhashables included."""

    def test_result_kinds_are_closed_sets(self) -> None:
        cases = (
            (PrimitiveFit, {"kind": "cuboid", "accepted": True, "rms_residual": 0.0,
                            "relative_residual": 0.0, "extent": 1.0}),
            (SketchEntity, {"kind": "spline", "start": (0.0, 0.0, 0.0), "end": (1.0, 0.0, 0.0),
                            "residual": 0.0, "point_count": 2}),
            (IntentProposal, {"kind": "concentric", "subjects": ("a",), "statement": "x",
                              "deviation": 0.0, "deviation_unit": "deg"}),
        )
        for cls, kwargs in cases:
            with self.subTest(cls=cls.__name__):
                with self.assertRaises(ValueError):
                    cls(**kwargs)
                unhashable = dict(kwargs, kind={"kind": "plane"})
                with self.assertRaises(ValueError):
                    cls(**unhashable)


class SerialisationTests(unittest.TestCase):
    def test_every_result_round_trips_to_plain_json_types(self) -> None:
        section = section_mesh(BOX_VERTS, BOX_TRIS, (0.0, 0.0, 0.5), (0.0, 0.0, 1.0))
        payload = section.to_dict()
        self.assertEqual(payload["coplanar_triangles"], 0)
        self.assertIsInstance(payload["polylines"][0]["points"][0], list)

        entity = classify_polyline(
            section.polylines[0].points, tolerance=1e-9, closed=True, normal=(0.0, 0.0, 1.0)
        )[0]
        self.assertEqual(entity.to_dict()["kind"], "line")
        self.assertNotIn("center", entity.to_dict())

        fit = fit_primitive(cylinder_points(5.0, 20.0, 32, 9), "cylinder")
        as_dict = fit.to_dict()
        self.assertEqual(as_dict["kind"], "cylinder")
        self.assertIsInstance(as_dict["parameters"]["axis_direction"], list)
        self.assertNotIn("rejection", as_dict)

        rejected = fit_primitive(near_flat_strip(), "cylinder").to_dict()
        self.assertIn("rejection", rejected)

        proposal = propose_nominal("bore diameter", 10.03, tolerance=0.05).to_dict()
        self.assertEqual(proposal["kind"], "nominal")
        self.assertEqual(proposal["subjects"], ["bore diameter"])


# --------------------------------------------------------------------------
# 5. tangency, equal radius, and the widened symmetry proposal
# --------------------------------------------------------------------------


def plane_fit(normal, point, extent=20.0) -> PrimitiveFit:
    offset = sum(n * p for n, p in zip(normal, point))
    return PrimitiveFit(
        kind="plane",
        accepted=True,
        rms_residual=0.0,
        relative_residual=0.0,
        extent=extent,
        parameters={"normal": normal, "offset": offset, "point_on_plane": point},
    )


def cone_fit(apex, axis_direction, half_angle_deg, extent=20.0) -> PrimitiveFit:
    return PrimitiveFit(
        kind="cone",
        accepted=True,
        rms_residual=0.0,
        relative_residual=0.0,
        extent=extent,
        parameters={
            "apex": apex,
            "axis_direction": axis_direction,
            "half_angle_deg": half_angle_deg,
            "reference_radius": 2.0,
        },
    )


def sphere_fit(centre, radius, extent=20.0) -> PrimitiveFit:
    return PrimitiveFit(
        kind="sphere",
        accepted=True,
        rms_residual=0.0,
        relative_residual=0.0,
        extent=extent,
        parameters={"center": centre, "radius": radius},
    )


class TangentProposalTests(unittest.TestCase):
    def test_a_cylinder_resting_on_a_plane_proposes_tangency_with_its_deviation(self) -> None:
        wall = plane_fit((1.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        boss = cylinder_fit((5.02, 0.0, 0.0), (0.0, 0.0, 1.0), 5.0)
        proposals = propose_design_intent(
            {"wall": wall, "boss": boss}, tangent_tolerance=0.1
        )
        tangent = [p for p in proposals if p.kind == "tangent"]
        self.assertEqual(len(tangent), 1)
        self.assertAlmostEqual(tangent[0].deviation, 0.02, places=12)
        self.assertEqual(tangent[0].deviation_unit, "length")
        self.assertAlmostEqual(tangent[0].detail["axis_to_plane_distance"], 5.02, places=12)

    def test_without_a_declared_tolerance_nothing_is_proposed(self) -> None:
        wall = plane_fit((1.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        boss = cylinder_fit((5.0, 0.0, 0.0), (0.0, 0.0, 1.0), 5.0)
        proposals = propose_design_intent({"wall": wall, "boss": boss})
        self.assertEqual([p for p in proposals if p.kind == "tangent"], [])

    def test_a_cylinder_crossing_a_plane_is_left_unproposed(self) -> None:
        # The axis is perpendicular to the plane, so it passes through it; the
        # axis-to-plane distance is not a clearance and means nothing here.
        floor = plane_fit((0.0, 0.0, 1.0), (0.0, 0.0, 0.0))
        boss = cylinder_fit((0.0, 0.0, 5.0), (0.0, 0.0, 1.0), 5.0)
        proposals = propose_design_intent(
            {"floor": floor, "boss": boss}, tangent_tolerance=0.1
        )
        self.assertEqual([p for p in proposals if p.kind == "tangent"], [])

    def test_two_cylinders_touching_externally_propose_tangency(self) -> None:
        left = cylinder_fit((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 3.0)
        right = cylinder_fit((7.99, 0.0, 0.0), (0.0, 0.0, 1.0), 5.0)
        proposals = propose_design_intent(
            {"left": left, "right": right}, tangent_tolerance=0.1
        )
        tangent = [p for p in proposals if p.kind == "tangent"]
        self.assertEqual(len(tangent), 1)
        self.assertEqual(tangent[0].proposed_value, "external")
        self.assertAlmostEqual(tangent[0].deviation, 0.01, places=12)

    def test_coincident_axes_are_coaxial_and_never_internally_tangent(self) -> None:
        inner = cylinder_fit((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 3.0)
        outer = cylinder_fit((0.0, 0.0, 4.0), (0.0, 0.0, 1.0), 3.0)
        proposals = propose_design_intent(
            {"inner": inner, "outer": outer}, tangent_tolerance=0.1
        )
        self.assertEqual([p for p in proposals if p.kind == "tangent"], [])
        self.assertEqual(len([p for p in proposals if p.kind == "coaxial"]), 1)


class EqualRadiusProposalTests(unittest.TestCase):
    def test_four_near_equal_bores_propose_every_pair(self) -> None:
        bores = {
            f"bore_{i}": cylinder_fit((10.0 * i, 0.0, 0.0), (0.0, 0.0, 1.0), radius)
            for i, radius in enumerate((2.5, 2.503, 2.498, 2.502))
        }
        proposals = propose_design_intent(bores, equal_radius_tolerance=0.01)
        equal = [p for p in proposals if p.kind == "equal_radius"]
        self.assertEqual(len(equal), 6)
        for proposal in equal:
            self.assertLessEqual(proposal.deviation, 0.01)
            self.assertEqual(proposal.deviation_unit, "length")
            self.assertAlmostEqual(
                proposal.proposed_value,
                (proposal.detail["radius_a"] + proposal.detail["radius_b"]) / 2.0,
            )

    def test_a_radius_beyond_the_tolerance_is_not_proposed(self) -> None:
        proposals = propose_design_intent(
            {
                "a": cylinder_fit((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 2.5),
                "b": cylinder_fit((10.0, 0.0, 0.0), (0.0, 0.0, 1.0), 4.0),
            },
            equal_radius_tolerance=0.01,
        )
        self.assertEqual([p for p in proposals if p.kind == "equal_radius"], [])

    def test_spheres_carry_a_radius_and_reach_the_proposal(self) -> None:
        proposals = propose_design_intent(
            {"ball_a": sphere_fit((0.0, 0.0, 0.0), 4.0), "ball_b": sphere_fit((20.0, 0.0, 0.0), 4.002)},
            equal_radius_tolerance=0.01,
        )
        self.assertEqual(len([p for p in proposals if p.kind == "equal_radius"]), 1)

    def test_a_cone_reference_radius_is_not_treated_as_a_diameter(self) -> None:
        # reference_radius is the radius at whichever axis point the search
        # landed on, so equating two of them would compare two arbitrary
        # stations. Left unproposed rather than approximated.
        proposals = propose_design_intent(
            {
                "csk_a": cone_fit((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 45.0),
                "csk_b": cone_fit((20.0, 0.0, 0.0), (0.0, 0.0, 1.0), 45.0),
            },
            equal_radius_tolerance=0.01,
        )
        self.assertEqual([p for p in proposals if p.kind == "equal_radius"], [])


class WidenedSymmetryTests(unittest.TestCase):
    def test_two_parallel_axis_cones_now_propose_a_mirror_plane(self) -> None:
        proposals = propose_design_intent(
            {
                "csk_left": cone_fit((-15.0, 0.0, 0.0), (0.0, 0.0, 1.0), 45.0),
                "csk_right": cone_fit((15.0, 0.0, 0.0), (0.0, 0.0, 1.0), 45.2),
            }
        )
        symmetric = [p for p in proposals if p.kind == "symmetric"]
        self.assertEqual(len(symmetric), 1)
        self.assertEqual(symmetric[0].deviation_unit, "deg")
        self.assertAlmostEqual(symmetric[0].deviation, 0.2, places=9)
        self.assertAlmostEqual(symmetric[0].proposed_value["offset"], 0.0, places=12)

    def test_a_cylinder_and_a_cone_are_not_each_others_mirror_image(self) -> None:
        proposals = propose_design_intent(
            {
                "bore": cylinder_fit((-15.0, 0.0, 0.0), (0.0, 0.0, 1.0), 2.5),
                "csk": cone_fit((15.0, 0.0, 0.0), (0.0, 0.0, 1.0), 45.0),
            }
        )
        self.assertEqual([p for p in proposals if p.kind == "symmetric"], [])

    def test_two_spheres_are_deliberately_left_unproposed(self) -> None:
        # Any two spheres are mirror-symmetric about the bisector of their
        # centres, so the proposal would carry no evidence at all.
        proposals = propose_design_intent(
            {"ball_a": sphere_fit((-15.0, 0.0, 0.0), 4.0), "ball_b": sphere_fit((15.0, 0.0, 0.0), 4.0)},
            equal_radius_tolerance=0.01,
        )
        self.assertEqual([p for p in proposals if p.kind == "symmetric"], [])


class IntentVocabularyTests(unittest.TestCase):
    def test_the_closed_set_now_covers_all_seven_kinds(self) -> None:
        self.assertEqual(
            INTENT_KINDS,
            {
                "coaxial",
                "parallel",
                "perpendicular",
                "symmetric",
                "tangent",
                "equal_radius",
                "nominal",
            },
        )

    def test_a_kind_outside_the_set_is_still_refused(self) -> None:
        with self.assertRaises(ValueError):
            IntentProposal(
                kind="concentric-ish",
                subjects=("a", "b"),
                statement="",
                deviation=0.0,
                deviation_unit="deg",
            )


# --------------------------------------------------------------------------
# the kinematic router and the spline entity
#
# Both tested on their *judgement*, not on their arithmetic: which verdict a
# region deserves, and when a span is refused rather than approximated. The
# geometry either produces those verdicts or the gates are wrong.
# --------------------------------------------------------------------------


def _unitise(vector):
    length = math.sqrt(sum(c * c for c in vector))
    return tuple(c / length for c in vector)


def extruded_cam_samples(n=40, m=12, height=30.0):
    """An irregular outline swept along z: the rung-1 case, prismatic but unfittable."""
    points, normals = [], []
    for k in range(n):
        t = 2.0 * math.pi * k / n
        r = 10.0 + 2.0 * math.cos(2.0 * t) + 1.5 * math.sin(3.0 * t)
        dr = -4.0 * math.sin(2.0 * t) + 4.5 * math.cos(3.0 * t)
        x, y = r * math.cos(t), r * math.sin(t)
        tx = dr * math.cos(t) - r * math.sin(t)
        ty = dr * math.sin(t) + r * math.cos(t)
        normal = _unitise((ty, -tx, 0.0))
        for j in range(m):
            points.append((x, y, height * j / m))
            normals.append(normal)
    return points, normals


def revolved_samples(n=40, m=12):
    points, normals = [], []
    for k in range(n):
        t = 2.0 * math.pi * k / n
        for j in range(m):
            z = j * 2.0
            radius = 8.0 + 0.5 * z - 0.01 * z * z
            slope = 0.5 - 0.02 * z
            nr, nz = _unitise((1.0, -slope))[0], _unitise((1.0, -slope))[1]
            points.append((radius * math.cos(t), radius * math.sin(t), z))
            normals.append((nr * math.cos(t), nr * math.sin(t), nz))
    return points, normals


def helicoid_samples(n=140, pitch=4.0, base=2.0, rungs=14):
    points, normals = [], []
    for k in range(n):
        s = k * 0.06
        for j in range(rungs):
            u = 1.0 + j
            points.append(((base + u) * math.cos(s), (base + u) * math.sin(s), pitch * s))
            normals.append(_unitise((pitch * math.sin(s), -pitch * math.cos(s), base + u)))
    return points, normals


def plane_samples(n=20):
    points = [(i * 1.0, j * 1.0, 0.0) for i in range(n) for j in range(n)]
    return points, [(0.0, 0.0, 1.0)] * len(points)


def cylinder_samples(n=40, m=10):
    points, normals = [], []
    for k in range(n):
        t = 2.0 * math.pi * k / n
        for j in range(m):
            points.append((8.0 * math.cos(t), 8.0 * math.sin(t), j * 1.0))
            normals.append((math.cos(t), math.sin(t), 0.0))
    return points, normals


def ellipsoid_samples(n=24, a=14.0, b=9.0, c=6.0):
    points, normals = [], []
    for i in range(n):
        for j in range(n):
            u = math.pi * (i + 0.5) / n
            v = 2.0 * math.pi * j / n
            x, y, z = a * math.sin(u) * math.cos(v), b * math.sin(u) * math.sin(v), c * math.cos(u)
            points.append((x, y, z))
            normals.append(_unitise((x / (a * a), y / (b * b), z / (c * c))))
    return points, normals


GATES = {
    "sigma_theta_rad": 0.005,
    "residual_sigma_factor": 3.0,
    "eigengap_min": 0.005,
    "translation_epsilon": 0.05,
    "pitch_epsilon": 0.02,
}


class KinematicRouterTests(unittest.TestCase):
    def test_a_swept_irregular_outline_routes_to_extrusion_along_its_own_axis(self) -> None:
        verdict = route_kinematic_surface(*extruded_cam_samples(), **GATES)
        self.assertEqual("extrusion", verdict["verdict"])
        self.assertIsNone(verdict["refusal"])
        # This is the whole rung-1 claim: no primitive fits this wall, and the
        # router still recovers the direction an extrude has to be built along.
        self.assertAlmostEqual(1.0, abs(verdict["direction"][2]), places=6)

    def test_a_surface_of_revolution_routes_to_revolution_about_its_own_axis(self) -> None:
        verdict = route_kinematic_surface(*revolved_samples(), **GATES)
        self.assertEqual("revolution", verdict["verdict"])
        self.assertAlmostEqual(1.0, abs(verdict["direction"][2]), places=6)
        self.assertLessEqual(abs(verdict["pitch_scaled"]), GATES["pitch_epsilon"])

    def test_a_screw_surface_routes_to_helical_and_recovers_its_pitch(self) -> None:
        verdict = route_kinematic_surface(*helicoid_samples(), **GATES)
        self.assertEqual("helical", verdict["verdict"])
        self.assertAlmostEqual(4.0, verdict["pitch"], places=6)

    def test_a_plane_and_a_cylinder_refuse_rather_than_pick_from_a_degenerate_family(self) -> None:
        # A plane admits a three-parameter family of invariant motions and a
        # cylinder a two-parameter one. Reporting either as "an extrusion" would
        # be picking an eigenvector out of a null space with no single direction.
        for name, samples in (("plane", plane_samples()), ("cylinder", cylinder_samples())):
            with self.subTest(name):
                verdict = route_kinematic_surface(*samples, **GATES)
                self.assertEqual("router-ambiguous", verdict["refusal"])
                self.assertEqual("none", verdict["verdict"])
                self.assertLess(verdict["eigengap"], GATES["eigengap_min"])

    def test_a_doubly_curved_surface_reaches_no_verdict(self) -> None:
        verdict = route_kinematic_surface(*ellipsoid_samples(), **GATES)
        self.assertEqual("none", verdict["verdict"])
        self.assertGreater(verdict["residual_rad"], verdict["residual_gate_rad"])

    def test_the_residual_gate_is_tied_to_the_measured_noise_and_not_to_a_constant(self) -> None:
        points, normals = extruded_cam_samples()
        loose = route_kinematic_surface(points, normals, **dict(GATES, sigma_theta_rad=0.05))
        tight = route_kinematic_surface(points, normals, **dict(GATES, sigma_theta_rad=1e-9))
        self.assertEqual(loose["residual_rad"], tight["residual_rad"])
        self.assertGreater(loose["residual_gate_rad"], tight["residual_gate_rad"])

    def test_a_doubly_curved_signature_contradicting_a_translation_falls_through(self) -> None:
        points, normals = extruded_cam_samples()
        verdict = route_kinematic_surface(points, normals, signature="peak-pit", **GATES)
        self.assertEqual("router-signature-conflict", verdict["refusal"])
        self.assertEqual("none", verdict["verdict"])

    def test_a_region_with_fewer_samples_than_unknowns_is_refused_not_fitted(self) -> None:
        points, normals = plane_samples(n=2)
        with self.assertRaises(ValueError):
            route_kinematic_surface(points, normals, **GATES)


def cam_outline(n=200):
    points = []
    for k in range(n):
        t = 2.0 * math.pi * k / n
        r = 10.0 + 2.0 * math.cos(2.0 * t) + 1.5 * math.sin(3.0 * t)
        points.append((r * math.cos(t), r * math.sin(t), 0.0))
    return points


def rounded_rectangle(width=30.0, height=20.0, radius=5.0, per_side=30):
    points = []
    corners = [
        (width / 2 - radius, height / 2 - radius, 0.0),
        (-width / 2 + radius, height / 2 - radius, math.pi / 2),
        (-width / 2 + radius, -height / 2 + radius, math.pi),
        (width / 2 - radius, -height / 2 + radius, 3 * math.pi / 2),
    ]
    for index, (cx, cy, start) in enumerate(corners):
        for k in range(per_side):
            angle = start + (math.pi / 2) * k / per_side
            points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle), 0.0))
        nx, ny, nstart = corners[(index + 1) % 4]
        sx = cx + radius * math.cos(start + math.pi / 2)
        sy = cy + radius * math.sin(start + math.pi / 2)
        ex, ey = nx + radius * math.cos(nstart), ny + radius * math.sin(nstart)
        for k in range(1, per_side):
            f = k / per_side
            points.append((sx + (ex - sx) * f, sy + (ey - sy) * f, 0.0))
    return points


class SplineProfileTests(unittest.TestCase):
    SPLINE = {"spline_tolerance": 0.02, "min_fit_point_spacing": 0.3, "max_fit_points": 60}

    def test_lines_and_arcs_are_unchanged_when_no_spline_tolerance_is_declared(self) -> None:
        # A spline is only honest once the caller has declared the floors that
        # keep it from reproducing noise, so silence keeps the old vocabulary.
        entities = classify_polyline(
            cam_outline(), tolerance=0.01, closed=True, normal=(0.0, 0.0, 1.0)
        )
        self.assertEqual(set(), {e.kind for e in entities} - {"line", "arc"})

    def test_a_biarc_chain_through_a_freeform_outline_becomes_one_spline(self) -> None:
        entities = classify_polyline(
            cam_outline(), tolerance=0.05, closed=True, normal=(0.0, 0.0, 1.0), **self.SPLINE
        )
        splines = [e for e in entities if e.kind == "spline"]
        self.assertTrue(splines)
        for spline in splines:
            # Few interpolated fit points, not a point per sample: the whole
            # point is a curve a human can drag, not a mesh in sketch clothing.
            self.assertLess(len(spline.fit_points), spline.point_count // 2)
            self.assertLessEqual(spline.residual, self.SPLINE["spline_tolerance"])
            self.assertEqual(spline.fit_points[0], spline.start)
            self.assertEqual(spline.fit_points[-1], spline.end)

    def test_a_designed_outline_keeps_its_lines_and_arcs(self) -> None:
        # The discriminating case. A rounded rectangle's arcs are separated by
        # lines, so no run of them is a biarc approximation of anything, and
        # replacing them with a spline would throw away four real radii.
        entities = classify_polyline(
            rounded_rectangle(), tolerance=0.01, closed=True, normal=(0.0, 0.0, 1.0), **self.SPLINE
        )
        kinds = sorted(e.kind for e in entities)
        self.assertEqual(["arc"] * 4 + ["line"] * 4, kinds)

    def test_chasing_a_noisy_traverse_refuses_on_the_spacing_floor(self) -> None:
        import random

        rng = random.Random(7)
        noisy = [
            (x + rng.gauss(0.0, 0.2), y + rng.gauss(0.0, 0.2), 0.0)
            for x, y, _z in cam_outline(400)
        ]
        with self.assertRaises(ProfileUnresolvable) as caught:
            select_fit_points(noisy, tolerance=0.001, min_spacing=1.0, max_points=400)
        self.assertEqual("fit-point-spacing", caught.exception.detail["reason"])

    def test_a_span_past_the_fit_point_budget_refuses_rather_than_emitting(self) -> None:
        with self.assertRaises(ProfileUnresolvable) as caught:
            select_fit_points(cam_outline(400), tolerance=1e-6, min_spacing=1e-9, max_points=8)
        self.assertEqual("fit-point-budget", caught.exception.detail["reason"])
        self.assertEqual(8, caught.exception.detail["fit_point_count"])

    def test_fit_point_selection_is_deterministic(self) -> None:
        first = select_fit_points(cam_outline(), tolerance=0.02, min_spacing=0.3, max_points=60)
        second = select_fit_points(cam_outline(), tolerance=0.02, min_spacing=0.3, max_points=60)
        self.assertEqual(first, second)

    def test_a_spline_entity_without_its_evidence_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            SketchEntity(kind="spline", start=(0.0, 0.0, 0.0), end=(1.0, 0.0, 0.0),
                         residual=0.0, point_count=4)
        with self.assertRaises(ValueError):
            SketchEntity(kind="line", start=(0.0, 0.0, 0.0), end=(1.0, 0.0, 0.0),
                         residual=0.0, point_count=2,
                         fit_points=((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)))



if __name__ == "__main__":
    unittest.main()
