from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class FeedbackRecord(Base):
    __tablename__ = "feedback_records"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    submission_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    qq: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    group_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(254), nullable=False, default="")
    diagnostics_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
