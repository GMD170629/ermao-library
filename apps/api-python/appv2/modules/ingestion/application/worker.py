from __future__ import annotations

import logging
import subprocess
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from appv2.modules.catalog.contracts import (
    CatalogImport,
    CatalogImportPort,
    CatalogImportResult,
    PreparedPublication,
)
from appv2.modules.ingestion.contracts import (
    ConversionPreparationPort,
    ImportPreparationPort,
    IngestionUnitOfWork,
    PreparedImport,
)

logger = logging.getLogger(__name__)


def _failure(error: Exception) -> tuple[str, bool]:
    if isinstance(error, FileNotFoundError):
        return "SOURCE_NOT_FOUND", False
    if isinstance(error, PermissionError):
        return "SOURCE_PERMISSION_DENIED", False
    if isinstance(error, (subprocess.TimeoutExpired, TimeoutError)):
        return "CONVERSION_TIMEOUT", True
    if isinstance(error, ValueError):
        if str(error) == "DRM_PROTECTED":
            return "DRM_PROTECTED", False
        return "INVALID_IMPORT_SOURCE", False
    return "IMPORT_FAILED", True


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

    @contextmanager
    def _lease_heartbeat(self, job_id: uuid.UUID, worker_id: str) -> Iterator[None]:
        stopped = threading.Event()
        interval = max(1.0, self._lease.total_seconds() / 3)

        def renew() -> None:
            while not stopped.wait(interval):
                try:
                    with self._uow_factory() as uow:
                        renewed = uow.ingestion.renew_lease(
                            job_id,
                            worker_id=worker_id,
                            lease_until=datetime.now(UTC) + self._lease,
                        )
                        uow.commit()
                    if not renewed:
                        return
                except Exception:
                    logger.exception("Failed to renew lease for import job %s", job_id)

        thread = threading.Thread(
            target=renew,
            name=f"ingestion-lease-{job_id}",
            daemon=True,
        )
        thread.start()
        try:
            yield
        finally:
            stopped.set()
            thread.join(timeout=interval)

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
        with self._uow_factory() as uow:
            if not uow.ingestion.update_progress(
                job.id,
                worker_id=worker_id,
                stage="preparing",
                progress=10,
                message_key="import.preparing",
            ):
                uow.ingestion.acknowledge_cancellation(job.id, worker_id=worker_id)
                uow.commit()
                return True
            uow.commit()
        conversion_source_id: str | None = None
        conversion_prepared: PreparedImport | None = None
        publication: PreparedPublication | None = None
        try:
            with self._lease_heartbeat(job.id, worker_id):
                if job.kind == "conversion":
                    source_edition_id = job.options.get("sourceEditionId")
                    source_language = job.options.get("sourceLanguage")
                    if not isinstance(source_edition_id, str):
                        raise ValueError("conversion job has no source edition")
                    conversion_source_id = source_edition_id
                    if source_language is not None and not isinstance(source_language, str):
                        raise ValueError("conversion job has an invalid source language")
                    conversion_prepared = self._conversion.prepare(
                        job.source_path,
                        identity=source_edition_id,
                        language=source_language,
                    )
                else:
                    publication = self._preparation.prepare(
                        job.source_path,
                        auto_convert_to_epub=job.options.get("autoConvertToEpub") is not False,
                    )
                with self._uow_factory() as uow:
                    uow.ingestion.renew_lease(
                        job.id,
                        worker_id=worker_id,
                        lease_until=datetime.now(UTC) + self._lease,
                    )
                    if not uow.ingestion.update_progress(
                        job.id,
                        worker_id=worker_id,
                        stage="publishing",
                        progress=75,
                        message_key="import.publishing",
                    ):
                        uow.ingestion.acknowledge_cancellation(job.id, worker_id=worker_id)
                        uow.commit()
                        return True
                    uow.commit()
                if job.kind == "conversion":
                    if conversion_source_id is None:
                        raise ValueError("conversion job has no source edition")
                    if conversion_prepared is None:
                        raise ValueError("conversion job produced no publication")
                    imported = CatalogImport(
                        title=conversion_prepared.title,
                        author=conversion_prepared.author,
                        media_type=conversion_prepared.media_type,
                        file_media_type=conversion_prepared.file_media_type,
                        format=conversion_prepared.format,
                        source_path=conversion_prepared.source_path,
                        original_name=conversion_prepared.original_name,
                        size_bytes=conversion_prepared.size_bytes,
                        checksum=conversion_prepared.checksum,
                        metadata=conversion_prepared.metadata,
                    )
                    edition = self._catalog.publish_conversion(
                        uuid.UUID(conversion_source_id),
                        imported,
                    )
                    if edition is None:
                        raise ValueError("conversion source edition no longer exists")
                    result = CatalogImportResult(
                        work_id=edition.work_id,
                        edition_id=edition.id,
                        volume_ids=(),
                        duplicate=False,
                    )
                else:
                    if publication is None:
                        raise ValueError("import job produced no publication")
                    result = self._catalog.import_publication(publication)
        except Exception as error:
            logger.exception("Import job %s failed", job.id)
            error_code, retryable = _failure(error)
            retry_at = (
                datetime.now(UTC) + timedelta(seconds=min(300, 2**job.attempt))
                if retryable and job.attempt < job.max_attempts
                else None
            )
            with self._uow_factory() as uow:
                failed = uow.ingestion.fail(
                    job.id,
                    worker_id=worker_id,
                    error_code=("CONVERSION_FAILED" if job.kind == "conversion" else error_code),
                    error_detail=str(error),
                    retryable=retryable,
                    retry_at=retry_at,
                )
                if not failed:
                    uow.ingestion.acknowledge_cancellation(
                        job.id,
                        worker_id=worker_id,
                    )
                uow.commit()
            return True
        with self._uow_factory() as uow:
            uow.ingestion.complete(
                job.id,
                worker_id=worker_id,
                work_id=result.work_id,
                edition_id=result.edition_id,
                volume_ids=result.volume_ids,
            )
            uow.commit()
        return True
