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
from pathlib import Path
import tempfile
import unittest

from fusion_design.cli import main
from fusion_design.mesh_datum import ReconstructionRefused, parse_fit_record
from fusion_design.mesh_dump import pack_mesh_dump
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
    vertices, triangles = ts.box_mesh(size=20.0, divisions=6)
    return ts.make_dump([(x * 0.5, y, z * 0.75) for x, y, z in vertices], triangles)


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


if __name__ == "__main__":
    unittest.main()
