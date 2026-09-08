"""SQLAlchemy projections for paginated readable-resource details."""

from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast

from sqlalchemy import (
    false,
    func,
    select,
    true,
)
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.contracts.library_navigation import navigation_entry_id
from app.models import (
    Library,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibraryResourceAssetMetadata,
    LibrarySourceNode,
    ReadableResourceNavigationUnit,
)
from app.modules.library.application.resource_details import (
    ResourceAssetDetail,
    ResourceCurrentChapter,
    ResourceDetailAccessScope,
    ResourceDetailItem,
    ResourceDetailResource,
)
from app.modules.library.domain.asset_titles import (
    AssetTitleCandidate,
    resolve_asset_display_titles,
)
from app.modules.reader.public import ReaderV5LibraryPresentationQueryPort


class _PdfDocument(Protocol):
    def __len__(self) -> int: ...

    def close(self) -> None: ...


class _PdfiumModule(Protocol):
    def PdfDocument(self, path: str) -> _PdfDocument: ...


class SqlAlchemyResourceDetailQueries:
    def __init__(
        self,
        db: Session,
        user_id: str,
        *,
        reader_queries: ReaderV5LibraryPresentationQueryPort,
    ) -> None:
        self._db = db
        self._user_id = user_id
        self._reader_queries = reader_queries

    def get_resource(
        self,
        *,
        context: ResourceDetailAccessScope,
        book_id: str,
        resource_id: str,
    ) -> ResourceDetailResource | None:
        row = self._db.execute(
            select(
                LibraryReadableResource,
                LibraryReadableResourceMetadata,
            )
            .outerjoin(
                LibraryReadableResourceMetadata,
                LibraryReadableResourceMetadata.resource_id
                == LibraryReadableResource.id,
            )
            .where(
                LibraryReadableResource.id == resource_id,
                LibraryReadableResource.book_id == book_id,
                LibraryReadableResource.enablement_state == "ENABLED",
                LibraryReadableResource.import_state == "READY",
                (
                    true()
                    if context.is_admin
                    else LibraryReadableResource.library_id.in_(context.library_ids)
                    if context.library_ids
                    else false()
                ),
            )
        ).one_or_none()
        if row is None:
            return None
        resource, metadata = row
        progress = self._reader_queries.get_presentation(
            user_id=self._user_id,
            resource_id=resource.id,
        )
        reading_state = self._reader_queries.list_reading_states(
            user_id=self._user_id,
            resource_ids=[resource.id],
        )[resource.id]
        current_href = None
        current_page_number = None
        current_position = None
        current_href = progress.current_href if progress is not None else None
        current_page_number = progress.page_number if progress is not None else None
        current_chapter_index = progress.chapter_index if progress is not None else None
        current_chapter_title = progress.chapter_title if progress is not None else None
        return ResourceDetailResource(
            presentation=progress.presentation if progress is not None else None,
            id=resource.id,
            book_id=resource.book_id,
            format=resource.format,
            page_count=metadata.page_count if metadata is not None else None,
            progress=float(reading_state.display_percent),
            current_href=current_href,
            current_page_number=current_page_number,
            current_position=current_position,
            current_chapter_index=current_chapter_index,
            current_chapter_title=current_chapter_title,
            current_chapter_navigation_key=progress.chapter_navigation_key
            if progress is not None
            else None,
        )

    def list_navigation_units(
        self,
        *,
        resource_id: str,
        asset_id: str | None,
        unit_type: str,
        limit: int,
        offset: int,
    ) -> tuple[tuple[ResourceDetailItem, ...], int]:
        predicate: list[ColumnElement[bool]] = [
            ReadableResourceNavigationUnit.resource_id == resource_id,
            func.lower(ReadableResourceNavigationUnit.unit_type)
            == unit_type.casefold(),
        ]
        if asset_id is not None:
            predicate.append(ReadableResourceNavigationUnit.asset_id == asset_id)
        rows = self._db.scalars(
            select(ReadableResourceNavigationUnit)
            .where(*predicate)
            .order_by(
                ReadableResourceNavigationUnit.sort_order.asc(),
                ReadableResourceNavigationUnit.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        ).all()
        total = int(
            self._db.scalar(
                select(func.count())
                .select_from(ReadableResourceNavigationUnit)
                .where(*predicate)
            )
            or 0
        )
        return (
            tuple(_navigation_detail_item(row) for row in rows),
            total,
        )

    def count_chapters(self, *, resource_id: str, asset_id: str) -> int:
        return int(
            self._db.scalar(
                select(func.count())
                .select_from(ReadableResourceNavigationUnit)
                .where(
                    ReadableResourceNavigationUnit.resource_id == resource_id,
                    ReadableResourceNavigationUnit.asset_id == asset_id,
                    ReadableResourceNavigationUnit.unit_type == "chapter",
                    ReadableResourceNavigationUnit.href != "",
                )
            )
            or 0
        )

    def list_assets(self, *, resource_id: str) -> tuple[ResourceAssetDetail, ...]:
        rows = self._db.execute(
            select(
                LibraryResourceAsset,
                LibraryResourceAssetMetadata,
                LibrarySourceNode,
            )
            .join(
                LibrarySourceNode,
                LibrarySourceNode.id == LibraryResourceAsset.source_node_id,
            )
            .outerjoin(
                LibraryResourceAssetMetadata,
                LibraryResourceAssetMetadata.asset_id == LibraryResourceAsset.id,
            )
            .where(
                LibraryResourceAsset.resource_id == resource_id,
                LibraryResourceAsset.import_state == "READY",
                LibrarySourceNode.physical_kind == "REGULAR_FILE",
            )
            .order_by(
                LibraryResourceAsset.sequence_index.asc(),
                LibraryResourceAsset.sort_key.asc(),
                LibraryResourceAsset.id.asc(),
            )
        ).all()
        titles = resolve_asset_display_titles(
            AssetTitleCandidate(
                asset_id=asset.id,
                metadata_title=metadata.title if metadata is not None else None,
                source_filename=source.name,
            )
            for asset, metadata, source in rows
        )
        return tuple(
            ResourceAssetDetail(
                id=asset.id,
                role=asset.role,
                title=titles[asset.id],
                media_type=metadata.mime_type if metadata is not None else None,
                sort_key=source.relative_path,
                sort_order=asset.sequence_index or 0,
                duration_ms=metadata.duration_ms if metadata is not None else None,
                disc_number=metadata.disc_number if metadata is not None else None,
                track_number=metadata.track_number if metadata is not None else None,
            )
            for asset, metadata, source in rows
        )

    def resolve_pdf_page_count(self, *, resource_id: str) -> int | None:
        row = self._db.execute(
            select(
                Library.root_path,
                LibrarySourceNode.relative_path,
            )
            .join(
                LibraryResourceAsset,
                LibraryResourceAsset.library_id == Library.id,
            )
            .join(
                LibrarySourceNode,
                LibrarySourceNode.id == LibraryResourceAsset.source_node_id,
            )
            .where(
                LibraryResourceAsset.resource_id == resource_id,
                LibraryResourceAsset.role == "PRIMARY",
                LibraryResourceAsset.import_state == "READY",
                LibrarySourceNode.physical_kind == "REGULAR_FILE",
            )
            .order_by(
                LibraryResourceAsset.sequence_index.asc(),
                LibraryResourceAsset.id.asc(),
            )
            .limit(1)
        ).one_or_none()
        if row is None:
            return None
        path = self._safe_source_path(str(row.root_path), str(row.relative_path))
        if path is None:
            return None
        document: _PdfDocument | None = None
        try:
            pdfium = cast(_PdfiumModule, import_module("pypdfium2"))
            document = pdfium.PdfDocument(str(path))
            return max(0, len(document))
        except (OSError, RuntimeError, TypeError, ValueError):
            return None
        finally:
            if document is not None:
                document.close()

    @staticmethod
    def _safe_source_path(root_value: str, relative_value: str) -> Path | None:
        try:
            root = Path(root_value).expanduser().resolve(strict=True)
            candidate = root.joinpath(*Path(relative_value).parts)
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, ValueError):
            return None
        if resolved != candidate or not resolved.is_file():
            return None
        return resolved

    def resolve_current_chapter(
        self,
        *,
        resource_id: str,
        asset_id: str,
        navigation_key: str,
    ) -> ResourceCurrentChapter | None:
        row = self._db.scalar(
            select(ReadableResourceNavigationUnit).where(
                ReadableResourceNavigationUnit.resource_id == resource_id,
                ReadableResourceNavigationUnit.asset_id == asset_id,
                ReadableResourceNavigationUnit.unit_type == "chapter",
                ReadableResourceNavigationUnit.id
                == navigation_entry_id(resource_id, navigation_key),
                ReadableResourceNavigationUnit.href != "",
            )
        )
        return (
            None
            if row is None
            else ResourceCurrentChapter(
                index=row.sort_order,
                title=row.title,
                sort_order=row.sort_order,
                href=row.href,
            )
        )


def _navigation_detail_item(row: ReadableResourceNavigationUnit) -> ResourceDetailItem:
    metadata: object = json.loads(row.metadata_json or "{}")
    if not isinstance(metadata, dict):
        raise TypeError("Navigation metadata is not an object")
    level = metadata.get("level")
    navigation_key = metadata.get("navigationKey")
    return ResourceDetailItem(
        id=row.id,
        unit_type=row.unit_type,
        title=row.title,
        sort_order=row.sort_order,
        asset_id=row.asset_id,
        href=row.href or None,
        media_type=row.media_type,
        duration_ms=row.duration_ms,
        metadata_json=row.metadata_json,
        level=level
        if isinstance(level, int) and not isinstance(level, bool) and level >= 0
        else None,
        navigation_key=navigation_key if isinstance(navigation_key, str) else None,
    )


__all__ = ["SqlAlchemyResourceDetailQueries"]
