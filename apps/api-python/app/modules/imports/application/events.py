"""Named import event persistence commands."""

from __future__ import annotations

from typing import Protocol

from app.modules.imports.application.ports import ImportUnitOfWork
from app.modules.system.public import PreparedSystemEvent


class PreparedImportEventStore(Protocol):
    def write(self, events: tuple[PreparedSystemEvent, ...]) -> None: ...


def persist_prepared_import_events(
    store: PreparedImportEventStore,
    unit_of_work: ImportUnitOfWork,
    events: tuple[PreparedSystemEvent, ...],
) -> None:
    """Persist prepared events in one SQL-only short transaction."""

    try:
        store.write(events)
        unit_of_work.commit()
    except Exception:
        unit_of_work.rollback()
        raise
