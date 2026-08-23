"""Browse a Book through its SourceNode tree and readable-resource overlay."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

BookContentSort = Literal["name", "type", "updated", "size"]
SortDirection = Literal["asc", "desc"]


@dataclass(frozen=True, slots=True)
class BookContentNode:
    source_node_id: str
    library_id: str
    parent_source_node_id: str | None
    name: str
    title: str
    description: str | None
    physical_kind: str
    size_bytes: int | None
    observed_at: datetime
    has_children: bool
    resource_id: str | None
    representative_resource_id: str | None
    cover_path: str | None


@dataclass(frozen=True, slots=True)
class BookContentPage:
    book_id: str
    current_source_node_id: str | None
    current_resource_id: str | None
    current_node: BookContentNode
    current_resource_ids: tuple[str, ...]
    parent_source_node_id: str | None
    breadcrumbs: tuple[BookContentNode, ...]
    entries: tuple[BookContentNode, ...]
    page: int
    page_size: int
    total: int


class BookContentsNotFoundError(Exception):
    """The Book or requested folder is outside the visible Book tree."""


class BookContentsQueries(Protocol):
    def get_book_root(self, book_id: str) -> BookContentNode | None: ...

    def get_node(self, source_node_id: str) -> BookContentNode | None: ...

    def list_resource_ids_under(
        self, *, book_id: str, source_node_id: str
    ) -> tuple[str, ...]: ...

    def list_children(
        self,
        *,
        book_id: str,
        parent_source_node_id: str,
        sort: BookContentSort,
        direction: SortDirection,
        limit: int,
        offset: int,
    ) -> tuple[tuple[BookContentNode, ...], int]: ...


class BrowseBookContents:
    """Return one deterministic folder page without exposing filesystem access."""

    def __init__(self, queries: BookContentsQueries) -> None:
        self._queries = queries

    def execute(
        self,
        *,
        book_id: str,
        source_node_id: str | None,
        sort: BookContentSort,
        direction: SortDirection,
        page: int,
        page_size: int,
    ) -> BookContentPage:
        root = self._queries.get_book_root(book_id)
        if root is None:
            raise BookContentsNotFoundError

        if root.physical_kind != "DIRECTORY":
            if source_node_id not in {None, root.source_node_id}:
                raise BookContentsNotFoundError
            return BookContentPage(
                book_id=book_id,
                current_source_node_id=None,
                current_resource_id=root.resource_id,
                current_node=root,
                current_resource_ids=(root.resource_id,) if root.resource_id else (),
                parent_source_node_id=None,
                breadcrumbs=(),
                entries=(root,),
                page=1,
                page_size=page_size,
                total=1,
            )

        current = (
            root if source_node_id is None else self._queries.get_node(source_node_id)
        )
        if current is None or current.physical_kind != "DIRECTORY":
            raise BookContentsNotFoundError

        lineage = self._lineage_to_root(root=root, current=current)
        normalized_page = max(1, page)
        entries, total = self._queries.list_children(
            book_id=book_id,
            parent_source_node_id=current.source_node_id,
            sort=sort,
            direction=direction,
            limit=page_size,
            offset=(normalized_page - 1) * page_size,
        )
        breadcrumbs = tuple(reversed(lineage[:-1]))
        return BookContentPage(
            book_id=book_id,
            current_source_node_id=current.source_node_id,
            current_resource_id=current.resource_id,
            current_node=current,
            current_resource_ids=self._queries.list_resource_ids_under(
                book_id=book_id,
                source_node_id=current.source_node_id,
            ),
            parent_source_node_id=(
                lineage[1].source_node_id if len(lineage) > 1 else None
            ),
            breadcrumbs=breadcrumbs,
            entries=entries,
            page=normalized_page,
            page_size=page_size,
            total=total,
        )

    def _lineage_to_root(
        self, *, root: BookContentNode, current: BookContentNode
    ) -> list[BookContentNode]:
        lineage = [current]
        seen = {current.source_node_id}
        while lineage[-1].source_node_id != root.source_node_id:
            parent_id = lineage[-1].parent_source_node_id
            if parent_id is None or parent_id in seen:
                raise BookContentsNotFoundError
            parent = self._queries.get_node(parent_id)
            if parent is None or parent.library_id != root.library_id:
                raise BookContentsNotFoundError
            lineage.append(parent)
            seen.add(parent.source_node_id)
        return lineage


__all__ = [
    "BookContentNode",
    "BookContentPage",
    "BookContentSort",
    "BookContentsNotFoundError",
    "BookContentsQueries",
    "BrowseBookContents",
    "SortDirection",
]
