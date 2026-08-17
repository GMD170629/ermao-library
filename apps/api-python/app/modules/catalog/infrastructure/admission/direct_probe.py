"""Bounded structural probes for non-archive source formats."""

from __future__ import annotations

import codecs
import re
from itertools import pairwise

from app.modules.catalog.domain.admission import (
    AdmissionRejectionReason,
    AudioCodec,
    AudioEvidence,
    DirectFileEvidence,
)
from app.modules.catalog.domain.model import SourceFormat

from .iso_bmff_probe import ISO_BMFF_PROBE_BYTE_BUDGET, inspect_iso_bmff
from .source_file import OpenedSource

MAX_PREFIX_BYTES = 64 * 1024
MAX_PDF_TAIL_BYTES = 2 * 1024
DIRECT_PROBE_BYTE_BUDGET = MAX_PREFIX_BYTES + MAX_PDF_TAIL_BYTES
_PDF_HEADER = re.compile(rb"%PDF-1\.[0-9]\b")
_MOBI_FORMATS = frozenset(
    {SourceFormat.MOBI, SourceFormat.AZW, SourceFormat.AZW3, SourceFormat.PRC}
)


def _is_synchsafe(value: bytes) -> bool:
    return len(value) == 4 and all(byte < 0x80 for byte in value)


def _synchsafe_size(value: bytes) -> int:
    return sum(byte << shift for byte, shift in zip(value, (21, 14, 7, 0)))


def _has_layer_three_frame(content: bytes, start: int) -> bool:
    for index in range(start, max(start, len(content) - 2)):
        first, second, third = content[index : index + 3]
        if first != 0xFF or second & 0xE0 != 0xE0:
            continue
        version = (second >> 3) & 0x03
        layer = (second >> 1) & 0x03
        bitrate_index = (third >> 4) & 0x0F
        sample_rate_index = (third >> 2) & 0x03
        if (
            version != 0x01
            and layer == 0x01
            and bitrate_index not in {0x00, 0x0F}
            and sample_rate_index != 0x03
        ):
            return True
    return False


def _mp3_rejection(prefix: bytes) -> AdmissionRejectionReason | None:
    frame_start = 0
    if prefix.startswith(b"ID3"):
        if len(prefix) < 10 or not _is_synchsafe(prefix[6:10]):
            return AdmissionRejectionReason.CORRUPT_SOURCE
        frame_start = 10 + _synchsafe_size(prefix[6:10])
        if prefix[5] & 0x10:
            frame_start += 10
        if frame_start >= len(prefix):
            return AdmissionRejectionReason.PROBE_BUDGET_EXCEEDED
    return (
        None
        if _has_layer_three_frame(prefix, frame_start)
        else AdmissionRejectionReason.SIGNATURE_MISMATCH
    )


def _pdf_rejection(prefix: bytes, tail: bytes) -> AdmissionRejectionReason | None:
    if _PDF_HEADER.match(prefix) is None:
        return AdmissionRejectionReason.SIGNATURE_MISMATCH
    eof_offset = tail.rfind(b"%%EOF")
    if eof_offset < 0 or b"startxref" not in tail[:eof_offset]:
        return AdmissionRejectionReason.CORRUPT_SOURCE
    return None


def _text_rejection(
    prefix: bytes,
    source_size: int,
) -> AdmissionRejectionReason | None:
    if not prefix:
        return AdmissionRejectionReason.CORRUPT_SOURCE
    content = prefix[3:] if prefix.startswith(b"\xef\xbb\xbf") else prefix
    try:
        decoder = codecs.getincrementaldecoder("utf-8")("strict")
        text = decoder.decode(content, final=source_size <= len(prefix))
    except UnicodeDecodeError:
        return AdmissionRejectionReason.SIGNATURE_MISMATCH
    if not text or not any(character.isprintable() for character in text):
        return AdmissionRejectionReason.CORRUPT_SOURCE
    if any(
        (ord(character) < 32 and character not in {"\t", "\n", "\r"})
        or ord(character) == 127
        for character in text
    ):
        return AdmissionRejectionReason.SIGNATURE_MISMATCH
    return None


def _pdb_record_offsets(
    prefix: bytes,
    source_size: int,
) -> tuple[int, ...] | AdmissionRejectionReason:
    if len(prefix) < 78:
        return AdmissionRejectionReason.CORRUPT_SOURCE
    record_count = int.from_bytes(prefix[76:78], "big")
    table_end = 78 + 8 * record_count
    if record_count == 0 or table_end > source_size:
        return AdmissionRejectionReason.CORRUPT_SOURCE
    if table_end > len(prefix):
        return AdmissionRejectionReason.PROBE_BUDGET_EXCEEDED
    offsets = tuple(
        int.from_bytes(prefix[index : index + 4], "big")
        for index in range(78, table_end, 8)
    )
    if (
        offsets[0] < table_end
        or offsets[-1] >= source_size
        or any(current >= following for current, following in pairwise(offsets))
    ):
        return AdmissionRejectionReason.CORRUPT_SOURCE
    return offsets


def _palmdoc_rejection(
    prefix: bytes,
    source_size: int,
    offsets: tuple[int, ...],
) -> AdmissionRejectionReason | None:
    first_record_offset = offsets[0]
    if first_record_offset + 16 > source_size:
        return AdmissionRejectionReason.CORRUPT_SOURCE
    if first_record_offset + 16 > len(prefix):
        return AdmissionRejectionReason.PROBE_BUDGET_EXCEEDED
    header = prefix[first_record_offset : first_record_offset + 16]
    compression = int.from_bytes(header[:2], "big")
    text_length = int.from_bytes(header[4:8], "big")
    text_record_count = int.from_bytes(header[8:10], "big")
    record_size = int.from_bytes(header[10:12], "big")
    encryption = int.from_bytes(header[12:14], "big")
    if (
        compression not in {1, 2}
        or text_length == 0
        or text_record_count == 0
        or text_record_count + 1 > len(offsets)
        or record_size == 0
        or encryption != 0
    ):
        return AdmissionRejectionReason.CORRUPT_SOURCE
    return None


def _mobi_rejection(
    prefix: bytes,
    source_size: int,
    source_format: SourceFormat,
) -> AdmissionRejectionReason | None:
    if len(prefix) < 68:
        return AdmissionRejectionReason.SIGNATURE_MISMATCH
    type_and_creator = prefix[60:68]
    if type_and_creator not in {b"BOOKMOBI", b"TEXtREAd"}:
        return AdmissionRejectionReason.SIGNATURE_MISMATCH
    if type_and_creator == b"TEXtREAd" and source_format is not SourceFormat.PRC:
        return AdmissionRejectionReason.SIGNATURE_MISMATCH
    offsets = _pdb_record_offsets(prefix, source_size)
    if isinstance(offsets, AdmissionRejectionReason):
        return offsets
    if type_and_creator == b"TEXtREAd":
        return _palmdoc_rejection(prefix, source_size, offsets)

    first_record_offset = offsets[0]
    if first_record_offset + 20 > source_size:
        return AdmissionRejectionReason.CORRUPT_SOURCE
    if first_record_offset + 20 > len(prefix):
        return AdmissionRejectionReason.PROBE_BUDGET_EXCEEDED
    compression = int.from_bytes(
        prefix[first_record_offset : first_record_offset + 2], "big"
    )
    encryption = int.from_bytes(
        prefix[first_record_offset + 12 : first_record_offset + 14], "big"
    )
    if (
        compression not in {1, 2, 17_480}
        or encryption != 0
        or prefix[first_record_offset + 16 : first_record_offset + 20] != b"MOBI"
    ):
        return AdmissionRejectionReason.CORRUPT_SOURCE
    return None


def inspect_direct(
    source: OpenedSource,
    source_format: SourceFormat,
) -> DirectFileEvidence | AudioEvidence | AdmissionRejectionReason:
    """Inspect one direct file through its format-specific bounded evidence."""

    if source_format in {SourceFormat.M4A, SourceFormat.M4B}:
        outcome = inspect_iso_bmff(source)
        if outcome.rejection is not None:
            return outcome.rejection
        return AudioEvidence(
            source_format=source_format,
            codec=AudioCodec.AAC,
            probe_bytes_examined=outcome.probe_bytes_examined,
            probe_byte_budget=ISO_BMFF_PROBE_BYTE_BUDGET,
        )

    prefix = source.read_prefix(MAX_PREFIX_BYTES)
    examined = len(prefix)
    rejection: AdmissionRejectionReason | None
    if source_format is SourceFormat.MP3:
        rejection = _mp3_rejection(prefix)
        if rejection is None:
            return AudioEvidence(
                source_format=source_format,
                codec=AudioCodec.MPEG_LAYER_III,
                probe_bytes_examined=examined,
                probe_byte_budget=DIRECT_PROBE_BYTE_BUDGET,
            )
    elif source_format is SourceFormat.PDF:
        tail = source.read_tail(MAX_PDF_TAIL_BYTES)
        examined += len(tail)
        rejection = _pdf_rejection(prefix, tail)
    elif source_format is SourceFormat.TXT:
        rejection = _text_rejection(prefix, source.size_bytes)
    elif source_format in _MOBI_FORMATS:
        rejection = _mobi_rejection(prefix, source.size_bytes, source_format)
    else:
        rejection = AdmissionRejectionReason.UNSUPPORTED_EXTENSION
    if rejection is not None:
        return rejection
    return DirectFileEvidence(
        source_format=source_format,
        probe_bytes_examined=examined,
        probe_byte_budget=DIRECT_PROBE_BYTE_BUDGET,
    )


__all__ = [
    "DIRECT_PROBE_BYTE_BUDGET",
    "MAX_PDF_TAIL_BYTES",
    "MAX_PREFIX_BYTES",
    "inspect_direct",
]
