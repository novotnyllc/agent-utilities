"""U5: what the editability proof actually proves, and what it refuses to claim.

Every scenario below runs the *emitted* transaction against Fusion doubles, so a
verdict is produced by the code that will run in Fusion.  The doubles are what
make the interesting cases reachable offline: a parameter that changes nothing, a
parameter that changes only the centroid, a recompute that breaks a feature, a
restore that does not come back.
"""

from __future__ import annotations

import json
import unittest

from fusion_design.manifest import ManifestValidationError
from fusion_design.mesh_editability import (
    emit_mesh_editability_script,
    validate_editability_report,
    validate_editability_spec,
)
from fusion_design.scripts import _script_prelude

import fakes_fusion_rebuild as fakes
from test_mesh_rebuild import build_manifest, run_transaction


NONCE = "fedcba9876543210fedcba9876543210"
REBUILD_NONCE = "0123456789abcdef0123456789abcdef"


def _manifest_hash():
    from fusion_design.scripts import manifest_sha256

    return manifest_sha256(build_manifest())


def rebuild_record(**overrides):
    record = {
        "kind": "mesh-rebuild",
        "ok": True,
        "failures": [],
        "component_name": "Reconstruction",
        "rebuild_nonce": REBUILD_NONCE,
        "dump_sha256": "d" * 64,
        "program_sha256": "p" * 64,
        "manifest_sha256": _manifest_hash(),
        "created": [
            {
                "kind": "sketch-extrude",
                "archetype_id": "sketch-extrude-aaaaaaaaaaaa",
                "feature_name": "recon_sketch_extrude_aaaaaaaaaaaa",
                "operation": "new-body",
                "sketch_name": "s",
                "token": "token-feature-1",
            }
        ],
        "user_parameters": [
            _parameter("recon_base_1_depth", "20.000000 mm", "volume"),
            _parameter("recon_plane_offset", "-10.000000 mm", "centroid"),
        ],
        "bodies": [{"name": "Body1", "volume_mm3": 8000.0, "token": "token-body-Body1"}],
    }
    record.update(overrides)
    return record


def _parameter(name, expression, observable):
    return {
        "name": name,
        "expression": expression,
        "unit": "mm",
        "quantity": "depth",
        "nominal": 20.0,
        "expected_observable": observable,
        "observable_rationale": "fixture",
        "driving_archetypes": ["sketch-extrude-aaaaaaaaaaaa"],
    }


def declared(value, rationale="fixture"):
    return {"value": value, "rationale": rationale}


def spec(**overrides):
    payload = {
        "rationale": "fixture: 5% perturbations against a synthetic 20 mm cube.",
        "observable_restore_epsilon": {
            "volume_mm3": declared(0.01),
            "centroid_mm": declared(0.001),
            "bbox_mm": declared(0.001),
        },
        "parameters": [
            {
                "name": "recon_base_1_depth",
                "perturbation": declared(22.0),
                "expected_observable": "volume",
                "min_observable_change": declared(100.0),
                "expected_direction": "increase",
                "rationale": "10% deeper; the extrude adds material so volume must rise.",
            },
            {
                "name": "recon_plane_offset",
                "perturbation": declared(-8.0),
                "expected_observable": "centroid",
                "min_observable_change": declared(1.0),
                "rationale": "slides the feature 2 mm along Z; volume is unchanged by design.",
            },
        ],
    }
    payload.update(overrides)
    return payload


def moves_volume(delta):
    def respond(design, name, value):
        design._volume_cm3 = 8.0 + (delta if "22" in value else 0.0)

    return respond


def moves_centroid(delta):
    def respond(design, name, value):
        design._centroid_cm = [1.0, 1.0, 1.0 + (delta if "-8" in value else 0.0)]

    return respond


def working_design(responses=None, **behaviour):
    """A design that already holds the rebuild the record describes."""
    design = fakes.make_design(
        behaviour=dict(
            behaviour,
            responses=responses
            if responses is not None
            else {
                "recon_base_1_depth": moves_volume(1.0),
                "recon_plane_offset": moves_centroid(0.5),
            },
        ),
        parameters=[
            ("recon_base_1_depth", "20.000000 mm"),
            ("recon_plane_offset", "-10.000000 mm"),
        ],
    )
    component = fakes.FakeComponent(design, "Reconstruction")
    occurrence = fakes.FakeOccurrence(component)
    design.root_occurrences.items.append(occurrence)
    feature = fakes.FakeFeature(design, "extrude", "adsk::fusion::ExtrudeFeature")
    feature.name = "recon_sketch_extrude_aaaaaaaaaaaa"
    design.add_timeline(feature)
    component.bodies.append(fakes.FakeBody(design, "Body1"))
    return design


def emit(record=None, payload=None):
    return emit_mesh_editability_script(
        build_manifest(), record or rebuild_record(), payload or spec(), NONCE
    )


class SpecValidationTests(unittest.TestCase):
    def names(self):
        return ["recon_base_1_depth", "recon_plane_offset"]

    def test_a_complete_spec_validates(self):
        self.assertEqual([], validate_editability_spec(spec(), self.names()))

    def test_a_parameter_the_rebuild_created_may_not_be_left_unmentioned(self):
        payload = spec()
        payload["parameters"] = payload["parameters"][:1]
        codes = {i.code for i in validate_editability_spec(payload, self.names())}
        self.assertIn("editability-spec-incomplete", codes)

    def test_a_deliberately_unexercised_parameter_is_allowed_but_must_say_why(self):
        payload = spec()
        payload["parameters"][1] = {
            "name": "recon_plane_offset",
            "exercise": False,
            "rationale": "this build has one body; the offset is proven by the deviation run.",
        }
        self.assertEqual([], validate_editability_spec(payload, self.names()))

    def test_a_change_smaller_than_the_restore_noise_is_unmeasurable(self):
        payload = spec()
        payload["parameters"][0]["min_observable_change"] = declared(0.001)
        codes = {i.code for i in validate_editability_spec(payload, self.names())}
        self.assertIn("editability-spec-unmeasurable", codes)

    def test_an_observable_outside_the_closed_set_is_rejected(self):
        payload = spec()
        payload["parameters"][0]["expected_observable"] = "surface_area"
        codes = {i.code for i in validate_editability_spec(payload, self.names())}
        self.assertIn("editability-spec-invalid-parameters", codes)

    def test_a_perturbation_without_a_rationale_is_rejected(self):
        payload = spec()
        payload["parameters"][0].pop("rationale")
        codes = {i.code for i in validate_editability_spec(payload, self.names())}
        self.assertIn("editability-spec-invalid-parameters", codes)

    def test_perturbing_a_parameter_to_its_own_nominal_is_a_silent_no_op(self):
        payload = spec()
        payload["parameters"][0]["perturbation"] = declared(20.0)
        codes = {
            i.code
            for i in validate_editability_spec(payload, rebuild_record()["user_parameters"])
        }
        self.assertIn("editability-spec-no-op", codes)

    def test_a_negative_perturbed_value_is_allowed(self):
        # A position parameter's perturbed value routinely is negative, and
        # refusing it would make the one parameter class this proof exists for
        # unprovable.
        payload = spec()
        self.assertEqual(
            [], validate_editability_spec(payload, rebuild_record()["user_parameters"])
        )
        self.assertLess(payload["parameters"][1]["perturbation"]["value"], 0.0)

    def test_a_spec_that_exercises_nothing_is_rejected(self):
        payload = spec()
        payload["parameters"] = [
            {"name": name, "exercise": False, "rationale": "not this run."}
            for name in self.names()
        ]
        codes = {i.code for i in validate_editability_spec(payload, self.names())}
        self.assertIn("editability-spec-exercises-nothing", codes)

    def test_a_spec_naming_a_parameter_the_rebuild_never_made_is_rejected(self):
        payload = spec()
        payload["parameters"][0]["name"] = "somebody_elses_parameter"
        codes = {i.code for i in validate_editability_spec(payload, self.names())}
        self.assertIn("editability-spec-unknown-parameter", codes)

    def test_a_failed_rebuild_cannot_have_its_editability_proven(self):
        with self.assertRaises(ValueError):
            emit(rebuild_record(ok=False, failures=["feature-failed"]))


class EmittedSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = build_manifest()
        cls.source = emit()
        cls.transaction = cls.source[len(_script_prelude(cls.manifest)) :]

    def test_the_source_compiles(self):
        compile(self.source, "<editability>", "exec")

    def test_designtype_appears_nowhere(self):
        # It is true of a faceted body with no timeline, so it proves nothing and
        # the proof must not be able to lean on it even by accident.
        self.assertNotIn("designType", self.source)

    def test_the_transaction_starts_no_process(self):
        for banned in ("subprocess", "os.system", "os.exec", "Popen", "sys.executable"):
            self.assertNotIn(banned, self.source, banned)

    def test_every_capability_probe_refuses_rather_than_defaulting(self):
        for line in self.transaction.splitlines():
            if "getattr(" in line:
                self.assertIn("_MISSING", line, line)

    def test_the_transaction_contains_no_direct_edit_or_faceted_shortcut(self):
        # `BaseFeature` appears as the string this proof bans; nothing else here
        # may reach for direct-edit or temporary-B-Rep construction.
        for banned in ("setByPlane", "TemporaryBRepManager", "baseFeatures"):
            self.assertNotIn(banned, self.transaction, banned)

    def test_the_nonce_and_the_rebuild_binding_are_embedded(self):
        for value in (NONCE, REBUILD_NONCE, "d" * 64, "p" * 64, _manifest_hash()):
            self.assertIn(value, self.source)

    def test_emission_is_byte_identical_across_runs(self):
        self.assertEqual(self.source, emit())

    def test_a_short_nonce_is_refused(self):
        with self.assertRaises(ValueError):
            emit_mesh_editability_script(self.manifest, rebuild_record(), spec(), "short")


class ProofTests(unittest.TestCase):
    def setUp(self):
        self.document = build_manifest().fusion_document

    def run_proof(self, design, payload=None, record=None):
        return run_transaction(emit(record, payload), design, self.document)

    def test_a_working_rebuild_passes_and_checks_every_parameter(self):
        report, error = self.run_proof(working_design())
        self.assertIsNone(error, report)
        self.assertTrue(report["ok"], report)
        self.assertEqual(
            ["recon_base_1_depth", "recon_plane_offset"], sorted(report["checked"])
        )
        self.assertEqual([], report["failures"])
        self.assertIs(False, report["interactions_exercised"])

    def test_a_position_parameter_passes_on_centroid_with_volume_unchanged(self):
        # The regression that overturned the parent plan's volume-only rule: a
        # correct parameter that moves no volume must not be called inert.
        report, _ = self.run_proof(working_design())
        row = next(r for r in report["parameters"] if r["name"] == "recon_plane_offset")
        self.assertEqual("centroid", row["expected_observable"])
        self.assertEqual(
            row["observables_before"]["volume_mm3"], row["observables_after"]["volume_mm3"]
        )
        self.assertGreater(row["measured_change"], row["declared_min_change"])
        self.assertIn("recon_plane_offset", report["checked"])

    def test_a_parameter_that_moves_nothing_is_a_failure_not_a_warning(self):
        design = working_design(
            responses={"recon_base_1_depth": lambda *_: None, "recon_plane_offset": moves_centroid(0.5)}
        )
        report, error = self.run_proof(design)
        self.assertIsNotNone(error)
        self.assertIn("parameter-inert", report["failures"])
        self.assertNotIn("recon_base_1_depth", report["checked"])
        row = next(r for r in report["parameters"] if r["name"] == "recon_base_1_depth")
        self.assertEqual("parameter-inert", row["failure"])
        self.assertFalse(report["ok"])

    def test_a_reversed_effect_is_named_when_a_direction_was_declared(self):
        design = working_design(
            responses={
                "recon_base_1_depth": moves_volume(-1.0),
                "recon_plane_offset": moves_centroid(0.5),
            }
        )
        report, _ = self.run_proof(design)
        self.assertIn("parameter-effect-reversed", report["failures"])

    def test_damage_that_predates_the_perturbation_is_not_blamed_on_it(self):
        # Blaming a parameter for a feature somebody else broke is as wrong as
        # missing the one it did break.
        design = working_design()
        stranger = fakes.FakeFeature(design, "extrude", "adsk::fusion::ExtrudeFeature")
        stranger.name = "somebody_elses_feature"
        stranger.healthy = False
        stranger.errorOrWarningMessage = "this was already broken"
        design.add_timeline(stranger)
        report, error = self.run_proof(design)
        self.assertIsNone(error, report)
        self.assertTrue(report["ok"])
        self.assertNotIn("parameter-broke-rebuild", report["failures"])

    def test_an_unhealthy_item_this_run_cannot_name_still_counts_as_broken(self):
        # A timeline entity with no readable name must not read as "not one of
        # ours, so nothing broke" -- that turns an absent API into a pass.
        design = working_design()

        def sicken(design_):
            nameless = fakes.FakeFeature(design_, "extrude", "adsk::fusion::ExtrudeFeature")
            del nameless.name
            nameless.healthy = False
            design_.add_timeline(nameless)

        design.behaviour["on_compute"] = _once(sicken)
        report, _ = self.run_proof(design)
        self.assertIn("parameter-broke-rebuild", report["failures"])
        row = next(r for r in report["parameters"] if r["name"] == "recon_base_1_depth")
        self.assertEqual([], row["broken_features"])
        self.assertEqual(1, row["unattributable_unhealthy"])

    def test_a_break_followed_by_a_failed_restore_keeps_both_attributions(self):
        def sicken(design_):
            for item in design_.timeline_items:
                item.entity.healthy = False
                item.entity.errorOrWarningMessage = "the profile no longer closes"

        design = working_design(on_compute=sicken)  # never recovers, so restore fails too
        report, _ = self.run_proof(design)
        row = next(r for r in report["parameters"] if r["name"] == "recon_base_1_depth")
        self.assertEqual("parameter-broke-rebuild", row["failure"])
        self.assertEqual("parameter-not-restorable", row["restore_failure"])
        self.assertEqual(
            ["parameter-broke-rebuild", "parameter-not-restorable"], report["failures"]
        )
        self.assertEqual("recon_base_1_depth", report["aborted_at"])

    def test_a_broken_recompute_names_the_parameter_and_the_feature(self):
        def sicken(design):
            for item in design.timeline_items:
                item.entity.healthy = False
                item.entity.errorOrWarningMessage = "the profile no longer closes"

        design = working_design(on_compute=_once(sicken))
        report, _ = self.run_proof(design)
        self.assertIn("parameter-broke-rebuild", report["failures"])
        row = next(r for r in report["parameters"] if r["name"] == "recon_base_1_depth")
        self.assertEqual("parameter-broke-rebuild", row["failure"])
        self.assertEqual(["recon_sketch_extrude_aaaaaaaaaaaa"], row["broken_features"])
        self.assertIn("the profile no longer closes", row["messages"])

    def test_a_model_that_does_not_come_back_aborts_the_loop_loudly(self):
        def wander(design, name, value):
            design._volume_cm3 = 9.0  # never returns to the baseline 8.0

        design = working_design(
            responses={"recon_base_1_depth": wander, "recon_plane_offset": moves_centroid(0.5)}
        )
        report, _ = self.run_proof(design)
        self.assertIn("parameter-not-restorable", report["failures"])
        self.assertEqual("recon_base_1_depth", report["aborted_at"])
        # R12: a parameter the loop never reached is named unproven, never
        # silently skipped and never counted as checked.
        self.assertEqual(["recon_plane_offset"], report["not_exercised"])
        self.assertEqual([], report["checked"])

    def test_a_body_backed_by_imported_geometry_is_caught_before_any_perturbation(self):
        design = working_design()
        imported = fakes.FakeFeature(design, "base", "adsk::fusion::BaseFeature")
        design.add_timeline(imported)
        report, error = self.run_proof(design)
        self.assertIsNotNone(error)
        self.assertEqual(["base-feature-detected"], report["failures"])
        self.assertEqual(0, design.compute_count)

    def test_a_document_whose_census_disagrees_refuses_before_perturbing(self):
        design = working_design()
        design.parameters[0]._expression = "999 mm"
        report, error = self.run_proof(design)
        self.assertIsNotNone(error)
        self.assertEqual(["rebuild-record-mismatch"], report["failures"])
        self.assertEqual(0, design.compute_count)

    def test_a_missing_component_refuses(self):
        design = working_design()
        design.root_occurrences.items[0].component.name = "SomethingElse"
        report, error = self.run_proof(design)
        self.assertIsNotNone(error)
        self.assertEqual(["rebuild-record-mismatch"], report["failures"])

    def test_a_missing_named_feature_refuses(self):
        design = working_design()
        design.timeline_items[0].entity.name = "somebody_elses_feature"
        report, error = self.run_proof(design)
        self.assertIsNotNone(error)
        self.assertEqual(["rebuild-record-mismatch"], report["failures"])

    def test_a_missing_api_member_refuses_by_name(self):
        design = working_design()
        original = fakes.FakeDesign.findEntityByToken
        del fakes.FakeDesign.findEntityByToken
        try:
            report, error = self.run_proof(design)
        finally:
            fakes.FakeDesign.findEntityByToken = original
        self.assertIsNotNone(error)
        self.assertEqual(["editability-capability"], report["failures"])
        self.assertIn("Design.findEntityByToken", report["refusal_detail"]["missing"])

    def test_a_missing_observable_property_refuses_instead_of_reading_as_no_movement(self):
        design = working_design()
        original = fakes.FakeBody.physicalProperties
        del fakes.FakeBody.physicalProperties
        try:
            report, error = self.run_proof(design)
        finally:
            fakes.FakeBody.physicalProperties = original
        self.assertIsNotNone(error)
        self.assertEqual(["editability-capability"], report["failures"])
        self.assertIn("BRepBody.physicalProperties", report["refusal_detail"]["missing"])
        self.assertEqual(0, design.compute_count)

    def test_token_resolution_is_recorded_as_measurement_and_changes_no_verdict(self):
        resolves, _ = self.run_proof(working_design())
        row = next(r for r in resolves["parameters"] if r["name"] == "recon_base_1_depth")
        self.assertEqual({"resolved": 1, "unresolved": 0, "unresolved_tokens": []}, row["entity_tokens"])

        design = working_design()
        design.behaviour["unresolvable_tokens"] = ["token-feature-1"]
        fails, error = self.run_proof(design)
        self.assertIsNone(error, fails)
        self.assertTrue(fails["ok"])
        row = next(r for r in fails["parameters"] if r["name"] == "recon_base_1_depth")
        self.assertEqual(1, row["entity_tokens"]["unresolved"])

    def test_an_unexercised_parameter_is_named_unproven(self):
        payload = spec()
        payload["parameters"][1] = {
            "name": "recon_plane_offset",
            "exercise": False,
            "rationale": "deliberately not perturbed in this run.",
        }
        report, error = self.run_proof(working_design(), payload)
        self.assertIsNone(error, report)
        self.assertEqual(["recon_base_1_depth"], report["checked"])
        self.assertEqual(["recon_plane_offset"], report["not_exercised"])


def _once(hook):
    """Run a hook on the first compute only, so the restore can succeed."""
    state = {"done": False}

    def wrapped(design):
        if not state["done"]:
            state["done"] = True
            hook(design)
        else:
            for item in design.timeline_items:
                item.entity.healthy = True

    return wrapped


class ReportValidatorTests(unittest.TestCase):
    """The host-side gate an orchestrating agent actually calls."""

    def setUp(self):
        self.document = build_manifest().fusion_document
        self.report, _ = run_transaction(emit(), working_design(), self.document)

    def validate(self, report=None, nonce=NONCE):
        return validate_editability_report(
            report if report is not None else self.report,
            nonce=nonce,
            rebuild_record=rebuild_record(),
        )

    def test_a_live_report_validates_and_says_what_it_proves(self):
        verdict = self.validate()
        self.assertTrue(verdict["ok"], verdict["problems"])
        self.assertEqual(
            ["recon_base_1_depth", "recon_plane_offset"], verdict["checked"]
        )
        self.assertIn("perturbed one at a time", verdict["proves"])

    def test_a_report_with_the_wrong_nonce_is_refused(self):
        verdict = self.validate(nonce="0" * 32)
        self.assertFalse(verdict["ok"])
        self.assertTrue(any("nonce" in problem for problem in verdict["problems"]))

    def test_a_hand_written_report_cannot_satisfy_the_gate(self):
        forged = {
            "kind": "mesh-editability",
            "ok": True,
            "checked": ["recon_base_1_depth", "recon_plane_offset"],
            "not_exercised": [],
            "failures": [],
            "parameters": [],
            "interactions_exercised": False,
        }
        verdict = self.validate(forged)
        self.assertFalse(verdict["ok"])

    def test_checked_may_not_name_a_parameter_the_rebuild_never_created(self):
        report = json.loads(json.dumps(self.report))
        report["checked"].append("invented_parameter")
        verdict = self.validate(report)
        self.assertFalse(verdict["ok"])
        self.assertTrue(any("never created" in problem for problem in verdict["problems"]))

    def test_a_parameter_neither_checked_nor_named_unexercised_is_caught(self):
        report = json.loads(json.dumps(self.report))
        report["checked"].remove("recon_plane_offset")
        verdict = self.validate(report)
        self.assertFalse(verdict["ok"])
        self.assertTrue(
            any("neither proven nor listed" in problem for problem in verdict["problems"])
        )

    def test_a_report_claiming_ok_alongside_a_failure_is_refused(self):
        report = json.loads(json.dumps(self.report))
        report["failures"] = ["parameter-inert"]
        verdict = self.validate(report)
        self.assertFalse(verdict["ok"])

    def test_a_failure_outside_the_closed_vocabulary_is_refused(self):
        report = json.loads(json.dumps(self.report))
        report["ok"] = False
        report["failures"] = ["it-did-not-feel-right"]
        verdict = self.validate(report)
        self.assertFalse(verdict["ok"])
        self.assertTrue(
            any("closed vocabulary" in problem for problem in verdict["problems"])
        )

    def test_a_report_that_hides_the_interactions_caveat_is_refused(self):
        report = json.loads(json.dumps(self.report))
        report.pop("interactions_exercised")
        verdict = self.validate(report)
        self.assertFalse(verdict["ok"])

    def test_a_checked_name_with_no_measurement_behind_it_is_refused(self):
        # The nonce proves the report came from the emitted script. It does not
        # prove any individual name in `checked` earned its place, so the gate
        # re-derives every one from the row that recorded the measurement.
        report = json.loads(json.dumps(self.report))
        report["parameters"] = [
            row for row in report["parameters"] if row["name"] != "recon_plane_offset"
        ]
        verdict = self.validate(report)
        self.assertFalse(verdict["ok"])
        self.assertTrue(any("no measurement" in problem for problem in verdict["problems"]))

    def test_a_checked_name_whose_row_never_restored_is_refused(self):
        report = json.loads(json.dumps(self.report))
        for row in report["parameters"]:
            row.pop("restore_gap", None)
        verdict = self.validate(report)
        self.assertFalse(verdict["ok"])
        self.assertTrue(
            any("never shown to come back" in problem for problem in verdict["problems"])
        )

    def test_a_checked_name_whose_row_records_a_failure_is_refused(self):
        report = json.loads(json.dumps(self.report))
        report["parameters"][0]["failure"] = "parameter-inert"
        verdict = self.validate(report)
        self.assertFalse(verdict["ok"])

    def test_a_report_bound_to_another_rebuild_is_refused(self):
        report = json.loads(json.dumps(self.report))
        report["program_sha256"] = "9" * 64
        verdict = self.validate(report)
        self.assertFalse(verdict["ok"])


if __name__ == "__main__":
    unittest.main()
