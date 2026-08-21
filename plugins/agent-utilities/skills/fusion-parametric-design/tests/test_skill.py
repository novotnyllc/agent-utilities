from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import unittest

from fusion_design.cli import build_parser


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT
SKILL = SKILL_DIR / "SKILL.md"


def _documented_commands(path: Path, anchor: str) -> set[str]:
    """Command tokens in the fenced block that follows `anchor` in `path`."""
    text = path.read_text(encoding="utf-8")
    block = re.search(re.escape(anchor) + r".*?```[a-z]*\n(?P<body>.*?)```", text, re.DOTALL)
    if block is None:
        raise AssertionError(f"{path.name} has no fenced command block after {anchor!r}")
    return set(re.findall(r"fusion-design\"? (\S+)", block.group("body")))


def _cli_commands() -> set[str]:
    actions = [
        action
        for action in build_parser()._actions
        if isinstance(action, argparse._SubParsersAction)
    ]
    return set(actions[0].choices)


class SkillContractTests(unittest.TestCase):
    def test_documented_command_lists_match_the_cli_exactly(self) -> None:
        # This omission has shipped three times. Both lists are now pinned to
        # build_parser() in both directions, so a new subcommand cannot land
        # undocumented and a removed one cannot linger in the docs.
        commands = _cli_commands()
        self.assertIn("emit-export", commands)
        for path, anchor in (
            (SKILL, "emits narrow Fusion Python transactions, and compares reports:"),
            (SKILL_DIR / "README.md", "Available commands:"),
        ):
            self.assertEqual(commands, _documented_commands(path, anchor), path.name)

    def test_frontmatter_is_discoverable_and_trigger_only(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        match = re.match(r"\A---\n(?P<frontmatter>.*?)\n---\n", text, re.DOTALL)
        self.assertIsNotNone(match)
        frontmatter = match.group("frontmatter")
        self.assertRegex(frontmatter, r"(?m)^name: fusion-parametric-design$")
        description = re.search(r"(?m)^description: (?P<value>.+)$", frontmatter)
        self.assertIsNotNone(description)
        self.assertTrue(description.group("value").startswith("Use when "))
        self.assertLess(len(frontmatter), 1024)

    def test_expert_operator_philosophy_and_prohibitions_are_stated(self) -> None:
        # The skill's spine: expert Fusion operation through thin MCP transport,
        # with the validation-framework prohibition stated unconditionally.
        text = SKILL.read_text(encoding="utf-8")
        for requirement in (
            "You are an expert Fusion user operating Fusion through MCP",
            "sole authority for geometry, feature validity, interference, measurement, and inspection",
            "Never create a validation framework",
            "MCP is transport",
            "stop and report the capability gap",
            "Do not generate monolithic modeling scripts for ordinary design work",
            "unless the user explicitly requests reusable automation, batch generation, or a repeatable product generator",
            "Use Fusion's native built-in functionality comprehensively",
        ):
            self.assertIn(requirement, text, requirement)

    def test_data_placement_and_catalog_gates_precede_geometry(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("Decide data placement before geometry", text)
        self.assertIn(
            "never begins in an arbitrary or unsaved `Untitled` document", text
        )
        self.assertIn("Insert Fastener", text)
        catalog = (SKILL_DIR / "references" / "data-and-catalog.md").read_text(
            encoding="utf-8"
        )
        for requirement in (
            "Insert Fastener",
            "linked external components",
            "canonical",
            "two occurrences of one canonical",
        ):
            self.assertIn(requirement, catalog, requirement)

    def test_base_fusion_first_and_no_extension_assumptions(self) -> None:
        # Paid extensions (Manage, Simulation, ...) are never assumed present;
        # part identity has a base-tier home and extensions get one gentle
        # mention at most.
        text = SKILL.read_text(encoding="utf-8")
        catalog = (SKILL_DIR / "references" / "data-and-catalog.md").read_text(
            encoding="utf-8"
        )
        for requirement in (
            "Base Fusion first",
            "never assume an extension is present",
            "part numbers and part identity require no Manage extension",
            "no workflow built around the assumption of purchase",
        ):
            self.assertIn(requirement, text, requirement)
        self.assertIn("base-tier BOM", catalog)

    def test_component_sourcing_is_proportionate(self) -> None:
        # The CAD-search ladder is fitness-for-purpose, not absolute: a named
        # provisional box is a legitimate occupancy component and sourcing
        # never delays the visible-result loop.
        text = SKILL.read_text(encoding="utf-8")
        catalog = (SKILL_DIR / "references" / "data-and-catalog.md").read_text(
            encoding="utf-8"
        )
        for document in (text, catalog):
            flat = " ".join(document.split())
            self.assertIn("not a failure to source", flat)
            self.assertIn("frequently wrong", flat)
        self.assertIn("Fitness for purpose decides the fidelity", text)
        self.assertIn("never delays the visible-result loop", " ".join(catalog.split()))

    def test_supplied_scan_defaults_to_envelope_not_reconstruction(self) -> None:
        # A scan the design fits around is an occupancy envelope derived with
        # native means; the reconstruction lane is only for rebuilding the
        # scanned object itself as editable CAD.
        text = SKILL.read_text(encoding="utf-8")
        doctrine = (SKILL_DIR / "references" / "mesh-reconstruction.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "A supplied scan is usually an envelope source, not a reconstruction job",
            text,
        )
        self.assertIn("editable CAD model of the scanned object itself", text)
        self.assertIn("an envelope, not a reconstruction job", doctrine)

    def test_free_add_ins_are_first_class_with_the_ui_capability_ladder(self) -> None:
        # Installed add-ins are discovered live and preferred when one owns the
        # job; free recommendations are unhesitant (unlike paid extensions);
        # UI-only capabilities climb probe-API -> computer-use -> ask-user.
        text = SKILL.read_text(encoding="utf-8")
        addins = " ".join(
            (SKILL_DIR / "references" / "add-ins.md")
            .read_text(encoding="utf-8")
            .split()
        )
        self.assertIn("Free add-ins are part of the toolkit", text)
        for requirement in (
            "Discover what is installed, live",
            "Prefer the tool that owns the job",
            "Probe the API at time of use",
            "Drive the UI directly",
            "only when the session has no computer-use capability at all",
            "Recommend missing add-ins proactively",
            "pricingModel=FREE",
            "ParametricText",
            "Wire Generator",
        ):
            self.assertIn(requirement, addins, requirement)
        # The old fallback shape is gone: asking the user is last resort,
        # never the first answer to a UI-only capability.
        self.assertNotIn("ask the user to run that one UI command", text)

    def test_joinery_is_decided_and_modeled_by_default(self) -> None:
        # The expert chooses the join and builds it in — with cataloged
        # fasteners and joints, pattern-matched against the user's prior
        # designs — surfacing the reason in the visual loop, not proposing.
        text = SKILL.read_text(encoding="utf-8")
        workflow = " ".join(
            (SKILL_DIR / "references" / "enclosure-workflow.md")
            .read_text(encoding="utf-8")
            .split()
        )
        for requirement in (
            "Joinery is decided and modeled, not proposed",
            "would print better split",
            "heat-set inserts",
            "without asking first",
            "real geometry, never prose",
            "reuse beats invention",
            "Act, show, iterate",
        ):
            self.assertIn(requirement, text, requirement)
        self.assertIn("print-driven part split", workflow)
        self.assertIn("model it by default", workflow)
        self.assertIn("pattern sources", workflow)

    def test_wiring_doctrine_is_native_and_advisory_only(self) -> None:
        # Wire runs are sweep/pipe modeling with recorded metadata;
        # electrical checking never becomes a host-side engine, and no native
        # harness environment is pretended into existence.
        text = SKILL.read_text(encoding="utf-8")
        workflow = (SKILL_DIR / "references" / "enclosure-workflow.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("never a host-side electrical-validation engine", text)
        flat = " ".join(workflow.split())
        for requirement in (
            "Wiring and terminations",
            "never a host-side electrical-validation engine",
            "no general harness or cable-routing environment",
            "Terminations are components",
        ):
            self.assertIn(requirement, flat, requirement)

    def test_anti_runaway_core_is_stated(self) -> None:
        # The minute-one lane gate, zero repo artifacts for ordinary modeling,
        # the screenshot heartbeat, shown-not-investigated failures, and the
        # latency norms.
        text = SKILL.read_text(encoding="utf-8")
        for requirement in (
            "The lane decision comes first, and ordinary modeling is the default",
            "when in doubt, it is ordinary modeling",
            "no files to the user's repository",
            "misclassification signal",
            "Progress is defined as the user seeing the model",
            "no screenshot in about ten minutes is off the rails",
            "Failures are shown, not silently investigated",
            "within about thirty minutes",
        ):
            self.assertIn(requirement, text, requirement)

    def test_automation_lanes_are_conditional_and_modeling_is_single_operator(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("never invoked for ordinary modeling or visual edits", text)
        self.assertIn("two direct native Fusion approaches fail", text)
        self.assertIn("No review agents before a visible result", text)
        routing = (SKILL_DIR / "references" / "model-routing.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("one Fusion-operating worker", routing)
        self.assertIn("no reviewer before a visible result", routing)

    def test_skill_and_references_carry_no_transition_language(self) -> None:
        # The skill describes how things work, in the present tense.
        paths = [SKILL, *sorted((SKILL_DIR / "references").glob("*.md"))]
        for path in paths:
            lowered = path.read_text(encoding="utf-8").lower()
            for word in ("legacy", "migration", "previously"):
                self.assertNotIn(word, lowered, f"{path.name}: {word}")

    def test_skill_preserves_fusion_native_source_of_truth_and_research_gate(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("The Fusion document is the product", text)
        self.assertIn("Research before asking for measurements", text)
        self.assertIn("Do not start fit-dependent geometry", text)
        # Browser names are humane; machine roles ride on attributes, with the
        # shouty name prefixes recognized only as an adoption fallback.
        self.assertIn("References/", text)
        self.assertIn("PD Trigger Envelope:1", text)
        self.assertIn("role `reference`", text)
        self.assertIn("role `packing`", text)
        self.assertIn("role `keepout`", text)
        self.assertIn("adoption fallback", text)
        self.assertNotIn("00_REFERENCES", text)

    def test_mcp_onboarding_delegates_to_roundhouse_shim(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        for requirement in (
            "roundhouse:mcp-shim",
            "codex plugin add roundhouse --marketplace novotnyllc",
            "claude plugin install roundhouse@novotnyllc",
            "http://127.0.0.1:27182/mcp",
            "Preferences > General > API",
            "codex mcp get <name>",
            "claude mcp get <name>",
        ):
            self.assertIn(requirement, text, requirement)
        self.assertNotIn("mcp-siding.mjs", text)

    def test_mesh_packing_requires_checkable_brep_for_automated_clash_checks(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        unsupported = (SKILL_DIR / "references" / "unsupported.md").read_text(encoding="utf-8")
        self.assertIn("checkable B-Rep envelope", text)
        self.assertIn("Mesh-only automated clearance and interference", unsupported)

    def test_capability_matrix_covers_every_public_nurb_command(self) -> None:
        matrix = (SKILL_DIR / "references" / "capability-matrix.md").read_text(encoding="utf-8")
        commands = [
            "new",
            "dev",
            "build",
            "check",
            "inspect",
            "scan",
            "rules",
            "api",
            "skill",
            "update",
            "card",
            "diff",
            "slice",
            "stress",
            "verify",
            "render",
            "export",
            "extract",
            "launcher",
        ]
        for command in commands:
            self.assertIn(f"`nurb {command}`", matrix, command)
        self.assertIn("Variants", matrix)
        self.assertIn("printer.toml", matrix)

    def test_unsupported_reference_names_non_equivalent_workflows(self) -> None:
        unsupported = (SKILL_DIR / "references" / "unsupported.md").read_text(encoding="utf-8")
        for heading in [
            "Automatic skill update and synchronization",
            "Batch variant runner",
            "Authoritative printer and material profiles",
            "Separate development server or launcher",
            "Headless rendering and verification bundle",
        ]:
            self.assertIn(f"## {heading}", unsupported, heading)

    def test_design_state_handoff_template_is_complete(self) -> None:
        template = ROOT / "templates" / "DESIGN-STATE.md"
        self.assertTrue(template.is_file())
        text = template.read_text(encoding="utf-8")
        for heading in [
            "## Intent and current variant",
            "## Fusion document state",
            "## Source and parameter ledger",
            "## Packing and component ledger",
            "## Verification results",
            "## Physical validation",
            "## Exports",
            "## Rejected decisions",
        ]:
            self.assertIn(heading, text, heading)

    def test_skill_local_cli_wrapper_runs_without_an_editable_install(self) -> None:
        wrapper = SKILL_DIR / "scripts" / "fusion-design"
        self.assertTrue(wrapper.is_file())
        self.assertTrue(wrapper.stat().st_mode & 0o111)
        result = subprocess.run(
            [str(wrapper), "validate", str(ROOT / "examples" / "electronics-enclosure" / "fusion-project.json")],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"ok": true', result.stdout)

    def test_material_decision_gate_is_stated_before_material_dependent_features(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("`references/material-selection.md`", text)
        for requirement in (
            "before finalizing",
            "snap fit or clip",
            "living hinge",
            "press fit",
            "heat-set insert boss",
            "load-bearing connector",
            "proposed, never silently assumed",
            "material_decision",
        ):
            self.assertIn(requirement, text, requirement)

    def test_material_selection_reference_ships_no_numeric_property_values(self) -> None:
        """The skill records material decisions; it does not carry numbers it cannot verify."""
        doctrine = (SKILL_DIR / "references" / "material-selection.md").read_text(encoding="utf-8")
        # Ordered-list markers are the only digits the document may contain.
        body = re.sub(r"(?m)^\d+\. ", "", doctrine)
        self.assertNotRegex(body, r"\d")
        # A spelled-out property value is the same violation with no digit in it,
        # so guard the unit and property tokens that would have to accompany one.
        self.assertNotRegex(body.lower(), r"°|\b(degrees?|mpa|psi|gpa|percent|mm)\b")

    def test_declared_reference_files_and_shipped_ones_are_the_same_set(self) -> None:
        # Both directions: a declared file that is missing breaks the skill, and
        # a shipped file nothing declares is doctrine no agent will ever read.
        text = SKILL.read_text(encoding="utf-8")
        referenced = set(re.findall(r"`references/([^`]+\.md)`", text))
        self.assertTrue(referenced)
        shipped = {path.name for path in (SKILL_DIR / "references").glob("*.md")}
        self.assertEqual(shipped, referenced)

    def test_mesh_reconstruction_doctrine_states_the_gate_and_the_api_boundary(self) -> None:
        doctrine = (SKILL_DIR / "references" / "mesh-reconstruction.md").read_text(encoding="utf-8")
        skill = SKILL.read_text(encoding="utf-8")
        capability = (SKILL_DIR / "references" / "capability-matrix.md").read_text(encoding="utf-8")
        unsupported = (SKILL_DIR / "references" / "unsupported.md").read_text(encoding="utf-8")
        for requirement in ("mesh-edit", "faceted-brep", "parametric-rebuild"):
            self.assertIn(requirement, doctrine, requirement)
        self.assertIn("Classify the edit before converting", skill)
        self.assertIn("references/mesh-reconstruction.md", skill)
        for document, name in ((capability, "capability-matrix"), (unsupported, "unsupported")):
            self.assertIn("Mesh Section Sketch", document, name)
            self.assertIn("Fit Curves", document, name)
            self.assertIn("UI-only", document, name)
            self.assertIn("compareWith", document, name)
            self.assertIn("preview", document, name)


if __name__ == "__main__":
    unittest.main()
