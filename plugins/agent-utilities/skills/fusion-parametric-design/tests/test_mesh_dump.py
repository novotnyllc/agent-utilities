from __future__ import annotations

import base64
import copy
import hashlib
import json
import struct
import tempfile
from pathlib import Path
import unittest

from fusion_design.mesh_dump import (
    MESH_DUMP_FORMAT_VERSION,
    MESH_DUMP_HEADER,
    MESH_DUMP_HEADER_SIZE,
    MESH_DUMP_MAGIC,
    MeshDumpError,
    assemble_inline_dump,
    connectivity_statistics,
    dihedral_statistics,
    pack_mesh_dump,
    parse_mesh_dump,
    read_mesh_dump,
)


METADATA = {
    "vertex_units": "mm",
    "internal_to_vertex_unit_scale": 10.0,
    "source_units": "mm",
    "source_unit_source": "declared",
    "mesh_source_id": "scan_bracket",
    "mesh_source_sha256": "a" * 64,
    "manifest_sha256": "b" * 64,
    "fusion_version": "2.0.20000",
    "component_path": "",
    "body_name": "bracket_scan",
    "transform": [
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ],
    "transform_source": "MeshBody.transform",
    "face_groups_source": "triangleFaceGroupTempIds",
}

# A welded unit square in millimetres: two triangles sharing edge 0-2.
SQUARE_VERTICES = [0.0, 0.0, 0.0, 10.0, 0.0, 0.0, 10.0, 10.0, 0.0, 0.0, 10.0, 0.0]
SQUARE_TRIANGLES = [0, 1, 2, 0, 2, 3]
SQUARE_GROUPS = [7, 7]


def metadata(**overrides) -> dict:
    value = copy.deepcopy(METADATA)
    value.update(overrides)
    return value


def packed(**overrides) -> bytes:
    return pack_mesh_dump(metadata(**overrides), SQUARE_VERTICES, SQUARE_TRIANGLES, SQUARE_GROUPS)


def refuse(payload: bytes) -> str:
    """Parse bytes that hash to themselves, so a structural refusal is what fires."""
    try:
        parse_mesh_dump(payload, hashlib.sha256(payload).hexdigest())
    except MeshDumpError as error:
        return error.reason
    raise AssertionError("expected the dump to be refused")


def rebuild(payload: bytes, **header) -> bytes:
    fields = list(struct.unpack(MESH_DUMP_HEADER, payload[:MESH_DUMP_HEADER_SIZE]))
    names = ("magic", "version", "metadata_len", "vertex_count", "triangle_count", "group_count", "reserved")
    for name, value in header.items():
        fields[names.index(name)] = value
    return struct.pack(MESH_DUMP_HEADER, *fields) + payload[MESH_DUMP_HEADER_SIZE:]


class DumpRoundTripTests(unittest.TestCase):
    def test_a_dump_round_trips_every_field_it_carries(self) -> None:
        payload = packed()
        dump = parse_mesh_dump(payload, hashlib.sha256(payload).hexdigest())
        self.assertEqual(MESH_DUMP_FORMAT_VERSION, dump.format_version)
        self.assertEqual(metadata(), dump.metadata)
        self.assertEqual(tuple(SQUARE_VERTICES), dump.vertices_mm)
        self.assertEqual(tuple(SQUARE_TRIANGLES), dump.triangles)
        self.assertEqual(tuple(SQUARE_GROUPS), dump.face_group_ids)
        self.assertEqual(4, dump.vertex_count)
        self.assertEqual(2, dump.triangle_count)
        self.assertEqual({7: 2}, dump.face_group_histogram())

    def test_packing_the_same_mesh_twice_produces_the_same_bytes(self) -> None:
        self.assertEqual(packed(), packed())

    def test_a_file_is_read_back_and_bound_to_its_digest(self) -> None:
        payload = packed()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bracket.meshdump"
            path.write_bytes(payload)
            dump = read_mesh_dump(path, hashlib.sha256(payload).hexdigest())
            self.assertEqual(2, dump.triangle_count)
            with self.assertRaises(MeshDumpError) as caught:
                read_mesh_dump(path, "c" * 64)
        self.assertEqual("dump-hash-mismatch", caught.exception.reason)

    def test_a_dump_path_that_cannot_be_read_refuses_by_name(self) -> None:
        """The one way a dump could be wrong that a caller could not branch on.

        A spec whose `dump_path` placeholder was never substituted reached the
        emitter and escaped as a bare OSError naming errno. Every other way a
        dump is wrong carries a reason from the closed vocabulary; this one does
        now too, and it names the path.
        """
        with self.assertRaises(MeshDumpError) as caught:
            read_mesh_dump("dumps/REPLACED_WITH_THE_PARTS_OWN_DUMP", "d" * 64)
        self.assertEqual("dump-unreadable", caught.exception.reason)
        self.assertIn("REPLACED_WITH_THE_PARTS_OWN_DUMP", str(caught.exception))

    def test_absent_face_groups_are_absent_and_never_one_fabricated_group(self) -> None:
        payload = pack_mesh_dump(
            metadata(face_groups_source="absent"), SQUARE_VERTICES, SQUARE_TRIANGLES, None
        )
        dump = parse_mesh_dump(payload, hashlib.sha256(payload).hexdigest())
        self.assertIsNone(dump.face_group_ids)
        self.assertIsNone(dump.face_group_histogram())

    def test_face_group_ids_must_be_one_per_triangle(self) -> None:
        with self.assertRaises(ValueError):
            pack_mesh_dump(metadata(), SQUARE_VERTICES, SQUARE_TRIANGLES, [1])


class DumpRefusalTests(unittest.TestCase):
    def test_a_single_altered_byte_fails_the_recorded_digest(self) -> None:
        payload = bytearray(packed())
        digest = hashlib.sha256(bytes(payload)).hexdigest()
        payload[-1] ^= 0x01
        with self.assertRaises(MeshDumpError) as caught:
            parse_mesh_dump(bytes(payload), digest)
        self.assertEqual("dump-hash-mismatch", caught.exception.reason)

    def test_an_omitted_or_malformed_digest_is_itself_a_refusal(self) -> None:
        payload = packed()
        for bad in (None, "", "not-a-digest", 17):
            with self.subTest(digest=bad):
                with self.assertRaises(MeshDumpError) as caught:
                    parse_mesh_dump(payload, bad)  # type: ignore[arg-type]
                self.assertEqual("dump-hash-mismatch", caught.exception.reason)

    def test_every_structural_defect_names_its_own_reason(self) -> None:
        payload = packed()
        cases = {
            "dump-too-short": payload[:8],
            "dump-bad-magic": b"NOTAMESH" + payload[8:],
            "dump-format-version-unsupported": rebuild(payload, version=MESH_DUMP_FORMAT_VERSION + 1),
            "dump-trailing-bytes": payload + b"\x00",
            "dump-truncated": payload[:-4],
        }
        for reason, mutated in cases.items():
            with self.subTest(reason=reason):
                self.assertEqual(reason, refuse(mutated))

    def test_a_reserved_word_that_is_not_zero_refuses(self) -> None:
        self.assertEqual("dump-metadata-invalid", refuse(rebuild(packed(), reserved=1)))

    def test_the_metadata_vocabulary_is_closed_in_both_directions(self) -> None:
        extra = metadata()
        extra["hopes"] = 1
        self.assertEqual(
            "dump-metadata-invalid",
            refuse(pack_mesh_dump(extra, SQUARE_VERTICES, SQUARE_TRIANGLES, SQUARE_GROUPS)),
        )
        missing = metadata()
        del missing["body_name"]
        self.assertEqual(
            "dump-metadata-invalid",
            refuse(pack_mesh_dump(missing, SQUARE_VERTICES, SQUARE_TRIANGLES, SQUARE_GROUPS)),
        )

    def test_an_unavailable_transform_is_never_recorded_as_identity(self) -> None:
        self.assertEqual(
            "dump-metadata-invalid",
            refuse(
                pack_mesh_dump(
                    metadata(transform_source="unavailable"),
                    SQUARE_VERTICES,
                    SQUARE_TRIANGLES,
                    SQUARE_GROUPS,
                )
            ),
        )
        payload = pack_mesh_dump(
            metadata(transform=None, transform_source="unavailable"),
            SQUARE_VERTICES,
            SQUARE_TRIANGLES,
            SQUARE_GROUPS,
        )
        dump = parse_mesh_dump(payload, hashlib.sha256(payload).hexdigest())
        self.assertIsNone(dump.metadata["transform"])
        for broken in ([1.0] * 15, "identity", [None] * 16):
            with self.subTest(transform=broken):
                self.assertEqual(
                    "dump-metadata-invalid",
                    refuse(
                        pack_mesh_dump(
                            metadata(transform=broken),
                            SQUARE_VERTICES,
                            SQUARE_TRIANGLES,
                            SQUARE_GROUPS,
                        )
                    ),
                )

    def test_metadata_that_disagrees_with_the_arrays_refuses(self) -> None:
        payload = pack_mesh_dump(
            metadata(face_groups_source="absent"), SQUARE_VERTICES, SQUARE_TRIANGLES, SQUARE_GROUPS
        )
        self.assertEqual("dump-group-count-invalid", refuse(payload))

    def test_a_triangle_pointing_past_the_vertex_array_refuses(self) -> None:
        payload = pack_mesh_dump(metadata(), SQUARE_VERTICES, [0, 1, 9, 0, 2, 3], SQUARE_GROUPS)
        self.assertEqual("dump-triangle-index-out-of-range", refuse(payload))

    def test_the_refusal_vocabulary_is_closed(self) -> None:
        with self.assertRaises(ValueError):
            MeshDumpError("dump-vibes-wrong", "not a real reason")


class MeasurementTests(unittest.TestCase):
    def test_the_square_reports_one_interior_edge_at_zero_degrees(self) -> None:
        stats = dihedral_statistics(SQUARE_VERTICES, SQUARE_TRIANGLES)
        self.assertEqual(5, stats["edge_count"])
        self.assertEqual(1, stats["interior_edge_count"])
        self.assertEqual(4, stats["boundary_edge_count"])
        self.assertEqual(0, stats["non_manifold_edge_count"])
        self.assertEqual(0, stats["degenerate_triangle_count"])
        self.assertAlmostEqual(0.0, stats["median_abs_dihedral_deg"])

    def test_a_folded_pair_reports_its_real_dihedral_angle(self) -> None:
        vertices = [0.0, 0.0, 0.0, 10.0, 0.0, 0.0, 10.0, 10.0, 0.0, 0.0, 10.0, 0.0, 0.0, 0.0, 10.0]
        # Triangles 0-1-2 and 0-2-3 lie flat; 0-1-4 stands vertically off edge 0-1.
        stats = dihedral_statistics(vertices, [0, 1, 2, 0, 2, 3, 0, 4, 1])
        self.assertEqual(2, stats["interior_edge_count"])
        # The flat seam reads 0 and the fold reads its true 90; the median is the
        # noise-floor estimator, so on a mostly-flat mesh it stays near zero.
        self.assertAlmostEqual(0.0, stats["median_abs_dihedral_deg"], places=6)
        self.assertAlmostEqual(90.0, stats["p90_abs_dihedral_deg"], places=6)
        self.assertAlmostEqual(90.0, stats["max_abs_dihedral_deg"], places=6)

    def test_no_interior_edge_reports_none_rather_than_a_flattering_zero(self) -> None:
        stats = dihedral_statistics([0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0], [0, 1, 2])
        self.assertEqual(0, stats["interior_edge_count"])
        self.assertIsNone(stats["median_abs_dihedral_deg"])
        self.assertIsNone(stats["p90_abs_dihedral_deg"])
        self.assertIsNone(stats["max_abs_dihedral_deg"])

    def test_a_degenerate_triangle_is_counted_and_not_measured(self) -> None:
        vertices = [0.0, 0.0, 0.0, 10.0, 0.0, 0.0, 20.0, 0.0, 0.0, 0.0, 10.0, 0.0]
        stats = dihedral_statistics(vertices, [0, 1, 2, 0, 1, 3])
        self.assertEqual(1, stats["degenerate_triangle_count"])
        self.assertEqual(1, stats["unmeasurable_edge_count"])
        self.assertEqual(0, stats["interior_edge_count"])

    def test_connectivity_reports_a_welded_mesh_as_welded(self) -> None:
        stats = connectivity_statistics(SQUARE_VERTICES, SQUARE_TRIANGLES)
        self.assertTrue(stats["welded"])
        self.assertEqual(4, stats["node_count"])
        self.assertEqual(4, stats["distinct_position_count"])
        self.assertEqual(0, stats["unreferenced_node_count"])
        self.assertEqual(2, stats["max_triangles_per_node"])

    def test_an_unwelded_soup_is_reported_unwelded_so_neighbourhoods_are_not_trusted(self) -> None:
        # The same square, but every triangle carries its own copy of each corner.
        soup_vertices = [
            0.0, 0.0, 0.0, 10.0, 0.0, 0.0, 10.0, 10.0, 0.0,
            0.0, 0.0, 0.0, 10.0, 10.0, 0.0, 0.0, 10.0, 0.0,
        ]
        stats = connectivity_statistics(soup_vertices, [0, 1, 2, 3, 4, 5])
        self.assertFalse(stats["welded"])
        self.assertEqual(6, stats["node_count"])
        self.assertEqual(4, stats["distinct_position_count"])
        self.assertEqual(2, stats["duplicate_position_node_count"])
        # And the adjacency really is gone: no interior edge survives the split.
        self.assertEqual(0, dihedral_statistics(soup_vertices, [0, 1, 2, 3, 4, 5])["interior_edge_count"])


class InlineTransportTests(unittest.TestCase):
    def _report(self, payload: bytes, chunk_bytes: int = 32) -> dict:
        chunks = []
        position = 0
        while position < len(payload):
            piece = payload[position : position + chunk_bytes]
            chunks.append(
                {
                    "index": len(chunks),
                    "sha256": hashlib.sha256(piece).hexdigest(),
                    "base64": base64.b64encode(piece).decode("ascii"),
                }
            )
            position += chunk_bytes
        return {
            "transport": "inline-base64",
            "dump_sha256": hashlib.sha256(payload).hexdigest(),
            "dump_chunk_count": len(chunks),
            "dump_chunks": chunks,
        }

    def test_the_fallback_reassembles_into_a_dump_that_parses(self) -> None:
        payload = packed()
        report = self._report(payload)
        rebuilt = assemble_inline_dump(report)
        self.assertEqual(payload, rebuilt)
        self.assertEqual(2, parse_mesh_dump(rebuilt, report["dump_sha256"]).triangle_count)

    def test_a_corrupted_chunk_is_caught_by_its_own_digest(self) -> None:
        report = self._report(packed())
        report["dump_chunks"][1]["base64"] = base64.b64encode(b"tampered").decode("ascii")
        with self.assertRaises(MeshDumpError) as caught:
            assemble_inline_dump(report)
        self.assertEqual("dump-hash-mismatch", caught.exception.reason)

    def test_a_malformed_transport_refuses_rather_than_returning_partial_bytes(self) -> None:
        payload = packed()
        cases = []
        dropped = self._report(payload)
        dropped["dump_chunks"].pop()
        cases.append(dropped)
        reordered = self._report(payload)
        reordered["dump_chunks"][0]["index"] = 5
        cases.append(reordered)
        shaped = self._report(payload)
        shaped["dump_chunks"][0] = {"index": 0, "base64": "AA=="}
        cases.append(shaped)
        cases.append({"transport": "file", "dump_path": "/tmp/x"})
        cases.append("not a report")
        for report in cases:
            with self.subTest(report=str(report)[:40]):
                with self.assertRaises(MeshDumpError):
                    assemble_inline_dump(report)

    def test_the_reassembled_bytes_are_still_bound_to_the_whole_dump_digest(self) -> None:
        report = self._report(packed())
        rebuilt = assemble_inline_dump(report)
        with self.assertRaises(MeshDumpError) as caught:
            parse_mesh_dump(rebuilt, "d" * 64)
        self.assertEqual("dump-hash-mismatch", caught.exception.reason)


class SharedSourceTests(unittest.TestCase):
    def test_the_shared_source_is_the_only_packer(self) -> None:
        # The host module and the generated transaction must run the same bytes
        # of source; a second implementation is how a binary format drifts.
        from fusion_design import mesh_dump

        module_text = Path(mesh_dump.__file__).read_text(encoding="utf-8")
        for name in ("pack_mesh_dump", "dihedral_statistics", "connectivity_statistics"):
            marker = "def " + name + "("
            self.assertIn(marker, mesh_dump._SHARED_SOURCE, name)
            self.assertEqual(1, module_text.count(marker), name)


if __name__ == "__main__":
    unittest.main()
