"""Bounded maintenance of expired external metadata results."""

from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from app.modules.metadata.application.commands import (
    MetadataUnitOfWork,
    MetadataWriteTransaction,
)


class ExpiredMetadataCacheStore(Protocol):
    def delete_expired_batch(self, *, now: datetime, limit: int) -> int: ...


def prune_expired_metadata_cache(
    store: ExpiredMetadataCacheStore,
    *,
    unit_of_work: MetadataUnitOfWork,
    now: datetime,
    cancelled: Callable[[], bool],
) -> int:
    deleted = 0
    for _ in range(8):
        if cancelled():
            break
        with MetadataWriteTransaction(unit_of_work):
            count = store.delete_expired_batch(now=now, limit=128)
        deleted += count
        if count < 128:
            break
    return deleted
