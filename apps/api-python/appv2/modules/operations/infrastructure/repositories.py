from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from types import TracebackType
from typing import Literal, Self

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from appv2.modules.operations.contracts import (
    BackupView,
    EventView,
    OperationsRepository,
    SettingView,
)
from appv2.modules.operations.infrastructure.models import (
    BackupRecord,
    EventRecord,
    SettingRecord,
)


def _setting(record: SettingRecord) -> SettingView:
    return SettingView(key=record.key, value=record.value, updated_at=record.updated_at)


def _event(record: EventRecord) -> EventView:
    return EventView(
        id=record.id,
        actor_id=record.actor_id,
        kind=record.kind,
        severity=record.severity,
        message_key=record.message_key,
        params=record.params,
        trace_id=record.trace_id,
        created_at=record.created_at,
    )


def _backup(record: BackupRecord) -> BackupView:
    return BackupView(
        id=record.id,
        status=record.status,
        archive_name=record.archive_name,
        app_version=record.app_version,
        postgres_major=record.postgres_major,
        alembic_revision=record.alembic_revision,
        checksum=record.checksum,
        size_bytes=record.size_bytes,
        error_detail=record.error_detail,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


class SqlOperationsRepository(OperationsRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_settings(self) -> list[SettingView]:
        records = self._session.scalars(select(SettingRecord).order_by(SettingRecord.key)).all()
        return [_setting(record) for record in records]

    def save_settings(
        self, values: dict[str, dict[str, object]], actor_id: uuid.UUID
    ) -> list[SettingView]:
        saved: list[SettingView] = []
        for key, value in values.items():
            record = self._session.scalar(
                insert(SettingRecord)
                .values(key=key, value=value, updated_by=actor_id)
                .on_conflict_do_update(
                    index_elements=["key"],
                    set_={"value": value, "updated_by": actor_id},
                )
                .returning(SettingRecord)
            )
            if record is not None:
                saved.append(_setting(record))
        return saved

    def append_event(
        self,
        *,
        actor_id: uuid.UUID | None,
        kind: str,
        severity: str,
        message_key: str,
        params: dict[str, object],
        trace_id: str | None,
        now: datetime,
    ) -> None:
        self._session.add(
            EventRecord(
                actor_id=actor_id,
                kind=kind,
                severity=severity,
                message_key=message_key,
                params=params,
                trace_id=trace_id,
                created_at=now,
            )
        )

    def list_events(
        self, *, offset: int, limit: int, kind: str | None
    ) -> tuple[list[EventView], int]:
        criteria = [EventRecord.kind == kind] if kind else []
        total = int(
            self._session.scalar(select(func.count()).select_from(EventRecord).where(*criteria))
            or 0
        )
        records = self._session.scalars(
            select(EventRecord)
            .where(*criteria)
            .order_by(EventRecord.created_at.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return [_event(record) for record in records], total

    def request_backup(
        self,
        *,
        requested_by: uuid.UUID,
        archive_name: str,
        app_version: str,
        postgres_major: int,
        alembic_revision: str,
    ) -> BackupView:
        record = BackupRecord(
            status="queued",
            archive_name=archive_name,
            app_version=app_version,
            postgres_major=postgres_major,
            alembic_revision=alembic_revision,
            requested_by=requested_by,
        )
        self._session.add(record)
        self._session.flush()
        return _backup(record)

    def list_backups(self) -> list[BackupView]:
        records = self._session.scalars(
            select(BackupRecord).order_by(BackupRecord.created_at.desc())
        ).all()
        return [_backup(record) for record in records]

    def get_backup(self, backup_id: uuid.UUID) -> BackupView | None:
        record = self._session.get(BackupRecord, backup_id)
        return _backup(record) if record is not None else None

    def delete_backup(self, backup_id: uuid.UUID) -> BackupView | None:
        record = self._session.get(BackupRecord, backup_id)
        if record is None or record.status in {"running", "restoring"}:
            return None
        view = _backup(record)
        self._session.delete(record)
        return view

    def claim_backup(self) -> BackupView | None:
        record = self._session.scalar(
            select(BackupRecord)
            .where(BackupRecord.status == "queued")
            .order_by(BackupRecord.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if record is None:
            return None
        record.status = "running"
        self._session.flush()
        return _backup(record)

    def complete_backup(self, backup_id: uuid.UUID, *, checksum: str, size_bytes: int) -> None:
        record = self._required_backup(backup_id)
        record.status = "ready"
        record.checksum = checksum
        record.size_bytes = size_bytes
        record.error_detail = None

    def fail_backup(self, backup_id: uuid.UUID, detail: str) -> None:
        record = self._required_backup(backup_id)
        record.status = "failed"
        record.error_detail = detail[:4000]

    def mark_restoring(self, backup_id: uuid.UUID) -> BackupView | None:
        record = self._session.scalar(
            select(BackupRecord)
            .where(BackupRecord.id == backup_id, BackupRecord.status == "ready")
            .with_for_update()
        )
        if record is None:
            return None
        record.status = "restoring"
        self._session.flush()
        return _backup(record)

    def complete_restore(self, backup_id: uuid.UUID) -> None:
        record = self._required_backup(backup_id)
        record.status = "restored"
        record.error_detail = None

    def _required_backup(self, backup_id: uuid.UUID) -> BackupRecord:
        record = self._session.get(BackupRecord, backup_id)
        if record is None:
            raise RuntimeError("backup no longer exists")
        return record


class OperationsSqlUnitOfWork:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None
        self.operations: OperationsRepository
        self._committed = False

    def __enter__(self) -> Self:
        self._session = self._session_factory()
        self.operations = SqlOperationsRepository(self._session)
        self._committed = False
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        del exc, traceback
        if self._session is None:
            return False
        try:
            if exc_type is not None or not self._committed:
                self._session.rollback()
        finally:
            self._session.close()
            self._session = None
        return False

    def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("UnitOfWork must be entered before commit")
        self._session.commit()
        self._committed = True

    def rollback(self) -> None:
        if self._session is None:
            raise RuntimeError("UnitOfWork must be entered before rollback")
        self._session.rollback()


def operations_uow_factory(
    session_factory: sessionmaker[Session],
) -> Callable[[], OperationsSqlUnitOfWork]:
    return lambda: OperationsSqlUnitOfWork(session_factory)
