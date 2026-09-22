"""Persistence schema for frozen permanent-deletion journals."""

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FileDeletePlanRow(Base):
    __tablename__ = "FileDeletePlan"
    id: Mapped[str] = mapped_column(String(191), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(191), index=True)
    grant_id: Mapped[str] = mapped_column(String(191), index=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)
