from __future__ import annotations

import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile


SCHEMA_VERSION = 2
ENVIRONMENT_VARIABLE = "FUSION_MCP_MODULE_CACHE"


def _require_private_cache_platform() -> None:
    if os.name != "posix" or not callable(getattr(os, "getuid", None)):
        raise ValueError(
            "Fusion MCP module bundles require POSIX owner and permission semantics; "
            "this platform is unsupported"
        )


def default_cache_root() -> Path:
    _require_private_cache_platform()
    override = os.environ.get(ENVIRONMENT_VARIABLE)
    if override:
        path = Path(override).expanduser()
        if not path.is_absolute():
            raise ValueError(f"{ENVIRONMENT_VARIABLE} must be an absolute path")
        return path
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "fusion-parametric-design" / "mcp-modules"
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".cache"
    if not base.is_absolute():
        raise ValueError("XDG_CACHE_HOME must be an absolute path")
    return base / "fusion-parametric-design" / "mcp-modules"


def _cache_root(explicit: str | None) -> Path:
    path = Path(explicit).expanduser() if explicit else default_cache_root()
    if not path.is_absolute():
        raise ValueError("cache root must be an absolute path")
    return Path(os.path.abspath(path))


def _is_link(path: Path) -> bool:
    return path.is_symlink()


def _assert_no_link_components(path: Path, label: str) -> None:
    for component in (path, *path.parents):
        if os.path.lexists(component) and _is_link(component):
            raise ValueError(f"{label} path must not traverse a symlink or junction: {component}")


def _assert_directory(path: Path, label: str) -> os.stat_result:
    if _is_link(path):
        raise ValueError(f"{label} must not be a symlink or junction: {path}")
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError(f"{label} must be a directory: {path}")
    if info.st_uid != os.getuid():
        raise ValueError(f"{label} must be owned by the current user: {path}")
    return info


def _assert_file(path: Path, label: str) -> os.stat_result:
    if _is_link(path):
        raise ValueError(f"{label} must not be a symlink or junction: {path}")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError(f"{label} must be a regular, unlinked file: {path}")
    if info.st_uid != os.getuid():
        raise ValueError(f"{label} must be owned by the current user: {path}")
    return info


def _source_files(source: Path) -> dict[str, bytes]:
    _assert_directory(source, "source package")
    if not (source / "__init__.py").is_file():
        raise ValueError("source package must contain __init__.py")
    files: dict[str, bytes] = {}
    for directory, names, filenames in os.walk(source, followlinks=False):
        current = Path(directory)
        _assert_directory(current, "source directory")
        for name in names:
            if name == "__pycache__":
                raise ValueError("module bundles must not contain __pycache__ directories")
            child = current / name
            _assert_directory(child, "source directory")
            if not (child / "__init__.py").is_file():
                raise ValueError(f"module bundle subdirectories must be Python packages: {child}")
        for name in filenames:
            path = current / name
            if path.suffix != ".py":
                raise ValueError(f"module bundles support only .py files: {path}")
            _assert_file(path, "source module")
            relative = path.relative_to(source).as_posix()
            files[relative] = path.read_bytes()
    return dict(sorted(files.items()))


def _file_hashes(files: dict[str, bytes]) -> dict[str, str]:
    return {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}


def _digest(entry_module: str, hashes: dict[str, str]) -> str:
    payload = json.dumps(
        {"schema_version": SCHEMA_VERSION, "entry_module": entry_module, "files": hashes},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_entry(entry_module: str, files: dict[str, object]) -> None:
    parts = entry_module.split(".")
    if not parts or any(not part.isidentifier() for part in parts):
        raise ValueError("entry module must be a dotted Python identifier")
    module = "/".join(parts)
    if f"{module}.py" not in files and f"{module}/__init__.py" not in files:
        raise ValueError(f"entry module does not exist in source package: {entry_module}")


def _bootstrap(
    bundle_dir: Path,
    package_name: str,
    entry_module: str,
    hashes: dict[str, str],
) -> str:
    qualified = f"{package_name}.{entry_module}"
    return f'''# Generated by fusion-design; pass this source to Fusion's Python execution capability.
import hashlib
import importlib
import os
import stat
import sys


def _verify_package(bundle_dir, package_name, expected_hashes):
    if set(os.listdir(bundle_dir)) != {{"bundle.json", package_name}}:
        raise RuntimeError("cached module bundle contains unexpected entries")
    package_dir = os.path.join(bundle_dir, package_name)
    actual_hashes = {{}}
    for directory, names, filenames in os.walk(package_dir, followlinks=False):
        if "__pycache__" in names:
            raise RuntimeError("cached module package contains __pycache__")
        for name in names:
            path = os.path.join(directory, name)
            if os.path.islink(path) or not os.path.isdir(path):
                raise RuntimeError("cached module package contains an unsupported directory")
            if not os.path.isfile(os.path.join(path, "__init__.py")):
                raise RuntimeError("cached module subdirectories must be Python packages")
        for name in filenames:
            path = os.path.join(directory, name)
            info = os.lstat(path)
            if (
                not name.endswith(".py")
                or not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
            ):
                raise RuntimeError("cached module package contains an unsupported file")
            relative = os.path.relpath(path, package_dir).replace(os.sep, "/")
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            try:
                opened = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or opened.st_nlink != 1
                    or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)
                ):
                    raise RuntimeError("cached module changed during runtime verification")
                with os.fdopen(descriptor, "rb") as stream:
                    descriptor = -1
                    actual_hashes[relative] = hashlib.sha256(stream.read()).hexdigest()
            finally:
                if descriptor != -1:
                    os.close(descriptor)
    if actual_hashes != expected_hashes:
        raise RuntimeError("cached module package failed runtime verification")


def run(context):
    bundle_dir = {str(bundle_dir)!r}
    package_name = {package_name!r}
    expected_hashes = {dict(sorted(hashes.items()))!r}
    old_path = list(sys.path)
    old_dont_write_bytecode = sys.dont_write_bytecode
    try:
        for name in list(sys.modules):
            if name == package_name or name.startswith(package_name + "."):
                del sys.modules[name]
        sys.dont_write_bytecode = True
        sys.path.insert(0, bundle_dir)
        _verify_package(bundle_dir, package_name, expected_hashes)
        module = importlib.import_module({qualified!r})
        entry = getattr(module, "run", None)
        if not callable(entry):
            raise RuntimeError({qualified!r} + " must define callable run(context)")
        return entry(context)
    finally:
        sys.path[:] = old_path
        sys.dont_write_bytecode = old_dont_write_bytecode
        for name in list(sys.modules):
            if name == package_name or name.startswith(package_name + "."):
                del sys.modules[name]
'''


def _metadata(digest: str, package_name: str, entry_module: str, hashes: dict[str, str]) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "bundle_sha256": digest,
        "package_name": package_name,
        "entry_module": entry_module,
        "files": hashes,
    }


def _result(bundle_file: Path, metadata: dict[str, object]) -> dict[str, object]:
    bundle_dir = bundle_file.parent
    package_name = str(metadata["package_name"])
    return {
        **metadata,
        "cache_root": str(bundle_dir.parent),
        "bundle_dir": str(bundle_dir),
        "bundle_file": str(bundle_file),
        "package_dir": str(bundle_dir / package_name),
    }


def prepare_module_bundle(source_package: str, entry_module: str, cache_root: str | None = None) -> dict[str, object]:
    _require_private_cache_platform()
    source = Path(source_package).expanduser()
    if not source.is_absolute():
        source = Path.cwd() / source
    source_root = source.resolve(strict=True)
    root = _cache_root(cache_root)
    _assert_no_link_components(root, "cache root")
    if root == source_root or source_root in root.parents or root in source_root.parents:
        raise ValueError("cache root and source package must not contain each other")
    files = _source_files(source)
    _validate_entry(entry_module, files)
    hashes = _file_hashes(files)
    digest = _digest(entry_module, hashes)
    package_name = f"fusion_mcp_{digest}"
    metadata = _metadata(digest, package_name, entry_module, hashes)

    existed = root.exists()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root_info = _assert_directory(root, "cache root")
    if not existed:
        root.chmod(0o700)
    elif stat.S_IMODE(root_info.st_mode) & 0o077:
        raise ValueError("existing cache root must not be accessible by group or other users")
    target = root / digest
    bundle_file = target / "bundle.json"
    if target.exists():
        verified = verify_module_bundle(str(bundle_file))
        if {key: verified[key] for key in metadata} != metadata:
            raise ValueError(f"existing cache bundle does not match requested content: {target}")
        return verified

    staging = Path(tempfile.mkdtemp(prefix=f".{digest}.", dir=root))
    try:
        package = staging / package_name
        package.mkdir(mode=0o700)
        for relative, content in files.items():
            output = package / relative
            output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            output.write_bytes(content)
            output.chmod(0o600)
        bundle = staging / "bundle.json"
        bundle.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        for directory, _, _ in os.walk(staging):
            Path(directory).chmod(0o700)
        bundle.chmod(0o600)
        try:
            staging.rename(target)
        except OSError as error:
            if error.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return verify_module_bundle(str(bundle_file))


def verify_module_bundle(bundle_path: str) -> dict[str, object]:
    _require_private_cache_platform()
    bundle_file = Path(bundle_path).expanduser()
    if not bundle_file.is_absolute():
        bundle_file = Path.cwd() / bundle_file
    if _is_link(bundle_file):
        raise ValueError(f"bundle metadata must not be a symlink or junction: {bundle_file}")
    bundle_file = Path(os.path.abspath(bundle_file))
    _assert_no_link_components(bundle_file, "bundle")
    _assert_file(bundle_file, "bundle metadata")
    bundle_dir = bundle_file.parent
    cache_info = _assert_directory(bundle_dir.parent, "cache root")
    bundle_info = _assert_directory(bundle_dir, "bundle directory")
    if stat.S_IMODE(cache_info.st_mode) & 0o077 or stat.S_IMODE(bundle_info.st_mode) & 0o077:
        raise ValueError("cache root and bundle directory must be private")
    if stat.S_IMODE(bundle_file.stat().st_mode) & 0o077:
        raise ValueError("bundle metadata must be private")
    metadata = json.loads(bundle_file.read_text(encoding="utf-8"))
    expected_keys = {"schema_version", "bundle_sha256", "package_name", "entry_module", "files"}
    if not isinstance(metadata, dict) or set(metadata) != expected_keys:
        raise ValueError("bundle metadata has an invalid shape")
    if metadata["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported module bundle schema version")
    digest = metadata["bundle_sha256"]
    package_name = metadata["package_name"]
    entry_module = metadata["entry_module"]
    hashes = metadata["files"]
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("invalid bundle digest")
    if bundle_dir.name != digest or package_name != f"fusion_mcp_{digest}":
        raise ValueError("bundle path or package name does not match its digest")
    if not isinstance(entry_module, str) or not isinstance(hashes, dict):
        raise ValueError("bundle entry module or file inventory is invalid")
    if any(not isinstance(name, str) or not isinstance(value, str) for name, value in hashes.items()):
        raise ValueError("bundle file inventory is invalid")
    _validate_entry(entry_module, hashes)
    if _digest(entry_module, hashes) != digest:
        raise ValueError("bundle metadata digest mismatch")

    package = bundle_dir / package_name
    actual_files = _source_files(package)
    for directory, _, filenames in os.walk(package):
        if stat.S_IMODE(Path(directory).stat().st_mode) & 0o077:
            raise ValueError("cached package directories must be private")
        for name in filenames:
            if stat.S_IMODE((Path(directory) / name).stat().st_mode) & 0o077:
                raise ValueError("cached package files must be private")
    if _file_hashes(actual_files) != hashes:
        raise ValueError("cached module content failed verification")
    expected_entries = {"bundle.json", package_name}
    if {path.name for path in bundle_dir.iterdir()} != expected_entries:
        raise ValueError("bundle directory contains unexpected entries")
    return _result(bundle_file, metadata)


def emit_module_bootstrap(bundle_path: str, output_path: str | None = None) -> str:
    verified = verify_module_bundle(bundle_path)
    if output_path:
        output = Path(os.path.abspath(Path(output_path).expanduser()))
        _assert_no_link_components(output, "bootstrap output")
        cache_root = Path(str(verified["cache_root"]))
        if output == cache_root or cache_root in output.parents:
            raise ValueError("bootstrap output must be outside the persistent module cache")
    return _bootstrap(
        Path(str(verified["bundle_dir"])),
        str(verified["package_name"]),
        str(verified["entry_module"]),
        dict(verified["files"]),
    )
