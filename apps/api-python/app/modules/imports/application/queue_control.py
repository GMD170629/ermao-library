"""Named persistence checkpoint for import queue control state and events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.modules.imports.application.ports import ImportUnitOfWork
from app.modules.system.public import PreparedSystemEvent


@dataclass(frozen=True, slots=True)
class PreparedImportQueueOperationCheckpoint:
    operation_id: str
    status: str
    message_code: str
    checkpoint_at: datetime
    events: tuple[PreparedSystemEvent, ...] = ()


class ImportQueueOperationCheckpointStore(Protocol):
    def persist(self, checkpoint: PreparedImportQueueOperationCheckpoint) -> None: ...


def persist_import_queue_operation_checkpoint(
    store: ImportQueueOperationCheckpointStore,
    unit_of_work: ImportUnitOfWork,
    checkpoint: PreparedImportQueueOperationCheckpoint,
) -> None:
    """Persist the prepared state patch and audit event in one transaction."""

    try:
        store.persist(checkpoint)
        unit_of_work.commit()
    except Exception:
        unit_of_work.rollback()
        raise
