"""Session-backed adapters for import application collaborator ports."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.time import now_timestamp_ms
from app.infrastructure.comic_archives import (
    extract_comic_cover,
    inspect_comic_archive,
)
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
)
from app.modules.imports.application.errors import (
    AudioTrackLimitExceededError,
    ImportExecutionError,
)
from app.modules.imports.application.pdf_types import (
    PdfCoverPublication,
    PdfInspection,
)
from app.modules.imports.application.reflowable_types import ReflowableBookMetadata
from app.modules.imports.infrastructure.audio_cover import publish_audio_cover
from app.modules.imports.infrastructure.conversion import bind_derived_volume
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
from app.modules.library.infrastructure.facets import sync_work_facets
from app.modules.system.infrastructure.events import record_system_event
from app.models.settings import MonitorFolder
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
    def __init__(self, db: Session, settings: Settings) -> None:
        self._db = db
        self._settings = settings
        self._new_publications: set[Path] = set()

    def load_preferences(self) -> ImportPreferencesDTO:
        preferences = load_import_preferences(self._db)
        return ImportPreferencesDTO(
            auto_convert_to_epub=preferences.auto_convert_to_epub,
            allowed_extensions=preferences.allowed_extensions,
            ignore_patterns=preferences.ignore_patterns,
        )

    def convert_text(
        self, import_task_id: str, source_path: Path
    ) -> ConversionArtifactDTO:
        try:
            artifact = convert_to_epub(
                self._db,
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
        identity = recognize_book_identity(
            self._db, self._settings, path, original_name
        )
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
            reused_work_id=identity.reused_work_id,
        )

    def recognize_filename_identity(self, filename: str) -> BookIdentityDTO:
        safe_filename = Path(filename).name
        identity = recognize_book_identity(
            self._db,
            self._settings,
            Path(safe_filename),
            safe_filename,
        )
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
            reused_work_id=identity.reused_work_id,
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
            reused_work_id=identity.reused_work_id,
        )

    def is_monitor_root(self, path: Path) -> bool:
        resolved_path = path.expanduser().resolve()
        root_paths = self._db.scalars(select(MonitorFolder.root_path)).all()
        return any(
            Path(root_path).expanduser().resolve() == resolved_path
            for root_path in root_paths
        )

    def list_sibling_files(self, path: Path) -> DirectorySiblingSnapshotDTO:
        resolved = path.resolve()
        try:
            siblings = tuple(
                candidate.resolve()
                for candidate in resolved.parent.iterdir()
                if candidate.is_file() and candidate.resolve() != resolved
            )
        except OSError:
            return DirectorySiblingSnapshotDTO(paths=(), complete=False)
        return DirectorySiblingSnapshotDTO(paths=siblings, complete=True)

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
        return ensure_default_cover(self._settings)

    def cover_status(self, value: object) -> str:
        return cover_status(value, self._settings)

    def is_default_cover_path(self, value: object) -> bool:
        return is_default_cover_path(value, self._settings)

    def inspect_comic_archive(
        self, path: Path, original_name: str | None
    ) -> ComicArchiveInspection:
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
        published = extract_comic_cover(
            storage_root,
            source_path,
            work_id,
            media_version_id,
            volume_id,
            entry_name,
        )
        self._new_publications.add(Path(published))
        return published

    def inspect_audio_bundle(self, path: Path) -> AudioBundleStructure | None:
        try:
            return inspect_audio_bundle(path)
        except AudioTrackLimitExceededError as exc:
            raise ImportExecutionError(
                exc.code,
                str(exc),
                retryable=False,
            ) from exc

    def parse_audio_metadata(self, path: Path) -> AudioFileMetadata:
        return parse_audio_metadata(path)

    def publish_audio_cover(
        self,
        storage_root: Path,
        work_id: str,
        media_version_id: str,
        metadata_items: tuple[AudioFileMetadata, ...],
        *,
        bundle_root: Path | None = None,
    ) -> str | None:
        possible_targets = {
            storage_root / "books" / work_id / media_version_id / f"cover{extension}"
            for extension in (".jpg", ".png", ".webp", ".gif")
        }
        existing_targets = {path for path in possible_targets if path.exists()}
        published = publish_audio_cover(
            storage_root,
            work_id,
            media_version_id,
            metadata_items,
            bundle_root=bundle_root,
        )
        if published:
            published_path = Path(published)
            if published_path not in existing_targets:
                self._new_publications.add(published_path)
        return published

    def inspect_reflowable_book(
        self, path: Path, source_format: str
    ) -> ReflowableBookMetadata:
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
        metadata: ReflowableBookMetadata,
    ) -> str | None:
        published = publish_reflowable_cover(
            storage_root,
            work_id,
            media_version_id,
            metadata.cover,
        )
        if published:
            self._new_publications.add(Path(published))
        return published

    def inspect_pdf(self, path: Path, original_name: str | None) -> PdfInspection:
        return inspect_pdf(path, original_name)

    def publish_pdf_cover(
        self,
        storage_root: Path,
        source_path: Path,
        work_id: str,
        media_version_id: str,
    ) -> PdfCoverPublication:
        publication = publish_pdf_cover(
            storage_root,
            source_path,
            work_id,
            media_version_id,
        )
        if publication.path:
            self._new_publications.add(Path(publication.path))
        return publication

    def finalize_publications(self) -> None:
        self._new_publications.clear()

    def rollback_publications(self) -> None:
        for path in tuple(self._new_publications):
            path.unlink(missing_ok=True)
        self._new_publications.clear()
