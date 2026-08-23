"""Read-only media application contracts for Book/Resource/Asset."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class MediaAssetResource:
    id: str
    path: str
    source_root: str
    mime_type: str


@dataclass(frozen=True, slots=True)
class SourceNodeCoverResource:
    found: bool
    path: str | None


class MediaResourceRepository(Protocol):
    def get_asset(self, asset_id: str) -> MediaAssetResource | None: ...

    def first_resource_asset(self, resource_id: str) -> MediaAssetResource | None: ...

    def resource_cover_path(self, resource_id: str) -> str | None: ...

    def source_node_cover(
        self, *, book_id: str, source_node_id: str
    ) -> SourceNodeCoverResource: ...


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
        resource_id: str | None,
    ) -> str | None:
        if resource_id is not None:
            return self._repository.resource_cover_path(resource_id)
        return None

    def source_node_cover(
        self, *, book_id: str, source_node_id: str
    ) -> SourceNodeCoverResource:
        return self._repository.source_node_cover(
            book_id=book_id,
            source_node_id=source_node_id,
        )
