from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi.responses import Response
from pydantic import Field

from app.contracts.http import HttpContractModel, SuccessEnvelope
from app.contracts.http_errors import HttpContractError


class BackupArchiveResponse(Response):
    media_type = "application/zip"


class Backup(HttpContractModel):
    id: str
    kind: str | None = None
    name: str
    filename: str | None = None
    size_bytes: int = Field(alias="sizeBytes")
    created_at: datetime = Field(alias="createdAt")
    counts: dict[str, int] | None = None


class BackupsPayload(HttpContractModel):
    backups: list[Backup]


class BackupPayload(HttpContractModel):
    backup: Backup


class BackupRestorePayload(HttpContractModel):
    id: str
    restored: Literal[True]
    restored_at: datetime = Field(alias="restoredAt")
    counts: dict[str, int] | None
    restored_counts: dict[str, int] = Field(alias="restoredCounts")
    actual_counts: dict[str, int] = Field(alias="actualCounts")


class BackupRestoreRequest(HttpContractModel):
    confirm: bool | None = None
    confirm_text: str | None = Field(default=None, alias="confirmText", max_length=32)


class BackupDeletePayload(HttpContractModel):
    deleted: bool
    id: str


class SystemManagerRequiredBody(HttpContractModel):
    message: str
    code: Literal["SYSTEM_MANAGER_REQUIRED"] = "SYSTEM_MANAGER_REQUIRED"


class SystemManagerRequiredError(HttpContractError[SystemManagerRequiredBody]):
    status_code = 403
    body_model = SystemManagerRequiredBody


BackupsResponse = SuccessEnvelope[BackupsPayload]
BackupResponse = SuccessEnvelope[BackupPayload]
BackupRestoreResponse = SuccessEnvelope[BackupRestorePayload]
BackupDeleteResponse = SuccessEnvelope[BackupDeletePayload]
