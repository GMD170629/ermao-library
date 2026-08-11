"""Named command for a prepared watched-import shelf link."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.modules.imports.application.ports import ImportUnitOfWork


@dataclass(frozen=True, slots=True)
class PreparedImportShelfLink:
    shelf_id: str
    work_id: str
    checkpoint_at: datetime


class ImportShelfLinkStore(Protocol):
    def write(self, prepared: PreparedImportShelfLink) -> None: ...


def persist_import_shelf_link(
    store: ImportShelfLinkStore,
    unit_of_work: ImportUnitOfWork,
    prepared: PreparedImportShelfLink,
) -> None:
    try:
        store.write(prepared)
        unit_of_work.commit()
    except Exception:
        unit_of_work.rollback()
        raise
