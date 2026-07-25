from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from appv2.modules.delivery.contracts import (
    DeliverableFilePort,
    DeliveryJob,
    DeliveryRequest,
    DeliveryUnitOfWork,
    EmailSettings,
    KindleSettings,
    SmtpPort,
)


class DeliveryNotFound(Exception):
    pass


class DeliveryService:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], DeliveryUnitOfWork],
        files: DeliverableFilePort,
        smtp: SmtpPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._files = files
        self._smtp = smtp

    def get_email_settings(self, owner_id: uuid.UUID) -> EmailSettings | None:
        with self._uow_factory() as uow:
            return uow.delivery.get_email_settings(owner_id)

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
        with self._uow_factory() as uow:
            settings = uow.delivery.save_email_settings(
                owner_id=owner_id,
                host=host,
                port=port,
                username=username,
                password=password,
                sender=sender,
                use_tls=use_tls,
            )
            uow.commit()
            return settings

    def test_email(self, owner_id: uuid.UUID, recipient: str) -> None:
        with self._uow_factory() as uow:
            configuration = uow.delivery.smtp_configuration(owner_id)
        if configuration is None:
            raise DeliveryNotFound
        self._smtp.test(configuration, recipient)

    def get_kindle_settings(self, owner_id: uuid.UUID) -> KindleSettings | None:
        with self._uow_factory() as uow:
            return uow.delivery.get_kindle_settings(owner_id)

    def save_kindle_settings(
        self,
        *,
        owner_id: uuid.UUID,
        kindle_email: str,
        convert_before_send: bool,
        options: dict[str, object],
    ) -> KindleSettings:
        with self._uow_factory() as uow:
            settings = uow.delivery.save_kindle_settings(
                owner_id=owner_id,
                kindle_email=kindle_email,
                convert_before_send=convert_before_send,
                options=options,
            )
            uow.commit()
            return settings

    def enqueue_kindle(
        self,
        *,
        owner_id: uuid.UUID,
        file_id: uuid.UUID,
        subject: str,
        idempotency_key: str | None,
    ) -> DeliveryJob:
        file = self._files.get_deliverable(file_id)
        if file is None:
            raise DeliveryNotFound
        with self._uow_factory() as uow:
            kindle = uow.delivery.get_kindle_settings(owner_id)
            if kindle is None:
                raise DeliveryNotFound
            key = (
                idempotency_key
                or hashlib.sha256(f"kindle\0{owner_id}\0{file_id}".encode()).hexdigest()
            )
            job = uow.delivery.enqueue(
                DeliveryRequest(
                    requested_by=owner_id,
                    file=file,
                    recipient=kindle.kindle_email,
                    subject=subject,
                    idempotency_key=key,
                ),
                kind="kindle",
                now=datetime.now(UTC),
            )
            uow.commit()
            return job

    def list_jobs(
        self,
        *,
        owner_id: uuid.UUID,
        page: int,
        page_size: int,
        status: str | None,
    ) -> tuple[list[DeliveryJob], int]:
        with self._uow_factory() as uow:
            return uow.delivery.list_jobs(
                owner_id=owner_id,
                offset=(page - 1) * page_size,
                limit=page_size,
                status=status,
            )

    def cancel(self, job_id: uuid.UUID, owner_id: uuid.UUID) -> None:
        with self._uow_factory() as uow:
            if not uow.delivery.cancel(job_id, owner_id):
                raise DeliveryNotFound
            uow.commit()

    def retry(self, job_id: uuid.UUID, owner_id: uuid.UUID) -> None:
        with self._uow_factory() as uow:
            if not uow.delivery.retry(job_id, owner_id, datetime.now(UTC)):
                raise DeliveryNotFound
            uow.commit()
