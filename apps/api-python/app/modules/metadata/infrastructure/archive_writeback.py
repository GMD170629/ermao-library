"""Stream-copy EPUB/CBZ members while changing only the selected metadata member."""

import hashlib
import stat
from copy import copy
from dataclasses import dataclass
from io import BufferedIOBase
from typing import BinaryIO, Literal
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from app.contracts.publication_metadata import PublicationMetadata
from app.infrastructure.epub_metadata import read_epub_package, read_zip_metadata
from app.modules.metadata.application.standard_files import StandardMetadataError
from app.modules.metadata.infrastructure.selective_comicinfo import patch_comicinfo
from app.modules.metadata.infrastructure.selective_opf import (
    parse_editable_opf,
    patch_opf_metadata,
)

ARCHIVE_MEMBER_LIMIT = 10_000
ARCHIVE_CONTENT_LIMIT = 100 * 1024**3
ARCHIVE_CHUNK_SIZE = 1024**2


class BoundedArchiveStream(BufferedIOBase):
    """Cap each ZIP parser allocation, including central-directory and EOCD reads."""

    def __init__(self, stream: BinaryIO) -> None:
        self.stream = stream

    def read(self, size: int | None = -1) -> bytes:
        if size is None or size < 0:
            position = self.stream.tell()
            size = self.stream.seek(0, 2) - position
            self.stream.seek(position)
            if size > 65558:
                raise StandardMetadataError("ARCHIVE_TAIL_LIMIT")
        if size > 8 * 1024**2:
            raise StandardMetadataError("ARCHIVE_STRUCTURE_LIMIT")
        return self.stream.read(size)

    def seek(self, offset: int, whence: int = 0) -> int:
        return self.stream.seek(offset, whence)

    def tell(self) -> int:
        return self.stream.tell()

    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True


@dataclass(frozen=True)
class ArchiveWriteProof:
    metadata_member: str
    unchanged_members: tuple[tuple[str, str], ...]


def inspect_archive_entries(archive: ZipFile) -> list[ZipInfo]:
    entries = archive.infolist()
    if (
        len(entries) > ARCHIVE_MEMBER_LIMIT
        or sum(item.file_size for item in entries) > ARCHIVE_CONTENT_LIMIT
    ):
        raise StandardMetadataError("ARCHIVE_LIMIT")
    names = [item.filename for item in entries]
    if len(names) != len(set(names)):
        raise StandardMetadataError("DUPLICATE_ARCHIVE_MEMBER")
    for item in entries:
        name = item.filename.rstrip("/")
        if (
            not name
            or name.startswith("/")
            or "\\" in name
            or any(part in {"", ".", ".."} for part in name.split("/"))
            or stat.S_ISLNK(item.external_attr >> 16)
        ):
            raise StandardMetadataError("UNSAFE_ARCHIVE_MEMBER")
        if item.flag_bits & 1:
            raise StandardMetadataError("ENCRYPTED_FILE_UNSUPPORTED")
        if item.compress_type not in {ZIP_DEFLATED, ZIP_STORED}:
            raise StandardMetadataError("ARCHIVE_COMPRESSION_UNSUPPORTED")
    return entries


def preview_archive_metadata(
    archive: ZipFile,
    format: Literal["EPUB", "CBZ", "ZIP"],
    values: PublicationMetadata,
    fields: frozenset[str],
) -> tuple[str, bytes]:
    names = archive.namelist()
    if format == "EPUB":
        folded = {name.casefold() for name in names}
        if {"meta-inf/encryption.xml", "meta-inf/signatures.xml"} & folded:
            raise StandardMetadataError("SIGNED_OR_ENCRYPTED_EPUB_UNSUPPORTED")
        if (
            not names
            or names[0] != "mimetype"
            or archive.getinfo("mimetype").compress_type != ZIP_STORED
            or read_zip_metadata(archive, "mimetype") != b"application/epub+zip"
        ):
            raise StandardMetadataError("INVALID_EPUB_CONTAINER")
        name, original = read_epub_package(archive)
        changed = patch_opf_metadata(original, values, fields)
        package, metadata = parse_editable_opf(changed)
        dc = "{http://purl.org/dc/elements/1.1/}"
        unique = package.get("unique-identifier")
        if not unique or not any(
            node.get("id") == unique and node.text
            for node in metadata.findall(dc + "identifier")
        ):
            raise StandardMetadataError("PRIMARY_IDENTIFIER_REQUIRED")
        for required in ("title", "language"):
            if not any(node.text for node in metadata.findall(dc + required)):
                raise StandardMetadataError("EPUB_REQUIRED_METADATA")
        return name, changed
    candidates = [
        name for name in names if name.rsplit("/", 1)[-1].casefold() == "comicinfo.xml"
    ]
    if len(candidates) > 1 or (candidates and "/" in candidates[0]):
        raise StandardMetadataError("AMBIGUOUS_COMICINFO")
    name = candidates[0] if candidates else "ComicInfo.xml"
    return name, patch_comicinfo(
        read_zip_metadata(archive, name) if candidates else None, values, fields
    )


def write_archive_metadata(
    source: BinaryIO,
    destination: BinaryIO,
    *,
    format: Literal["EPUB", "CBZ", "ZIP"],
    values: PublicationMetadata,
    fields: frozenset[str],
) -> ArchiveWriteProof:
    if source is destination:
        raise StandardMetadataError("SEPARATE_PREPARATION_REQUIRED")
    if destination.seek(0, 2) != 0:
        raise StandardMetadataError("EMPTY_PREPARATION_REQUIRED")
    with ZipFile(BoundedArchiveStream(source)) as original:
        entries = inspect_archive_entries(original)
        member, changed = preview_archive_metadata(original, format, values, fields)
        hashes: list[tuple[str, str]] = []
        with ZipFile(destination, "w") as output:
            output.comment = original.comment
            for entry in entries:
                if entry.filename == member:
                    output.writestr(copy(entry), changed)
                    continue
                digest = hashlib.sha256()
                size = 0
                with (
                    original.open(entry) as reader,
                    output.open(
                        copy(entry), "w", force_zip64=entry.file_size >= 2**31
                    ) as writer,
                ):
                    while chunk := reader.read(ARCHIVE_CHUNK_SIZE):
                        size += len(chunk)
                        if size > entry.file_size:
                            raise StandardMetadataError("ARCHIVE_MEMBER_SIZE_CHANGED")
                        writer.write(chunk)
                        digest.update(chunk)
                if size != entry.file_size:
                    raise StandardMetadataError("ARCHIVE_MEMBER_SIZE_CHANGED")
                hashes.append((entry.filename, digest.hexdigest()))
            if member not in original.namelist():
                output.writestr(member, changed, compress_type=ZIP_DEFLATED)
    destination.flush()
    destination.seek(0)
    with ZipFile(BoundedArchiveStream(destination)) as verified:
        if verified.namelist() != [entry.filename for entry in entries] + (
            [member] if member not in [entry.filename for entry in entries] else []
        ):
            raise StandardMetadataError("ARCHIVE_ORDER_CHANGED")
        if read_zip_metadata(verified, member) != changed:
            raise StandardMetadataError("METADATA_READBACK_FAILED")
        for name, expected in hashes:
            digest = hashlib.sha256()
            with verified.open(name) as reader:
                while chunk := reader.read(ARCHIVE_CHUNK_SIZE):
                    digest.update(chunk)
            if digest.hexdigest() != expected:
                raise StandardMetadataError("ARCHIVE_CONTENT_CHANGED")
    return ArchiveWriteProof(member, tuple(hashes))
