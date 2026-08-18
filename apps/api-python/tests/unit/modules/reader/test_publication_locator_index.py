from __future__ import annotations

from datetime import UTC, datetime

from app.modules.publications.application.resolve_source_identity import (
    PublicationSourceIdentity,
)
from app.modules.publications.domain.model import PublicationUnsupportedError
from app.modules.reader.application.dto import (
    ReaderAccessScope,
    ReaderFileDto,
    ReaderMediaVersionDto,
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


class _SourceIdentity:
    def execute(self, **_kwargs: object) -> PublicationSourceIdentity:
        return PublicationSourceIdentity(
            original_file_hash="sha256:" + "a" * 64,
            source_format="mobi",
        )


class _ReaderRepository:
    def __init__(self) -> None:
        volume = ReaderVolumeDto(
            id="volume-1",
            media_version_id="media-1",
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
            media_version=ReaderMediaVersionDto("media-1", "work-1", "EBOOK"),
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
                fingerprint=None,
                full_hash=None,
                mtime_ms=1,
            )
        ]

    def get_context(self, volume_id: str) -> ReaderVolumeContextDto | None:
        return self.context if volume_id == self.context.volume.id else None

    def list_files(self, volume_id: str) -> list[ReaderFileDto]:
        return self.files if volume_id == self.context.volume.id else []


def test_uses_actual_source_hash_when_mobi_parser_is_unavailable() -> None:
    repository = _ReaderRepository()
    index = NormalizedPublicationLocatorIndex(
        _UnavailablePublication(),  # type: ignore[arg-type]
        repository,  # type: ignore[arg-type]
        _SourceIdentity(),  # type: ignore[arg-type]
    )

    fingerprint = index.fingerprint(
        volume_id="volume-1",
        access_scope=ReaderAccessScope(
            is_admin=True,
            can_view_manual_imports=True,
            library_ids=(),
        ),
    )

    assert fingerprint is not None
    assert fingerprint.original_file_hash == "sha256:" + "a" * 64
    assert fingerprint.parser.startswith("libmobi:0.12")
    assert fingerprint.normalization == "ermao-mobi-core-v1+shuku-locator-dom-v2"
