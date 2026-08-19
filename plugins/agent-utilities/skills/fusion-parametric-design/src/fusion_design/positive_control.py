from __future__ import annotations

import math
import re

from .manifest import Manifest


_BOX_SPECS = (
    {
        "path": "00_REFERENCES/PACK__PD_TRIGGER__EXACT_OR_CONSERVATIVE",
        "body_name": "POSITIVE_CONTROL__PACK_PD_TRIGGER",
        "size_parameters": ["src_pd_board_length", "src_pd_board_width", "src_pd_board_height"],
        "origin_mm": [0.0, 0.0, 0.0],
    },
    {
        "path": "00_REFERENCES/PACK__EKYLIN__EXACT_OR_CONSERVATIVE",
        "body_name": "POSITIVE_CONTROL__PACK_EKYLIN",
        "size_parameters": ["src_ekylin_length", "src_ekylin_width", "src_ekylin_height"],
        "origin_mm": [120.0, 0.0, 0.0],
    },
    {
        "path": "00_REFERENCES/KEEP__USB_C_INSERTION",
        "body_name": "POSITIVE_CONTROL__KEEP_USB_C_INSERTION",
        "size_mm": [20.0, 20.0, 5.0],
        "origin_mm": [0.0, 0.0, 0.0],
    },
    {
        "path": "00_REFERENCES/KEEP__EKYLIN_WIRE_BENDS",
        "body_name": "POSITIVE_CONTROL__KEEP_EKYLIN_WIRE_BENDS",
        "size_mm": [20.0, 20.0, 5.0],
        "origin_mm": [120.0, 0.0, 0.0],
    },
    {
        "path": "10_PRODUCT/PROD__BASE",
        "body_name": "POSITIVE_CONTROL__PROD_BASE",
        "size_mm": [100.0, 60.0],
        "height_parameter": "fab_wall_thickness",
        "origin_mm": [0.0, 50.0, 0.0],
    },
    {
        "path": "10_PRODUCT/PROD__LID",
        "body_name": "POSITIVE_CONTROL__PROD_LID",
        "size_parameters": ["src_pd_board_length", "src_pd_board_width", "fab_wall_thickness"],
        "origin_mm": [0.0, 0.0, 10.0],
    },
    {
        "path": "90_VALIDATION/VAL__PD_FIT_COUPON",
        "body_name": "POSITIVE_CONTROL__VAL_PD_FIT_COUPON",
        "size_mm": [10.0, 10.0],
        "height_parameter": "fab_wall_thickness",
        "origin_mm": [0.0, 100.0, 0.0],
    },
)


def _parameter_mm(manifest: Manifest, name: str) -> float:
    parameters = {parameter["name"]: parameter for parameter in manifest.parameters}
    parameter = parameters.get(name)
    if not parameter or parameter.get("units") != "mm":
        raise ValueError(f"Electronics-enclosure positive control requires millimeter parameter {name!r}.")
    match = re.fullmatch(r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*mm\s*", str(parameter.get("expression", "")))
    if not match:
        raise ValueError(f"Electronics-enclosure positive control requires a literal millimeter value for {name!r}.")
    value = float(match.group(1))
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"Electronics-enclosure positive control requires a positive value for {name!r}.")
    return value


def _bounds(spec: dict) -> tuple[list[float], list[float]]:
    minimum = [float(value) for value in spec["origin_mm"]]
    maximum = [minimum[index] + float(spec["size_mm"][index]) for index in range(3)]
    return minimum, maximum


def _validate_contract(manifest: Manifest, specs: tuple[dict, ...]) -> None:
    by_path = {spec["path"]: spec for spec in specs}
    verification = manifest.verification
    for path in verification.get("expected_print_parts", []):
        if path not in by_path:
            raise ValueError(f"Positive-control geometry is missing expected print part {path!r}.")

    # Positive-control boxes stand in for the real print parts, so they must
    # satisfy the same declared print-part expectations verification asserts.
    for part in manifest.printable_parts:
        spec = by_path.get(str(part.get("path", "")).strip())
        if not spec:
            continue
        volume = spec["size_mm"][0] * spec["size_mm"][1] * spec["size_mm"][2]
        try:
            minimum = float(part.get("minimum_volume_mm3"))
        except (OverflowError, TypeError, ValueError) as error:
            raise ValueError(
                f"Printable part {spec['path']!r} has no usable minimum_volume_mm3."
            ) from error
        if volume < minimum:
            raise ValueError(
                f"Positive-control box for {spec['path']!r} is {volume} mm3, "
                f"below the declared minimum_volume_mm3 {minimum}."
            )

    for check in verification.get("clearance_checks", []):
        one = by_path.get(check["one"])
        two = by_path.get(check["two"])
        if not one or not two:
            raise ValueError(f"Positive-control geometry is missing clearance check {check['id']!r}.")
        one_min, one_max = _bounds(one)
        two_min, two_max = _bounds(two)
        gaps = [max(two_min[index] - one_max[index], one_min[index] - two_max[index], 0.0) for index in range(3)]
        distance = math.sqrt(sum(gap * gap for gap in gaps))
        try:
            minimum = float(check["minimum_mm"])
        except (OverflowError, TypeError, ValueError) as error:
            raise ValueError(f"Positive-control clearance {check['id']!r} has an invalid minimum.") from error
        if not math.isfinite(minimum) or minimum < 0:
            raise ValueError(f"Positive-control clearance {check['id']!r} has an invalid minimum.")
        if distance + 1e-9 < minimum:
            raise ValueError(
                f"Positive-control clearance {check['id']!r} is {distance} mm, below the manifest minimum."
            )

    for check in verification.get("interference_checks", []):
        one = by_path.get(check["one"])
        two = by_path.get(check["two"])
        if not one or not two:
            raise ValueError(f"Positive-control geometry is missing interference check {check['id']!r}.")
        if check.get("allow_interference", False):
            continue
        one_min, one_max = _bounds(one)
        two_min, two_max = _bounds(two)
        overlaps = [min(one_max[index], two_max[index]) - max(one_min[index], two_min[index]) for index in range(3)]
        if all(overlap > 0 for overlap in overlaps):
            raise ValueError(f"Positive-control geometry violates interference check {check['id']!r}.")


def _box_specs(manifest: Manifest) -> tuple[dict, ...]:
    if manifest.project_name != "wearable-controller-pod" or manifest.fusion_document != "Wearable Controller Pod":
        raise ValueError("Positive-control geometry is only defined for the electronics-enclosure example manifest.")
    required_paths = {spec["path"] for spec in _BOX_SPECS}
    if not required_paths.issubset(manifest.component_tree):
        raise ValueError("Electronics-enclosure positive-control component paths are missing from the manifest.")

    resolved = []
    for template in _BOX_SPECS:
        spec = dict(template)
        parameter_names = spec.pop("size_parameters", None)
        height_parameter = spec.pop("height_parameter", None)
        if parameter_names:
            spec["size_mm"] = [_parameter_mm(manifest, name) for name in parameter_names]
        elif height_parameter:
            spec["size_mm"] = [*spec["size_mm"], _parameter_mm(manifest, height_parameter)]
        resolved.append(spec)
    specs = tuple(resolved)
    _validate_contract(manifest, specs)
    return specs


def emit_positive_control_script(manifest: Manifest) -> str:
    from .scripts import _json_literal, _script_prelude

    transaction = '''BOX_SPECS = json.loads(__BOX_SPECS__)
ATTRIBUTE_GROUP = "fusion_parametric_design"
GEOMETRY_TOLERANCE_MM = 1e-6
IDENTITY_MATRIX = tuple(adsk.core.Matrix3D.create().asArray())


def _attribute_value(component, name):
    attribute = component.attributes.itemByName(ATTRIBUTE_GROUP, name)
    return attribute.value if attribute else None


def _require_scaffold_identity(occurrence, path):
    component = occurrence.component
    if _attribute_value(component, "managed") != "true":
        raise RuntimeError("Positive control requires scaffold identity for " + path + ".")
    if _attribute_value(component, "manifest_sha256") != MANIFEST_SHA256:
        raise RuntimeError("Positive control scaffold manifest identity mismatch for " + path + ".")


def _require_identity_transform(occurrence, path):
    transform = getattr(occurrence, "transform2", None)
    if not transform:
        raise RuntimeError("Positive control requires Occurrence.transform2 for " + path + ".")
    values = tuple(float(value) for value in transform.asArray())
    if len(values) != len(IDENTITY_MATRIX) or any(
        abs(actual - expected) > GEOMETRY_TOLERANCE_MM / 1000.0
        for actual, expected in zip(values, IDENTITY_MATRIX)
    ):
        raise RuntimeError(
            "Positive control requires identity occurrence transforms; "
            + path
            + " is not identity."
        )


def _expected_bounds(spec):
    origin = spec["origin_mm"]
    size = spec["size_mm"]
    return {
        "min": list(origin),
        "max": [origin[index] + size[index] for index in range(3)],
    }


def _validate_geometry(occurrence, spec):
    path = spec["path"]
    _require_identity_transform(occurrence, path)
    bodies = occurrence.component.bRepBodies
    if bodies.count != 1:
        raise RuntimeError(
            "Positive control requires exactly one B-Rep body for "
            + path
            + "; found "
            + str(bodies.count)
            + "."
        )
    body = bodies.item(0)
    if body.name != spec["body_name"]:
        raise RuntimeError(
            "Positive control body name mismatch for "
            + path
            + ": expected "
            + repr(spec["body_name"])
            + ", found "
            + repr(body.name)
            + "."
        )
    volume_mm3 = float(body.volume) * 1000.0
    if not body.isSolid or volume_mm3 <= 1e-9:
        raise RuntimeError("Positive control body is not a positive-volume solid: " + path + ".")
    actual_bounds = _bbox_mm(occurrence)
    expected_bounds = _expected_bounds(spec)
    for bound in ("min", "max"):
        for index, (actual, expected) in enumerate(
            zip(actual_bounds[bound], expected_bounds[bound])
        ):
            if abs(float(actual) - float(expected)) > GEOMETRY_TOLERANCE_MM:
                raise RuntimeError(
                    "Positive control geometry mismatch for "
                    + path
                    + ": expected complete bounds "
                    + repr(expected_bounds)
                    + ", found "
                    + repr(actual_bounds)
                    + "."
                )
    return {
        "path": path,
        "body_name": body.name,
        "expected_bounds_mm": expected_bounds,
        "actual_bounds_mm": actual_bounds,
        "volume_mm3": volume_mm3,
        "is_solid": bool(body.isSolid),
        "ok": True,
    }, body


def _is_valid(entity):
    if not entity:
        return False
    try:
        return bool(entity.isValid)
    except Exception:
        return True


def _cleanup_pair(body, base_feature, editing=False):
    attempts = []
    if editing and base_feature:
        try:
            if not base_feature.finishEdit():
                attempts.append("finishEdit returned false")
        except Exception as error:
            attempts.append("finishEdit failed: " + str(error))
    for label, entity in (("body", body), ("base feature", base_feature)):
        if not entity:
            continue
        try:
            entity.deleteMe()
        except Exception as error:
            attempts.append(label + " delete failed: " + str(error))
    remaining = [label for label, entity in (("body", body), ("base feature", base_feature)) if _is_valid(entity)]
    if not remaining:
        return []
    detail = "; ".join(attempts) if attempts else "delete left valid entities"
    return [", ".join(remaining) + ": " + detail]


def _create_body(occurrence, spec):
    length_mm, width_mm, height_mm = spec["size_mm"]
    x_mm, y_mm, z_mm = spec["origin_mm"]
    center = adsk.core.Point3D.create(
        (x_mm + length_mm / 2.0) / 10.0,
        (y_mm + width_mm / 2.0) / 10.0,
        (z_mm + height_mm / 2.0) / 10.0,
    )
    box = adsk.core.OrientedBoundingBox3D.create(
        center,
        adsk.core.Vector3D.create(1.0, 0.0, 0.0),
        adsk.core.Vector3D.create(0.0, 1.0, 0.0),
        length_mm / 10.0,
        width_mm / 10.0,
        height_mm / 10.0,
    )
    temporary_body = adsk.fusion.TemporaryBRepManager.get().createBox(box)
    if not temporary_body:
        raise RuntimeError("Fusion failed to create temporary box: " + spec["path"])

    component = occurrence.component
    base_feature = component.features.baseFeatures.add()
    if not base_feature:
        raise RuntimeError("Fusion failed to create a parametric base feature: " + spec["path"])
    body = None
    editing = False
    try:
        if not base_feature.startEdit():
            raise RuntimeError("Fusion failed to enter base-feature edit mode: " + spec["path"])
        editing = True
        body = component.bRepBodies.add(temporary_body, base_feature)
        if not body:
            raise RuntimeError("Fusion failed to persist positive-control body: " + spec["path"])
        body.name = spec["body_name"]
        if not base_feature.finishEdit():
            raise RuntimeError("Fusion failed to finish base-feature edit mode: " + spec["path"])
        editing = False
        return body, base_feature
    except Exception as error:
        cleanup_errors = _cleanup_pair(body, base_feature, editing)
        if cleanup_errors:
            raise RuntimeError(
                "Positive-control creation failed and cleanup left partial artifacts for "
                + spec["path"]
                + ": "
                + "; ".join(cleanup_errors)
            ) from error
        raise


def _cleanup_created(resources):
    deleted = []
    errors = []
    for path, body, base_feature in reversed(resources):
        pair_errors = _cleanup_pair(body, base_feature)
        if pair_errors:
            errors.extend(path + ": " + detail for detail in pair_errors)
        else:
            deleted.append(path)
    return sorted(deleted), errors


def run(context):
    created_resources = []
    try:
        app, design = _active_design()
        target_document = _require_target_document(app)
        if bool(getattr(target_document, "isSaved", True)):
            raise RuntimeError("Positive control requires an unsaved target document.")
        if design.designType != adsk.fusion.DesignTypes.ParametricDesignType:
            raise RuntimeError(
                "Positive-control geometry requires a parametric design; "
                "refusing a destructive design-type change."
            )
        _pump_events(app, design, target_document)
        _, occurrence_map, duplicate_semantic_paths = _root_context_occurrence_map(design.rootComponent)
        if duplicate_semantic_paths:
            raise RuntimeError(
                "Positive control refuses duplicate semantic component paths: "
                + repr(duplicate_semantic_paths)
                + "."
            )
        missing_paths = sorted(spec["path"] for spec in BOX_SPECS if spec["path"] not in occurrence_map)
        if missing_paths:
            raise RuntimeError("Positive-control scaffold components are missing: " + ", ".join(missing_paths))
        for spec in BOX_SPECS:
            occurrence = occurrence_map[spec["path"]]
            _require_scaffold_identity(occurrence, spec["path"])
            _require_identity_transform(occurrence, spec["path"])

        created = []
        reused = []
        for index, spec in enumerate(BOX_SPECS):
            occurrence = occurrence_map[spec["path"]]
            if occurrence.component.bRepBodies.count:
                _, body = _validate_geometry(occurrence, spec)
                reused.append(spec["path"])
            else:
                body, base_feature = _create_body(occurrence, spec)
                created_resources.append((spec["path"], body, base_feature))
                _validate_geometry(occurrence, spec)
                created.append(spec["path"])
            _pump_events_periodically(app, design, target_document, index)

        _pump_events(app, design, target_document)
        compute_invoked = design.computeAll()
        _pump_events(app, design, target_document)
        # Re-derive the verdict from a post-pump read.  Every yield above can
        # carry a user edit that makes the tree ambiguous or revokes scaffold
        # identity, so the pre-pump map is evidence of nothing by this point.
        _, verified_map, duplicate_semantic_paths = _root_context_occurrence_map(design.rootComponent)
        box_paths = [spec["path"] for spec in BOX_SPECS]
        ambiguous_component_paths = sorted(set(duplicate_semantic_paths).intersection(box_paths))
        components_missing = sorted(path for path in box_paths if path not in verified_map)
        scaffold_identity_failures = []
        body_reports = []
        if not ambiguous_component_paths and not components_missing:
            for spec in BOX_SPECS:
                occurrence = verified_map[spec["path"]]
                try:
                    _require_scaffold_identity(occurrence, spec["path"])
                except Exception as identity_error:
                    scaffold_identity_failures.append(str(identity_error))
                    continue
                body_report, _ = _validate_geometry(occurrence, spec)
                body_reports.append(body_report)
        timeline = _timeline_health(design)
        report = {
            "kind": "positive-control",
            "project": PROJECT_NAME,
            "manifest_sha256": MANIFEST_SHA256,
            "document_name": target_document.name,
            "created": sorted(created),
            "reused": sorted(reused),
            "bodies": body_reports,
            "compute_invoked": bool(compute_invoked),
            "duplicate_semantic_paths": duplicate_semantic_paths,
            "ambiguous_component_paths": ambiguous_component_paths,
            "components_missing": components_missing,
            "scaffold_identity_failures": scaffold_identity_failures,
            "timeline": timeline,
            "ok": (
                bool(compute_invoked)
                and not timeline["unhealthy"]
                and not ambiguous_component_paths
                and not components_missing
                and not scaffold_identity_failures
                and len(body_reports) == len(BOX_SPECS)
            ),
        }
        _emit(report)
        if not report["ok"]:
            raise RuntimeError("Positive-control geometry did not satisfy its report contract.")
    except Exception as error:
        created_paths = sorted(path for path, _, _ in created_resources)
        if isinstance(error, DocumentChangedError):
            # The guard fired precisely because this document is no longer ours.
            # Deleting from it would be the largest mutation in the transaction,
            # against a document the user switched to.  Disclose and stop.
            cleanup = {
                "performed": False,
                "reason": "active-document-changed",
                "left_behind": created_paths,
            }
            cleanup_failure = None
        else:
            deleted, cleanup_errors = _cleanup_created(created_resources)
            cleanup = {"performed": True, "deleted": deleted, "errors": cleanup_errors}
            cleanup_failure = None
            if cleanup_errors:
                cleanup_failure = RuntimeError(
                    "Positive-control transaction failed and cleanup left partial artifacts: "
                    + "; ".join(cleanup_errors)
                )
        # Always emitted, including when a report was already emitted: a reader
        # reconciling the report against the document must be able to tell
        # created-and-rolled-back from created-and-orphaned.  The last emitted
        # block is the transaction's final word.
        _emit({
            "kind": "positive-control",
            "project": PROJECT_NAME,
            "manifest_sha256": MANIFEST_SHA256,
            "ok": False,
            "error": str(cleanup_failure or error),
            "created": created_paths,
            "cleanup": cleanup,
            "traceback": traceback.format_exc(),
        })
        if cleanup_failure:
            raise cleanup_failure from error
        raise
'''
    return _script_prelude(manifest) + transaction.replace("__BOX_SPECS__", _json_literal(_box_specs(manifest)))
