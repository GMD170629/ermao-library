from __future__ import annotations

import logging
from collections.abc import Callable

from appv2.modules.operations.application.errors import safe_error_detail
from appv2.modules.operations.contracts import BackupExecutorPort, OperationsUnitOfWork

logger = logging.getLogger(__name__)


class BackupWorker:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], OperationsUnitOfWork],
        executor: BackupExecutorPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._executor = executor

    def run_once(self) -> bool:
        with self._uow_factory() as uow:
            backup = uow.operations.claim_backup()
            if backup is None:
                return False
            uow.commit()
        try:
            checksum, size_bytes = self._executor.create(backup)
        except Exception as error:
            detail = safe_error_detail(error)
            logger.error("Backup %s failed: %s", backup.id, detail)
            with self._uow_factory() as uow:
                uow.operations.fail_backup(backup.id, detail)
                uow.commit()
            return True
        with self._uow_factory() as uow:
            uow.operations.complete_backup(backup.id, checksum=checksum, size_bytes=size_bytes)
            uow.commit()
        return True
