"""Session-backed adapters for import application collaborator ports."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.imports.application.audio_types import (
    AudioBundleStructure,
    AudioFileMetadata,
)
from app.modules.imports.application.dto import (
    BookIdentityDTO,
    ConversionArtifactDTO,
    ImportPreferencesDTO,
    ImportSystemEvent,
)
from app.modules.imports.application.errors import (
    AudioTrackLimitExceededError,
    ImportExecutionError,
)
from app.modules.imports.infrastructure.audio_cover import publish_audio_cover
from app.modules.library.infrastructure.facets import sync_work_facets
from app.modules.system.infrastructure.events import record_system_event
from app.services.audio_metadata import inspect_audio_bundle, parse_audio_metadata
from app.services.book_identity import logical_import_path, recognize_book_identity
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

    def logical_import_path(self, path: Path, original_name: str | None) -> str:
        return logical_import_path(self._db, self._settings, path, original_name)

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
        edition_id: str,
        metadata_items: tuple[AudioFileMetadata, ...],
        *,
        bundle_root: Path | None = None,
    ) -> str | None:
        possible_targets = {
            storage_root / "books" / work_id / edition_id / f"cover{extension}"
            for extension in (".jpg", ".png", ".webp", ".gif")
        }
        existing_targets = {path for path in possible_targets if path.exists()}
        published = publish_audio_cover(
            storage_root,
            work_id,
            edition_id,
            metadata_items,
            bundle_root=bundle_root,
        )
        if published:
            published_path = Path(published)
            if published_path not in existing_targets:
                self._new_publications.add(published_path)
        return published

    def finalize_publications(self) -> None:
        self._new_publications.clear()

    def rollback_publications(self) -> None:
        for path in tuple(self._new_publications):
            path.unlink(missing_ok=True)
        self._new_publications.clear()
