"""The mesh dump: the one wire between Fusion's mesh and the host-side numerics.

The format is deliberately boring — a fixed binary header, one canonical JSON
metadata block, then three flat arrays — because two processes have to agree on
it byte for byte and one of them is Fusion's embedded interpreter, which cannot
import this module.

That constraint is why ``_SHARED_SOURCE`` exists.  The packer and the dihedral
measurement are written once, as source text; this module ``exec``s it into its
own namespace and ``mesh_extract`` embeds the identical text into the generated
transaction.  Two copies of a binary writer is how a format drifts, and a drifted
format would produce a dump whose hash is perfectly valid and whose contents mean
something else.

Reading is fail-closed and in this order: hash the bytes, compare against the
digest the transaction reported, and only then parse.  A dump that does not hash
to its recorded value is never parsed, so nothing downstream can describe content
that was not the content that was measured.
"""

from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import re
from pathlib import Path
from typing import Any


_SHA256_RE = re.compile(r"[0-9a-f]{64}")


# Shared verbatim with the in-Fusion transaction; see the module docstring.
_SHARED_SOURCE = '''import hashlib
import json
import math
import struct

MESH_DUMP_MAGIC = b"FSNMESH\\x00"
MESH_DUMP_FORMAT_VERSION = 1
MESH_DUMP_HEADER = "<8sIIIIII"
MESH_DUMP_HEADER_SIZE = 32


def pack_mesh_dump(metadata, vertices_mm, triangles, face_group_ids):
    """Pack one indexed mesh into the versioned dump bytes.

    ``vertices_mm`` and ``triangles`` are flat triples.  ``face_group_ids`` is one
    id per triangle, or None when Fusion reported no grouping -- None writes a
    zero count, which the reader surfaces as absent.  A single fabricated group
    covering every triangle would be indistinguishable from real segmentation.
    """
    vertex_count = len(vertices_mm) // 3
    triangle_count = len(triangles) // 3
    if vertex_count * 3 != len(vertices_mm) or triangle_count * 3 != len(triangles):
        raise ValueError("mesh dump arrays must be flat triples")
    if face_group_ids is None:
        group_count = 0
    else:
        group_count = len(face_group_ids)
        if group_count != triangle_count:
            raise ValueError("face group ids must be one per triangle, or absent")
    encoded = json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("utf-8")
    parts = [
        struct.pack(
            MESH_DUMP_HEADER,
            MESH_DUMP_MAGIC,
            MESH_DUMP_FORMAT_VERSION,
            len(encoded),
            vertex_count,
            triangle_count,
            group_count,
            0,
        ),
        encoded,
        struct.pack("<%dd" % len(vertices_mm), *vertices_mm),
        struct.pack("<%dI" % len(triangles), *triangles),
    ]
    if group_count:
        parts.append(struct.pack("<%dI" % group_count, *face_group_ids))
    return b"".join(parts)


def _percentile(sorted_values, fraction):
    if not sorted_values:
        return None
    rank = int(math.ceil(fraction * len(sorted_values))) - 1
    if rank < 0:
        rank = 0
    if rank >= len(sorted_values):
        rank = len(sorted_values) - 1
    return sorted_values[rank]


def connectivity_statistics(vertices_mm, triangles):
    """Report whether this dump's indices actually carry adjacency.

    An indexed mesh gives a robust estimator everything it needs -- vertex-ring
    neighbourhoods, edge adjacency, per-vertex normals -- but only if the mesh is
    welded.  An unwelded mesh repeats a position under several node indices, and
    then two triangles that touch in space share no index, so every neighbourhood
    is a single triangle and every edge reads as a boundary.

    This measures it rather than fixing it: welding needs a tolerance, and a
    tolerance is a caller-declared threshold that belongs to whoever consumes the
    dump.  ``welded`` false here means neighbourhood normals are not trustworthy
    until the consumer welds with a declared tolerance and says so.
    """
    node_count = len(vertices_mm) // 3
    positions = set()
    for index in range(node_count):
        positions.add(
            (vertices_mm[3 * index], vertices_mm[3 * index + 1], vertices_mm[3 * index + 2])
        )
    referenced = set(triangles)
    incident = {}
    for value in triangles:
        incident[value] = incident.get(value, 0) + 1
    counts = sorted(incident.values())
    return {
        "node_count": node_count,
        "distinct_position_count": len(positions),
        "duplicate_position_node_count": node_count - len(positions),
        "welded": len(positions) == node_count,
        "referenced_node_count": len(referenced),
        "unreferenced_node_count": node_count - len(referenced),
        "min_triangles_per_node": counts[0] if counts else None,
        "median_triangles_per_node": _percentile(counts, 0.5),
        "max_triangles_per_node": counts[-1] if counts else None,
    }


def dihedral_statistics(vertices_mm, triangles):
    """Measure the mesh's own interior-edge dihedral angles, in degrees.

    This reports measurements and applies no threshold: the crease threshold and
    the noise factor it is compared against are caller-declared downstream.  When
    there is no interior edge to measure, the percentiles are None rather than
    0.0, so a caller that compares them against a threshold fails loudly instead
    of reading a fabricated zero as a pristine mesh.
    """
    normals = []
    degenerate = 0
    edges = {}
    triangle_count = len(triangles) // 3
    for index in range(triangle_count):
        a = triangles[3 * index]
        b = triangles[3 * index + 1]
        c = triangles[3 * index + 2]
        ax = vertices_mm[3 * a]
        ay = vertices_mm[3 * a + 1]
        az = vertices_mm[3 * a + 2]
        ux = vertices_mm[3 * b] - ax
        uy = vertices_mm[3 * b + 1] - ay
        uz = vertices_mm[3 * b + 2] - az
        vx = vertices_mm[3 * c] - ax
        vy = vertices_mm[3 * c + 1] - ay
        vz = vertices_mm[3 * c + 2] - az
        nx = uy * vz - uz * vy
        ny = uz * vx - ux * vz
        nz = ux * vy - uy * vx
        length = math.sqrt(nx * nx + ny * ny + nz * nz)
        if length <= 0.0:
            degenerate += 1
            normals.append(None)
        else:
            normals.append((nx / length, ny / length, nz / length))
        for first, second in ((a, b), (b, c), (c, a)):
            key = (first, second) if first < second else (second, first)
            if key in edges:
                edges[key].append(index)
            else:
                edges[key] = [index]

    angles = []
    boundary_edges = 0
    non_manifold_edges = 0
    unmeasurable_edges = 0
    for key in edges:
        faces = edges[key]
        if len(faces) == 1:
            boundary_edges += 1
            continue
        if len(faces) > 2:
            non_manifold_edges += 1
            continue
        left = normals[faces[0]]
        right = normals[faces[1]]
        if left is None or right is None:
            unmeasurable_edges += 1
            continue
        dot = left[0] * right[0] + left[1] * right[1] + left[2] * right[2]
        if dot > 1.0:
            dot = 1.0
        elif dot < -1.0:
            dot = -1.0
        angles.append(math.degrees(math.acos(dot)))
    angles.sort()
    return {
        "edge_count": len(edges),
        "interior_edge_count": len(angles),
        "boundary_edge_count": boundary_edges,
        "non_manifold_edge_count": non_manifold_edges,
        "unmeasurable_edge_count": unmeasurable_edges,
        "degenerate_triangle_count": degenerate,
        "median_abs_dihedral_deg": _percentile(angles, 0.5),
        "p90_abs_dihedral_deg": _percentile(angles, 0.9),
        "max_abs_dihedral_deg": angles[-1] if angles else None,
    }
'''

exec(_SHARED_SOURCE, globals())  # noqa: S102 - one implementation, two processes.


MESH_DUMP_METADATA_FIELDS = {
    "vertex_units",
    "internal_to_vertex_unit_scale",
    "source_units",
    "source_unit_source",
    "mesh_source_id",
    "mesh_source_sha256",
    "manifest_sha256",
    "fusion_version",
    "component_path",
    "body_name",
    "transform",
    "transform_source",
    "face_groups_source",
}

FACE_GROUP_SOURCES = {"triangleFaceGroupTempIds", "absent"}
TRANSFORM_SOURCES = {"MeshBody.transform", "unavailable"}

# The closed refusal vocabulary for reading a dump. A reader that invents a
# reason is a reader nobody can write a handler for.
MESH_DUMP_REFUSALS = {
    "dump-hash-mismatch",
    "dump-too-short",
    "dump-bad-magic",
    "dump-format-version-unsupported",
    "dump-metadata-invalid",
    "dump-truncated",
    "dump-trailing-bytes",
    "dump-triangle-index-out-of-range",
    "dump-group-count-invalid",
    "dump-transport-invalid",
    "dump-unreadable",
}


class MeshDumpError(ValueError):
    """A dump was refused. ``reason`` is from ``MESH_DUMP_REFUSALS``."""

    def __init__(self, reason: str, detail: str) -> None:
        if reason not in MESH_DUMP_REFUSALS:
            raise ValueError(f"unknown mesh dump refusal {reason!r}")
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True, slots=True)
class MeshDump:
    """A parsed dump, bound to the digest its bytes actually hashed to."""

    sha256: str
    format_version: int
    metadata: dict[str, Any]
    vertices_mm: tuple[float, ...]
    triangles: tuple[int, ...]
    face_group_ids: tuple[int, ...] | None

    @property
    def vertex_count(self) -> int:
        return len(self.vertices_mm) // 3

    @property
    def triangle_count(self) -> int:
        return len(self.triangles) // 3

    def face_group_histogram(self) -> dict[int, int] | None:
        """Triangles per face-group id, or None when Fusion reported no grouping."""
        if self.face_group_ids is None:
            return None
        histogram: dict[int, int] = {}
        for value in self.face_group_ids:
            histogram[value] = histogram.get(value, 0) + 1
        return histogram


def _require(condition: bool, reason: str, detail: str) -> None:
    if not condition:
        raise MeshDumpError(reason, detail)


def _validate_metadata(metadata: Any) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        raise MeshDumpError("dump-metadata-invalid", "the metadata block is not a JSON object")
    missing = sorted(MESH_DUMP_METADATA_FIELDS - set(metadata))
    unknown = sorted(set(metadata) - MESH_DUMP_METADATA_FIELDS)
    if missing or unknown:
        raise MeshDumpError(
            "dump-metadata-invalid",
            f"missing {missing}, unknown {unknown}; the metadata vocabulary is closed",
        )
    if metadata["vertex_units"] != "mm":
        raise MeshDumpError(
            "dump-metadata-invalid",
            f"format version 1 writes millimetres, not {metadata['vertex_units']!r}",
        )
    for field in ("mesh_source_sha256", "manifest_sha256"):
        value = metadata[field]
        if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
            raise MeshDumpError("dump-metadata-invalid", f"{field} is not a sha-256 digest")
    if metadata["face_groups_source"] not in FACE_GROUP_SOURCES:
        raise MeshDumpError(
            "dump-metadata-invalid",
            f"face_groups_source must be one of {sorted(FACE_GROUP_SOURCES)}",
        )
    transform_source = metadata["transform_source"]
    if transform_source not in TRANSFORM_SOURCES:
        raise MeshDumpError(
            "dump-metadata-invalid", f"transform_source must be one of {sorted(TRANSFORM_SOURCES)}"
        )
    transform = metadata["transform"]
    # An unreadable transform is recorded as absent, never as identity: a
    # substituted identity places the mesh in the wrong frame silently.
    if transform_source == "unavailable":
        if transform is not None:
            raise MeshDumpError(
                "dump-metadata-invalid", "an unavailable transform must be recorded as null"
            )
    else:
        if not isinstance(transform, list) or len(transform) != 16:
            raise MeshDumpError(
                "dump-metadata-invalid", "a recorded transform must be 16 numbers (Matrix3D.asArray)"
            )
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in transform):
            raise MeshDumpError("dump-metadata-invalid", "the transform must be numeric")
    return dict(metadata)


def parse_mesh_dump(data: bytes, expected_sha256: str) -> MeshDump:
    """Hash the bytes, compare, and only then parse them.

    ``expected_sha256`` has no default on purpose.  A digest the caller may omit
    is a digest that gets omitted, and then the parsed content is bound to
    nothing.
    """
    if not isinstance(expected_sha256, str) or not _SHA256_RE.fullmatch(expected_sha256):
        raise MeshDumpError(
            "dump-hash-mismatch", "expected_sha256 must be the digest the extraction reported"
        )
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected_sha256:
        raise MeshDumpError(
            "dump-hash-mismatch",
            f"the dump hashes to {actual[:12]}..., not the recorded {expected_sha256[:12]}...",
        )

    _require(
        len(data) >= MESH_DUMP_HEADER_SIZE,  # noqa: F821 - from _SHARED_SOURCE
        "dump-too-short",
        f"{len(data)} bytes cannot hold a {MESH_DUMP_HEADER_SIZE} byte header",  # noqa: F821
    )
    magic, version, metadata_len, vertex_count, triangle_count, group_count, reserved = (
        struct.unpack(MESH_DUMP_HEADER, data[:MESH_DUMP_HEADER_SIZE])  # noqa: F821
    )
    _require(magic == MESH_DUMP_MAGIC, "dump-bad-magic", f"leading bytes {magic!r}")  # noqa: F821
    _require(
        version == MESH_DUMP_FORMAT_VERSION,  # noqa: F821
        "dump-format-version-unsupported",
        f"this reader implements version {MESH_DUMP_FORMAT_VERSION}, the dump declares {version}",  # noqa: F821
    )
    _require(reserved == 0, "dump-metadata-invalid", f"reserved header word is {reserved}, not 0")

    offset = MESH_DUMP_HEADER_SIZE  # noqa: F821
    end = offset + metadata_len
    _require(len(data) >= end, "dump-truncated", "the metadata block runs past the end of the dump")
    try:
        metadata = json.loads(data[offset:end].decode("utf-8"))  # noqa: F821
    except (UnicodeDecodeError, ValueError) as error:
        raise MeshDumpError("dump-metadata-invalid", str(error)) from error
    metadata = _validate_metadata(metadata)
    if metadata["face_groups_source"] == "absent" and group_count != 0:
        raise MeshDumpError(
            "dump-group-count-invalid",
            f"metadata records no grouping but {group_count} ids are present",
        )
    if group_count not in (0, triangle_count):
        raise MeshDumpError(
            "dump-group-count-invalid",
            f"{group_count} face-group ids for {triangle_count} triangles",
        )

    vertex_bytes = vertex_count * 3 * 8
    triangle_bytes = triangle_count * 3 * 4
    group_bytes = group_count * 4
    expected_len = end + vertex_bytes + triangle_bytes + group_bytes
    _require(
        len(data) >= expected_len,
        "dump-truncated",
        f"the header declares {expected_len} bytes, the dump holds {len(data)}",
    )
    _require(
        len(data) == expected_len,
        "dump-trailing-bytes",
        f"{len(data) - expected_len} bytes follow the declared arrays",
    )

    vertices = struct.unpack("<%dd" % (vertex_count * 3), data[end : end + vertex_bytes])  # noqa: F821
    cursor = end + vertex_bytes
    triangles = struct.unpack("<%dI" % (triangle_count * 3), data[cursor : cursor + triangle_bytes])  # noqa: F821
    cursor += triangle_bytes
    groups: tuple[int, ...] | None = None
    if group_count:
        groups = struct.unpack("<%dI" % group_count, data[cursor : cursor + group_bytes])  # noqa: F821

    for index in triangles:
        if index >= vertex_count:
            raise MeshDumpError(
                "dump-triangle-index-out-of-range",
                f"vertex index {index} against {vertex_count} vertices",
            )
    return MeshDump(
        sha256=actual,
        format_version=version,
        metadata=metadata,
        vertices_mm=vertices,
        triangles=triangles,
        face_group_ids=groups,
    )


def read_mesh_dump(path: str | Path, expected_sha256: str) -> MeshDump:
    """Read a dump file and refuse it unless its bytes hash to the recorded digest.

    A path that cannot be read refuses by name like every other way a dump can
    be wrong.  It used to escape as a bare ``OSError`` naming errno, which is the
    one refusal in this module a caller could not branch on -- and the path that
    produced it most often is a spec whose ``dump_path`` placeholder was never
    substituted, where "no such file" is the whole diagnosis.
    """
    try:
        data = Path(path).read_bytes()
    except OSError as error:
        raise MeshDumpError(
            "dump-unreadable",
            f"{path} could not be read ({error.strerror or error}); the dump this program is "
            "bound to has to be on disk before anything can be emitted against it.",
        ) from error
    return parse_mesh_dump(data, expected_sha256)


def assemble_inline_dump(report: Any) -> bytes:
    """Reassemble the chunked-base64 fallback, checking every chunk's own digest.

    The fallback exists because writing a file from Fusion's interpreter is an
    assumption, not a fact (plan A4).  It is not a weaker path: each chunk
    carries its digest, the whole carries its own, and both are checked here.
    """
    if not isinstance(report, dict):
        raise MeshDumpError("dump-transport-invalid", "the extraction report is not an object")
    transport = report.get("transport")
    if transport != "inline-base64":
        raise MeshDumpError(
            "dump-transport-invalid",
            f"transport is {transport!r}; only 'inline-base64' is reassembled here",
        )
    chunks = report.get("dump_chunks")
    if not isinstance(chunks, list) or not chunks:
        raise MeshDumpError("dump-transport-invalid", "dump_chunks is missing or empty")
    declared_count = report.get("dump_chunk_count")
    if declared_count != len(chunks):
        raise MeshDumpError(
            "dump-transport-invalid",
            f"the report declares {declared_count} chunks and carries {len(chunks)}",
        )
    payload = bytearray()
    for position, chunk in enumerate(chunks):
        if not isinstance(chunk, dict) or set(chunk) != {"index", "sha256", "base64"}:
            raise MeshDumpError("dump-transport-invalid", f"chunk {position} has an unknown shape")
        if chunk["index"] != position:
            raise MeshDumpError(
                "dump-transport-invalid", f"chunk {position} declares index {chunk['index']}"
            )
        try:
            raw = base64.b64decode(chunk["base64"], validate=True)
        except (ValueError, TypeError) as error:
            raise MeshDumpError("dump-transport-invalid", f"chunk {position}: {error}") from error
        digest = hashlib.sha256(raw).hexdigest()
        if digest != chunk["sha256"]:
            raise MeshDumpError(
                "dump-hash-mismatch",
                f"chunk {position} hashes to {digest[:12]}..., not {str(chunk['sha256'])[:12]}...",
            )
        payload.extend(raw)
    return bytes(payload)
