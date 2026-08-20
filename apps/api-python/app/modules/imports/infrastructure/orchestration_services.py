"""Session-backed adapters for import application collaborator ports."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.contracts.local_metadata import LocalMetadataSource
from app.core.config import Settings
from app.infrastructure.comic_archives import (
    extract_comic_cover,
    inspect_comic_archive,
)
from app.infrastructure.local_metadata_policy import (
    load_raw_local_metadata_priority_projection,
    prepare_local_metadata_priority,
)
from app.models.common import db_timestamp
from app.modules.imports.application.audio_types import (
    AudioBundleStructure,
    AudioFileMetadata,
)
from app.modules.imports.application.comic_types import ComicArchiveInspection
from app.modules.imports.application.dto import (
    BookIdentityDTO,
    ImportPreferencesDTO,
    ImportSystemEvent,
    SidecarMetadataDTO,
)
from app.modules.imports.application.errors import (
    AudioInspectionError,
    AudioTrackLimitExceededError,
    ImportExecutionError,
)
from app.modules.imports.application.pdf_types import (
    PdfCoverPublication,
    PdfInspection,
)
from app.modules.imports.application.ports import ImportUnitOfWork
from app.modules.imports.application.reflowable_types import ReflowableBookMetadata
from app.modules.imports.application.transactions import PreparedImportWriteBuffer
from app.modules.imports.infrastructure.audio_cover import publish_audio_cover
from app.modules.imports.infrastructure.pdf_inspection import (
    inspect_pdf,
    publish_pdf_cover,
)
from app.modules.imports.infrastructure.reflowable_cover import (
    publish_reflowable_cover,
)
from app.modules.imports.infrastructure.reflowable_metadata import (
    ReflowableMetadataError,
    inspect_reflowable_book,
)
from app.modules.imports.infrastructure.sidecar_cover import publish_sidecar_cover
from app.modules.imports.infrastructure.sidecar_opf import discover_sidecar_opf
from app.modules.imports.infrastructure.uow import SqlAlchemyImportUnitOfWork
from app.modules.library.application.facet_sync import prepare_work_facet
from app.modules.library.infrastructure.facet_sync import (
    execute_work_facet_write,
    load_work_facet_projections,
    prepare_work_facet_write,
)
from app.services.audio_metadata import inspect_audio_bundle, parse_audio_metadata
from app.services.book_identity import recognize_book_identity
from app.services.default_cover import (
    cover_status,
    ensure_default_cover,
    is_default_cover_path,
)
from app.services.import_preferences import (
    load_raw_import_preferences_projection,
    prepare_import_preferences,
)
from app.services.system_events import (
    prepare_system_event,
)


class SessionImportOrchestrationServices:
    def __init__(
        self,
        db: Session,
        settings: Settings,
        unit_of_work: ImportUnitOfWork | None = None,
        write_buffer: PreparedImportWriteBuffer | None = None,
    ) -> None:
        self._db = db
        self._settings = settings
        self._unit_of_work = unit_of_work or SqlAlchemyImportUnitOfWork(db)
        self._write_buffer = write_buffer or PreparedImportWriteBuffer()

    def _require_released_transaction(self, operation: str) -> None:
        if self._db.in_transaction():
            raise RuntimeError(
                f"import external operation started inside a database transaction: {operation}"
            )

    def load_preferences(self) -> ImportPreferencesDTO:
        projection = load_raw_import_preferences_projection(self._db)
        self._unit_of_work.release()
        preferences = prepare_import_preferences(projection)
        return ImportPreferencesDTO(
            allowed_extensions=preferences.allowed_extensions,
            ignore_patterns=preferences.ignore_patterns,
        )

    def load_local_metadata_priority(self) -> tuple[LocalMetadataSource, ...]:
        projection = load_raw_local_metadata_priority_projection(self._db)
        self._unit_of_work.release()
        return prepare_local_metadata_priority(projection)

    def recognize_identity(
        self, path: Path, original_name: str | None
    ) -> BookIdentityDTO:
        self._require_released_transaction("recognize_identity")
        identity = recognize_book_identity(
            self._db, self._settings, path, original_name
        )
        self._unit_of_work.release()
        return BookIdentityDTO(
            title=identity.title,
            author=identity.author,
            volume_index=identity.volume_index,
            source=identity.source,
            confidence=identity.confidence,
            logical_path=identity.logical_path,
            fallback_reason=identity.fallback_reason,
            fallback_code=identity.fallback_code,
            cache_hit=identity.cache_hit,
        )

    def recognize_filename_identity(self, filename: str) -> BookIdentityDTO:
        self._require_released_transaction("recognize_filename_identity")
        safe_filename = Path(filename).name
        identity = recognize_book_identity(
            self._db,
            self._settings,
            Path(safe_filename),
            safe_filename,
        )
        self._unit_of_work.release()
        return BookIdentityDTO(
            title=identity.title,
            author=identity.author,
            volume_index=identity.volume_index,
            source=identity.source,
            confidence=identity.confidence,
            logical_path=identity.logical_path,
            fallback_reason=identity.fallback_reason,
            fallback_code=identity.fallback_code,
            cache_hit=identity.cache_hit,
        )

    def read_sidecar_metadata(
        self, path: Path, *, directory_fallback: bool
    ) -> SidecarMetadataDTO | None:
        self._require_released_transaction("read_sidecar_metadata")
        result = discover_sidecar_opf(path, directory_fallback=directory_fallback)
        if result is None:
            return None
        return SidecarMetadataDTO(
            metadata=result.metadata,
            cover_path=result.cover_path,
            source_kind=result.source_kind,
            field_sources=result.field_sources,
        )

    def sync_work_facets(self, work_id: str) -> None:
        projections = load_work_facet_projections(self._db, (work_id,))
        self._unit_of_work.release()
        prepared = prepare_work_facet_write(
            tuple(prepare_work_facet(projection) for projection in projections),
            now=db_timestamp(),
        )
        execute_work_facet_write(self._db, prepared)
        self._unit_of_work.release()

    def stage_system_event(self, event: ImportSystemEvent) -> None:
        prepared_event = prepare_system_event(
            source=event.source,
            action=event.action,
            message=event.message,
            level=event.level,
            actor_type=event.actor_type,
            actor_id=event.actor_id,
            target_type=event.target_type,
            target_id=event.target_id,
            metadata=dict(event.metadata) if event.metadata is not None else None,
        )
        self._write_buffer.stage_system_event(prepared_event)

    def ensure_default_cover(self) -> str:
        self._require_released_transaction("ensure_default_cover")
        return ensure_default_cover(self._settings)

    def cover_status(self, value: object) -> str:
        return cover_status(value, self._settings)

    def is_default_cover_path(self, value: object) -> bool:
        return is_default_cover_path(value, self._settings)

    def inspect_comic_archive(
        self, path: Path, original_name: str | None
    ) -> ComicArchiveInspection:
        self._require_released_transaction("inspect_comic_archive")
        return inspect_comic_archive(path, original_name)

    def publish_comic_cover(
        self,
        storage_root: Path,
        source_path: Path,
        work_id: str,
        version_id: str,
        volume_id: str,
        entry_name: str,
    ) -> str:
        self._require_released_transaction("publish_comic_cover")
        published = extract_comic_cover(
            storage_root,
            source_path,
            work_id,
            version_id,
            volume_id,
            entry_name,
        )
        return published

    def publish_sidecar_cover(
        self,
        storage_root: Path,
        source_path: Path,
        work_id: str,
        version_id: str,
        volume_id: str,
    ) -> str:
        self._require_released_transaction("publish_sidecar_cover")
        published = publish_sidecar_cover(
            storage_root,
            source_path,
            work_id,
            version_id,
            volume_id,
        )
        return published

    def inspect_audio_bundle(self, path: Path) -> AudioBundleStructure | None:
        self._require_released_transaction("inspect_audio_bundle")
        try:
            return inspect_audio_bundle(path)
        except AudioTrackLimitExceededError as exc:
            raise ImportExecutionError(
                exc.code,
                str(exc),
                retryable=False,
            ) from exc

    def parse_audio_metadata(self, path: Path) -> AudioFileMetadata:
        self._require_released_transaction("parse_audio_metadata")
        try:
            return parse_audio_metadata(path)
        except AudioInspectionError as exc:
            raise ImportExecutionError(
                exc.code,
                str(exc),
                retryable=False,
            ) from exc

    def publish_audio_cover(
        self,
        storage_root: Path,
        work_id: str,
        version_id: str,
        metadata_items: tuple[AudioFileMetadata, ...],
        *,
        bundle_root: Path | None = None,
    ) -> str | None:
        self._require_released_transaction("publish_audio_cover")
        published = publish_audio_cover(
            storage_root,
            work_id,
            version_id,
            metadata_items,
            bundle_root=bundle_root,
        )
        return published

    def inspect_reflowable_book(
        self, path: Path, source_format: str
    ) -> ReflowableBookMetadata:
        self._require_released_transaction("inspect_reflowable_book")
        try:
            return inspect_reflowable_book(path, source_format)
        except ReflowableMetadataError as exc:
            return ReflowableBookMetadata(
                title=path.stem,
                authors=(),
                language=None,
                publisher=None,
                published_at=None,
                identifier=None,
                isbn=None,
                description=None,
                subjects=(),
                cover=None,
                raw_metadata={
                    "sourceFormat": source_format,
                    "inspectionWarning": str(exc),
                },
            )

    def publish_reflowable_cover(
        self,
        storage_root: Path,
        work_id: str,
        version_id: str,
        volume_id: str,
        metadata: ReflowableBookMetadata,
    ) -> str | None:
        self._require_released_transaction("publish_reflowable_cover")
        published = publish_reflowable_cover(
            storage_root,
            work_id,
            version_id,
            volume_id,
            metadata.cover,
        )
        return published

    def inspect_pdf(self, path: Path, original_name: str | None) -> PdfInspection:
        self._require_released_transaction("inspect_pdf")
        return inspect_pdf(path, original_name)

    def publish_pdf_cover(
        self,
        storage_root: Path,
        source_path: Path,
        work_id: str,
        version_id: str,
        volume_id: str,
    ) -> PdfCoverPublication:
        self._require_released_transaction("publish_pdf_cover")
        publication = publish_pdf_cover(
            storage_root,
            source_path,
            work_id,
            version_id,
            volume_id,
        )
        return publication
