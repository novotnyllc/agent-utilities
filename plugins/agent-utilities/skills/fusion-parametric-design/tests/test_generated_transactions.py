"""Behavioural tests for the generated transactions.

These drive the real emitted functions -- `_semantic_path_from_full_path`,
`_root_context_occurrence_map`, `_body_summary`, `_timeline_health`, and both
`run()` entry points -- against geometry doubles instead of substituting the
functions under test with lambdas.
"""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from fusion_design.manifest import Manifest, load_manifest
from fusion_design.positive_control import emit_positive_control_script
from fusion_design.scripts import (
    emit_inventory_script,
    emit_scaffold_script,
    emit_verification_script,
    manifest_sha256,
)

from test_scripts import load_generated_script


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "electronics-enclosure" / "fusion-project.json"
ATTRIBUTE_GROUP = "fusion_parametric_design"
IDENTITY = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]


class FakeList:
    def __init__(self, items=()):
        self.items = list(items)

    @property
    def count(self):
        return len(self.items)

    def item(self, index):
        return self.items[index]


class FakeBody:
    """A B-Rep body double. Fusion reports volume in cm3 and points in cm."""

    def __init__(self, name, volume_mm3, is_solid=True, min_mm=(0.0, 0.0, 0.0), max_mm=(10.0, 10.0, 10.0)):
        self.name = name
        self.volume = volume_mm3 / 1000.0
        self.isSolid = is_solid
        self.isValid = True
        self.min_mm = list(min_mm)
        self.max_mm = list(max_mm)
        self.deleted = False

    def deleteMe(self):
        self.deleted = True
        self.isValid = False
        return True


class FakeBodies(FakeList):
    def add(self, temporary_body, base_feature):
        body = FakeBody(
            "unnamed",
            temporary_body.volume_cm3 * 1000.0,
            min_mm=[value * 10.0 for value in temporary_body.min_cm],
            max_mm=[value * 10.0 for value in temporary_body.max_cm],
        )
        self.items.append(body)
        return body


class FakeAttributes:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def itemByName(self, group, name):
        if (group, name) not in self.values:
            return None
        return SimpleNamespace(
            value=self.values[(group, name)],
            deleteMe=lambda: self.values.pop((group, name), None) is not None,
        )

    def add(self, group, name, value):
        self.values[(group, name)] = value
        return SimpleNamespace(value=value)


class FakeBaseFeature:
    def __init__(self):
        self.isValid = True
        self.deleted = False

    def startEdit(self):
        return True

    def finishEdit(self):
        return True

    def deleteMe(self):
        self.deleted = True
        self.isValid = False
        return True


class FakeBaseFeatures:
    def __init__(self):
        self.created = []

    def add(self):
        feature = FakeBaseFeature()
        self.created.append(feature)
        return feature


class FakeComponent:
    def __init__(self, name, bodies=(), mesh_body_count=0, attributes=None):
        self.name = name
        self.bRepBodies = FakeBodies(bodies)
        self.meshBodies = FakeList([SimpleNamespace()] * mesh_body_count)
        self.attributes = FakeAttributes(attributes)
        self.features = SimpleNamespace(baseFeatures=FakeBaseFeatures())
        self.occurrences = FakeList()


class FakeOccurrence:
    def __init__(self, full_path_name, component, is_suppressed=False, transform=IDENTITY):
        self.fullPathName = full_path_name
        self.component = component
        # A root-context proxy exposes the same bodies as its component.
        self.bRepBodies = component.bRepBodies
        self.transform2 = SimpleNamespace(asArray=lambda: list(transform)) if transform else None
        self.isSuppressed = is_suppressed
        self.isLightBulbOn = True
        self.isVisible = not is_suppressed

    def _bounds_cm(self):
        bodies = [body for body in self.bRepBodies.items if body.isSolid]
        if not bodies:
            return None
        minimum = [min(body.min_mm[axis] for body in bodies) / 10.0 for axis in range(3)]
        maximum = [max(body.max_mm[axis] for body in bodies) / 10.0 for axis in range(3)]
        return SimpleNamespace(
            minPoint=SimpleNamespace(x=minimum[0], y=minimum[1], z=minimum[2]),
            maxPoint=SimpleNamespace(x=maximum[0], y=maximum[1], z=maximum[2]),
        )

    @property
    def preciseBoundingBox(self):
        return self._bounds_cm()

    def boundingBox2(self, entity_type):
        return self._bounds_cm()


def full_path_name(path):
    """Fusion's occurrence path form: `A:1+B:1`, root component omitted."""
    return "+".join(segment + ":1" for segment in path.split("/"))


def build_occurrences(manifest, body_factory, suppressed=()):
    occurrences = {}
    for path in manifest.component_tree:
        leaf = path.rsplit("/", 1)[-1]
        component = FakeComponent(
            leaf,
            bodies=body_factory(path),
            attributes={
                (ATTRIBUTE_GROUP, "managed"): "true",
                (ATTRIBUTE_GROUP, "manifest_sha256"): manifest_sha256(manifest),
            },
        )
        occurrences[path] = FakeOccurrence(
            full_path_name(path), component, is_suppressed=path in suppressed
        )
    return occurrences


def solid_part(path):
    """One healthy solid per component, sized well above the declared floors."""
    leaf = path.rsplit("/", 1)[-1]
    return [FakeBody(leaf + "__BODY", 5000.0, min_mm=(0.0, 0.0, 0.0), max_mm=(20.0, 20.0, 12.5))]


class FakeTimeline(FakeList):
    @staticmethod
    def with_states(states):
        return FakeTimeline(
            [SimpleNamespace(healthState=state, entity=None) for state in states]
        )


def verification_harness(
    manifest,
    occurrences,
    *,
    timeline_states=("healthy",),
    distance_cm=0.5,
    interferences=(),
    compute=True,
    nonce="",
):
    namespace = load_generated_script(emit_verification_script(manifest, nonce))
    root = SimpleNamespace(name="Root", allOccurrences=FakeList(list(occurrences.values())))
    parameters = {
        spec["name"]: SimpleNamespace(expression=spec["expression"], unit=spec["units"])
        for spec in namespace["PARAMETER_SPECS"]
    }
    design = SimpleNamespace(
        designType="parametric",
        rootComponent=root,
        computeAll=lambda: compute,
        userParameters=SimpleNamespace(itemByName=parameters.get),
        timeline=FakeTimeline.with_states(timeline_states),
        createInterferenceInput=lambda entities: entities,
        analyzeInterference=lambda analysis_input: FakeList(list(interferences)),
    )
    app = SimpleNamespace(
        activeDocument=SimpleNamespace(name=manifest.fusion_document),
        measureManager=SimpleNamespace(
            measureMinimumDistance=lambda one, two: SimpleNamespace(value=distance_cm)
        ),
    )
    namespace["_active_design"] = lambda: (app, design)
    return namespace, app, design


def run_and_capture(namespace, expect_failure=True):
    output = StringIO()
    error = None
    with redirect_stdout(output):
        try:
            namespace["run"](None)
        except Exception as raised:  # noqa: BLE001 - the report is the assertion target
            error = raised
    reports = [
        json.loads(line) for line in output.getvalue().splitlines() if line.startswith("{")
    ]
    if expect_failure and error is None:
        raise AssertionError("expected the transaction to raise; it did not")
    if not expect_failure and error is not None:
        raise error
    return reports, error


class OccurrenceMapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = load_manifest(EXAMPLE)
        self.namespace = load_generated_script(emit_verification_script(self.manifest))

    def test_semantic_path_handles_real_full_path_names(self) -> None:
        semantic_path = self.namespace["_semantic_path_from_full_path"]
        self.assertEqual("A/B", semantic_path("A:1+B:1", "Root"))
        self.assertEqual("A/B", semantic_path("Root:1+A:1+B:1", "Root"))
        self.assertEqual("A/B", semantic_path("A:1+B:12", "Root"))
        # A ':' that is not an instance suffix belongs to the component name.
        self.assertEqual("A:left/B", semantic_path("A:left:1+B:1", "Root"))
        self.assertEqual("", semantic_path("Root:1", "Root"))

    def test_root_context_map_keys_paths_and_records_duplicates_as_a_dict(self) -> None:
        occurrence_map = self.namespace["_root_context_occurrence_map"]
        first = FakeOccurrence("Product:1+Base:1", FakeComponent("Base"))
        duplicate = FakeOccurrence("Product:1+Base:2", FakeComponent("Base"))
        lid = FakeOccurrence("Product:1+Lid:1", FakeComponent("Lid"))
        parent = FakeOccurrence("Product:1", FakeComponent("Product"))
        root_itself = FakeOccurrence("Root:1", FakeComponent("Root"))
        root = SimpleNamespace(
            name="Root",
            allOccurrences=FakeList([parent, first, duplicate, lid, root_itself]),
        )

        paths, mapping, duplicates = occurrence_map(root)

        self.assertEqual(
            ["Product", "Product/Base", "Product/Lid"], paths
        )
        self.assertIs(first, mapping["Product/Base"])
        self.assertIsInstance(duplicates, dict)
        self.assertEqual(
            {
                "Product/Base": [
                    "Product:1+Base:1",
                    "Product:1+Base:2",
                ]
            },
            duplicates,
        )

    def test_body_summary_classifies_sliver_surface_and_mesh_bodies(self) -> None:
        occurrence = FakeOccurrence(
            "Product:1+Base:1",
            FakeComponent(
                "Base",
                bodies=[
                    FakeBody("Base__SOLID", 5000.0),
                    FakeBody("SLIVER", 1e-6),
                    FakeBody("SURFACE", 0.0, is_solid=False),
                ],
                mesh_body_count=2,
            ),
        )

        summary = self.namespace["_body_summary"](occurrence)

        self.assertEqual(3, summary["brep_body_count"])
        self.assertEqual(1, summary["surface_or_zero_volume_body_count"])
        self.assertEqual(2, summary["mesh_body_count"])
        # The sliver counts as a solid: this is exactly why the print-part gate
        # is measured against a declared minimum volume instead of this flag.
        self.assertEqual(2, summary["solid_body_count"])
        self.assertTrue(summary["has_positive_solid"])
        self.assertAlmostEqual(5000.0 + 1e-6, summary["total_solid_volume_mm3"])
        self.assertEqual(
            ["Base__SOLID", "SLIVER", "SURFACE"],
            [row["name"] for row in summary["bodies"]],
        )

    def test_timeline_health_reports_suppression_separately(self) -> None:
        timeline_health = self.namespace["_timeline_health"]
        design = SimpleNamespace(
            timeline=FakeTimeline.with_states(("healthy", "suppressed", "warning", "unknown"))
        )

        health = timeline_health(design)

        self.assertEqual(4, health["count"])
        self.assertEqual([1], [row["index"] for row in health["suppressed"]])
        self.assertEqual([2], [row["index"] for row in health["unhealthy"]])
        self.assertEqual([3], [row["index"] for row in health["informational"]])


class VerificationRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = load_manifest(EXAMPLE)

    def test_declared_geometry_passes_and_measures_clearance_and_interference(self) -> None:
        occurrences = build_occurrences(self.manifest, solid_part)
        namespace, _, _ = verification_harness(self.manifest, occurrences)

        reports, _ = run_and_capture(namespace, expect_failure=False)

        report = reports[0]
        self.assertEqual([], report["failures"])
        self.assertTrue(report["ok"])
        self.assertEqual([], report["print_part_failures"])
        self.assertEqual([5.0], [row["distance_mm"] for row in report["clearance_results"]])
        self.assertTrue(all(row["ok"] for row in report["clearance_results"]))
        self.assertEqual([0, 0], [row["count"] for row in report["interference_results"]])
        self.assertEqual(IDENTITY, report["occurrence_transforms"]["Product/Base"])
        self.assertEqual(
            {"is_suppressed": False, "is_light_bulb_on": True, "is_visible": True},
            report["occurrence_states"]["Product/Base"],
        )
        self.assertEqual(
            {"min": [0.0, 0.0, 0.0], "max": [20.0, 20.0, 12.5]},
            report["brep_bounding_boxes_mm"]["Product/Base"],
        )

    def test_checked_names_only_the_gates_the_run_performed(self) -> None:
        # A manifest declaring no clearance, interference or print-part checks
        # must not report those gates as checked: claiming a gate that was never
        # defined turns an honest gap into a positive false assurance.
        data = self.manifest.to_dict()
        data["verification"] = {
            "required_components": [],
            "clearance_checks": [],
            "interference_checks": [],
            "expected_print_parts": [],
        }
        data.pop("printable_parts", None)
        data["parameters"] = []
        manifest = Manifest.from_data(data, validate=False)
        namespace, _, _ = verification_harness(manifest, {})

        reports, _ = run_and_capture(namespace, expect_failure=False)

        # Nothing was declared, so nothing but the unconditional gates ran --
        # and `ok` is true, which is precisely why `checked` must not lie.
        report = reports[0]
        self.assertTrue(report["ok"])
        self.assertEqual(
            ["compute-all", "design-type", "timeline-health", "timeline-suppressed"],
            report["checked"],
        )
        for token in ("clearance", "interference", "print-parts", "required-components", "parameters"):
            self.assertNotIn(token, report["checked"], token)
            self.assertIn(token, report["not_declared"], token)

    def test_checked_includes_every_gate_the_example_declares(self) -> None:
        occurrences = build_occurrences(self.manifest, solid_part)
        namespace, _, _ = verification_harness(self.manifest, occurrences)

        reports, _ = run_and_capture(namespace, expect_failure=False)

        report = reports[0]
        for token in (
            "clearance",
            "interference",
            "print-parts",
            "required-components",
            "suppressed-occurrence",
            "unreadable-occurrence-state",
        ):
            self.assertIn(token, report["checked"], token)
        self.assertEqual([], report["not_declared"])

    def test_undeclared_print_part_is_a_checked_failure_not_an_omission(self) -> None:
        # `expected_print_parts` without `printable_parts` means the gate ran and
        # failed for want of a declaration -- it must not read as "not declared".
        data = self.manifest.to_dict()
        data.pop("printable_parts")
        manifest = Manifest.from_data(data)
        occurrences = build_occurrences(manifest, solid_part)
        namespace, _, _ = verification_harness(manifest, occurrences)

        reports, _ = run_and_capture(namespace)

        report = reports[0]
        self.assertIn("print-parts", report["checked"])
        self.assertNotIn("print-parts", report["not_declared"])
        self.assertIn("print-parts", report["failures"])

    def test_verification_report_echoes_the_emitted_nonce(self) -> None:
        # The nonce is what binds an export to a report this CLI emitted; a
        # report that cannot echo it cannot justify an export.
        occurrences = build_occurrences(self.manifest, solid_part)
        namespace, _, _ = verification_harness(self.manifest, occurrences)
        reports, _ = run_and_capture(namespace, expect_failure=False)
        self.assertEqual("", reports[0]["verification_nonce"])

        namespace, _, _ = verification_harness(
            self.manifest, build_occurrences(self.manifest, solid_part), nonce="cafe" * 8
        )
        reports, _ = run_and_capture(namespace, expect_failure=False)
        self.assertEqual("cafe" * 8, reports[0]["verification_nonce"])

    def test_sliver_print_part_fails_the_declared_minimum_volume(self) -> None:
        def slivers(path):
            if path in self.manifest.verification["expected_print_parts"]:
                return [FakeBody(path.rsplit("/", 1)[-1] + "__BODY", 1e-6)]
            return solid_part(path)

        occurrences = build_occurrences(self.manifest, slivers)
        namespace, _, _ = verification_harness(self.manifest, occurrences)

        reports, _ = run_and_capture(namespace)

        report = reports[0]
        self.assertFalse(report["ok"])
        self.assertIn("print-parts", report["failures"])
        self.assertEqual(
            {"below-declared-minimum-volume"},
            {row["reason"] for row in report["print_part_failures"]},
        )
        self.assertEqual(
            sorted(self.manifest.verification["expected_print_parts"]),
            sorted(row["path"] for row in report["print_part_failures"]),
        )

    def test_extra_solid_body_fails_the_declared_body_count(self) -> None:
        def two_solids(path):
            bodies = solid_part(path)
            if path == "Product/Base":
                bodies.append(FakeBody("VESTIGIAL", 4000.0))
            return bodies

        occurrences = build_occurrences(self.manifest, two_solids)
        namespace, _, _ = verification_harness(self.manifest, occurrences)

        reports, _ = run_and_capture(namespace)

        failure = next(
            row
            for row in reports[0]["print_part_failures"]
            if row["path"] == "Product/Base"
        )
        self.assertEqual("solid-body-count", failure["reason"])
        self.assertEqual(1, failure["expected"])
        self.assertEqual(2, failure["actual"])

    def test_declared_body_name_mismatch_fails_verification(self) -> None:
        data = self.manifest.to_dict()
        data["printable_parts"][0]["body_name"] = "PROD_BASE_SHELL"
        manifest = Manifest.from_data(data)
        occurrences = build_occurrences(manifest, solid_part)
        namespace, _, _ = verification_harness(manifest, occurrences)

        reports, _ = run_and_capture(namespace)

        failure = next(
            row
            for row in reports[0]["print_part_failures"]
            if row["path"] == "Product/Base"
        )
        self.assertEqual("body-name-mismatch", failure["reason"])
        self.assertEqual("PROD_BASE_SHELL", failure["expected"])
        self.assertEqual("Base__BODY", failure["actual"])

    def test_print_part_without_a_declared_expectation_fails(self) -> None:
        data = self.manifest.to_dict()
        data.pop("printable_parts")
        manifest = Manifest.from_data(data)
        occurrences = build_occurrences(manifest, solid_part)
        namespace, _, _ = verification_harness(manifest, occurrences)

        reports, _ = run_and_capture(namespace)

        self.assertEqual(
            {"no-declared-expectation"},
            {row["reason"] for row in reports[0]["print_part_failures"]},
        )

    def test_forged_minimum_volume_is_implausible_against_the_bounding_box(self) -> None:
        # The supported authoring path: declare a floor low enough that a sliver
        # clears it. The bounding box the author did not choose catches it.
        data = self.manifest.to_dict()
        for part in data["printable_parts"]:
            part["minimum_volume_mm3"] = 1e-12
        manifest = Manifest.from_data(data)

        def slivers(path):
            if path in manifest.verification["expected_print_parts"]:
                # A part-sized envelope holding 1e-6 mm3 of material.
                return [
                    FakeBody(
                        path.rsplit("/", 1)[-1] + "__BODY",
                        1e-6,
                        min_mm=(0.0, 0.0, 0.0),
                        max_mm=(20.0, 20.0, 12.5),
                    )
                ]
            return solid_part(path)

        occurrences = build_occurrences(manifest, slivers)
        namespace, _, _ = verification_harness(manifest, occurrences)

        reports, _ = run_and_capture(namespace)

        report = reports[0]
        self.assertFalse(report["ok"])
        self.assertIn("print-parts", report["failures"])
        self.assertEqual(
            {"implausible-declared-minimum"},
            {row["reason"] for row in report["print_part_failures"]},
        )
        failure = report["print_part_failures"][0]
        self.assertEqual(5000.0, failure["bounding_box_volume_mm3"])
        self.assertEqual(1e-3, report["print_part_rules"]["minimum_volume_bounding_box_fraction"])
        # The hard-coded rules are reported apart from the declared expectations.
        self.assertEqual(
            {"minimum_volume_mm3"},
            set(report["print_part_expectations"]["Product/Base"]),
        )
        self.assertEqual(1, report["print_part_rules"]["solid_body_count"])

    def test_unreadable_occurrence_state_fails_closed(self) -> None:
        occurrences = build_occurrences(self.manifest, solid_part)

        class OpaqueOccurrence:
            """An occurrence whose participation state cannot be read."""

            def __init__(self, inner):
                self._inner = inner

            def __getattr__(self, name):
                if name == "isSuppressed":
                    raise RuntimeError("Fusion did not expose isSuppressed")
                return getattr(self._inner, name)

        target = "References/USB-C Insertion Keep-Out"
        occurrences[target] = OpaqueOccurrence(occurrences[target])
        namespace, _, _ = verification_harness(self.manifest, occurrences)

        reports, _ = run_and_capture(namespace)

        report = reports[0]
        self.assertFalse(report["ok"])
        self.assertIn("unreadable-occurrence-state", report["failures"])
        self.assertEqual([target], report["unreadable_occurrence_states"])
        self.assertEqual([], report["suppressed_occurrences"])
        self.assertIsNone(report["occurrence_states"][target]["is_suppressed"])

    def test_declared_suppression_is_recorded_and_passes(self) -> None:
        target = "References/USB-C Insertion Keep-Out"
        data = self.manifest.to_dict()
        data["verification"]["allowed_suppressed_paths"] = [target]
        data["verification"]["allow_suppressed_timeline_features"] = True
        manifest = Manifest.from_data(data)
        occurrences = build_occurrences(manifest, solid_part, suppressed=(target,))
        namespace, _, _ = verification_harness(
            manifest, occurrences, timeline_states=("healthy", "suppressed")
        )

        reports, _ = run_and_capture(namespace, expect_failure=False)

        report = reports[0]
        self.assertTrue(report["ok"])
        self.assertEqual([], report["failures"])
        self.assertEqual([target], report["suppressed_occurrences"])
        self.assertEqual([], report["undeclared_suppressed_occurrences"])
        self.assertEqual(1, len(report["timeline"]["suppressed"]))

    def test_all_timeline_features_suppressed_is_a_failure(self) -> None:
        occurrences = build_occurrences(self.manifest, solid_part)
        namespace, _, _ = verification_harness(
            self.manifest, occurrences, timeline_states=("suppressed",) * 12
        )

        reports, _ = run_and_capture(namespace)

        report = reports[0]
        self.assertFalse(report["ok"])
        self.assertIn("timeline-suppressed", report["failures"])
        self.assertEqual([], report["timeline"]["unhealthy"])
        self.assertEqual(12, len(report["timeline"]["suppressed"]))

    def test_suppressed_occurrence_is_recorded_and_fails(self) -> None:
        occurrences = build_occurrences(
            self.manifest, solid_part, suppressed=("References/USB-C Insertion Keep-Out",)
        )
        namespace, _, _ = verification_harness(self.manifest, occurrences)

        reports, _ = run_and_capture(namespace)

        report = reports[0]
        self.assertIn("suppressed-occurrence", report["failures"])
        self.assertEqual(["References/USB-C Insertion Keep-Out"], report["suppressed_occurrences"])
        self.assertTrue(
            report["occurrence_states"]["References/USB-C Insertion Keep-Out"]["is_suppressed"]
        )

    def test_clearance_below_the_manifest_minimum_fails(self) -> None:
        occurrences = build_occurrences(self.manifest, solid_part)
        namespace, _, _ = verification_harness(self.manifest, occurrences, distance_cm=0.05)

        reports, _ = run_and_capture(namespace)

        report = reports[0]
        self.assertIn("clearance", report["failures"])
        self.assertEqual([0.5], [row["distance_mm"] for row in report["clearance_results"]])
        self.assertEqual([False], [row["ok"] for row in report["clearance_results"]])

    def test_found_interference_fails_and_reports_the_pair(self) -> None:
        occurrences = build_occurrences(self.manifest, solid_part)
        interference = SimpleNamespace(
            interferenceBody=SimpleNamespace(volume=0.25),
            entityOne=SimpleNamespace(fullPathName="References:1+USB-C Insertion Keep-Out:1"),
            entityTwo=SimpleNamespace(fullPathName="Product:1+Base:1"),
        )
        namespace, _, _ = verification_harness(
            self.manifest, occurrences, interferences=(interference,)
        )

        reports, _ = run_and_capture(namespace)

        report = reports[0]
        self.assertIn("interference", report["failures"])
        first = report["interference_results"][0]
        self.assertEqual(1, first["count"])
        self.assertFalse(first["ok"])
        self.assertAlmostEqual(250.0, first["total_interference_volume_mm3"])
        self.assertEqual(
            "References:1+USB-C Insertion Keep-Out:1", first["pairs"][0]["entity_one"]
        )

    def test_duplicate_semantic_path_on_a_checked_component_fails(self) -> None:
        occurrences = build_occurrences(self.manifest, solid_part)
        clone = FakeOccurrence(
            "Product:1+Base:2",
            FakeComponent("Base", bodies=solid_part("Product/Base")),
        )
        occurrences["Product/Base__clone"] = clone
        namespace, _, _ = verification_harness(self.manifest, occurrences)

        reports, _ = run_and_capture(namespace)

        report = reports[0]
        self.assertIn("ambiguous-components", report["failures"])
        self.assertEqual(["Product/Base"], report["ambiguous_component_paths"])
        self.assertIn("Product/Base", report["duplicate_semantic_paths"])


class InventoryRoleTests(unittest.TestCase):
    """Roles are read attribute-first; legacy shouty names are an adoption
    fallback, and an unreadable probe is disclosed, never silently blank."""

    def setUp(self) -> None:
        self.role = load_generated_script(emit_inventory_script(load_manifest(EXAMPLE)))[
            "_component_role"
        ]

    def occurrence(self, name, attributes=None):
        return FakeOccurrence(full_path_name(name), FakeComponent(name, attributes=attributes))

    def test_attribute_wins_over_a_legacy_name(self) -> None:
        occurrence = self.occurrence(
            "PACK__OLD_THING", attributes={(ATTRIBUTE_GROUP, "role"): "keepout"}
        )
        self.assertEqual(
            {"role": "keepout", "provenance": "attribute"},
            self.role(occurrence, "References/PACK__OLD_THING"),
        )

    def test_legacy_prefix_answers_when_no_attribute_is_present(self) -> None:
        occurrence = self.occurrence("PACK__OLD_THING")
        self.assertEqual(
            {"role": "packing", "provenance": "legacy-name"},
            self.role(occurrence, "00_REFERENCES/PACK__OLD_THING"),
        )

    def test_plain_unmanaged_component_is_undeclared(self) -> None:
        occurrence = self.occurrence("Base")
        self.assertEqual(
            {"role": None, "provenance": "undeclared"}, self.role(occurrence, "Product/Base")
        )

    def test_unreadable_probe_is_disclosed_not_blanked(self) -> None:
        occurrence = self.occurrence("Base")

        def broken(group, name):
            raise RuntimeError("attributes offline")

        occurrence.component.attributes.itemByName = broken
        report = self.role(occurrence, "Product/Base")
        self.assertEqual("attribute-unreadable", report["provenance"])
        self.assertIsNone(report["role"])
        self.assertIn("attributes offline", report["attribute_error"])


class GrowableOccurrences(FakeList):
    """The one Fusion behavior _ensure_component_path needs: addNewComponent."""

    def addNewComponent(self, matrix):
        component = FakeComponent("unnamed")
        component.occurrences = GrowableOccurrences([])
        occurrence = SimpleNamespace(component=component)
        self.items.append(occurrence)
        return occurrence


class ScaffoldRunTests(unittest.TestCase):
    def test_scaffold_writes_role_attributes_from_the_manifest(self) -> None:
        manifest = load_manifest(EXAMPLE)
        namespace = load_generated_script(emit_scaffold_script(manifest))
        root = FakeComponent("Root")
        root.occurrences = GrowableOccurrences([])

        components = {}
        for path in manifest.component_tree:
            namespace["_ensure_component_path"](root, path)
            parent = root
            for name in path.split("/"):
                occurrence = namespace["_find_child"](parent, name)
                parent = occurrence.component
            components[path] = parent

        roles = manifest.component_roles()
        self.assertTrue(roles)
        for path, component in components.items():
            attribute = component.attributes.itemByName(ATTRIBUTE_GROUP, "role")
            if path in roles:
                self.assertEqual(roles[path], attribute.value, path)
            else:
                # Group containers carry no role; names stay organizational.
                self.assertIsNone(attribute, path)
            self.assertEqual(
                "true", component.attributes.itemByName(ATTRIBUTE_GROUP, "managed").value
            )

    def test_scaffold_removes_a_role_the_manifest_no_longer_claims(self) -> None:
        # A revision kept the path in component_tree but dropped its
        # classification; the stale attribute must go, or inventory
        # (attribute-first) keeps reporting the obsolete role.
        manifest = load_manifest(EXAMPLE)
        namespace = load_generated_script(emit_scaffold_script(manifest))
        unclassified = next(
            path for path in manifest.component_tree if path not in manifest.component_roles()
        )
        root = FakeComponent("Root")
        root.occurrences = GrowableOccurrences([])
        namespace["_ensure_component_path"](root, unclassified)
        component = namespace["_find_child"](root, unclassified.split("/")[0]).component
        component.attributes.add(ATTRIBUTE_GROUP, "role", "packing")

        _, attribute_updates = namespace["_ensure_component_path"](root, unclassified)

        self.assertIsNone(component.attributes.itemByName(ATTRIBUTE_GROUP, "role"))
        self.assertIn(
            {"component_path": unclassified.split("/")[0], "attributes": ["role-removed"]},
            attribute_updates,
        )

    def test_document_change_discloses_the_components_left_behind(self) -> None:
        manifest = load_manifest(EXAMPLE)
        namespace = load_generated_script(emit_scaffold_script(manifest))
        root = SimpleNamespace(name="Root", allOccurrences=FakeList([]))
        design = SimpleNamespace(
            designType="parametric",
            rootComponent=root,
            computeAll=lambda: True,
            timeline=FakeTimeline.with_states(()),
        )
        app = SimpleNamespace(activeDocument=SimpleNamespace(name=manifest.fusion_document))
        namespace["_active_design"] = lambda: (app, design)
        namespace["_ensure_component_path"] = lambda root_component, path: ([path], [])
        pumps = {"count": 0}

        def switch_document():
            pumps["count"] += 1
            app.activeDocument = SimpleNamespace(name="Some Other Design")

        namespace["adsk"].doEvents = switch_document

        reports, error = run_and_capture(namespace)

        self.assertRegex(str(error), "document changed")
        # Scaffolding cannot roll back, so the failure block must name what it made.
        report = reports[-1]
        self.assertEqual("component-scaffold", report["kind"])
        self.assertFalse(report["ok"])
        # The guard fires on the first periodic pump, part-way through the loop.
        self.assertTrue(report["created"])
        self.assertLess(len(report["created"]), len(namespace["COMPONENT_PATHS"]))
        self.assertLessEqual(set(report["created"]), set(namespace["COMPONENT_PATHS"]))
        self.assertEqual(report["created"], report["left_behind"])


def positive_control_harness(manifest, *, occurrences=None, timeline_states=("healthy",)):
    namespace = load_generated_script(emit_positive_control_script(manifest))
    if occurrences is None:
        occurrences = build_occurrences(manifest, lambda path: [])
    root = SimpleNamespace(name="Root", allOccurrences=FakeList(list(occurrences.values())))
    design = SimpleNamespace(
        designType="parametric",
        rootComponent=root,
        computeAll=lambda: True,
        timeline=FakeTimeline.with_states(timeline_states),
    )
    document = SimpleNamespace(name=manifest.fusion_document, isSaved=False)
    app = SimpleNamespace(activeDocument=document)
    namespace["_active_design"] = lambda: (app, design)
    return namespace, app, design, occurrences


def created_bodies(occurrences):
    return [body for occurrence in occurrences.values() for body in occurrence.bRepBodies.items]


def created_base_features(occurrences):
    return [
        feature
        for occurrence in occurrences.values()
        for feature in occurrence.component.features.baseFeatures.created
    ]


class PositiveControlRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = load_manifest(EXAMPLE)

    def test_run_creates_validated_boxes_and_reports_ok(self) -> None:
        namespace, _, _, occurrences = positive_control_harness(self.manifest)

        reports, _ = run_and_capture(namespace, expect_failure=False)

        report = reports[0]
        self.assertTrue(report["ok"])
        self.assertEqual(
            sorted(spec["path"] for spec in namespace["BOX_SPECS"]), report["created"]
        )
        self.assertEqual([], report["reused"])
        self.assertEqual({}, report["duplicate_semantic_paths"])
        self.assertEqual([], report["scaffold_identity_failures"])
        self.assertEqual(len(namespace["BOX_SPECS"]), len(report["bodies"]))
        for body_report in report["bodies"]:
            for bound in ("min", "max"):
                for expected, actual in zip(
                    body_report["expected_bounds_mm"][bound],
                    body_report["actual_bounds_mm"][bound],
                ):
                    self.assertAlmostEqual(expected, actual, places=9)
        self.assertEqual([], [body for body in created_bodies(occurrences) if body.deleted])

    def test_document_change_leaves_created_geometry_alone_and_discloses_it(self) -> None:
        namespace, app, _, occurrences = positive_control_harness(self.manifest)
        pumps = {"count": 0}

        def switch_document_after_creation():
            pumps["count"] += 1
            if pumps["count"] >= 2:
                app.activeDocument = SimpleNamespace(name="Some Other Design", isSaved=False)

        namespace["adsk"].doEvents = switch_document_after_creation

        reports, error = run_and_capture(namespace)

        self.assertRegex(str(error), "document changed")
        self.assertEqual(
            [], [body for body in created_bodies(occurrences) if body.deleted],
            "cleanup must not delete from a document the transaction has disowned",
        )
        self.assertEqual([], [feature for feature in created_base_features(occurrences) if feature.deleted])
        disclosure = reports[-1]
        self.assertEqual("positive-control", disclosure["kind"])
        self.assertFalse(disclosure["ok"])
        self.assertFalse(disclosure["cleanup"]["performed"])
        self.assertEqual("active-document-changed", disclosure["cleanup"]["reason"])
        self.assertEqual(
            sorted(spec["path"] for spec in namespace["BOX_SPECS"]),
            disclosure["cleanup"]["left_behind"],
        )

    def test_verdict_is_rederived_after_the_final_pump(self) -> None:
        namespace, _, design, occurrences = positive_control_harness(self.manifest)
        target = "Product/Base"
        pumps = {"count": 0}

        def edit_document_during_processing():
            pumps["count"] += 1
            if pumps["count"] != 2:
                return
            clone = FakeOccurrence(full_path_name(target), FakeComponent("Base"))
            design.rootComponent.allOccurrences.items.append(clone)
            occurrences[target].component.attributes.values[
                (ATTRIBUTE_GROUP, "managed")
            ] = "false"

        namespace["adsk"].doEvents = edit_document_during_processing

        reports, _ = run_and_capture(namespace)

        report = reports[0]
        self.assertEqual("positive-control", report["kind"])
        self.assertFalse(report["ok"])
        self.assertIn(target, report["duplicate_semantic_paths"])
        self.assertEqual([target], report["ambiguous_component_paths"])
        self.assertEqual([], report["bodies"])

    def test_revoked_scaffold_identity_after_the_pump_fails_the_verdict(self) -> None:
        namespace, _, _, occurrences = positive_control_harness(self.manifest)
        target = "Product/Base"
        pumps = {"count": 0}

        def revoke_identity():
            pumps["count"] += 1
            if pumps["count"] == 2:
                occurrences[target].component.attributes.values[
                    (ATTRIBUTE_GROUP, "managed")
                ] = "false"

        namespace["adsk"].doEvents = revoke_identity

        reports, _ = run_and_capture(namespace)

        report = reports[0]
        self.assertFalse(report["ok"])
        self.assertEqual({}, report["duplicate_semantic_paths"])
        self.assertEqual(1, len(report["scaffold_identity_failures"]))
        self.assertRegex(report["scaffold_identity_failures"][0], "requires scaffold identity")

    def test_failure_after_the_report_still_discloses_the_cleanup(self) -> None:
        namespace, _, design, occurrences = positive_control_harness(
            self.manifest, timeline_states=("error",)
        )

        reports, error = run_and_capture(namespace)

        self.assertRegex(str(error), "did not satisfy its report contract")
        self.assertEqual(2, len(reports))
        self.assertFalse(reports[0]["ok"])
        disclosure = reports[1]
        self.assertNotIn("cleanup", reports[0])
        self.assertTrue(disclosure["cleanup"]["performed"])
        self.assertEqual(
            sorted(spec["path"] for spec in namespace["BOX_SPECS"]),
            disclosure["cleanup"]["deleted"],
        )
        self.assertEqual([], disclosure["cleanup"]["errors"])
        self.assertTrue(all(body.deleted for body in created_bodies(occurrences)))

    def test_cleanup_errors_are_named_with_their_component_path(self) -> None:
        namespace, _, _, occurrences = positive_control_harness(
            self.manifest, timeline_states=("error",)
        )
        original_delete = FakeBody.deleteMe

        def stubborn_delete(self):
            original_delete(self)
            self.isValid = True
            return False

        FakeBody.deleteMe = stubborn_delete
        try:
            reports, error = run_and_capture(namespace)
        finally:
            FakeBody.deleteMe = original_delete

        self.assertRegex(str(error), "cleanup left partial artifacts")
        cleanup = reports[-1]["cleanup"]
        self.assertEqual(
            {"performed", "reason", "deleted", "errors", "left_behind"}, set(cleanup)
        )
        self.assertEqual([], cleanup["deleted"])
        box_paths = sorted(spec["path"] for spec in namespace["BOX_SPECS"])
        # Every path that failed to delete is still in the document, named as a
        # path -- not buried as a prefix inside a free-text error string.
        self.assertEqual(box_paths, cleanup["left_behind"])
        self.assertEqual(box_paths, sorted(row["path"] for row in cleanup["errors"]))
        self.assertRegex(cleanup["errors"][0]["detail"], "body")


if __name__ == "__main__":
    unittest.main()
