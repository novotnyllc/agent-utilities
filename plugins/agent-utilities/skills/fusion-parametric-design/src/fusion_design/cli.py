from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import secrets
import sys
from typing import Any, Callable

from .export_handoff import (
    ALLOWED_FORMATS,
    ExportConfig,
    emit_export_script,
    verification_binding_from_report,
)
from .manifest import ManifestValidationError, load_manifest, validate_manifest_data
from .module_cache import emit_module_bootstrap, prepare_module_bundle
from .planner import build_plan
from .prusaslicer_project import build_project, resolve_presets
from .prusaslicer_slice import slice_project
from .report_diff import diff_reports
from .scripts import (
    emit_inventory_script,
    emit_parameter_sync_script,
    emit_scaffold_script,
    emit_verification_script,
    manifest_sha256,
)
from .variant_matrix import (
    DEFAULT_SLOW_STEP_SECONDS,
    FAILURE_POLICIES,
    MatrixConfig,
    build_matrix_plan,
    run_variant_matrix,
    saved_report_executor,
)


def _write_output(content: str, output: str | None) -> None:
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
    else:
        print(content)


def _same_path(left: str, right: str) -> bool:
    return Path(left).resolve(strict=False) == Path(right).resolve(strict=False)


def _validate_named_paths(named_paths: list[tuple[str, str]]) -> None:
    for index, (left_name, left_path) in enumerate(named_paths):
        for right_name, right_path in named_paths[index + 1 :]:
            if _same_path(left_path, right_path):
                raise ValueError(f"{left_name} and {right_name} must name different files")


def _validate_emit_paths(args: argparse.Namespace) -> None:
    named_paths = [("manifest", args.manifest)]
    if args.output:
        named_paths.append(("output", args.output))
    _validate_named_paths(named_paths)


def _manifest_command(args: argparse.Namespace, function: Callable) -> int:
    _validate_emit_paths(args)
    manifest = load_manifest(args.manifest)
    _write_output(function(manifest), args.output)
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    path = Path(args.manifest)
    data = json.loads(path.read_text(encoding="utf-8"))
    issues = validate_manifest_data(data)
    payload = {"ok": not issues, "issues": [asdict(issue) for issue in issues]}
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if not issues else 2


def _cmd_plan(args: argparse.Namespace) -> int:
    plan = build_plan(load_manifest(args.manifest))
    print(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
    return 2 if plan.blocked else 0


def _cmd_emit_verification(args: argparse.Namespace) -> int:
    _validate_emit_paths(args)
    manifest = load_manifest(args.manifest)
    # Minted here, never derived from the manifest: a report can only echo it
    # back by having been produced by this very script.
    nonce = secrets.token_hex(16)
    _write_output(emit_verification_script(manifest, nonce), args.output)
    print(
        f"verification nonce: {nonce}\n"
        "Pass it to emit-export as --verification-nonce once this script has run in Fusion "
        "and its report is saved. Re-emitting mints a new nonce and invalidates this one.",
        file=sys.stderr,
    )
    return 0


def _require_live_verification_report(report_data: Any, nonce: str) -> None:
    """Refuse anything but the report the emitted verification script wrote.

    The nonce is the load-bearing check. `emit-verification` mints a random one,
    embeds it in the script it emits, and prints it to stderr; only a report
    produced by running that exact script echoes it back. Nothing derivable from
    the manifest alone -- including this package's own
    `export_handoff.example_verification_report` -- can satisfy it.

    The checks below it are cheap consistency checks, not proof of liveness:
    each is a constant that anyone holding the script could also supply. They
    catch a truncated or hand-edited report early; they are not a second
    independent gate, and must not be described as one.
    """
    if not isinstance(report_data, dict):
        raise ValueError("Verification report must be a JSON object.")
    if report_data.get("sample"):
        raise ValueError(
            "refusing to bind a sample verification report; run the live verification transaction and pass its saved report"
        )
    reported_nonce = report_data.get("verification_nonce")
    if not isinstance(reported_nonce, str) or not reported_nonce or reported_nonce != nonce:
        raise ValueError(
            "verification report nonce does not match --verification-nonce; bind the export to a "
            "report produced by running the script emit-verification emitted, and pass the nonce "
            "that command printed"
        )
    missing = []
    if report_data.get("compute_invoked") is not True:
        missing.append("compute_invoked: true")
    if report_data.get("failures") != []:
        missing.append("failures: []")
    for key in ("timeline", "geometry"):
        value = report_data.get(key)
        if not isinstance(value, dict) or not value:
            missing.append(f"a non-empty {key} object")
    if missing:
        raise ValueError(
            "verification report is not internally consistent ("
            + "; ".join(missing)
            + "); run the live verification transaction and pass its saved report"
        )


def _cmd_emit_export(args: argparse.Namespace) -> int:
    named_paths = [("manifest", args.manifest), ("verification-report", args.verification_report)]
    if args.output:
        named_paths.append(("output", args.output))
    _validate_named_paths(named_paths)

    formats = tuple(args.formats or ("step", "3mf"))
    if len(set(formats)) != len(formats):
        raise ValueError("--format values must not repeat")

    report_bytes = Path(args.verification_report).read_bytes()
    manifest = load_manifest(args.manifest)
    report_data = json.loads(report_bytes.decode("utf-8"))
    _require_live_verification_report(report_data, args.verification_nonce)
    config = ExportConfig(
        export_dir=args.export_dir,
        formats=formats,
        verification_report_sha256=hashlib.sha256(report_bytes).hexdigest(),
        expected_bounds_mm=verification_binding_from_report(manifest, report_data),
    )
    _write_output(emit_export_script(manifest, config), args.output)
    return 0


# Slicing is supported but opt-in: the default path builds the project file and
# executes nothing at all.
SLICE_NOT_ATTEMPTED = {
    "supported": True,
    "attempted": False,
    "reason": (
        "Slicing was not requested. Pass --slice to run PrusaSlicer headlessly on the generated "
        "project and report the statistics its G-code actually contains."
    ),
    "detail": (
        "Without --slice, no print time, filament mass, or G-code statistic is available here, and "
        "none may be inferred, estimated, or interpolated from this project. Either re-run with "
        "--slice or slice the project in the PrusaSlicer GUI and record the result against this "
        "project's sha256."
    ),
}


def _cmd_prusaslicer_project(args: argparse.Namespace) -> int:
    _validate_named_paths(
        [("manifest", args.manifest), ("export-index", args.export_index), ("output", args.output)]
    )
    manifest = load_manifest(args.manifest)
    presets = resolve_presets(
        {"printer": args.printer, "filament": args.filament, "print": args.print_preset},
        args.config_root,
    )
    result = build_project(manifest, args.export_index, args.output, presets)
    if args.slice:
        result["slice"] = slice_project(
            result["project_path"], presets, executable=args.slicer_executable
        )
    else:
        result["slice"] = SLICE_NOT_ATTEMPTED
    print(json.dumps(result, indent=2, sort_keys=True))
    # A requested slice that did not produce G-code must not look like success.
    return 2 if args.slice and not result["slice"].get("ok") else 0


# Only these two report kinds have a shape diff_reports understands. Diffing
# across kinds invents removals, because the shapes are not comparable.
DIFFABLE_REPORT_KINDS = ("inventory", "verification")


def _require_comparable_reports(before: Any, after: Any, allow_manifest_change: bool) -> None:
    for label, report in (("before", before), ("after", after)):
        if not isinstance(report, dict):
            raise ValueError(f"{label} report must be a JSON object.")
    before_kind = before.get("kind")
    after_kind = after.get("kind")
    if before_kind != after_kind:
        raise ValueError(
            f"refusing to diff a {before_kind!r} report against a {after_kind!r} report; "
            "the shapes are not comparable and the result would invent changes"
        )
    if before_kind not in DIFFABLE_REPORT_KINDS:
        raise ValueError(
            f"report kind {before_kind!r} cannot be diffed; expected one of "
            f"{', '.join(DIFFABLE_REPORT_KINDS)}"
        )
    # Absence must fail like a mismatch: two reports that both omit `project`
    # would otherwise compare None == None and sail through.
    for field in ("project", "manifest_sha256"):
        for label, report in (("before", before), ("after", after)):
            value = report.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"{label} report has no usable {field!r}; a report without it cannot be "
                    "shown to describe the same design"
                )
    if before["project"] != after["project"]:
        raise ValueError(
            f"refusing to diff reports from different projects: {before['project']!r} "
            f"and {after['project']!r}"
        )
    if not allow_manifest_change and before["manifest_sha256"] != after["manifest_sha256"]:
        raise ValueError(
            "the two reports were produced from different manifests "
            f"({before['manifest_sha256']!r} and {after['manifest_sha256']!r}); "
            "pass --allow-manifest-change if the manifest was intentionally edited between them"
        )


def _cmd_plan_variants(args: argparse.Namespace) -> int:
    named_paths = [("manifest", args.manifest)]
    if args.output:
        named_paths.append(("output", args.output))
    if args.reports_dir:
        named_paths.append(("reports-dir", args.reports_dir))
    _validate_named_paths(named_paths)

    formats = tuple(args.formats or ("step", "3mf"))
    if len(set(formats)) != len(formats):
        raise ValueError("--format values must not repeat")

    manifest = load_manifest(args.manifest)
    config = MatrixConfig(
        export_dir=args.export_dir,
        formats=formats,
        on_failure=args.on_failure,
        slow_step_seconds=args.slow_step_seconds,
    )
    if args.reports_dir:
        record = run_variant_matrix(manifest, config, saved_report_executor(args.reports_dir))
        _write_output(json.dumps(record, indent=2, sort_keys=True), args.output)
        # A run still waiting on reports is incomplete, not failed; only a real
        # failure — a variant, the capture, or the restore — exits non-zero.
        return 2 if record["failures"] else 0

    plan = build_matrix_plan(manifest, config)
    payload = {
        "kind": "variant-matrix-plan",
        "project": manifest.project_name,
        "manifest_sha256": manifest_sha256(manifest),
        "on_failure": config.on_failure,
        "slow_step_seconds": float(config.slow_step_seconds),
        "export_requested": bool(config.export_dir),
        "steps": [step.to_dict() for step in plan],
    }
    _write_output(json.dumps(payload, indent=2, sort_keys=True), args.output)
    return 0


def _cmd_diff(args: argparse.Namespace) -> int:
    before = json.loads(Path(args.before).read_text(encoding="utf-8"))
    after = json.loads(Path(args.after).read_text(encoding="utf-8"))
    _require_comparable_reports(before, after, args.allow_manifest_change)
    diff = diff_reports(before, after)
    print(json.dumps(diff, indent=2, sort_keys=True))
    # Every sibling command exits 2 when the thing it was asked to check failed.
    # A diff that found a regression is that case, not a successful no-op.
    regressed = bool(diff["failures_added"]) or (diff["ok_before"] and not diff["ok_after"])
    return 2 if regressed else 0


def _cmd_prepare_module_bundle(args: argparse.Namespace) -> int:
    result = prepare_module_bundle(args.source_package, args.entry_module, args.cache_root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _cmd_emit_module_bootstrap(args: argparse.Namespace) -> int:
    _write_output(emit_module_bootstrap(args.bundle, args.output), args.output)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fusion-design",
        description="Validate a Fusion design manifest, produce a workflow plan, and emit small Fusion Python transactions.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate a fusion-project.json manifest.")
    validate.add_argument("manifest")
    validate.set_defaults(handler=_cmd_validate)

    plan = subparsers.add_parser("plan", help="Produce the gated research/model/verification plan.")
    plan.add_argument("manifest")
    plan.set_defaults(handler=_cmd_plan)

    emitters = {
        "emit-inventory": emit_inventory_script,
        "emit-parameter-sync": emit_parameter_sync_script,
        "emit-scaffold": emit_scaffold_script,
    }
    for name, emitter in emitters.items():
        command = subparsers.add_parser(name, help=f"Emit the {name.removeprefix('emit-')} Fusion Python script.")
        command.add_argument("manifest")
        command.add_argument("-o", "--output")
        command.set_defaults(handler=lambda args, fn=emitter: _manifest_command(args, fn))

    emit_verification = subparsers.add_parser(
        "emit-verification",
        help=(
            "Emit the verification Fusion Python script. Mints a single-use nonce, embeds it in "
            "the script, and prints it to stderr; emit-export requires that nonce."
        ),
    )
    emit_verification.add_argument("manifest")
    emit_verification.add_argument("-o", "--output")
    emit_verification.set_defaults(handler=_cmd_emit_verification)

    emit_export = subparsers.add_parser(
        "emit-export",
        help="Emit the deterministic export/handoff Fusion Python script bound to a passing verification report.",
    )
    emit_export.add_argument("manifest")
    emit_export.add_argument(
        "--verification-report",
        required=True,
        help="Path to the saved verification report JSON this export is justified by.",
    )
    emit_export.add_argument(
        "--verification-nonce",
        required=True,
        help=(
            "The nonce emit-verification printed for the script that produced this report. The "
            "report must echo it back, which only running that script can do."
        ),
    )
    emit_export.add_argument(
        "--export-dir",
        required=True,
        help="Directory on the Fusion host where export files and the handoff index are written.",
    )
    emit_export.add_argument(
        "--format",
        action="append",
        choices=list(ALLOWED_FORMATS),
        dest="formats",
        help=(
            "Export format (repeatable). Defaults to step plus 3mf; step is always required. "
            "The prusaslicer-project adapter reads only 3MF artifacts, so an index emitted "
            "without 3mf cannot feed it."
        ),
    )
    emit_export.add_argument("-o", "--output")
    emit_export.set_defaults(handler=_cmd_emit_export)

    plan_variants = subparsers.add_parser(
        "plan-variants",
        help="Plan the bounded variant matrix, or fold saved step reports into the run record.",
    )
    plan_variants.add_argument("manifest")
    plan_variants.add_argument(
        "--export-dir",
        help=(
            "Directory on the Fusion host under which each variant gets its own export subdirectory. "
            "Omit to verify without exporting."
        ),
    )
    plan_variants.add_argument(
        "--format",
        action="append",
        choices=list(ALLOWED_FORMATS),
        dest="formats",
        help="Export format (repeatable). Defaults to step plus 3mf; step is always required.",
    )
    plan_variants.add_argument(
        "--on-failure",
        choices=sorted(FAILURE_POLICIES),
        default="stop",
        help="Whether a failing variant stops the run or the matrix continues. The overall run fails either way.",
    )
    plan_variants.add_argument(
        "--slow-step-seconds",
        type=float,
        default=DEFAULT_SLOW_STEP_SECONDS,
        help=(
            "Elapsed-time threshold above which a step that has already returned is failed as "
            "untrustworthy. Not a budget: nothing is cancelled, and a hung transaction never returns."
        ),
    )
    plan_variants.add_argument(
        "--reports-dir",
        help=(
            "Directory holding the step reports already executed and saved under their planned report "
            "names. Given this, the run record is folded from that evidence and names the next step."
        ),
    )
    plan_variants.add_argument("-o", "--output")
    plan_variants.set_defaults(handler=_cmd_plan_variants)

    prusaslicer = subparsers.add_parser(
        "prusaslicer-project",
        help="Build a PrusaSlicer project 3MF from a verified export index; optionally slice it.",
    )
    prusaslicer.add_argument("manifest")
    prusaslicer.add_argument(
        "--export-index",
        required=True,
        help=(
            "Path to the export-handoff index JSON. Its manifest_sha256 must match this manifest, "
            "and its 3MF artifacts are re-verified by hash and byte size."
        ),
    )
    prusaslicer.add_argument(
        "--output",
        required=True,
        help="Project .3mf to create. An existing path is never overwritten.",
    )
    prusaslicer.add_argument("--printer", help="Installed PrusaSlicer printer preset name.")
    prusaslicer.add_argument("--filament", help="Installed PrusaSlicer filament preset name.")
    prusaslicer.add_argument("--print", dest="print_preset", help="Installed PrusaSlicer print preset name.")
    prusaslicer.add_argument(
        "--config-root",
        help="PrusaSlicer configuration directory. Defaults to the platform user configuration location.",
    )
    prusaslicer.add_argument(
        "--slice",
        action="store_true",
        help=(
            "Also run PrusaSlicer headlessly on the generated project and report the statistics its "
            "G-code contains. Off by default: without this flag no binary is executed."
        ),
    )
    prusaslicer.add_argument(
        "--slicer-executable",
        help="Path to the PrusaSlicer binary. Defaults to the installed app bundle, then PATH.",
    )
    prusaslicer.set_defaults(handler=_cmd_prusaslicer_project)

    diff = subparsers.add_parser(
        "diff-reports",
        help=(
            "Diff two machine-readable Fusion reports of the same kind (inventory or verification) "
            "from the same project."
        ),
    )
    diff.add_argument("before")
    diff.add_argument("after")
    diff.add_argument(
        "--allow-manifest-change",
        action="store_true",
        help="Permit a diff whose two reports were produced from different manifest hashes.",
    )
    diff.set_defaults(handler=_cmd_diff)

    prepare_modules = subparsers.add_parser(
        "prepare-module-bundle",
        help="Cache a pure-Python package for use by Fusion MCP execution.",
    )
    prepare_modules.add_argument("source_package")
    prepare_modules.add_argument("entry_module")
    prepare_modules.add_argument("--cache-root")
    prepare_modules.set_defaults(handler=_cmd_prepare_module_bundle)

    emit_bootstrap = subparsers.add_parser(
        "emit-module-bootstrap",
        help="Verify a cached module bundle and emit its Fusion bootstrap.",
    )
    emit_bootstrap.add_argument("bundle")
    emit_bootstrap.add_argument("-o", "--output")
    emit_bootstrap.set_defaults(handler=_cmd_emit_module_bootstrap)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except ManifestValidationError as error:
        print(str(error), file=sys.stderr)
        return 2
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
