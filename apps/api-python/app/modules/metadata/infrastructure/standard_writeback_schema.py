"""Immutable standard-write plans and durable results beside the existing work queue."""

from sqlalchemy import JSON, BigInteger, Boolean, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MetadataStandardWritePlan(Base):
    __tablename__ = "MetadataStandardWritePlan"
    id: Mapped[str] = mapped_column(String(191), primary_key=True)
    grant_id: Mapped[str] = mapped_column("grantId", String(191))
    user_id: Mapped[str] = mapped_column("userId", String(191))
    expires_at_ms: Mapped[int] = mapped_column("expiresAt", BigInteger)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class MetadataStandardWriteOperation(Base):
    __tablename__ = "MetadataStandardWriteOperation"
    id: Mapped[str] = mapped_column(String(191), primary_key=True)
    plan_id: Mapped[str] = mapped_column(
        "planId", ForeignKey("MetadataStandardWritePlan.id"), unique=True
    )
    grant_id: Mapped[str] = mapped_column("grantId", String(191))
    user_id: Mapped[str] = mapped_column("userId", String(191))
    request_id: Mapped[str] = mapped_column("requestId", String(128))
    cancel_requested: Mapped[bool] = mapped_column(
        "cancelRequested", Boolean, default=False
    )
    created_at_ms: Mapped[int] = mapped_column("createdAt", BigInteger)
    updated_at_ms: Mapped[int] = mapped_column("updatedAt", BigInteger)


class MetadataStandardWriteTarget(Base):
    __tablename__ = "MetadataStandardWriteTarget"
    __table_args__ = (
        Index("MetadataStandardWriteTarget_libraryId_stage_idx", "libraryId", "stage"),
    )
    operation_id: Mapped[str] = mapped_column(
        "operationId",
        ForeignKey("MetadataStandardWriteOperation.id", ondelete="CASCADE"),
        primary_key=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    library_id: Mapped[str] = mapped_column("libraryId", String(191))
    queue_target_id: Mapped[str] = mapped_column(
        "queueTargetId", String(191), unique=True
    )
    stage: Mapped[str] = mapped_column(String(32), default="QUEUED")
    recovery: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column("errorCode", String(100))
    reserved_bytes: Mapped[int] = mapped_column("reservedBytes", BigInteger)
    recovery_released: Mapped[bool] = mapped_column(
        "recoveryReleased", Boolean, default=False
    )
