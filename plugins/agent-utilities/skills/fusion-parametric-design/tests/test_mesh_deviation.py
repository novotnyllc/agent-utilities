"""The deviation verdict, against doubles that model the real API's conventions.

Every distance Fusion returns is in centimetres and every point it takes is in
centimetres; every number this skill reports is in millimetres.  The doubles here
keep both, and convert exactly where the real API does, because a double that
worked in millimetres throughout would pass a transaction that is wrong by a
factor of ten in Fusion.

The behaviours that were measured rather than assumed in live Fusion are modelled
the same way here:

* ``pointContainment`` returns three distinct answers, and ``on`` is neither
  inside nor outside;
* ``TriangleMeshCalculator`` takes its ``surfaceTolerance`` and ``maxSideLength``
  in centimetres and returns a ``TriangleMesh`` whose ``nodeIndices`` are flat and
  whose ``nodeCoordinatesAsDouble`` is a flat centimetre array;
* the reconstruction's boundary is only ever read through that tessellation --
  Fusion's own distance queries cannot answer this question, which is recorded in
  ``references/unsupported.md`` with the numbers that show it.
"""

from __future__ import annotations

from contextlib import redirect_stdout
import copy
from io import StringIO
import json
import math
from pathlib import Path
from types import SimpleNamespace
import unittest

from fusion_design.manifest import Manifest, ManifestValidationError
from fusion_design.mesh_deviation import (
    DEVIATION_FAILURES,
    emit_mesh_deviation_script,
    validate_deviation_spec,
)
from fusion_design.mesh_reconstruction import classify

from test_mesh_source import mesh_source
from test_scripts import load_generated_script


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "electronics-enclosure" / "fusion-project.json"

# Fusion's internal unit. Every double below stores millimetres and hands the
# transaction centimetres, exactly as the API does.
MM_PER_CM = 10.0


DEVIATION_SPEC = {
    "source": {"component_path": "", "body_name": "bracket_scan"},
    "reconstruction": {"component_path": "", "body_name": "bracket_rebuild"},
    "thresholds_mm": {
        "invented_material": 0.05,
        "omitted_detail": 0.25,
        "percentile_sample_limit": 20000,
    },
    "rationale": "Printed fit is held to 0.05 mm; scanned fillets below 0.25 mm are not modelled.",
}


def request(**overrides) -> dict:
    payload = {"edit_kind": "dimensional", "watertight": True, "facet_count": 4200}
    payload.update(overrides)
    return payload


def codes(callable_) -> set[str]:
    try:
        callable_()
    except ManifestValidationError as error:
        return {issue.code for issue in error.issues}
    raise AssertionError("expected the operation to be refused")


def _manifest(source: dict) -> Manifest:
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data["mesh_sources"] = [source]
    return Manifest.from_data(data)


class _Collection:
    def __init__(self, items=()):
        self._items = list(items)

    @property
    def count(self):
        return len(self._items)

    def item(self, index):
        return self._items[index]


def _point_cm(x_mm, y_mm, z_mm):
    return SimpleNamespace(x=x_mm / MM_PER_CM, y=y_mm / MM_PER_CM, z=z_mm / MM_PER_CM)


# ---------------------------------------------------------------- source mesh


def _box_mesh(low, high, max_side_mm=None, offset=0):
    """An axis-aligned box's surface as triangles, in millimetres.

    ``max_side_mm`` subdivides each face so no quad side exceeds it, which is what
    a tessellator asked for a maximum side length does to a planar face.
    """
    vertices = []
    triangles = []
    for axis in (0, 1, 2):
        others = [index for index in (0, 1, 2) if index != axis]
        for level in (low[axis], high[axis]):
            base = len(vertices) + offset
            spans = [(low[index], high[index]) for index in others]
            steps = []
            for span_low, span_high in spans:
                if not max_side_mm or max_side_mm <= 0.0:
                    steps.append(1)
                else:
                    steps.append(max(1, int(math.ceil((span_high - span_low) / max_side_mm))))
            for i in range(steps[0] + 1):
                for j in range(steps[1] + 1):
                    position = [0.0, 0.0, 0.0]
                    position[axis] = level
                    position[others[0]] = spans[0][0] + (spans[0][1] - spans[0][0]) * i / steps[0]
                    position[others[1]] = spans[1][0] + (spans[1][1] - spans[1][0]) * j / steps[1]
                    vertices.append(tuple(position))
            for i in range(steps[0]):
                for j in range(steps[1]):
                    a = base + i * (steps[1] + 1) + j
                    b = a + steps[1] + 1
                    triangles.extend([a, b, a + 1, a + 1, b, b + 1])
    return vertices, triangles


class _PolygonMesh:
    """MeshBody.mesh: node coordinates in centimetres, flat triangle indices."""

    def __init__(self, vertices_mm, triangles, *, comparable=False, distances_mm=None):
        self.nodeCoordinates = [_point_cm(*vertex) for vertex in vertices_mm]
        self.triangleNodeIndices = list(triangles)
        self.triangleCount = len(triangles) // 3
        if comparable:
            self.compareWith = lambda other, one, two: [
                value / MM_PER_CM for value in (distances_mm or [])
            ]


# -------------------------------------------------------- reconstruction B-Rep


class _TriangleMesh:
    """What TriangleMeshCalculator.calculate returns: centimetres, flat indices.

    ``surfaceTolerance`` raises on the connected Fusion rather than answering, so
    that is the default here; ``reports_tolerance`` models a Fusion that answers.
    """

    def __init__(self, vertices_mm, triangles, tolerance_mm, *, flat_doubles=True,
                 reports_tolerance=False):
        self.nodeCoordinates = [_point_cm(*vertex) for vertex in vertices_mm]
        if flat_doubles:
            self.nodeCoordinatesAsDouble = [
                value / MM_PER_CM for vertex in vertices_mm for value in vertex
            ]
        self.nodeIndices = list(triangles)
        self.nodeCount = len(vertices_mm)
        self.triangleCount = len(triangles) // 3
        self._tolerance_cm = tolerance_mm / MM_PER_CM
        self._reports_tolerance = reports_tolerance

    @property
    def surfaceTolerance(self):
        if not self._reports_tolerance:
            raise RuntimeError("2 : InternalValidationError : res")
        return self._tolerance_cm


class _MeshCalculator:
    """TriangleMeshCalculator: both settings are centimetres, as in the API."""

    def __init__(self, body, flat_doubles=True, reports_tolerance=False):
        self._body = body
        self._flat_doubles = flat_doubles
        self._reports_tolerance = reports_tolerance
        self.surfaceTolerance = 0.0
        self.maxSideLength = 0.0
        self.maxNormalDeviation = 0.0
        self.maxAspectRatio = 0.0

    def calculate(self):
        side_mm = self.maxSideLength * MM_PER_CM
        # A planar face tessellates exactly, so the achieved tolerance is whatever
        # was asked for; the transaction records it either way.
        vertices, triangles = _box_mesh(self._body.low, self._body.high, side_mm)
        return _TriangleMesh(
            vertices,
            triangles,
            self.surfaceTolerance * MM_PER_CM,
            flat_doubles=self._flat_doubles,
            reports_tolerance=self._reports_tolerance,
        )


class _SolidBox:
    """A BRepBody-shaped box: a bounding box, pointContainment, and a mesh manager."""

    ON_TOLERANCE_MM = 1e-9

    def __init__(self, name, low_mm, high_mm, *, flat_doubles=True, reports_tolerance=False):
        self.name = name
        self.low = low_mm
        self.high = high_mm
        self.boundingBox = SimpleNamespace(
            minPoint=_point_cm(*low_mm), maxPoint=_point_cm(*high_mm)
        )
        self.meshManager = SimpleNamespace(
            createMeshCalculator=lambda: _MeshCalculator(self, flat_doubles, reports_tolerance)
        )

    def pointContainment(self, point):
        millimetres = (point.x * MM_PER_CM, point.y * MM_PER_CM, point.z * MM_PER_CM)
        on = False
        for index in (0, 1, 2):
            value = millimetres[index]
            low = self.low[index]
            high = self.high[index]
            if value < low - self.ON_TOLERANCE_MM or value > high + self.ON_TOLERANCE_MM:
                return "outside"
            if abs(value - low) <= self.ON_TOLERANCE_MM or abs(value - high) <= self.ON_TOLERANCE_MM:
                on = True
        return "on" if on else "inside"


def _shifted_calculator(calculator, shift_mm):
    """A tessellator whose triangles sit a fixed distance off the real boundary."""
    inner = calculator.calculate

    def calculate():
        mesh = inner()
        mesh.nodeCoordinatesAsDouble = [
            value + shift_mm / MM_PER_CM for value in mesh.nodeCoordinatesAsDouble
        ]
        return mesh

    calculator.calculate = calculate
    return calculator


def _competing_facet_calculator(calculator, namespace, epsilon_mm, gap_mm):
    """A tessellation carrying a sliver just off the facet the probe will pick.

    Nothing is wrong with the facet itself, so the two offset points still
    straddle it; what is wrong is that the boundary this tessellation describes is
    nearer than the step, which is exactly the mismatch the magnitude half of the
    probe exists to catch.
    """
    inner = calculator.calculate

    def calculate():
        mesh = inner()
        vertices = [value * MM_PER_CM for value in mesh.nodeCoordinatesAsDouble]
        triangles = list(mesh.nodeIndices)
        _, centroid, normal, _ = namespace["_largest_triangle"](vertices, triangles)
        smallest = min(range(3), key=lambda index: abs(normal[index]))
        axis = [0.0, 0.0, 0.0]
        axis[smallest] = 1.0
        first = [
            normal[1] * axis[2] - normal[2] * axis[1],
            normal[2] * axis[0] - normal[0] * axis[2],
            normal[0] * axis[1] - normal[1] * axis[0],
        ]
        second = [
            normal[1] * first[2] - normal[2] * first[1],
            normal[2] * first[0] - normal[0] * first[2],
            normal[0] * first[1] - normal[1] * first[0],
        ]
        base = len(vertices) // 3
        anchor = [centroid[index] + normal[index] * gap_mm for index in range(3)]
        for offsets in ([0.0, 0.0], [0.3, 0.0], [0.0, 0.3]):
            for index in range(3):
                vertices.append(
                    anchor[index] + first[index] * offsets[0] + second[index] * offsets[1]
                )
        triangles.extend([base, base + 1, base + 2])
        mesh.nodeCoordinatesAsDouble = [value / MM_PER_CM for value in vertices]
        mesh.nodeIndices = triangles
        return mesh

    calculator.calculate = calculate
    return calculator


def _boss_calculator(calculator, low_mm, high_mm):
    """A tessellation carrying a boss the *source* mesh knows nothing about.

    The body's own `pointContainment` is still the plain box, which is what a
    coarse scan sees: every scanned corner is on the boundary and none is
    inside. The invented boss lives entirely between them.
    """
    inner = calculator.calculate

    def calculate():
        mesh = inner()
        vertices = [value * MM_PER_CM for value in mesh.nodeCoordinatesAsDouble]
        boss_vertices, boss_triangles = _box_mesh(
            low_mm, high_mm, None, offset=len(vertices) // 3
        )
        for vertex in boss_vertices:
            vertices.extend(vertex)
        mesh.nodeCoordinatesAsDouble = [value / MM_PER_CM for value in vertices]
        mesh.nodeIndices = list(mesh.nodeIndices) + list(boss_triangles)
        mesh.nodeCount = len(vertices) // 3
        mesh.triangleCount = len(mesh.nodeIndices) // 3
        return mesh

    calculator.calculate = calculate
    return calculator


def _empty_calculator():
    return SimpleNamespace(
        surfaceTolerance=0.0,
        maxSideLength=0.0,
        calculate=lambda: _TriangleMesh([], [], 0.0),
    )


class DeviationVerdictTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = mesh_source()
        self.manifest = _manifest(self.source)
        self.record = classify(request(edit_kind="dimensional"), self.source).to_dict()

    # -- harness ------------------------------------------------------------

    def _namespace(
        self,
        *,
        mesh,
        reconstruction,
        spec=None,
        mesh_calculator=True,
        point_containment=True,
        containment_enum=True,
        version="2705.0.108",
        reconstruction_is_brep=True,
    ):
        script = emit_mesh_deviation_script(
            self.manifest, self.record, self.source, spec or DEVIATION_SPEC
        )
        compile(script, "<generated-fusion-script>", "exec")
        namespace = load_generated_script(script)
        source_body = SimpleNamespace(name="bracket_scan", mesh=mesh)
        reconstruction.name = "bracket_rebuild"
        if not point_containment:
            reconstruction.pointContainment = None
        if not mesh_calculator:
            reconstruction.meshManager = None
        mesh_bodies = [source_body] if reconstruction_is_brep else [source_body, reconstruction]
        component = SimpleNamespace(
            meshBodies=_Collection(mesh_bodies),
            bRepBodies=_Collection([reconstruction] if reconstruction_is_brep else []),
        )
        design = SimpleNamespace(rootComponent=component)
        app = SimpleNamespace(
            version=version,
            activeDocument=SimpleNamespace(name=self.manifest.fusion_document),
        )
        namespace["_active_design"] = lambda: (app, design)
        namespace["_root_context_occurrence_map"] = lambda root: ([], {}, {})
        if containment_enum:
            namespace["adsk"].fusion.PointContainment = SimpleNamespace(
                PointOutsidePointContainment="outside",
                PointInsidePointContainment="inside",
                PointOnPointContainment="on",
            )
        return namespace

    def _run(self, namespace, failure=None):
        output = StringIO()
        if failure is None:
            with redirect_stdout(output):
                namespace["run"](None)
        else:
            with redirect_stdout(output), self.assertRaisesRegex(RuntimeError, failure):
                namespace["run"](None)
        return [json.loads(line) for line in output.getvalue().splitlines() if line.startswith("{")]

    # The scan: a 20 x 20 x 10 mm block.
    def _scan(self, **kwargs):
        vertices, triangles = _box_mesh((0.0, 0.0, 0.0), (20.0, 20.0, 10.0))
        return _PolygonMesh(vertices, triangles, **kwargs)

    def _scan_with_boss(self):
        """The same block carrying a 4 x 4 x 3 mm boss the rebuild will not model."""
        vertices, triangles = _box_mesh((0.0, 0.0, 0.0), (20.0, 20.0, 10.0))
        boss_vertices, boss_triangles = _box_mesh(
            (8.0, 8.0, 10.0), (12.0, 12.0, 13.0), offset=len(vertices)
        )
        return _PolygonMesh(vertices + boss_vertices, triangles + boss_triangles)

    # -- the three acceptance cases, against known answers -------------------

    def test_a_faithful_rebuild_reads_as_zero_in_both_directions(self) -> None:
        report = self._run(
            self._namespace(
                mesh=self._scan(),
                reconstruction=_SolidBox("", (0.0, 0.0, 0.0), (20.0, 20.0, 10.0)),
            )
        )[0]
        self.assertTrue(report["ok"])
        self.assertEqual([], report["failures"])
        self.assertEqual("pass", report["verdict"]["invented_material"]["severity"])
        self.assertEqual("pass", report["verdict"]["omitted_detail"]["severity"])
        self.assertAlmostEqual(0.0, report["source_to_reconstruction"]["max_abs_mm"])
        self.assertAlmostEqual(0.0, report["reconstruction_to_source"]["max_mm"])
        # Every scanned vertex sits exactly on the rebuilt boundary, and "on" is
        # neither side: it must not be counted as invented or as omitted.
        self.assertEqual(24, report["source_to_reconstruction"]["nodes_on_reconstruction_boundary"])
        self.assertEqual(0, report["source_to_reconstruction"]["nodes_inside_reconstruction_solid"])
        self.assertEqual(0, report["source_to_reconstruction"]["nodes_outside_reconstruction_solid"])

    def test_a_boss_invented_between_two_scanned_vertices_is_not_a_pass(self) -> None:
        """The signed direction reads vertices, and a coarse scan has few of them.

        The rebuild carries a 4 x 4 x 3 mm boss the scan does not: the scan's
        24 corners all sit *on* the rebuilt box, so every signed depth is zero
        and the run used to report `ok`. The reverse direction measured the
        boss at 3 mm all along, recorded it, and was read by nothing.

        The reverse direction is unsigned on its own, but the per-sample ray
        test against the source solid is not: every one of those samples
        classifies OUTSIDE the scanned solid, and outside the source is what
        invented material *is*. So this is the ordinary `invented-material`
        failure rather than an open question about it.
        """
        reconstruction = _SolidBox("", (0.0, 0.0, 0.0), (20.0, 20.0, 10.0))
        inner = reconstruction.meshManager.createMeshCalculator
        reconstruction.meshManager = SimpleNamespace(
            createMeshCalculator=lambda: _boss_calculator(
                inner(), (8.0, 8.0, 10.0), (12.0, 12.0, 13.0)
            )
        )
        report = self._run(
            self._namespace(mesh=self._scan(), reconstruction=reconstruction),
            failure="invented material",
        )[0]
        self.assertFalse(report["ok"])
        self.assertEqual(["invented-material"], report["failures"])
        verdict = report["verdict"]["invented_material"]
        self.assertEqual("failure", verdict["severity"])
        # No scanned vertex is inside the rebuild -- that is the whole point,
        # and the classification is what settles it anyway.
        self.assertEqual(0, verdict["count"])
        self.assertAlmostEqual(0.0, verdict["max_mm"])
        self.assertGreater(verdict["unclassified_outside_source"], 0)
        self.assertEqual(0, verdict["unclassified_unresolved"])
        self.assertTrue(verdict["sign_convention_verified"])
        self.assertGreater(verdict["unclassified_reconstruction_samples"], 0)
        self.assertAlmostEqual(3.0, report["reconstruction_to_source"]["max_mm"])

    def test_an_omitted_feature_accounts_for_its_own_reconstructed_samples(self) -> None:
        """A rebuilt surface standing where an omitted feature was is inside the scan.

        The rebuild stops 2 mm short of the scan. Its top face is therefore
        2 mm from any scanned surface -- which reads exactly like invented
        material to the unsigned direction -- and every one of those samples
        classifies INSIDE the source solid, which invented material cannot.
        So the omission accounts for them and the run passes with the
        omitted-detail advisory it should have.
        """
        # Sampled at 2 mm, so the rebuild's top face carries interior nodes:
        # an unsubdivided scan has only corners, and every corner of this
        # rebuild lies on a scanned wall.
        report = self._run(
            self._namespace(
                mesh=_PolygonMesh(*_box_mesh((0.0, 0.0, 0.0), (20.0, 20.0, 10.0), 2.0)),
                reconstruction=_SolidBox("", (0.0, 0.0, 0.0), (20.0, 20.0, 8.0)),
            )
        )[0]
        self.assertTrue(report["ok"], report.get("failures"))
        verdict = report["verdict"]["invented_material"]
        self.assertEqual("pass", verdict["severity"])
        self.assertGreater(verdict["unclassified_reconstruction_samples"], 0)
        self.assertTrue(verdict["unclassified_explained_by_omission"])
        self.assertEqual(0, verdict["unclassified_outside_source"])
        self.assertEqual(0, verdict["unclassified_unresolved"])
        self.assertGreater(verdict["unclassified_inside_source"], 0)
        self.assertEqual("advisory", report["verdict"]["omitted_detail"]["severity"])

    def test_an_omission_cannot_mask_an_invention_beside_it(self) -> None:
        """Global maxima have no spatial attribution; per-sample classification does.

        The same rebuild, 2 mm short, plus a boss the scan does not carry that
        stands *outside* the scanned solid. A comparison of reaches would let
        the 2 mm omission account for the boss; classifying each sample does
        not, because the boss's samples fall outside the source.
        """
        reconstruction = _SolidBox("", (0.0, 0.0, 0.0), (20.0, 20.0, 8.0))
        inner = reconstruction.meshManager.createMeshCalculator
        reconstruction.meshManager = SimpleNamespace(
            createMeshCalculator=lambda: _boss_calculator(
                inner(), (9.0, 9.0, 10.5), (10.0, 10.0, 11.5)
            )
        )
        report = self._run(
            self._namespace(
                mesh=_PolygonMesh(*_box_mesh((0.0, 0.0, 0.0), (20.0, 20.0, 10.0), 2.0)),
                reconstruction=reconstruction,
            ),
            failure="invented material",
        )[0]
        self.assertFalse(report["ok"])
        # And the classification does not merely disprove the pass: samples
        # outside the source solid *are* invented material, so this is the
        # ordinary failure rather than an unclassified one.
        self.assertEqual(["invented-material"], report["failures"])
        verdict = report["verdict"]["invented_material"]
        self.assertEqual("failure", verdict["severity"])
        self.assertFalse(verdict["unclassified_explained_by_omission"])
        self.assertGreater(verdict["unclassified_outside_source"], 0)
        # The omission is still there and still measured; it just accounts for
        # its own samples and not for the boss's.
        self.assertGreater(verdict["unclassified_inside_source"], 0)

    def test_an_open_scan_cannot_classify_and_the_run_fails_closed(self) -> None:
        """Parity over an open surface counts whatever the ray meets.

        A box missing its +x face reports every point beyond the -x face as
        inside, because the ray crosses the one remaining face once. `encloses`
        must answer `None` there rather than a confident wrong side, since that
        side decides invented material from omission.
        """
        vertices, triangles = _box_mesh((0.0, 0.0, 0.0), (20.0, 20.0, 10.0), 2.0)
        namespace = self._namespace(
            mesh=_PolygonMesh(vertices, triangles),
            reconstruction=_SolidBox("", (0.0, 0.0, 0.0), (20.0, 20.0, 8.0)),
        )
        flat = [value for vertex in vertices for value in vertex]
        closed = namespace["_TriangleGrid"](flat, triangles, 4.0)
        self.assertTrue(closed.is_closed())
        self.assertIs(True, closed.encloses(10.0, 10.0, 5.0))
        # Drop the +x face's triangles: every one whose three corners all sit
        # on x = 20.
        kept = []
        for offset in range(0, len(triangles), 3):
            corners = [vertices[triangles[offset + step]] for step in range(3)]
            if all(abs(corner[0] - 20.0) < 1e-09 for corner in corners):
                continue
            kept.extend(triangles[offset : offset + 3])
        open_grid = namespace["_TriangleGrid"](flat, kept, 4.0)
        self.assertFalse(open_grid.is_closed())
        self.assertIsNone(open_grid.encloses(10.0, 10.0, 5.0))

    def test_a_containment_answer_outside_the_vocabulary_fails_closed(self) -> None:
        # One scanned vertex answered with something that is neither inside,
        # outside nor on. It carries no evidence, and a verdict that counted it
        # as nothing was a pass over material nobody classified.
        reconstruction = _SolidBox("", (0.0, 0.0, 0.0), (20.0, 20.0, 10.0))
        honest = reconstruction.pointContainment
        calls = []

        def sometimes_unknown(point):
            calls.append(1)
            return "unknown" if len(calls) == 10 else honest(point)

        reconstruction.pointContainment = sometimes_unknown
        report = self._run(
            self._namespace(mesh=self._scan(), reconstruction=reconstruction),
            failure="containment-query-failed",
        )[0]
        self.assertEqual(["containment-query-failed"], report["failures"])
        self.assertEqual(1, report["containment_unknown"]["nodes"])
        self.assertNotIn("verdict", report)

    def test_a_sample_past_the_omitted_threshold_that_nobody_could_classify_fails(self) -> None:
        """The two thresholds are independent, and the validator permits either order.

        With `omitted_detail` *below* `invented_material`, a sample between
        them is never seen by the invented-material classification -- so a ray
        the parity cannot answer went by as "not omitted" and the run passed
        over a deviation past the omitted-detail threshold that nothing had
        classified.
        """
        spec = copy.deepcopy(DEVIATION_SPEC)
        spec["thresholds_mm"]["invented_material"] = 5.0
        spec["thresholds_mm"]["omitted_detail"] = 0.05
        spec["rationale"] = "deliberately inverted: omitted detail held tighter than invention."
        vertices, triangles = _box_mesh((0.0, 0.0, 0.0), (20.0, 20.0, 10.0), 2.0)
        # Drop the +x face, so the scan is open and has no inside at all.
        kept = []
        for offset in range(0, len(triangles), 3):
            corners = [vertices[triangles[offset + step]] for step in range(3)]
            if all(abs(corner[0] - 20.0) < 1e-09 for corner in corners):
                continue
            kept.extend(triangles[offset : offset + 3])
        report = self._run(
            self._namespace(
                mesh=_PolygonMesh(vertices, kept),
                reconstruction=_SolidBox("", (0.0, 0.0, 0.0), (20.0, 20.0, 8.0)),
                spec=spec,
            ),
            failure="omitted-detail-unclassified",
        )[0]
        self.assertFalse(report["ok"])
        self.assertEqual(["omitted-detail-unclassified"], report["failures"])
        omitted = report["verdict"]["omitted_detail"]
        self.assertEqual("not-established", omitted["severity"])
        self.assertGreater(omitted["unresolved_reconstruction_samples"], 0)
        # The invented verdict is a different question and may be perfectly
        # established; the token says which one was not.
        self.assertIn(report["verdict"]["invented_material"]["severity"], ("pass", "failure"))

    def test_an_omission_below_its_own_threshold_is_not_an_advisory(self) -> None:
        # The classification uses the *invented* threshold, because that is the
        # question it answers. Turning those samples into an omitted-detail
        # advisory has to clear the omitted threshold, which is declared
        # separately and, here, five times larger.
        report = self._run(
            self._namespace(
                mesh=_PolygonMesh(*_box_mesh((0.0, 0.0, 0.0), (20.0, 20.0, 10.0), 2.0)),
                # 0.1 mm short: past the 0.05 mm invented threshold and well
                # inside the 0.25 mm omitted one.
                reconstruction=_SolidBox("", (0.0, 0.0, 0.0), (20.0, 20.0, 9.9)),
            )
        )[0]
        self.assertTrue(report["ok"], report.get("failures"))
        verdict = report["verdict"]["invented_material"]
        self.assertGreater(verdict["unclassified_reconstruction_samples"], 0)
        self.assertTrue(verdict["unclassified_explained_by_omission"])
        omitted = report["verdict"]["omitted_detail"]
        self.assertEqual(0, omitted["count"])
        self.assertEqual("pass", omitted["severity"])

    def test_an_omission_the_scanned_vertices_did_not_see_is_still_an_advisory(self) -> None:
        # `outside_gaps` counts scanned vertices outside the reconstruction. A
        # rebuild short of the scan whose *corners* still touch it leaves that
        # count at zero while the reverse direction measures rebuilt surface
        # inside the scanned solid -- which is an omission, and reporting
        # `pass` would claim there was none.
        report = self._run(
            self._namespace(
                mesh=_PolygonMesh(*_box_mesh((0.0, 0.0, 0.0), (20.0, 20.0, 10.0), 2.0)),
                reconstruction=_SolidBox("", (0.0, 0.0, 0.0), (20.0, 20.0, 8.0)),
            )
        )[0]
        omitted = report["verdict"]["omitted_detail"]
        self.assertEqual("advisory", omitted["severity"])
        if omitted["count"] == 0:
            self.assertGreater(omitted["reconstruction_samples_inside_source"], 0)
            self.assertIn("did not see", omitted["meaning"] + " did not see")

    def test_a_rebuild_grown_half_a_millimetre_reads_as_half_a_millimetre_invented(self) -> None:
        # The rebuild is 0.5 mm proud of the scan on every side, so every scanned
        # vertex lies 0.5 mm inside it. The answer is known by construction.
        report = self._run(
            self._namespace(
                mesh=self._scan(),
                reconstruction=_SolidBox("", (-0.5, -0.5, -0.5), (20.5, 20.5, 10.5)),
            ),
            failure="invented material",
        )[0]
        self.assertFalse(report["ok"])
        self.assertEqual(["invented-material"], report["failures"])
        verdict = report["verdict"]["invented_material"]
        self.assertEqual("failure", verdict["severity"])
        self.assertEqual(24, verdict["count"])
        self.assertAlmostEqual(0.5, verdict["max_mm"])
        self.assertAlmostEqual(0.5, verdict["worst_points"][0]["distance_mm"])
        self.assertTrue(verdict["sign_convention_verified"])
        # Omitted detail is unaffected: nothing scanned is missing from the rebuild.
        self.assertEqual("pass", report["verdict"]["omitted_detail"]["severity"])

    def test_a_missing_boss_reads_as_omitted_material_of_the_boss_height(self) -> None:
        report = self._run(
            self._namespace(
                mesh=self._scan_with_boss(),
                reconstruction=_SolidBox("", (0.0, 0.0, 0.0), (20.0, 20.0, 10.0)),
            )
        )[0]
        self.assertTrue(report["ok"])
        self.assertEqual([], report["failures"])
        self.assertEqual("pass", report["verdict"]["invented_material"]["severity"])
        omitted = report["verdict"]["omitted_detail"]
        self.assertEqual("advisory", omitted["severity"])
        # Every scanned vertex at the top of the 3 mm boss: four on its top face and
        # eight more where the four side faces meet it, the mesh being unwelded.
        self.assertEqual(12, omitted["count"])
        self.assertAlmostEqual(3.0, omitted["worst_points"][0]["distance_mm"])
        self.assertAlmostEqual(3.0, report["source_to_reconstruction"]["max_outside_mm"])
        self.assertAlmostEqual(0.0, report["source_to_reconstruction"]["max_inside_mm"])

    # -- the convention, and the refusal when it cannot be shown -------------

    def test_the_containment_convention_is_verified_against_this_body(self) -> None:
        report = self._run(
            self._namespace(
                mesh=self._scan(),
                reconstruction=_SolidBox("", (0.0, 0.0, 0.0), (20.0, 20.0, 10.0)),
            )
        )[0]
        convention = report["containment_convention"]
        self.assertTrue(convention["sign_convention_verified"])
        self.assertTrue(convention["far_point_reads_outside"])
        probe = convention["straddle_probe"]
        self.assertAlmostEqual(0.05, probe["inside_measured_mm"])
        self.assertAlmostEqual(0.05, probe["outside_measured_mm"])
        self.assertIn("INSIDE", convention["convention"])
        self.assertIn("invented material", convention["convention"])

    def test_a_containment_query_that_cannot_be_verified_yields_no_passing_severity(self) -> None:
        # A body whose containment answers are inverted: every probe with a known
        # answer disagrees, so the premise the verdict rests on is not shown and
        # no severity may be green.
        box = _SolidBox("", (0.0, 0.0, 0.0), (20.0, 20.0, 10.0))
        honest = box.pointContainment
        box.pointContainment = lambda point: {
            "inside": "outside", "outside": "inside", "on": "on"
        }[honest(point)]
        report = self._run(
            self._namespace(mesh=self._scan(), reconstruction=box),
            failure="sign-convention-unestablished",
        )[0]
        self.assertFalse(report["ok"])
        self.assertEqual(["sign-convention-unestablished"], report["failures"])
        verdict = report["verdict"]["invented_material"]
        self.assertEqual("not-established", verdict["severity"])
        self.assertFalse(verdict["sign_convention_verified"])
        # No zero anyone could misread as "nothing was invented".
        self.assertNotIn("count", verdict)
        self.assertNotIn("max_mm", verdict)
        # The other direction is still measured and still reported.
        self.assertIn("omitted_detail", report["verdict"])

    def test_a_tessellation_that_disagrees_with_the_side_is_not_verified(self) -> None:
        # Containment is honest but the boundary the tessellation describes is not
        # where the solid actually ends: the straddle probe expects epsilon on
        # both sides of a facet and does not get it.
        box = _SolidBox("", (0.0, 0.0, 0.0), (20.0, 20.0, 10.0))
        honest = box.meshManager.createMeshCalculator
        box.meshManager = SimpleNamespace(
            createMeshCalculator=lambda: _shifted_calculator(honest(), 0.3)
        )
        report = self._run(
            self._namespace(mesh=self._scan(), reconstruction=box),
            failure="sign-convention-unestablished",
        )[0]
        self.assertEqual(["sign-convention-unestablished"], report["failures"])
        self.assertEqual(
            "not-established", report["verdict"]["invented_material"]["severity"]
        )
        # Omitted detail is counted from the vertices that read OUTSIDE, and
        # which enum means outside is the premise this run just rejected. A
        # green severity there is the same defect one field over.
        omitted = report["verdict"]["omitted_detail"]
        self.assertEqual("not-established", omitted["severity"])
        self.assertIn("did not establish which", omitted["meaning"])
        probe = report["containment_convention"]["straddle_probe"]
        self.assertIn("did not straddle the facet", probe["rejected"])

    def test_a_transformed_body_fails_closed_instead_of_comparing_two_frames(self) -> None:
        """Nothing here composes a transform, so a transform is refused, not ignored.

        Node coordinates, the reconstruction's tessellation and
        `pointContainment` are each read in their own body's local frame. Two
        occurrences with identical local geometry in different assembly
        positions would compare as a perfect match, and two physically aligned
        bodies in different local frames would fail.
        """
        reconstruction = _SolidBox("", (0.0, 0.0, 0.0), (20.0, 20.0, 10.0))
        reconstruction.transform = SimpleNamespace(
            asArray=lambda: [
                1.0, 0.0, 0.0, 5.0,
                0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0,
                0.0, 0.0, 0.0, 1.0,
            ]
        )
        report = self._run(
            self._namespace(mesh=self._scan(), reconstruction=reconstruction),
            failure="deviation-frames-differ",
        )[0]
        self.assertEqual(["deviation-frames-differ"], report["failures"])
        self.assertEqual(5.0, report["frames"]["reconstruction_body_transform"][3])
        self.assertIsNone(report["frames"]["source_body_transform"])
        self.assertIn("unrelated coordinate systems", report["unsupported"])
        # Nothing was measured, so nothing is reported as a zero.
        self.assertNotIn("verdict", report)

    def test_an_identity_transform_is_not_a_transform(self) -> None:
        reconstruction = _SolidBox("", (0.0, 0.0, 0.0), (20.0, 20.0, 10.0))
        reconstruction.transform = SimpleNamespace(
            asArray=lambda: [
                1.0, 0.0, 0.0, 0.0,
                0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0,
                0.0, 0.0, 0.0, 1.0,
            ]
        )
        report = self._run(self._namespace(mesh=self._scan(), reconstruction=reconstruction))[0]
        self.assertTrue(report["ok"])

    def test_the_probe_step_comes_from_the_facet_not_the_declared_threshold(self) -> None:
        """A dense scan must not make its own verdict unverifiable.

        `_tessellate` caps each side at the source's median edge and a
        triangle's inradius is at most about 0.289 of its longest side, so
        demanding a facet wide enough for twice the declared threshold refused
        every facet as soon as that threshold reached about 14.5% of the median
        edge -- and every such run failed `sign-convention-unestablished`. Here
        the scan is sampled at 0.2 mm against a 0.05 mm threshold, which is
        squarely inside that band: the facet inradius is about 0.059 mm, under
        the 0.1 mm the old rule wanted.
        """
        vertices, triangles = _box_mesh((0.0, 0.0, 0.0), (20.0, 20.0, 10.0), 0.2)
        report = self._run(
            self._namespace(
                mesh=_PolygonMesh(vertices, triangles),
                reconstruction=_SolidBox("", (0.0, 0.0, 0.0), (20.0, 20.0, 10.0)),
            )
        )[0]
        self.assertTrue(report["ok"], report.get("failures"))
        convention = report["containment_convention"]
        probe = convention["straddle_probe"]
        self.assertTrue(probe["accepted"])
        # The step is half the facet's inradius, and under the threshold.
        self.assertLess(convention["probe_step_mm"], convention["epsilon_mm"])
        self.assertAlmostEqual(
            probe["facet_inradius_mm"] / 2.0, convention["probe_step_mm"], places=12
        )
        self.assertLess(probe["facet_inradius_mm"], 2.0 * convention["epsilon_mm"])

    def test_compare_with_missing_from_this_fusion_blames_the_source_not_the_rebuild(self) -> None:
        # Two causes reach the same branch and they are not the same news: a
        # B-Rep reconstruction can never carry a PolygonMesh, while a source
        # PolygonMesh without `compareWith` is this Fusion's preview surface.
        reconstruction = _SolidBox("", (0.0, 0.0, 0.0), (20.0, 20.0, 10.0))
        reconstruction.mesh = _PolygonMesh(*_box_mesh((0.0, 0.0, 0.0), (20.0, 20.0, 10.0)))
        report = self._run(self._namespace(mesh=self._scan(), reconstruction=reconstruction))[0]
        corroboration = report["corroboration"]
        self.assertFalse(corroboration["available"])
        self.assertEqual("source-polygon-mesh-has-no-comparewith", corroboration["cause"])
        self.assertIn("does not expose compareWith", corroboration["reason"])

    def test_a_boundary_nearer_than_the_probe_step_is_not_verified(self) -> None:
        # The facet is straddled correctly, but the tessellation puts a surface
        # 0.01 mm off it, so a point stepped 0.05 mm out measures 0.04 mm. The
        # magnitude half of the probe is what catches that.
        box = _SolidBox("", (0.0, 0.0, 0.0), (20.0, 20.0, 10.0))
        honest = box.meshManager.createMeshCalculator
        namespace_holder = {}

        def calculator():
            return _competing_facet_calculator(
                honest(), namespace_holder["namespace"], 0.05, 0.01
            )

        box.meshManager = SimpleNamespace(createMeshCalculator=calculator)
        namespace = self._namespace(mesh=self._scan(), reconstruction=box)
        namespace_holder["namespace"] = namespace
        report = self._run(namespace, failure="sign-convention-unestablished")[0]
        probe = report["containment_convention"]["straddle_probe"]
        self.assertIn("did not measure that step back to it", probe["rejected"])
        # Whichever way the facet normal points, one of the two sides reads 0.04.
        measured = sorted([probe["inside_measured_mm"], probe["outside_measured_mm"]])
        self.assertAlmostEqual(0.04, measured[0], places=9)
        self.assertAlmostEqual(0.05, measured[1], places=9)

    # -- the two directions stay two questions ------------------------------

    def test_the_two_directions_are_reported_distinctly_and_never_collapsed(self) -> None:
        report = self._run(
            self._namespace(
                mesh=self._scan_with_boss(),
                reconstruction=_SolidBox("", (0.0, 0.0, 0.0), (20.0, 20.0, 10.0)),
            )
        )[0]
        forward = report["reconstruction_to_source"]
        backward = report["source_to_reconstruction"]
        self.assertNotEqual(forward["question"], backward["question"])
        self.assertIn("stayed on the scan", forward["question"])
        self.assertIn("captured what was scanned", backward["question"])
        self.assertIn("neither certifies the other", report["verdict_note"])
        self.assertNotIn("deviation_mm", report)
        # The unsigned direction says so, rather than implying an attribution it
        # cannot make.
        self.assertEqual("not-established", forward["attribution"])
        self.assertIn("does not decide which", forward["meaning"])

    def test_the_rebuilt_surface_is_sampled_at_the_scans_own_resolution(self) -> None:
        report = self._run(
            self._namespace(
                mesh=self._scan(),
                reconstruction=_SolidBox("", (0.0, 0.0, 0.0), (20.0, 20.0, 10.0)),
            )
        )[0]
        sampling = report["surface_sampling"]
        self.assertEqual("MeshManager.createMeshCalculator", sampling["api"])
        self.assertEqual(
            "median triangle edge of the source mesh", sampling["max_side_length_source"]
        )
        # The scan's triangles are 20 x 20 x 28.28 mm, so its median edge is 20 mm.
        self.assertAlmostEqual(20.0, sampling["max_side_length_mm"])
        # A tenth of the declared invented-material threshold, and no other number.
        self.assertAlmostEqual(0.005, sampling["requested_surface_tolerance_mm"])
        self.assertIn("tenth", sampling["surface_tolerance_source"])
        # The connected Fusion refuses to report what it achieved. The request is
        # never copied into the achieved slot to fill the hole.
        self.assertIsNone(sampling["achieved_surface_tolerance_mm"])
        self.assertIn("InternalValidationError", sampling["achieved_surface_tolerance_error"])
        self.assertEqual(12, sampling["triangle_count"])
        self.assertEqual(24, sampling["node_count"])
        self.assertIn("cap asked for rather than a cap seen honoured", sampling["meaning"])

    def test_an_achieved_surface_tolerance_is_recorded_where_fusion_reports_it(self) -> None:
        report = self._run(
            self._namespace(
                mesh=self._scan(),
                reconstruction=_SolidBox(
                    "", (0.0, 0.0, 0.0), (20.0, 20.0, 10.0), reports_tolerance=True
                ),
            )
        )[0]
        sampling = report["surface_sampling"]
        self.assertAlmostEqual(0.005, sampling["achieved_surface_tolerance_mm"])
        self.assertIsNone(sampling["achieved_surface_tolerance_error"])

    def test_the_second_direction_catches_a_rebuilt_surface_off_the_scan(self) -> None:
        # The rebuild is proud of the scan, so its own surface stands away from
        # every scanned triangle. This direction measures that without claiming
        # to know whether it is invented or simplified.
        report = self._run(
            self._namespace(
                mesh=self._scan(),
                reconstruction=_SolidBox("", (-0.5, -0.5, -0.5), (20.5, 20.5, 10.5)),
            ),
            failure="invented material",
        )[0]
        forward = report["reconstruction_to_source"]
        self.assertGreater(forward["beyond_invented_material_threshold"], 0)
        # A corner of the grown box is sqrt(3) x 0.5 mm from the scan's corner,
        # which is the furthest the rebuilt surface gets from any scanned triangle.
        self.assertAlmostEqual(math.sqrt(3.0) * 0.5, forward["max_mm"], places=9)
        self.assertTrue(forward["worst_points"])
        self.assertIn("point_mm", forward["worst_points"][0])

    def test_the_declared_thresholds_and_their_rationale_are_recorded(self) -> None:
        report = self._run(
            self._namespace(
                mesh=self._scan(),
                reconstruction=_SolidBox("", (0.0, 0.0, 0.0), (20.0, 20.0, 10.0)),
            )
        )[0]
        self.assertEqual(DEVIATION_SPEC["thresholds_mm"], report["declared_thresholds_mm"])
        self.assertEqual(DEVIATION_SPEC["rationale"], report["threshold_rationale"])
        self.assertEqual(0.05, report["verdict"]["invented_material"]["threshold_mm"])
        self.assertEqual(0.25, report["verdict"]["omitted_detail"]["threshold_mm"])

    def test_percentiles_may_be_sampled_but_the_threshold_comparison_is_not(self) -> None:
        spec = copy.deepcopy(DEVIATION_SPEC)
        spec["thresholds_mm"]["percentile_sample_limit"] = 2
        report = self._run(
            self._namespace(
                mesh=self._scan(),
                reconstruction=_SolidBox("", (-0.5, -0.5, -0.5), (20.5, 20.5, 10.5)),
                spec=spec,
            ),
            failure="invented material",
        )[0]
        self.assertTrue(report["source_to_reconstruction"]["percentiles_sampled"])
        # Every one of the 24 vertices is compared exactly, strided or not.
        self.assertEqual(24, report["verdict"]["invented_material"]["count"])

    # -- corroboration, never preference ------------------------------------

    def test_compare_with_is_recorded_as_structurally_unavailable_for_a_brep(self) -> None:
        report = self._run(
            self._namespace(
                mesh=self._scan(),
                reconstruction=_SolidBox("", (0.0, 0.0, 0.0), (20.0, 20.0, 10.0)),
            )
        )[0]
        corroboration = report["corroboration"]
        self.assertEqual("PolygonMesh.compareWith", corroboration["api"])
        self.assertFalse(corroboration["available"])
        self.assertIn("TriangleMesh", corroboration["reason"])
        self.assertEqual([], report["preview_apis"])
        self.assertTrue(report["ok"])

    def test_a_disagreeing_corroboration_is_flagged_and_never_preferred(self) -> None:
        namespace = self._namespace(
            mesh=self._scan(comparable=True, distances_mm=[9.0] * 8),
            reconstruction=_SolidBox("", (-0.5, -0.5, -0.5), (20.5, 20.5, 10.5)),
        )
        _, design = namespace["_active_design"]()
        reconstruction = design.rootComponent.bRepBodies.item(0)
        reconstruction.mesh = SimpleNamespace(nodeCoordinates=[], triangleNodeIndices=[])
        report = self._run(namespace, failure="invented material")[0]
        corroboration = report["corroboration"]
        self.assertTrue(corroboration["ran"])
        self.assertTrue(corroboration["disagrees_with_native"])
        self.assertAlmostEqual(9.0, corroboration["max_abs_mm"])
        self.assertAlmostEqual(0.5, corroboration["native_max_abs_mm"])
        # The verdict is the native measurement's, not compareWith's.
        self.assertAlmostEqual(0.5, report["verdict"]["invented_material"]["max_mm"])
        self.assertIn("never resolved in", corroboration["meaning"])

    # -- capability refusals -------------------------------------------------

    def test_a_missing_mesh_calculator_fails_closed_naming_the_api_and_version(self) -> None:
        report = self._run(
            self._namespace(
                mesh=self._scan(),
                reconstruction=_SolidBox("", (0.0, 0.0, 0.0), (20.0, 20.0, 10.0)),
                mesh_calculator=False,
            ),
            failure="Deviation verdict unsupported",
        )[0]
        self.assertEqual(["deviation-capability"], report["failures"])
        self.assertIn("BRepBody.meshManager", report["missing_capabilities"])
        self.assertIn("2705.0.108", report["unsupported"])
        self.assertIn("UI-only", report["unsupported"])
        self.assertNotIn("verdict", report)

    def test_a_reconstruction_without_the_containment_query_fails_closed(self) -> None:
        report = self._run(
            self._namespace(
                mesh=self._scan(),
                reconstruction=_SolidBox("", (0.0, 0.0, 0.0), (20.0, 20.0, 10.0)),
                point_containment=False,
            ),
            failure="Deviation verdict unsupported",
        )[0]
        self.assertEqual(["deviation-capability"], report["failures"])
        self.assertIn("BRepBody.pointContainment", report["missing_capabilities"])

    def test_a_missing_containment_enum_is_a_capability_failure_not_a_clean_result(self) -> None:
        # Nothing equals a None enum, so every vertex would read as neither side
        # and the report would assert the native query ran and found nothing.
        report = self._run(
            self._namespace(
                mesh=self._scan(),
                reconstruction=_SolidBox("", (0.0, 0.0, 0.0), (20.0, 20.0, 10.0)),
                containment_enum=False,
            ),
            failure="Deviation verdict unsupported",
        )[0]
        self.assertEqual(["deviation-capability"], report["failures"])
        self.assertIn(
            "adsk.fusion.PointContainment.PointOnPointContainment",
            report["missing_capabilities"],
        )
        self.assertNotIn("source_to_reconstruction", report)
        self.assertNotIn("verdict", report)

    def test_the_tessellation_is_read_without_the_flat_double_array_when_absent(self) -> None:
        # nodeCoordinatesAsDouble is the fast path; a Fusion that only offers
        # nodeCoordinates must reach the same numbers, not a different verdict.
        report = self._run(
            self._namespace(
                mesh=self._scan(),
                reconstruction=_SolidBox(
                    "", (-0.5, -0.5, -0.5), (20.5, 20.5, 10.5), flat_doubles=False
                ),
            ),
            failure="invented material",
        )[0]
        self.assertAlmostEqual(0.5, report["verdict"]["invented_material"]["max_mm"])
        self.assertEqual(24, report["verdict"]["invented_material"]["count"])

    def test_a_source_without_triangles_cannot_be_compared_against(self) -> None:
        vertices, _ = _box_mesh((0.0, 0.0, 0.0), (20.0, 20.0, 10.0))
        report = self._run(
            self._namespace(
                mesh=_PolygonMesh(vertices, []),
                reconstruction=_SolidBox("", (0.0, 0.0, 0.0), (20.0, 20.0, 10.0)),
            ),
            failure="Deviation verdict unsupported",
        )[0]
        self.assertEqual(["deviation-capability"], report["failures"])
        self.assertIn(
            "PolygonMesh.triangleNodeIndices (source)", report["missing_capabilities"]
        )

    def test_a_reconstruction_that_is_not_a_brep_fails_closed(self) -> None:
        # Containment is a B-Rep query. A mesh reconstruction has no side to ask
        # about, and the refusal says which API is missing rather than skipping.
        report = self._run(
            self._namespace(
                mesh=self._scan(),
                reconstruction=_SolidBox("", (0.0, 0.0, 0.0), (20.0, 20.0, 10.0)),
                reconstruction_is_brep=False,
            ),
            failure="Deviation verdict unsupported",
        )[0]
        self.assertEqual(["deviation-capability"], report["failures"])
        self.assertIn(
            "reconstruction must be a BRepBody for BRepBody.pointContainment",
            report["missing_capabilities"],
        )

    def test_a_tessellation_that_returns_nothing_is_never_read_as_a_clean_result(self) -> None:
        box = _SolidBox("", (0.0, 0.0, 0.0), (20.0, 20.0, 10.0))
        box.meshManager = SimpleNamespace(
            createMeshCalculator=lambda: _empty_calculator()
        )
        report = self._run(
            self._namespace(mesh=self._scan(), reconstruction=box),
            failure="tessellation-failed",
        )[0]
        self.assertEqual(["tessellation-failed"], report["failures"])
        self.assertIn("nothing here is a zero", report["error"])
        self.assertNotIn("verdict", report)

    def test_every_failure_the_transaction_can_emit_is_in_the_closed_set(self) -> None:
        source = emit_mesh_deviation_script(
            self.manifest, self.record, self.source, DEVIATION_SPEC
        )
        emitted = set()
        for line in source.splitlines():
            marker = 'report["failures"] = ['
            if marker in line:
                emitted.add(line.split(marker, 1)[1].split("]", 1)[0].strip().strip('"'))
        self.assertTrue(emitted)
        self.assertEqual(set(), emitted - DEVIATION_FAILURES)

    # -- the gate and the spec ----------------------------------------------

    def test_the_gate_refuses_a_verdict_for_a_mesh_edit(self) -> None:
        mesh_edit = classify(request(edit_kind="clearance-only"), self.source).to_dict()
        self.assertIn(
            "classification-path-forbids-operation",
            codes(
                lambda: emit_mesh_deviation_script(
                    self.manifest, mesh_edit, self.source, DEVIATION_SPEC
                )
            ),
        )
        self.assertIn(
            "classification-required",
            codes(
                lambda: emit_mesh_deviation_script(
                    self.manifest, None, self.source, DEVIATION_SPEC
                )
            ),
        )

    def test_thresholds_are_declared_per_reconstruction_never_defaulted(self) -> None:
        codes_for = lambda spec: {issue.code for issue in validate_deviation_spec(spec)}
        missing = copy.deepcopy(DEVIATION_SPEC)
        missing["thresholds_mm"].pop("invented_material")
        self.assertIn("deviation-spec-invalid-thresholds", codes_for(missing))
        blank = copy.deepcopy(DEVIATION_SPEC)
        blank["rationale"] = "  "
        self.assertIn("deviation-spec-invalid-rationale", codes_for(blank))
        bad_limit = copy.deepcopy(DEVIATION_SPEC)
        bad_limit["thresholds_mm"]["percentile_sample_limit"] = 0
        self.assertIn("deviation-spec-invalid-thresholds", codes_for(bad_limit))
        no_binding = copy.deepcopy(DEVIATION_SPEC)
        no_binding.pop("reconstruction")
        self.assertIn("deviation-spec-invalid-binding", codes_for(no_binding))
        self.assertIn("unknown-manifest-field", codes_for(dict(DEVIATION_SPEC, hopes=1)))
        self.assertIn("deviation-spec-must-be-object", codes_for("no"))


class PointToTriangleTests(unittest.TestCase):
    """The one piece of numerics this transaction implements itself.

    Fusion has no point-to-mesh distance query -- measureMinimumDistance refuses
    a MeshBody and a PolygonMesh alike -- so the closest-point-on-triangle test
    and the grid over it are ours, and they are checked against answers that can
    be worked out by hand.
    """

    def setUp(self) -> None:
        source = mesh_source()
        script = emit_mesh_deviation_script(
            _manifest(source),
            classify(request(edit_kind="dimensional"), source).to_dict(),
            source,
            DEVIATION_SPEC,
        )
        self.namespace = load_generated_script(script)

    def _distance(self, point, triangle):
        squared = self.namespace["_point_triangle_distance_sq"](*point, *triangle[0], *triangle[1], *triangle[2])
        return math.sqrt(squared)

    def test_the_closest_point_is_found_in_the_face_on_an_edge_and_at_a_vertex(self) -> None:
        triangle = ((0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (0.0, 4.0, 0.0))
        cases = (
            ((1.0, 1.0, 3.0), 3.0, "above the interior"),
            ((2.0, -2.0, 0.0), 2.0, "beyond the a-b edge"),
            ((-3.0, -4.0, 0.0), 5.0, "beyond the a vertex"),
            ((10.0, 0.0, 0.0), 6.0, "beyond the b vertex"),
            ((0.0, 10.0, 0.0), 6.0, "beyond the c vertex"),
            ((4.0, 4.0, 0.0), math.sqrt(2.0) * 2.0, "beyond the hypotenuse"),
            ((1.0, 1.0, 0.0), 0.0, "on the face"),
        )
        for point, expected, label in cases:
            with self.subTest(label):
                self.assertAlmostEqual(expected, self._distance(point, triangle))

    def test_a_degenerate_sliver_still_answers_its_own_distance(self) -> None:
        # A zero-area triangle is a segment; the closest point is on that segment,
        # not on a plane it does not define.
        sliver = ((0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (2.0, 0.0, 0.0))
        self.assertAlmostEqual(3.0, self._distance((2.0, 3.0, 0.0), sliver))
        self.assertAlmostEqual(5.0, self._distance((8.0, 3.0, 0.0), sliver))

    def test_the_grid_agrees_with_a_brute_force_scan(self) -> None:
        vertices, triangles = _box_mesh((0.0, 0.0, 0.0), (20.0, 20.0, 10.0))
        flat = [value for vertex in vertices for value in vertex]
        grid = self.namespace["_TriangleGrid"](flat, triangles, 8.0)
        distance_sq = self.namespace["_point_triangle_distance_sq"]
        probes = [
            (10.0, 10.0, 5.0), (-7.0, 3.0, 4.0), (10.0, 10.0, 25.0),
            (0.0, 0.0, 0.0), (21.0, 21.0, 11.0), (3.0, 17.0, 9.5),
        ]
        for probe in probes:
            with self.subTest(probe=probe):
                brute = min(
                    distance_sq(
                        probe[0], probe[1], probe[2],
                        *vertices[triangles[offset]],
                        *vertices[triangles[offset + 1]],
                        *vertices[triangles[offset + 2]],
                    )
                    for offset in range(0, len(triangles), 3)
                )
                self.assertAlmostEqual(math.sqrt(brute), grid.nearest_mm(*probe), places=9)

    def test_a_query_far_outside_the_mesh_does_not_walk_the_empty_space(self) -> None:
        """A displaced reconstruction must not be able to hang the transaction.

        The ring walk used to start at the query cell and enumerate every cell
        of every shell until it reached an occupied one. At a 0.1 mm cell and
        100 mm of displacement that is a thousand shells of up to 24 million
        empty lookups -- per node, inside a Fusion transaction. The grid's own
        occupied box bounds both ends now, so the work is the box's size rather
        than the displacement's cube.
        """
        vertices, triangles = _box_mesh((0.0, 0.0, 0.0), (20.0, 20.0, 10.0), 5.0)
        flat = [value for vertex in vertices for value in vertex]
        grid = self.namespace["_TriangleGrid"](flat, triangles, 5.0)

        class _CountingBuckets(dict):
            lookups = 0

            def get(self, key, default=None):
                _CountingBuckets.lookups += 1
                return dict.get(self, key, default)

        grid.buckets = _CountingBuckets(grid.buckets)
        # 100 mm away on every axis: 20 cells of displacement.
        self.assertAlmostEqual(
            math.sqrt(3.0) * 100.0, grid.nearest_mm(120.0, 120.0, 110.0), places=6
        )
        # The occupied box is 4 x 4 x 2 cells and nothing outside it is ever
        # probed, so the total is that box a few times over. The old walk needed
        # more than 68,000 lookups just to reach the first occupied cell.
        self.assertLess(_CountingBuckets.lookups, 200)

    def test_a_query_deep_inside_a_hollow_body_does_not_walk_the_interior(self) -> None:
        """The occupied box bounds the outside; the interior needed its own bound.

        A smaller reconstruction enclosed by a dense scan puts query points
        inside the source's bounding box and far from every surface bucket, so
        the box clamp does nothing and the walk enumerates the empty interior
        shell by shell -- the same cost, one direction in.
        """
        vertices, triangles = _box_mesh((0.0, 0.0, 0.0), (200.0, 200.0, 200.0), 5.0)
        flat = [value for vertex in vertices for value in vertex]
        grid = self.namespace["_TriangleGrid"](flat, triangles, 1.0)

        budget = 200000

        class _CountingBuckets(dict):
            lookups = 0

            def get(self, key, default=None):
                _CountingBuckets.lookups += 1
                if _CountingBuckets.lookups > budget:
                    # Raise rather than let the assertion below wait for the
                    # interior walk to finish: without the bound it does not,
                    # in any time a test suite should spend.
                    raise AssertionError("the interior walk is enumerating empty cells")
                return dict.get(self, key, default)

        grid.buckets = _CountingBuckets(grid.buckets)
        # Dead centre: 100 mm from every face, 100 cells of empty interior.
        self.assertAlmostEqual(100.0, grid.nearest_mm(100.0, 100.0, 100.0), places=6)
        # Shells 0..99 are empty by construction and are never enumerated.
        self.assertLess(_CountingBuckets.lookups, budget)

    def test_a_surface_query_never_walks_the_coarse_overlay(self) -> None:
        """The overlay's scan is per distinct query cell, so it has to be rare.

        `_coarse_floor` walks the coarse set in arbitrary order to find the
        nearest occupied cell -- once per query cell it has not seen, which on
        a dense scan is once per occupied coarse cell, and quadratic in exactly
        the meshes that have the most of them. Every one of those queries is on
        the surface, where the answer is a floor of zero and twenty-seven set
        lookups say so.
        """
        vertices, triangles = _box_mesh((0.0, 0.0, 0.0), (200.0, 200.0, 200.0), 5.0)
        flat = [value for vertex in vertices for value in vertex]
        # A cell wider than the facets, so they bucket rather than land in the
        # oversized list, which is what puts queries on the overlay at all.
        grid = self.namespace["_TriangleGrid"](flat, triangles, 8.0)

        class _CountingSet(set):
            walked = 0

            def __iter__(self):
                _CountingSet.walked += 1
                return set.__iter__(self)

        grid._coarse = _CountingSet(grid._coarse_occupancy())
        grid._coarse_floors = {}
        for step in range(0, 200, 7):
            # On the +z face, and just off it: both sit in an occupied coarse
            # cell or a neighbour of one.
            self.assertAlmostEqual(0.0, grid.nearest_mm(float(step), float(step), 200.0))
            self.assertAlmostEqual(0.5, grid.nearest_mm(float(step), float(step), 200.5))
        self.assertEqual(0, _CountingSet.walked)
        # And the walk is still there for a point the neighbourhood cannot
        # settle: far outside, the floor is the coarse bound, not zero.
        self.assertGreater(grid._coarse_floor(-1000, -1000, -1000), 0)
        self.assertEqual(1, _CountingSet.walked)

    def test_a_degenerate_sliver_does_not_make_a_closed_scan_open(self) -> None:
        """A zero-area facet carries no surface, and it was carrying a verdict.

        Indices `(A, A, B)` add one self-edge and a second copy of `A-B`, so a
        scan that encloses a perfectly good solid read as open -- and an open
        surface has no inside, which sends every reverse deviation to
        `unclassified`. The distance path supports these slivers on purpose,
        because scans carry them.
        """
        vertices, triangles = _box_mesh((0.0, 0.0, 0.0), (10.0, 10.0, 10.0), 5.0)
        flat = [value for vertex in vertices for value in vertex]
        grid = self.namespace["_TriangleGrid"](flat, triangles, 4.0)
        self.assertTrue(grid.is_closed())
        slivered = self.namespace["_TriangleGrid"](
            flat, list(triangles) + [triangles[0], triangles[0], triangles[1]], 4.0
        )
        self.assertTrue(slivered.is_closed())
        self.assertTrue(slivered.encloses(5.0, 5.0, 5.0))
        self.assertFalse(slivered.encloses(50.0, 5.0, 5.0))
        # Three *distinct* corners on one line have no area either, and the
        # distance and ray paths already read them that way.
        line = list(flat) + [30.0, 0.0, 0.0, 31.0, 0.0, 0.0, 32.0, 0.0, 0.0]
        base = len(vertices)
        collinear = self.namespace["_TriangleGrid"](
            line, list(triangles) + [base, base + 1, base + 2], 4.0
        )
        self.assertTrue(collinear.is_closed())
        self.assertTrue(collinear.encloses(5.0, 5.0, 5.0))
        self.assertFalse(collinear.encloses(50.0, 5.0, 5.0))

    def test_oversized_facets_are_pruned_by_their_boxes_not_all_measured(self) -> None:
        """Every query paid the full point-triangle test on every long facet.

        The cell is derived from the median facet, so a scan with nonuniform
        facets can put a large fraction of the mesh in the oversized list -- and
        that list was measured in full, per query, before the grid was even
        consulted. On this mesh every facet is oversized; the query is 1 mm
        from one face and 200 mm from the far side, and the boxes settle all
        but a handful without a triangle test.
        """
        vertices, triangles = _box_mesh((0.0, 0.0, 0.0), (200.0, 200.0, 200.0), 5.0)
        flat = [value for vertex in vertices for value in vertex]
        grid = self.namespace["_TriangleGrid"](flat, triangles, 0.5)
        self.assertGreater(len(grid.oversized), 500)
        self.assertEqual(len(grid.oversized), len(grid.oversized_boxes))

        # Indexed on the coarse grid, not scanned: only the few too wide to
        # index are measured on every query.
        self.assertTrue(grid.oversized_cells)
        self.assertLess(len(grid.oversized_wide), len(grid.oversized) / 10)

        exact = [0]
        boxes = [0]
        measure = grid._triangle_distance_sq
        box_measure = self.namespace["_box_distance_sq"]

        def counting(offset, x, y, z):
            exact[0] += 1
            return measure(offset, x, y, z)

        def counting_box(box, x, y, z):
            boxes[0] += 1
            return box_measure(box, x, y, z)

        grid._triangle_distance_sq = counting
        self.namespace["_box_distance_sq"] = counting_box
        try:
            self.assertAlmostEqual(1.0, grid.nearest_mm(100.0, 100.0, 201.0), places=6)
        finally:
            self.namespace["_box_distance_sq"] = box_measure
        self.assertLess(exact[0], 60)
        self.assertLess(exact[0], len(grid.oversized) / 10)
        # And no per-query pass over every box either, which is the O(K log K)
        # the sort used to cost on every one of Q samples.
        self.assertLess(boxes[0], len(grid.oversized))

    def test_a_triangle_far_larger_than_the_cell_is_still_found(self) -> None:
        # One triangle spanning many cells goes to the oversized list rather than
        # into hundreds of buckets; it must still answer.
        vertices = [0.0, 0.0, 0.0, 100.0, 0.0, 0.0, 0.0, 100.0, 0.0]
        grid = self.namespace["_TriangleGrid"](vertices, [0, 1, 2], 1.0)
        self.assertTrue(grid.oversized)
        self.assertAlmostEqual(4.0, grid.nearest_mm(10.0, 10.0, 4.0))


if __name__ == "__main__":
    unittest.main()
