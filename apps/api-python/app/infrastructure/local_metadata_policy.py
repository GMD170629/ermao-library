"""Cross-capability adapter for the persisted local metadata source order."""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.local_metadata import (
    DEFAULT_LOCAL_METADATA_PRIORITY,
    LocalMetadataSource,
    validate_local_metadata_priority,
)
from app.models.organize import OrganizePolicy


@dataclass(frozen=True, slots=True)
class RawLocalMetadataPriorityProjection:
    available: bool
    stored_json: str | None = None


def load_raw_local_metadata_priority_projection(
    db: Session,
) -> RawLocalMetadataPriorityProjection:
    """Read only the persisted JSON column for transaction-external parsing."""

    stored = db.scalar(
        select(OrganizePolicy.local_metadata_priority_json).where(
            OrganizePolicy.id == "default"
        )
    )
    return RawLocalMetadataPriorityProjection(
        available=True,
        stored_json=None if stored is None else str(stored),
    )


def prepare_local_metadata_priority(
    projection: RawLocalMetadataPriorityProjection,
) -> tuple[LocalMetadataSource, ...]:
    """Validate persisted priority outside the database transaction."""

    if not projection.available:
        return DEFAULT_LOCAL_METADATA_PRIORITY
    try:
        parsed = json.loads(projection.stored_json or "[]")
        return validate_local_metadata_priority(parsed)
    except (TypeError, ValueError):
        return DEFAULT_LOCAL_METADATA_PRIORITY


__all__ = [
    "RawLocalMetadataPriorityProjection",
    "load_raw_local_metadata_priority_projection",
    "prepare_local_metadata_priority",
]


class SqlAlchemyLocalMetadataPriority:
    def __init__(self, db: Session) -> None:
        self._db = db

    def load(self) -> tuple[LocalMetadataSource, ...]:
        return prepare_local_metadata_priority(
            load_raw_local_metadata_priority_projection(self._db)
        )


__all__.append("SqlAlchemyLocalMetadataPriority")
