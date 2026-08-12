#!/usr/bin/env python3
"""Generate deterministic, non-book negative and extension fixtures for R5."""

from __future__ import annotations

import hashlib
import struct
import sys
from pathlib import Path


def first_record_offset(publication: bytes) -> int:
    if len(publication) < 82:
        raise ValueError("fixture is too small for a Palm database record table")
    return struct.unpack_from(">I", publication, 78)[0]


def write_fixture(path: Path, payload: bytes) -> str:
    path.write_bytes(payload)
    return f"{hashlib.sha256(payload).hexdigest()}  {path.name}"


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <shared-mobi-corpus>", file=sys.stderr)
        return 2
    corpus = Path(sys.argv[1]).resolve()
    source = (corpus / "01-basic-mobi6.mobi").read_bytes()
    record_zero = first_record_offset(source)
    if record_zero + 16 > len(source):
        raise ValueError("fixture record zero is out of range")

    outputs: list[str] = []
    outputs.append(write_fixture(corpus / "12-basic.prc", source))
    outputs.append(write_fixture(corpus / "13-basic.azw", source))
    outputs.append(write_fixture(corpus / "negative-truncated.mobi", source[:96]))
    pseudo_payload = b"This is deliberately not a Palm database or MOBI publication.\n"
    outputs.append(write_fixture(corpus / "negative-pseudo.mobi", pseudo_payload))
    outputs.append(write_fixture(corpus / "negative-synthetic-kfx.kfx", pseudo_payload))
    outputs.append(write_fixture(corpus / "negative-synthetic-azw4.azw4", pseudo_payload))

    drm_header = bytearray(source)
    struct.pack_into(">H", drm_header, record_zero + 12, 1)
    outputs.append(write_fixture(corpus / "negative-synthetic-drm-header.mobi", drm_header))

    no_content = bytearray(source)
    struct.pack_into(">I", no_content, record_zero + 4, 0)
    struct.pack_into(">H", no_content, record_zero + 8, 0)
    outputs.append(write_fixture(corpus / "negative-no-content.mobi", no_content))

    corrupt_offset = bytearray(source)
    struct.pack_into(">I", corrupt_offset, 78, len(source) + 4096)
    outputs.append(write_fixture(corpus / "negative-corrupt-record-offset.mobi", corrupt_offset))

    (corpus / "GENERATED-SHA256SUMS").write_text("\n".join(outputs) + "\n", encoding="ascii")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
