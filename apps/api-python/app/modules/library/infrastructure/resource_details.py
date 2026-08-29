"""SQLAlchemy projections for paginated readable-resource details."""

from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast

from sqlalchemy import (
    Integer,
    and_,
    case,
    false,
    func,
    or_,
    select,
    true,
)
from sqlalchemy import cast as sql_cast
from sqlalchemy.orm import Session

from app.models import (
    Library,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibraryResourceAssetMetadata,
    LibrarySourceNode,
    ReadableResourceNavigationUnit,
    ReaderResourceProgress,
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


def _progress_position(
    location_json: str | None,
    *,
    fallback_href: str | None,
    fallback_page: int | None,
) -> tuple[str | None, int | None, int | None]:
    if not location_json:
        return fallback_href, fallback_page, None
    try:
        value = json.loads(location_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback_href, fallback_page, None
    if not isinstance(value, dict):
        return fallback_href, fallback_page, None
    kind = value.get("kind")
    if kind == "reflowable":
        engine = value.get("engineLocator")
        payload = engine.get("payload") if isinstance(engine, dict) else None
        href = payload.get("href") if isinstance(payload, dict) else None
        locations = payload.get("locations") if isinstance(payload, dict) else None
        locations = locations if isinstance(locations, dict) else {}
        fragments = locations.get("fragments")
        if (
            isinstance(href, str)
            and "#" not in href
            and isinstance(fragments, list)
            and len(fragments) == 1
            and isinstance(fragments[0], str)
            and fragments[0]
        ):
            href = f"{href}#{fragments[0].lstrip('#')}"
        position = locations.get("position")
        return (
            (href.strip() if isinstance(href, str) and href.strip() else fallback_href),
            None,
            (
                position
                if isinstance(position, int)
                and not isinstance(position, bool)
                and position >= 1
                else None
            ),
        )
    if kind in {"comic", "pdf"}:
        page_index = value.get("pageIndex")
        if isinstance(page_index, int) and page_index >= 0:
            return None, page_index + 1, None
    return fallback_href, fallback_page, None


class _PdfDocument(Protocol):
    def __len__(self) -> int: ...

    def close(self) -> None: ...


class _PdfiumModule(Protocol):
    def PdfDocument(self, path: str) -> _PdfDocument: ...


class SqlAlchemyResourceDetailQueries:
    def __init__(self, db: Session, user_id: str) -> None:
        self._db = db
        self._user_id = user_id

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
                ReaderResourceProgress,
            )
            .outerjoin(
                LibraryReadableResourceMetadata,
                LibraryReadableResourceMetadata.resource_id
                == LibraryReadableResource.id,
            )
            .outerjoin(
                ReaderResourceProgress,
                (ReaderResourceProgress.resource_id == LibraryReadableResource.id)
                & (ReaderResourceProgress.user_id == self._user_id),
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
        resource, metadata, progress = row
        current_href = None
        current_page_number = None
        current_position = None
        if progress is not None:
            current_href, current_page_number, current_position = _progress_position(
                progress.location_json,
                fallback_href=str(progress.position or "").strip() or None,
                fallback_page=progress.page,
            )
        return ResourceDetailResource(
            id=resource.id,
            book_id=resource.book_id,
            format=resource.format,
            page_count=metadata.page_count if metadata is not None else None,
            progress=float(progress.percent if progress is not None else 0),
            current_href=current_href,
            current_page_number=current_page_number,
            current_position=current_position,
        )

    def list_navigation_units(
        self,
        *,
        resource_id: str,
        unit_type: str,
        limit: int,
        offset: int,
    ) -> tuple[tuple[ResourceDetailItem, ...], int]:
        predicate = (
            ReadableResourceNavigationUnit.resource_id == resource_id,
            func.lower(ReadableResourceNavigationUnit.unit_type)
            == unit_type.casefold(),
        )
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
            tuple(
                ResourceDetailItem(
                    id=row.id,
                    unit_type=row.unit_type,
                    title=row.title,
                    sort_order=row.sort_order,
                    asset_id=row.asset_id,
                    href=row.href,
                    media_type=row.media_type,
                    duration_ms=row.duration_ms,
                    metadata_json=row.metadata_json,
                )
                for row in rows
            ),
            total,
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
        current_href: str | None,
        current_position: int | None,
    ) -> ResourceCurrentChapter | None:
        base_predicate = (
            ReadableResourceNavigationUnit.resource_id == resource_id,
            func.lower(ReadableResourceNavigationUnit.unit_type) == "chapter",
        )
        row: ReadableResourceNavigationUnit | None = None
        if current_href:
            href_rows = self._db.scalars(
                select(ReadableResourceNavigationUnit)
                .where(
                    *base_predicate,
                    func.lower(ReadableResourceNavigationUnit.href)
                    == current_href.casefold(),
                )
                .order_by(
                    ReadableResourceNavigationUnit.sort_order.asc(),
                    ReadableResourceNavigationUnit.id.asc(),
                )
                .limit(2)
            ).all()
            if len(href_rows) == 1:
                row = href_rows[0]

        if row is None and current_position is not None:
            safe_metadata = case(
                (
                    func.json_valid(ReadableResourceNavigationUnit.metadata_json) == 1,
                    ReadableResourceNavigationUnit.metadata_json,
                ),
                else_="{}",
            )
            position_expression = sql_cast(
                func.json_extract(safe_metadata, "$.readingOrderPosition"),
                Integer,
            )
            nearest_position = self._db.scalar(
                select(func.max(position_expression)).where(
                    *base_predicate,
                    position_expression <= current_position,
                )
            )
            if nearest_position is not None:
                position_rows = self._db.scalars(
                    select(ReadableResourceNavigationUnit)
                    .where(
                        *base_predicate,
                        position_expression == nearest_position,
                    )
                    .order_by(
                        ReadableResourceNavigationUnit.sort_order.asc(),
                        ReadableResourceNavigationUnit.id.asc(),
                    )
                    .limit(2)
                ).all()
                if len(position_rows) == 1:
                    row = position_rows[0]

        if row is None:
            return None
        chapter_index = int(
            self._db.scalar(
                select(func.count())
                .select_from(ReadableResourceNavigationUnit)
                .where(
                    *base_predicate,
                    or_(
                        ReadableResourceNavigationUnit.sort_order < row.sort_order,
                        and_(
                            ReadableResourceNavigationUnit.sort_order == row.sort_order,
                            ReadableResourceNavigationUnit.id < row.id,
                        ),
                    ),
                )
            )
            or 0
        )
        return ResourceCurrentChapter(
            index=chapter_index,
            title=row.title,
            sort_order=row.sort_order,
            href=row.href,
        )


__all__ = ["SqlAlchemyResourceDetailQueries"]
