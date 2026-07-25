from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from appv2.modules.catalog.contracts import CatalogImport, CatalogImportPort
from appv2.modules.ingestion.contracts import (
    ImportPreparationPort,
    IngestionUnitOfWork,
)

logger = logging.getLogger(__name__)


class IngestionWorker:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], IngestionUnitOfWork],
        preparation: ImportPreparationPort,
        catalog: CatalogImportPort,
        lease_seconds: int,
    ) -> None:
        self._uow_factory = uow_factory
        self._preparation = preparation
        self._catalog = catalog
        self._lease = timedelta(seconds=lease_seconds)

    def run_once(self, worker_id: str) -> bool:
        now = datetime.now(UTC)
        with self._uow_factory() as uow:
            job = uow.ingestion.claim_next(
                worker_id=worker_id,
                now=now,
                lease_until=now + self._lease,
            )
            if job is None:
                return False
            uow.commit()
        try:
            prepared = self._preparation.prepare(job.source_path)
            edition = self._catalog.import_file(
                CatalogImport(
                    title=prepared.title,
                    author=prepared.author,
                    media_type=prepared.media_type,
                    format=prepared.format,
                    source_path=prepared.source_path,
                    original_name=prepared.original_name,
                    size_bytes=prepared.size_bytes,
                    checksum=prepared.checksum,
                    metadata=prepared.metadata,
                )
            )
        except Exception as error:
            logger.exception("Import job %s failed", job.id)
            retry_at = (
                datetime.now(UTC) + timedelta(seconds=min(300, 2**job.attempt))
                if job.attempt < 5
                else None
            )
            with self._uow_factory() as uow:
                uow.ingestion.fail(
                    job.id,
                    error_code="IMPORT_FAILED",
                    error_detail=str(error),
                    retry_at=retry_at,
                )
                uow.commit()
            return True
        with self._uow_factory() as uow:
            uow.ingestion.complete(job.id, edition.id)
            uow.commit()
        return True
