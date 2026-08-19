"""The coverage account: it may lose area at every stage and gain it at none."""

from __future__ import annotations

import unittest

from fusion_design.reconstruction_coverage import (
    COVERAGE_LABELS,
    compose_coverage,
    format_coverage,
)

import fixtures_rebuild as fx


def program(*, fractions=(0.70, 0.20, 0.05), covered=0.95, unreconstructed=None):
    body = fx.program(
        "a" * 64,
        archetypes=[fx.extrude_archetype(), fx.hole_archetype(), fx.fillet_archetype()],
    )
    for group, fraction in zip(body["archetypes"], fractions):
        group["area_fraction"] = fraction
    body["covered_area_fraction"] = covered
    body["unreconstructed"] = (
        [
            {
                "region_id": "f" * 64,
                "area_fraction": 0.05,
                "gate": "material-side-unavailable: the mesh is not closed.",
            }
        ]
        if unreconstructed is None
        else unreconstructed
    )
    return body


def built(skipped=(), created=("sketch-extrude-aaaaaaaaaaaa", "hole-cccccccccccc")):
    return {
        "ok": True,
        "failures": [],
        "created": [{"archetype_id": identifier} for identifier in created],
        "fillets_skipped": list(skipped),
    }


SKIPPED_FILLET = {
    "archetype_id": "fillet-eeeeeeeeeeee",
    "reason": "entity-resolution-ambiguous",
    "detail": "the two features this blend rounds share no edge.",
}


class LabelTests(unittest.TestCase):
    def test_a_partial_rebuild_is_labelled_partial_and_says_it_is_a_success(self) -> None:
        account = compose_coverage(program(), rebuild_report=built(skipped=[SKIPPED_FILLET]))
        self.assertEqual("parametric-partial", account["label"])
        self.assertIn("successful outcome", account["label_rationale"])
        self.assertIn("reference geometry", account["label_rationale"])

    def test_a_fully_covered_and_fully_built_program_is_labelled_full(self) -> None:
        account = compose_coverage(
            program(fractions=(0.70, 0.25, 0.05), covered=1.0, unreconstructed=[]),
            rebuild_report=built(
                created=(
                    "sketch-extrude-aaaaaaaaaaaa",
                    "hole-cccccccccccc",
                    "fillet-eeeeeeeeeeee",
                )
            ),
        )
        self.assertEqual("parametric-full", account["label"])
        self.assertAlmostEqual(1.0, account["delivered_area_fraction"])
        self.assertEqual([], account["unreconstructed"])

    def test_a_refused_rebuild_delivers_nothing_however_much_was_planned(self) -> None:
        account = compose_coverage(
            program(),
            rebuild_report={"ok": False, "failures": ["feature-failed"], "created": []},
        )
        self.assertEqual("reconstruction-refused", account["label"])
        self.assertEqual(0.0, account["delivered_area_fraction"])
        self.assertIn("feature-failed", account["label_rationale"])
        # Every planned archetype is named as undelivered, not just the one that
        # failed: a rollback removes all of them.
        self.assertEqual(4, len(account["unreconstructed"]))

    def test_a_plan_that_was_never_run_has_reconstructed_nothing(self) -> None:
        account = compose_coverage(program())
        self.assertEqual("reconstruction-refused", account["label"])
        self.assertEqual(0.0, account["delivered_area_fraction"])
        self.assertIn("a plan that has not been run", account["label_rationale"])
        build = next(stage for stage in account["stages"] if stage["stage"] == "build")
        self.assertIn("A plan is not a model", build["unavailable_reason"])

    def test_the_label_set_is_closed_and_carried_in_the_account(self) -> None:
        self.assertEqual(
            ("parametric-full", "parametric-partial", "reconstruction-refused"), COVERAGE_LABELS
        )
        self.assertEqual(list(COVERAGE_LABELS), compose_coverage(program())["labels"])


class ArithmeticTests(unittest.TestCase):
    def test_a_skipped_fillet_is_subtracted_even_though_the_build_succeeded(self) -> None:
        # The defect this whole module exists to prevent: an archetype that was
        # planned and not delivered must not keep counting as reconstructed.
        account = compose_coverage(program(), rebuild_report=built(skipped=[SKIPPED_FILLET]))
        self.assertAlmostEqual(0.90, account["delivered_area_fraction"])
        gates = " ".join(entry["gate"] for entry in account["unreconstructed"])
        self.assertIn("entity-resolution-ambiguous", gates)
        self.assertIn("share no edge", gates)

    def test_delivered_never_exceeds_what_the_program_planned(self) -> None:
        account = compose_coverage(
            program(covered=0.60),
            rebuild_report=built(
                created=(
                    "sketch-extrude-aaaaaaaaaaaa",
                    "hole-cccccccccccc",
                    "fillet-eeeeeeeeeeee",
                )
            ),
        )
        self.assertAlmostEqual(0.60, account["delivered_area_fraction"])

    def test_an_absent_fit_record_is_reported_absent_not_read_as_complete(self) -> None:
        account = compose_coverage(program(), rebuild_report=built())
        fit = next(stage for stage in account["stages"] if stage["stage"] == "fit")
        self.assertIsNone(fit["covered_area_fraction"])
        self.assertIn("never read as complete", fit["unavailable_reason"])

    def test_the_fit_stage_carries_what_was_never_claimed_at_all(self) -> None:
        account = compose_coverage(
            program(),
            fit_record={
                "covered_area_fraction": 0.97,
                "unclaimed": {
                    "components": [{"area_fraction": 0.03, "dominant_curvature": "saddle"}]
                },
                "unfitted_regions": [
                    {"region_hash": "b" * 64, "area_fraction": 0.0, "failed_gate": "residual"}
                ],
            },
            rebuild_report=built(skipped=[SKIPPED_FILLET]),
        )
        fit = next(stage for stage in account["stages"] if stage["stage"] == "fit")
        self.assertEqual(0.97, fit["covered_area_fraction"])
        self.assertEqual("saddle", fit["unclaimed_components"][0]["dominant_curvature"])


class EditabilityTests(unittest.TestCase):
    def test_editability_is_carried_beside_coverage_and_never_folded_into_it(self) -> None:
        # A fully covered model whose parameters are all inert is not a better
        # outcome than a partial model that edits. One number cannot say both.
        account = compose_coverage(
            program(),
            rebuild_report=built(skipped=[SKIPPED_FILLET]),
            editability_verdict={
                "ok": True,
                "report": {
                    "checked": ["recon_hole_1_dia"],
                    "not_exercised": ["recon_hole_1_x"],
                    "interactions_exercised": False,
                },
            },
        )
        stage = next(s for s in account["stages"] if s["stage"] == "editability")
        self.assertTrue(stage["ok"])
        self.assertEqual(["recon_hole_1_dia"], stage["checked"])
        self.assertEqual(["recon_hole_1_x"], stage["not_exercised"])
        self.assertIs(False, stage["interactions_exercised"])
        self.assertAlmostEqual(0.90, account["delivered_area_fraction"])

    def test_an_absent_editability_verdict_proves_nothing_and_says_so(self) -> None:
        account = compose_coverage(program(), rebuild_report=built())
        stage = next(s for s in account["stages"] if s["stage"] == "editability")
        self.assertFalse(stage["ran"])
        self.assertIn("has been shown to rebuild", stage["unavailable_reason"])


class ProseTests(unittest.TestCase):
    def test_the_prose_names_the_label_the_fraction_and_every_gate(self) -> None:
        text = format_coverage(
            compose_coverage(program(), rebuild_report=built(skipped=[SKIPPED_FILLET]))
        )
        self.assertIn("parametric-partial", text)
        self.assertIn("0.9000", text)
        self.assertIn("material-side-unavailable", text)
        self.assertIn("entity-resolution-ambiguous", text)

    def test_the_account_refuses_the_claims_it_did_not_establish(self) -> None:
        text = format_coverage(compose_coverage(program(), rebuild_report=built()))
        self.assertIn("does not claim", text)
        self.assertIn("deviation verdict", text)
        self.assertIn("never *the* original", text)


if __name__ == "__main__":
    unittest.main()
