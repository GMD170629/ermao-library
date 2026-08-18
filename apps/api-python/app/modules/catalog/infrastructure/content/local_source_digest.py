"""Secure, read-only full digests for original catalog source files."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Callable
from typing import NoReturn

from app.modules.catalog.application.content_dto import (
    SourceDigestEvidence,
    SourceDigestProgress,
    SourceDigestRequest,
)
from app.modules.catalog.application.content_ports import (
    InvalidSourceDigestRelativePath,
    SourceChangedDuringDigest,
    SourceDigestCheckpointPort,
    SourceDigestIoError,
    SourceDigestOperationalError,
    SourceDigestPermissionDenied,
    SourceDigestPort,
    SourceDigestRootIdentityChanged,
    SourceDigestUnavailable,
)
from app.modules.catalog.application.source_admission_ports import (
    InvalidSourceRelativePath,
    SourceAdmissionOperationalError,
    SourceChangedDuringProbe,
    SourceProbeIoError,
    SourceProbePermissionDenied,
    SourceProbeUnavailable,
    SourceStatExpectation,
)
from app.modules.catalog.domain.content import Sha256Digest
from app.modules.catalog.domain.model import EntryType
from app.modules.catalog.infrastructure.admission.source_file import (
    OpenedSource,
    open_source,
)

_DIGEST_CHUNK_BYTES = 1024 * 1024


def _root_identity(source_stat: os.stat_result) -> str:
    return f"{source_stat.st_dev}:{source_stat.st_ino}"


def _raise_digest_error(error: SourceAdmissionOperationalError) -> NoReturn:
    if isinstance(error, InvalidSourceRelativePath):
        raise InvalidSourceDigestRelativePath() from error
    if isinstance(error, SourceChangedDuringProbe):
        raise SourceChangedDuringDigest() from error
    if isinstance(error, SourceProbePermissionDenied):
        raise SourceDigestPermissionDenied() from error
    if isinstance(error, SourceProbeUnavailable):
        raise SourceDigestUnavailable() from error
    if isinstance(error, SourceProbeIoError):
        raise SourceDigestIoError() from error
    raise SourceDigestIoError() from error


def _current_root_identity(canonical_root: str) -> str:
    if (
        not isinstance(canonical_root, str)
        or not canonical_root
        or "\x00" in canonical_root
        or not os.path.isabs(canonical_root)
    ):
        raise SourceDigestUnavailable()
    try:
        root_stat = os.stat(canonical_root, follow_symlinks=False)
    except PermissionError as error:
        raise SourceDigestPermissionDenied() from error
    except (FileNotFoundError, NotADirectoryError) as error:
        raise SourceDigestUnavailable() from error
    except OSError as error:
        raise SourceDigestIoError() from error
    if not stat.S_ISDIR(root_stat.st_mode):
        raise SourceDigestRootIdentityChanged()
    return _root_identity(root_stat)


def _require_root_identity(canonical_root: str, expected_identity: str) -> None:
    if _current_root_identity(canonical_root) != expected_identity:
        raise SourceDigestRootIdentityChanged()


def _opened_root_identity(source: OpenedSource) -> str:
    try:
        return _root_identity(os.fstat(source.root_fd))
    except OSError as error:
        raise SourceDigestIoError() from error


def _observed_stat(source: OpenedSource) -> SourceStatExpectation:
    return SourceStatExpectation(
        device_id=source.initial_stat.st_dev,
        file_id=source.initial_stat.st_ino,
        size_bytes=source.initial_stat.st_size,
        modified_ns=source.initial_stat.st_mtime_ns,
    )


def _full_digest(
    source: OpenedSource,
    request: SourceDigestRequest,
    checkpoint: SourceDigestCheckpointPort,
) -> tuple[int, Sha256Digest]:
    if source.entry_type is not EntryType.FILE or source.source_fd is None:
        raise SourceDigestUnavailable()
    digest = hashlib.sha256()
    bytes_hashed = 0
    with source.duplicate_binary() as stream:
        while True:
            chunk = stream.read(_DIGEST_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
            bytes_hashed += len(chunk)
            checkpoint.checkpoint(
                SourceDigestProgress(
                    source_entry_id=request.source_entry_id,
                    input_revision=request.input_revision,
                    bytes_hashed=bytes_hashed,
                )
            )
    if bytes_hashed != source.size_bytes:
        raise SourceChangedDuringDigest()
    return bytes_hashed, Sha256Digest(f"sha256:{digest.hexdigest()}")


class LocalSourceDigestAdapter(SourceDigestPort):
    """Hash one original source through a no-follow, root-relative handle."""

    def __init__(
        self,
        *,
        digest_completion_hook: Callable[[], None] | None = None,
    ) -> None:
        self._digest_completion_hook = digest_completion_hook

    def digest(
        self,
        request: SourceDigestRequest,
        checkpoint: SourceDigestCheckpointPort,
    ) -> SourceDigestEvidence:
        if not isinstance(request, SourceDigestRequest):
            raise TypeError("request must be a SourceDigestRequest")
        try:
            _require_root_identity(
                request.canonical_root,
                request.expected_root_identity,
            )
            with open_source(
                canonical_root=request.canonical_root,
                relative_path=request.relative_path,
                expected_stat=request.expected_stat,
            ) as source:
                if _opened_root_identity(source) != request.expected_root_identity:
                    raise SourceDigestRootIdentityChanged()
                try:
                    bytes_hashed, content_digest = _full_digest(
                        source,
                        request,
                        checkpoint,
                    )
                except (PermissionError, OSError):
                    source.verify_unchanged()
                    raise
                if self._digest_completion_hook is not None:
                    self._digest_completion_hook()
                source.verify_unchanged()
                _require_root_identity(
                    request.canonical_root,
                    request.expected_root_identity,
                )
                return SourceDigestEvidence(
                    source_entry_id=request.source_entry_id,
                    input_revision=request.input_revision,
                    observed_stat=_observed_stat(source),
                    bytes_hashed=bytes_hashed,
                    content_digest=content_digest,
                )
        except SourceDigestOperationalError:
            raise
        except SourceAdmissionOperationalError as error:
            _raise_digest_error(error)
        except PermissionError as error:
            raise SourceDigestPermissionDenied() from error
        except OSError as error:
            raise SourceDigestIoError() from error


__all__ = ["LocalSourceDigestAdapter"]
