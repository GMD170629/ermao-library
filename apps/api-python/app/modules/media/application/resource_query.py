"""Read-only media application contracts for Book/Resource/Asset."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class MediaAssetResource:
    id: str
    path: str
    mime_type: str


class MediaResourceRepository(Protocol):
    def get_asset(self, asset_id: str) -> MediaAssetResource | None: ...

    def first_resource_asset(self, resource_id: str) -> MediaAssetResource | None: ...

    def book_cover_path(self, book_id: str) -> str | None: ...

    def resource_cover_path(self, resource_id: str) -> str | None: ...


class MediaResourceQuery:
    def __init__(self, repository: MediaResourceRepository) -> None:
        self._repository = repository

    def get_asset(self, asset_id: str) -> MediaAssetResource | None:
        return self._repository.get_asset(asset_id)

    def first_resource_asset(self, resource_id: str) -> MediaAssetResource | None:
        return self._repository.first_resource_asset(resource_id)

    def cover_path(
        self,
        *,
        book_id: str | None = None,
        resource_id: str | None = None,
    ) -> str | None:
        if book_id is not None:
            return self._repository.book_cover_path(book_id)
        if resource_id is not None:
            return self._repository.resource_cover_path(resource_id)
        return None
