from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import Callable

from .manifest import ManifestValidationError, load_manifest, validate_manifest_data
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


def _manifest_command(args: argparse.Namespace, function: Callable) -> int:
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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except ManifestValidationError as error:
        print(str(error), file=sys.stderr)
        return 2
    except (OSError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
