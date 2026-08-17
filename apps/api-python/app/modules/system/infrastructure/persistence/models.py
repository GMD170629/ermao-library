"""Current system persistence models.

This module is intentionally independent from the legacy ORM registry.  The
current schema owns one system row whose identity bootstrap timestamp is the
only bootstrap marker needed by the application.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import TimestampMilliseconds
from app.db.current.registry import CurrentBase


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SystemInstance(CurrentBase):
    """The single current application system row."""

    __tablename__ = "SystemInstance"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    __table_args__ = (CheckConstraint(id == 1, name="SystemInstance_singleton_ck"),)

    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TimestampMilliseconds(),
        nullable=False,
        default=_utc_now,
    )
    identity_bootstrap_completed_at: Mapped[datetime | None] = mapped_column(
        "identityBootstrapCompletedAt",
        TimestampMilliseconds(),
        nullable=True,
    )
