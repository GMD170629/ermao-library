from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import TimestampMilliseconds
from app.db.base import Base
from app.models.common import cuid, db_timestamp, timestamp_ms_server_default


class OrganizePolicy(Base):
    __tablename__ = "OrganizePolicy"

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    schedule_mode: Mapped[str] = mapped_column("scheduleMode", String(191), nullable=False, default="MANUAL", server_default="MANUAL")
    interval_minutes: Mapped[int] = mapped_column("intervalMinutes", Integer, nullable=False, default=60, server_default="60")
    auto_run_on_new: Mapped[bool] = mapped_column("autoRunOnNew", Boolean, nullable=False, default=False, server_default="0")
    auto_run_on_new_since: Mapped[datetime | None] = mapped_column("autoRunOnNewSince", TimestampMilliseconds(), nullable=True)
    rules_json: Mapped[str] = mapped_column("rulesJson", Text, nullable=False, default="{}", server_default="{}")
    overwrite_title_author: Mapped[bool] = mapped_column(
        "overwriteTitleAuthor",
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )
    last_scheduled_at: Mapped[datetime | None] = mapped_column("lastScheduledAt", TimestampMilliseconds(), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column("nextRunAt", TimestampMilliseconds(), nullable=True)
    created_at: Mapped[datetime] = mapped_column("createdAt", TimestampMilliseconds(), nullable=False, default=db_timestamp, server_default=timestamp_ms_server_default())
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TimestampMilliseconds(), nullable=False, default=db_timestamp, onupdate=db_timestamp)


class OrganizeRun(Base):
    __tablename__ = "OrganizeRun"
    __table_args__ = (Index("OrganizeRun_status_createdAt_idx", "status", "createdAt"),)

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    trigger: Mapped[str] = mapped_column(String(191), nullable=False)
    scope_json: Mapped[str] = mapped_column("scopeJson", Text, nullable=False, default="{}", server_default="{}")
    dedupe_key: Mapped[str | None] = mapped_column("dedupeKey", String(191), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="QUEUED", server_default="QUEUED")
    queued_count: Mapped[int] = mapped_column("queuedCount", Integer, nullable=False, default=0, server_default="0")
    completed_count: Mapped[int] = mapped_column("completedCount", Integer, nullable=False, default=0, server_default="0")
    review_count: Mapped[int] = mapped_column("reviewCount", Integer, nullable=False, default=0, server_default="0")
    failed_count: Mapped[int] = mapped_column("failedCount", Integer, nullable=False, default=0, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column("startedAt", TimestampMilliseconds(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column("finishedAt", TimestampMilliseconds(), nullable=True)
    created_at: Mapped[datetime] = mapped_column("createdAt", TimestampMilliseconds(), nullable=False, default=db_timestamp, server_default=timestamp_ms_server_default())
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TimestampMilliseconds(), nullable=False, default=db_timestamp, onupdate=db_timestamp)


class OrganizeJob(Base):
    __tablename__ = "OrganizeJob"
    __table_args__ = (
        Index("OrganizeJob_workId_status_idx", "workId", "status"),
        Index(
            "OrganizeJob_unresolved_workId_key",
            "workId",
            unique=True,
            sqlite_where=text(
                "status IN ('LOOKUP_PENDING', 'PENDING', 'QUEUED', 'RUNNING', 'RETRY_WAIT', 'REVIEWING', 'FAILED')"
            ),
        ),
        Index("OrganizeJob_runId_status_idx", "runId", "status"),
        Index("OrganizeJob_editionId_idx", "editionId"),
        Index("OrganizeJob_importTaskId_idx", "importTaskId"),
        Index("OrganizeJob_status_updatedAt_idx", "status", "updatedAt"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    run_id: Mapped[str | None] = mapped_column(
        "runId",
        String(191),
        ForeignKey("OrganizeRun.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    work_id: Mapped[str] = mapped_column(
        "workId",
        String(191),
        ForeignKey("LibraryWork.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    edition_id: Mapped[str | None] = mapped_column(
        "editionId",
        String(191),
        ForeignKey("LibraryEdition.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    import_task_id: Mapped[str | None] = mapped_column(
        "importTaskId",
        String(191),
        ForeignKey("ImportTask.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    trigger: Mapped[str] = mapped_column(String(191), nullable=False, default="LEGACY", server_default="LEGACY")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="REVIEWING", server_default="REVIEWING")
    issue_codes: Mapped[str] = mapped_column("issueCodes", Text, nullable=False)
    reason_codes: Mapped[str] = mapped_column("reasonCodes", Text, nullable=False, default="[]", server_default="[]")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_summary: Mapped[str | None] = mapped_column("errorSummary", Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column("startedAt", TimestampMilliseconds(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column("finishedAt", TimestampMilliseconds(), nullable=True)
    created_at: Mapped[datetime] = mapped_column("createdAt", TimestampMilliseconds(), nullable=False, default=db_timestamp, server_default=timestamp_ms_server_default())
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TimestampMilliseconds(), nullable=False, default=db_timestamp, onupdate=db_timestamp)


class MetadataLookupTask(Base):
    __tablename__ = "MetadataLookupTask"
    __table_args__ = (
        Index("MetadataLookupTask_status_nextAttemptAt_idx", "status", "nextAttemptAt"),
        Index("MetadataLookupTask_workId_createdAt_idx", "workId", "createdAt"),
        UniqueConstraint("importTaskId", name="MetadataLookupTask_importTaskId_key"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    work_id: Mapped[str] = mapped_column(
        "workId",
        String(191),
        ForeignKey("LibraryWork.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    edition_id: Mapped[str | None] = mapped_column(
        "editionId",
        String(191),
        ForeignKey("LibraryEdition.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    import_task_id: Mapped[str | None] = mapped_column(
        "importTaskId",
        String(191),
        ForeignKey("ImportTask.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    organize_job_id: Mapped[str | None] = mapped_column(
        "organizeJobId",
        String(191),
        ForeignKey("OrganizeJob.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING", server_default="PENDING")
    provider_order: Mapped[str] = mapped_column("providerOrder", Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column("nextAttemptAt", TimestampMilliseconds(), nullable=True)
    result_source: Mapped[str | None] = mapped_column("resultSource", Text, nullable=True)
    candidate_raw_json: Mapped[str | None] = mapped_column("candidateRawJson", Text, nullable=True)
    applied_fields: Mapped[str | None] = mapped_column("appliedFields", Text, nullable=True)
    error_summary: Mapped[str | None] = mapped_column("errorSummary", Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column("startedAt", TimestampMilliseconds(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column("finishedAt", TimestampMilliseconds(), nullable=True)
    created_at: Mapped[datetime] = mapped_column("createdAt", TimestampMilliseconds(), nullable=False, default=db_timestamp, server_default=timestamp_ms_server_default())
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TimestampMilliseconds(), nullable=False, default=db_timestamp, onupdate=db_timestamp)


class MetadataProviderExecution(Base):
    __tablename__ = "MetadataProviderExecution"
    __table_args__ = (
        Index("MetadataProviderExecution_jobId_status_idx", "jobId", "status"),
        Index("MetadataProviderExecution_lookupTaskId_idx", "lookupTaskId"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    job_id: Mapped[str | None] = mapped_column(
        "jobId",
        String(191),
        ForeignKey("OrganizeJob.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=True,
    )
    lookup_task_id: Mapped[str | None] = mapped_column(
        "lookupTaskId",
        String(191),
        ForeignKey("MetadataLookupTask.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=True,
    )
    provider_id: Mapped[str] = mapped_column("providerId", String(191), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING", server_default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    raw_result_json: Mapped[str | None] = mapped_column("rawResultJson", Text, nullable=True)
    error_summary: Mapped[str | None] = mapped_column("errorSummary", Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column("startedAt", TimestampMilliseconds(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column("finishedAt", TimestampMilliseconds(), nullable=True)
    created_at: Mapped[datetime] = mapped_column("createdAt", TimestampMilliseconds(), nullable=False, default=db_timestamp, server_default=timestamp_ms_server_default())
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TimestampMilliseconds(), nullable=False, default=db_timestamp, onupdate=db_timestamp)


class MetadataProviderPipeline(Base):
    __tablename__ = "MetadataProviderPipeline"
    __table_args__ = (Index("MetadataProviderPipeline_workType_position_idx", "workType", "included", "position"),)

    work_type: Mapped[str] = mapped_column("workType", String(191), primary_key=True)
    provider_id: Mapped[str] = mapped_column("providerId", String(191), primary_key=True)
    included: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=100, server_default="100")
    created_at: Mapped[datetime] = mapped_column("createdAt", TimestampMilliseconds(), nullable=False, default=db_timestamp, server_default=timestamp_ms_server_default())
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TimestampMilliseconds(), nullable=False, default=db_timestamp, onupdate=db_timestamp)


class MetadataSuggestion(Base):
    __tablename__ = "MetadataSuggestion"
    __table_args__ = (
        Index("MetadataSuggestion_jobId_status_idx", "jobId", "status"),
        Index("MetadataSuggestion_field_idx", "field"),
        Index("MetadataSuggestion_source_idx", "source"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    job_id: Mapped[str] = mapped_column(
        "jobId",
        String(191),
        ForeignKey("OrganizeJob.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    field: Mapped[str] = mapped_column(String(191), nullable=False)
    current_value: Mapped[str | None] = mapped_column("currentValue", Text, nullable=True)
    suggested_value: Mapped[str] = mapped_column("suggestedValue", Text, nullable=False)
    source: Mapped[str] = mapped_column(String(191), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0, server_default="0")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING", server_default="PENDING")
    created_at: Mapped[datetime] = mapped_column("createdAt", TimestampMilliseconds(), nullable=False, default=db_timestamp, server_default=timestamp_ms_server_default())
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TimestampMilliseconds(), nullable=False, default=db_timestamp, onupdate=db_timestamp)


class DuplicateCandidate(Base):
    __tablename__ = "DuplicateCandidate"
    __table_args__ = (
        Index("DuplicateCandidate_jobId_status_idx", "jobId", "status"),
        Index("DuplicateCandidate_targetWorkId_idx", "targetWorkId"),
        Index("DuplicateCandidate_suggestedAction_idx", "suggestedAction"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    job_id: Mapped[str] = mapped_column(
        "jobId",
        String(191),
        ForeignKey("OrganizeJob.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    target_work_id: Mapped[str] = mapped_column(
        "targetWorkId",
        String(191),
        ForeignKey("LibraryWork.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    reasons: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0, server_default="0")
    suggested_action: Mapped[str] = mapped_column("suggestedAction", String(191), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING", server_default="PENDING")
    created_at: Mapped[datetime] = mapped_column("createdAt", TimestampMilliseconds(), nullable=False, default=db_timestamp, server_default=timestamp_ms_server_default())
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TimestampMilliseconds(), nullable=False, default=db_timestamp, onupdate=db_timestamp)
