"""Reader for PrusaSlicer binary G-code (.bgcode) containers.

Binary G-code is the Prusa XL presets' default output. The statistics we need
still live as ``; key = value`` comment lines inside the container's G-code
blocks, so decoding the container is what lets slicing default to binary output
instead of forcing ASCII (the previous ``--binary-gcode=0`` workaround).

Format (bgcode open format, little-endian throughout):

* 5-byte file header: magic b"GCDE" then a 1-byte version (must be 1).
* A sequence of blocks. Each block header is 10 bytes: a 2-byte bitfield
  (low 5 bits = block type, bits 5-7 = compression), a 4-byte compressed
  payload size, then a 4-byte *uncompressed* payload size.
* G-code block payloads are UTF-8 text, optionally compressed. Metadata and
  thumbnail blocks are skipped without decoding; unknown block types are
  skipped too -- the statistics live only in G-code blocks, so anything else
  cannot change what we report.

Compression: 0 = none, 1 = gzip/deflate via zlib, 2 = heatshrink. A
heatshrink block starts with a 1-byte header: high nibble = window bits
(2^n bytes), low nibble = lookahead bits. The bitstream is MSB-first: each
token begins with a tag bit -- 0 emits one literal byte, 1 emits a back
reference of window-bits index then lookahead-bits count (index + 1 bytes
copied from that far behind the current output position; overlapping copies
allowed). This decoder reads the parameters from the header rather than
assuming the encoder's defaults, because a wrong window silently corrupts
statistics into plausible-looking numbers.

Everything malformed raises BgcodeError -- a corrupt container must surface
as a structured slice failure, never as silently missing statistics.
"""

from __future__ import annotations

import io
import struct
import zlib
from pathlib import Path


MAGIC = b"GCDE"
FORMAT_VERSION = 1
_FILE_HEADER_SIZE = len(MAGIC) + 1
_BLOCK_HEADER_SIZE = 10
_BLOCK_HEADER = struct.Struct("<IIH")

BLOCK_TYPE_GCODE = 0
BLOCK_TYPE_METADATA = 3
BLOCK_TYPE_FILE_METADATA = 5
BLOCK_TYPE_PRINTER_METADATA = 6
BLOCK_TYPE_PRINT_METADATA = 7
BLOCK_TYPE_THUMBNAIL = 8

COMPRESSION_NONE = 0
COMPRESSION_DEFLATE = 1
COMPRESSION_HEATSHRINK = 2


class BgcodeError(ValueError):
    """A .bgcode container is malformed or uses an unsupported encoding."""


def _read_exact(handle: io.BufferedIOBase, count: int, what: str) -> bytes:
    data = handle.read(count)
    if len(data) != count:
        raise BgcodeError(f"Truncated .bgcode: {what} needs {count} bytes, got {len(data)}.")
    return data


def _heatshrink_decode(payload: bytes, window_sz2: int, lookahead_sz2: int) -> bytes:
    """Decode a heatshrink-compressed block body (parameter header stripped).

    The parameters come from the block's own 1-byte header, never assumed:
    decoding with a window different from the encoder's silently corrupts text
    into plausible-looking numbers.
    """
    if not 4 <= window_sz2 <= 15:
        raise BgcodeError(f"Unsupported heatshrink window size 2^{window_sz2} in block header.")
    if not 3 <= lookahead_sz2 < window_sz2:
        raise BgcodeError(f"Unsupported heatshrink lookahead size 2^{lookahead_sz2} in block header.")

    out = bytearray()
    # MSB-first bit reader over the whole payload.
    bits = int.from_bytes(payload, "big")
    total_bits = len(payload) * 8
    position = 0

    def take(count: int) -> int:
        nonlocal position
        if position + count > total_bits:
            raise BgcodeError("Truncated heatshrink bitstream in .bgcode block.")
        shift = total_bits - position - count
        position += count
        return (bits >> shift) & ((1 << count) - 1)

    # The encoder zero-pads the final byte, and a pad is never long enough to
    # form a whole token (a literal needs 9 bits, a back reference
    # 1 + window + lookahead), so stop once less than the smallest possible
    # token remains instead of decoding the padding as data.
    smallest_token_bits = min(9, 1 + window_sz2 + lookahead_sz2)
    while total_bits - position >= smallest_token_bits:
        if take(1) == 0:
            out.append(take(8))
            continue
        index = take(window_sz2)
        count = take(lookahead_sz2) + 1
        start = len(out) - index - 1
        if start < 0:
            raise BgcodeError("Heatshrink back reference points before the start of the block output.")
        # Overlapping copies (count > index + 1) repeat the window, byte by byte.
        for offset in range(count):
            out.append(out[start + offset])
    return bytes(out)


def _decode_block_payload(payload: bytes, compression: int) -> bytes:
    if compression == COMPRESSION_NONE:
        return payload
    if compression == COMPRESSION_DEFLATE:
        try:
            # wbits=47 auto-detects zlib and gzip framing; the bgcode writer
            # emits gzip bytes, and plain zlib.decompress() rejects those.
            return zlib.decompress(payload, 47)
        except zlib.error as error:
            raise BgcodeError(f"Corrupt gzip/deflate block in .bgcode: {error}") from error
    if compression == COMPRESSION_HEATSHRINK:
        if not payload:
            raise BgcodeError("Empty heatshrink block in .bgcode: the parameter header is missing.")
        return _heatshrink_decode(payload[1:], payload[0] >> 4, payload[0] & 0x0F)
    raise BgcodeError(f"Unsupported block compression {compression} in .bgcode.")


def read_bgcode(path: str | Path) -> str:
    """Decode a .bgcode file and return the concatenated G-code text.

    G-code blocks are joined in file order. Metadata and thumbnail blocks are
    skipped; unknown block types are skipped too -- the statistics this project
    parses live only in G-code blocks, so anything else cannot change what is
    reported. Malformed containers raise BgcodeError.
    """
    parts: list[bytes] = []
    with Path(path).open("rb") as handle:
        header = _read_exact(handle, _FILE_HEADER_SIZE, "file header")
        if header[: len(MAGIC)] != MAGIC:
            # A bare gzip stream is not a container, but it is a real G-code
            # payload (some writers emit plain gzipped text); decoding it here
            # keeps the caller's binary mode honest without inventing a second
            # entry point for "gzip but not bgcode".
            handle.seek(0)
            import gzip

            try:
                return gzip.decompress(handle.read()).decode("utf-8")
            except OSError:
                raise BgcodeError(
                    f"Not a .bgcode file: expected magic {MAGIC!r}, got {header[: len(MAGIC)]!r}."
                ) from None
        if header[len(MAGIC)] != FORMAT_VERSION:
            raise BgcodeError(
                f"Unsupported .bgcode format version {header[len(MAGIC)]}; expected {FORMAT_VERSION}."
            )
        block_number = 0
        while True:
            header_bytes = handle.read(_BLOCK_HEADER_SIZE)
            if not header_bytes:
                break  # clean EOF after the last block
            if len(header_bytes) != _BLOCK_HEADER_SIZE:
                raise BgcodeError("Truncated .bgcode: block header is incomplete.")
            block_number += 1
            compressed_size, uncompressed_size, flags = _BLOCK_HEADER.unpack(header_bytes)
            block_type = flags & 0x1F
            compression = (flags >> 5) & 0x07
            payload = _read_exact(handle, compressed_size, f"payload of block {block_number}")
            if block_type != BLOCK_TYPE_GCODE:
                continue
            decoded = _decode_block_payload(payload, compression)
            if len(decoded) != uncompressed_size:
                raise BgcodeError(
                    f"G-code block {block_number} decoded to {len(decoded)} bytes; "
                    f"its header declares {uncompressed_size}."
                )
            parts.append(decoded)
    if not parts:
        raise BgcodeError("The .bgcode container holds no G-code block, so no statistics can exist in it.")
    return b"".join(parts).decode("utf-8", errors="replace")
