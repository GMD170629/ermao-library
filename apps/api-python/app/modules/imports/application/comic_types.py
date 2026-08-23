"""Typed comic archive inspection contracts."""

from __future__ import annotations

from typing import TypedDict


class ComicPageInspection(TypedDict):
    index: int
    title: str
    entryPath: str
    mediaType: str
    size: int


class ComicInfoMetadata(TypedDict, total=False):
    title: str | None
    series: str | None
    volume: float | None
    summary: str | None
    writer: str | None
    penciller: str | None
    publisher: str | None
    tags: list[str]
    coverImageIndex: int | None
    raw: dict[str, str]


class ComicArchiveInspection(TypedDict):
    title: str
    author: str
    description: str | None
    format: str
    pageCount: int
    coverEntryPath: str
    pages: list[ComicPageInspection]
    comicInfo: ComicInfoMetadata | None
    rawMetadata: dict[str, object]
