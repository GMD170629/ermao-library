"""Pure content classification policy independent of file parsers and storage."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MediaKindPolicy(StrEnum):
    MIXED = "MIXED"
    EBOOK = "EBOOK"
    COMIC = "COMIC"
    AUDIOBOOK = "AUDIOBOOK"


class ClassificationSource(StrEnum):
    AUTO = "AUTO"
    MONITOR_FOLDER = "MONITOR_FOLDER"
    USER = "USER"


@dataclass(frozen=True, slots=True)
class ContentEvidence:
    volume_format: str
    subjects: tuple[str, ...] = ()
    title: str | None = None
    publisher: str | None = None
    has_comic_info: bool = False
    fixed_layout: bool = False
    image_dominant: bool = False
    image_only: bool = False


@dataclass(frozen=True, slots=True)
class ContentClassification:
    media_kind: str
    source: ClassificationSource
    reason: str
    suggested_media_kind: str | None = None


_AUDIO_FORMATS = frozenset({"AUDIO", "AUDIOBOOK", "MP3", "M4A", "M4B"})
_COMIC_ARCHIVES = frozenset({"COMIC", "CBR", "CBZ", "RAR", "ZIP"})
_COMIC_TERMS = frozenset(
    {
        "comic",
        "comics",
        "manga",
        "manhua",
        "manhwa",
        "漫画",
        "漫畫",
    }
)


def normalize_media_kind_policy(value: object) -> MediaKindPolicy:
    try:
        return MediaKindPolicy(str(value or "MIXED").strip().upper())
    except ValueError:
        return MediaKindPolicy.MIXED


def _contains_comic_term(values: tuple[str, ...]) -> bool:
    for raw_value in values:
        normalized = raw_value.strip().casefold()
        tokens = {
            token
            for token in normalized.replace("/", " ").replace(",", " ").split()
            if token
        }
        if normalized in _COMIC_TERMS or tokens.intersection(_COMIC_TERMS):
            return True
    return False


def classify_content(
    policy: MediaKindPolicy,
    evidence: ContentEvidence,
) -> ContentClassification:
    if policy is not MediaKindPolicy.MIXED:
        return ContentClassification(
            media_kind=policy.value,
            source=ClassificationSource.MONITOR_FOLDER,
            reason="FOLDER_POLICY",
        )

    normalized_format = evidence.volume_format.strip().upper()
    if normalized_format in _AUDIO_FORMATS:
        return ContentClassification(
            media_kind="AUDIOBOOK",
            source=ClassificationSource.AUTO,
            reason="AUDIO_FORMAT",
        )
    if evidence.has_comic_info:
        return ContentClassification(
            media_kind="COMIC",
            source=ClassificationSource.AUTO,
            reason="COMIC_INFO",
        )
    if normalized_format in _COMIC_ARCHIVES:
        return ContentClassification(
            media_kind="COMIC",
            source=ClassificationSource.AUTO,
            reason="COMIC_ARCHIVE",
        )
    if _contains_comic_term(evidence.subjects):
        return ContentClassification(
            media_kind="COMIC",
            source=ClassificationSource.AUTO,
            reason="COMIC_SUBJECT",
        )
    if evidence.fixed_layout:
        return ContentClassification(
            media_kind="EBOOK",
            source=ClassificationSource.AUTO,
            reason="EPUB_FIXED_LAYOUT",
            suggested_media_kind="COMIC",
        )
    if evidence.image_dominant:
        return ContentClassification(
            media_kind="EBOOK",
            source=ClassificationSource.AUTO,
            reason="IMAGE_DOMINANT",
            suggested_media_kind="COMIC",
        )
    if evidence.image_only and normalized_format == "PDF":
        return ContentClassification(
            media_kind="EBOOK",
            source=ClassificationSource.AUTO,
            reason="PDF_IMAGE_ONLY",
            suggested_media_kind="COMIC",
        )
    return ContentClassification(
        media_kind="EBOOK",
        source=ClassificationSource.AUTO,
        reason="FORMAT_DEFAULT",
    )
