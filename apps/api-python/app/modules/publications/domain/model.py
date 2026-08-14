"""Renderer-neutral publication values and invariants."""

from __future__ import annotations

from dataclasses import dataclass


class PublicationNotFoundError(Exception):
    """The actor cannot open the requested publication."""


class PublicationUnsupportedError(Exception):
    """The source format has no production publication adapter."""


class PublicationCorruptError(Exception):
    """The source cannot safely produce a normalized publication."""


class PublicationSecurityError(PublicationCorruptError):
    """The source contains an active construct which must not be rendered."""


class PublicationMarkupError(PublicationCorruptError):
    """One publication markup resource is malformed but may be recoverable."""


class PublicationStructureError(PublicationCorruptError):
    """The publication package cannot provide a usable reading order."""


class PublicationResourceNotFoundError(Exception):
    """The requested resource is not in the validated publication index."""


@dataclass(frozen=True, slots=True)
class PublicationFingerprint:
    original_file_hash: str
    parser: str
    normalization: str


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
    fingerprint: PublicationFingerprint
    reading_order: tuple[PublicationLink, ...]
    resources: tuple[PublicationLink, ...]
    toc: tuple[PublicationTocEntry, ...]


@dataclass(frozen=True, slots=True)
class PublicationResource:
    href: str
    media_type: str
    content: bytes
    source_mtime: float
