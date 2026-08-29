"""Composition root for Resource actions that continue the import pipeline."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.bootstrap.readable_resource_pipeline import continue_source_import
from app.core.config import Settings
from app.modules.library.application.bulk_operations import ExecuteBulkCovers
from app.modules.library.application.resource_cover import (
    RegenerateResourceCover,
    ResourceSourceContinuationPort,
    UploadResourceCover,
)
from app.modules.library.infrastructure.bulk_operations import (
    SqlAlchemyBulkBookOperations,
)
from app.modules.library.infrastructure.resource_commands import (
    SqlAlchemyResourceMetadata,
)
from app.modules.library.infrastructure.resource_cover import (
    FilesystemResourceCoverPublication,
    SqlAlchemyResourceCover,
)


class ReadableResourceSourceContinuation(ResourceSourceContinuationPort):
    """Adapt the canonical ContinueImport use case to Resource cover actions."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def enqueue_source_import(self, source_node_id: str) -> str | None:
        return continue_source_import(self._db, source_node_id).task_id


def regenerate_resource_cover(db: Session) -> RegenerateResourceCover:
    """Build the Resource cover use case with its canonical queue adapter."""

    return RegenerateResourceCover(
        SqlAlchemyResourceCover(db),
        ReadableResourceSourceContinuation(db),
        db,
    )


def upload_resource_cover(db: Session, settings: Settings) -> UploadResourceCover:
    return UploadResourceCover(
        SqlAlchemyResourceMetadata(db),
        SqlAlchemyResourceCover(db),
        FilesystemResourceCoverPublication(settings.resolved_storage_root),
        db,
    )


def bulk_covers(db: Session, settings: Settings) -> ExecuteBulkCovers:
    return ExecuteBulkCovers(
        SqlAlchemyBulkBookOperations(
            db,
            storage_root=settings.resolved_storage_root,
            enqueue_source_import=lambda source_node_id: continue_source_import(
                db, source_node_id
            ),
        ),
        db,
    )


__all__ = [
    "ReadableResourceSourceContinuation",
    "bulk_covers",
    "regenerate_resource_cover",
    "upload_resource_cover",
]
