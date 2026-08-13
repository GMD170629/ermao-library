"""Adapter validating Reader locators against normalized publication resources."""

from dataclasses import asdict

from app.modules.publications.public import (
    NormalizedPublication,
    OpenPublication,
    PublicationAccessScope,
    PublicationCorruptError,
    PublicationNotFoundError,
    PublicationUnsupportedError,
)
from app.modules.reader.application.content_fingerprint import (
    build_publication_fingerprint,
)
from app.modules.reader.application.dto import (
    ReaderAccessScope,
    ReaderAudioExactLocationDto,
    ReaderComicExactLocationDto,
    ReaderExactLocationDto,
    ReaderPdfExactLocationDto,
    ReaderPublicationFingerprintDto,
    ReaderReflowableExactLocationDto,
)
from app.modules.reader.application.ports import ReaderVolumeRepository


class NormalizedPublicationLocatorIndex:
    def __init__(
        self,
        publications: OpenPublication,
        reader_repository: ReaderVolumeRepository,
    ) -> None:
        self._publications = publications
        self._reader_repository = reader_repository

    def fingerprint(
        self,
        *,
        volume_id: str,
        access_scope: ReaderAccessScope,
    ) -> ReaderPublicationFingerprintDto | None:
        publication = self._manifest(volume_id=volume_id, access_scope=access_scope)
        if publication is not None:
            return _publication_fingerprint(publication)
        return self._indexed_fingerprint(volume_id)

    def validate(
        self,
        *,
        volume_id: str,
        access_scope: ReaderAccessScope,
        location: ReaderExactLocationDto,
    ) -> ReaderPublicationFingerprintDto | None:
        if isinstance(location, ReaderReflowableExactLocationDto):
            publication = self._manifest(volume_id=volume_id, access_scope=access_scope)
            if publication is None or not any(
                link.href == location.resource_href
                and link.media_type == location.media_type
                for link in (*publication.reading_order, *publication.resources)
            ):
                return None
            return _publication_fingerprint(publication)
        if not self._is_indexed_location(volume_id, location):
            return None
        return self._indexed_fingerprint(volume_id)

    def _indexed_fingerprint(
        self, volume_id: str
    ) -> ReaderPublicationFingerprintDto | None:
        context = self._reader_repository.get_context(volume_id)
        if context is None or context.volume.format.lower() not in _INDEXED_FORMATS:
            return None
        files = self._reader_repository.list_files(volume_id)
        return build_publication_fingerprint(
            asdict(context.volume),
            [asdict(file) for file in files],
        )

    def _is_indexed_location(
        self,
        volume_id: str,
        location: ReaderExactLocationDto,
    ) -> bool:
        context = self._reader_repository.get_context(volume_id)
        if context is None:
            return False
        if isinstance(location, ReaderPdfExactLocationDto):
            return (
                context.volume.format.lower() == "pdf"
                and context.volume.page_count is not None
                and location.page_index < context.volume.page_count
            )
        if isinstance(location, ReaderComicExactLocationDto):
            if context.volume.format.lower() not in _COMIC_FORMATS:
                return False
            page_units = [
                unit
                for unit in self._reader_repository.list_units(volume_id)
                if unit.unit_type == "page"
            ]
            return (
                location.page_index < len(page_units)
                and page_units[location.page_index].href == location.resource_href
            )
        if isinstance(location, ReaderAudioExactLocationDto):
            if context.volume.format.lower() not in _AUDIO_FORMATS:
                return False
            files = self._reader_repository.list_files(volume_id)
            target = next((file for file in files if file.id == location.file_id), None)
            if target is None or not target.mime_type.lower().startswith("audio/"):
                return False
            if (
                target.duration_ms is not None
                and location.position_millis > target.duration_ms
            ):
                return False
            if location.chapter_id is None:
                return True
            return any(
                unit.id == location.chapter_id and unit.file_id == location.file_id
                for unit in self._reader_repository.list_units(volume_id)
            )
        return False

    def _manifest(
        self,
        *,
        volume_id: str,
        access_scope: ReaderAccessScope,
    ) -> NormalizedPublication | None:
        try:
            return self._publications.manifest(
                volume_id=volume_id,
                access_scope=PublicationAccessScope(
                    is_admin=access_scope.is_admin,
                    can_view_manual_imports=access_scope.can_view_manual_imports,
                    monitor_folder_ids=access_scope.monitor_folder_ids,
                ),
            )
        except (
            PublicationCorruptError,
            PublicationNotFoundError,
            PublicationUnsupportedError,
        ):
            return None


_AUDIO_FORMATS = frozenset(
    {"audio", "audiobook", "mp3", "m4b", "m4a", "flac", "ogg", "opus", "wav"}
)
_COMIC_FORMATS = frozenset({"cbz", "cbr", "zip", "rar"})
_INDEXED_FORMATS = _AUDIO_FORMATS | _COMIC_FORMATS | {"pdf"}


def _publication_fingerprint(
    publication: NormalizedPublication,
) -> ReaderPublicationFingerprintDto:
    return ReaderPublicationFingerprintDto(
        original_file_hash=publication.fingerprint.original_file_hash,
        parser=publication.fingerprint.parser,
        normalization=publication.fingerprint.normalization,
    )
