from __future__ import annotations

import uuid
from collections.abc import Callable

from appv2.modules.catalog.contracts import (
    CatalogEdition,
    CatalogFile,
    CatalogReadPort,
    CatalogUnitOfWork,
    CatalogWork,
)


class CatalogReadAdapter(CatalogReadPort):
    def __init__(self, uow_factory: Callable[[], CatalogUnitOfWork]) -> None:
        self._uow_factory = uow_factory

    def get_work(self, work_id: uuid.UUID) -> CatalogWork | None:
        with self._uow_factory() as uow:
            return uow.catalog.get_work(work_id)

    def get_edition(self, edition_id: uuid.UUID) -> CatalogEdition | None:
        with self._uow_factory() as uow:
            return uow.catalog.get_edition(edition_id)

    def get_file(self, file_id: uuid.UUID) -> CatalogFile | None:
        with self._uow_factory() as uow:
            return uow.catalog.get_file(file_id)

    def files_for_edition(self, edition_id: uuid.UUID) -> list[CatalogFile]:
        with self._uow_factory() as uow:
            return uow.catalog.files_for_edition(edition_id)
