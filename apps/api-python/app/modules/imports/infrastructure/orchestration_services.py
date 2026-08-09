"""Session-backed adapters for import application collaborator ports."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.contracts.local_metadata import LocalMetadataSource
from app.core.config import Settings
from app.core.time import now_timestamp_ms
from app.infrastructure.comic_archives import (
    extract_comic_cover,
    inspect_comic_archive,
)
from app.infrastructure.local_metadata_policy import load_local_metadata_priority
from app.models.settings import MonitorFolder
from app.modules.imports.application.audio_types import (
    AudioBundleStructure,
    AudioFileMetadata,
)
from app.modules.imports.application.comic_types import ComicArchiveInspection
from app.modules.imports.application.dto import (
    BookIdentityDTO,
    ConversionArtifactDTO,
    DirectorySiblingSnapshotDTO,
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
from app.modules.imports.application.ports import (
    ImportUnitOfWork,
    TextConversionProgressStore,
)
from app.modules.imports.application.reflowable_types import ReflowableBookMetadata
from app.modules.imports.infrastructure.audio_cover import publish_audio_cover
from app.modules.imports.infrastructure.conversion import bind_derived_volume
from app.modules.imports.infrastructure.conversion_progress import (
    SqlAlchemyTextConversionProgress,
)
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
from app.modules.library.infrastructure.facets import sync_work_facets
from app.modules.system.infrastructure.events import record_system_event
from app.services.audio_metadata import inspect_audio_bundle, parse_audio_metadata
from app.services.book_identity import (
    recognize_book_identity,
    recognize_book_identity_with_regex,
)
from app.services.default_cover import (
    cover_status,
    ensure_default_cover,
    is_default_cover_path,
)
from app.services.import_preferences import load_import_preferences
from app.services.text_conversion import ConversionFailure, convert_to_epub


class SessionImportOrchestrationServices:
    def __init__(
        self,
        db: Session,
        settings: Settings,
        unit_of_work: ImportUnitOfWork | None = None,
        conversion_progress: TextConversionProgressStore | None = None,
    ) -> None:
        self._db = db
        self._settings = settings
        self._unit_of_work = unit_of_work or SqlAlchemyImportUnitOfWork(db)
        self._conversion_progress = conversion_progress

    def _text_conversion_progress(self) -> TextConversionProgressStore:
        if self._conversion_progress is None:
            self._conversion_progress = SqlAlchemyTextConversionProgress(
                sessionmaker(
                    bind=self._db.get_bind(),
                    autoflush=False,
                    expire_on_commit=False,
                )
            )
        return self._conversion_progress

    def _require_released_transaction(self, operation: str) -> None:
        if self._db.in_transaction():
            raise RuntimeError(
                f"import external operation started inside a database transaction: {operation}"
            )

    def load_preferences(self) -> ImportPreferencesDTO:
        preferences = load_import_preferences(self._db)
        return ImportPreferencesDTO(
            auto_convert_to_epub=preferences.auto_convert_to_epub,
            allowed_extensions=preferences.allowed_extensions,
            ignore_patterns=preferences.ignore_patterns,
        )

    def load_local_metadata_priority(self) -> tuple[LocalMetadataSource, ...]:
        return load_local_metadata_priority(self._db)

    def convert_text(
        self, import_task_id: str, source_path: Path
    ) -> ConversionArtifactDTO:
        self._require_released_transaction("convert_text")
        try:
            artifact = convert_to_epub(
                self._text_conversion_progress(),
                self._settings,
                import_task_id,
                source_path,
            )
        except ConversionFailure as exc:
            raise ImportExecutionError(
                exc.code,
                str(exc),
                retryable=exc.retryable,
            ) from exc
        return ConversionArtifactDTO(
            source_path=artifact.source_path,
            output_path=artifact.output_path,
            source_format=artifact.source_format,
            source_hash=artifact.source_hash,
            converter=artifact.converter,
            converter_version=artifact.converter_version,
            cached=artifact.cached,
            idempotency_key=artifact.idempotency_key,
        )

    def bind_conversion_result(
        self, idempotency_key: str, derived_volume_id: str
    ) -> None:
        bind_derived_volume(
            self._db,
            idempotency_key=idempotency_key,
            derived_volume_id=derived_volume_id,
            now=now_timestamp_ms(),
        )

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

    def parse_filename_identity(self, filename: str) -> BookIdentityDTO:
        safe_filename = Path(filename).name
        identity = recognize_book_identity_with_regex(safe_filename)
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

    def monitor_root_path(self, monitor_folder_id: str | None) -> Path | None:
        if monitor_folder_id is None:
            return None
        root_path = self._db.scalar(
            select(MonitorFolder.root_path).where(MonitorFolder.id == monitor_folder_id)
        )
        self._unit_of_work.release()
        if root_path is None:
            return None
        return Path(root_path).expanduser().resolve()

    def list_sibling_files(self, path: Path) -> DirectorySiblingSnapshotDTO:
        self._require_released_transaction("list_sibling_files")
        resolved = path.resolve()
        try:
            siblings = tuple(
                candidate.resolve()
                for candidate in resolved.parent.iterdir()
                if candidate.is_file()
                and not candidate.is_symlink()
                and candidate.resolve() != resolved
            )
        except OSError:
            return DirectorySiblingSnapshotDTO(paths=(), complete=False)
        return DirectorySiblingSnapshotDTO(paths=siblings, complete=True)

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
        sync_work_facets(self._db, work_id)

    def stage_system_event(self, event: ImportSystemEvent) -> None:
        record_system_event(
            self._db,
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
        media_version_id: str,
        volume_id: str,
        entry_name: str,
    ) -> str:
        self._require_released_transaction("publish_comic_cover")
        published = extract_comic_cover(
            storage_root,
            source_path,
            work_id,
            media_version_id,
            volume_id,
            entry_name,
        )
        return published

    def publish_sidecar_cover(
        self,
        storage_root: Path,
        source_path: Path,
        work_id: str,
        media_version_id: str,
        volume_id: str,
    ) -> str:
        self._require_released_transaction("publish_sidecar_cover")
        published = publish_sidecar_cover(
            storage_root,
            source_path,
            work_id,
            media_version_id,
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
        media_version_id: str,
        metadata_items: tuple[AudioFileMetadata, ...],
        *,
        bundle_root: Path | None = None,
    ) -> str | None:
        self._require_released_transaction("publish_audio_cover")
        published = publish_audio_cover(
            storage_root,
            work_id,
            media_version_id,
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
                chapters=(),
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
        media_version_id: str,
        volume_id: str,
        metadata: ReflowableBookMetadata,
    ) -> str | None:
        self._require_released_transaction("publish_reflowable_cover")
        published = publish_reflowable_cover(
            storage_root,
            work_id,
            media_version_id,
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
        media_version_id: str,
        volume_id: str,
    ) -> PdfCoverPublication:
        self._require_released_transaction("publish_pdf_cover")
        publication = publish_pdf_cover(
            storage_root,
            source_path,
            work_id,
            media_version_id,
            volume_id,
        )
        return publication
