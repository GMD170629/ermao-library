"""Application boundary for read-only source admission probes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.modules.catalog.domain.admission import SourceAdmissionResult


class SourceAdmissionOperationalError(RuntimeError):
    """Stable operational failure whose message never contains a source path."""

    code = "SOURCE_ADMISSION_OPERATIONAL_ERROR"

    def __init__(self) -> None:
        super().__init__(self.code)


class InvalidSourceRelativePath(SourceAdmissionOperationalError):
    code = "INVALID_SOURCE_RELATIVE_PATH"


class SourceProbeIoError(SourceAdmissionOperationalError):
    code = "SOURCE_PROBE_IO_ERROR"


class SourceProbePermissionDenied(SourceAdmissionOperationalError):
    code = "SOURCE_PROBE_PERMISSION_DENIED"


class SourceProbeUnavailable(SourceAdmissionOperationalError):
    code = "SOURCE_PROBE_UNAVAILABLE"


class SourceChangedDuringProbe(SourceAdmissionOperationalError):
    code = "SOURCE_CHANGED_DURING_PROBE"


@dataclass(frozen=True, slots=True)
class SourceStatExpectation:
    """Portable stat facts captured by the scanner before a probe begins."""

    device_id: int
    file_id: int
    size_bytes: int
    modified_ns: int

    def __post_init__(self) -> None:
        for field_name in ("device_id", "file_id", "size_bytes"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if isinstance(self.modified_ns, bool) or not isinstance(self.modified_ns, int):
            raise TypeError("modified_ns must be an integer")


class SourceAdmissionPort(Protocol):
    """Probe one root-relative filesystem entry without mutating it."""

    def probe(
        self,
        *,
        canonical_root: str,
        relative_path: tuple[str, ...],
        expected_stat: SourceStatExpectation | None = None,
    ) -> SourceAdmissionResult: ...


__all__ = [
    "InvalidSourceRelativePath",
    "SourceAdmissionOperationalError",
    "SourceAdmissionPort",
    "SourceChangedDuringProbe",
    "SourceProbeIoError",
    "SourceProbePermissionDenied",
    "SourceProbeUnavailable",
    "SourceStatExpectation",
]
