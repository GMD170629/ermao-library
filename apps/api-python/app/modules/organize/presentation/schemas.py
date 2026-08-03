from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.contracts.http import HttpContractModel, SuccessEnvelope
from app.contracts.http_errors import HttpContractError
from app.modules.library.public import WorkView


class OrganizeRules(HttpContractModel):
    unrecognized: bool
    missing_metadata: bool = Field(alias="missingMetadata")


class OrganizePolicy(HttpContractModel):
    id: str
    enabled: bool
    schedule_mode: Literal["MANUAL", "INTERVAL"] = Field(alias="scheduleMode")
    interval_minutes: int = Field(alias="intervalMinutes")
    auto_run_on_new: bool = Field(alias="autoRunOnNew")
    auto_run_on_new_since: datetime | None = Field(alias="autoRunOnNewSince")
    rules: OrganizeRules
    overwrite_title_author: bool = Field(alias="overwriteTitleAuthor")
    last_scheduled_at: datetime | None = Field(alias="lastScheduledAt")
    next_run_at: datetime | None = Field(alias="nextRunAt")
    updated_at: datetime = Field(alias="updatedAt")


class OrganizePolicyPayload(HttpContractModel):
    policy: OrganizePolicy


class OrganizeCandidate(HttpContractModel):
    id: str
    title: str | None
    author: str | None
    available_media_kinds: list[str] = Field(alias="availableMediaKinds")
    cover_path: str | None = Field(alias="coverPath")
    metadata_quality: int = Field(alias="metadataQuality")
    reason_codes: list[str] = Field(alias="reasonCodes")
    created_at: datetime | None = Field(alias="createdAt")


class OrganizeCandidates(HttpContractModel):
    total: int
    reason_counts: dict[str, int] = Field(alias="reasonCounts")
    works: list[OrganizeCandidate]


class OrganizeCandidatesPayload(HttpContractModel):
    candidates: OrganizeCandidates


class OrganizeRunScope(HttpContractModel):
    work_ids: list[str] = Field(alias="workIds")
    rules: OrganizeRules


class OrganizeRun(HttpContractModel):
    id: str
    trigger: str
    scope: OrganizeRunScope
    status: str
    queued_count: int = Field(alias="queuedCount")
    completed_count: int = Field(alias="completedCount")
    review_count: int = Field(alias="reviewCount")
    failed_count: int = Field(alias="failedCount")
    started_at: datetime | None = Field(alias="startedAt")
    finished_at: datetime | None = Field(alias="finishedAt")
    created_at: datetime | None = Field(alias="createdAt")
    updated_at: datetime | None = Field(alias="updatedAt")


class OrganizeRunsPayload(HttpContractModel):
    runs: list[OrganizeRun]


class DeletedOrganizeJobPayload(HttpContractModel):
    id: str
    work_id: str = Field(alias="workId")
    deleted: Literal[True]


class ProviderExecution(HttpContractModel):
    id: str
    provider_id: str = Field(alias="providerId")
    status: str
    attempts: int
    error_summary: str | None = Field(alias="errorSummary")
    started_at: datetime | None = Field(alias="startedAt")
    finished_at: datetime | None = Field(alias="finishedAt")


class OrganizeJob(HttpContractModel):
    id: str
    run_id: str | None = Field(alias="runId")
    volume_id: str | None = Field(alias="volumeId")
    media_version_id: str | None = Field(default=None, alias="mediaVersionId")
    trigger: str
    status: str
    status_category: Literal["SUCCESS", "FAILED", "RECOGNIZING", "WAITING"] = Field(
        alias="statusCategory"
    )
    issue_codes: list[str] = Field(alias="issueCodes")
    reason_codes: list[str] = Field(alias="reasonCodes")
    summary: str | None
    error_summary: str | None = Field(alias="errorSummary")
    metadata_lookup_status: str | None = Field(alias="metadataLookupStatus")
    metadata_lookup_source: str | None = Field(alias="metadataLookupSource")
    metadata_lookup_providers: list[str] = Field(alias="metadataLookupProviders")
    metadata_sources: list[str] = Field(alias="metadataSources")
    metadata_lookup_error: str | None = Field(alias="metadataLookupError")
    provider_executions: list[ProviderExecution] = Field(alias="providerExecutions")
    started_at: datetime | None = Field(alias="startedAt")
    finished_at: datetime | None = Field(alias="finishedAt")
    created_at: datetime | None = Field(alias="createdAt")
    updated_at: datetime | None = Field(alias="updatedAt")
    book: WorkView


class OrganizeJobListBook(HttpContractModel):
    id: str
    title: str
    author: str
    available_media_kinds: list[str] = Field(alias="availableMediaKinds")


class OrganizeJobListItem(HttpContractModel):
    id: str
    trigger: str
    status_category: Literal["SUCCESS", "FAILED", "RECOGNIZING", "WAITING"] = Field(
        alias="statusCategory"
    )
    issue_codes: list[str] = Field(alias="issueCodes")
    reason_codes: list[str] = Field(alias="reasonCodes")
    metadata_sources: list[str] = Field(alias="metadataSources")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    book: OrganizeJobListBook


class OrganizeStatusCounts(HttpContractModel):
    success: int = Field(alias="SUCCESS")
    failed: int = Field(alias="FAILED")
    recognizing: int = Field(alias="RECOGNIZING")
    waiting: int = Field(alias="WAITING")


class OrganizeJobsPayload(HttpContractModel):
    jobs: list[OrganizeJobListItem]
    page: int
    page_size: int = Field(alias="pageSize")
    total: int
    total_pages: int = Field(alias="totalPages")
    status_counts: OrganizeStatusCounts = Field(alias="statusCounts")
    provider_names: dict[str, str] = Field(alias="providerNames")


class PendingOrganizeJobsPayload(HttpContractModel):
    jobs: list[OrganizeJob]
    books: list[WorkView]
    total: int


class OrganizeJobPayload(HttpContractModel):
    job: OrganizeJob


OrganizePolicyResponse = SuccessEnvelope[OrganizePolicyPayload]
OrganizeCandidatesResponse = SuccessEnvelope[OrganizeCandidatesPayload]
OrganizeRunsResponse = SuccessEnvelope[OrganizeRunsPayload]
DeletedOrganizeJobResponse = SuccessEnvelope[DeletedOrganizeJobPayload]
OrganizeJobsResponse = SuccessEnvelope[OrganizeJobsPayload]
PendingOrganizeJobsResponse = SuccessEnvelope[PendingOrganizeJobsPayload]
OrganizeJobResponse = SuccessEnvelope[OrganizeJobPayload]


class OrganizeErrorBody(HttpContractModel):
    message: str
    code: str | None = None


class OrganizeBadRequestError(HttpContractError[OrganizeErrorBody]):
    status_code = 400
    body_model = OrganizeErrorBody


class OrganizeNotFoundError(HttpContractError[OrganizeErrorBody]):
    status_code = 404
    body_model = OrganizeErrorBody


class OrganizeUnavailableError(HttpContractError[OrganizeErrorBody]):
    status_code = 503
    body_model = OrganizeErrorBody
