from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-skill.sh"


class InstallSkillScriptTests(unittest.TestCase):
    def test_refuses_to_overwrite_existing_skill_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skills_root = Path(temporary)
            destination = skills_root / "fusion-parametric-design"
            destination.mkdir()
            sentinel = destination / "local-change.txt"
            sentinel.write_text("preserve me", encoding="utf-8")

            result = subprocess.run(
                [str(INSTALLER), str(skills_root)],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(2, result.returncode)
            self.assertTrue(sentinel.is_file())
            self.assertIn("already exists", result.stderr)

    def test_force_installs_complete_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            source = temporary_root / "source"
            shutil.copytree(
                ROOT,
                source,
                ignore=shutil.ignore_patterns(
                    ".venv", "build", "__pycache__", "*.egg-info", "*.pyc", "*.pyo", ".DS_Store"
                ),
            )
            (source / ".venv").mkdir()
            (source / ".venv" / "host-only").write_text("ignore", encoding="utf-8")
            (source / "build").mkdir()
            (source / "build" / "generated.py").write_text("ignore", encoding="utf-8")
            skills_root = temporary_root / "skills"
            skills_root.mkdir()
            destination = skills_root / "fusion-parametric-design"
            destination.mkdir()
            (destination / "obsolete.txt").write_text("old", encoding="utf-8")

            result = subprocess.run(
                [str(source / "scripts" / "install-skill.sh"), "--force", str(skills_root)],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue((destination / "SKILL.md").is_file())
            self.assertTrue((destination / "references" / "unsupported.md").is_file())
            self.assertFalse((destination / "obsolete.txt").exists())
            self.assertFalse((destination / ".venv").exists())
            self.assertFalse((destination / "build").exists())
            self.assertFalse(any(destination.rglob("__pycache__")))


if __name__ == "__main__":
    unittest.main()
