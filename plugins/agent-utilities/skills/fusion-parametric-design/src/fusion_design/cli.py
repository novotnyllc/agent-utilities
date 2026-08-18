from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import Callable

from .manifest import ManifestValidationError, load_manifest, validate_manifest_data
from .module_cache import emit_module_bootstrap, prepare_module_bundle
from .planner import build_plan
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


def _validate_emit_paths(args: argparse.Namespace) -> None:
    named_paths = [("manifest", args.manifest)]
    if args.output:
        named_paths.append(("output", args.output))

    for index, (left_name, left_path) in enumerate(named_paths):
        for right_name, right_path in named_paths[index + 1 :]:
            if _same_path(left_path, right_path):
                raise ValueError(f"{left_name} and {right_name} must name different files")


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


def _cmd_diff(args: argparse.Namespace) -> int:
    before = json.loads(Path(args.before).read_text(encoding="utf-8"))
    after = json.loads(Path(args.after).read_text(encoding="utf-8"))
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

    diff = subparsers.add_parser("diff-reports", help="Diff two machine-readable Fusion inventory/verification reports.")
    diff.add_argument("before")
    diff.add_argument("after")
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
