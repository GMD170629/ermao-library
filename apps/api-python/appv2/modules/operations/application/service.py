from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from appv2.modules.operations.contracts import (
    BackupArchive,
    BackupExecutorPort,
    BackupView,
    EventView,
    HealthContributor,
    HealthStatus,
    OperationsUnitOfWork,
    RestoreControlPort,
    SettingView,
)


class OperationsNotFound(Exception):
    pass


class OperationsService:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], OperationsUnitOfWork],
        health_contributors: tuple[HealthContributor, ...],
        backup_executor: BackupExecutorPort,
        restore_control: RestoreControlPort,
        app_version: str,
        alembic_revision: str,
    ) -> None:
        self._uow_factory = uow_factory
        self._health = health_contributors
        self._backup_executor = backup_executor
        self._restore_control = restore_control
        self._app_version = app_version
        self._alembic_revision = alembic_revision

    def health(self) -> list[HealthStatus]:
        return [contributor.check() for contributor in self._health]

    def list_settings(self) -> list[SettingView]:
        with self._uow_factory() as uow:
            return uow.operations.list_settings()

    def save_settings(
        self, values: dict[str, dict[str, object]], actor_id: uuid.UUID
    ) -> list[SettingView]:
        with self._uow_factory() as uow:
            settings = uow.operations.save_settings(values, actor_id)
            uow.operations.append_event(
                actor_id=actor_id,
                kind="settings.updated",
                severity="info",
                message_key="settings.updated",
                params={"keys": sorted(values)},
                trace_id=None,
                now=datetime.now(UTC),
            )
            uow.commit()
            return settings

    def list_events(
        self, *, page: int, page_size: int, kind: str | None
    ) -> tuple[list[EventView], int]:
        with self._uow_factory() as uow:
            return uow.operations.list_events(
                offset=(page - 1) * page_size, limit=page_size, kind=kind
            )

    def request_backup(self, actor_id: uuid.UUID) -> BackupView:
        backup_id = uuid.uuid4()
        archive_name = f"shuku-v2-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{backup_id}.dump"
        with self._uow_factory() as uow:
            backup = uow.operations.request_backup(
                requested_by=actor_id,
                archive_name=archive_name,
                app_version=self._app_version,
                postgres_major=18,
                alembic_revision=self._alembic_revision,
            )
            uow.operations.append_event(
                actor_id=actor_id,
                kind="backup.requested",
                severity="info",
                message_key="backup.requested",
                params={"backupId": str(backup.id)},
                trace_id=None,
                now=datetime.now(UTC),
            )
            uow.commit()
            return backup

    def list_backups(self) -> list[BackupView]:
        with self._uow_factory() as uow:
            return uow.operations.list_backups()

    def get_backup(self, backup_id: uuid.UUID) -> BackupView:
        with self._uow_factory() as uow:
            backup = uow.operations.get_backup(backup_id)
            if backup is None:
                raise OperationsNotFound
            return backup

    def delete_backup(self, backup_id: uuid.UUID) -> None:
        with self._uow_factory() as uow:
            backup = uow.operations.delete_backup(backup_id)
            if backup is None:
                raise OperationsNotFound
            self._backup_executor.delete(backup)
            uow.commit()

    def download_backup(self, backup_id: uuid.UUID) -> BackupArchive:
        backup = self.get_backup(backup_id)
        try:
            return self._backup_executor.open(backup)
        except FileNotFoundError as error:
            raise OperationsNotFound from error

    def request_restore(self, backup_id: uuid.UUID, actor_id: uuid.UUID) -> str:
        with self._uow_factory() as uow:
            backup = uow.operations.mark_restoring(backup_id)
            if backup is None:
                raise OperationsNotFound
            request_id = self._restore_control.request(backup, actor_id)
            uow.operations.append_event(
                actor_id=actor_id,
                kind="restore.requested",
                severity="warning",
                message_key="restore.requested",
                params={"backupId": str(backup.id), "requestId": request_id},
                trace_id=None,
                now=datetime.now(UTC),
            )
            uow.commit()
            return request_id
