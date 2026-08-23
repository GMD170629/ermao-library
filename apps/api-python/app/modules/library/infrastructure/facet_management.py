"""SQLAlchemy adapter for canonical LibraryFacet governance commands."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models import (
    LibraryBookFacet,
    LibraryBookMetadata,
    LibraryReadableResourceFacet,
)
from app.modules.library.application.management_commands import (
    LibraryFacetManagementGateway,
)
from app.modules.library.domain.authors import UNKNOWN_AUTHOR_PLACEHOLDER
from app.modules.library.domain.facets import FACET_KINDS
from app.modules.library.infrastructure import categories as facet_store
from app.modules.library.infrastructure import operations as operation_store
from app.modules.library.infrastructure.facets import (
    normalized_name,
    parse_json,
    split_authors,
    unique_names,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _book_snapshots(db: Session, book_ids: list[str]) -> list[dict[str, Any]]:
    if not book_ids:
        return []
    rows = db.scalars(
        select(LibraryBookMetadata).where(LibraryBookMetadata.book_id.in_(book_ids))
    ).all()
    return [
        {
            "id": row.book_id,
            "author": row.author,
            "normalizedAuthor": row.normalized_author,
            "seriesName": row.series_name,
            "seriesIndex": row.series_index,
            "updatedAt": row.updated_at,
        }
        for row in rows
    ]


def _linked_book_ids(links: list[dict[str, Any]]) -> list[str]:
    return list(dict.fromkeys(str(link["bookId"]) for link in links))


def _replace_author_names(
    author: str | None,
    source_names: set[str],
    replacement: str | None,
) -> str:
    values = [
        replacement if normalized_name(value) in source_names else value
        for value in split_authors(author)
        if replacement is not None or normalized_name(value) not in source_names
    ]
    return "、".join(unique_names(values)) or UNKNOWN_AUTHOR_PLACEHOLDER


def _replace_book_metadata(
    db: Session,
    *,
    kind: str,
    book_ids: list[str],
    source_names: set[str],
    replacement: str | None,
    now: datetime,
) -> None:
    if kind not in {"AUTHOR", "SERIES"} or not book_ids:
        return
    rows = db.scalars(
        select(LibraryBookMetadata).where(LibraryBookMetadata.book_id.in_(book_ids))
    ).all()
    for metadata in rows:
        if kind == "AUTHOR":
            author = _replace_author_names(
                metadata.author,
                source_names,
                replacement,
            )
            metadata.author = author
            metadata.normalized_author = normalized_name(author)
        elif normalized_name(metadata.series_name) in source_names:
            metadata.series_name = replacement
            if replacement is None:
                metadata.series_index = None
        metadata.updated_at = now


def _copy_links_to_target(
    db: Session,
    *,
    target_id: str,
    book_links: list[dict[str, Any]],
    resource_links: list[dict[str, Any]],
    now: datetime,
) -> None:
    book_rows = [
        {
            "facet_id": target_id,
            "book_id": str(link["bookId"]),
            "sort_order": int(link.get("sortOrder") or 0),
            "created_at": now,
        }
        for link in book_links
        if str(link["facetId"]) != target_id
    ]
    if book_rows:
        db.execute(
            sqlite_insert(LibraryBookFacet)
            .values(book_rows)
            .on_conflict_do_nothing(
                index_elements=[LibraryBookFacet.facet_id, LibraryBookFacet.book_id]
            )
        )
    resource_rows = [
        {
            "facet_id": target_id,
            "resource_id": str(link["resourceId"]),
            "created_at": now,
        }
        for link in resource_links
        if str(link["facetId"]) != target_id
    ]
    if resource_rows:
        db.execute(
            sqlite_insert(LibraryReadableResourceFacet)
            .values(resource_rows)
            .on_conflict_do_nothing(
                index_elements=[
                    LibraryReadableResourceFacet.facet_id,
                    LibraryReadableResourceFacet.resource_id,
                ]
            )
        )


def _operation_view(operation: dict[str, Any]) -> dict[str, Any]:
    return asdict(operation_store.operation_summary(operation))


class SqlAlchemyLibraryFacetManagement(LibraryFacetManagementGateway):
    """Persist facet changes without owning the surrounding transaction."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def merge_facets(
        self,
        kind: str,
        source_ids: list[str],
        target_id: str,
        user_id: str | None,
    ) -> dict[str, object]:
        normalized_kind = kind.strip().upper()
        if normalized_kind not in FACET_KINDS:
            raise ValueError("Facet 类型无效")
        target = facet_store.get_facet_of_kind(self._db, target_id, normalized_kind)
        sources = [
            facet_id for facet_id in dict.fromkeys(source_ids) if facet_id != target_id
        ]
        source_rows = facet_store.list_facets_of_kind(
            self._db, sources, normalized_kind
        )
        if target is None or not sources or len(source_rows) != len(sources):
            raise ValueError("请选择同一 Facet 类型中的有效合并项")

        all_ids = [target_id, *sources]
        book_links = facet_store.list_book_facet_links(self._db, all_ids)
        resource_links = facet_store.list_resource_facet_links(self._db, all_ids)
        book_ids = _linked_book_ids(book_links)
        inverse = {
            "facets": [target, *source_rows],
            "bookLinks": book_links,
            "resourceLinks": resource_links,
            "books": _book_snapshots(self._db, book_ids),
            "kind": normalized_kind,
        }
        target_name = str(target["name"])
        source_names = {normalized_name(row.get("name")) for row in source_rows}
        now = _now()
        _replace_book_metadata(
            self._db,
            kind=normalized_kind,
            book_ids=book_ids,
            source_names=source_names,
            replacement=target_name,
            now=now,
        )
        _copy_links_to_target(
            self._db,
            target_id=target_id,
            book_links=book_links,
            resource_links=resource_links,
            now=now,
        )
        aliases = unique_names(
            [
                *parse_json(target.get("aliases"), []),
                *(row.get("name") for row in source_rows),
                *(
                    alias
                    for row in source_rows
                    for alias in parse_json(row.get("aliases"), [])
                ),
            ]
        )
        facet_store.update_facet_aliases(
            self._db,
            facet_id=target_id,
            aliases_json=_json(aliases),
            now=now,
        )
        facet_store.delete_facets(self._db, sources)
        operation = operation_store.create_operation(
            self._db,
            user_id=user_id,
            action="MERGE_FACETS",
            target_type="facet",
            target_id=target_id,
            summary=f"已合并 {len(source_rows) + 1} 个 {normalized_kind} Facet",
            payload={
                "kind": normalized_kind,
                "targetId": target_id,
                "sourceIds": sources,
            },
            inverse=inverse,
            now=now,
        )
        return {
            "targetId": target_id,
            "mergedIds": sources,
            "operation": _operation_view(operation),
        }

    def rename_facet(
        self, facet_id: str, name: str, user_id: str | None
    ) -> dict[str, object]:
        facet = facet_store.get_facet(self._db, facet_id)
        next_name = re.sub(r"\s+", " ", name).strip()
        if facet is None or not next_name:
            raise ValueError("Facet 不存在或名称无效")
        kind = str(facet["kind"])
        if kind not in FACET_KINDS:
            raise ValueError("Facet 类型无效")
        normalized = normalized_name(next_name)
        if not normalized:
            raise ValueError("Facet 名称无效")
        if facet_store.find_normalized_name_conflict(
            self._db,
            kind=kind,
            normalized_name=normalized,
            exclude_facet_id=facet_id,
        ):
            raise ValueError("同名 Facet 已存在，请使用合并")

        book_ids = facet_store.list_book_ids_for_facet(self._db, facet_id)
        source_name = str(facet["name"])
        now = _now()
        inverse = {
            "facet": facet,
            "books": _book_snapshots(self._db, book_ids),
        }
        _replace_book_metadata(
            self._db,
            kind=kind,
            book_ids=book_ids,
            source_names={normalized_name(source_name)},
            replacement=next_name,
            now=now,
        )
        aliases = unique_names([*parse_json(facet.get("aliases"), []), source_name])
        facet_store.update_facet_name(
            self._db,
            facet_id=facet_id,
            name=next_name,
            normalized_name=normalized,
            aliases_json=_json(aliases),
            now=now,
        )
        operation = operation_store.create_operation(
            self._db,
            user_id=user_id,
            action="RENAME_FACET",
            target_type="facet",
            target_id=facet_id,
            summary=f"已将“{source_name}”重命名为“{next_name}”",
            payload={"facetId": facet_id, "name": next_name},
            inverse=inverse,
            now=now,
        )
        return {
            "facetId": facet_id,
            "name": next_name,
            "operation": _operation_view(operation),
        }

    def delete_facet(self, facet_id: str, user_id: str | None) -> dict[str, object]:
        facet = facet_store.get_facet(self._db, facet_id)
        if facet is None:
            raise ValueError("Facet 不存在")
        kind = str(facet["kind"])
        if kind not in FACET_KINDS:
            raise ValueError("Facet 类型无效")
        book_links = facet_store.list_book_facet_links(self._db, [facet_id])
        resource_links = facet_store.list_resource_facet_links(self._db, [facet_id])
        book_ids = _linked_book_ids(book_links)
        now = _now()
        inverse = {
            "facet": facet,
            "bookLinks": book_links,
            "resourceLinks": resource_links,
            "books": _book_snapshots(self._db, book_ids),
        }
        _replace_book_metadata(
            self._db,
            kind=kind,
            book_ids=book_ids,
            source_names={normalized_name(facet.get("name"))},
            replacement=None,
            now=now,
        )
        facet_store.delete_facets(self._db, [facet_id])
        operation = operation_store.create_operation(
            self._db,
            user_id=user_id,
            action="DELETE_FACET",
            target_type="facet",
            target_id=facet_id,
            summary=f"已删除 {kind} Facet“{facet['name']}”",
            payload={"facetId": facet_id, "kind": kind},
            inverse=inverse,
            now=now,
        )
        return {
            "facetId": facet_id,
            "deleted": True,
            "operation": _operation_view(operation),
        }


__all__ = ["SqlAlchemyLibraryFacetManagement"]
