from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from appv2.modules.catalog.contracts import CatalogImport, CatalogImportPort
from appv2.modules.ingestion.contracts import (
    ConversionPreparationPort,
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
        conversion: ConversionPreparationPort,
        catalog: CatalogImportPort,
        lease_seconds: int,
    ) -> None:
        self._uow_factory = uow_factory
        self._preparation = preparation
        self._conversion = conversion
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
        conversion_source_id: str | None = None
        try:
            if job.kind == "conversion":
                source_edition_id = job.options.get("sourceEditionId")
                source_language = job.options.get("sourceLanguage")
                if not isinstance(source_edition_id, str):
                    raise ValueError("conversion job has no source edition")
                conversion_source_id = source_edition_id
                if source_language is not None and not isinstance(source_language, str):
                    raise ValueError("conversion job has an invalid source language")
                prepared = self._conversion.prepare(
                    job.source_path,
                    identity=source_edition_id,
                    language=source_language,
                )
            else:
                prepared = self._preparation.prepare(job.source_path)
            imported = CatalogImport(
                title=prepared.title,
                author=prepared.author,
                media_type=prepared.media_type,
                file_media_type=prepared.file_media_type,
                format=prepared.format,
                source_path=prepared.source_path,
                original_name=prepared.original_name,
                size_bytes=prepared.size_bytes,
                checksum=prepared.checksum,
                metadata=prepared.metadata,
            )
            if job.kind == "conversion":
                if conversion_source_id is None:
                    raise ValueError("conversion job has no source edition")
                edition = self._catalog.publish_conversion(
                    uuid.UUID(conversion_source_id),
                    imported,
                )
                if edition is None:
                    raise ValueError("conversion source edition no longer exists")
            else:
                edition = self._catalog.import_file(imported)
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
                    error_code=(
                        "CONVERSION_FAILED" if job.kind == "conversion" else "IMPORT_FAILED"
                    ),
                    error_detail=str(error),
                    retry_at=retry_at,
                )
                uow.commit()
            return True
        with self._uow_factory() as uow:
            uow.ingestion.complete(job.id, edition.id)
            uow.commit()
        return True
