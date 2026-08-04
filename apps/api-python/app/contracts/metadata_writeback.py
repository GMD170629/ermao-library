"""Stable, path-safe metadata writeback progress contract."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.contracts.http import HttpContractModel


class MetadataWritebackTargetContract(HttpContractModel):
    format: str
    status: str
    written_fields: list[str] = Field(alias="writtenFields")
    warning_code: str | None = Field(alias="warningCode")
    error_summary: str | None = Field(alias="errorSummary")


class MetadataWritebackOperationContract(HttpContractModel):
    id: str
    status: Literal["PENDING", "RUNNING", "COMPLETED", "COMPLETED_WITH_WARNINGS"]
    total_targets: int = Field(alias="totalTargets")
    completed_targets: int = Field(alias="completedTargets")
    warning_targets: int = Field(alias="warningTargets")
    targets: list[MetadataWritebackTargetContract]
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    finished_at: datetime | None = Field(alias="finishedAt")
