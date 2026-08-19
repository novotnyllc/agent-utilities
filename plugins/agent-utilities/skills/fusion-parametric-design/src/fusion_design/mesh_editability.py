"""U5: proving the rebuild is editable, rather than asserting it.

``design.designType == ParametricDesignType`` proves nothing.  It is true of a
document holding one faceted body and no timeline at all, and the word
``designType`` therefore appears nowhere in the source this module emits — a
string-search test enforces that.

What proves editability is a measurement: change one parameter, recompute, watch
a **declared observable** move, restore it, recompute, and watch the model come
back.  The observable is declared per parameter because volume alone is the
wrong instrument.  A hole-position or plane-offset parameter can move a whole
feature through the body while preserving volume to within noise; a volume-only
inertness test would call it dead and fail a correct model.  So each parameter's
spec names ``volume``, ``centroid`` or ``bbox``, with the reason, and the proof
asserts against that one.  The other two are recorded as evidence and asserted
against nothing.

A failure names **which parameter broke which feature**, by the feature's own
deterministic name, because "the rebuild broke" is not actionable and this
report exists to be acted on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .manifest import ManifestValidationError, ValidationIssue, _reject_unknown_fields
from .reconstruction_program import OBSERVABLES, _declared_number

if TYPE_CHECKING:
    from .manifest import Manifest


EDITABILITY_SPEC_FIELDS = {"parameters", "observable_restore_epsilon", "rationale"}

PARAMETER_SPEC_FIELDS = {
    "name",
    "exercise",
    "perturbation",
    "expected_observable",
    "min_observable_change",
    "expected_direction",
    "rationale",
}

RESTORE_EPSILON_FIELDS = {"volume_mm3", "centroid_mm", "bbox_mm"}

DIRECTIONS = {"increase", "decrease"}

# Every way this proof can fail, named. A verdict outside this set is a verdict
# nobody can write a handler for.
EDITABILITY_FAILURES = {
    "editability-capability",
    "rebuild-record-mismatch",
    "parameter-inert",
    "parameter-effect-reversed",
    "parameter-broke-rebuild",
    "parameter-not-restorable",
    "body-count-changed",
    "base-feature-detected",
    "document-changed",
}


def _declared_signed(issues: list[ValidationIssue], raw: Any, path: str) -> float | None:
    """A declared value that may be negative.

    ``_declared_number`` insists on a positive value, which is right for a
    tolerance and wrong for a perturbation: a plane offset's perturbed value is
    routinely negative, and refusing it would make the one parameter class this
    design exists to prove -- position -- unprovable.
    """
    if not isinstance(raw, dict):
        issues.append(
            ValidationIssue(
                "threshold-must-be-declared",
                path,
                "Every declared value is an object with a value and the rationale for it.",
            )
        )
        return None
    _reject_unknown_fields(issues, raw, {"value", "rationale"}, path)
    value = raw.get("value")
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or value != value
        or value in (float("inf"), float("-inf"))
    ):
        issues.append(
            ValidationIssue(
                "threshold-invalid-value",
                f"{path}.value",
                "value must be a finite number. It may be negative: a position parameter's "
                "perturbed value routinely is.",
            )
        )
        value = None
    rationale = raw.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        issues.append(
            ValidationIssue(
                "threshold-missing-rationale",
                f"{path}.rationale",
                "State why this is the right perturbation for this parameter.",
            )
        )
    return None if value is None else float(value)


def _observable_unit(observable: str) -> str:
    return {"volume": "mm3", "centroid": "mm", "bbox": "mm"}[observable]


def validate_editability_spec(spec: Any, parameters_declared: Any = ()) -> list[ValidationIssue]:
    """Validate the caller's declared perturbations, including their arithmetic.

    ``parameters_declared`` is the rebuild record's own parameter list — either
    plain names or the full rows, in which case the nominal value is checked too.
    Every one of them must appear in the spec: either exercised, or explicitly
    declared ``exercise: false`` with a reason.  Silence is not an option: a
    parameter nobody mentioned would be a parameter nobody proved and nobody
    noticed.
    """
    nominals: dict[str, float] = {}
    declared_names: list[str] = []
    for entry in parameters_declared:
        if isinstance(entry, str):
            declared_names.append(entry)
            continue
        declared_names.append(str(entry["name"]))
        if isinstance(entry.get("nominal"), (int, float)) and not isinstance(
            entry.get("nominal"), bool
        ):
            nominals[str(entry["name"])] = float(entry["nominal"])
    issues: list[ValidationIssue] = []
    if not isinstance(spec, dict):
        return [
            ValidationIssue(
                "editability-spec-must-be-object",
                "editability_spec",
                "An editability spec must be an object.",
            )
        ]
    _reject_unknown_fields(issues, spec, EDITABILITY_SPEC_FIELDS, "editability_spec")

    epsilon = spec.get("observable_restore_epsilon")
    if not isinstance(epsilon, dict):
        issues.append(
            ValidationIssue(
                "editability-spec-invalid-epsilon",
                "editability_spec.observable_restore_epsilon",
                "Declare the noise floor each observable is allowed to return within. It is "
                "caller-declared precisely because the physicalProperties noise floor is not "
                "knowable offline.",
            )
        )
        epsilon = {}
    else:
        _reject_unknown_fields(
            issues,
            epsilon,
            RESTORE_EPSILON_FIELDS,
            "editability_spec.observable_restore_epsilon",
        )
        for field in sorted(RESTORE_EPSILON_FIELDS):
            _declared_number(
                issues,
                epsilon.get(field),
                f"editability_spec.observable_restore_epsilon.{field}",
            )

    rationale = spec.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        issues.append(
            ValidationIssue(
                "editability-spec-invalid-rationale",
                "editability_spec.rationale",
                "Record why these perturbations and this noise floor are right for this model.",
            )
        )

    parameters = spec.get("parameters")
    if not isinstance(parameters, list) or not parameters:
        issues.append(
            ValidationIssue(
                "editability-spec-invalid-parameters",
                "editability_spec.parameters",
                "parameters must be a non-empty array; a proof that exercises nothing proves nothing.",
            )
        )
        return issues

    named: list[str] = []
    for index, entry in enumerate(parameters):
        path = f"editability_spec.parameters[{index}]"
        if not isinstance(entry, dict):
            issues.append(
                ValidationIssue(
                    "editability-spec-invalid-parameters", path, "Each parameter spec is an object."
                )
            )
            continue
        _reject_unknown_fields(issues, entry, PARAMETER_SPEC_FIELDS, path)
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            issues.append(
                ValidationIssue(
                    "editability-spec-invalid-parameters",
                    f"{path}.name",
                    "Name the user parameter this entry perturbs.",
                )
            )
        else:
            named.append(name)
        entry_rationale = entry.get("rationale")
        if not isinstance(entry_rationale, str) or not entry_rationale.strip():
            issues.append(
                ValidationIssue(
                    "editability-spec-invalid-parameters",
                    f"{path}.rationale",
                    "Every perturbation carries the reason it is the right size for this parameter.",
                )
            )
        if entry.get("exercise") is False:
            # Deliberately unexercised is a decision, recorded as one. It lands
            # in `not_exercised` and the report never counts it as proven.
            continue
        observable = entry.get("expected_observable")
        if observable not in OBSERVABLES:
            issues.append(
                ValidationIssue(
                    "editability-spec-invalid-parameters",
                    f"{path}.expected_observable",
                    "expected_observable must be one of "
                    + ", ".join(sorted(OBSERVABLES))
                    + "; volume alone would report a correct position parameter as inert, which is "
                    "the over-claim this field exists to prevent.",
                )
            )
            observable = None
        perturbed = _declared_signed(issues, entry.get("perturbation"), f"{path}.perturbation")
        nominal = nominals.get(str(name))
        if perturbed is not None and nominal is not None and perturbed == nominal:
            issues.append(
                ValidationIssue(
                    "editability-spec-no-op",
                    f"{path}.perturbation",
                    f"The perturbed value equals the parameter's own nominal ({nominal:g}), so this "
                    "entry would set the parameter to what it already is and then report that "
                    "nothing moved. That is a silent no-op dressed as a proof.",
                )
            )
        _declared_number(issues, entry.get("min_observable_change"), f"{path}.min_observable_change")
        direction = entry.get("expected_direction")
        if direction is not None and direction not in DIRECTIONS:
            issues.append(
                ValidationIssue(
                    "editability-spec-invalid-parameters",
                    f"{path}.expected_direction",
                    "expected_direction, when declared, must be 'increase' or 'decrease'. Leave it "
                    "out when the sign is not known in advance rather than guessing one.",
                )
            )
        if observable is None:
            continue
        change = entry.get("min_observable_change")
        floor_key = {"volume": "volume_mm3", "centroid": "centroid_mm", "bbox": "bbox_mm"}[observable]
        floor = epsilon.get(floor_key)
        if (
            isinstance(change, dict)
            and isinstance(change.get("value"), (int, float))
            and isinstance(floor, dict)
            and isinstance(floor.get("value"), (int, float))
            and float(change["value"]) <= float(floor["value"])
        ):
            issues.append(
                ValidationIssue(
                    "editability-spec-unmeasurable",
                    f"{path}.min_observable_change",
                    f"A change of {float(change['value']):g} {_observable_unit(observable)} is not "
                    f"larger than the {float(floor['value']):g} this spec is willing to call noise "
                    "on restore. You cannot assert a movement smaller than the noise you tolerate.",
                )
            )

    if not any(entry.get("exercise") is not False for entry in parameters if isinstance(entry, dict)):
        issues.append(
            ValidationIssue(
                "editability-spec-exercises-nothing",
                "editability_spec.parameters",
                "Every entry declares exercise: false, so this run would perturb nothing and then "
                "report ok. A proof that exercises nothing proves nothing, and a gate that passes "
                "it fails open.",
            )
        )

    if declared_names:
        missing = sorted(set(declared_names) - set(named))
        unknown = sorted(set(named) - set(declared_names))
        if missing:
            issues.append(
                ValidationIssue(
                    "editability-spec-incomplete",
                    "editability_spec.parameters",
                    "The rebuild created these parameters and the spec does not mention them: "
                    + ", ".join(missing)
                    + ". Declare a perturbation, or declare exercise: false with the reason; a "
                    "parameter nobody mentioned is a parameter nobody proved and nobody noticed.",
                )
            )
        if unknown:
            issues.append(
                ValidationIssue(
                    "editability-spec-unknown-parameter",
                    "editability_spec.parameters",
                    "The spec names parameters the rebuild record does not contain: "
                    + ", ".join(unknown),
                )
            )
    return issues


def _rebuild_binding(record: Any) -> dict[str, Any]:
    """Pull the census U5 refuses to run without out of the U4 report."""
    if not isinstance(record, dict):
        raise ValueError("The rebuild record must be the JSON report the rebuild transaction wrote.")
    if record.get("kind") != "mesh-rebuild":
        raise ValueError("The rebuild record must be a mesh-rebuild report.")
    if record.get("ok") is not True or record.get("failures"):
        raise ValueError(
            "Refusing to prove the editability of a rebuild that did not succeed; its report "
            f"carries failures {record.get('failures')!r}."
        )
    nonce = record.get("rebuild_nonce")
    if not isinstance(nonce, str) or not nonce:
        raise ValueError("The rebuild record carries no nonce, so nothing binds it to an emission.")
    features = [
        {
            "feature_name": entry["feature_name"],
            "archetype_id": entry["archetype_id"],
            "token": entry.get("token"),
        }
        for entry in record.get("created") or ()
        if entry.get("kind") in ("sketch-extrude", "revolve")
    ]
    if not features:
        raise ValueError("The rebuild record names no features, so there is nothing to perturb.")
    return {
        "component_name": record["component_name"],
        "rebuild_nonce": nonce,
        "dump_sha256": record["dump_sha256"],
        "program_sha256": record["program_sha256"],
        "manifest_sha256": record["manifest_sha256"],
        "features": features,
        "parameters": [
            {
                "name": row["name"],
                "expression": row["expression"],
                "unit": row["unit"],
                "nominal": row["nominal"],
                "expected_observable": row["expected_observable"],
                "driving_archetypes": row["driving_archetypes"],
            }
            for row in record.get("user_parameters") or ()
        ],
        "body_count": len(record.get("bodies") or ()),
    }


def emit_mesh_editability_script(
    manifest: "Manifest", rebuild_record: Any, spec: Any, nonce: str
) -> str:
    """Emit the perturbation proof."""
    from .scripts import _json_literal, _script_prelude

    binding = _rebuild_binding(rebuild_record)
    issues = validate_editability_spec(spec, binding["parameters"])
    if issues:
        raise ManifestValidationError(issues)
    if not isinstance(nonce, str) or len(nonce) < 16:
        raise ValueError("The editability nonce must be minted by the CLI, not derived from a file.")

    payload = {
        "binding": binding,
        "nonce": nonce,
        "observable_restore_epsilon": {
            key: dict(value) for key, value in spec["observable_restore_epsilon"].items()
        },
        "rationale": str(spec["rationale"]).strip(),
        "parameters": [dict(entry) for entry in spec["parameters"]],
    }
    return _script_prelude(manifest) + _EDITABILITY_TRANSACTION.replace(
        "__EDITABILITY_SPEC__", _json_literal(payload)
    )


# --------------------------------------------------------------------------
# the host-side report validator
# --------------------------------------------------------------------------


def validate_editability_report(
    report: Any, *, nonce: str, rebuild_record: Any
) -> dict[str, Any]:
    """Refuse a report that asserts more than it ran. Offline, and the gate.

    This is the function an orchestrating agent calls.  It cannot be satisfied by
    a hand-written six-line JSON file: the nonce exists only inside the source
    this emission generated, and the hash chain binds the report to the manifest,
    the dump, the program and the rebuild that produced it.
    """
    binding = _rebuild_binding(rebuild_record)
    problems: list[str] = []
    if not isinstance(report, dict):
        return {"ok": False, "problems": ["the editability report is not a JSON object"]}
    if report.get("kind") != "mesh-editability":
        problems.append("the report is not a mesh-editability report")
    if report.get("editability_nonce") != nonce:
        problems.append(
            "the report's nonce does not match the one emit-mesh-editability minted; bind the "
            "verdict to a report produced by running that exact script"
        )
    for field in ("dump_sha256", "program_sha256", "manifest_sha256", "rebuild_nonce"):
        if report.get(field) != binding[field]:
            problems.append(f"{field} does not match the rebuild record")

    checked = report.get("checked")
    declared = {row["name"] for row in binding["parameters"]}
    if not isinstance(checked, list):
        problems.append("checked must be the list of parameters the loop actually completed")
        checked = []
    extra = sorted(set(checked) - declared)
    if extra:
        problems.append(
            "checked names parameters the rebuild never created: " + ", ".join(extra)
        )
    if len(set(checked)) != len(checked):
        problems.append("checked repeats a parameter")

    # The nonce proves the report came from the emitted script. It does not
    # prove any individual name in `checked` earned its place, so every one is
    # re-derived from the row that recorded the measurement.
    rows = report.get("parameters") if isinstance(report.get("parameters"), list) else []
    by_name = {
        row.get("name"): row for row in rows if isinstance(row, dict) and row.get("name")
    }
    for name in checked:
        row = by_name.get(name)
        if row is None:
            problems.append(f"checked names {name!r} and the report carries no measurement for it")
            continue
        if row.get("exercised") is not True:
            problems.append(f"checked names {name!r}, whose row says it was not exercised")
        if row.get("failure"):
            problems.append(
                f"checked names {name!r}, whose row records failure {row['failure']!r}"
            )
        if not isinstance(row.get("restore_gap"), dict):
            problems.append(
                f"checked names {name!r} and its row carries no restore measurement, so the "
                "model was never shown to come back"
            )
        if not isinstance(row.get("measured_change"), (int, float)):
            problems.append(
                f"checked names {name!r} and its row carries no measured observable change"
            )

    for field in ("not_exercised", "failures", "parameters"):
        if not isinstance(report.get(field), list):
            problems.append(f"the report carries no {field} list")
    if report.get("interactions_exercised") is not False:
        problems.append(
            "interactions_exercised must be present and false: this loop perturbs one parameter at "
            "a time and must say so"
        )
    failures = report.get("failures") if isinstance(report.get("failures"), list) else []
    unknown = sorted(set(failures) - EDITABILITY_FAILURES)
    if unknown:
        problems.append("the report names failures outside the closed vocabulary: " + ", ".join(unknown))
    if failures and report.get("ok") is True:
        problems.append("the report claims ok with failures recorded")

    unproven = sorted(
        declared - set(checked) - {name for name in report.get("not_exercised") or () if isinstance(name, str)}
    )
    if unproven and not failures:
        problems.append(
            "these parameters are neither proven nor listed not_exercised, and the report claims no "
            "failure: " + ", ".join(unproven)
        )
    return {
        "ok": not problems and report.get("ok") is True,
        "problems": problems,
        "checked": sorted(set(checked)),
        "not_exercised": sorted(
            name for name in report.get("not_exercised") or () if isinstance(name, str)
        ),
        "failures": sorted(set(failures)),
        "proves": (
            "Each parameter in `checked` was set to a perturbed value, the model recomputed, its "
            "declared observable moved by at least the declared minimum, the parameter was restored, "
            "the model recomputed again and all three observables returned within the declared "
            "epsilon. Nothing else is proven: parameters were perturbed one at a time, so no "
            "interaction between them was exercised, and entity token resolution is reported as a "
            "per-run measurement, not a guarantee."
        ),
    }


_EDITABILITY_TRANSACTION = '''SPEC = json.loads(__EDITABILITY_SPEC__)

_MISSING = object()

# A base feature holds imported geometry, so a body backed by one is a faceted
# import wearing a timeline -- exactly the thing this proof exists to
# distinguish. The check is a ban rather than an allow-list on purpose: the
# timeline is document-wide, so a legitimate feature the user added elsewhere
# would fail an allow-list and that would be a false failure, not a finding.
# Every type present is reported as evidence either way.
BANNED_FEATURE_TYPE = "adsk::fusion::BaseFeature"


class Failed(RuntimeError):
    def __init__(self, token, message, detail=None):
        RuntimeError.__init__(self, token + ": " + message)
        self.token = token
        self.message = message
        self.detail = detail or {}


def _probe(owner, name, missing, label):
    """Read an API member, or record it missing. Never defaults."""
    value = getattr(owner, name, _MISSING)
    if value is _MISSING or value is None:
        missing.append(label)
        return None
    return value


def _recorded(owner, name, default=None):
    """Read a member for the *record only*; its result is compared against nothing."""
    value = getattr(owner, name, _MISSING)
    return default if value is _MISSING else value


def _find_component(design, name):
    root = design.rootComponent
    occurrences = root.allOccurrences
    for index in range(occurrences.count):
        occurrence = occurrences.item(index)
        if occurrence.component.name == name:
            return occurrence.component
    return None


def _observables(component, accuracy):
    """Volume, centroid and bounding box of every body in the component.

    All three are measured every time. Only the parameter's declared one is
    asserted against; the other two are recorded, because evidence without an
    assertion is still evidence and an assertion without a declaration is an
    over-claim.
    """
    bodies = component.bRepBodies
    volume = 0.0
    moment = [0.0, 0.0, 0.0]
    low = [None, None, None]
    high = [None, None, None]
    for index in range(bodies.count):
        body = bodies.item(index)
        properties = body.physicalProperties(accuracy)
        body_volume = float(properties.volume) * 1000.0
        centre = properties.centerOfMass
        volume += body_volume
        for axis, value in enumerate((centre.x, centre.y, centre.z)):
            moment[axis] += value * 10.0 * body_volume
        box = body.boundingBox
        for axis, value in enumerate((box.minPoint.x, box.minPoint.y, box.minPoint.z)):
            scaled = value * 10.0
            low[axis] = scaled if low[axis] is None else min(low[axis], scaled)
        for axis, value in enumerate((box.maxPoint.x, box.maxPoint.y, box.maxPoint.z)):
            scaled = value * 10.0
            high[axis] = scaled if high[axis] is None else max(high[axis], scaled)
    centroid = [0.0, 0.0, 0.0] if volume <= 0.0 else [value / volume for value in moment]
    extent = [
        0.0 if low[axis] is None else high[axis] - low[axis] for axis in range(3)
    ]
    return {
        "body_count": bodies.count,
        "volume_mm3": volume,
        "centroid_mm": centroid,
        "bbox_extent_mm": extent,
    }


def _distance(a, b):
    return sum((first - second) ** 2 for first, second in zip(a, b)) ** 0.5


def _movement(observable, before, after):
    """How far the declared observable moved, signed where a sign exists.

    Centroid displacement is a distance and has no sign, which is why a
    centroid parameter cannot declare an expected direction and the spec
    validator does not invent one for it.
    """
    if observable == "volume":
        return after["volume_mm3"] - before["volume_mm3"]
    if observable == "centroid":
        return _distance(after["centroid_mm"], before["centroid_mm"])
    changes = [
        after["bbox_extent_mm"][axis] - before["bbox_extent_mm"][axis] for axis in range(3)
    ]
    return max(changes, key=abs)


def _restore_gap(before, after):
    """The worst of the three observables' distance from baseline."""
    return {
        "volume_mm3": abs(after["volume_mm3"] - before["volume_mm3"]),
        "centroid_mm": _distance(after["centroid_mm"], before["centroid_mm"]),
        "bbox_mm": max(
            abs(after["bbox_extent_mm"][axis] - before["bbox_extent_mm"][axis])
            for axis in range(3)
        ),
    }


def _unhealthy(design):
    """Every timeline entry the design currently reports unwell, by index.

    Keyed by index and not by name: an entry with no readable name still counts.
    Dropping it would turn "this API does not expose a name" into "nothing broke
    here", which is the fail-open shape this whole file is written against.
    """
    healthy = str(adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState)
    rows = {}
    for index in range(design.timeline.count):
        item = design.timeline.item(index)
        if str(item.healthState) == healthy:
            continue
        entity = item.entity
        rows[index] = {
            "name": _recorded(entity, "name"),
            "message": _recorded(entity, "errorOrWarningMessage", ""),
        }
    return rows


def _newly_broken(design, feature_names, baseline_unhealthy):
    """What this perturbation broke, as distinct from what was already broken.

    Blaming a parameter for damage that predates it is as wrong as missing the
    damage it caused, so the comparison is against a baseline taken before the
    expression changed.
    """
    health = _timeline_health(design)
    current = _unhealthy(design)
    known = set(feature_names)
    broken = []
    unattributable = 0
    messages = []
    for index, row in current.items():
        if index in baseline_unhealthy:
            continue
        if row["message"]:
            messages.append(str(row["message"]))
        name = row["name"]
        if name is not None and str(name) in known:
            broken.append(str(name))
        else:
            # Something this perturbation broke that cannot be named. It still
            # counts as broken; it just cannot be attributed to a feature.
            unattributable += 1
    return health, sorted(set(broken)), unattributable, messages


def _resolve_tokens(design, tokens):
    """Re-resolve recorded entity tokens. A measurement, never a premise."""
    resolved = []
    unresolved = []
    for token in tokens:
        try:
            found = design.findEntityByToken(token)
        except Exception:
            found = None
        if found:
            resolved.append(token)
        else:
            unresolved.append(token)
    return {"resolved": len(resolved), "unresolved": len(unresolved), "unresolved_tokens": unresolved}


def run(context):
    report_attempted = False
    binding = SPEC["binding"]
    epsilon = SPEC["observable_restore_epsilon"]
    report = {
        "kind": "mesh-editability",
        "ok": False,
        "project": PROJECT_NAME,
        "manifest_sha256": MANIFEST_SHA256,
        "editability_nonce": SPEC["nonce"],
        "rebuild_nonce": binding["rebuild_nonce"],
        "dump_sha256": binding["dump_sha256"],
        "program_sha256": binding["program_sha256"],
        "component_name": binding["component_name"],
        "declared_restore_epsilon": epsilon,
        "spec_rationale": SPEC["rationale"],
        "checked": [],
        "not_exercised": [],
        "parameters": [],
        "failures": [],
        "interactions_exercised": False,
        "interactions_note": (
            "Parameters were perturbed one at a time. No interaction between two parameters was "
            "exercised by this run, and none is claimed."
        ),
    }
    try:
        app, design = _active_design()
        target_document = _require_target_document(app)
        _pump_events(app, design, target_document)
        report["fusion_version"] = _recorded(app, "version")

        missing = []
        accuracy_enum = _probe(
            adsk.fusion, "CalculationAccuracy", missing, "adsk.fusion.CalculationAccuracy"
        )
        accuracy = None
        if accuracy_enum is not None:
            accuracy = _probe(
                accuracy_enum,
                "VeryHighCalculationAccuracy",
                missing,
                "adsk.fusion.CalculationAccuracy.VeryHighCalculationAccuracy",
            )
        user_parameters = _probe(design, "userParameters", missing, "Design.userParameters")
        _probe(design, "computeAll", missing, "Design.computeAll")
        _probe(design, "findEntityByToken", missing, "Design.findEntityByToken")
        if missing:
            raise Failed(
                "editability-capability",
                "this Fusion does not expose what the proof needs: " + ", ".join(missing),
                {"missing": missing},
            )

        component = _find_component(design, binding["component_name"])
        if component is None:
            raise Failed(
                "rebuild-record-mismatch",
                "the document holds no component named " + repr(binding["component_name"]) + ".",
                {"component_name": binding["component_name"]},
            )

        feature_names = [entry["feature_name"] for entry in binding["features"]]
        present = []
        for index in range(design.timeline.count):
            name = getattr(design.timeline.item(index).entity, "name", _MISSING)
            if name is not _MISSING and name is not None:
                present.append(str(name))
        absent = sorted(set(feature_names) - set(present))
        if absent:
            raise Failed(
                "rebuild-record-mismatch",
                "the rebuild record names features the timeline does not contain: "
                + ", ".join(absent),
                {"missing_features": absent},
            )

        parameter_handles = {}
        for index in range(user_parameters.count):
            handle = user_parameters.item(index)
            parameter_handles[handle.name] = handle
        units = {row["name"]: row["unit"] for row in binding["parameters"]}
        recorded = {row["name"]: row["expression"] for row in binding["parameters"]}
        drifted = sorted(
            name
            for name, expression in recorded.items()
            if name not in parameter_handles or parameter_handles[name].expression != expression
        )
        if drifted:
            raise Failed(
                "rebuild-record-mismatch",
                "these parameters are missing or no longer carry the expression the rebuild "
                "recorded: " + ", ".join(drifted),
                {"parameters": drifted},
            )

        # The base-feature check runs before any perturbation: a body backed by
        # imported geometry is not made editable by surviving a recompute.
        timeline_types = []
        for index in range(design.timeline.count):
            entity = design.timeline.item(index).entity
            timeline_types.append(str(_recorded(entity, "objectType", "")))
        report["timeline_feature_types"] = sorted(set(timeline_types))
        if BANNED_FEATURE_TYPE in timeline_types:
            raise Failed(
                "base-feature-detected",
                "the timeline contains a base feature, so at least one body here is imported "
                "geometry rather than a feature this rebuild constructed.",
                {"timeline_feature_types": sorted(set(timeline_types))},
            )

        # The observables are the whole instrument. A missing property here must
        # refuse by name, never read as "the model did not move".
        component_bodies = component.bRepBodies
        if component_bodies.count:
            sample = component_bodies.item(0)
            _probe(sample, "physicalProperties", missing, "BRepBody.physicalProperties")
            _probe(sample, "boundingBox", missing, "BRepBody.boundingBox")
        if missing:
            raise Failed(
                "editability-capability",
                "this Fusion does not expose what the proof measures: " + ", ".join(missing),
                {"missing": missing},
            )

        tokens = [
            entry["token"]
            for entry in binding["features"]
            if entry.get("token")
        ]
        baseline = _observables(component, accuracy)
        report["baseline"] = baseline
        if baseline["body_count"] != binding["body_count"]:
            raise Failed(
                "rebuild-record-mismatch",
                "the component holds "
                + str(baseline["body_count"])
                + " bodies and the rebuild recorded "
                + str(binding["body_count"])
                + ".",
                {"body_count": baseline["body_count"]},
            )

        specs = SPEC["parameters"]
        aborted_at = None
        for position, entry in enumerate(specs):
            name = entry["name"]
            if aborted_at is not None:
                report["not_exercised"].append(name)
                continue
            if entry.get("exercise") is False:
                report["not_exercised"].append(name)
                report["parameters"].append(
                    {
                        "name": name,
                        "exercised": False,
                        "rationale": entry["rationale"],
                    }
                )
                continue

            handle = parameter_handles[name]
            original = handle.expression
            observable = entry["expected_observable"]
            minimum = float(entry["min_observable_change"]["value"])
            perturbation = float(entry["perturbation"]["value"])
            row = {
                "name": name,
                "exercised": True,
                "expected_observable": observable,
                "declared_min_change": minimum,
                "perturbation": perturbation,
                "original_expression": original,
                "rationale": entry["rationale"],
            }

            before = _observables(component, accuracy)
            baseline_unhealthy = _unhealthy(design)
            # The perturbed value carries the parameter's own declared unit, so
            # the expression means the same thing the rebuild meant by it.
            perturbed_expression = repr(perturbation) + " " + units[name]
            row["perturbed_expression"] = perturbed_expression
            broke = None
            try:
                handle.expression = perturbed_expression
                design.computeAll()
                _pump_events(app, design, target_document)
            except DocumentChangedError:
                raise
            except Exception as error:
                broke = str(error)
            health, broken_features, unattributable, messages = _newly_broken(
                design, feature_names, baseline_unhealthy
            )
            if broke is None and (broken_features or unattributable):
                broke = "; ".join(messages) or "the timeline reports new unhealthy items"
            if broke is not None:
                row["failure"] = "parameter-broke-rebuild"
                row["broken_features"] = broken_features
                row["unattributable_unhealthy"] = unattributable
                row["messages"] = messages
                row["error"] = broke
                report["failures"].append("parameter-broke-rebuild")
                report["parameters"].append(row)
                _restore(handle, original, design, app, target_document, report, row,
                         component, accuracy, baseline, epsilon, baseline_unhealthy)
                if row.get("restore_failure"):
                    aborted_at = name
                continue

            after = _observables(component, accuracy)
            row["observables_before"] = before
            row["observables_after"] = after
            movement = _movement(observable, before, after)
            row["measured_change"] = movement
            row["timeline"] = health
            if after["body_count"] != before["body_count"]:
                row["failure"] = "body-count-changed"
                report["failures"].append("body-count-changed")
            elif abs(movement) < minimum:
                row["failure"] = "parameter-inert"
                report["failures"].append("parameter-inert")
            elif entry.get("expected_direction") == "increase" and movement <= 0.0:
                row["failure"] = "parameter-effect-reversed"
                report["failures"].append("parameter-effect-reversed")
            elif entry.get("expected_direction") == "decrease" and movement >= 0.0:
                row["failure"] = "parameter-effect-reversed"
                report["failures"].append("parameter-effect-reversed")

            _restore(handle, original, design, app, target_document, report, row,
                     component, accuracy, baseline, epsilon, baseline_unhealthy)
            row["entity_tokens"] = _resolve_tokens(design, tokens)
            report["parameters"].append(row)
            if row.get("restore_failure"):
                aborted_at = name
                continue
            if row.get("failure"):
                continue
            # Only now: perturb, assert, restore and assert all completed.
            report["checked"].append(name)

        if aborted_at is not None:
            report["aborted_at"] = aborted_at
            report["abort_note"] = (
                "The loop stopped after " + aborted_at + " could not be restored. Every parameter "
                "after it is listed not_exercised and is unproven."
            )
        report["ok"] = not report["failures"]
        report["failures"] = sorted(set(report["failures"]))
        report_attempted = True
        _emit(report)
        if not report["ok"]:
            raise RuntimeError(
                "Editability proof failed: " + ", ".join(report["failures"])
            )
        return
    except Exception as error:
        if not report_attempted:
            token = _recorded(error, "token")
            if isinstance(error, DocumentChangedError):
                token = "document-changed"
            if token:
                report["failures"] = sorted(set(report["failures"] + [token]))
            report["error"] = str(error)
            report["refusal_detail"] = _recorded(error, "detail", {})
            report["traceback"] = traceback.format_exc()
            report["ok"] = False
            report_attempted = True
            _emit(report)
        raise


def _restore(handle, original, design, app, target_document, report, row, component, accuracy,
             baseline, epsilon, baseline_unhealthy):
    """Put the parameter back, recompute, and check the model actually returned.

    Returning means two things and both are checked: the observables come back
    within the declared epsilon, *and* the timeline is no sicker than it was
    before the perturbation. A model that is still broken after the expression
    goes back has not returned, whatever its volume says.
    """
    try:
        handle.expression = original
        design.computeAll()
        _pump_events(app, design, target_document)
    except DocumentChangedError:
        raise
    except Exception as error:
        _record_restore_failure(row, report)
        row["restore_error"] = str(error)
        return
    still_broken = [
        index for index in _unhealthy(design) if index not in baseline_unhealthy
    ]
    if still_broken:
        _record_restore_failure(row, report)
        row["restore_timeline_still_unhealthy"] = len(still_broken)
        return
    restored = _observables(component, accuracy)
    gap = _restore_gap(baseline, restored)
    row["restore_gap"] = gap
    beyond = [
        key
        for key in ("volume_mm3", "centroid_mm", "bbox_mm")
        if gap[key] > float(epsilon[key]["value"])
    ]
    if beyond:
        _record_restore_failure(row, report)
        row["restore_beyond_epsilon"] = beyond


def _record_restore_failure(row, report):
    """Record the restore failure without erasing the failure it followed.

    A parameter that broke the rebuild and then would not restore is two
    findings, and the per-parameter row is where the attribution lives -- so the
    first failure keeps `failure` and the restore gets its own field.
    """
    row["restore_failure"] = "parameter-not-restorable"
    if not row.get("failure"):
        row["failure"] = "parameter-not-restorable"
    report["failures"].append("parameter-not-restorable")
'''
