"""Bounded audio-container evidence excluding only explicitly mutable metadata."""

import hashlib
from typing import BinaryIO

from app.modules.metadata.application.standard_files import StandardMetadataError

MAX_AUDIO_METADATA = 8 * 1024**2
CHUNK = 1024**2


def read_at(stream: BinaryIO, offset: int, size: int) -> bytes:
    if size < 0 or size > MAX_AUDIO_METADATA:
        raise StandardMetadataError("AUDIO_STRUCTURE_LIMIT")
    stream.seek(offset)
    value = stream.read(size)
    if len(value) != size:
        raise StandardMetadataError("INVALID_AUDIO_STRUCTURE")
    return value


def size_of(stream: BinaryIO) -> int:
    return stream.seek(0, 2)


def range_hash(stream: BinaryIO, offset: int, size: int) -> str:
    stream.seek(offset)
    result = hashlib.sha256()
    while size:
        chunk = stream.read(min(CHUNK, size))
        if not chunk:
            raise StandardMetadataError("INVALID_AUDIO_STRUCTURE")
        result.update(chunk)
        size -= len(chunk)
    return result.hexdigest()


def syncsafe(raw: bytes) -> int:
    if len(raw) != 4 or any(value & 128 for value in raw):
        raise StandardMetadataError("INVALID_ID3_SIZE")
    return sum(value << (7 * (3 - index)) for index, value in enumerate(raw))


def mp3_structure(
    stream: BinaryIO, changed: frozenset[str], *, verify_payload: bool = True
) -> tuple[int, tuple[bytes, ...], str]:
    size = size_of(stream)
    header = read_at(stream, 0, 10)
    if header[:3] != b"ID3" or header[3] not in (3, 4) or header[4:6] != b"\0\0":
        raise StandardMetadataError("UNSUPPORTED_ID3_STRUCTURE")
    length = syncsafe(header[6:10])
    content = read_at(stream, 10, length)
    if size < length + 10 or (size >= 128 and read_at(stream, size - 128, 3) == b"TAG"):
        raise StandardMetadataError("UNSUPPORTED_ID3_V1")
    offset = 0
    preserved = []
    while offset < len(content):
        if content[offset] == 0:
            if content[offset:].strip(b"\0"):
                raise StandardMetadataError("INVALID_ID3_PADDING")
            break
        if len(content) - offset < 10:
            raise StandardMetadataError("INVALID_ID3_STRUCTURE")
        name = content[offset : offset + 4]
        raw_size = content[offset + 4 : offset + 8]
        length = (
            syncsafe(raw_size) if header[3] == 4 else int.from_bytes(raw_size, "big")
        )
        end = offset + 10 + length
        if (
            end > len(content)
            or not length
            or not all(48 <= byte <= 57 or 65 <= byte <= 90 for byte in name)
        ):
            raise StandardMetadataError("INVALID_ID3_STRUCTURE")
        frame = content[offset:end]
        if name == b"CHAP":
            terminator = frame.find(b"\0", 10)
            if (
                terminator < 0
                or len(frame) < terminator + 17
                or frame[terminator + 9 : terminator + 17] != b"\xff" * 8
            ):
                raise StandardMetadataError("UNSUPPORTED_CHAPTER_BYTE_OFFSETS")
        if name.decode("ascii") not in changed:
            preserved.append(frame)
        offset = end
    start = 10 + syncsafe(header[6:10])
    return (
        header[3],
        tuple(sorted(preserved)),
        range_hash(stream, start, size - start) if verify_payload else "",
    )


def flac_structure(
    stream: BinaryIO, *, verify_payload: bool = True
) -> tuple[tuple[tuple[int, str], ...], str]:
    if read_at(stream, 0, 4) != b"fLaC":
        raise StandardMetadataError("UNSUPPORTED_FLAC_STRUCTURE")
    offset = 4
    blocks = []
    metadata_size = 0
    for _ in range(10_000):
        header = read_at(stream, offset, 4)
        kind, length = header[0] & 127, int.from_bytes(header[1:], "big")
        metadata_size += length + 4
        if metadata_size > MAX_AUDIO_METADATA:
            raise StandardMetadataError("AUDIO_STRUCTURE_LIMIT")
        content = read_at(stream, offset + 4, length)
        if kind not in {1, 4}:
            blocks.append((kind, hashlib.sha256(content).hexdigest()))
        offset += length + 4
        if header[0] & 128:
            break
    else:
        raise StandardMetadataError("AUDIO_STRUCTURE_LIMIT")
    size = size_of(stream)
    if offset > size:
        raise StandardMetadataError("INVALID_AUDIO_STRUCTURE")
    return tuple(blocks), range_hash(
        stream, offset, size - offset
    ) if verify_payload else ""


def mp4_structure(
    stream: BinaryIO, *, verify_payload: bool = True
) -> tuple[tuple[str, str], ...]:
    size = size_of(stream)
    count = 0

    def atoms(start: int, end: int):
        nonlocal count
        offset = start
        while offset < end:
            count += 1
            if count > 100_000 or end - offset < 8:
                raise StandardMetadataError("AUDIO_STRUCTURE_LIMIT")
            header = read_at(stream, offset, 8)
            length, name = int.from_bytes(header[:4], "big"), header[4:]
            header_size = 8
            if length == 1:
                length = int.from_bytes(read_at(stream, offset + 8, 8), "big")
                header_size = 16
            if length == 0:
                length = end - offset
            if length < header_size or offset + length > end:
                raise StandardMetadataError("INVALID_MP4_ATOM")
            yield name, offset + header_size, offset + length
            offset += length

    top = tuple(atoms(0, size))
    if any(name in {b"moof", b"mfra"} for name, _, _ in top):
        raise StandardMetadataError("UNSUPPORTED_FRAGMENTED_MP4")
    if any(
        name == b"moov" and end - start > MAX_AUDIO_METADATA for name, start, end in top
    ):
        raise StandardMetadataError("AUDIO_STRUCTURE_LIMIT")
    media = [(start, end) for name, start, end in top if name == b"mdat"]
    if not media or sum(name == b"moov" for name, _, _ in top) != 1:
        raise StandardMetadataError("INVALID_MP4_STRUCTURE")
    result = []

    def visit(entries, prefix: str, depth: int) -> None:
        if depth > 16:
            raise StandardMetadataError("AUDIO_STRUCTURE_LIMIT")
        for name, start, end in entries:
            path = prefix + "/" + name.hex()
            if name in {b"free", b"skip"}:
                continue
            if name == b"ilst" and prefix.endswith("/75647461/6d657461"):
                if end - start > MAX_AUDIO_METADATA:
                    raise StandardMetadataError("AUDIO_STRUCTURE_LIMIT")
                continue
            if name in {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"udta", b"meta"}:
                if name == b"meta":
                    result.append((path + "/flags", read_at(stream, start, 4).hex()))
                    start += 4
                visit(atoms(start, end), path, depth + 1)
            elif name in {b"stco", b"co64"}:
                content = read_at(stream, start, end - start)
                width = 4 if name == b"stco" else 8
                if len(content) < 8 or len(content) != 8 + width * int.from_bytes(
                    content[4:8], "big"
                ):
                    raise StandardMetadataError("INVALID_CHUNK_OFFSETS")
                relative = []
                for index in range(8, len(content), width):
                    offset = int.from_bytes(content[index : index + width], "big")
                    locations = [
                        (part, offset - begin)
                        for part, (begin, finish) in enumerate(media)
                        if begin <= offset < finish
                    ]
                    if len(locations) != 1:
                        raise StandardMetadataError("INVALID_CHUNK_OFFSETS")
                    relative.append(locations[0])
                result.append(
                    (prefix + "/chunk_offsets", repr((content[:4], relative)))
                )
            else:
                if name in {b"senc", b"saio", b"saiz"}:
                    raise StandardMetadataError("ENCRYPTED_AUDIO")
                if name == b"stsd":
                    content = read_at(stream, start, end - start)
                    if b"enca" in content or b"sinf" in content:
                        raise StandardMetadataError("ENCRYPTED_AUDIO")
                result.append(
                    (
                        path,
                        range_hash(stream, start, end - start)
                        if verify_payload
                        else "",
                    )
                )

    visit(top, "", 0)
    return tuple(result)
