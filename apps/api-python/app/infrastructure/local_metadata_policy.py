"""Cross-capability adapter for the persisted local metadata source order."""

from __future__ import annotations

import json

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.contracts.local_metadata import (
    DEFAULT_LOCAL_METADATA_PRIORITY,
    LocalMetadataSource,
    validate_local_metadata_priority,
)
from app.models.organize import OrganizePolicy


def load_local_metadata_priority(
    db: Session,
) -> tuple[LocalMetadataSource, ...]:
    if not inspect(db.connection()).has_table(OrganizePolicy.__tablename__):
        return DEFAULT_LOCAL_METADATA_PRIORITY
    stored = db.scalar(
        select(OrganizePolicy.local_metadata_priority_json).where(
            OrganizePolicy.id == "default"
        )
    )
    try:
        parsed = json.loads(stored or "[]")
        return validate_local_metadata_priority(parsed)
    except (TypeError, ValueError):
        return DEFAULT_LOCAL_METADATA_PRIORITY


__all__ = ["load_local_metadata_priority"]
