"""Publication-owned navigation cache values and deterministic projection rules."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from app.modules.publications.domain.model import (
    NormalizedPublication,
    PublicationTocEntry,
)


@dataclass(frozen=True, slots=True)
class PublicationNavigationMarkerState:
    asset_id: str
    chapter_count: int


@dataclass(frozen=True, slots=True)
class PublicationNavigationEntry:
    id: str
    navigation_key: str
    title: str
    href: str
    media_type: str | None
    sort_order: int
    level: int
    path: tuple[int, ...]
    reading_order_position: int | None


def _href_without_fragment(href: str) -> str:
    split = urlsplit(href)
    return urlunsplit((split.scheme, split.netloc, split.path, split.query, ""))


def _navigation_key(resource_id: str, href: str, path: tuple[int, ...]) -> str:
    path_key = ".".join(str(part) for part in path)
    digest = hashlib.sha256(f"{resource_id}\0{href}\0{path_key}".encode()).hexdigest()
    return f"pubnav_{digest[:32]}"


def flatten_publication_navigation(
    *,
    resource_id: str,
    publication: NormalizedPublication,
) -> tuple[PublicationNavigationEntry, ...]:
    """Flatten Publication TOC using stable zero-based pre-order traversal."""

    media_types = {
        _href_without_fragment(link.href): link.media_type
        for link in (*publication.reading_order, *publication.resources)
    }
    reading_order_positions = {
        _href_without_fragment(link.href): index + 1
        for index, link in enumerate(publication.reading_order)
    }
    flattened: list[PublicationNavigationEntry] = []

    def visit(
        entries: tuple[PublicationTocEntry, ...],
        parent: tuple[int, ...],
    ) -> None:
        for child_index, entry in enumerate(entries):
            path = (*parent, child_index)
            navigation_key = _navigation_key(resource_id, entry.href, path)
            flattened.append(
                PublicationNavigationEntry(
                    id=navigation_key,
                    navigation_key=navigation_key,
                    title=entry.title,
                    href=entry.href,
                    media_type=media_types.get(_href_without_fragment(entry.href)),
                    sort_order=len(flattened),
                    level=len(path) - 1,
                    path=path,
                    reading_order_position=reading_order_positions.get(
                        _href_without_fragment(entry.href)
                    ),
                )
            )
            visit(entry.children, path)

    visit(publication.toc, ())
    return tuple(flattened)


__all__ = [
    "PublicationNavigationEntry",
    "PublicationNavigationMarkerState",
    "flatten_publication_navigation",
]
