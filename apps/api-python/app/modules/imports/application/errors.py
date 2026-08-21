"""Named import application errors."""

from __future__ import annotations


class AudioInspectionError(ValueError):
    """A source cannot satisfy the audiobook media-inspection contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class AudioTrackLimitExceededError(RuntimeError):
    """A logical audiobook contains more tracks than one import may own."""

    code = "AUDIO_TRACK_LIMIT_EXCEEDED"

    def __init__(
        self,
        *,
        path: str,
        limit: int,
        observed_count: int,
    ) -> None:
        super().__init__(f"有声书音轨超过 {limit} 条，请拆分目录后重新导入")
        self.path = path
        self.limit = limit
        self.observed_count = observed_count


class ComicArchiveError(RuntimeError):
    """Base error for comic archive inspection and entry reads."""


class ComicArchiveEncryptedError(ComicArchiveError):
    """A comic archive requires a password."""


class ComicArchiveMultiVolumeError(ComicArchiveError):
    """A comic archive spans multiple RAR volumes."""


class ComicArchiveBackendUnavailableError(ComicArchiveError):
    """The host cannot read compressed RAR data."""


class ComicArchiveInvalidError(ComicArchiveError):
    """A comic archive is malformed or unsupported."""
