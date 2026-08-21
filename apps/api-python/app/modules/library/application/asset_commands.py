"""Application use case for deleting a ResourceAsset."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ResourceAssetDeletion:
    asset_id: str
    resource_id: str
    ready_asset_count: int


class ResourceAssetMutationPort(Protocol):
    """Persistence operations required to delete a ResourceAsset."""

    def delete_asset(self, *, asset_id: str) -> ResourceAssetDeletion | None: ...

    def mark_resource_failed(self, *, resource_id: str) -> None: ...


class ResourceAssetUnitOfWork(Protocol):
    """Transaction boundary for a ResourceAsset mutation."""

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class ResourceAssetNotFoundError(Exception):
    """The requested ResourceAsset is not visible at mutation time."""


@dataclass(frozen=True, slots=True)
class DeleteResourceAssetResult:
    asset_id: str
    deleted: bool


class DeleteResourceAsset:
    """Delete one ResourceAsset and fail its Resource when no READY assets remain."""

    def __init__(
        self,
        port: ResourceAssetMutationPort,
        unit_of_work: ResourceAssetUnitOfWork,
    ) -> None:
        self._port = port
        self._unit_of_work = unit_of_work

    def execute(self, *, asset_id: str) -> DeleteResourceAssetResult:
        try:
            deletion = self._port.delete_asset(asset_id=asset_id)
            if deletion is None:
                raise ResourceAssetNotFoundError
            if deletion.ready_asset_count == 0:
                self._port.mark_resource_failed(resource_id=deletion.resource_id)
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            raise
        return DeleteResourceAssetResult(asset_id=deletion.asset_id, deleted=True)


__all__ = [
    "DeleteResourceAsset",
    "DeleteResourceAssetResult",
    "ResourceAssetDeletion",
    "ResourceAssetMutationPort",
    "ResourceAssetNotFoundError",
    "ResourceAssetUnitOfWork",
]
