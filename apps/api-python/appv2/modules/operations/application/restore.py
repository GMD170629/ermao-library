from __future__ import annotations

import logging
from collections.abc import Callable

from appv2.modules.operations.application.errors import safe_error_detail
from appv2.modules.operations.contracts import (
    OperationsUnitOfWork,
    RestoreControlInboxPort,
    RestoreExecutorPort,
)

logger = logging.getLogger(__name__)


class RestoreService:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], OperationsUnitOfWork],
        inbox: RestoreControlInboxPort,
        executor: RestoreExecutorPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._inbox = inbox
        self._executor = executor

    def run_once(self) -> bool:
        request = self._inbox.next_request()
        if request is None:
            return False
        try:
            self._executor.execute(request)
            with self._uow_factory() as uow:
                uow.operations.complete_restore(request.backup_id)
                uow.commit()
            self._inbox.complete(request)
        except Exception as error:
            detail = safe_error_detail(error)
            logger.error("Restore request %s failed: %s", request.request_id, detail)
            self._inbox.fail(request, detail)
            raise
        return True
