"""Composition root for Resource actions that continue the import pipeline."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.bootstrap.readable_resource_pipeline import continue_source_import
from app.modules.library.application.resource_cover import (
    RegenerateResourceCover,
    ResourceSourceContinuationPort,
)
from app.modules.library.infrastructure.resource_cover import SqlAlchemyResourceCover


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


__all__ = ["ReadableResourceSourceContinuation", "regenerate_resource_cover"]
