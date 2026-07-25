from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from appv2.modules.metadata.contracts import MetadataUnitOfWork, ProviderRegistry

logger = logging.getLogger(__name__)


class MetadataWorker:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], MetadataUnitOfWork],
        providers: ProviderRegistry,
        lease_seconds: int,
    ) -> None:
        self._uow_factory = uow_factory
        self._providers = providers
        self._lease = timedelta(seconds=lease_seconds)

    def run_once(self, worker_id: str) -> bool:
        now = datetime.now(UTC)
        with self._uow_factory() as uow:
            job = uow.metadata.claim_next(
                worker_id=worker_id, now=now, lease_until=now + self._lease
            )
            providers = uow.metadata.list_providers()
            if job is None:
                return False
            if job.provider_id is not None:
                providers = [provider for provider in providers if provider.id == job.provider_id]
            uow.commit()
        try:
            candidates = self._providers.search_all(job.query, providers)
        except Exception as error:
            logger.exception("Metadata job %s failed", job.id)
            retry_at = (
                datetime.now(UTC) + timedelta(seconds=min(300, 2**job.attempt))
                if job.attempt < 5
                else None
            )
            with self._uow_factory() as uow:
                uow.metadata.fail_job(
                    job.id,
                    error_code="METADATA_LOOKUP_FAILED",
                    error_detail=str(error),
                    retry_at=retry_at,
                )
                uow.commit()
            return True
        with self._uow_factory() as uow:
            uow.metadata.save_candidates(job.id, candidates)
            uow.commit()
        return True
