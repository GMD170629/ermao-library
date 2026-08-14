"""Typed contracts for native reflowable-book inspection."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class EmbeddedBookCover:
    content: bytes
    media_type: str
    extension: str


@dataclass(frozen=True)
class ReflowableBookMetadata:
    title: str | None
    authors: tuple[str, ...]
    language: str | None
    publisher: str | None
    published_at: str | None
    identifier: str | None
    isbn: str | None
    description: str | None
    subjects: tuple[str, ...]
    cover: EmbeddedBookCover | None
    raw_metadata: Mapping[str, object]
    series_name: str | None = None
    series_index: float | None = None

    @property
    def author(self) -> str | None:
        return ", ".join(self.authors) if self.authors else None
