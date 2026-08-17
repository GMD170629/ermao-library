"""Bounded random-access ISO-BMFF audio evidence without payload scanning."""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.catalog.domain.admission import AdmissionRejectionReason

from .source_file import OpenedSource

MAX_ISO_BMFF_BOXES = 4_096
MAX_ISO_BMFF_DEPTH = 16
MAX_ISO_BMFF_FTYP_PAYLOAD_BYTES = 4 * 1024
ISO_BMFF_PROBE_BYTE_BUDGET = MAX_ISO_BMFF_FTYP_PAYLOAD_BYTES + MAX_ISO_BMFF_BOXES * 24
_ISO_BMFF_AUDIO_BRANDS = frozenset(
    {b"M4A ", b"M4B ", b"isom", b"iso2", b"mp41", b"mp42", b"qt  "}
)
_EXPECTED_CHILD_CONTAINER = {
    None: b"moov",
    b"moov": b"trak",
    b"trak": b"mdia",
    b"mdia": b"minf",
    b"minf": b"stbl",
}


class _MalformedIsoBmff(Exception):
    pass


class _IsoBmffBudgetExceeded(Exception):
    pass


@dataclass(frozen=True, slots=True)
class _Box:
    box_type: bytes
    payload_start: int
    box_end: int


@dataclass(frozen=True, slots=True)
class IsoBmffProbeOutcome:
    rejection: AdmissionRejectionReason | None
    probe_bytes_examined: int


@dataclass(slots=True)
class _ProbeBudget:
    bytes_examined: int = 0
    box_count: int = 0

    def read_exact(self, source: OpenedSource, offset: int, size: int) -> bytes:
        if (
            offset < 0
            or size < 0
            or self.bytes_examined + size > ISO_BMFF_PROBE_BYTE_BUDGET
        ):
            raise _IsoBmffBudgetExceeded
        content = source.read_at(offset, size)
        self.bytes_examined += len(content)
        if len(content) != size:
            raise _MalformedIsoBmff
        return content

    def observe_box(self) -> None:
        self.box_count += 1
        if self.box_count > MAX_ISO_BMFF_BOXES:
            raise _IsoBmffBudgetExceeded


def _read_box(
    source: OpenedSource,
    offset: int,
    parent_end: int,
    budget: _ProbeBudget,
    *,
    initial_header: bytes | None = None,
) -> _Box:
    if offset < 0 or parent_end > source.size_bytes or offset + 8 > parent_end:
        raise _MalformedIsoBmff
    budget.observe_box()
    header = initial_header or budget.read_exact(source, offset, 8)
    if len(header) != 8:
        raise _MalformedIsoBmff
    declared_size = int.from_bytes(header[:4], "big")
    box_type = header[4:8]
    header_size = 8
    if declared_size == 1:
        declared_size = int.from_bytes(
            budget.read_exact(source, offset + 8, 8),
            "big",
        )
        header_size = 16
    elif declared_size == 0:
        raise _MalformedIsoBmff
    box_end = offset + declared_size
    if declared_size < header_size or box_end > parent_end:
        raise _MalformedIsoBmff
    return _Box(
        box_type=box_type,
        payload_start=offset + header_size,
        box_end=box_end,
    )


def _inspect_sample_descriptions(
    source: OpenedSource,
    box: _Box,
    budget: _ProbeBudget,
) -> bool:
    if box.payload_start + 8 > box.box_end:
        raise _MalformedIsoBmff
    full_box_header = budget.read_exact(source, box.payload_start, 8)
    if full_box_header[:4] != b"\x00\x00\x00\x00":
        raise _MalformedIsoBmff
    entry_count = int.from_bytes(full_box_header[4:8], "big")
    if entry_count > MAX_ISO_BMFF_BOXES:
        raise _IsoBmffBudgetExceeded

    cursor = box.payload_start + 8
    found_audio_sample = False
    for _entry_index in range(entry_count):
        sample_entry = _read_box(source, cursor, box.box_end, budget)
        if (
            sample_entry.box_type == b"mp4a"
            and sample_entry.box_end - sample_entry.payload_start >= 28
        ):
            found_audio_sample = True
        cursor = sample_entry.box_end
    if cursor != box.box_end:
        raise _MalformedIsoBmff
    return found_audio_sample


def _walk_box_sequence(
    source: OpenedSource,
    start: int,
    end: int,
    budget: _ProbeBudget,
    *,
    parent_type: bytes | None,
    depth: int,
) -> bool:
    if depth > MAX_ISO_BMFF_DEPTH:
        raise _IsoBmffBudgetExceeded
    expected_child = _EXPECTED_CHILD_CONTAINER.get(parent_type)
    found_audio_sample = False
    cursor = start
    while cursor < end:
        box = _read_box(source, cursor, end, budget)
        if expected_child is not None and box.box_type == expected_child:
            if _walk_box_sequence(
                source,
                box.payload_start,
                box.box_end,
                budget,
                parent_type=box.box_type,
                depth=depth + 1,
            ):
                found_audio_sample = True
        elif (
            parent_type == b"stbl"
            and box.box_type == b"stsd"
            and _inspect_sample_descriptions(source, box, budget)
        ):
            found_audio_sample = True
        cursor = box.box_end
    if cursor != end:
        raise _MalformedIsoBmff
    return found_audio_sample


def inspect_iso_bmff(source: OpenedSource) -> IsoBmffProbeOutcome:
    """Verify ISO-BMFF brands and an ``mp4a`` sample entry via box headers."""

    budget = _ProbeBudget()
    initial_size = min(8, source.size_bytes)
    initial_header = budget.read_exact(source, 0, initial_size)
    if len(initial_header) < 8 or initial_header[4:8] != b"ftyp":
        return IsoBmffProbeOutcome(
            AdmissionRejectionReason.SIGNATURE_MISMATCH,
            budget.bytes_examined,
        )
    try:
        ftyp = _read_box(
            source,
            0,
            source.size_bytes,
            budget,
            initial_header=initial_header,
        )
        ftyp_payload_size = ftyp.box_end - ftyp.payload_start
        if ftyp_payload_size < 8:
            raise _MalformedIsoBmff
        if ftyp_payload_size > MAX_ISO_BMFF_FTYP_PAYLOAD_BYTES:
            raise _IsoBmffBudgetExceeded
        brand_bytes = budget.read_exact(
            source,
            ftyp.payload_start,
            ftyp_payload_size,
        )
        if (len(brand_bytes) - 8) % 4:
            raise _MalformedIsoBmff
        brands = {brand_bytes[:4]}
        brands.update(
            brand_bytes[index : index + 4] for index in range(8, len(brand_bytes), 4)
        )
        if not brands & _ISO_BMFF_AUDIO_BRANDS:
            return IsoBmffProbeOutcome(
                AdmissionRejectionReason.SIGNATURE_MISMATCH,
                budget.bytes_examined,
            )
        found_audio_sample = _walk_box_sequence(
            source,
            ftyp.box_end,
            source.size_bytes,
            budget,
            parent_type=None,
            depth=0,
        )
    except _IsoBmffBudgetExceeded:
        return IsoBmffProbeOutcome(
            AdmissionRejectionReason.PROBE_BUDGET_EXCEEDED,
            budget.bytes_examined,
        )
    except _MalformedIsoBmff:
        return IsoBmffProbeOutcome(
            AdmissionRejectionReason.CORRUPT_SOURCE,
            budget.bytes_examined,
        )
    return IsoBmffProbeOutcome(
        None if found_audio_sample else AdmissionRejectionReason.SIGNATURE_MISMATCH,
        budget.bytes_examined,
    )


__all__ = [
    "ISO_BMFF_PROBE_BYTE_BUDGET",
    "MAX_ISO_BMFF_BOXES",
    "MAX_ISO_BMFF_DEPTH",
    "MAX_ISO_BMFF_FTYP_PAYLOAD_BYTES",
    "IsoBmffProbeOutcome",
    "inspect_iso_bmff",
]
