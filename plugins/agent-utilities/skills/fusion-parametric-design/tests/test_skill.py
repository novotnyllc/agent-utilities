from __future__ import annotations

from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT
SKILL = SKILL_DIR / "SKILL.md"


class SkillContractTests(unittest.TestCase):
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

    def test_skill_preserves_fusion_native_source_of_truth_and_research_gate(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("The Fusion document is the product", text)
        self.assertIn("Research before asking for measurements", text)
        self.assertIn("Do not start fit-dependent geometry", text)
        self.assertIn("REF__", text)
        self.assertIn("PACK__", text)
        self.assertIn("KEEP__", text)

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

    def test_all_declared_reference_files_exist(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        referenced = re.findall(r"`references/([^`]+\.md)`", text)
        self.assertTrue(referenced)
        for relative in referenced:
            self.assertTrue((SKILL_DIR / "references" / relative).is_file(), relative)


if __name__ == "__main__":
    unittest.main()
