"""Authorized, cacheable thumbnail previews for readable-resource pages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ResourcePreviewAccessScope:
    is_admin: bool
    library_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResourcePreviewData:
    content: bytes
    media_type: str
    etag: str


class ResourcePreviewNotFoundError(Exception):
    """The resource or requested page is not visible."""


class ResourcePreviewUnavailableError(Exception):
    """The visible page cannot be converted into a safe preview."""


class ResourcePreviewPort(Protocol):
    def load(
        self,
        *,
        scope: ResourcePreviewAccessScope,
        resource_id: str,
        page_index: int,
    ) -> ResourcePreviewData: ...


class GetResourcePreview:
    def __init__(self, previews: ResourcePreviewPort) -> None:
        self._previews = previews

    def execute(
        self,
        *,
        scope: ResourcePreviewAccessScope,
        resource_id: str,
        page_index: int,
    ) -> ResourcePreviewData:
        if page_index < 0:
            raise ResourcePreviewNotFoundError
        return self._previews.load(
            scope=scope,
            resource_id=resource_id,
            page_index=page_index,
        )


__all__ = [
    "GetResourcePreview",
    "ResourcePreviewAccessScope",
    "ResourcePreviewData",
    "ResourcePreviewNotFoundError",
    "ResourcePreviewPort",
    "ResourcePreviewUnavailableError",
]
