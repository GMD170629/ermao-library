"""Infrastructure adapter for Resource downloads.
No archive writer is provided: the cutover forbids generated ZIP artifacts.
"""

from __future__ import annotations

from typing import NoReturn

from app.modules.media.application.resource_archive import (
    ResourceDownloadUnsupportedError,
)


class ResourceDownloadAdapter:
    def prepare_directory_resource(self, resource_id: str) -> NoReturn:
        raise ResourceDownloadUnsupportedError(
            f"DIRECTORY_RESOURCE_DOWNLOAD_UNSUPPORTED:{resource_id}"
        )
