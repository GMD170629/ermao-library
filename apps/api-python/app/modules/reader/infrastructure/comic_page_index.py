"""Reader adapter for the canonical media comic page index."""

from collections.abc import Callable

from app.modules.media.public import (
    ReadOnlyResourcePageIndex,
    ResourcePageIndexProjection,
)


class MediaComicPageIndex:
    def __init__(
        self,
        load_projection: Callable[[str], ResourcePageIndexProjection],
    ) -> None:
        self._load_projection = load_projection
        self._resolver = ReadOnlyResourcePageIndex()

    def canonical_href(self, resource_id: str, page_index: int) -> str | None:
        pages = self._resolver.execute(self._load_projection(resource_id)).pages
        if page_index < 0 or page_index >= len(pages):
            return None
        return f"pages/{page_index}"


__all__ = ["MediaComicPageIndex"]
