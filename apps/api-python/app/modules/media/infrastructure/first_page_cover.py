"""Optional first-page artwork using the same renderer as page previews."""

import logging
from pathlib import Path

from app.core.exception_diagnostics import record_exception
from app.modules.media.application.resource_preview import (
    ResourcePreviewNotFoundError,
    ResourcePreviewUnavailableError,
)
from app.modules.media.infrastructure.page_image import (
    PageImageRenderer,
    PageImageSource,
)


class FilesystemFirstPageCover:
    def __init__(self, renderer: PageImageRenderer) -> None:
        self._renderer = renderer

    def extract(self, *, path: Path, source_format: str) -> bytes | None:
        if source_format not in {"PDF", "IMAGE_DIR"}:
            return None
        try:
            return self._renderer.render(PageImageSource(source_format, path), 0)
        except (ResourcePreviewNotFoundError, ResourcePreviewUnavailableError) as error:
            record_exception(logging.getLogger(__name__), "modules.media.infrastructure.first_page_cover.extract.failed", error,
                             context={"step": "extract"})
            return None
