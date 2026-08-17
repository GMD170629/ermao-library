"""Read-only host filesystem adapter for topology-v1 source admission."""

from __future__ import annotations

from collections.abc import Callable

from app.modules.catalog.application.source_admission_ports import (
    SourceAdmissionOperationalError,
    SourceAdmissionPort,
    SourceProbeIoError,
    SourceProbePermissionDenied,
    SourceStatExpectation,
)
from app.modules.catalog.domain.admission import (
    AdmissionRejectionReason,
    AudioEvidence,
    SourceAdmissionEvidence,
    SourceAdmissionRejection,
    SourceAdmissionResult,
    is_system_noise_name,
)
from app.modules.catalog.domain.model import (
    AdmissionKind,
    EntryType,
    SidecarRole,
    SourceFormat,
)

from .direct_probe import inspect_direct
from .rar_probe import (
    RarDirectoryBackend,
    RarfileDirectoryBackend,
    RarProbeOutcome,
    inspect_rar,
)
from .source_file import OpenedSource, open_source
from .zip_probe import ZipProbeOutcome, inspect_zip

_SIDECAR_SUFFIXES = {
    ".opf": SidecarRole.OPF,
    ".lrc": SidecarRole.LYRICS,
    ".cue": SidecarRole.CUE,
    ".jpg": SidecarRole.ARTWORK,
    ".jpeg": SidecarRole.ARTWORK,
    ".png": SidecarRole.ARTWORK,
    ".webp": SidecarRole.ARTWORK,
}
_DIRECT_SUFFIXES = {
    ".mobi": SourceFormat.MOBI,
    ".azw": SourceFormat.AZW,
    ".azw3": SourceFormat.AZW3,
    ".prc": SourceFormat.PRC,
    ".txt": SourceFormat.TXT,
    ".pdf": SourceFormat.PDF,
    ".mp3": SourceFormat.MP3,
    ".m4a": SourceFormat.M4A,
    ".m4b": SourceFormat.M4B,
}
_ZIP_SUFFIXES = {
    ".epub": SourceFormat.EPUB,
    ".cbz": SourceFormat.CBZ,
    ".zip": SourceFormat.ZIP,
}
_RAR_SUFFIXES = {
    ".cbr": SourceFormat.CBR,
    ".rar": SourceFormat.RAR,
}


def _suffix(filename: str) -> str:
    separator = filename.rfind(".")
    return filename[separator:].casefold() if separator >= 0 else ""


def _rejection(
    source: OpenedSource,
    reason: AdmissionRejectionReason,
) -> SourceAdmissionRejection:
    return SourceAdmissionRejection(
        relative_path=source.relative_path,
        entry_type=source.entry_type,
        reason=reason,
    )


def _archive_result(
    source: OpenedSource,
    outcome: ZipProbeOutcome | RarProbeOutcome,
) -> SourceAdmissionResult:
    if outcome.evidence is None:
        reason = outcome.rejection or AdmissionRejectionReason.CORRUPT_SOURCE
        return _rejection(source, reason)
    return SourceAdmissionEvidence(
        relative_path=source.relative_path,
        entry_type=EntryType.FILE,
        admission=AdmissionKind.PRIMARY,
        source_format=outcome.evidence.source_format,
        evidence=outcome.evidence,
    )


class LocalSourceAdmissionAdapter(SourceAdmissionPort):
    """Probe one entry through no-follow root-relative handles and byte budgets."""

    def __init__(
        self,
        *,
        rar_backend: RarDirectoryBackend | None = None,
        probe_completion_hook: Callable[[], None] | None = None,
    ) -> None:
        self._rar_backend = (
            rar_backend if rar_backend is not None else RarfileDirectoryBackend()
        )
        self._probe_completion_hook = probe_completion_hook

    def probe(
        self,
        *,
        canonical_root: str,
        relative_path: tuple[str, ...],
        expected_stat: SourceStatExpectation | None = None,
    ) -> SourceAdmissionResult:
        try:
            with open_source(
                canonical_root=canonical_root,
                relative_path=relative_path,
                expected_stat=expected_stat,
            ) as source:
                try:
                    result = self._inspect(source)
                except SourceAdmissionOperationalError:
                    source.verify_unchanged()
                    raise
                except PermissionError as error:
                    source.verify_unchanged()
                    raise SourceProbePermissionDenied() from error
                except OSError as error:
                    source.verify_unchanged()
                    raise SourceProbeIoError() from error
                if self._probe_completion_hook is not None:
                    self._probe_completion_hook()
                source.verify_unchanged()
                return result
        except SourceAdmissionOperationalError:
            raise
        except PermissionError as error:
            raise SourceProbePermissionDenied() from error
        except OSError as error:
            raise SourceProbeIoError() from error

    def _inspect(self, source: OpenedSource) -> SourceAdmissionResult:
        if source.entry_type is EntryType.SYMLINK:
            return _rejection(
                source,
                AdmissionRejectionReason.SYMLINK_NOT_ALLOWED,
            )
        if source.entry_type is EntryType.JUNCTION:
            return _rejection(
                source,
                AdmissionRejectionReason.JUNCTION_NOT_ALLOWED,
            )
        if source.entry_type is EntryType.DIRECTORY:
            return SourceAdmissionEvidence(
                relative_path=source.relative_path,
                entry_type=EntryType.DIRECTORY,
                admission=AdmissionKind.IGNORED,
            )

        filename = source.filename
        if is_system_noise_name(filename):
            return SourceAdmissionEvidence(
                relative_path=source.relative_path,
                entry_type=EntryType.FILE,
                admission=AdmissionKind.IGNORED,
            )

        suffix = _suffix(filename)
        sidecar_role = _SIDECAR_SUFFIXES.get(suffix)
        if sidecar_role is not None:
            return SourceAdmissionEvidence(
                relative_path=source.relative_path,
                entry_type=EntryType.FILE,
                admission=AdmissionKind.SIDECAR,
                sidecar_role=sidecar_role,
            )

        direct_format = _DIRECT_SUFFIXES.get(suffix)
        if direct_format is not None:
            inspected = inspect_direct(source, direct_format)
            if isinstance(inspected, AdmissionRejectionReason):
                return _rejection(source, inspected)
            admission = (
                AdmissionKind.AUDIO_TRACK
                if isinstance(inspected, AudioEvidence)
                else AdmissionKind.PRIMARY
            )
            return SourceAdmissionEvidence(
                relative_path=source.relative_path,
                entry_type=EntryType.FILE,
                admission=admission,
                source_format=direct_format,
                evidence=inspected,
            )

        zip_format = _ZIP_SUFFIXES.get(suffix)
        if zip_format is not None:
            return _archive_result(source, inspect_zip(source, zip_format))

        rar_format = _RAR_SUFFIXES.get(suffix)
        if rar_format is not None:
            return _archive_result(
                source,
                inspect_rar(source, rar_format, self._rar_backend),
            )

        return _rejection(
            source,
            AdmissionRejectionReason.UNSUPPORTED_EXTENSION,
        )


__all__ = ["LocalSourceAdmissionAdapter"]
