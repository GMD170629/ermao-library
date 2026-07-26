from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from appv2.modules.ingestion.contracts import (
    IngestionOutboxEvent,
    IngestionUnitOfWork,
)

logger = logging.getLogger(__name__)


class IngestionEventHandler(Protocol):
    def handle(self, event: IngestionOutboxEvent) -> None: ...


class IngestionOutboxPublisher:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], IngestionUnitOfWork],
        handler: IngestionEventHandler,
    ) -> None:
        self._uow_factory = uow_factory
        self._handler = handler

    def run_once(self) -> bool:
        now = datetime.now(UTC)
        with self._uow_factory() as uow:
            event = uow.ingestion.claim_outbox(
                now=now,
                lease_until=now + timedelta(seconds=30),
            )
            if event is None:
                return False
            uow.commit()
        try:
            self._handler.handle(event)
        except Exception as error:
            logger.exception("failed to publish ingestion event %s", event.id)
            with self._uow_factory() as uow:
                uow.ingestion.fail_outbox(
                    event.id,
                    error_detail=str(error),
                    retry_at=now + timedelta(seconds=min(300, 2**event.attempt)),
                )
                uow.commit()
            return True
        with self._uow_factory() as uow:
            uow.ingestion.publish_outbox(event.id, published_at=datetime.now(UTC))
            uow.commit()
        return True
