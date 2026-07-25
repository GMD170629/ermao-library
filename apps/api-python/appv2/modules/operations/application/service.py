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
    LogStorageView,
    OperationsUnitOfWork,
    RestoreControlPort,
    SettingView,
)


class OperationsNotFound(Exception):
    pass


DEFAULT_LOG_MAX_BYTES = 5 * 1024 * 1024


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
        self,
        *,
        page: int,
        page_size: int,
        kind: str | None,
        source: str | None = None,
        severity: str | None = None,
        search: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> tuple[list[EventView], int]:
        with self._uow_factory() as uow:
            return uow.operations.list_events(
                offset=(page - 1) * page_size,
                limit=page_size,
                kind=kind,
                source=source,
                severity=severity,
                search=search,
                date_from=date_from,
                date_to=date_to,
            )

    def clear_events(self, actor_id: uuid.UUID) -> int:
        with self._uow_factory() as uow:
            deleted = uow.operations.clear_events()
            uow.operations.append_event(
                actor_id=actor_id,
                kind="events.cleared",
                severity="warning",
                message_key="events.cleared",
                params={"deleted": deleted},
                trace_id=None,
                now=datetime.now(UTC),
            )
            uow.commit()
            return deleted

    def log_settings(self) -> LogStorageView:
        with self._uow_factory() as uow:
            settings = uow.operations.list_settings()
            max_bytes = self._log_max_bytes(settings)
            return LogStorageView(
                size_bytes=uow.operations.event_storage_size(),
                max_bytes=max_bytes,
                last_pruned_at=None,
            )

    def save_log_settings(self, max_bytes: int, actor_id: uuid.UUID) -> LogStorageView:
        if not 1024 * 1024 <= max_bytes <= 100 * 1024 * 1024:
            raise ValueError("log capacity must be between 1 MiB and 100 MiB")
        now = datetime.now(UTC)
        with self._uow_factory() as uow:
            uow.operations.save_settings(
                {"operations.logRetention": {"maxBytes": max_bytes}},
                actor_id,
            )
            deleted = uow.operations.prune_events(max_bytes)
            uow.operations.append_event(
                actor_id=actor_id,
                kind="events.retention.updated",
                severity="warning",
                message_key="events.retention.updated",
                params={"maxBytes": max_bytes, "deleted": deleted},
                trace_id=None,
                now=now,
            )
            size_bytes = uow.operations.event_storage_size()
            uow.commit()
            return LogStorageView(
                size_bytes=size_bytes,
                max_bytes=max_bytes,
                last_pruned_at=now if deleted else None,
            )

    @staticmethod
    def _log_max_bytes(settings: list[SettingView]) -> int:
        for setting in settings:
            if setting.key != "operations.logRetention":
                continue
            value = setting.value.get("maxBytes")
            if isinstance(value, int):
                return value
        return DEFAULT_LOG_MAX_BYTES

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
