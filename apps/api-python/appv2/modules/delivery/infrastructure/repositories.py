from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from types import TracebackType
from typing import Literal, Self

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from appv2.modules.delivery.contracts import (
    DeliveryJob,
    DeliveryRepository,
    DeliveryRequest,
    EmailSettings,
    KindleSettings,
    SmtpConfiguration,
)
from appv2.modules.delivery.infrastructure.crypto import SecretCipher
from appv2.modules.delivery.infrastructure.models import (
    DeliveryJobRecord,
    EmailSettingsRecord,
    KindleSettingsRecord,
)


def _email(record: EmailSettingsRecord) -> EmailSettings:
    return EmailSettings(
        owner_id=record.owner_id,
        host=record.host,
        port=record.port,
        username=record.username,
        sender=record.sender,
        use_tls=record.use_tls,
        password_set=record.encrypted_password is not None,
    )


def _kindle(record: KindleSettingsRecord) -> KindleSettings:
    return KindleSettings(
        owner_id=record.owner_id,
        kindle_email=record.kindle_email,
        convert_before_send=record.convert_before_send,
        options=record.options,
    )


def _job(record: DeliveryJobRecord) -> DeliveryJob:
    return DeliveryJob(
        id=record.id,
        requested_by=record.requested_by,
        file_id=record.file_id,
        kind=record.kind,
        recipient=record.recipient,
        subject=record.subject,
        status=record.status,
        attempt=record.attempt,
        next_attempt_at=record.next_attempt_at,
        error_code=record.error_code,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


class SqlDeliveryRepository(DeliveryRepository):
    def __init__(self, session: Session, cipher: SecretCipher) -> None:
        self._session = session
        self._cipher = cipher

    def get_email_settings(self, owner_id: uuid.UUID) -> EmailSettings | None:
        record = self._email_record(owner_id)
        return _email(record) if record is not None else None

    def save_email_settings(
        self,
        *,
        owner_id: uuid.UUID,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        sender: str,
        use_tls: bool,
    ) -> EmailSettings:
        record = self._email_record(owner_id)
        encrypted = self._cipher.encrypt(password) if password else None
        if record is None:
            record = EmailSettingsRecord(
                owner_id=owner_id,
                host=host,
                port=port,
                username=username,
                encrypted_password=encrypted,
                sender=sender,
                use_tls=use_tls,
            )
            self._session.add(record)
        else:
            record.host = host
            record.port = port
            record.username = username
            if password is not None:
                record.encrypted_password = encrypted
            record.sender = sender
            record.use_tls = use_tls
        self._session.flush()
        return _email(record)

    def smtp_configuration(self, owner_id: uuid.UUID) -> SmtpConfiguration | None:
        record = self._email_record(owner_id)
        if record is None:
            return None
        return SmtpConfiguration(
            host=record.host,
            port=record.port,
            username=record.username,
            password=(
                self._cipher.decrypt(record.encrypted_password)
                if record.encrypted_password
                else None
            ),
            sender=record.sender,
            use_tls=record.use_tls,
        )

    def get_kindle_settings(self, owner_id: uuid.UUID) -> KindleSettings | None:
        record = self._session.scalar(
            select(KindleSettingsRecord).where(KindleSettingsRecord.owner_id == owner_id)
        )
        return _kindle(record) if record is not None else None

    def save_kindle_settings(
        self,
        *,
        owner_id: uuid.UUID,
        kindle_email: str,
        convert_before_send: bool,
        options: dict[str, object],
    ) -> KindleSettings:
        record = self._session.scalar(
            select(KindleSettingsRecord).where(KindleSettingsRecord.owner_id == owner_id)
        )
        if record is None:
            record = KindleSettingsRecord(
                owner_id=owner_id,
                kindle_email=kindle_email,
                convert_before_send=convert_before_send,
                options=options,
            )
            self._session.add(record)
        else:
            record.kindle_email = kindle_email
            record.convert_before_send = convert_before_send
            record.options = options
        self._session.flush()
        return _kindle(record)

    def enqueue(self, request: DeliveryRequest, *, kind: str, now: datetime) -> DeliveryJob:
        record = self._session.scalar(
            insert(DeliveryJobRecord)
            .values(
                requested_by=request.requested_by,
                file_id=request.file.file_id,
                kind=kind,
                recipient=request.recipient,
                subject=request.subject,
                status="queued",
                idempotency_key=request.idempotency_key,
                attempt=0,
                max_attempts=5,
                next_attempt_at=now,
            )
            .on_conflict_do_update(
                index_elements=["idempotency_key"],
                set_={"subject": request.subject},
            )
            .returning(DeliveryJobRecord)
        )
        if record is None:
            raise RuntimeError("delivery job upsert did not return a row")
        return _job(record)

    def list_jobs(
        self,
        *,
        owner_id: uuid.UUID,
        offset: int,
        limit: int,
        status: str | None,
    ) -> tuple[list[DeliveryJob], int]:
        criteria = [DeliveryJobRecord.requested_by == owner_id]
        if status:
            criteria.append(DeliveryJobRecord.status == status)
        total = int(
            self._session.scalar(
                select(func.count()).select_from(DeliveryJobRecord).where(*criteria)
            )
            or 0
        )
        records = self._session.scalars(
            select(DeliveryJobRecord)
            .where(*criteria)
            .order_by(DeliveryJobRecord.created_at.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return [_job(record) for record in records], total

    def claim_next(
        self, *, worker_id: str, now: datetime, lease_until: datetime
    ) -> DeliveryJob | None:
        record = self._session.scalar(
            select(DeliveryJobRecord)
            .where(
                DeliveryJobRecord.status.in_(("queued", "retry")),
                DeliveryJobRecord.next_attempt_at <= now,
                (
                    DeliveryJobRecord.lease_expires_at.is_(None)
                    | (DeliveryJobRecord.lease_expires_at < now)
                ),
            )
            .order_by(DeliveryJobRecord.next_attempt_at, DeliveryJobRecord.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if record is None:
            return None
        record.status = "running"
        record.attempt += 1
        record.lease_owner = worker_id
        record.lease_expires_at = lease_until
        self._session.flush()
        return _job(record)

    def complete(self, job_id: uuid.UUID) -> None:
        record = self._required_job(job_id)
        record.status = "completed"
        record.lease_owner = None
        record.lease_expires_at = None
        record.error_code = None
        record.error_detail = None

    def fail(
        self,
        job_id: uuid.UUID,
        *,
        error_code: str,
        error_detail: str,
        retry_at: datetime | None,
    ) -> None:
        record = self._required_job(job_id)
        record.status = "retry" if retry_at is not None else "failed"
        record.next_attempt_at = retry_at or record.next_attempt_at
        record.lease_owner = None
        record.lease_expires_at = None
        record.error_code = error_code
        record.error_detail = error_detail[:4000]

    def cancel(self, job_id: uuid.UUID, owner_id: uuid.UUID) -> bool:
        record = self._session.scalar(
            select(DeliveryJobRecord).where(
                DeliveryJobRecord.id == job_id,
                DeliveryJobRecord.requested_by == owner_id,
            )
        )
        if record is None or record.status in {"completed", "cancelled"}:
            return False
        record.status = "cancelled"
        record.lease_owner = None
        record.lease_expires_at = None
        return True

    def retry(self, job_id: uuid.UUID, owner_id: uuid.UUID, now: datetime) -> bool:
        record = self._session.scalar(
            select(DeliveryJobRecord).where(
                DeliveryJobRecord.id == job_id,
                DeliveryJobRecord.requested_by == owner_id,
            )
        )
        if record is None or record.status not in {"failed", "cancelled"}:
            return False
        record.status = "queued"
        record.next_attempt_at = now
        record.lease_owner = None
        record.lease_expires_at = None
        return True

    def _email_record(self, owner_id: uuid.UUID) -> EmailSettingsRecord | None:
        return self._session.scalar(
            select(EmailSettingsRecord).where(EmailSettingsRecord.owner_id == owner_id)
        )

    def _required_job(self, job_id: uuid.UUID) -> DeliveryJobRecord:
        record = self._session.get(DeliveryJobRecord, job_id)
        if record is None:
            raise RuntimeError("delivery job no longer exists")
        return record


class DeliverySqlUnitOfWork:
    def __init__(self, session_factory: sessionmaker[Session], cipher: SecretCipher) -> None:
        self._session_factory = session_factory
        self._cipher = cipher
        self._session: Session | None = None
        self.delivery: DeliveryRepository
        self._committed = False

    def __enter__(self) -> Self:
        self._session = self._session_factory()
        self.delivery = SqlDeliveryRepository(self._session, self._cipher)
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


def delivery_uow_factory(
    session_factory: sessionmaker[Session], cipher: SecretCipher
) -> Callable[[], DeliverySqlUnitOfWork]:
    return lambda: DeliverySqlUnitOfWork(session_factory, cipher)
