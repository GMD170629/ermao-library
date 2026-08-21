"""SQLAlchemy adapter for ResourceAsset mutations."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import LibraryReadableResource, LibraryResourceAsset
from app.modules.library.application.asset_commands import (
    ResourceAssetDeletion,
    ResourceAssetMutationPort,
)


class SqlAlchemyResourceAssetMutation(ResourceAssetMutationPort):
    """Delete ResourceAssets and expose the post-delete Resource state."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def delete_asset(self, *, asset_id: str) -> ResourceAssetDeletion | None:
        asset = self._db.get(LibraryResourceAsset, asset_id)
        if asset is None:
            return None
        resource_id = asset.resource_id
        self._db.delete(asset)
        self._db.flush()
        ready_asset_count = int(
            self._db.scalar(
                select(func.count())
                .select_from(LibraryResourceAsset)
                .where(
                    LibraryResourceAsset.resource_id == resource_id,
                    LibraryResourceAsset.import_state == "READY",
                )
            )
            or 0
        )
        return ResourceAssetDeletion(
            asset_id=asset_id,
            resource_id=resource_id,
            ready_asset_count=ready_asset_count,
        )

    def mark_resource_failed(self, *, resource_id: str) -> None:
        resource = self._db.get(LibraryReadableResource, resource_id)
        if resource is not None:
            resource.import_state = "FAILED"


__all__ = ["SqlAlchemyResourceAssetMutation"]
