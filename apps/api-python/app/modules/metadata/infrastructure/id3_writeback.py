"""Replace selected ID3 frames while preserving every other frame byte-for-byte."""

from io import BytesIO
from typing import BinaryIO

from mutagen.id3 import ID3

from app.modules.metadata.application.standard_files import StandardMetadataError
from app.modules.metadata.infrastructure.audio_structure import read_at, syncsafe


def write_selected_id3(
    source: BinaryIO,
    output: BinaryIO,
    replacement: ID3,
    changed: frozenset[str],
    version: int,
) -> None:
    header = read_at(source, 0, 10)
    old_size = syncsafe(header[6:10])
    content = read_at(source, 10, old_size)
    kept = []
    offset = 0
    while offset < len(content) and content[offset] != 0:
        size = (
            syncsafe(content[offset + 4 : offset + 8])
            if version == 4
            else int.from_bytes(content[offset + 4 : offset + 8], "big")
        )
        frame = content[offset : offset + 10 + size]
        name = frame[:4].decode("ascii")
        selected = name in changed
        if name == "COMM" and selected:
            # Only the default English description, never language-specific comments.
            encoding = frame[10] if len(frame) > 10 else -1
            selected = False
            if frame[11:14] == b"eng":
                try:
                    codec = {0: "latin-1", 1: "utf-16", 2: "utf-16-be", 3: "utf-8"}[
                        encoding
                    ]
                    selected = frame[14:].decode(codec).split("\0", 1)[0] == ""
                except (KeyError, UnicodeError) as error:
                    raise StandardMetadataError("INVALID_ID3_DESCRIPTION") from error
        if not selected:
            kept.append(frame)
        offset += len(frame)
    encoded = BytesIO()
    replacement.save(encoded, v2_version=version, padding=lambda _: 0)
    new_frames = encoded.getvalue()[10:]
    body = b"".join(kept) + new_frames
    padding = max(0, old_size - len(body))
    body += b"\0" * padding
    size = len(body)
    new_header = header[:6] + bytes((size >> shift) & 127 for shift in (21, 14, 7, 0))
    output.seek(0)
    output.truncate()
    output.write(new_header)
    output.write(body)
    source.seek(10 + old_size)
    while chunk := source.read(1024**2):
        output.write(chunk)
    output.flush()
