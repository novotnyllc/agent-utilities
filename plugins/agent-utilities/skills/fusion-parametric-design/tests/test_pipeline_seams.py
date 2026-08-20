"""Every stage boundary of the reconstruction pipeline, producer against consumer.

The rest of the suite tests each stage against a *fixture* of its input.  A
fixture is written by whoever is testing the consumer, which means it is shaped
like the consumer's expectation rather than like the producer's output -- and
when the two disagree, every test passes and the pipeline has never run.  That
is exactly what happened: `fit-regions` wrote `topology.total_area` and
`plan-reconstruction` read `total_area`, so the real CLI refused every real
record with `fit-record-malformed`, and 861 tests said nothing because
`fixtures_fit_record` hand-builds the top-level key.

So nothing here builds a record by hand.  Each test takes the *actual output* of
one stage and feeds it to the next, and the chain runs from a mesh dump all the
way to a coverage account.  The in-Fusion stages run their emitted source
against the Fusion doubles, which is as real as this gets offline.
"""

from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
import io
import json
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
from typing import Any, ClassVar
import unittest

from fusion_design.cli import main
from fusion_design import mesh_fitting as mf
from fusion_design import reconstruction_program as rp
from fusion_design.mesh_datum import (
    ReconstructionRefused,
    derive_datum_frame,
    parse_fit_record,
)
from fusion_design.mesh_dump import pack_mesh_dump, read_mesh_dump
from fusion_design.mesh_extract import emit_mesh_extract_script
from fusion_design.mesh_face_groups import emit_mesh_face_groups_script
from fusion_design.mesh_reconstruction import classify
from fusion_design.mesh_editability import (
    emit_mesh_editability_script,
    validate_editability_report,
)
from fusion_design.mesh_rebuild import emit_mesh_rebuild_script, plan_emission, replan_without
from fusion_design.reconstruction_coverage import compose_coverage
from fusion_design.reconstruction_program import build_reconstruction_program
from fusion_design import mesh_segmentation as seg

import fakes_fusion_rebuild as fakes
import fixtures_fit_record as fxr
import fixtures_rebuild as fx
import test_mesh_editability as te
import test_mesh_extract as tme
import test_mesh_face_groups as tfg
import test_mesh_reconstruction as tmr
import test_mesh_source as tms
from test_scripts import load_generated_script
import test_mesh_segmentation as ts
from test_mesh_rebuild import (
    NONCE,
    _dump_bytes,
    _manifest_hash,
    build_manifest,
    classification_record,
    run_transaction,
    source_record,
)


EDITABILITY_NONCE = "fedcba9876543210fedcba9876543210"


def brick_dump():
    """A closed, welded 10 x 20 x 15 box: six planes, every answer known.

    Deliberately not a cube.  Three distinct face areas give the datum frame an
    unambiguous primary and secondary axis, so the run reaches the archetypes
    instead of refusing `frame-ambiguous` on a tie.
    """
    vertices, triangles, groups = ts.box_mesh(size=20.0, divisions=6)
    return ts.make_dump(
        [(x * 0.5, y, z * 0.75) for x, y, z in vertices], triangles, face_groups=groups
    )


def fitted(dump=None):
    """The real fit record `fit-regions` writes for the brick."""
    return seg.fit_regions(dump or brick_dump(), ts.spec())


def planned(record, manifest):
    return build_reconstruction_program(
        parse_fit_record(record), fxr.spec(), manifest_sha256=_manifest_hash(manifest)
    )


class FitToPlanSeamTests(unittest.TestCase):
    """`fit-regions` output, read by `plan-reconstruction`. No fixture record."""

    def setUp(self):
        self.record = fitted()

    def test_the_record_carries_the_total_area_the_planner_reads(self) -> None:
        # The regression that started this: the key lived one level down inside
        # the `topology` diagnostic block, and `parse_fit_record` refused.
        fit = parse_fit_record(self.record)
        self.assertGreater(fit.total_area, 0.0)
        self.assertAlmostEqual(1300.0, fit.total_area, places=6)

    def test_the_record_carries_the_uncertainty_names_the_planner_licenses_from(self) -> None:
        # The fitter's own parameterization is local (`tilt_u`, `tilt_v`,
        # `offset`); U3 licenses relationships against scalar magnitudes per kind.
        # The two vocabularies overlapped on one name per kind, so every accepted
        # region was refused `fit-record-missing-uncertainty`.
        for region in self.record["regions"]:
            if not region["accepted"]:
                continue
            self.assertIn("normal_deg", region["fit"]["uncertainty"], region["region_hash"])
            self.assertIn("offset", region["fit"]["uncertainty"], region["region_hash"])

    def test_a_real_fit_record_plans_a_real_reconstruction_program(self) -> None:
        program = planned(self.record, build_manifest())
        self.assertEqual([g["kind"] for g in program["archetypes"]], ["sketch-extrude"])
        self.assertAlmostEqual(1.0, program["covered_area_fraction"], places=6)
        self.assertAlmostEqual(
            program["covered_area_fraction"],
            sum(g["area_fraction"] for g in program["archetypes"]),
            places=6,
        )

    def test_the_regime_the_fitter_measured_reaches_the_program(self) -> None:
        """Producer against consumer, so the two cannot drift on this block either.

        `fit-regions` detects the regime and every noise floor it applied hangs
        off that verdict; the program is what a rebuild is judged against. The
        block was written and then dropped at `parse_fit_record`, so no fixture
        on either side could have caught it.
        """
        program = planned(self.record, build_manifest())
        self.assertEqual("tessellation", self.record["regime"]["regime"])
        self.assertEqual(
            {"regime": "tessellation", "declared": "auto", "overridden": False},
            program["regime"],
        )

    def test_the_two_clis_connect_through_files_on_disk(self) -> None:
        """The seam as a user runs it: one command's output file, the next's input."""
        dump = brick_dump()
        manifest_path = str(Path(__file__).resolve().parents[1] / "examples" / "electronics-enclosure" / "fusion-project.json")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "mesh.bin").write_bytes(_dump_bytes(dump))
            (root / "detection.json").write_text(
                json.dumps(
                    {
                        name: {"value": value, "rationale": why}
                        for name, (value, why) in ts.REFERENCE.items()
                    }
                ),
                encoding="utf-8",
            )
            (root / "program-spec.json").write_text(json.dumps(fxr.spec()), encoding="utf-8")
            code = main(
                [
                    "fit-regions",
                    str(root / "mesh.bin"),
                    "--dump-sha256",
                    dump.sha256,
                    "--spec",
                    str(root / "detection.json"),
                    "-o",
                    str(root / "fit-record.json"),
                ]
            )
            self.assertEqual(0, code)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "plan-reconstruction",
                        manifest_path,
                        "--fit-record",
                        str(root / "fit-record.json"),
                        "--program-spec",
                        str(root / "program-spec.json"),
                        "-o",
                        str(root / "program.json"),
                    ]
                )
            self.assertEqual(0, code, output.getvalue())
            program = json.loads((root / "program.json").read_text(encoding="utf-8"))
            self.assertEqual(dump.sha256, program["dump_sha256"])
            self.assertTrue(program["archetypes"])


class GroupingToFitSeamTests(unittest.TestCase):
    """The new first seam: Fusion groups the mesh, extraction carries the grouping.

    Both transactions are the real emitted source, run against Fusion doubles.
    The face-group transaction applies the grouping to the body; the extraction
    transaction reads whatever grouping the body carries and writes the dump;
    `fit-regions` reads that dump off disk and fits it. No fixture record and no
    hand-built grouping crosses any of those boundaries -- which is the point,
    because the grouping *is* the segmentation now.
    """

    def setUp(self) -> None:
        self.source = tms.mesh_source(provenance="designed_export")
        self.manifest = tmr._manifest(self.source)
        self.classification = classify(tmr.request(edit_kind="dimensional"), self.source).to_dict()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        # The brick, in Fusion's internal centimetres, with the analytic grouping
        # the accurate method returns for it.
        vertices, triangles, groups = ts.box_mesh(size=20.0, divisions=6)
        self.vertices_cm = [(x * 0.05, y * 0.1, z * 0.075) for x, y, z in vertices]
        self.triangles = triangles
        self.groups = groups

    def _body(self):
        return tfg._Bodies, tfg._Features

    def _run(self, script, body, *, failure=None):
        namespace = load_generated_script(script)
        component = SimpleNamespace(
            meshBodies=tfg._Bodies([body]),
            features=SimpleNamespace(meshGenerateFaceGroupsFeatures=body._features),
        )
        design = SimpleNamespace(rootComponent=component)
        app = SimpleNamespace(
            version="2.0.20000",
            activeDocument=SimpleNamespace(name=self.manifest.fusion_document),
        )
        namespace["_active_design"] = lambda: (app, design)
        namespace["_root_context_occurrence_map"] = lambda root: ([], {}, {})
        output = io.StringIO()
        with redirect_stdout(output):
            namespace["run"](None)
        return [
            json.loads(line)
            for line in output.getvalue().splitlines()
            if line.startswith("{")
        ]

    def _mesh_body(self):
        """A mesh body whose grouping does not exist until the feature applies it."""

        class _Mesh:
            triangleCount = len(self.triangles)
            triangleFaceGroupTempIds = None
            nodeCoordinates = [
                SimpleNamespace(x=p[0], y=p[1], z=p[2]) for p in self.vertices_cm
            ]
            triangleNodeIndices = [i for t in self.triangles for i in t]

        mesh = _Mesh()
        groups = self.groups

        class _Applying(tfg._Features):
            def add(self, group_input):
                self.added_with = group_input.meshGenerateFaceGroupsMethodType
                # Fusion's own temp ids: arbitrary, not zero-based, not stable.
                mesh.triangleFaceGroupTempIds = [40 + 3 * g for g in groups]
                return None

        body = SimpleNamespace(
            name=self.source["body_name"] if "body_name" in self.source else "bracket_scan",
            mesh=mesh,
            isValid=True,
            faceGroups=tfg._Bodies([]),
            transform=SimpleNamespace(
                asArray=lambda: [
                    1.0, 0.0, 0.0, 0.0,
                    0.0, 1.0, 0.0, 0.0,
                    0.0, 0.0, 1.0, 0.0,
                    0.0, 0.0, 0.0, 1.0,
                ]
            ),
        )
        body._features = _Applying(mesh)
        return body

    def _extract_spec(self):
        spec = dict(tme.EXTRACT_SPEC)
        spec["body_name"] = "bracket_scan"
        spec["dump_dir"] = str(self.root / "dumps")
        return spec

    def test_extraction_without_the_grouping_stage_produces_a_dump_that_refuses(self) -> None:
        """The reason the two stages are ordered, stated as a run rather than a comment."""
        body = self._mesh_body()
        report = self._run(
            emit_mesh_extract_script(
                self.manifest, self.classification, self.source, self._extract_spec()
            ),
            body,
        )[0]
        self.assertTrue(report["ok"], report)
        self.assertEqual("absent", report["face_groups"]["source"])
        dump = read_mesh_dump(report["dump_path"], report["dump_sha256"])
        record = seg.fit_regions(dump, ts.spec())
        self.assertEqual("face-groups-absent", record["refusal"]["reason"])
        self.assertIn("emit-mesh-face-groups", record["refusal"]["alternative"])

    def test_the_grouping_transaction_feeds_extraction_which_feeds_the_fitters(self) -> None:
        body = self._mesh_body()
        grouping = self._run(
            emit_mesh_face_groups_script(
                self.manifest,
                self.classification,
                self.source,
                {"component_path": "", "body_name": "bracket_scan"},
            ),
            body,
        )[0]
        self.assertTrue(grouping["ok"], grouping)
        self.assertEqual("AccurateGenerateFaceGroupsType", grouping["applied_method"])
        self.assertEqual(6, grouping["group_count"])

        extraction = self._run(
            emit_mesh_extract_script(
                self.manifest, self.classification, self.source, self._extract_spec()
            ),
            body,
        )[0]
        self.assertTrue(extraction["ok"], extraction)
        self.assertEqual("triangleFaceGroupTempIds", extraction["face_groups"]["source"])
        # The grouping the first transaction applied is the grouping the second
        # one wrote, group for group.
        self.assertEqual(
            grouping["triangles_per_group"], extraction["face_groups"]["histogram"]
        )

        dump = read_mesh_dump(extraction["dump_path"], extraction["dump_sha256"])
        record = seg.fit_regions(dump, ts.spec())
        self.assertIsNone(record["refusal"], record["refusal"])
        self.assertEqual(6, record["face_groups"]["group_count"])
        self.assertEqual(
            ["plane"] * 6, sorted(r["fit"]["kind"] for r in record["regions"] if r["accepted"])
        )
        self.assertAlmostEqual(1.0, record["covered_area_fraction"], places=6)
        # Fusion's temp ids are temp ids. They partitioned the triangles and then
        # stopped existing: nothing in the record is keyed by, or carries, one.
        payload = json.dumps(record)
        self.assertNotIn("temp_id", payload)
        self.assertNotIn("tempId", payload)
        # Re-numbering every group without moving a triangle leaves the same
        # partition, which is the property the hash has to have.
        renumbered = ts.make_dump(
            [tuple(c * 10.0 for c in p) for p in self.vertices_cm],
            self.triangles,
            face_groups=[900 - 5 * g for g in self.groups],
            **{
                key: dump.metadata[key]
                for key in ("mesh_source_id", "mesh_source_sha256", "manifest_sha256")
            },
        )
        again = seg.fit_regions(renumbered, ts.spec())
        self.assertEqual(
            sorted(sorted(r["triangle_indices"]) for r in record["regions"]),
            sorted(sorted(r["triangle_indices"]) for r in again["regions"]),
        )

        # And the record a real grouping produced plans a real program.
        program = planned(record, self.manifest)
        self.assertEqual(["sketch-extrude"], [g["kind"] for g in program["archetypes"]])
        self.assertEqual(dump.sha256, program["dump_sha256"])

    def test_a_grouping_that_did_not_stick_never_reaches_a_dump(self) -> None:
        """Fast is the default, so a method that did not apply must stop the run."""
        body = self._mesh_body()

        class _Stubborn(tfg._Features):
            def createInput(self, mesh_body):
                return tfg._Input(keeps=False)

        body._features = _Stubborn(body.mesh)
        namespace = load_generated_script(
            emit_mesh_face_groups_script(
                self.manifest,
                self.classification,
                self.source,
                {"component_path": "", "body_name": "bracket_scan"},
            )
        )
        component = SimpleNamespace(
            meshBodies=tfg._Bodies([body]),
            features=SimpleNamespace(meshGenerateFaceGroupsFeatures=body._features),
        )
        design = SimpleNamespace(rootComponent=component)
        app = SimpleNamespace(
            version="2.0.20000",
            activeDocument=SimpleNamespace(name=self.manifest.fusion_document),
        )
        namespace["_active_design"] = lambda: (app, design)
        namespace["_root_context_occurrence_map"] = lambda root: ([], {}, {})
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(RuntimeError):
            namespace["run"](None)
        report = [
            json.loads(line)
            for line in output.getvalue().splitlines()
            if line.startswith("{")
        ][0]
        self.assertEqual(["face-group-method-not-applied"], report["failures"])
        self.assertIsNone(body.mesh.triangleFaceGroupTempIds)


class NormalsAcrossTheDumpSeamTests(GroupingToFitSeamTests):
    """The facet data the new fitting path needs has to survive the dump.

    Nothing in the dump carries a normal. The fitters reconstruct every facet
    normal, centroid and area from `triangleNodeIndices` and the node
    coordinates, host-side, after welding -- so a winding the extraction
    transaction reordered, or a weld that collapsed the wrong node, would silently
    produce normals that point somewhere else and an axis determined from them
    would be confidently wrong. This runs the real grouping and extraction
    transactions over a shallow two-ring bore and checks the axis that comes out
    the far end, because that is the only place the round trip is actually tested.
    """

    def setUp(self) -> None:
        super().setUp()
        # The brick, plus a shallow tube standing beside it. One stack: two rings
        # of vertices and nothing between them, which is how a solid modeller
        # tessellates a shallow bore -- and the shape that 85 face groups across
        # 11 production STLs were refused for. The brick is there because the
        # grouping transaction refuses a body it can only find one group in, and
        # one group over a whole body is not a segmentation.
        brick_v, brick_t, brick_g = ts.box_mesh(size=20.0, divisions=6)
        tube_v, tube_t, _tube_g = ts.cylinder_mesh(radius=5.0, height=2.0, sides=48, stacks=1)
        offset = len(brick_v)
        self.vertices_cm = [(x * 0.1, y * 0.1, z * 0.1) for x, y, z in brick_v] + [
            ((x + 60.0) * 0.1, y * 0.1, z * 0.1) for x, y, z in tube_v
        ]
        self.triangles = list(brick_t) + [tuple(i + offset for i in t) for t in tube_t]
        self.groups = list(brick_g) + [max(brick_g) + 1] * len(tube_t)

    def _run_both(self):
        body = self._mesh_body()
        grouping = self._run(
            emit_mesh_face_groups_script(
                self.manifest,
                self.classification,
                self.source,
                {"component_path": "", "body_name": "bracket_scan"},
            ),
            body,
        )[0]
        self.assertTrue(grouping["ok"], grouping)
        extraction = self._run(
            emit_mesh_extract_script(
                self.manifest, self.classification, self.source, self._extract_spec()
            ),
            body,
        )[0]
        self.assertTrue(extraction["ok"], extraction)
        return read_mesh_dump(extraction["dump_path"], extraction["dump_sha256"])

    def test_extraction_without_the_grouping_stage_produces_a_dump_that_refuses(self) -> None:
        super().test_extraction_without_the_grouping_stage_produces_a_dump_that_refuses()

    def test_a_grouping_that_did_not_stick_never_reaches_a_dump(self) -> None:
        super().test_a_grouping_that_did_not_stick_never_reaches_a_dump()

    def test_the_grouping_transaction_feeds_extraction_which_feeds_the_fitters(self) -> None:
        """Overridden: this fixture is one group, so the brick's assertions do not apply."""
        dump = self._run_both()
        record = seg.fit_regions(dump, ts.spec())
        self.assertIsNone(record["refusal"], record["refusal"])
        self.assertEqual(7, record["face_groups"]["group_count"])

    def test_the_bore_survives_the_dump_and_takes_its_axis_from_the_facets(self) -> None:
        dump = self._run_both()
        record = seg.fit_regions(dump, ts.spec())
        self.assertIsNone(record["refusal"], record["refusal"])
        cylinders = [
            r for r in record["regions"] if r["accepted"] and r["fit"]["kind"] == "cylinder"
        ]
        self.assertTrue(cylinders, record["unfitted_regions"])
        fit = cylinders[0]["fit"]
        support = fit["support"]
        self.assertEqual("facet-normals", support["axis_evidence"]["source"])
        # The reconstructed normals put the axis on z to float precision. A dump
        # that had lost the winding would put it anywhere.
        self.assertAlmostEqual(1.0, abs(fit["parameters"]["axis_direction"][2]), places=9)
        self.assertAlmostEqual(5.0, fit["parameters"]["radius"], places=6)
        self.assertAlmostEqual(0.5, support["axis_evidence"]["eigengap"], places=6)
        # And the boundary the grouping left behind agrees with it, independently.
        self.assertAlmostEqual(5.0, support["boundary_circle"]["loop_radius"], places=6)
        self.assertIsNone(support["boundary_circle"]["flag"])

    def test_the_record_the_new_path_produces_still_parses_for_the_planner(self) -> None:
        """The uncertainty names U3 licenses from are the ones the joint system writes."""
        dump = self._run_both()
        record = seg.fit_regions(dump, ts.spec())
        parsed = parse_fit_record(record)
        cylinder = [r for r in parsed.regions if r.accepted and r.fit.kind == "cylinder"][0]
        for key in ("axis_direction_deg", "axis_point", "radius"):
            self.assertIsNotNone(cylinder.sigma(key), key)
        # The axis sigma the planner reads is the joint one, not the vertex one.
        raw = next(
            r for r in record["regions"] if r["region_hash"] == cylinder.region_hash
        )
        self.assertEqual(
            raw["fit"]["support"]["axis_evidence"]["axis_tilt_sigma_deg"],
            cylinder.sigma("axis_direction_deg"),
        )
        self.assertNotEqual(
            raw["fit"]["uncertainty"]["axis_tilt_vertices_deg"],
            cylinder.sigma("axis_direction_deg"),
        )


class PrismAcrossTheDumpSeamTests(NormalsAcrossTheDumpSeamTests):
    """A hexagonal pocket and a real bore, side by side, through the real transactions.

    The measured failure: on the honeycomb organiser six hexagonal pockets came
    back as six round bores of radius 15*cos(30), because a regular hexagon's six
    corners lie *exactly* on that circle -- so the vertex fit is exact and every
    gate that reads vertices passes it. Only the facet normals separate the two,
    and the normals are reconstructed host-side from `triangleNodeIndices` after
    welding, which is why this belongs at the dump seam rather than in a unit
    test: a winding the extraction reordered would hand the same six spikes back
    in a different order and the discrimination would silently stop working.

    The bore beside it is the control. Both live in the same dump, both reach the
    fitters through the same two emitted transactions, and the assertion is that
    one is refused by name and the other is not touched.
    """

    def setUp(self) -> None:
        super().setUp()
        brick_v, brick_t, brick_g = ts.box_mesh(size=20.0, divisions=6)
        bore_v, bore_t, _g = ts.cylinder_mesh(radius=5.0, height=2.0, sides=48, stacks=1)
        hex_v, hex_t, _g = ts.cylinder_mesh(radius=5.0, height=6.0, sides=6, stacks=3)
        bore_at = len(brick_v)
        hex_at = bore_at + len(bore_v)
        self.vertices_cm = (
            [(x * 0.1, y * 0.1, z * 0.1) for x, y, z in brick_v]
            + [((x + 60.0) * 0.1, y * 0.1, z * 0.1) for x, y, z in bore_v]
            + [((x + 60.0) * 0.1, (y + 40.0) * 0.1, z * 0.1) for x, y, z in hex_v]
        )
        self.triangles = (
            list(brick_t)
            + [tuple(i + bore_at for i in t) for t in bore_t]
            + [tuple(i + hex_at for i in t) for t in hex_t]
        )
        self.groups = (
            list(brick_g)
            + [max(brick_g) + 1] * len(bore_t)
            + [max(brick_g) + 2] * len(hex_t)
        )

    def test_the_grouping_transaction_feeds_extraction_which_feeds_the_fitters(self) -> None:
        """Overridden: this fixture carries the brick's six faces plus two pockets."""
        record = seg.fit_regions(self._run_both(), ts.spec())
        self.assertIsNone(record["refusal"], record["refusal"])
        self.assertEqual(8, record["face_groups"]["group_count"])

    def _pockets(self):
        record = seg.fit_regions(self._run_both(), ts.spec())
        self.assertIsNone(record["refusal"], record["refusal"])
        by_count = {r["triangle_count"]: r for r in record["regions"]}
        self.assertIn(96, by_count, sorted(by_count))
        self.assertIn(36, by_count, sorted(by_count))
        return record, by_count[96], by_count[36]

    def test_the_hexagonal_pocket_is_refused_by_name_across_the_real_dump(self) -> None:
        _record, _bore, pocket = self._pockets()
        self.assertFalse(pocket["accepted"])
        self.assertIn("cylinder-normals-discrete", pocket["fit"]["rejection"])
        spread = pocket["fit"]["support"]["normal_direction_spread"]
        self.assertEqual(6, spread["directions"])
        self.assertEqual(36, spread["facet_count"])
        self.assertLess(spread["directions_per_turn"], spread["min_directions_per_turn"])
        # And it claims nothing while refusing: the radius it would have reported
        # is the hexagon's circumradius, which is what made this invisible to
        # every vertex-side gate in the first place.
        self.assertEqual({}, pocket["fit"]["parameters"])

    def test_the_bore_in_the_same_dump_is_untouched_by_the_gate(self) -> None:
        _record, bore, _pocket = self._pockets()
        self.assertTrue(bore["accepted"], bore["fit"].get("rejection"))
        self.assertEqual("cylinder", bore["fit"]["kind"])
        self.assertAlmostEqual(5.0, bore["fit"]["parameters"]["radius"], places=6)
        spread = bore["fit"]["support"]["normal_direction_spread"]
        self.assertEqual(48, spread["directions"])
        self.assertIn("cylinder-normals-discrete", bore["fit"]["support"]["checked"])

    def test_the_refused_pocket_survives_the_seam_as_a_refusal(self) -> None:
        """It has to reach the planner as unclaimed area, not vanish from the record."""
        record, _bore, pocket = self._pockets()
        parsed = parse_fit_record(record)
        self.assertNotIn(
            pocket["region_hash"], {r.region_hash for r in parsed.regions if r.accepted}
        )
        self.assertIn(pocket["region_hash"], {r.region_hash for r in parsed.regions})


class LoopEvidenceSeamTests(unittest.TestCase):
    """The loop verdict, traced from a real dump's triangles to a real fit record.

    Nothing here is hand-built: the dump is the one `fit-regions` fitted, the
    region hashes on the loop's walls are that record's own, and the station is
    the program's own mid-station. The reason it belongs across the seam rather
    than in the fitting module's synthetic tests is that the verdict rests on the
    dump's *winding* -- a winding the extraction reordered, or a weld that
    collapsed the wrong node, would produce a confidently wrong answer that no
    synthetic mesh built alongside the classifier could ever catch.
    """

    @classmethod
    def setUpClass(cls):
        cls.manifest = build_manifest()
        cls.dump = brick_dump()
        cls.record = fitted(cls.dump)
        cls.program = planned(cls.record, cls.manifest)

    def _mesh(self):
        flat, index = self.dump.vertices_mm, self.dump.triangles
        return (
            [tuple(flat[i : i + 3]) for i in range(0, len(flat), 3)],
            [tuple(index[i : i + 3]) for i in range(0, len(index), 3)],
        )

    def _station(self):
        group = self.program["archetypes"][0]
        axis = {"XY": "z_axis", "YZ": "x_axis", "XZ": "y_axis"}[group["plane"]["datum_plane"]]
        normal = tuple(float(v) for v in self.program["datum"][axis])
        origin = tuple(float(v) for v in self.program["datum"]["origin"])
        station = float(group["plane"]["offset"]) + float(group["extent"]["value"]) / 2.0
        return mf._add(origin, mf._scale(normal, station)), normal

    def _evidence(self, verts, tris, regions=None):
        point, normal = self._station()
        section = mf.section_mesh(verts, tris, point, normal, tolerance=1e-9)
        return mf.loop_material_evidence(
            section,
            verts,
            tris,
            normal,
            consensus_fraction=0.95,
            attribution_min_fraction=0.05,
            triangle_regions=regions,
        )

    def _regions(self):
        return {
            int(index): region["region_hash"]
            for region in self.record["regions"]
            for index in region["triangle_indices"]
        }

    def test_the_brick_reads_as_material_inside_its_own_outline(self) -> None:
        verts, tris = self._mesh()
        evidence = self._evidence(verts, tris, self._regions())
        self.assertTrue(evidence["winding"]["closed"])
        self.assertTrue(evidence["winding"]["consistently_wound"])
        self.assertEqual("outward", evidence["winding"]["winding"])
        self.assertEqual(1, evidence["closed_loop_count"])
        loop = evidence["loops"][0]
        self.assertEqual("material-inside", loop["verdict"])
        self.assertEqual(1.0, loop["consensus_fraction"])
        self.assertEqual(0, loop["depth"])
        self.assertTrue(loop["parity_agrees"])
        self.assertEqual([], evidence["gates"])

    def test_the_walls_it_names_are_this_records_own_regions(self) -> None:
        verts, tris = self._mesh()
        loop = self._evidence(verts, tris, self._regions())["loops"][0]
        hashes = {region["region_hash"] for region in self.record["regions"]}
        self.assertTrue(loop["wall_regions"])
        self.assertTrue(set(loop["wall_regions"]) <= hashes)
        # Four walls: a mid-station section of a box crosses its four sides and
        # neither of its caps.
        self.assertEqual(4, len(loop["wall_regions"]))

    def test_the_same_dump_wound_the_other_way_gives_the_same_verdict(self) -> None:
        # The verdict is about the material, not about the exporter's winding
        # convention, so reversing every triangle of the real dump must not move
        # it -- only the licence's own reported direction.
        verts, tris = self._mesh()
        flipped = [(c, b, a) for a, b, c in tris]
        outward = self._evidence(verts, tris)["loops"][0]
        inward = self._evidence(verts, flipped)["loops"][0]
        self.assertEqual("inward", mf.mesh_winding_evidence(verts, flipped)["winding"])
        self.assertEqual(outward["verdict"], inward["verdict"])
        self.assertEqual(outward["consensus_fraction"], inward["consensus_fraction"])
        self.assertEqual(outward["parity_agrees"], inward["parity_agrees"])

    def test_one_wall_inverted_in_the_real_dump_reaches_contradictory(self) -> None:
        verts, tris = self._mesh()
        point, normal = self._station()
        # The triangles this station's own loop was cut from, named by the
        # section itself rather than re-derived: whichever way the brick's
        # tessellation happens to meet the plane, these are its walls.
        loop = mf.section_mesh(verts, tris, point, normal, tolerance=1e-9).polylines[0]
        producers = sorted({t for entry in loop.segment_triangles for t in entry})
        self.assertGreater(len(producers), 4)
        broken = list(tris)
        for index in producers[: max(1, len(producers) // 4)]:
            broken[index] = tuple(reversed(broken[index]))
        evidence = self._evidence(verts, broken)
        self.assertTrue(evidence["winding"]["closed"])
        self.assertFalse(evidence["winding"]["consistently_wound"])
        loop = evidence["loops"][0]
        self.assertEqual("contradictory", loop["verdict"])
        self.assertLess(loop["consensus_fraction"], 0.95)
        self.assertIn("loop-material-contradictory", evidence["gates"])

    def test_a_torn_dump_stops_at_the_orientation_gate_before_any_verdict(self) -> None:
        verts, tris = self._mesh()
        evidence = self._evidence(verts, tris[:-2])
        self.assertFalse(evidence["winding"]["closed"])
        self.assertEqual(["loop-orientation-unavailable"], evidence["gates"])
        for loop in evidence["loops"]:
            self.assertEqual("unavailable", loop["verdict"])


class SlabDecompositionSeamTests(unittest.TestCase):
    """`fit-regions` output and its own dump, read by the 2.5D decomposition.

    The events come from the fit record's plane offsets and sigmas; the loops
    come from sectioning the dump those fits were derived from. Neither half is
    hand-built, which matters because they are produced by different stages and
    the decomposition is the first thing that needs both to agree about where
    the part's own boundaries are.
    """

    def _plan(self, dump, **spec_overrides):
        record = seg.fit_regions(dump, ts.spec())
        self.assertIsNone(record["refusal"], record["refusal"])
        return build_reconstruction_program(
            parse_fit_record(record),
            fxr.spec(slabs=True, **spec_overrides),
            manifest_sha256=_manifest_hash(build_manifest()),
            dump=dump,
        )

    def test_the_events_are_this_records_own_plane_stations(self) -> None:
        # A plinth with a boss on it: 0, the shoulder at 10, the top at 18, and
        # nothing else -- the three places material starts or stops along the
        # datum primary axis, each with an accepted plane fit behind it.
        program = self._plan(fx.stepped_block_dump())
        self.assertEqual(
            [0.0, 10.0, 18.0], [round(event["station"], 6) for event in program["events"]]
        )
        for event in program["events"]:
            self.assertGreaterEqual(event["defining_members"], 1)
            self.assertTrue(any(m["kind"] == "plane-fit" for m in event["members"]))
            # The side walls' span ends corroborate the fitted stations rather
            # than inventing their own: every one merged into these three.
            self.assertTrue(any(m["kind"] == "span-end" for m in event["members"]))
            self.assertAlmostEqual(1.0, sum(m["weight"] for m in event["members"]), places=9)

    def test_a_two_step_part_plans_two_stacked_join_only_extrudes(self) -> None:
        program = self._plan(fx.stepped_block_dump())
        slabs = [g for g in program["archetypes"] if g.get("slab") is not None]
        self.assertEqual(2, len(slabs))
        self.assertEqual(["new-body", "join"], [g["operation"] for g in slabs])
        self.assertEqual([0.0, 10.0], [round(g["plane"]["offset"], 6) for g in slabs])
        self.assertEqual([10.0, 8.0], [round(g["extent"]["value"], 6) for g in slabs])
        # A join needs a body to join to, so each slab depends on the one below.
        self.assertEqual([], slabs[0]["dependencies"])
        self.assertEqual([slabs[0]["id"]], slabs[1]["dependencies"])
        self.assertEqual(
            ["recon_station_1 - recon_station_0", "recon_station_2 - recon_station_1"],
            [g["slab"]["extent_expression"] for g in slabs],
        )
        self.assertEqual(["first", "step-in"], [g["slab"]["relation_to_below"] for g in slabs])
        for group in slabs:
            slab = group["slab"]
            self.assertTrue(slab["constancy"]["constant"])
            self.assertEqual(["outer"], [loop["role"] for loop in slab["loops"]])
            self.assertEqual([1.0], [loop["consensus_fraction"] for loop in slab["loops"]])
            self.assertEqual([], slab["gates"])
        # Each region is claimed by exactly one slab: the coverage account sums
        # what each archetype claims, and a wall counted twice would inflate it.
        claimed = [h for group in slabs for h in group["regions"]]
        self.assertEqual(sorted(set(claimed)), sorted(claimed))

    def test_the_shoulder_between_two_slabs_is_claimed_by_the_slab_that_builds_it(
        self,
    ) -> None:
        """The stack delivers faces the single extrude cannot, and must say so.

        The shoulder at station 10 is the plinth's top: 768 mm2 of this part's
        4472, and no part of the single extrude's account, because one extrude
        of the plinth outline does not produce it. The stack does -- it is
        exactly slab 0's cap -- but assignment drew only from the extrude's
        regions, so the shoulder was built and claimed by nobody and the
        coverage account read 0.828 on a part reconstructed whole.
        """
        record = seg.fit_regions(fx.stepped_block_dump(), ts.spec())
        fit = parse_fit_record(record)
        program = self._plan(fx.stepped_block_dump())
        slabs = [g for g in program["archetypes"] if g.get("slab") is not None]
        claimed = [h for group in slabs for h in group["regions"]]
        self.assertEqual(sorted(set(claimed)), sorted(claimed))
        area = {region.region_hash: region.area for region in fit.regions}
        self.assertEqual(sorted(area), sorted(claimed))
        self.assertAlmostEqual(
            1.0, sum(area[h] for h in claimed) / sum(area.values()), places=9
        )
        # And by the slab below it, whose extrude to station 10 *is* that face,
        # rather than by the boss standing on top of it.
        shoulder = next(
            h
            for h, value in area.items()
            if abs(value - 768.0) < 1e-9
        )
        self.assertIn(shoulder, slabs[0]["regions"])
        self.assertNotIn(shoulder, slabs[1]["regions"])

    def test_slabs_coalesce_only_when_every_station_they_sampled_agrees(self) -> None:
        """Congruence at the midpoints is not congruence over the merged range.

        Each slab holds its own sections to within the tolerance and their
        midpoints agree to within it, so the two ends of the merged slab are
        bounded only by the sum -- while the record keeps the lower slab's
        `loops` and calls the whole merged height constant. A boss a hair
        narrower than its plinth coalesces, as it should; give that boss a
        0.01 taper and its upper station walks outside the window while its
        midpoint stays inside, and the merge is exactly the claim that is not
        true.
        """

        def coalesced(**mesh: Any) -> list[int]:
            spec = fxr.spec(slabs=True)
            spec["thresholds"]["slab_evidence"]["slab_constancy_tolerance_mm"] = {
                "value": 0.3,
                "rationale": (
                    "this fixture's step is deliberately inside the window, which is the only "
                    "way to reach the coalescing branch: below it the two slabs are one section."
                ),
            }
            dump = fx.stepped_block_dump(upper=(39.8, 29.8), **mesh)
            record = seg.fit_regions(dump, ts.spec())
            self.assertIsNone(record["refusal"], record["refusal"])
            program = build_reconstruction_program(
                parse_fit_record(record),
                spec,
                manifest_sha256=_manifest_hash(build_manifest()),
                dump=dump,
            )
            return [
                index
                for index, event in enumerate(program["events"])
                if event.get("coalesced")
            ]

        self.assertEqual([1], coalesced())
        self.assertEqual([], coalesced(boss_taper=0.01))

    def test_the_emitter_refuses_a_slab_stack_it_cannot_build(self) -> None:
        # PR 2 plans slabs and does not emit them: the multi-loop profile path is
        # a later unit, and building each slab's outer loop while dropping its
        # cavities would be exactly the improvisation this package bans.
        dump = fx.stepped_block_dump()
        program = self._plan(dump)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "mesh.bin"
            path.write_bytes(_dump_bytes(dump))
            with self.assertRaises(ReconstructionRefused) as caught:
                plan_emission(program, dump, fx.rebuild_spec(str(path)))
        self.assertEqual("program-schema-violation", caught.exception.reason)
        self.assertEqual(2, caught.exception.detail["slab_count"])

    def test_a_tapered_step_refuses_by_measurement_and_the_slab_below_stands(self) -> None:
        # The upper step is a truncated pyramid, so its cross-section differs at
        # every station. The guard measures the disagreement and that slab is not
        # built; the constant slab below it still is.
        program = self._plan(fx.stepped_block_dump(boss_taper=0.5))
        gates = [
            entry["gate"]
            for entry in program["unreconstructed"]
            if entry["gate"].startswith("slab-section-inconstant")
        ]
        self.assertTrue(gates, program["unreconstructed"])
        slabs = [g for g in program["archetypes"] if g.get("slab") is not None]
        self.assertEqual(1, len(slabs))
        self.assertTrue(slabs[0]["slab"]["constancy"]["constant"])
        self.assertEqual(0.0, round(slabs[0]["plane"]["offset"], 6))

    def test_a_slab_whose_inner_loop_has_no_role_is_gated_even_with_an_outer(self) -> None:
        """The gate is about the section, not only about its outer boundary.

        A cavity wall crossing a local non-manifold edge reaches no material
        verdict, so its loop is `unclassified` -- and with an outer loop still
        present the slab used to be built anyway, counting its regions as
        reconstructed on a question nobody answered. The role table is forced
        here rather than fixtured: what is under test is the gate.
        """
        from unittest.mock import patch

        from fusion_design import mesh_slabs as ms

        honest = ms.classify_loops
        calls = []

        def with_one_unclassified(loops, projected, bore_regions):
            rows = honest(loops, projected, bore_regions)
            calls.append(1)
            # Only the first section, so one slab is gated and the other is not:
            # gating every slab leaves the single-extrude fallback claiming all
            # the regions, which is a different path.
            if rows and len(calls) == 1:
                rows = rows + [dict(rows[0], polyline_index=len(rows), role="unclassified")]
            return rows

        with patch.object(ms, "classify_loops", with_one_unclassified):
            program = self._plan(fx.stepped_block_dump())
        gates = [
            entry["gate"]
            for entry in program["unreconstructed"]
            if entry["gate"].startswith("slab-loops-unclassified")
        ]
        self.assertTrue(gates, program["unreconstructed"])
        # And the outer loop really was there: this is not the old case.
        decomposition = program["slab_decomposition"]
        self.assertIsNotNone(decomposition)

    def test_a_loop_that_named_a_role_and_a_gate_still_gates_its_slab(self) -> None:
        """A role is a verdict; a gate says how far the verdict can be trusted.

        `loop_material_evidence` can hand back both: enough of the walls voted
        to call a loop `outer`, and more of its length went unattributed than
        the caller declared tolerable, so it also records
        `slab-wall-unattributed`. Reading only the role accepted the slab and
        counted its regions as reconstructed while the recorded attribution
        failure said the evidence was thin.
        """
        from unittest.mock import patch

        from fusion_design import mesh_slabs as ms

        honest = ms.classify_loops
        calls = []

        def with_one_gated(loops, projected, bore_regions):
            rows = honest(loops, projected, bore_regions)
            calls.append(1)
            if rows and len(calls) == 1:
                rows = [dict(rows[0], gates=["slab-wall-unattributed"])] + list(rows[1:])
            return rows

        with patch.object(ms, "classify_loops", with_one_gated):
            program = self._plan(fx.stepped_block_dump())
        gates = [
            entry["gate"]
            for entry in program["unreconstructed"]
            if entry["gate"].startswith("slab-wall-unattributed")
        ]
        self.assertTrue(gates, program["unreconstructed"])
        # And the token is in this stage's own closed set, not arriving from
        # outside it.
        self.assertIn("slab-wall-unattributed", ms.SLAB_GATES)

    def test_a_triangle_two_regions_both_claim_is_refused_not_resolved_by_order(self) -> None:
        """Region ownership decides bore-or-cavity, so it cannot depend on order.

        The map from triangle to region is what `classify_loops` reads to tell
        a wall of a bore this program already cuts from a wall of a cavity. A
        triangle listed by two regions used to let the later record win
        silently, so *reordering* two records could change which feature the
        planner planned. An index outside the dump names a triangle of some
        other mesh entirely.
        """
        dump = fx.stepped_block_dump()
        record = seg.fit_regions(dump, ts.spec())
        self.assertIsNone(record["refusal"], record["refusal"])
        digest = _manifest_hash(build_manifest())

        def plan(mutate):
            edited = json.loads(json.dumps(record))
            mutate(edited)
            return build_reconstruction_program(
                parse_fit_record(edited),
                fxr.spec(slabs=True),
                manifest_sha256=digest,
                dump=dump,
            )

        def double_claim(edited):
            regions = [r for r in edited["regions"] if r.get("triangle_indices")]
            regions[1]["triangle_indices"] = list(regions[1]["triangle_indices"]) + [
                regions[0]["triangle_indices"][0]
            ]

        def out_of_range(edited):
            region = next(r for r in edited["regions"] if r.get("triangle_indices"))
            region["triangle_indices"] = list(region["triangle_indices"]) + [10 ** 9]

        for mutate, needle in (
            (double_claim, "claimed by both region"),
            (out_of_range, "names a triangle of some other mesh"),
        ):
            with self.subTest(needle=needle):
                with self.assertRaises(ReconstructionRefused) as caught:
                    plan(mutate)
                self.assertEqual("fit-record-malformed", caught.exception.reason)
                self.assertIn(needle, caught.exception.message)

    def test_dirt_on_one_face_does_not_cost_the_loops_that_do_not_touch_it(self) -> None:
        # One duplicated triangle on the bottom face: three edges now carry three
        # incident triangles, so the mesh is not closed in the whole-mesh sense.
        # Neither slab's section is cut from those triangles, so both classify --
        # the per-edge locality the design assumes, which the whole-mesh licence
        # measured in PR 1 did not deliver.
        vertices, triangles, groups = fx.stepped_block_mesh()
        dirty = list(triangles) + [triangles[0]]
        winding = mf.mesh_winding_evidence(vertices, dirty)
        self.assertFalse(winding["closed"])
        self.assertEqual(0, winding["boundary_edges"])
        self.assertEqual(3, winding["non_manifold_edges"])
        self.assertEqual("outward", winding["winding"])
        self.assertTrue(winding["non_manifold_triangles"])

        program = self._plan(
            ts.make_dump(vertices, dirty, face_groups=list(groups) + [groups[0]])
        )
        slabs = [g for g in program["archetypes"] if g.get("slab") is not None]
        self.assertEqual(2, len(slabs))
        for group in slabs:
            loops = group["slab"]["loops"]
            self.assertEqual(["outer"], [loop["role"] for loop in loops])
            self.assertEqual([1.0], [loop["consensus_fraction"] for loop in loops])
            self.assertEqual([[]], [loop["gates"] for loop in loops])

    def test_a_torn_dump_still_refuses_every_loop_globally(self) -> None:
        # The other half of the locality rule: a *boundary* edge means the
        # surface has a hole in it, the enclosed volume is undefined, and no loop
        # anywhere on it can be classified. Locality is about self-touches only.
        vertices, triangles, _groups = fx.stepped_block_mesh()
        winding = mf.mesh_winding_evidence(vertices, triangles[:-4])
        self.assertGreater(winding["boundary_edges"], 0)
        self.assertIsNone(winding["winding"])
        self.assertIn("hole in it", winding["unavailable_reason"])

    def test_one_slab_plans_exactly_what_the_planner_planned_without_slabs(self) -> None:
        """The generalisation's safety proof: the old planner is the base case.

        A plain brick decomposes to a single slab, and a single slab must produce
        the *same archetype* the planner produced before slabs existed -- same
        regions, same caps, same plane, same extent -- with the slab record added
        beside it. Anything else and every existing part's plan has quietly moved.
        """
        dump = brick_dump()
        record = seg.fit_regions(dump, ts.spec())
        digest = _manifest_hash(build_manifest())
        without = build_reconstruction_program(
            parse_fit_record(record), fxr.spec(), manifest_sha256=digest
        )
        with_slabs = build_reconstruction_program(
            parse_fit_record(record), fxr.spec(slabs=True), manifest_sha256=digest, dump=dump
        )
        self.assertEqual(1, len([g for g in with_slabs["archetypes"] if g.get("slab")]))
        self.assertEqual(without["order"], with_slabs["order"])
        self.assertEqual(without["user_parameters"], with_slabs["user_parameters"])
        # `zip` truncates to the shorter list, so a gained or lost archetype
        # would leave this loop passing on the ones that survived.
        self.assertEqual(len(without["archetypes"]), len(with_slabs["archetypes"]))
        for before, after in zip(
            without["archetypes"], with_slabs["archetypes"], strict=True
        ):
            self.assertEqual(
                {k: v for k, v in before.items() if k != "slab"},
                {k: v for k, v in after.items() if k != "slab"},
            )
        self.assertEqual(without["unreconstructed"], with_slabs["unreconstructed"])
        self.assertEqual(
            without["covered_area_fraction"], with_slabs["covered_area_fraction"]
        )

    def test_undeclared_gates_mean_no_decomposition_and_the_program_says_so(self) -> None:
        # The router's own rule, applied here: without declared gates nothing is
        # claimed, and the plan is what it was before slabs existed.
        dump = fx.stepped_block_dump()
        record = seg.fit_regions(dump, ts.spec())
        program = build_reconstruction_program(
            parse_fit_record(record),
            fxr.spec(),
            manifest_sha256=_manifest_hash(build_manifest()),
            dump=dump,
        )
        self.assertEqual([], program["events"])
        self.assertFalse(program["slab_decomposition"]["usable"])
        self.assertIn("slab_evidence", program["slab_decomposition"]["detail"])
        self.assertEqual(
            [None], [g.get("slab") for g in program["archetypes"] if g["kind"] == "sketch-extrude"]
        )


class PlanToRebuildSeamTests(unittest.TestCase):
    """A real program, emitted and run: the cap ordering has to survive the frame."""

    @classmethod
    def setUpClass(cls):
        cls.manifest = build_manifest()
        cls.dump = brick_dump()
        cls.record = fitted(cls.dump)
        cls.program = planned(cls.record, cls.manifest)

    def emit(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "mesh.bin"
            path.write_bytes(_dump_bytes(self.dump))
            return emit_mesh_rebuild_script(
                self.manifest,
                classification_record(),
                source_record(self.manifest),
                self.program,
                fx.rebuild_spec(str(path)),
                NONCE,
            )

    def test_the_sketch_plane_names_the_cap_the_body_extrudes_away_from(self) -> None:
        # The datum axis can be anti-parallel to the caps' own fit normal. U3
        # ordered the caps in the fit normal's frame and reported the offset in
        # the datum's, so it handed over the far cap and U4 refused
        # `cap-order-inverted` on a plain rectangular box.
        group = self.program["archetypes"][0]
        axis = {"XY": "z_axis", "YZ": "x_axis", "XZ": "y_axis"}[group["plane"]["datum_plane"]]
        direction = self.program["datum"][axis]
        origin = self.program["datum"]["origin"]
        flat = list(self.dump.vertices_mm)
        stations = [
            sum(d * (flat[base + i] - o) for i, (d, o) in enumerate(zip(direction, origin)))
            for base in range(0, len(flat), 3)
        ]
        near = group["plane"]["offset"]
        self.assertAlmostEqual(min(stations), near, places=6)
        self.assertAlmostEqual(max(stations), near + group["extent"]["value"], places=6)

    def test_a_real_program_emits_and_the_transaction_builds_it(self) -> None:
        report, error = run_transaction(
            self.emit(), fakes.make_design(), self.manifest.fusion_document
        )
        self.assertIsNone(error, report)
        self.assertTrue(report["ok"], report)
        self.assertIn("sketch-extrude", [entry["kind"] for entry in report["created"]])

    def test_the_whole_chain_reports_full_coverage_of_the_brick(self) -> None:
        report, _ = run_transaction(
            self.emit(), fakes.make_design(), self.manifest.fusion_document
        )
        account = compose_coverage(
            self.program, fit_record=self.record, rebuild_report=report
        )
        self.assertEqual("parametric-full", account["label"])
        self.assertAlmostEqual(1.0, account["delivered_area_fraction"], places=6)


class RebuildToEditabilitySeamTests(unittest.TestCase):
    """The rebuild report U4 writes, read by U5 and then by the verdict."""

    @classmethod
    def setUpClass(cls):
        cls.manifest = build_manifest()
        cls.dump = brick_dump()
        cls.record = fitted(cls.dump)
        cls.program = planned(cls.record, cls.manifest)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "mesh.bin"
            path.write_bytes(_dump_bytes(cls.dump))
            source = emit_mesh_rebuild_script(
                cls.manifest,
                classification_record(),
                source_record(cls.manifest),
                cls.program,
                fx.rebuild_spec(str(path)),
                NONCE,
            )
        cls.report, _ = run_transaction(source, fakes.make_design(), cls.manifest.fusion_document)

    def editability_spec(self, driver):
        others = [
            row["name"] for row in self.report["user_parameters"] if row["name"] != driver
        ]
        return {
            "rationale": "seam probe: one driver exercised, the rest declared unexercised.",
            "observable_restore_epsilon": {
                "volume_mm3": te.declared(0.01),
                "centroid_mm": te.declared(0.001),
                "bbox_mm": te.declared(0.001),
            },
            "parameters": [
                {
                    "name": driver,
                    "perturbation": te.declared(22.0),
                    "expected_observable": "volume",
                    "min_observable_change": te.declared(100.0),
                    "expected_direction": "increase",
                    "rationale": "10% deeper; the extrude adds material so volume must rise.",
                },
                *(
                    {
                        "name": name,
                        "exercise": False,
                        "rationale": "this probe exercises the depth parameter only.",
                    }
                    for name in others
                ),
            ],
        }

    def test_the_report_names_the_parameters_the_editability_spec_must_declare(self) -> None:
        driver = self.report["user_parameters"][0]["name"]
        source = emit_mesh_editability_script(
            self.manifest, self.report, self.editability_spec(driver), EDITABILITY_NONCE
        )
        self.assertIn(driver, source)

    def test_the_proof_runs_against_the_rebuilt_model_and_the_verdict_reads_it(self) -> None:
        driver = self.report["user_parameters"][0]["name"]
        source = emit_mesh_editability_script(
            self.manifest, self.report, self.editability_spec(driver), EDITABILITY_NONCE
        )
        design = fakes.make_design(
            behaviour={"responses": {driver: te.moves_volume(1.0)}},
            parameters=[
                (row["name"], row["expression"]) for row in self.report["user_parameters"]
            ],
        )
        component = fakes.FakeComponent(design, "Reconstruction")
        design.root_occurrences.items.append(fakes.FakeOccurrence(component))
        for entry in self.report["created"]:
            if entry.get("feature_name"):
                feature = fakes.FakeFeature(design, "extrude", "adsk::fusion::ExtrudeFeature")
                feature.name = entry["feature_name"]
                design.add_timeline(feature)
        component.bodies.append(fakes.FakeBody(design, "Body1"))

        proof, error = run_transaction(source, design, self.manifest.fusion_document)
        self.assertIsNone(error, proof)
        verdict = validate_editability_report(
            proof, nonce=EDITABILITY_NONCE, rebuild_record=self.report
        )
        self.assertTrue(verdict["ok"], verdict)
        account = compose_coverage(
            self.program,
            fit_record=self.record,
            rebuild_report=self.report,
            editability_verdict=verdict,
        )
        self.assertEqual([driver], account["stages"][3]["checked"])


class FilletSeamTests(unittest.TestCase):
    """A partial-arc cylinder round, from the mesh to an emitted fillet feature.

    The producer changed shape under the consumer and every test passed. U2 stopped
    proposing fillets as tori -- a face-grouped mesh delivers an edge round as a run
    of *partial-arc cylinders*, and across the 11 benchmark parts it produced 114
    such candidates and not one torus -- while U3 still required `fit.kind ==
    "torus"`. All 114 died at planning with `fillet-fit-unaccepted` and no fillet
    archetype has ever been emitted. The unit tests on either side were green
    throughout, because each was written against its own idea of the record.

    So nothing here is a fixture: a mesh with a rounded edge is segmented, fitted,
    planned, emitted and run against the Fusion doubles, and the assertion is that
    a fillet feature comes out the far end.
    """

    @classmethod
    def setUpClass(cls):
        cls.manifest = build_manifest()
        vertices, triangles, groups = ts.rounded_plinth_mesh()
        cls.dump = ts.make_dump(vertices, triangles, face_groups=groups)
        cls.record = fitted(cls.dump)
        cls.program = planned(cls.record, cls.manifest)

    def blend(self):
        """The one region U2 marked, straight out of the real record."""
        marked = [r for r in self.record["regions"] if r.get("fillet_candidate")]
        self.assertEqual(1, len(marked), [r["region_hash"] for r in marked])
        return marked[0]

    def fillets(self):
        return [g for g in self.program["archetypes"] if g["kind"] == "fillet"]

    def test_the_producer_marks_the_round_as_a_cylinder_and_not_a_torus(self) -> None:
        # If this ever goes back to a torus the widened gate stops being the
        # thing under test, and the rest of this class would pass for the wrong
        # reason.
        blend = self.blend()
        self.assertEqual("cylinder", blend["fit"]["kind"])
        self.assertLess(blend["fit"]["support"]["angular_span_deg"], 180.0)
        self.assertAlmostEqual(4.0, blend["fillet"]["radius"], places=6)

    def test_the_planner_turns_that_cylinder_into_a_fillet_archetype(self) -> None:
        fillets = self.fillets()
        self.assertEqual(1, len(fillets), self.program["unreconstructed"])
        fillet = fillets[0]
        self.assertEqual([self.blend()["region_hash"]], fillet["regions"])
        self.assertAlmostEqual(4.0, fillet["radius"]["value"], places=6)
        # The evidence a fillet needs: two neighbours, each rebuilt by a
        # *different* archetype this same program contains.
        owners = {g["id"]: g["kind"] for g in self.program["archetypes"]}
        self.assertEqual(2, len(set(fillet["between"])))
        self.assertEqual({"revolve", "sketch-extrude"}, {owners[i] for i in fillet["between"]})
        self.assertEqual(fillet["between"], fillet["dependencies"])
        # Ordered after both, because it rounds what they built.
        order = self.program["order"]
        self.assertEqual(order[-1], fillet["id"])

    def test_the_radius_is_bound_to_a_user_parameter_not_a_magic_number(self) -> None:
        fillet = self.fillets()[0]
        name = fillet["radius"]["parameter"]
        row = [p for p in self.program["user_parameters"] if p["name"] == name]
        self.assertEqual(1, len(row), self.program["user_parameters"])
        self.assertEqual("radius", row[0]["quantity"])
        self.assertAlmostEqual(fillet["radius"]["value"], row[0]["nominal"], places=9)

    def test_the_blend_area_is_counted_once_and_only_once(self) -> None:
        # A partial-arc cylinder can be claimed by another archetype where a
        # torus never could -- as a side of the extrude, or the wall of a bore.
        # Rebuilding it twice would put more than the scan in the coverage.
        self.assertAlmostEqual(
            self.program["covered_area_fraction"],
            sum(g["area_fraction"] for g in self.program["archetypes"]),
            places=9,
        )

    def test_the_outer_fragments_of_the_round_are_refused_not_filleted(self) -> None:
        # Only the middle fragment touches exactly two faces. The outer two also
        # touch a side plane, and a blend against three primaries is not an edge.
        gates = {
            entry["region_id"]: entry["gate"] for entry in self.program["unreconstructed"]
        }
        partial = [
            region
            for region in self.record["regions"]
            if region["fit"]["kind"] == "cylinder"
            and not region.get("fillet_candidate")
            # `.get`, not `[]`: `partial` includes rejected cylinders, and
            # `_support_floors` writes the span only once the fit reaches the
            # gates. A cylinder refused earlier carries no span, and a KeyError
            # here would hide whichever assertion below actually broke. Its
            # default is 360, which is "not a partial arc".
            and region["fit"]["support"].get("angular_span_deg", 360.0) < 180.0
        ]
        self.assertEqual(2, len(partial))
        # One of the three does not survive the fit stage at all: refitting a
        # 101 deg arc on a spatially blocked half of its points moves it by
        # 0.07 mm on geometry that is exact to 4e-16, which is the instability
        # the held-out gate is for. It reaches the planner as no fit rather
        # than as a cylinder, which is a stronger statement than the gate below.
        refused = [region for region in partial if not region["accepted"]]
        self.assertEqual(1, len(refused))
        self.assertIn("held-out residual", refused[0]["fit"]["rejection"])
        fragments = [region["region_hash"] for region in partial if region["accepted"]]
        self.assertEqual(1, len(fragments))
        for region_hash in fragments:
            self.assertIn(region_hash, gates)

    def test_the_fillet_reaches_an_emitted_script_and_the_transaction_builds_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "mesh.bin"
            path.write_bytes(_dump_bytes(self.dump))
            source = emit_mesh_rebuild_script(
                self.manifest,
                classification_record(),
                source_record(self.manifest),
                self.program,
                fx.rebuild_spec(str(path)),
                NONCE,
            )
        report, error = run_transaction(source, fakes.make_design(), self.manifest.fusion_document)
        self.assertIsNone(error, report)
        self.assertTrue(report["ok"], report)
        built = [entry for entry in report["created"] if entry["kind"] == "fillet"]
        self.assertEqual(1, len(built), report)
        self.assertEqual(self.fillets()[0]["id"], built[0]["archetype_id"])
        self.assertEqual(self.fillets()[0]["between"], built[0]["between"])
        self.assertGreater(built[0]["edge_count"], 0)
        self.assertEqual([], report["fillets_skipped"], report)


class SameFeatureFilletSeamTests(unittest.TestCase):
    """A round on one extrude's own edge, from the mesh to a built fillet.

    The planner refused every one of these: it read `fillet` as "an operation on
    the edge between two *features*", so a blend whose two neighbours were both
    surfaces of one archetype was gated `fillet-neighbour-shared`. Across the 11
    benchmark parts that gate held 42 of the 114 fillet candidates, and Fusion's
    own `filletFeatures` rounds such an edge without complaint -- a box's top
    edge runs between two faces of one extrude.

    The plinth here is the same plinth, with its post sunk into the body as a
    bore instead of standing on it. That one change removes the revolve, so the
    top face joins the extrude that already owns the front face, and the round
    that used to sit between two features now sits between a cap face and a side
    face of one. Nothing about the round itself changed.
    """

    @classmethod
    def setUpClass(cls):
        cls.manifest = build_manifest()
        vertices, triangles, groups = ts.rounded_plinth_mesh(post_inward=True)
        cls.dump = ts.make_dump(vertices, triangles, face_groups=groups)
        cls.record = fitted(cls.dump)
        cls.program = planned(cls.record, cls.manifest)

    def fillet(self):
        fillets = [g for g in self.program["archetypes"] if g["kind"] == "fillet"]
        self.assertEqual(1, len(fillets), self.program["unreconstructed"])
        return fillets[0]

    def test_the_bore_leaves_one_extrude_that_owns_both_of_the_blends_neighbours(self) -> None:
        # If a revolve ever comes back here the fillet stops being a same-feature
        # one and this class would pass for the old reason.
        marked = [r for r in self.record["regions"] if r.get("fillet_candidate")]
        self.assertEqual(1, len(marked))
        owner = {h: g for g in self.program["archetypes"] for h in g["regions"]}
        neighbours = marked[0]["fillet"]["between"]
        self.assertEqual(1, len({owner[h]["id"] for h in neighbours}), owner)
        self.assertEqual("sketch-extrude", owner[neighbours[0]]["kind"])

    def test_the_planner_names_one_archetype_and_which_of_its_face_sets(self) -> None:
        fillet = self.fillet()
        self.assertEqual(1, len(fillet["between"]))
        # A cap face and a side face: the plan recorded its caps in station
        # order, so the emitter can tell startFaces from endFaces. The round is
        # on the plinth's *top* edge and the extrude now runs up the datum
        # primary axis from the bottom face, so the cap it touches is the far one
        # -- the feature's endFaces.
        self.assertEqual("end-side", fillet["edge_faces"])
        self.assertAlmostEqual(4.0, fillet["radius"]["value"], places=6)
        self.assertEqual(fillet["between"], fillet["dependencies"])
        self.assertEqual(self.program["order"][-1], fillet["id"])

    def test_the_radius_is_still_bound_to_a_user_parameter(self) -> None:
        name = self.fillet()["radius"]["parameter"]
        row = [p for p in self.program["user_parameters"] if p["name"] == name]
        self.assertEqual(1, len(row), self.program["user_parameters"])
        self.assertAlmostEqual(4.0, row[0]["nominal"], places=6)

    def test_the_blend_area_is_counted_once_and_only_once(self) -> None:
        self.assertAlmostEqual(
            self.program["covered_area_fraction"],
            sum(g["area_fraction"] for g in self.program["archetypes"]),
            places=9,
        )

    def test_the_fillet_reaches_an_emitted_script_and_the_transaction_builds_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "mesh.bin"
            path.write_bytes(_dump_bytes(self.dump))
            source = emit_mesh_rebuild_script(
                self.manifest,
                classification_record(),
                source_record(self.manifest),
                self.program,
                fx.rebuild_spec(str(path)),
                NONCE,
            )
        report, error = run_transaction(source, fakes.make_design(), self.manifest.fusion_document)
        self.assertIsNone(error, report)
        self.assertTrue(report["ok"], report)
        built = [entry for entry in report["created"] if entry["kind"] == "fillet"]
        self.assertEqual(1, len(built), report)
        self.assertEqual(self.fillet()["id"], built[0]["archetype_id"])
        self.assertEqual(self.fillet()["between"], built[0]["between"])
        self.assertEqual("end-side", built[0]["edge_faces"])
        # The edges the start cap shares with the side faces, and no others: the
        # feature's own interior edges are not all of them.
        self.assertGreater(built[0]["edge_count"], 0)
        self.assertEqual([], report["fillets_skipped"], report)


class RefusalToReplanSeamTests(unittest.TestCase):
    """The refusal `emit-mesh-rebuild` prints, read by `replan-without`.

    `entity-resolution-ambiguous` is raised on both sides of the emission
    boundary -- by the planner before Fusion is touched, and by the transaction
    inside it -- and the two carry it in differently named fields. `replan-without`
    read only the transaction's, so the documented step-11 recovery loop was dead
    for every refusal that happened before the transaction ever ran.
    """

    def setUp(self):
        self.manifest = build_manifest()
        self.dump = fx.capped_cylinder_dump()
        self.program = fx.program(
            self.dump.sha256,
            manifest_sha256=_manifest_hash(self.manifest),
            archetypes=[fx.revolve_archetype(radius=99.0)],
        )

    def emission_refusal(self):
        """The exact JSON the CLI prints, produced by a real emission attempt."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "mesh.bin"
            path.write_bytes(_dump_bytes(self.dump))
            with self.assertRaises(ReconstructionRefused) as caught:
                plan_emission(self.program, self.dump, fx.rebuild_spec(str(path)))
        return caught.exception.to_dict()

    def test_the_emission_refusal_carries_detail_and_refusal_not_the_transaction_names(self) -> None:
        refusal = self.emission_refusal()
        self.assertEqual("entity-resolution-ambiguous", refusal["refusal"])
        self.assertIn("archetype_id", refusal["detail"])
        self.assertNotIn("refusal_detail", refusal)
        self.assertNotIn("failures", refusal)

    def test_replan_without_reads_the_emission_time_refusal(self) -> None:
        replanned = replan_without(self.program, self.emission_refusal())
        self.assertEqual([], replanned["archetypes"])
        self.assertEqual("entity-resolution-ambiguous", replanned["replanned_from"]["refusal"])
        self.assertEqual(0.0, replanned["covered_area_fraction"])
        self.assertTrue(
            all(
                "entity-resolution-ambiguous" in entry["gate"]
                for entry in replanned["unreconstructed"]
            )
        )

    def test_replan_without_still_reads_the_in_fusion_transaction_refusal(self) -> None:
        transaction_shape = {
            "failures": ["feature-failed"],
            "refusal_detail": {"archetype_id": self.program["archetypes"][0]["id"]},
        }
        replanned = replan_without(self.program, transaction_shape)
        self.assertEqual("feature-failed", replanned["replanned_from"]["refusal"])

    def test_the_cli_completes_the_documented_recovery_loop(self) -> None:
        refusal = self.emission_refusal()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "program.json").write_text(json.dumps(self.program), encoding="utf-8")
            (root / "refusal.json").write_text(json.dumps(refusal), encoding="utf-8")
            code = main(
                [
                    "replan-without",
                    str(root / "program.json"),
                    "--refusal",
                    str(root / "refusal.json"),
                    "-o",
                    str(root / "replanned.json"),
                ]
            )
            self.assertEqual(0, code)
            replanned = json.loads((root / "replanned.json").read_text(encoding="utf-8"))
        self.assertEqual([], replanned["archetypes"])


class DroppedCoverageTests(unittest.TestCase):
    """A dropped archetype subtracts the area fraction it declares, not a proxy."""

    def test_the_drop_uses_the_archetypes_own_area_fraction(self) -> None:
        first = fx.extrude_archetype(identifier="sketch-extrude-aaaaaaaaaaaa")
        second = fx.extrude_archetype(
            identifier="sketch-extrude-dddddddddddd",
            operation="join",
            parameter="recon_base_2_depth",
        )
        second["regions"] = ["d" * 64, "e" * 64, "f" * 64]
        # Two archetypes, three regions to one and one to the other: the
        # region-count proxy would say 0.75 of the coverage goes with the big one.
        first["area_fraction"] = 0.2269
        second["area_fraction"] = 0.7731
        program = fx.program(
            "a" * 64, archetypes=[first, second], covered_area_fraction=1.0
        )
        replanned = replan_without(
            program, {"failures": ["feature-failed"], "refusal_detail": {"archetype_id": second["id"]}}
        )
        self.assertAlmostEqual(0.2269, replanned["covered_area_fraction"], places=6)
        self.assertNotIn("estimate", replanned["replanned_from"]["covered_area_fraction_basis"])

    def test_an_archetype_with_no_area_fraction_refuses_rather_than_guessing(self) -> None:
        program = fx.program("a" * 64)
        program["archetypes"][0].pop("area_fraction")
        with self.assertRaises(ValueError) as caught:
            replan_without(
                program,
                {
                    "failures": ["feature-failed"],
                    "refusal_detail": {"archetype_id": program["archetypes"][0]["id"]},
                },
            )
        self.assertIn("area_fraction", str(caught.exception))


class NothingBuiltTests(unittest.TestCase):
    """No rebuild report means nothing was built, and the number has to say so."""

    def setUp(self):
        self.manifest = build_manifest()
        self.record = fitted()
        self.program = planned(self.record, self.manifest)

    def test_a_program_that_was_never_run_delivers_nothing(self) -> None:
        account = compose_coverage(self.program, fit_record=self.record)
        self.assertEqual("reconstruction-refused", account["label"])
        # It used to label itself refused and report a third of the surface
        # delivered as editable features in the same account.
        self.assertEqual(0.0, account["delivered_area_fraction"])

    def test_an_archetype_with_an_unknown_share_cannot_leave_coverage_behind(self) -> None:
        # The old guard subtracted only the archetypes whose share was known, so
        # one unknown share left its area standing as "delivered".
        program = dict(self.program)
        program["archetypes"] = [dict(g) for g in program["archetypes"]]
        program["archetypes"][0]["area_fraction"] = None
        account = compose_coverage(program, fit_record=self.record)
        self.assertEqual(0.0, account["delivered_area_fraction"])

    def test_the_cli_exits_two_and_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "program.json").write_text(json.dumps(self.program), encoding="utf-8")
            (root / "fit.json").write_text(json.dumps(self.record), encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = main(
                    [
                        "reconstruction-coverage",
                        str(root / "program.json"),
                        "--fit-record",
                        str(root / "fit.json"),
                        "-o",
                        str(root / "coverage.json"),
                    ]
                )
            self.assertEqual(2, code)
            self.assertIn("delivered area fraction: 0.0000", err.getvalue())


def _plinth(**overrides):
    vertices, triangles, groups = ts.rounded_plinth_mesh(**overrides)
    return ts.make_dump(vertices, triangles, face_groups=groups)


class MotionEvidenceSeamTests(unittest.TestCase):
    """The revolve precedence, decided on the facets the fit record now carries.

    The defect this exists for was measured twice. The first live acceptance run
    planned an 80 x 50 x 10 rectangular plate as a 360-degree revolve of radius
    10 covering 77% of its area, which then died at emission with
    `entity-resolution-ambiguous`. On the eleven-part benchmark the two
    rectangular lids planned as revolves, and because a revolve's faces cannot be
    partitioned into named sets, all 61 remaining fillet candidates gated
    `fillet-neighbour-shared` inside them.

    The cause was one line: any plane perpendicular to the primary axis counted
    as a surface of revolution about it. A perpendicular cap is *consistent with*
    a revolve; it is not evidence for one, and a plane's normal field genuinely
    cannot tell an annulus from a rectangular plate -- both are +-z everywhere.

    So the evidence had to come from somewhere the fit record did not reach.
    Every region now carries its own kinematic moment block -- the sufficient
    statistic of `n . (c_bar + c x x) = 0` over its facets -- and the planner
    sums the blocks of a candidate group and asks the router whether they are
    swept by one rotation about this axis. Nothing here is a fixture: the mesh is
    segmented, fitted, planned and emitted, and the emitted script runs against
    the Fusion doubles.
    """

    #: The acceptance run's own plate: 80 x 50 x 10, whose only coaxial outward
    #: turned surface is one round of radius 10 that is not centred on it.
    ACCEPTANCE: ClassVar[dict] = dict(
        width=80.0, depth=50.0, height=10.0, post_radius=10.0, post_height=6.0,
        post_centre=(22.0, 16.0), nx=16, ny=12, nz=5,
    )

    @classmethod
    def setUpClass(cls):
        cls.manifest = build_manifest()
        cls.dump = _plinth(post_centre=(6.0, 12.0))
        cls.record = fitted(cls.dump)
        cls.program = planned(cls.record, cls.manifest)

    def old_rule_group(self, record):
        """The membership the planner used before this change, re-stated here.

        `_is_coaxial_with` is the line that changed, so "the old planning would
        have produced the revolve" is asserted by re-running the old predicate --
        every plane perpendicular to the axis, plus every turned surface on it --
        against this same record and this same datum frame.
        """
        parsed = parse_fit_record(record)
        frame = derive_datum_frame(
            list(parsed.accepted()),
            frame_margin=0.1,
            angle_tolerance_deg=2.0,
            offset_tolerance=0.5,
            sigma_multiple=3.0,
        )
        out = []
        for region in parsed.accepted():
            direction, anchor = region.direction(), region.anchor()
            if direction is None or anchor is None:
                continue
            if mf._angle_deg(direction, frame.z_axis) > 2.0:
                continue
            if region.fit.kind == "plane" or (
                rp._distance_to_line(anchor, frame.origin, frame.z_axis) <= 0.5
            ):
                out.append(region)
        return out, parsed.total_area

    def largest_planes(self, record, count=2):
        return sorted(
            (r for r in record["regions"] if r["accepted"] and r["fit"]["kind"] == "plane"),
            key=lambda r: -r["area"],
        )[:count]

    def test_the_fit_record_carries_the_moment_block_the_planner_routes(self) -> None:
        # The producer/consumer seam itself. `motion_moments` is written by
        # `fit-regions` and read by `plan-reconstruction`; a fixture on either
        # side would let the two drift, which is the failure this file exists for.
        for region in self.record["regions"]:
            block = region["motion_moments"]
            self.assertEqual(21, len(block["matrix"]), region["region_hash"])
            self.assertEqual(region["triangle_count"], block["facet_count"])
            self.assertAlmostEqual(region["area"], block["area"], places=6)
        parsed = parse_fit_record(self.record)
        self.assertTrue(all(r.motion_moments is not None for r in parsed.regions))

    def test_the_summed_blocks_answer_what_the_regions_own_facets_answer(self) -> None:
        # The exactness claim behind carrying 21 numbers instead of triangles:
        # routing a group from its members' blocks is the same computation as
        # routing the union of their facets, not an approximation of it.
        regions = self.largest_planes(self.record, 3)
        points, normals, areas = [], [], []
        for region in regions:
            for index in region["triangle_indices"]:
                corners = [
                    tuple(
                        self.dump.vertices_mm[3 * self.dump.triangles[3 * index + corner] + axis]
                        for axis in range(3)
                    )
                    for corner in range(3)
                ]
                first = tuple(corners[1][k] - corners[0][k] for k in range(3))
                second = tuple(corners[2][k] - corners[0][k] for k in range(3))
                cross = (
                    first[1] * second[2] - first[2] * second[1],
                    first[2] * second[0] - first[0] * second[2],
                    first[0] * second[1] - first[1] * second[0],
                )
                magnitude = math.sqrt(sum(v * v for v in cross))
                points.append(tuple(sum(p[k] for p in corners) / 3.0 for k in range(3)))
                normals.append(tuple(v / magnitude for v in cross))
                areas.append(magnitude / 2.0)
        gates = {
            "sigma_theta_rad": 0.005,
            "residual_sigma_factor": 3.0,
            "eigengap_min": 0.005,
            "translation_epsilon": 0.05,
            "pitch_epsilon": 0.02,
        }
        direct = mf.route_kinematic_surface(points, normals, facet_areas=areas, **gates)
        grouped = mf.route_kinematic_group(
            [r["motion_moments"] for r in regions], mf._extent(points), **gates
        )
        self.assertEqual(direct["verdict"], grouped["verdict"])
        self.assertEqual(direct["refusal"], grouped["refusal"])
        # The additivity is exact *in the algebra* and float-exact only to
        # rounding: the two paths accumulate the same terms in different orders
        # and through a congruence, so the honest claim is a relative one.
        # Measured here at 2.0e-16 -- about one ulp -- and asserted as such,
        # because `places=9` on a number of size 0.017 is an absolute tolerance
        # seven orders looser than the agreement it is meant to pin.
        self.assertLessEqual(
            abs(direct["eigengap"] - grouped["eigengap"]) / abs(direct["eigengap"]), 1e-12
        )

    def test_the_old_rule_would_have_revolved_most_of_this_plate(self) -> None:
        # Without this the test below only shows that the plate is an extrude,
        # not that it stopped being a revolve.
        group, total = self.old_rule_group(self.record)
        turned = [
            region for region in group
            if region.fit.kind in ("cylinder", "cone") and region.material_side != "inside"
        ]
        self.assertGreaterEqual(len(group), 2)
        self.assertTrue(turned, "the old rule needed one outward turned surface, and had one")
        self.assertGreater(sum(region.area for region in group) / total, 0.5)

    def test_the_plate_plans_as_an_extrude_and_a_revolve_keeps_only_the_boss(self) -> None:
        owner = {h: g for g in self.program["archetypes"] for h in g["regions"]}
        for cap in self.largest_planes(self.record):
            self.assertEqual(
                "sketch-extrude", owner[cap["region_hash"]]["kind"], cap["region_hash"]
            )
        # A boss is a legal revolve and this one is genuinely turned about its
        # own axis; what it may not do any more is drag the plate in with it.
        for group in [g for g in self.program["archetypes"] if g["kind"] == "revolve"]:
            self.assertTrue(group["motion_evidence"]["confirmed"])
            self.assertLess(group["area_fraction"], 0.2)

    def test_the_acceptance_runs_own_plate_dimensions_behave_the_same(self) -> None:
        record = fitted(_plinth(**self.ACCEPTANCE))
        program = planned(record, self.manifest)
        group, total = self.old_rule_group(record)
        radii = [
            region.fit.parameters["radius"] for region in group
            if region.fit.kind == "cylinder" and region.material_side != "inside"
        ]
        self.assertTrue(radii)
        self.assertAlmostEqual(10.0, max(radii), places=3)
        self.assertGreater(sum(region.area for region in group) / total, 0.7)
        owner = {h: g for g in program["archetypes"] for h in g["regions"]}
        for cap in self.largest_planes(record):
            self.assertEqual("sketch-extrude", owner[cap["region_hash"]]["kind"])

    def test_the_replanned_plate_emits_its_fillet_through_the_transaction(self) -> None:
        # The point of the whole change, end to end: with the plate's top face in
        # an extrude rather than in a revolve, the round on its top edge sits
        # between two face sets of one nameable feature and Fusion builds it.
        fillets = [g for g in self.program["archetypes"] if g["kind"] == "fillet"]
        self.assertEqual(1, len(fillets), self.program["unreconstructed"])
        # The round is on the plate's top edge, and the extrude runs up from the
        # bottom face: the cap that edge touches is the feature's endFaces.
        self.assertEqual("end-side", fillets[0]["edge_faces"])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "mesh.bin"
            path.write_bytes(_dump_bytes(self.dump))
            source = emit_mesh_rebuild_script(
                self.manifest,
                classification_record(),
                source_record(self.manifest),
                self.program,
                fx.rebuild_spec(str(path)),
                NONCE,
            )
        report, error = run_transaction(source, fakes.make_design(), self.manifest.fusion_document)
        self.assertIsNone(error, report)
        self.assertTrue(report["ok"], report)
        built = [entry for entry in report["created"] if entry["kind"] == "fillet"]
        self.assertEqual(1, len(built), report)
        self.assertEqual(fillets[0]["id"], built[0]["archetype_id"])
        self.assertGreater(built[0]["edge_count"], 0)
        self.assertEqual([], report["fillets_skipped"], report)

    def test_a_genuinely_turned_part_still_plans_as_a_revolve(self) -> None:
        # The other half of the claim, and the half a discriminator can fail
        # silently: the same plinth with its post standing on the *centre* of the
        # top face is turned about that axis, its top face really is an annulus
        # about it, and the router finds one rotation and no other motion.
        program = planned(fitted(_plinth()), self.manifest)
        revolves = [g for g in program["archetypes"] if g["kind"] == "revolve"]
        self.assertEqual(1, len(revolves), [g["kind"] for g in program["archetypes"]])
        evidence = revolves[0]["motion_evidence"]
        self.assertTrue(evidence["confirmed"], evidence)
        self.assertEqual("revolution", evidence["router"]["verdict"])
        self.assertGreater(evidence["router"]["eigengap"], 0.005)
        self.assertLessEqual(evidence["axis_tilt_deg"], 2.0)
        # The top face is in it, which is the case the change must not break.
        self.assertGreater(revolves[0]["area_fraction"], 0.3)

def bored_plate_mesh(width=60.0, depth=44.0, thickness=6.0, radius=4.0, nx=10, ny=8, rings=6):
    """A wide thin plate with one bore straight down it.

    The shape the cap rule was getting wrong.  The plate is ten times wider than
    it is thick, so its *most separated* parallel plane pair is a pair of side
    walls, and an extrude taking those runs across the plate with the bore --
    which goes down the thickness -- oblique to it.

    Each face is a grid of rings interpolated from the bore's rim out to the
    plate's outline, so its triangles are small in both directions.  A fan
    straight from rim to outline would be slivers, and the segmentation would
    then read the part's own noise floor as larger than the features it is asked
    to find (`feature-scale-below-noise`), which is a fixture failing rather than
    a stage.
    """
    vertices: list[tuple[float, float, float]] = []
    index: dict[tuple, int] = {}
    triangles: list[tuple[int, int, int]] = []
    groups: list[int] = []
    centre = (width / 2.0, depth / 2.0)
    perimeter = 2 * (nx + ny)

    def node(key, point):
        if key not in index:
            index[key] = len(vertices)
            vertices.append(point)
        return index[key]

    def span(lo, hi, steps, i):
        return lo + (hi - lo) * i / steps

    def outline_point(i):
        i %= perimeter
        if i < nx:
            return (span(0.0, width, nx, i), 0.0)
        if i < nx + ny:
            return (width, span(0.0, depth, ny, i - nx))
        if i < 2 * nx + ny:
            return (span(width, 0.0, nx, i - nx - ny), depth)
        return (0.0, span(depth, 0.0, ny, i - 2 * nx - ny))

    def rim_point(i):
        angle = 2.0 * math.pi * (i % perimeter) / perimeter
        return (centre[0] + radius * math.cos(angle), centre[1] + radius * math.sin(angle))

    def ring(level, r, i):
        inner, outer = rim_point(i), outline_point(i)
        t = r / rings
        return node(
            ("g", level, r, i % perimeter),
            (
                inner[0] + (outer[0] - inner[0]) * t,
                inner[1] + (outer[1] - inner[1]) * t,
                thickness * level,
            ),
        )

    def quad(a, b, c, d, group):
        triangles.append((a, b, c))
        groups.append(group)
        triangles.append((a, c, d))
        groups.append(group)

    for level, group in ((0, 0), (1, 1)):
        for r in range(rings):
            for i in range(perimeter):
                a, b = ring(level, r, i), ring(level, r, i + 1)
                c, d = ring(level, r + 1, i + 1), ring(level, r + 1, i)
                quad(a, b, c, d, group) if level else quad(a, d, c, b, group)
    for i in range(perimeter):
        lo_a, lo_b = ring(0, rings, i), ring(0, rings, i + 1)
        hi_a, hi_b = ring(1, rings, i), ring(1, rings, i + 1)
        wall = 2 + (0 if i < nx else 1 if i < nx + ny else 2 if i < 2 * nx + ny else 3)
        quad(lo_a, hi_a, hi_b, lo_b, wall)
    # The bore wall, wound so its normals face its own axis: that is what makes
    # `material_side` read "inside", and reading "inside" is what makes it a bore.
    for i in range(perimeter):
        lo_a, lo_b = ring(0, 0, i), ring(0, 0, i + 1)
        hi_a, hi_b = ring(1, 0, i), ring(1, 0, i + 1)
        quad(lo_a, lo_b, hi_b, hi_a, 6)
    return vertices, triangles, groups


def _most_separated_pair(record):
    """The caps the *pre-change* rule would have taken, over every direction.

    Written out here rather than imported, because the rule it describes no
    longer exists in the planner: it is the claim under test, not a helper.
    """
    planes = [
        region
        for region in record["regions"]
        if region["accepted"] and region["fit"]["kind"] == "plane"
    ]
    best = None
    for index, first in enumerate(planes):
        for second in planes[index + 1 :]:
            a = tuple(first["fit"]["parameters"]["normal"])
            b = tuple(second["fit"]["parameters"]["normal"])
            if mf._angle_deg(a, b) > 2.0:
                continue
            separation = abs(
                mf._dot(a, tuple(second["fit"]["parameters"]["point_on_plane"]))
                - mf._dot(a, tuple(first["fit"]["parameters"]["point_on_plane"]))
            )
            if best is None or separation > best[0]:
                best = (separation, a)
    return best


class CapDirectionSeamTests(unittest.TestCase):
    """Which parallel plane pair an extrude sweeps, on a real wide thin plate.

    `_extrude_caps` ranked candidate pairs by *separation* alone, which is a fact
    about the part's bounding box rather than about how the part was built. On
    POD-A1-LID -- 140 x 95 x 6.6 with thirteen bores down it -- the most
    separated pair is two 70 mm2 facelets on the side walls 59 mm apart, so the
    extrude came out on datum YZ and all thirteen bores read
    `hole-axis-oblique` against it: 86 refusals over the eleven benchmark parts.

    The direction now comes from the datum frame, which `derive_datum_frame`
    already derived from these same accepted fits and already refused as
    `frame-ambiguous` when its candidates were too close to call. Nothing else in
    the program was ever expressed in any other frame.
    """

    @classmethod
    def setUpClass(cls):
        cls.manifest = build_manifest()
        vertices, triangles, groups = bored_plate_mesh()
        cls.dump = ts.make_dump(vertices, triangles, face_groups=groups)
        cls.record = fitted(cls.dump)
        cls.program = planned(cls.record, cls.manifest)

    def test_the_producer_gives_the_planner_a_plate_and_a_bore(self) -> None:
        # If this fixture ever stops delivering an inward cylinder the rest of
        # the class would pass for the wrong reason.
        kinds = sorted(r["fit"]["kind"] for r in self.record["regions"] if r["accepted"])
        self.assertEqual(["cylinder"] + ["plane"] * 6, kinds)
        bore = next(r for r in self.record["regions"] if r["fit"]["kind"] == "cylinder")
        self.assertEqual("inside", bore["orientation"]["material_side"])
        self.assertAlmostEqual(4.0, bore["fit"]["parameters"]["radius"], places=6)

    def test_the_pre_change_rule_would_have_taken_the_side_walls(self) -> None:
        # The measurement that made this a bug rather than a preference: the
        # widest separation on this plate is ten times the thickness, and it is
        # across a pair of walls whose normal is nothing like the bore's axis.
        separation, normal = _most_separated_pair(self.record)
        self.assertAlmostEqual(60.0, separation, places=6)
        self.assertGreater(mf._angle_deg(normal, (0.0, 0.0, 1.0)), 45.0)

    def test_the_caps_the_planner_takes_are_the_ones_on_the_datum_axis(self) -> None:
        extrudes = [g for g in self.program["archetypes"] if g["kind"] == "sketch-extrude"]
        self.assertEqual(1, len(extrudes), self.program["archetypes"])
        selection = extrudes[0]["cap_selection"]
        self.assertEqual("datum-primary-axis", selection["rule"])
        self.assertAlmostEqual(6.0, selection["separation"], places=6)
        self.assertEqual("XY", extrudes[0]["plane"]["datum_plane"])
        self.assertAlmostEqual(6.0, extrudes[0]["extent"]["value"], places=6)
        # The direction is the frame's, not this stage's own reading of it.
        self.assertLessEqual(
            mf._angle_deg(tuple(selection["direction"]), tuple(self.program["datum"]["z_axis"])),
            1e-9,
        )

    def test_the_bore_plans_as_a_hole_instead_of_reading_oblique(self) -> None:
        holes = [g for g in self.program["archetypes"] if g["kind"] == "hole"]
        self.assertEqual(1, len(holes), self.program["unreconstructed"])
        self.assertAlmostEqual(8.0, holes[0]["hole"]["diameter"]["value"], places=6)
        self.assertAlmostEqual(6.0, holes[0]["extent"]["value"], places=6)
        gates = " ".join(entry["gate"] for entry in self.program["unreconstructed"])
        self.assertNotIn("hole-axis-oblique", gates)
        self.assertAlmostEqual(1.0, self.program["covered_area_fraction"], places=6)

    def test_the_plate_emits_and_the_transaction_builds_both_features(self) -> None:
        # And the section it sketches is the plate's outline, not the bore's: the
        # midpoint section of a bored plate closes two loops, and the second one
        # is identified against the hole this same program cuts rather than being
        # discarded as "the smaller loop".
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "mesh.bin"
            path.write_bytes(_dump_bytes(self.dump))
            source = emit_mesh_rebuild_script(
                self.manifest,
                classification_record(),
                source_record(self.manifest),
                self.program,
                fx.rebuild_spec(str(path)),
                NONCE,
            )
        report, error = run_transaction(source, fakes.make_design(), self.manifest.fusion_document)
        self.assertIsNone(error, report)
        self.assertTrue(report["ok"], report)
        self.assertEqual(
            ["component", "sketch-extrude", "hole"],
            [entry["kind"] for entry in report["created"]],
            report,
        )
        # Four entities in the sketch: the plate's outline. The bore's loop was
        # identified against the hole and left out, rather than sketched a second
        # time or refused as a second profile.
        sketch = next(
            entry for entry in report["sketches"] if entry["archetype_id"].startswith("sketch-")
        )
        self.assertEqual(4, sketch["entity_count"], sketch)


class PerEdgeFilletSeamTests(unittest.TestCase):
    """Two rounds, two radii, one face-set pair -- and one fillet per edge.

    The same-feature fillet pooled every fragment on one `(feature, face-set
    pair)` key regardless of which edge it lay on. POD-A1-LID's outer wall meets
    its top cap along twenty-four separate rounds -- corners at 12 mm, tabs at
    2 mm, steps at 8.45 and 9.65 -- and pooled on that key they arrive as one
    fillet carrying four radii, which the stage then correctly refuses as
    `fillet-radius-disagrees`. The refusal is right and the key is wrong.

    The plinth here carries the same shape in miniature: its front-top edge is
    rounded at 4 mm and its back-top edge at 6 mm, both between the top cap and a
    side wall of one extrude. The record's own chain ids say which fragments lie
    on which edge, so the two pool separately and each carries the radius it was
    measured with.
    """

    @classmethod
    def setUpClass(cls):
        cls.manifest = build_manifest()
        vertices, triangles, groups = ts.rounded_plinth_mesh(post_inward=True, back_radius=6.0)
        cls.dump = ts.make_dump(vertices, triangles, face_groups=groups)
        cls.record = fitted(cls.dump)
        cls.program = planned(cls.record, cls.manifest)

    def fillets(self):
        found = [g for g in self.program["archetypes"] if g["kind"] == "fillet"]
        return sorted(found, key=lambda g: g["radius"]["value"])

    def test_the_producer_marks_two_rounds_and_names_the_edge_of_each(self) -> None:
        marked = [r for r in self.record["regions"] if r.get("fillet_candidate")]
        self.assertEqual(2, len(marked), [r["region_hash"] for r in marked])
        radii = sorted(round(r["fillet"]["radius"], 6) for r in marked)
        self.assertEqual([4.0, 6.0], radii)
        chains = {r["fillet"]["chain_id"] for r in marked}
        self.assertEqual(2, len(chains), "two edges are two chains")

    def test_each_edge_plans_its_own_fillet_with_its_own_radius(self) -> None:
        fillets = self.fillets()
        self.assertEqual(2, len(fillets), self.program["unreconstructed"])
        self.assertAlmostEqual(4.0, fillets[0]["radius"]["value"], places=6)
        self.assertAlmostEqual(6.0, fillets[1]["radius"]["value"], places=6)
        # Both between the *same* face sets of the same feature: this is the key
        # that used to pool them, and pooling them is what has to stop.
        self.assertEqual([1, 1], [len(g["between"]) for g in fillets])
        self.assertEqual({"end-side"}, {g["edge_faces"] for g in fillets})
        self.assertEqual(1, len({g["between"][0] for g in fillets}))
        gates = " ".join(entry["gate"] for entry in self.program["unreconstructed"])
        self.assertNotIn("fillet-radius-disagrees", gates)

    def test_each_fillet_carries_where_its_own_fragments_were_measured(self) -> None:
        # Enough to tell one edge of the pair from the other, in the datum frame
        # the rebuild is built in -- not in the mesh's.
        small, large = self.fillets()
        for fillet in (small, large):
            evidence = fillet["edge_evidence"]
            self.assertEqual("datum", evidence["frame"])
            for low, high in zip(evidence["box_min"], evidence["box_max"]):
                self.assertLessEqual(low, high)
        # The two boxes are disjoint along the datum Y axis: one round is on the
        # front edge and one on the back, which is what emission has to resolve.
        self.assertLess(small["edge_evidence"]["box_max"][1], large["edge_evidence"]["box_min"][1])

    def test_the_transaction_rounds_a_different_edge_for_each_fillet(self) -> None:
        # The doubles place the extrude's four end-to-side edges where this
        # plinth's really are, in centimetres and in the datum frame: the front
        # edge at y = -1.7, the back at y = +1.3, and the two ends at x = +-1.0.
        # The first feature built takes edge ids 1100..1103 for that face pair.
        boxes = {
            1100: ((-1.0, -1.7, 1.2), (1.0, -1.7, 1.2)),
            1101: ((1.0, -1.7, 1.2), (1.0, 1.3, 1.2)),
            1102: ((-1.0, 1.3, 1.2), (1.0, 1.3, 1.2)),
            1103: ((-1.0, -1.7, 1.2), (-1.0, 1.3, 1.2)),
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "mesh.bin"
            path.write_bytes(_dump_bytes(self.dump))
            source = emit_mesh_rebuild_script(
                self.manifest,
                classification_record(),
                source_record(self.manifest),
                self.program,
                fx.rebuild_spec(str(path)),
                NONCE,
            )
        design = fakes.make_design(behaviour={"edge_boxes": boxes})
        report, error = run_transaction(source, design, self.manifest.fusion_document)
        self.assertIsNone(error, report)
        self.assertTrue(report["ok"], report)
        built = {
            entry["archetype_id"]: entry
            for entry in report["created"]
            if entry["kind"] == "fillet"
        }
        self.assertEqual(2, len(built), report)
        self.assertEqual([], report["fillets_skipped"], report)
        small, large = self.fillets()
        # One edge each, chosen out of the four the face pair shares, and not the
        # same one twice.
        for fillet in (small, large):
            entry = built[fillet["id"]]
            self.assertEqual(1, entry["edge_count"], entry)
            self.assertEqual({"candidates": 4, "selected": 1}, entry["edge_selection"])
        self.assertNotEqual(
            built[small["id"]]["edge_tokens"], built[large["id"]]["edge_tokens"]
        )
        # And the *right* edge each: the 4 mm round is on the front edge, the
        # 6 mm round on the back one.
        self.assertEqual(["token-edge-1100"], built[small["id"]]["edge_tokens"])
        self.assertEqual(["token-edge-1102"], built[large["id"]]["edge_tokens"])

    def test_two_edges_the_evidence_cannot_tell_apart_refuse_by_name(self) -> None:
        # The other half of the rule: nearest wins only when it is
        # *distinguishably* nearest. Two edges at the same distance from where
        # the fragments were measured are not resolved by this evidence, and
        # rounding whichever sorted first is exactly the guess this refuses.
        boxes = {
            1100: ((-1.0, -1.7, 1.2), (1.0, -1.7, 1.2)),
            1101: ((-1.0, -1.7, 1.2), (1.0, -1.7, 1.2)),
            1102: ((-1.0, 1.3, 1.2), (1.0, 1.3, 1.2)),
            1103: ((-1.0, 1.3, 1.2), (1.0, 1.3, 1.2)),
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "mesh.bin"
            path.write_bytes(_dump_bytes(self.dump))
            source = emit_mesh_rebuild_script(
                self.manifest,
                classification_record(),
                source_record(self.manifest),
                self.program,
                fx.rebuild_spec(str(path)),
                NONCE,
            )
        design = fakes.make_design(behaviour={"edge_boxes": boxes})
        report, error = run_transaction(source, design, self.manifest.fusion_document)
        self.assertIsNone(error, report)
        self.assertTrue(report["ok"], report)
        self.assertEqual([], [e for e in report["created"] if e["kind"] == "fillet"])
        reasons = {entry["reason"] for entry in report["fillets_skipped"]}
        self.assertEqual({"entity-resolution-ambiguous"}, reasons, report["fillets_skipped"])

if __name__ == "__main__":
    unittest.main()
