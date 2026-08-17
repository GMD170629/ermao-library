"""Bounded RAR/CBR directory evidence without extracting members."""

from __future__ import annotations

import io
import struct
import unicodedata
from dataclasses import dataclass
from typing import Protocol

import rarfile  # type: ignore[import-untyped]  # Package has no typing marker.

from app.modules.catalog.application.source_admission_ports import (
    SourceProbeIoError,
    SourceProbeUnavailable,
)
from app.modules.catalog.domain.admission import (
    AdmissionRejectionReason,
    ArchiveEvidence,
)
from app.modules.catalog.domain.model import SourceFormat

from .bounded_reader import BoundedRandomAccess, ProbeBudgetExceeded
from .source_file import OpenedSource

MAX_RAR_ENTRIES = 10_000
MAX_RAR_HEADER_READ_BYTES = 8 * 1024 * 1024
MAX_RAR_MEMBER_BYTES = 256 * 1024 * 1024
MAX_RAR_TOTAL_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_RAR_COMPRESSION_RATIO = 100
RAR_PROBE_BYTE_BUDGET = MAX_RAR_HEADER_READ_BYTES + 8
_RAR4_SIGNATURE = b"Rar!\x1a\x07\x00"
_RAR5_SIGNATURE = b"Rar!\x1a\x07\x01\x00"
_IMAGE_SUFFIXES = frozenset({".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp"})


class _MalformedRar(Exception):
    pass


@dataclass(frozen=True, slots=True)
class RarMemberFact:
    """Validated facts returned by an injected read-only RAR directory backend."""

    name: str
    compressed_bytes: int
    uncompressed_bytes: int
    directory: bool = False
    symlink_or_redirection: bool = False
    encrypted: bool = False
    continuation_volume: bool = False


class RarDirectoryBackend(Protocol):
    """Obtain RAR directory facts without opening or extracting a member."""

    def inspect(self, source: io.BufferedIOBase) -> tuple[RarMemberFact, ...]: ...


def _integer_attribute(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _MalformedRar
    return value


class RarfileDirectoryBackend:
    """RAR directory backend backed by ``rarfile`` and an installed CLI tool."""

    def inspect(self, source: io.BufferedIOBase) -> tuple[RarMemberFact, ...]:
        try:
            rarfile.tool_setup()
        except (OSError, rarfile.RarCannotExec) as error:
            raise SourceProbeUnavailable() from error

        try:
            with rarfile.RarFile(source, "r", errors="strict") as archive:
                archive_encrypted = bool(archive.needs_password())
                raw_members = archive.infolist()
                members: list[RarMemberFact] = []
                for raw_member in raw_members:
                    name = raw_member.filename
                    if not isinstance(name, str):
                        raise _MalformedRar
                    members.append(
                        RarMemberFact(
                            name=name,
                            compressed_bytes=_integer_attribute(
                                raw_member.compress_size
                            ),
                            uncompressed_bytes=_integer_attribute(raw_member.file_size),
                            directory=bool(raw_member.is_dir()),
                            symlink_or_redirection=bool(
                                raw_member.is_symlink()
                                or raw_member.file_redir is not None
                            ),
                            encrypted=bool(
                                archive_encrypted or raw_member.needs_password()
                            ),
                            continuation_volume=_integer_attribute(raw_member.volume)
                            != 0,
                        )
                    )
                return tuple(members)
        except SourceProbeUnavailable:
            raise
        except rarfile.RarCannotExec as error:
            raise SourceProbeUnavailable() from error
        except OSError as error:
            raise SourceProbeIoError() from error
        except (
            EOFError,
            TypeError,
            ValueError,
            struct.error,
            rarfile.Error,
        ) as error:
            raise _MalformedRar from error


@dataclass(frozen=True, slots=True)
class RarProbeOutcome:
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
    return "/".join(
        unicodedata.normalize("NFC", component).casefold() for component in components
    )


def inspect_rar(
    source: OpenedSource,
    source_format: SourceFormat,
    backend: RarDirectoryBackend,
) -> RarProbeOutcome:
    """Return bounded comic-archive evidence from a configured RAR backend."""

    prefix = source.read_prefix(8)
    if not (prefix.startswith(_RAR4_SIGNATURE) or prefix == _RAR5_SIGNATURE):
        return RarProbeOutcome(
            evidence=None,
            rejection=AdmissionRejectionReason.SIGNATURE_MISMATCH,
            probe_bytes_examined=len(prefix),
        )

    try:
        raw = source.duplicate_binary()
        bounded = BoundedRandomAccess(
            raw,
            maximum_read_bytes=MAX_RAR_HEADER_READ_BYTES,
        )
        with bounded:
            members = backend.inspect(bounded)
        examined = len(prefix) + bounded.bytes_read
    except ProbeBudgetExceeded:
        return RarProbeOutcome(
            None,
            AdmissionRejectionReason.PROBE_BUDGET_EXCEEDED,
            len(prefix) + MAX_RAR_HEADER_READ_BYTES,
        )
    except _MalformedRar:
        return RarProbeOutcome(
            None,
            AdmissionRejectionReason.CORRUPT_SOURCE,
            len(prefix),
        )

    if not members:
        return RarProbeOutcome(
            None,
            AdmissionRejectionReason.CORRUPT_SOURCE,
            examined,
        )
    if len(members) > MAX_RAR_ENTRIES:
        return RarProbeOutcome(
            None,
            AdmissionRejectionReason.PROBE_BUDGET_EXCEEDED,
            examined,
        )

    normalized_names: set[str] = set()
    total_compressed = 0
    total_uncompressed = 0
    image_entry_count = 0
    for member in members:
        key = _archive_path_key(member.name, directory=member.directory)
        if key is None or key in normalized_names or member.symlink_or_redirection:
            return RarProbeOutcome(
                None,
                AdmissionRejectionReason.UNSAFE_ARCHIVE_PATH,
                examined,
            )
        normalized_names.add(key)
        if member.encrypted:
            return RarProbeOutcome(
                None,
                AdmissionRejectionReason.ENCRYPTED_ARCHIVE,
                examined,
            )
        if member.continuation_volume:
            return RarProbeOutcome(
                None,
                AdmissionRejectionReason.CORRUPT_SOURCE,
                examined,
            )
        if (
            member.uncompressed_bytes > MAX_RAR_MEMBER_BYTES
            or member.uncompressed_bytes
            and (
                member.compressed_bytes == 0
                or member.uncompressed_bytes
                > member.compressed_bytes * MAX_RAR_COMPRESSION_RATIO
            )
        ):
            return RarProbeOutcome(
                None,
                AdmissionRejectionReason.PROBE_BUDGET_EXCEEDED,
                examined,
            )
        total_compressed += member.compressed_bytes
        total_uncompressed += member.uncompressed_bytes
        if total_uncompressed > MAX_RAR_TOTAL_UNCOMPRESSED_BYTES:
            return RarProbeOutcome(
                None,
                AdmissionRejectionReason.PROBE_BUDGET_EXCEEDED,
                examined,
            )
        if not member.directory and any(
            key.endswith(suffix) for suffix in _IMAGE_SUFFIXES
        ):
            image_entry_count += 1

    if image_entry_count == 0:
        return RarProbeOutcome(
            None,
            AdmissionRejectionReason.SIGNATURE_MISMATCH,
            examined,
        )
    try:
        evidence = ArchiveEvidence(
            source_format=source_format,
            entry_count=len(members),
            inspected_entry_count=len(members),
            entry_budget=MAX_RAR_ENTRIES,
            total_compressed_bytes=total_compressed,
            total_uncompressed_bytes=total_uncompressed,
            uncompressed_byte_budget=MAX_RAR_TOTAL_UNCOMPRESSED_BYTES,
            compression_ratio_limit=MAX_RAR_COMPRESSION_RATIO,
            probe_bytes_examined=examined,
            probe_byte_budget=RAR_PROBE_BYTE_BUDGET,
            image_entry_count=image_entry_count,
            comic_archive_verified=True,
        )
    except (TypeError, ValueError):
        return RarProbeOutcome(
            None,
            AdmissionRejectionReason.CORRUPT_SOURCE,
            examined,
        )
    return RarProbeOutcome(evidence, None, examined)


__all__ = [
    "MAX_RAR_COMPRESSION_RATIO",
    "MAX_RAR_ENTRIES",
    "MAX_RAR_HEADER_READ_BYTES",
    "MAX_RAR_MEMBER_BYTES",
    "MAX_RAR_TOTAL_UNCOMPRESSED_BYTES",
    "RAR_PROBE_BYTE_BUDGET",
    "RarDirectoryBackend",
    "RarMemberFact",
    "RarProbeOutcome",
    "RarfileDirectoryBackend",
    "inspect_rar",
]
