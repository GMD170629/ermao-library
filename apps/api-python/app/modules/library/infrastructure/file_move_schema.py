"""Frozen file moves and durable publication checkpoints, owned by Library."""

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    SQLColumnExpression,
    String,
    or_,
    select,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.elements import ColumnElement

from app.db.base import Base


class LibraryFileMovePlan(Base):
    __tablename__ = "LibraryFileMovePlan"
    id: Mapped[str] = mapped_column(String(191), primary_key=True)
    grant_id: Mapped[str] = mapped_column("grantId", String(191), nullable=False)
    user_id: Mapped[str] = mapped_column("userId", String(191), nullable=False)
    expires_at_ms: Mapped[int] = mapped_column("expiresAt", BigInteger)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class LibraryFileMoveOperation(Base):
    __tablename__ = "LibraryFileMoveOperation"
    __table_args__ = (
        Index("LibraryFileMoveOperation_status_createdAt_idx", "status", "createdAt"),
    )
    id: Mapped[str] = mapped_column(String(191), primary_key=True)
    plan_id: Mapped[str] = mapped_column(
        "planId", ForeignKey("LibraryFileMovePlan.id"), unique=True
    )
    grant_id: Mapped[str] = mapped_column("grantId", String(191), nullable=False)
    user_id: Mapped[str] = mapped_column("userId", String(191), nullable=False)
    request_id: Mapped[str] = mapped_column("requestId", String(128))
    status: Mapped[str] = mapped_column(String(32), default="QUEUED")
    cancel_requested: Mapped[bool] = mapped_column(
        "cancelRequested", Boolean, default=False
    )
    created_at_ms: Mapped[int] = mapped_column("createdAt", BigInteger)
    updated_at_ms: Mapped[int] = mapped_column("updatedAt", BigInteger)
    error_code: Mapped[str | None] = mapped_column("errorCode", String(100))

    @classmethod
    def blocks_library(
        cls, library_id: SQLColumnExpression[str]
    ) -> ColumnElement[bool]:
        """One durable conflict predicate shared by scan and writeback claims."""
        return (
            select(LibraryFileMoveTarget.operation_id)
            .join(cls, cls.id == LibraryFileMoveTarget.operation_id)
            .where(
                cls.status.in_(
                    (
                        "QUEUED",
                        "PREPARING",
                        "FILES_PUBLISHED",
                        "INDEX_UPDATED",
                        "RECOVERY_REQUIRED",
                    )
                ),
                or_(
                    LibraryFileMoveTarget.source_library_id == library_id,
                    LibraryFileMoveTarget.destination_library_id == library_id,
                ),
            )
            .exists()
        )


class LibraryFileMoveTarget(Base):
    __tablename__ = "LibraryFileMoveTarget"
    __table_args__ = (
        Index("LibraryFileMoveTarget_sourceLibraryId_idx", "sourceLibraryId"),
        Index("LibraryFileMoveTarget_destinationLibraryId_idx", "destinationLibraryId"),
    )
    operation_id: Mapped[str] = mapped_column(
        "operationId",
        ForeignKey("LibraryFileMoveOperation.id", ondelete="CASCADE"),
        primary_key=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_library_id: Mapped[str] = mapped_column("sourceLibraryId", String(191))
    destination_library_id: Mapped[str] = mapped_column(
        "destinationLibraryId", String(191)
    )
    stage: Mapped[str] = mapped_column(String(32), default="QUEUED")
    recovery: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column("errorCode", String(100))
