from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from appv2.platform.database.contracts import UnitOfWork


@dataclass(frozen=True, slots=True)
class DeliverableFile:
    file_id: uuid.UUID
    name: str
    media_type: str
    size_bytes: int
    path: str
    checksum: str


@dataclass(frozen=True, slots=True)
class DeliveryRequest:
    requested_by: uuid.UUID
    file: DeliverableFile
    recipient: str
    subject: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class EmailSettings:
    owner_id: uuid.UUID
    host: str
    port: int
    username: str | None
    sender: str
    use_tls: bool
    password_set: bool


@dataclass(frozen=True, slots=True)
class SmtpConfiguration:
    host: str
    port: int
    username: str | None
    password: str | None
    sender: str
    use_tls: bool


@dataclass(frozen=True, slots=True)
class KindleSettings:
    owner_id: uuid.UUID
    kindle_email: str
    convert_before_send: bool
    options: dict[str, object]


@dataclass(frozen=True, slots=True)
class DeliveryJob:
    id: uuid.UUID
    requested_by: uuid.UUID
    file_id: uuid.UUID
    kind: str
    recipient: str
    subject: str
    status: str
    attempt: int
    next_attempt_at: datetime
    error_code: str | None
    created_at: datetime
    updated_at: datetime


class DeliveryRepository(Protocol):
    def get_email_settings(self, owner_id: uuid.UUID) -> EmailSettings | None: ...

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
    ) -> EmailSettings: ...

    def smtp_configuration(self, owner_id: uuid.UUID) -> SmtpConfiguration | None: ...

    def get_kindle_settings(self, owner_id: uuid.UUID) -> KindleSettings | None: ...

    def save_kindle_settings(
        self,
        *,
        owner_id: uuid.UUID,
        kindle_email: str,
        convert_before_send: bool,
        options: dict[str, object],
    ) -> KindleSettings: ...

    def enqueue(self, request: DeliveryRequest, *, kind: str, now: datetime) -> DeliveryJob: ...

    def list_jobs(
        self, *, owner_id: uuid.UUID, offset: int, limit: int, status: str | None
    ) -> tuple[list[DeliveryJob], int]: ...

    def claim_next(
        self, *, worker_id: str, now: datetime, lease_until: datetime
    ) -> DeliveryJob | None: ...

    def complete(self, job_id: uuid.UUID) -> None: ...

    def fail(
        self,
        job_id: uuid.UUID,
        *,
        error_code: str,
        error_detail: str,
        retry_at: datetime | None,
    ) -> None: ...

    def cancel(self, job_id: uuid.UUID, owner_id: uuid.UUID) -> bool: ...

    def retry(self, job_id: uuid.UUID, owner_id: uuid.UUID, now: datetime) -> bool: ...


class DeliveryUnitOfWork(UnitOfWork, Protocol):
    delivery: DeliveryRepository


class DeliverableFilePort(Protocol):
    def get_deliverable(self, file_id: uuid.UUID) -> DeliverableFile | None: ...


class SmtpPort(Protocol):
    def test(self, configuration: SmtpConfiguration, recipient: str) -> None: ...

    def send(
        self,
        configuration: SmtpConfiguration,
        *,
        recipient: str,
        subject: str,
        file: DeliverableFile,
    ) -> None: ...
