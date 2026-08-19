from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
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


def _require_live_verification_report(report_data: Any) -> None:
    """Refuse anything but the report a live verification transaction actually wrote.

    A self-declared `sample` marker is one deletion away from a valid binding, so
    the real gate is the evidence only the live transaction produces: it invokes
    Compute All, records an explicit empty failure list, and reports timeline and
    geometry maps. A hand-assembled or sample report carries none of them.
    """
    if not isinstance(report_data, dict):
        raise ValueError("Verification report must be a JSON object.")
    if report_data.get("sample"):
        raise ValueError(
            "refusing to bind a sample verification report; run the live verification transaction and pass its saved report"
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
            "verification report lacks live-transaction evidence ("
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
    _require_live_verification_report(report_data)
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
    if before.get("project") != after.get("project"):
        raise ValueError(
            f"refusing to diff reports from different projects: {before.get('project')!r} "
            f"and {after.get('project')!r}"
        )
    if not allow_manifest_change and before.get("manifest_sha256") != after.get("manifest_sha256"):
        raise ValueError(
            "the two reports were produced from different manifests "
            f"({before.get('manifest_sha256')!r} and {after.get('manifest_sha256')!r}); "
            "pass --allow-manifest-change if the manifest was intentionally edited between them"
        )


def _cmd_diff(args: argparse.Namespace) -> int:
    before = json.loads(Path(args.before).read_text(encoding="utf-8"))
    after = json.loads(Path(args.after).read_text(encoding="utf-8"))
    _require_comparable_reports(before, after, args.allow_manifest_change)
    print(json.dumps(diff_reports(before, after), indent=2, sort_keys=True))
    return 0


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
        "emit-verification": emit_verification_script,
    }
    for name, emitter in emitters.items():
        command = subparsers.add_parser(name, help=f"Emit the {name.removeprefix('emit-')} Fusion Python script.")
        command.add_argument("manifest")
        command.add_argument("-o", "--output")
        command.set_defaults(handler=lambda args, fn=emitter: _manifest_command(args, fn))

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
