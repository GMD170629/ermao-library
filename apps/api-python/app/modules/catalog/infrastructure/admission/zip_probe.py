"""Bounded ZIP/EPUB central-directory evidence without extraction."""

from __future__ import annotations

import stat
import struct
import unicodedata
import zipfile
from dataclasses import dataclass
from itertools import pairwise
from xml.etree import ElementTree

from app.modules.catalog.domain.admission import (
    AdmissionRejectionReason,
    ArchiveEvidence,
)
from app.modules.catalog.domain.model import SourceFormat

from .bounded_reader import BoundedRandomAccess, ProbeBudgetExceeded
from .source_file import OpenedSource

MAX_ARCHIVE_ENTRIES = 10_000
MAX_CENTRAL_DIRECTORY_BYTES = 8 * 1024 * 1024
MAX_ARCHIVE_MEMBER_BYTES = 256 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100
MAX_EPUB_CONTROL_BYTES = 64 * 1024
_MAX_EOCD_BYTES = 65_535 + 22
_ZIP_PARSER_READ_BUDGET = 2 * MAX_CENTRAL_DIRECTORY_BYTES + 2 * 1024 * 1024
ZIP_PROBE_BYTE_BUDGET = (
    _MAX_EOCD_BYTES + MAX_CENTRAL_DIRECTORY_BYTES + _ZIP_PARSER_READ_BUDGET + 4
)
_EOCD_SIGNATURE = b"PK\x05\x06"
_CENTRAL_HEADER = struct.Struct("<4s6H3I5H2I")
_EOCD = struct.Struct("<4s4H2IH")
_IMAGE_SUFFIXES = frozenset({".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp"})


@dataclass(frozen=True, slots=True)
class _ZipMember:
    name: str
    normalized_key: str
    compressed_bytes: int
    uncompressed_bytes: int
    compression_method: int
    flags: int
    external_attributes: int
    local_header_offset: int
    directory: bool

    @property
    def encrypted(self) -> bool:
        return bool(self.flags & 0x41)

    @property
    def symlink(self) -> bool:
        return stat.S_ISLNK((self.external_attributes >> 16) & 0xFFFF)


@dataclass(frozen=True, slots=True)
class ZipProbeOutcome:
    evidence: ArchiveEvidence | None
    rejection: AdmissionRejectionReason | None
    probe_bytes_examined: int


def _archive_path_key(name: str, *, directory: bool) -> str | None:
    if not name or "\x00" in name or "\\" in name or name.startswith("/"):
        return None
    raw_path = name[:-1] if directory and name.endswith("/") else name
    if not raw_path or raw_path.endswith("/"):
        return None
    if len(raw_path) >= 2 and raw_path[0].isalpha() and raw_path[1] == ":":
        return None
    components = raw_path.split("/")
    if any(not component or component in {".", ".."} for component in components):
        return None
    normalized_components = tuple(
        unicodedata.normalize("NFC", component) for component in components
    )
    return "/".join(component.casefold() for component in normalized_components)


def _decode_member_name(raw_name: bytes, flags: int) -> str | None:
    try:
        return raw_name.decode("utf-8" if flags & 0x800 else "cp437", "strict")
    except UnicodeDecodeError:
        return None


def _read_central_directory(
    source: OpenedSource,
) -> tuple[tuple[_ZipMember, ...] | None, AdmissionRejectionReason | None, int]:
    tail = source.read_tail(_MAX_EOCD_BYTES)
    tail_offset = source.size_bytes - len(tail)
    relative_eocd_offset = tail.rfind(_EOCD_SIGNATURE)
    if relative_eocd_offset < 0 or len(tail) - relative_eocd_offset < _EOCD.size:
        return None, AdmissionRejectionReason.CORRUPT_SOURCE, len(tail)
    try:
        (
            _signature,
            disk_number,
            central_disk,
            entries_on_disk,
            total_entries,
            central_size,
            central_offset,
            comment_size,
        ) = _EOCD.unpack_from(tail, relative_eocd_offset)
    except struct.error:
        return None, AdmissionRejectionReason.CORRUPT_SOURCE, len(tail)
    eocd_offset = tail_offset + relative_eocd_offset
    if eocd_offset + _EOCD.size + comment_size != source.size_bytes:
        return None, AdmissionRejectionReason.CORRUPT_SOURCE, len(tail)
    if disk_number != 0 or central_disk != 0 or entries_on_disk != total_entries:
        return None, AdmissionRejectionReason.CORRUPT_SOURCE, len(tail)
    if (
        total_entries == 0xFFFF
        or central_size == 0xFFFFFFFF
        or central_offset == 0xFFFFFFFF
        or total_entries > MAX_ARCHIVE_ENTRIES
        or central_size > MAX_CENTRAL_DIRECTORY_BYTES
    ):
        return None, AdmissionRejectionReason.PROBE_BUDGET_EXCEEDED, len(tail)
    if central_offset + central_size > eocd_offset:
        return None, AdmissionRejectionReason.CORRUPT_SOURCE, len(tail)
    central = source.read_at(central_offset, central_size)
    examined = len(tail) + len(central)
    if len(central) != central_size:
        return None, AdmissionRejectionReason.CORRUPT_SOURCE, examined

    members: list[_ZipMember] = []
    normalized_names: set[str] = set()
    total_uncompressed = 0
    cursor = 0
    for _entry_index in range(total_entries):
        if cursor + _CENTRAL_HEADER.size > len(central):
            return None, AdmissionRejectionReason.CORRUPT_SOURCE, examined
        fields = _CENTRAL_HEADER.unpack_from(central, cursor)
        if fields[0] != b"PK\x01\x02":
            return None, AdmissionRejectionReason.CORRUPT_SOURCE, examined
        flags = fields[3]
        compression_method = fields[4]
        compressed_bytes = fields[8]
        uncompressed_bytes = fields[9]
        name_size, extra_size, member_comment_size = fields[10:13]
        disk_start = fields[13]
        external_attributes = fields[15]
        local_header_offset = fields[16]
        record_size = (
            _CENTRAL_HEADER.size + name_size + extra_size + member_comment_size
        )
        if cursor + record_size > len(central) or disk_start != 0:
            return None, AdmissionRejectionReason.CORRUPT_SOURCE, examined
        raw_name = central[
            cursor + _CENTRAL_HEADER.size : cursor + _CENTRAL_HEADER.size + name_size
        ]
        name = _decode_member_name(raw_name, flags)
        if name is None:
            return None, AdmissionRejectionReason.UNSAFE_ARCHIVE_PATH, examined
        directory = name.endswith("/")
        normalized_key = _archive_path_key(name, directory=directory)
        if normalized_key is None or normalized_key in normalized_names:
            return None, AdmissionRejectionReason.UNSAFE_ARCHIVE_PATH, examined
        normalized_names.add(normalized_key)
        member = _ZipMember(
            name=name,
            normalized_key=normalized_key,
            compressed_bytes=compressed_bytes,
            uncompressed_bytes=uncompressed_bytes,
            compression_method=compression_method,
            flags=flags,
            external_attributes=external_attributes,
            local_header_offset=local_header_offset,
            directory=directory,
        )
        if member.encrypted:
            return None, AdmissionRejectionReason.ENCRYPTED_ARCHIVE, examined
        if member.symlink:
            return None, AdmissionRejectionReason.UNSAFE_ARCHIVE_PATH, examined
        if compression_method not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            return None, AdmissionRejectionReason.CORRUPT_SOURCE, examined
        if (
            compressed_bytes == 0xFFFFFFFF
            or uncompressed_bytes == 0xFFFFFFFF
            or local_header_offset == 0xFFFFFFFF
            or uncompressed_bytes > MAX_ARCHIVE_MEMBER_BYTES
        ):
            return None, AdmissionRejectionReason.PROBE_BUDGET_EXCEEDED, examined
        if local_header_offset + 30 > central_offset:
            return None, AdmissionRejectionReason.CORRUPT_SOURCE, examined
        if compressed_bytes > central_offset - local_header_offset - 30:
            return None, AdmissionRejectionReason.CORRUPT_SOURCE, examined
        total_uncompressed += uncompressed_bytes
        if total_uncompressed > MAX_TOTAL_UNCOMPRESSED_BYTES:
            return None, AdmissionRejectionReason.PROBE_BUDGET_EXCEEDED, examined
        if uncompressed_bytes and (
            compressed_bytes == 0
            or uncompressed_bytes > compressed_bytes * MAX_COMPRESSION_RATIO
        ):
            return None, AdmissionRejectionReason.PROBE_BUDGET_EXCEEDED, examined
        members.append(member)
        cursor += record_size
    if cursor != len(central):
        return None, AdmissionRejectionReason.CORRUPT_SOURCE, examined
    minimum_local_regions = sorted(
        (
            member.local_header_offset,
            member.local_header_offset + 30 + member.compressed_bytes,
        )
        for member in members
    )
    if any(
        current_end > following_start
        for (_, current_end), (following_start, _) in pairwise(minimum_local_regions)
    ):
        return None, AdmissionRejectionReason.CORRUPT_SOURCE, examined
    return tuple(members), None, examined


def _read_zip_entry(
    archive: zipfile.ZipFile,
    member: zipfile.ZipInfo,
    *,
    maximum_bytes: int,
) -> bytes:
    with archive.open(member, "r") as stream:
        content = stream.read(maximum_bytes + 1)
    if len(content) > maximum_bytes:
        raise ProbeBudgetExceeded
    return content


def _container_is_valid(content: bytes, member_names: set[str]) -> bool:
    uppercase = content.upper()
    if b"<!DOCTYPE" in uppercase or b"<!ENTITY" in uppercase:
        return False
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError:
        return False
    if root.tag.rsplit("}", 1)[-1] != "container":
        return False
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "rootfile":
            continue
        full_path = element.attrib.get("full-path", "")
        key = _archive_path_key(full_path, directory=False)
        normalized_path = unicodedata.normalize("NFC", full_path)
        if key is not None and normalized_path in member_names:
            return True
    return False


def inspect_zip(
    source: OpenedSource,
    candidate_format: SourceFormat,
) -> ZipProbeOutcome:
    """Return bounded structural evidence for one ZIP-family source."""

    prefix = source.read_prefix(4)
    if prefix not in {b"PK\x03\x04", b"PK\x05\x06"}:
        return ZipProbeOutcome(
            evidence=None,
            rejection=AdmissionRejectionReason.SIGNATURE_MISMATCH,
            probe_bytes_examined=len(prefix),
        )
    members, rejection, examined = _read_central_directory(source)
    examined += len(prefix)
    if rejection is not None or members is None:
        return ZipProbeOutcome(None, rejection, examined)

    image_entry_count = sum(
        not member.directory
        and any(member.normalized_key.endswith(suffix) for suffix in _IMAGE_SUFFIXES)
        for member in members
    )
    total_compressed = sum(member.compressed_bytes for member in members)
    total_uncompressed = sum(member.uncompressed_bytes for member in members)
    mimetype_member = next(
        (member for member in members if member.name == "mimetype"),
        None,
    )
    container_member = next(
        (member for member in members if member.name == "META-INF/container.xml"),
        None,
    )
    has_mimetype = mimetype_member is not None
    has_container = container_member is not None
    if has_mimetype != has_container:
        return ZipProbeOutcome(
            None,
            AdmissionRejectionReason.CORRUPT_SOURCE,
            examined,
        )

    mimetype_verified = False
    container_verified = False
    if mimetype_member is not None and container_member is not None:
        try:
            raw = source.duplicate_binary()
            bounded = BoundedRandomAccess(
                raw,
                maximum_read_bytes=_ZIP_PARSER_READ_BUDGET,
            )
            with bounded, zipfile.ZipFile(bounded, "r") as archive:
                mimetype_info = archive.getinfo(mimetype_member.name)
                container_info = archive.getinfo(container_member.name)
                mimetype_content = _read_zip_entry(
                    archive,
                    mimetype_info,
                    maximum_bytes=64,
                )
                container_content = _read_zip_entry(
                    archive,
                    container_info,
                    maximum_bytes=MAX_EPUB_CONTROL_BYTES,
                )
                mimetype_verified = (
                    members[0].name == "mimetype"
                    and mimetype_member.local_header_offset == 0
                    and mimetype_member.compression_method == zipfile.ZIP_STORED
                    and mimetype_content == b"application/epub+zip"
                )
                container_verified = _container_is_valid(
                    container_content,
                    {
                        unicodedata.normalize("NFC", member.name)
                        for member in members
                        if not member.directory
                    },
                )
                examined += bounded.bytes_read
        except ProbeBudgetExceeded:
            return ZipProbeOutcome(
                None,
                AdmissionRejectionReason.PROBE_BUDGET_EXCEEDED,
                examined,
            )
        except (
            KeyError,
            LookupError,
            NotImplementedError,
            RuntimeError,
            ValueError,
            zipfile.BadZipFile,
        ):
            return ZipProbeOutcome(
                None,
                AdmissionRejectionReason.CORRUPT_SOURCE,
                examined,
            )

    if has_mimetype and (not mimetype_verified or not container_verified):
        return ZipProbeOutcome(
            None,
            AdmissionRejectionReason.CORRUPT_SOURCE,
            examined,
        )
    is_epub = mimetype_verified and container_verified
    if candidate_format is SourceFormat.EPUB and not is_epub:
        return ZipProbeOutcome(
            None,
            AdmissionRejectionReason.CORRUPT_SOURCE,
            examined,
        )
    if not is_epub and image_entry_count == 0:
        return ZipProbeOutcome(
            None,
            AdmissionRejectionReason.SIGNATURE_MISMATCH,
            examined,
        )
    source_format = SourceFormat.EPUB if is_epub else candidate_format
    try:
        evidence = ArchiveEvidence(
            source_format=source_format,
            entry_count=len(members),
            inspected_entry_count=len(members),
            entry_budget=MAX_ARCHIVE_ENTRIES,
            total_compressed_bytes=total_compressed,
            total_uncompressed_bytes=total_uncompressed,
            uncompressed_byte_budget=MAX_TOTAL_UNCOMPRESSED_BYTES,
            compression_ratio_limit=MAX_COMPRESSION_RATIO,
            probe_bytes_examined=examined,
            probe_byte_budget=ZIP_PROBE_BYTE_BUDGET,
            image_entry_count=0 if is_epub else image_entry_count,
            epub_mimetype_verified=is_epub,
            epub_container_verified=is_epub,
            comic_archive_verified=not is_epub,
        )
    except (TypeError, ValueError):
        return ZipProbeOutcome(
            None,
            AdmissionRejectionReason.CORRUPT_SOURCE,
            examined,
        )
    return ZipProbeOutcome(evidence, None, examined)


__all__ = [
    "MAX_ARCHIVE_ENTRIES",
    "MAX_ARCHIVE_MEMBER_BYTES",
    "MAX_CENTRAL_DIRECTORY_BYTES",
    "MAX_COMPRESSION_RATIO",
    "MAX_TOTAL_UNCOMPRESSED_BYTES",
    "ZIP_PROBE_BYTE_BUDGET",
    "ZipProbeOutcome",
    "inspect_zip",
]
