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
    ReaderPublicationFingerprintDto,
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
        href: str,
        media_type: str,
    ) -> ReaderPublicationFingerprintDto | None:
        publication = self._manifest(volume_id=volume_id, access_scope=access_scope)
        if publication is not None:
            if not any(
                link.href == href and link.media_type == media_type
                for link in (*publication.reading_order, *publication.resources)
            ):
                return None
            return _publication_fingerprint(publication)
        if not self._is_indexed_resource(volume_id, href, media_type):
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

    def _is_indexed_resource(
        self,
        volume_id: str,
        href: str,
        media_type: str,
    ) -> bool:
        context = self._reader_repository.get_context(volume_id)
        if context is None:
            return False
        normalized_format = context.volume.format.lower()
        if normalized_format in _AUDIO_FORMATS:
            return any(
                file.id == href and file.mime_type == media_type
                for file in self._reader_repository.list_files(volume_id)
            )
        page_number = _canonical_page_number(href)
        if page_number is None:
            return False
        if normalized_format == "pdf":
            return (
                media_type == "application/pdf"
                and context.volume.page_count is not None
                and page_number <= context.volume.page_count
            )
        if normalized_format not in _COMIC_FORMATS:
            return False
        page_units = [
            unit
            for unit in self._reader_repository.list_units(volume_id)
            if unit.unit_type == "page"
        ]
        if page_number > len(page_units):
            return False
        return page_units[page_number - 1].media_type == media_type

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


def _canonical_page_number(href: str) -> int | None:
    prefix = "page-"
    if not href.startswith(prefix):
        return None
    raw_number = href.removeprefix(prefix)
    if not raw_number.isascii() or not raw_number.isdecimal():
        return None
    page_number = int(raw_number)
    return page_number if page_number >= 1 else None


def _publication_fingerprint(
    publication: NormalizedPublication,
) -> ReaderPublicationFingerprintDto:
    return ReaderPublicationFingerprintDto(
        original_file_hash=publication.fingerprint.original_file_hash,
        parser=publication.fingerprint.parser,
        normalization=publication.fingerprint.normalization,
    )
