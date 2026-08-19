"""Bounded variant-matrix runner.

The runner orchestrates from the host: one Fusion transaction per step, each
emitted by the *existing* inventory, parameter-sync, verification and export
helpers so there is never a second implementation to drift from the first.  The
whole state machine — including every failure and restoration path — runs
offline through an injected step executor.

Three invariants the tests exist to defend:

* Restoration is verified, not attempted.  The initial parameter expressions
  (and active configuration) are captured before the first variant and read back
  afterwards on every exit path; a mismatch is a loud failure.
* Evidence is additive.  A variant's row is recorded as soon as it starts, so a
  later failure can never erase what an earlier variant earned.
* The verdict is conjunctive.  A run passes only when every declared variant
  passed and the document was verifiably restored.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any, Callable

from .export_handoff import ExportConfig, emit_export_script, verification_binding_from_report
from .manifest import Manifest
from .printable_parts import _in_closed_set
from .scripts import (
    emit_inventory_script,
    emit_parameter_sync_script,
    emit_verification_script,
    manifest_sha256,
)
from .variants import variant_configuration, variant_id, variant_parameter_overrides


FAILURE_POLICIES = {"stop", "continue"}

# One live Fusion transaction is minutes, not hours; a step that outruns this
# budget is a hung session, not a slow one.
DEFAULT_TIMEOUT_SECONDS = 900.0

CAPTURE_STATE_STEP = "capture-initial-state"
CAPTURE_CONFIGURATION_STEP = "capture-initial-configuration"
RESTORE_PARAMETERS_STEP = "restore-parameters"
RESTORE_CONFIGURATION_STEP = "restore-configuration"
VERIFY_RESTORE_STEP = "verify-restore"
VARIANT_STEPS = ("apply", "inventory", "verify", "export")


class StepReportUnavailable(Exception):
    """The executor has no report for this step yet; the run halts, incomplete.

    Distinct from a failure: nothing is known to be wrong, the evidence simply
    has not been produced. The runner reports the step as the next one to run.
    """


@dataclass(frozen=True, slots=True)
class MatrixConfig:
    export_dir: str | None = None
    formats: tuple[str, ...] = ("step", "3mf")
    on_failure: str = "stop"
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not _in_closed_set(self.on_failure, FAILURE_POLICIES):
            raise ValueError(f"on_failure must be one of {', '.join(sorted(FAILURE_POLICIES))}.")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(float(self.timeout_seconds))
            or float(self.timeout_seconds) <= 0
        ):
            raise ValueError("timeout_seconds must be a positive, finite number of seconds.")
        if self.export_dir is not None and not str(self.export_dir).strip():
            raise ValueError("export_dir must be a non-empty Fusion-host path when export is requested.")


@dataclass(frozen=True, slots=True)
class MatrixStep:
    """One Fusion transaction plus the evidence it must produce."""

    step_id: str
    variant_id: str
    report_kind: str
    report_name: str
    timeout_seconds: float
    manifest_sha256: str | None = None
    script: str | None = None
    deferred_reason: str | None = None

    def to_dict(self, *, include_script: bool = True) -> dict[str, Any]:
        row: dict[str, Any] = {
            "step_id": self.step_id,
            "variant_id": self.variant_id,
            "report_kind": self.report_kind,
            "report_name": self.report_name,
            "timeout_seconds": self.timeout_seconds,
            "manifest_sha256": self.manifest_sha256,
        }
        if self.deferred_reason:
            row["deferred_reason"] = self.deferred_reason
        if include_script:
            row["script"] = self.script
        return row


def variant_manifest(manifest: Manifest, raw_variant: Any) -> Manifest:
    """The base manifest with this variant's parameter overrides substituted.

    Substituting into the manifest is what lets every existing emitter be reused
    unchanged: the variant's hash, parameter-sync, verification and export all
    fall out of the same code the single-configuration path uses, and the hash
    binds each variant's evidence to its own declared state.
    """
    overrides = variant_parameter_overrides(raw_variant)
    data = manifest.to_dict()
    if not overrides:
        return Manifest.from_data(data)
    remaining = dict(overrides)
    for parameter in data.get("parameters", []):
        if not isinstance(parameter, dict):
            continue
        # Stripped exactly as variants.py strips, so an override never misses
        # the parameter it names.
        name = str(parameter.get("name", "")).strip()
        if name in remaining:
            parameter["expression"] = remaining.pop(name)
    if remaining:
        raise ValueError(
            f"Variant {variant_id(raw_variant)!r} overrides parameters the manifest does not declare: "
            f"{', '.join(sorted(remaining))}."
        )
    return Manifest.from_data(data)


def restore_manifest(manifest: Manifest, snapshot: dict[str, str]) -> Manifest:
    """The base manifest with the captured initial expressions substituted."""
    data = manifest.to_dict()
    remaining = dict(snapshot)
    for parameter in data.get("parameters", []):
        if not isinstance(parameter, dict):
            continue
        name = str(parameter.get("name", "")).strip()
        if name in remaining:
            parameter["expression"] = remaining.pop(name)
    if remaining:
        raise ValueError(
            f"Cannot restore parameters the manifest does not declare: {', '.join(sorted(remaining))}."
        )
    return Manifest.from_data(data)


def emit_configuration_script(manifest: Manifest, configuration_name: str | None) -> str:
    """Probe Fusion's configuration API and, when named, activate one row.

    Configuration activation depends on an API that may be absent in the
    connected Fusion release.  This fails closed with a clear message rather than
    silently applying nothing and calling the base design a variant.  Passing
    ``None`` captures the currently active row without changing anything.
    """
    from .scripts import _json_literal, _script_prelude

    return _script_prelude(manifest) + f'''REQUESTED_CONFIGURATION = json.loads({_json_literal(configuration_name)})


def _configuration_table(design):
    table = getattr(design, "configurationTable", None)
    if not table:
        raise RuntimeError(
            "This Fusion release exposes no Design.configurationTable, so a named configuration cannot be "
            "read or activated. Refusing to continue: applying nothing silently would record the base design "
            "as a variant. Declare this family as parameter-set variants instead."
        )
    rows = getattr(table, "rows", None)
    if rows is None:
        raise RuntimeError(
            "Design.configurationTable exposes no rows collection in this Fusion release; the configuration "
            "adapter does not match the connected API."
        )
    return table, rows


def _active_configuration_name(table):
    active = getattr(table, "activeRow", None)
    return getattr(active, "name", None) if active else None


def run(context):
    report_attempted = False
    try:
        app, design = _active_design()
        target_document = _require_target_document(app)
        table, rows = _configuration_table(design)
        available = []
        row_by_name = {{}}
        for index in range(rows.count):
            row = rows.item(index)
            available.append(row.name)
            row_by_name.setdefault(row.name, row)

        compute_invoked = None
        activate_returned = None
        if REQUESTED_CONFIGURATION is not None:
            row = row_by_name.get(REQUESTED_CONFIGURATION)
            if not row:
                raise RuntimeError(
                    "Fusion configuration " + repr(REQUESTED_CONFIGURATION) + " is not in this document; "
                    "available rows are " + repr(sorted(available)) + "."
                )
            if not hasattr(row, "activate"):
                raise RuntimeError(
                    "This Fusion release's configuration rows expose no activate(); the configuration adapter "
                    "does not match the connected API."
                )
            activate_returned = row.activate()
            _pump_events(app, design, target_document)
            compute_invoked = design.computeAll()
            _pump_events(app, design, target_document)

        # The active row is read back after the pump: an activation that did not
        # take must not be reported as one that did.
        active = _active_configuration_name(table)
        timeline = _timeline_health(design)
        failures = []
        if not active:
            failures.append("no-active-configuration")
        if timeline["unhealthy"]:
            failures.append("timeline-health")
        if REQUESTED_CONFIGURATION is not None:
            if not compute_invoked:
                failures.append("compute-all")
            if active != REQUESTED_CONFIGURATION:
                failures.append("configuration-not-active")

        report = {{
            "kind": "configuration-activation",
            "project": PROJECT_NAME,
            "manifest_sha256": MANIFEST_SHA256,
            "requested_configuration": REQUESTED_CONFIGURATION,
            "active_configuration": active,
            "available_configurations": sorted(available),
            "activate_returned": activate_returned,
            "compute_invoked": compute_invoked,
            "timeline": timeline,
            "ok": not failures,
            "failures": failures,
        }}
        report_attempted = True
        _emit(report)
        if failures:
            raise RuntimeError("Fusion configuration step failed: " + ", ".join(failures))
    except Exception as error:
        if not report_attempted:
            report_attempted = True
            _emit({{
                "kind": "configuration-activation",
                "ok": False,
                "error": str(error),
                "traceback": traceback.format_exc(),
            }})
        raise
'''


def _variant_step(
    identity: str,
    digest: str,
    timeout: float,
    step_id: str,
    report_kind: str,
    script: str | None,
    deferred_reason: str | None = None,
) -> MatrixStep:
    return MatrixStep(
        step_id=step_id,
        variant_id=identity,
        report_kind=report_kind,
        report_name=f"{identity}__{step_id}__{digest[:8]}.json",
        timeout_seconds=timeout,
        manifest_sha256=digest,
        script=script,
        deferred_reason=deferred_reason,
    )


def _variant_export_dir(export_dir: str, identity: str) -> str:
    """Per-variant export directory: no two variants can share an artifact path."""
    return f"{str(export_dir).rstrip('/')}/{identity}"


def build_matrix_plan(manifest: Manifest, config: MatrixConfig) -> tuple[MatrixStep, ...]:
    """The ordered step plan: capture, then each variant, then verified restore."""
    variants = manifest.variants
    if not variants:
        raise ValueError(
            "Manifest declares no variants; add a 'variants' section before planning a matrix run."
        )
    base_digest = manifest_sha256(manifest)
    short = base_digest[:8]
    timeout = float(config.timeout_seconds)
    has_parameter_variant = any(variant_parameter_overrides(variant) for variant in variants)
    has_configuration_variant = any(
        not variant_parameter_overrides(variant) and variant_configuration(variant) for variant in variants
    )

    steps: list[MatrixStep] = [
        MatrixStep(
            step_id=CAPTURE_STATE_STEP,
            variant_id="",
            report_kind="inventory",
            report_name=f"{CAPTURE_STATE_STEP}__{short}.json",
            timeout_seconds=timeout,
            manifest_sha256=base_digest,
            script=emit_inventory_script(manifest),
        )
    ]
    if has_configuration_variant:
        steps.append(
            MatrixStep(
                step_id=CAPTURE_CONFIGURATION_STEP,
                variant_id="",
                report_kind="configuration-activation",
                report_name=f"{CAPTURE_CONFIGURATION_STEP}__{short}.json",
                timeout_seconds=timeout,
                manifest_sha256=base_digest,
                script=emit_configuration_script(manifest, None),
            )
        )

    for raw_variant in variants:
        identity = variant_id(raw_variant)
        overrides = variant_parameter_overrides(raw_variant)
        derived = variant_manifest(manifest, raw_variant)
        digest = manifest_sha256(derived)

        if overrides:
            apply_kind, apply_script = "parameter-sync", emit_parameter_sync_script(derived)
        else:
            apply_kind = "configuration-activation"
            apply_script = emit_configuration_script(derived, variant_configuration(raw_variant))
        steps.append(_variant_step(identity, digest, timeout, "apply", apply_kind, apply_script))
        steps.append(
            _variant_step(identity, digest, timeout, "inventory", "inventory", emit_inventory_script(derived))
        )
        steps.append(
            _variant_step(identity, digest, timeout, "verify", "verification", emit_verification_script(derived))
        )
        if config.export_dir:
            steps.append(
                _variant_step(
                    identity,
                    digest,
                    timeout,
                    "export",
                    "export-handoff",
                    None,
                    "Emitted once this variant's verification report is captured; the export is bound to that report's hash.",
                )
            )

    if has_parameter_variant:
        steps.append(
            MatrixStep(
                step_id=RESTORE_PARAMETERS_STEP,
                variant_id="",
                report_kind="parameter-sync",
                report_name=f"{RESTORE_PARAMETERS_STEP}__{short}.json",
                timeout_seconds=timeout,
                deferred_reason="Emitted from the captured initial parameter expressions, which are read at run time.",
            )
        )
    if has_configuration_variant:
        steps.append(
            MatrixStep(
                step_id=RESTORE_CONFIGURATION_STEP,
                variant_id="",
                report_kind="configuration-activation",
                report_name=f"{RESTORE_CONFIGURATION_STEP}__{short}.json",
                timeout_seconds=timeout,
                manifest_sha256=base_digest,
                deferred_reason="Emitted from the captured initially active configuration, which is read at run time.",
            )
        )
    steps.append(
        MatrixStep(
            step_id=VERIFY_RESTORE_STEP,
            variant_id="",
            report_kind="inventory",
            report_name=f"{VERIFY_RESTORE_STEP}__{short}.json",
            timeout_seconds=timeout,
            manifest_sha256=base_digest,
            script=emit_inventory_script(manifest),
        )
    )

    owners: dict[str, str] = {}
    for step in steps:
        if step.report_name in owners:
            raise ValueError(
                f"Variant report identities collide: {step.step_id!r} and {owners[step.report_name]!r} "
                f"both produce {step.report_name!r}; rename one variant id."
            )
        owners[step.report_name] = step.step_id
    return tuple(steps)


def _canonical_report_bytes(report: Any) -> bytes:
    return (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _coerce_executor_result(value: Any) -> tuple[Any, bytes | None]:
    if isinstance(value, tuple):
        if len(value) != 2 or not isinstance(value[1], (bytes, bytearray)):
            raise TypeError("A step executor tuple must be (report, raw_report_bytes).")
        return value[0], bytes(value[1])
    return value, None


def _verification_summary(report: dict[str, Any]) -> dict[str, Any]:
    timeline = report.get("timeline")
    unhealthy = timeline.get("unhealthy") if isinstance(timeline, dict) else None
    unsupported: list[dict[str, Any]] = []
    for key in ("clearance_results", "interference_results"):
        for result in report.get(key) or []:
            # A check carrying an error was not evaluated at all (mesh-only or
            # missing geometry); that is a different fact from a measured miss.
            if isinstance(result, dict) and result.get("error"):
                unsupported.append({"id": result.get("id"), "check": key, "error": result["error"]})
    return {
        "compute_invoked": bool(report.get("compute_invoked")),
        "timeline_unhealthy_count": len(unhealthy) if isinstance(unhealthy, list) else None,
        "verification_failures": list(report.get("failures") or []),
        "unsupported_checks": unsupported,
    }


def _export_summary(report: dict[str, Any]) -> dict[str, Any]:
    artifacts = []
    for artifact in report.get("artifacts") or []:
        if isinstance(artifact, dict):
            artifacts.append(
                {
                    "part_path": artifact.get("part_path"),
                    "filename": artifact.get("filename"),
                    "sha256": artifact.get("sha256"),
                    "byte_size": artifact.get("byte_size"),
                }
            )
    return {
        "export_dir": report.get("export_dir"),
        "verification_report_sha256": report.get("verification_report_sha256"),
        "artifacts": artifacts,
    }


class _MatrixRun:
    def __init__(
        self,
        manifest: Manifest,
        config: MatrixConfig,
        executor: Callable[[MatrixStep], Any],
        clock: Callable[[], float],
    ) -> None:
        self.manifest = manifest
        self.config = config
        self.executor = executor
        self.clock = clock
        self.plan = build_matrix_plan(manifest, config)
        self.snapshot: dict[str, str] = {}
        self.initial_configuration: str | None = None
        self.mutated = False
        self.halted_at: MatrixStep | None = None
        self.record: dict[str, Any] = {
            "kind": "variant-matrix",
            "project": manifest.project_name,
            "manifest_sha256": manifest_sha256(manifest),
            "on_failure": config.on_failure,
            "timeout_seconds": float(config.timeout_seconds),
            "export_requested": bool(config.export_dir),
            "plan": [step.to_dict(include_script=False) for step in self.plan],
            "initial_state": {"captured": False},
            "variants": [],
            "restore": {"required": False, "attempted": False, "ok": True, "verified": False, "steps": []},
            "failures": [],
            "complete": False,
            "ok": False,
        }

    # -- step execution -------------------------------------------------

    def _step(self, step_id: str, variant: str = "") -> MatrixStep:
        for step in self.plan:
            if step.step_id == step_id and step.variant_id == variant:
                return step
        raise KeyError(f"No planned step {step_id!r} for variant {variant!r}.")

    def _execute(self, step: MatrixStep) -> tuple[bool, Any, bytes | None, dict[str, Any]]:
        """Run one step. Raises StepReportUnavailable to halt the run cleanly."""
        result: dict[str, Any] = {
            "step_id": step.step_id,
            "variant_id": step.variant_id,
            "report_name": step.report_name,
            "report_kind": step.report_kind,
            "manifest_sha256": step.manifest_sha256,
            "ok": False,
        }
        started = self.clock()
        try:
            report, raw = _coerce_executor_result(self.executor(step))
        except StepReportUnavailable:
            # Not a failure: nothing is known to be wrong, the evidence simply
            # is not there yet. Remember the step so the record can name it.
            self.halted_at = step
            raise
        except Exception as error:  # noqa: BLE001 - any executor failure is this step's failure
            result["elapsed_seconds"] = self.clock() - started
            result["error"] = str(error)
            if isinstance(error, TimeoutError):
                result["timed_out"] = True
            return False, None, None, result
        elapsed = self.clock() - started
        result["elapsed_seconds"] = elapsed
        if elapsed > step.timeout_seconds:
            result["timed_out"] = True
            result["error"] = (
                f"Step exceeded its {step.timeout_seconds} second budget after {elapsed} seconds."
            )
            return False, report, raw, result
        reason = self._report_rejection(step, report)
        if reason:
            result["error"] = reason
            return False, report, raw, result
        result["ok"] = True
        return True, report, raw, result

    @staticmethod
    def _report_rejection(step: MatrixStep, report: Any) -> str | None:
        if not isinstance(report, dict):
            return "Step report is not a JSON object."
        kind = report.get("kind")
        if kind != step.report_kind:
            return f"Step report kind {kind!r} is not the expected {step.report_kind!r}."
        if step.manifest_sha256 and report.get("manifest_sha256") != step.manifest_sha256:
            return (
                f"Step report manifest_sha256 {report.get('manifest_sha256')!r} is not this step's "
                f"{step.manifest_sha256!r}; the evidence does not belong to this variant."
            )
        if report.get("ok") is not True:
            return "Step report is not ok: true."
        return None

    # -- phases ---------------------------------------------------------

    def _capture(self) -> bool:
        step = self._step(CAPTURE_STATE_STEP)
        ok, report, _, result = self._execute(step)
        self.record["initial_state"]["steps"] = [result]
        if not ok:
            self.record["failures"].append("initial-state-capture")
            return False
        self.snapshot = self._snapshot_from(report)
        self.record["initial_state"].update({"captured": True, "parameters": dict(self.snapshot)})

        if any(step.step_id == CAPTURE_CONFIGURATION_STEP for step in self.plan):
            configuration_step = self._step(CAPTURE_CONFIGURATION_STEP)
            ok, report, _, result = self._execute(configuration_step)
            self.record["initial_state"]["steps"].append(result)
            if not ok:
                self.record["failures"].append("initial-state-capture")
                self.record["initial_state"]["captured"] = False
                return False
            active = report.get("active_configuration")
            if not isinstance(active, str) or not active.strip():
                self.record["initial_state"]["captured"] = False
                self.record["failures"].append("initial-state-capture")
                result["ok"] = False
                result["error"] = "Initial state capture reported no active configuration to restore to."
                return False
            self.initial_configuration = active.strip()
            self.record["initial_state"]["configuration"] = self.initial_configuration
        return True

    def _snapshot_from(self, report: dict[str, Any]) -> dict[str, str]:
        names = sorted(
            {
                name
                for raw_variant in self.manifest.variants
                for name in variant_parameter_overrides(raw_variant)
            }
        )
        parameters = report.get("parameters")
        if names and not isinstance(parameters, dict):
            raise ValueError("Initial state capture reported no parameters; the run cannot be restored.")
        snapshot: dict[str, str] = {}
        for name in names:
            entry = parameters.get(name) if isinstance(parameters, dict) else None
            expression = entry.get("expression") if isinstance(entry, dict) else None
            if not isinstance(expression, str) or not expression.strip():
                raise ValueError(
                    f"Initial state capture has no usable expression for parameter {name!r}; a run that "
                    "cannot be restored must not start. Sync the base parameters first."
                )
            snapshot[name] = expression.strip()
        return snapshot

    def _run_variant(self, raw_variant: dict[str, Any]) -> bool:
        identity = variant_id(raw_variant)
        overrides = variant_parameter_overrides(raw_variant)
        derived = variant_manifest(self.manifest, raw_variant)
        row: dict[str, Any] = {
            "variant_id": identity,
            "description": str(raw_variant.get("description", "")),
            "source": "parameters" if overrides else "configuration",
            "manifest_sha256": manifest_sha256(derived),
            "ok": False,
            "failures": [],
            "steps": [],
        }
        if overrides:
            row["parameters"] = dict(overrides)
        else:
            row["configuration"] = variant_configuration(raw_variant)
        # Recorded before the first transaction: evidence is additive, so a later
        # variant's failure can never remove this row.
        self.record["variants"].append(row)

        verification_report: dict[str, Any] | None = None
        verification_bytes: bytes | None = None
        for step_id in VARIANT_STEPS:
            if step_id == "export" and not self.config.export_dir:
                continue
            step = self._step(step_id, identity)
            if step_id == "export":
                try:
                    step = replace(
                        step,
                        script=self._export_script(derived, identity, verification_report, verification_bytes),
                        deferred_reason=None,
                    )
                except (ValueError, TypeError) as error:
                    row["failures"].append("export")
                    row["steps"].append(
                        {"step_id": step_id, "variant_id": identity, "ok": False, "error": str(error)}
                    )
                    return False
            if step_id == "apply":
                self.mutated = True
            ok, report, raw, result = self._execute(step)
            row["steps"].append(result)
            if not ok:
                row["failures"].append(step_id)
                if step_id == "verify" and isinstance(report, dict):
                    row.update(_verification_summary(report))
                return False
            if step_id == "verify":
                verification_report = report
                verification_bytes = raw if raw is not None else _canonical_report_bytes(report)
                row.update(_verification_summary(report))
            elif step_id == "export":
                row["export"] = _export_summary(report)
        row["ok"] = True
        return True

    def _export_script(
        self,
        derived: Manifest,
        identity: str,
        verification_report: dict[str, Any] | None,
        verification_bytes: bytes | None,
    ) -> str:
        if verification_report is None or verification_bytes is None:
            raise ValueError("Export requires this variant's passing verification report.")
        config = ExportConfig(
            export_dir=_variant_export_dir(str(self.config.export_dir), identity),
            formats=tuple(self.config.formats),
            verification_report_sha256=hashlib.sha256(verification_bytes).hexdigest(),
            expected_bounds_mm=verification_binding_from_report(derived, verification_report),
        )
        return emit_export_script(derived, config)

    def _restore(self) -> None:
        restore = self.record["restore"]
        restore["required"] = self.mutated
        if not self.mutated:
            restore["reason"] = "No variant was applied, so the document was never moved off its initial state."
            return
        restore["attempted"] = True
        restore["ok"] = False
        if not self.record["initial_state"].get("captured"):
            restore["reason"] = "The initial state was never captured, so the document cannot be restored."
            self.record["failures"].append("restore")
            return

        steps: list[dict[str, Any]] = restore["steps"]
        if any(step.step_id == RESTORE_PARAMETERS_STEP for step in self.plan):
            target = restore_manifest(self.manifest, self.snapshot)
            step = replace(
                self._step(RESTORE_PARAMETERS_STEP),
                manifest_sha256=manifest_sha256(target),
                script=emit_parameter_sync_script(target),
                deferred_reason=None,
            )
            ok, _, _, result = self._execute(step)
            steps.append(result)
            if not ok:
                restore["reason"] = "Restoring the initial parameter expressions failed."
                self.record["failures"].append("restore")
                return
        if any(step.step_id == RESTORE_CONFIGURATION_STEP for step in self.plan):
            step = replace(
                self._step(RESTORE_CONFIGURATION_STEP),
                script=emit_configuration_script(self.manifest, self.initial_configuration),
                deferred_reason=None,
            )
            ok, report, _, result = self._execute(step)
            steps.append(result)
            if not ok:
                restore["reason"] = "Restoring the initially active configuration failed."
                self.record["failures"].append("restore")
                return
            active = report.get("active_configuration")
            restore["active_configuration"] = active
            if active != self.initial_configuration:
                restore["reason"] = (
                    f"Read-back configuration {active!r} is not the captured {self.initial_configuration!r}."
                )
                self.record["failures"].append("restore")
                return

        # Restoration is verified, not attempted: read the state back and compare.
        step = self._step(VERIFY_RESTORE_STEP)
        ok, report, _, result = self._execute(step)
        steps.append(result)
        if not ok:
            restore["reason"] = "The document state could not be read back, so restoration is unverified."
            self.record["failures"].append("restore")
            return
        mismatches = []
        parameters = report.get("parameters") if isinstance(report, dict) else None
        for name, expected in sorted(self.snapshot.items()):
            entry = parameters.get(name) if isinstance(parameters, dict) else None
            actual = entry.get("expression") if isinstance(entry, dict) else None
            if actual != expected:
                mismatches.append({"name": name, "expected": expected, "actual": actual})
        restore["mismatches"] = mismatches
        if mismatches:
            restore["reason"] = "Read-back parameter expressions disagree with the captured initial state."
            self.record["failures"].append("restore")
            return
        restore["ok"] = True
        restore["verified"] = True

    # -- driver ---------------------------------------------------------

    def _restore_guarded(self) -> None:
        try:
            self._restore()
        except StepReportUnavailable:
            raise
        except Exception as error:  # noqa: BLE001 - an unverifiable restore is a loud failure
            self.record["restore"]["ok"] = False
            self.record["restore"]["reason"] = str(error)
            if "restore" not in self.record["failures"]:
                self.record["failures"].append("restore")

    def _halted(self) -> dict[str, Any]:
        self.record["next_step"] = self.halted_at.to_dict() if self.halted_at else None
        self.record["complete"] = False
        self.record["ok"] = False
        return self.record

    def run(self) -> dict[str, Any]:
        variants = self.manifest.variants
        try:
            if self._capture():
                for raw_variant in variants:
                    if not self._run_variant(raw_variant) and self.config.on_failure == "stop":
                        self.record["failures"].append("variant-failed")
                        break
        except StepReportUnavailable:
            return self._halted()
        except Exception as error:  # noqa: BLE001 - an unexpected fault still restores
            self.record["failures"].append("runner-error")
            self.record["error"] = str(error)

        # Restoration runs on every exit path: success, a failing variant, and
        # an exception.
        try:
            self._restore_guarded()
        except StepReportUnavailable:
            return self._halted()

        rows = self.record["variants"]
        if any(not row["ok"] for row in rows) and "variant-failed" not in self.record["failures"]:
            self.record["failures"].append("variant-failed")
        if len(rows) != len(variants) and self.record["initial_state"].get("captured"):
            self.record["failures"].append("variants-incomplete")
        self.record["complete"] = True
        # Conjunctive: partial success is not success.
        self.record["ok"] = (
            not self.record["failures"]
            and bool(rows)
            and len(rows) == len(variants)
            and all(row["ok"] for row in rows)
            and self.record["restore"]["ok"]
        )
        return self.record


def run_variant_matrix(
    manifest: Manifest,
    config: MatrixConfig,
    executor: Callable[[MatrixStep], Any],
    *,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Drive the whole matrix through ``executor`` and return the run record.

    ``executor`` receives one :class:`MatrixStep` and returns that step's parsed
    report — or ``(report, raw_bytes)`` when the exact saved bytes are known, so
    an export binds to the hash of the file that really exists.  Raising
    :class:`StepReportUnavailable` halts the run as incomplete rather than
    failed, and the record names the step to run next.
    """
    return _MatrixRun(manifest, config, executor, clock).run()


def saved_report_executor(directory: str | Path) -> Callable[[MatrixStep], tuple[Any, bytes]]:
    """Fold reports an agent already executed and saved as ``<report_name>``.

    A missing report halts the run as incomplete and names the step to run next,
    which is what makes a live matrix resumable: execute, save, fold, repeat.
    """
    root = Path(directory)

    def execute(step: MatrixStep) -> tuple[Any, bytes]:
        path = root / step.report_name
        try:
            raw = path.read_bytes()
        except FileNotFoundError as error:
            raise StepReportUnavailable(
                f"Execute this step and save its report as {path}."
            ) from error
        return json.loads(raw.decode("utf-8")), raw

    return execute
