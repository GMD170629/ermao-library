from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from appv2.modules.discovery.contracts import (
    DiscoveryUnitOfWork,
    DownloadPort,
    ImportEnqueuePort,
)

logger = logging.getLogger(__name__)


class DiscoveryWorker:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], DiscoveryUnitOfWork],
        downloads: DownloadPort,
        ingestion: ImportEnqueuePort,
        lease_seconds: int,
    ) -> None:
        self._uow_factory = uow_factory
        self._downloads = downloads
        self._ingestion = ingestion
        self._lease = timedelta(seconds=lease_seconds)

    def run_once(self, worker_id: str) -> bool:
        now = datetime.now(UTC)
        with self._uow_factory() as uow:
            claimed = uow.discovery.claim_download(
                worker_id=worker_id, now=now, lease_until=now + self._lease
            )
            if claimed is None:
                return False
            job, result = claimed
            uow.commit()
        try:
            destination = self._downloads.download(result)
            self._ingestion.enqueue_downloaded(
                path=destination,
                requested_by=job.requested_by,
                idempotency_key=f"download-import:{job.id}",
            )
        except Exception as error:
            logger.exception("Download job %s failed", job.id)
            retry_at = (
                datetime.now(UTC) + timedelta(seconds=min(300, 2**job.attempt))
                if job.attempt < 5
                else None
            )
            with self._uow_factory() as uow:
                uow.discovery.fail_download(
                    job.id,
                    error_code="DOWNLOAD_FAILED",
                    error_detail=str(error),
                    retry_at=retry_at,
                )
                uow.commit()
            return True
        with self._uow_factory() as uow:
            uow.discovery.complete_download(job.id, destination)
            uow.commit()
        return True
