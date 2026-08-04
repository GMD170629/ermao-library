"""Stable publication metadata shared by import and file writeback capabilities."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PublicationMetadata:
    """A publication snapshot whose title is always the owning work title."""

    title: str | None = None
    volume_title: str | None = None
    authors: tuple[str, ...] = ()
    description: str | None = None
    subjects: tuple[str, ...] = ()
    series_name: str | None = None
    series_index: float | None = None
    volume_index: float | None = None
    language: str | None = None
    publisher: str | None = None
    published_at: str | None = None
    identifier: str | None = None
    isbn: str | None = None
    cover_href: str | None = None
    unparsed_values: tuple[tuple[str, str], ...] = ()

    @property
    def author(self) -> str | None:
        return " / ".join(self.authors) if self.authors else None

    @property
    def populated_fields(self) -> tuple[str, ...]:
        values: tuple[tuple[str, object], ...] = (
            ("title", self.title),
            ("volumeTitle", self.volume_title),
            ("author", self.authors),
            ("description", self.description),
            ("tags", self.subjects),
            ("seriesName", self.series_name),
            ("seriesIndex", self.series_index),
            ("volumeIndex", self.volume_index),
            ("language", self.language),
            ("publisher", self.publisher),
            ("publishedAt", self.published_at),
            ("identifier", self.identifier),
            ("isbn", self.isbn),
            ("cover", self.cover_href),
        )
        return tuple(name for name, value in values if value not in (None, (), ""))
