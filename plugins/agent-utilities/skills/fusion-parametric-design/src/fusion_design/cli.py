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
from .mesh_convert import emit_mesh_convert_script
from .mesh_datum import ReconstructionRefused, parse_fit_record
from .reconstruction_coverage import compose_coverage, format_coverage
from .reconstruction_program import build_reconstruction_program
from .mesh_deviation import emit_mesh_deviation_script
from .mesh_dump import MeshDumpError, read_mesh_dump
from .mesh_editability import (
    emit_mesh_editability_script,
    validate_editability_report,
)
from .mesh_extract import emit_mesh_extract_script
from .mesh_face_groups import emit_mesh_face_groups_script
from .mesh_rebuild import emit_mesh_rebuild_script, load_program, replan_without
from .mesh_segmentation import fit_regions, load_spec
from .mesh_probe import emit_capability_probe_script
from .mesh_source import (
    emit_mesh_capture_script,
    mesh_source_record,
    verify_manifest_mesh_sources,
)
from .module_cache import emit_module_bootstrap, prepare_module_bundle
from .planner import build_plan
from .prusaslicer_project import build_project, resolve_presets
from .prusaslicer_slice import slice_project
from .report_diff import diff_reports
from .scripts import (
    emit_document_save_script,
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


def _reject_output_inside(directory: str, output: str, label: str) -> None:
    """An output written into an evidence directory destroys evidence.

    Both sides are resolved first, so a symlink or a ``..`` segment cannot walk
    into the directory behind the check.
    """
    root = Path(directory).resolve(strict=False)
    if Path(output).resolve(strict=False).is_relative_to(root):
        raise ValueError(f"output must not be written inside {label}")


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
    # Load through the same door as every other command. A bare json.loads here
    # skipped the duplicate-key guard, the root-type check and JSONDecodeError
    # reporting, so the one command a human runs to sign a manifest off was the
    # one command that did not see what `plan` and the emitters see.
    try:
        issues = validate_manifest_data(load_manifest(args.manifest).data)
    except ManifestValidationError as error:
        issues = list(error.issues)
    # Warnings are reported but do not block: they record something the manifest
    # left undeclared rather than something it got wrong.
    blocking = [issue for issue in issues if issue.severity == "error"]
    payload = {"ok": not blocking, "issues": [asdict(issue) for issue in issues]}
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if not blocking else 2


def _cmd_plan(args: argparse.Namespace) -> int:
    plan = build_plan(load_manifest(args.manifest))
    print(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
    return 2 if plan.blocked else 0


def _cmd_emit_document_save(args: argparse.Namespace) -> int:
    _validate_emit_paths(args)
    manifest = load_manifest(args.manifest)
    _write_output(emit_document_save_script(manifest, args.document_id), args.output)
    return 0


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


def _cmd_emit_mesh_capture(args: argparse.Namespace) -> int:
    _validate_emit_paths(args)
    manifest = load_manifest(args.manifest)
    # The recorded digest is only load-bearing if something re-checks it: a
    # source swapped after capture must stop the workflow here, not be silently
    # re-measured by the transaction this command emits.
    verify_manifest_mesh_sources(manifest, args.manifest)
    _write_output(emit_mesh_capture_script(manifest), args.output)
    return 0


def _cmd_emit_capability_probe(args: argparse.Namespace) -> int:
    named_paths = [("manifest", args.manifest)]
    if args.probe_spec:
        named_paths.append(("probe-spec", args.probe_spec))
    if args.output:
        named_paths.append(("output", args.output))
    _validate_named_paths(named_paths)

    manifest = load_manifest(args.manifest)
    spec = None
    if args.probe_spec:
        spec = json.loads(Path(args.probe_spec).read_text(encoding="utf-8"))
    _write_output(emit_capability_probe_script(manifest, spec), args.output)
    return 0


def _mesh_path_command(args: argparse.Namespace, spec_name: str, function: Callable) -> int:
    spec_path = getattr(args, spec_name)
    named_paths = [("manifest", args.manifest), ("classification", args.classification), ("spec", spec_path)]
    if args.output:
        named_paths.append(("output", args.output))
    _validate_named_paths(named_paths)

    manifest = load_manifest(args.manifest)
    verify_manifest_mesh_sources(manifest, args.manifest)
    classification = json.loads(Path(args.classification).read_text(encoding="utf-8"))
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    if not isinstance(classification, dict):
        raise ValueError("The classification record must be a JSON object.")
    # The source is named independently of the record, so the gate's identity
    # check compares two values that came from different places. Reading the id
    # out of the record and then looking the record up by it would compare a
    # value against itself and could never fail.
    source_record = mesh_source_record(manifest, args.mesh_source_id)
    _write_output(function(manifest, classification, source_record, spec), args.output)
    return 0


def _cmd_plan_reconstruction(args: argparse.Namespace) -> int:
    named_paths = [("manifest", args.manifest), ("fit-record", args.fit_record), ("program-spec", args.program_spec)]
    if args.output:
        named_paths.append(("output", args.output))
    if args.dump:
        named_paths.append(("dump", args.dump))
    _validate_named_paths(named_paths)

    manifest = load_manifest(args.manifest)
    fit_record = parse_fit_record(json.loads(Path(args.fit_record).read_text(encoding="utf-8")))
    spec = json.loads(Path(args.program_spec).read_text(encoding="utf-8"))
    dump = None
    if args.dump:
        # Re-hashed against the digest the fit record is bound to, before a byte
        # of it is parsed -- the same rule the emitter follows for the same file.
        try:
            dump = read_mesh_dump(args.dump, fit_record.dump_sha256)
        except MeshDumpError as error:
            print(
                json.dumps(
                    {"reason": error.reason, "detail": error.detail}, indent=2, sort_keys=True
                )
            )
            return 2
    try:
        program = build_reconstruction_program(
            fit_record, spec, manifest_sha256=manifest_sha256(manifest), dump=dump
        )
    except ReconstructionRefused as refused:
        # A refusal is a result, not a crash: it prints its named reason and the
        # alternative on stdout so the record can be kept as evidence.
        print(json.dumps(refused.to_dict(), indent=2, sort_keys=True))
        return 2
    _write_output(json.dumps(program, indent=2, sort_keys=True), args.output)
    return 0


def _cmd_emit_mesh_rebuild(args: argparse.Namespace) -> int:
    named_paths = [
        ("manifest", args.manifest),
        ("classification", args.classification),
        ("program", args.program),
        ("rebuild-spec", args.rebuild_spec),
    ]
    if args.output:
        named_paths.append(("output", args.output))
    _validate_named_paths(named_paths)

    manifest = load_manifest(args.manifest)
    verify_manifest_mesh_sources(manifest, args.manifest)
    classification = json.loads(Path(args.classification).read_text(encoding="utf-8"))
    program = load_program(args.program)
    spec = json.loads(Path(args.rebuild_spec).read_text(encoding="utf-8"))
    source_record = mesh_source_record(manifest, args.mesh_source_id)
    # Minted here, never derived from the program: only a report produced by
    # running this exact script can echo it back.
    nonce = secrets.token_hex(16)
    try:
        source = emit_mesh_rebuild_script(
            manifest, classification, source_record, program, spec, nonce
        )
    except ReconstructionRefused as refused:
        print(json.dumps(refused.to_dict(), indent=2, sort_keys=True))
        return 2
    _write_output(source, args.output)
    print(
        f"rebuild nonce: {nonce}\n"
        "The rebuild report echoes it back; emit-mesh-editability binds to that report. "
        "Re-emitting mints a new nonce and invalidates this one.",
        file=sys.stderr,
    )
    return 0


def _cmd_emit_mesh_editability(args: argparse.Namespace) -> int:
    named_paths = [
        ("manifest", args.manifest),
        ("rebuild-record", args.rebuild_record),
        ("editability-spec", args.editability_spec),
    ]
    if args.output:
        named_paths.append(("output", args.output))
    _validate_named_paths(named_paths)

    manifest = load_manifest(args.manifest)
    record = json.loads(Path(args.rebuild_record).read_text(encoding="utf-8"))
    spec = json.loads(Path(args.editability_spec).read_text(encoding="utf-8"))
    nonce = secrets.token_hex(16)
    try:
        source = emit_mesh_editability_script(manifest, record, spec, nonce)
    except ManifestValidationError as invalid:
        print(
            json.dumps(
                {"ok": False, "issues": [asdict(issue) for issue in invalid.issues]},
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    _write_output(source, args.output)
    print(
        f"editability nonce: {nonce}\n"
        "Pass it to check-editability once this script has run in Fusion and its report is saved.",
        file=sys.stderr,
    )
    return 0


def _cmd_check_editability(args: argparse.Namespace) -> int:
    _validate_named_paths(
        [("rebuild-record", args.rebuild_record), ("editability-report", args.editability_report)]
    )
    record = json.loads(Path(args.rebuild_record).read_text(encoding="utf-8"))
    report = json.loads(Path(args.editability_report).read_text(encoding="utf-8"))
    verdict = validate_editability_report(
        report, nonce=args.editability_nonce, rebuild_record=record
    )
    print(json.dumps(verdict, indent=2, sort_keys=True))
    return 0 if verdict["ok"] else 2


def _cmd_reconstruction_coverage(args: argparse.Namespace) -> int:
    named_paths = [("program", args.program)]
    for name, value in (
        ("fit-record", args.fit_record),
        ("rebuild-report", args.rebuild_report),
        ("editability-verdict", args.editability_verdict),
        ("output", args.output),
    ):
        if value:
            named_paths.append((name, value))
    _validate_named_paths(named_paths)

    def read(path: str | None) -> dict | None:
        return None if not path else json.loads(Path(path).read_text(encoding="utf-8"))

    account = compose_coverage(
        load_program(args.program),
        fit_record=read(args.fit_record),
        rebuild_report=read(args.rebuild_report),
        editability_verdict=read(args.editability_verdict),
    )
    _write_output(json.dumps(account, indent=2, sort_keys=True), args.output)
    # The prose goes to stderr so the JSON stays pipeable, and it goes out on
    # every run: a partial reconstruction that is only visible to a reader who
    # parsed the JSON is a partial reconstruction that gets reported as a
    # success.
    print(format_coverage(account), file=sys.stderr)
    return 0 if account["label"] != "reconstruction-refused" else 2


def _cmd_replan_without(args: argparse.Namespace) -> int:
    named_paths = [("program", args.program), ("refusal", args.refusal)]
    if args.output:
        named_paths.append(("output", args.output))
    _validate_named_paths(named_paths)
    program = load_program(args.program)
    refusal_report = json.loads(Path(args.refusal).read_text(encoding="utf-8"))
    replanned = replan_without(program, refusal_report)
    _write_output(json.dumps(replanned, indent=2, sort_keys=True), args.output)
    return 0


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
        verification_binding=verification_binding_from_report(manifest, report_data),
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
        # The whole chain, not just the project hash: the slice block is the part
        # a human quotes, and on its own it names nothing that verified it.
        result["slice"] = slice_project(
            result["project_path"],
            presets,
            bindings={
                key: result[key]
                for key in (
                    "project_sha256",
                    "export_index_sha256",
                    "manifest_sha256",
                    "verification_report_sha256",
                    "export_run_id",
                )
            },
            executable=args.slicer_executable,
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
    if args.reports_dir and args.output:
        # Writing the record over a saved step report either loses that
        # evidence or feeds the record back to a later fold as evidence.
        _reject_output_inside(args.reports_dir, args.output, "reports-dir")

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


def _cmd_fit_regions(args: argparse.Namespace) -> int:
    """Detect primitives in a hash-bound mesh dump and print the fit record.

    The dump digest is a required argument, never read from the dump itself: a
    hash a file carries about its own bytes is not a binding, and the point of
    this argument is that it came from the extraction report.
    """
    _validate_named_paths(
        [("dump", args.dump), ("spec", args.spec)]
        + ([("output", args.output)] if args.output else [])
    )
    spec = load_spec(json.loads(Path(args.spec).read_text(encoding="utf-8")))
    dump = read_mesh_dump(args.dump, args.dump_sha256)
    record = fit_regions(dump, spec)
    _write_output(json.dumps(record, indent=2, sort_keys=True), args.output)
    # A refusal is a declared outcome with a named reason, so it exits non-zero:
    # nothing downstream may consume a record that produced no geometry.
    return 2 if record["refusal"] is not None else 0


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

    document_save = subparsers.add_parser(
        "emit-document-save",
        help=(
            "Emit the document save/adopt Fusion Python script: name an unsaved active document "
            "from the manifest and save it into the resolved project folder, version-checkpoint "
            "one already saved, or — with --document-id — reconnect to the recorded document by "
            "dataFile id (open documents first, then the data API), never by name."
        ),
    )
    document_save.add_argument("manifest")
    document_save.add_argument(
        "--document-id",
        help=(
            "The dataFile id a previous document-save report recorded. With it the transaction "
            "adopts the open document carrying that id, or locates and opens it through the data "
            "API; a missing id is a named refusal, and a name match is only ever reported as a hint."
        ),
    )
    document_save.add_argument("-o", "--output")
    document_save.set_defaults(handler=_cmd_emit_document_save)

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

    mesh_capture = subparsers.add_parser(
        "emit-mesh-capture",
        help="Emit the read-only immutable mesh capture script, re-verifying every declared source hash.",
    )
    mesh_capture.add_argument("manifest")
    mesh_capture.add_argument("-o", "--output")
    mesh_capture.set_defaults(handler=_cmd_emit_mesh_capture)

    capability_probe = subparsers.add_parser(
        "emit-capability-probe",
        help=(
            "Emit the read-only runtime capability probe: the embedded interpreter's tag triple, its "
            "writable sys.path entries, which preview mesh and construction APIs exist, and — when a "
            "probe spec binds a body — the face-group histogram and a dump write round-trip."
        ),
    )
    capability_probe.add_argument("manifest")
    capability_probe.add_argument(
        "--probe-spec",
        help=(
            "Optional path to a probe spec JSON: component_path, body_name, dump_dir. Without it the "
            "face-group and write-back probes report 'not-requested' rather than passing."
        ),
    )
    capability_probe.add_argument("-o", "--output")
    capability_probe.set_defaults(handler=_cmd_emit_capability_probe)

    mesh_extract = subparsers.add_parser(
        "emit-mesh-extract",
        help=(
            "Emit the read-only mesh extraction script: writes a hash-bound indexed mesh dump the host "
            "reader re-hashes before parsing. Requires a classification of parametric-rebuild for this "
            "exact mesh source."
        ),
    )
    mesh_extract.add_argument("manifest")
    mesh_extract.add_argument(
        "--mesh-source-id",
        required=True,
        help="Id of the mesh_sources record being operated on; the classification must agree with it.",
    )
    mesh_extract.add_argument(
        "--classification",
        required=True,
        help="Path to the recorded classification JSON; its path must be 'parametric-rebuild'.",
    )
    mesh_extract.add_argument(
        "--extract-spec",
        required=True,
        help=(
            "Path to the extraction spec JSON: body binding, dump_dir, and the declared max_triangles "
            "and fallback_max_bytes with their rationales."
        ),
    )
    mesh_extract.add_argument("-o", "--output")
    mesh_extract.set_defaults(
        handler=lambda args: _mesh_path_command(args, "extract_spec", emit_mesh_extract_script)
    )

    mesh_face_groups = subparsers.add_parser(
        "emit-mesh-face-groups",
        help=(
            "Emit the segmentation script: runs MeshGenerateFaceGroups on the mesh body with the "
            "accurate method set explicitly, then reads the per-triangle grouping and per-group "
            "metadata back. Run this before emit-mesh-extract, which reads the grouping and never "
            "generates one. Requires a classification of parametric-rebuild for this exact mesh "
            "source."
        ),
    )
    mesh_face_groups.add_argument("manifest")
    mesh_face_groups.add_argument(
        "--mesh-source-id",
        required=True,
        help="Id of the mesh_sources record being operated on; the classification must agree with it.",
    )
    mesh_face_groups.add_argument(
        "--classification",
        required=True,
        help="Path to the recorded classification JSON; its path must be 'parametric-rebuild'.",
    )
    mesh_face_groups.add_argument(
        "--face-group-spec",
        required=True,
        help=(
            "Path to the face-group spec JSON: the body binding. The grouping method is not a spec "
            "field -- the fast method is measurably wrong on real parts, so only the accurate one is "
            "offered."
        ),
    )
    mesh_face_groups.add_argument("-o", "--output")
    mesh_face_groups.set_defaults(
        handler=lambda args: _mesh_path_command(
            args, "face_group_spec", emit_mesh_face_groups_script
        )
    )

    mesh_convert = subparsers.add_parser(
        "emit-mesh-convert",
        help=(
            "Emit the faceted mesh-to-B-Rep conversion script with its refusal ladder. Refuses unless the "
            "recorded classification chose faceted-brep for this exact mesh source."
        ),
    )
    mesh_convert.add_argument("manifest")
    mesh_convert.add_argument(
        "--mesh-source-id",
        required=True,
        help="Id of the mesh_sources record being operated on; the classification must agree with it.",
    )
    mesh_convert.add_argument(
        "--classification",
        required=True,
        help="Path to the recorded classification JSON; its path must be 'faceted-brep'.",
    )
    mesh_convert.add_argument(
        "--convert-spec",
        required=True,
        help="Path to the conversion spec JSON: component_path, body_name, max_faces_per_face_group.",
    )
    mesh_convert.add_argument("-o", "--output")
    mesh_convert.set_defaults(
        handler=lambda args: _mesh_path_command(args, "convert_spec", emit_mesh_convert_script)
    )

    mesh_deviation = subparsers.add_parser(
        "emit-mesh-deviation",
        help=(
            "Emit the deviation script and its asymmetric verdict against the immutable source. Requires a "
            "classification of faceted-brep or parametric-rebuild for this exact mesh source."
        ),
    )
    mesh_deviation.add_argument("manifest")
    mesh_deviation.add_argument(
        "--mesh-source-id",
        required=True,
        help="Id of the mesh_sources record being operated on; the classification must agree with it.",
    )
    mesh_deviation.add_argument(
        "--classification",
        required=True,
        help="Path to the recorded classification JSON for the mesh source being graded.",
    )
    mesh_deviation.add_argument(
        "--deviation-spec",
        required=True,
        help=(
            "Path to the deviation spec JSON: source and reconstruction body bindings, declared "
            "thresholds_mm, and the rationale for those thresholds."
        ),
    )
    mesh_deviation.add_argument("-o", "--output")
    mesh_deviation.set_defaults(
        handler=lambda args: _mesh_path_command(args, "deviation_spec", emit_mesh_deviation_script)
    )

    plan_reconstruction = subparsers.add_parser(
        "plan-reconstruction",
        help=(
            "Derive the datum frame, license and adopt relationships, and emit the versioned "
            "reconstruction program from a fit record. Host-side only; no Fusion needed."
        ),
    )
    plan_reconstruction.add_argument("manifest")
    plan_reconstruction.add_argument(
        "--fit-record",
        required=True,
        help="Path to the fit record JSON produced by the fitting stage, bound to a mesh dump hash.",
    )
    plan_reconstruction.add_argument(
        "--program-spec",
        required=True,
        help=(
            "Path to the program spec JSON: the declared thresholds with their rationales, and the "
            "adoption decision for each proposal that is adopted."
        ),
    )
    plan_reconstruction.add_argument(
        "--dump",
        help=(
            "Optional path to the mesh dump this fit record was derived from. With it the planner "
            "decomposes the part into 2.5D slabs -- a slab's loops are cut from the dump's own "
            "triangles, which the fit record does not carry. Without it the plan is what it was "
            "before slabs existed and the program records that it was not attempted."
        ),
    )
    plan_reconstruction.add_argument("-o", "--output")
    plan_reconstruction.set_defaults(handler=_cmd_plan_reconstruction)

    mesh_rebuild = subparsers.add_parser(
        "emit-mesh-rebuild",
        help=(
            "Emit the parametric rebuild transaction from a reconstruction program and its bound "
            "mesh dump. Requires a parametric-rebuild classification for this exact mesh source."
        ),
    )
    mesh_rebuild.add_argument("manifest")
    mesh_rebuild.add_argument(
        "--mesh-source-id",
        required=True,
        help="Id of the mesh_sources record being rebuilt; the classification must agree with it.",
    )
    mesh_rebuild.add_argument(
        "--classification", required=True, help="Path to the recorded classification JSON."
    )
    mesh_rebuild.add_argument(
        "--program",
        required=True,
        help="Path to the reconstruction program JSON produced by plan-reconstruction.",
    )
    mesh_rebuild.add_argument(
        "--rebuild-spec",
        required=True,
        help=(
            "Path to the rebuild spec JSON: the component name, the path to the mesh dump the "
            "program was fitted from, and the declared emission thresholds with their rationales."
        ),
    )
    mesh_rebuild.add_argument("-o", "--output")
    mesh_rebuild.set_defaults(handler=_cmd_emit_mesh_rebuild)

    mesh_editability = subparsers.add_parser(
        "emit-mesh-editability",
        help=(
            "Emit the editability proof: perturb each rebuilt parameter, assert its declared "
            "observable moved, restore, and assert the model returned."
        ),
    )
    mesh_editability.add_argument("manifest")
    mesh_editability.add_argument(
        "--rebuild-record",
        required=True,
        help="Path to the saved report the rebuild transaction wrote.",
    )
    mesh_editability.add_argument(
        "--editability-spec",
        required=True,
        help=(
            "Path to the editability spec JSON: per-parameter perturbation, expected observable, "
            "minimum observable change and rationale, plus the restore epsilon per observable."
        ),
    )
    mesh_editability.add_argument("-o", "--output")
    mesh_editability.set_defaults(handler=_cmd_emit_mesh_editability)

    check_editability = subparsers.add_parser(
        "check-editability",
        help=(
            "Validate a saved editability report against its nonce and hash chain. This is the "
            "gate: it cannot pass a report that asserts more than the run performed."
        ),
    )
    check_editability.add_argument(
        "--rebuild-record", required=True, help="Path to the saved rebuild report."
    )
    check_editability.add_argument(
        "--editability-report", required=True, help="Path to the saved editability report."
    )
    check_editability.add_argument(
        "--editability-nonce",
        required=True,
        help="The nonce emit-mesh-editability printed for the script that produced this report.",
    )
    check_editability.set_defaults(handler=_cmd_check_editability)

    coverage = subparsers.add_parser(
        "reconstruction-coverage",
        help=(
            "Compose the fit record, the program, the rebuild report and the editability verdict "
            "into one account of what was reconstructed and what was not, with the label "
            "parametric-full, parametric-partial or reconstruction-refused."
        ),
    )
    coverage.add_argument("program")
    coverage.add_argument(
        "--fit-record",
        help=(
            "Path to the saved fit record. Optional, and its absence is reported rather than "
            "read as full coverage."
        ),
    )
    coverage.add_argument(
        "--rebuild-report",
        help="Path to the saved rebuild report. Without it nothing has been built and the label says so.",
    )
    coverage.add_argument(
        "--editability-verdict", help="Path to the saved check-editability verdict."
    )
    coverage.add_argument("-o", "--output")
    coverage.set_defaults(handler=_cmd_reconstruction_coverage)

    replan = subparsers.add_parser(
        "replan-without",
        help=(
            "Move the archetype a rebuild refusal named into unreconstructed and re-hash the "
            "program, so a second emission run is one explicit, recorded command away."
        ),
    )
    replan.add_argument("program")
    replan.add_argument(
        "--refusal", required=True, help="Path to the saved refusal report from the rebuild run."
    )
    replan.add_argument("-o", "--output")
    replan.set_defaults(handler=_cmd_replan_without)

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

    fit = subparsers.add_parser(
        "fit-regions",
        help=(
            "Detect analytic primitives in a hash-bound mesh dump and print the fit record: regions, "
            "their disproof-gated fits with per-parameter uncertainty, unclaimed area, and the "
            "measured noise and feature-size budget. Needs no Fusion."
        ),
    )
    fit.add_argument("dump", help="Path to the mesh dump the extraction transaction wrote.")
    fit.add_argument(
        "--dump-sha256",
        required=True,
        help="The SHA-256 the extraction report recorded; the reader refuses bytes that do not match it.",
    )
    fit.add_argument(
        "--spec",
        required=True,
        help=(
            "Path to the detection spec JSON. Every threshold is an object with a value and a "
            "rationale; a threshold without a rationale is rejected."
        ),
    )
    fit.add_argument("-o", "--output")
    fit.set_defaults(handler=_cmd_fit_regions)

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
