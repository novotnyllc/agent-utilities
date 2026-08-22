from __future__ import annotations

import io
import math
import unittest
import zipfile
from xml.sax.saxutils import escape

from fusion_design.mesh_strength_proxies import (
    OVERHANG_THRESHOLD_ANGLE_DEGREES,
    MeshStrengthProxyError,
    compute_strength_proxies,
)


def _3mf(model_xml: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("3D/3dmodel.model", model_xml)
    return buffer.getvalue()


def _model(vertices: list[tuple[float, float, float]], triangles: list[tuple[int, int, int]]) -> str:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">', " <resources>", '  <object id="1" type="model">', "   <mesh>", "    <vertices>"]
    for x, y, z in vertices:
        lines.append(f'     <vertex x="{x}" y="{y}" z="{z}"/>')
    lines.append("    </vertices>")
    lines.append("    <triangles>")
    for a, b, c in triangles:
        lines.append(f'     <triangle v1="{a}" v2="{b}" v3="{c}"/>')
    lines += ["    </triangles>", "   </mesh>", "  </object>", " </resources>", "</model>"]
    return "\n".join(lines) + "\n"


def _box(size_x: float, size_y: float, size_z: float) -> tuple[list, list]:
    """A closed axis-aligned box with consistent outward (CCW from outside) winding."""
    sx, sy, sz = size_x, size_y, size_z
    vertices = [
        (0, 0, 0), (sx, 0, 0), (sx, sy, 0), (0, sy, 0),
        (0, 0, sz), (sx, 0, sz), (sx, sy, sz), (0, sy, sz),
    ]
    quads = [
        (4, 5, 6, 7),  # top (+Z)
        (0, 3, 2, 1),  # bottom (-Z)
        (0, 4, 5, 1),  # -Y side
        (1, 5, 6, 2),  # +X side
        (2, 6, 7, 3),  # +Y side
        (3, 7, 4, 0),  # -X side
    ]
    triangles = []
    for a, b, c, d in quads:
        triangles += [(a, b, c), (a, c, d)]
    return vertices, triangles


class MeshStrengthProxyTests(unittest.TestCase):
    def test_flat_plate_yields_zero_overhang_fraction(self) -> None:
        vertices, triangles = _box(10, 10, 1)
        result = compute_strength_proxies(_3mf(_model(vertices, triangles)), "flat")
        self.assertEqual(0.0, result["overhang_area_fraction"])
        self.assertEqual(0.0, result["max_unsupported_span_mm"])
        for key in ("overhang_area_fraction", "max_unsupported_span_mm", "vertical_wall_fraction"):
            self.assertTrue(result["proxy"], key)

    def test_a_box_side_alone_is_fully_vertical(self) -> None:
        # One rectangle standing in the x-z plane: every triangle's normal has
        # zero z-component.
        vertices = [(0, 0, 0), (10, 0, 0), (10, 0, 20), (0, 0, 20)]
        triangles = [(0, 1, 2), (0, 2, 3)]
        result = compute_strength_proxies(_3mf(_model(vertices, triangles)), "side")
        self.assertAlmostEqual(1.0, result["vertical_wall_fraction"], places=9)

    def test_box_vertical_fraction_matches_side_area_share(self) -> None:
        vertices, triangles = _box(10, 10, 20)
        result = compute_strength_proxies(_3mf(_model(vertices, triangles)), "box")
        # Four 10x20 sides against two 10x10 caps: 800 of 1000 total area.
        self.assertAlmostEqual(0.8, result["vertical_wall_fraction"], places=9)
        # The box bottom sits on the bed; nothing above it faces downward.
        self.assertEqual(0.0, result["overhang_area_fraction"])

    def test_raised_plate_reports_overhang_and_span(self) -> None:
        # A thin plate held above the bed by four corner legs: its underside is
        # entirely downward-facing area above the bed.
        height = 5.0
        plate_z = height
        thickness = 1.0
        vertices = [
            (0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0),          # bed corners
            (0, 0, plate_z), (10, 0, plate_z), (10, 10, plate_z), (0, 10, plate_z),  # plate bottom
            (0, 0, plate_z + thickness), (10, 0, plate_z + thickness),
            (10, 10, plate_z + thickness), (0, 10, plate_z + thickness),             # plate top
        ]
        def quad(a, b, c, d):
            return [(a, b, c), (a, c, d)]
        triangles = []
        triangles += quad(8, 9, 10, 11)   # top of raised plate (+Z)
        triangles += quad(7, 6, 5, 4)     # underside of raised plate (-Z)
        triangles += quad(0, 1, 5, 4)     # leg walls and rim
        triangles += quad(1, 2, 6, 5)
        triangles += quad(2, 3, 7, 6)
        triangles += quad(3, 0, 4, 7)
        result = compute_strength_proxies(_3mf(_model(vertices, triangles)), "raised")
        total_area = 2 * (10 * 10) + 4 * (height * 10)
        expected = (10 * 10) / total_area
        self.assertAlmostEqual(expected, result["overhang_area_fraction"], places=9)
        self.assertAlmostEqual(10.0, result["max_unsupported_span_mm"], places=9)

    def test_steep_tilt_is_not_overhang(self) -> None:
        # A downward-facing rectangle sloping 60 degrees from horizontal is
        # steeper than the 45-degree threshold, so none of it counts as overhang.
        tilt = math.radians(60)
        vertices = [
            (0, 0, 0),
            (math.cos(tilt), 0, math.sin(tilt)),
            (math.cos(tilt), 10, math.sin(tilt)),
            (0, 10, 0),
        ]
        triangles = [(0, 3, 2), (0, 2, 1)]
        result = compute_strength_proxies(_3mf(_model(vertices, triangles)), "steep")
        self.assertEqual(0.0, result["overhang_area_fraction"])

    def test_shallow_tilt_counts_as_overhang(self) -> None:
        # Tilted only 20 degrees from horizontal: shallower than the threshold,
        # so the entire downward-facing area counts as overhang.
        tilt = math.radians(20)
        vertices = [(0, 0, 0), (math.cos(tilt), 0, math.sin(tilt)), (math.cos(tilt), 10, math.sin(tilt)), (0, 10, 0)]
        # Flip winding so the surface faces downward (normal -Z-ish).
        triangles = [(0, 3, 2), (0, 2, 1)]
        result = compute_strength_proxies(_3mf(_model(vertices, triangles)), "shallow")
        self.assertAlmostEqual(1.0, result["overhang_area_fraction"], places=9)

    def test_empty_mesh_fails_named(self) -> None:
        with self.assertRaisesRegex(MeshStrengthProxyError, "no mesh geometry"):
            compute_strength_proxies(_3mf(_model([], [])), "empty")

    def test_degenerate_triangle_fails_named(self) -> None:
        vertices = [(0, 0, 0), (1, 0, 0), (2, 0, 0)]
        with self.assertRaisesRegex(MeshStrengthProxyError, "zero-area"):
            compute_strength_proxies(_3mf(_model(vertices, [(0, 1, 2)])), "degenerate")

    def test_corrupt_package_fails_named(self) -> None:
        with self.assertRaisesRegex(MeshStrengthProxyError, "not a readable zip"):
            compute_strength_proxies(b"not a zip", "junk")

    def test_threshold_constant_is_declared_in_output(self) -> None:
        vertices, triangles = _box(2, 2, 2)
        result = compute_strength_proxies(_3mf(_model(vertices, triangles)), "box")
        self.assertEqual(OVERHANG_THRESHOLD_ANGLE_DEGREES, result["overhang_threshold_angle_degrees"])


if __name__ == "__main__":
    unittest.main()
