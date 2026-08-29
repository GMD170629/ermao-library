from __future__ import annotations

from datetime import UTC, datetime

from app.modules.reader.application.dto import (
    ReaderAccessScope,
    ReaderAssetDto,
    ReaderBookDto,
    ReaderEngineLocatorDto,
    ReaderReflowableExactLocationDto,
    ReaderResourceContextDto,
    ReaderResourceDto,
)
from app.modules.reader.infrastructure.resource_locator_index import (
    ResourceLocatorIndex,
)


class _ComicPageIndex:
    def canonical_href(self, resource_id: str, page_index: int) -> str | None:
        del resource_id, page_index
        return None


class _ReaderRepository:
    def __init__(self, source_format: str = "MOBI") -> None:
        resource = ReaderResourceDto(
            id="resource-1",
            book_id="book-1",
            source_node_id="source-1",
            title="Original publication",
            format=source_format,
            source_format=source_format,
            resource_index=1,
            sort_order=0,
            page_count=None,
            chapter_count=None,
            duration_ms=None,
            track_count=None,
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        self.context = ReaderResourceContextDto(
            book=ReaderBookDto("book-1", "Original publication", "Author"),
            resource=resource,
        )
        self.assets = [
            ReaderAssetDto(
                id="asset-1",
                title="Original publication",
                resource_id=resource.id,
                source_node_id="source-1",
                role="PRIMARY",
                mime_type="application/x-mobipocket-ebook",
                size_bytes=100,
                duration_ms=None,
                disc_number=None,
                track_number=None,
                sort_order=0,
                mtime_ms=1,
            )
        ]

    def get_context(self, resource_id: str) -> ReaderResourceContextDto | None:
        return self.context if resource_id == self.context.resource.id else None

    def list_assets(self, resource_id: str) -> list[ReaderAssetDto]:
        return self.assets if resource_id == self.context.resource.id else []

    def list_navigation_units(self, resource_id: str) -> list[object]:
        del resource_id
        return []


def _location(
    media_type: str = "application/xhtml+xml",
) -> ReaderReflowableExactLocationDto:
    return ReaderReflowableExactLocationDto(
        resource_href="chapter.xhtml",
        media_type=media_type,
        resource_progression=0.0,
        total_progression=0.0,
        engine_locator=ReaderEngineLocatorDto(
            platform="web",
            version="readium-test:1",
            payload_json="{}",
        ),
    )


def _scope() -> ReaderAccessScope:
    return ReaderAccessScope(
        is_admin=True,
        can_view_manual_imports=True,
        library_ids=(),
    )


def test_reflowable_validation_uses_local_parser_contract_without_server_open() -> None:
    for source_format in ("EPUB", "FB2", "TXT", "MOBI", "AZW", "AZW3", "PRC"):
        index = ResourceLocatorIndex(
            _ReaderRepository(source_format),
            _ComicPageIndex(),
        )
        assert index.validate(
            resource_id="resource-1",
            access_scope=_scope(),
            location=_location(),
        )


def test_reflowable_validation_rejects_non_reflowable_resource_or_media_type() -> None:
    pdf_index = ResourceLocatorIndex(
        _ReaderRepository("PDF"),
        _ComicPageIndex(),
    )
    mobi_index = ResourceLocatorIndex(
        _ReaderRepository("MOBI"),
        _ComicPageIndex(),
    )
    assert not pdf_index.validate(
        resource_id="resource-1",
        access_scope=_scope(),
        location=_location(),
    )
    assert not mobi_index.validate(
        resource_id="resource-1",
        access_scope=_scope(),
        location=_location("application/pdf"),
    )
