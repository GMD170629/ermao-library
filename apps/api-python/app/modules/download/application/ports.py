from __future__ import annotations

from typing import Protocol

from app.modules.download.application.dto import (
    CreateDownloadTask,
    DownloadTaskDTO,
    UpdateDownloadTask,
)


class DownloadTaskRepository(Protocol):
    def list_recent(self, *, limit: int) -> list[DownloadTaskDTO]: ...

    def get(self, task_id: str) -> DownloadTaskDTO | None: ...

    def create(self, command: CreateDownloadTask) -> DownloadTaskDTO: ...

    def update(
        self,
        task_id: str,
        changes: UpdateDownloadTask,
    ) -> DownloadTaskDTO | None: ...

    def delete(self, task_id: str) -> bool: ...


class DownloadUnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...
