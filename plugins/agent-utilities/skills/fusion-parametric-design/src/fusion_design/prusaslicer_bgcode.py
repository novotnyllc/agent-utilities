"""Reader for PrusaSlicer binary G-code (.bgcode) containers.

Binary G-code is the Prusa XL presets' default output. The statistics we need
still live as ; key = value comment lines inside the container's G-code
blocks, so decoding the container is what lets slicing default to binary output
instead of forcing ASCII (the previous --binary-gcode=0 workaround).

Decoding is delegated to Prusa's official libbgcode (AGPL-3.0-or-later) via the
vendored WASM build invoked through Node. See THIRD_PARTY_NOTICES.md and
scripts/bgcode-decode.js. The hand-rolled parser this module once carried could
drift from the real container format; the vendor binding cannot.

WASM provenance: the vendored bgcode.wasm + bgcode.js are captured from the
libbgcode GitHub Actions build (workflow: build.yml, artifact:
libbgcode-wasm). The pinned commit and capture date are recorded in
wasm/PROVENANCE.md so the assets can be checked for upstream updates.

A leading gzip stream (some writers emit plain gzipped text instead of a true
container) and plain-text passthrough are still handled here without any
dependency. Everything malformed raises BgcodeError.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


MAGIC = b"GCDE"


class BgcodeError(ValueError):
    """A .bgcode container is malformed or uses an unsupported encoding."""


def _decode_with_wasm(path: Path) -> str:
    """Decode via the vendored libbgcode WASM module through Node."""
    import shutil

    node = shutil.which("node")
    if node is None:
        raise BgcodeError(
            f"Cannot decode binary G-code {str(path)!r}: Node.js is not on PATH "
            "(https://nodejs.org)."
        )
    script = Path(__file__).resolve().parent.parent.parent / "scripts" / "bgcode-decode.js"
    if not script.is_file():
        raise BgcodeError(
            f"Cannot decode binary G-code: wrapper not found at {str(script)!r}."
        )
    result = subprocess.run(
        [node, str(script), str(path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise BgcodeError(
            f"WASM bgcode decoder failed on {str(path)!r}: "
            f"{result.stderr.strip() or 'unknown error'}"
        )
    return result.stdout


def read_bgcode(path: str | Path) -> str:
    """Decode a .bgcode file and return its concatenated G-code text.

    True GCDE containers are decoded by the vendored libbgcode WASM build. A
    bare gzip stream and plain text pass through dependency-free.
    Malformed containers raise BgcodeError.
    """
    file_path = Path(path)
    with file_path.open("rb") as handle:
        header = handle.read(len(MAGIC))
        if header != MAGIC:
            handle.seek(0)
            import gzip

            payload = handle.read()
            try:
                return gzip.decompress(payload).decode("utf-8", errors="replace")
            except OSError:
                if payload[:2] == bytes([0x1f, 0x8b]):
                    raise BgcodeError(f"Corrupt gzip stream in {str(file_path)!r}.") from None
            # Not gzip either: plain text passthrough (the common case for a
            # .gcode file that arrives at read_bgcode by suffix confusion).
            handle.seek(0)
            return handle.read().decode("utf-8", errors="replace")
    return _decode_with_wasm(file_path)
