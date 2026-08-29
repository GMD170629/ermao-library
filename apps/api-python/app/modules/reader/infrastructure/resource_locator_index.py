"""Validate Reader locators without opening reflowable publication content."""

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


class ResourceLocatorIndex:
    """Validate morphology-specific anchors against lightweight resource facts.

    Reflowable hrefs are produced by the client's local original-file parser. The
    transport schema has already made them bounded, relative, and traversal-free,
    so the server must not reopen the publication merely to rediscover that href.
    """

    def __init__(
        self,
        reader_repository: ReaderResourceRepository,
        comic_page_index: ReaderComicPageIndex,
    ) -> None:
        self._reader_repository = reader_repository
        self._comic_page_index = comic_page_index

    def validate(
        self,
        *,
        resource_id: str,
        access_scope: ReaderAccessScope,
        location: ReaderExactLocationDto,
    ) -> bool:
        del access_scope
        context = self._reader_repository.get_context(resource_id)
        if context is None:
            return False
        if isinstance(location, ReaderReflowableExactLocationDto):
            return (
                context.resource.source_format.lower() in _REFLOWABLE_FORMATS
                and _is_reflowable_markup(location.media_type)
            )
        if isinstance(location, ReaderPdfExactLocationDto):
            return (
                context.resource.source_format.lower() == "pdf"
                and context.resource.page_count is not None
                and location.page_index < context.resource.page_count
            )
        if isinstance(location, ReaderComicExactLocationDto):
            if context.resource.source_format.lower() not in _COMIC_FORMATS:
                return False
            canonical_href = self._comic_page_index.canonical_href(
                resource_id, location.page_index
            )
            return (
                canonical_href is not None and location.resource_href == canonical_href
            )
        if isinstance(location, ReaderAudioExactLocationDto):
            if context.resource.source_format.lower() not in _AUDIO_FORMATS:
                return False
            assets = self._reader_repository.list_assets(resource_id)
            target = next(
                (asset for asset in assets if asset.id == location.asset_id), None
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


def _is_reflowable_markup(media_type: str) -> bool:
    return media_type.partition(";")[0].strip().lower() in {
        "application/xhtml+xml",
        "text/html",
        "text/plain",
    }


_REFLOWABLE_FORMATS = frozenset({"epub", "fb2", "txt", "mobi", "azw", "azw3", "prc"})
_COMIC_FORMATS = frozenset({"cbz", "cbr", "zip", "rar", "image_dir"})
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
