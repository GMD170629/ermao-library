from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from appv2.modules.delivery.contracts import (
    DeliverableFilePort,
    DeliveryUnitOfWork,
    SmtpPort,
)

logger = logging.getLogger(__name__)


class DeliveryWorker:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], DeliveryUnitOfWork],
        files: DeliverableFilePort,
        smtp: SmtpPort,
        lease_seconds: int,
    ) -> None:
        self._uow_factory = uow_factory
        self._files = files
        self._smtp = smtp
        self._lease = timedelta(seconds=lease_seconds)

    def run_once(self, worker_id: str) -> bool:
        now = datetime.now(UTC)
        with self._uow_factory() as uow:
            job = uow.delivery.claim_next(
                worker_id=worker_id, now=now, lease_until=now + self._lease
            )
            if job is None:
                return False
            configuration = uow.delivery.smtp_configuration(job.requested_by)
            uow.commit()
        try:
            file = self._files.get_deliverable(job.file_id)
            if file is None or configuration is None:
                raise ValueError("delivery file or SMTP configuration is missing")
            self._smtp.send(
                configuration,
                recipient=job.recipient,
                subject=job.subject,
                file=file,
            )
        except Exception as error:
            logger.exception("Delivery job %s failed", job.id)
            retry_at = (
                datetime.now(UTC) + timedelta(seconds=min(300, 2**job.attempt))
                if job.attempt < 5
                else None
            )
            with self._uow_factory() as uow:
                uow.delivery.fail(
                    job.id,
                    error_code="DELIVERY_FAILED",
                    error_detail=str(error),
                    retry_at=retry_at,
                )
                uow.commit()
            return True
        with self._uow_factory() as uow:
            uow.delivery.complete(job.id)
            uow.commit()
        return True
