from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import errno
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from fusion_design.cli import main
from fusion_design import module_cache
from fusion_design.module_cache import (
    default_cache_root,
    emit_module_bootstrap,
    prepare_module_bundle,
    verify_module_bundle,
)


@unittest.skipIf(os.name == "nt", "Fusion MCP module cache requires POSIX semantics")
class ModuleCacheTests(unittest.TestCase):
    def _package(self, root: Path) -> Path:
        package = root / "authoring_package"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "helper.py").write_text("def answer():\n    return 42\n", encoding="utf-8")
        (package / "entry.py").write_text(
            "from .helper import answer\n\ndef run(context):\n    context.append(answer())\n",
            encoding="utf-8",
        )
        return package

    def test_prepare_reuses_content_addressed_bundle_and_bootstrap_cleans_up(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            package = self._package(root)
            cache = root / "persistent-cache"
            first = prepare_module_bundle(str(package), "entry", str(cache))
            second = prepare_module_bundle(str(package), "entry", str(cache))
            self.assertEqual(first, second)
            self.assertEqual(2, first["schema_version"])
            self.assertNotIn("bootstrap", first)
            other_root = root / "another-repository"
            other_root.mkdir()
            cross_repo = prepare_module_bundle(str(self._package(other_root)), "entry", str(cache))
            self.assertEqual(first, cross_repo)
            self.assertEqual(cache.resolve(), Path(str(first["cache_root"])))

            source = emit_module_bootstrap(str(first["bundle_file"]))
            self.assertNotIn("invalidate_caches", source)
            namespace: dict[str, object] = {}
            exec(source, namespace)
            original_path = list(sys.path)
            original_bytecode = sys.dont_write_bytecode
            observations: list[int] = []
            namespace["run"](observations)  # type: ignore[index, operator]
            self.assertEqual([42], observations)
            self.assertEqual(original_path, sys.path)
            self.assertEqual(original_bytecode, sys.dont_write_bytecode)
            prefix = str(first["package_name"])
            self.assertFalse(any(name == prefix or name.startswith(prefix + ".") for name in sys.modules))
            self.assertFalse(any(Path(str(first["package_dir"])).rglob("__pycache__")))

    def test_bootstrap_cleans_up_when_entry_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            package = self._package(root)
            (package / "entry.py").write_text(
                "from .helper import answer\n\ndef run(context):\n    raise RuntimeError(str(answer()))\n",
                encoding="utf-8",
            )
            result = prepare_module_bundle(str(package), "entry", str(root / "cache"))
            namespace: dict[str, object] = {}
            exec(emit_module_bootstrap(str(result["bundle_file"])), namespace)
            original_path = list(sys.path)
            original_bytecode = sys.dont_write_bytecode
            with self.assertRaisesRegex(RuntimeError, "42"):
                namespace["run"](None)  # type: ignore[index, operator]
            self.assertEqual(original_path, sys.path)
            self.assertEqual(original_bytecode, sys.dont_write_bytecode)
            prefix = str(result["package_name"])
            self.assertFalse(any(name == prefix or name.startswith(prefix + ".") for name in sys.modules))

    def test_emitted_bootstrap_rejects_cache_tampering_before_import(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            result = prepare_module_bundle(str(self._package(root)), "entry", str(root / "cache"))
            source = emit_module_bootstrap(str(result["bundle_file"]))
            (Path(str(result["package_dir"])) / "helper.py").write_text(
                "def answer():\n    return 99\n", encoding="utf-8"
            )
            namespace: dict[str, object] = {}
            exec(source, namespace)
            with self.assertRaisesRegex(RuntimeError, "runtime verification"):
                namespace["run"]([])  # type: ignore[index, operator]

    def test_emitted_bootstrap_rejects_sibling_module_shadowing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            package = self._package(root)
            (package / "entry.py").write_text(
                "import shadow\n\ndef run(context):\n    context.append(shadow.answer())\n",
                encoding="utf-8",
            )
            result = prepare_module_bundle(str(package), "entry", str(root / "cache"))
            source = emit_module_bootstrap(str(result["bundle_file"]))
            (Path(str(result["bundle_dir"])) / "shadow.py").write_text(
                "def answer():\n    return 99\n", encoding="utf-8"
            )
            namespace: dict[str, object] = {}
            exec(source, namespace)
            with self.assertRaisesRegex(RuntimeError, "unexpected entries"):
                namespace["run"]([])  # type: ignore[index, operator]

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFOs unavailable")
    def test_emitted_bootstrap_rejects_special_files_without_opening_them(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            result = prepare_module_bundle(str(self._package(root)), "entry", str(root / "cache"))
            source = emit_module_bootstrap(str(result["bundle_file"]))
            os.mkfifo(Path(str(result["package_dir"])) / "blocked.py")
            namespace: dict[str, object] = {}
            exec(source, namespace)
            with self.assertRaisesRegex(RuntimeError, "unsupported file"):
                namespace["run"]([])  # type: ignore[index, operator]

    def test_changed_source_creates_new_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            package = self._package(root)
            cache = root / "cache"
            first = prepare_module_bundle(str(package), "entry", str(cache))
            (package / "helper.py").write_text("def answer():\n    return 43\n", encoding="utf-8")
            second = prepare_module_bundle(str(package), "entry", str(cache))
            self.assertNotEqual(first["bundle_sha256"], second["bundle_sha256"])
            self.assertTrue(Path(str(first["bundle_file"])).is_file())
            self.assertTrue(Path(str(second["bundle_file"])).is_file())

    def test_concurrent_identical_publication_uses_completed_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            package = self._package(root)
            cache = root / "cache"

            def publish_then_report_nonempty(source: Path, target: Path) -> None:
                shutil.copytree(source, target)
                raise OSError(errno.ENOTEMPTY, "directory not empty")

            with patch.object(Path, "rename", autospec=True, side_effect=publish_then_report_nonempty):
                result = prepare_module_bundle(str(package), "entry", str(cache))

            self.assertEqual(result, verify_module_bundle(str(result["bundle_file"])))

    def test_verification_rejects_tampered_module(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            result = prepare_module_bundle(str(self._package(root)), "entry", str(root / "cache"))
            path = Path(str(result["package_dir"])) / "helper.py"
            path.write_text("# tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "failed verification"):
                verify_module_bundle(str(result["bundle_file"]))

    def test_verification_rejects_unexpected_cached_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            result = prepare_module_bundle(str(self._package(root)), "entry", str(root / "cache"))
            extra = Path(str(result["bundle_dir"])) / "unexpected.txt"
            extra.write_text("unexpected", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unexpected entries"):
                verify_module_bundle(str(result["bundle_file"]))

    def test_verification_rejects_untracked_package_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            result = prepare_module_bundle(str(self._package(root)), "entry", str(root / "cache"))
            (Path(str(result["package_dir"])) / "entry").mkdir()
            with self.assertRaisesRegex(ValueError, "subdirectories must be Python packages"):
                verify_module_bundle(str(result["bundle_file"]))

    def test_rejects_unsupported_source_and_invalid_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            package = self._package(root)
            (package / "data.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "only .py"):
                prepare_module_bundle(str(package), "entry", str(root / "cache"))
            (package / "data.json").unlink()
            with self.assertRaisesRegex(ValueError, "does not exist"):
                prepare_module_bundle(str(package), "missing", str(root / "cache"))

            pycache = package / "__pycache__"
            pycache.mkdir()
            (pycache / "stale.py").write_text("", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "__pycache__"):
                prepare_module_bundle(str(package), "entry", str(root / "other-cache"))

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_rejects_symlinked_source_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            package = self._package(root)
            (package / "helper.py").unlink()
            os.symlink(package / "entry.py", package / "helper.py")
            with self.assertRaisesRegex(ValueError, "symlink"):
                prepare_module_bundle(str(package), "entry", str(root / "cache"))

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_rejects_symlinked_cache_root_and_bundle_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            package = self._package(root)
            real_cache = root / "real-cache"
            real_cache.mkdir(mode=0o700)
            cache_alias = root / "cache-alias"
            os.symlink(real_cache, cache_alias)
            with self.assertRaisesRegex(ValueError, "cache root path"):
                prepare_module_bundle(str(package), "entry", str(cache_alias))

            result = prepare_module_bundle(str(package), "entry", str(real_cache))
            bundle_alias = root / "bundle-alias"
            os.symlink(Path(str(result["bundle_dir"])), bundle_alias)
            with self.assertRaisesRegex(ValueError, "bundle path"):
                verify_module_bundle(str(bundle_alias / "bundle.json"))

    def test_environment_override_must_be_absolute(self) -> None:
        with patch.dict(os.environ, {"FUSION_MCP_MODULE_CACHE": "relative/cache"}, clear=False):
            with self.assertRaisesRegex(ValueError, "must be an absolute path"):
                default_cache_root()

    @unittest.skipIf(os.name == "nt", "POSIX mode check")
    def test_existing_public_cache_root_is_rejected_without_chmod(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            package = self._package(root)
            cache = root / "cache"
            cache.mkdir(mode=0o755)
            cache.chmod(0o755)
            with self.assertRaisesRegex(ValueError, "group or other"):
                prepare_module_bundle(str(package), "entry", str(cache))
            self.assertEqual(0o755, cache.stat().st_mode & 0o777)

    def test_cache_and_source_must_not_contain_each_other(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            package = self._package(root)
            nested_cache = package / "cache"
            nested_cache.mkdir(mode=0o700)
            (nested_cache / "would-break-scan.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must not contain each other"):
                prepare_module_bundle(str(package), "entry", str(nested_cache))
            self.assertTrue(nested_cache.exists())

    @unittest.skipIf(os.name == "nt", "POSIX mode check")
    def test_verification_rejects_public_cached_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            result = prepare_module_bundle(str(self._package(root)), "entry", str(root / "cache"))
            cached = Path(str(result["package_dir"])) / "helper.py"
            cached.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "files must be private"):
                verify_module_bundle(str(result["bundle_file"]))

    def test_cli_prepares_and_emits_verified_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            package = self._package(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    ["prepare-module-bundle", str(package), "entry", "--cache-root", str(root / "cache")]
                )
            self.assertEqual(0, code)
            result = json.loads(output.getvalue())
            metadata_before = Path(result["bundle_file"]).read_bytes()
            errors = io.StringIO()
            with redirect_stderr(errors):
                code = main(
                    [
                        "emit-module-bootstrap",
                        result["bundle_file"],
                        "-o",
                        result["bundle_file"],
                    ]
                )
            self.assertEqual(2, code)
            self.assertIn("outside the persistent module cache", errors.getvalue())
            self.assertEqual(metadata_before, Path(result["bundle_file"]).read_bytes())

            bootstrap = io.StringIO()
            with redirect_stdout(bootstrap):
                code = main(["emit-module-bootstrap", result["bundle_file"]])
            self.assertEqual(0, code)
            self.assertIn("def run(context):", bootstrap.getvalue())

            (Path(result["package_dir"]) / "helper.py").write_text(
                "# tampered\n", encoding="utf-8"
            )
            errors = io.StringIO()
            with redirect_stderr(errors):
                code = main(["emit-module-bootstrap", result["bundle_file"]])
            self.assertEqual(2, code)
            self.assertIn("failed verification", errors.getvalue())


class ModuleCachePlatformTests(unittest.TestCase):
    def test_module_cache_fails_closed_without_posix_permissions(self) -> None:
        with patch.object(module_cache.os, "name", "nt"):
            with self.assertRaisesRegex(ValueError, "require POSIX"):
                prepare_module_bundle("unused", "entry", "C:/unused")
