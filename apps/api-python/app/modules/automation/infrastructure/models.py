"""Persist fixed grants; no mutable permission expansion endpoint."""

from sqlalchemy import JSON, BigInteger, Boolean, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AutomationGrantRow(Base):
    __tablename__ = "AutomationGrant"
    __table_args__ = (Index("AutomationGrant_userId_idx", "userId"),)

    id: Mapped[str] = mapped_column(String(191), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        "userId", ForeignKey("User.id", ondelete="CASCADE", onupdate="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(100))
    token_digest: Mapped[str] = mapped_column("tokenDigest", String(64), unique=True)
    scopes: Mapped[list[str]] = mapped_column(JSON)
    library_ids: Mapped[list[str]] = mapped_column("libraryIds", JSON)
    writeback_targets: Mapped[list[str]] = mapped_column(
        "writebackTargets", JSON, default=list, server_default="[]"
    )
    allow_cross_library: Mapped[bool] = mapped_column(
        "allowCrossLibrary", Boolean, default=False, server_default="0"
    )
    created_at_ms: Mapped[int] = mapped_column("createdAt", BigInteger)
    expires_at_ms: Mapped[int] = mapped_column("expiresAt", BigInteger)
    revoked_at_ms: Mapped[int | None] = mapped_column("revokedAt", BigInteger)
    last_used_at_ms: Mapped[int | None] = mapped_column("lastUsedAt", BigInteger)


class AutomationReceiptRow(Base):
    __tablename__ = "AutomationReceipt"

    grant_id: Mapped[str] = mapped_column(
        "grantId",
        ForeignKey("AutomationGrant.id", ondelete="CASCADE"),
        primary_key=True,
    )
    request_id: Mapped[str] = mapped_column("requestId", String(128), primary_key=True)
    tool: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at_ms: Mapped[int] = mapped_column("createdAt", BigInteger)
    result: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
