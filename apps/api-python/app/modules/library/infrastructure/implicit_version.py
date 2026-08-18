"""One implicit LibraryVersion per work until Scanner owns real versions."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.library import LibraryVersion

IMPLICIT_VERSION_SOURCE_KEY = "__implicit__"


def get_or_create_implicit_version(
    db: Session, work_id: str, *, now: datetime | None = None
) -> LibraryVersion:
    existing = db.scalar(
        select(LibraryVersion)
        .where(
            LibraryVersion.work_id == work_id,
            LibraryVersion.source_key == IMPLICIT_VERSION_SOURCE_KEY,
        )
        .limit(1)
    )
    if existing is not None:
        return existing
    timestamp = now or datetime.now(UTC)
    version = LibraryVersion(
        work_id=work_id,
        source_key=IMPLICIT_VERSION_SOURCE_KEY,
        source_name=None,
        created_at=timestamp,
        updated_at=timestamp,
    )
    db.add(version)
    db.flush()
    return version
