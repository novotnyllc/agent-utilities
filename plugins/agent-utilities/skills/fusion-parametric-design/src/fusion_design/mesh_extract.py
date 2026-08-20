"""Mesh extraction: get the triangles out of Fusion, bound by a hash.

The transaction this emits reads a mesh body and writes one dump.  It creates no
geometry, edits nothing, and reports the digest of the exact bytes it wrote --
re-read from disk before reporting, so the digest describes what the host will
actually parse rather than what was held in memory.

Everything the dump format knows lives in ``mesh_dump``; the packer and the
dihedral measurement are embedded here verbatim from that module so the two
processes cannot drift apart.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .manifest import ManifestValidationError, ValidationIssue, _reject_unknown_fields
from .mesh_dump import _SHARED_SOURCE
from .mesh_reconstruction import (
    _source_evidence,
    _validate_body_binding,
    require_classification,
)

if TYPE_CHECKING:
    from .manifest import Manifest


EXTRACT_SPEC_FIELDS = {
    "component_path",
    "body_name",
    "dump_dir",
    "max_triangles",
    "max_triangles_rationale",
    "fallback_max_bytes",
    "fallback_max_bytes_rationale",
}

# Fusion's API works in centimetres internally; the dump is written in
# millimetres so no downstream stage has to remember which one it is holding.
INTERNAL_TO_MM = 10.0


def _require_positive_int(
    issues: list[ValidationIssue], value: Any, path: str, code: str, message: str
) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        issues.append(ValidationIssue(code, path, message))


def _require_rationale(issues: list[ValidationIssue], value: Any, path: str, code: str, subject: str) -> None:
    if not isinstance(value, str) or not value.strip():
        issues.append(
            ValidationIssue(
                code,
                path,
                f"Record why this {subject} is the right one for this mesh; a limit nobody justified "
                "can be set high enough that it never fires, and it is never a module constant.",
            )
        )


def validate_extract_spec(spec: Any) -> list[ValidationIssue]:
    """Validate the extraction spec: which body, where the dump goes, and both declared limits."""
    issues: list[ValidationIssue] = []
    if not isinstance(spec, dict):
        return [
            ValidationIssue(
                "extract-spec-must-be-object",
                "extract_spec",
                "A mesh extraction spec must be an object.",
            )
        ]
    _reject_unknown_fields(issues, spec, EXTRACT_SPEC_FIELDS, "extract_spec")
    _validate_body_binding(
        issues,
        {key: spec[key] for key in ("component_path", "body_name") if key in spec},
        "extract_spec",
        "extract-spec-invalid-binding",
    )
    dump_dir = spec.get("dump_dir")
    if not isinstance(dump_dir, str) or not dump_dir.strip():
        issues.append(
            ValidationIssue(
                "extract-spec-invalid-dump-dir",
                "extract_spec.dump_dir",
                "dump_dir must name a directory on the machine running Fusion; the transaction writes "
                "the dump there and reports its digest.",
            )
        )
    _require_positive_int(
        issues,
        spec.get("max_triangles"),
        "extract_spec.max_triangles",
        "extract-spec-invalid-budget",
        "max_triangles must be a positive integer declared for this extraction; the triangle budget "
        "is never a module constant.",
    )
    _require_rationale(
        issues,
        spec.get("max_triangles_rationale"),
        "extract_spec.max_triangles_rationale",
        "extract-spec-invalid-budget-rationale",
        "triangle budget",
    )
    _require_positive_int(
        issues,
        spec.get("fallback_max_bytes"),
        "extract_spec.fallback_max_bytes",
        "extract-spec-invalid-fallback-ceiling",
        "fallback_max_bytes must be a positive integer: the chunked-stdout fallback is size-limited, "
        "and the ceiling is declared rather than discovered when a report is truncated.",
    )
    _require_rationale(
        issues,
        spec.get("fallback_max_bytes_rationale"),
        "extract_spec.fallback_max_bytes_rationale",
        "extract-spec-invalid-fallback-rationale",
        "stdout fallback ceiling",
    )
    return issues


def dump_file_name(source_record: dict[str, Any]) -> str:
    """The dump's file name, derived from the source it was extracted from.

    Derived rather than declared so two extractions of different sources cannot
    collide on one path, and so the name itself says which mesh it came from.
    """
    return f"{source_record['id']}-{str(source_record['sha256'])[:12]}.meshdump"


def emit_mesh_extract_script(
    manifest: "Manifest",
    classification_record: Any,
    source_record: Any,
    spec: Any,
) -> str:
    """Emit the read-only extraction transaction: budget, arrays, dump, digest."""
    from .scripts import _json_literal, _script_prelude, manifest_sha256

    classification = require_classification(
        classification_record, "mesh-extract", {"parametric-rebuild"}, source_record
    )
    issues = validate_extract_spec(spec)
    if issues:
        raise ManifestValidationError(issues)

    specs = {
        "classification": classification.to_dict(),
        "mesh_source": _source_evidence(source_record),
        "component_path": spec["component_path"],
        "body_name": spec["body_name"],
        "dump_dir": str(spec["dump_dir"]).strip(),
        "dump_name": dump_file_name(source_record),
        "max_triangles": int(spec["max_triangles"]),
        "max_triangles_rationale": str(spec["max_triangles_rationale"]).strip(),
        "fallback_max_bytes": int(spec["fallback_max_bytes"]),
        "fallback_max_bytes_rationale": str(spec["fallback_max_bytes_rationale"]).strip(),
        "internal_to_mm": INTERNAL_TO_MM,
        "manifest_sha256": manifest_sha256(manifest),
    }

    transaction = '''EXTRACT_SPECS = json.loads(__EXTRACT_SPECS__)

import base64
import os

# The dump is the interface: everything downstream parses these bytes, so the
# digest reported here is taken from the file after it was written and read back,
# never from the buffer that was meant to be written.
TRANSPORT_NOTE = (
    "This report binds a mesh dump by sha-256. Nothing downstream may parse those bytes without "
    "re-hashing them to this digest first; a dump that does not match is a different mesh."
)


def _refuse(reason, detail, alternative):
    return {"reason": reason, "detail": detail, "alternative": alternative}


def _read(source, name, unavailable):
    try:
        value = getattr(source, name, None)
    except Exception:
        value = None
    if value is None:
        unavailable.append(name)
    return value


def _target_component(design, component_path):
    if not component_path:
        return design.rootComponent, None
    _, occurrence_map, duplicate_semantic_paths = _root_context_occurrence_map(design.rootComponent)
    if component_path in duplicate_semantic_paths:
        return None, "duplicate-semantic-path"
    occurrence = occurrence_map.get(component_path)
    if occurrence is None:
        return None, "component-path-missing"
    return occurrence.component, None


def _mesh_body(component, body_name):
    mesh_bodies = getattr(component, "meshBodies", None)
    if mesh_bodies is None:
        return None
    for index in range(mesh_bodies.count):
        body = mesh_bodies.item(index)
        if getattr(body, "name", None) == body_name:
            return body
    return None


def _transform_array(mesh_body):
    """Record the body transform, or record that it is unreadable. Never substitute identity."""
    try:
        transform = getattr(mesh_body, "transform", None)
        if transform is None:
            return None, "unavailable"
        values = [float(value) for value in transform.asArray()]
    except Exception:
        return None, "unavailable"
    if len(values) != 16:
        return None, "unavailable"
    return values, "MeshBody.transform"


def _face_group_ids(mesh, triangle_count):
    try:
        raw = getattr(mesh, "triangleFaceGroupTempIds", None)
    except Exception as error:
        return None, {"source": "absent", "reason": "triangleFaceGroupTempIds raised: " + str(error)}
    if raw is None:
        return None, {
            "source": "absent",
            "reason": "Fusion reported no triangleFaceGroupTempIds on this mesh.",
        }
    try:
        ids = [int(value) for value in raw]
    except Exception as error:
        return None, {"source": "absent", "reason": "triangleFaceGroupTempIds unreadable: " + str(error)}
    if len(ids) != triangle_count:
        # Neither padded nor truncated: a partial grouping is not a grouping.
        return None, {
            "source": "absent",
            "reason": (
                "triangleFaceGroupTempIds carried " + str(len(ids)) + " ids for "
                + str(triangle_count) + " triangles."
            ),
        }
    histogram = {}
    for value in ids:
        key = str(value)
        histogram[key] = histogram.get(key, 0) + 1
    return ids, {
        "source": "triangleFaceGroupTempIds",
        "group_count": len(histogram),
        "histogram": histogram,
        "single_group": len(histogram) == 1,
    }


def _chunk(payload, chunk_bytes):
    chunks = []
    index = 0
    position = 0
    while position < len(payload):
        piece = payload[position:position + chunk_bytes]
        chunks.append({
            "index": index,
            "sha256": hashlib.sha256(piece).hexdigest(),
            "base64": base64.b64encode(piece).decode("ascii"),
        })
        index += 1
        position += chunk_bytes
    return chunks


def run(context):
    report_attempted = False
    try:
        app, design = _active_design()
        fusion_version = getattr(app, "version", None)
        target_document = _require_target_document(app)
        _pump_events(app, design, target_document)

        checked = []
        report = {
            "kind": "mesh-extract",
            "ok": False,
            "project": PROJECT_NAME,
            "manifest_sha256": MANIFEST_SHA256,
            "fusion_version": fusion_version,
            "classification": EXTRACT_SPECS["classification"],
            "mesh_source": EXTRACT_SPECS["mesh_source"],
            "component_path": EXTRACT_SPECS["component_path"],
            "body_name": EXTRACT_SPECS["body_name"],
            "declared_max_triangles": EXTRACT_SPECS["max_triangles"],
            "max_triangles_rationale": EXTRACT_SPECS["max_triangles_rationale"],
            "declared_fallback_max_bytes": EXTRACT_SPECS["fallback_max_bytes"],
            "fallback_max_bytes_rationale": EXTRACT_SPECS["fallback_max_bytes_rationale"],
            "dump_format_version": MESH_DUMP_FORMAT_VERSION,
            "transport": None,
            "dump_sha256": None,
            "checked": checked,
            "refusals": [],
            "failures": [],
            "preview_apis": [
                "MeshBody.mesh",
                "PolygonMesh.nodeCoordinates",
                "PolygonMesh.triangleNodeIndices",
                "PolygonMesh.triangleFaceGroupTempIds",
            ],
            "note": TRANSPORT_NOTE,
        }

        def fail(reasons):
            report["failures"] = sorted(set(reasons))
            _emit(report)
            raise RuntimeError("Mesh extraction refused: " + ", ".join(report["failures"]))

        component, resolution_error = _target_component(design, EXTRACT_SPECS["component_path"])
        if component is None:
            report["refusals"].append(_refuse(
                "source-not-found",
                {"component_path": EXTRACT_SPECS["component_path"], "reason": resolution_error},
                "Re-read the capture report and bind the body by its reported component path and name.",
            ))
            report_attempted = True
            fail(["source-not-found"])

        mesh_body = _mesh_body(component, EXTRACT_SPECS["body_name"])
        if mesh_body is None:
            report["refusals"].append(_refuse(
                "source-not-found",
                {"body_name": EXTRACT_SPECS["body_name"], "detail": "no mesh body of that name"},
                "Extraction reads a mesh body; a missing body is a binding error, not an empty mesh.",
            ))
            report_attempted = True
            fail(["source-not-found"])
        checked.append("mesh-body-bound")

        unavailable = []
        mesh = _read(mesh_body, "mesh", unavailable)
        triangle_count = None
        if mesh is not None:
            triangle_count = _read(mesh, "triangleCount", unavailable)
        if mesh is None or triangle_count is None:
            report["refusals"].append(_refuse(
                "mesh-evidence-unavailable",
                {"unavailable": sorted(set(unavailable))},
                "These preview properties are the extraction's own inputs. A missing count is not a "
                "count of zero, so nothing is read and nothing is written.",
            ))
            report_attempted = True
            fail(["mesh-evidence-unavailable"])

        triangle_count = int(triangle_count)
        report["triangle_count"] = triangle_count
        # Before any coordinate array is touched: an oversized mesh costs nothing.
        if triangle_count > EXTRACT_SPECS["max_triangles"]:
            report["refusals"].append(_refuse(
                "triangle-budget-exceeded",
                {
                    "triangle_count": triangle_count,
                    "declared_max_triangles": EXTRACT_SPECS["max_triangles"],
                    "rationale": EXTRACT_SPECS["max_triangles_rationale"],
                },
                "Decimate the mesh and re-capture it as a new source with its own digest, or declare a "
                "larger budget and say what the algorithm can honestly use at that density.",
            ))
            report_attempted = True
            fail(["triangle-budget-exceeded"])
        checked.append("triangle-budget")

        raw_nodes = _read(mesh, "nodeCoordinates", unavailable)
        raw_indices = _read(mesh, "triangleNodeIndices", unavailable)
        if raw_nodes is None or raw_indices is None:
            report["refusals"].append(_refuse(
                "mesh-evidence-unavailable",
                {"unavailable": sorted(set(unavailable))},
                "Without both arrays there is no mesh to dump; an absent array is never an empty one.",
            ))
            report_attempted = True
            fail(["mesh-evidence-unavailable"])

        scale = EXTRACT_SPECS["internal_to_mm"]
        vertices_mm = []
        try:
            for index in range(len(raw_nodes)):
                point = raw_nodes[index]
                vertices_mm.append(float(point.x) * scale)
                vertices_mm.append(float(point.y) * scale)
                vertices_mm.append(float(point.z) * scale)
                _pump_events_periodically(app, design, target_document, index)
            triangles = [int(value) for value in raw_indices]
        except DocumentChangedError:
            raise
        except Exception as error:
            report["refusals"].append(_refuse(
                "mesh-arrays-unreadable",
                {"error": str(error)},
                "The arrays are present but did not read as numbers; this is an adapter/API mismatch, "
                "not proof the mesh is empty.",
            ))
            report_attempted = True
            fail(["mesh-arrays-unreadable"])

        if len(triangles) != triangle_count * 3:
            report["refusals"].append(_refuse(
                "mesh-arrays-inconsistent",
                {"triangle_count": triangle_count, "index_count": len(triangles)},
                "triangleNodeIndices did not carry three indices per triangle; nothing is written from "
                "arrays that disagree with each other.",
            ))
            report_attempted = True
            fail(["mesh-arrays-inconsistent"])
        vertex_count = len(vertices_mm) // 3
        for value in triangles:
            if value >= vertex_count:
                report["refusals"].append(_refuse(
                    "mesh-arrays-inconsistent",
                    {"vertex_count": vertex_count, "index": value},
                    "A triangle references a vertex that was not reported; the dump would not parse.",
                ))
                report_attempted = True
                fail(["mesh-arrays-inconsistent"])
        report["vertex_count"] = vertex_count
        checked.append("mesh-arrays-read")

        face_group_ids, face_groups = _face_group_ids(mesh, triangle_count)
        report["face_groups"] = face_groups
        if face_group_ids is not None:
            checked.append("face-groups-read")

        transform, transform_source = _transform_array(mesh_body)
        report["transform_source"] = transform_source

        source = EXTRACT_SPECS["mesh_source"]
        metadata = {
            "vertex_units": "mm",
            "internal_to_vertex_unit_scale": scale,
            "source_units": source["units"],
            "source_unit_source": source["unit_source"],
            "mesh_source_id": source["id"],
            "mesh_source_sha256": source["sha256"],
            "manifest_sha256": EXTRACT_SPECS["manifest_sha256"],
            "fusion_version": str(fusion_version) if fusion_version else None,
            "component_path": EXTRACT_SPECS["component_path"],
            "body_name": EXTRACT_SPECS["body_name"],
            "transform": transform,
            "transform_source": transform_source,
            "face_groups_source": face_groups["source"],
        }
        payload = pack_mesh_dump(metadata, vertices_mm, triangles, face_group_ids)
        payload_sha256 = hashlib.sha256(payload).hexdigest()
        report["dump_bytes"] = len(payload)

        _pump_events(app, design, target_document)
        dump_path = os.path.join(EXTRACT_SPECS["dump_dir"], EXTRACT_SPECS["dump_name"])
        write_error = None
        try:
            os.makedirs(EXTRACT_SPECS["dump_dir"], exist_ok=True)
            handle = open(dump_path, "wb")
            try:
                handle.write(payload)
            finally:
                handle.close()
            handle = open(dump_path, "rb")
            try:
                written = handle.read()
            finally:
                handle.close()
            written_sha256 = hashlib.sha256(written).hexdigest()
            if written_sha256 != payload_sha256:
                write_error = (
                    "the file on disk hashes to " + written_sha256[:12] + "..., not "
                    + payload_sha256[:12] + "..."
                )
        except Exception as error:
            write_error = str(error)

        if write_error is None:
            report["transport"] = "file"
            report["dump_path"] = dump_path
            report["dump_sha256"] = payload_sha256
            checked.append("dump-written-and-reread")
        else:
            # A4 was an assumption, so the fallback is implemented rather than hoped for.
            # A recovered write is recorded here and not in refusals: refusals are
            # things this run would not do, and this one carried the dump anyway.
            report["dump_write_error"] = write_error
            report["dump_write_fallback"] = _refuse(
                "dump-write-unavailable",
                {"dump_path": dump_path, "error": write_error},
                "Falling back to chunked base64 over this report, which is size-limited by the declared "
                "fallback_max_bytes.",
            )
            chunks = _chunk(payload, 262144)
            encoded_bytes = 0
            for chunk in chunks:
                encoded_bytes += len(chunk["base64"])
            if encoded_bytes > EXTRACT_SPECS["fallback_max_bytes"]:
                report["refusals"].append(report["dump_write_fallback"])
                report["refusals"].append(_refuse(
                    "dump-too-large-for-fallback",
                    {
                        "encoded_bytes": encoded_bytes,
                        "declared_fallback_max_bytes": EXTRACT_SPECS["fallback_max_bytes"],
                    },
                    "Make the dump directory writable from Fusion, or decimate the mesh and re-capture "
                    "it as a new source with its own digest.",
                ))
                report_attempted = True
                fail(["dump-write-unavailable", "dump-too-large-for-fallback"])
            report["transport"] = "inline-base64"
            report["dump_sha256"] = payload_sha256
            report["dump_chunk_count"] = len(chunks)
            report["dump_chunks"] = chunks
            report["dump_encoded_bytes"] = encoded_bytes
            checked.append("dump-inline-chunked")

        report["dihedral_statistics"] = dihedral_statistics(vertices_mm, triangles)
        checked.append("dihedral-statistics")
        # A robust estimator works on neighbourhoods, not on isolated triangles,
        # so the report states whether this mesh's indices carry adjacency at all.
        report["connectivity_statistics"] = connectivity_statistics(vertices_mm, triangles)
        checked.append("connectivity-statistics")

        try:
            source_present = getattr(mesh_body, "isValid", None)
        except Exception:
            source_present = None
        # Unreadable is not proof the source survived; only True is.
        report["source_mesh_body_present"] = source_present
        if source_present is not True:
            report_attempted = True
            fail(["source-mesh-consumed"])
        checked.append("source-mesh-intact")

        report["ok"] = True
        report["failures"] = []
        report_attempted = True
        _emit(report)
    except Exception as error:
        if not report_attempted:
            report_attempted = True
            _emit({
                "kind": "mesh-extract",
                "ok": False,
                "project": PROJECT_NAME,
                "manifest_sha256": MANIFEST_SHA256,
                "transport": None,
                "dump_sha256": None,
                "error": str(error),
                "traceback": traceback.format_exc(),
            })
        raise
'''
    return (
        # Beside the dump this transaction writes: the extraction's own inputs
        # and its output already live there.
        _script_prelude(manifest, report_dir=specs["dump_dir"])
        + _SHARED_SOURCE
        + "\n\n"
        + transaction.replace("__EXTRACT_SPECS__", _json_literal(specs))
    )
