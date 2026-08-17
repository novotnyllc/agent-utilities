from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import secrets
import stat
import tempfile
from typing import Any, Callable

from .manifest import Manifest, load_manifest
from .scripts import (
    emit_inventory_script,
    emit_parameter_sync_script,
    emit_scaffold_script,
    emit_verification_script,
    manifest_sha256,
)


SESSION_FILE_NAME = "session.json"
_RUN_ID_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_HASH_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_SESSION_KEYS = frozenset(
    {"session_file", "script", "report_path", "run_id", "kind", "manifest_sha256"}
)
# The CLI keeps the short ``scaffold`` spelling, while Fusion reports have
# always used the established ``component-scaffold`` identity.
_CLI_KIND_ALIASES = {"scaffold": "component-scaffold"}
_EMITTERS: dict[str, tuple[str, Callable[[Manifest, str, str], str]]] = {
    "inventory": ("inventory.py", emit_inventory_script),
    "parameter-sync": ("parameter-sync.py", emit_parameter_sync_script),
    "component-scaffold": ("scaffold.py", emit_scaffold_script),
    "verification": ("verification.py", emit_verification_script),
}


def _require_report_file_platform() -> None:
    """Fail closed unless the report fallback has its required POSIX semantics."""

    required = (
        "chmod",
        "fchmod",
        "fstat",
        "getuid",
        "lstat",
        "open",
        "scandir",
        "unlink",
        "rmdir",
    )
    missing = [name for name in required if not callable(getattr(os, name, None))]
    if not hasattr(os, "O_NOFOLLOW"):
        missing.append("O_NOFOLLOW")
    if os.name != "posix" or missing:
        detail = f"os.name={os.name!r}"
        if missing:
            detail += "; missing " + ", ".join(missing)
        raise ValueError(
            "report-file fallback requires POSIX file semantics; "
            f"unavailable on this runtime ({detail}). Use stdout execution or stop."
        )


@dataclass(frozen=True, slots=True)
class ReportSession:
    session_file: Path
    script: Path
    report_path: Path
    run_id: str
    kind: str
    manifest_sha256: str

    @property
    def directory(self) -> Path:
        return self.session_file.parent


def _canonical_path(value: str, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty absolute path")
    if "\x00" in value:
        raise ValueError(f"{label} must not contain NUL characters")
    if not os.path.isabs(value):
        raise ValueError(f"{label} must be absolute")
    lexical = os.path.abspath(value)
    resolved = os.path.realpath(lexical)
    if value != lexical or lexical != resolved:
        raise ValueError(f"{label} must be a canonical path without aliases")
    return Path(resolved)


def _current_uid() -> int | None:
    getuid = getattr(os, "getuid", None)
    return int(getuid()) if getuid else None


def _check_owner(result: os.stat_result, label: str) -> None:
    uid = _current_uid()
    if uid is not None and result.st_uid != uid:
        raise ValueError(f"{label} is not owned by the current user")


def _lstat(path: Path, label: str, *, missing_ok: bool = False) -> os.stat_result | None:
    try:
        result = os.lstat(path)
    except FileNotFoundError:
        if missing_ok:
            return None
        raise ValueError(f"{label} is missing")
    if stat.S_ISLNK(result.st_mode):
        raise ValueError(f"{label} must not be a symlink")
    return result


def _require_directory(path: Path, label: str) -> os.stat_result:
    result = _lstat(path, label)
    assert result is not None
    _check_owner(result, label)
    if not stat.S_ISDIR(result.st_mode):
        raise ValueError(f"{label} must be a directory")
    if stat.S_IMODE(result.st_mode) != 0o700:
        raise ValueError(f"{label} must have mode 0700")
    return result


def _validate_regular_stat(
    result: os.stat_result,
    label: str,
    *,
    mode: int | None = None,
) -> os.stat_result:
    if stat.S_ISLNK(result.st_mode) or not stat.S_ISREG(result.st_mode):
        raise ValueError(f"{label} must be a regular file")
    _check_owner(result, label)
    if result.st_nlink != 1:
        raise ValueError(f"{label} must not be a hard-link alias")
    if mode is not None and stat.S_IMODE(result.st_mode) != mode:
        raise ValueError(f"{label} must have mode {mode:04o}")
    return result


def _require_regular(
    path: Path,
    label: str,
    *,
    mode: int | None = None,
    missing_ok: bool = False,
) -> os.stat_result | None:
    result = _lstat(path, label, missing_ok=missing_ok)
    if result is None:
        return None
    return _validate_regular_stat(result, label, mode=mode)


def _read_regular_json(path: Path, label: str, *, mode: int | None = None) -> dict[str, Any]:
    _require_regular(path, label, mode=mode)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ValueError(f"unable to read {label}: {error}") from error
    try:
        descriptor_stat = os.fstat(descriptor)
        _validate_regular_stat(descriptor_stat, label, mode=mode)
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            descriptor = -1
            text = stream.read()
    finally:
        if descriptor != -1:
            os.close(descriptor)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"{label} must contain one JSON object: {error.msg}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain one JSON object")
    return value


def _validate_directory_entries(session: ReportSession) -> None:
    expected = {session.session_file.name, session.script.name, session.report_path.name}
    try:
        entries = {entry.name for entry in os.scandir(session.directory)}
    except OSError as error:
        raise ValueError(f"unable to inspect report-session directory: {error}") from error
    unexpected = sorted(entries - expected)
    if unexpected:
        raise ValueError("report-session directory contains unexpected entries: " + ", ".join(unexpected))


def _require_child(session_directory: Path, value: str, label: str, expected_name: str) -> Path:
    path = _canonical_path(value, label)
    if path.parent != session_directory or path.name != expected_name:
        raise ValueError(f"{label} must be the exact generated child of the session directory")
    return path


def _session_from_metadata(session_file: Path, metadata: dict[str, Any]) -> ReportSession:
    if set(metadata) != _SESSION_KEYS:
        raise ValueError("session metadata fields are not exactly the expected set")
    values = {key: metadata[key] for key in _SESSION_KEYS}
    if any(not isinstance(value, str) or not value for value in values.values()):
        raise ValueError("session metadata fields must be non-empty strings")
    kind = metadata["kind"]
    if kind not in _EMITTERS:
        raise ValueError(f"unsupported report-session kind: {kind!r}")
    run_id = metadata["run_id"]
    if not _RUN_ID_RE.fullmatch(run_id):
        raise ValueError("session run ID must be exactly 64 lowercase hexadecimal characters")
    digest = metadata["manifest_sha256"]
    if not _HASH_RE.fullmatch(digest):
        raise ValueError("session manifest SHA-256 must be exactly 64 lowercase hexadecimal characters")

    session_directory = session_file.parent
    _require_directory(session_directory, "report-session directory")
    if metadata["session_file"] != str(session_file):
        raise ValueError("session_file does not name the supplied session metadata file")
    script_name, _ = _EMITTERS[kind]
    script = _require_child(session_directory, metadata["script"], "script", script_name)
    report = _require_child(session_directory, metadata["report_path"], "report_path", f"{kind}.json")
    session = ReportSession(session_file, script, report, run_id, kind, digest)
    _validate_directory_entries(session)
    return session


def _write_private_file(path: Path, content: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = -1
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor != -1:
            os.close(descriptor)


def _remove_fresh_file(path: Path) -> None:
    try:
        result = os.lstat(path)
    except FileNotFoundError:
        return
    if stat.S_ISLNK(result.st_mode) or not stat.S_ISREG(result.st_mode):
        return
    os.unlink(path)


def prepare_report_session(manifest_path: str, kind: str) -> dict[str, str]:
    _require_report_file_platform()
    canonical_kind = _CLI_KIND_ALIASES.get(kind, kind)
    if canonical_kind not in _EMITTERS:
        raise ValueError(f"unsupported report-session kind: {kind!r}")
    manifest = load_manifest(manifest_path)
    script_name, emitter = _EMITTERS[canonical_kind]
    run_id = secrets.token_hex(32)
    if not _RUN_ID_RE.fullmatch(run_id):
        raise RuntimeError("generated run ID did not meet the strict format")

    directory = Path(tempfile.mkdtemp(prefix="fusion-design-report-")).resolve(strict=True)
    os.chmod(directory, 0o700)
    session_file = directory / SESSION_FILE_NAME
    script = directory / script_name
    report = directory / f"{canonical_kind}.json"
    metadata = {
        "session_file": str(session_file),
        "script": str(script),
        "report_path": str(report),
        "run_id": run_id,
        "kind": canonical_kind,
        "manifest_sha256": manifest_sha256(manifest),
    }
    try:
        _write_private_file(script, emitter(manifest, str(report), run_id))
        _write_private_file(session_file, json.dumps(metadata, sort_keys=True, separators=(",", ":")) + "\n")
        _require_regular(session_file, "session metadata", mode=0o600)
        _require_regular(script, "generated Fusion script", mode=0o600)
        _require_directory(directory, "report-session directory")
    except Exception:
        _remove_fresh_file(session_file)
        _remove_fresh_file(script)
        _remove_fresh_file(report)
        try:
            os.rmdir(directory)
        except OSError:
            pass
        raise
    return metadata


def _load_session(session_path: str) -> ReportSession:
    _require_report_file_platform()
    session_file = _canonical_path(session_path, "session file")
    _require_regular(session_file, "session metadata", mode=0o600)
    metadata = _read_regular_json(session_file, "session metadata", mode=0o600)
    return _session_from_metadata(session_file, metadata)


def verify_report_session(session_path: str) -> dict[str, Any]:
    session = _load_session(session_path)
    _require_regular(session.script, "generated Fusion script", mode=0o600)
    _require_regular(session.report_path, "Fusion report")
    report = _read_regular_json(session.report_path, "Fusion report")
    expected = {
        "report_run_id": session.run_id,
        "kind": session.kind,
        "manifest_sha256": session.manifest_sha256,
    }
    mismatches = [key for key, value in expected.items() if report.get(key) != value]
    if mismatches:
        raise ValueError("Fusion report identity mismatch: " + ", ".join(mismatches))
    return report


def cleanup_report_session(session_path: str) -> dict[str, str]:
    _require_report_file_platform()
    session_file = _canonical_path(session_path, "session file")
    if _lstat(session_file, "session metadata", missing_ok=True) is None:
        return {"status": "already-absent", "session_file": str(session_file)}
    session = _load_session(session_path)
    _require_regular(session.script, "generated Fusion script", mode=0o600, missing_ok=True)
    _require_regular(session.report_path, "Fusion report", missing_ok=True)
    _require_regular(session.session_file, "session metadata", mode=0o600)

    # Validate every target before removing any of them.  The directory check
    # above prevents an accidental recursive cleanup if a caller edits a file.
    for path in (session.script, session.report_path, session.session_file):
        if os.path.lexists(path):
            os.unlink(path)
    try:
        os.rmdir(session.directory)
    except OSError as error:
        raise ValueError(f"report-session directory was not empty after cleanup: {error}") from error
    return {"status": "removed", "session_file": str(session_file)}
