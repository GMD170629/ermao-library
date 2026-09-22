"""Persistent attachment upload journals."""

from sqlalchemy import JSON, BigInteger, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AutomationUploadRow(Base):
    __tablename__ = "AutomationUpload"
    __table_args__ = (
        Index("AutomationUpload_grantId_status_idx", "grantId", "status"),
        Index("AutomationUpload_expiresAt_idx", "expiresAt"),
        Index("AutomationUpload_userId_createdAt_idx", "userId", "createdAt"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column("userId", String(191))
    grant_id: Mapped[str] = mapped_column("grantId", String(191))
    library_id: Mapped[str] = mapped_column("libraryId", String(191))
    status: Mapped[str] = mapped_column(String(32))
    size_bytes: Mapped[int] = mapped_column("sizeBytes", BigInteger)
    created_at_ms: Mapped[int] = mapped_column("createdAt", BigInteger)
    expires_at_ms: Mapped[int] = mapped_column("expiresAt", BigInteger)
    cleanup_after_ms: Mapped[int] = mapped_column(
        "cleanupAfter", BigInteger, default=0, server_default="0"
    )
    payload: Mapped[dict[str, object]] = mapped_column(JSON)
