"""Process-isolated, source-backed PrusaSlicer profile queries.

This module owns the only runtime boundary used for installed profile discovery.
It deliberately returns evidence-shaped dictionaries: query failures are useful
diagnostics, not exceptions that force a caller into an unlabelled fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
from typing import Any, Callable


AUTHORIZED_VERSION = "2.9.6"
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_OUTPUT_BYTES = 4 * 1024 * 1024

BUNDLE_EXECUTABLE = Path(
    "/Applications/Original Prusa Drivers/PrusaSlicer.app/Contents/MacOS/PrusaSlicer"
)
PATH_EXECUTABLE_NAMES = ("prusa-slicer", "PrusaSlicer")

_VERSION_RE = re.compile(r"\bPrusaSlicer(?:\s+|-)(\d+\.\d+\.\d+)(?![0-9A-Za-z.+-])")
_MISSING_CONFIG_RE = re.compile(
    r"configuration wasn['’]t found|missing.*(?:appconfig|configuration)|check your ['\"]?datadir",
    re.IGNORECASE,
)
_MISSING_PROFILE_RE = re.compile(
    r"printer profile .* wasn['’]t found|wasn['’]t found among installed printers|profile .* not found",
    re.IGNORECASE,
)


def resolve_executable(explicit: str | Path | None = None) -> Path | None:
    """Resolve an explicit binary, then the known macOS bundle, then ``PATH``."""
    if explicit is not None:
        candidate = Path(explicit).expanduser()
        return candidate if candidate.is_file() else None
    if BUNDLE_EXECUTABLE.is_file():
        return BUNDLE_EXECUTABLE
    for name in PATH_EXECUTABLE_NAMES:
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def sha256_file(path: str | Path) -> str:
    """Hash a file without loading it all into memory."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def profile_snapshot_files(datadir: str | Path) -> tuple[Path, ...]:
    """Return the relevant configuration files in deterministic relative order."""
    root = Path(datadir).expanduser()
    candidates: list[Path] = []
    selection = root / "PrusaSlicer.ini"
    if selection.is_file():
        candidates.append(selection)
    for directory_name in ("printer", "print", "filament", "vendor"):
        directory = root / directory_name
        if directory.is_dir():
            candidates.extend(path for path in directory.rglob("*.ini") if path.is_file())
    return tuple(sorted(set(candidates), key=lambda path: path.relative_to(root).as_posix()))


def profile_snapshot_sha256(datadir: str | Path) -> str:
    """Hash names and bytes of PrusaSlicer.ini plus relevant profile .ini files."""
    root = Path(datadir).expanduser()
    digest = hashlib.sha256()
    for path in profile_snapshot_files(root):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def runtime_fingerprint(executable: str | Path, datadir: str | Path) -> dict[str, Any]:
    """Bind the binary and the profile files that affect resolution/slicing."""
    try:
        executable_hash = sha256_file(executable)
    except OSError:
        executable_hash = None
    try:
        snapshot_hash = profile_snapshot_sha256(datadir)
    except OSError:
        snapshot_hash = None
    return {
        "executable": str(executable),
        "executable_sha256": executable_hash,
        "datadir": str(datadir),
        "profile_snapshot_sha256": snapshot_hash,
    }


def _safe_snapshot_sha256(datadir: str | Path) -> str | None:
    try:
        return profile_snapshot_sha256(datadir)
    except OSError:
        return None


def _bounded(value: Any, limit: int = MAX_OUTPUT_BYTES) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    text = str(value)
    if len(text) <= limit:
        return text
    return "..." + text[-limit + 3 :]


def _bounded_file(handle: Any, limit: int) -> tuple[str, bool]:
    size = handle.seek(0, 2)
    handle.seek(max(0, size - limit))
    return handle.read().decode("utf-8", errors="replace"), size > limit


def _signal_for_exit(exit_code: int | None) -> int | None:
    if exit_code is None:
        return None
    if exit_code < 0:
        return -exit_code
    return None


def _version_from_output(stdout: str, stderr: str) -> str | None:
    match = _VERSION_RE.search(stdout) or _VERSION_RE.search(stderr)
    return match.group(1) if match else None


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _present_variant(value: Any) -> bool:
    return value is not None and (not isinstance(value, str) or bool(value.strip()))


def _valid_payload(action: str, payload: Any, *, printer_profile: str | None = None) -> bool:
    if not isinstance(payload, dict):
        return False
    if action == "--query-printer-models":
        models = payload.get("printer_models")
        if not isinstance(models, list):
            return False
        for model in models:
            if not isinstance(model, dict) or not _nonempty_string(model.get("id")) or not _nonempty_string(model.get("name")):
                return False
            variants = model.get("variants")
            if not isinstance(variants, list):
                return False
            for variant in variants:
                if not isinstance(variant, dict) or not _present_variant(variant.get("name")):
                    return False
                for key in ("printer_profiles", "user_printer_profiles"):
                    profiles = variant.get(key, [])
                    if not isinstance(profiles, list):
                        return False
                    for profile in profiles:
                        if not isinstance(profile, dict) or not _nonempty_string(profile.get("name")):
                            return False
                        extruders = profile.get("extruders_cnt")
                        bed = profile.get("bed")
                        if (
                            isinstance(extruders, bool)
                            or not isinstance(extruders, int)
                            or extruders < 1
                            or not isinstance(bed, dict)
                        ):
                            return False
                        width = bed.get("width")
                        height = bed.get("height")
                        if (
                            isinstance(width, bool)
                            or not isinstance(width, (int, float))
                            or not math.isfinite(float(width))
                            or width <= 0
                            or isinstance(height, bool)
                            or not isinstance(height, (int, float))
                            or not math.isfinite(float(height))
                            or height <= 0
                        ):
                            return False
        return True
    if action == "--query-print-filament-profiles":
        if not _nonempty_string(payload.get("printer_profile")):
            return False
        if printer_profile is not None and payload.get("printer_profile") != printer_profile:
            return False
        profiles = payload.get("print_profiles")
        if not isinstance(profiles, list):
            return False
        for profile in profiles:
            if not isinstance(profile, dict) or not _nonempty_string(profile.get("name")):
                return False
            for key in ("filament_profiles", "user_filament_profiles"):
                values = profile.get(key, [])
                if not isinstance(values, list) or not all(_nonempty_string(value) for value in values):
                    return False
        return True
    return False


def _json_payload(text: str) -> Any | None:
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _fingerprint_drift(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    drift: dict[str, Any] = {}
    for key in ("executable", "executable_sha256", "datadir", "profile_snapshot_sha256"):
        if before.get(key) != after.get(key):
            drift[key] = {"before": before.get(key), "after": after.get(key)}
    return drift


@dataclass
class PrusaSlicerRuntime:
    """A small, reusable process boundary for PrusaSlicer 2.9.6 queries."""

    executable: Path | None
    datadir: Path
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    output_limit: int = MAX_OUTPUT_BYTES
    runner: Callable[..., Any] = subprocess.run
    _version_result: dict[str, Any] | None = field(default=None, init=False, repr=False)
    _authoritative_fingerprint: dict[str, Any] | None = field(default=None, init=False, repr=False)

    def __init__(
        self,
        executable: str | Path | None,
        datadir: str | Path,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        output_limit: int = MAX_OUTPUT_BYTES,
        runner: Callable[..., Any] = subprocess.run,
    ) -> None:
        root = Path(datadir).expanduser()
        if not root.is_absolute():
            raise ValueError(f"An explicit absolute PrusaSlicer datadir is required; got {datadir!r}.")
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        if output_limit < 128:
            raise ValueError("output_limit is too small to retain bounded diagnostics")
        self.executable = resolve_executable(executable)
        self.datadir = root
        self.timeout = float(timeout)
        self.output_limit = int(output_limit)
        self.runner = runner
        self._version_result = None
        self._authoritative_fingerprint = None

    def _run(self, command: list[str]) -> Any:
        kwargs = {
            "text": True,
            "timeout": self.timeout,
            "check": False,
            "shell": False,
        }
        if self.runner is not subprocess.run:
            completed = self.runner(command, capture_output=True, **kwargs)
            raw_stdout = getattr(completed, "stdout", "") or ""
            raw_stderr = getattr(completed, "stderr", "") or ""
            stdout = _bounded(raw_stdout, self.output_limit)
            stderr = _bounded(raw_stderr, self.output_limit)
            return SimpleNamespace(
                returncode=getattr(completed, "returncode", 0),
                stdout=stdout,
                stderr=stderr,
                stdout_truncated=len(raw_stdout) > self.output_limit,
                stderr_truncated=len(raw_stderr) > self.output_limit,
            )
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            try:
                completed = self.runner(
                    command,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    timeout=self.timeout,
                    check=False,
                    shell=False,
                )
            except subprocess.TimeoutExpired as error:
                stdout, stdout_truncated = _bounded_file(stdout_file, self.output_limit)
                stderr, stderr_truncated = _bounded_file(stderr_file, self.output_limit)
                raise subprocess.TimeoutExpired(
                    error.cmd,
                    error.timeout,
                    output=stdout,
                    stderr=stderr,
                ) from error
            stdout, stdout_truncated = _bounded_file(stdout_file, self.output_limit)
            stderr, stderr_truncated = _bounded_file(stderr_file, self.output_limit)
        return SimpleNamespace(
            returncode=completed.returncode,
            stdout=stdout,
            stderr=stderr,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
        )

    def _fingerprint(self) -> dict[str, Any]:
        if self.executable is None:
            return {
                "executable": None,
                "executable_sha256": None,
                "datadir": str(self.datadir),
                "profile_snapshot_sha256": _safe_snapshot_sha256(self.datadir),
            }
        return runtime_fingerprint(self.executable, self.datadir)

    def _base_result(self, *, fingerprint: dict[str, Any] | None = None) -> dict[str, Any]:
        evidence = fingerprint or self._fingerprint()
        return {
            "ok": False,
            "outcome": None,
            "supported": False,
            "version": None,
            "executable": evidence["executable"],
            "executable_sha256": evidence["executable_sha256"],
            "datadir": evidence["datadir"],
            "profile_snapshot_sha256": evidence["profile_snapshot_sha256"],
            "command": None,
            "exit_code": None,
            "signal": None,
            "stdout_tail": "",
            "stderr_tail": "",
        }

    def probe_version(self) -> dict[str, Any]:
        """Probe ``--help`` and accept only the source-validated version."""
        if self._version_result is not None:
            cached = dict(self._version_result)
            cached_after = cached.get("fingerprint_after")
            current = self._fingerprint()
            if isinstance(cached_after, dict) and not _fingerprint_drift(cached_after, current):
                return cached
            cached.update(
                {
                    "ok": False,
                    "supported": False,
                    "outcome": "snapshot_changed",
                    "reason": "Executable or profile datadir changed since the version probe.",
                    "fingerprint_after": current,
                    "drift": _fingerprint_drift(cached_after or {}, current),
                }
            )
            return cached
        before = self._fingerprint()
        result = self._base_result(fingerprint=before)
        result["fingerprint_before"] = dict(before)
        command = [str(self.executable), "--help"] if self.executable is not None else None
        result["command"] = command
        if self.executable is None:
            result.update(
                {
                    "outcome": "not_found",
                    "reason": "PrusaSlicer executable was not found.",
                    "fingerprint_after": dict(before),
                }
            )
            self._version_result = dict(result)
            return result
        try:
            completed = self._run(command)
        except subprocess.TimeoutExpired as error:
            after = self._fingerprint()
            drift = _fingerprint_drift(before, after)
            result.update(
                {
                    "outcome": "snapshot_changed" if drift else "timeout",
                    "reason": f"PrusaSlicer --help exceeded {self.timeout} seconds.",
                    "stdout_tail": _bounded(getattr(error, "stdout", None), self.output_limit),
                    "stderr_tail": _bounded(getattr(error, "stderr", None), self.output_limit),
                    "fingerprint_after": dict(after),
                }
            )
            if drift:
                result["reason"] = "Executable or profile datadir changed during the version probe."
                result["drift"] = drift
            self._version_result = dict(result)
            return result
        except OSError as error:
            after = self._fingerprint()
            drift = _fingerprint_drift(before, after)
            result.update(
                {
                    "outcome": "snapshot_changed" if drift else "not_found",
                    "reason": f"PrusaSlicer could not be executed: {error}",
                    "fingerprint_after": dict(after),
                }
            )
            if drift:
                result["reason"] = "Executable or profile datadir changed during the version probe."
                result["drift"] = drift
            self._version_result = dict(result)
            return result

        stdout = _bounded(getattr(completed, "stdout", None), self.output_limit)
        stderr = _bounded(getattr(completed, "stderr", None), self.output_limit)
        exit_code = int(getattr(completed, "returncode", 0))
        version = _version_from_output(stdout, stderr)
        result.update(
            {
                "version": version,
                "exit_code": exit_code,
                "signal": _signal_for_exit(exit_code),
                "stdout_tail": stdout,
                "stderr_tail": stderr,
            }
        )
        after = self._fingerprint()
        result["fingerprint_after"] = dict(after)
        drift = _fingerprint_drift(before, after)
        if drift:
            result.update(
                {
                    "outcome": "snapshot_changed",
                    "reason": "Executable or profile datadir changed during the version probe.",
                    "drift": drift,
                }
            )
        elif result["signal"] is not None:
            result.update({"outcome": "signal_crash", "reason": f"PrusaSlicer --help terminated by signal {result['signal']}."})
        elif exit_code != 0:
            result.update({"outcome": "nonzero_exit", "reason": f"PrusaSlicer --help exited {exit_code}."})
        elif version != AUTHORIZED_VERSION:
            result.update(
                {
                    "outcome": "unsupported_version",
                    "reason": f"Expected PrusaSlicer {AUTHORIZED_VERSION}; detected {version or 'no version banner' }.",
                }
            )
        else:
            result.update({"ok": True, "supported": True, "outcome": "success"})
        self._version_result = dict(result)
        return result

    def _query(
        self,
        action: str,
        *,
        printer_profile: str | None = None,
        require_supported_version: bool = False,
    ) -> dict[str, Any]:
        before = self._fingerprint()
        result = self._base_result(fingerprint=before)
        result["command_kind"] = action
        result["fingerprint_before"] = dict(before)
        result.update(
            {
                "executable_sha256": before.get("executable_sha256"),
            }
        )
        if require_supported_version and self._authoritative_fingerprint:
            session_drift = _fingerprint_drift(self._authoritative_fingerprint, before)
            if session_drift:
                result.update(
                    {
                        "outcome": "snapshot_changed",
                        "reason": "Executable or profile datadir changed between authoritative queries.",
                        "drift": session_drift,
                        "fingerprint_after": dict(before),
                    }
                )
                return result
        if self.executable is None:
            result.update({"outcome": "not_found", "reason": "PrusaSlicer executable was not found."})
            return result
        version_result = self._version_result
        if version_result is not None:
            result.update(
                {
                    "version": version_result.get("version"),
                    "supported": version_result.get("supported", False),
                }
            )
        if require_supported_version:
            version_result = self.probe_version()
            result.update(
                {
                    "version": version_result.get("version"),
                    "supported": version_result.get("supported", False),
                }
            )
        if version_result is not None:
            probe_drift = _fingerprint_drift(version_result.get("fingerprint_after", {}), before)
            if probe_drift:
                result.update(
                    {
                        "outcome": "snapshot_changed",
                        "reason": "Executable or profile datadir changed since the version probe.",
                        "drift": probe_drift,
                        "fingerprint_after": dict(before),
                    }
                )
                return result
        if version_result is not None and not version_result.get("ok"):
            result.update(
                {
                    "outcome": version_result.get("outcome"),
                    "reason": version_result.get("reason"),
                    "exit_code": version_result.get("exit_code"),
                    "signal": version_result.get("signal"),
                    "stdout_tail": version_result.get("stdout_tail", ""),
                    "stderr_tail": version_result.get("stderr_tail", ""),
                }
            )
            return result
        if action == "--query-print-filament-profiles":
            if not isinstance(printer_profile, str) or not printer_profile:
                result.update({"outcome": "profile_not_resolvable", "reason": "A printer profile identifier is required."})
                return result
            command = [str(self.executable), action, "--datadir", str(self.datadir), "--printer-profile", printer_profile]
        else:
            command = [str(self.executable), action, "--datadir", str(self.datadir)]
        result["command"] = command
        try:
            completed = self._run(command)
        except subprocess.TimeoutExpired as error:
            after = self._fingerprint()
            drift = _fingerprint_drift(before, after)
            result.update(
                {
                    "outcome": "snapshot_changed" if drift else "timeout",
                    "reason": f"{action} exceeded {self.timeout} seconds.",
                    "stdout_tail": _bounded(getattr(error, "stdout", None), self.output_limit),
                    "stderr_tail": _bounded(getattr(error, "stderr", None), self.output_limit),
                    "fingerprint_after": dict(after),
                }
            )
            if drift:
                result["reason"] = "Executable or profile datadir changed during the query."
                result["drift"] = drift
            return result
        except OSError as error:
            after = self._fingerprint()
            drift = _fingerprint_drift(before, after)
            result.update(
                {
                    "outcome": "snapshot_changed" if drift else "not_found",
                    "reason": f"PrusaSlicer could not be executed: {error}",
                    "fingerprint_after": dict(after),
                }
            )
            if drift:
                result["reason"] = "Executable or profile datadir changed during the query."
                result["drift"] = drift
            return result

        stdout = _bounded(getattr(completed, "stdout", None), self.output_limit)
        stderr = _bounded(getattr(completed, "stderr", None), self.output_limit)
        exit_code = int(getattr(completed, "returncode", 0))
        result.update(
            {
                "exit_code": exit_code,
                "signal": _signal_for_exit(exit_code),
                "stdout_tail": stdout,
                "stderr_tail": stderr,
            }
        )
        output_truncated = bool(getattr(completed, "stdout_truncated", False))
        payload = None if output_truncated else _json_payload(stdout)
        valid = payload is not None and _valid_payload(action, payload, printer_profile=printer_profile)
        result["payload"] = payload
        result["stderr_truncated"] = bool(getattr(completed, "stderr_truncated", False))
        combined = f"{stdout}\n{stderr}"
        after = self._fingerprint()
        result["fingerprint_after"] = dict(after)
        drift = _fingerprint_drift(before, after)
        if drift:
            result.update({"outcome": "snapshot_changed", "reason": "Executable or profile datadir changed during the query.", "drift": drift})
            return result
        if output_truncated:
            result.update(
                {
                    "outcome": "malformed_json",
                    "reason": f"PrusaSlicer query output exceeded the {self.output_limit}-byte limit.",
                }
            )
        elif result["signal"] is not None:
            result.update({"outcome": "signal_crash", "reason": f"PrusaSlicer query terminated by signal {result['signal']}."})
        elif _MISSING_CONFIG_RE.search(combined):
            result.update({"outcome": "missing_app_config", "reason": "PrusaSlicer could not load its application configuration."})
        elif _MISSING_PROFILE_RE.search(combined):
            result.update({"outcome": "profile_not_resolvable", "reason": "The requested printer profile is not installed."})
        elif valid and exit_code in (0, 1):
            result.update({"ok": True, "outcome": "success"})
        elif exit_code == 1:
            result.update({"outcome": "nonzero_exit", "reason": "PrusaSlicer returned exit code 1 without valid expected JSON."})
        elif exit_code != 0:
            result.update({"outcome": "nonzero_exit", "reason": f"PrusaSlicer exited {exit_code} without valid expected JSON."})
        else:
            result.update({"outcome": "malformed_json", "reason": "PrusaSlicer returned malformed or schema-invalid JSON."})
        if require_supported_version and result.get("ok"):
            self._authoritative_fingerprint = dict(after)
        return result

    def query_printer_models(self, *, require_supported_version: bool = False) -> dict[str, Any]:
        return self._query("--query-printer-models", require_supported_version=require_supported_version)

    def query_print_filament_profiles(
        self,
        printer_profile: str,
        *,
        require_supported_version: bool = False,
    ) -> dict[str, Any]:
        return self._query(
            "--query-print-filament-profiles",
            printer_profile=printer_profile,
            require_supported_version=require_supported_version,
        )

    def query_printer_models_authoritative(self) -> dict[str, Any]:
        return self.query_printer_models(require_supported_version=True)

    def query_print_filament_profiles_authoritative(self, printer_profile: str) -> dict[str, Any]:
        return self.query_print_filament_profiles(printer_profile, require_supported_version=True)
