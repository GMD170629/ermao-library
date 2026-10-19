"""Named import application errors."""

from __future__ import annotations


class ImportFileTooLargeError(ValueError):
    """A new source file exceeds the shared single-file import allowance."""

    code = "IMPORT_FILE_TOO_LARGE"

    def __init__(self) -> None:
        super().__init__(self.code)


class AudioInspectionError(ValueError):
    """A source cannot satisfy the audiobook media-inspection contract."""

    def __init__(self, code: str, message: str, *, rule_id: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.rule_id = rule_id


class ComicArchiveError(RuntimeError):
    """Base error for comic archive inspection and entry reads."""

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        rule_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.rule_id = rule_id


class ComicArchiveEncryptedError(ComicArchiveError):
    """A comic archive requires a password."""


class ComicArchiveMultiVolumeError(ComicArchiveError):
    """A comic archive spans multiple RAR volumes."""


class ComicArchiveBackendUnavailableError(ComicArchiveError):
    """The host cannot read compressed RAR data."""


class ComicArchiveInvalidError(ComicArchiveError):
    """A comic archive is malformed or unsupported."""
