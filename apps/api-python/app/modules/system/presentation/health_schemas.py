"""Typed HTTP contracts for health and queue-control endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi.responses import StreamingResponse
from pydantic import Field, field_validator

from app.contracts.http import HttpContractModel, SuccessEnvelope
from app.contracts.http_errors import HttpContractError
from app.core.time import timestamp_ms_to_iso


class HealthCheck(HttpContractModel):
    name: str
    status: str
    message: str
    details: None = None


class ServiceHealthPayload(HttpContractModel):
    service: Literal["ermao-books"]
    status: str


class SystemHealthPayload(HttpContractModel):
    status: str
    checks: list[HealthCheck]


class DatabasePingPayload(HttpContractModel):
    database: Literal["ok"]


class EmptyDetails(HttpContractModel):
    pass


class DirectoryOptions(HttpContractModel):
    path: str
    writable: bool
    name: str | None = None


class QueueOptions(HttpContractModel):
    queue: Literal["import", "download", "kindle", "metadata"]
    enabled: bool


class ProviderOptions(HttpContractModel):
    media_kind: Literal["EBOOK", "COMIC", "AUDIOBOOK"] = Field(alias="mediaKind")


class DirectoryHealthDetails(HttpContractModel):
    path: str
    writable_required: bool = Field(alias="writableRequired")
    name: str | None
    error: str | None = None


class DatabaseHealthDetails(HttpContractModel):
    error: str


class QueueRuntime(HttpContractModel):
    queue_name: str = Field(alias="queueName")
    instance_id: str = Field(alias="instanceId")
    status: str
    poll_interval_seconds: float = Field(alias="pollIntervalSeconds")
    started_at: int = Field(alias="startedAt")
    heartbeat_at: int = Field(alias="heartbeatAt")
    last_processed_at: int | None = Field(alias="lastProcessedAt")
    last_error: str | None = Field(alias="lastError")
    updated_at: int = Field(alias="updatedAt")
    heartbeat_age_ms: int | None = Field(alias="heartbeatAgeMs")
    stale_after_ms: int = Field(alias="staleAfterMs")
    stale: bool


class QueueHealthDetails(HttpContractModel):
    queue: str
    runtime: QueueRuntime | None
    pending: int
    running: int
    failed: int
    oldest_pending_at: datetime | None = Field(alias="oldestPendingAt")


class SmtpHealthDetails(HttpContractModel):
    recipient_count: int = Field(alias="recipientCount")
    configured: bool
    error: str | None = None


class ProviderProbe(HttpContractModel):
    id: str
    ok: bool
    message: str


class ProviderHealthDetails(HttpContractModel):
    media_kind: str = Field(alias="mediaKind")
    providers: list[ProviderProbe]


class QueueSkippedDetails(HttpContractModel):
    queue: str


HealthItemOptions = EmptyDetails | DirectoryOptions | QueueOptions | ProviderOptions
HealthItemDetails = (
    EmptyDetails
    | DirectoryHealthDetails
    | DatabaseHealthDetails
    | QueueHealthDetails
    | SmtpHealthDetails
    | ProviderHealthDetails
    | QueueSkippedDetails
)


class HealthRunItem(HttpContractModel):
    id: str
    group: str
    label_code: str = Field(alias="labelCode")
    kind: str
    options: HealthItemOptions
    status: str
    message_code: str = Field(alias="messageCode")
    message_params: EmptyDetails = Field(alias="messageParams")
    details: HealthItemDetails
    started_at: int | None = Field(alias="startedAt")
    finished_at: int | None = Field(alias="finishedAt")
    duration_ms: int | None = Field(alias="durationMs")


class HealthRunSummary(HttpContractModel):
    total: int
    completed: int
    ok: int
    warning: int
    error: int
    skipped: int


class HealthRunGroup(HttpContractModel):
    id: str
    labelCode: str


class HealthRun(HttpContractModel):
    run_id: str = Field(alias="runId")
    status: str
    version: int
    started_at: int = Field(alias="startedAt")
    finished_at: int | None = Field(alias="finishedAt")
    groups: list[HealthRunGroup]
    items: list[HealthRunItem]
    summary: HealthRunSummary
    created: bool | None = None


class HealthRunPayload(HttpContractModel):
    run: HealthRun
    created: bool | None = None


class QueueOperation(HttpContractModel):
    id: str
    queue_name: str = Field(alias="queueName")
    action: str
    status: str
    actor_user_id: str = Field(alias="actorUserId")
    message_code: str = Field(alias="messageCode")
    requested_at: str = Field(alias="requestedAt")
    started_at: str | None = Field(alias="startedAt")
    finished_at: str | None = Field(alias="finishedAt")
    updated_at: str = Field(alias="updatedAt")

    @field_validator(
        "requested_at",
        "started_at",
        "finished_at",
        "updated_at",
        mode="before",
    )
    @classmethod
    def normalize_timestamp(cls, value: object) -> str | None:
        return timestamp_ms_to_iso(value)


class QueueOperationPayload(HttpContractModel):
    operation: QueueOperation
    created: bool | None = None


class EventStorage(HttpContractModel):
    size_bytes: int = Field(alias="sizeBytes")
    max_bytes: int = Field(alias="maxBytes")
    last_pruned_at: str | None = Field(alias="lastPrunedAt")


class LogSettingsPayload(HttpContractModel):
    storage: EventStorage
    min_bytes: int | None = Field(default=None, alias="minBytes")
    max_bytes: int | None = Field(default=None, alias="maxBytes")


class UpdateLogSettingsRequest(HttpContractModel):
    max_bytes: int = Field(alias="maxBytes")


class HealthEventStreamResponse(StreamingResponse):
    media_type = "text/event-stream"


class UnauthorizedBody(HttpContractModel):
    message: Literal["UNAUTHORIZED"] = "UNAUTHORIZED"
    code: Literal["UNAUTHORIZED"] = "UNAUTHORIZED"


class UnauthorizedError(HttpContractError[UnauthorizedBody]):
    status_code = 401
    body_model = UnauthorizedBody


class SystemManagerRequiredBody(HttpContractModel):
    message: str
    code: Literal["SYSTEM_MANAGER_REQUIRED"] = "SYSTEM_MANAGER_REQUIRED"


class SystemManagerRequiredError(HttpContractError[SystemManagerRequiredBody]):
    status_code = 403
    body_model = SystemManagerRequiredBody


class HealthRunNotFoundBody(HttpContractModel):
    message: str
    code: Literal["HEALTH_RUN_NOT_FOUND"] = "HEALTH_RUN_NOT_FOUND"


class HealthRunNotFoundError(HttpContractError[HealthRunNotFoundBody]):
    status_code = 404
    body_model = HealthRunNotFoundBody


class QueueOperationNotFoundBody(HttpContractModel):
    message: str
    code: Literal["QUEUE_OPERATION_NOT_FOUND"] = "QUEUE_OPERATION_NOT_FOUND"


class QueueOperationNotFoundError(HttpContractError[QueueOperationNotFoundBody]):
    status_code = 404
    body_model = QueueOperationNotFoundBody


class QueueOperationConflictBody(HttpContractModel):
    message: str
    code: Literal["QUEUE_OPERATION_CONFLICT"] = "QUEUE_OPERATION_CONFLICT"


class QueueOperationConflictError(HttpContractError[QueueOperationConflictBody]):
    status_code = 409
    body_model = QueueOperationConflictBody


class HealthRunActiveBody(HttpContractModel):
    message: str
    code: Literal["HEALTH_RUN_ACTIVE"] = "HEALTH_RUN_ACTIVE"


class HealthRunActiveError(HttpContractError[HealthRunActiveBody]):
    status_code = 409
    body_model = HealthRunActiveBody


class ImportQueueOfflineBody(HttpContractModel):
    message: str
    code: Literal["IMPORT_QUEUE_OFFLINE"] = "IMPORT_QUEUE_OFFLINE"


class ImportQueueOfflineError(HttpContractError[ImportQueueOfflineBody]):
    status_code = 409
    body_model = ImportQueueOfflineBody


class InvalidLogMaxBytesBody(HttpContractModel):
    message: str
    code: Literal["INVALID_LOG_MAX_BYTES"] = "INVALID_LOG_MAX_BYTES"


class InvalidLogMaxBytesError(HttpContractError[InvalidLogMaxBytesBody]):
    status_code = 400
    body_model = InvalidLogMaxBytesBody


ServiceHealthResponse = SuccessEnvelope[ServiceHealthPayload]
SystemHealthResponse = SuccessEnvelope[SystemHealthPayload]
DatabasePingResponse = SuccessEnvelope[DatabasePingPayload]
HealthRunResponse = SuccessEnvelope[HealthRunPayload]
QueueOperationResponse = SuccessEnvelope[QueueOperationPayload]
LogSettingsResponse = SuccessEnvelope[LogSettingsPayload]
