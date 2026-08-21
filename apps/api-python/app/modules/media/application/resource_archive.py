"""Resource download policy.
A Resource is served in its original format. Directory Resources are not
materialized as temporary ZIP files.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn


class ResourceDownloadUnsupportedError(Exception):
    """Raised when a requested Resource cannot be served as one original file."""


@dataclass(frozen=True, slots=True)
class ResourceDownloadDescriptor:
    resource_id: str
    asset_id: str
    path: str
    mime_type: str
    download_name: str


def reject_directory_resource_download() -> NoReturn:
    raise ResourceDownloadUnsupportedError(
        "DIRECTORY_RESOURCE_DOWNLOAD_UNSUPPORTED"
    )
