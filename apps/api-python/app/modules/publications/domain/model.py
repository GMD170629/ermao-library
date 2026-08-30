"""Renderer-neutral publication values and invariants."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from app.contracts.reader_safety_policy_generated import ReaderSafetyErrorCode


class PublicationNotFoundError(Exception):
    """The actor cannot open the requested publication."""

    code: str = "PUBLICATION_NOT_FOUND"


class PublicationUnsupportedError(Exception):
    """The source format has no production publication adapter."""

    code: str = "PUBLICATION_UNSUPPORTED"


class PublicationCorruptError(Exception):
    """The source cannot safely produce a normalized publication."""

    code: str = ReaderSafetyErrorCode.PUBLICATION_CORRUPT.value


class PublicationTxtEncodingError(PublicationCorruptError):
    """TXT cannot be decoded using the supported encoding policy."""

    code: str = "PUBLICATION_TXT_ENCODING_UNSUPPORTED"


class PublicationTxtEmptyError(PublicationCorruptError):
    """Decoded TXT contains no non-whitespace text."""

    code: str = "PUBLICATION_TXT_EMPTY"


class PublicationSecurityError(PublicationCorruptError):
    """The source contains an active construct which must not be rendered."""

    code: str = ReaderSafetyErrorCode.PUBLICATION_SECURITY_REJECTED.value

    def __init__(self, message: str, *, rule_id: str) -> None:
        super().__init__(message)
        self.rule_id = rule_id


class PublicationMarkupError(PublicationCorruptError):
    """One publication markup resource is malformed but may be recoverable."""

    code = "PUBLICATION_MARKUP_INVALID"


class PublicationStructureError(PublicationCorruptError):
    """The publication package cannot provide a usable reading order."""

    code = "PUBLICATION_STRUCTURE_INVALID"


class PublicationReadError(PublicationCorruptError):
    """The filesystem or archive could not read the requested bytes."""

    code: str = "PUBLICATION_READ_FAILED"


class PublicationParserLimitError(PublicationCorruptError):
    """An explicit parser resource budget was exceeded."""

    code: str = ReaderSafetyErrorCode.PUBLICATION_PARSER_LIMIT.value

    def __init__(self, message: str, *, rule_id: str | None = None) -> None:
        super().__init__(message)
        self.rule_id = rule_id


class PublicationParserError(PublicationCorruptError):
    """An actual native parser operation failed; no raw path enters the wire error."""

    def __init__(
        self,
        *,
        code: str,
        parser: str,
        operation: str,
        reason: str,
        rule_id: str | None = None,
    ) -> None:
        super().__init__(f"{parser} {operation}: {reason}")
        self.code = code
        self.parser = parser
        self.operation = operation
        self.reason = reason
        self.rule_id = rule_id


class PublicationResourceTooLargeError(Exception):
    """The original or one requested resource exceeds a parser safety limit."""

    code = "PUBLICATION_RESOURCE_TOO_LARGE"

    def __init__(
        self,
        message: str = "Publication resource exceeds the size limit",
        *,
        code: str | None = None,
        rule_id: str | None = None,
    ) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        self.rule_id = rule_id


class PublicationChangedError(Exception):
    """The original changed after the reader opened its metadata."""


class PublicationResourceNotFoundError(Exception):
    """The requested resource is not in the validated publication index."""

    code: str = "PUBLICATION_NOT_FOUND"


@dataclass(frozen=True, slots=True)
class PublicationRevision:
    source_size_bytes: int
    source_mtime_ms: int
    parser: str
    normalization: str

    @property
    def token(self) -> str:
        identity = f"{self.source_size_bytes}:{self.source_mtime_ms}:{self.parser}:{self.normalization}"
        return sha256(identity.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class PublicationLink:
    href: str
    media_type: str
    title: str | None = None
    rel: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PublicationTocEntry:
    href: str
    title: str
    children: tuple[PublicationTocEntry, ...] = ()


@dataclass(frozen=True, slots=True)
class NormalizedPublication:
    identifier: str
    title: str
    author: str | None
    language: str | None
    reading_progression: str
    revision: PublicationRevision
    reading_order: tuple[PublicationLink, ...]
    resources: tuple[PublicationLink, ...]
    toc: tuple[PublicationTocEntry, ...]


@dataclass(frozen=True, slots=True)
class PublicationResource:
    href: str
    media_type: str
    content: bytes
    source_mtime: float
