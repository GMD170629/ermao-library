from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.contracts.http import HttpContractModel, SuccessEnvelope


class SmtpSettingsRequest(HttpContractModel):
    host: str | None = None
    port: int | str | None = None
    security: str | None = None
    username: str | None = None
    password: str | None = None
    from_email: str | None = Field(default=None, alias="fromEmail")
    from_name: str | None = Field(default=None, alias="fromName")
    max_attachment_mb: float | int | str | None = Field(
        default=None, alias="maxAttachmentMb"
    )


class KindleAddressRequest(HttpContractModel):
    email: str | None = None


class UpdateEmailSettingsRequest(HttpContractModel):
    smtp: SmtpSettingsRequest | None = None
    kindle: KindleAddressRequest | None = None
    clear_smtp_password: bool = Field(default=False, alias="clearSmtpPassword")


class UpdateKindleSettingsRequest(HttpContractModel):
    email: str | None = None


class CreateKindleTaskRequest(HttpContractModel):
    file_id: str | None = Field(default=None, alias="fileId")
    work_id: str | None = Field(default=None, alias="workId")


class SmtpSettings(HttpContractModel):
    host: str
    port: int
    security: Literal["starttls", "ssl", "none"]
    username: str
    from_email: str = Field(alias="fromEmail")
    from_name: str = Field(alias="fromName")
    max_attachment_mb: float | None = Field(alias="maxAttachmentMb")
    password_configured: bool = Field(alias="passwordConfigured")


class KindleAddress(HttpContractModel):
    email: str


class EmailSettingsPayload(HttpContractModel):
    smtp: SmtpSettings
    kindle: KindleAddress


class SmtpTestPayload(HttpContractModel):
    connected: Literal[True]
    message: str


class KindleSmtpStatus(HttpContractModel):
    configured: bool
    from_email: str = Field(alias="fromEmail")


class KindleSettingsPayload(HttpContractModel):
    kindle: KindleAddress
    smtp: KindleSmtpStatus | None = None


class KindleTask(HttpContractModel):
    id: str
    user_id: str | None = Field(default=None, alias="userId")
    work_id: str | None = Field(default=None, alias="workId")
    volume_id: str | None = Field(default=None, alias="volumeId")
    file_id: str | None = Field(default=None, alias="fileId")
    book_title: str = Field(alias="bookTitle")
    volume_title: str | None = Field(default=None, alias="volumeTitle")
    file_name: str = Field(alias="fileName")
    format: str
    mime_type: str = Field(alias="mimeType")
    size_bytes: int = Field(alias="sizeBytes")
    sender_email: str | None = Field(default=None, alias="senderEmail")
    recipient_email: str = Field(alias="recipientEmail")
    subject: str
    smtp_host: str | None = Field(default=None, alias="smtpHost")
    smtp_port: int | None = Field(default=None, alias="smtpPort")
    smtp_security: str | None = Field(default=None, alias="smtpSecurity")
    smtp_username: str | None = Field(default=None, alias="smtpUsername")
    message_id: str | None = Field(default=None, alias="messageId")
    status: str
    attempt_count: int = Field(alias="attemptCount")
    next_attempt_at: datetime | None = Field(default=None, alias="nextAttemptAt")
    error_message: str | None = Field(default=None, alias="errorMessage")
    started_at: datetime | None = Field(default=None, alias="startedAt")
    sent_at: datetime | None = Field(default=None, alias="sentAt")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    can_cancel: bool = Field(alias="canCancel")
    can_retry: bool = Field(alias="canRetry")
    can_delete: bool = Field(alias="canDelete")


class KindleTaskPayload(HttpContractModel):
    task: KindleTask
    already_queued: bool | None = Field(
        default=None,
        alias="alreadyQueued",
        exclude_if=lambda value: value is None,
    )


class KindleTasksPayload(HttpContractModel):
    tasks: list[KindleTask]
    total: int
    page: int
    page_size: int = Field(alias="pageSize")
    total_pages: int = Field(alias="totalPages")


class DeletedKindleTaskPayload(HttpContractModel):
    deleted: bool
    id: str


EmailSettingsResponse = SuccessEnvelope[EmailSettingsPayload]
SmtpTestResponse = SuccessEnvelope[SmtpTestPayload]
KindleSettingsResponse = SuccessEnvelope[KindleSettingsPayload]
KindleTaskResponse = SuccessEnvelope[KindleTaskPayload]
KindleTasksResponse = SuccessEnvelope[KindleTasksPayload]
DeletedKindleTaskResponse = SuccessEnvelope[DeletedKindleTaskPayload]
