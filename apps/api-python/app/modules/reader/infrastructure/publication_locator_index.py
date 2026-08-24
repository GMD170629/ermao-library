"""Adapter validating Reader locators against normalized publication resources."""

from app.modules.publications.public import (
    NormalizedPublication,
    OpenPublication,
    PublicationAccessScope,
    PublicationCorruptError,
    PublicationNotFoundError,
    PublicationUnsupportedError,
)
from app.modules.reader.application.dto import (
    ReaderAccessScope,
    ReaderAudioExactLocationDto,
    ReaderComicExactLocationDto,
    ReaderExactLocationDto,
    ReaderPdfExactLocationDto,
    ReaderReflowableExactLocationDto,
)
from app.modules.reader.application.ports import (
    ReaderComicPageIndex,
    ReaderResourceRepository,
)


class NormalizedPublicationLocatorIndex:
    def __init__(
        self,
        publications: OpenPublication,
        reader_repository: ReaderResourceRepository,
        comic_page_index: ReaderComicPageIndex,
    ) -> None:
        self._publications = publications
        self._reader_repository = reader_repository
        self._comic_page_index = comic_page_index

    def validate(
        self,
        *,
        resource_id: str,
        access_scope: ReaderAccessScope,
        location: ReaderExactLocationDto,
    ) -> bool:
        if isinstance(location, ReaderReflowableExactLocationDto):
            publication = self._manifest(
                resource_id=resource_id, access_scope=access_scope
            )
            return publication is not None and any(
                link.href == location.resource_href
                and _is_reflowable_markup(link.media_type)
                and _is_reflowable_markup(location.media_type)
                for link in (*publication.reading_order, *publication.resources)
            )
        return self._is_indexed_location(resource_id, location)

    def _is_indexed_location(
        self,
        resource_id: str,
        location: ReaderExactLocationDto,
    ) -> bool:
        context = self._reader_repository.get_context(resource_id)
        if context is None:
            return False
        if isinstance(location, ReaderPdfExactLocationDto):
            return (
                context.resource.format.lower() == "pdf"
                and context.resource.page_count is not None
                and location.page_index < context.resource.page_count
            )
        if isinstance(location, ReaderComicExactLocationDto):
            if context.resource.format.lower() not in _COMIC_FORMATS:
                return False
            canonical_href = self._comic_page_index.canonical_href(
                resource_id, location.page_index
            )
            return canonical_href is not None and location.resource_href == canonical_href
        if isinstance(location, ReaderAudioExactLocationDto):
            if context.resource.format.lower() not in _AUDIO_FORMATS:
                return False
            assets = self._reader_repository.list_assets(resource_id)
            target = next(
                (file for file in assets if file.id == location.asset_id), None
            )
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
                unit.id == location.chapter_id and unit.asset_id == location.asset_id
                for unit in self._reader_repository.list_navigation_units(resource_id)
            )
        return False

    def _manifest(
        self,
        *,
        resource_id: str,
        access_scope: ReaderAccessScope,
    ) -> NormalizedPublication | None:
        try:
            return self._publications.manifest(
                resource_id=resource_id,
                access_scope=PublicationAccessScope(
                    is_admin=access_scope.is_admin,
                    can_view_manual_imports=access_scope.can_view_manual_imports,
                    library_ids=access_scope.library_ids,
                ),
            )
        except (
            PublicationCorruptError,
            PublicationNotFoundError,
            PublicationUnsupportedError,
        ):
            return None


_AUDIO_FORMATS = frozenset(
    {
        "audio",
        "audiobook",
        "audiobook_dir",
        "mp3",
        "m4b",
        "m4a",
        "flac",
        "ogg",
        "opus",
        "wav",
    }
)


def _is_reflowable_markup(media_type: str) -> bool:
    return media_type.partition(";")[0].strip().lower() in {
        "application/xhtml+xml",
        "text/html",
        "text/plain",
    }


_COMIC_FORMATS = frozenset({"cbz", "cbr", "zip", "rar", "image_dir"})
