from __future__ import annotations

from datetime import UTC, datetime

from app.modules.publications.domain.model import PublicationUnsupportedError
from app.modules.reader.application.dto import (
    ReaderAccessScope,
    ReaderEngineLocatorDto,
    ReaderFileDto,
    ReaderReflowableExactLocationDto,
    ReaderVersionDto,
    ReaderVolumeContextDto,
    ReaderVolumeDto,
    ReaderWorkDto,
)
from app.modules.reader.infrastructure.publication_locator_index import (
    NormalizedPublicationLocatorIndex,
)


class _UnavailablePublication:
    def manifest(self, **_kwargs: object) -> None:
        raise PublicationUnsupportedError("MOBI runtime unavailable")


class _ReaderRepository:
    def __init__(self) -> None:
        volume = ReaderVolumeDto(
            id="volume-1",
            version_id="version-1",
            title="Legacy MOBI",
            volume_index=1,
            sort_order=0,
            format="MOBI",
            derived_from_volume_id=None,
            page_count=None,
            chapter_count=None,
            duration_ms=None,
            track_count=None,
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        self.context = ReaderVolumeContextDto(
            work=ReaderWorkDto("work-1", "Legacy MOBI", "Author"),
            version=ReaderVersionDto(
                "version-1",
                "work-1",
                "__implicit__",
                None,
            ),
            volume=volume,
        )
        self.files = [
            ReaderFileDto(
                id="file-1",
                volume_id=volume.id,
                kind="MOBI",
                mime_type="application/x-mobipocket-ebook",
                size_bytes=100,
                duration_ms=None,
                disc_number=None,
                track_number=None,
                sort_order=0,
                mtime_ms=1,
            )
        ]

    def get_context(self, volume_id: str) -> ReaderVolumeContextDto | None:
        return self.context if volume_id == self.context.volume.id else None

    def list_files(self, volume_id: str) -> list[ReaderFileDto]:
        return self.files if volume_id == self.context.volume.id else []


def test_reflowable_validation_fails_when_publication_is_unavailable() -> None:
    repository = _ReaderRepository()
    index = NormalizedPublicationLocatorIndex(
        _UnavailablePublication(),  # type: ignore[arg-type]
        repository,  # type: ignore[arg-type]
    )

    valid = index.validate(
        volume_id="volume-1",
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
