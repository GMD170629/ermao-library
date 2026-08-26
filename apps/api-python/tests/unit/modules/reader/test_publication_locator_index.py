from __future__ import annotations

from datetime import UTC, datetime

from app.modules.publications.domain.model import PublicationUnsupportedError
from app.modules.reader.application.dto import (
    ReaderAccessScope,
    ReaderAssetDto,
    ReaderBookDto,
    ReaderEngineLocatorDto,
    ReaderReflowableExactLocationDto,
    ReaderResourceContextDto,
    ReaderResourceDto,
)
from app.modules.reader.infrastructure.publication_locator_index import (
    NormalizedPublicationLocatorIndex,
)


class _UnavailablePublication:
    def manifest(self, **_kwargs: object) -> None:
        raise PublicationUnsupportedError("MOBI runtime unavailable")


class _ComicPageIndex:
    def canonical_href(self, resource_id: str, page_index: int) -> str | None:
        del resource_id, page_index
        return None


class _ReaderRepository:
    def __init__(self) -> None:
        resource = ReaderResourceDto(
            id="resource-1",
            book_id="book-1",
            source_node_id="source-1",
            title="Legacy MOBI",
            format="MOBI",
            source_format="MOBI",
            resource_index=1,
            sort_order=0,
            page_count=None,
            chapter_count=None,
            duration_ms=None,
            track_count=None,
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        self.context = ReaderResourceContextDto(
            book=ReaderBookDto("book-1", "Legacy MOBI", "Author"),
            resource=resource,
        )
        self.assets = [
            ReaderAssetDto(
                id="asset-1",
                title="Legacy MOBI",
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


def test_reflowable_validation_fails_when_publication_is_unavailable() -> None:
    repository = _ReaderRepository()
    index = NormalizedPublicationLocatorIndex(
        _UnavailablePublication(),  # type: ignore[arg-type]
        repository,  # type: ignore[arg-type]
        _ComicPageIndex(),
    )

    valid = index.validate(
        resource_id="resource-1",
        access_scope=ReaderAccessScope(
            is_admin=True,
            can_view_manual_imports=True,
            library_ids=(),
        ),
        location=ReaderReflowableExactLocationDto(
            resource_href="chapter.xhtml",
            media_type="application/xhtml+xml",
            resource_progression=0.0,
            total_progression=0.0,
            engine_locator=ReaderEngineLocatorDto(
                platform="web",
                version="readium-test:1",
                payload_json="{}",
            ),
        ),
    )

    assert valid is False
